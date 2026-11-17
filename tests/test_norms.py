import json
import tempfile
import unittest
from pathlib import Path

from speakup import norms

SOURCES = {"a": {"cite": "Alpha, A., Beta, B., and Gamma, G. (1999). Title. J, 1, 1-2.", "doi": "x", "verified": True},
           "b": {"cite": "Delta, D. (2001). Title. J, 2, 3-4.", "doi": "y", "verified": True}}


def entry(phoneme, lo, hi, sex="any", context="any", source="a", verified=True, **formants):
    e = {"phoneme": phoneme, "context": context, "age_min_months": lo, "age_max_months": hi, "sex": sex, "n": 10,
         "F1": None, "F2": None, "F3": None, "F3_F2": None, "spread": "1sd", "extra": {}, "source": source,
         "verified": verified, "note": ""}
    for k, (a, b) in formants.items():
        e[k] = {"mean": (a + b) / 2, "sd": (b - a) / 2, "lo": a, "hi": b}
    return e


class NormsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "norms.json"
        norms._load.cache_clear()

    def tearDown(self):
        norms._load.cache_clear()
        self.tmp.cleanup()

    def write(self, rows, cues=None):
        self.path.write_text(json.dumps({"version": 1, "sources": SOURCES, "cues": cues or {}, "norms": rows}),
                             encoding="utf-8")

    def test_narrowest_band_per_formant(self):
        # A wide band with F2 and F3 and a narrow one with only F3-F2: each formant keeps its own narrowest band.
        self.write([entry("ɝ", 120, 155, F2=(1500, 1800), F3=(1900, 2300)),
                    entry("ɝ", 120, 131, source="b", F3_F2=(300, 700))])
        n = norms.norms_for("ɝ", 125, path=self.path)
        self.assertEqual(set(n.bands), {"F2", "F3", "F3_F2"})
        self.assertEqual(n.bands["F2"].source, "a")
        self.assertEqual(n.bands["F3_F2"].source, "b")
        self.assertTrue(n.exact_age)
        self.assertIsNone(n.warning)

    def test_context_match_wins_over_any_and_other_contexts_are_left_out(self):
        self.write([entry("ɹ", 72, 141, context="prevocalic", F3=(1800, 2700)),
                    entry("ɹ", 72, 141, context="any", F3=(2000, 3000)),
                    entry("ɹ", 72, 141, context="cluster", F3=(2100, 3100))])
        self.assertEqual(norms.norms_for("ɹ", 80, "prevocalic", path=self.path).bands["F3"].together.lo, 1800)
        self.assertEqual(norms.norms_for("ɹ", 80, "postvocalic", path=self.path).bands["F3"].together.lo, 2000)

    def test_no_entry_for_the_position_is_none(self):
        self.write([entry("ɹ", 72, 141, context="prevocalic", F3=(1800, 2700))])
        self.assertIsNone(norms.norms_for("ɹ", 80, "intervocalic", path=self.path))
        out = norms.ranges_json("ɹ", 80, "intervocalic", path=self.path)
        self.assertEqual(out["status"], "nosound")
        self.assertIn("middle of a word", out["message"])

    def test_boys_and_girls_stay_apart_with_the_pooled_range_alongside(self):
        self.write([entry("i", 120, 155, sex="male", F2=(2800, 3100)),
                    entry("i", 120, 155, sex="female", F2=(2900, 3300)),
                    entry("i", 120, 155, sex="any", F2=(2850, 3200))])
        b = norms.norms_for("i", 130, path=self.path).bands["F2"]
        self.assertEqual((b.boys.lo, b.boys.hi), (2800, 3100))
        self.assertEqual((b.girls.lo, b.girls.hi), (2900, 3300))
        self.assertEqual((b.together.lo, b.together.hi), (2850, 3200))
        self.assertTrue(b.pooled_by_source)

    def test_merge_when_the_source_gave_only_the_two_groups(self):
        self.write([entry("i", 120, 155, sex="male", F2=(2800, 3100)),
                    entry("i", 120, 155, sex="female", F2=(2900, 3300))])
        b = norms.norms_for("i", 130, path=self.path).bands["F2"]
        self.assertEqual((b.together.lo, b.together.hi), (2800, 3300))
        self.assertFalse(b.pooled_by_source)

    def test_younger_child_gets_the_nearest_older_band_with_a_warning(self):
        self.write([entry("ɝ", 60, 71, F3_F2=(300, 800)), entry("ɝ", 72, 83, F3_F2=(300, 700))])
        n = norms.norms_for("ɝ", 48, path=self.path)
        self.assertFalse(n.exact_age)
        self.assertEqual(n.bands["F3_F2"].age_min, 60)
        self.assertIn("No published range for age 4;0; showing 5;0 to 5;11", n.warning)
        self.assertIn("Younger children usually have higher formants", n.warning)

    def test_older_than_every_band_gets_the_nearest_younger_with_a_warning(self):
        self.write([entry("ɹ", 72, 141, F3=(1800, 2700))])
        n = norms.norms_for("ɹ", 170, path=self.path)
        self.assertEqual(n.bands["F3"].age_max, 141)
        self.assertIn("Older children and adults", n.warning)

    def test_unverified_entries_are_never_used(self):
        self.write([entry("w", 60, 71, verified=False, F2=(700, 900))])
        self.assertIsNone(norms.norms_for("w", 65, path=self.path))

    def test_missing_cue_formants_are_named(self):
        self.write([entry("ɹ", 72, 141, F3=(1800, 2700))], cues={"ɹ": {"key": ["F2", "F3"], "measure": "F3-F2", "say": "x"}})
        out = norms.ranges_json("ɹ", 80, path=self.path)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["missing"], ["F2"])
        self.assertEqual(out["cue"]["key"], ["F2", "F3"])
        self.assertEqual(out["bands"][0]["age"], "6;0 to 11;9")
        self.assertIn("Alpha", out["bands"][0]["cite"])

    def test_extras_such_as_noise_peaks_are_bands_too(self):
        e = entry("s", 30, 42)
        e["extra"] = {"spectral_peak": {"mean": 6769, "sd": 1000, "lo": 5769, "hi": 7769}}
        self.write([e])
        out = norms.ranges_json("s", 36, path=self.path)
        self.assertEqual(out["bands"][0]["label"], "Noise peak")

    def test_missing_or_broken_file_says_so_and_never_crashes(self):
        out = norms.ranges_json("ɹ", 80, path=Path(self.tmp.name) / "nope.json")
        self.assertEqual(out["status"], "nofile")
        self.assertIn("No range data on this machine", out["message"])
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(norms.ranges_json("ɹ", 80, path=self.path)["status"], "nofile")
        with self.assertRaises(norms.NormsUnavailable):
            norms.norms_for("ɹ", 80, path=self.path)

    def test_cue_fallback_only_for_consonant_r(self):
        missing = Path(self.tmp.name) / "nope.json"
        self.assertEqual(norms.cue_for("ɹ", missing)["key"], ["F2", "F3"])
        self.assertEqual(norms.cue_for("k", missing)["key"], [])

    def test_no_age_or_no_target(self):
        self.write([])
        self.assertEqual(norms.ranges_json("ɹ", None, path=self.path)["status"], "noage")
        self.assertEqual(norms.ranges_json(None, 80, path=self.path)["status"], "nosound")


class ShippedNormsTest(unittest.TestCase):
    """The file in speakup/data, when present: it loads and gives the six-year-old's rabbit an F3 range."""

    def test_shipped_file_if_present(self):
        if not norms.NORMS_PATH.exists():
            self.skipTest("no norms file in speakup/data")
        out = norms.ranges_json("ɹ", 78, "prevocalic")
        self.assertEqual(out["status"], "ok")
        self.assertIn("F3", [b["measure"] for b in out["bands"]])


if __name__ == "__main__":
    unittest.main()
