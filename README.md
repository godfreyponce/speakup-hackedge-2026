# Speak Up | HackEdge 2026

An offline speech screening aid for school speech-language pathologists (SLPs), running on a Texas Instruments
SK-AM62B. A child says short words with the /r/ sound; a small on-device model (Arti) judges each r; the SLP checks
every call and gets a tally plus a short note written by a language model on the same board. No network, no cloud,
and no audio leaves the board. It **screens and monitors; it never diagnoses**, and the SLP makes every decision.

UTD HackEdge 2026 (UT Dallas ECE and Texas Instruments), Track 3: Edge AI Assistant.
Report: [Speak Up report](https://cometmail-my.sharepoint.com/:w:/g/personal/gvp240000_utdallas_edu/cQqkwAIWWNOOSqpLiowiF3fUEgUCEr9cKd_L1bGeyGrhbyVSNg).

## Team

- Godfrey Ponce (computer science)
- Rafael Amador (computer engineering)
- Alexis "Lexi" Marsh (Speech, Language & Hearing Science and Child Development)

## Contents

1. [Quick start: try it on a laptop in 2 minutes](#quick-start-laptop-no-model-needed)
2. [Dependencies](#dependencies)
3. [Run on the SK-AM62B board](#run-on-the-sk-am62b-board)
4. [Models: where they come from and why they are not in this repo](#models)
5. [Tests](#tests)
6. [What is where](#what-is-where)
7. [Results](#results)
8. [Data and privacy rules](#data-and-privacy-rules)

## Quick start (laptop, no model needed)

Demo mode answers from a fixed script instead of the model and the microphone, so it runs anywhere with Python.

```bash
git clone https://github.com/godfreyponce/speakup-hackedge-2026.git
cd speakup-hackedge-2026
python3 -m pip install numpy
python3 -m speakup --demo
```

Then open in a browser:

| Page | What it is |
|---|---|
| http://localhost:8000/ | The SLP view: start a session, see each call, agree or disagree (keys A, D, L to listen again) |
| http://localhost:8000/kid | The child view: the buddy, the word and its picture (on the board this is the HDMI screen) |
| http://localhost:8000/sessions | Finished sessions |

Enter an age of 8 years or more so every scripted error is flagged. To try the sound analysis (formants, the F3-F2
gap) on a real recording instead of the script, use `python3 -m speakup --sample-clip path/to/word.wav`.

## Dependencies

| Where | What | Why |
|---|---|---|
| Laptop and board | Python 3.12 or newer (the board image ships 3.14) | The app (standard library web server, no framework) |
| Laptop and board | `numpy` | Sound analysis |
| Board (or laptop with a model) | `onnxruntime` | Runs Arti, the r-sound model |
| Board | `arecord` (ALSA, in the TI image) | Records from the USB microphone |
| Board, optional | [llama.cpp](https://github.com/ggml-org/llama.cpp) `llama-completion`, built on the board | The end-of-session note (Qwen2.5-0.5B-Instruct, 4-bit) |
| Training only (laptop with a GPU) | `torch`, `torchaudio`, `onnx`, `onnxscript` | Training and exporting Arti; not needed to run the app |

Without onnxruntime the app still runs in demo mode; without llama.cpp the end screen shows the tally only.

## Run on the SK-AM62B board

### Hardware

| Item | Notes |
|---|---|
| TI SK-AM62B | AM62x: 4 Arm Cortex-A53 cores, 2 GB RAM, no AI accelerator |
| microSD card, 32 GB or more | TI Processor SDK Linux AM62x 12.01.00.05.03 image |
| USB-C power supply, 5 V / 3 A | Into J11 |
| USB microphone | We use an Audio-Technica ATR2100-USB, on a powered USB hub |
| Ethernet cable | Laptop to board, direct (the SLP view is opened from the laptop) |
| HDMI monitor | The child view |

### Setup

Flashing the card, the serial console, the network, SSH, the microphone and the monitor are step by step in
**[docs/board-setup.md](docs/board-setup.md)**, including the problems we hit and their fixes.

On the board, check the Python modules (all are in the TI image):

```bash
python3 -c "import onnxruntime, numpy, sqlite3"
```

Copy the app and the model from the laptop (see [Models](#models) for the model file):

```bash
ssh <board> mkdir -p speakup-app/models
scp -r speakup scripts <board>:speakup-app/
scp models/arti-v0.onnx <board>:speakup-app/models/
```

Optional, for the end-of-session note: build llama.cpp on the board and download the Qwen model, as in
[docs/model-timing.md, "llama.cpp and the end screen's note"](docs/model-timing.md#llamacpp-and-the-end-screens-note-9).

### Run

```bash
cd speakup-app
python3 -m speakup --arecord --device plughw:0,0 --arti models/arti-v0.onnx \
    --llm-bin ~/llama.cpp/build/bin/llama-completion --llm-model models/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

- `--device`: the microphone's ALSA device (`arecord -l` lists them; ours is `plughw:0,0`).
- Leave out `--llm-bin` and `--llm-model` to run without the note.
- Open `http://<board-ip>:8000/` on the laptop (SLP view) and `http://localhost:8000/kid` on the board's monitor.
- Backup with no microphone: `--replay <folder>` uses saved clips (one per word on screen) instead of the mic; use it in place of `--arecord`.

Other options: `python3 -m speakup --help`.

## Models

| Model | Size | Where it comes from |
|---|---|---|
| Arti (`arti-v0.onnx`) | 1.0 MB, 60,706 parameters | Trained by us on the PERCEPT-R corpus with `scripts/train_arti.py` |
| Qwen2.5-0.5B-Instruct, Q4_K_M | 491 MB | Public download from Hugging Face |

**Arti is not in this repo, and we cannot give out copies.** It is trained on PERCEPT-R, which TalkBank
distributes; TalkBank asked us (Nov 13, 2026) not to share models trained on its data publicly, and allows them
in a competition demo only if no one keeps a copy. To build your own:

1. Get the PERCEPT-R corpus from TalkBank/PhonBank with a free account (doi:10.21415/0JPJ-X403).
2. Pick the held-out test set, then train and export (about 20 minutes on a laptop GPU):

```bash
python3 -I scripts/pick_test_set.py data/percept-r/PERCEPT-R.zip
uv run --managed-python --python 3.12 --with torch --with torchaudio --with onnx --with onnxscript \
    --with onnxruntime --with numpy python -I scripts/train_arti.py data/percept-r/PERCEPT-R.zip --out models/arti-v0.onnx
```

Qwen:

```bash
uv run --managed-python --with huggingface_hub hf download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
    qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir models
```

How Arti is built and why (input, layers, training, export): [docs/model-timing.md](docs/model-timing.md#how-arti-was-trained).

## Tests

```bash
python3 -m pip install numpy
python3 -m unittest discover -s tests
```

A few tests fake `arecord` and `llama-completion` with shell scripts and only pass on Linux or macOS.

## What is where

| Path | What |
|---|---|
| `speakup/` | The app: web server and pages (`server.py`, `pages.py`), recorder, Arti (`arti.py`), sound analysis (`acoustics.py`), sessions, the language-model note (`llm.py`, `summary.py`) |
| `speakup/static/` | Child-view art and scripts |
| `scripts/` | Training, test-set picking, timing on the board |
| `tests/` | Unit and server tests |
| `docs/board-setup.md` | Board setup from a blank card |
| `docs/model-timing.md` | Model choice, sizes, timing, how Arti was trained |
| `docs/test-set.md` | The 300-clip held-out test set and its rules |
| `docs/research/` | Data and licences, fairness and wording, the /s/ sound, recruiting, the Round 3 plan |
| `docs/round3-demo-script.md` | The final demo, step by step |

## Results

- **Arti v0 on 300 clips from 55 children never seen in training: agrees with trained listeners on 258**
  (86%; catches 119 of 150 wrong r sounds, flags 11 of 150 correct ones). Clips are ones listeners mostly agreed
  on. Details: [docs/test-set.md](docs/test-set.md), [docs/model-timing.md](docs/model-timing.md).
- **On the board:** 0.058 s per clip and 71 MB of memory for Arti; the language model runs at 4.6 tokens per
  second, which is why the note is built from approved sentences and every number in it is checked by code.

## Data and privacy rules

- Never commit audio recordings, child data or trained models. `data/`, `recordings/` and `models/` are ignored.
- Recordings and sessions stay on the machine that runs the app (`recordings/`, `data/speakup.db`).
- Wording, accents and dialects: [docs/research/fairness-and-wording.md](docs/research/fairness-and-wording.md).

## References

- Benway, N. R., et al. (2023). PERCEPT-R classifier. *Journal of Speech, Language, and Hearing Research*. doi:10.1044/2023_JSLHR-22-00343
- Benway, N. R., et al. (2022). The PERCEPT-R corpus. *Proc. Interspeech 2022*, 3648-3652. doi:10.21437/Interspeech.2022-10785
- PERCEPT-R Corpus, TalkBank. doi:10.21415/0JPJ-X403
