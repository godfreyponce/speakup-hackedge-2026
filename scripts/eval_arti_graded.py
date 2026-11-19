"""Graded agreement: does P(correct) track the share of listeners who heard the r as correct, not just the side of 0.5?

Runs the exported ONNX models on (1) the 300 test clips (clear clips only, shares 0-0.25 and 0.75-1), (2) every
labelled clip of the 55 test children, unclear ones included, and (3) every labelled clip of the validation children.
Prints Spearman, Pearson and mean absolute error against the listener share, and a 5-bin reliability table.

    python -I scripts/eval_arti_graded.py data/percept-r/PERCEPT-R.zip models/arti-v0.onnx models/arti-v2-s2028.onnx \
        models/arti-v2-soft.onnx
"""

import argparse
import csv
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from scipy.stats import pearsonr, spearmanr

from scripts import train_arti as t
from scripts.experiment_arti_soft import soft_clips
from speakup.arti import prepare

_worker = {}


def _init(zip_path, models):
    _worker["zf"] = zipfile.ZipFile(zip_path)
    _worker["sessions"] = [t.session(m) for m in models]


def _p_correct(name):
    audio = np.asarray([prepare(t.to_16k(_worker["zf"].read(name)))], dtype=np.float32)
    return [1 - float(s.run(["p_wrong"], {"audio": audio})[0][0]) for s in _worker["sessions"]]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("models", type=Path, nargs="+")
    args = p.parse_args(argv)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with open(data_dir / "test-set.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with zipfile.ZipFile(args.zip_path) as zf:
        _, _, val_s, test_s, _, _ = t.index(zf, test_speakers)
        sets = {"300 test clips": [(r["zip_path"], float(r["label"])) for r in rows]}
        for label, speakers in (("all test-children clips", test_s), ("all val-children clips", val_s)):
            sets[label] = [(n, 1 - y) for n, _, y in soft_clips(zf, speakers, unclear_only=False)]
    names = sorted({n for clips in sets.values() for n, _ in clips})
    with t.Pool(6, initializer=_init, initargs=(str(args.zip_path), args.models)) as pool:
        pc = dict(zip(names, pool.map(_p_correct, names, chunksize=64)))
    edges = np.linspace(0, 1, 6)
    for label, clips in sets.items():
        share = np.array([y for _, y in clips])
        print(f"=== {label}: {len(clips)} clips, {(np.abs(share - 0.5) < 0.25).mean():.1%} unclear", flush=True)
        for j, m in enumerate(args.models):
            pr = np.array([pc[n][j] for n, _ in clips])
            print(f"RESULT {label} | {m.stem} | Spearman {spearmanr(pr, share)[0]:.3f} | Pearson {pearsonr(pr, share)[0]:.3f}"
                  f" | MAE {np.abs(pr - share).mean():.3f}")
            b = np.clip(np.digitize(pr, edges) - 1, 0, 4)
            print("  reliability (P(correct) bin: n, mean P, mean listener share): " + "; ".join(
                f"{edges[k]:.1f}-{edges[k + 1]:.1f}: {(b == k).sum()}, {pr[b == k].mean():.2f}, {share[b == k].mean():.2f}"
                if (b == k).any() else f"{edges[k]:.1f}-{edges[k + 1]:.1f}: 0" for k in range(5)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
