"""The adaptive coach: which word comes next, the tip the child sees after a miss, and "almost there" for the SLP.
Code makes every choice. Qwen only rewords the approved tips, and a reworded tip must pass `check_tip` first."""

import json
import re
from collections import Counter

from speakup.words import Word

# DRAFT tips for Lexi to approve before any child sees them. Kid words, no clinical terms. One per r position (shown
# with the word), and one per error the SLP can mark (shown after that miss instead of the position tip).
TIPS: dict[str, str] = {
    "start": "Get your tongue ready before you start. Pull it back and say rrr first.",
    "middle": "Go slow in the middle of the word. Hold the rrr a little longer.",
    "end": "Finish strong. Keep the rrr going to the very end of the word.",
    "gliding": "Keep your lips still so it is not a w. Pull your tongue back for rrr.",
    "distortion": "Lift the sides of your tongue up to your back teeth and growl rrr.",
}
# Words a reworded tip may use besides the approved tip's own words.
_EXTRA = frozenset("you your can now try it again so and the a to up on say just like this way nice good".split())
_MAX_TIP_WORDS = 16
ALMOST = 0.65  # an error call below this confidence is "almost there": a near miss, not a clear one


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def weakest(attempts) -> str | None:
    """The r position the child misses most, from the SLP-checked calls; None until a position has two tries."""
    tries, misses = Counter(), Counter()
    for a in attempts:
        tries[a.word.position] += 1
        misses[a.word.position] += a.result.error_type is not None
    rates = {p: misses[p] / n for p, n in tries.items() if n >= 2 and misses[p]}
    return max(rates, key=rates.get) if rates else None


def next_word(words: list[Word], attempts, turn: int) -> Word:
    """After a miss, stay on the child's weakest position (rotating its words); otherwise walk the list."""
    weak = weakest(attempts)
    if weak and attempts and attempts[-1].result.error_type is not None:
        pool = [w for w in words if w.position == weak]
        return pool[turn % len(pool)]
    return words[turn % len(words)]


def almost(result) -> bool:
    return result.error_type is not None and result.confidence is not None and result.confidence < ALMOST


def check_tip(tip: str, approved: str) -> None:
    """Raise ValueError naming why a reworded tip may not replace the approved one."""
    words = _words(tip)
    if not words or len(words) > _MAX_TIP_WORDS:
        raise ValueError(f"{len(words)} words")
    allowed = set(_words(approved)) | _EXTRA
    for w in words:
        if w not in allowed:
            raise ValueError(f"new word: {w}")
    if not tip.rstrip().endswith((".", "!")):
        raise ValueError("no end mark")


def tip_grammar() -> str:
    keys = ' ", " '.join(f'"\\"{p}\\": \\"" tip "\\""' for p in TIPS)
    return f'root ::= "{{" {keys} "}}"\ntip ::= [a-zA-Z\' ,]{{8,90}} [.!]'


def tip_prompt() -> str:
    system = ("You help a young child practice the r sound. Reword each tip so a 6-year-old understands it. "
              "Keep it short and kind, use the same ideas and mostly the same words. Answer with one JSON object "
              "with the same keys.")
    return (f"<|im_start|>system\n{system}<|im_end|>\n<|im_start|>user\n{json.dumps(TIPS)}<|im_end|>\n"
            "<|im_start|>assistant\n")


def parse_tips(reply: str, log=lambda m: None) -> dict[str, str]:
    """The approved tips, with each one Qwen reworded well enough swapped in."""
    tips = dict(TIPS)
    try:
        got = json.loads(reply)
    except ValueError:
        got = None
    if not isinstance(got, dict):
        log("tips reply is not a JSON object")
        return tips
    for pos, approved in TIPS.items():
        tip = got.get(pos)
        try:
            check_tip(tip if isinstance(tip, str) else "", approved)
        except ValueError as e:
            log(f"kept the approved {pos} tip, dropped {tip!r} ({e})")
            continue
        tips[pos] = tip.strip()
    return tips
