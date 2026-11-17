import unittest

from speakup.bank import load_fallback
from speakup.practice import Practice, next_level
from speakup.result import Result
from speakup.words import Word

WORDS = [Word("rabbit", "start"), Word("carrot", "middle")]
HEARD = {None: "ɹ", "gliding": "w"}


def result(word, error_type):
    return Result(
        word=word,
        target_sound="r",
        expected_phone="ɹ",
        heard_phone=HEARD[error_type],
        error_type=error_type,
        confidence=None,
        model="test",
        recorded_at="2026-11-05T10:15:00-06:00",
    )


class NextLevelTest(unittest.TestCase):
    def test_up_one_on_right(self):
        self.assertEqual(next_level("word", True), "phrase")
        self.assertEqual(next_level("phrase", True), "sentence")

    def test_down_one_on_miss(self):
        self.assertEqual(next_level("sentence", False), "phrase")
        self.assertEqual(next_level("phrase", False), "word")

    def test_top_stays(self):
        self.assertEqual(next_level("sentence", True), "sentence")

    def test_bottom_stays(self):
        self.assertEqual(next_level("word", False), "word")


class PracticeTest(unittest.TestCase):
    def setUp(self):
        self.bank = load_fallback(WORDS)

    def practice(self, age_months=96):
        return Practice("S-014", age_months, WORDS, self.bank)

    def test_practice_walks_words_and_levels(self):
        p = self.practice()
        self.assertEqual((p.current_word, p.level, p.line), (WORDS[0], "word", "rabbit"))
        p.add_result(result("rabbit", None))
        p.next(self.bank)
        self.assertEqual((p.current_word, p.level, p.line), (WORDS[1], "phrase", "a long carrot"))

    def test_next_waits_for_a_result(self):
        p = self.practice()
        p.next(self.bank)
        self.assertEqual((p.turn, p.level), (0, "word"))

    def test_record_again_replaces(self):
        p = self.practice()
        p.add_result(result("rabbit", "gliding"))
        p.add_result(result("rabbit", None))
        self.assertEqual(len(p.attempts), 1)
        p.next(self.bank)
        self.assertEqual(p.level, "phrase")

    def test_attempt_carries_level_line_and_age_rule(self):
        p = self.practice(age_months=90)
        p.add_result(result("rabbit", None))
        p.next(self.bank)
        attempt = p.add_result(result("carrot", "gliding"))
        self.assertEqual((attempt.level, attempt.line, attempt.flagged), ("phrase", "a long carrot", True))

    def test_words_wrap_around(self):
        p = self.practice()
        for word in WORDS:
            p.add_result(result(word.word, None))
            p.next(self.bank)
        self.assertEqual(p.current_word, WORDS[0])
        self.assertEqual(len(p.attempts), 2)


if __name__ == "__main__":
    unittest.main()
