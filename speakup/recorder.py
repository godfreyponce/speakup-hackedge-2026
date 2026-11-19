"""Records one clip on the board's mic (#5). The browser never touches the mic: plain http can't ask for it."""

import signal
import subprocess
import threading
from pathlib import Path


class RecorderError(Exception):
    pass


class Stoppable:
    """The SLP's Stop button (Nov 4): `request_stop()`, called from another thread, ends the recording that
    is running at its next 20 ms frame and keeps what was recorded. Each recording starts with the flag clear."""

    def __init__(self):
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def _begin(self) -> None:
        self._stop.clear()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()


class FakeRecorder(Stoppable):
    """For a laptop with no board: the fake model ignores the audio anyway."""

    def __init__(self, seconds: float = 0, sample: Path | None = None):
        super().__init__()
        self.seconds = seconds  # the lab copy waits like the real mic, so the child screen's listening state shows
        self.sample = sample  # a WAV to hand back as the first "recording", to try the sound analysis on a laptop

    def record(self, path: Path) -> None:
        self._begin()
        self._stop.wait(self.seconds)  # Stop ends the wait early, as it ends a real recording
        if self.sample is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(self.sample.read_bytes())
            self.sample = None  # only the first word: the clip says "rabbit", so later words get no clip


# 48 kHz (Nov 4): children's /s/ reaches 7 to 9 kHz, beyond a 16 kHz recording's 8 kHz limit. Arti and the
# trackers still get 16 kHz, made by speakup/audio.py.
CAPTURE_RATE = 48000
HIGH_PASS_HZ = 150  # the board's USB mic hums at 60 Hz and its harmonics, 90 to 99% of the room's noise (Nov 11)


def dehum(data: bytes, rate: int) -> bytes:
    """The clip with everything under 150 Hz taken out: the hum drops 11 dB, the voice 1 dB (a child's voice starts
    at 200 Hz; a man's keeps its harmonics). Unchanged without numpy."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        return data
    x = np.frombuffer(data, dtype="<i2").astype(np.float64)
    if len(x) < rate // 10:
        return data
    spec = np.fft.rfft(x - x.mean())
    hz = np.fft.rfftfreq(len(x), 1 / rate)
    spec *= 1 / np.sqrt(1 + (HIGH_PASS_HZ / np.maximum(hz, 1e-3)) ** 8)  # 4th-order Butterworth response
    y = np.fft.irfft(spec, len(x))
    return np.clip(np.round(y), -32768, 32767).astype("<i2").tobytes()


def frame_peak(samples) -> int:
    """A frame's loudest point above about 200 Hz, so the hum never counts as a voice. Plain peak without numpy."""
    try:
        import numpy as np
    except ImportError:  # pragma: no cover
        np = None
    if np is None or len(samples) < 64:  # too short to filter: the plain peak
        return max(max(samples), -min(samples))
    x = np.asarray(samples, dtype=np.float64)
    spec = np.fft.rfft(x * np.hanning(len(x)))
    spec[: max(1, round(200 * len(x) / CAPTURE_RATE)) + 1] = 0
    return int(np.abs(np.fft.irfft(spec, len(x))).max())


class ArecordRecorder(Stoppable):
    def __init__(self, seconds: int, device: str | None = None, command: str = "arecord", rate: int = CAPTURE_RATE):
        super().__init__()
        self.seconds = seconds
        self.device = device
        self.command = command
        self.rate = rate
        self.live: Gate | None = None  # the gate of the recording in progress

    def record(self, path: Path) -> None:
        self._begin()
        path.parent.mkdir(parents=True, exist_ok=True)
        args = [self.command, "-q", "-t", "wav", "-f", "S16_LE", "-r", str(self.rate), "-c", "1", "-d", str(self.seconds)]
        if self.device:
            args += ["-D", self.device]
        args.append(str(path))
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        except FileNotFoundError as e:
            raise RecorderError(f"{self.command} not found") from e
        stopped = False
        while proc.poll() is None:
            if self.stopping and not stopped:
                # arecord finishes the WAV properly on Ctrl+C, so the clip so far is kept.
                proc.send_signal(signal.SIGINT)
                stopped = True
            try:
                proc.wait(timeout=0.02)
            except subprocess.TimeoutExpired:
                pass
        _, err = proc.communicate()
        if proc.returncode != 0 and not stopped:
            raise RecorderError(err.strip() or f"{self.command} exited with {proc.returncode}")


class Gate:
    """Decides, 20 ms at a time, when a voice starts and when it has finished (lab, Nov 4).

    The room sets the bar: the first 0.3 s are taken as background, and a voice must peak above both
    `start_peak` (300 on the board, of 32,767, measured above 200 Hz) and 3x the background. Once a voice has
    started, `trailing` seconds under `quiet_bar` (twice the room) end the clip. Small noises never start it.

    Nov 4 (owner): the whole utterance is recorded, a phrase or a sentence with its pauses, so the quiet that
    ends it is 2 s (was 0.7 s, then 3 s; the owner's range was 2 to 6 s) and the longest recording is 30 s. The SLP can
    also press Stop at any time. The kept clip ends `tail` after the last loud frame, not after the 2 s of
    quiet, so the SLP's waveform is not mostly silence."""

    FRAME = 0.02

    def __init__(self, start_peak: int = 2000, trailing: float = 2.0, wait: float = 120.0, longest: float = 30.0,
                 lead: float = 0.3, calibrate: float = 0.3, tail: float = 0.4):
        self.start_peak = start_peak
        self.trailing = trailing
        # Give up if nobody speaks in this long. A child may need a while (Nov 12: the kid screen asks again every
        # 8 s instead), so this is only a safety net for a board left recording; the SLP can press Stop any time.
        self.wait = wait
        self.longest = longest  # cut the clip at this length after the voice starts
        self.lead = lead  # keep this much before the voice starts, so a soft first sound is not lost
        self.calibrate = calibrate
        self.tail = tail  # quiet kept after the last loud frame
        self.frames = 0
        self.noise: list[int] = []
        self.started_at: int | None = None  # frame index where the voice started
        self.last_loud: int | None = None  # frame count at the last loud frame
        self.quiet = 0
        self.loudest = 0  # the loudest frame before a voice started, to say why nothing was heard

    @property
    def heard(self) -> bool:
        """A voice has started in this recording."""
        return self.started_at is not None

    @property
    def floor(self) -> float:
        # The quieter quarter of the calibration: a child who speaks right away must not count as the room.
        return sorted(self.noise)[len(self.noise) // 4] if self.noise else 0

    @property
    def bar(self) -> float:
        return max(self.start_peak, 3 * self.floor)

    @property
    def quiet_bar(self) -> float:
        """Under this the voice has stopped: twice the room, so room noise alone never keeps a clip going."""
        return max(self.start_peak / 2, 2 * self.floor)

    def feed(self, peak: int) -> str:
        """One frame's peak in; out: "waiting", "voice", "done" (voice ended) or "silent" (nobody spoke)."""
        self.frames += 1
        seconds = self.frames * self.FRAME
        if self.started_at is None:
            if seconds <= self.calibrate:
                self.noise.append(peak)
                return "waiting"
            self.loudest = max(self.loudest, peak)
            if peak >= self.bar:
                self.started_at = self.frames - 1
                self.last_loud = self.frames
                return "voice"
            return "silent" if seconds >= self.wait else "waiting"
        self.quiet = self.quiet + 1 if peak < self.quiet_bar else 0
        if self.quiet == 0:
            self.last_loud = self.frames
        # Whole frames, so float rounding never ends the clip one frame early.
        if self.quiet >= round(self.trailing / self.FRAME) or self.frames - self.started_at >= round(self.longest / self.FRAME):
            return "done"
        return "voice"

    def keep(self) -> tuple[int, int]:
        """The frames to keep: a little before the voice, up to a little after its last loud frame.
        Before any voice (the SLP pressed Stop on a quiet clip) everything after the calibration is kept."""
        if self.started_at is None:
            return min(self.frames, round(self.calibrate / self.FRAME)), self.frames
        first = max(0, self.started_at - round(self.lead / self.FRAME))
        last = min(self.frames, (self.last_loud or self.frames) + round(self.tail / self.FRAME))
        return first, last


def run_gate(gate: Gate, read, size: int, stopping, frames: list[bytes]) -> str:
    """Feed `size`-byte chunks from `read()` through the gate into `frames` until it says "done" or
    "silent", the SLP presses Stop ("stopped": the frames so far are kept) or the stream ends ("broken")."""
    from array import array

    state = "waiting"
    while state in ("waiting", "voice"):
        if stopping():
            return "stopped"
        chunk = read()
        if len(chunk) < size:
            return "broken"
        frames.append(chunk)
        samples = array("h", chunk)
        state = gate.feed(frame_peak(samples))
    return state


# Shortest clip worth keeping when the SLP presses Stop: under this there is nothing to score.
MIN_KEEP_SECONDS = 0.2


class VoiceRecorder(Stoppable):
    """The board's mic, voice-activated: listens until the child speaks and stops 2 s after they finish, or
    when the SLP presses Stop. arecord streams raw mono (48 kHz) to us; nothing is written until the end."""

    def __init__(self, device: str | None = None, command: str = "arecord", gate: dict | None = None,
                 rate: int = CAPTURE_RATE):
        super().__init__()
        self.device = device
        self.command = command
        self.gate = gate or {}
        self.rate = rate
        self.live: Gate | None = None  # the gate of the recording in progress

    def record(self, path: Path) -> None:
        import wave

        self._begin()
        path.parent.mkdir(parents=True, exist_ok=True)
        args = [self.command, "-q", "-t", "raw", "-f", "S16_LE", "-r", str(self.rate), "-c", "1"]
        if self.device:
            args += ["-D", self.device]
        try:
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError as e:
            raise RecorderError(f"{self.command} not found") from e
        gate = self.live = Gate(**self.gate)  # the child screen reads live.heard
        size = int(self.rate * Gate.FRAME) * 2
        frames: list[bytes] = []
        try:
            state = run_gate(gate, lambda: proc.stdout.read(size), size, lambda: self.stopping, frames)
            if state == "broken":
                err = proc.stderr.read().decode(errors="replace").strip()
                raise RecorderError(err or f"{self.command} stopped")
        finally:
            proc.kill()
            proc.wait()
        if state == "silent":
            raise RecorderError(f"No voice heard in {gate.wait:.0f} s (loudest sound {gate.loudest:,}, a voice needs {round(gate.bar):,}). "
                                "Bring the mic closer to the child and press Record again.")
        first, last = gate.keep()
        if (last - first) * Gate.FRAME < MIN_KEEP_SECONDS:
            raise RecorderError("Stopped before anything was recorded. Press Record and have the child say it again.")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.rate)
            w.writeframes(b"".join(frames[first:last]))  # raw: Arti was trained on unfiltered audio (Nov 12)
