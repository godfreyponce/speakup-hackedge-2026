"""The target sound window the SLP drags on the analysis viewer (Nov 5): the measures that depend on it follow it,
the original analysis is never changed, and the server keeps the window with the try until the word box moves."""

import json
import re
import unittest
from unittest import mock

import numpy as np

from speakup import acoustics, pages, soundview
from speakup.acoustics import Analysis


def word(window=(0.0, 0.135)):
    """0.3 s, 60 frames. The F3-F2 gap is 1,000 Hz except a narrow 300 Hz dip at frames 40 to 44 (0.20 to
    0.22 s), outside the automatic start window, and a 600 Hz dip at frames 10 to 14 inside it."""
    n = 60
    times = np.arange(n) * 0.005
    f = np.tile([500.0, 1500.0, 2500.0], (n, 1))
    f[10:15, 2] = 2100.0
    f[40:45, 2] = 1800.0
    a = Analysis(start=0.1, end=0.4, times=times, f0=np.full(n, 250.0), formants=f,
                 spec_db=np.zeros((8, 8)), spec_seconds=0.3, rms=np.full(n, 0.1), wave=np.zeros((10, 2)),
                 window=window, auto_window=window)
    acoustics._search_gap(a)
    return a


class WithWindowTest(unittest.TestCase):
    def test_automatic_window_finds_the_dip_inside_it(self):
        a = word()
        self.assertEqual(a.gap_min, 600.0)
        self.assertAlmostEqual(a.gap_time, 0.05, places=3)  # first frame whose 5-frame median dips

    def test_moving_the_window_searches_again_and_leaves_the_original(self):
        a = word()
        b = acoustics.with_window(a, (0.18, 0.26))
        self.assertEqual(b.window, (0.18, 0.26))
        self.assertEqual(b.auto_window, (0.0, 0.135))
        self.assertEqual(b.gap_min, 300.0)
        self.assertAlmostEqual(b.gap_time, 0.20, places=3)
        self.assertEqual(b.at_gap, (500.0, 1500.0, 1800.0))
        self.assertEqual((a.window, a.gap_min), ((0.0, 0.135), 600.0))  # the cached analysis is untouched

    def test_none_goes_back_to_the_automatic_window(self):
        b = acoustics.with_window(acoustics.with_window(word(), (0.18, 0.26)), None)
        self.assertEqual((b.window, b.gap_min), ((0.0, 0.135), 600.0))

    def test_window_is_kept_inside_the_word_and_at_least_20_ms(self):
        b = acoustics.with_window(word(), (0.5, -1.0))  # reversed and outside: sorted, then clamped
        self.assertEqual(b.window, (0.0, 0.3))
        c = acoustics.with_window(word(), (0.1, 0.1))
        self.assertAlmostEqual(c.window[1] - c.window[0], acoustics.MIN_WINDOW, places=4)
        d = acoustics.with_window(word(), (0.299, 0.3))
        self.assertAlmostEqual(d.window[0], 0.3 - acoustics.MIN_WINDOW, places=4)

    def test_window_with_no_tracked_frames_says_so_once(self):
        a = word()
        a.formants[30:40] = np.nan
        b = acoustics.with_window(a, (0.15, 0.19))
        self.assertIsNone(b.gap_min)
        self.assertEqual(b.notes.count(acoustics.NO_GAP), 1)
        c = acoustics.with_window(b, None)
        self.assertNotIn(acoustics.NO_GAP, c.notes)

    def test_measures_and_gap_text_say_who_set_the_window(self):
        a, b = word(), acoustics.with_window(word(), (0.18, 0.26))
        self.assertIn("Target sound window (automatic)", pages.measures_html(a, None))
        self.assertIn("Target sound window (moved by you)", pages.measures_html(b, None))
        self.assertIn("0.18 to 0.26 s", pages.measures_html(b, None))
        self.assertEqual(pages.gap_text(a), "F3-F2 gap where the r should be: 600 Hz (experimental).")
        self.assertEqual(pages.gap_text(b), "F3-F2 gap in the target window you set: 300 Hz (experimental).")

    def test_viewer_data_carries_the_window_contract(self):
        b = acoustics.with_window(word(), (0.18, 0.26))
        html = soundview.viewer(b, "/audio/s0.wav", target="ɹ", age_months=78, word="rabbit", key="s0")
        d = json.loads(re.search(r'<script id="sv-data" type="application/json">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(d["win"], [0.18, 0.26])
        self.assertEqual(d["win_auto"], [0.0, 0.135])
        self.assertTrue(d["win_manual"])
        self.assertEqual(d["win_url"], "/analysis/s0/window")
        self.assertEqual((d["word"], d["key"], d["sex"]), ("rabbit", "s0", None))
        self.assertIn("Reset target window", html)


if __name__ == "__main__":
    unittest.main()
