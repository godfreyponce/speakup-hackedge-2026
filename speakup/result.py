"""What the model hands to the app for one word. See docs/result-format.md."""

from dataclasses import dataclass, fields
from datetime import datetime
from typing import Optional

ERROR_WORDS: dict[str, str] = {"gliding": "gliding", "distortion": "distortion", "off": "the r sounded off"}
ERROR_TYPES = tuple(ERROR_WORDS)


@dataclass(frozen=True)
class Result:
    word: str
    target_sound: str
    expected_phone: str
    heard_phone: Optional[str]
    error_type: Optional[str]
    confidence: Optional[float]
    model: str
    recorded_at: str


FIELDS = tuple(f.name for f in fields(Result))


def check(d: dict) -> Result:
    """Return d as a Result, or raise ValueError naming every bad field."""
    problems = []
    missing = [k for k in FIELDS if k not in d]
    extra = [k for k in d if k not in FIELDS]
    if missing:
        problems.append(f"missing: {', '.join(missing)}")
    # Rejecting unknown keys keeps a child's name or audio path from riding along.
    if extra:
        problems.append(f"not in the format: {', '.join(extra)}")
    if missing:
        raise ValueError("; ".join(problems))

    for k in ("word", "target_sound", "expected_phone", "model"):
        if not isinstance(d[k], str) or not d[k]:
            problems.append(f"{k} must be a non-empty string")
    if d["heard_phone"] is not None and (not isinstance(d["heard_phone"], str) or not d["heard_phone"]):
        problems.append("heard_phone must be a non-empty string or null")
    if d["error_type"] is not None and d["error_type"] not in ERROR_TYPES:
        problems.append(f"error_type must be one of {ERROR_TYPES} or null")
    if d["error_type"] is None and d["heard_phone"] not in (None, d["expected_phone"]):
        problems.append("heard_phone must equal expected_phone when error_type is null")
    c = d["confidence"]
    if c is not None and (isinstance(c, bool) or not isinstance(c, (int, float)) or not 0 <= c <= 1):
        problems.append("confidence must be a number from 0 to 1, or null")
    try:
        if datetime.fromisoformat(d["recorded_at"]).tzinfo is None:
            problems.append("recorded_at needs a UTC offset")
    except (TypeError, ValueError):
        problems.append("recorded_at must be an ISO 8601 time")

    if problems:
        raise ValueError("; ".join(problems))
    return Result(**d)
