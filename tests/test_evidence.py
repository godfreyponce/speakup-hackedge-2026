import json
import tempfile
import unittest
from pathlib import Path

from speakup import evidence

REF = {"start": {"cutoff_hz": 1300.0, "median_gap_correct": 900.0, "median_gap_wrong": 1700.0},
       "end": {"cutoff_hz": 1100.0, "median_gap_correct": 700.0, "median_gap_wrong": 1500.0}}


class GapLineTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "ref.json"
        self.path.write_text(json.dumps(REF), encoding="utf-8")

    def tearDown(self):
        self.dir.cleanup()

    def test_a_wide_gap_agrees_with_an_off_call(self):
        text, agrees = evidence.gap_line(1850.0, "start", True, self.path)
        self.assertTrue(agrees)
        self.assertIn("1,850 Hz, above the 1,300 Hz line", text)
        self.assertIn("agrees with Arti", text)

    def test_a_narrow_gap_against_an_off_call_says_listen(self):
        text, agrees = evidence.gap_line(800.0, "start", True, self.path)
        self.assertFalse(agrees)
        self.assertIn("at or below", text)
        self.assertIn("listen before you decide", text)

    def test_each_position_uses_its_own_line(self):
        _, agrees = evidence.gap_line(1200.0, "end", False, self.path)
        self.assertFalse(agrees)  # above the end line, so the measure says off while Arti said right

    def test_no_gap_no_reference_or_no_file_shows_nothing(self):
        self.assertIsNone(evidence.gap_line(None, "start", True, self.path))
        self.assertIsNone(evidence.gap_line(900.0, "middle", True, self.path))
        self.assertIsNone(evidence.gap_line(900.0, "start", True, Path(self.dir.name) / "missing.json"))


if __name__ == "__main__":
    unittest.main()
