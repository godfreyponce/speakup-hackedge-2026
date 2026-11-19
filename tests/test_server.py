import json
import sqlite3
from datetime import date, timedelta

from tests.test_acoustics import synth
from tests.test_acoustics import write as write_voice
from tests.test_clipcheck import write_clip
import http.client
import io
import multiprocessing
import os
import re
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import BrokenExecutor, ProcessPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from speakup import acoustics
from speakup.bank import Bank
from speakup.clipcheck import check_clip
from speakup.llm import LlmError
from speakup.recorder import RecorderError
from speakup.server import make_server
from speakup.store import load_sessions, save_session
from speakup.words import Word

HEARD = {None: "ɹ", "gliding": "w", "distortion": None, "off": None}

TRUE_NOTE = "The child tried 2 words with the r sound. Rabbit had gliding (heard w), which is flagged for age."
PENDING = '<p class="note">Qwen, a small language model on the board, is writing a note on these results.</p>'
REFRESH = '<meta http-equiv="refresh" content="3; url=/summary">'


class NoteModel:
    """Stands in for llama.cpp: records each prompt, then replies or raises."""

    def __init__(self, reply=None, raise_=None, gate: threading.Event | None = None):
        self.reply = reply
        self.raise_ = raise_
        self.gate = gate
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        if self.gate:
            self.gate.wait()
        if self.raise_:
            raise self.raise_
        return self.reply(prompt) if callable(self.reply) else self.reply


def check_or_die(path):
    """The recording check, but a worker process dies on it, as under the OOM killer."""
    if multiprocessing.parent_process() is not None:
        os._exit(1)
    return check_clip(path)


def analyse_or_die(path, position):
    """The sound analysis, but a worker process dies on it, as under the OOM killer."""
    if multiprocessing.parent_process() is not None:
        os._exit(1)
    return ANALYSE(path, position)


ANALYSE = acoustics.analyse


class BrokenPool:
    """A worker pool that can never take a job, so later() has to run it here."""

    def __init__(self, workers=None):
        pass

    def submit(self, fn, *args):
        raise BrokenExecutor("no workers")

    def shutdown(self, wait=True):
        pass


# The family notes (#39) for the server tests' session: rabbit flagged at 8 yr 0 mo, carrot said right.
FAMILY_EN = "Today your child said 2 words with the r sound. Please practice rabbit at home, slowly and for fun."
FAMILY_ES = "Hoy su hijo o hija dijo 2 palabras con el sonido r. Practiquen rabbit en casa, despacio y jugando."
FIXED_EN = "Words your child said today with the r sound: 2. Please practice these words at home, slowly and for fun: rabbit."
FIXED_ES = "Palabras con el sonido r que su hijo o hija dijo hoy: 2. Practiquen estas palabras en casa, despacio y jugando: rabbit."
CHECKED = '<span class="pill ok">✓ every number checked by code</span>'


def by_prompt(slp=TRUE_NOTE, en=FAMILY_EN, es=FAMILY_ES):
    """A reply for each of the three prompts: the SLP note, then the family note in English and in Spanish."""
    return lambda prompt: es if "Palabras para practicar" in prompt else en if "Words to practice" in prompt else slp


def birth_date_for(years: int, months: int) -> str:
    """The birth date that makes a child exactly years and months old today."""
    today = date.today()
    total = today.year * 12 + today.month - 1 - (years * 12 + months)
    return date(total // 12, total % 12 + 1, min(today.day, 28)).isoformat()


class ServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.recordings = Path(tmp.name) / "recordings"
        self.db = Path(tmp.name) / "data" / "speakup.db"
        self.outcomes = {}
        self.clips = []
        self.clip_pieces = None  # set to (seconds, amplitude) runs to have the stand-in mic write a real WAV
        self.clip_voice = None  # or to a synthetic voice (numpy array) for the sound analysis
        self.mic_fails = False
        self.bad_model = False
        self.disk_fails = False
        self.sound = "r"
        patcher = mock.patch("speakup.server.save_session", self.save_session)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = make_server(
            "127.0.0.1", 0,
            words=[Word("rabbit", "start"), Word("carrot", "middle")],
            listen=self.listen,
            recorder=self,
            recordings_dir=self.recordings,
            db_path=self.db,
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.server = server
        self.port = server.server_address[1]

    def quiet_stderr(self):
        patcher = mock.patch("sys.stderr", new_callable=io.StringIO)
        err = patcher.start()
        self.addCleanup(patcher.stop)
        return err

    # The test case stands in for the recorder.
    def record(self, path):
        if self.mic_fails:
            raise RecorderError("mic unplugged")
        if self.clip_voice is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_voice(path, self.clip_voice)
        elif self.clip_pieces is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_clip(path, self.clip_pieces)
        self.clips.append(path)

    def save_session(self, db_path, session):
        if self.disk_fails:
            raise OSError("No space left on device")
        return save_session(db_path, session)

    def listen(self, word, path):
        if self.bad_model:
            return {"word": word}
        error_type = self.outcomes.get(word)
        return {
            "word": word, "target_sound": self.sound, "expected_phone": "ɹ",
            "heard_phone": HEARD[error_type], "error_type": error_type,
            "confidence": None, "model": "stub", "recorded_at": "2026-11-05T10:15:00-06:00",
        }

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(fields) if fields is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, dict(response.getheaders()), response.read().decode("utf-8")
        conn.close()
        return result

    def get(self, path):
        return self.request("GET", path)

    def post(self, path, fields=None):
        return self.request("POST", path, fields or {})

    def start(self, years="8", months="0"):
        return self.post("/start", {"student_id": "S-014", "birth_date": birth_date_for(int(years), int(months))})

    def finish(self, years="8", months="0"):
        self.start(years, months)
        for _ in range(2):
            self.post("/record")
            self.post("/next")

    def wait_for_note(self):
        self.server.note_thread.join(timeout=5)
        self.assertFalse(self.server.note_thread.is_alive())

    def gated(self, *args, **kwargs):
        gate = threading.Event()
        self.addCleanup(gate.set)
        return NoteModel(*args, gate=gate, **kwargs), gate

    def assertRedirect(self, response, location):
        status, headers, _ = response
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], location)

    def test_home_shows_start_form(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        for name in ['name="student_id"', 'name="birth_date"', 'type="date"', "It is not saved."]:
            self.assertIn(name, body)

    def test_start_rejects_bad_input(self):
        future = (date.today() + timedelta(days=3)).isoformat()
        bad = [("../x", "2018-01-01"), ("Emma Smith", "2018-01-01"), ("", "2018-01-01"), ("S-014", ""),
               ("S-014", "01/02/2018"), ("S-014", future), ("S-014", "1950-01-01")]
        for student_id, birth_date in bad:
            with self.subTest(student_id=student_id, birth_date=birth_date):
                status, _, body = self.post("/start", {"student_id": student_id, "birth_date": birth_date})
                self.assertEqual(status, 400)
                self.assertIn('name="student_id"', body)
                self.assertNotIn("Child ID", body)
        self.assertRedirect(self.get("/word"), "/")

    def test_birth_date_is_never_stored(self):
        self.post("/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 3)})
        for _ in range(2):
            self.post("/record")
            self.post("/next")
        conn = sqlite3.connect(self.db)
        dump = " ".join(conn.iterdump())
        conn.close()
        self.assertNotIn(birth_date_for(8, 3), dump)
        self.assertIn("99", dump)  # 8 yr 3 mo = 99 months is what is kept

    def test_start_then_word(self):
        self.assertRedirect(self.start(), "/word")
        status, _, body = self.get("/word")
        self.assertEqual(status, 200)
        self.assertIn("rabbit", body)

    def test_pages_before_start_redirect_home(self):
        self.assertRedirect(self.get("/word"), "/")
        self.assertRedirect(self.get("/summary"), "/")

    def test_record_shows_flag_for_age(self):
        self.outcomes["rabbit"] = "gliding"
        self.start("7", "0")
        self.assertRedirect(self.post("/record"), "/word")
        body = self.get("/word")[2]
        self.assertIn("Arti suggests", body)
        self.assertIn("r sounded off", body)
        self.assertIn("Flagged: this error is expected to be gone by 7 yr 0 mo, and the child is 7 yr 0 mo.", body)

        self.start("6", "11")
        self.post("/record")
        self.assertIn("Keep an eye on it: it is worth watching from 5 yr 0 mo", self.get("/word")[2])

    def test_off_reads_sounded_off(self):
        self.outcomes["rabbit"] = "off"
        self.start()
        self.post("/record")
        body = self.get("/word")[2]
        self.assertIn("r sounded off", body)
        self.assertNotIn("(off)", body)

    def test_child_state_never_carries_a_result(self):
        self.outcomes["rabbit"] = "gliding"
        self.start("8", "0")
        self.post("/record")
        status, _, body = self.get("/api/state")
        self.assertEqual(status, 200)
        state = json.loads(body)
        self.assertEqual((state["word"], state["tried"], state["phase"]), ("rabbit", True, "idle"))
        for leak in ("gliding", "flag", "error", "heard", "confidence", "child"):
            self.assertNotIn(leak, body.lower())

    def test_kid_page_has_no_result_words(self):
        status, _, body = self.get("/kid")
        self.assertEqual(status, 200)
        for leak in ("Flagged", "Heard", "sounded off", "confidence"):
            self.assertNotIn(leak, body)

    def test_slp_verdict_replaces_arti_and_moves_on(self):
        self.outcomes["rabbit"] = "gliding"
        self.start("8", "0")
        self.post("/record")
        self.assertRedirect(self.post("/verify", {"verdict": "correct"}), "/word")
        attempt = self.server.session.attempts[0]
        self.assertEqual((attempt.slp, attempt.result.error_type, attempt.flagged), ("correct", None, False))
        self.assertEqual(attempt.arti.error_type, "gliding")
        self.assertEqual((attempt.result.model, attempt.arti_call), ("stub", "wrong"))

    def test_verify_before_record_is_refused(self):
        self.start()
        status, _, _ = self.post("/verify", {"verdict": "wrong"})
        self.assertEqual(status, 400)

    def test_picture_served_and_bad_name_404(self):
        self.assertEqual(self.get("/pics/rabbit.svg")[0], 200)
        self.assertEqual(self.get("/pics/../server.svg")[0], 404)

    def test_felt_layer_served_and_bad_path_404(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/felt/meadow.webp")
        response = conn.getresponse()
        body = response.read()
        conn.close()
        self.assertEqual((response.status, response.getheader("Content-Type")), (200, "image/webp"))
        self.assertEqual(body[8:12], b"WEBP")
        for bad in ("/felt/../server.py", "/felt/meadow.png", "/felt/Meadow.webp"):
            self.assertEqual(self.get(bad)[0], 404)

    def test_look_page_shows_every_world_and_buddy(self):
        status, _, body = self.get("/look")
        self.assertEqual(status, 200)
        for world in ("meadow", "garden", "bakery", "night"):
            self.assertIn(f'src="/felt/thumb-{world}.webp"', body)
        for buddy in ("patch", "dusty", "juniper", "toffee"):
            self.assertIn(f'src="/felt/{buddy}-spin-000.webp"', body)
        self.assertIn('value="meadow" aria-pressed="true"', body)
        self.assertIn('value="patch" aria-pressed="true"', body)
        self.assertIn('href="/look"', self.get("/")[2])

    def test_look_pick_reaches_the_child_screen(self):
        self.assertEqual(json.loads(self.get("/api/state")[2])["look"], {"world": "meadow", "buddy": "patch"})
        self.assertRedirect(self.post("/look", {"world": "night"}), "/look")
        self.assertRedirect(self.post("/look", {"buddy": "toffee"}), "/look")
        self.assertEqual(json.loads(self.get("/api/state")[2])["look"], {"world": "night", "buddy": "toffee"})
        self.assertIn('value="night" aria-pressed="true"', self.get("/look")[2])

    def test_look_refuses_what_was_not_built(self):
        for fields in ({"world": "picker"}, {"buddy": "Patch"}, {"world": "../meadow"}, {}):
            status, _, body = self.post("/look", fields)
            self.assertEqual(status, 400)
            self.assertIn("Pick a world or a buddy", body)
        self.assertEqual(self.server.look, {"world": "meadow", "buddy": "patch"})

    def test_recording_check_warns_on_silence(self):
        self.clip_pieces = [(3.0, 0)]
        self.start()
        self.post("/record")
        body = self.get("/word")[2]
        self.assertIn("Check the recording before trusting Arti", body)
        self.assertIn("No speech heard", body)
        self.assertIn("don't rely on it", body)
        self.assertNotIn("ok suggested", body)
        self.assertNotIn("off suggested", body)
        self.assertIn('src="/audio/s0.wav"', body)
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", "/audio/s0.wav")
        response = conn.getresponse()
        self.assertEqual((response.status, response.getheader("Content-Type"), response.read()[:4]),
                         (200, "audio/wav", b"RIFF"))
        conn.close()

    def test_recording_check_ok_on_a_clear_word(self):
        self.clip_pieces = [(1.0, 0), (0.6, 9000), (1.4, 0)]
        self.start()
        self.post("/record")
        self.assertIn("Recording OK", self.get("/word")[2])

    def test_record_goes_on_after_a_worker_dies(self):
        self.server.workers = 1
        self.server.pool = ProcessPoolExecutor(1)
        self.addCleanup(lambda: self.server.pool.shutdown())
        self.server.pool.submit(os._exit, 1).exception()  # the worker dies, as under the OOM killer
        self.quiet_stderr()
        self.clip_pieces = [(1.0, 0), (0.6, 9000), (1.4, 0)]
        self.start()
        self.assertRedirect(self.post("/record"), "/word")
        self.assertEqual(len(self.server.session.attempts), 1)
        self.assertIn("Recording OK", self.get("/word")[2])

    def test_try_is_shown_when_a_worker_dies_during_the_check(self):
        self.server.workers = 1
        self.server.pool = ProcessPoolExecutor(1)
        self.addCleanup(lambda: self.server.pool.shutdown())
        mock.patch("speakup.server.check_clip", check_or_die).start()
        self.addCleanup(mock.patch.stopall)
        self.quiet_stderr()
        self.clip_pieces = [(1.0, 0), (0.6, 9000), (1.4, 0)]
        self.start()
        self.assertRedirect(self.post("/record"), "/word")
        self.assertEqual(len(self.server.session.attempts), 1)
        self.assertIn("Recording OK", self.get("/word")[2])

    def test_sound_picture_is_shown_when_a_worker_dies_during_the_analysis(self):
        self.server.workers = 1
        self.server.pool = ProcessPoolExecutor(1)
        self.addCleanup(lambda: self.server.pool.shutdown())
        mock.patch("speakup.acoustics.analyse", analyse_or_die).start()
        self.addCleanup(mock.patch.stopall)
        self.quiet_stderr()
        self.clip_voice = synth(150, [(450, 80), (1200, 100), (1650, 120)])
        self.start()
        self.assertRedirect(self.post("/record"), "/word")
        self.assertIn("Sound picture (estimate)", self.get("/word")[2])
        body = self.get("/analysis/s0")[2]
        self.assertNotIn("laptop", body)
        self.assertIn("Frame by frame", body)

    def test_jobs_run_here_when_the_pool_cannot_be_rebuilt(self):
        self.server.workers = 1
        self.server.pool = BrokenPool()
        mock.patch("speakup.server.ProcessPoolExecutor", BrokenPool).start()
        self.addCleanup(mock.patch.stopall)
        self.quiet_stderr()
        self.clip_pieces = [(1.0, 0), (0.6, 9000), (1.4, 0)]
        self.start()
        self.assertRedirect(self.post("/record"), "/word")
        self.assertEqual(len(self.server.session.attempts), 1)
        self.assertIn("Recording OK", self.get("/word")[2])

    def test_no_clip_says_test_mode_and_offers_no_replay(self):
        self.start()
        self.post("/record")
        body = self.get("/word")[2]
        self.assertIn("laptop test mode", body)
        self.assertNotIn("/audio/", body)
        self.assertNotIn('class="listen"', body)
        self.assertIn("leaves out Listen to the box", body)

    def test_word_page_shows_last_time_for_this_child(self):
        self.outcomes["rabbit"] = "gliding"
        self.finish()
        self.start()
        self.assertIn("the r sounded off (Arti only, not checked)", self.get("/word")[2])

    def test_word_page_shows_session_tally_and_agreement(self):
        self.outcomes["rabbit"] = "gliding"
        self.start()
        self.post("/record")
        self.post("/verify", {"verdict": "wrong"})
        body = self.get("/word")[2]
        self.assertIn("<td>r at the start</td><td>0 right, 1 off</td>", body)
        self.assertIn("You agreed with Arti on 1 of 1 checked words.", body)

    def test_child_state_carries_line_and_picture(self):
        self.start()
        state = json.loads(self.get("/api/state")[2])
        self.assertEqual((state["line"], state["picture"]), ("rabbit", "/pics/rabbit.svg"))

    def test_word_page_shows_the_sound_picture(self):
        self.clip_voice = synth(150, [(450, 80), (1200, 100), (1650, 120)])
        self.start()
        self.post("/record")
        body = self.get("/word")[2]
        self.assertIn("Sound picture (estimate)", body)
        self.assertIn("F3-F2 gap where the r should be:", body)
        self.assertIn('href="/analysis/s0"', body)
        # The picture itself opens the full analysis, and there is no reading guide on the screen.
        self.assertIn('<a class="picture" href="/analysis/s0"', body)
        self.assertNotIn("Small is r-like", body)

    def test_analysis_page_without_then_with_a_reference(self):
        self.clip_voice = synth(150, [(450, 80), (1200, 100), (1650, 120)])
        self.start()
        self.post("/record")
        body = self.get("/analysis/s0")[2]
        self.assertIn("Sound analysis: rabbit", body)
        # No reference yet: the comparison card is left out rather than shown empty.
        self.assertNotIn("Compared with this student", body)
        self.assertNotIn("How to read it", body)
        self.assertIn('id="sv-data"', body)
        self.assertIn('src="/audio/s0.wav"', body)
        self.assertIn("Frame by frame", body)
        self.assertIn("F0 median", body)
        self.assertIn("Screening aid, not a diagnosis.", body)
        # The SLP calls it correct; the next session can compare against it.
        self.post("/verify", {"verdict": "correct"})
        self.post("/next")
        self.post("/record")
        self.post("/verify", {"verdict": "correct"})
        self.post("/next")
        self.start()
        self.post("/record")
        body = self.get("/analysis/s0")[2]
        self.assertIn("Correct on", body)
        self.assertIn("about the same as in that correct production", body)

    def test_analysis_before_start_goes_home(self):
        self.assertRedirect(self.get("/analysis/s0"), "/")

    def test_record_saves_clip_under_recordings_dir(self):
        self.start()
        self.post("/record")
        self.assertEqual(len(self.clips), 1)
        clip = self.clips[0]
        self.assertEqual(clip.parent, self.recordings)
        self.assertTrue(clip.name.startswith("S-014-"))
        self.assertTrue(clip.name.endswith("-rabbit.wav"))

    def test_next_waits_for_a_result(self):
        self.start()
        self.assertRedirect(self.post("/next"), "/word")
        self.assertIn("rabbit", self.get("/word")[2])

    def test_full_session_refer_and_pass(self):
        self.outcomes["rabbit"] = "gliding"
        self.start()
        self.post("/record")
        self.assertRedirect(self.post("/next"), "/word")
        self.post("/record")
        self.assertRedirect(self.post("/next"), "/summary")
        body = self.get("/summary")[2]
        self.assertIn("Refer: 1 of 2 words flagged for age 8 yr 0 mo (rabbit).", body)
        self.assertIn("Flagged: gliding 1<", body)

        self.outcomes.clear()
        self.start()
        for _ in range(2):
            self.post("/record")
            self.post("/next")
        self.assertIn("Pass: 0 of 2 words flagged for age 8 yr 0 mo.", self.get("/summary")[2])

    def test_recorder_error_shows_on_word_page(self):
        self.start()
        self.mic_fails = True
        status, _, body = self.post("/record")
        self.assertEqual(status, 500)
        self.assertIn("Recording failed: mic unplugged", body)
        self.assertIn("rabbit", body)
        self.mic_fails = False
        self.assertRedirect(self.post("/record"), "/word")

    def test_bad_model_record_shows_error(self):
        self.start()
        self.bad_model = True
        status, _, body = self.post("/record")
        self.assertEqual(status, 500)
        self.assertIn("Model gave a bad result", body)
        self.assertNotIn("Heard:", self.get("/word")[2])

    def test_summary_and_record_out_of_order(self):
        self.start()
        self.assertRedirect(self.get("/summary"), "/word")
        for _ in range(2):
            self.post("/record")
            self.post("/next")
        self.assertRedirect(self.post("/record"), "/summary")
        self.assertRedirect(self.get("/word"), "/summary")

    def test_model_result_with_no_age_norm_shows_error(self):
        self.outcomes["rabbit"] = "gliding"
        self.sound = "s"
        self.start()
        status, _, body = self.post("/record")
        self.assertEqual(status, 500)
        self.assertIn("Model gave a bad result", body)
        self.assertNotIn("Heard:", self.get("/word")[2])

    def test_unknown_path_is_404(self):
        self.assertEqual(self.get("/nope")[0], 404)

    def test_pages_load_nothing_from_elsewhere(self):
        self.outcomes["rabbit"] = "gliding"
        bodies = [self.get("/")[2]]
        self.start()
        self.post("/record")
        bodies.append(self.get("/word")[2])
        self.post("/next")
        self.post("/record")
        self.post("/next")
        bodies.append(self.get("/summary")[2])
        bodies.append(self.get("/sessions")[2])
        bodies.append(self.get("/child/S-014")[2])
        for body in bodies:
            self.assertNotIn("://", body)
            self.assertNotIn("<script src", body)  # inline, same-page scripts only (Nov 4: Record, Stop, the box)

    def test_finished_session_is_saved(self):
        self.start()
        self.post("/record")
        self.outcomes["rabbit"] = "gliding"
        self.post("/record")
        self.post("/next")
        self.post("/record")
        self.assertEqual(load_sessions(self.db), [])
        self.assertRedirect(self.post("/next"), "/summary")
        [saved] = load_sessions(self.db)
        self.assertEqual([r.word for r in saved.results], ["rabbit", "carrot"])
        self.assertEqual(saved.results[0].error_type, "gliding")

        self.assertRedirect(self.post("/next"), "/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)

        self.start()
        self.post("/record")
        self.assertEqual(len(load_sessions(self.db)), 1)

    def test_failed_save_warns_and_save_again_saves(self):
        self.disk_fails = True
        self.start()
        self.post("/record")
        self.post("/next")
        self.post("/record")
        status, _, body = self.post("/next")
        self.assertEqual(status, 500)
        self.assertIn("Not saved: No space left on device. The results below are not stored.", body)
        self.assertIn('<form method="post" action="/save"><button class="primary">Save again</button></form>', body)
        self.assertIn("Pass: 0 of 2 words flagged", body)
        self.assertEqual(load_sessions(self.db), [])
        status, _, body = self.get("/summary")
        self.assertEqual(status, 500)
        self.assertIn("Not saved: No space left on device.", body)
        self.assertEqual(self.post("/save")[0], 500)

        self.disk_fails = False
        self.assertRedirect(self.post("/save"), "/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertNotIn("Not saved", body)
        self.assertIn("Pass: 0 of 2 words flagged", body)
        self.assertRedirect(self.post("/save"), "/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)

    def test_saved_summary_has_no_warning(self):
        self.assertRedirect(self.post("/save"), "/")
        self.finish()
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertNotIn("Not saved", body)
        self.assertNotIn('action="/save"', body)

    def test_sessions_page_lists_saved(self):
        self.assertIn('href="/sessions"', self.get("/")[2])
        status, _, body = self.get("/sessions")
        self.assertEqual(status, 200)
        self.assertNotIn('href="/child/', body)

        self.outcomes["rabbit"] = "gliding"
        self.finish()
        status, _, body = self.get("/sessions")
        self.assertEqual(status, 200)
        self.assertIn('href="/child/S-014"', body)
        self.assertIn('<td class="age">8 yr 0 mo</td><td class="n hot">1</td>', body)
        started = datetime.fromisoformat(load_sessions(self.db)[0].started_at)
        self.assertIn(f"{started:%b} {started.day}, {started.year}", body)

    def test_child_page_shows_sessions_in_order(self):
        self.outcomes["rabbit"] = "gliding"
        self.finish("6", "11")
        self.finish("7", "0")
        status, _, body = self.get("/child/S-014")
        self.assertEqual(status, 200)
        older, newer = re.findall(r'<tr class="session">(.*?)</tr>', body, re.S)
        self.assertIn("6 yr 11 mo", older)
        self.assertIn('class="chip normal">rabbit<', older)
        self.assertIn("7 yr 0 mo", newer)
        self.assertIn('class="chip flag">rabbit<', newer)
        self.assertIn('<span class="chip normal">wrong, not flagged for age</span>', body)

    def test_child_page_unknown_or_bad_id_is_404(self):
        self.finish()
        self.assertEqual(self.get("/child/S-014")[0], 200)
        for path in ["/child/S-999", "/child/..", "/child/S-014/x", "/child/"]:
            with self.subTest(path=path):
                self.assertEqual(self.get(path)[0], 404)


    def test_end_screen_works_with_no_model(self):
        self.outcomes["rabbit"] = "gliding"
        self.finish()
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertIn("Refer: 1 of 2 words flagged for age 8 yr 0 mo (rabbit).", body)
        self.assertIn("Flagged: gliding 1<", body)
        self.assertNotIn('class="note"', body)
        self.assertNotIn(REFRESH, body)
        self.assertIsNone(self.server.note_thread)

    def test_end_screen_shows_tally_while_note_is_written(self):
        self.outcomes["rabbit"] = "gliding"
        fake, gate = self.gated(TRUE_NOTE)
        self.server.generate = fake
        self.finish()
        self.assertEqual(len(load_sessions(self.db)), 1)
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertIn("Refer: 1 of 2 words flagged for age 8 yr 0 mo (rabbit).", body)
        self.assertIn("Flagged: gliding 1<", body)
        self.assertIn(PENDING, body)
        self.assertNotIn("minute", body)
        self.assertIn(REFRESH, body)
        self.assertNotIn("Note by Qwen", body)
        gate.set()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertIn(f'<p class="note"><b>Note by Qwen, a small language model running on the board:</b> {TRUE_NOTE}</p>', body)
        self.assertNotIn(PENDING, body)
        self.assertNotIn(REFRESH, body)

    def test_old_note_dropped_on_new_session(self):
        self.outcomes["rabbit"] = "gliding"
        fake, gate = self.gated(TRUE_NOTE)
        self.server.generate = fake
        self.finish()
        old = self.server.note_thread
        self.server.generate = None
        self.finish()
        gate.set()
        old.join(timeout=5)
        self.assertFalse(old.is_alive())
        body = self.get("/summary")[2]
        self.assertNotIn('class="note"', body)
        self.assertNotIn(REFRESH, body)

    def test_old_note_leaves_new_pending_line(self):
        self.outcomes["rabbit"] = "gliding"
        fake, gate = self.gated(TRUE_NOTE)
        self.server.generate = fake
        self.finish()
        old = self.server.note_thread
        self.server.generate, gate2 = self.gated(TRUE_NOTE)
        self.finish()
        gate.set()
        old.join(timeout=5)
        self.assertFalse(old.is_alive())
        body = self.get("/summary")[2]
        self.assertIn(PENDING, body)
        self.assertIn(REFRESH, body)
        self.assertNotIn("Note by Qwen", body)
        gate2.set()
        self.wait_for_note()
        self.assertIn(f'<p class="note"><b>Note by Qwen, a small language model running on the board:</b> {TRUE_NOTE}</p>', self.get("/summary")[2])

    def test_unexpected_note_error_clears_pending_line(self):
        self.outcomes["rabbit"] = "gliding"
        self.quiet_stderr()
        self.server.generate = NoteModel(raise_=RuntimeError("boom"))
        self.finish()
        self.wait_for_note()
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertNotIn('class="note"', body)
        self.assertNotIn(REFRESH, body)

    def test_watch_session_end_screen(self):
        self.outcomes["rabbit"] = "gliding"
        self.finish("6", "0")
        body = self.get("/summary")[2]
        self.assertIn("Watch: 1 of 2 words to keep an eye on for age 6 yr 0 mo (rabbit).", body)
        self.assertIn("no, keep an eye on it", body)
        self.assertIn("Flagged: none<", body)
        self.assertNotIn("Refer", body)
        self.assertNotIn('class="verdict bubble refer"', body)

    def test_summary_shows_model_note(self):
        self.outcomes["rabbit"] = "gliding"
        fake = NoteModel(TRUE_NOTE)
        self.server.generate = fake
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertIn(f'<p class="note"><b>Note by Qwen, a small language model running on the board:</b> {TRUE_NOTE}</p>', body)
        self.assertNotIn(REFRESH, body)
        self.get("/summary")
        self.assertEqual(len(fake.prompts), 3)  # the SLP note, then the family note in English and in Spanish
        self.assertIn("Number of words tried: 2", fake.prompts[0])

    def test_model_failure_shows_tally_only(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(raise_=LlmError("llama-completion exited with 1"))
        err = self.quiet_stderr()
        self.finish()
        self.wait_for_note()
        status, _, body = self.get("/summary")
        self.assertEqual(status, 200)
        self.assertIn("Refer: 1 of 2 words flagged", body)
        self.assertNotIn('class="note"', body)
        self.assertNotIn(REFRESH, body)
        self.assertIn("summary note skipped: llama-completion exited with 1", err.getvalue())

    def test_wrong_model_claim_shows_tally_only(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(
            "The child tried 2 words with the r sound. Carrot had gliding, which is flagged for age.")
        err = self.quiet_stderr()
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertNotIn('class="note"', body)
        self.assertNotIn(REFRESH, body)
        self.assertIn("summary note skipped: ", err.getvalue())

    def test_new_session_clears_note(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(TRUE_NOTE)
        self.finish()
        self.wait_for_note()
        self.server.generate = None
        self.finish()
        self.assertNotIn('class="note"', self.get("/summary")[2])

    def test_failed_save_keeps_note(self):
        self.outcomes["rabbit"] = "gliding"
        fake, gate = self.gated(TRUE_NOTE)
        self.server.generate = fake
        self.disk_fails = True
        self.start()
        for _ in range(2):
            self.post("/record")
            status, _, body = self.post("/next")
        self.assertEqual(status, 500)
        self.assertIn("Not saved: No space left on device.", body)
        self.assertIn(PENDING, body)
        self.assertIn(REFRESH, body)
        gate.set()
        self.wait_for_note()
        status, _, body = self.get("/summary")
        self.assertEqual(status, 500)
        self.assertIn("Not saved: No space left on device.", body)
        self.assertIn(TRUE_NOTE, body)


    # The family note (#39).

    def test_no_model_shows_the_fixed_family_note(self):
        self.outcomes["rabbit"] = "gliding"
        self.finish()
        body = self.get("/summary")[2]
        self.assertIn(f'<p lang="en"><b>English, fixed note filled in by code</b><br>{FIXED_EN}</p>', body)
        self.assertIn(f'<p lang="es"><b>Español, fixed note filled in by code</b><br>{FIXED_ES}</p>', body)
        self.assertNotIn(CHECKED, body)
        self.assertNotIn(REFRESH, body)

    def test_qwen_notes_show_with_green_checks(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(by_prompt())
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertIn(f'{TRUE_NOTE}</p>\n  <p class="checked">{CHECKED}</p>', body)
        self.assertIn(f'<p lang="en"><b>English, by Qwen</b> {CHECKED}<br>{FAMILY_EN}</p>', body)
        self.assertIn(f'<p lang="es"><b>Español, by Qwen</b> {CHECKED}<br>{FAMILY_ES}</p>', body)
        self.assertNotIn("fixed note", body)
        self.assertNotIn(REFRESH, body)

    def test_failed_family_check_shows_the_fixed_note_and_logs_why(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(by_prompt(es=FAMILY_ES.replace("2 palabras", "3 palabras")))
        err = self.quiet_stderr()
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertIn(f'<p lang="en"><b>English, by Qwen</b> {CHECKED}<br>{FAMILY_EN}</p>', body)
        self.assertIn(f'<p lang="es"><b>Español, fixed note filled in by code</b><br>{FIXED_ES}</p>', body)
        self.assertIn("family note (es) fixed: has a number not in the facts: 3", err.getvalue())

    def test_failed_slp_check_shows_no_check_mark(self):
        self.outcomes["rabbit"] = "gliding"
        self.server.generate = NoteModel(by_prompt(slp=TRUE_NOTE.replace("2 words", "two words")))
        err = self.quiet_stderr()
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertNotIn('class="note"', body)
        self.assertNotIn('class="checked"', body)
        self.assertIn("summary note skipped: has a number written as a word: two", err.getvalue())
        self.assertIn(FAMILY_EN, body)

    def test_qwen_off_after_an_llm_error_uses_fixed_family_notes(self):
        self.outcomes["rabbit"] = "gliding"
        fake = NoteModel(raise_=LlmError("llama.cpp took longer than 240 s"))
        self.server.generate = fake
        err = self.quiet_stderr()
        self.finish()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertEqual(len(fake.prompts), 1)
        self.assertIn(FIXED_EN, body)
        self.assertIn(FIXED_ES, body)
        self.assertIn("family note (en) fixed: Qwen is off", err.getvalue())

    def test_tally_first_then_each_note_as_it_arrives(self):
        self.outcomes["rabbit"] = "gliding"
        fake, gate = self.gated(by_prompt())
        self.server.generate = fake
        self.finish()
        body = self.get("/summary")[2]
        self.assertIn("Refer: 1 of 2 words flagged", body)
        self.assertIn(PENDING, body)
        self.assertIn('<p lang="en"><b>English</b><br>Qwen writes it after the note.</p>', body)
        self.assertIn(REFRESH, body)
        gate.set()
        self.wait_for_note()
        body = self.get("/summary")[2]
        self.assertIn(FAMILY_EN, body)
        self.assertIn(FAMILY_ES, body)
        self.assertNotIn(REFRESH, body)

    def test_listen_words_show_on_the_end_screen_and_in_the_facts(self):
        self.outcomes["rabbit"] = "gliding"
        fake = NoteModel(by_prompt())
        self.server.generate = fake
        with mock.patch("speakup.summary.listen_words", lambda attempts: ["carrot"]):
            self.finish()
            self.wait_for_note()
            body = self.get("/summary")[2]
        self.assertIn('<p class="listen">SLP please listen: carrot</p>', body)
        self.assertIn("SLP please listen: carrot", fake.prompts[0])
        self.assertNotIn("SLP please listen", fake.prompts[1])

    # Practice (#21): the fallback bank covers rabbit and carrot.

    def start_practice(self, years="8", months="0"):
        return self.post("/start", {"student_id": "S-014", "birth_date": birth_date_for(int(years), int(months)),
                                    "mode": "practice"})

    def practice_try(self):
        self.post("/practice/record")
        return self.post("/practice/next")

    def test_start_page_has_practice_button(self):
        body = self.get("/")[2]
        self.assertIn('<button class="secondary" name="mode" value="practice">Practice</button>', body)
        self.assertLess(body.index(">Start screening</button>"), body.index(">Practice</button>"))

    def test_start_practice_shows_first_word(self):
        self.assertRedirect(self.start_practice(), "/practice")
        status, _, body = self.get("/practice")
        self.assertEqual(status, 200)
        self.assertIn('<div class="tline">rabbit</div>', body)
        self.assertIn("Practice, Word level, try 1", body)
        self.assertIn("Screening aid, not a diagnosis", body)
        self.assertRedirect(self.get("/word"), "/")

    def test_practice_start_rejects_bad_input(self):
        status, _, body = self.post("/start", {"child_id": "Emma Smith", "age_years": "7", "mode": "practice"})
        self.assertEqual(status, 400)
        self.assertRedirect(self.get("/practice"), "/")

    def test_practice_steps_up_on_right(self):
        self.start_practice()
        self.assertRedirect(self.practice_try(), "/practice")
        body = self.get("/practice")[2]
        self.assertIn('<div class="tline">a long carrot</div>', body)
        self.assertIn("Phrase level, try 2", body)

    def test_practice_steps_down_on_miss(self):
        self.start_practice()
        self.practice_try()
        self.outcomes["carrot"] = "gliding"
        self.post("/practice/record")
        body = self.get("/practice")[2]
        self.assertIn("Heard: w (gliding)", body)
        self.assertIn("Flagged for age 8 yr 0 mo", body)
        self.post("/practice/next")
        body = self.get("/practice")[2]
        self.assertIn("Word level, try 3", body)
        self.assertIn('<div class="tline">rabbit</div>', body)

    def test_practice_end_saves_tries_with_levels(self):
        self.start_practice()
        self.practice_try()
        self.outcomes["carrot"] = "gliding"
        self.post("/practice/record")
        self.assertRedirect(self.post("/practice/end"), "/practice/summary")
        [saved] = load_sessions(self.db)
        self.assertEqual([r.word for r in saved.results], ["rabbit", "carrot"])
        with sqlite3.connect(self.db) as conn:
            rows = conn.execute("SELECT level, line FROM results ORDER BY position").fetchall()
        self.assertEqual(rows, [("word", "rabbit"), ("phrase", "a long carrot")])
        status, _, body = self.get("/practice/summary")
        self.assertEqual(status, 200)
        self.assertIn("Refer: 1 of 2 words flagged for age 8 yr 0 mo (carrot).", body)
        self.assertIn("Flagged: gliding 1<", body)
        self.assertIn("<th>Try</th><th>Level</th><th>Line</th><th>Heard</th><th>Flagged</th>", body)
        self.assertIn("<td>Phrase</td><td>a long carrot</td>", body)
        self.assertIn("Screening aid, not a diagnosis", body)
        self.assertNotIn("Note by Qwen", body)

        # An ended practice takes no more tries and saves once.
        self.assertRedirect(self.get("/practice"), "/practice/summary")
        self.assertRedirect(self.post("/practice/record"), "/practice/summary")
        self.assertRedirect(self.post("/practice/end"), "/practice/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)

    def test_end_practice_with_no_try_goes_home(self):
        self.start_practice()
        with mock.patch("speakup.server.save_session") as save:
            self.assertRedirect(self.post("/practice/end"), "/")
        save.assert_not_called()
        self.assertRedirect(self.get("/practice"), "/")
        self.assertRedirect(self.get("/practice/summary"), "/")

    def test_practice_failed_save_shows_save_again(self):
        self.disk_fails = True
        self.start_practice()
        self.practice_try()
        status, _, body = self.post("/practice/end")
        self.assertEqual(status, 500)
        self.assertIn("Not saved: No space left on device.", body)
        self.assertIn('<form method="post" action="/practice/save"><button class="primary">Save again</button></form>',
                      body)
        self.assertEqual(self.get("/practice/summary")[0], 500)
        self.assertEqual(load_sessions(self.db), [])

        self.disk_fails = False
        self.assertRedirect(self.post("/practice/save"), "/practice/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)
        status, _, body = self.get("/practice/summary")
        self.assertEqual(status, 200)
        self.assertNotIn("Not saved", body)
        self.assertRedirect(self.post("/practice/save"), "/practice/summary")
        self.assertEqual(len(load_sessions(self.db)), 1)

    def test_screen_unchanged_by_practice(self):
        self.start_practice()
        self.practice_try()
        self.post("/practice/record")
        self.post("/practice/end")
        self.assertRedirect(self.start(), "/word")
        self.assertIn("Word 1 of 2", self.get("/word")[2])
        self.post("/record")
        self.post("/next")
        self.post("/record")
        self.assertRedirect(self.post("/next"), "/summary")
        body = self.get("/summary")[2]
        self.assertIn("Pass: 0 of 2 words flagged for age 8 yr 0 mo.", body)
        self.assertIn("<th>Word</th><th>Arti</th><th>SLP</th><th>Flagged</th>", body)
        self.assertEqual(len(load_sessions(self.db)), 2)

    def test_practice_pages_load_nothing_from_elsewhere(self):
        self.start_practice()
        bodies = [self.get("/practice")[2]]
        self.post("/practice/record")
        bodies.append(self.get("/practice")[2])
        self.post("/practice/end")
        bodies.append(self.get("/practice/summary")[2])
        for body in bodies:
            self.assertNotIn("://", body)
            self.assertNotIn("<script src", body)  # inline, same-page scripts only (Nov 4: Record, Stop, the box)
            self.assertNotIn("\u00b7", body)

    def test_server_swaps_bank(self):
        self.start_practice()
        self.practice_try()
        self.server.bank = Bank({("rabbit", "sentence"): "the cat sees a new rabbit.",
                                 ("carrot", "phrase"): "a new carrot"})
        self.assertIn("a long carrot", self.get("/practice")[2])
        self.practice_try()
        self.assertIn('<div class="tline">the cat sees a new rabbit.</div>', self.get("/practice")[2])

    def test_only_qwens_own_line_says_qwen(self):
        self.start_practice()
        self.practice_try()
        self.server.bank = Bank({("rabbit", "sentence"): "the cat sees a new rabbit.", ("carrot", "phrase"): "a new carrot"},
                                qwen=frozenset({("rabbit", "sentence"), ("carrot", "phrase")}))
        body = self.get("/practice")[2]
        self.assertIn('<div class="tline">a long carrot</div>', body)  # the fixed line, taken before the swap
        self.assertNotIn("Line written by Qwen", body)
        self.practice_try()
        body = self.get("/practice")[2]
        self.assertIn('<div class="tline">the cat sees a new rabbit.</div>', body)
        self.assertIn("Line written by Qwen on the board.", body)

    def test_missing_practice_lines_turn_practice_off_not_the_screen(self):
        # A words.csv word with no line in practice_lines.csv: the screen still starts, practice is off.
        err = self.quiet_stderr()
        server = make_server("127.0.0.1", 0, words=[Word("cherry", "middle")], listen=self.listen, recorder=self,
                             recordings_dir=self.recordings, db_path=self.db)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]
        self.assertIn("practice off:", err.getvalue())
        self.assertIn("cherry", err.getvalue())
        self.assertNotIn('value="practice"', self.get("/")[2])
        self.assertRedirect(self.start_practice(), "/")
        self.assertRedirect(self.get("/practice"), "/")
        self.assertRedirect(self.start(), "/word")
        self.post("/record")
        self.assertRedirect(self.post("/next"), "/summary")
        self.assertIn("Pass: 0 of 1 words flagged", self.get("/summary")[2])

    # The lab UI on top of the practice coach: select-then-Next, go back, the adult-voice adjustment.

    def test_correct_wrong_only_selects_and_next_moves_on(self):
        self.start()
        self.post("/record")
        self.assertRedirect(self.post("/verify", {"verdict": "wrong"}), "/word")
        body = self.get("/word")[2]
        self.assertIn("Word 1 of 2", body)
        self.assertIn('class="half disagree on"', body)  # Arti said right, the SLP said wrong
        self.assertRedirect(self.post("/next"), "/word")
        self.assertIn("Word 2 of 2", self.get("/word")[2])

    def test_go_back_to_a_word(self):
        self.start()
        self.post("/record")
        self.post("/next")
        self.assertRedirect(self.post("/go", {"i": "0"}), "/word")
        self.assertIn("Word 1 of 2", self.get("/word")[2])
        self.assertEqual(self.post("/go", {"i": "9"})[0], 400)

    def test_finish_early_saves_what_was_recorded(self):
        self.start()
        self.post("/record")
        self.assertRedirect(self.post("/finish"), "/summary")
        body = self.get("/summary")[2]
        self.assertIn("1 word(s) not recorded", body)

    def test_practice_verify_overrides_artis_answer_for_the_level(self):
        self.start_practice()
        self.outcomes["rabbit"] = "gliding"
        self.post("/practice/record")
        self.assertRedirect(self.post("/practice/verify", {"verdict": "correct"}), "/practice")
        self.post("/practice/next")
        self.assertIn("Phrase level, try 2", self.get("/practice")[2])

    def test_child_screen_follows_practice_line(self):
        self.start_practice()
        state = json.loads(self.get("/api/state")[2])
        self.assertEqual((state["line"], state["picture"]), ("rabbit", "/pics/rabbit.svg"))
        self.practice_try()
        state = json.loads(self.get("/api/state")[2])
        self.assertEqual(state["line"], "a long carrot")
        self.assertNotIn("error_type", json.dumps(state))

    def test_adult_voice_uses_the_stretch_from_pitch(self):
        calls = []

        def stretched(word, path, alpha):
            from speakup.voice import Reading
            calls.append(alpha)
            raw = self.listen(word, path)
            raw["model"] = f"stub+adult{alpha:.2f}"
            return raw, Reading(alpha, 0.1, ((alpha - 0.05, 0.2), (alpha + 0.05, 0.6)), 0.3)

        listen = self.listen

        def wrapped(word, path):
            return listen(word, path)
        wrapped.stretched = stretched
        self.server.listen = wrapped
        self.clip_voice = synth(110, [(450, 80), (1200, 100), (2400, 120)])
        self.assertIn("An adult (demo)", self.get("/")[2])
        self.post("/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0), "voice": "adult"})
        self.post("/record")
        self.assertEqual(calls, [1.3])  # 110 Hz: (250 / 110) ** 0.3 = 1.28, on the grid 1.3
        body = self.get("/word")[2]
        self.assertIn("Adult voice adjustment", body)
        self.assertIn("raised ×1.30", body)
        self.assertIn("decide by ear", body)  # 1.35 flips the answer
        self.assertIn("Arti is unsure", body)
        self.assertIn("stub+adult1.30", body)

    def test_child_mode_warns_on_a_low_voice(self):
        self.clip_voice = synth(110, [(450, 80), (1200, 100), (2400, 120)])
        self.start()
        self.post("/record")
        body = self.get("/word")[2]
        self.assertIn("adult man's range", body)


if __name__ == "__main__":
    unittest.main()
