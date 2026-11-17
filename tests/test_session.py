import unittest
from datetime import date, datetime

from speakup.result import Result
from dataclasses import replace

from speakup.session import Session, agreement, arti_p_wrong, verdict_for, format_age, parse_age, parse_birth_date, parse_child_id, position_tally, tally
from speakup.words import Word

WORDS = [Word("rabbit", "start"), Word("carrot", "middle")]
HEARD = {None: "ɹ", "gliding": "w", "distortion": None}


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


class ParseTest(unittest.TestCase):
    def test_parse_age(self):
        self.assertEqual(parse_age("7", "4"), 88)
        self.assertEqual(parse_age("7", ""), 84)
        self.assertEqual(parse_age("6", "11"), 83)
        self.assertEqual(parse_age("0", "0"), 0)
        for years, months in [("seven", "0"), ("-1", "0"), ("7", "12"), ("7", "-1"), ("", "3"), ("7.5", "0")]:
            with self.subTest(years=years, months=months), self.assertRaises(ValueError):
                parse_age(years, months)

    def test_parse_child_id(self):
        self.assertEqual(parse_child_id("S-014"), "S-014")
        self.assertEqual(parse_child_id(" S-014 "), "S-014")
        for raw in ["", "Emma Smith", "../x", "a/b", "S_014"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_child_id(raw)

    def test_format_age(self):
        self.assertEqual(format_age(88), "7 yr 4 mo")
        self.assertEqual(format_age(84), "7 yr 0 mo")


class SessionTest(unittest.TestCase):
    def test_flag_uses_age_rule(self):
        self.assertFalse(Session("S-014", 83, WORDS).add_result(result("rabbit", "gliding")).flagged)
        self.assertTrue(Session("S-014", 84, WORDS).add_result(result("rabbit", "gliding")).flagged)
        self.assertFalse(Session("S-014", 200, WORDS).add_result(result("rabbit", None)).flagged)

    def test_next_waits_for_a_result(self):
        s = Session("S-014", 96, WORDS)
        s.next()
        self.assertEqual(s.current_word, WORDS[0])
        s.add_result(result("rabbit", None))
        s.next()
        self.assertEqual(s.current_word, WORDS[1])
        self.assertFalse(s.done)
        s.add_result(result("carrot", None))
        s.next()
        self.assertTrue(s.done)
        self.assertIsNone(s.current_word)
        self.assertIsNotNone(datetime.fromisoformat(s.started_at).tzinfo)

    def test_record_again_replaces(self):
        s = Session("S-014", 96, WORDS)
        s.add_result(result("rabbit", "gliding"))
        s.add_result(result("rabbit", None))
        self.assertEqual(len(s.attempts), 1)
        self.assertIsNone(s.attempts[0].result.error_type)
        self.assertEqual(s.current_attempt, s.attempts[0])

    def test_tally(self):
        s = Session("S-014", 90, WORDS)
        s.add_result(result("rabbit", None))
        self.assertEqual(tally(s.attempts), {"gliding": 0, "distortion": 0, "off": 0})
        s.add_result(result("rabbit", "gliding"))
        s.next()
        s.add_result(result("carrot", "distortion"))  # distortion flags from 84 months, so at 90 too
        self.assertEqual(tally(s.attempts), {"gliding": 1, "distortion": 1, "off": 0})

    def test_watch_uses_age_rule(self):
        for age, watched, flagged in [(59, False, False), (60, True, False), (83, True, False), (84, False, True)]:
            with self.subTest(age=age):
                a = Session("S-014", age, WORDS).add_result(result("rabbit", "gliding"))
                self.assertEqual((a.watched, a.flagged), (watched, flagged))
        self.assertFalse(Session("S-014", 70, WORDS).add_result(result("rabbit", None)).watched)


class SlpCallTest(unittest.TestCase):
    """#37: Arti's call and the SLP's call stay apart; A and D are relative to Arti's call."""

    def test_arti_call_stays_after_the_slp_call(self):
        s = Session("S-1", 96, WORDS)
        s.add_result(result("rabbit", "gliding"))
        self.assertEqual((s.current_attempt.arti_call, s.current_attempt.slp), ("wrong", None))
        a = s.verify("correct")
        self.assertEqual((a.arti_call, a.slp, a.result.error_type), ("wrong", "correct", None))

    def test_agree_and_disagree_follow_artis_call(self):
        s = Session("S-1", 96, WORDS)
        off = s.add_result(result("rabbit", "gliding"))
        self.assertEqual((verdict_for(off, "agree"), verdict_for(off, "disagree")), ("wrong", "correct"))
        right = replace(off, result=result("rabbit", None))
        self.assertEqual((verdict_for(right, "agree"), verdict_for(right, "disagree")), ("correct", "wrong"))

    def test_agree_after_a_check_still_means_artis_call(self):
        s = Session("S-1", 96, WORDS)
        s.add_result(result("rabbit", "gliding"))
        a = s.verify("correct")
        self.assertEqual(verdict_for(a, "agree"), "wrong")

    def test_verdict_for_passes_correct_and_wrong_through_and_refuses_others(self):
        s = Session("S-1", 96, WORDS)
        a = s.add_result(result("rabbit", None))
        self.assertEqual((verdict_for(a, "correct"), verdict_for(a, "wrong")), ("correct", "wrong"))
        with self.assertRaises(ValueError):
            verdict_for(a, "maybe")

    def test_arti_p_wrong_from_its_confidence(self):
        s = Session("S-1", 96, WORDS)
        a = s.add_result(replace(result("rabbit", "distortion"), confidence=0.8))
        self.assertAlmostEqual(arti_p_wrong(s.verify("correct")), 0.8)
        b = replace(a, result=replace(result("rabbit", None), confidence=0.7), arti=None)
        self.assertAlmostEqual(arti_p_wrong(b), 0.3)
        self.assertIsNone(arti_p_wrong(replace(b, result=result("rabbit", None))))

    def test_arti_p_wrong_is_rounded_like_the_stored_confidence(self):
        a = Session("S-1", 96, WORDS).add_result(replace(result("rabbit", None), confidence=0.7))
        self.assertEqual(arti_p_wrong(a), 0.3)  # 1 - 0.7 is 0.30000000000000004, past a band edge at 0.3


if __name__ == "__main__":
    unittest.main()


class SlpCheckTest(unittest.TestCase):
    """The SLP's verdict (lab UI): it replaces Arti's call for flags, tally and saving, and is counted."""

    def session(self, age_months=96):
        return Session("S-1", age_months, WORDS)

    def test_verify_wrong_on_a_right_call_becomes_off_and_flags(self):
        s = self.session()
        s.add_result(result("rabbit", None))
        a = s.verify("wrong")
        self.assertEqual((a.result.error_type, a.result.heard_phone, a.flagged, a.slp), ("off", None, True, "wrong"))
        self.assertIsNone(a.arti.error_type)

    def test_verify_wrong_keeps_arti_error_type(self):
        s = self.session()
        s.add_result(result("rabbit", "gliding"))
        self.assertEqual(s.verify("wrong").result.error_type, "gliding")

    def test_verify_twice_keeps_the_first_arti_call(self):
        s = self.session()
        s.add_result(result("rabbit", "gliding"))
        s.verify("correct")
        a = s.verify("wrong")
        self.assertEqual(a.arti.error_type, "gliding")
        self.assertEqual(a.result.model, "test")

    def test_verify_needs_a_recording_and_a_known_verdict(self):
        s = self.session()
        with self.assertRaises(ValueError):
            s.verify("correct")
        s.add_result(result("rabbit", None))
        with self.assertRaises(ValueError):
            s.verify("maybe")

    def test_position_tally_counts_only_checked_words_by_the_slp_call(self):
        s = self.session()
        s.add_result(result("rabbit", "gliding"))
        s.verify("correct")
        s.next()
        s.add_result(result("carrot", "gliding"))  # not checked yet
        self.assertEqual(position_tally(s.attempts), {"start": (1, 0)})
        s.verify("wrong")
        self.assertEqual(position_tally(s.attempts), {"start": (1, 0), "middle": (0, 1)})

    def test_agreement_counts_only_checked_words(self):
        s = self.session()
        s.add_result(result("rabbit", "gliding"))
        s.verify("wrong")  # agrees
        s.next()
        s.add_result(result("carrot", None))  # not checked
        self.assertEqual(agreement(s.attempts), (1, 1))
        s.verify("wrong")  # disagrees
        self.assertEqual(agreement(s.attempts), (1, 2))


class BirthDateTest(unittest.TestCase):
    def test_whole_months_turn_on_the_day_of_the_month(self):
        today = date(2026, 11, 4)
        self.assertEqual(parse_birth_date("2018-11-04", today), 96)  # 8th birthday today
        self.assertEqual(parse_birth_date("2018-11-05", today), 95)  # tomorrow
        self.assertEqual(parse_birth_date("2018-09-30", today), 97)
        self.assertEqual(parse_birth_date(" 2018-11-04 ", today), 96)

    def test_bad_or_unlikely_dates_are_refused(self):
        today = date(2026, 11, 4)
        for raw in ["", "11/04/2018", "2018-13-01", "2026-11-05", "2025-01-01", "1990-01-01"]:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_birth_date(raw, today)


class GoBackTest(unittest.TestCase):
    """One slot per word: the SLP can reopen any word, and Next goes to the next word not yet recorded."""

    def setUp(self):
        self.words = [Word("rabbit", "start"), Word("carrot", "middle"), Word("car", "end")]
        self.s = Session("S-1", 96, self.words)

    def test_go_back_and_record_again_replaces_only_that_word(self):
        self.s.add_result(result("rabbit", None)); self.s.next()
        self.s.add_result(result("carrot", None)); self.s.next()
        self.s.go(0)
        self.s.add_result(result("rabbit", "gliding"))
        self.assertEqual([a.result.error_type for a in self.s.attempts], ["gliding", None])
        self.s.next()
        self.assertEqual(self.s.index, 2)  # the first word not yet recorded

    def test_next_wraps_to_a_skipped_word_then_finishes(self):
        self.s.go(1)
        self.s.add_result(result("carrot", None)); self.s.next()
        self.assertEqual(self.s.index, 2)
        self.s.add_result(result("car", None)); self.s.next()
        self.assertEqual(self.s.index, 0)
        self.s.add_result(result("rabbit", None)); self.s.next()
        self.assertTrue(self.s.done)
        self.assertEqual([a.word.word for a in self.s.attempts], ["rabbit", "carrot", "car"])

    def test_finish_early_leaves_unrecorded_words_out(self):
        self.s.add_result(result("rabbit", None))
        self.s.finish()
        self.assertTrue(self.s.done)
        self.assertEqual(len(self.s.attempts), 1)
        with self.assertRaises(ValueError):
            self.s.go(0)

    def test_go_rejects_a_bad_index(self):
        with self.assertRaises(ValueError):
            self.s.go(3)

    def test_verify_can_be_changed_and_keeps_artis_answer(self):
        self.s.add_result(result("rabbit", "gliding"))
        self.s.verify("correct")
        a = self.s.verify("wrong")
        self.assertEqual(a.slp, "wrong")
        self.assertEqual(a.arti.error_type, "gliding")
        self.assertEqual(a.result.error_type, "gliding")
        self.assertEqual(a.result.model, "test")
