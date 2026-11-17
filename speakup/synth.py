"""A small Klatt-style formant synthesizer, written for Speak Up in numpy (no other dependency).

It makes the computer-made sound pictures in the sound book: speech "recreated digitally from knowing how the sounds
work", never a recording of anyone. The design follows Klatt (1980, J. Acoust. Soc. Am. 67, 971-995) and Klatt and
Klatt (1990, J. Acoust. Soc. Am. 87, 820-857), simplified:

- Voicing source: an impulse train at F0 through a low-pass glottal resonator (Klatt's RGP, 0 Hz, 100 Hz bandwidth),
  which gives the usual -12 dB per octave source slope; aspiration noise is added for /h/ and for the voice onset
  time (VOT) of /p t k/.
- Cascade branch (vowels, approximants, nasals): a nasal pole-zero pair, then formant resonators F1 to F5 in series.
  When the nasal pole and zero sit at the same frequency they cancel (an oral sound); moving them apart nasalizes.
- Parallel branch (fricatives, bursts): noise through resonators whose frequencies, bandwidths and levels are given
  per sound, plus a flat bypass path. In voiced fricatives the noise is pulsed by the voicing, as in Klatt (1980).
- Radiation at the lips: a first difference on the cascade output (+6 dB per octave).

Parameters are given as segments (one sound each: duration, formant targets, source levels); the tracks between
segments are straight-line transitions, updated every millisecond. Everything is deterministic: the noise comes from
a fixed seed, so the same plan always gives the same samples."""

from dataclasses import dataclass, field

import numpy as np

RATE = 48000
STEP = RATE // 1000  # parameters are updated every 1 ms
OFF = -120.0  # dB value that means "this source is off"


@dataclass
class Seg:
    """One sound in a plan. Levels are in dB (relative, about 60 = a full vowel); OFF means silent."""
    name: str
    ms: float
    F: tuple  # F1..F5 targets, Hz
    B: tuple = (80, 100, 140, 250, 300)  # bandwidths, Hz
    av: float = OFF  # voicing
    ah: float = OFF  # aspiration (into the cascade, shaped by the formants)
    af: float = OFF  # frication (parallel branch)
    fric: tuple = ()  # parallel resonators: (Hz, bandwidth Hz, dB) each
    bypass: float = OFF  # flat noise path in the parallel branch, dB
    nasal: tuple = (270, 100, 270, 100)  # nasal pole Hz, bandwidth, nasal zero Hz, bandwidth (equal = no nasality)
    trans: float = 40  # ms of formant movement at the boundary into this segment
    lead: float = 0.0  # share of that transition placed before the boundary (0 = all inside this segment)
    ramp: float = 6  # ms of level change at the boundary into this segment (0 = abrupt, as a burst)
    label: str = ""  # what to call it on the picture ("" = the name)
    focus: bool = False  # the sound the picture is about: its targets are marked


@dataclass
class Plan:
    segs: list
    f0: float  # mean F0, Hz
    f0_start: float = 1.06  # declining contour: F0 at the start and end as shares of the mean
    f0_end: float = 0.88
    seed: int = 1
    pad_ms: float = 60  # silence before and after
    tilt: float = 0.0  # extra source tilt (dB per octave above 1 kHz, negative = steeper); breathy child voices
    meta: dict = field(default_factory=dict)

    def bounds(self) -> list[tuple[float, float]]:
        """Start and end time (s, from the start of the sound file) of every segment."""
        out, t = [], self.pad_ms / 1000
        for s in self.segs:
            out.append((t, t + s.ms / 1000))
            t += s.ms / 1000
        return out

    @property
    def seconds(self) -> float:
        return (sum(s.ms for s in self.segs) + 2 * self.pad_ms) / 1000


def _tracks(plan: Plan) -> dict[str, np.ndarray]:
    """Per-millisecond parameter tracks from the segments, with straight-line transitions."""
    pad = int(round(plan.pad_ms))
    edges = [pad]
    for s in plan.segs:
        edges.append(edges[-1] + int(round(s.ms)))
    n = edges[-1] + pad
    tr: dict[str, np.ndarray] = {}

    def step(get, fill):
        a = np.full(n, fill, dtype=float)
        for s, a0, a1 in zip(plan.segs, edges[:-1], edges[1:]):
            a[a0:a1] = get(s)
        a[:edges[0]] = get(plan.segs[0]) if fill is None else fill
        a[edges[-1]:] = get(plan.segs[-1]) if fill is None else fill
        return a

    for i in range(5):
        a = step(lambda s, i=i: s.F[i], None)
        b = step(lambda s, i=i: s.B[i], None)
        for k in range(1, len(plan.segs)):
            s, e = plan.segs[k], edges[k]
            T = int(round(s.trans))
            if T <= 0:
                continue
            lo, hi = max(0, e - int(round(T * s.lead))), min(n, e + T - int(round(T * s.lead)))
            if hi - lo > 1:
                for arr in (a, b):
                    v0, v1 = arr[lo - 1] if lo > 0 else arr[lo], arr[min(hi, n - 1)]
                    arr[lo:hi] = np.linspace(v0, v1, hi - lo, endpoint=False)
        tr[f"F{i + 1}"], tr[f"B{i + 1}"] = a, b
    for j, key in enumerate(("fnp", "bnp", "fnz", "bnz")):
        tr[key] = step(lambda s, j=j: s.nasal[j], None)
    for key in ("av", "ah", "af", "bypass"):
        lin = step(lambda s, key=key: 10 ** (getattr(s, key) / 20) if getattr(s, key) > OFF else 0.0, 0.0)
        for k in range(len(plan.segs)):
            s, e = plan.segs[k], edges[k]
            R = int(round(s.ramp))
            if R > 0 and 0 < e < n:
                lo, hi = max(0, e - R // 2), min(n, e + R - R // 2)
                lin[lo:hi] = np.linspace(lin[lo - 1] if lo else 0.0, lin[min(hi, n - 1)], hi - lo, endpoint=False)
        end = edges[-1]
        lin[end - 12:end] *= np.linspace(1, 0, 12)  # fade out at the end of the last sound
        tr[key] = lin
    # The frication resonators of each segment: up to 6, (Hz, bandwidth, linear gain); unused ones are silent.
    fr = np.zeros((n, 6, 3))
    fr[:, :, 0], fr[:, :, 1] = 1000.0, 1000.0
    for s, a0, a1 in zip(plan.segs, edges[:-1], edges[1:]):
        for r, (hz, bw, db) in enumerate(s.fric[:6]):
            fr[a0:a1, r] = (hz, bw, 10 ** (db / 20))
    tr["fric"] = fr
    t = np.linspace(0, 1, n)
    tr["f0"] = plan.f0 * np.exp(np.log(plan.f0_start) + (np.log(plan.f0_end) - np.log(plan.f0_start)) * t)
    tr["n"] = np.array([n])
    return tr


def _coefs(f: np.ndarray, bw: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Klatt's resonator coefficients A, B, C for frequency and bandwidth arrays."""
    T = 1.0 / RATE
    C = -np.exp(-2 * np.pi * bw * T)
    B = 2 * np.exp(-np.pi * bw * T) * np.cos(2 * np.pi * f * T)
    return 1 - B - C, B, C


def _resonate(x: np.ndarray, f: np.ndarray, bw: np.ndarray, anti: bool = False, peak: bool = False) -> np.ndarray:
    """Time-varying 2-pole resonator (or 2-zero antiresonator), coefficients held for each 1 ms block.
    peak: scale to a gain of 1 at the resonance (the parallel branch), instead of Klatt's gain of 1 at 0 Hz."""
    fs, bs = np.repeat(f, STEP)[:len(x)], np.repeat(bw, STEP)[:len(x)]
    A, B, C = _coefs(fs, bs)
    if peak:
        z = np.exp(-2j * np.pi * fs / RATE)
        A = A / np.abs(A / (1 - B * z - C * z * z))
    y = np.zeros_like(x)
    if anti:  # y[n] = x[n]/A - B/A x[n-1] - C/A x[n-2]
        x1 = np.concatenate(([0.0], x[:-1]))
        x2 = np.concatenate(([0.0, 0.0], x[:-2]))
        return (x - B * x1 - C * x2) / A
    y1 = y2 = 0.0
    a, b, c = A.tolist(), B.tolist(), C.tolist()
    xs = x.tolist()
    out = [0.0] * len(xs)
    for i, v in enumerate(xs):
        y0 = a[i] * v + b[i] * y1 + c[i] * y2
        out[i] = y0
        y2, y1 = y1, y0
    return np.array(out)


def synthesize(plan: Plan) -> np.ndarray:
    """The plan as samples at RATE, floats with the loudest sample at 0.5."""
    tr = _tracks(plan)
    n_ms = int(tr["n"][0])
    n = n_ms * STEP
    rng = np.random.default_rng(plan.seed)
    up = lambda a: np.repeat(a, STEP)[:n]  # noqa: E731
    # Voicing: one impulse per glottal period, placed by integrating F0.
    f0 = up(tr["f0"])
    phase = np.cumsum(f0) / RATE
    pulses = np.zeros(n)
    pulses[1:][np.floor(phase[1:]) > np.floor(phase[:-1])] = 1.0
    glottal = _resonate(pulses, np.zeros(n_ms), np.full(n_ms, 100.0))
    glottal = _resonate(glottal, np.zeros(n_ms), np.full(n_ms, 200.0)) if plan.tilt < 0 else glottal
    in_period = np.mod(phase, 1.0)  # 0..1 inside each glottal period
    noise = rng.standard_normal(n)
    av, ah, af, byp = up(tr["av"]), up(tr["ah"]), up(tr["af"]), up(tr["bypass"])
    # Radiation at the lips (+6 dB per octave) is a first difference. The system is linear, so it is taken on the
    # glottal wave before the voicing level is applied: the wave's steady part then never reaches the resonators, and
    # switching the voicing on or off gives no low-frequency thump.
    dglottal = np.append(0.0, np.diff(glottal)) / (np.max(np.abs(glottal)) + 1e-12)
    asp = np.convolve(noise, [0.5, 0.0, -0.5], mode="same")  # aspiration with the radiation slope too
    source = av * dglottal + ah * asp * 0.02
    # Cascade: nasal zero and pole, then F1..F5 (the high formants first, as in Klatt's cascade).
    y = _resonate(source, tr["fnz"], tr["bnz"], anti=True)
    y = _resonate(y, tr["fnp"], tr["bnp"])
    for i in (5, 4, 3, 2, 1):
        y = _resonate(y, tr[f"F{i}"], tr[f"B{i}"])
    # Parallel branch: noise, pulsed by the voicing in voiced fricatives (stronger in the open half of each period).
    voiced_now = av > 0
    pulse_mod = np.where(voiced_now, np.where(in_period < 0.5, 1.0, 0.35), 1.0)
    fnoise = rng.standard_normal(n) * pulse_mod * af
    par = byp * fnoise
    fr = tr["fric"]
    for r in range(fr.shape[1]):
        gain = up(fr[:, r, 2])
        if not gain.any():
            continue
        # Each parallel resonance is applied twice (4 poles): the noise then falls off steeply away from its peak,
        # as a fricative's does below its front-cavity resonance. The bandwidth is widened to keep the -3 dB width.
        out = fnoise
        for _ in range(2):
            out = _resonate(out, fr[:, r, 0], fr[:, r, 1] * 1.55, peak=True)
        par = par + (-1) ** r * gain * out
    x = y * 0.05 + par * 0.0011  # balanced so /s/ is about 5 dB below the vowel /ɑ/
    peak = np.max(np.abs(x))
    return x * (0.5 / peak) if peak > 0 else x


def wav_bytes(x: np.ndarray, rate: int = RATE) -> bytes:
    """16-bit mono WAV file bytes."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()
