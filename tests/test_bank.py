import io
import json
import re
import unittest
from contextlib import redirect_stderr

from speakup.bank import INTENSIFIERS, KID_WORDS, build_prompt, check_line, fill, grammar, load_fallback, parse_reply
from speakup.llm import LlmError
from speakup.words import Word, load_words

WORDS = [Word("rabbit", "start"), Word("carrot", "middle"), Word("car", "end")]


class CheckLineTest(unittest.TestCase):
    def test_passing_line(self):
        check_line("the puppy sees a soft rabbit.", Word("rabbit", "start"), WORDS)

    def test_non_word(self):
        # The line also lacks its target; the first reason wins.
        with self.assertRaisesRegex(ValueError, "not a word: wabbit"):
            check_line("a big wabbit", Word("rabbit", "start"), WORDS)

    def test_r_in_wrong_position(self):
        # car is Lexi's end-position word; asked for as start, it fails.
        with self.assertRaisesRegex(ValueError, "position"):
            check_line("a blue car", Word("car", "start"), WORDS)

    def test_target_missing_or_twice(self):
        with self.assertRaisesRegex(ValueError, "target missing"):
            check_line("a big dog", Word("rabbit", "start"), WORDS)
        with self.assertRaisesRegex(ValueError, "target twice"):
            check_line("a car a car", Word("car", "end"), WORDS)

    def test_second_r_word(self):
        with self.assertRaisesRegex(ValueError, "another r word: car"):
            check_line("the rabbit sees a car", Word("rabbit", "start"), WORDS)


class WordListTest(unittest.TestCase):
    def test_kid_words_have_no_r_and_no_lexi_word(self):
        lexi = {w.word for w in load_words()}
        for group, kid_words in KID_WORDS.items():
            for word in kid_words:
                with self.subTest(group=group, word=word):
                    self.assertNotIn("r", word)
                    self.assertNotIn(word, lexi)

    def test_lexi_words_read_as_nouns(self):
        # Pins Decision 3: if Lexi adds a non-noun, this test names it.
        self.assertEqual({w.word for w in load_words()} - INTENSIFIERS,
                         {"rabbit", "rain", "ring", "rocket", "truck", "carrot", "car", "door", "bear"})


class FallbackTest(unittest.TestCase):
    def test_every_fallback_line_passes(self):
        load_fallback(load_words())

    def test_fallback_missing_word_raises(self):
        with self.assertRaisesRegex(ValueError, "cherry"):
            load_fallback([Word("cherry", "middle")])

    def test_bank_line(self):
        bank = load_fallback(load_words())
        self.assertEqual(bank.line(Word("rabbit", "start"), "word"), "rabbit")
        self.assertEqual(bank.line(Word("rabbit", "start"), "sentence"), "the puppy sees a soft rabbit.")


# What Qwen2.5-0.5B answered under the grammar while planning (plan, "What the planning session measured").
PHRASE_REPLY = ('{"rabbit": "a little rabbit", "rain": "a big rain", "ring": "a little ring", "rocket": "a big rocket", '
                '"truck": "a big truck", "carrot": "a little carrot", "very": "a very big toy", "car": "a big car", '
                '"door": "a big door", "bear": "a big bear"}')
SENTENCE_REPLY = ('{"rabbit": "the little bunny sees a big rabbit.", "rain": "the big dog sees a big rain.", '
                  '"ring": "the little dog sees a big ring.", "rocket": "the big dog sees a big rocket.", '
                  '"truck": "the big dog sees a big truck.", "carrot": "the little dog sees a big carrot.", '
                  '"very": "the dog sees a very big toy.", "car": "the big dog sees a big car.", '
                  '"door": "the big dog sees a big door.", "bear": "the big dog sees a big bear."}')


def _without_quoted(text):
    return re.sub(r'"(?:[^"\\]|\\.)*"', " ", text)


class QwenBankTest(unittest.TestCase):
    def test_grammar_defines_every_rule_it_uses(self):
        for level in ("phrase", "sentence"):
            rules = dict(line.split(" ::= ", 1) for line in grammar(level, load_words()).splitlines())
            used = set(re.findall(r"[a-z][a-z0-9-]*", " ".join(_without_quoted(rhs) for rhs in rules.values())))
            with self.subTest(level=level):
                self.assertIn("root", rules)
                self.assertEqual(used - set(rules), set())

    def test_grammar_locks_each_word(self):
        rules = dict(line.split(" ::= ", 1) for line in grammar("phrase", WORDS).splitlines())
        self.assertIn('"rabbit"', rules["l-rabbit"])
        self.assertNotIn("carrot", rules["l-rabbit"])
        self.assertNotIn('"car"', rules["l-rabbit"])
        very = dict(line.split(" ::= ", 1) for line in grammar("phrase", [Word("very", "middle")]).splitlines())
        self.assertIn('" very "', very["l-very"])

    def test_prompt_names_format_words_and_examples(self):
        prompt = build_prompt("sentence", load_words())
        for text in ("one JSON object", "Words: rabbit, rain,", "the cat likes a very soft bed."):
            self.assertIn(text, prompt)

    def test_parse_reply_keeps_passing_lines(self):
        lines = parse_reply(SENTENCE_REPLY, "sentence", load_words())
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines["rabbit"], "the little bunny sees a big rabbit.")

    def test_parse_reply_drops_and_logs(self):
        reply = json.loads(PHRASE_REPLY)
        reply["rabbit"] = "a big wabbit"
        err = io.StringIO()
        with redirect_stderr(err):
            lines = parse_reply(json.dumps(reply), "phrase", load_words())
        self.assertNotIn("rabbit", lines)
        self.assertEqual(len(lines), 9)
        self.assertIn("bank: dropped phrase line for rabbit: 'a big wabbit' (not a word: wabbit)", err.getvalue())

    def test_parse_reply_bad_json_keeps_fallback(self):
        words = load_words()
        fallback = load_fallback(words)
        rabbit = Word("rabbit", "start")
        for reply in ('{"rabbit": "a big rab', '["a big rabbit"]', '{"cherry": "a big cherry"}', '{"rabbit": 7}'):
            with self.subTest(reply=reply), redirect_stderr(io.StringIO()):
                bank = fill(lambda prompt, grammar=None, n_predict=96: reply, words, fallback)
                self.assertEqual(bank.line(rabbit, "phrase"), "a soft rabbit")
                self.assertEqual(bank.line(rabbit, "sentence"), "the puppy sees a soft rabbit.")

    def test_fill_uses_qwen_lines_and_survives_llm_error(self):
        words = load_words()
        calls = []

        def generate(prompt, grammar=None, n_predict=96):
            calls.append((grammar, n_predict))
            if "short phrase" in prompt:
                return PHRASE_REPLY
            raise LlmError("llama.cpp took longer than 120 s")

        err = io.StringIO()
        with redirect_stderr(err):
            bank = fill(generate, words, load_fallback(words))
        rabbit = Word("rabbit", "start")
        self.assertEqual(bank.line(rabbit, "phrase"), "a little rabbit")
        self.assertEqual(bank.line(rabbit, "sentence"), "the puppy sees a soft rabbit.")
        self.assertIn("bank: sentence call failed: llama.cpp took longer than 120 s", err.getvalue())
        self.assertRegex(err.getvalue(), r"bank: phrase took \d+\.\d s, kept 10 of 10 lines")
        self.assertEqual(len(calls), 2)
        for grammar_text, n_predict in calls:
            self.assertTrue(grammar_text)
            self.assertEqual(n_predict, 400)

    def test_by_qwen_only_for_the_lines_qwen_kept(self):
        words = load_words()
        with redirect_stderr(io.StringIO()):
            bank = fill(lambda prompt, grammar=None, n_predict=96: PHRASE_REPLY if "short phrase" in prompt else "{}",
                        words, load_fallback(words))
        rabbit = Word("rabbit", "start")
        self.assertTrue(bank.by_qwen(rabbit, "phrase", "a little rabbit"))
        self.assertFalse(bank.by_qwen(rabbit, "phrase", "a soft rabbit"))  # the fixed line, taken before the swap
        self.assertFalse(bank.by_qwen(rabbit, "sentence", "the puppy sees a soft rabbit."))
        self.assertFalse(bank.by_qwen(rabbit, "word", "rabbit"))
        self.assertFalse(load_fallback(words).by_qwen(rabbit, "phrase", "a soft rabbit"))


if __name__ == "__main__":
    unittest.main()
