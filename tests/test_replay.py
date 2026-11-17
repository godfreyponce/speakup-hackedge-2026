import contextlib
import http.client
import io
import math
import sys
import tempfile
import threading
import unittest
import wave
from array import array
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from speakup import replay
from speakup.bank import Bank
from speakup.recorder import FakeRecorder, RecorderError
from speakup.replay import ReplayError, ReplayRecorder
from speakup.server import make_server
from speakup.words import Word

WORDS = ["rabbit", "carrot", "car"]


def write_wav(path: Path, hz: float = 220.0, seconds: float = 0.05, rate: int = 16000, channels: int = 1) -> None:
    """A tiny tone, so each test clip has its own bytes."""
    samples = array("h", (int(8000 * math.sin(2 * math.pi * hz * i / rate)) for i in range(int(rate * seconds))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes() * channels)


class ReplayTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.folder = self.tmp / "clips"
        self.folder.mkdir()

    def clips(self, rows: list[tuple[str, str]], header: str = "file,word") -> None:
        """Write the folder: one tone per clip file and a manifest of the rows."""
        for i, (name, _) in enumerate(rows):
            if not (self.folder / name).exists():
                write_wav(self.folder / name, hz=200 + 50 * i)
        lines = ["# de-identified demo clips", header] + [f"{name},{word}" for name, word in rows]
        (self.folder / "manifest.csv").write_text("\n".join(lines) + "\n")


class LoadTest(ReplayTestCase):
    def test_maps_each_word_to_its_clips_in_manifest_order(self):
        self.clips([("a.wav", "rabbit"), ("b.wav", "car"), ("c.wav", "rabbit")])
        clips = replay.load(self.folder, WORDS)
        self.assertEqual(clips, {"rabbit": [self.folder / "a.wav", self.folder / "c.wav"], "car": [self.folder / "b.wav"]})

    def test_missing_folder(self):
        with self.assertRaisesRegex(ReplayError, "no folder"):
            replay.load(self.tmp / "nope", WORDS)

    def test_missing_manifest(self):
        with self.assertRaisesRegex(ReplayError, "manifest.csv"):
            replay.load(self.folder, WORDS)

    def test_manifest_without_file_and_word_header(self):
        self.clips([("a.wav", "rabbit")], header="clip,target")
        with self.assertRaisesRegex(ReplayError, "file,word"):
            replay.load(self.folder, WORDS)

    def test_empty_manifest(self):
        self.clips([])
        with self.assertRaisesRegex(ReplayError, "no clips"):
            replay.load(self.folder, WORDS)

    def test_missing_clip_is_named(self):
        self.clips([("a.wav", "rabbit")])
        (self.folder / "manifest.csv").write_text("file,word\na.wav,rabbit\ngone.wav,car\n")
        with self.assertRaisesRegex(ReplayError, "gone.wav"):
            replay.load(self.folder, WORDS)

    def test_word_not_in_the_word_list(self):
        self.clips([("a.wav", "sun")])
        with self.assertRaisesRegex(ReplayError, "'sun' is not in the word list"):
            replay.load(self.folder, WORDS)

    def test_manifest_that_is_not_utf8_is_named(self):
        self.clips([("a.wav", "rabbit")])
        (self.folder / "manifest.csv").write_bytes("file,word\na.wav,rabbit\n# caf\u00e9\n".encode("latin-1"))
        with self.assertRaisesRegex(ReplayError, "manifest.csv.*UTF-8"):
            replay.load(self.folder, WORDS)

    def test_clip_that_arti_cannot_read(self):
        self.clips([("a.wav", "rabbit")])
        write_wav(self.folder / "a.wav", channels=2)
        with self.assertRaisesRegex(ReplayError, "a.wav.*mono"):
            replay.load(self.folder, WORDS)
        (self.folder / "a.wav").write_text("not audio")
        with self.assertRaisesRegex(ReplayError, "a.wav"):
            replay.load(self.folder, WORDS)


class RecorderTest(ReplayTestCase):
    def recorder(self, rows):
        self.clips(rows)
        return ReplayRecorder(self.folder, replay.load(self.folder, WORDS))

    def test_each_try_on_a_word_is_its_next_clip_then_it_starts_over(self):
        r = self.recorder([("a.wav", "rabbit"), ("b.wav", "car"), ("c.wav", "rabbit")])
        got = []
        for i, word in enumerate(["rabbit", "rabbit", "car", "rabbit"]):
            r.cue(word)
            out = self.tmp / "rec" / f"{i}.wav"
            r.record(out)
            got.append(out.read_bytes())
        clip = lambda name: (self.folder / name).read_bytes()
        self.assertEqual(got, [clip("a.wav"), clip("c.wav"), clip("b.wav"), clip("a.wav")])

    def test_word_without_a_clip_says_which_words_have_one(self):
        r = self.recorder([("a.wav", "rabbit"), ("b.wav", "car")])
        r.cue("carrot")
        with self.assertRaisesRegex(RecorderError, "No replay clip for carrot.*rabbit, car"):
            r.record(self.tmp / "out.wav")

    def test_clip_removed_after_start_is_named(self):
        r = self.recorder([("a.wav", "rabbit")])
        (self.folder / "a.wav").unlink()
        r.cue("rabbit")
        with self.assertRaisesRegex(RecorderError, "a.wav"):
            r.record(self.tmp / "out.wav")

    def test_says_it_is_replaying_and_names_the_folder_even_when_given_as_dot(self):
        self.clips([("a.wav", "rabbit")])
        with contextlib.chdir(self.folder):
            r = ReplayRecorder(Path("."), replay.load(self.folder, WORDS))
        self.assertEqual(r.mode, "Replay: saved clips from clips, not the mic")


class FlowTest(ReplayTestCase):
    """The normal screening flow on a server whose recorder is the replay and whose model is a stand-in for Arti."""

    def setUp(self):
        super().setUp()
        self.clips([("a.wav", "rabbit"), ("b.wav", "carrot")])
        self.heard = []  # (word, the bytes of the full recording) for each time the model was asked
        self.played = []  # the bytes the model was given, in order

    def serve(self, words=("rabbit", "carrot"), recorder=None):
        """Car has no clip, so a word list with car in it is a replay with a gap."""
        positions = {"rabbit": "start", "carrot": "middle", "car": "end"}
        words = [Word(w, positions[w]) for w in words]
        server = make_server(
            "127.0.0.1", 0,
            words=words,
            listen=self.listen,
            recorder=recorder or ReplayRecorder(self.folder, replay.load(self.folder, [w.word for w in words])),
            recordings_dir=self.tmp / "recordings",
            db_path=self.tmp / "data" / "speakup.db",
            bank=Bank({}),  # the stand-in Arti always hears gliding, so practice stays at the word level
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def listen(self, word, path):
        self.heard.append((word, Path(path).is_file()))
        self.played.append(Path(path).read_bytes() if Path(path).is_file() else None)
        return {
            "word": word, "target_sound": "r", "expected_phone": "ɹ", "heard_phone": "w", "error_type": "gliding",
            "confidence": 0.91, "model": "arti-stand-in", "recorded_at": "2026-11-14T10:15:00-06:00",
        }

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(fields) if fields is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read().decode("utf-8")
        conn.close()
        return result

    def practice_words(self, tries: int) -> list[str]:
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01", "mode": "practice"})
        for _ in range(tries):
            self.request("POST", "/practice/record", {})
            self.request("POST", "/practice/next", {})
        return [word for word, _ in self.heard]

    def test_practice_walks_only_the_words_with_a_clip_in_list_order(self):
        self.serve(words=["rabbit", "car", "carrot"])
        self.assertEqual(self.practice_words(3), ["rabbit", "carrot", "rabbit"])

    def test_live_practice_still_walks_every_word(self):
        self.serve(words=["rabbit", "car", "carrot"], recorder=FakeRecorder())
        self.assertEqual(self.practice_words(4), ["rabbit", "car", "carrot", "rabbit"])

    def test_end_pages_and_sound_analysis_show_the_replay_tag(self):
        self.serve()
        tag = "Replay: saved clips from clips, not the mic"
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01"})
        for _ in range(2):
            self.request("POST", "/record", {})
            self.request("POST", "/next", {})
        status, body = self.request("GET", "/analysis/s0")
        self.assertEqual(status, 200)
        self.assertIn(tag, body)
        status, body = self.request("GET", "/summary")
        self.assertEqual(status, 200)
        self.assertIn(tag, body)
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01", "mode": "practice"})
        self.request("POST", "/practice/record", {})
        self.request("POST", "/practice/end", {})
        status, body = self.request("GET", "/practice/summary")
        self.assertEqual(status, 200)
        self.assertIn(tag, body)

    def rabbit_clips(self):
        """Rabbit gets a second clip, so the cursor's place shows in which clip a try plays."""
        self.clips([("a.wav", "rabbit"), ("b.wav", "carrot"), ("c.wav", "rabbit")])
        self.serve()
        return (self.folder / "a.wav").read_bytes(), (self.folder / "c.wav").read_bytes()

    def test_retries_in_one_session_step_through_the_clips(self):
        first, second = self.rabbit_clips()
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01"})
        self.request("POST", "/record", {})
        self.request("POST", "/record", {})
        self.assertEqual(self.played, [first, second])

    def test_a_new_session_starts_each_word_at_its_first_clip(self):
        first, _ = self.rabbit_clips()
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01"})
        for _ in range(2):
            self.request("POST", "/record", {})
            self.request("POST", "/next", {})
        self.request("POST", "/start", {"student_id": "DEMO-2", "birth_date": "2018-01-01"})
        self.request("POST", "/record", {})
        self.request("POST", "/start", {"student_id": "DEMO-3", "birth_date": "2018-01-01", "mode": "practice"})
        self.request("POST", "/practice/record", {})
        self.assertEqual([w for w, _ in self.heard], ["rabbit", "carrot", "rabbit", "rabbit"])
        self.assertEqual(self.played[2:], [first, first])

    def test_each_word_is_scored_on_its_clip(self):
        self.serve()
        self.request("POST", "/start", {"student_id": "DEMO-1", "birth_date": "2018-01-01"})
        self.request("POST", "/record", {})
        status, body = self.request("GET", "/word")
        self.assertEqual(status, 200)
        self.assertIn("Model: arti-stand-in.", body)  # the #37 question card
        self.assertIn("Replay", body)
        self.request("POST", "/next", {})
        self.request("POST", "/record", {})
        self.assertEqual(self.heard, [("rabbit", True), ("carrot", True)])
        recordings = sorted((self.tmp / "recordings").glob("DEMO-1-*.wav"))
        full = {p.name.rsplit("-", 1)[1]: p.read_bytes() for p in recordings if not p.stem.endswith("-word")}
        self.assertEqual(full, {"rabbit.wav": (self.folder / "a.wav").read_bytes(),
                                "carrot.wav": (self.folder / "b.wav").read_bytes()})


class MainTest(ReplayTestCase):
    def run_main(self, *argv) -> str:
        """Runs python3 -m speakup with these arguments up to its exit; returns what it said."""
        from speakup.__main__ import main

        err = io.StringIO()
        with mock.patch.object(sys, "argv", ["speakup", *argv]), mock.patch("sys.stderr", err), \
                mock.patch("speakup.arti.load", side_effect=AssertionError("Arti loaded before the folder was checked")):
            with self.assertRaises(SystemExit) as caught:
                main()
        return f"{err.getvalue()}{caught.exception.code}"

    def test_replay_needs_arti(self):
        self.clips([("a.wav", "rabbit")])
        self.assertIn("--replay needs --arti", self.run_main("--replay", str(self.folder)))

    def test_replay_does_not_mix_with_the_mic(self):
        self.clips([("a.wav", "rabbit")])
        said = self.run_main("--replay", str(self.folder), "--arti", "m.onnx", "--arecord")
        self.assertIn("--replay can't run with --arecord", said)

    def test_manifest_that_is_not_utf8_is_one_plain_line(self):
        self.clips([("a.wav", "rabbit")])
        (self.folder / "manifest.csv").write_bytes("file,word\na.wav,rabbit\n# caf\u00e9\n".encode("latin-1"))
        said = self.run_main("--replay", str(self.folder), "--arti", "m.onnx")
        self.assertTrue(said.startswith(f"--replay: {self.folder / 'manifest.csv'}"), said)
        self.assertNotIn("\n", said)
        self.assertNotIn("Traceback", said)

    def test_missing_folder_stops_before_arti_loads(self):
        said = self.run_main("--replay", str(self.tmp / "nope"), "--arti", "m.onnx")
        self.assertIn("--replay:", said)
        self.assertIn("no folder", said)


if __name__ == "__main__":
    unittest.main()
