"""A scripted stand-in model for the Round 2 demo (#5): each word always gets the same result,
so the screen agrees with what the presenter says ("wabbit")."""

from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from speakup.result import Result
from speakup.words import Word

DEMO_OUTCOMES: dict[str, str | None] = {
    "rabbit": "gliding",
    "rain": None,
    "ring": None,
    "rocket": None,
    "truck": "gliding",
    "carrot": "distortion",
    "very": None,
    "car": None,
    "door": None,
    "bear": None,
}

# Distorted r has no agreed IPA symbol, so heard_phone stays null for it, as in fake_model.
_HEARD = {None: "ɹ", "gliding": "w", "distortion": None}


def check_script(words: list[Word]) -> None:
    missing = [w.word for w in words if w.word not in DEMO_OUTCOMES]
    if missing:
        raise ValueError(f"the demo script has no result for: {', '.join(missing)}")


def demo_listen(word: str, audio_path: Path | None = None) -> dict:
    error_type = DEMO_OUTCOMES[word]
    return asdict(Result(
        word=word,
        target_sound="r",
        expected_phone="ɹ",
        heard_phone=_HEARD[error_type],
        error_type=error_type,
        confidence=None,
        model="demo",
        recorded_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    ))
