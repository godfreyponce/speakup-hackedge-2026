"""Recording the whole utterance in the background with Stop, and the selection box's rescoring (Nov 4)."""

import http.client
import json
import sqlite3
import tempfile
import threading
import time
import unittest
import wave
from contextlib import closing
from pathlib import Path
from urllib.parse import urlencode

from speakup.server import make_server
from speakup.words import Word
from tests.test_select import clip, write
from tests.test_server import birth_date_for

# "um", a pause, then the word: the pick should skip the "um".
UM_THEN_WORD = [(0.3, 0), (0.12, 0.3), (0.5, 0), (0.55, 0.5), (0.5, 0)]


class StoppableMic:
    """Stands in for the board's mic: holds the recording open until Stop (or `seconds`), then writes a clip."""

    def __init__(self):
        self.pieces = UM_THEN_WORD
        self.seconds = 0.0
        self.fail = False
        self.stops = 0
        self._stop = threading.Event()
        self.listening = threading.Event()

    def request_stop(self):
        self.stops += 1
        self._stop.set()

    def record(self, path):
        self._stop.clear()
        self.listening.set()
        self._stop.wait(self.seconds)
        self.listening.clear()
        if self.fail:
            from speakup.recorder import RecorderError
            raise RecorderError("mic unplugged")
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, clip(self.pieces))


class SelectServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.mic = StoppableMic()
        self.heard = []  # (word, path, seconds of audio) for each time Arti listened
        self.outcome = None
        server = make_server(
            "127.0.0.1", 0, words=[Word("rabbit", "start"), Word("carrot", "middle")], listen=self.listen,
            recorder=self.mic, recordings_dir=self.dir / "recordings", db_path=self.dir / "data" / "speakup.db",
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        self.port = server.server_address[1]

    def listen(self, word, path):
        with wave.open(str(path)) as w:
            self.heard.append((word, Path(path), w.getnframes() / w.getframerate()))
        return {"word": word, "target_sound": "r", "expected_phone": "ɹ",
                "heard_phone": "w" if self.outcome else "ɹ", "error_type": self.outcome,
                "confidence": None, "model": "stub", "recorded_at": "2026-11-05T10:15:00-06:00"}

    def request(self, method, path, fields=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(fields) if fields is not None else None
        all_headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        all_headers.update(headers or {})
        conn.request(method, path, body=body, headers=all_headers)
        r = conn.getresponse()
        out = r.status, dict(r.getheaders()), r.read()
        conn.close()
        return out

    def page(self, path):
        return self.request("GET", path)[2].decode("utf-8")

    def post(self, path, fields=None, headers=None):
        return self.request("POST", path, fields or {}, headers)

    def post_json(self, path, fields=None, headers=None):
        status, _, body = self.post(path, fields, headers)
        self.assertEqual(status, 200)
        return json.loads(body)

    def start(self, mode="screen"):
        self.post("/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "mode": mode})

    def wait_rec(self, until=("done", "error")):
        for _ in range(200):
            state = json.loads(self.page("/api/record"))
            if state["state"] in until:
                return state
            time.sleep(0.02)
        self.fail(f"recording never reached {until}")

    # The stop flow

    def test_background_record_shows_listening_then_stop_keeps_the_try(self):
        self.mic.seconds = 10  # a long recording: only Stop ends it quickly
        self.start()
        self.assertEqual(self.post_json("/record", headers={"X-Record": "background"}), {"ok": True})
        self.assertTrue(self.mic.listening.wait(2))
        self.assertEqual(json.loads(self.page("/api/record"))["state"], "listening")
        self.assertEqual(json.loads(self.page("/api/state"))["phase"], "listening")  # the child screen follows
        began = time.monotonic()
        self.assertEqual(self.post_json("/stop"), {"ok": True})
        state = self.wait_rec()
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual(state, {"state": "done", "error": None, "go": "/word"})
        self.assertEqual(self.mic.stops, 1)
        body = self.page("/word")
        self.assertIn("Picked automatically, listen to check", body)
        self.assertIn('id="sel-canvas"', body)
        self.assertIn("The r sounded right", body)

    def test_nothing_moves_while_recording(self):
        self.mic.seconds = 10
        self.start()
        self.post_json("/record", headers={"X-Record": "background"})
        self.assertTrue(self.mic.listening.wait(2))
        status, headers, _ = self.post("/next")
        self.assertEqual((status, headers["Location"]), (303, "/word"))
        refused = self.post_json("/record", headers={"X-Record": "background"})
        self.assertFalse(refused["ok"])
        self.assertIn("Stop", refused["error"])
        self.post("/stop")
        self.wait_rec()
        self.assertIn("word 1 of 2", self.page("/word"))

    def test_stop_with_no_recording_does_nothing(self):
        self.start()
        self.assertEqual(self.post_json("/stop"), {"ok": True})
        self.assertEqual(self.mic.stops, 0)

    def test_background_failure_is_reported_to_the_page(self):
        self.mic.fail = True
        self.start()
        self.post_json("/record", headers={"X-Record": "background"})
        state = self.wait_rec()
        self.assertEqual(state["state"], "error")
        self.assertIn("Recording failed: mic unplugged", state["error"])
        self.assertEqual(json.loads(self.page("/api/state"))["phase"], "idle")

    def test_practice_records_in_the_background_too(self):
        self.start("practice")
        self.post_json("/practice/record", headers={"X-Record": "background"})
        self.assertEqual(self.wait_rec()["go"], "/practice")
        self.assertIn('id="sel-canvas"', self.page("/practice"))

    def test_plain_form_record_still_works_without_the_script(self):
        self.start()
        status, headers, _ = self.post("/record")
        self.assertEqual((status, headers["Location"]), (303, "/word"))
        self.assertIn("Picked automatically", self.page("/word"))

    # The selection and its rescoring

    def test_arti_hears_only_the_auto_pick(self):
        self.start()
        self.post("/record")
        word, path, seconds = self.heard[-1]
        self.assertEqual(word, "rabbit")
        self.assertTrue(path.name.endswith("-rabbit-word.wav"))
        self.assertAlmostEqual(seconds, 0.55 + 2 * 0.05, delta=0.03)  # the word, not the "um"
        full = self.request("GET", "/audio/s0-full.wav")[2]
        cut = self.request("GET", "/audio/s0.wav")[2]
        self.assertGreater(len(full), len(cut))

    def test_moving_the_box_rescores_the_crop(self):
        self.start()
        self.post("/record")
        self.outcome = "gliding"
        reply = self.post_json("/select", {"start": "0.2", "end": "0.8"}, {"X-Select": "json"})
        self.assertEqual(reply, {"ok": True, "start": 0.2, "end": 0.8, "auto": False})
        word, path, seconds = self.heard[-1]
        self.assertTrue(path.name.endswith("-word.wav"))
        self.assertAlmostEqual(seconds, 0.6, places=2)
        body = self.page("/word")
        self.assertIn("Moved by you", body)
        self.assertIn("The r sounded off", body)  # Arti's new answer on the crop
        self.assertIn("0.20 s to 0.80 s", body)
        with wave.open(str(path)) as w:  # what /audio/s0.wav and the analysis page now use
            self.assertAlmostEqual(w.getnframes() / w.getframerate(), 0.6, places=2)
        analysis = self.page("/analysis/s0")
        self.assertIn('"/audio/s0.wav"', analysis.replace("\\/", "/"))

    def test_slps_call_survives_a_rescore(self):
        self.start()
        self.post("/record")
        self.post("/verify", {"verdict": "wrong"})
        self.post_json("/select", {"start": "0.5", "end": "1.2"}, {"X-Select": "json"})
        body = self.page("/word")
        self.assertIn("Your call is saved", body)
        self.assertIn('class="half disagree on"', body)  # Arti said right, the SLP said wrong
        self.assertNotIn("Arti changed its answer", body)

    def test_card_says_when_arti_changed_its_answer_after_the_check(self):
        self.start()
        self.post("/record")
        self.post("/verify", {"verdict": "agree"})  # Arti said right, and so did the SLP
        self.outcome = "gliding"
        self.post_json("/select", {"start": "0.5", "end": "1.2"}, {"X-Select": "json"})
        body = self.page("/word")
        self.assertIn("Arti changed its answer after you moved the box.", body)
        self.assertIn('class="half disagree on"', body)  # the saved call is still "right"; Arti now says off
        self.outcome = None
        self.post_json("/select", {"start": "0.4", "end": "1.2"}, {"X-Select": "json"})
        self.assertNotIn("Arti changed its answer", self.page("/word"))  # back to the answer the SLP agreed with

    def test_pick_again_goes_back_to_the_auto_pick(self):
        self.start()
        self.post("/record")
        auto_seconds = self.heard[-1][2]
        self.post_json("/select", {"start": "0.0", "end": "0.4"}, {"X-Select": "json"})
        self.assertIn("Pick again automatically", self.page("/word"))
        status, headers, _ = self.post("/select", {"reset": "1"})
        self.assertEqual((status, headers["Location"]), (303, "/word"))
        self.assertAlmostEqual(self.heard[-1][2], auto_seconds, places=2)
        self.assertIn("Picked automatically", self.page("/word"))

    def test_box_is_kept_inside_the_clip(self):
        self.start()
        self.post("/record")
        reply = self.post_json("/select", {"start": "-3", "end": "99"}, {"X-Select": "json"})
        self.assertEqual(reply["start"], 0.0)
        self.assertAlmostEqual(reply["end"], sum(s for s, _ in UM_THEN_WORD), places=2)

    def test_bad_selection_is_refused(self):
        self.start()
        reply = self.post_json("/select", {"start": "0.1", "end": "0.5"}, {"X-Select": "json"})
        self.assertFalse(reply["ok"])  # nothing recorded yet
        self.post("/record")
        reply = self.post_json("/select", {"start": "soon", "end": "0.5"}, {"X-Select": "json"})
        self.assertFalse(reply["ok"])
        self.assertIn("start and an end", reply["error"])

    def test_practice_phrase_picks_the_target_word_and_can_be_moved(self):
        self.start("practice")
        for _ in range(2):  # two right answers: word, then phrase level
            self.post("/practice/record")
            self.post("/practice/verify", {"verdict": "correct"})
            self.post("/practice/next")
        line = self.server.practice.line
        self.assertEqual(self.server.practice.level, "sentence")
        self.mic.pieces = [(0.3, 0)] + [(0.2, 0.4), (0.15, 0)] * (len(line.split()) - 1) + [(0.45, 0.4), (0.4, 0)]
        self.post("/practice/record")
        info = self.server.info[f"p{self.server.practice.turn}"]
        self.assertEqual(line, "the puppy sees a soft rabbit.")  # the fixed line; rabbit is the last word
        self.assertAlmostEqual(info.selection[1] - info.selection[0], 0.45 + 0.1, delta=0.03)
        self.assertEqual(info.method, "count")
        self.assertEqual(info.line, line)
        reply = self.post_json("/practice/select", {"start": "0.3", "end": "0.6"}, {"X-Select": "json"})
        self.assertTrue(reply["ok"])
        self.assertEqual(self.server.practice.current_attempt.sel_auto, False)

    def test_selection_is_saved_with_the_attempt(self):
        self.start()
        self.post("/record")
        self.post_json("/select", {"start": "0.5", "end": "1.1"}, {"X-Select": "json"})
        self.post("/next")
        self.post("/record")
        self.post("/next")
        with closing(sqlite3.connect(self.dir / "data" / "speakup.db")) as conn:
            rows = conn.execute("SELECT word, sel_start, sel_end, sel_auto FROM results ORDER BY position").fetchall()
        self.assertEqual(rows[0], ("rabbit", 0.5, 1.1, 0))
        self.assertEqual(rows[1][0], "carrot")
        self.assertEqual(rows[1][3], 1)
        self.assertLess(rows[1][1], rows[1][2])

    # The target sound window on the analysis viewer (Nov 5)

    def test_moving_the_target_window_remeasures_and_is_kept_with_the_try(self):
        self.start()
        self.post("/record")
        auto = self.server.info["s0"].target_window
        self.assertIsNone(auto)
        reply = self.post_json("/analysis/s0/window", {"start": "0.30", "end": "0.45"})
        self.assertTrue(reply["ok"])
        self.assertTrue(reply["manual"])
        self.assertEqual(reply["window"], [0.3, 0.45])
        self.assertIn("Target sound window (moved by you)", reply["measures_html"])
        self.assertIn("in the target window you set", reply["gap_text"]) if reply["gap"] else \
            self.assertIn("not measured", reply["gap_text"])
        self.assertEqual(self.server.info["s0"].target_window, (0.3, 0.45))
        page = self.page("/analysis/s0")
        self.assertIn('"win_manual":true', page)
        self.assertIn("Target sound window (moved by you)", page)
        self.assertNotIn("in the target window you set", self.page("/word")) if not reply["gap"] else \
            self.assertIn("in the target window you set", self.page("/word"))
        back = self.post_json("/analysis/s0/window", {"reset": "1"})
        self.assertFalse(back["manual"])
        self.assertEqual(back["window"], back["auto_window"])
        self.assertLess(back["gap"]["t"], back["auto_window"][1] + 1e-9)
        self.assertIn("where the r should be", back["gap_text"])
        self.assertIsNone(self.server.info["s0"].target_window)

    def test_target_window_refuses_bad_input_and_unknown_tries(self):
        self.start()
        self.assertFalse(self.post_json("/analysis/s0/window", {"start": "0.1", "end": "0.2"})["ok"])  # no try yet
        self.post("/record")
        for bad in ({"start": "x", "end": "0.2"}, {"start": "nan", "end": "0.2"}, {"start": "0.1"}):
            reply = self.post_json("/analysis/s0/window", bad)
            self.assertFalse(reply["ok"])
            self.assertIn("start and an end", reply["error"])
        self.assertIsNone(self.server.info["s0"].target_window)

    def test_moving_the_word_box_drops_the_target_window(self):
        self.start()
        self.post("/record")
        self.post_json("/analysis/s0/window", {"start": "0.05", "end": "0.2"})
        self.post_json("/select", {"start": "0.2", "end": "0.8"}, {"X-Select": "json"})
        self.assertIsNone(self.server.info["s0"].target_window)

    def test_word_page_opens_the_full_view_over_itself(self):
        self.start()
        self.post("/record")
        body = self.page("/word")
        self.assertIn('data-full="/analysis/s0"', body)
        self.assertNotIn("Open full view", body)  # the owner wants the plain arrow back, no button
        self.assertIn('<a class="expand" href="/analysis/s0" data-full="/analysis/s0" title="Open the full sound analysis" '
                      'aria-label="Open the full sound analysis">⤢</a>', body)
        self.assertIn('<a class="picture" href="/analysis/s0" data-full="/analysis/s0"', body)
        self.assertIn('class="fv-book"', body)  # the full view carries the Sound book link
        self.assertIn("window.FullView", body)
        self.assertIn('id="sel-canvas"', body)  # the word box is still there
        embed = self.page("/analysis/s0?embed=1")
        self.assertIn("sv-close", embed)
        self.assertIn('class="backnav" href="#" data-close-full="1"', embed)  # Back on the page closes the overlay
        plain = self.page("/analysis/s0")
        self.assertIn('<a class="backnav" href="/word"', plain)  # the direct link still works as its own page
        self.assertNotIn("sv-close", plain)
        self.assertNotIn("Compare with typical", plain)
        self.assertIn('id="sv-cmp-pop"', plain)  # the Compare tool's pop-up


if __name__ == "__main__":
    unittest.main()
