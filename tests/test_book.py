import json
import re
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from speakup import book, lexicon


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.hrefs, self.srcs = set(), [], []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag)
        a = dict(attrs)
        if "href" in a:
            self.hrefs.append(a["href"])
        if "src" in a:
            self.srcs.append(a["src"])


ENGLISH = ("p b t d k ɡ m n ŋ f v θ ð s z ʃ ʒ h tʃ dʒ w j l ɹ "
           "i ɪ eɪ ɛ æ ɑ ɔ oʊ ʊ u ʌ ə ɝ ɚ aɪ aʊ ɔɪ").split()


class ContentTest(unittest.TestCase):
    """The shipped sound_book.json keeps the plan's contract (3b)."""

    @classmethod
    def setUpClass(cls):
        cls.book = book.load()
        cls.ids = [s["id"] for s in cls.book["sections"]]

    def test_ids_are_unique_ascii_and_parents_exist(self):
        self.assertEqual(len(self.ids), len(set(self.ids)))
        for s in self.book["sections"]:
            self.assertRegex(s["id"], r"^[a-z0-9-]+$")
            self.assertTrue(s["parent"] is None or s["parent"] in self.ids, s["id"])

    def test_every_section_is_in_the_reading_order_once(self):
        self.assertEqual(sorted(s["id"] for s, _ in book.ordered(self.book)), sorted(self.ids))

    def test_links_and_confusions_point_to_real_sections(self):
        for s in self.book["sections"]:
            for c in s["confused_with"]:
                self.assertIn(c, self.ids, s["id"])
            for href in re.findall(r'href="([^"]*)"', s["body_html"]):
                self.assertTrue(href.startswith("#") and href[1:] in self.ids, f'{s["id"]}: {href}')

    def test_every_section_has_references_that_exist(self):
        for s in self.book["sections"]:
            self.assertTrue(s["refs"], s["id"])
            for r in s["refs"]:
                self.assertIn(r, self.book["references"], s["id"])

    def test_bodies_use_only_allowed_tags_and_local_figures(self):
        for s in self.book["sections"]:
            t = Tags()
            t.feed(s["body_html"])
            self.assertLessEqual(t.tags, book.ALLOWED_TAGS, s["id"])
            for src in t.srcs:
                self.assertRegex(src, r"^figures/[a-z0-9-]+\.png$")
                self.assertTrue((book.FIGURES / src.removeprefix("figures/")).is_file(), src)

    def test_every_english_sound_and_every_lexicon_sound_has_an_entry(self):
        lex = {p for w in json.loads(lexicon.LEXICON_PATH.read_text(encoding="utf-8"))["words"].values()
               for p in w["ipa"]}
        for p in set(ENGLISH) | lex:
            home = book.home_section(self.book, p)
            self.assertIsNotNone(home, p)
            self.assertTrue(home["id"].startswith("snd-"), p)

    def test_screen_and_mouth_parts_exist(self):
        for part in ("read-waveform", "read-spectrogram", "read-formants", "read-pitch", "read-intensity",
                     "read-spectrum", "read-tool-cursor", "read-tool-scrub", "read-tool-ranges", "read-tool-lines"):
            self.assertIn(part, self.ids)
        self.assertTrue(any(i.startswith("art-") for i in self.ids))


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.book = book.load()

    def test_home_section_prefers_the_own_entry(self):
        self.assertEqual(book.home_section(self.book, "ɹ")["id"], "snd-r")
        self.assertEqual(book.home_section(self.book, "eɪ")["id"], "snd-ey")
        self.assertIsNone(book.home_section(self.book, "q"))

    def test_rabbit_lists_its_sounds_with_r_as_target(self):
        ctx = book.context_for(self.book, "Rabbit")
        self.assertEqual([s.phoneme for s in ctx.sounds], ["ɹ", "æ", "b", "ɪ", "t"])
        self.assertEqual(ctx.targets, ["ɹ"])
        self.assertEqual(ctx.home_ids, {"snd-r", "snd-ae", "snd-b", "snd-ih", "snd-t"})

    def test_line_puts_the_word_first_then_the_other_sounds(self):
        ctx = book.context_for(self.book, "rabbit", "a soft rabbit")
        self.assertEqual([s.phoneme for s in ctx.sounds][:5], ["ɹ", "æ", "b", "ɪ", "t"])
        self.assertIn("s", [s.phoneme for s in ctx.sounds])

    def test_page_for_rabbit_highlights_its_sections_and_keeps_every_other(self):
        html = book.book_page("rabbit", book=self.book)
        self.assertIn("For this word: rabbit", html)
        self.assertEqual(len(re.findall(r'<a class="chip', html)), 5)
        for sid in ("snd-r", "snd-ae", "snd-b", "snd-ih", "snd-t"):
            self.assertRegex(html, rf'<section id="{sid}" class="[^"]*ctx-home')
            self.assertIn(f'href="#{sid}"', html)
        self.assertNotRegex(html, r'<section id="snd-s" class="[^"]*ctx-home')
        self.assertEqual(html.count("<section id="), len(self.book["sections"]))
        self.assertRegex(html, r'<section id="err-gliding" class="[^"]*ctx-rel')  # target-related, lighter mark

    def test_unknown_word_says_so_and_highlights_nothing(self):
        html = book.book_page("zebra", book=self.book)
        self.assertIn("not in the word list yet", html)
        self.assertNotRegex(html, r'class="[^"]*ctx-(home|rel)')

    def test_plain_page_has_no_panel_and_escapes_the_word(self):
        self.assertNotIn('id="for-this-word"', book.book_page(book=self.book))
        self.assertNotIn("<script>alert", book.book_page("<script>alert(1)</script>", book=self.book))

    def test_page_is_offline(self):
        for html in (book.book_page("rabbit", book=self.book), book.print_page(self.book)):
            t = Tags()
            t.feed(html)
            for url in t.hrefs + t.srcs:
                self.assertFalse(re.match(r"^(https?:)?//", url), url)
            self.assertNotIn("@import", html)

    def test_index_links_every_section(self):
        html = book.book_page(book=self.book)
        toc = html.split('<ul class="toc">')[1].split("</ul>")[0]
        self.assertEqual(sorted(re.findall(r'href="#([^"]+)"', toc)), sorted(s["id"] for s in self.book["sections"]))

    def test_figures_are_served_from_the_book_path(self):
        html = book.book_page(book=self.book)
        self.assertIn('src="/book/figures/', html)
        self.assertNotIn('src="figures/', html)

    def test_print_page_has_every_section_in_order(self):
        html = book.print_page(self.book)
        found = re.findall(r'<section id="([^"]+)"', html)
        self.assertEqual(found, [s["id"] for s, _ in book.ordered(self.book)])

    def test_figure_path_refuses_anything_but_a_figure_name(self):
        self.assertIsNotNone(book.figure_path("fig-classes.png"))
        for bad in ("../book.py", "x.svg", "..%2Fbook.py", ""):
            self.assertIsNone(book.figure_path(bad))


class MissingBookTest(unittest.TestCase):
    def test_missing_and_broken_files_raise_a_clear_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(book.BookError, "not on this machine"):
                book.load(str(Path(d) / "none.json"))
            bad = Path(d) / "bad.json"
            bad.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(book.BookError, "could not be read"):
                book.load(str(bad))


if __name__ == "__main__":
    unittest.main()
