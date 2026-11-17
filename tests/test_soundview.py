import json
import re
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from speakup import pages, soundview
from speakup.acoustics import Analysis
from speakup.words import Word


def analysis(window=(0.0, 0.2)):
    n = 60
    times = np.arange(n) * 0.005
    formants = np.tile([500.0, 1300.0, 1700.0], (n, 1))
    formants[20:26] = np.nan  # a gap the Lines tool must not bridge
    return Analysis(start=0.4, end=0.7, times=times, f0=np.full(n, 250.0), formants=formants,
                    spec_db=np.random.default_rng(0).normal(size=(64, 80)), spec_seconds=0.3, window=window,
                    rms=np.full(n, 0.1), wave=np.zeros((50, 2)), gap_min=400.0, gap_time=0.1,
                    at_gap=(500.0, 1300.0, 1700.0))


def data_of(html):
    return json.loads(re.search(r'<script id="sv-data" type="application/json">(.*?)</script>', html, re.S).group(1))


RANGES = {"status": "ok", "message": None, "warning": None, "missing": ["F2"],
          "cue": {"key": ["F2", "F3"], "measure": "F3-F2", "say": "F3 dips low, toward F2"},
          "bands": [{"measure": "F3", "label": "F3", "age": "6;0 to 11;9", "cite": "X (2012)", "together": {"lo": 1815, "hi": 2716},
                     "boys": None, "girls": None}]}


class SoundViewTest(unittest.TestCase):
    def test_viewer_carries_target_age_and_ranges(self):
        with mock.patch.object(soundview, "_ranges", return_value=RANGES) as r:
            html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78, context="prevocalic")
        r.assert_called_once_with("ɹ", 78, "prevocalic")
        d = data_of(html)
        self.assertEqual(d["target"], "ɹ")
        self.assertEqual(d["age_months"], 78)
        self.assertEqual(d["ranges"]["bands"][0]["together"], {"lo": 1815, "hi": 2716})
        self.assertEqual(d["cursor_colors"], list(soundview.CURSOR_COLORS))
        self.assertEqual(d["gap_frames"], 3)
        self.assertIsNone(d["f"][22][0])  # the gap reaches the script as nulls
        self.assertEqual(d["audio"], "/audio/s0.wav")

    def test_toolbar_and_every_tool_are_on_the_page(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78)
        self.assertIn('id="sv-tools"', html)
        for tool in ("move", "cursor", "scrub", "layers", "target", "ranges", "lines"):
            self.assertIn(f'id: "{tool}"', html)
        for words in ("Time only", "Hz only", "Time and Hz", "Add cursor", "Straight lines", "Fitted curve",
                      "Smoothed", "Bands", "Numbers", "Both", "Play what is shown", "Zoom to /ɹ/"):
            self.assertIn(words, html)
        self.assertIn('id="sv-audio"', html)

    def test_no_audio_no_play_button(self):
        html = soundview.viewer(analysis(), None)
        self.assertNotIn("Play what is shown", html)
        self.assertNotIn('id="sv-audio"', html)
        self.assertIsNone(data_of(html)["audio"])

    def test_json_is_safe_inside_a_script_tag(self):
        bad = dict(RANGES, bands=[dict(RANGES["bands"][0], cite="</script><b>")])
        with mock.patch.object(soundview, "_ranges", return_value=bad):
            html = soundview.viewer(analysis(), None, target="ɹ", age_months=78)
        self.assertNotIn("</script><b>", html)
        self.assertEqual(data_of(html)["ranges"]["bands"][0]["cite"], "</script><b>")

    def test_nov5_viewer_changes_are_on_the_page(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78, word="rabbit", key="s0")
        self.assertNotIn("rgba(255,201,20", html)  # the yellow gap boxes are gone
        self.assertIn('id: "ranges", label: "Age ranges", kind: "overlay", default: false', html)  # off, and parked:
        self.assertIn('SV.overlays = ["layers", "target", "lines"];', html)  # not in the toolbar (revision 4)
        self.assertIn("during a correct /", html)
        for words in ("Plays it backwards", "Half speed", "Quarter speed", "bestStart",
                      "setValueCurveAtTime"):
            self.assertIn(words, html)
        self.assertIn('id="sv-winreset" hidden', html)

    def test_nov5_revision_compare_tool_and_scrub(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78, word="rabbit", key="s0")
        # Compare is a pop-up from the toolbar that draws reference curves; the side panel is gone.
        self.assertIn('id="sv-cmp-pop" role="dialog" aria-label="Compare with" hidden', html)
        self.assertIn("data-compare", html)
        self.assertIn('"/compare/curves/"', html)
        self.assertIn('id="sv-refs"', html)
        for gone in ("Compare with typical", 'id="sv-compare"', "window.openCompare", "/compare/pic/"):
            self.assertNotIn(gone, html)
        # Scrub: the engine script comes before the viewer's; holding still stops, no loop or hold options.
        self.assertLess(html.index("window.SVScrub = (function"), html.index('JSON.parse(document.getElementById("sv-data")'))
        for gone in ("Loop a short slice", "Hold the sound", "When still", "Looping "):
            self.assertNotIn(gone, html)
        self.assertIn("Stop moving and it fades out.", html)
        self.assertIn('id="sv-winreset" hidden', html)  # the reset button waits until the SLP moves the window

    def test_revision5_scrub_is_one_stretched_stream(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78, word="rabbit", key="s0")
        # The vendored time-stretcher loads before the engine, and the engine before the viewer.
        lib, eng = html.index('<script src="/js/signalsmith-stretch.js"></script>'), html.index("window.SVScrub = (function")
        self.assertLess(lib, eng)
        self.assertIn("function stretchEngine(", html)
        self.assertIn("function oneEuro(", html)
        self.assertIn("if (want * st.dir < 0) want = 0;", html)  # never runs against the hand
        self.assertIn("window.SVScrub.stretchers(S.ac, S.P)", html)  # the viewer uses it
        self.assertIn("the older scrub is used", html)  # and says so when it falls back
        self.assertIn("The pink line shows where the sound is.", html)

    def test_revision4_compare_fits_itself_and_scrub_never_repeats(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78, word="rabbit", key="s0")
        self.assertIn("function autoFit(r)", html)  # the reference finds its best spot and length
        self.assertIn("Fit again", html)
        self.assertNotIn("Reset alignment", html)
        self.assertIn('bump("waits")', html)  # the scrub waits for a slow pointer instead of jumping back
        self.assertIn('back: "reverse"', html)

    def test_ui_text_rules(self):
        html = soundview.viewer(analysis(), "/audio/s0.wav", target="ɹ", age_months=78)
        self.assertNotIn("—", html)  # no em dashes
        self.assertNotIn("·", html)  # no middle dots


class AnalysisPageTest(unittest.TestCase):
    def test_page_passes_word_target_and_child_age(self):
        owner = SimpleNamespace(age_months=78, child_id="A1")
        with mock.patch.object(pages, "_banner", return_value=""), \
             mock.patch.object(soundview, "_ranges", return_value=RANGES) as r:
            html = pages.analysis_page(owner, Word("rabbit", "start"), analysis(), None, audio_url="/audio/s0.wav")
        r.assert_called_once_with("ɹ", 78, "prevocalic")
        self.assertIn("This recording: rabbit, /ɹ/ at the start", html)
        self.assertIn('id="sv-tools"', html)


if __name__ == "__main__":
    unittest.main()
