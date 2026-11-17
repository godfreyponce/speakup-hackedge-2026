"""Word to sounds (IPA) for every word the app shows, so the viewer, the word page and the sound book know
which sound a word tests. The list is speakup/data/lexicon.json. Sound-general: nothing here is r-only."""

import json
import re
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path(__file__).with_name("data") / "lexicon.json"
DEFAULT_TARGET = "ɹ"  # today Arti scores only r


@lru_cache(maxsize=1)
def _words(path: str = str(LEXICON_PATH)) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)["words"]


def entry(word: str) -> dict | None:
    """{"ipa": [...], "targets": [{"phoneme", "index", "context"}]} or None for a word not in the list."""
    return _words().get(word.strip().lower())


def target_of(word: str) -> str:
    """The sound this word tests (IPA). Falls back to r for a word not in the list."""
    e = entry(word)
    return e["targets"][0]["phoneme"] if e and e.get("targets") else DEFAULT_TARGET


def target_context(word: str) -> str | None:
    e = entry(word)
    return e["targets"][0].get("context") if e and e.get("targets") else None


def phonemes_of(text: str) -> list[str]:
    """Every sound in a word or practice line, first-seen order, no repeats. Unknown words are skipped."""
    seen: list[str] = []
    for token in re.findall(r"[a-z']+", text.lower()):
        for p in (entry(token) or {}).get("ipa", []):
            if p not in seen:
                seen.append(p)
    return seen
