"""Checks one recorded clip before anyone trusts Arti's answer on it: is there speech, is it loud enough,
is it clipped, and does the speech run into either edge of the clip (a word cut off by the recording window).
The SLP sees the problems in plain words and can record again. Standard library only, so it runs on the board."""

import math
import sys
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path

FRAME_SECONDS = 0.02  # 20 ms frames, the usual size for speech energy
FULL_SCALE = 32767
QUIET_PEAK = 800  # below this the word is too quiet to judge; a child 2 ft from the mic peaks at 1,000 to 2,000
CLIPPED_LEVEL = 32000
CLIPPED_SHARE = 0.001  # more than 0.1% of samples at full scale means the sound is distorted
MIN_SPEECH_SECONDS = 0.15  # a short word like "car" is still longer than this
SPEECH_FLOOR = 100  # frame loudness (RMS) that always counts as silence on a 16-bit clip
EDGE_FRAMES = 2  # speech in the first or last 40 ms means the word may be cut off


@dataclass(frozen=True)
class ClipCheck:
    seconds: float
    peak: int
    speech_seconds: float
    clipped_share: float
    problems: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.problems


def check_clip(path: Path) -> ClipCheck:
    """Read a 16-bit mono WAV and say what is wrong with it, if anything."""
    try:
        with wave.open(str(path), "rb") as w:
            if w.getsampwidth() != 2 or w.getnchannels() != 1:
                return ClipCheck(0.0, 0, 0.0, 0.0, ("Not a 16-bit mono WAV, so it cannot be checked.",))
            rate = w.getframerate()
            samples = array("h", w.readframes(w.getnframes()))
    except (OSError, wave.Error, EOFError) as e:
        return ClipCheck(0.0, 0, 0.0, 0.0, (f"The clip could not be read: {e}.",))
    if sys.byteorder == "big":
        samples.byteswap()  # WAV is little-endian
    if not samples:
        return ClipCheck(0.0, 0, 0.0, 0.0, ("The clip is empty.",))

    seconds = len(samples) / rate
    peak = max(abs(min(samples)), max(samples))
    clipped_share = sum(1 for s in samples if abs(s) >= CLIPPED_LEVEL) / len(samples)

    step = max(1, int(rate * FRAME_SECONDS))
    energy = [
        math.sqrt(sum(s * s for s in samples[i:i + step]) / len(samples[i:i + step]))
        for i in range(0, len(samples), step)
    ]
    # Background noise is the quiet end of the clip's frames; speech stands well above it.
    noise = sorted(energy)[len(energy) // 5]
    threshold = max(SPEECH_FLOOR, noise * 2)  # 6 dB over the room: far from the mic, speech is only 10 to 15 dB over
    speech = [e > threshold for e in energy]
    speech_seconds = sum(speech) * step / rate

    problems = []
    if speech_seconds < MIN_SPEECH_SECONDS:
        problems.append("No speech heard: check the mic and record again.")
    elif peak < QUIET_PEAK:
        problems.append(f"Too quiet (peak {peak} of {FULL_SCALE}): bring the mic closer and record again.")
    if clipped_share > CLIPPED_SHARE:
        problems.append("Too loud: the sound is clipped. Move the mic back a little and record again.")
    if speech_seconds >= MIN_SPEECH_SECONDS:
        if any(speech[:EDGE_FRAMES]):
            problems.append("Speech at the very start: the beginning of the word may be cut off.")
        if any(speech[-EDGE_FRAMES:]):
            problems.append("Speech runs to the end of the clip: the end of the word may be cut off.")
    return ClipCheck(round(seconds, 2), peak, round(speech_seconds, 2), clipped_share, tuple(problems))
