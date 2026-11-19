"""The session log (#6): finished sessions and their per-word results, in SQLite on the board."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from speakup.age_norms import should_flag
from speakup.practice import Practice
from speakup.result import FIELDS, Result
from speakup.session import Session

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY,
  child_id TEXT NOT NULL,
  age_months INTEGER NOT NULL,
  started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  position INTEGER NOT NULL,
  word TEXT NOT NULL,
  target_sound TEXT NOT NULL,
  expected_phone TEXT NOT NULL,
  heard_phone TEXT,
  error_type TEXT,
  confidence REAL,
  model TEXT NOT NULL,
  recorded_at TEXT NOT NULL,
  PRIMARY KEY (session_id, position)
);
"""
_COLUMNS = ", ".join(FIELDS)
# Practice tries only (#21); screen rows leave them NULL. Added on open, so a database from before #21 gains them too.
_PRACTICE_COLUMNS = ("level", "line")
# The recording's path on this machine (the SLP's side-by-side), then the practice columns.
_EXTRA_COLUMNS = ("clip", *_PRACTICE_COLUMNS)
# Where the target word sits in the recording, in seconds, and 1 if the app picked it, 0 if the SLP moved it
# (Nov 4). Added on open like the columns above; older rows leave them NULL.
_SELECTION_COLUMNS = (("sel_start", "REAL"), ("sel_end", "REAL"), ("sel_auto", "INTEGER"))
# Arti's own call and the SLP's call, each "correct" or "wrong" (#37); slp_call is NULL until the SLP checks.
# The result columns hold the call that counts: the SLP's once made, else Arti's.
_CALL_COLUMNS = ("arti_call", "slp_call")
_ADDED_COLUMNS = (*((name, "TEXT") for name in _EXTRA_COLUMNS), *_SELECTION_COLUMNS,
                  *((name, "TEXT") for name in _CALL_COLUMNS))


@dataclass(frozen=True)
class SavedSession:
    id: int
    child_id: str
    age_months: int
    started_at: str
    results: list[Result]

    # Flags are worked out on read, so every session of a child is judged by today's rule.
    def is_flagged(self, r: Result) -> bool:
        return should_flag(r.error_type, r.target_sound, self.age_months)

    def flag_count(self) -> int:
        return sum(self.is_flagged(r) for r in self.results)


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    # clip, level and line came after the first logs were written: add them to an older database in place.
    if not {name for name, _ in _ADDED_COLUMNS} <= _columns(conn):
        _upgrade(conn)
    return conn


def _columns(conn: sqlite3.Connection) -> set[str]:
    return {row[1] for row in conn.execute("PRAGMA table_info(results)")}


def _upgrade(conn: sqlite3.Connection) -> None:
    """Two connections can open an old database at once (#52), so the columns are read again under the write
    lock: the second connection then finds them added. One transaction, so a failed upgrade leaves no call column
    without its filled-in calls."""
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        have = _columns(conn)
        for name, kind in _ADDED_COLUMNS:
            if name not in have:
                conn.execute(f"ALTER TABLE results ADD COLUMN {name} {kind}")
        if "slp_call" not in have:
            _fill_in_calls(conn)


def _fill_in_calls(conn: sqlite3.Connection) -> None:
    """Before #37 a checked row was marked only by "+slp" on its model, and Arti's own call on it was not kept."""
    call = "CASE WHEN error_type IS NULL THEN 'correct' ELSE 'wrong' END"
    conn.execute(f"UPDATE results SET slp_call = {call} WHERE model LIKE '%+slp'")
    conn.execute(f"UPDATE results SET arti_call = {call} WHERE model NOT LIKE '%+slp'")


def save_session(db_path: Path, session: Session | Practice) -> int:
    with closing(_connect(db_path)) as conn, conn:
        old = getattr(session, "saved_id", None)
        if old is not None:
            conn.execute("DELETE FROM results WHERE session_id = ?", (old,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (old,))
        session_id = conn.execute(
            "INSERT INTO sessions (child_id, age_months, started_at) VALUES (?, ?, ?)",
            (session.child_id, session.age_months, session.started_at),
        ).lastrowid
        extra = (*_EXTRA_COLUMNS, *(name for name, _ in _SELECTION_COLUMNS), *_CALL_COLUMNS)
        conn.executemany(
            f"INSERT INTO results (session_id, position, {_COLUMNS}, {', '.join(extra)}) "
            f"VALUES ({', '.join('?' * (len(FIELDS) + 2 + len(extra)))})",
            [
                (session_id, position, *(getattr(a.result, f) for f in FIELDS), a.clip, a.level, a.line,
                 a.sel_start, a.sel_end, None if a.sel_start is None else int(a.sel_auto), a.arti_call, a.slp)
                for position, a in enumerate(session.attempts)
            ],
        )
    return session_id


def load_sessions(db_path: Path, child_id: str | None = None) -> list[SavedSession]:
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT id, child_id, age_months, started_at FROM sessions"
            + (" WHERE child_id = ?" if child_id is not None else "")
            + " ORDER BY id",
            () if child_id is None else (child_id,),
        ).fetchall()
        return [
            SavedSession(
                id=id_,
                child_id=cid,
                age_months=age,
                started_at=started,
                results=[
                    Result(**dict(zip(FIELDS, r)))
                    for r in conn.execute(
                        f"SELECT {_COLUMNS} FROM results WHERE session_id = ? ORDER BY position", (id_,)
                    )
                ],
            )
            for id_, cid, age, started in rows
        ]


@dataclass(frozen=True)
class LastTime:
    started_at: str
    result: Result
    slp_call: str | None = None

    @property
    def slp_checked(self) -> bool:
        return self.slp_call is not None


def last_result(db_path: Path, child_id: str, word: str) -> LastTime | None:
    """The most recent saved result for this child on this word, for the SLP to compare against."""
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            f"SELECT s.started_at, r.slp_call, {', '.join('r.' + f for f in FIELDS)} "
            "FROM results r JOIN sessions s ON s.id = r.session_id "
            "WHERE s.child_id = ? AND r.word = ? ORDER BY s.id DESC, r.position DESC LIMIT 1",
            (child_id, word),
        ).fetchone()
    if row is None:
        return None
    started_at, slp_call, *values = row
    return LastTime(started_at, Result(**dict(zip(FIELDS, values))), slp_call)


def saved_clip(db_path: Path, session_id: int, position: int) -> Path | None:
    """The recording of one saved word, if it is still on the board."""
    with closing(_connect(db_path)) as conn:
        row = conn.execute("SELECT clip FROM results WHERE session_id = ? AND position = ?",
                           (session_id, position)).fetchone()
    return Path(row[0]) if row and row[0] else None


def last_correct_clip(db_path: Path, child_id: str, word: str) -> tuple[str, Path] | None:
    """This child's most recent recording of the word that the SLP checked and called correct, if its
    file is still on this machine: (started_at, path). Only an SLP-confirmed production is a fair reference."""
    with closing(_connect(db_path)) as conn:
        rows = conn.execute(
            "SELECT s.started_at, r.clip FROM results r JOIN sessions s ON s.id = r.session_id "
            "WHERE s.child_id = ? AND r.word = ? AND r.slp_call = 'correct' "
            "AND r.clip IS NOT NULL ORDER BY s.id DESC, r.position DESC",
            (child_id, word),
        ).fetchall()
    for started_at, clip in rows:
        if Path(clip).is_file():
            return started_at, Path(clip)
    return None
