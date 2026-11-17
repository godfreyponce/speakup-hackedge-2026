"""One screening session (#5): the checks on what the therapist types, and the per-word results. No I/O."""

import re
from dataclasses import dataclass, replace
from datetime import date, datetime

from speakup.age_norms import should_flag, should_watch
from speakup.result import ERROR_TYPES, Result
from speakup.words import Word

# The ID goes into the clip's file name, so a "/" or ".." must never get through.
_CHILD_ID = re.compile(r"[A-Za-z0-9-]+")
_WHOLE_NUMBER = re.compile(r"[0-9]+")


def parse_child_id(raw: str) -> str:
    child_id = raw.strip()
    if not _CHILD_ID.fullmatch(child_id):
        raise ValueError("Child ID: use letters, digits and hyphens only, and no names.")
    return child_id


def parse_age(years: str, months: str) -> int:
    years, months = years.strip(), months.strip() or "0"
    if not _WHOLE_NUMBER.fullmatch(years):
        raise ValueError("Age: years must be a whole number.")
    if not _WHOLE_NUMBER.fullmatch(months) or int(months) > 11:
        raise ValueError("Age: months must be a whole number from 0 to 11, or blank.")
    return int(years) * 12 + int(months)


# School age, with room on both sides: a birth date outside this is almost surely a typing slip.
MIN_AGE_MONTHS, MAX_AGE_MONTHS = 2 * 12, 22 * 12


def parse_birth_date(raw: str, today: date | None = None) -> int:
    """Age in whole months on the screening day, from a YYYY-MM-DD birth date (what a date field sends).
    Only the age is kept: the birth date itself is never stored."""
    today = today or date.today()
    try:
        born = date.fromisoformat(raw.strip())
    except ValueError:
        raise ValueError("Date of birth: pick a date.") from None
    if born > today:
        raise ValueError("Date of birth: that date is in the future.")
    months = (today.year - born.year) * 12 + (today.month - born.month) - (1 if today.day < born.day else 0)
    if not MIN_AGE_MONTHS <= months <= MAX_AGE_MONTHS:
        raise ValueError(f"Date of birth: that makes the student {months // 12} years old. Check the year.")
    return months


def format_age(age_months: int) -> str:
    return f"{age_months // 12} yr {age_months % 12} mo"


@dataclass(frozen=True)
class Attempt:
    word: Word
    result: Result
    flagged: bool
    watched: bool
    # What Arti said before the SLP checked it; None until the SLP gives a verdict.
    arti: Result | None = None
    slp: str | None = None  # "correct" or "wrong" once the SLP has checked this word
    clip: str | None = None  # path of the recording on this machine; audio never leaves the board
    # Practice tries only (#21); screen tries leave both None.
    level: str | None = None
    line: str | None = None
    # The target word inside the recording (Nov 4), seconds from its start; Arti scored only this part.
    sel_start: float | None = None
    sel_end: float | None = None
    sel_auto: bool = True  # False once the SLP has moved the box
    arti_call_checked: str | None = None  # Arti's call when the SLP checked; moving the box can change it after

    @property
    def arti_call(self) -> str:
        """Arti's own call, in the SLP's words: "correct" or "wrong". It never changes with the SLP's call."""
        return "wrong" if (self.arti or self.result).error_type else "correct"


def verdict_for(attempt: Attempt, call: str) -> str:
    """The SLP's call from the word card: agree or disagree with Arti's own call (#37), or correct or wrong."""
    if call in ("correct", "wrong"):
        return call
    if call == "agree":
        return attempt.arti_call
    if call == "disagree":
        return "correct" if attempt.arti_call == "wrong" else "wrong"
    raise ValueError(f"verdict must be agree, disagree, correct or wrong, not {call!r}")


def arti_p_wrong(attempt: Attempt) -> float | None:
    """Arti's p(wrong) for this try, from the confidence it gave its own call; None when it gave none."""
    arti = attempt.arti or attempt.result
    if arti.confidence is None:
        return None
    return round(arti.confidence if arti.error_type else 1 - arti.confidence, 2)  # confidence is kept at 2 places


def checked(attempt: Attempt, verdict: str, age_months: int) -> Attempt:
    """The SLP's call replaces Arti's: only the checked result is flagged, tallied and saved.
    Picking the other button later changes the call; Arti's own answer is kept in `arti`."""
    if verdict not in ("correct", "wrong"):
        raise ValueError(f"verdict must be correct or wrong, not {verdict!r}")
    arti = attempt.arti or attempt.result
    if verdict == "correct":
        result = replace(arti, error_type=None, heard_phone=arti.expected_phone)
    elif arti.error_type is not None:
        result = arti
    else:
        result = replace(arti, error_type="off", heard_phone=None)
    return replace(
        attempt, result=result,
        flagged=should_flag(result.error_type, result.target_sound, age_months),
        watched=should_watch(result.error_type, result.target_sound, age_months),
        arti=arti, slp=verdict, arti_call_checked=attempt.arti_call,
    )


def rescored(attempt: Attempt, result: Result, selection: tuple[float, float, bool], age_months: int) -> Attempt:
    """The same try with Arti's answer on a new selection. The SLP's call, if made, stays and is applied
    to the new answer, so moving the box never silently undoes a check."""
    start, end, auto = selection
    fresh = replace(
        attempt, result=result, arti=None, slp=None, sel_start=start, sel_end=end, sel_auto=auto,
        flagged=should_flag(result.error_type, result.target_sound, age_months),
        watched=should_watch(result.error_type, result.target_sound, age_months),
    )
    if not attempt.slp:
        return fresh
    return replace(checked(fresh, attempt.slp, age_months), arti_call_checked=attempt.arti_call_checked)


class Session:
    """One slot per word. The SLP can go back to any word; recording it again replaces that word's slot."""

    def __init__(self, child_id: str, age_months: int, words: list[Word]):
        self.child_id = child_id
        self.age_months = age_months
        self.words = words
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.index = 0
        self._slots: list[Attempt | None] = [None] * len(words)

    @property
    def done(self) -> bool:
        return self.index >= len(self.words)

    @property
    def current_word(self) -> Word | None:
        return None if self.done else self.words[self.index]

    @property
    def current_attempt(self) -> Attempt | None:
        return None if self.done else self._slots[self.index]

    @property
    def attempts(self) -> list[Attempt]:
        """The recorded words, in word-list order."""
        return [a for a in self._slots if a is not None]

    def slot(self, i: int) -> Attempt | None:
        return self._slots[i]

    def add_result(self, result: Result, clip: str | None = None,
                   selection: tuple[float, float, bool] | None = None) -> Attempt:
        if self.done:
            raise ValueError("the session is finished")
        start, end, auto = selection or (None, None, True)
        attempt = Attempt(
            word=self.current_word,
            result=result,
            flagged=should_flag(result.error_type, result.target_sound, self.age_months),
            watched=should_watch(result.error_type, result.target_sound, self.age_months),
            clip=clip, sel_start=start, sel_end=end, sel_auto=auto,
        )
        self._slots[self.index] = attempt
        return attempt

    def rescore(self, result: Result, selection: tuple[float, float, bool]) -> Attempt:
        """Arti's answer on the SLP's new selection of the current word's recording."""
        attempt = self.current_attempt
        if attempt is None:
            raise ValueError("record the word before choosing part of it")
        self._slots[self.index] = rescored(attempt, result, selection, self.age_months)
        return self._slots[self.index]

    def verify(self, verdict: str, i: int | None = None) -> Attempt:
        """The SLP's call on word i, the word the card shows (#78); without i, the current word."""
        i = self.index if i is None else i
        attempt = self._slots[i] if 0 <= i < len(self._slots) else None
        if attempt is None:
            raise ValueError("record the word before checking it")
        self._slots[i] = checked(attempt, verdict_for(attempt, verdict), self.age_months)
        return self._slots[i]

    def go(self, i: int) -> None:
        """Jump to word i (0-based) while the session is open."""
        if self.done:
            raise ValueError("the session is finished")
        if not 0 <= i < len(self.words):
            raise ValueError(f"no word {i + 1}")
        self.index = i

    def next(self) -> None:
        """Move on from a recorded word. From the last word it goes to the first word not yet recorded,
        and finishes the session only when every word has a recording."""
        if self.current_attempt is None:
            return
        empty = [i for i, a in enumerate(self._slots) if a is None]
        later = [i for i in empty if i > self.index]
        self.index = later[0] if later else (empty[0] if empty else len(self.words))

    def finish(self) -> None:
        """End early: words never recorded are left out of the tally and the save."""
        self.index = len(self.words)


def tally(attempts: list[Attempt]) -> dict[str, int]:
    counts = {error_type: 0 for error_type in ERROR_TYPES}
    for a in attempts:
        if a.flagged:
            counts[a.result.error_type] += 1
    return counts


def position_tally(attempts: list[Attempt]) -> dict[str, tuple[int, int]]:
    """Right and off counts per r position over the words the SLP has checked: only the SLP's call counts.
    Keys follow the word list's positions; the practice coach (#21) can key the same way by level."""
    counts: dict[str, list[int]] = {}
    for a in attempts:
        if a.slp is None:
            continue
        right_off = counts.setdefault(a.word.position, [0, 0])
        right_off[0 if a.result.error_type is None else 1] += 1
    return {position: (right, off) for position, (right, off) in counts.items()}


def agreement(attempts: list[Attempt]) -> tuple[int, int]:
    """How many of the SLP's checks matched Arti's call, out of how many checks."""
    checked = [a for a in attempts if a.slp is not None and a.arti is not None]
    agreed = sum((a.arti.error_type is None) == (a.slp == "correct") for a in checked)
    return agreed, len(checked)
