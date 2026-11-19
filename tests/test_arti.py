import struct
import tempfile
import unittest
import wave
from pathlib import Path

from speakup.arti import prepare, read_wav, to_result
from speakup.result import check

RATE = 16000


def write_wav(path, samples, rate=RATE, channels=1, width=2):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(samples)}h", *samples))


class PrepareTest(unittest.TestCase):
    def test_prepare_length(self):
        self.assertEqual(len(prepare([100] * int(0.3 * RATE))), 24000)
        self.assertEqual(len(prepare([100] * (3 * RATE))), 24000)

    def test_prepare_finds_the_loud_part(self):
        clip = [0] * (3 * RATE)
        start = int(1.4 * RATE)
        clip[start:start + RATE // 2] = [8000] * (RATE // 2)
        out = prepare(clip)
        self.assertEqual(sum(1 for x in out if x), 8000)
        self.assertEqual(max(abs(x) for x in out), 1.0)

    def test_prepare_silence(self):
        self.assertEqual(prepare([0] * 48000), [0.0] * 24000)


class ReadWavTest(unittest.TestCase):
    def test_read_wav_rejects_other_formats(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Faster rates are brought down to 16 kHz (the mic records at 48 kHz); slower ones cannot be.
            phone = Path(tmp) / "phone.wav"
            write_wav(phone, [0, 0], rate=8000)
            with self.assertRaisesRegex(ValueError, "8000 Hz"):
                read_wav(phone)

            stereo = Path(tmp) / "stereo.wav"
            write_wav(stereo, [0, 0], channels=2)
            with self.assertRaises(ValueError):
                read_wav(stereo)

            good = Path(tmp) / "good.wav"
            write_wav(good, [1, -2, 3])
            self.assertEqual(read_wav(good), [1, -2, 3])


class ToResultTest(unittest.TestCase):
    def test_to_result_threshold(self):
        wrong = to_result("rabbit", 0.5)
        self.assertEqual(wrong["error_type"], "off")
        self.assertIsNone(wrong["heard_phone"])
        self.assertEqual(wrong["confidence"], 0.5)

        right = to_result("rabbit", 0.49)
        self.assertIsNone(right["error_type"])
        self.assertEqual(right["heard_phone"], "ɹ")
        self.assertEqual(right["confidence"], 0.51)

        for d in (wrong, right):
            self.assertEqual(check(d).model, "arti-v2-soft")


if __name__ == "__main__":
    unittest.main()
