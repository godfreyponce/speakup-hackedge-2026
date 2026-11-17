import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from speakup import acoustics, arti, audio


def tone(freq, rate, seconds=0.5, amp=0.5):
    t = np.arange(int(seconds * rate)) / rate
    return amp * np.sin(2 * np.pi * freq * t)


def write(path, x, rate):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(np.round(x * 32767), -32768, 32767).astype("<i2").tobytes())
    return path


def rms(x):
    x = x[len(x) // 4: -len(x) // 4]  # skip the filter's edges
    return float(np.sqrt(np.mean(x ** 2)))


class DownsampleTest(unittest.TestCase):
    def test_speech_band_passes_and_high_band_is_removed(self):
        for rate in (48000, 44100):
            kept = audio.to_16k(tone(2500, rate), rate)
            self.assertAlmostEqual(rms(kept), 0.5 / np.sqrt(2), delta=0.01)
            # 12 kHz would fold to 4 kHz at 16 kHz if it were not filtered out first.
            gone = audio.to_16k(tone(12000, rate), rate)
            self.assertLess(rms(gone), 0.001)
            self.assertAlmostEqual(len(kept), 8000, delta=2)

    def test_16k_is_left_alone(self):
        x = tone(1000, 16000)
        self.assertIs(audio.to_16k(x, 16000), x)


class FortyEightKTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_arti_hears_a_16k_copy(self):
        path = write(self.dir / "a.wav", tone(1000, 48000, seconds=0.3), 48000)
        samples = arti.read_wav(path)
        self.assertAlmostEqual(len(samples), 4800, delta=2)
        self.assertGreater(max(samples), 15000)

    def test_analysis_shows_up_to_11k_and_tracks_like_16k(self):
        from tests.test_acoustics import synth, write as write16
        x16 = synth(150, [(450, 80), (1200, 100), (1650, 120)])
        a16 = acoustics.analyse(write16(self.dir / "r16.wav", x16), "start")
        # The same voice at 48 kHz (sample-and-hold upsampling is enough: the trackers see the 16 kHz copy).
        x48 = np.repeat(x16, 3)
        a48 = acoustics.analyse(write(self.dir / "r48.wav", x48, 48000), "start")
        self.assertEqual(a16.spec_top, 8000)
        self.assertEqual(a48.spec_top, 11000)
        self.assertEqual(a48.rate, 48000)
        self.assertAlmostEqual(a48.f0_median, a16.f0_median, delta=5)
        self.assertAlmostEqual(np.nanmedian(a48.formants[:, 1]), np.nanmedian(a16.formants[:, 1]), delta=80)
        # 31.25 Hz rows up to the top at either rate.
        self.assertAlmostEqual(a48.spec_db.shape[0], 11000 / 31.25, delta=2)


if __name__ == "__main__":
    unittest.main()
