"""The F3-F2 gap alone as an r judge: how far does the physics measure get without a model?

Measures the gap (speakup/acoustics.py, the same code the SLP page uses) on a sample of training-speaker clips,
picks one cutoff per word position from those clips only, then scores the cutoff on the fixed 300-clip test set
that Arti is scored on. Nothing from the test speakers is used to pick the cutoff. Prints numbers only; writes no
audio. Laptop only.

    python -I scripts/gap_baseline.py data/percept-r/PERCEPT-R.zip [--per-cell 300]
"""

import argparse
import csv
import json
import random
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from scripts.pick_test_set import END_WORDS, START_WORDS
from scripts.train_arti import index
from speakup import acoustics


def word_of(zip_path):
    return Path(zip_path).stem.split("_")[-2]


def gap(zf, name, position, tmp):
    tmp.write_bytes(zf.read(name))
    try:
        return acoustics.analyse(tmp, position).gap_min
    except Exception:  # a clip the tracker cannot read counts as not measured, like on the SLP page
        return None


def best_cutoff(gaps, wrong):
    """The gap above which a clip is called wrong, chosen for the best balanced accuracy on these clips."""
    gaps, wrong = np.asarray(gaps), np.asarray(wrong, dtype=bool)
    best = (0.0, None)
    for cut in np.unique(gaps):
        called = gaps > cut
        ba = (np.mean(called[wrong]) + np.mean(~called[~wrong])) / 2
        best = max(best, (ba, float(cut)))
    return best


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("zip_path", type=Path)
    p.add_argument("--per-cell", type=int, default=300, help="training clips measured per position and label")
    args = p.parse_args(argv)
    data_dir = args.zip_path.resolve().parent
    test_speakers = (data_dir / "test-speakers.txt").read_text(encoding="utf-8").split()
    out = {"per_cell": args.per_cell}
    with zipfile.ZipFile(args.zip_path) as zf, tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "clip.wav"
        clips, train_s, _, _, _, _ = index(zf, test_speakers)
        cells = {}
        for name, speaker, wrong in clips:
            w = word_of(name)
            if speaker in train_s and (w in START_WORDS or w in END_WORDS):
                cells.setdefault(("start" if w in START_WORDS else "end", wrong), []).append(name)
        rng = random.Random(2026)
        cutoffs = {}
        for position in ("start", "end"):
            gaps, wrongs, missing = [], [], 0
            for wrong in (0, 1):
                names = cells.get((position, wrong), [])
                for name in rng.sample(names, min(args.per_cell, len(names))):
                    g = gap(zf, name, position, tmp)
                    if g is None:
                        missing += 1
                        continue
                    gaps.append(g)
                    wrongs.append(wrong)
            gaps_a, wrongs_a = np.array(gaps), np.array(wrongs, dtype=bool)
            ba, cut = best_cutoff(gaps, wrongs)
            cutoffs[position] = cut
            out[position] = {"median_gap_correct": float(np.median(gaps_a[~wrongs_a])),
                             "median_gap_wrong": float(np.median(gaps_a[wrongs_a])),
                             "cutoff_hz": cut, "train_balanced_accuracy": round(float(ba), 3),
                             "measured": len(gaps), "not_measured": missing}
            print(f"{position}-r training sample: correct median {out[position]['median_gap_correct']:,.0f} Hz, "
                  f"wrong median {out[position]['median_gap_wrong']:,.0f} Hz, cutoff {cut:,.0f} Hz, "
                  f"balanced accuracy {ba:.3f}, not measured {missing}", flush=True)

        with open(data_dir / "test-set.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        tally = {}
        for row in rows:
            g = gap(zf, row["zip_path"], row["position"], tmp)
            key = (row["position"], row["listener_says"])
            t = tally.setdefault(key, {"agreed": 0, "not_measured": 0, "total": 0})
            t["total"] += 1
            if g is None:
                t["not_measured"] += 1
                continue
            t["agreed"] += (g > cutoffs[row["position"]]) == (row["listener_says"] == "wrong")
    out["test"] = {f"{k[0]}-{k[1]}": v for k, v in sorted(tally.items())}
    for k, v in out["test"].items():
        print(f"test {k}: agreed {v['agreed']} of {v['total']} (not measured {v['not_measured']})")
    agreed = sum(v["agreed"] for v in out["test"].values())
    unmeasured = sum(v["not_measured"] for v in out["test"].values())
    print(f"F3-F2 cutoff alone agreed with the listeners on {agreed} of {len(rows)} test clips "
          f"({unmeasured} could not be measured and count as not agreed).")
    out["test_agreed"], out["test_not_measured"] = agreed, unmeasured
    (data_dir / "gap-baseline.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
