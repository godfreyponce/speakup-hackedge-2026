"""The /s/ check: measured, not trained (no public child data marks /s/ errors yet).

Two measures, from a UTD speech scientist who studies children's /s/ (docs/research/s-sound.md):
- spread (the square root of the second spectral moment, m2): a clear /s/ concentrates its noise; a frontal lisp
  ("thun" for "sun") spreads it like a "th";
- peak: the strongest frequency from 3 kHz up (to 9 kHz when the recording has it): an /s/ peaks higher than a
  "sh" ("shun" for "sun").
There is no fixed cutoff for either, because the values depend on the size of the child's vocal tract. So the
child's /s/ is compared with the same child's own "sh" and "th" from the same session. "th" is the
weakest of the three, so the references work best held for a second ("shhhh", "thhhh"), as SLPs often ask. The ratios below are a
starting point, not calibrated on rated recordings: the screen says so and the SLP listens.

The app records at 48 kHz by default, which covers the whole 3 to 9 kHz range; a 16 kHz clip stops at 8 kHz.

    python -m speakup.sibilant sun.wav --sh shoe.wav --th thumb.wav
"""

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from speakup import audio

FRAME = 0.01  # s
LOW_HZ = 1000.0  # moments are taken from here up: below it is voicing and room noise
PEAK_LOW_HZ, PEAK_HIGH_HZ = 3000.0, 9000.0
HIGH_SHARE = 0.45  # a frame is frication when this share of its energy is above 2.5 kHz
MIN_SECONDS = 0.04
SH_RATIO = 1.25  # an /s/ peak should sit at least 25% above the child's own "sh" peak
TH_RATIO = 0.8  # an /s/ spread should be at most 80% of the child's own "th" spread


@dataclass(frozen=True)
class Fricative:
    seconds: float
    centre_hz: float  # m1, the centre of gravity
    spread_hz: float  # sqrt(m2)
    peak_hz: float
    top_hz: float  # highest frequency the recording has


def measure(path: Path | str) -> Fricative | None:
    """The longest stretch of frication in the clip, or None when there is none."""
    x, rate = audio.read(Path(path))
    n = int(FRAME * rate)
    if len(x) < 4 * n:
        return None
    frames = np.lib.stride_tricks.sliding_window_view(x, n)[::n] * np.hanning(n)
    spec = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(n, 1 / rate)
    total = spec.sum(axis=1) + 1e-12
    loud = total > 0.01 * total.max()  # "th" is weak: keep frames down to 1% of the loudest
    hiss = spec[:, freqs >= 2500].sum(axis=1) / total > HIGH_SHARE
    run = _longest(loud & hiss)
    if run is None or (run[1] - run[0]) * FRAME < MIN_SECONDS:
        return None
    a, b = run
    keep = slice(a + (b - a) // 4, b - (b - a) // 4 or b)  # the steady middle half
    s = slice(int(keep.start * n), int(keep.stop * n))
    seg = x[s]
    nfft = 1 << int(np.ceil(np.log2(max(len(seg), 2 * n))))
    p = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nfft)) ** 2
    f = np.fft.rfftfreq(nfft, 1 / rate)
    band = f >= LOW_HZ
    pb, fb = p[band] / p[band].sum(), f[band]
    centre = float((fb * pb).sum())
    spread = float(np.sqrt(((fb - centre) ** 2 * pb).sum()))
    smooth = np.convolve(p, np.ones(9) / 9, mode="same")
    peak_band = (f >= PEAK_LOW_HZ) & (f <= PEAK_HIGH_HZ)
    peak = float(f[peak_band][np.argmax(smooth[peak_band])])
    return Fricative(seconds=(b - a) * FRAME, centre_hz=centre, spread_hz=spread, peak_hz=peak, top_hz=rate / 2)


def _longest(mask: np.ndarray) -> tuple[int, int] | None:
    best, start = None, None
    for i, on in enumerate(np.append(mask, False)):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def compare(s: Fricative, sh: Fricative | None = None, th: Fricative | None = None) -> list[tuple[str, bool]]:
    """(sentence, looks like a good /s/) per comparison the session has a reference for."""
    out = []
    if sh is not None:
        ok = s.peak_hz >= SH_RATIO * sh.peak_hz
        out.append((f"/s/ peak {s.peak_hz / 1000:.1f} kHz vs this child's \"sh\" {sh.peak_hz / 1000:.1f} kHz: "
                    + ("clearly higher, as an /s/ should be." if ok else "close to the \"sh\", so it may sound like \"sh\"."), ok))
    if th is not None:
        ok = s.spread_hz <= TH_RATIO * th.spread_hz
        out.append((f"/s/ spread {s.spread_hz / 1000:.1f} kHz vs this child's \"th\" {th.spread_hz / 1000:.1f} kHz: "
                    + ("more focused, as an /s/ should be." if ok else "as spread as the \"th\", so it may be a frontal lisp."), ok))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description="Measure a child's /s/ against the same child's own \"sh\" and \"th\".")
    p.add_argument("s_wav", type=Path)
    p.add_argument("--sh", type=Path, help="the same child holding \"shhhh\" for a second (or a word such as shoe)")
    p.add_argument("--th", type=Path, help="the same child holding \"thhhh\" for a second (a word such as thumb can be too weak)")
    args = p.parse_args(argv)
    found = {k: measure(v) for k, v in (("s", args.s_wav), ("sh", args.sh), ("th", args.th)) if v}
    for k, v in found.items():
        print(f"{k}: " + ("no frication found" if v is None else
                          f"{v.seconds:.2f} s, centre {v.centre_hz:,.0f} Hz, spread {v.spread_hz:,.0f} Hz, "
                          f"peak {v.peak_hz:,.0f} Hz (recording reaches {v.top_hz:,.0f} Hz)"))
    if found.get("s") is None:
        return 1
    for line, ok in compare(found["s"], found.get("sh"), found.get("th")):
        print(("OK    " if ok else "CHECK ") + line)
    print("Measured, not trained, and not calibrated on rated recordings: the SLP listens and decides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
