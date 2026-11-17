import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from speakup import compare, synthview
from speakup.server import make_server
from speakup.words import Word


class DefaultsTest(unittest.TestCase):
    def test_rabbit_at_six_opens_on_rabbit_with_gliding_and_derhotacized(self):
        d = compare.defaults("ɹ", 78, None, "prevocalic", "rabbit")
        self.assertEqual(d["item"], "w-rabbit")
        self.assertEqual(d["compare"], ["e-wabbit", "e-rabbit-derhot"])
        self.assertEqual(d["band"], "6")
        self.assertIsNone(d["warning"])
        self.assertIsNone(d["missing"])
        self.assertEqual(d["top_hz"], 6000)

    def test_rabbit_at_eleven_uses_the_ten_to_twelve_band(self):
        d = compare.defaults("ɹ", 11 * 12 + 2, None, "prevocalic", "rabbit")
        self.assertEqual((d["item"], d["band"], d["warning"]), ("w-rabbit", "10-12", None))

    def test_unknown_sex_shows_a_girl_and_says_so(self):
        d = compare.defaults("ɹ", 78, None, "prevocalic", "rabbit")
        self.assertEqual(d["sex"], "female")
        self.assertFalse(d["sex_known"])
        self.assertIn("Sex not recorded", d["sex_note"])
        known = compare.defaults("ɹ", 78, "male", "prevocalic", "rabbit")
        self.assertEqual((known["sex"], known["sex_known"], known["sex_note"]), ("male", True, ""))

    def test_age_between_bands_falls_back_to_the_nearest_older_with_the_warning(self):
        d = compare.defaults("ɹ", 100, None, "prevocalic", "rabbit")
        self.assertEqual(d["band"], "10-12")
        self.assertEqual(d["warning"], "No published range for age 8;4; showing 10;0 to 12;11. "
                                       "Younger children usually have higher formants.")
        young = compare.defaults("ɹ", 60)
        self.assertEqual(young["band"], "6")
        self.assertIn("No published range for age 5;0; showing 6;0 to 7;11.", young["warning"])
        self.assertIn("Age not recorded", compare.defaults("ɹ", None)["warning"])

    def test_r_picture_follows_where_the_sound_sits(self):
        self.assertEqual(compare.item_for("ɹ", "intervocalic", "carrot"), "c-r")
        self.assertEqual(compare.item_for("ɹ", "postvocalic", "car"), "v-er")
        self.assertEqual(compare.item_for("ɹ", "cluster", "truck"), "w-rabbit")
        self.assertEqual(compare.defaults("ɹ", 78, None, "intervocalic", "carrot")["compare"],
                         ["e-wabbit", "e-rabbit-derhot"])
        self.assertEqual(compare.defaults("ɹ", 78, None, "postvocalic", "car")["compare"], ["v-ah"])

    def test_other_sounds_work_too(self):
        s = compare.defaults("s", 78)
        self.assertEqual(s["item"], "c-s")
        self.assertEqual(len(s["compare"]), 2)
        self.assertTrue(all(i.startswith("e-s-") for i in s["compare"]))
        self.assertEqual(s["top_hz"], 11000)  # /s/ noise sits high: the shared scale grows to show it
        k = compare.defaults("k", 78)
        self.assertEqual((k["item"], k["compare"]), ("c-k", ["c-t"]))  # fronting: the book's error pair first
        self.assertEqual(compare.defaults("gliding", 78)["item"], "e-wabbit")

    def test_missing_sound_says_so(self):
        d = compare.defaults("ʔ", 78)
        self.assertIsNone(d["item"])
        self.assertEqual(d["compare"], [])
        self.assertIn("No reference for /ʔ/", d["missing"])
        self.assertIn("No reference for this sound", compare.defaults(None, 78)["missing"])

    def test_no_pictures_on_this_machine(self):
        with mock.patch.object(synthview, "index", return_value=None):
            d = compare.data("ɹ", 78)
        self.assertIsNone(d["defaults"]["item"])
        self.assertIn("not on this machine", d["defaults"]["missing"])
        self.assertEqual(d["items"], [])

    def test_every_lexicon_target_has_a_picture(self):
        from speakup import lexicon
        for word, e in lexicon._words().items():
            for t in e.get("targets", []):
                self.assertIsNotNone(compare.item_for(t["phoneme"], t.get("context"), word), word)

    def test_data_lists_every_item_with_its_related_sounds(self):
        d = compare.data("ɹ", 78, None, "prevocalic", "rabbit")
        ids = [i["id"] for i in d["items"]]
        self.assertEqual(len(ids), len(synthview.index()["items"]))
        rabbit = next(i for i in d["items"] if i["id"] == "w-rabbit")
        self.assertEqual(rabbit["related"][:2], ["e-wabbit", "e-rabbit-derhot"])
        self.assertEqual(rabbit["section"], "snd-r")
        self.assertTrue(rabbit["look"])
        self.assertEqual([b["label"] for b in d["bands"]], ["6;0 to 7;11", "10;0 to 12;11", "adults"])
        self.assertEqual(d["group_of"]["10-12|male"], "boy10")
        self.assertEqual(d["max_references"], 2)

    def test_curves_follow_the_synthesized_tracks(self):
        from speakup import synth, synth_book
        c = compare.curves("w-rabbit-girl6")
        self.assertEqual((c["item"], c["group"], c["sound"]), ("w-rabbit", "girl6", "ɹ"))
        self.assertEqual(len(c["t"]), len(c["f"]))
        self.assertAlmostEqual(c["t"][1] - c["t"][0], compare.STEP_MS / 1000)
        self.assertLess(c["focus"][0], c["focus"][1])
        self.assertLessEqual(c["focus"][1], c["seconds"])
        # Inside the /ɹ/ the curves sit on the values the book's picture marks (F1, F2, F3 of the r).
        mid = (c["focus"][0] + c["focus"][1]) / 2
        i = min(range(len(c["t"])), key=lambda j: abs(c["t"][j] - mid))
        self.assertEqual(c["f"][i], [m["v"] for m in c["targets"]])
        # Exactly the synthesizer's tracks, every 5 ms.
        tr = synth._tracks(synth_book.build("w-rabbit", "girl6").plan)
        self.assertEqual(c["f"][i][2], round(float(tr["F3"][int(round(c["t"][i] * 1000))])))
        # Silence around the word and the /b/ and /t/ closures are gaps.
        self.assertEqual(c["f"][0], [None, None, None])
        b = next(sg for sg in c["segs"] if sg["label"] == "b")
        j = min(range(len(c["t"])), key=lambda j: abs(c["t"][j] - (b["t0"] + b["t1"]) / 2))
        self.assertEqual(c["f"][j], [None, None, None])
        self.assertEqual(c["section"], "snd-r")

    def test_wabbit_has_a_high_f3_and_rabbit_a_low_one(self):
        r, w = compare.curves("w-rabbit-girl6"), compare.curves("e-wabbit-girl6")
        f3 = lambda c: c["f"][min(range(len(c["t"])), key=lambda j: abs(c["t"][j] - sum(c["focus"]) / 2))][2]  # noqa: E731
        self.assertLess(f3(r) + 500, f3(w))  # a correct r lowers F3 a long way; the w does not

    def test_unknown_curves(self):
        self.assertIsNone(compare.curves("e-wabbit-nobody"))
        self.assertIsNone(compare.curves("../etc-girl6"))
        self.assertIsNone(compare.curves("nothing-girl6"))

    def test_ui_text_rules(self):
        text = json.dumps(compare.data("ɹ", 100), ensure_ascii=False) + json.dumps(compare.curves("w-rabbit-boy10"),
                                                                                  ensure_ascii=False)
        self.assertNotIn("—", text)
        self.assertNotIn("·", text)


class CompareServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch("speakup.server.save_session", lambda *a: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = make_server("127.0.0.1", 0, words=[Word("rabbit", "start")], listen=lambda word, path: {},
                             recorder=self, recordings_dir=Path(tmp.name) / "rec", db_path=Path(tmp.name) / "s.db")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def record(self, path):
        pass

    def get(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        r = conn.getresponse()
        out = r.status, r.getheader("Content-Type"), r.read()
        conn.close()
        return out

    def test_data_route(self):
        q = urlencode({"target": "ɹ", "age_months": "135", "sex": "", "context": "prevocalic", "word": "rabbit"})
        status, kind, body = self.get("/compare/data?" + q)
        self.assertEqual((status, kind), (200, "application/json"))
        d = json.loads(body)["defaults"]
        self.assertEqual((d["item"], d["band"], d["sex"]), ("w-rabbit", "10-12", "female"))
        status, _, body = self.get("/compare/data?target=%CA%94&age_months=78")
        self.assertIn("No reference for", json.loads(body)["defaults"]["missing"])

    def test_data_route_reads_a_superscript_digit_as_no_age(self):
        status, kind, body = self.get("/compare/data?target=%C9%B9&age_months=%C2%B2")
        self.assertEqual((status, kind), (200, "application/json"))
        _, _, no_age = self.get("/compare/data?target=%C9%B9")
        self.assertEqual(json.loads(body), json.loads(no_age))

    def test_curves_route(self):
        status, kind, body = self.get("/compare/curves/e-wabbit-girl6.json")
        self.assertEqual((status, kind), (200, "application/json"))
        d = json.loads(body)
        self.assertEqual((d["item"], d["group"]), ("e-wabbit", "girl6"))
        self.assertEqual(len(d["t"]), len(d["f"]))
        status, _, body = self.get("/compare/curves/w-rabbit-nobody.json")
        self.assertEqual(status, 404)
        self.assertIn("error", json.loads(body))
        self.assertEqual(self.get("/compare/pic/w-rabbit-girl6.json")[0], 404)  # the old side panel's pictures are gone


if __name__ == "__main__":
    unittest.main()


class SyllableTest(unittest.TestCase):
    def test_reference_carries_its_syllable_and_vowel(self):
        from speakup import compare
        d = compare.curves("w-rabbit-man")
        if d is None:
            self.skipTest("no reference data")
        self.assertEqual(d["span"][0], d["focus"][0])
        self.assertGreater(d["span"][1], d["focus"][1])  # the vowel after the r is drawn too
        self.assertTrue(d["vowel"]["t0"] >= d["focus"][1])
        self.assertTrue(1500 < d["vowel_f3"] < 3500)
        er = compare.curves("v-er-boy10")
        self.assertIsNone(er["vowel"])  # no vowel next to it: not sized
