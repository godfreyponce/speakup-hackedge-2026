"""Write 10 sample end-screen notes (#39) to a text file, for Lexi's wording and grammar check.

The sessions are made up (fixed words, errors and ages, no child, no recording). For each one the file holds the code's
verdict line, the fixed family note in English and Spanish, and, with --llm-model, Qwen's SLP note and family notes
with the code's check result and the time each took. Write the file outside the repo: it is not committed.

Run: python3 scripts/note_samples.py OUT.txt [--llm-model models/qwen2.5-0.5b-instruct-q4_k_m.gguf]"""

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from speakup import family, llm, summary  # noqa: E402
from speakup.result import Result  # noqa: E402
from speakup.session import format_age  # noqa: E402

HEARD = {None: "ɹ", "gliding": "w", "distortion": None, "off": None}

# (age in months, {word: error type or None}): made up, from Lexi's word list.
SESSIONS = [
    (96, {"rabbit": "gliding", "rain": None, "ring": None, "carrot": "distortion", "car": None}),
    (66, {"rabbit": "gliding", "rocket": None, "truck": "gliding", "very": None}),
    (59, {"rabbit": "gliding", "ring": None, "door": None}),
    (84, {"rain": None, "ring": None, "rocket": None, "truck": None, "carrot": None}),
    (102, {"truck": "off", "bear": None, "car": "off"}),
    (78, {"rabbit": None, "rain": "gliding", "ring": None, "rocket": None, "very": None, "door": None}),
    (90, {"carrot": "distortion"}),
    (72, {"rabbit": "gliding", "rain": "gliding", "ring": "gliding", "rocket": None}),
    (108, {"rabbit": None, "rain": None, "truck": "distortion", "carrot": None, "very": None, "car": None,
           "door": None, "bear": "off"}),
    (63, {"bear": "gliding", "door": None, "car": None, "very": None, "ring": None}),
]


def results(words: dict[str, str | None]) -> list[Result]:
    return [Result(word=w, target_sound="r", expected_phone="ɹ", heard_phone=HEARD[e], error_type=e, confidence=None,
                   model="sample", recorded_at="2026-11-14T10:00:00-06:00") for w, e in words.items()]


def timed(fn) -> str:
    start = time.monotonic()
    try:
        text = fn()
        verdict = "passed the check"
    except (llm.LlmError, ValueError) as e:
        text, verdict = "", f"failed: {e}"
    return f"[{verdict}, {time.monotonic() - start:.1f} s] {text}"


def sample(n: int, age: int, words: dict[str, str | None], generate: summary.Generate | None) -> str:
    rs = results(words)
    lines = [f"=== Sample {n}: age {format_age(age)}, "
             + ", ".join(f"{w} ({e or 'right'})" for w, e in words.items()),
             summary.pass_or_refer(rs, age)]
    if generate is not None:
        lines.append("SLP note by Qwen " + timed(lambda: summary.note(rs, age, generate)))
    for lang in family.LANGS:
        lines.append(f"Family note, fixed ({lang}): {family.fixed_note(rs, age, lang)}")
        if generate is not None:
            lines.append(f"Family note by Qwen ({lang}) " + timed(lambda: family.qwen_note(rs, age, lang, generate)))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path, help="text file to write, outside the repo")
    parser.add_argument("--llm-model", type=Path, help="GGUF model; without it only the fixed notes are written")
    parser.add_argument("--llm-bin", default="llama-completion")
    args = parser.parse_args(argv)
    generate = llm.load(args.llm_bin, args.llm_model) if args.llm_model else None
    text = "\n\n".join(sample(n, age, words, generate) for n, (age, words) in enumerate(SESSIONS, 1))
    args.out.write_text(text + "\n", encoding="utf-8")
    print(f"wrote {len(SESSIONS)} samples to {args.out}")


if __name__ == "__main__":
    main()
