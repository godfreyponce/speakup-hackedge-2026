"""Pick the fixed PERCEPT-R test set (#14) that #2 scores the model against.

Run from the repo root:

    python3 -I scripts/pick_test_set.py data/percept-r/PERCEPT-R.zip

It reads the zip in place, never extracts it, and never unpickles corpus data:
labels and ages are read opcode by opcode with pickletools.genops. It writes
test-set.csv and test-speakers.txt beside the zip.

Corpus: PERCEPT-R, Benway et al. 2023, doi:10.1044/2023_JSLHR-22-00343;
TalkBank, doi:10.21415/0JPJ-X403. CC BY-ND 4.0.
"""

import argparse
import csv
import io
import os
import pickletools
import random
import sys
import zipfile
from collections import defaultdict
from typing import NamedTuple

START_WORDS = ("rabbit", "rain", "ring", "rocket", "red", "rock", "run", "rug", "rose")
END_WORDS = ("car", "door", "bear", "star", "chair", "floor", "hair", "pear", "deer")
WRONG_MAX = 0.25
CORRECT_MIN = 0.75
MAX_AGE_MONTHS = 144
PER_CELL = 75
SEED = 2026
CELLS = (("start", "correct"), ("start", "wrong"), ("end", "correct"), ("end", "wrong"))
COLUMNS = ("zip_path", "speaker", "age_months", "word", "position", "label", "listener_says")

_FRAMING = ("PROTO", "FRAME", "STOP")
_INT_OPS = ("BININT1", "BININT2", "BININT")


def _single_op(data):
    try:
        ops = [(op.name, arg) for op, arg, _ in pickletools.genops(io.BytesIO(data))
               if op.name not in _FRAMING]
    except ValueError:
        return None
    return ops[0] if len(ops) == 1 else None


def read_float(data):
    op = _single_op(data)
    return op[1] if op and op[0] == "BINFLOAT" else None


def read_int(data):
    op = _single_op(data)
    return op[1] if op and op[0] in _INT_OPS else None


def listener_says(label):
    if label <= WRONG_MAX:
        return "wrong"
    if label >= CORRECT_MIN:
        return "correct"
    return None


class Picked(NamedTuple):
    rows: list
    test_speakers: list
    test_ages: list
    children: int
    skipped_labels: int
    skipped_speakers: int
    clips_total: int
    clips_removed: int


def _position(word):
    return "start" if word in START_WORDS else "end"


def pick(zip_path, per_cell=PER_CELL, seed=SEED):
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        speaker_root = {}
        wavs = []
        for name in sorted(names):
            parts = name.split("/")
            if len(parts) != 4 or not parts[3]:
                continue
            root, speaker, kind, file = parts
            speaker_root.setdefault(speaker, root)
            if kind == "audio" and file.endswith(".wav"):
                wavs.append((speaker, root, file[:-len(".wav")]))

        ages = {}
        skipped_speakers = 0
        for speaker, root in speaker_root.items():
            age_name = f"{root}/{speaker}/metadata/age.pickle"
            age = read_int(zf.read(age_name)) if age_name in names else None
            if age is None:
                skipped_speakers += 1
            elif age <= MAX_AGE_MONTHS:
                ages[speaker] = age

        words = START_WORDS + END_WORDS
        kept = defaultdict(list)
        skipped_labels = 0
        for speaker, root, stem in wavs:
            fields = stem.split("_")
            if speaker not in ages or len(fields) != 5 or fields[3] not in words:
                continue
            word = fields[3]
            label_name = f"{root}/{speaker}/rhotic_perceptual_labels/{stem}.pickle"
            label = read_float(zf.read(label_name)) if label_name in names else None
            if label is None:
                skipped_labels += 1
                continue
            says = listener_says(label)
            if says is not None:
                wav = f"{root}/{speaker}/audio/{stem}.wav"
                kept[(speaker, word)].append(
                    (wav, speaker, ages[speaker], word, _position(word), label, says))

    rng = random.Random(seed)
    order = sorted(ages, key=int)
    rng.shuffle(order)
    pool = defaultdict(list)
    held = []
    filled = False
    for speaker in order:
        for word in sorted(w for s, w in kept if s == speaker):
            clip = rng.choice(sorted(kept[(speaker, word)]))
            pool[(clip[4], clip[6])].append(clip)
        held.append(speaker)
        if all(len(pool[cell]) >= per_cell for cell in CELLS):
            filled = True
            break
    if not filled:
        short = [f"{pos} {says}: {len(pool[(pos, says)])} of {per_cell}"
                 for pos, says in CELLS if len(pool[(pos, says)]) < per_cell]
        raise ValueError("not enough clear child clips to fill every cell: " + ", ".join(short))

    rows = []
    for cell in CELLS:
        rows.extend(rng.sample(pool[cell], per_cell))
    rows.sort(key=lambda row: (CELLS.index((row[4], row[6])), row[0]))
    held_set = set(held)
    return Picked(
        rows=rows,
        test_speakers=sorted(held, key=int),
        test_ages=[ages[speaker] for speaker in sorted(held, key=int)],
        children=len(ages),
        skipped_labels=skipped_labels,
        skipped_speakers=skipped_speakers,
        clips_total=len(wavs),
        clips_removed=sum(1 for speaker, _, _ in wavs if speaker in held_set),
    )


def write_outputs(picked, out_dir):
    with open(os.path.join(out_dir, "test-set.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(COLUMNS)
        writer.writerows(picked.rows)
    with open(os.path.join(out_dir, "test-speakers.txt"), "w", newline="", encoding="utf-8") as f:
        f.write("".join(f"{speaker}\n" for speaker in picked.test_speakers))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zip_path")
    zip_path = parser.parse_args(argv).zip_path
    try:
        picked = pick(zip_path)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    out_dir = os.path.dirname(os.path.abspath(zip_path))
    write_outputs(picked, out_dir)

    counts = {cell: 0 for cell in CELLS}
    for row in picked.rows:
        counts[(row[4], row[6])] += 1
    print(f"test speakers: {len(picked.test_speakers)} of {picked.children} children, "
          f"ages {min(picked.test_ages)}-{max(picked.test_ages)} months")
    print("clips picked: " + ", ".join(f"{pos} {says} {counts[(pos, says)]}" for pos, says in CELLS))
    print(f"label pickles skipped (not one float): {picked.skipped_labels}")
    print(f"speakers skipped (age not one int): {picked.skipped_speakers}")
    print(f"training pool: {picked.clips_total} clips, {picked.clips_removed} removed by the "
          f"speaker hold-out, {picked.clips_total - picked.clips_removed} left")
    print(f"wrote {os.path.join(out_dir, 'test-set.csv')} and "
          f"{os.path.join(out_dir, 'test-speakers.txt')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
