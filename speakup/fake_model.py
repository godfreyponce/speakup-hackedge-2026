"""Stands in for the real speech model until #2 lands."""

import random
from dataclasses import asdict
from datetime import datetime

from speakup.result import Result

# Distorted r has no single IPA symbol the team has agreed on, so the fake leaves heard_phone null.
_OUTCOMES = ((None, "ɹ"), ("gliding", "w"), ("distortion", None))


def fake_listen(word: str, rng: random.Random = random) -> dict:
    error_type, heard_phone = rng.choice(_OUTCOMES)
    return asdict(Result(
        word=word,
        target_sound="r",
        expected_phone="ɹ",
        heard_phone=heard_phone,
        error_type=error_type,
        confidence=round(rng.random(), 2),
        model="fake",
        recorded_at=datetime.now().astimezone().isoformat(timespec="seconds"),
    ))
