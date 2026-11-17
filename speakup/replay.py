"""--replay (#40): the demo's backup when the mic or the room fails. Each recording is the next saved clip for the
word on screen, from a folder whose manifest.csv maps clip file to word, and the real Arti scores it live.
The clips stay outside git: they are recordings, even de-identified."""

import csv
import shutil
import wave
from pathlib import Path

from speakup.arti import RATE
from speakup.recorder import RecorderError, Stoppable

MANIFEST = "manifest.csv"


class ReplayError(Exception):
    pass


def _check_clip(path: Path) -> None:
    """The clip opens as a WAV Arti can read: mono, 16-bit, 16 kHz or faster (speakup/arti.py's read_wav)."""
    try:
        with wave.open(str(path), "rb") as w:
            rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
    except (OSError, wave.Error, EOFError) as e:
        raise ReplayError(f"{path.name} can't be read as a WAV file ({e})") from e
    if (channels, width) != (1, 2) or rate < RATE:
        raise ReplayError(f"{path.name}: Arti needs mono 16-bit at {RATE} Hz or faster, "
                          f"got {channels} channel(s), {8 * width}-bit, {rate} Hz")


def load(folder: Path, words: list[str]) -> dict[str, list[Path]]:
    """Each word's clips, in manifest order. Raises ReplayError naming what is missing or wrong."""
    if not folder.is_dir():
        raise ReplayError(f"{folder}: no folder there")
    manifest = folder / MANIFEST
    if not manifest.is_file():
        raise ReplayError(f"{manifest} is missing. Write it with the header file,word and one row per clip")
    # utf-8-sig and # comments, as in words.csv.
    try:
        with open(manifest, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(line for line in f if not line.startswith("#"))
            if reader.fieldnames is None or not {"file", "word"} <= {n.strip() for n in reader.fieldnames}:
                raise ReplayError(f"{manifest}: the first row must be the header file,word")
            rows = [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]
    except UnicodeDecodeError as e:
        raise ReplayError(f"{manifest} is not UTF-8 text. Save it as UTF-8 and start again") from e
    clips: dict[str, list[Path]] = {}
    for row in rows:
        name, word = row.get("file", ""), row.get("word", "")
        if not name or not word:
            raise ReplayError(f"{manifest}: a row needs both a file and a word")
        if word not in words:
            raise ReplayError(f"{name}: {word!r} is not in the word list ({', '.join(words)})")
        path = folder / name
        if not path.is_file():
            raise ReplayError(f"{path}: the clip is missing")
        _check_clip(path)
        clips.setdefault(word, []).append(path)
    if not clips:
        raise ReplayError(f"{manifest} lists no clips")
    return clips


class ReplayRecorder(Stoppable):
    """Stands in for the mic: the server cues the word on screen, and each recording of that word copies its next
    clip, starting over after the last. It takes as long as the clip, so the child screen shows listening."""

    def __init__(self, folder: Path, clips: dict[str, list[Path]]):
        super().__init__()
        self.clips = clips
        self.mode = f"Replay: saved clips from {folder.resolve().name}, not the mic"
        self.rewind()
        self.word: str | None = None

    def cue(self, word: str) -> None:
        self.word = word

    def has_clip(self, word: str) -> bool:
        return word in self.clips

    def rewind(self) -> None:
        """A new session starts every word at its first clip, so each run plays the order the team practised."""
        self.turns = {word: 0 for word in self.clips}

    def record(self, path: Path) -> None:
        self._begin()
        clips = self.clips.get(self.word or "")
        if not clips:
            # Practice walks only the words with a clip (server.py), so only the word screen gets here.
            raise RecorderError(f"No replay clip for {self.word}. {MANIFEST} has clips for {', '.join(self.clips)}. "
                                "On the word screen, click one of those in the Words list.")
        clip = clips[self.turns[self.word] % len(clips)]
        self.turns[self.word] += 1
        try:
            with wave.open(str(clip), "rb") as w:
                seconds = w.getnframes() / w.getframerate()
        except (OSError, wave.Error, EOFError) as e:
            raise RecorderError(f"Replay clip {clip} can't be read: {e}") from e
        self._stop.wait(seconds)  # Stop ends the wait early; the whole clip is still kept
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(clip, path)
