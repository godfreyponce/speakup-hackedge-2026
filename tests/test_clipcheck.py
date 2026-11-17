import math
import tempfile
import unittest
import wave
from array import array
from pathlib import Path

from speakup.clipcheck import check_clip

RATE = 16000


def write_clip(path: Path, pieces, rate=RATE, channels=1):
    """pieces: (seconds, amplitude) runs; amplitude 0 is silence, anything else a 220 Hz tone."""
    samples = array("h")
    for seconds, amplitude in pieces:
        for i in range(int(seconds * rate)):
            value = amplitude * math.sin(2 * math.pi * 220 * i / rate) if amplitude else 0
            samples.append(max(-32768, min(32767, int(value))))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return path


class ClipCheckTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def clip(self, *pieces, **kw):
        return check_clip(write_clip(self.dir / "c.wav", pieces, **kw))

    def test_clear_word_in_the_middle_is_ok(self):
        c = self.clip((1.0, 0), (0.6, 9000), (1.4, 0))
        self.assertTrue(c.ok, c.problems)
        self.assertEqual(c.seconds, 3.0)
        self.assertAlmostEqual(c.speech_seconds, 0.6, delta=0.05)

    def test_silence_says_no_speech(self):
        c = self.clip((3.0, 0))
        self.assertIn("No speech heard", c.problems[0])

    def test_quiet_word_says_too_quiet(self):
        c = self.clip((1.0, 0), (0.6, 600), (1.4, 0))
        self.assertTrue(any("Too quiet" in p for p in c.problems), c.problems)

    def test_clipped_word_says_too_loud(self):
        c = self.clip((1.0, 0), (0.6, 60000), (1.4, 0))
        self.assertTrue(any("Too loud" in p for p in c.problems), c.problems)

    def test_word_cut_off_at_the_end(self):
        c = self.clip((2.6, 0), (0.4, 9000))
        self.assertTrue(any("end of the word" in p for p in c.problems), c.problems)

    def test_word_cut_off_at_the_start(self):
        c = self.clip((0.4, 9000), (2.6, 0))
        self.assertTrue(any("beginning of the word" in p for p in c.problems), c.problems)

    def test_stereo_is_refused_not_guessed(self):
        c = self.clip((1.0, 9000), channels=2)
        self.assertIn("16-bit mono", c.problems[0])

    def test_missing_file_is_a_problem_not_a_crash(self):
        c = check_clip(self.dir / "nope.wav")
        self.assertFalse(c.ok)


if __name__ == "__main__":
    unittest.main()
