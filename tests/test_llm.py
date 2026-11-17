import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from speakup import bank, proof
from speakup.llm import LlmError, load
from speakup.words import load_words

# A stand-in llama-completion: the -m file says what to do, so each test picks a behavior.
FAKE = """#!{python}
import json, sys, time
args = sys.argv[1:]
mode = open(args[args.index("-m") + 1]).read()
prompt = open(args[args.index("-f") + 1], encoding="utf-8").read()
if mode == "echo":
    sys.stdout.buffer.write(("\\n" + prompt + " [end of text]\\n\\n").encode("utf-8"))
elif mode == "fail":
    sys.stderr.write("loading model\\nerror: unable to load model")
    sys.exit(1)
elif mode == "args":
    sys.stdout.write(json.dumps(args))
elif mode == "timed":
    sys.stdout.write("hi")
    sys.stderr.write("llama_perf_context_print:        eval time =     150.00 ms /    10 runs   (   15.00 ms per token,    66.67 tokens per second)\\n")
elif mode == "hang":
    time.sleep(10)
elif mode == "turns":
    with open(args[args.index("-m") + 1] + ".log", "a") as log:
        log.write("start\\n")
        log.flush()
        time.sleep(0.3)
        log.write("end\\n")
elif mode == "slow":
    open(args[args.index("-m") + 1] + ".started", "w").close()
    time.sleep(1.5)
"""


class LlmTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.fake = self.dir / "fake-llama"
        self.fake.write_text(FAKE.format(python=sys.executable))
        os.chmod(self.fake, 0o755)

    def model(self, text):
        path = self.dir / f"{text}.gguf"
        path.write_text(text)
        return path

    def test_reply_comes_back_clean(self):
        self.assertEqual(load(str(self.fake), self.model("echo"))("facts ɹ\nline 2"), "facts ɹ\nline 2")

    def test_args(self):
        generate = load(str(self.fake), self.model("args"))
        plain = json.loads(generate("x"))
        self.assertEqual(plain[plain.index("-c") + 1], "1024")
        self.assertEqual(plain[plain.index("-n") + 1], "96")
        self.assertNotIn("--grammar", plain)
        with_grammar = json.loads(generate("x", grammar='root ::= "x"', n_predict=400))
        self.assertEqual(with_grammar[with_grammar.index("--grammar") + 1], 'root ::= "x"')
        self.assertEqual(with_grammar[with_grammar.index("-n") + 1], "400")

    def test_speed_goes_to_the_proof_banner(self):
        live = proof.Proof()
        with mock.patch.object(proof, "LIVE", live):
            self.assertEqual(load(str(self.fake), self.model("timed"))("x"), "hi")
        self.assertEqual(live.snapshot().qwen_tps, 66.67)

    def test_failed_run_raises(self):
        generate = load(str(self.fake), self.model("fail"))
        with self.assertRaisesRegex(LlmError, "unable to load model"):
            generate("x")

    def test_hang_times_out(self):
        generate = load(str(self.fake), self.model("hang"), timeout_s=0.5)
        with self.assertRaises(LlmError):
            generate("x")

    def test_two_threads_take_turns(self):
        model = self.model("turns")
        generate = load(str(self.fake), model)
        threads = [threading.Thread(target=generate, args=("x",)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(Path(f"{model}.log").read_text().split(), ["start", "end", "start", "end"])

    def test_bank_time_leaves_out_the_wait_for_a_turn(self):
        # The bank's "took" lines go into docs/model-timing.md (#21), so they must be llama.cpp's own time (#60).
        slow = self.model("slow")
        note = threading.Thread(target=load(str(self.fake), slow), args=("x",))
        note.start()
        self.addCleanup(note.join)
        while not Path(f"{slow}.started").exists():
            time.sleep(0.01)
        words = load_words()
        err = io.StringIO()
        with redirect_stderr(err):
            bank.fill(load(str(self.fake), self.model("echo")), words, bank.load_fallback(words))
        took = [float(s) for s in re.findall(r"took ([\d.]+) s", err.getvalue())]
        self.assertEqual(len(took), 2, err.getvalue())
        self.assertTrue(all(t < 1.0 for t in took), took)

    def test_no_room_for_the_prompt_file_raises(self):
        generate = load(str(self.fake), self.model("echo"))
        with mock.patch("tempfile.NamedTemporaryFile", side_effect=OSError("No space left on device")):
            with self.assertRaisesRegex(LlmError, "No space left"):
                generate("x")

    def test_missing_model_raises_at_load(self):
        with self.assertRaisesRegex(LlmError, "no model file"):
            load(str(self.fake), self.dir / "none.gguf")

    def test_missing_binary_raises_at_load(self):
        with self.assertRaisesRegex(LlmError, "not found"):
            load(str(self.dir / "no-such-llama"), self.model("echo"))


if __name__ == "__main__":
    unittest.main()
