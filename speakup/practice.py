"""The practice coach (#21): the child says one item, Arti scores it, and this code moves the level.
Qwen never sets the level or picks the word; it only fills the bank of lines and rewords the tips."""

from datetime import datetime

from speakup import coach
from speakup.age_norms import should_flag, should_watch
from speakup.bank import LEVELS, Bank
from speakup.result import Result
from speakup.session import Attempt, checked, rescored, verdict_for
from speakup.words import Word


def next_level(level: str, correct: bool) -> str:
    i = LEVELS.index(level) + (1 if correct else -1)
    return LEVELS[min(max(i, 0), len(LEVELS) - 1)]


class Practice:
    def __init__(self, child_id: str, age_months: int, words: list[Word], bank: Bank):
        self.child_id = child_id
        self.age_months = age_months
        self.words = words
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.level = LEVELS[0]
        self.turn = 0
        self._order = [words[0]]  # the word of each turn; the coach picks each next one
        self.tip: str | None = None  # shown to the child with the line after a miss
        self.line = bank.line(self.current_word, self.level)
        self._attempts: list[Attempt] = []

    @property
    def current_word(self) -> Word:
        return self._order[self.turn]

    @property
    def current_attempt(self) -> Attempt | None:
        return self._attempts[self.turn] if self.turn < len(self._attempts) else None

    @property
    def attempts(self) -> list[Attempt]:
        return list(self._attempts)

    def add_result(self, result: Result, clip: str | None = None,
                   selection: tuple[float, float, bool] | None = None) -> Attempt:
        start, end, auto = selection or (None, None, True)
        attempt = Attempt(
            word=self.current_word,
            result=result,
            flagged=should_flag(result.error_type, result.target_sound, self.age_months),
            watched=should_watch(result.error_type, result.target_sound, self.age_months),
            level=self.level,
            line=self.line,
            clip=clip, sel_start=start, sel_end=end, sel_auto=auto,
        )
        # Record again replaces the current try instead of adding a second one.
        self._attempts[self.turn:] = [attempt]
        return attempt

    def rescore(self, result: Result, selection: tuple[float, float, bool]) -> Attempt:
        """Arti's answer on the SLP's new selection of this try; the level is untouched until Next."""
        attempt = self.current_attempt
        if attempt is None:
            raise ValueError("record the line before choosing part of it")
        self._attempts[self.turn] = rescored(attempt, result, selection, self.age_months)
        return self._attempts[self.turn]

    def verify(self, verdict: str, i: int | None = None) -> Attempt:
        """The SLP's call replaces Arti's for try i, the try the card shows (#78); without i, the current try.
        On the current try it also decides the next level."""
        i = self.turn if i is None else i
        attempt = self._attempts[i] if 0 <= i < len(self._attempts) else None
        if attempt is None:
            raise ValueError("record the line before checking it")
        self._attempts[i] = checked(attempt, verdict_for(attempt, verdict), self.age_months)
        return self._attempts[i]

    def next(self, bank: Bank) -> None:
        # The bank comes in on each call because the server swaps it when Qwen finishes; a line on screen stays.
        attempt = self.current_attempt
        if attempt is None:
            return
        missed = attempt.result.error_type is not None
        self.level = next_level(self.level, not missed)
        self.turn += 1
        self._order[self.turn:] = [coach.next_word(self.words, self._attempts, self.turn)]
        self.tip = bank.tips.get(attempt.result.error_type) or bank.tips[self.current_word.position] if missed else None
        self.line = bank.line(self.current_word, self.level)
