---
glass: hackedge-2026
status: in-progress
last_worked_on: 2026-11-15
next_action: "#9"
blocked_on: ""
phase: ""
---

# Hackedge-2026 — Project State

Speak Up, the team's HackEdge 2026 entry: an offline r-sound speech screener on a TI SK-AM62B board. Python 3 with numpy. Visibility: Private.

*Thin snapshot. `next_action` above names the ticket that is up now — start there.
Archive: `docs/HISTORY.md`. Queue: GitHub Issues (`gh issue list`). Protocol: `AGENTS.md`.*

## Now

- Raf has the board and runs every board step below; the owner cannot reach it.
- #9 is on main but stays open: the board run (llama.cpp built and run on the AM62x, the note on the board's end screen, the real time for the 120 s guess); steps in `docs/model-timing.md`.
- #21 is on main but stays open: the phrase and sentence check through Arti on the board, the board's `bank:` timing lines into `docs/model-timing.md`, and `python3 -m unittest` on the board (plan steps 2 to 4).
- Round 3 (#37, #38, #39, #40, #45) and the fixes after it (#49 to #61, #73, #77, #78) are on main. The "## Board steps" of PRs #41, #42, #43, #44, #46 and of the fix PRs #64, #65, #67, #68, #69, #70, #74, #75, #76, #80, #81 are still to run. #22 waits on those board runs.
- PR #81's board step 2 is corrected in `docs/HISTORY.md` (#77): kill one worker by a PID from `pgrep -P <server pid>`, not with `pkill -9 -f multiprocessing`.

## Run / verify

- `python3 -m unittest` — every test in `tests/`. The app and the tests need a python3 that has numpy. The board has numpy preinstalled; on the owner's Mac, Homebrew's python3 has none, so use `/usr/local/bin/python3`

## Gotchas

- The board: setup, connectors and every pitfall hit so far (Etcher, serial paste, HDMI mode, mic level, wrong clock) are in `docs/board-setup.md`.

- Under `--replay`, starting a practice or a screening puts every word back at its first clip, for the other one too (#73, by design). A practice run during a rehearsal rewinds the screening's clip order, so tell the team first.

- On the board, run `python3 -m speakup --arecord --device <dev> --arti models/arti-v2-soft.onnx`; the default ALSA device may be the onboard codec, not the USB mic. The board check is #13.
