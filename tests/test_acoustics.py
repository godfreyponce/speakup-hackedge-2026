import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from speakup import acoustics

RATE = 16000


def resonator(x, freq, bw):
    """Two-pole resonance at freq Hz with bandwidth bw Hz: one formant."""
    r = np.exp(-np.pi * bw / RATE)
    a1, a2 = 2 * r * np.cos(2 * np.pi * freq / RATE), -r * r
    y = np.zeros_like(x)
    for n in range(len(x)):
        y[n] = x[n] + a1 * (y[n - 1] if n else 0) + a2 * (y[n - 2] if n > 1 else 0)
    return y


def synth(f0, formants, seconds=0.5, silence=0.6):
    """A steady synthetic voice: glottal pulses at f0 through formant resonances, between silences."""
    n = int(seconds * RATE)
    src = np.zeros(n)
    src[:: int(RATE / f0)] = 1.0
    y = src
    for f, bw in formants:
        y = resonator(y, f, bw)
    y = y / np.max(np.abs(y)) * 0.5
    pad = np.zeros(int(silence * RATE))
    return np.concatenate([pad, y, pad])


def write(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


class AcousticsTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def analyse(self, x):
        return acoustics.analyse(write(self.dir / "s.wav", x))

    def test_finds_the_word_between_silences(self):
        a = self.analyse(synth(200, [(700, 80), (1200, 100), (2600, 150)]))
        self.assertAlmostEqual(a.start, 0.6 - acoustics.PAD, delta=0.05)
        self.assertAlmostEqual(a.end, 1.1 + acoustics.PAD, delta=0.05)

    def test_pitch_of_a_child_like_voice(self):
        a = self.analyse(synth(250, [(700, 80), (1200, 100), (2600, 150)]))
        self.assertAlmostEqual(a.f0_median, 250, delta=12)

    def test_formants_of_a_vowel(self):
        a = self.analyse(synth(150, [(700, 80), (1200, 100), (2600, 150)]))
        f1, f2, f3 = (np.nanmedian(a.formants[:, i]) for i in range(3))
        self.assertAlmostEqual(f1, 700, delta=100)
        self.assertAlmostEqual(f2, 1200, delta=120)
        self.assertAlmostEqual(f3, 2600, delta=200)
        self.assertAlmostEqual(a.gap_min, 1400, delta=250)

    def test_r_like_voice_has_a_small_f3_f2_gap(self):
        vowel = self.analyse(synth(150, [(600, 80), (1300, 100), (2700, 150)]))
        r_like = self.analyse(synth(150, [(450, 80), (1200, 100), (1650, 120)]))
        self.assertLess(r_like.gap_min, 700)
        self.assertLess(r_like.gap_min, vowel.gap_min - 600)

    def test_spectrogram_covers_the_word_up_to_its_top(self):
        # A 16 kHz clip shows up to its 8 kHz limit; the compact picture crops to TOP_HZ when it draws.
        a = self.analyse(synth(200, [(700, 80), (1200, 100), (2600, 150)]))
        bins, cols = a.spec_db.shape
        self.assertEqual(a.spec_top, 8000)
        self.assertEqual(bins, int(a.spec_top / (RATE / acoustics.SPEC_NFFT)) + 1)
        self.assertAlmostEqual(cols * acoustics.SPEC_HOP, a.spec_seconds, delta=0.02)

    def test_silence_gives_no_gap_and_says_why(self):
        a = self.analyse(np.zeros(RATE))
        self.assertIsNone(a.gap_min)
        self.assertTrue(a.notes)

    def test_wrong_format_is_refused(self):
        path = self.dir / "s8k.wav"
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(8000)
            w.writeframes(b"\0\0" * 8000)
        with self.assertRaises(ValueError):
            acoustics.analyse(path)



class SoundPicTest(unittest.TestCase):
    def test_png_is_valid_and_decodes(self):
        import struct
        import zlib
        from speakup.soundpic import png_gray
        pixels = np.arange(12, dtype=np.uint8).reshape(3, 4)
        data = png_gray(pixels)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        w, h = struct.unpack(">II", data[16:24])
        self.assertEqual((w, h), (4, 3))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        raw = zlib.decompress(idat)
        self.assertEqual(raw, b"".join(b"\x00" + bytes(pixels[y]) for y in range(3)))

    def test_svg_has_the_tracks_and_the_gap_label(self):
        from speakup.soundpic import svg
        d = Path(tempfile.mkdtemp())
        a = acoustics.analyse(write(d / "r.wav", synth(150, [(450, 80), (1200, 100), (1650, 120)])), "start")
        out = svg(a)
        self.assertTrue(out.startswith("<svg") and out.endswith("</svg>"))
        for color in ("#1f77b4", "#2ca02c", "#d62728"):
            self.assertIn(color, out)
        self.assertIn("F3-F2", out)
        self.assertIn("data:image/png;base64,", out)

    def test_gap_is_searched_only_where_the_r_should_be(self):
        d = Path(tempfile.mkdtemp())
        a = acoustics.analyse(write(d / "r.wav", synth(150, [(450, 80), (1200, 100), (1650, 120)])), "end")
        lo, hi = a.window
        self.assertTrue(lo <= a.gap_time <= hi)
        self.assertAlmostEqual(lo, 0.55 * a.spec_seconds, delta=0.01)

if __name__ == "__main__":
    unittest.main()
