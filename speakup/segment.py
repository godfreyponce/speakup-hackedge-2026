"""Finds the target word in a whole recording (Nov 4), so Arti hears only that word and the SLP can check it.

The recording now runs until 2 s of quiet or the SLP's Stop, so it may hold a phrase, a sentence, a false
start or a cough. This module picks the stretch of the recording that should be the target word:

- one word on the screen: the first voiced stretch that is a whole word (at least 0.15 s with a voice's
  pitch, within 15 dB of the loudest), after joining gaps under 250 ms (the closure of a b or a k inside a
  word is silent for 50 to 150 ms, so a word is one stretch once those are joined). The child speaks when
  Record starts; what follows is more often chatter or noise. No such stretch: the most voiced one;
- a phrase or sentence: the voiced stretches are split at shorter gaps; when there is one stretch per
  word, the target is the stretch at its place in the line; otherwise each word gets a share of the speech
  in proportion to its number of sounds (from the lexicon) and the stretches that lie mostly inside the
  target's share are taken.

This is the interim rule (plan R8): energy and pitch, no model. A stretch counts only where it has a voice's
pitch (Nov 12): coughs, clicks, breath and room noise have none, and on the board they won the box. A forced aligner (research track T1) can plug in
through `Aligner`; when it gives an answer that answer wins, and when it gives none the energy rule runs.
The SLP always sees the pick as a box on the waveform, can listen to it and move it.
Nothing here assumes a particular sound: it works from the line's words and the lexicon's sound counts.
"""

import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from speakup import audio

FRAME = 0.01  # s, energy frame
WORD_JOIN = 0.25  # s: gaps shorter than this are inside one word (stop closures)
PHRASE_JOIN = 0.08  # s: in running speech the gap between two words can be this short
MIN_STRETCH = 0.05  # s: shorter bursts are clicks, not words
PAD = 0.05  # s kept on each side of the pick, so a soft first or last sound is not cut
SPEECH_RANGE_DB = 35.0  # frames this far below the loud part of the clip are not speech
ABOVE_FLOOR_DB = 10.0  # and speech stands at least this far above the room
EDGE_DB = 4.0  # a found stretch grows while its frames stay this far above the room and voiced: a soft r is kept
MAX_EDGE = 0.3  # s, the most a stretch grows on each side
VOICED = 0.7  # normalized autocorrelation at a voice's pitch (80 to 400 Hz) that marks a frame voiced
MIN_VOICED = 0.03  # s of voiced frames a stretch needs (a short "truck" has 3 frames); clicks, coughs and noise have less
WORD_VOICED = 0.15  # s of voiced frames a whole word has
WORD_DB = 15.0  # a word is within this of the clip's loudest frame
MIN_SELECTION = 0.05  # s, the smallest box the SLP can make

# A future aligner: (samples, rate, the line's words, target word index) -> (start, end) in s, or None.
Aligner = Callable[[np.ndarray, int, list[str], int], "tuple[float, float] | None"]


@dataclass(frozen=True)
class Selection:
    start: float  # s from the start of the full recording
    end: float
    method: str  # "word", "count", "share", "aligner", "whole" (no speech found), "slp" (moved by hand)
    auto: bool = True

    @property
    def length(self) -> float:
        return self.end - self.start


def _frame_db(x: np.ndarray, rate: int) -> np.ndarray:
    step = max(1, int(rate * FRAME))
    n = len(x) // step
    if n == 0:
        return np.zeros(0)
    frames = x[: n * step].reshape(n, step)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    return 20 * np.log10(rms + 1e-9)


def _voiced(x: np.ndarray, rate: int) -> np.ndarray:
    """Per energy frame: does it repeat at a voice's pitch? The peak of the normalized autocorrelation over lags
    of 2.5 to 12.5 ms (unbiased, 150 Hz to 1 kHz where the pitch harmonics are), on 40 ms windows at 16 kHz. On the
    board's 31 test clips, words score 0.8 to 1.0 and nine in ten room frames under 0.7."""
    q = max(1, rate // 16000)
    y = x[: len(x) // q * q].reshape(-1, q).mean(axis=1)
    r = rate / q
    hop, win = max(1, int(r * FRAME)), int(r * 0.04)
    n = len(x) // max(1, int(rate * FRAME))
    padded = np.concatenate([np.zeros(win // 2), y, np.zeros(win)])
    frames = padded[np.arange(n)[:, None] * hop + np.arange(win)[None, :]]
    frames = frames - frames.mean(axis=1, keepdims=True)
    power = np.abs(np.fft.rfft(frames, 2 * win)) ** 2
    power[:, : int(150 * 2 * win / r)] = 0  # mains hum (60, 120 Hz) repeats too
    power[:, int(1000 * 2 * win / r):] = 0
    ac = np.fft.irfft(power)[:, :win]
    lags = np.arange(int(r / 400), int(r / 80))
    return (ac[:, lags] / ((win - lags) / win)).max(axis=1) / (ac[:, 0] + 1e-12) > VOICED


def stretches(x: np.ndarray, rate: int, join: float) -> list[tuple[float, float]]:
    """The voiced stretches of a clip in seconds, gaps shorter than `join` joined; a stretch with under 30 ms of
    voiced frames (a click, a cough, a breath) is dropped."""
    return [(a, b) for a, b, _, _ in _stretches(x, rate, join)]


def _stretches(x: np.ndarray, rate: int, join: float) -> list[tuple[float, float, float, float]]:
    """(start, end, voiced seconds, loudest dB below the clip's top) per stretch."""
    db = _frame_db(x, rate)
    if len(db) == 0:
        return []
    floor, top = np.percentile(db, 10), np.percentile(db, 99)
    if top - floor < ABOVE_FLOOR_DB:
        return []  # nothing stands above the room
    voiced = _voiced(x, rate)[: len(db)]
    loud = db > max(floor + ABOVE_FLOOR_DB, top - SPEECH_RANGE_DB)
    runs: list[list[int]] = []
    for i, on in enumerate(loud):
        if not on:
            continue
        if runs and (i - runs[-1][1]) * FRAME < join:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1])
    # Two thresholds (Nov 11): the loud core finds the word, the softer edge keeps its quiet start and end. A child
    # far from the mic is only 10 to 15 dB above the room, so the end of "bear" fell under the core's bar. The edge
    # grows only into voiced frames (Nov 12): on the soft bar alone it grew into room noise and clicks.
    soft, most = (db > floor + EDGE_DB) & voiced, round(MAX_EDGE / FRAME)
    for run in runs:
        a, b = run
        while a > 0 and run[0] - a < most and soft[a - 1]:
            a -= 1
        while b < len(db) and b - run[1] < most and soft[b]:
            b += 1
        run[:] = [a, b]
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * FRAME < join:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        said = voiced[a:b].sum() * FRAME
        if (b - a) * FRAME >= MIN_STRETCH and said >= MIN_VOICED:
            out.append((a * FRAME, b * FRAME, said, float(db[a:b].max() - top)))
    return out


def tokens(line: str) -> list[str]:
    return re.findall(r"[a-z']+", line.lower())


def target_index(words: list[str], target: str) -> int | None:
    """Where the target word sits in the line; a plural or -ing form ("rabbits") still counts."""
    target = target.lower()
    for i, w in enumerate(words):
        if w == target:
            return i
    for i, w in enumerate(words):
        if w.startswith(target):
            return i
    return None


def sound_count(word: str) -> int:
    """How many sounds a word has: from the lexicon, else roughly one per letter (a fair guess for short words)."""
    from speakup import lexicon

    entry = lexicon.entry(word)
    if entry and entry.get("ipa"):
        return len(entry["ipa"])
    return max(1, len(re.sub(r"[^a-z]", "", word.lower())))


def _padded(start: float, end: float, duration: float, method: str) -> Selection:
    return Selection(round(max(0.0, start - PAD), 3), round(min(duration, end + PAD), 3), method)


def _whole(duration: float) -> Selection:
    return Selection(0.0, round(duration, 3), "whole")


def word_span(x: np.ndarray, rate: int) -> Selection:
    duration = len(x) / rate
    found = _stretches(x, rate, WORD_JOIN)
    if not found:
        return _whole(duration)
    words = [s for s in found if s[2] >= WORD_VOICED and s[3] >= -WORD_DB]
    a, b = words[0][:2] if words else max(found, key=lambda s: s[2])[:2]
    return _padded(a, b, duration, "word")


def phrase_span(x: np.ndarray, rate: int, words: list[str], index: int) -> Selection:
    duration = len(x) / rate
    found = stretches(x, rate, PHRASE_JOIN)
    if not found:
        return _whole(duration)
    if len(found) == len(words):
        a, b = found[index]
        return _padded(a, b, duration, "count")
    # Share the speech out by sound count, then take the stretch that best covers the target's share.
    weights = [sound_count(w) for w in words]
    first, last = found[0][0], found[-1][1]
    per = (last - first) / sum(weights)
    lo = first + per * sum(weights[:index])
    hi = lo + per * weights[index]

    def overlap(s):
        return max(0.0, min(s[1], hi) - max(s[0], lo))

    best = max(found, key=overlap)
    if overlap(best) == 0:
        return _padded(lo, hi, duration, "share")
    # A word split at a closure (the k in rocket) is two stretches: take every stretch mostly inside the share.
    inside = [s for s in found if overlap(s) >= 0.5 * (s[1] - s[0])] or [best]
    a, b = min(s[0] for s in inside), max(s[1] for s in inside)
    if b - a > 1.6 * (hi - lo):  # several words run together: keep the share, a little wider
        margin = 0.25 * (hi - lo)
        a, b = max(a, lo - margin), min(b, hi + margin)
    return _padded(a, b, duration, "share")


def pick(x: np.ndarray, rate: int, line: str, target: str, aligner: Aligner | None = None) -> Selection:
    """The target word's place in a recording of `line` (a single word, a phrase or a sentence)."""
    duration = len(x) / rate
    words = tokens(line) or [target.lower()]
    index = target_index(words, target)
    if aligner is not None and index is not None:
        span = aligner(x, rate, words, index)
        if span is not None:
            a, b = span
            return Selection(round(max(0.0, a), 3), round(min(duration, b), 3), "aligner")
    if len(words) == 1 or index is None:
        return word_span(x, rate)
    return phrase_span(x, rate, words, index)


def pick_file(path: Path, line: str, target: str, aligner: Aligner | None = None) -> Selection:
    x, rate = audio.read(path)
    return pick(x, rate, line, target, aligner)


def duration_of(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def clamp(start: float, end: float, duration: float) -> tuple[float, float]:
    """An SLP's box, kept inside the clip and at least 50 ms long. Raises ValueError for nonsense."""
    if not (np.isfinite(start) and np.isfinite(end)):
        raise ValueError("the selection needs a start and an end in seconds")
    start, end = min(start, end), max(start, end)
    start, end = max(0.0, start), min(duration, end)
    if end - start < MIN_SELECTION:
        end = min(duration, start + MIN_SELECTION)
        start = max(0.0, end - MIN_SELECTION)
    return round(start, 3), round(end, 3)


def crop(src: Path, dst: Path, start: float, end: float) -> None:
    """Write src[start:end] to dst at the same rate. Standard library only."""
    with wave.open(str(src), "rb") as r:
        params = r.getparams()
        rate = r.getframerate()
        first = max(0, int(round(start * rate)))
        last = min(r.getnframes(), int(round(end * rate)))
        r.setpos(min(first, r.getnframes()))
        data = r.readframes(max(0, last - first))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dst), "wb") as w:
        w.setparams(params)
        w.writeframes(data)


def peaks(path: Path, columns: int = 600) -> tuple[float, list[float]]:
    """The clip's length and its waveform as `columns` peak values (0 to 1), for the selection box."""
    x, rate = audio.read(path)
    duration = len(x) / rate if rate else 0.0
    if len(x) == 0:
        return duration, []
    columns = min(columns, len(x))
    edges = np.linspace(0, len(x), columns + 1).astype(int)
    top = float(np.max(np.abs(x))) or 1.0
    return duration, [round(float(np.max(np.abs(x[a:b]))) / top, 3) if b > a else 0.0
                      for a, b in zip(edges[:-1], edges[1:])]
