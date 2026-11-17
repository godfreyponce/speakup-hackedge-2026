"""Time one ONNX model on exactly 1.0 s of audio, and optionally the #7 summary model beside it (#2).

Needs only onnxruntime and numpy, so the same command runs on the laptop and on the board:

    python3 scripts/time_model.py models/arti-v0.onnx recordings/rabbit-say.wav
    python3 scripts/time_model.py models/arti-v0.onnx recordings/rabbit-say.wav \
        --llm "llama-completion -m models/qwen2.5-0.5b-instruct-q4_k_m.gguf -f {prompt_file} -n 96 --temp 0 -t 4"

It prints one "key: value" line each. peak_ram_mb is this process's peak resident memory.
With --llm, the command runs while the ONNX session is still loaded; both_peak_ram_mb adds the
two peaks, an upper bound for both at once.
"""

import argparse
import resource
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import onnxruntime as ort

from speakup.arti import RATE, THREADS, prepare, read_wav
from speakup.result import Result
from speakup.summary import build_prompt


def peak_mb(who):
    rss = resource.getrusage(who).ru_maxrss
    # ru_maxrss is bytes on macOS and kilobytes on Linux.
    return rss / 1e6 if sys.platform == "darwin" else rss * 1024 / 1e6


def size_mb(model):
    files = [model] + [p for p in [model.with_name(model.name + ".data")] if p.exists()]
    return sum(p.stat().st_size for p in files) / 1e6


def one_second(wav):
    samples = read_wav(wav)[:RATE]
    samples += [0] * (RATE - len(samples))
    return np.asarray([samples], dtype=np.float32) / 32768


def made_up_prompt():
    def result(word, error_type):
        return Result(word=word, target_sound="r", expected_phone="ɹ",
                      heard_phone=None if error_type else "ɹ", error_type=error_type,
                      confidence=None, model="arti-v0", recorded_at="2026-11-05T10:15:00-06:00")
    return build_prompt([result("rabbit", "off"), result("carrot", None), result("red", "off")], 96)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("model", type=Path)
    parser.add_argument("wav", type=Path)
    parser.add_argument("--runs", type=int, default=20, help="timed runs after one warm-up; 20 is a guess")
    parser.add_argument("--llm", help='summary command, with {prompt_file} where the prompt file goes')
    parser.add_argument("--prepare", action="store_true",
                        help="also time Arti's whole app path on the WAV as given: read_wav, prepare, run")
    args = parser.parse_args(argv)

    audio = one_second(args.wav)
    t0 = time.perf_counter()
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    sess = ort.InferenceSession(str(args.model), options, providers=["CPUExecutionProvider"])
    load_s = time.perf_counter() - t0
    feed = {sess.get_inputs()[0].name: audio}
    sess.run(None, feed)
    times = []
    for _ in range(args.runs):
        t0 = time.perf_counter()
        sess.run(None, feed)
        times.append(time.perf_counter() - t0)

    print(f"model: {args.model.name}")
    print(f"size_mb: {size_mb(args.model):.1f}")
    print(f"load_s: {load_s:.3f}")
    print(f"run_s_median: {statistics.median(times):.4f}")
    print(f"run_s_max: {max(times):.4f}")
    if args.prepare:
        app_times = []
        for _ in range(args.runs):
            t0 = time.perf_counter()
            clip = np.asarray([prepare(read_wav(args.wav))], dtype=np.float32)
            sess.run(None, {sess.get_inputs()[0].name: clip})
            app_times.append(time.perf_counter() - t0)
        print(f"app_s_median: {statistics.median(app_times):.4f}")
        print(f"app_s_max: {max(app_times):.4f}")
    print(f"peak_ram_mb: {peak_mb(resource.RUSAGE_SELF):.0f}")

    if args.llm:
        with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as f:
            f.write(made_up_prompt())
        try:
            command = shlex.split(args.llm.replace("{prompt_file}", f.name))
            t0 = time.perf_counter()
            reply = subprocess.run(command, capture_output=True, text=True, check=True).stdout
            llm_s = time.perf_counter() - t0
        finally:
            Path(f.name).unlink()
        print(f"llm_s: {llm_s:.2f}")
        print(f"llm_peak_ram_mb: {peak_mb(resource.RUSAGE_CHILDREN):.0f}")
        print(f"both_peak_ram_mb: {peak_mb(resource.RUSAGE_SELF) + peak_mb(resource.RUSAGE_CHILDREN):.0f}")
        print(f"llm_reply: {' '.join(reply.split())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
