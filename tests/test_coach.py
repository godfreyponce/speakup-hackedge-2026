import json
import unittest

from speakup import coach
from speakup.bank import fill, load_fallback
from speakup.practice import Practice
from speakup.result import Result
from speakup.words import Word, load_words

WORDS = [Word("rabbit", "start"), Word("carrot", "middle"), Word("rain", "start")]


def result(word, error_type, confidence=None):
    return Result(word=word, target_sound="r", expected_phone="ɹ", heard_phone="w" if error_type else "ɹ",
                  error_type=error_type, confidence=confidence, model="test", recorded_at="2026-11-18T22:00:00-06:00")


class CoachTest(unittest.TestCase):
    def setUp(self):
        self.bank = load_fallback(WORDS)

    def play(self, p, error_type, confidence=None):
        p.add_result(result(p.current_word.word, error_type, confidence))
        p.next(self.bank)

    def test_misses_at_the_start_keep_the_child_on_start_words(self):
        p = Practice("S-1", 96, WORDS, self.bank)
        self.play(p, "gliding")               # rabbit (start) missed
        self.play(p, None)                    # carrot (middle) right
        self.play(p, "gliding")               # start missed again: start is now weakest
        self.assertEqual(p.current_word.position, "start")
        self.assertEqual(p.tip, self.bank.tips["gliding"])  # the miss's own tip wins over the position's
        self.play(p, "off")
        self.assertEqual(p.tip, self.bank.tips[p.current_word.position])

    def test_no_tip_after_a_right_answer(self):
        p = Practice("S-1", 96, WORDS, self.bank)
        self.play(p, None)
        self.assertIsNone(p.tip)
        self.assertEqual(p.current_word, WORDS[1])

    def test_almost_there_is_a_low_confidence_miss(self):
        self.assertTrue(coach.almost(result("rain", "gliding", 0.55)))
        self.assertFalse(coach.almost(result("rain", "gliding", 0.9)))
        self.assertFalse(coach.almost(result("rain", None, 0.3)))

    def test_check_tip(self):
        approved = coach.TIPS["start"]
        coach.check_tip("Pull your tongue back and say rrr first.", approved)
        for bad in ("Put your tongue on your palate.", "", "Pull it back"):
            with self.assertRaises(ValueError):
                coach.check_tip(bad, approved)

    def test_qwen_rewording_swaps_in_only_checked_tips(self):
        reply = json.dumps({"start": "Pull your tongue back and say rrr first.",
                            "middle": "Your alveolar ridge is key.", "end": "Keep the rrr going to the end!"})
        tips = coach.parse_tips(reply)
        self.assertEqual(tips["start"], "Pull your tongue back and say rrr first.")
        self.assertEqual(tips["middle"], coach.TIPS["middle"])
        self.assertEqual(tips["end"], "Keep the rrr going to the end!")
        self.assertEqual(coach.parse_tips("not json"), coach.TIPS)

    def test_fill_rewords_tips_through_the_same_generate(self):
        words = load_words()
        def generate(prompt, grammar, n_predict):
            if "r sound" in prompt:
                return json.dumps({"start": "Pull it back and say rrr first.", "middle": "x", "end": "y"})
            return "{}"
        bank = fill(generate, words, load_fallback(words))
        self.assertEqual(bank.tips["start"], "Pull it back and say rrr first.")
        self.assertEqual(bank.tips["middle"], coach.TIPS["middle"])


if __name__ == "__main__":
    unittest.main()
