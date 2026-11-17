import http.client
import re
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import urlencode

from speakup import book, pages
from speakup.server import make_server
from speakup.words import Word
from tests.test_server import birth_date_for


class BookServerTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch("speakup.server.save_session", lambda *a: None)
        patcher.start()
        self.addCleanup(patcher.stop)
        server = make_server("127.0.0.1", 0, words=[Word("rabbit", "start"), Word("carrot", "middle")],
                             listen=lambda word, path: {}, recorder=self, recordings_dir=Path(tmp.name) / "rec",
                             db_path=Path(tmp.name) / "speakup.db")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.port = server.server_address[1]

    def record(self, path):  # the stand-in mic; these tests never record
        pass

    def request(self, method, path, fields=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(fields) if fields is not None else None
        headers = {"Content-Type": "application/x-www-form-urlencoded"} if fields is not None else {}
        conn.request(method, path, body=body, headers=headers)
        r = conn.getresponse()
        out = r.status, dict(r.getheaders()), r.read()
        conn.close()
        return out

    def test_book_opens_with_index_search_and_every_section(self):
        status, headers, body = self.request("GET", "/book")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn('<input id="q" type="search"', html)
        self.assertIn('<nav class="index"', html)
        self.assertEqual(html.count("<section id="), len(book.load()["sections"]))
        self.assertNotIn('id="for-this-word"', html)

    def test_guide_is_the_same_page(self):
        self.assertEqual(self.request("GET", "/guide?word=rabbit")[2], self.request("GET", "/book?word=rabbit")[2])

    def test_book_for_rabbit_lists_and_highlights_its_sounds(self):
        status, _, body = self.request("GET", "/book?word=rabbit")
        html = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("For this word: rabbit", html)
        for p, sid in (("ɹ", "snd-r"), ("æ", "snd-ae"), ("b", "snd-b"), ("ɪ", "snd-ih"), ("t", "snd-t")):
            self.assertRegex(html, rf'<a class="chip[^"]*" href="#{sid}"><b>/{p}/</b>')
            self.assertRegex(html, rf'<section id="{sid}" class="[^"]*ctx-home')

    def test_practice_line_adds_its_sounds(self):
        html = self.request("GET", "/book?" + urlencode({"word": "rabbit", "line": "a soft rabbit"}))[2].decode()
        self.assertIn("Line: a soft rabbit", html)
        self.assertRegex(html, r'<section id="snd-s" class="[^"]*ctx-home')

    def test_print_page_and_figures(self):
        status, _, body = self.request("GET", "/book/print")
        self.assertEqual(status, 200)
        self.assertIn("Contents", body.decode("utf-8"))
        status, headers, png = self.request("GET", "/book/figures/fig-classes.png")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertEqual(self.request("GET", "/book/figures/..%2Fbook.json")[0], 404)
        self.assertEqual(self.request("GET", "/book/figures/none.png")[0], 404)

    def test_missing_book_says_so(self):
        with mock.patch.object(book, "load", side_effect=book.BookError("The sound book file is not on this machine.")):
            status, _, body = self.request("GET", "/book")
        self.assertEqual(status, 500)
        self.assertIn("not on this machine", body.decode("utf-8"))

    def test_word_page_banner_opens_the_book_for_the_current_word(self):
        self.request("POST", "/start", {"student_id": "S-014", "birth_date": birth_date_for(8, 0)})
        html = self.request("GET", "/word")[2].decode("utf-8")
        self.assertRegex(html, r'<a href="/book\?word=rabbit&amp;age=96" data-book>Sound book</a>')
        self.assertIn("window.BookLink", html)  # the same tab, with the spot to come back to

    def test_book_shows_back_to_where_you_were_for_an_app_page(self):
        back = "/word#back:y=420&fv=%2Fanalysis%2Fs0&fy=0"
        html = self.request("GET", "/book?" + urlencode({"word": "rabbit", "back": back}))[2].decode("utf-8")
        self.assertIn('id="book-back"', html)
        self.assertIn("Back to where you were", html)
        self.assertIn('href="/word#back:y=420&amp;fv=%2Fanalysis%2Fs0&amp;fy=0"', html)
        self.assertIn("history.back()", html)
        self.assertNotIn('target="_blank">Sound book', html)
        # the brand link keeps the way back
        self.assertIn('href="/book?word=rabbit&amp;back=%2Fword%23back', html)
        plain = self.request("GET", "/book?word=rabbit")[2].decode("utf-8")
        self.assertNotIn('id="book-back"', plain)

    def test_book_back_never_leaves_the_app(self):
        for bad in ("https://example.com/", "//example.com/x", "javascript:alert(1)", "/x\\y", "/a\"b", "word"):
            html = self.request("GET", "/book?" + urlencode({"back": bad}))[2].decode("utf-8")
            self.assertNotIn('id="book-back"', html, bad)


    def test_sound_sections_carry_the_picture_viewer(self):
        html = self.request("GET", "/book")[2].decode("utf-8")
        self.assertIn('<div class="sv" data-group="girl6">', html)
        self.assertIn('src="/book/synth/c-s-girl6.png"', html)
        self.assertIn("Computer-made from published averages (", html)
        self.assertNotIn(".wav", html)  # no Play for the computer-made sound: too rough to hear the differences
        self.assertNotIn("<audio", html)
        self.assertIn("window.SV_DATA = {", html)

    def test_book_for_rabbit_shows_pictures_at_the_child_age(self):
        html = self.request("GET", "/book?word=rabbit&age=130&sex=male")[2].decode("utf-8")
        panel = html[html.index('id="for-this-word"'):html.index("<section")]
        self.assertIn("Pictures of these sounds", panel)
        self.assertIn('src="/book/synth/w-rabbit-boy10.png"', panel)
        self.assertIn('src="/book/synth/v-ae-boy10.png"', panel)
        html = self.request("GET", "/book?word=rabbit&age=80")[2].decode("utf-8")
        self.assertIn("sex is not recorded", html)
        self.assertIn('src="/book/synth/w-rabbit-girl6.png"', html)

    def test_error_sections_compare_target_and_error(self):
        html = self.request("GET", "/book")[2].decode("utf-8")
        sec = html[html.index('<section id="err-gliding"'):]
        sec = sec[:sec.index("</section>")]
        self.assertIn("Target: ", sec)
        self.assertIn('src="/book/synth/e-wabbit-girl6.png"', sec)

    def test_picture_is_served_and_the_sound_is_not(self):
        status, headers, body = self.request("GET", "/book/synth/c-s-man.png")
        self.assertEqual((status, headers["Content-Type"]), (200, "image/png"))
        self.assertEqual(self.request("GET", "/book/synth/c-s-man.wav")[0], 404)
        self.assertEqual(self.request("GET", "/book/synth/index.json")[0], 404)

    def test_scrub_time_stretcher_is_served_locally(self):
        # The Scrub tool's stretcher is vendored (MIT): the board is offline, so it never comes from a CDN.
        status, headers, body = self.request("GET", "/js/signalsmith-stretch.js")
        self.assertEqual((status, headers["Content-Type"]), (200, "text/javascript"))
        self.assertIn(b"SignalsmithStretch", body)
        self.assertEqual(self.request("GET", "/js/other.js")[0], 404)


class BannerLinkTest(unittest.TestCase):
    def test_analysis_page_links_the_analysed_word(self):
        owner = SimpleNamespace(current_word=Word("carrot", "middle"), line=None)
        self.assertEqual(pages._book_link(owner, "Sound analysis: rabbit", None), "/book?word=rabbit")

    def test_practice_line_goes_along(self):
        owner = SimpleNamespace(current_word=Word("rabbit", "start"), line="a soft rabbit")
        self.assertEqual(pages._book_link(owner, "Practice", None), "/book?word=rabbit&line=a+soft+rabbit")
        owner.line = "rabbit"
        self.assertEqual(pages._book_link(owner, "Practice", None), "/book?word=rabbit")

    def test_done_session_opens_the_plain_book(self):
        owner = SimpleNamespace(current_word=None)
        self.assertEqual(pages._book_link(owner, "Screening done", None), "/book")
        html = pages._banner(SimpleNamespace(current_word=None, child_id="S-1", age_months=96), "Screening done")
        self.assertTrue(re.search(r'<a href="/book" data-book>Sound book</a>', html))


if __name__ == "__main__":
    unittest.main()
