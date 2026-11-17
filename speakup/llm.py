"""llama.cpp's `llama-completion` as #7's `Generate`, run as a subprocess (#9)."""

import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from speakup import proof
from speakup.summary import Generate

THREADS = 3  # of the AM62x's four A53 cores: one stays free for the app and the browser
TIMEOUT_S = 240  # the board took 107 s for a 10-word note (Nov 11); a hung llama.cpp must not freeze the demo
# The bank fill and the end-screen note run in separate threads; two runs at once share the 4 cores and can pass
# TIMEOUT_S (#60). The wait for a turn is outside the timeout, which is for one llama.cpp run. Re-entrant, so a
# caller can take its turn first and time only its own run (bank.fill).
TURN = threading.RLock()


class LlmError(Exception):
    pass


def load(binary: str, model: Path, timeout_s: float = TIMEOUT_S) -> Generate:
    if not model.is_file():
        raise LlmError(f"no model file at {model}")
    resolved = shutil.which(binary)
    if resolved is None:
        raise LlmError(f"{binary} not found")
    nice = shutil.which("nice")  # low priority, so the screen stays quick while a note or the bank is written

    def generate(prompt: str, grammar: str | None = None, n_predict: int = 96) -> str:
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt") as f:
                f.write(prompt)
                f.flush()
                # #2's timing flags (docs/model-timing.md). -c 1024 fits the note (203-token prompt, -n 96) and the
                # #21 bank (up to 121-token prompt, -n 400), as measured on the laptop.
                args = [resolved, "-m", str(model), "-f", f.name, "-n", str(n_predict), "--temp", "0",
                        "-t", str(THREADS), "-c", "1024", "-ngl", "0", "-no-cnv", "--no-display-prompt"]
                if nice:
                    args = [nice, "-n", "10", *args]
                if grammar is not None:
                    args += ["--grammar", grammar]
                with TURN:
                    done = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
                                          errors="replace", timeout=timeout_s)
        except subprocess.TimeoutExpired as e:
            raise LlmError(f"llama.cpp took longer than {timeout_s} s") from e
        # A full /tmp lands here too: an escaped OSError would drop the last Next before the save.
        except OSError as e:
            raise LlmError(f"{binary}: {e}") from e
        if done.returncode != 0:
            lines = done.stderr.strip().splitlines()
            raise LlmError(lines[-1] if lines else f"{binary} exited with {done.returncode}")
        proof.LIVE.add_llama_log(done.stderr)
        return done.stdout.strip().removesuffix("[end of text]").strip()

    return generate
