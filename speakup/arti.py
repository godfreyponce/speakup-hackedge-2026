"""Arti, the board's r model (#2): one ONNX file that answers right or wrong for the r in one word.
Training and export live in scripts/train_arti.py; see docs/model-timing.md."""

import json
import sys
import wave
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from speakup import proof
from speakup.result import Result, check

RATE = 16000
# The loudest 1.5 s holds the word in 95% of corpus clips (docs/model-timing.md).
WINDOW_SECONDS = 1.5
THRESHOLD = 0.5
MODEL_NAME = "arti-v2-soft"  # shipped model; a result names the file it came from (load)
# The board's four A53 cores.
THREADS = 1  # measured on the SK-AM62B (docs/architecture-comparison.md): 1 thread is as fast idle, 2x faster while the
#            language model and browser run, and uses 1.7x less energy per clip than 4

_WINDOW = int(RATE * WINDOW_SECONDS)
_FRAME = RATE // 100


def read_wav(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if (channels, width) != (1, 2) or rate < RATE:
            raise ValueError(f"{path.name}: need 16 kHz or faster, mono 16-bit, got {rate} Hz, {channels} channel(s), {8*width}-bit")
        data = w.readframes(w.getnframes())
    if rate != RATE:
        # The mic records at 48 kHz; Arti learned from 16 kHz audio, so it hears a 16 kHz copy.
        from speakup import audio
        x, _ = audio.read(path)
        return audio.int16(audio.to_16k(x, rate))
    return list(memoryview(data).cast("h"))


def prepare(samples: Sequence[int]) -> list[float]:
    """The loudest 1.5 s of the clip, padded with silence at the end, scaled to a peak of 1.0."""
    start = 0
    if len(samples) > _WINDOW:
        energy = [sum(x * x for x in samples[i:i + _FRAME]) for i in range(0, len(samples) - _FRAME + 1, _FRAME)]
        per_window = _WINDOW // _FRAME
        starts = (len(samples) - _WINDOW) // _FRAME + 1
        run = sum(energy[:per_window])
        best, best_run = 0, run
        for s in range(1, starts):
            run += energy[s + per_window - 1] - energy[s - 1]
            if run > best_run:
                best, best_run = s, run
        start = best * _FRAME
    window = list(samples[start:start + _WINDOW])
    window += [0] * (_WINDOW - len(window))
    peak = max(abs(x) for x in window)
    if peak == 0:
        return [0.0] * _WINDOW
    return [x / peak for x in window]


def to_result(word: str, p_wrong: float, model: str = MODEL_NAME) -> dict:
    wrong = p_wrong >= THRESHOLD
    return asdict(Result(
        word=word,
        target_sound="r",
        expected_phone="ɹ",
        heard_phone=None if wrong else "ɹ",
        error_type="off" if wrong else None,
        confidence=round(p_wrong if wrong else 1 - p_wrong, 2),
        model=model,
        recorded_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    ))


def load(model_path: Path) -> Callable[[str, Path], dict]:
    """Arti as listen(word, path) -> result dict. The returned function also carries `stretched(word, path,
    alpha) -> (result dict, voice.Reading)`: Arti read through the adult-voice stretch (speakup/voice.py)."""
    # Imported here so the app and its tests run without them; the board gets both from TI's SDK.
    import numpy as np

    from speakup.voice import Stretcher

    stretcher = Stretcher(model_path, THREADS)
    name = Path(model_path).stem

    def audio_of(path: Path):
        return np.asarray([prepare(read_wav(Path(path)))], dtype=np.float32)

    def listen(word: str, path: Path) -> dict:
        audio = audio_of(path)
        with proof.LIVE.arti_timer():
            p_wrong = stretcher.p_wrong(audio, 1.0)
        return to_result(word, p_wrong, name)

    def stretched(word: str, path: Path, alpha: float):
        audio = audio_of(path)
        with proof.LIVE.arti_timer():  # all of the word's model runs: three or four with the stretch
            reading = stretcher.read(audio, alpha)
        result = to_result(word, reading.p_wrong, name)
        if reading.alpha != 1.0:
            result["model"] = f"{name}+adult{reading.alpha:.2f}"
        return result, reading

    listen.stretched = stretched
    return listen


def main(argv: list[str]) -> None:
    if len(argv) != 3:
        sys.exit("usage: python3 -m speakup.arti MODEL.onnx CLIP.wav WORD")
    model, clip, word = argv
    print(json.dumps(asdict(check(load(Path(model))(word, Path(clip)))), ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
