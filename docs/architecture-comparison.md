# Architecture comparison: accuracy vs. what the SK-AM62B can afford (Nov 18, 2026)

Accuracy: the same 300-clip held-out test set (55 children never seen in training), `docs/arti-v2-experiment.md`.
Board: TI SK-AM62B (4x Cortex-A53, 2 GB, no accelerator), onnxruntime 1.31.1, CPU provider, 1.0 s of audio per call
(the model includes its log-mel front end). `scripts/bench_models.py`, 100 timed runs after 5 warm-ups, one model per
process. Raw logs: `data/logs/bench-board-idle.txt` (idle) and `bench-board-run2.txt` (app + language model busy).

| Model | Test agreed /300 | Weights (model body) | ONNX | Idle, 1 thread: median (p95) | Idle, 4 threads | Busy board, 1 thread | Busy, 4 threads | CPU per clip (1 thread) | Peak RAM |
|---|---|---|---|---|---|---|---|---|---|
| F3-F2 gap (acoustics only) | 214 | 0 | - | not timed | - | - | - | - | - |
| Arti v0 (CNN) | 258 | 60,706 | 0.95 MB | **20.2 ms** (20.5) | 18.4 ms (25.5) | 20.6 ms | 47.6 ms (66) | 20.1 ms | 68 MB |
| Arti v2 (BC-ResNet), seed 2028 | 267 | ~81,000 | 1.27 MB | **46.5 ms** (47.0) | 53.3 ms (73) | 47.6 ms | 108 ms (168) | 45.9 ms | 71 MB |
| Arti v2 + soft labels | 268 | ~81,000 | 1.27 MB | 46.7 ms (47.3) | 47.2 ms (68) | - | 109 ms (172) | 46.1 ms | 72 MB |
| Arti v2 + teen/adult voices | 269 | ~81,000 | 1.27 MB | 46.5 ms (46.9) | 50.2 ms (79) | - | 99.6 ms (155) | 45.9 ms | 71 MB |

The ONNX files also hold ~168,500 constants for the log-mel front end (DFT + filterbank), so the raw initializer count is
229,199 (v0) and 249,670 (v2); the "model body" column is the trained network.

## What the hardware taught us
- **Every model fits easily**: under 50 ms per clip and under 75 MB, against a 2 GB board and a child who takes ~1 s per
  word. The board's limit is not Arti; it is the on-board language model (4.6 tokens/s) and the browser.
- **One thread beats four on this board.** With 4 threads the A53 spends more CPU on coordination (v2: 158 ms of CPU
  for a 53 ms answer) and the tail grows (p95 73 ms vs 47 ms). On a busy board (language model + child view running)
  4 threads more than double the latency (108 ms vs 47.6 ms) while 1 thread is unaffected. Decision: run Arti on 1 thread.
- **v2 costs 2.3x the compute of v0 for +9 test clips** (258 -> 267); soft labels add no cost and make the unsure band
  honest (sends 18.7% of validation clips to the SLP, 92% right on the rest). Both are still ~20x faster than real time.

## Power (measured on the board's own INA power monitors)
The SK-AM62B has TI INA power monitors on the AM62x rails (SPRUJ40F Table 2-19: VDD_CORE 0x40, VDDR_CORE 0x41,
3.3 V I/O 0x4C, 1.8 V I/O 0x45, 1.8 V analog 0x4D, DDR4 0x47, all 10 mOhm). `scripts/soc_power.py` samples them at
~17 Hz while a model runs continuously (child view + browser on in all rows). SoC rails only, not the whole board.

| Load | SoC power | Core | DDR | Latency | Extra energy per clip (over idle) |
|---|---|---|---|---|---|
| Idle (app on, waiting) | 1.10 W | 0.75 W | 0.08 W | - | - |
| v0, 1 thread | 1.30 W | 0.89 W | 0.14 W | 20.3 ms | **4 mJ** |
| v2, 1 thread | 1.32 W | 0.89 W | 0.17 W | 48.5 ms | **11 mJ** |
| v2 soft labels, 1 thread | 1.32 W | 0.89 W | 0.17 W | 48.5 ms | **11 mJ** |
| v2, 4 threads | 1.48 W | 1.05 W | 0.16 W | 50.3 ms | **19 mJ** |

- Running Arti adds only ~0.2 W to the SoC; a 20-word session costs ~0.2 J of extra energy with v2 on 1 thread.
- **4 threads cost 1.7x the energy per clip of 1 thread for no speed gain** (and are 2x slower on a busy board):
  the hardware argument for 1 thread.

## Confidence, not just accuracy (validation clips, `docs/arti-v2-experiment.md`)
How well each model knows when it is unsure: share of clips inside a +/-0.2 "unsure" band (sent to the SLP) and
balanced accuracy on the clips it keeps.

| Model | Sent to the SLP | Right on the rest |
|---|---|---|
| v0 CNN | 13.4% | 90.4% |
| v2, hard labels (seed 2028) | 4.6% | 87.6% (over-confident: sure even when wrong) |
| **v2, soft labels** | **18.7%** | **92.3%** |

The soft-label v2 is the model whose confidence means something: trained on the clips listeners disagreed on (as the
listeners' share), it is unsure where people are unsure, so the SLP reviews the right clips. Same size, speed and
power as v2, +1 test clip (268).

## Pick
**v2 with soft labels, 1 thread**: best test score of the children-only models after adults (268/300), honest
confidence for the SLP review band, 48 ms and 11 mJ per clip, 72 MB.

## Stage experiments (Nov 18 night)
Three changes to v2, each trained once at seed 2028 on the laptop GPU and scored on the same 300-clip test set. The
"+/-0.2 band" columns are validation clips. Board: SK-AM62B idle, `bench_models.py`, 100 runs, 1 thread. Logs:
`data/logs/30-33*.txt`, `bench-board-hop80.txt`, `bench-board-pos.txt`. Scripts: `scripts/experiment_arti_hop.py`,
`experiment_arti_position.py`, `experiment_arti_hybrid.py`.

| Model | Test /300 | Wrong r caught | Correct r passed | Val bal acc | +/-0.2: sent to SLP / acc on rest | Board ms, 1 thread | ONNX MB |
|---|---|---|---|---|---|---|---|
| v2, seed 2028 (baseline) | 267 | 128 / 150 | 139 / 150 | 0.863 | 4.6% / 87.6% | 46.5 | 1.27 |
| v2 soft labels (baseline) | 268 | 125 / 150 | 143 / 150 | 0.869 | 18.7% / 92.3% | 46.7 | 1.27 |
| 1. v2, 5 ms hop (296 frames) | 262 | 122 / 150 | 140 / 150 | 0.855 | 12.4% / 89.6% | 95.5 (4 threads 103) | 1.27 |
| 2. v2 + r-position head (lambda 0.3) | 268 | 124 / 150 | 144 / 150 | 0.871 | 8.6% / 89.6% | 46.6 (4 threads 47.4) | 1.27 |
| 3a. v2 on 25% of training clips | 243 (237 of 292 measurable) | 106 / 150 | 137 / 150 | 0.818 | 21.2% / 87.0% | - | - |
| 3b. v2 + F3-F2 gap, same 25% | 247 (241 of 292 measurable) | 113 / 150 | 134 / 150 | 0.804 | 12.0% / 83.7% | not timed* | 1.27 |

\* The gap is a second ONNX input measured outside the model (`speakup/acoustics.py`, ~0.2 s per clip on the laptop),
so the network's cost is v2's. Measuring all 42k training clips would have taken ~90 min, so 3a/3b train on a
stratified 25% of each (position, label) cell (8,343 clips) and validate on all 8,984 val clips; 8 of 300 test clips
have no measurable gap and get a "not measured" flag.

- **Finer time grid (1): no gain, twice the cost.** 262 vs 267 is inside the ~9-clip seed spread, but it is not
  better on any column and the board time doubles (95.5 ms vs 46.5 ms). The 10 ms hop already resolves the r.
- **Position head (2): same score, free.** 268 vs 267 is noise; best validation of the hard-label runs (0.871) and a
  slightly less over-confident band (sends 8.6% vs 4.6%) but nowhere near soft labels' honest 18.7% / 92.3%. No cost
  on the board, since only the main head is exported. Worth combining with soft labels, not a reason to switch.
- **F3-F2 gap as input (3): not shown to help.** +4 test clips over v2 trained on the same subset (247 vs 243; 241 vs
  237 on measurable clips), all within noise, with *lower* validation (0.804 vs 0.818) and a worse band. The network
  already hears what the gap measures, and the gap costs ~0.2 s of CPU per clip. Single runs: differences under ~9
  test clips are not significant, and even a fixed seed is not bit-identical on the GPU (3a's val moved 0.813 to
  0.818 between two runs).

## Stage evidence tests (Nov 18)
Binary accuracy on 300 clear clips cannot show the gains the 5-stage pipeline argues for (the /r/ cue is a slow F3
drop, so a better-sampled input or a deeper encoder adds little to a yes/no call). These three tests measure where
stages 3-5 should show up instead. Laptop GPU, same speaker split (train / val / test children never overlap), same
300-clip test set. Logs: `data/logs/34*-36*.txt`. Scripts: `scripts/experiment_arti_adapt.py`,
`experiment_arti_curve.py`, `eval_arti_graded.py`.

**Stage 3, graded output: does P(correct) track the share of listeners who heard a correct r?** The 300 test clips
are all clear (share 0-0.25 or 0.75-1), so the same models also ran on every labelled clip of the 55 test children
(21,591 clips, 24% unclear) and of the 12 validation children (12,522, 28% unclear). Existing ONNX files, no retraining.

| Model | 300 test: Spearman / Pearson / MAE | All test-children clips | All val-children clips |
|---|---|---|---|
| v0 CNN | 0.636 / 0.748 / 0.189 | 0.593 / 0.634 / 0.239 | 0.591 / 0.626 / 0.221 |
| v2 hard, seed 2028 | 0.734 / 0.805 / 0.159 | 0.595 / 0.630 / 0.237 | 0.610 / 0.645 / 0.217 |
| **v2 soft labels** | **0.747 / 0.827 / 0.156** | **0.624 / 0.676 / 0.208** | **0.684 / 0.698 / 0.187** |

Reliability, all test-children clips (P(correct) bin: clips, mean listener share):

| Model | 0-0.2 | 0.2-0.4 | 0.4-0.6 | 0.6-0.8 | 0.8-1 |
|---|---|---|---|---|---|
| v0 | 10,649: 0.18 | 1,639: 0.26 | 1,142: 0.31 | 1,282: 0.39 | 6,879: 0.68 |
| v2 hard | 13,028: 0.20 | 790: 0.36 | 590: 0.41 | 644: 0.44 | 6,539: 0.69 |
| v2 soft | 9,326: 0.16 | 3,321: 0.28 | 2,081: 0.38 | 2,036: 0.53 | 4,827: 0.75 |

**Stage 4, multi-loss: does the r-position head help more with less data?** v2 soft labels (a) without and (b) with
the position head (lambda 0.3), trained on 10/25/50/100% of each training (position, label) cell (unclear clips are
their own cell); a and b see the same clips, the seed changes training only. Columns: test /300, val balanced
accuracy, +/-0.2 band on val (sent to SLP / balanced accuracy on the rest).

| Training clips | Seed | (a) soft | (b) soft + position head | b - a, test |
|---|---|---|---|---|
| 10% (4,208) | 2028 | 252, 0.814, 22.5% / 87.6% | 258, 0.813, 21.1% / 87.1% | +6 |
| 10% | 2029 | 247, 0.811, 17.7% / 85.8% | 253, 0.802, 16.0% / 84.4% | +6 |
| 25% (10,518) | 2028 | 251, 0.828, 25.8% / 89.4% | 261, 0.836, 18.5% / 89.0% | +10 |
| 25% | 2029 | 252, 0.837, 29.0% / 91.4% | 264, 0.818, 17.5% / 87.5% | +12 |
| 50% (21,035) | 2028 | 264, 0.847, 15.7% / 89.2% | 263, 0.867, 16.7% / 91.9% | -1 |
| 100% (42,066) | 2028 | 268, 0.869, 18.7% / 92.3% (Nov 17)* | **270, 0.883, 20.4% / 93.9%** | +2 |

\* Retrained tonight as the adaptation base: val 0.873, 19.4% / 93.0%; its test score was lost (the ONNX export
crashed on a console-encoding error after the weights were saved).

**Stage 5, per-child adaptation: does fine-tuning on K of one child's clips help on that child's other clips?** Base:
the soft-label v2 above. Children: the first 20 (by ID) of the 29 test children with >= 40 labelled clips and >= 10
clear clips of each kind (93 to 2,585 clips each); never trained or validated on. Fine-tune the last BC block, final
conv stack and head (class-balanced soft cross-entropy, BatchNorm frozen, Adam, 30 full-batch steps); lr 3e-4 picked
on the 8 eligible validation children from 1e-4 / 3e-4 / 1e-3. K clips drawn stratified by heard correct / wrong, 3
draws per child per K; scored on the child's remaining clips (balanced accuracy on clear ones, Spearman with the
listener share on all). Mean +/- SD across the 20 children.

| K | Balanced accuracy, base (same clips) | Adapted | Spearman, base | Adapted |
|---|---|---|---|---|
| 0 | 0.768 +/- 0.126 | - | 0.475 +/- 0.226 | - |
| 5 | 0.768 +/- 0.126 | 0.754 +/- 0.123 | 0.475 +/- 0.223 | 0.468 +/- 0.236 |
| 10 | 0.768 +/- 0.126 | 0.771 +/- 0.110 | 0.475 +/- 0.226 | 0.475 +/- 0.232 |
| 20 | 0.768 +/- 0.125 | 0.773 +/- 0.115 | 0.475 +/- 0.225 | 0.477 +/- 0.239 |

- **Stage 3 has the clearest evidence.** Soft labels make the output graded: on unseen children's clips, including
  the unclear ones, Spearman rises 0.59-0.61 -> 0.62-0.68 and the mean error falls ~0.03, and the soft model's bins
  climb steadily (0.16 -> 0.75 listener share) where the hard model puts 60% of clips in the bottom bin. Still
  over-confident at both ends (says 0.93 where listeners say 0.75). On the 300 clear clips v2 hard and soft are close
  (0.734 vs 0.747); the gain shows on the unclear clips binary accuracy never scores.
- **Stage 4 is suggestive, not shown.** The position head added 6 to 12 test clips in all four low-data runs (10%
  and 25%) and ~0 at 50% and 100%, the pattern theory predicts. But validation, which picks models, does not agree
  (b - a = -0.019 to +0.008 at 10-25%), single 300-clip differences under ~9 are within seed noise, and only two seeds
  were run. The full-data soft + position run is the best single model so far (270, val 0.883, band 20.4% / 93.9%)
  but by +2 test clips. Worth more seeds before claiming it.
- **Stage 5 is a null result at this size.** Averaged over 20 children, K = 5 hurts (-0.014) and K = 10-20 are flat
  (+0.002, +0.005), far inside the 0.12 spread between children. Per child it is mixed (K = 20 helps 11 of 20):
  children the base model handles badly (46: 0.52 -> 0.64; 98: 0.49 -> 0.57) gain, strong ones lose a little. A
  child's few clips are mostly the same few words, so this tests word adaptation as much as voice adaptation.
- **Caveats.** One adaptation recipe (lr chosen on 8 val children, no layer or step sweep); per-child Spearman is
  lower than pooled because one child's clips span a narrower range; val clips also chose the training epoch, so
  the test-children columns are the clean ones for stage 3.
