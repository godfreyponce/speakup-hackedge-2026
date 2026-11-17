"""The practice coach's lines (#21): one line per Lexi word and level, and the check every line passes first.
A child never sees a line `check_line` has not passed. The kid word list stands in for CMUdict, a download:
a word is real when it is one of Lexi's words or in KID_WORDS."""

import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable

from speakup.llm import TURN, LlmError
from speakup.words import Word

LEVELS = ("word", "phrase", "sentence")

# Common words for a young child, by part of speech. None has the letter r, so the target is the line's only r.
KID_WORDS: dict[str, tuple[str, ...]] = {
    "det": ("a", "the", "my", "his", "this", "that"),
    "adj": ("big", "small", "little", "new", "hot", "cold", "wet", "soft", "fast", "slow", "happy", "silly", "funny",
            "good", "nice", "blue", "pink", "yellow", "black", "white", "tall", "long"),
    "who": ("dog", "cat", "cow", "pig", "hen", "duck", "fish", "mom", "dad", "baby", "puppy", "kitten", "bunny", "fox"),
    "noun": ("ball", "bed", "box", "cup", "hat", "cake", "book", "toy", "boat", "bus", "shoe", "sock", "bag", "kite",
             "bike"),
    "verb": ("sees", "saw", "has", "had", "likes", "wants", "finds", "found", "holds", "kicks", "pulls", "pushes", "gets",
             "hugs"),
}
_KID_WORDS = frozenset(w for group in KID_WORDS.values() for w in group)

# Lexi's words that are not nouns; every other Lexi word fills a noun slot.
INTENSIFIERS = frozenset({"very"})

FALLBACK_PATH = Path(__file__).with_name("practice_lines.csv")


def check_line(line: str, target: Word, words: list[Word]) -> None:
    """Raise ValueError naming the first reason the line is not fit to show for target."""
    tokens = line.lower().split()
    if tokens:
        tokens[-1] = tokens[-1].removesuffix(".")
    by_word = {w.word: w for w in words}
    for token in tokens:
        if token not in by_word and token not in _KID_WORDS:
            raise ValueError(f"not a word: {token}")
    count = tokens.count(target.word)
    if count == 0:
        raise ValueError("target missing")
    if count > 1:
        raise ValueError("target twice")
    for token in tokens:
        if token != target.word and "r" in token:
            raise ValueError(f"another r word: {token}")
    listed = by_word.get(target.word)
    if listed is None or listed.position != target.position:
        where = listed.position if listed else "missing"
        raise ValueError(f"r in the wrong position: {target.word} is {where} in words.csv")


class Bank:
    def __init__(self, lines: dict[tuple[str, str], str], qwen: frozenset[tuple[str, str]] = frozenset()):
        self.lines = lines
        self.qwen = qwen  # the (word, level) keys whose line Qwen wrote

    def line(self, word: Word, level: str) -> str:
        return word.word if level == "word" else self.lines[(word.word, level)]

    def by_qwen(self, word: Word, level: str, line: str) -> bool:
        # The line on screen may have been taken from the fixed bank before the swap, so it must also be Qwen's text.
        return (word.word, level) in self.qwen and self.lines[(word.word, level)] == line


def load_fallback(words: list[Word], path=FALLBACK_PATH) -> Bank:
    wanted = {w.word: w for w in words}
    lines = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(line for line in f if not line.startswith("#")):
            word, level, line = row["word"].strip(), row["level"].strip(), row["line"].strip()
            if word not in wanted:
                continue
            try:
                check_line(line, wanted[word], words)
            except ValueError as e:
                raise ValueError(f"{path}: {level} line for {word} {line!r}: {e}") from e
            lines[(word, level)] = line
    for w in words:
        for level in LEVELS[1:]:
            if (w.word, level) not in lines:
                raise ValueError(f"{path}: no {level} line for {w.word}")
    return Bank(lines)


# Qwen fills the phrase and sentence lines at startup (#21). The grammar fixes each line's shape by part of speech:
# with only a target slot in a free run of kid words, Qwen wrote word salad ("a small white very in the sun.").
_DESC = {
    "phrase": "a short phrase of 3 or 4 words",
    "sentence": "a short sentence of 5 to 8 words that ends with a period",
}
# The owner approved these example lines at gate 1.
_EXAMPLES = {
    "phrase": ("a silly rabbit", "the blue car", "a very big dog"),
    "sentence": ("my dad has a big truck.", "the fox sees a pink ring.", "the cat likes a very soft bed."),
}
_REPLY_TOKENS = 400  # a cap: the grammar ends the reply when the JSON object closes; measured replies ran 75 to 152


def _shape(level: str, word: str) -> str:
    target = f'"{word}"'
    if level == "phrase":
        return 'det " very " adj " " noun' if word in INTENSIFIERS else f'det " " adj " " {target}'
    if word in INTENSIFIERS:
        return 'det " " who " " verb " " det " very " adj " " noun "."'
    return f'det (" " adj)? " " who " " verb " " det (" " adj)? " " {target} "."'


def _rule_name(word: str) -> str:
    return "l-" + re.sub(r"[^a-z0-9]", "-", word.lower())


def grammar(level: str, words: list[Word]) -> str:
    """GBNF for one JSON object: each Lexi word in order as a key, its value locked to the level's shape."""
    pairs = ' ", " '.join(f'"\\"{w.word}\\": \\"" {_rule_name(w.word)} "\\""' for w in words)
    rules = [f'root ::= "{{" {pairs} "}}"']
    rules += [f"{_rule_name(w.word)} ::= {_shape(level, w.word)}" for w in words]
    rules += [f"{group} ::= " + " | ".join(f'"{w}"' for w in kid_words) for group, kid_words in KID_WORDS.items()]
    return "\n".join(rules)


def _turn(role: str, text: str) -> str:
    return f"<|im_start|>{role}\n{text}<|im_end|>\n"


def build_prompt(level: str, words: list[Word]) -> str:
    # ChatML, as summary.py's note prompt.
    system = (
        f"You write speech practice lines for a young child. For each word, write {_DESC[level]} that uses the word "
        "once. Use only simple words a young child knows. Answer with one JSON object: each key is a word, "
        f"each value is its line.\nExample lines: {'; '.join(_EXAMPLES[level])}"
    )
    return (_turn("system", system) + _turn("user", "Words: " + ", ".join(w.word for w in words))
            + "<|im_start|>assistant\n")


def _log(message: str) -> None:
    print(f"bank: {message}", file=sys.stderr, flush=True)


def parse_reply(reply: str, level: str, words: list[Word]) -> dict[str, str]:
    """Return word to line for each line in the reply that passes check_line; log every drop."""
    try:
        lines = json.loads(reply)
    except ValueError:
        lines = None
    if not isinstance(lines, dict) or not all(isinstance(v, str) for v in lines.values()):
        _log(f"{level} reply is not a JSON object")
        return {}
    by_word = {w.word: w for w in words}
    kept = {}
    for word, line in lines.items():
        if word not in by_word:
            _log(f"dropped {level} line for {word}: {line!r} (not in words.csv)")
            continue
        try:
            check_line(line, by_word[word], words)
        except ValueError as e:
            _log(f"dropped {level} line for {word}: {line!r} ({e})")
            continue
        kept[word] = line
    return kept


def fill(generate: Callable[..., str], words: list[Word], fallback: Bank) -> Bank:
    """One llama.cpp call per level; any word without a passed line keeps its fallback line."""
    lines = dict(fallback.lines)
    qwen = set()
    for level in LEVELS[1:]:
        try:
            with TURN:  # the clock starts on the bank's turn, so a note's run is not counted as the bank's (#60)
                started = time.monotonic()
                reply = generate(build_prompt(level, words), grammar=grammar(level, words), n_predict=_REPLY_TOKENS)
        except LlmError as e:
            _log(f"{level} call failed: {e}")
            continue
        took = time.monotonic() - started
        kept = parse_reply(reply, level, words)
        _log(f"{level} took {took:.1f} s, kept {len(kept)} of {len(words)} lines")
        lines.update({(word, level): line for word, line in kept.items()})
        qwen.update((word, level) for word in kept)
    return Bank(lines, frozenset(qwen))
