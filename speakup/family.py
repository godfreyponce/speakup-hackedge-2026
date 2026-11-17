"""The family practice note on the end screen (#39), in English and Spanish. Qwen writes it from code-built facts
and code checks it; when Qwen is off or its note fails, the fixed note from data/family_notes.json shows instead."""

import json
import re
from pathlib import Path
from typing import Sequence

from speakup.age_norms import should_flag, should_watch
from speakup.result import Result
from speakup.summary import BANNED, Generate, _turn, check_count_sentence, check_numbers, check_sound
from speakup.words import load_words

LANGS = ("en", "es")
FIXED_PATH = Path(__file__).parent / "data" / "family_notes.json"

INSTRUCTIONS = {
    "en": ("You write a short note for a child's family after a speech screening. Write 2 plain sentences in English. "
           "Use only the facts given. Name the words to practice. "
           "Do not say whether the child passes or should be referred. Do not diagnose."),
    "es": ("Escribes una nota corta para la familia de un niño después de una prueba del habla. "
           "Escribe 2 oraciones sencillas en español. Usa solo los datos dados. Nombra las palabras para practicar. "
           "No digas si el niño aprueba ni si debe ser referido. No diagnostiques."),
}
LABELS = {"en": ("Sound", "Number of words tried", "Words to practice"),
          "es": ("Sonido", "Número de palabras dichas", "Palabras para practicar")}
# One worked example, as for the SLP note: without one, Qwen2.5-0.5B copies the facts back. The Sound line is there
# because without it Qwen named the word's first letter ("the b sound" for bear) in 6 of 16 laptop samples (Nov 14).
# Three words, not two: with "rope and bird" Qwen dropped the third word of the demo's three.
EXAMPLE_WORDS = ("rope", "bird", "fork")
EXAMPLE_REPLIES = {
    "en": "Today your child said 4 words with the r sound. Please practice rope, bird and fork at home, slowly and for fun.",
    "es": "Hoy su hijo o hija dijo 4 palabras con el sonido r. Practiquen rope, bird y fork en casa, despacio y jugando.",
}
# The only number in the facts is the count of words tried. It may sit only in the example reply's first sentence or
# the fixed note's count sentence: any other wording can make it a false count of errors ("said 4 words correctly").
# The sound is the session's target sound (#50): "the r sound" in an /s/ session would be a false claim.
COUNT_SENTENCE = {"en": r"today your child said \d+ words? with the {sound} sound\.",
                  "es": r"hoy su hijo o hija dijo \d+ palabras? con el sonido {sound}\."}
# Every other sentence is a sentence of the fixed note, or a practice line as in EXAMPLE_REPLIES: the opener, then only
# the words to practice and these words. Anything else can widen the count ("and the remaining words", "All were hard").
PRACTICE_OPENER = {"en": "please practice ", "es": "practiquen "}
PRACTICE_LINE_WORDS = {"en": {"these", "words", "at", "home", "slowly", "and", "for", "fun"},
                       "es": {"estas", "palabras", "en", "casa", "despacio", "y", "jugando"}}
# Common short words of each language, to catch a note written in the wrong one.
MARKERS = {"en": {"the", "and", "your", "with", "at", "to", "these", "words", "please", "today"},
           "es": {"el", "la", "los", "las", "de", "en", "y", "que", "su", "con", "para", "palabras", "estas", "hoy"}}


def practice_words(results: Sequence[Result], age_months: int) -> list[str]:
    """Words flagged or to keep an eye on for the child's age. An error that is normal for age is not practice work."""
    return [r.word for r in results
            if should_flag(r.error_type, r.target_sound, age_months)
            or should_watch(r.error_type, r.target_sound, age_months)]


def _facts_text(lang: str, sound: str, tried: int, words: Sequence[str]) -> str:
    sound_label, count, practice = LABELS[lang]
    return f"{sound_label}: {sound}\n{count}: {tried}\n{practice}: {', '.join(words)}"


def sound_name(results: Sequence[Result]) -> str:
    """The session's target sounds as the facts, the fixed note and the count sentence name them."""
    return ", ".join(sorted({r.target_sound for r in results}))


def facts(results: Sequence[Result], age_months: int, lang: str) -> str:
    return _facts_text(lang, sound_name(results), len(results), practice_words(results, age_months))


def build_prompt(results: Sequence[Result], age_months: int, lang: str) -> str:
    return (
        _turn("system", INSTRUCTIONS[lang])
        + _turn("user", _facts_text(lang, "r", 4, EXAMPLE_WORDS))
        + _turn("assistant", EXAMPLE_REPLIES[lang])
        + _turn("user", facts(results, age_months, lang))
        + "<|im_start|>assistant\n"
    )


def check_family(reply: str, results: Sequence[Result], age_months: int, lang: str) -> str:
    """Return the reply stripped, or raise ValueError when it is cut off, in the wrong language, holds a banned word,
    a number not in the facts or a sound not tested, names a word that is not a word to practice, or leaves one out."""
    reply = reply.strip()
    if not reply:
        raise ValueError("empty reply")
    if not reply.endswith((".", "!", "?")):
        raise ValueError("cut off mid-sentence")
    if re.search(r"[{}]", reply):
        raise ValueError("has an unfilled {placeholder} from the fixed note")
    banned = BANNED.search(reply)
    if banned:
        raise ValueError(f"says {banned.group(0)!r}")
    check_numbers(reply, facts(results, age_months, lang), lang)
    sound = sound_name(results)
    count_sentence = re.compile(COUNT_SENTENCE[lang].format(sound=re.escape(sound)), re.I)
    check_count_sentence(reply, r"\d", [count_sentence, *_fixed_count_sentences(lang, sound)])
    practice = [w.lower() for w in practice_words(results, age_months)]
    fixed = set(re.split(r"(?<=[.!?])\s+", fixed_note(results, age_months, lang)))
    for sentence in re.split(r"(?<=[.!?])\s+", reply):
        line = sentence.lower()
        if re.search(r"\d", sentence) or sentence in fixed:
            continue
        if not line.startswith(PRACTICE_OPENER[lang]) or (
                set(re.findall(r"\w+", line.removeprefix(PRACTICE_OPENER[lang])))
                - PRACTICE_LINE_WORDS[lang] - set(practice)):
            raise ValueError(f"has a sentence that is not the count or a practice line: {sentence}")
    check_sound(reply, {r.target_sound for r in results})
    tokens = re.findall(r"\w+", reply.lower())
    other = next(o for o in LANGS if o != lang)
    if sum(t in MARKERS[lang] for t in tokens) <= sum(t in MARKERS[other] for t in tokens):
        raise ValueError(f"not written in {lang}")
    listed = {w.word.lower() for w in load_words()} | {r.word.lower() for r in results} | set(EXAMPLE_WORDS)
    for w in sorted(listed):
        if w in tokens and w not in practice:
            raise ValueError(f"names {w}, which is not a word to practice")
    missing = [w for w in practice if w not in tokens]
    if missing:
        raise ValueError(f"leaves out a word to practice: {', '.join(missing)}")
    # Qwen once wrote "Practiquen rain, rain, rain, rain, rain y rain" (Nov 14).
    repeated = [w for w in practice if tokens.count(w) > 1]
    if repeated:
        raise ValueError(f"repeats a word: {', '.join(repeated)}")
    return reply


def _fixed_count_sentences(lang: str, sound: str) -> list[re.Pattern]:
    """The fixed notes' first sentences with any count: they hold {tried} and {sound}, and Lexi may reword them."""
    firsts = {re.split(r"(?<=[.!?])\s+", t)[0] for t in _fixed_templates(lang).values()}
    return [re.compile(re.escape(f).replace(re.escape("{tried}"), r"\d+").replace(re.escape("{sound}"), re.escape(sound)),
                       re.I) for f in firsts]


def _fixed_templates(lang: str) -> dict:
    return json.loads(FIXED_PATH.read_text(encoding="utf-8"))[lang]


def fixed_note(results: Sequence[Result], age_months: int, lang: str) -> str:
    templates = _fixed_templates(lang)
    words = practice_words(results, age_months)
    return templates["practice" if words else "none"].format(tried=len(results), sound=sound_name(results),
                                                             words=", ".join(words))


def qwen_note(results: Sequence[Result], age_months: int, lang: str, generate: Generate) -> str:
    """Qwen's checked note, or ValueError. With no word to practice Qwen is not asked: it copies the example's words."""
    if not practice_words(results, age_months):
        raise ValueError("no words to practice")
    return check_family(generate(build_prompt(results, age_months, lang)), results, age_months, lang)
