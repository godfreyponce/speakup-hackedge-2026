"""Arti v2 with a second task: also predict where the r sits in the word (start or end).

Loss = CE(right/wrong) + 0.3 * CE(position); clips with the r in the middle add no position loss. Only the
right/wrong head is exported, so the ONNX file is the same shape and cost as v2's. Data, seed and scoring as
experiment_arti_v2.py.

    python -I scripts/experiment_arti_position.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-pos.onnx
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
from scripts.experiment_arti_v2 import WIDTH, BCResNet, position_of, unsure_table

LAMBDA = 0.3


class TwoHead(BCResNet):
    def __init__(self):
        super().__init__()
        self.pos_head = nn.Linear(32 * WIDTH, 2)

    def forward(self, mels):
        z = self.embed(mels)
        return self.head(z), self.pos_head(z)


def fit(make, xs, labels, is_val, device, seed, pos=None, lam=0.0):
    """t.train for any body taking the arrays in xs: class-weighted CE on right/wrong, plus lam * CE on position
    (-1 = no position) when the body also returns position logits. Keeps the epoch with the best val accuracy."""
    torch.manual_seed(seed)
    body = make().to(device)
    x_tr = [torch.from_numpy(x[~is_val]) for x in xs]
    x_val = [torch.from_numpy(x[is_val]) for x in xs]
    y_tr, y_val = torch.from_numpy(labels[~is_val]), labels[is_val]
    p_tr = torch.from_numpy(pos[~is_val]) if pos is not None else None
    counts = torch.bincount(y_tr, minlength=2).float()
    ce = nn.CrossEntropyLoss(weight=(counts.sum() / (2 * counts)).to(device))
    pos_ce = nn.CrossEntropyLoss(ignore_index=-1)
    opt = torch.optim.Adam(body.parameters(), lr=t.LR)

    def main_logits(out):
        return out[0] if isinstance(out, tuple) else out

    best, best_state, best_epoch = -1.0, None, 0
    for epoch in range(1, t.EPOCHS + 1):
        body.train()
        perm = torch.randperm(len(y_tr))
        for i in range(0, len(perm), t.BATCH):
            idx = perm[i:i + t.BATCH]
            out = body(*(x[idx].float().to(device) for x in x_tr))
            loss = ce(main_logits(out), y_tr[idx].to(device))
            if lam:
                loss = loss + lam * pos_ce(out[1], p_tr[idx].to(device))
            opt.zero_grad()
            loss.backward()
            opt.step()
        body.eval()
        with torch.no_grad():
            pred = torch.cat([main_logits(body(*(x[i:i + 1024].float().to(device) for x in x_val))).argmax(1).cpu()
                              for i in range(0, len(y_val), 1024)]).numpy()
        bacc = t.balanced_accuracy(pred, y_val)
        print(f"epoch {epoch}: val balanced accuracy {bacc:.4f}", flush=True)
        if bacc > best:
            best, best_epoch = bacc, epoch
            best_state = {k: v.detach().cpu().clone() for k, v in body.state_dict().items()}
    print(f"kept epoch {best_epoch}: val balanced accuracy {best:.4f}", flush=True)
    body = make()
    body.load_state_dict(best_state)
    return body.eval()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--seed", type=int, default=2028)
    args = p.parse_args(argv)
    t.Pool = functools.partial(t.Pool, 6)  # keep the laptop usable
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with zipfile.ZipFile(args.zip_path) as zf:
        clips, _, val_s, _, _, _ = t.index(zf, test_speakers)
        mels = t.build_cache(args.zip_path, clips, data_dir / "arti-cache")
        labels = np.array([lab for _, _, lab in clips], dtype=np.int64)
        is_val = np.array([s in val_s for _, s, _ in clips])
        pos = np.array([{"start": 0, "end": 1}.get(position_of(n), -1) for n, _, _ in clips], dtype=np.int64)
        print(f"position labels: start {(pos == 0).sum()}, end {(pos == 1).sum()}, middle (no loss) {(pos == -1).sum()}",
              flush=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        two = fit(TwoHead, [mels], labels, is_val, device, args.seed, pos, LAMBDA)
        body = BCResNet()
        body.load_state_dict({k: v for k, v in two.state_dict().items() if not k.startswith("pos_head.")})
        body.eval()
        unsure_table(body, mels[is_val], labels[is_val])
        sess = t.export(t.Arti(t.Frontend(), body).eval(), args.out, zf, [n for n, s, _ in clips if s in val_s])
        t.score(sess, zf, data_dir / "test-set.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
