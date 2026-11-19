"""Arti v2 plus the measured F3-F2 gap: does the physics measure add anything the network does not already hear?

The gap (speakup/acoustics.py, the SLP page's code, searched where the word's r sits) is measured once per clip and
cached in gap-cache.npz. The classifier sees v2's pooled features plus two numbers: the gap (in kHz, minus 1) and
a "could not measure" flag (gap then 0). The gap is an ONNX input, measured outside the model. Measuring all
42k clips would take ~90 min, so the gap is measured on every val clip and a stratified share of the training
clips, and v2 is retrained on the same subset for a fair comparison. Seed and test set as experiment_arti_v2.py.

    python -I scripts/experiment_arti_hybrid.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-gap.onnx
    python -I scripts/experiment_arti_hybrid.py data/percept-r/PERCEPT-R.zip --gaps-only   # build the cache only
"""

import argparse
import csv
import functools
import os
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from torch import nn

from scripts import train_arti as t
from scripts.experiment_arti_position import fit
from scripts.experiment_arti_v2 import WIDTH, BCResNet, band_table, position_of
from speakup import acoustics
from speakup.arti import RATE, WINDOW_SECONDS, prepare

_worker = {}


def _init(zip_path, tmp_dir):
    _worker["zf"] = zipfile.ZipFile(zip_path)
    _worker["tmp"] = Path(tmp_dir) / f"{os.getpid()}.wav"


def _gap(name):
    _worker["tmp"].write_bytes(_worker["zf"].read(name))
    try:
        g = acoustics.analyse(_worker["tmp"], position_of(name)).gap_min
    except Exception:  # not measurable, like on the SLP page
        g = None
    return np.nan if g is None else g


def gap_cache(zip_path, names, path):
    if path.exists():
        cached = np.load(path)
        if list(cached["names"]) == names:
            print(f"gap cache: reusing {path}", flush=True)
            return cached["gap"]
    gaps, t0 = [], time.time()
    with tempfile.TemporaryDirectory() as td, t.Pool(initializer=_init, initargs=(str(zip_path), td)) as pool:
        for g in pool.imap(_gap, names, chunksize=64):
            gaps.append(g)
            if len(gaps) % 2000 == 0 or len(gaps) == len(names):
                print(f"gap cache: {len(gaps)} of {len(names)} clips, {time.time() - t0:.0f} s", flush=True)
    gaps = np.array(gaps)
    np.savez(path, names=np.array(names), gap=gaps)
    return gaps


def features(gaps):
    return np.stack([np.nan_to_num(gaps / 1000 - 1), np.isnan(gaps)], 1).astype(np.float32)


class Hybrid(BCResNet):
    def __init__(self):
        super().__init__()
        self.head = nn.Linear(32 * WIDTH + 2, 2)

    def forward(self, mels, gap):
        return self.head(torch.cat([self.embed(mels), gap], 1))


class HybridArti(nn.Module):
    """audio [1, N], gap features [1, 2] -> p_wrong [1]."""

    def __init__(self, body):
        super().__init__()
        self.frontend, self.body = t.Frontend(), body

    def forward(self, audio, gap):
        return torch.softmax(self.body(self.frontend(audio), gap), dim=1)[:, 1]


def mels_of(zf, names):
    """log-mel for clips that are not in a cache (the 300 test clips), as the caches store them."""
    frontend = t.Frontend().eval()
    with torch.no_grad():
        return np.concatenate([frontend(torch.tensor([prepare(t.to_16k(zf.read(n)))])).numpy()
                               for n in names]).astype(np.float16)


def probs(body, xs):
    """p_wrong for every clip; xs are per-clip arrays (mels, and gap features for the hybrid)."""
    with torch.no_grad():
        return torch.cat([torch.softmax(body(*(torch.from_numpy(x[i:i + 1024]).float() for x in xs)), 1)[:, 1]
                          for i in range(0, len(xs[0]), 1024)]).numpy()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--seed", type=int, default=2028)
    p.add_argument("--train-share", type=float, default=0.25,
                   help="share of each training (position, label) cell measured and trained on; val and test are whole")
    p.add_argument("--gaps-only", action="store_true")
    args = p.parse_args(argv)
    t.Pool = functools.partial(t.Pool, 6)  # keep the laptop usable
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with open(data_dir / "test-set.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with zipfile.ZipFile(args.zip_path) as zf:
        all_clips, _, val_s, _, _, _ = t.index(zf, test_speakers)
        # Measuring every clip takes ~90 min here, so: all val clips plus a stratified share of the training clips.
        rng = np.random.default_rng(2026)
        keep = np.array([s in val_s for _, s, _ in all_clips])
        cells = {}
        for i, (n, s, lab) in enumerate(all_clips):
            if s not in val_s:
                cells.setdefault((position_of(n), lab), []).append(i)
        for idx in cells.values():
            keep[rng.choice(idx, round(len(idx) * args.train_share), replace=False)] = True
        clips = [c for c, k in zip(all_clips, keep) if k]
        names = [n for n, _, _ in clips] + [r["zip_path"] for r in rows]
        gaps = gap_cache(args.zip_path, names, data_dir / "gap-cache.npz")
        print(f"gap not measurable: {np.isnan(gaps[:len(clips)]).sum()} of {len(clips)} train/val clips, "
              f"{np.isnan(gaps[len(clips):]).sum()} of {len(rows)} test clips", flush=True)
        if args.gaps_only:
            return 0
        feats, test_feats = features(gaps[:len(clips)]), features(gaps[len(clips):])
        mels = t.build_cache(args.zip_path, all_clips, data_dir / "arti-cache")[keep]
        labels = np.array([lab for _, _, lab in clips], dtype=np.int64)
        is_val = np.array([s in val_s for _, s, _ in clips])
        print(f"train clips {(~is_val).sum()} ({args.train_share:.0%} of each cell), val clips {is_val.sum()}", flush=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        test_mels = mels_of(zf, [r["zip_path"] for r in rows])
        truth = np.array([r["listener_says"] == "wrong" for r in rows])
        measured = test_feats[:, 1] == 0
        for name, make, xs, txs in (("v2 (same subset)", BCResNet, [mels], [test_mels]),
                                    ("hybrid", Hybrid, [mels, feats], [test_mels, test_feats])):
            print(f"--- {name}", flush=True)
            body = fit(make, xs, labels, is_val, device, args.seed)
            band_table(probs(body, [x[is_val] for x in xs]), labels[is_val])
            agreed = (probs(body, txs) >= 0.5) == truth
            for pos in ("start", "end"):
                for says in ("correct", "wrong"):
                    cell = np.array([r["position"] == pos and r["listener_says"] == says for r in rows])
                    print(f"{pos}-r {says}: agreed on {agreed[cell].sum()} of {cell.sum()}")
            print(f"{name} agreed with the listeners on {agreed.sum()} of {len(rows)} clips; "
                  f"on the {measured.sum()} with a measurable gap: {agreed[measured].sum()}.", flush=True)

    model = HybridArti(body).eval()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, (torch.zeros(1, int(RATE * WINDOW_SECONDS)), torch.zeros(1, 2)), str(args.out),
                      input_names=["audio", "gap"], output_names=["p_wrong"], opset_version=18,
                      dynamic_shapes={"audio": {1: torch.export.Dim("samples", min=t.MIN_SAMPLES)}, "gap": None},
                      dynamo=True, external_data=False)
    print(f"exported {args.out} ({args.out.stat().st_size / 1e6:.2f} MB)", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
