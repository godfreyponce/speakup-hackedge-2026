import sqlite3
import unittest
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from speakup import store
from speakup.bank import load_fallback
from speakup.practice import Practice
from speakup.result import Result
from speakup.session import Session
from speakup.store import SavedSession, last_correct_clip, last_result, load_sessions, save_session
from speakup.words import Word

WORDS = [Word("rabbit", "start"), Word("carrot", "middle")]
HEARD = {None: "ɹ", "gliding": "w", "distortion": None}


def result(word, error_type):
    return Result(
        word=word,
        target_sound="r",
        expected_phone="ɹ",
        heard_phone=HEARD[error_type],
        error_type=error_type,
        confidence=None,
        model="test",
        recorded_at="2026-11-05T10:15:00-06:00",
    )


def finished(child_id, age_months, outcomes):
    session = Session(child_id, age_months, WORDS)
    for word, error_type in zip(WORDS, outcomes):
        session.add_result(result(word.word, error_type))
        session.next()
    return session


class StoreTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "data" / "speakup.db"

    def columns(self, query):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute(query).fetchall()

    def test_practice_saves_level_and_line(self):
        bank = load_fallback(WORDS)
        practice = Practice("S-014", 90, WORDS, bank)
        practice.add_result(result("rabbit", None))
        practice.next(bank)
        practice.add_result(result("carrot", "gliding"))
        save_session(self.db, practice)
        self.assertEqual(self.columns("SELECT level, line FROM results ORDER BY position"),
                         [("word", "rabbit"), ("phrase", "a long carrot")])
        [saved] = load_sessions(self.db)
        self.assertEqual([saved.is_flagged(r) for r in saved.results], [False, True])

    def test_screen_rows_have_null_level(self):
        save_session(self.db, finished("S-014", 88, [None, "gliding"]))
        self.assertEqual(self.columns("SELECT level, line FROM results"), [(None, None), (None, None)])

    def test_old_database_gains_columns(self):
        self.db.parent.mkdir(parents=True)
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.executescript("""
CREATE TABLE sessions (id INTEGER PRIMARY KEY, child_id TEXT NOT NULL, age_months INTEGER NOT NULL,
  started_at TEXT NOT NULL);
CREATE TABLE results (session_id INTEGER NOT NULL REFERENCES sessions(id), position INTEGER NOT NULL,
  word TEXT NOT NULL, target_sound TEXT NOT NULL, expected_phone TEXT NOT NULL, heard_phone TEXT, error_type TEXT,
  confidence REAL, model TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (session_id, position));
INSERT INTO sessions VALUES (1, 'S-014', 88, '2026-11-01T10:00:00-06:00');
INSERT INTO results VALUES (1, 0, 'rabbit', 'r', 'ɹ', 'w', 'gliding', NULL, 'test', '2026-11-01T10:00:05-06:00');
""")
        [saved] = load_sessions(self.db)
        self.assertEqual([r.word for r in saved.results], ["rabbit"])
        names = [row[1] for row in self.columns("PRAGMA table_info(results)")]
        self.assertIn("level", names)
        self.assertIn("line", names)

    def test_save_and_read_back(self):
        session = Session("S-014", 88, WORDS)
        session.add_result(replace(result("rabbit", "gliding"), confidence=0.82))
        session.next()
        session.add_result(result("carrot", None))
        session.next()

        self.assertIsInstance(save_session(self.db, session), int)
        [saved] = load_sessions(self.db)
        self.assertIsInstance(saved, SavedSession)
        self.assertEqual(saved.child_id, "S-014")
        self.assertEqual(saved.age_months, 88)
        self.assertEqual(saved.started_at, session.started_at)
        self.assertEqual(saved.results, [a.result for a in session.attempts])

    def test_flag_count_uses_age_rule(self):
        save_session(self.db, finished("S-014", 84, ["gliding", None]))
        save_session(self.db, finished("S-014", 83, ["gliding", None]))
        at_84, at_83 = load_sessions(self.db)
        self.assertEqual(at_84.flag_count(), 1)
        self.assertEqual(at_83.flag_count(), 0)
        self.assertFalse(at_83.is_flagged(at_83.results[0]))

    def test_child_filter_and_order(self):
        save_session(self.db, finished("S-014", 84, [None, None]))
        save_session(self.db, finished("S-021", 90, [None, None]))
        save_session(self.db, finished("S-014", 85, [None, None]))
        self.assertEqual([s.age_months for s in load_sessions(self.db, "S-014")], [84, 85])
        self.assertEqual([s.child_id for s in load_sessions(self.db)], ["S-014", "S-021", "S-014"])
        self.assertEqual(load_sessions(self.db, "S-999"), [])

    def test_empty_store_and_folder_created(self):
        self.assertFalse(self.db.parent.exists())
        self.assertEqual(load_sessions(self.db), [])
        self.assertTrue(self.db.exists())


if __name__ == "__main__":
    unittest.main()


class LastResultTest(unittest.TestCase):
    def test_latest_result_for_the_word_or_none(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "speakup.db"
            self.assertIsNone(last_result(db, "S-1", "rabbit"))
            save_session(db, finished("S-1", 96, [None, None]))
            save_session(db, finished("S-1", 97, ["gliding", None]))
            save_session(db, finished("S-2", 97, [None, None]))
            last = last_result(db, "S-1", "rabbit")
            self.assertEqual(last.result.error_type, "gliding")
            self.assertFalse(last.slp_checked)
            self.assertIsNone(last_result(db, "S-1", "giraffe"))

    def test_slp_checked_result_is_marked(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "speakup.db"
            s = Session("S-1", 96, WORDS)
            s.add_result(result("rabbit", "gliding"))
            s.verify("correct")
            s.next()
            save_session(db, s)
            self.assertTrue(last_result(db, "S-1", "rabbit").slp_checked)


class SlpCallStoreTest(unittest.TestCase):
    """#37: Arti's call and the SLP's call are separate columns; the model name is left alone."""

    def calls(self, db):
        with closing(sqlite3.connect(db)) as conn:
            return conn.execute("SELECT word, model, error_type, arti_call, slp_call FROM results ORDER BY position").fetchall()

    def test_both_calls_saved_apart(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "speakup.db"
            s = Session("S-1", 96, WORDS)
            s.add_result(result("rabbit", "gliding"))
            s.verify("correct")
            s.next()
            s.add_result(result("carrot", None))  # not checked
            s.next()
            save_session(db, s)
            self.assertEqual(self.calls(db), [("rabbit", "test", None, "wrong", "correct"),
                                              ("carrot", "test", None, "correct", None)])
            self.assertTrue(last_result(db, "S-1", "rabbit").slp_checked)
            self.assertFalse(last_result(db, "S-1", "carrot").slp_checked)

    def test_old_database_gains_the_call_columns_and_its_slp_rows_count_as_checked(self):
        with TemporaryDirectory() as tmp:
            db, clip = Path(tmp) / "speakup.db", Path(tmp) / "rabbit.wav"
            clip.write_bytes(b"RIFF")
            conn = sqlite3.connect(db)
            conn.executescript(f"""
                CREATE TABLE sessions (id INTEGER PRIMARY KEY, child_id TEXT NOT NULL, age_months INTEGER NOT NULL,
                                       started_at TEXT NOT NULL);
                CREATE TABLE results (session_id INTEGER NOT NULL, position INTEGER NOT NULL, word TEXT NOT NULL,
                  target_sound TEXT NOT NULL, expected_phone TEXT NOT NULL, heard_phone TEXT, error_type TEXT,
                  confidence REAL, model TEXT NOT NULL, recorded_at TEXT NOT NULL, clip TEXT,
                  PRIMARY KEY (session_id, position));
                INSERT INTO sessions VALUES (1, 'S-1', 96, '2026-11-01T10:00:00-06:00');
                INSERT INTO results VALUES (1, 0, 'rabbit', 'r', 'ɹ', 'ɹ', NULL, 0.9, 'arti-v0+slp', '2026-11-01T10:00:05-06:00', '{clip}');
                INSERT INTO results VALUES (1, 1, 'carrot', 'r', 'ɹ', NULL, 'off', 0.8, 'arti-v0', '2026-11-01T10:00:09-06:00', NULL);
            """)
            conn.commit()
            conn.close()
            self.assertEqual(len(load_sessions(db, "S-1")[0].results), 2)
            # Arti's own call on an old checked row was never kept, so it stays unknown.
            self.assertEqual(self.calls(db), [("rabbit", "arti-v0+slp", None, None, "correct"),
                                              ("carrot", "arti-v0", "off", "wrong", None)])
            self.assertTrue(last_result(db, "S-1", "rabbit").slp_checked)
            self.assertFalse(last_result(db, "S-1", "carrot").slp_checked)
            self.assertEqual(last_correct_clip(db, "S-1", "rabbit")[1], clip)


    def test_a_call_column_left_by_a_broken_upgrade_is_not_added_twice(self):
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "speakup.db"
            with closing(sqlite3.connect(db)) as conn:
                conn.executescript("""
                    CREATE TABLE results (session_id INTEGER NOT NULL, position INTEGER NOT NULL, word TEXT NOT NULL,
                      target_sound TEXT NOT NULL, expected_phone TEXT NOT NULL, heard_phone TEXT, error_type TEXT,
                      confidence REAL, model TEXT NOT NULL, recorded_at TEXT NOT NULL, arti_call TEXT,
                      PRIMARY KEY (session_id, position));
                """)
            self.assertEqual(load_sessions(db, "S-1"), [])
            with closing(sqlite3.connect(db)) as conn:
                names = [row[1] for row in conn.execute("PRAGMA table_info(results)")]
            self.assertEqual((names.count("arti_call"), names.count("slp_call")), (1, 1))


class ClipTest(unittest.TestCase):
    def test_old_database_gains_the_clip_column_and_keeps_its_rows(self):
        import sqlite3
        with TemporaryDirectory() as tmp:
            db = Path(tmp) / "speakup.db"
            conn = sqlite3.connect(db)
            conn.executescript("""
                CREATE TABLE sessions (id INTEGER PRIMARY KEY, child_id TEXT NOT NULL, age_months INTEGER NOT NULL,
                                       started_at TEXT NOT NULL);
                CREATE TABLE results (session_id INTEGER NOT NULL, position INTEGER NOT NULL, word TEXT NOT NULL,
                  target_sound TEXT NOT NULL, expected_phone TEXT NOT NULL, heard_phone TEXT, error_type TEXT,
                  confidence REAL, model TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (session_id, position));
                INSERT INTO sessions VALUES (1, 'S-1', 96, '2026-11-01T10:00:00-06:00');
                INSERT INTO results VALUES (1, 0, 'rabbit', 'r', 'ɹ', 'ɹ', NULL, 0.9, 'arti-v0', '2026-11-01T10:00:05-06:00');
            """)
            conn.commit()
            conn.close()
            self.assertEqual(len(load_sessions(db, "S-1")[0].results), 1)
            save_session(db, finished("S-1", 97, [None, None]))
            self.assertEqual(len(load_sessions(db, "S-1")), 2)

    def test_last_correct_clip_needs_an_slp_correct_and_a_file(self):
        with TemporaryDirectory() as tmp:
            db, clip = Path(tmp) / "speakup.db", Path(tmp) / "rabbit.wav"
            clip.write_bytes(b"RIFF")
            self.assertIsNone(last_correct_clip(db, "S-1", "rabbit"))
            s = Session("S-1", 96, WORDS)
            s.add_result(result("rabbit", None), str(clip))  # Arti said right, nobody checked: not a reference
            s.next()
            save_session(db, s)
            self.assertIsNone(last_correct_clip(db, "S-1", "rabbit"))
            s = Session("S-1", 96, WORDS)
            s.add_result(result("rabbit", "gliding"), str(clip))
            s.verify("correct")
            s.next()
            save_session(db, s)
            self.assertEqual(last_correct_clip(db, "S-1", "rabbit")[1], clip)
            clip.unlink()
            self.assertIsNone(last_correct_clip(db, "S-1", "rabbit"))


_OLDEST = """
CREATE TABLE sessions (id INTEGER PRIMARY KEY, child_id TEXT NOT NULL, age_months INTEGER NOT NULL,
                       started_at TEXT NOT NULL);
CREATE TABLE results (session_id INTEGER NOT NULL, position INTEGER NOT NULL, word TEXT NOT NULL,
  target_sound TEXT NOT NULL, expected_phone TEXT NOT NULL, heard_phone TEXT, error_type TEXT,
  confidence REAL, model TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY (session_id, position));
INSERT INTO sessions VALUES (1, 'S-1', 96, '2026-11-01T10:00:00-06:00');
INSERT INTO results VALUES (1, 0, 'rabbit', 'r', 'ɹ', 'ɹ', NULL, 0.9, 'arti-v0+slp', '2026-11-01T10:00:05-06:00');
INSERT INTO results VALUES (1, 1, 'carrot', 'r', 'ɹ', NULL, 'off', 0.8, 'arti-v0', '2026-11-01T10:00:09-06:00');
"""
# After the Nov 4 selection columns, before #37's call columns.
_BEFORE_CALLS = "\n".join([_OLDEST] + [f"ALTER TABLE results ADD COLUMN {name} {kind};" for name, kind in (
    ("clip", "TEXT"), ("level", "TEXT"), ("line", "TEXT"), ("sel_start", "REAL"), ("sel_end", "REAL"),
    ("sel_auto", "INTEGER"))])


class UpgradeRaceTest(unittest.TestCase):
    """#52: two connections open an old database at once. The second one runs its whole upgrade between the
    first one reading the columns and adding them."""

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / "speakup.db"

    def old_database(self, script):
        with closing(sqlite3.connect(self.db)) as conn:
            conn.executescript(script)

    def open_while_another_upgrades(self):
        db, raced = self.db, []

        class FirstOfTwo(sqlite3.Connection):
            def execute(self, sql, *args):
                rows = super().execute(sql, *args).fetchall()
                if sql.startswith("PRAGMA table_info") and not raced:
                    raced.append(True)
                    store._connect(db).close()
                return rows

        real_connect = sqlite3.connect
        with mock.patch.object(store.sqlite3, "connect", lambda path: real_connect(path, factory=FirstOfTwo)):
            store._connect(db).close()
        self.assertEqual(raced, [True])

    def columns(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return [row[1] for row in conn.execute("PRAGMA table_info(results)")]

    def calls(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute("SELECT word, arti_call, slp_call FROM results ORDER BY position").fetchall()

    def assert_upgraded_once(self):
        names = self.columns()
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({"clip", "level", "line", "sel_start", "sel_end", "sel_auto", "arti_call", "slp_call"}
                        <= set(names))
        self.assertEqual(self.calls(), [("rabbit", None, "correct"), ("carrot", "wrong", None)])

    def test_the_oldest_upgrade_survives_a_second_connection(self):
        self.old_database(_OLDEST)
        self.open_while_another_upgrades()
        self.assert_upgraded_once()

    def test_the_call_upgrade_survives_a_second_connection(self):
        self.old_database(_BEFORE_CALLS)
        self.open_while_another_upgrades()
        self.assert_upgraded_once()

    def test_an_upgraded_database_opens_as_before(self):
        self.old_database(_OLDEST)
        load_sessions(self.db)
        before = self.columns(), self.calls()
        self.assertEqual(len(load_sessions(self.db, "S-1")[0].results), 2)
        self.assertEqual((self.columns(), self.calls()), before)

    def test_a_fresh_database_gets_every_column_once(self):
        save_session(self.db, finished("S-1", 96, [None, "gliding"]))
        self.assertEqual(len(self.columns()), len(set(self.columns())))
        self.assertEqual(self.calls(), [("rabbit", "correct", None), ("carrot", "wrong", None)])
