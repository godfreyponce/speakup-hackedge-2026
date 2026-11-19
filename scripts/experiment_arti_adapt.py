"""Per-child adaptation: does fine-tuning the soft-label v2 on K of one child's clips help on that child's other clips?

The speaker split is already speaker-disjoint (train / val / test children never overlap), so the children here are
the test children (or, with --on val, the validation children, used to pick --lr and --steps). Every labelled clip
of a child counts, unclear ones too. For each child with enough clips of both kinds, K clips are drawn (stratified by
heard correct / wrong), the last BC block, the final conv stack and the head are fine-tuned on their listener shares
(class-balanced soft cross-entropy, BatchNorm statistics frozen), and the child's remaining clips are scored with and without adaptation: balanced
accuracy on the clear ones, Spearman correlation of P(correct) with the listener share on all of them.

    python -I scripts/experiment_arti_soft.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-soft.onnx \
        --save models/arti-v2-soft.pt
    python -I scripts/experiment_arti_adapt.py data/percept-r/PERCEPT-R.zip models/arti-v2-soft.pt
"""

import argparse
import copy
import functools
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from scipy.stats import spearmanr

from scripts import train_arti as t
from scripts.experiment_arti_soft import soft_clips
from scripts.experiment_arti_v2 import BCBlock, BCResNet

KS, REPS, MIN_CLIPS, MIN_CLEAR = (5, 10, 20), 3, 40, 10


def metrics(p_wrong, share_wrong):
    clear = np.abs(share_wrong - 0.5) >= 0.25
    bacc = t.balanced_accuracy((p_wrong[clear] >= 0.5).astype(int), (share_wrong[clear] >= 0.5).astype(int))
    return bacc, spearmanr(1 - p_wrong, 1 - share_wrong)[0]


def predict(body, x):
    with torch.no_grad():
        return torch.cat([torch.softmax(body(x[i:i + 256]), 1)[:, 1] for i in range(0, len(x), 256)]).cpu().numpy()


def adapt(base, x, y, lr, steps):
    body = copy.deepcopy(base)
    last = max(i for i, m in enumerate(body.blocks) if isinstance(m, BCBlock))
    params = [p for m in list(body.blocks)[last:] + [body.head] for p in m.parameters()]
    for p in body.parameters():
        p.requires_grad_(False)
    for p in params:
        p.requires_grad_(True)
    body.eval()  # BatchNorm stats and dropout frozen: K clips are too few to re-estimate them
    opt = torch.optim.Adam(params, lr=lr)
    sw = float(y.mean().clamp(0.1, 0.9))  # class-balanced like the base's training, or 0.5 drifts to the child's mix
    for _ in range(steps):
        logp = torch.log_softmax(body(x), 1)
        loss = -(0.5 / sw * y * logp[:, 1] + 0.5 / (1 - sw) * (1 - y) * logp[:, 0]).mean()
        opt.zero_grad()
        loss.backward()
        opt.step()
    return body


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("weights", type=Path, help="state_dict of the soft-label BCResNet")
    p.add_argument("--on", choices=("test", "val"), default="test")
    p.add_argument("--lr", type=float, default=3e-4)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--max-children", type=int, default=20)
    args = p.parse_args(argv)
    t.Pool = functools.partial(t.Pool, 4)  # keep the laptop usable (and its page file)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with zipfile.ZipFile(args.zip_path) as zf:
        _, train_s, val_s, test_s, _, _ = t.index(zf, test_speakers)
        speakers = test_s if args.on == "test" else val_s
        assert not (speakers & train_s)
        items = soft_clips(zf, speakers, unclear_only=False)
        mels = t.build_cache(args.zip_path, [(n, s, 0) for n, s, _ in items], data_dir / f"arti-cache-all-{args.on}")
    share = np.array([y for _, _, y in items], dtype=np.float32)
    who = np.array([s for _, s, _ in items])
    device = "cuda" if torch.cuda.is_available() else "cpu"
    base = BCResNet()
    base.load_state_dict(torch.load(args.weights))
    base = base.to(device).eval()
    children = [s for s in sorted(speakers, key=int)
                if (who == s).sum() >= MIN_CLIPS
                and min(((who == s) & (share <= 0.25)).sum(), ((who == s) & (share >= 0.75)).sum()) >= MIN_CLEAR]
    print(f"{len(speakers)} {args.on} children, {len(children)} with >= {MIN_CLIPS} clips and >= {MIN_CLEAR} clear "
          f"of each kind; using {min(len(children), args.max_children)}; lr {args.lr}, {args.steps} steps", flush=True)
    rng = np.random.default_rng(2026)
    rows = {k: [] for k in (0,) + KS}  # per child: (base bacc, adapted bacc, base rho, adapted rho), mean over reps
    for s in children[:args.max_children]:
        idx = np.flatnonzero(who == s)
        x = torch.from_numpy(mels[idx]).float().to(device)
        y = torch.from_numpy(share[idx]).to(device)
        p0 = predict(base, x)
        b0, r0 = metrics(p0, share[idx])
        rows[0].append((b0, b0, r0, r0))
        line = f"child {s}: {len(idx)} clips, K=0 bacc {b0:.3f} rho {r0:.3f}"
        for k in KS:
            reps = []
            for _ in range(REPS):
                wrong = share[idx] >= 0.5
                n_wrong = int(round(k * wrong.mean()))
                pick = np.concatenate([rng.choice(np.flatnonzero(wrong), n_wrong, replace=False),
                                       rng.choice(np.flatnonzero(~wrong), k - n_wrong, replace=False)])
                rest = np.setdiff1d(np.arange(len(idx)), pick)
                pa = predict(adapt(base, x[pick], y[pick], args.lr, args.steps), x[rest])
                reps.append(metrics(p0[rest], share[idx][rest]) + metrics(pa, share[idx][rest]))
            b, r, ba, ra = np.mean(reps, 0)
            rows[k].append((b, ba, r, ra))
            line += f" | K={k} bacc {b:.3f}->{ba:.3f} rho {r:.3f}->{ra:.3f}"
        print(line, flush=True)
    print("K | children | bacc base on same rest | bacc adapted | rho base | rho adapted  (mean +/- sd across children)")
    for k, v in rows.items():
        v = np.array(v)
        m, sd = v.mean(0), v.std(0)
        print(f"RESULT K={k} | {len(v)} | {m[0]:.3f} +/- {sd[0]:.3f} | {m[1]:.3f} +/- {sd[1]:.3f} | "
              f"{m[2]:.3f} +/- {sd[2]:.3f} | {m[3]:.3f} +/- {sd[3]:.3f} | mean gain bacc {np.mean(v[:, 1] - v[:, 0]):+.3f}, "
              f"rho {np.mean(v[:, 3] - v[:, 2]):+.3f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
