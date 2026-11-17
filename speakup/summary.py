"""End-of-session summary for the SLP (#7). The code decides pass, watch or refer; the model only words the facts,
and `check_reply` keeps a reply off the screen when its claims do not match the session (#9)."""

import re
from typing import Callable, Sequence

from speakup.age_norms import should_flag, should_watch
from speakup.result import ERROR_WORDS, Result
from speakup import calibration
from speakup.session import Attempt, arti_p_wrong, format_age

Generate = Callable[[str], str]

INSTRUCTIONS = (
    "You write a short note for a school speech therapist about one speech screening session. "
    "Write 2 or 3 plain sentences. Use only the facts given. "
    "Do not say whether the child passes or should be referred. Do not diagnose."
)
# One worked example: without it Qwen2.5-0.5B copied the facts list back instead of writing sentences.
# At 5 yr 6 mo: with a 7-year-old example the model called every 5-to-6 word flagged (#24 plan).
EXAMPLE_FACTS = (
    "Child's age: 5 yr 6 mo\n"
    "Number of words tried: 4\n"
    "Words with an error heard:\n"
    "- rope: gliding (heard w), keep an eye on it\n"
    "- bird: distortion, keep an eye on it"
)
EXAMPLE_REPLY = (
    "The child tried 4 words with the r sound. Rope had gliding (heard w), so keep an eye on it. "
    "Bird had a distortion, so keep an eye on it."
)
EXAMPLE_WORDS = ("rope", "bird")


# Words neither note may hold, in English and Spanish: the code decides pass or refer, and nothing diagnoses.
BANNED = re.compile(r"\b(?:(?:pass|fail|refer|diagn[oó]s|disorder|aprob|reprob|trastorno|desorden|deriv|remit)\w*"
                    r"|suspend\w*|pas(?:ó|o|a|ar)\b|fall(?:ó|o|a|ar|aron|ado)\b)", re.I)


# A number written as a word gets past the digit check, so the notes may hold digits only (#39).
SPELLED_NUMBERS = {
    "en": ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
           "seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred dozen once twice"),
    # "un" and "una" are also the Spanish "a", so they stay allowed.
    "es": ("cero uno dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis "
           "dieciseis diecisiete dieciocho diecinueve veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa cien "
           "ciento docena"),
}


# "a single word" and "una sola palabra" are a count of 1 that the digit check does not see.
_ONE_WORD = re.compile(r"\b(?:an?|un|una)\s+(?:single\s+|sol[oa]\s+)?(?:word|palabra)\b", re.I)


def check_numbers(reply: str, facts: str, lang: str = "en") -> None:
    """Raise ValueError when the reply holds a digit that is not in the facts, or a number written as a word."""
    numbers = set(re.findall(r"\d+", reply)) | ({"1"} if _ONE_WORD.search(reply) else set())
    numbers -= set(re.findall(r"\d+", facts))
    if numbers:
        raise ValueError(f"has a number not in the facts: {', '.join(sorted(numbers))}")
    spelled = [w for w in re.findall(r"\w+", reply.lower())
               if w in SPELLED_NUMBERS[lang].split() or (lang == "es" and w.startswith("veinti"))]
    if spelled:
        raise ValueError(f"has a number written as a word: {', '.join(spelled)}")


def _check_number_meanings(reply: str, results: Sequence[Result], age_months: int) -> None:
    """Each digit must say what its fact says: "8 words" is the count, "7 yr 6 mo" the age. Without this, a note
    with 5 words tried at 7 yr 6 mo could say "tried 7 words" and pass, since 7 is in the facts."""
    years, months = divmod(age_months, 12)
    facts = ((r"(\d+)\s+words?\b", len(results)), (r"(\d+)\s*(?:yr|years?)\b", years),
             (r"(\d+)\s*(?:mo|months?)\b", months))
    tied = 0
    for pattern, value in facts:
        for m in re.finditer(pattern, reply, re.I):
            if int(m.group(1)) != value:
                raise ValueError(f"says {m.group(0)!r}, but the fact is {value}")
            tied += 1
    if tied != len(re.findall(r"\d+", reply)):
        raise ValueError("has a number that is not the count of words or the age")


# Words that claim an error (#39): a sentence of the SLP note with one must have a word with an error as its subject.
ERROR_CLAIM = re.compile(r"\b(?:wrong\w*|miss\w*|errors?|errores|err[oó]ne\w*|incorrect\w*|inaccura\w*|mistak\w*"
                         r"|mispronounc\w*|trouble\w*|difficult\w*|dificultad\w*|dif[ií]cil\w*|problem\w*|issues?"
                         r"|struggl\w*|stumbl\w*|off|distort\w*|mal[oa]?s?|equivoc\w*|fall(?:as|os)|cost[oóa]|costaron"
                         r"|costar\w*|cuesta\w*|trab[oóa]|trabad\w*|trabar\w*)\b", re.I)


# Words that point at the words as a group or say how many had an error ("All were tricky", "Rabbit was the only
# error"): the SLP note names each word with an error, so it needs none, and each can make a false count (#39).
POINTER = re.compile(r"\b(?:all|every\w*|each|both|them|they|rest|others?|most|many|several|some|few|only|alone|sole"
                     r"|just|whole|half|majority|remaining|these|those|list)\b", re.I)


# The only sentence a word count may sit in, as in EXAMPLE_REPLY (#39). Any other wording can make the count of words
# tried a false count of errors: "5 words had an error", "the child said 5 words correctly".
COUNT_SENTENCE = re.compile(r"the child tried \d+ words? with the \w+ sound\.", re.I)


def check_count_sentence(reply: str, count: str, allowed: Sequence[re.Pattern]) -> None:
    """Raise ValueError when a sentence holding a `count` match is not one of the `allowed` sentences in full."""
    for sentence in re.split(r"(?<=[.!?])\s+", reply):
        if re.search(count, sentence, re.I) and not any(p.fullmatch(sentence) for p in allowed):
            raise ValueError(f"has a count outside the count sentence: {sentence}")


def check_sound(reply: str, sounds: set[str]) -> None:
    """Raise ValueError when the reply names a sound that is not a target sound: Qwen wrote "the b sound" for bear."""
    named = re.findall(r"\bthe ['\"/]?(\w+)['\"/]? sound\b|\bsonido (?:de (?:la )?)?['\"/]?(\w+)", reply.lower())
    wrong = sorted({en or es for en, es in named} - sounds)
    if wrong:
        raise ValueError(f"names a sound that was not tested: {', '.join(wrong)}")


def listen_words(attempts: Sequence[Attempt]) -> list[str]:
    """Words the end screen lists as "SLP please listen": Arti's p(wrong) is in Raf's unsure band (#37). Empty while
    calibration.UNSURE_BAND is None."""
    return [a.word.word for a in attempts if (p := arti_p_wrong(a)) is not None and calibration.unsure(p)]


def _require_results(results: Sequence[Result]) -> None:
    # "Pass: 0 of 0 words" would tell the SLP a child passed a screen they never took.
    if not results:
        raise ValueError("a session needs at least one result")


def _flagged(r: Result, age_months: int) -> bool:
    return should_flag(r.error_type, r.target_sound, age_months)


VERDICT_PHRASES = {"flag": "flagged for age", "watch": "keep an eye on it", "normal": "normal for age"}


def _any_of(phrases) -> str:
    return "|".join(re.escape(p) for p in phrases)


# Every SLP note sentence is one of these, in lower case (#39): open wording kept finding new ways to make a false
# claim ("Red was said correctly", "Rabbit was the lone error", "Nothing else stood out"). The glue words are the
# ones Qwen wrote in the Nov 14 samples and the #28 "very clearly" reply.
ERROR_SENTENCE = re.compile(rf"(?P<word>[a-z]+) had (?:an? |the )?(?:{_any_of(ERROR_WORDS.values())})"
                            rf"(?: \(heard (?P<heard>[^)\s]+)\))?, (?:so |which is )?(?:very clearly )?"
                            rf"(?:{_any_of(VERDICT_PHRASES.values())})\.")
OTHER_SENTENCES = (COUNT_SENTENCE, re.compile(r"the child is \d+ yr \d+ mo\."),
                   re.compile(r"there were no errors heard\."))
# The second form copies the facts line: the only listen sentence Qwen wrote in the #50 measurement.
LISTEN_SENTENCES = (re.compile(r"(?P<words>[a-z]+) needs the slp to listen\."),
                    re.compile(r"slp please listen: (?P<words>[a-z]+(?:, [a-z]+)*)\."))


def _check_allowed_sentence(sentence: str, by_word: dict[str, Result], listen: Sequence[str]) -> str | None:
    """Raise ValueError when the sentence is not an allowed one; return the word an error sentence is about."""
    error = ERROR_SENTENCE.fullmatch(sentence)
    asks = next((m for p in LISTEN_SENTENCES if (m := p.fullmatch(sentence))), None)
    named = asks.group("words").split(", ") if asks else []
    if set(named) - {w.lower() for w in listen}:
        raise ValueError(f"asks the SLP to listen to a word not in the unsure band: {sentence}")
    if len(set(named)) < len(named):
        raise ValueError(f"repeats a word: {sentence}")
    if not error and not asks and not any(p.fullmatch(sentence) for p in OTHER_SENTENCES):
        raise ValueError(f"has a sentence the SLP note does not allow: {sentence}")
    r = by_word.get(error.group("word")) if error else None
    # A word not in the session is left to the subject check below, which names the real fault.
    if r is not None and error.group("heard") and error.group("heard") != r.heard_phone:
        raise ValueError(f"says a heard sound that was not heard: {sentence}")
    return error.group("word") if error else None


def _verdict(r: Result, age_months: int) -> str:
    if should_flag(r.error_type, r.target_sound, age_months):
        return "flag"
    return "watch" if should_watch(r.error_type, r.target_sound, age_months) else "normal"


def pass_or_refer(results: Sequence[Result], age_months: int) -> str:
    _require_results(results)
    flagged = [r.word for r in results if _flagged(r, age_months)]
    n, age = len(results), format_age(age_months)
    if flagged:
        return f"Refer: {len(flagged)} of {n} words flagged for age {age} ({', '.join(flagged)})."
    watched = [r.word for r in results if should_watch(r.error_type, r.target_sound, age_months)]
    if watched:
        return f"Watch: {len(watched)} of {n} words to keep an eye on for age {age} ({', '.join(watched)})."
    return f"Pass: 0 of {n} words flagged for age {age}."


def _error_line(r: Result, age_months: int) -> str:
    heard = f" (heard {r.heard_phone})" if r.heard_phone is not None else ""
    return f"- {r.word}: {ERROR_WORDS[r.error_type]}{heard}, {VERDICT_PHRASES[_verdict(r, age_months)]}"


def _facts(results: Sequence[Result], age_months: int, listen: Sequence[str] = ()) -> str:
    errors = [_error_line(r, age_months) for r in results if r.error_type is not None]
    lines = [
        f"Child's age: {format_age(age_months)}",
        f"Number of words tried: {len(results)}",
        "Words with an error heard:" if errors else "Words with an error heard: none",
        *errors,
    ]
    if listen:
        lines.append(f"SLP please listen: {', '.join(listen)}")
    return "\n".join(lines)


def _turn(role: str, text: str) -> str:
    return f"<|im_start|>{role}\n{text}<|im_end|>\n"


def build_prompt(results: Sequence[Result], age_months: int, listen: Sequence[str] = ()) -> str:
    # ChatML is the chat format of Qwen2.5 and SmolLM2, the models #9 names.
    _require_results(results)
    return (
        _turn("system", INSTRUCTIONS)
        + _turn("user", EXAMPLE_FACTS)
        + _turn("assistant", EXAMPLE_REPLY)
        + _turn("user", _facts(results, age_months, listen))
        + "<|im_start|>assistant\n"
    )


def check_reply(reply: str, results: Sequence[Result], age_months: int, listen: Sequence[str] = ()) -> str:
    """Return the reply stripped, or raise ValueError when a claim in it does not match the session.
    Strict on purpose: the note sits under a Refer line a therapist acts on."""
    reply = reply.strip()
    if not reply:
        raise ValueError("empty reply")
    verdict = BANNED.search(reply)
    if verdict:
        raise ValueError(f"says {verdict.group(0)!r}")
    pointer = POINTER.search(reply)
    if pointer:
        raise ValueError(f"says {pointer.group(0)!r}")
    check_numbers(reply, _facts(results, age_months, listen))
    _check_number_meanings(reply, results, age_months)
    check_count_sentence(reply, r"\d+\s+words?\b", [COUNT_SENTENCE])
    check_sound(reply, {r.target_sound for r in results})

    by_word = {r.word.lower(): r for r in results}
    has_errors = any(r.error_type is not None for r in results)
    verdict_keys = (("flag", "flagged"), ("normal", "normal"), ("watch", "keep an eye"))
    claims = (*ERROR_WORDS.values(), *(key for _, key in verdict_keys))
    told = set()
    for sentence in re.split(r"(?<=[.!?])\s+", reply.lower()):
        told.add(_check_allowed_sentence(sentence, by_word, listen))
        # The word checks below only see sentences that name a word, and read "not flagged" as "flagged".
        if re.search(r"\bwords?\b", sentence) and not COUNT_SENTENCE.fullmatch(sentence):
            raise ValueError(f"says word outside the count sentence: {sentence}")
        if re.search(r"not\b|n't\b|\bwithout\b", sentence):
            raise ValueError(f"has a negation: {sentence}")
        if has_errors and re.search(r"\b(no|none)\b", sentence):
            raise ValueError(f"says no or none in a session with errors: {sentence}")
        # A correctly said list word ("very") is also plain English, so it counts only as the subject (#28).
        first = re.match(r"(?:on\s+)?([a-z]+)", sentence)
        subject = first.group(1) if first else None
        named = [subject] if subject in (*by_word, *EXAMPLE_WORDS) else []
        named += [w for w, r in by_word.items() if r.error_type is not None and w != subject
                  and re.search(rf"\b{re.escape(w)}\b", sentence)]
        for w in named:
            if w not in by_word:
                raise ValueError(f"names {w}, which is not a word with an error")
            if by_word[w].error_type is None and w not in listen:
                raise ValueError(f"names {w}, which had no error")
        if any(c in sentence for c in claims) and (subject not in by_word or by_word[subject].error_type is None):
            raise ValueError(f"makes a claim about {subject}, which is not a word with an error: {sentence}")
        # "All were wrong": an error claim with no word with an error as subject. A clean session may say "no errors".
        if ERROR_CLAIM.search(sentence) and not (re.search(r"\b(no|none)\b", sentence) if not has_errors
                                                 else subject in by_word and by_word[subject].error_type is not None):
            raise ValueError(f"claims an error with no word with an error as subject: {sentence}")
        named_results = [by_word[w] for w in named]
        verdicts = {_verdict(r, age_months) for r in named_results}
        for verdict, key in verdict_keys:
            if key in sentence and verdicts - {verdict}:
                raise ValueError(f"says {key} for a word that is {VERDICT_PHRASES[(verdicts - {verdict}).pop()]}: {sentence}")
        for error_type, phrase in ERROR_WORDS.items():
            for r in named_results:
                if phrase in sentence and r.error_type != error_type:
                    raise ValueError(f"says {phrase} for {r.word}, which had {ERROR_WORDS[r.error_type]}")
    # The SLP reads the note under the Refer line, so a flagged word it leaves out could be missed (#50).
    left_out = [w for w, r in by_word.items() if _flagged(r, age_months) and w not in told]
    if left_out:
        raise ValueError(f"leaves out a word flagged for age: {', '.join(left_out)}")
    return reply


def note(results: Sequence[Result], age_months: int, generate: Generate, listen: Sequence[str] = ()) -> str:
    return check_reply(generate(build_prompt(results, age_months, listen)), results, age_months, listen)
