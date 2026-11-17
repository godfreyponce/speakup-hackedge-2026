# Arti masking experiment (#19)

Run on Nov 10, 2026, with `scripts/experiment_arti.py`. Validation speakers only. Nothing is deployed.

## Question

Does light time masking or frequency masking of the log-mel input during training raise Arti's
validation balanced accuracy, with everything else fixed?

## Setup

- Fixed, as in `scripts/train_arti.py` (see "How Arti was trained" in `docs/model-timing.md`):
  the 40-bin log-mel frontend, 4 conv blocks (60,706 parameters), 20 epochs, Adam at 0.001,
  batch 256, class-weighted cross-entropy, threshold 0.5, and the speaker split with seed 2026.
  That split is 106 training speakers (33,366 clips) and 12 validation speakers (8,984 clips:
  2,019 correct, 6,965 wrong). The experiment did not use the 55 held-out test speakers.
- Each run keeps the epoch with the best validation balanced accuracy, the same rule as
  `train_arti.py`.
- Time mask: one band per training clip, width drawn uniformly from 0 to 5 frames (0 to 50 ms),
  across all 40 mel bins.
- Frequency mask: one band per training clip, width drawn uniformly from 0 to 2 mel bins, across
  all frames.
- Fill: the clip's mean log-mel value, from the unmasked float32 batch. Masks touch training
  batches only. The cached features, the validation clips, and `models/arti-v0.onnx` do not
  change.
- Training seeds 2026, 2027 and 2028. Each seed gives three separate seeds through
  `numpy.random.SeedSequence(seed).generate_state(3)`: weight init, minibatch order, and mask.
  So for one training seed, all three methods start from the same weights and see the same
  example order.
- Device: MPS (Apple M3 Pro), torch 2.15.0.

## Runs

| method | seed | best epoch | balanced accuracy | missed errors | false alarms | train seconds |
|---|---|---|---|---|---|---|
| baseline | 2026 | 10 | 0.8533 | 739 | 378 | 157 |
| time | 2026 | 20 | 0.8666 | 1047 | 235 | 151 |
| frequency | 2026 | 17 | 0.8565 | 595 | 407 | 146 |
| baseline | 2027 | 18 | 0.8562 | 1338 | 193 | 149 |
| time | 2027 | 20 | 0.8633 | 718 | 344 | 157 |
| frequency | 2027 | 17 | 0.8682 | 646 | 345 | 144 |
| baseline | 2028 | 14 | 0.8574 | 651 | 387 | 146 |
| time | 2028 | 18 | 0.8613 | 900 | 299 | 147 |
| frequency | 2028 | 12 | 0.8645 | 745 | 331 | 160 |

A missed error is a clip the listener heard as wrong that the model called correct (out of
6,965). A false alarm is a clip the listener heard as correct that the model called wrong (out
of 2,019).

## Result

Ranked by mean validation balanced accuracy over the three seeds.

| rank | method | mean | sd | min | max | paired difference vs baseline (2026, 2027, 2028) |
|---|---|---|---|---|---|---|
| 1 | time | 0.8638 | 0.0027 | 0.8613 | 0.8666 | +0.0133, +0.0071, +0.0039 |
| 2 | frequency | 0.8631 | 0.0060 | 0.8565 | 0.8682 | +0.0032, +0.0120, +0.0071 |
| 3 | baseline | 0.8556 | 0.0021 | 0.8533 | 0.8574 | 0 |

## Decision

The time mask ranks first, with a mean 0.0082 above baseline. It is the selected candidate for
the follow-up checks.

- The gain over baseline is larger than the seed spread. Every time-mask run (lowest 0.8613) and
  every frequency-mask run but one (lowest 0.8565) is above the best baseline run (0.8574).
- All 3 paired differences are positive for both masks.
- Time and frequency differ by 0.0007 in the mean, which is smaller than the spread of either
  across seeds. This experiment does not show that one mask is better than the other. The
  ranking picks time only because its mean is higher, the rule the ticket set.
- Nothing is deployed. Held-out scoring on the 300 test clips, ONNX export of the selected run,
  live-mic checks and board timing are follow-ups.

## Limitations

- 3 seeds and 12 validation speakers. A different set of validation speakers could give a
  different order.
- Validation picks both the best epoch and the method, so these numbers are optimistic. They are
  not a test score.
- The time mask kept epoch 20, the last one, for 2 of 3 seeds. It may still have been improving.
  The ticket fixed the training length.
- Missed errors and false alarms move a lot between seeds at the fixed 0.5 threshold (for
  example, baseline missed 651 to 1,338). Balanced accuracy is steadier than either count.
- MPS float math is not guaranteed to repeat exactly on a rerun. On CPU, a run repeats
  exactly (`tests/test_arti_experiment.py`).
- The fill mean includes the silence padding of short clips (log of 1e-6), so their fill is
  lower than the mean of their speech. This is the ticket's rule.
- The baseline here is not the Nov 3 model. That model used seed 2026 directly for init and
  the global generator for order; here each training seed is split into three seeds.
- The experiment did not use the test set. The old 258 of 300 (259 of 300 in the first build) is historical
  evidence only.

## Rerun

From the repo root, on the laptop:

```bash
uv run --managed-python --python 3.12 --with torch --with torchaudio --with onnx --with onnxscript --with onnxruntime --with numpy python -I scripts/experiment_arti.py data/percept-r/PERCEPT-R.zip
```

- It reads `PERCEPT-R.zip`, `test-speakers.txt` and the mel cache in `arti-cache/`, all in the
  zip's folder. It never reads `test-set.csv`, never scores the test clips, and never exports a
  model.
- Outputs go to `arti-masking/` beside the zip: `results.json` (every run, then the ranking once
  all 9 are done) and `<method>-seed<N>.pt`, the best-epoch weights of each run. These are in
  `data/`, which is gitignored.
- `--out-dir <folder>` writes somewhere else. `--device cpu` gives a run that repeats exactly
  (slower than MPS).
- A rerun replaces `results.json` and the `.pt` files. If a rerun stops early, the folder holds
  the new `results.json` with only the finished runs, plus `.pt` files from the earlier run for
  the runs not redone. Use only the `.pt` files that `results.json` lists.
- The 9 runs took about 23 minutes on MPS, about 150 s each.
