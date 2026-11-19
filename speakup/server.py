"""The session's web app (#5): plain HTML forms, each POST redirecting (303) to the next page.
Requests run on threads so the child view's poll answers during a recording. The note thread (#29)
also writes the session's note, so note_lock guards the session and its note where they meet."""

import json
import math
import re
import sqlite3
import sys
import threading
from concurrent.futures import BrokenExecutor, Future, ProcessPoolExecutor
from dataclasses import replace
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from speakup import book, compare, pages, proof, synthview
from speakup.bank import Bank, load_fallback
from speakup.clipcheck import check_clip
from speakup.llm import LlmError
from speakup.practice import Practice
from speakup.recorder import RecorderError
from speakup.result import check
from speakup.session import Session, parse_birth_date, parse_child_id
from speakup.store import last_correct_clip, last_result, load_sessions, save_session, saved_clip

try:  # the sound analysis, the voice check and the word pick need numpy; the app still runs without them
    from speakup import acoustics, segment, voice
except ImportError:  # pragma: no cover
    acoustics = segment = voice = None
from speakup import family, summary
from speakup.summary import Generate, note
from speakup.words import Word

Listen = Callable[[str, Path], dict]


STATIC = Path(__file__).with_name("static")
_PIC = re.compile(r"/pics/([a-z]+)\.svg")
# The child screen's felt look: pre-rendered WebP layers, their layout and the page's own script and style.
_FELT = re.compile(r"/felt/([a-z0-9-]+\.(webp|json|js|css))")
_FELT_KIND = {"webp": "image/webp", "json": "application/json", "js": "text/javascript", "css": "text/css"}


def felt_looks() -> dict[str, list[str]]:
    """The worlds and buddies scripts/felt/build.py baked, in its order: what /look offers."""
    felt = json.loads((STATIC / "felt" / "felt.json").read_text(encoding="utf-8"))
    return {"world": list(felt["worlds"]), "buddy": list(felt["buddies"])}
# A try is keyed s3 (screen, word 4) or p5 (practice, try 6): its clip, its analysis, its voice reading.
# /audio/s3.wav is the selected word (what Arti scored and the analysis shows), /audio/s3-full.wav the recording.
_SAVED = re.compile(r"/saved/([0-9]+)/([0-9]+)\.wav")
_AUDIO = re.compile(r"/audio/([sp][0-9]+)(-full)?\.wav")
_ANALYSIS = re.compile(r"/analysis/([sp][0-9]+)(?:\?embed=1)?")
_WINDOW = re.compile(r"/analysis/([sp][0-9]+)/window")
_BOOK_FIG = re.compile(r"/book/figures/([^/?#]+)")
_BOOK_SYNTH = re.compile(r"/book/synth/([^/?#]+)")
_COMPARE_CURVES = re.compile(r"/compare/curves/([a-z0-9-]+)\.json")


class SpeakUpServer(ThreadingHTTPServer):
    # Threads, so the child screen's status poll answers while a clip records.
    daemon_threads = True
    # The Look page asks for eight thumbnails at once while the child screen polls; the default backlog of 5 refused some.
    request_queue_size = 32
    # On Windows, address reuse lets a second server bind the same port while the first keeps answering.
    allow_reuse_address = sys.platform != "win32"

    def __init__(self, address, *, words: list[Word], listen: Listen, recorder, recordings_dir: Path, db_path: Path,
                 generate: Generate | None = None, bank: Bank | None = None, workers: int = 0):
        super().__init__(address, Handler)
        # Worker processes for the numpy work after a recording, so it uses the board's other cores. None: run inline.
        self.workers = workers
        self.pool = ProcessPoolExecutor(workers) if workers else None
        for _ in range(workers):
            self.pool.submit(_warm)  # each worker imports numpy and the analysis now, not on the first recording
        self.words = words
        self.listen = listen
        self.recorder = recorder
        self.recordings_dir = recordings_dir
        self.db_path = db_path
        self.session: Session | None = None
        self.save_error: str | None = None
        self.generate = generate
        self.note: str | None = None
        self.note_lock = threading.Lock()
        self.note_pending = False
        self.note_thread: threading.Thread | None = None
        self.family: dict[str, tuple[str, bool]] = {}  # language -> (family note, written by Qwen); missing: pending
        self.phase = "idle"  # idle, listening, thinking: what the child screen shows
        self.tries = 0  # counts finished tries, so the child screen knows when to cheer
        self.active = "screen"  # which of the two the child screen follows: "screen" or "practice"
        self.voice_mode = "child"  # "adult" turns on the stretch (speakup/voice.py) for this session
        self.look = {"world": "meadow", "buddy": "patch"}  # the child screen's world and buddy, picked on /look
        self.pitches: list[float] = []  # median pitch of each clip this session, for the stretch
        self.info: dict[str, pages.TryInfo] = {}  # try key -> clip, recording check, pitch, voice reading
        self.analyses: dict = {}  # (clip path, r position) -> acoustics.Analysis, computed once per clip
        # The practice (#21) runs beside the screen's session; __main__ swaps in Qwen's bank when it is done.
        # No bank means practice is off: a words.csv edit without its practice lines must not stop the screen.
        if bank is None:
            try:
                bank = load_fallback(words)
            except ValueError as e:
                print(f"practice off: {e}", file=sys.stderr, flush=True)
        self.bank: Bank | None = bank
        self.practice: Practice | None = None
        self.practice_ended = False
        self.practice_save_error: str | None = None
        # The recording running in the background (Nov 4), so the page can show Stop and poll.
        # state: idle, listening, thinking, done, error; go: the page to show when it is done.
        self.rec_lock = threading.Lock()
        self.rec: dict = {"state": "idle", "error": None, "go": "/"}
        self.select_gen = 0  # counts box moves, so only the newest one's score is kept

    @property
    def recording(self) -> bool:
        return self.rec["state"] in ("listening", "thinking")

    def reset_try_state(self, active: str, voice_mode: str) -> None:
        self.active = active
        self.voice_mode = voice_mode
        self.pitches = []
        # The other owner's session stays open, so its clips stay on its word page (#54).
        prefix = "p" if active == "practice" else "s"  # try_key's s<word index> and p<practice turn>
        # list() copies in one step: a window or /select request in another thread may add a key meanwhile.
        self.info = {k: v for k, v in list(self.info.items()) if not k.startswith(prefix)}
        self.rec = {"state": "idle", "error": None, "go": "/"}
        proof.LIVE.new_session()
        rewind = getattr(self.recorder, "rewind", None)  # --replay: each session plays its clips from the first
        if rewind is not None:
            rewind()

    def reset_demo(self) -> None:
        """Demo only: drop the open screening and practice (unsaved ones are discarded) and blank the child screen.
        Saved sessions stay in the database."""
        with self.note_lock:
            self.session = None
            self.save_error = None
            self.note = None
            self.note_pending = False
        self.practice = None
        self.practice_ended = False
        self.practice_save_error = None
        self.phase = "idle"
        self.tries = 0
        self.analyses = {}
        self.reset_try_state("screen", "child")

    def later(self, fn: Callable, *args) -> Future:
        """fn(*args) on a worker process, or here and now without a pool."""
        pool = self.pool
        if pool is not None:
            try:
                return pool.submit(fn, *args)
            except BrokenExecutor as e:
                # One dead worker (the OOM killer) breaks the pool for good; a new pool lets the screening go on.
                print(f"worker pool broken, starting a new one: {e}", file=sys.stderr, flush=True)
                pool.shutdown(wait=False)
                self.pool = pool = ProcessPoolExecutor(self.workers)
                try:
                    return pool.submit(fn, *args)
                except BrokenExecutor as e:
                    print(f"new worker pool broken too, running here: {e}", file=sys.stderr, flush=True)
        job: Future = Future()
        try:
            job.set_result(fn(*args))
        except Exception as e:
            job.set_exception(e)
        return job

    def start_note(self, session: Session) -> None:
        if self.generate is None:
            with self.note_lock:
                results = [a.result for a in session.attempts]
                self.family = {lang: (family.fixed_note(results, session.age_months, lang), False)
                               for lang in family.LANGS}
            return
        with self.note_lock:
            self.note = None
            self.note_pending = True
            self.family = {}
        self.note_thread = threading.Thread(target=self.write_note, args=(session,), daemon=True)
        self.note_thread.start()

    def write_note(self, session: Session) -> None:
        """The SLP note, then the family note in each language, each shown as it arrives. After an LlmError
        (llama.cpp failed or timed out) Qwen is not asked again: the family gets the fixed note at once."""
        results, age = [a.result for a in session.attempts], session.age_months
        text = None
        qwen_off = False
        try:
            try:
                text = note(results, age, self.generate, summary.listen_words(session.attempts))
            except (LlmError, ValueError) as e:
                print(f"summary note skipped: {e}", file=sys.stderr, flush=True)
                qwen_off = isinstance(e, LlmError)
            finally:
                with self.note_lock:
                    if self.session is session:
                        self.note = text
                        self.note_pending = False
            for lang in family.LANGS:
                if self.session is not session:
                    return
                if qwen_off:
                    made = self.fixed_family(session, lang, "Qwen is off")
                else:
                    try:
                        made = family.qwen_note(results, age, lang, self.generate), True
                    except (LlmError, ValueError) as e:
                        qwen_off = isinstance(e, LlmError)
                        made = self.fixed_family(session, lang, str(e))
                with self.note_lock:
                    if self.session is session:
                        self.family[lang] = made
        finally:
            with self.note_lock:
                if self.session is session:
                    for lang in family.LANGS:
                        if lang not in self.family:
                            self.family[lang] = self.fixed_family(session, lang, "the note thread stopped")

    @staticmethod
    def fixed_family(session: Session, lang: str, why: str) -> tuple[str, bool]:
        print(f"family note ({lang}) fixed: {why}", file=sys.stderr, flush=True)
        return family.fixed_note([a.result for a in session.attempts], session.age_months, lang), False

    def note_state(self) -> tuple[str | None, bool]:
        with self.note_lock:
            return self.note, self.note_pending

    def family_state(self) -> dict[str, tuple[str, bool]]:
        with self.note_lock:
            return dict(self.family)


class Handler(BaseHTTPRequestHandler):
    server: SpeakUpServer

    def log_message(self, format, *args):
        pass

    def send_page(self, status: int, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, data: dict) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path | None, kind: str) -> None:
        if path is None or not path.is_file():
            self.send_page(404, pages.not_found_page())
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def state(self) -> dict:
        """What the child screen may know: the line to say, its picture and the phase. Never a result or a flag."""
        live = getattr(self.server.recorder, "live", None)
        base = {"phase": self.server.phase, "tries": self.server.tries, "look": self.server.look,
                "speaking": bool(live is not None and live.heard)}  # the child has started (never a result)
        practice = self.server.practice
        if self.server.active == "practice" and practice is not None:
            if self.server.practice_ended:
                return {**base, "session": True, "done": True, "total": 5, "index": 5}
            word = practice.current_word
            return {
                **base, "session": True, "done": False,
                # Five stars that refill: practice has no fixed length.
                "total": 5, "index": practice.turn % 5,
                "word": word.word, "line": practice.line, "picture": self.picture(word.word),
                "tried": practice.current_attempt is not None,
                # The coach panel: level, where the r is, and a tip (the miss tip after a miss, else the word's).
                "practice": {"level": practice.level, "position": word.position,
                             "tip": practice.tip or self.server.bank.tips[word.position]},
            }
        session = self.server.session
        if session is None:
            return {**base, "session": False}
        word = session.current_word
        return {
            **base, "session": True,
            "done": session.done,
            "index": len(session.attempts) - (1 if session.current_attempt else 0),
            "total": len(session.words),
            "word": word.word if word else None,
            "line": word.word if word else None,
            "picture": self.picture(word.word) if word else None,
            "tried": session.current_attempt is not None,
        }

    def picture(self, word: str) -> str | None:
        return f"/pics/{word}.svg" if (STATIC / "pics" / f"{word}.svg").is_file() else None

    def analysis_of(self, clip: Path | None, position: str):
        """The sound analysis of a clip, cached; None without a clip, without numpy, or if it fails."""
        if clip is None or acoustics is None or not Path(clip).is_file():
            return None
        key = (str(clip), position)
        if key not in self.server.analyses:
            self.start_analysis(Path(clip), position)
        a = self.server.analyses.get(key)
        if isinstance(a, Future):
            try:
                try:
                    a = a.result()
                except BrokenExecutor as e:  # its worker died; the analysis is not lost with it
                    print(f"sound analysis failed on a worker, running here: {e}", file=sys.stderr, flush=True)
                    a = acoustics.analyse(Path(clip), position)
            except (OSError, ValueError) as e:
                print(f"sound analysis failed for {clip}: {e}", file=sys.stderr, flush=True)
                a = None
            self.server.analyses[key] = a
        return a

    def start_analysis(self, clip: Path, position: str) -> None:
        """Start the clip's analysis on a worker; analysis_of waits for it."""
        if acoustics is None:
            return
        self.server.analyses[(str(clip), position)] = self.server.later(acoustics.analyse, clip, position)
        if len(self.server.analyses) > 64:  # a session is 10 words; keep the cache small on the board
            self.server.analyses.pop(next(iter(self.server.analyses)))

    def analysis_for(self, info) -> object:
        """The analysis the SLP sees for a try: its word clip's, with the target window the SLP set, if any."""
        a = self.analysis_of(info.word_clip or info.clip, info.word.position) if info else None
        if a is not None and info.target_window is not None:
            a = acoustics.with_window(a, info.target_window)
        return a

    def try_key(self) -> str | None:
        """The key of the try on the SLP's screen now: s<word index> or p<practice turn>."""
        if self.server.active == "practice" and self.server.practice is not None:
            return f"p{self.server.practice.turn}"
        session = self.server.session
        if session is None or session.done:
            return None
        return f"s{session.index}"

    def stretch_available(self) -> bool:
        return getattr(self.server.listen, "stretched", None) is not None

    def analysis_page(self, key: str) -> None:
        owner = self.server.practice if key.startswith("p") else self.server.session
        info = self.server.info.get(key)
        if owner is None or info is None:
            self.redirect("/")
            return
        word = info.word
        try:
            ref = last_correct_clip(self.server.db_path, owner.child_id, word.word)
        except (OSError, sqlite3.Error) as e:
            print(f"reference lookup failed: {e}", file=sys.stderr, flush=True)
            ref = None
        if ref:  # compare word with word: the earlier try's selected word when it is still on this machine
            ref_word = word_clip_path(ref[1])
            ref = (ref[0], ref_word if ref_word.is_file() else ref[1])
        reference = (ref[0], self.analysis_of(ref[1], word.position)) if ref else None
        back = "/practice" if key.startswith("p") else "/word"
        embed = self.path.endswith("?embed=1")
        self.send_page(200, pages.analysis_page(owner, word, self.analysis_for(info),
                                                reference, acoustics is not None, back, info,
                                                f"/audio/{key}.wav" if info.clip else None, key=key, embed=embed,
                                                mode=self.recorder_mode()))

    def target_window(self, key: str, fields: dict[str, str]) -> None:
        """The SLP dragged the target-sound window on the viewer (start, end in s from the word start), or asked
        for the automatic one again (reset=1). Kept with the try; the measures that depend on it come back."""
        info = self.server.info.get(key)
        a = self.analysis_of(info.word_clip or info.clip, info.word.position) if info else None
        if a is None:
            self.send_json({"ok": False, "error": "No analysis for this try."})
            return
        if fields.get("reset"):
            window = None
        else:
            try:
                window = (float(fields.get("start", "")), float(fields.get("end", "")))
            except ValueError:
                self.send_json({"ok": False, "error": "The window needs a start and an end in seconds."})
                return
            if not all(math.isfinite(v) for v in window):
                self.send_json({"ok": False, "error": "The window needs a start and an end in seconds."})
                return
        b = acoustics.with_window(a, window)
        manual = window is not None
        self.server.info[key] = replace(info, target_window=b.window if manual else None)
        self.send_json({
            "ok": True, "window": list(b.window) if b.window else None,
            "auto_window": list(b.auto_window) if b.auto_window else None, "manual": manual,
            "gap": None if b.gap_time is None else {"t": b.gap_time, "v": b.gap_min, "f": list(b.at_gap or ())},
            "measures_html": pages.measures_html(b, info), "gap_text": pages.gap_text(b), "notes": b.notes,
        })

    def word_view(self, owner) -> pages.WordView:
        key = self.try_key()
        info = self.server.info.get(key) if key else None
        word = owner.current_word
        try:
            last = last_result(self.server.db_path, owner.child_id, word.word)
        except (OSError, sqlite3.Error) as e:
            print(f"last result lookup failed: {e}", file=sys.stderr, flush=True)
            last = None
        clip = (info.word_clip or info.clip) if info else None
        wave = None
        if info is not None and info.clip is not None and info.selection and segment is not None:
            try:
                wave = segment.peaks(info.clip)
            except (OSError, ValueError) as e:
                print(f"waveform failed for {info.clip}: {e}", file=sys.stderr, flush=True)
        return pages.WordView(
            key=key, info=info, last=last, picture=self.picture(word.word),
            analysis=self.analysis_for(info) if info else self.analysis_of(clip, word.position),
            voice_mode=self.server.voice_mode,
            stretch_available=self.stretch_available(),
            wave=wave,
            quiet_s=float(getattr(self.server.recorder, "gate", {}).get("trailing", 2.0)),
            qwen_line=isinstance(owner, Practice) and self.server.bank.by_qwen(word, owner.level, owner.line),
            mode=self.recorder_mode(),
        )

    def recorder_mode(self) -> str | None:
        """--replay: says the clips are saved ones, not the mic."""
        return getattr(self.server.recorder, "mode", None)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def form(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        fields = parse_qs(self.rfile.read(length).decode("utf-8"), keep_blank_values=True)
        return {name: values[0] for name, values in fields.items()}

    def do_GET(self):
        session = self.server.session
        practice = self.server.practice
        if self.path == "/":
            self.send_page(200, pages.start_page(practice=self.server.bank is not None,
                                                 stretch=self.stretch_available()))
        elif self.path == "/kid":
            self.send_page(200, pages.kid_page())
        elif self.path == "/look":
            self.send_page(200, pages.look_page(felt_looks(), self.server.look))
        elif self.path == "/api/state":
            self.send_json(self.state())
        elif self.path == "/api/record":
            self.send_json(self.server.rec)
        elif self.path == "/js/signalsmith-stretch.js":  # the Scrub tool's time-stretcher (MIT, vendored, offline)
            self.send_file(STATIC / "js" / "signalsmith-stretch.js", "text/javascript")
        elif _PIC.fullmatch(self.path):
            self.send_file(STATIC / "pics" / f"{_PIC.fullmatch(self.path).group(1)}.svg", "image/svg+xml")
        elif _FELT.fullmatch(self.path):
            m = _FELT.fullmatch(self.path)
            self.send_file(STATIC / "felt" / m.group(1), _FELT_KIND[m.group(2)])
        elif _AUDIO.fullmatch(self.path):
            m = _AUDIO.fullmatch(self.path)
            info = self.server.info.get(m.group(1))
            clip = None
            if info and info.clip:
                clip = info.clip if m.group(2) or info.word_clip is None else info.word_clip
            self.send_file(Path(clip) if clip else None, "audio/wav")
        elif _ANALYSIS.fullmatch(self.path):
            self.analysis_page(_ANALYSIS.fullmatch(self.path).group(1))
        elif self.path == "/sessions":
            self.send_page(200, pages.sessions_page(load_sessions(self.server.db_path)))
        elif _SAVED.fullmatch(self.path):
            m = _SAVED.fullmatch(self.path)
            self.send_file(saved_clip(self.server.db_path, int(m.group(1)), int(m.group(2))), "audio/wav")
        elif self.path.startswith("/child/"):
            self.child(self.path.removeprefix("/child/"))
        elif self.path in ("/word", "/summary") and session is None:
            self.redirect("/")
        elif self.path == "/word":
            if session.done:
                self.redirect("/summary")
            else:
                self.server.active = "screen"
                self.send_page(200, pages.word_page(session, None, self.word_view(session)))
        elif self.path == "/summary":
            if session.done:
                error = self.server.save_error
                note, pending = self.server.note_state()
                self.send_page(500 if error else 200, pages.summary_page(session, error, note, pending,
                                                                         self.server.family_state(),
                                                                         self.recorder_mode(),
                                                                         self.server.bank is not None))
            else:
                self.redirect("/word")
        elif self.path in ("/practice", "/practice/summary") and practice is None:
            self.redirect("/")
        elif self.path == "/practice":
            if self.server.practice_ended:
                self.redirect("/practice/summary")
            else:
                self.server.active = "practice"
                self.send_page(200, pages.practice_page(practice, None, self.word_view(practice)))
        elif self.path == "/practice/summary":
            if self.server.practice_ended:
                error = self.server.practice_save_error
                self.send_page(500 if error else 200, pages.practice_summary_page(practice, error,
                                                                                  self.recorder_mode()))
            else:
                self.redirect("/practice")
        elif urlsplit(self.path).path in ("/book", "/guide"):
            self.book_page()
        elif self.path == "/book/print":
            self.book_print()
        elif _BOOK_FIG.fullmatch(self.path):
            self.send_file(book.figure_path(_BOOK_FIG.fullmatch(self.path).group(1)), "image/png")
        elif _BOOK_SYNTH.fullmatch(self.path):
            self.book_synth(_BOOK_SYNTH.fullmatch(self.path).group(1))
        elif urlsplit(self.path).path == "/compare/data":
            self.compare_data()
        elif _COMPARE_CURVES.fullmatch(self.path):
            self.compare_curves(_COMPARE_CURVES.fullmatch(self.path).group(1))
        else:
            self.send_page(404, pages.not_found_page())

    def do_POST(self):
        fields = self.form()
        session = self.server.session
        practice = self.server.practice
        if self.path == "/stop":
            # The SLP's Stop: the recorder ends at its next 20 ms frame and keeps what it has.
            stop = getattr(self.server.recorder, "request_stop", None)
            if stop is not None and self.server.recording:
                stop()
            self.send_json({"ok": True})
        elif self.path == "/look":
            # The SLP picks the world or the buddy; the child screen sees it in the state and reloads.
            looks = felt_looks()
            pick = {k: v for k, v in fields.items() if k in looks}
            if not pick or any(v not in looks[k] for k, v in pick.items()):
                self.send_page(400, pages.look_page(looks, self.server.look, "Pick a world or a buddy from the list."))
            else:
                self.server.look = {**self.server.look, **pick}
                self.redirect("/look")
        elif _WINDOW.fullmatch(self.path):
            # Pure arithmetic on the cached analysis: safe even while the mic is on.
            self.target_window(_WINDOW.fullmatch(self.path).group(1), fields)
        elif self.server.recording:
            # One thing at a time: nothing moves the session while the mic is on or Arti is scoring.
            if self.headers.get("X-Record") or self.headers.get("X-Select"):
                self.send_json({"ok": False, "error": "A recording is still running. Press Stop first."})
            else:
                self.redirect(self.server.rec["go"])
        elif self.path == "/start":
            self.start(fields)
        elif self.path == "/practice-again":
            self.practice_again(session)
        elif self.path == "/resume" and session is not None and session.done:
            session.resume()
            with self.server.note_lock:
                self.server.note = None
                self.server.note_pending = False
            self.redirect("/word")
        elif self.path == "/reset" and self.server.recording:
            self.redirect(self.server.rec["go"])
        elif self.path == "/reset":
            self.server.reset_demo()
            self.redirect("/")
        elif self.path == "/select" and (session is None or session.done):
            self.redirect("/")
        elif self.path == "/select":
            self.select(session, fields, pages.word_page, "/word")
        elif self.path == "/practice/select" and (practice is None or self.server.practice_ended):
            self.redirect("/")
        elif self.path == "/practice/select":
            self.select(practice, fields, pages.practice_page, "/practice")
        elif self.path in ("/record", "/next", "/verify", "/go", "/finish", "/save") and session is None:
            self.redirect("/")
        elif self.path in ("/record", "/next", "/verify", "/go", "/finish") and session.done:
            self.redirect("/summary")
        elif self.path == "/record":
            self.server.active = "screen"
            self.record(session, pages.word_page, "/word")
        elif self.path == "/next":
            session.next()
            self.after_move(session)
        elif self.path == "/verify":
            # Correct / Wrong only records the SLP's call; Next moves on.
            try:
                session.verify(fields.get("verdict", ""), _try_index(fields, session.started_at))
            except ValueError as e:
                self.send_page(400, pages.word_page(session, str(e), self.word_view(session)))
                return
            self.redirect("/word")
        elif self.path == "/go":
            try:
                session.go(int(fields.get("i", "")))
            except ValueError as e:
                self.send_page(400, pages.word_page(session, str(e), self.word_view(session)))
                return
            self.redirect("/word")
        elif self.path == "/finish":
            if not session.attempts:
                self.redirect("/word")
                return
            session.finish()
            self.after_move(session)
        elif self.path == "/save" and self.server.save_error:
            self.save(session)
        elif self.path == "/save":
            self.redirect("/summary")
        elif self.path.startswith("/practice/") and practice is None:
            self.redirect("/")
        elif self.path.startswith("/practice/") and self.path != "/practice/save" and self.server.practice_ended:
            self.redirect("/practice/summary")
        elif self.path == "/practice/record":
            self.server.active = "practice"
            self.record(practice, pages.practice_page, "/practice")
        elif self.path == "/practice/verify":
            try:
                practice.verify(fields.get("verdict", ""), _try_index(fields, practice.started_at))
            except ValueError as e:
                self.send_page(400, pages.practice_page(practice, str(e), self.word_view(practice)))
                return
            self.redirect("/practice")
        elif self.path == "/practice/next":
            practice.next(self.server.bank)
            self.redirect("/practice")
        elif self.path == "/practice/end" and not practice.attempts:
            # Nothing to save, and pass_or_refer refuses "Pass: 0 of 0".
            self.server.practice = None
            self.server.active = "screen"
            self.redirect("/")
        elif self.path == "/practice/end":
            self.server.practice_ended = True
            self.save_practice(practice)
        elif self.path == "/practice/save" and self.server.practice_ended and self.server.practice_save_error:
            self.save_practice(practice)
        elif self.path == "/practice/save":
            self.redirect("/practice/summary")
        else:
            self.send_page(404, pages.not_found_page())

    def after_move(self, session: Session) -> None:
        if session.done:
            self.server.start_note(session)
            self.save(session)
        else:
            self.redirect("/word")

    def start(self, fields: dict[str, str]) -> None:
        student_id, birth_date = fields.get("student_id", ""), fields.get("birth_date", "")
        voice_mode = "adult" if fields.get("voice") == "adult" else "child"
        practice_on = self.server.bank is not None
        try:
            parsed_id, age_months = parse_child_id(student_id), parse_birth_date(birth_date)
        except ValueError as e:
            self.send_page(400, pages.start_page(str(e).replace("Child ID", "Student ID"), student_id, birth_date,
                                                 practice_on, self.stretch_available(), voice_mode))
            return
        if fields.get("mode") == "practice" and not practice_on:
            self.redirect("/")
            return
        if fields.get("mode") == "practice":
            self.begin_practice(parsed_id, age_months, voice_mode)
            return
        session = Session(parsed_id, age_months, self.server.words)
        with self.server.note_lock:
            self.server.session = session
            self.server.save_error = None
            self.server.note = None
            self.server.note_pending = False
            self.server.family = {}
        self.server.reset_try_state("screen", voice_mode)
        self.redirect("/word")

    def begin_practice(self, child_id: str, age_months: int, voice_mode: str) -> None:
        words = self.server.words
        has_clip = getattr(self.server.recorder, "has_clip", None)
        if has_clip is not None:  # --replay: practice can't skip a word, so it walks only the words with a clip
            words = [w for w in words if has_clip(w.word)]
        self.server.practice = Practice(child_id, age_months, words, self.server.bank)
        self.server.practice_ended = False
        self.server.practice_save_error = None
        self.server.reset_try_state("practice", voice_mode)
        self.redirect("/practice")

    def practice_again(self, session: Session | None) -> None:
        """Practice for the student just screened, from the summary: no re-entering the ID and birth date."""
        if session is None or self.server.bank is None:
            self.redirect("/")
            return
        self.begin_practice(session.child_id, session.age_months, self.server.voice_mode)

    def save(self, session: Session) -> None:
        try:
            session.saved_id = save_session(self.server.db_path, session)
        except (OSError, sqlite3.Error) as e:
            self.server.save_error = str(e)
            note, pending = self.server.note_state()
            self.send_page(500, pages.summary_page(session, self.server.save_error, note, pending,
                                                   self.server.family_state(), self.recorder_mode(),
                                                   self.server.bank is not None))
            return
        self.server.save_error = None
        self.redirect("/summary")

    def save_practice(self, practice: Practice) -> None:
        try:
            save_session(self.server.db_path, practice)
        except (OSError, sqlite3.Error) as e:
            self.server.practice_save_error = str(e)
            self.send_page(500, pages.practice_summary_page(practice, self.server.practice_save_error,
                                                            self.recorder_mode()))
            return
        self.server.practice_save_error = None
        self.redirect("/practice/summary")

    def child(self, raw_id: str) -> None:
        try:
            child_id = parse_child_id(raw_id)
        except ValueError:
            self.send_page(404, pages.not_found_page())
            return
        sessions = load_sessions(self.server.db_path, child_id)
        if not sessions:
            self.send_page(404, pages.not_found_page())
            return
        self.send_page(200, pages.child_page(child_id, sessions))

    def record(self, owner: Session | Practice, page: Callable[..., str], back: str) -> None:
        """Record the whole utterance, pick the target word in it and have Arti score that word.
        With the header X-Record: background (the page's script) it answers at once and records in a thread,
        so the page can show Stop and poll /api/record; a plain form post waits, as before."""
        key = self.try_key()
        word = owner.current_word
        line = getattr(owner, "line", None) or word.word
        path = self.server.recordings_dir / f"{owner.child_id}-{datetime.now():%Y%m%dT%H%M%S}-{word.word}.wav"
        if self.headers.get("X-Record") == "background":
            with self.server.rec_lock:
                if self.server.recording:
                    self.send_json({"ok": False, "error": "A recording is already running."})
                    return
                self.server.rec = {"state": "listening", "error": None, "go": back}
                self.server.phase = "listening"

            def job() -> None:
                try:
                    error = self.take(owner, key, word, line, path)
                except Exception as e:  # never leave the page polling a recording that died
                    print(f"recording failed: {e!r}", file=sys.stderr, flush=True)
                    error = f"Recording failed: {e}"
                    self.server.phase = "idle"
                self.server.rec = {"state": "error" if error else "done", "error": error, "go": back}

            threading.Thread(target=job, daemon=True).start()
            self.send_json({"ok": True})
            return
        error = self.take(owner, key, word, line, path)
        if error:
            self.send_page(500, page(owner, error, self.word_view(owner)))
            return
        self.redirect(back)

    def take(self, owner: Session | Practice, key: str, word: Word, line: str, path: Path) -> str | None:
        """One try: record, pick the word, score it, store it. Returns the error to show, or None."""
        have_clip, f0, reading, sel, word_clip = False, None, None, None, None
        try:
            self.server.phase = "listening"
            cue = getattr(self.server.recorder, "cue", None)  # --replay: the clip is chosen by the word on screen
            if cue is not None:
                cue(word.word)
            self.server.recorder.record(path)
            self.server.phase = "thinking"
            if self.server.rec["state"] == "listening":
                self.server.rec = {**self.server.rec, "state": "thinking"}
            have_clip = path.is_file()
            # Pitch, the recording check and the analysis run on the other cores while the word is scored.
            check_job = self.server.later(check_clip, path) if have_clip else None
            if have_clip:
                sel = self.pick(path, line, word.word)
            if sel is not None:
                word_clip = word_clip_path(path)
                segment.crop(path, word_clip, sel.start, sel.end)
                self.forget_analysis(word_clip)
            # The speaker's pitch from the word only (Nov 12): a cough or other talk in the clip read 205 Hz.
            f0_job = self.server.later(voice.pitch, word_clip or path) if have_clip and voice is not None else None
            if have_clip and self.server.pool is not None:  # without workers the page computes it when it needs it
                self.start_analysis(word_clip or path, word.position)
            f0 = self.pitch_of(f0_job)
            if f0:
                self.server.pitches.append(f0)
            raw, reading = self.score(word, word_clip or path, have_clip)
            # add_result raises ValueError too, when the record's sound and error type have no age norm.
            owner.add_result(check(raw), str(path) if have_clip else None,
                             (sel.start, sel.end, True) if sel else None)
        except RecorderError as e:
            print(f"recording failed: {e}", file=sys.stderr, flush=True)
            return f"Recording failed: {e}"
        except ValueError as e:
            return f"Model gave a bad result: {e}"
        finally:
            self.server.phase = "idle"
        self.server.info[key] = pages.TryInfo(
            word=word, clip=path if have_clip else None,
            check=self.check_of(check_job, path), f0=f0, reading=reading,
            word_clip=word_clip, selection=(sel.start, sel.end) if sel else None, auto_selected=True,
            method=sel.method if sel else None, line=line,
        )
        self.server.tries += 1
        return None

    def pick(self, path: Path, line: str, target: str):
        """The app's pick of the target word, or None (no numpy, or a clip it cannot read: Arti hears it all)."""
        if segment is None:
            return None
        try:
            sel = segment.pick_file(path, line, target)
        except (OSError, ValueError) as e:
            print(f"word pick failed for {path}: {e}", file=sys.stderr, flush=True)
            return None
        # Nothing stands above the room: no box to offer, Arti hears it all and the recording check says why.
        return None if sel.method == "whole" else sel

    def score(self, word: Word, path: Path, have_clip: bool) -> tuple[dict, object]:
        """Arti's raw answer on `path`, through the adult-voice stretch when that is on."""
        stretched = getattr(self.server.listen, "stretched", None)
        if self.server.voice_mode == "adult" and stretched is not None and have_clip:
            # The stretch comes from the speaker's pitch over the session so far, never from Arti's answer.
            pitches = sorted(self.server.pitches)
            alpha = voice.alpha_for(pitches[len(pitches) // 2] if pitches else None)
            return stretched(word.word, path, alpha)
        return self.server.listen(word.word, path), None

    def forget_analysis(self, clip: Path) -> None:
        for k in [k for k in self.server.analyses if k[0] == str(clip)]:
            del self.server.analyses[k]

    def select(self, owner: Session | Practice, fields: dict[str, str], page: Callable[..., str], back: str) -> None:
        """The SLP moved the box (start and end in s) or asked for the automatic pick again (reset=1):
        crop that part, have Arti score it again, keep the SLP's call. JSON for the page's script
        (X-Select header), a redirect for a plain form."""
        as_json = bool(self.headers.get("X-Select"))
        key = self.try_key()
        info = self.server.info.get(key) if key else None

        def refuse(status: int, message: str) -> None:
            if as_json:
                self.send_json({"ok": False, "error": message})
            else:
                self.send_page(status, page(owner, message, self.word_view(owner)))

        if info is None or info.clip is None or owner.current_attempt is None or segment is None:
            refuse(400, "Record first: there is no recording to choose from.")
            return
        try:
            duration = segment.duration_of(info.clip)
            if fields.get("reset"):
                sel = segment.pick_file(info.clip, info.line or info.word.word, info.word.word)
                start, end, auto, method = sel.start, sel.end, True, sel.method
            else:
                start, end = segment.clamp(float(fields.get("start", "")), float(fields.get("end", "")), duration)
                auto, method = False, "slp"
        except (OSError, ValueError):
            refuse(400, "The selection needs a start and an end in seconds.")
            return
        word_clip = word_clip_path(info.clip)
        self.server.select_gen += 1
        gen = self.server.select_gen
        try:
            segment.crop(info.clip, word_clip, start, end)
            self.forget_analysis(word_clip)
            raw, reading = self.score(info.word, word_clip, True)
            if gen != self.server.select_gen:  # the SLP moved the box again meanwhile
                refuse(409, "Replaced by a newer move.")
                return
            owner.rescore(check(raw), (start, end, auto))
        except (OSError, ValueError) as e:
            refuse(500, f"Model gave a bad result: {e}")
            return
        self.server.info[key] = replace(info, word_clip=word_clip, selection=(start, end), auto_selected=auto,
                                        target_window=None,
                                        method=method, reading=reading if reading is not None else info.reading)
        if as_json:
            self.send_json({"ok": True, "start": start, "end": end, "auto": auto})
        else:
            self.redirect(back)

    def check_of(self, job: Future | None, path: Path):
        """The recording check from its job; if its worker died, the check runs here, as it is light."""
        if job is None:
            return None
        try:
            return job.result()
        except BrokenExecutor as e:
            print(f"recording check failed on a worker, running here: {e}", file=sys.stderr, flush=True)
            return check_clip(path)

    def pitch_of(self, job: Future | None) -> float | None:
        if job is None:
            return None
        try:
            return job.result()
        except (OSError, ValueError, BrokenExecutor) as e:
            print(f"pitch failed: {e}", file=sys.stderr, flush=True)
            return None

    def book_page(self) -> None:
        """The sound book; ?word= (and &line=) opens it for that word, with its sounds listed and highlighted; &back= is
        the app page to return to (its "Back to where you were" button)."""
        query = parse_qs(urlsplit(self.path).query)
        try:
            html = book.book_page(word=query.get("word", [""])[0], line=query.get("line", [""])[0],
                                  age=query.get("age", [""])[0], sex=query.get("sex", [""])[0],
                                  back=query.get("back", [""])[0])
        except book.BookError as e:
            self.send_page(500, book.problem_page(str(e)))
            return
        self.send_page(200, html)

    def compare_data(self) -> None:
        """The Compare pop-up's defaults and sound list, for ?target=&age_months=&sex=&context=&word=."""
        q = {k: v[0] for k, v in parse_qs(urlsplit(self.path).query).items()}
        age = q.get("age_months", "")
        self.send_json(compare.data(q.get("target") or None, int(age) if age.isdecimal() else None, q.get("sex") or None,
                                    q.get("context") or None, q.get("word") or None))

    def compare_curves(self, name: str) -> None:
        """One reference's F1, F2 and F3 curves for the viewer's Compare tool, as JSON (speakup.compare.curves)."""
        if acoustics is None:
            self.send_error_json(503, "The reference curves need numpy, which this machine does not have.")
            return
        try:
            data = compare.curves(name)
        except (OSError, ValueError) as e:
            print(f"reference curves failed for {name}: {e}", file=sys.stderr, flush=True)
            self.send_error_json(500, f"The reference curves could not be made: {e}")
            return
        if data is None:
            self.send_error_json(404, "No reference by that name.")
            return
        self.send_json(data)

    def send_error_json(self, status: int, message: str) -> None:
        body = json.dumps({"error": message}).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def book_synth(self, name: str) -> None:
        """A computer-made picture (PNG on disk) for the book's viewer. Its sound is no longer offered (too rough)."""
        self.send_file(synthview.png_path(name), "image/png")

    def book_print(self) -> None:
        try:
            html = book.print_page()
        except book.BookError as e:
            self.send_page(500, book.problem_page(str(e)))
            return
        self.send_page(200, html)


def _try_index(fields: dict[str, str], started_at: str) -> int | None:
    """The try a question card posts its call for (#78). A card from another session, or a value that is not a
    number, becomes -1, which no try has."""
    i = fields.get("i")
    if i is None:
        return None
    if fields.get("started") != started_at:
        return -1
    try:
        return int(i)
    except ValueError:
        return -1


def word_clip_path(clip: Path) -> Path:
    """Where the selected word of a recording is kept: <clip stem>-word.wav beside it."""
    clip = Path(clip)
    return clip.with_name(f"{clip.stem}-word.wav")


def _warm() -> None:
    """A worker's first task: unpickling it imports this module, numpy and the analysis."""


def make_server(
    host: str, port: int, *, words: list[Word], listen: Listen, recorder, recordings_dir: Path, db_path: Path,
    generate: Generate | None = None, bank: Bank | None = None, workers: int = 0,
) -> SpeakUpServer:
    return SpeakUpServer(
        (host, port), words=words, listen=listen, recorder=recorder, recordings_dir=recordings_dir, db_path=db_path,
        generate=generate, bank=bank, workers=workers,
    )
