"""Learning curve for v2 soft labels, without and with the r-position head: does the extra task help more when
there is less data?

Each run trains on a share of every training (position, label) cell (unclear clips are their own cell), drawn once
with rng 2026 so lambda 0 and 0.3 see the same clips; --seeds varies the training seed only. Validation (all clear
val clips) and the 300-clip test set are whole. Training as experiment_arti_soft.py, head as
experiment_arti_position.py.

    python -I scripts/experiment_arti_curve.py data/percept-r/PERCEPT-R.zip --shares 0.1 0.25 --seeds 2028 2029
"""

import argparse
import csv
import functools
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch

from scripts import train_arti as t
from scripts.experiment_arti_hybrid import mels_of, probs
from scripts.experiment_arti_position import TwoHead
from scripts.experiment_arti_soft import soft_clips, train_soft
from scripts.experiment_arti_v2 import BCResNet, position_of


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("--shares", type=float, nargs="+", default=[0.1, 0.25, 0.5])
    p.add_argument("--seeds", type=int, nargs="+", default=[2028])
    p.add_argument("--lams", type=float, nargs="+", default=[0.0, 0.3])
    args = p.parse_args(argv)
    t.Pool = functools.partial(t.Pool, 4)  # keep the laptop usable
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with open(data_dir / "test-set.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with zipfile.ZipFile(args.zip_path) as zf:
        clips, train_s, val_s, _, _, _ = t.index(zf, test_speakers)
        extra = soft_clips(zf, train_s)
        mels = np.concatenate([t.build_cache(args.zip_path, clips, data_dir / "arti-cache"),
                               t.build_cache(args.zip_path, [(n, s, 0) for n, s, _ in extra],
                                             data_dir / "arti-cache-unclear")])
        test_mels = mels_of(zf, [r["zip_path"] for r in rows])
    items = clips + extra
    targets = np.array([y for _, _, y in items], dtype=np.float32)
    is_val = np.array([s in val_s for _, s, _ in clips] + [False] * len(extra))
    val_labels = np.array([lab for _, s, lab in clips if s in val_s], dtype=np.int64)
    pos = np.array([{"start": 0, "end": 1}.get(position_of(n), -1) for n, _, _ in items], dtype=np.int64)
    kind = [str(y) if i < len(clips) else "unclear" for i, (_, _, y) in enumerate(items)]
    truth = np.array([r["listener_says"] == "wrong" for r in rows])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    for share in args.shares:
        keep = is_val.copy()
        cells, rng = {}, np.random.default_rng(2026)
        for i in np.flatnonzero(~is_val):
            cells.setdefault((pos[i], kind[i]), []).append(i)
        for idx in cells.values():
            keep[rng.choice(idx, round(len(idx) * share), replace=False)] = True
        print(f"=== share {share:.0%}: {(keep & ~is_val).sum()} training clips", flush=True)
        for seed in args.seeds:
            for lam in args.lams:
                trained = train_soft(mels[keep], targets[keep], is_val[keep], val_labels, device, seed,
                                     TwoHead if lam else BCResNet, pos[keep], lam)
                body = BCResNet()
                body.load_state_dict({k: v for k, v in trained.state_dict().items() if not k.startswith("pos_head.")})
                body.eval()
                pv = probs(body, [mels[is_val]])
                val_bacc = t.balanced_accuracy((pv >= 0.5).astype(int), val_labels)
                sure = np.abs(pv - 0.5) > 0.2
                band_bacc = t.balanced_accuracy((pv[sure] >= 0.5).astype(int), val_labels[sure])
                agreed = int(((probs(body, [test_mels]) >= 0.5) == truth).sum())
                print(f"RESULT share {share:.2f} seed {seed} lambda {lam}: test {agreed}/300, val bal acc "
                      f"{val_bacc:.3f}, +/-0.2 band sends {1 - sure.mean():.1%}, acc on rest {band_bacc:.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
