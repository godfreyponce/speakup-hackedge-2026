import random
import unittest

from speakup.fake_model import fake_listen
from speakup.result import Result, check

GOOD = {
    "word": "rabbit",
    "target_sound": "r",
    "expected_phone": "ɹ",
    "heard_phone": "w",
    "error_type": "gliding",
    "confidence": 0.82,
    "model": "arti-v0",
    "recorded_at": "2026-11-05T10:15:00-06:00",
}


def with_(**changes):
    return {**GOOD, **changes}


class CheckTest(unittest.TestCase):
    def test_good_record_passes(self):
        self.assertEqual(check(GOOD), Result(**GOOD))

    def test_correct_word_with_nulls_passes(self):
        check(with_(heard_phone="ɹ", error_type=None, confidence=None))

    def test_missing_field_fails(self):
        bad = dict(GOOD)
        del bad["word"]
        with self.assertRaisesRegex(ValueError, "word"):
            check(bad)

    def test_extra_field_fails(self):
        with self.assertRaisesRegex(ValueError, "child_name"):
            check(with_(child_name="Sam"))

    def test_unknown_error_type_fails(self):
        with self.assertRaisesRegex(ValueError, "error_type"):
            check(with_(error_type="stopping"))

    def test_off_with_no_heard_phone(self):
        self.assertEqual(check(with_(error_type="off", heard_phone=None)).error_type, "off")

    def test_confidence_out_of_range_fails(self):
        with self.assertRaisesRegex(ValueError, "confidence"):
            check(with_(confidence=1.5))

    def test_confidence_bool_fails(self):
        with self.assertRaisesRegex(ValueError, "confidence"):
            check(with_(confidence=True))

    def test_empty_word_fails(self):
        with self.assertRaisesRegex(ValueError, "word"):
            check(with_(word=""))

    def test_bad_timestamp_fails(self):
        with self.assertRaisesRegex(ValueError, "recorded_at"):
            check(with_(recorded_at="yesterday"))

    def test_timestamp_without_offset_fails(self):
        with self.assertRaisesRegex(ValueError, "recorded_at"):
            check(with_(recorded_at="2026-11-05T10:15:00"))

    def test_error_without_heard_phone_is_allowed(self):
        check(with_(error_type="distortion", heard_phone=None))

    def test_correct_needs_heard_phone_to_match(self):
        with self.assertRaisesRegex(ValueError, "heard_phone"):
            check(with_(error_type=None, heard_phone="w"))


class FakeModelTest(unittest.TestCase):
    def test_every_answer_is_valid(self):
        rng = random.Random(0)
        for _ in range(200):
            check(fake_listen("rabbit", rng))

    def test_echoes_the_word(self):
        self.assertEqual(fake_listen("carrot", random.Random(0))["word"], "carrot")

    def test_gives_all_three_outcomes(self):
        rng = random.Random(0)
        seen = {fake_listen("rabbit", rng)["error_type"] for _ in range(200)}
        self.assertEqual(seen, {None, "gliding", "distortion"})

    def test_names_itself(self):
        self.assertEqual(fake_listen("rabbit")["model"], "fake")


if __name__ == "__main__":
    unittest.main()
