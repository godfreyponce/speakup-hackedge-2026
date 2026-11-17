# Speak Up: Round 3 demo script (draft for the team to edit)

Background for every claim below: [research/](research/README.md).

Final demo: **Friday, November 20, 2026.** Target length: 4 minutes. Three speakers: Rafael (tech), Godfrey (app + language model), Lexi (clinical).

## Before you start (setup checklist)
- [ ] SK-AM62B on, app running on the HDMI monitor (kid view).
- [ ] SLP view open on a laptop or iPad connected to the board over the local network.
- [ ] **Headset or gooseneck USB mic** (cardioid) plugged in. Hold-to-speak key ready as a backup.
- [ ] Inline USB-C power meter between the power supply and the board.
- [ ] Internet cable visibly unplugged from the board.
- [ ] "Replay real clips" backup mode tested: 6 de-identified clips (correct /r/, glided /r/, interdental /s/, Spanish tapped r, plus 2 spares).
- [ ] Adult-voice handling on (voice normalization), tested on all three team voices that morning.
- [ ] Printed Speak Up case on the board.
- [ ] Only numbers we measured ourselves on the board appear on screen or slides.

## 0:00–0:40, The problem and the promise (Lexi)
"A school speech therapist (SLP) in Texas carries about 50 students. Screening every child takes hours, and children who speak Spanish at home, or African American English, are too often flagged for errors that are really just normal dialect.

Speak Up is a small device that helps the SLP screen faster and more fairly. A child says a few words; an AI model on this board points out sounds that might need a closer look; the SLP always makes the call."

(Rafael points at the board.) "Everything runs here, on a Texas Instruments board drawing about [measured] watts, with the internet unplugged. A child's voice never leaves the room."

## 0:40–2:00, Live test with a judge (Rafael)
Hand the headset to a judge.
1. "Please say *red*." → the kid screen gives stars (always the same praise, never a score). The SLP screen shows **correct**, the F3–F2 gap in the target zone, and the model's time in milliseconds.
2. "Now say it like a little kid who can't say r yet: *wed*." → the SLP screen flags **possible gliding**, with the evidence (F3 stayed high). If the camera tie-breaker is built, show the lip-rounding gauge too.
3. (If /s/ is ready) "Say *sun* with a lisp, *thun*." → the /s/ check (spectral variance, see [research/s-sound.md](research/s-sound.md)) leaves the green zone and the call is flagged.

Say: "It worked on an adult voice. Our first model only knew children's voices, and we fixed that by normalizing the voice before the model hears it."

## 2:00–2:50, Fairness (Lexi)
"An accent is not a disorder. Speak Up only scores sounds where every dialect agrees, like the r at the start of *red*, and a rule filter marks known dialect patterns as 'may be a dialect difference, please check' instead of errors."

Show: a Spanish-tapped r or an African American English *star* → **not flagged as an error**, while *wed* for *red* is still flagged.
(If measured) show the false-alarm rate per accent group, before and after the filter.

## 2:50–3:45, The on-board language model at work (Godfrey)
Click **End screening** on the SLP view.
- The small language model on the board writes the SLP's screening note, plus a short **Spanish/English practice note for the family**.
- A green check shows every number in the note was verified by code. The model never does math or diagnoses.
- (If built) type a goal like "six starting-r words, animals" → the model turns it into a checked practice plan.

## 3:45–4:00, The SLP decides, and where it goes next (Lexi + Rafael)
Lexi overrides one call with one key: "The therapist is always in charge."
Rafael: "Next, everything here, including the camera, fits on one TI AM62A chip with a built-in AI accelerator. We're talking with researchers at UT Dallas and across the country to grow from one sound to many."

## If something breaks
- **Mic or noise problem:** switch to hold-to-speak; if it still fails, switch to replay mode (real clips, still scored live on the board).
- **Language model slow:** show the saved startup bank of practice lines; mention the measured speed honestly.
- **Board crash:** the laptop runs the same app in demo mode (`python -m speakup --demo`); say so plainly.

## Lines to never say
- "diagnoses", "detects disorders", "replaces the therapist"
- Any number we did not measure ourselves
