"""Reading recordings at the rate they were made, and bringing them down to 16 kHz for Arti and the trackers.

The mic records at 48 kHz (Nov 4): children's /s/ centres at 6.4 to 7.7 kHz and can peak above 9 kHz (Todd,
Edwards and Litovsky 2011; Wong and Munson 2025), and 16 kHz holds nothing above 8 kHz. Arti was trained on
16 kHz audio and the formant and pitch trackers are tuned for it, so they get a 16 kHz copy made here; the
spectrogram uses the full recording.

Downsampling: a Kaiser-windowed sinc low-pass just under the new Nyquist (as torchaudio's resampler, which
made Arti's training audio, does), then every q-th sample when the rate is a multiple of 16 kHz. Other rates
(44.1 kHz) are low-passed and then interpolated, which is close enough for a lab clip.
"""

import wave
from pathlib import Path

import numpy as np

TARGET = 16000
CUTOFF = 7600.0  # Hz: passband edge below the 8 kHz Nyquist of the 16 kHz copy
TAPS_PER_FACTOR = 64
KAISER_BETA = 8.6  # about 90 dB stopband


def read(path: Path) -> tuple[np.ndarray, int]:
    """The samples as floats in -1..1, and the rate. 16-bit mono only."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError(f"{Path(path).name}: needs a 16-bit mono WAV")
        rate = w.getframerate()
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, dtype="<i2").astype(np.float64) / 32768.0, rate


def lowpass(rate: int, cutoff: float = CUTOFF) -> np.ndarray:
    q = max(1, round(rate / TARGET))
    n = TAPS_PER_FACTOR * q + 1
    t = np.arange(n) - (n - 1) / 2
    h = 2 * cutoff / rate * np.sinc(2 * cutoff / rate * t) * np.kaiser(n, KAISER_BETA)
    return h / h.sum()


def to_16k(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == TARGET or len(x) == 0:
        return x
    if rate < TARGET:
        raise ValueError(f"recording at {rate} Hz is below 16 kHz")
    y = np.convolve(x, lowpass(rate), mode="same")
    if rate % TARGET == 0:
        return y[::rate // TARGET].copy()
    n = int(len(x) * TARGET / rate)
    return np.interp(np.arange(n) * rate / TARGET, np.arange(len(y)), y)


def read_16k(path: Path) -> np.ndarray:
    x, rate = read(path)
    return to_16k(x, rate)


def int16(x: np.ndarray) -> list[int]:
    return np.clip(np.round(x * 32768.0), -32768, 32767).astype(np.int16).tolist()
