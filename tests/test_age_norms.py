import unittest

from speakup.age_norms import AGE_NORMS, explain, should_flag, should_watch


class ShouldFlagTest(unittest.TestCase):
    def test_band_edges(self):
        for error_type in ("gliding", "distortion", "off"):
            with self.subTest(error_type):
                self.assertEqual((should_watch(error_type, "r", 59), should_flag(error_type, "r", 59)), (False, False))
                self.assertEqual((should_watch(error_type, "r", 60), should_flag(error_type, "r", 60)), (True, False))
                self.assertEqual((should_watch(error_type, "r", 83), should_flag(error_type, "r", 83)), (True, False))
                self.assertEqual((should_watch(error_type, "r", 84), should_flag(error_type, "r", 84)), (False, True))

    def test_correct_sound_never_flags(self):
        for age in (0, 60, 83, 84, 96, 200):
            self.assertFalse(should_flag(None, "r", age))
            self.assertFalse(should_watch(None, "r", age))
        self.assertFalse(should_flag(None, "s", 200))
        self.assertFalse(should_watch(None, "s", 200))

    def test_unknown_error_type_raises(self):
        for error_type in ("stopping", "Gliding", ""):
            with self.assertRaises(ValueError):
                should_flag(error_type, "r", 100)
            with self.assertRaises(ValueError):
                should_watch(error_type, "r", 100)

    def test_unknown_sound_raises(self):
        with self.assertRaises(ValueError):
            should_flag("gliding", "s", 100)
        with self.assertRaises(ValueError):
            should_watch("gliding", "s", 100)

    def test_every_row_cites_asha(self):
        for norm in AGE_NORMS.values():
            self.assertTrue(norm.source.startswith("https://www.asha.org/"))


class ExplainTest(unittest.TestCase):
    def test_explains_both_sides_of_the_cutoff(self):
        self.assertEqual(explain("gliding", "r", 84),
                         "Flagged: this error is expected to be gone by 7 yr 0 mo, and the child is 7 yr 0 mo.")
        self.assertEqual(explain("gliding", "r", 83),
                         "Not flagged: this error is still common until 7 yr 0 mo, and the child is 6 yr 11 mo. "
                     "Keep an eye on it: it is worth watching from 5 yr 0 mo.")

    def test_correct_sound_has_no_explanation(self):
        self.assertEqual(explain(None, "r", 100), "")

    def test_explain_agrees_with_should_flag_everywhere(self):
        for (sound, error_type), norm in AGE_NORMS.items():
            for age in range(norm.flag_from_months - 2, norm.flag_from_months + 2):
                self.assertEqual(explain(error_type, sound, age).startswith("Flagged"),
                                 should_flag(error_type, sound, age))
