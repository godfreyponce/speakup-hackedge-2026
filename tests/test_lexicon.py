import csv
import json
import re
import unittest

from speakup import lexicon
from speakup.bank import FALLBACK_PATH, KID_WORDS
from speakup.words import load_words


def every_word_the_app_shows() -> set[str]:
    words = {w.word for w in load_words()}
    words |= {w for group in KID_WORDS.values() for w in group}
    with open(FALLBACK_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            words |= set(re.findall(r"[a-z']+", row["line"].lower()))
    return words


class LexiconTest(unittest.TestCase):
    def test_every_word_the_app_can_show_is_listed(self):
        missing = sorted(w for w in every_word_the_app_shows() if lexicon.entry(w) is None)
        self.assertEqual(missing, [])

    def test_every_practice_line_has_sounds_for_each_word(self):
        with open(FALLBACK_PATH, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                sounds = lexicon.phonemes_of(row["line"])
                for p in lexicon.entry(row["word"])["ipa"]:
                    self.assertIn(p, sounds, row["line"])

    def test_lexis_words_test_r_at_their_listed_place(self):
        for w in load_words():
            e = lexicon.entry(w.word)
            self.assertEqual(lexicon.target_of(w.word), "ɹ")
            t = e["targets"][0]
            self.assertEqual(e["ipa"][t["index"]], t["phoneme"])

    def test_rabbit(self):
        self.assertEqual(lexicon.phonemes_of("rabbit"), ["ɹ", "æ", "b", "ɪ", "t"])
        self.assertEqual(lexicon.target_context("Rabbit "), "prevocalic")

    def test_line_keeps_first_seen_order_without_repeats(self):
        self.assertEqual(lexicon.phonemes_of("a soft rabbit."), ["ə", "s", "ɔ", "f", "t", "ɹ", "æ", "b", "ɪ"])

    def test_unknown_word_is_skipped_and_target_falls_back(self):
        self.assertIsNone(lexicon.entry("zebra"))
        self.assertEqual(lexicon.phonemes_of("zebra"), [])
        self.assertEqual(lexicon.target_of("zebra"), lexicon.DEFAULT_TARGET)

    def test_carrier_words_test_nothing(self):
        for w in (w for group in KID_WORDS.values() for w in group):
            self.assertEqual(lexicon.entry(w)["targets"], [], w)

    def test_file_is_plain_ipa(self):
        with open(lexicon.LEXICON_PATH, encoding="utf-8") as f:
            data = json.load(f)
        for word, e in data["words"].items():
            self.assertTrue(e["ipa"], word)
            for p in e["ipa"]:
                self.assertNotIn(p, {"g", "r"}, f"{word}: use IPA ɡ and ɹ")


if __name__ == "__main__":
    unittest.main()
