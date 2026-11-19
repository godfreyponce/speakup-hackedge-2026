"""Arti v2 side experiment: does a BC-ResNet body, and/or teen+adult speakers in training, beat arti-v0?

Laptop only, nothing deployed. Reuses train_arti.py's data, cache, training loop, export and scoring;
only the body (and, with --adults, the age cap on training speakers) changes. Test speakers and the
300-clip test set are the same as v0's, so "agreed on N of 300" is directly comparable to v0's 258.

    uv run --managed-python --python 3.12 --index https://download.pytorch.org/whl/cu128 \
        --with torch --with torchaudio --with onnx --with onnxscript --with onnxruntime --with numpy \
        python -I scripts/experiment_arti_v2.py data/percept-r/PERCEPT-R.zip --out models/arti-v2.onnx [--adults]

BC-ResNet: Kim et al., "Broadcasted Residual Learning for Efficient Keyword Spotting", Interspeech 2021.
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

WIDTH = 4  # ~100K parameters; paper's BC-ResNet-3 is ~54K, -6 is ~188K
STAGES = ((8, 2, 1, 1), (12, 2, 2, 2), (16, 4, 2, 4), (20, 4, 1, 8))  # (channels/WIDTH, blocks, freq stride, dilation)


class BCBlock(nn.Module):
    def __init__(self, c_in, c, stride, dilation):
        super().__init__()
        self.transition = c_in != c or stride != 1
        self.pre = nn.Sequential(nn.Conv2d(c_in, c, 1, bias=False), nn.BatchNorm2d(c), nn.ReLU()) if self.transition else nn.Identity()
        self.f2 = nn.Sequential(nn.Conv2d(c, c, (3, 1), (stride, 1), (1, 0), groups=c, bias=False), nn.BatchNorm2d(c))
        self.f1 = nn.Sequential(
            nn.Conv2d(c, c, (1, 3), padding=(0, dilation), dilation=(1, dilation), groups=c, bias=False),
            nn.BatchNorm2d(c), nn.SiLU(), nn.Conv2d(c, c, 1, bias=False), nn.Dropout2d(0.1))

    def forward(self, x):
        x = self.pre(x)
        aux = self.f2(x)
        out = aux + self.f1(aux.mean(dim=2, keepdim=True))
        return torch.relu(out if self.transition else out + x)


class BCResNet(nn.Module):
    """log-mel [B, mels, frames] -> logits [B, 2]."""

    def __init__(self):
        super().__init__()
        c0 = 16 * WIDTH
        layers = [nn.Conv2d(1, c0, 5, (2, 1), 2, bias=False), nn.BatchNorm2d(c0), nn.ReLU()]
        c_in = c0
        for ch, n, stride, dil in STAGES:
            c = ch * WIDTH
            for i in range(n):
                layers.append(BCBlock(c_in, c, stride if i == 0 else 1, dil))
                c_in = c
        layers += [nn.Conv2d(c_in, c_in, 5, padding=(0, 2), groups=c_in, bias=False), nn.Conv2d(c_in, 32 * WIDTH, 1, bias=False),
                   nn.BatchNorm2d(32 * WIDTH), nn.ReLU()]
        self.blocks = nn.Sequential(*layers)
        self.head = nn.Linear(32 * WIDTH, 2)

    def embed(self, mels):
        x = mels.unsqueeze(1)
        x = (x - x.mean(dim=(2, 3), keepdim=True)) / (x.std(dim=(2, 3), keepdim=True) + 1e-5)  # per-clip norm: level-proof
        return self.blocks(x).mean(dim=(2, 3))

    def forward(self, mels):
        return self.head(self.embed(mels))


def position_of(name):
    """start or end from the word in the clip's file name (..._<word>_<n>.wav); None for an r in the middle."""
    word = Path(name).stem.split("_")[-2].lower()
    return "start" if word.startswith(("r", "wr")) else "end" if word.endswith(("r", "re")) else None


def unsure_table(body, mels, labels):
    """Validation clips only: for each Unsure band around 0.5, the share handed to the SLP and how well Arti does
    on the rest. Chooses nothing; the band is set by hand in speakup/calibration.py."""
    with torch.no_grad():
        p = torch.cat([torch.softmax(body(torch.from_numpy(mels[i:i + 1024]).float()), 1)[:, 1]
                       for i in range(0, len(mels), 1024)]).numpy()
    band_table(p, labels)


def band_table(p, labels):
    for h in (0.0, 0.1, 0.2, 0.3):
        sure = np.abs(p - 0.5) > h
        ba = t.balanced_accuracy((p[sure] >= 0.5).astype(int), labels[sure]) if sure.any() else float("nan")
        print(f"unsure band 0.5±{h:.1f}: {1 - sure.mean():.1%} of val clips to the SLP, "
              f"balanced accuracy on the rest {ba:.3f}", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--adults", action="store_true", help="also train on speakers over 12 (test stays children)")
    parser.add_argument("--epochs", type=int, default=t.EPOCHS)
    parser.add_argument("--seed", type=int, default=t.SEED, help="training seed only; the speaker split stays seed 2026")
    parser.add_argument("--v0-body", action="store_true", help="train v0's plain CNN instead (same-machine baseline)")
    parser.add_argument("--train-position", choices=("start", "end"),
                        help="train and validate only on words with r at the start (or end); the test set is unchanged, "
                             "so the other position's cells show whether Arti learned the r or the words")
    args = parser.parse_args(argv)
    # Keep the laptop usable: 6 feature workers instead of one per thread, below-normal priority (inherited by them).
    t.Pool = functools.partial(t.Pool, 6)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
    if not args.v0_body:
        t.Body = BCResNet
    t.EPOCHS = args.epochs
    if args.adults:
        t.MAX_AGE_MONTHS = 10 ** 6
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    with zipfile.ZipFile(args.zip_path) as zf:
        clips, train_s, val_s, test, skipped, unclear = t.index(zf, test_speakers)
        print(f"clips {len(clips)}; speakers train {len(train_s)}, val {len(val_s)}, test {len(test)}", flush=True)
        mels = t.build_cache(args.zip_path, clips, data_dir / ("arti-cache-adults" if args.adults else "arti-cache"))
        labels = np.array([lab for _, _, lab in clips], dtype=np.int64)
        is_val = np.array([s in val_s for _, s, _ in clips])
        if args.train_position:
            keep = np.array([position_of(n) == args.train_position for n, _, _ in clips])
            clips = [c for c, k in zip(clips, keep) if k]
            mels, labels, is_val = mels[keep], labels[keep], is_val[keep]
            print(f"train position {args.train_position}: {len(clips)} clips kept", flush=True)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"device {device}", flush=True)
        body, _, _ = t.train(mels, labels, is_val, device, seed=args.seed)
        unsure_table(body, mels[is_val], labels[is_val])
        model = t.Arti(t.Frontend(), body).eval()
        sess = t.export(model, args.out, zf, [n for n, s, _ in clips if s in val_s])
        t.score(sess, zf, data_dir / "test-set.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
