# Arti v2 experiment (Nov 17, 2026)

Laptop only (RTX 2000 Ada), nothing deployed. `scripts/experiment_arti_v2.py` on `PERCEPT-R 2.2.2py`, the same
speaker split (seed 2026: 106 train, 12 validate, 55 test) and the same 300-clip test set as `arti-v0`. The test
set rebuilt on this machine is identical to the one v0 was scored on (checked against Godfrey's `test-set.csv`
and `test-speakers.txt`). Models are chosen on validation clips, never on the test set.

## Results

| run | body | trained on | val balanced accuracy | test: agreed of 300 | wrong r caught | correct r passed |
|---|---|---|---|---|---|---|
| v0 (Nov 3, Godfrey) | CNN, 60,706 params | children | 0.844 | 258 | 119 / 150 | 139 / 150 |
| v0 again, this machine | CNN | children | 0.858 | 259 | 120 / 150 | 139 / 150 |
| v2, seed 2026 | BC-ResNet | children | 0.847 | 261 | 119 / 150 | 142 / 150 |
| v2, seed 2027 | BC-ResNet | children | 0.856 | 258 | not kept* | not kept* |
| v2, seed 2028 | BC-ResNet | children | **0.863** | **267** | 128 / 150 | 139 / 150 |
| v2, seed 2028, soft labels | BC-ResNet | children, + 8,700 unclear clips | 0.869 | 268 | 125 / 150 | 143 / 150 |
| v2, seed 2026, `--adults` | BC-ResNet | children + teens + adults | 0.857 | 269 | 127 / 150 | 142 / 150 |
| v2, `--train-position start` | BC-ResNet | start-r words only | 0.890 (start-r val only) | 218 | 127 / 150 | 91 / 150 |
| F3-F2 gap alone (`scripts/gap_baseline.py`) | no model | cutoff from 600 training clips | 0.757 / 0.764 (sample) | 214 | 114 / 150 | 100 / 150 |

\* A duplicate restart overwrote seed 2027's log; its total (258) is from the run's status line.

- **Run-to-run spread is about 1 to 9 clips.** Retraining v0 unchanged moved it from 258 to 259; v2's three seeds
  gave 258, 261 and 267. One run is not evidence; the mean of v2's seeds is 262 against v0's 258 to 259.
- **The validation pick is v2 seed 2028** (best validation, 0.863), which scores 267 of 300: it passes the
  ship gate's first condition (259 or more). The other two conditions are still open: the adult red/wed test and
  timing on the board.
- **Adding teen and adult speakers** scored 269, the highest, but its validation (0.857) is below seed 2028's, so
  by the rule it is not the pick. It is the candidate for the adult red/wed test, the reason it was trained.
- **Position hold-out:** trained only on words with r at the start, it still caught wrong end-r sounds (64 of 75)
  but called most correct end-r sounds wrong (24 of 75 passed). It learned what a good start r sounds like, not
  the r in general. Train on both positions, and test new positions before claiming them.
- **Physics alone:** the F3-F2 gap with one cutoff per position agrees on 214 of 300 (8 clips not measurable).
  Arti adds about 45 to 55 clips over the measurement it is usually explained with. The gap's medians are now the
  evidence line on the SLP card (PR "SLP card: measured F3-F2 gap").

- **Soft labels** (`scripts/experiment_arti_soft.py`): the training speakers' 8,700 clips that listeners
  disagreed on, each trained toward its listener share instead of dropped. The test score barely moves (268 vs
  267, inside the seed spread), but the model's confidence becomes honest: with a ±0.2 band it sends 18.7% of
  validation clips to the SLP and is right on 92.3% of the rest, where the same body trained on clear clips only
  sends 4.6% and is right on 87.6%. The hard-label model is sure even when it is wrong; the soft one knows when
  to ask. This is the case for soft labels: a usable "SLP, please listen" output, not a higher score.

## Unsure band (validation clips, v0 again)

| band around 0.5 | share sent to the SLP | balanced accuracy on the rest |
|---|---|---|
| none | 0% | 0.858 |
| ±0.1 | 6.4% | 0.880 |
| ±0.2 | 13.4% | 0.904 |
| ±0.3 | 22.9% | 0.926 |

Soft-label v2 (seed 2028), for comparison: ±0.1 sends 8.8% (0.902 on the rest), ±0.2 sends 18.7% (0.923),
±0.3 sends 32.1% (0.947).

`speakup/calibration.py` still has `UNSURE_BAND = None`; set it by hand after the board test, from this table for
the model that ships.

## Rebuild

From this worktree, with the corpus in `data/percept-r/` (never committed):

```bash
python -I scripts/pick_test_set.py data/percept-r/PERCEPT-R.zip
python -I scripts/experiment_arti_v2.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-s2028.onnx
python -I scripts/experiment_arti_v2.py data/percept-r/PERCEPT-R.zip --adults --out models/arti-v2-adults.onnx
python -I scripts/experiment_arti_soft.py data/percept-r/PERCEPT-R.zip --seed 2028 --out models/arti-v2-soft.onnx
```

Other rows: `--v0-body`, `--seed 2026|2027`, `--train-position start`. Each run takes about 16 minutes on the
laptop GPU after the feature cache is built (about 4 minutes; 6 workers at below-normal priority).
