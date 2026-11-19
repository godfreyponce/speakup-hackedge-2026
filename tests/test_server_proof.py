"""The proof bar on the SLP pages (#38)."""

import http.client
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import urlencode

from speakup import proof
from speakup.server import make_server
from speakup.words import Word
from tests.test_server import birth_date_for


class ProofServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        live = mock.patch.object(proof, "LIVE", proof.Proof(meminfo_path=Path(tmp.name) / "none",
                                                            route_path=Path(tmp.name) / "none"))
        self.live = live.start()
        self.addCleanup(live.stop)
        server = make_server("127.0.0.1", 0, words=[Word("rabbit", "start")], listen=self.listen, recorder=self,
                             recordings_dir=Path(tmp.name) / "recordings", db_path=Path(tmp.name) / "speakup.db")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def record(self, path):
        pass

    def listen(self, word, path):
        return {"word": word, "target_sound": "r", "expected_phone": "ɹ", "heard_phone": "ɹ", "error_type": None,
                "confidence": None, "model": "stub", "recorded_at": "2026-11-14T10:00:00-06:00"}

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(fields) if fields is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        conn.request(method, path, body=body, headers=headers)
        response = conn.getresponse()
        result = response.status, response.read().decode("utf-8")
        conn.close()
        return result

    def start(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0)})

    def test_word_page_shows_the_bar_with_nothing_measured(self):
        self.start()
        status, body = self.request("GET", "/word")
        self.assertEqual(status, 200)
        self.assertIn('<footer class="proof"', body)
        footer = body.split('<footer class="proof"')[1].split("</footer>")[0]
        self.assertNotRegex(footer, r'class="tile[ "]')  # nothing measured: one quiet line, no tiles
        self.assertIn('class="unmeasured"', footer)

    def test_start_page_has_no_bar(self):
        self.assertNotIn('<footer class="proof"', self.request("GET", "/")[1])

    def test_new_session_clears_arti_times(self):
        self.live.add_arti_ms(60.0)
        self.start()
        self.assertEqual(self.live.snapshot().arti_words, 0)


if __name__ == "__main__":
    unittest.main()
