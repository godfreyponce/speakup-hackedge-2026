"""Train Arti (#2) on PERCEPT-R, export it to ONNX, and score it on the #14 test set.

Laptop only. Run from the repo root:

    uv run --managed-python --python 3.12 --with torch --with torchaudio --with onnx --with onnxscript \
        --with onnxruntime --with numpy python -I scripts/train_arti.py \
        /path/to/data/percept-r/PERCEPT-R.zip --out models/arti-v0.onnx

It reads the zip in place, never extracts it, and never unpickles corpus data. The mel cache
goes in arti-cache/ beside the zip. No speaker in test-speakers.txt is trained or validated on.
The shape and training settings are guesses with no tuning budget; see docs/model-timing.md.

Corpus: PERCEPT-R, Benway et al. 2023, doi:10.1044/2023_JSLHR-22-00343;
TalkBank, doi:10.21415/0JPJ-X403. CC BY-ND 4.0.
"""

import argparse
import csv
import io
import random
import sys
import time
import wave
import zipfile
from multiprocessing import Pool
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import onnxruntime as ort
import torch
import torchaudio
from torch import nn

from scripts.pick_test_set import MAX_AGE_MONTHS, listener_says, read_float, read_int
from speakup.arti import RATE, THREADS, WINDOW_SECONDS, prepare, to_result

SEED = 2026
VAL_SHARE = 0.1
N_FFT, HOP, N_MELS = 400, 160, 40
EPOCHS, BATCH, LR = 20, 256, 1e-3
PARITY_CLIPS, PARITY_TOL = 64, 1e-4
CHANNELS = (16, 32, 64, 64)
# Four 2x pools need at least 16 frames, so the dynamic time axis starts there.
MIN_SAMPLES = N_FFT + (2 ** len(CHANNELS) - 1) * HOP


class Frontend(nn.Module):
    """Log-mel as plain Conv and MatMul ops, so the ONNX graph needs no STFT op."""

    def __init__(self):
        super().__init__()
        n = torch.arange(N_FFT, dtype=torch.float64)
        k = torch.arange(N_FFT // 2 + 1, dtype=torch.float64)
        window = torch.hann_window(N_FFT, periodic=True, dtype=torch.float64)
        angle = 2 * torch.pi * k[:, None] * n[None, :] / N_FFT
        basis = torch.cat([torch.cos(angle), -torch.sin(angle)]) * window
        self.register_buffer("dft", basis.float().unsqueeze(1))
        mel = torchaudio.functional.melscale_fbanks(N_FFT // 2 + 1, 0.0, RATE / 2, N_MELS, RATE)
        self.register_buffer("mel", mel.T.contiguous())

    def forward(self, audio):
        spec = nn.functional.conv1d(audio.unsqueeze(1), self.dft, stride=HOP)
        re, im = spec.chunk(2, dim=1)
        return torch.log(torch.matmul(self.mel, re * re + im * im) + 1e-6)


class Body(nn.Module):
    def __init__(self):
        super().__init__()
        layers, c_in = [], 1
        for c in CHANNELS:
            layers += [nn.Conv2d(c_in, c, 3, padding=1), nn.BatchNorm2d(c), nn.ReLU(), nn.MaxPool2d(2)]
            c_in = c
        self.blocks = nn.Sequential(*layers)
        self.head = nn.Linear(c_in, 2)

    def forward(self, mels):
        return self.head(self.blocks(mels.unsqueeze(1)).mean(dim=(2, 3)))


class Arti(nn.Module):
    """audio [1, N] at 16 kHz, -1..1 -> p_wrong [1]."""

    def __init__(self, frontend, body):
        super().__init__()
        self.frontend, self.body = frontend, body

    def forward(self, audio):
        return torch.softmax(self.body(self.frontend(audio)), dim=1)[:, 1]


def index(zf, test_speakers):
    names = set(zf.namelist())
    speaker_root, wavs = {}, []
    for name in sorted(names):
        parts = name.split("/")
        if len(parts) != 4 or not parts[3]:
            continue
        root, speaker, kind, file = parts
        speaker_root.setdefault(speaker, root)
        if kind == "audio" and file.endswith(".wav"):
            wavs.append((speaker, root, file[:-len(".wav")]))
    ages = {}
    for speaker, root in speaker_root.items():
        age_name = f"{root}/{speaker}/metadata/age.pickle"
        age = read_int(zf.read(age_name)) if age_name in names else None
        if age is not None and age <= MAX_AGE_MONTHS:
            ages[speaker] = age

    pool_speakers = sorted((s for s in ages if s not in test_speakers), key=int)
    rng = random.Random(SEED)
    rng.shuffle(pool_speakers)
    n_val = round(len(pool_speakers) * VAL_SHARE)
    val, train = set(pool_speakers[:n_val]), set(pool_speakers[n_val:])
    test = set(test_speakers) & set(ages)
    assert not (train & val) and not (train & set(test_speakers)) and not (val & set(test_speakers)), \
        "a speaker is in more than one of train, val and test"

    clips, skipped, unclear = [], 0, 0
    for speaker, root, stem in wavs:
        if speaker not in train and speaker not in val:
            continue
        label_name = f"{root}/{speaker}/rhotic_perceptual_labels/{stem}.pickle"
        label = read_float(zf.read(label_name)) if label_name in names else None
        if label is None:
            skipped += 1
            continue
        says = listener_says(label)
        if says is None:
            unclear += 1
            continue
        clips.append((f"{root}/{speaker}/audio/{stem}.wav", speaker, 1 if says == "wrong" else 0))
    return clips, train, val, test, skipped, unclear


def to_16k(data):
    with wave.open(io.BytesIO(data), "rb") as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        if channels != 1 or width != 2:
            raise ValueError(f"need mono 16-bit, got {channels} channel(s), {8 * width}-bit")
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    x = torch.from_numpy(pcm.astype(np.float32))
    if rate != RATE:
        x = torchaudio.functional.resample(x, rate, RATE)
    return x.round().clamp(-32768, 32767).to(torch.int16).tolist()


_worker = {}


def _init(zip_path):
    torch.set_num_threads(1)
    _worker["zf"] = zipfile.ZipFile(zip_path)
    _worker["frontend"] = Frontend().eval()


def _mels(names):
    zf, frontend = _worker["zf"], _worker["frontend"]
    audio = torch.tensor([prepare(to_16k(zf.read(n))) for n in names], dtype=torch.float32)
    with torch.no_grad():
        return frontend(audio).to(torch.float16).numpy()


def build_cache(zip_path, clips, cache):
    cache.mkdir(exist_ok=True)
    index_file = cache / "index.csv"
    wanted = "".join(f"{name},{speaker},{label}\n" for name, speaker, label in clips)
    if index_file.exists() and index_file.read_text(encoding="utf-8") == wanted and (cache / "mels.npy").exists():
        mels = np.load(cache / "mels.npy")
        if len(mels) == len(clips):
            print(f"cache: reusing {cache} ({len(mels)} clips)", flush=True)
            return mels
    names = [c[0] for c in clips]
    chunks = [names[i:i + 500] for i in range(0, len(names), 500)]
    parts, done, next_line, t0 = [], 0, 10000, time.time()
    with Pool(initializer=_init, initargs=(str(zip_path),)) as pool:
        for part in pool.imap(_mels, chunks):
            parts.append(part)
            done += len(part)
            if done >= next_line or done == len(names):
                print(f"cache: {done} of {len(names)} clips, {time.time() - t0:.0f} s", flush=True)
                next_line += 10000
    mels = np.concatenate(parts)
    np.save(cache / "mels.npy", mels)
    index_file.write_text(wanted, encoding="utf-8")
    return mels


def balanced_accuracy(pred, truth):
    recalls = [(pred[truth == c] == c).mean() for c in (0, 1)]
    return float(sum(recalls) / 2)


def train(mels, labels, is_val, device, *, seed=SEED, order=None, augment=None):
    torch.manual_seed(seed)
    body = Body().to(device)
    print(f"parameters: {sum(p.numel() for p in body.parameters())}", flush=True)
    x_train = torch.from_numpy(mels[~is_val])
    y_train = torch.from_numpy(labels[~is_val]).long()
    x_val = torch.from_numpy(mels[is_val])
    y_val = labels[is_val]
    counts = torch.bincount(y_train, minlength=2).float()
    weight = (counts.sum() / (2 * counts)).to(device)
    loss_fn = nn.CrossEntropyLoss(weight=weight)
    opt = torch.optim.Adam(body.parameters(), lr=LR)
    best, best_state, best_epoch, best_pred = -1.0, None, 0, None
    for epoch in range(1, EPOCHS + 1):
        body.train()
        perm = torch.randperm(len(x_train), generator=order)
        total = 0.0
        for i in range(0, len(perm), BATCH):
            idx = perm[i:i + BATCH]
            xb = x_train[idx].float()
            if augment is not None:
                xb = augment(xb)
            xb, yb = xb.to(device), y_train[idx].to(device)
            loss = loss_fn(body(xb), yb)
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += loss.item() * len(idx)
        body.eval()
        with torch.no_grad():
            pred = torch.cat([body(x_val[i:i + 1024].float().to(device)).argmax(1).cpu()
                              for i in range(0, len(x_val), 1024)]).numpy()
        bacc = balanced_accuracy(pred, y_val)
        print(f"epoch {epoch}: train loss {total / len(perm):.4f}, val balanced accuracy {bacc:.4f}", flush=True)
        if bacc > best:
            best, best_epoch, best_pred = bacc, epoch, pred
            best_state = {k: v.detach().cpu().clone() for k, v in body.state_dict().items()}
    print(f"kept epoch {best_epoch}: val balanced accuracy {best:.4f}", flush=True)
    body = Body()
    body.load_state_dict(best_state)
    return body.eval(), best_epoch, best_pred


def session(path):
    options = ort.SessionOptions()
    options.intra_op_num_threads = THREADS
    return ort.InferenceSession(str(path), options, providers=["CPUExecutionProvider"])


def export(model, out, zf, val_names):
    out.parent.mkdir(parents=True, exist_ok=True)
    example = torch.zeros(1, int(RATE * WINDOW_SECONDS))
    torch.onnx.export(
        model, (example,), str(out), input_names=["audio"], output_names=["p_wrong"], opset_version=18,
        dynamic_shapes={"audio": {1: torch.export.Dim("samples", min=MIN_SAMPLES)}}, dynamo=True, external_data=False,
    )
    sess = session(out)
    worst = 0.0
    for name in val_names[:PARITY_CLIPS]:
        audio = torch.tensor([prepare(to_16k(zf.read(name)))], dtype=torch.float32)
        with torch.no_grad():
            want = float(model(audio)[0])
        got = float(sess.run(["p_wrong"], {"audio": audio.numpy()})[0][0])
        worst = max(worst, abs(want - got))
    if worst > PARITY_TOL:
        sys.exit(f"export parity failed: torch and ONNX Runtime differ by {worst:.2e} (limit {PARITY_TOL})")
    print(f"exported {out} ({out.stat().st_size / 1e6:.2f} MB); parity on {PARITY_CLIPS} val clips: "
          f"max difference {worst:.2e}", flush=True)
    return sess


def score(sess, zf, test_csv):
    cells = {}
    with open(test_csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        audio = np.asarray([prepare(to_16k(zf.read(row["zip_path"])))], dtype=np.float32)
        result = to_result(row["word"], float(sess.run(["p_wrong"], {"audio": audio})[0][0]))
        agreed = (result["error_type"] is None) == (row["listener_says"] == "correct")
        cell = cells.setdefault((row["position"], row["listener_says"]), [0, 0])
        cell[0] += agreed
        cell[1] += 1
    for (position, says), (agreed, total) in sorted(cells.items(), key=lambda kv: (kv[0][0] != "start", kv[0][1])):
        print(f"{position}-r {says}: agreed on {agreed} of {total}")
    agreed = sum(a for a, _ in cells.values())
    print(f"Arti agreed with the listeners on {agreed} of {len(rows)} clips.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip_path", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    data_dir = args.zip_path.resolve().parent
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

        device = "mps" if torch.backends.mps.is_available() else "cpu"
        body, _, _ = train(mels, labels, is_val, device)
        model = Arti(Frontend(), body).eval()
        val_names = [name for name, speaker, _ in clips if speaker in val_speakers]
        sess = export(model, args.out, zf, val_names)
        score(sess, zf, data_dir / "test-set.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
