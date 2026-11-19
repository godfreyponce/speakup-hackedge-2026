"""Arti v2 with the clips listeners disagreed on: does training on the listeners' share help?

v0 and v2 train only on clear clips (0.25 or less, or 0.75 or more of listeners heard the r as correct) and drop
the clips in between. Here the training speakers' unclear clips (8,700) are kept, each with its listener share as a soft
target (the model learns "60% of listeners heard this as correct" instead of nothing). Validation stays on clear
clips only and the 300-clip test set is unchanged, so the result compares directly with v2's runs.

    python -I scripts/experiment_arti_soft.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-soft.onnx
"""

import argparse
import functools
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import torch
from torch import nn

from scripts import train_arti as t
from scripts.experiment_arti_v2 import BCResNet, unsure_table


def soft_clips(zf, train_speakers, unclear_only=True):
    """(zip path, speaker, share heard as wrong) for every unclear (or, with unclear_only=False, every labelled) clip
    of the given speakers."""
    names = set(zf.namelist())
    out = []
    for name in sorted(names):
        parts = name.split("/")
        if len(parts) != 4 or parts[2] != "audio" or not parts[3].endswith(".wav") or parts[1] not in train_speakers:
            continue
        root, speaker, _, file = parts
        label_name = f"{root}/{speaker}/rhotic_perceptual_labels/{file[:-4]}.pickle"
        label = t.read_float(zf.read(label_name)) if label_name in names else None
        if label is not None and (not unclear_only or t.listener_says(label) is None):
            out.append((name, speaker, 1.0 - label))  # label is the share heard correct
    return out


def train_soft(mels, targets, is_val, val_labels, device, seed, make=BCResNet, pos=None, lam=0.0):
    """t.train with soft targets: class-weighted cross-entropy against (1 - y, y), plus lam * CE on position
    (-1 = no position) when make() also returns position logits (experiment_arti_position.TwoHead)."""
    torch.manual_seed(seed)
    body = make().to(device)
    p_tr = torch.from_numpy(pos[~is_val]) if lam else None
    pos_ce = nn.CrossEntropyLoss(ignore_index=-1)
    x_train, y_train = torch.from_numpy(mels[~is_val]), torch.from_numpy(targets[~is_val]).float()
    x_val = torch.from_numpy(mels[is_val])
    share_wrong = float(y_train.mean())
    weight = torch.tensor([0.5 / (1 - share_wrong), 0.5 / share_wrong], device=device)
    opt = torch.optim.Adam(body.parameters(), lr=t.LR)
    best, best_state, best_epoch = -1.0, None, 0
    for epoch in range(1, t.EPOCHS + 1):
        body.train()
        perm = torch.randperm(len(x_train))
        for i in range(0, len(perm), t.BATCH):
            idx = perm[i:i + t.BATCH]
            xb, yb = x_train[idx].float().to(device), y_train[idx].to(device)
            out = body(xb)
            logp = torch.log_softmax(out[0] if lam else out, 1)
            loss = -(weight[1] * yb * logp[:, 1] + weight[0] * (1 - yb) * logp[:, 0]).mean()
            if lam:
                loss = loss + lam * pos_ce(out[1], p_tr[idx].to(device))
            opt.zero_grad()
            loss.backward()
            opt.step()
        body.eval()
        with torch.no_grad():
            pred = torch.cat([main_head(body(x_val[i:i + 1024].float().to(device))).argmax(1).cpu()
                              for i in range(0, len(x_val), 1024)]).numpy()
        bacc = t.balanced_accuracy(pred, val_labels)
        print(f"epoch {epoch}: val balanced accuracy {bacc:.4f}", flush=True)
        if bacc > best:
            best, best_epoch = bacc, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in body.state_dict().items()}
    print(f"kept epoch {best_epoch}: val balanced accuracy {best:.4f}", flush=True)
    body = make()
    body.load_state_dict(best_state)
    return body.eval()


def main_head(out):
    return out[0] if isinstance(out, tuple) else out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=2028)
    p.add_argument("--save", type=Path, help="also save the body's state_dict (for experiment_arti_adapt.py)")
    args = p.parse_args(argv)
    t.Pool = functools.partial(t.Pool, 4)  # keep the laptop usable
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with zipfile.ZipFile(args.zip_path) as zf:
        clips, train_s, val_s, _, _, _ = t.index(zf, test_speakers)
        extra = soft_clips(zf, train_s)
        print(f"clear clips {len(clips)}; unclear training clips added {len(extra)}", flush=True)
        clear_mels = t.build_cache(args.zip_path, clips, data_dir / "arti-cache")
        mels = clear_mels
        if extra:
            extra_mels = t.build_cache(args.zip_path, [(n, s, 0) for n, s, _ in extra], data_dir / "arti-cache-unclear")
            mels = np.concatenate([clear_mels, extra_mels])
        targets = np.array([lab for _, _, lab in clips] + [y for _, _, y in extra], dtype=np.float32)
        is_val = np.array([s in val_s for _, s, _ in clips] + [False] * len(extra))
        val_labels = np.array([lab for _, s, lab in clips if s in val_s], dtype=np.int64)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        body = train_soft(mels, targets, is_val, val_labels, device, args.seed)
        unsure_table(body, mels[is_val], val_labels)
        if args.save:
            torch.save(body.state_dict(), args.save)
        model = t.Arti(t.Frontend(), body).eval()
        sess = t.export(model, args.out, zf, [n for n, s, _ in clips if s in val_s])
        t.score(sess, zf, data_dir / "test-set.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
