import os
import pickle
import tempfile
import unittest
import zipfile
from collections import Counter

from scripts.pick_test_set import (
    CELLS,
    END_WORDS,
    START_WORDS,
    listener_says,
    pick,
    read_float,
    read_int,
    write_outputs,
)

TRIPPED = []


def _trip():
    TRIPPED.append(True)


class _Trip:
    def __reduce__(self):
        return (_trip, ())


def _f(x):
    return pickle.dumps(x, protocol=4)


# speaker: (age pickle, [(word, take, label pickle), ...])
SPEAKERS = {
    "1": (_f(100), [("red", 1, _f(0.0)), ("red", 2, _f(1.0)), ("rug", 1, _f(0.9)),
                    ("door", 1, _f(0.1)), ("star", 1, _f(0.8)), ("cheer", 1, _f(0.0)),
                    ("rah", 1, _f(0.0))]),
    "2": (_f(144), [("red", 1, _f(0.25)), ("run", 1, _f(0.75)), ("door", 1, _f(0.75)),
                    ("chair", 1, _f(0.25)), ("pear", 1, _f(0.5)),
                    ("floor", 1, pickle.dumps("NA")), ("hair", 1, pickle.dumps(_Trip()))]),
    "3": (_f(120), [("rock", 1, _f(0.0)), ("rose", 1, _f(1.0)), ("deer", 1, _f(0.0)),
                    ("bear", 1, _f(1.0))]),
    "4": (_f(72), [("ring", 1, _f(0.1)), ("rain", 1, _f(0.9)), ("car", 1, _f(0.2)),
                   ("hair", 1, _f(0.95))]),
    "5": (_f(145), [("red", 1, _f(0.0)), ("rug", 1, _f(1.0)), ("door", 1, _f(0.0)),
                    ("star", 1, _f(1.0))]),
    "6": (pickle.dumps("ten"), [("red", 1, _f(0.0))]),
}
AGES = {"1": 100, "2": 144, "3": 120, "4": 72}


def _make_zip(path, speakers):
    root = "FAKE 1.0py"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(f"{root}/README.txt", "fake corpus")
        for sid, (age, clips) in speakers.items():
            zf.writestr(f"{root}/{sid}/metadata/age.pickle", age)
            for word, take, label in clips:
                stem = f"{sid}_X_A-1_{word}_{take}"
                zf.writestr(f"{root}/{sid}/audio/{stem}.wav", b"")
                zf.writestr(f"{root}/{sid}/rhotic_perceptual_labels/{stem}.pickle", label)


class PickTestSetTest(unittest.TestCase):
    def setUp(self):
        TRIPPED.clear()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.zip = os.path.join(self._tmp.name, "corpus.zip")
        _make_zip(self.zip, SPEAKERS)

    def test_read_float_accepts_one_float_only(self):
        self.assertEqual(read_float(_f(0.111)), 0.111)
        for data in (pickle.dumps("NA"), pickle.dumps([0.5]), pickle.dumps(1),
                     b"not a pickle", pickle.dumps(_Trip())):
            self.assertIsNone(read_float(data), data)
        self.assertEqual(TRIPPED, [])

    def test_read_int(self):
        self.assertEqual(read_int(_f(110)), 110)
        self.assertEqual(read_int(_f(288)), 288)
        self.assertIsNone(read_int(pickle.dumps(0.5)))
        self.assertIsNone(read_int(pickle.dumps("ten")))

    def test_label_rule(self):
        self.assertEqual(listener_says(0.0), "wrong")
        self.assertEqual(listener_says(0.25), "wrong")
        self.assertEqual(listener_says(0.75), "correct")
        self.assertEqual(listener_says(1.0), "correct")
        for label in (0.26, 0.5, 0.74):
            self.assertIsNone(listener_says(label), label)

    def test_counts_per_cell(self):
        p = pick(self.zip, per_cell=2)
        counts = Counter((row[4], row[6]) for row in p.rows)
        self.assertEqual(counts, {cell: 2 for cell in CELLS})
        self.assertEqual(len(p.rows), 8)

    def test_age_filter_and_word_lists(self):
        p = pick(self.zip, per_cell=2)
        for row in p.rows:
            zip_path, speaker, age, word, position, label, says = row
            self.assertNotIn(speaker, ("5", "6"))
            self.assertTrue((word in START_WORDS and position == "start")
                            or (word in END_WORDS and position == "end"), row)
            self.assertNotIn(word, ("cheer", "rah", "pear"))
            self.assertEqual(age, AGES[speaker])
        self.assertNotIn("5", p.test_speakers)
        self.assertNotIn("6", p.test_speakers)
        self.assertEqual(p.children, 4)
        self.assertEqual(p.skipped_speakers, 1)

    def test_hold_out_and_one_clip_per_speaker_word(self):
        # Speaker 1 has a clear-wrong and a clear-correct take of red; only some
        # seeds hold speaker 1 out, so walk enough seeds to include them.
        held_two_take_speaker = False
        for seed in range(50):
            p = pick(self.zip, per_cell=2, seed=seed)
            held_two_take_speaker |= "1" in p.test_speakers
            for row in p.rows:
                self.assertIn(row[1], p.test_speakers)
            pairs = [(row[1], row[3]) for row in p.rows]
            self.assertEqual(len(pairs), len(set(pairs)), seed)
        self.assertTrue(held_two_take_speaker)

        p = pick(self.zip, per_cell=2)
        self.assertEqual(p.clips_total, 27)
        removed = sum(len(SPEAKERS[sid][1]) for sid in p.test_speakers)
        self.assertEqual(p.clips_removed, removed)

    def test_bad_labels_are_skipped_counted_and_never_loaded(self):
        p = pick(self.zip, per_cell=2)
        self.assertEqual(p.skipped_labels, 2)
        for row in p.rows:
            self.assertFalse(row[0].endswith("2_X_A-1_floor_1.wav"))
            self.assertFalse(row[0].endswith("2_X_A-1_hair_1.wav"))
        self.assertEqual(TRIPPED, [])

    def test_two_runs_byte_identical(self):
        dir_a = os.path.join(self._tmp.name, "a")
        dir_b = os.path.join(self._tmp.name, "b")
        os.mkdir(dir_a)
        os.mkdir(dir_b)
        p = pick(self.zip, per_cell=2)
        write_outputs(p, dir_a)
        write_outputs(pick(self.zip, per_cell=2), dir_b)
        for name in ("test-set.csv", "test-speakers.txt"):
            with open(os.path.join(dir_a, name), "rb") as a, open(os.path.join(dir_b, name), "rb") as b:
                self.assertEqual(a.read(), b.read(), name)
        with open(os.path.join(dir_a, "test-set.csv"), encoding="utf-8") as f:
            self.assertEqual(f.readline(),
                             "zip_path,speaker,age_months,word,position,label,listener_says\n")
        with open(os.path.join(dir_a, "test-speakers.txt"), encoding="utf-8") as f:
            self.assertEqual(f.read().splitlines(), p.test_speakers)

    def test_not_enough_clips_raises(self):
        with self.assertRaises(ValueError) as caught:
            pick(self.zip, per_cell=5)
        self.assertIn("end correct", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
