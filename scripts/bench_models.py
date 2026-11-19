"""Board benchmark for the architecture comparison (report 4.2 / 5.1 / 5.2). One model per process:

    python3 bench_models.py MODEL.onnx [--runs 100] [--threads 4]

Prints one JSON line: file size, parameter count, load time, median / p95 latency on 1.0 s of audio,
CPU time per clip, and this process's peak resident memory. Needs only numpy + onnxruntime.
"""
import argparse, json, os, resource, statistics, sys, time
import numpy as np
import onnxruntime as ort
import onnx_params


def main():
    p = argparse.ArgumentParser()
    p.add_argument("model")
    p.add_argument("--runs", type=int, default=100)
    p.add_argument("--threads", type=int, default=4)
    a = p.parse_args()
    so = ort.SessionOptions()
    so.intra_op_num_threads = a.threads
    t0 = time.perf_counter()
    s = ort.InferenceSession(a.model, so, providers=["CPUExecutionProvider"])
    load = time.perf_counter() - t0
    inp = s.get_inputs()[0]
    shape = [d if isinstance(d, int) else 1 for d in inp.shape]
    if len(shape) >= 1 and shape[-1] in (1, None):
        shape[-1] = 16000
    x = (np.random.default_rng(0).standard_normal(shape) * 0.05).astype(np.float32)
    for _ in range(5):
        s.run(None, {inp.name: x})
    lat, cpu = [], []
    for _ in range(a.runs):
        c0, t0 = time.process_time(), time.perf_counter()
        s.run(None, {inp.name: x})
        lat.append(time.perf_counter() - t0)
        cpu.append(time.process_time() - c0)
    lat.sort()
    print(json.dumps(dict(model=os.path.basename(a.model), size_mb=round(os.path.getsize(a.model) / 1e6, 3),
                          params=onnx_params.count(a.model), input=list(shape), load_s=round(load, 3),
                          median_ms=round(1000 * statistics.median(lat), 2), p95_ms=round(1000 * lat[int(0.95 * len(lat))], 2),
                          cpu_ms=round(1000 * statistics.median(cpu), 2), threads=a.threads,
                          peak_ram_mb=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1))))


if __name__ == "__main__":
    main()
