import os
import tempfile
import unittest

from speakup.words import POSITIONS, load_words


class LoadWordsTest(unittest.TestCase):
    def test_shipped_list_loads_and_covers_every_position(self):
        words = load_words()
        self.assertTrue(words)
        self.assertEqual({w.position for w in words}, set(POSITIONS))

    def _load(self, text):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return load_words(path)

    def test_comment_lines_are_skipped(self):
        words = self._load("# a note\nword,position\nrabbit,start\n")
        self.assertEqual([(w.word, w.position) for w in words], [("rabbit", "start")])

    def test_bad_position_raises(self):
        for position in ("initial", "Start", ""):
            with self.assertRaises(ValueError):
                self._load(f"word,position\nrabbit,{position}\n")

    def test_empty_word_raises(self):
        with self.assertRaises(ValueError):
            self._load("word,position\n,start\n")
