import unittest

from speakup.demo_model import check_script, demo_listen
from speakup.result import check
from speakup.words import Word, load_words


class DemoModelTest(unittest.TestCase):
    def test_script_covers_shipped_words(self):
        # When words.csv changes, this fails until the script is updated. On purpose.
        check_script(load_words())

    def test_missing_word_is_named(self):
        with self.assertRaises(ValueError) as caught:
            check_script([Word("zebra", "start")])
        self.assertIn("zebra", str(caught.exception))

    def test_demo_listen_follows_script(self):
        rabbit = check(demo_listen("rabbit"))
        self.assertEqual(rabbit.error_type, "gliding")
        self.assertEqual(rabbit.heard_phone, "w")
        self.assertEqual(rabbit.model, "demo")
        rain = check(demo_listen("rain"))
        self.assertIsNone(rain.error_type)
        self.assertEqual(rain.heard_phone, "ɹ")


if __name__ == "__main__":
    unittest.main()
