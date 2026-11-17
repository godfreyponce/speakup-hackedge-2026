"""Compare Arti trained with no mask, a time mask and a frequency mask, on validation speakers only (#19).

Laptop only. Run from the repo root:

    uv run --managed-python --python 3.12 --with torch --with torchaudio --with onnx --with onnxscript \
        --with onnxruntime --with numpy python -I scripts/experiment_arti.py \
        /path/to/data/percept-r/PERCEPT-R.zip

It trains 9 times (3 methods, training seeds 2026, 2027 and 2028) with everything else as in
scripts/train_arti.py, and writes results.json and each run's best-epoch weights to
arti-masking/ beside the zip (--out-dir to change). A rerun replaces them. It never reads
test-set.csv, never scores the test clips, and never exports a model.
"""

import argparse
import json
import statistics
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from scripts.train_arti import (
    BATCH, CHANNELS, EPOCHS, HOP, LR, N_FFT, N_MELS, SEED, VAL_SHARE, build_cache, index, train,
)

METHODS = ("baseline", "time", "frequency")
TRAIN_SEEDS = (2026, 2027, 2028)
TIME_MAX_FRAMES = 5
FREQ_MAX_BINS = 2
AXES = {"time": 2, "frequency": 1}
MAX_WIDTH = {"time": TIME_MAX_FRAMES, "frequency": FREQ_MAX_BINS}


def stream_seeds(seed):
    """(init, order, mask) seeds, so the three random streams never start in the same place."""
    return tuple(int(s) for s in np.random.SeedSequence(seed).generate_state(3))


def mask(batch, axis, max_width, gen):
    """One band per clip on axis (1 = mel bins, 2 = frames), filled with the clip's mean."""
    n, size = len(batch), batch.shape[axis]
    width = torch.randint(0, max_width + 1, (n,), generator=gen)
    start = (torch.rand(n, generator=gen) * (size - width + 1)).floor().long()
    pos = torch.arange(size)
    band = (pos >= start[:, None]) & (pos < (start + width)[:, None])
    band = band[:, :, None] if axis == 1 else band[:, None, :]
    return torch.where(band, batch.mean(dim=(1, 2))[:, None, None], batch)


def augmenter(method, gen):
    if method == "baseline":
        return None
    return lambda b: mask(b, AXES[method], MAX_WIDTH[method], gen)


def _counts(labels):
    return {"correct": int((labels == 0).sum()), "wrong": int((labels == 1).sum())}


def run_one(mels, labels, is_val, device, method, seed):
    init_seed, order_seed, mask_seed = stream_seeds(seed)
    order = torch.Generator().manual_seed(order_seed)
    gen = torch.Generator().manual_seed(mask_seed)
    t0 = time.perf_counter()
    body, best_epoch, pred = train(mels, labels, is_val, device, seed=init_seed, order=order,
                                   augment=augmenter(method, gen))
    seconds = time.perf_counter() - t0
    y_val = labels[is_val]
    recalls = [(pred[y_val == c] == c).mean() for c in (0, 1)]
    record = {
        "method": method,
        "seed": seed,
        "init_seed": init_seed,
        "order_seed": order_seed,
        "mask_seed": mask_seed,
        "config": {
            "epochs": EPOCHS, "batch": BATCH, "lr": LR, "channels": list(CHANNELS), "n_mels": N_MELS,
            "n_fft": N_FFT, "hop": HOP, "split_seed": SEED, "val_share": VAL_SHARE,
            "mask": None if method == "baseline" else
            {"axis": method, "max_width": MAX_WIDTH[method], "fill": "clip mean log-mel"},
            "device": device, "torch_version": torch.__version__,
        },
        "best_epoch": best_epoch,
        "balanced_accuracy": float(sum(recalls) / 2),
        "missed_errors": int(((y_val == 1) & (pred == 0)).sum()),
        "false_alarms": int(((y_val == 0) & (pred == 1)).sum()),
        "val_counts": _counts(y_val),
        "train_counts": _counts(labels[~is_val]),
        "train_seconds": round(seconds, 1),
    }
    return record, body


def summarize(runs):
    baseline = {r["seed"]: r["balanced_accuracy"] for r in runs if r["method"] == "baseline"}
    rows = []
    for method in METHODS:
        mine = [r for r in runs if r["method"] == method]
        baccs = [r["balanced_accuracy"] for r in mine]
        rows.append({
            "method": method,
            "mean_balanced_accuracy": statistics.mean(baccs),
            "sd_balanced_accuracy": statistics.stdev(baccs),
            "min_balanced_accuracy": min(baccs),
            "max_balanced_accuracy": max(baccs),
            "per_seed": {r["seed"]: r["balanced_accuracy"] for r in mine},
            "paired_difference": {r["seed"]: r["balanced_accuracy"] - baseline[r["seed"]] for r in mine},
            "mean_missed_errors": statistics.mean(r["missed_errors"] for r in mine),
            "mean_false_alarms": statistics.mean(r["false_alarms"] for r in mine),
            "mean_best_epoch": statistics.mean(r["best_epoch"] for r in mine),
        })
    return sorted(rows, key=lambda r: (-r["mean_balanced_accuracy"], METHODS.index(r["method"])))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--device", choices=("auto", "cpu", "mps"), default="auto")
    args = parser.parse_args(argv)
    data_dir = args.zip_path.resolve().parent
    out_dir = args.out_dir or data_dir / "arti-masking"
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()

    with zipfile.ZipFile(args.zip_path) as zf:
        clips, train_speakers, val_speakers, test, skipped, unclear = index(zf, test_speakers)
    wrong = sum(label for _, _, label in clips)
    print(f"clips kept: {len(clips)} ({len(clips) - wrong} correct, {wrong} wrong)")
    print(f"label pickles skipped (not one float): {skipped}; unclear labels left out: {unclear}")
    print(f"speakers: train {len(train_speakers)}, val {len(val_speakers)}, test {len(test)} "
          "(pairwise disjoint)", flush=True)

    mels = build_cache(args.zip_path, clips, data_dir / "arti-cache")
    labels = np.array([label for _, _, label in clips], dtype=np.int64)
    is_val = np.array([speaker in val_speakers for _, speaker, _ in clips])
    print(f"train clips {int((~is_val).sum())}, val clips {int(is_val.sum())}", flush=True)

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    out_dir.mkdir(parents=True, exist_ok=True)
    results = {
        "speakers": {"train": len(train_speakers), "val": len(val_speakers), "test": len(test)},
        "clips": {"train": int((~is_val).sum()), "val": int(is_val.sum())},
        "runs": [],
    }
    for seed in TRAIN_SEEDS:
        for method in METHODS:
            record, body = run_one(mels, labels, is_val, device, method, seed)
            torch.save(body.state_dict(), out_dir / f"{method}-seed{seed}.pt")
            print(f"run {method} seed {seed}: best epoch {record['best_epoch']}, "
                  f"val balanced accuracy {record['balanced_accuracy']:.4f}, "
                  f"missed {record['missed_errors']}, false alarms {record['false_alarms']}, "
                  f"{record['train_seconds']:.0f} s", flush=True)
            results["runs"].append(record)
            if len(results["runs"]) == len(TRAIN_SEEDS) * len(METHODS):
                results["ranking"] = summarize(results["runs"])
            (out_dir / "results.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")

    for row in results["ranking"]:
        print(f"{row['method']}: mean {row['mean_balanced_accuracy']:.4f}, sd {row['sd_balanced_accuracy']:.4f}, "
              f"min {row['min_balanced_accuracy']:.4f}, max {row['max_balanced_accuracy']:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
