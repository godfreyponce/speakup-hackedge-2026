import json
import re
import unittest
from pathlib import Path

import numpy as np

from speakup import synth, synth_book, synthview

ROOT = Path(__file__).resolve().parent.parent
SYNTH_DIR = ROOT / "speakup" / "static" / "book" / "synth"


class SynthTest(unittest.TestCase):
    def test_same_plan_gives_the_same_samples(self):
        a = synth_book.audio("w-rabbit", "boy6")
        b = synth_book.audio("w-rabbit", "boy6")
        self.assertTrue(np.array_equal(a, b))
        self.assertAlmostEqual(float(np.max(np.abs(a))), 0.5, places=6)

    def test_groups_differ(self):
        self.assertFalse(np.array_equal(synth_book.audio("c-s", "man")[:4800], synth_book.audio("c-s", "girl6")[:4800]))

    def test_a_vowel_lands_where_it_was_asked(self):
        # The cascade's resonances sit at the requested formants: the spectrum of a held vowel peaks near F1 and F2.
        segs = [synth.Seg("a", 300, (700, 1200, 2500, 3500, 4500), av=60, focus=True)]
        x = synth.synthesize(synth.Plan(segs, 120, pad_ms=0))
        mid = x[len(x) // 4:3 * len(x) // 4]
        spec = np.abs(np.fft.rfft(mid * np.hanning(len(mid))))
        hz = np.fft.rfftfreq(len(mid), 1 / synth.RATE)
        smooth = np.convolve(spec, np.ones(200) / 200, mode="same")
        low = (hz > 400) & (hz < 950)
        self.assertLess(abs(hz[low][np.argmax(smooth[low])] - 700), 150)

    def test_wav_is_16_bit_mono_48k(self):
        data = synth.wav_bytes(np.zeros(480))
        self.assertEqual(data[:4], b"RIFF")
        self.assertEqual(int.from_bytes(data[24:28], "little"), 48000)

    def test_every_value_is_measured_or_estimated_with_a_reason(self):
        for item in synth_book.ITEMS:
            for g in synth_book.GROUPS:
                built = synth_book.build(item, g.id)
                for v in built.values:
                    self.assertIn(v.status, ("measured", "estimated"), (item, g.id, v.what))
                    if v.status == "estimated":
                        self.assertTrue(v.how, (item, g.id, v.what))
                    self.assertTrue(v.source, (item, g.id, v.what))

    def test_six_year_olds_and_error_versions_are_always_estimated(self):
        for item in synth_book.ITEMS:
            self.assertTrue(synth_book.build(item, "boy6").estimated, item)
        for item in (i for i in synth_book.ITEMS.values() if i.kind == "error"):
            self.assertTrue(synth_book.build(item.id, "man").estimated, item.id)

    def test_measured_vowels_use_the_published_table(self):
        built = synth_book.build("v-iy", "man")
        f = {v.what: v.hz for v in built.values}
        self.assertEqual(f["F1 of /i/"], 343)
        self.assertEqual(f["F2 of /i/"], 2323)
        self.assertFalse(built.estimated)

    def test_group_for_age_and_sex(self):
        self.assertEqual(synth_book.group_for(80, "male"), ["boy6"])
        self.assertEqual(synth_book.group_for(96, "male"), ["boy10"])  # no band at 8: the nearest older one
        self.assertEqual(synth_book.group_for(130, "female"), ["girl10"])
        self.assertEqual(synth_book.group_for(72), ["girl6", "boy6"])

    def test_lookup_by_sound_variant_sex_and_age(self):
        self.assertEqual(synth_book.lookup("ɹ", "male", 80),
                         {"item": "c-r", "group": "boy6", "file": "c-r-boy6.png", "age_band": "6", "fallback": False})
        hit = synth_book.lookup("gliding", None, 100)
        self.assertEqual((hit["item"], hit["group"], hit["fallback"]), ("e-wabbit", "girl10", True))
        self.assertEqual(synth_book.lookup("s", "female", age="adult")["file"], "c-s-woman.png")
        self.assertTrue(synth_book.lookup("s", "female", 50)["fallback"])
        self.assertIsNone(synth_book.lookup("x"))

    def test_every_item_has_a_look_for_line_and_confusables(self):
        for item in synth_book.ITEMS:
            text = synth_book.LOOK_FOR[item]
            self.assertTrue(0 < text.count(".") <= 2, item)
            self.assertNotIn("—", text)
            for c in synth_book.confusable(item):
                self.assertIn(c, synth_book.ITEMS)
        self.assertIn("c-w", synth_book.confusable("c-r"))
        self.assertIn("e-wabbit", synth_book.confusable("c-r"))
        self.assertIn("c-th", synth_book.confusable("c-s"))


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.index = json.loads((SYNTH_DIR / "index.json").read_text(encoding="utf-8"))

    def test_every_item_and_group_has_a_picture_file(self):
        have = {(p["item"], p["group"]) for p in self.index["pictures"]}
        for item in synth_book.ITEMS:
            for g in synth_book.GROUPS:
                self.assertIn((item, g.id), have)
        for p in self.index["pictures"]:
            path = SYNTH_DIR / p["file"]
            self.assertTrue(path.is_file(), p["file"])
            self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(p["file"], synth_book.picture_name(p["item"], p["group"]))

    def test_index_fields(self):
        for p in self.index["pictures"]:
            for key in ("sound", "context", "age_band", "sex", "estimated", "sources", "values", "check"):
                self.assertIn(key, p)
            self.assertEqual(p["estimated"], any(v["status"] == "estimated" for v in p["values"]))
            if p["estimated"]:
                self.assertTrue(p["reasons"], p["file"])
            self.assertTrue(p["check"]["pass"], p["file"])

    def test_index_matches_the_current_tables(self):
        # A change to the parameter tables needs a rebuild of the pictures (scripts/build_synth_pictures.py).
        for p in self.index["pictures"][::7]:
            built = synth_book.build(p["item"], p["group"])
            self.assertEqual([v["value"] for v in p["values"]], [v.hz for v in built.values], p["file"])

    def test_sections_and_pairs_name_real_items_and_sections(self):
        from speakup import book
        ids = {s["id"] for s in book.load()["sections"]}
        for sec, v in self.index["sections"].items():
            self.assertIn(sec, ids)
            for i in v["items"]:
                self.assertIn(i, synth_book.ITEMS)
        for sec, pairs in self.index["pairs"].items():
            self.assertIn(sec, ids)
            for a, b in pairs:
                self.assertIn(a, synth_book.ITEMS)
                self.assertIn(b, synth_book.ITEMS)

    def test_pictures_stay_small(self):
        total = sum(p.stat().st_size for p in SYNTH_DIR.glob("*.png"))
        self.assertLess(total, 15_000_000)


class ViewTest(unittest.TestCase):
    def test_captions_are_plain(self):
        idx = synthview.index()
        from speakup import book
        refs = synthview._refs(book.load(), idx)
        for p in idx["pictures"]:
            text = synthview.caption(p, refs)
            self.assertTrue(text.startswith("Computer-made from published averages ("), text)
            self.assertIn("not a recording", text)
            self.assertNotIn("—", text)
            self.assertNotIn("·", text)

    def test_short_cite(self):
        self.assertEqual(synthview.short_cite("Hillenbrand, J., Getty, L. A., Clark, M. J., & Wheeler, K. (1995). "
                                              "Acoustic characteristics."), "Hillenbrand et al. 1995")
        self.assertEqual(synthview.short_cite("Klatt, D. H., & Klatt, L. C. (1990). Analysis."), "Klatt and Klatt 1990")

    def test_names(self):
        self.assertIsNotNone(synthview.png_path("c-s-girl10.png"))
        self.assertIsNone(synthview.png_path("../index.json"))
        self.assertIsNone(synthview.png_path("c-s-man.wav"))  # the computer-made sound is no longer served
        self.assertFalse(hasattr(synthview, "wav"))


if __name__ == "__main__":
    unittest.main()
