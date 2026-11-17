import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from speakup import sibilant

RATE = 22050


def noise(lo, hi, seconds=0.25, seed=0):
    """Band-limited noise between lo and hi Hz, with silence on both sides."""
    rng = np.random.default_rng(seed)
    n = int(seconds * RATE)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / RATE)
    spec[(f < lo) | (f > hi)] = 0
    x = np.fft.irfft(spec, n)
    x = 0.5 * x / np.abs(x).max()
    pad = np.zeros(int(0.15 * RATE))
    return np.concatenate([pad, x, pad])


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    return path


class SibilantTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.s = write(d / "s.wav", noise(5500, 7500, seed=1))  # concentrated and high
        self.sh = write(d / "sh.wav", noise(2600, 4000, seed=2))  # lower peak
        self.th = write(d / "th.wav", noise(1200, 10000, seed=3))  # spread out
        self.lisp = write(d / "lisp.wav", noise(1300, 9500, seed=4))  # an /s/ spread like the th

    def tearDown(self):
        self.dir.cleanup()

    def test_measures_peak_and_spread(self):
        s, sh, th = (sibilant.measure(p) for p in (self.s, self.sh, self.th))
        self.assertTrue(5000 < s.peak_hz < 8000)
        self.assertLess(sh.peak_hz, s.peak_hz)
        self.assertGreater(th.spread_hz, s.spread_hz)
        self.assertAlmostEqual(s.seconds, 0.25, delta=0.03)

    def test_a_clear_s_passes_both_checks(self):
        lines = sibilant.compare(*(sibilant.measure(p) for p in (self.s, self.sh, self.th)))
        self.assertEqual([ok for _, ok in lines], [True, True])

    def test_a_spread_s_is_flagged_as_a_possible_lisp(self):
        lines = sibilant.compare(*(sibilant.measure(p) for p in (self.lisp, self.sh, self.th)))
        self.assertFalse(lines[1][1])
        self.assertIn("frontal lisp", lines[1][0])

    def test_silence_has_no_frication(self):
        quiet = write(Path(self.dir.name) / "quiet.wav", np.zeros(RATE // 2))
        self.assertIsNone(sibilant.measure(quiet))

    def test_only_the_references_given_are_compared(self):
        self.assertEqual(len(sibilant.compare(sibilant.measure(self.s))), 0)
        self.assertEqual(len(sibilant.compare(sibilant.measure(self.s), th=sibilant.measure(self.th))), 1)


if __name__ == "__main__":
    unittest.main()
