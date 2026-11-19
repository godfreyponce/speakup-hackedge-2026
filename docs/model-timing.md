# Model timing (#2)

Which speech model the board runs, with numbers. Every number below is from the laptop. The board
columns wait for the commands in [On the board](#on-the-board), tracked in #17.

**Pick:** Arti (`arti-v0`, ONNX Runtime on the A53 cores, no accelerator). On the
laptop it takes 1.0 MB on disk, 64 MB peak RAM and 0.0019 s per 1-second clip through the app's
whole path, against wav2vec2 int8's 358 MB, 626 MB and 0.059 s for the model alone. It agreed with the listeners on 258 of 300 test clips, and it
answers right or wrong directly, where wav2vec2 gives phones that still need a rule.

## Table

Laptop: Apple M3 Pro, 18 GB, macOS. Python 3.12.13, ONNX Runtime 1.31.1 on the CPU with 4
threads, the board's core count. Each speech model ran once to warm up, then 20 times on the same
1.0 s clip (`recordings/rabbit-say.wav`, made with `say`, not child audio). Peak RAM is the whole
process's peak resident memory, Python and ONNX Runtime included.

| model | size on disk | peak RAM | seconds per 1-second clip | how it ran | where |
|---|---|---|---|---|---|
| Arti (`arti-v0.onnx`) | 1.0 MB | 64 MB | 0.0019 (max 0.0020) app path; 0.0003 model alone | ONNX Runtime, CPU, no accelerator | laptop |
| Arti | | | not run yet (#1) | ONNX Runtime, A53 cores, no accelerator | board |
| wav2vec2 fp32 (`facebook/wav2vec2-lv-60-espeak-cv-ft`) | 1267 MB | 1401 MB | 0.112 (max 0.142) | ONNX Runtime, CPU, no accelerator | laptop |
| wav2vec2 fp32 | | | not run yet (#1) | ONNX Runtime, A53 cores, no accelerator | board |
| wav2vec2 int8 (dynamic, MatMul weights) | 358 MB | 626 MB | 0.059 (max 0.072) | ONNX Runtime, CPU, no accelerator | laptop |
| wav2vec2 int8 | | | not run yet (#1) | ONNX Runtime, A53 cores, no accelerator | board |
| Qwen2.5-0.5B-Instruct Q4_K_M summary, Arti loaded | 491 MB | 1125 MB llama.cpp; 1187 MB with Arti | 1.56 per summary | llama.cpp b11146, CPU (`-ngl 0`), 4 threads | laptop |
| same, with `-c 256` | 491 MB | 844 MB llama.cpp; 905 MB with Arti | 1.22 per summary | llama.cpp b11146, CPU (`-ngl 0`), 4 threads | laptop |
| Qwen2.5-0.5B summary, Arti loaded | | | not run yet (#1) | llama.cpp from #9, A53 cores | board |

Notes on the table:

- Arti's app path is what the app does per clip: `read_wav`, `prepare` (pure Python) and the
  model. The model alone is 0.0003 s, so most of Arti's time is the Python before it. On a 3 s
  clip, the length the app records, the app path is 0.0033 s (max 0.0038). The wav2vec2 rows
  time the model alone.
- Laptop numbers are not board numbers. The A53 cores are much slower than the M3 Pro. No
  scale factor is applied, because nothing has measured one.
- The summary is one reply of at most 96 tokens to the #7 prompt for a made-up session (rabbit
  and red "the r sounded off", carrot correct, age 8). The prompt is 89 tokens.
- llama.cpp's default context is the model's own, 32k tokens. Its cache is most of the gap
  between the two summary rows. `-c 256` fits the 89-token prompt and the 96-token reply.
- "with Arti" adds the two processes' peaks, which is an upper bound for both at once. On macOS
  the llama.cpp peak also counts the model file's mapped pages.
- The summary model got the raw prompt with no chat template. It wrote no sentences: it listed
  errors over and over, and one of them was false. It said "carrot: the r sounded off", but
  carrot was correct in the session. The time counts all 96 tokens either way. The prompt form
  and a check on what the model claims belong to #9.
- Peak RAM for wav2vec2 fp32 is 1.4 GB, more than half of the board's 2 GB. int8 is the copy
  with a chance to run beside the summary model.

## How Arti was trained

`scripts/train_arti.py`, run on Nov 3, 2026, on `PERCEPT-R 2.2.2py`.

- Pool: every clip from a child speaker (144 months or less) who is not one of the 55 test
  speakers in `data/percept-r/test-speakers.txt`, any word, with a clear label (0.25 or less
  is wrong, 0.75 or more is correct, the same rule as #14). That is 42,350 clips: 12,203
  correct and 30,147 wrong. 12,238 clips with unclear labels were left out, and 54 label
  pickles that are not one float were skipped.
- Split by speaker, seed 2026: 106 speakers train (33,366 clips), 12 validate (8,984 clips),
  55 are the test set. The script asserts that the three sets share no speaker before it reads
  any audio.
- Input: each clip resampled from 44.1 kHz to 16 kHz, then the loudest 1.5 s, scaled to a peak
  of 1.0 (`prepare` in `speakup/arti.py`). 1.5 s is from a 400-clip sample of the corpus: the
  loud part ran 0.68 s at the median and 1.41 s at the 95th percentile.
- Shape, a guess sized like a keyword-spotting model: a log-mel frontend (40 mel bins, 25 ms
  window, 10 ms hop, 0 to 8000 Hz) built from plain Conv and MatMul ops, then 4 blocks of
  3x3 conv, batch norm, ReLU and 2x max pool (16, 32, 64, 64 channels), global average pool and
  one linear layer. 60,706 parameters.
- Training, also guesses with no tuning budget: Adam, learning rate 0.001, batch 256, 20 epochs,
  class-weighted cross-entropy. The script keeps the epoch with the best validation balanced
  accuracy: epoch 4, 0.844. Validation balanced accuracy swung from 0.64 to 0.84 between
  epochs, so the kept epoch is partly luck.
- Export: ONNX opset 18, one input `audio` float32 `[1, N]` (16 kHz, -1 to 1, N of 2800 or
  more), one output `p_wrong` float32 `[1]`. The frontend is inside the graph, so the board
  needs no feature code. Torch and ONNX Runtime agreed within 2.5e-07 on 64 validation clips.
- Test set (#14, 300 clips, held-out speakers): Arti agreed with the listeners on 258 of 300.

| position | listener said correct | listener said wrong |
|---|---|---|
| start-r | 70 of 75 | 59 of 75 |
| end-r | 69 of 75 | 60 of 75 |

The app counts `p_wrong` of 0.5 or more as wrong, and shows it as "the r sounded off".

No model file is in git. Arti is trained on PERCEPT-R. The release we use says CC BY-ND 4.0,
TalkBank's default is CC BY-NC-SA 4.0 (noncommercial, share-alike). TalkBank answered on Nov 13: trained models
are not shared publicly, and a competition demo is fine as long as no one keeps a copy. Sources in
[test-set.md](test-set.md#license) and [research/data-and-licences.md](research/data-and-licences.md). The
other three are large downloads. `models/` is gitignored. Rebuild them with:

```bash
uv run --managed-python --python 3.12 --with torch --with torchaudio --with onnx --with onnxscript --with onnxruntime --with numpy python -I scripts/train_arti.py /path/to/data/percept-r/PERCEPT-R.zip --out models/arti-v0.onnx
```

```bash
uv run --managed-python --python 3.12 --with torch --with transformers --with onnx --with onnxscript --with onnxruntime --with numpy --with huggingface_hub python scripts/export_wav2vec2.py
```

```bash
uv run --managed-python --with huggingface_hub hf download Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir models
```

`--managed-python` matters on a Mac with the Python.org 3.12 installed: its site-packages leak
an old protobuf into uv's environment and break `import onnx`.

Corpus: Benway et al. (2022), *Proceedings of Interspeech 2022*, pp. 3648-3652,
doi:10.21437/Interspeech.2022-10785 (the corpus paper); Benway et al. (2023), *Journal of
Speech, Language, and Hearing Research*, doi:10.1044/2023_JSLHR-22-00343. The PERCEPT-R
corpus on TalkBank: doi:10.21415/0JPJ-X403.

## Laptop commands

From the repo root, with `uv run --managed-python --python 3.12 --with onnxruntime --with numpy
python` in place of `python3`:

```bash
say -o recordings/rabbit-say.wav --data-format=LEI16@16000 rabbit
```

```bash
python3 scripts/time_model.py models/arti-v0.onnx recordings/rabbit-say.wav --prepare
```

```bash
python3 scripts/time_model.py models/arti-v0.onnx recordings/rabbit-say.wav --llm "llama-completion -m models/qwen2.5-0.5b-instruct-q4_k_m.gguf -f {prompt_file} -n 96 --temp 0 -t 4 -ngl 0 -no-cnv --no-display-prompt"
```

The wav2vec2 rows use the same first command, without `--prepare`, with `models/wav2vec2-lv60-espeak.onnx` and
`models/wav2vec2-lv60-espeak-int8.onnx`. The `-c 256` row adds `-c 256` to the `--llm` command.

## On the board

After #1, from the laptop, copy the repo and the four model files (the fp32 wav2vec2 has a
`.data` file beside it):

```bash
ssh <board> mkdir -p speakup-app/models && scp -r speakup scripts <board>:speakup-app/ && scp models/arti-v0.onnx models/wav2vec2-lv60-espeak.onnx models/wav2vec2-lv60-espeak.onnx.data models/wav2vec2-lv60-espeak-int8.onnx models/qwen2.5-0.5b-instruct-q4_k_m.gguf <board>:speakup-app/models/
```

Then on the board, in `speakup-app/`:

```bash
python3 -c "import onnxruntime, numpy, sqlite3"
```

```bash
mkdir -p recordings && arecord -D <dev> -f S16_LE -r 16000 -c 1 -d 1 recordings/board-1s.wav
```

```bash
python3 scripts/time_model.py models/arti-v0.onnx recordings/board-1s.wav --prepare
```

```bash
python3 scripts/time_model.py models/wav2vec2-lv60-espeak.onnx recordings/board-1s.wav
```

```bash
python3 scripts/time_model.py models/wav2vec2-lv60-espeak-int8.onnx recordings/board-1s.wav
```

```bash
python3 scripts/time_model.py models/arti-v0.onnx recordings/board-1s.wav --llm "$HOME/llama.cpp/build/bin/llama-completion -m models/qwen2.5-0.5b-instruct-q4_k_m.gguf -f {prompt_file} -n 96 --temp 0 -t 4 -c 512 -no-cnv --no-display-prompt"
```

Since #9 the prompt has the chat template and one example, 203 tokens, so `-c 256` is too small.

```bash
python3 -m speakup.arti models/arti-v0.onnx recordings/board-1s.wav rabbit
```

The last command is the ticket's "reads a WAV recorded on the board and prints a result in the
format from #3".

### llama.cpp and the end screen's note (#9)

On the laptop, pack the llama.cpp source without its git history and copy it to the board.

```bash
tar -czf /tmp/llama.cpp.tgz --exclude=.git -C <folder that holds llama.cpp> llama.cpp && scp /tmp/llama.cpp.tgz <board>:
```

On the board, check that the image has the build tools. If one is missing, stop: the app still
runs without llama.cpp, with the tally only.

```bash
which cmake make g++
```

Build only the completion tool. The board has no internet, so HTTPS support is off.

```bash
tar -xzf llama.cpp.tgz && cmake -S llama.cpp -B llama.cpp/build -DLLAMA_OPENSSL=OFF -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=OFF && cmake --build llama.cpp/build --target llama-completion -j 4
```

If the compiler is killed for lack of memory, run the last command again with `-j 1`.

Then the `time_model.py --llm` command above runs Qwen on the board from the command line.

Run the app with the note, in `speakup-app/`:

```bash
python3 -m speakup --arecord --device <dev> --arti models/arti-v0.onnx --llm-bin "$HOME/llama.cpp/build/bin/llama-completion" --llm-model models/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

If the end screen shows no note, the terminal shows a line that starts `summary note skipped:`
with the reason.
