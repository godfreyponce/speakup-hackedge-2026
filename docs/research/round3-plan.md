# Round 3: the plan for Nov 20

Final demo **Fri Nov 20, 2026**. Code freeze on the board **Wed Nov 18**. Judging: innovation 25%,
technical 20%, edge AI 20%, demo 15%, presentation 10%, impact 10%. Demo script:
[../round3-demo-script.md](../round3-demo-script.md).

## Model

- **Arti v2:** BC-ResNet (about 110K parameters), 64 mel bands up to 8 kHz, pre-emphasis,
  attention pooling, distilled from a larger phonetic model. Done when it matches or beats v0 on
  the same 300-clip test set ([../test-set.md](../test-set.md)) and its board time is measured.
- **Keep FP32 on the board.** The AM62x's Cortex-A53 has no dot-product (SDOT) instructions, so
  int8 is not faster there.
- **Adult voices:** pitch-gated voice normalization and an adult training mix. Done when all three
  team voices score "red" and "wed" correctly on the board.
- **Calibration** and "Unsure, SLP please listen" ([fairness-and-wording.md](fairness-and-wording.md)).
- **F3–F2 reading:** pre-emphasis, voiced frames only, formant bounds.
- **/s/ check:** spectral variance for the lisp, mid-frequency peak for /s/–"sh" ([s-sound.md](s-sound.md)).
- Error-type outputs (gliding, derhotacized, lisp types) wait for labelled data.

## By date

| Date | Work |
|---|---|
| Fri Nov 13 | Measure the language model's speed on the board (Qwen2.5-0.5B vs Qwen3-0.6B vs SmolLM2-360M). Order a cardioid headset mic and a USB-C power meter. |
| Sat–Sun Nov 14–15 | Arti v2; voice normalization tested on the team's voices; calibration; F3–F2 fix and the /s/ check; SLP view on a laptop or iPad with one-key overrides. |
| Mon Nov 16 | Lexi approves the word list (word-initial scoring only). SLP note and Spanish family note, grammar-checked. |
| Tue Nov 17 | Dialect rule filter and per-accent false-alarm rates. Telemetry banner (ms, RAM, watts) and the replay-real-clips backup. Optional: camera tie-breaker, 8-hour cap. |
| Wed Nov 18 | **Freeze.** Everything tested on the board. Rehearse the demo twice. |
| Thu Nov 19 | Final rehearsal; slides use only measured numbers. Pack the board, mic, power meter, cables and a laptop with demo mode. |
| Fri Nov 20 | Test adult voices and the mic in the room before judging. Demo. |

## Optional: camera tie-breaker

A Pi 5 with a Hailo AI accelerator reading mouth landmarks. A camera sees lip rounding and a
frontal lisp, not a lateral lisp or the tongue shape of /r/. Only if the rest is on track, 8 hours
at most, and frames are never stored.

## After Nov 20

- A clean CC BY-only model (JIBO Kids, Speechocean762) that can be shared.
- Error-type outputs, then a phone recognizer that finds sounds inside sentences, then more sounds.
- A faculty lead and an IRB: adult volunteers first, then children ([recruiting.md](recruiting.md)).
- One-chip hardware: TI AM62A (2 TOPS accelerator) for audio and camera; an XMOS microphone array
  for noisy rooms.
- Remove `arti-v0.onnx` from git history (#25).
- NSF I-Corps at UTD; check student IP ownership with UTD's Office of Technology Commercialization.
