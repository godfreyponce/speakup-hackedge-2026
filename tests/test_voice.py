import tempfile
import unittest
from pathlib import Path

import numpy as np

from speakup import voice
from tests.test_acoustics import synth
from tests.test_acoustics import write as write_voice


class AlphaTest(unittest.TestCase):
    def test_grid(self):
        self.assertEqual(voice.ALPHAS[0], 1.0)
        self.assertEqual(voice.ALPHAS[-1], 1.4)
        self.assertEqual(voice.snap(1.27), 1.25)

    def test_alpha_from_pitch(self):
        self.assertEqual(voice.alpha_for(100.0), 1.3)  # an adult man
        self.assertEqual(voice.alpha_for(165.0), 1.15)  # an adult woman
        self.assertEqual(voice.alpha_for(260.0), 1.0)  # a child: no stretch
        self.assertEqual(voice.alpha_for(60.0), 1.4)  # clamped
        self.assertEqual(voice.alpha_for(None), voice.ALPHA_FALLBACK)

    def test_hint_is_only_sure_for_a_low_voice(self):
        self.assertEqual(voice.hint(110.0), "adult-man")
        self.assertEqual(voice.hint(180.0), "unclear")
        self.assertEqual(voice.hint(250.0), "child-or-woman")
        self.assertEqual(voice.hint(None), "unclear")


class MelTest(unittest.TestCase):
    def test_shape_and_identity(self):
        bank = voice.mel_bank(1.0)
        self.assertEqual(bank.shape, (40, 201))
        self.assertEqual(bank.dtype, np.float32)

    def test_stretch_moves_every_band_down(self):
        plain, stretched = voice.mel_bank(1.0), voice.mel_bank(1.25)
        bins = np.arange(201)
        for m in range(5, 35):
            centre = (bins * plain[m]).sum() / plain[m].sum()
            moved = (bins * stretched[m]).sum() / stretched[m].sum()
            self.assertAlmostEqual(moved, centre / 1.25, delta=1.0)

    def test_stretch_keeps_band_weight(self):
        plain, stretched = voice.mel_bank(1.0), voice.mel_bank(1.25)
        np.testing.assert_allclose(stretched[10:30].sum(axis=1), plain[10:30].sum(axis=1), rtol=0.05)

    def test_matches_the_model_file(self):
        try:
            import onnx
            from onnx import numpy_helper
        except ImportError:
            self.skipTest("onnx not installed (laptop check only)")
        model = onnx.load(str(Path(__file__).parents[1] / "models" / "arti-v0.onnx"))
        [mel] = [numpy_helper.to_array(i) for i in model.graph.initializer if i.name == "frontend.mel"]
        np.testing.assert_allclose(voice.mel_bank(1.0), mel, atol=1e-5)


class PitchTest(unittest.TestCase):
    def test_pitch_of_a_synthetic_voice(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "v.wav"
            write_voice(path, synth(120, [(500, 80), (1500, 100), (2500, 120)]))
            self.assertAlmostEqual(voice.pitch(path), 120, delta=6)


class ReadingTest(unittest.TestCase):
    def test_stable_when_neighbours_agree(self):
        self.assertTrue(voice.Reading(1.3, 0.8, ((1.25, 0.7), (1.35, 0.9)), 0.2).stable)
        self.assertFalse(voice.Reading(1.3, 0.6, ((1.25, 0.4), (1.35, 0.9)), 0.2).stable)


class StretcherTest(unittest.TestCase):
    def test_arti_runs_at_every_alpha(self):
        try:
            import onnxruntime  # noqa: F401
        except ImportError:
            self.skipTest("onnxruntime not installed")
        st = voice.Stretcher(Path(__file__).parents[1] / "models" / "arti-v0.onnx", 1)
        audio = np.zeros((1, 24000), dtype=np.float32)
        audio[0, ::40] = 0.5
        reading = st.read(audio, 1.3)
        self.assertEqual(reading.alpha, 1.3)
        self.assertEqual([a for a, _ in reading.neighbours], [1.25, 1.35])
        self.assertTrue(0.0 <= reading.p_wrong <= 1.0)


if __name__ == "__main__":
    unittest.main()
