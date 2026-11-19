"""#37: the SLP view's one-key calls, the Unsure state, and two screens on one session."""

import http.client
import json
import re
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from speakup import calibration, pages
from speakup.bank import load_fallback
from speakup.server import make_server
from speakup.words import Word
from tests.test_server import birth_date_for

UNSURE = "Unsure, SLP please listen"


class SlpViewTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.outcome = "gliding"
        self.confidence = 0.55
        words = [Word("rabbit", "start"), Word("carrot", "middle")]
        server = make_server(
            "127.0.0.1", 0, words=words, listen=self.listen, recorder=self, bank=load_fallback(words),
            recordings_dir=Path(tmp.name) / "recordings", db_path=Path(tmp.name) / "speakup.db",
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server

    def record(self, path):  # the test stands in for the mic: no clip on disk unless a test asks for one
        if getattr(self, "clip_on_disk", False):
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
                w.writeframes(b"\x00\x00" * 16000)

    def listen(self, word, path):
        off = self.outcome is not None
        return {"word": word, "target_sound": "r", "expected_phone": "ɹ", "heard_phone": None if off else "ɹ",
                "error_type": self.outcome, "confidence": self.confidence, "model": "stub",
                "recorded_at": "2026-11-14T10:15:00-06:00"}

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        conn.request(method, path, body=urlencode(fields) if fields is not None else None, headers=headers)
        response = conn.getresponse()
        result = response.status, response.getheader("Location"), response.read().decode("utf-8")
        conn.close()
        return result

    def audio_status(self, path):  # request() decodes the body as text, and a WAV is not text
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_address[1])
        conn.request("GET", path)
        status = conn.getresponse().status
        conn.close()
        return status

    def recorded(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0)})
        self.request("POST", "/record", {})

    def test_agree_takes_artis_call(self):
        self.recorded()
        self.assertEqual(self.request("POST", "/verify", {"verdict": "agree"})[:2], (303, "/word"))
        a = self.server.session.attempts[0]
        self.assertEqual((a.arti_call, a.slp, a.result.error_type), ("wrong", "wrong", "gliding"))

    def test_disagree_takes_the_other_call_and_keeps_artis(self):
        self.recorded()
        self.assertEqual(self.request("POST", "/verify", {"verdict": "disagree"})[:2], (303, "/word"))
        a = self.server.session.attempts[0]
        self.assertEqual((a.arti_call, a.slp, a.result.error_type), ("wrong", "correct", None))

    def test_agree_on_a_right_call(self):
        self.outcome = None
        self.recorded()
        self.request("POST", "/verify", {"verdict": "agree"})
        self.assertEqual(self.server.session.attempts[0].slp, "correct")

    def test_unknown_call_is_refused(self):
        self.recorded()
        self.assertEqual(self.request("POST", "/verify", {"verdict": "maybe"})[0], 400)

    def test_practice_takes_agree_and_disagree_too(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        self.assertEqual(self.request("POST", "/practice/verify", {"verdict": "disagree"})[:2], (303, "/practice"))
        self.assertEqual(self.server.practice.current_attempt.slp, "correct")

    def test_unsure_shows_only_inside_the_band(self):
        self.recorded()
        self.assertFalse(UNSURE in self.request("GET", "/word")[2])
        with mock.patch.object(calibration, "UNSURE_BAND", (0.4, 0.6)):
            self.assertTrue(UNSURE in self.request("GET", "/word")[2])
        self.confidence = None
        self.request("POST", "/record", {})
        with mock.patch.object(calibration, "UNSURE_BAND", (0.0, 1.0)):
            self.assertFalse(UNSURE in self.request("GET", "/word")[2])

    def test_word_card_asks_agree_or_disagree_with_keys(self):
        self.recorded()
        page = self.request("GET", "/word")[2]
        self.assertIn('Arti heard: <b class="off">the r sounded off</b>. Do you agree?', page)
        for key, half in (("a", "agree"), ("d", "disagree")):
            self.assertIn(f'class="half {half}" data-key="{key}"', page)
        self.assertIn('action="/verify"', page)
        self.assertNotIn('class="listen"', page)  # no clip on disk in this test: no Listen circle
        self.assertIn('<script id="slp-keys">', page)
        self.assertIn('<details class="evidence" open>', page)

    def posted_calls(self, page):
        """What each half of the question card posts, by its class (#56)."""
        return dict((half, call) for call, half in re.findall(
            r'name="verdict" value="(\w+)"><button type="submit" class="half (\w+)', page))

    def test_halves_post_the_call_the_card_shows(self):
        # Agree and Disagree post an absolute call, so a try recorded again under the page can't flip it (#56).
        self.recorded()
        self.assertEqual(self.posted_calls(self.request("GET", "/word")[2]), {"agree": "wrong", "disagree": "correct"})
        self.outcome = None
        self.request("POST", "/record", {})
        self.assertEqual(self.posted_calls(self.request("GET", "/word")[2]), {"agree": "correct", "disagree": "wrong"})

    def test_agree_on_a_stale_card_saves_the_call_it_showed(self):
        self.recorded()
        shown = self.posted_calls(self.request("GET", "/word")[2])  # the card says the r sounded off
        self.outcome = None
        self.request("POST", "/record", {})  # recorded again in another tab: Arti now says right
        self.request("POST", "/verify", {"verdict": shown["agree"]})
        self.assertEqual(self.server.session.attempts[0].slp, "wrong")

    def card_post(self, page, half):
        """The fields the given half of the question card posts, as a browser sends them (#78)."""
        form = re.search(r'<form method="post" action="[^"]*/verify">(.*?)<button type="submit" class="half '
                         + half + r'\b', page).group(1)
        return dict(re.findall(r'<input type="hidden" name="(\w+)" value="([^"]*)">', form))

    def test_agree_on_an_older_card_saves_onto_the_word_it_shows(self):
        # A second tab still shows rabbit's card while the session has moved on to carrot (#78).
        self.recorded()
        old = self.request("GET", "/word")[2]
        self.request("POST", "/next", {})
        self.request("POST", "/record", {})
        current = self.request("GET", "/word")[2]
        self.assertEqual(self.request("POST", "/verify", self.card_post(old, "agree"))[:2], (303, "/word"))
        self.assertEqual([a.slp for a in self.server.session.attempts], ["wrong", None])
        self.request("POST", "/verify", self.card_post(current, "disagree"))
        self.assertEqual([a.slp for a in self.server.session.attempts], ["wrong", "correct"])

    def test_a_call_on_a_try_that_is_not_there_saves_nothing(self):
        self.recorded()
        for i in ("1", "7", "-1", "x"):  # carrot not recorded yet, then no such words
            status, _, page = self.request("POST", "/verify", {"started": self.server.session.started_at, "i": i, "verdict": "wrong"})
            self.assertEqual(status, 400, i)
            self.assertIn("record the word before checking it", page)
        self.assertIsNone(self.server.session.attempts[0].slp)

    def test_a_card_from_an_earlier_session_saves_nothing(self):
        self.recorded()
        self.server.session.started_at = "2026-11-14T09:00:00-06:00"  # started_at counts seconds: keep the two apart
        old = self.request("GET", "/word")[2]
        self.request("POST", "/finish", {})
        self.request("POST", "/start", {"student_id": "S-099", "birth_date": birth_date_for(8, 0)})
        self.request("POST", "/record", {})
        status, _, page = self.request("POST", "/verify", self.card_post(old, "agree"))
        self.assertEqual(status, 400)
        self.assertIn("record the word before checking it", page)
        self.assertIsNone(self.server.session.attempts[0].slp)

    def test_practice_card_from_an_earlier_practice_saves_nothing(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        self.server.practice.started_at = "2026-11-14T09:00:00-06:00"
        old = self.request("GET", "/practice")[2]
        self.request("POST", "/practice/end", {})
        self.request("POST", "/start", {"student_id": "S-099", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        status, _, page = self.request("POST", "/practice/verify", self.card_post(old, "agree"))
        self.assertEqual(status, 400)
        self.assertIn("record the line before checking it", page)
        self.assertIsNone(self.server.practice.attempts[0].slp)

    def test_practice_agree_on_an_older_card_saves_onto_the_try_it_shows(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        old = self.request("GET", "/practice")[2]
        self.request("POST", "/practice/next", {})
        self.request("POST", "/practice/record", {})
        current = self.request("GET", "/practice")[2]
        self.assertEqual(self.request("POST", "/practice/verify", self.card_post(old, "disagree"))[:2],
                         (303, "/practice"))
        self.assertEqual([a.slp for a in self.server.practice.attempts], ["correct", None])
        self.request("POST", "/practice/verify", self.card_post(current, "agree"))
        self.assertEqual([a.slp for a in self.server.practice.attempts], ["correct", "wrong"])

    def test_practice_call_on_a_try_that_is_not_there_saves_nothing(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        status, _, page = self.request("POST", "/practice/verify", {"started": self.server.practice.started_at, "i": "3", "verdict": "wrong"})
        self.assertEqual(status, 400)
        self.assertIn("record the line before checking it", page)
        self.assertIsNone(self.server.practice.attempts[0].slp)

    def test_the_slps_call_stays_lit(self):
        self.recorded()
        self.request("POST", "/verify", {"verdict": "disagree"})
        page = self.request("GET", "/word")[2]
        self.assertIn('class="half disagree on"', page)
        self.assertIn('class="half agree"', page)
        self.assertIn("You disagreed with Arti: the r sounded right.", page)

    def test_listen_again_plays_the_clip(self):
        self.clip_on_disk = True
        self.recorded()
        page = self.request("GET", "/word")[2]
        self.assertIn('data-key="l" data-clip="/audio/s0.wav"', page)

    def test_starting_a_practice_keeps_the_open_screenings_clip(self):  # #54
        self.clip_on_disk = True
        self.recorded()
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.assertIn('data-key="l" data-clip="/audio/s0.wav"', self.request("GET", "/word")[2])
        self.assertEqual(self.audio_status("/audio/s0.wav"), 200)

    def test_starting_a_screening_keeps_the_open_practices_clip(self):  # #54
        self.clip_on_disk = True
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0)})
        self.assertIn('data-key="l" data-clip="/audio/p0.wav"', self.request("GET", "/practice")[2])
        self.assertEqual(self.audio_status("/audio/p0.wav"), 200)

    def test_practice_page_has_the_question_card(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": "practice"})
        self.request("POST", "/practice/record", {})
        page = self.request("GET", "/practice")[2]
        self.assertIn('action="/practice/verify"', page)
        self.assertEqual(self.posted_calls(page), {"agree": "wrong", "disagree": "correct"})
        self.assertIn('<script id="slp-keys">', page)

    def test_kid_screen_follows_the_slp_screen(self):
        # Each request is its own connection: the SLP's laptop and the board's monitor are two clients.
        self.recorded()
        kid = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual((kid["word"], kid["tried"]), ("rabbit", True))
        self.request("POST", "/verify", {"verdict": "agree"})
        self.request("POST", "/next", {})
        kid = json.loads(self.request("GET", "/api/state")[2])
        self.assertEqual((kid["word"], kid["tried"]), ("carrot", False))
        self.assertTrue("carrot" in self.request("GET", "/word")[2])



class ListenStyleTest(unittest.TestCase):
    def test_end_screen_listen_rule_skips_the_word_page_listen_button(self):
        """/word's Listen circle is <button class="listen">; the end screen's line is <p class="listen"> (#42).
        Every SLP_CSS selector naming .listen must be for the <p>, or it shifts and restyles the button."""
        selectors = [part.strip() for rule in re.findall(r"([^{}]*)\{", pages.SLP_CSS)
                     for part in rule.split(",") if re.search(r"\.listen\b", part)]
        self.assertTrue(selectors)
        for selector in selectors:
            self.assertRegex(selector, r"^p\.listen\b")


if __name__ == "__main__":
    unittest.main()
