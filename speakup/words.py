"""The practice words a child says in a session (#10). The list itself is words.csv."""

import csv
from dataclasses import dataclass
from pathlib import Path

POSITIONS = ("start", "middle", "end")
WORDS_PATH = Path(__file__).with_name("words.csv")


@dataclass(frozen=True)
class Word:
    word: str
    position: str


def load_words(path=WORDS_PATH) -> list[Word]:
    # utf-8-sig: Excel's "CSV UTF-8" export starts the file with a BOM.
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        words = [Word(word=row["word"].strip(), position=row["position"].strip()) for row in rows]
    for w in words:
        if not w.word:
            raise ValueError(f"{path}: a row has no word")
        if w.position not in POSITIONS:
            raise ValueError(f"{path}: {w.word!r} has position {w.position!r}, not one of {POSITIONS}")
    return words
