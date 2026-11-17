"""The word pick (speakup/segment.py) on synthetic recordings: bursts of tone in a quiet room."""

import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from speakup import segment


def clip(pieces, rate=16000, noise=0.002, seed=1):
    """pieces: (seconds, amplitude) runs; amplitude 0 is the room, a positive one a 200 Hz voice-like tone, a
    negative one a burst of hiss (a cough, a click's ring, breath) with no pitch."""
    rng = np.random.default_rng(seed)
    parts = []
    for seconds, amp in pieces:
        n = int(seconds * rate)
        t = np.arange(n) / rate
        if amp < 0:
            parts.append(-amp * rng.normal(0, 0.5, n))
        else:
            parts.append(amp * np.sin(2 * np.pi * 200 * t) if amp else np.zeros(n))
    x = np.concatenate(parts)
    return x + rng.normal(0, noise, len(x))


def write(path, x, rate=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


class StretchTest(unittest.TestCase):
    def test_finds_voiced_stretches(self):
        x = clip([(0.5, 0), (0.4, 0.5), (0.6, 0), (0.3, 0.5), (0.5, 0)])
        found = segment.stretches(x, 16000, segment.WORD_JOIN)
        self.assertEqual(len(found), 2)
        self.assertAlmostEqual(found[0][0], 0.5, delta=0.02)
        self.assertAlmostEqual(found[0][1], 0.9, delta=0.02)
        self.assertAlmostEqual(found[1][0], 1.5, delta=0.02)

    def test_short_gap_inside_a_word_is_joined(self):
        # A 100 ms stop closure (the b in rabbit) does not split the word.
        x = clip([(0.4, 0), (0.2, 0.5), (0.1, 0), (0.25, 0.5), (0.4, 0)])
        self.assertEqual(len(segment.stretches(x, 16000, segment.WORD_JOIN)), 1)
        self.assertEqual(len(segment.stretches(x, 16000, segment.PHRASE_JOIN)), 2)

    def test_clicks_are_not_words(self):
        x = clip([(0.4, 0), (0.02, 0.8), (0.4, 0), (0.3, 0.4), (0.4, 0)])
        found = segment.stretches(x, 16000, segment.WORD_JOIN)
        self.assertEqual(len(found), 1)
        self.assertAlmostEqual(found[0][0], 0.82, delta=0.02)

    def test_room_only_has_no_stretch(self):
        self.assertEqual(segment.stretches(clip([(2.0, 0)]), 16000, segment.WORD_JOIN), [])


class WordPickTest(unittest.TestCase):
    def test_single_word_takes_the_first_whole_word_padded(self):
        # A short "um" (under 0.15 s), then the word, then a short burst.
        x = clip([(0.3, 0), (0.12, 0.3), (0.5, 0), (0.55, 0.5), (0.6, 0), (0.1, 0.6), (0.4, 0)])
        sel = segment.pick(x, 16000, "rabbit", "rabbit")
        self.assertEqual(sel.method, "word")
        self.assertTrue(sel.auto)
        self.assertAlmostEqual(sel.start, 0.92 - segment.PAD, delta=0.02)
        self.assertAlmostEqual(sel.end, 1.47 + segment.PAD, delta=0.02)

    def test_a_long_burst_with_no_pitch_is_not_the_word(self):
        # Board, Nov 12: a cough or a click's ring longer than the word took the box.
        x = clip([(0.3, 0), (0.4, 0.3), (0.8, 0), (1.0, -0.4), (0.4, 0)])
        sel = segment.pick(x, 16000, "rabbit", "rabbit")
        self.assertAlmostEqual(sel.start, 0.3 - segment.PAD, delta=0.02)
        self.assertAlmostEqual(sel.end, 0.7 + segment.PAD, delta=0.02)

    def test_the_first_word_beats_louder_talk_after_it(self):
        # Board, Nov 12: the child said "rocket", then talked; the talk was longer and louder.
        x = clip([(0.3, 0), (0.4, 0.2), (1.0, 0), (1.2, 0.6), (0.4, 0)])
        sel = segment.pick(x, 16000, "rocket", "rocket")
        self.assertAlmostEqual(sel.start, 0.3 - segment.PAD, delta=0.02)
        self.assertAlmostEqual(sel.end, 0.7 + segment.PAD, delta=0.02)

    def test_no_speech_gives_the_whole_clip(self):
        sel = segment.pick(clip([(1.5, 0)]), 16000, "rabbit", "rabbit")
        self.assertEqual((sel.method, sel.start), ("whole", 0.0))
        self.assertAlmostEqual(sel.end, 1.5, delta=0.01)

    def test_works_at_48k(self):
        x = clip([(0.3, 0), (0.5, 0.5), (0.3, 0)], rate=48000)
        sel = segment.pick(x, 48000, "car", "car")
        self.assertAlmostEqual(sel.start, 0.25, delta=0.02)
        self.assertAlmostEqual(sel.end, 0.85, delta=0.02)


class PhrasePickTest(unittest.TestCase):
    def test_one_stretch_per_word_takes_the_targets_place(self):
        # "a soft rabbit": three stretches, the target is the third.
        x = clip([(0.3, 0), (0.12, 0.4), (0.15, 0), (0.3, 0.4), (0.15, 0), (0.45, 0.4), (0.4, 0)])
        sel = segment.pick(x, 16000, "a soft rabbit", "rabbit")
        self.assertEqual(sel.method, "count")
        self.assertAlmostEqual(sel.start, 1.02 - segment.PAD, delta=0.02)
        self.assertAlmostEqual(sel.end, 1.47 + segment.PAD, delta=0.02)

    def test_run_together_words_share_by_sound_count(self):
        # "the cold rain" said without gaps: one long stretch, 0.3 to 1.5 s. Each word's share of the speech is
        # its sound count (lexicon, else letters), so rain gets the last part; the counts come from
        # segment.sound_count so the test follows the lexicon as it grows.
        x = clip([(0.3, 0), (1.2, 0.4), (0.4, 0)])
        sel = segment.pick(x, 16000, "the cold rain", "rain")
        self.assertEqual(sel.method, "share")
        counts = [segment.sound_count(w) for w in ("the", "cold", "rain")]
        share = 1.2 * counts[2] / sum(counts)
        self.assertAlmostEqual(sel.start, 1.5 - share - share / 4 - segment.PAD, delta=0.03)  # a quarter-share margin
        self.assertAlmostEqual(sel.end, 1.5 + segment.PAD, delta=0.03)

    def test_extra_stretches_pick_the_one_covering_the_share(self):
        # "my dog sees a fast rocket" with a pause in rocket's k: more stretches than words.
        x = clip([(0.3, 0), (0.15, 0.4), (0.1, 0), (0.2, 0.4), (0.1, 0), (0.25, 0.4), (0.1, 0), (0.05, 0.4),
                  (0.1, 0), (0.3, 0.4), (0.1, 0), (0.25, 0.4), (0.12, 0), (0.2, 0.4), (0.4, 0)])
        sel = segment.pick(x, 16000, "my dog sees a fast rocket", "rocket")
        self.assertEqual(sel.method, "share")
        # rocket is the last two stretches, 1.75 to 2.0 and 2.12 to 2.32: both are taken.
        self.assertAlmostEqual(sel.start, 1.75 - segment.PAD, delta=0.02)
        self.assertAlmostEqual(sel.end, 2.32 + segment.PAD, delta=0.02)

    def test_hiss_after_the_sentence_is_not_its_last_word(self):
        # Board, Nov 12: noise after "... a big rocket." counted as speech, and the box landed in it.
        x = clip([(0.3, 0), (0.3, 0.4), (0.15, 0), (0.3, 0.4), (0.15, 0), (0.4, 0.4), (0.2, 0), (1.2, -0.05),
                  (0.3, 0)])
        sel = segment.pick(x, 16000, "a big rocket", "rocket")
        self.assertAlmostEqual(sel.start, 1.2 - segment.PAD, delta=0.03)
        self.assertAlmostEqual(sel.end, 1.6 + segment.PAD, delta=0.03)

    def test_plural_still_finds_the_target(self):
        self.assertEqual(segment.target_index(["two", "rabbits"], "rabbit"), 1)
        self.assertIsNone(segment.target_index(["a", "dog"], "rabbit"))

    def test_target_missing_from_line_falls_back_to_the_longest(self):
        x = clip([(0.3, 0), (0.1, 0.4), (0.2, 0), (0.6, 0.4), (0.3, 0)])
        self.assertEqual(segment.pick(x, 16000, "a dog", "rabbit").method, "word")

    def test_sound_count_uses_the_lexicon_then_letters(self):
        self.assertEqual(segment.sound_count("rabbit"), 5)
        self.assertEqual(segment.sound_count("dog"), 3)

    def test_an_aligner_wins_when_it_answers(self):
        x = clip([(0.3, 0), (1.0, 0.4), (0.3, 0)])
        seen = {}

        def aligner(samples, rate, words, index):
            seen["args"] = (rate, words, index)
            return (0.8, 1.1)

        sel = segment.pick(x, 16000, "a fast rocket", "rocket", aligner=aligner)
        self.assertEqual((sel.start, sel.end, sel.method), (0.8, 1.1, "aligner"))
        self.assertEqual(seen["args"], (16000, ["a", "fast", "rocket"], 2))
        fallback = segment.pick(x, 16000, "a fast rocket", "rocket", aligner=lambda *a: None)
        self.assertEqual(fallback.method, "share")


class CropTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_crop_keeps_rate_and_length(self):
        src = write(self.dir / "full.wav", clip([(2.0, 0.3)], rate=48000), rate=48000)
        dst = self.dir / "full-word.wav"
        segment.crop(src, dst, 0.5, 1.25)
        with wave.open(str(dst)) as w:
            self.assertEqual(w.getframerate(), 48000)
            self.assertEqual(w.getnframes(), int(0.75 * 48000))

    def test_clamp_keeps_the_box_inside_and_at_least_50_ms(self):
        self.assertEqual(segment.clamp(-1, 9, 2.0), (0.0, 2.0))
        self.assertEqual(segment.clamp(1.2, 0.4, 2.0), (0.4, 1.2))  # swapped edges
        self.assertEqual(segment.clamp(1.99, 1.995, 2.0), (1.95, 2.0))
        with self.assertRaises(ValueError):
            segment.clamp(float("nan"), 1, 2.0)

    def test_peaks_for_the_waveform(self):
        src = write(self.dir / "p.wav", clip([(0.5, 0), (0.5, 0.5)]))
        duration, peaks = segment.peaks(src, columns=10)
        self.assertAlmostEqual(duration, 1.0, places=2)
        self.assertEqual(len(peaks), 10)
        self.assertLess(max(peaks[:5]), 0.1)
        self.assertGreater(min(peaks[5:]), 0.9)


if __name__ == "__main__":
    unittest.main()
