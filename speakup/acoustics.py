"""Sound analysis of one clip for the SLP (lab): where the word is, a spectrogram of it, formant tracks
(F1, F2, F3), the pitch (F0) contour, and the F3-F2 distance, the acoustic measure the r research uses
(Campbell et al. 2018: normalized F3-F2 tracked clinicians' ratings of children's r best; a correct
American r pulls F3 down toward F2).

Everything here is an estimate. Formant tracking is error-prone on children's high voices, in this code
as in Praat, so the screen says so. Needs numpy, which the board's image ships (ONNX Runtime needs it too).
"""

import wave
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

RATE = 16000
FRAME = 0.02  # speech detection frames, as in clipcheck
PAD = 0.08  # seconds kept around the detected word
SPEC_WINDOW = 0.006  # 6 ms: a wideband spectrogram shows formants as bands, even for high child voices
SPEC_HOP = 0.002
SPEC_NFFT = 512
TOP_HZ = 6000  # the compact picture stops here: the formants of interest for r sit well below it
SPEC_TOP_MAX = 11000  # the full analysis shows up to here when the recording has it (children's /s/ reaches 9 kHz)
LPC_WINDOW = 0.025
LPC_HOP = 0.005
F0_MIN, F0_MAX = 75.0, 500.0  # children's voices reach 400 Hz and more
VOICING = 0.45  # normalized autocorrelation peak needed to call a frame voiced
# Plausible ranges for children's and adults' formants; a root outside its range is not that formant.
F_RANGES = ((200.0, 1300.0), (700.0, 3800.0), (1400.0, 5000.0))
MAX_BANDWIDTH = 1500.0  # real voices give broad F2/F3 peaks; the tracker prefers sharp ones instead
LPC_ORDER = 14


@dataclass
class Analysis:
    start: float  # seconds into the clip where the word starts
    end: float
    times: np.ndarray  # frame times (s, from the word start) for formants and pitch
    f0: np.ndarray  # Hz, NaN where unvoiced
    formants: np.ndarray  # shape (frames, 3): F1, F2, F3 in Hz, NaN where not found
    spec_db: np.ndarray  # shape (bins, columns), low frequencies first, 0 to spec_top Hz
    spec_seconds: float
    gap_min: float | None = None  # smallest F3-F2 in Hz over voiced frames
    gap_time: float | None = None
    at_gap: tuple[float, float, float] | None = None  # F1, F2, F3 at that moment
    f0_median: float | None = None
    window: tuple[float, float] | None = None  # part of the word (s) searched for the r's F3-F2 gap
    auto_window: tuple[float, float] | None = None  # the app's own window, kept when the SLP moves it
    notes: list[str] = field(default_factory=list)
    rms: np.ndarray = field(default_factory=lambda: np.zeros(0))  # per frame (same times), 0..1 full scale
    wave: np.ndarray = field(default_factory=lambda: np.zeros((0, 2)))  # waveform outline: (buckets, 2) min, max
    peak: float = 0.0  # loudest sample of the word, 0..1 full scale
    clip_seconds: float = 0.0  # length of the whole recording
    spec_top: float = TOP_HZ  # Hz at the top row of spec_db
    rate: int = RATE  # the recording's own sample rate (formants and pitch always use a 16 kHz copy)

    @property
    def duration(self) -> float:
        return self.end - self.start


def read(path: Path) -> np.ndarray:
    """The clip at 16 kHz (a 48 kHz recording is brought down first), floats in -1..1."""
    from speakup import audio
    return audio.read_16k(path)


def find_word(x: np.ndarray) -> tuple[int, int]:
    """Sample range of the longest stretch of speech, padded, using the same energy rule as clipcheck."""
    step = int(RATE * FRAME)
    n = len(x) // step
    if n == 0:
        return 0, len(x)
    rms = np.sqrt(np.mean(x[: n * step].reshape(n, step) ** 2, axis=1)) * 32768
    noise = np.sort(rms)[n // 5]
    speech = rms > max(300.0, noise * 3)
    best, run_start, best_span = None, None, 0
    # Bridge gaps of up to 100 ms, so a stop consonant ("ra-b-it") does not split the word.
    bridged = speech.copy()
    gap = 0
    for i in range(n):
        if speech[i]:
            if 0 < gap <= 5:
                bridged[i - gap:i] = True
            gap = 0
        else:
            gap += 1
    for i in range(n + 1):
        on = i < n and bridged[i]
        if on and run_start is None:
            run_start = i
        if not on and run_start is not None:
            if i - run_start > best_span:
                best, best_span = (run_start, i), i - run_start
            run_start = None
    if best is None:
        return 0, len(x)
    pad = int(PAD * RATE)
    return max(0, best[0] * step - pad), min(len(x), best[1] * step + pad)


def spectrogram(x: np.ndarray, rate: int = RATE, top_hz: float = TOP_HZ) -> np.ndarray:
    """Wideband spectrogram in dB, rows 0..top_hz. The window is 6 ms whatever the rate, and the FFT grows
    with the rate so the frequency spacing stays at 31.25 Hz."""
    win = int(SPEC_WINDOW * rate)
    hop = int(SPEC_HOP * rate)
    nfft = SPEC_NFFT * max(1, round(rate / RATE))
    if len(x) == 0:
        x = np.zeros(win)
    y = np.append(x[0], x[1:] - 0.95 * x[:-1])  # pre-emphasis lifts the weak high formants into view
    if len(y) < win:
        y = np.pad(y, (0, win - len(y)))
    starts = range(0, len(y) - win + 1, hop)
    frames = np.stack([y[s:s + win] * np.hanning(win) for s in starts])
    power = np.abs(np.fft.rfft(frames, nfft)) ** 2
    top = int(top_hz / (rate / nfft)) + 1
    return (10 * np.log10(power[:, :top] + 1e-12)).T


def _lpc(frame: np.ndarray, order: int) -> np.ndarray:
    r = np.correlate(frame, frame, "full")[len(frame) - 1:len(frame) + order]
    if r[0] <= 0:
        return np.zeros(order + 1)
    a = np.zeros(order + 1)
    a[0], err = 1.0, r[0]
    for i in range(1, order + 1):  # Levinson-Durbin
        k = -(r[i] + np.dot(a[1:i], r[i - 1:0:-1])) / err
        a[1:i] = a[1:i] + k * a[i - 1:0:-1]
        a[i] = k
        err *= 1 - k * k
        if err <= 0:
            break
    return a


def candidates(frame: np.ndarray, order: int = LPC_ORDER) -> list[tuple[float, float]]:
    """(frequency, bandwidth) of each resonance in one frame, from the LPC polynomial's roots, low to high."""
    a = _lpc(frame * np.hamming(len(frame)), order)
    if not a.any():
        return []
    roots = np.roots(a)
    roots = roots[np.imag(roots) > 0]
    freqs = np.angle(roots) * RATE / (2 * np.pi)
    bws = -np.log(np.abs(roots)) * RATE / np.pi
    return sorted((float(f), float(bw)) for f, bw in zip(freqs, bws) if bw < MAX_BANDWIDTH and 150 < f < 5500)


# Reference formants for an adult-sized vocal tract (Praat's tracker uses the same idea); children's are
# higher in proportion to their shorter tracts, so the reference is scaled by the voice's pitch.
REFERENCE = np.array([500.0, 1500.0, 2500.0])
MISSING_COST = 1.5  # cost of leaving a frame unlabeled rather than forcing a bad triple
REF_WEIGHT = 0.6
MOVE_WEIGHT = 4.0
BANDWIDTH_WEIGHT = 0.4  # per kHz of bandwidth: a sharp peak is more likely a real formant
# Formants are consecutive resonances. A labelling that leaves out a sharp resonance below F3 says that resonance is
# not a formant, which is how the tracker used to skip a correct r's low F3 (merged near F2) and call F4 "F3": the
# reference's F3 of 2,500 Hz made 3,000 look closer than 1,850. Each sharp resonance skipped now costs SKIP_COST.
SKIP_COST = 0.35
SHARP_BW = 500.0  # Hz: a resonance this narrow counts as clear
# The LPC order sets how many resonances fit under 8 kHz. One order cannot suit men (long tract, five formants
# under 5 kHz: about 18) and young children (about 12) alike, and a merged F2-F3 needs a high one to split.
# Each word is tracked at every order here and keeps the smoothest result (the idea of Barreda's Fast Track:
# the right analysis setting gives the smoothest formant tracks). Measured Nov 5 on an adult man's correct
# "rabbit": order 14 alone gave F3 about 3,000 Hz during the r, this gives about 1,850, rising to 2,400 in the vowel.
LPC_ORDERS = (12, 14, 16, 18, 20)


def reference_for(f0_median: float | None) -> np.ndarray:
    if f0_median is None or f0_median < 180:
        return REFERENCE
    return REFERENCE * (1.15 if f0_median < 260 else 1.3)


def track(cands: list[list[tuple[float, float]]], ref: np.ndarray) -> np.ndarray:
    """Label F1-F3 across frames with a Viterbi search: each frame takes the ordered triple of its
    resonances that stays closest to the reference and moves least from the previous frame. A frame
    can also stay unlabeled, which is better than a wrong label."""
    n = len(cands)
    out = np.full((n, 3), np.nan)
    if n == 0:
        return out
    states = []
    widths = []
    for c in cands:
        triples, bw = [None], [0.0]
        for i in range(len(c)):
            for j in range(i + 1, len(c)):
                for k in range(j + 1, len(c)):
                    t = (c[i][0], c[j][0], c[k][0])
                    if all(lo <= f <= hi for f, (lo, hi) in zip(t, F_RANGES)) and t[1] - t[0] > 150 and t[2] - t[1] > 150:
                        skipped = sum(1 for m in range(i + 1, k) if m != j and c[m][1] < SHARP_BW)
                        skipped += sum(1 for m in range(i) if c[m][1] < SHARP_BW and c[m][0] > 200)
                        triples.append(np.array(t))
                        bw.append(c[i][1] + c[j][1] + c[k][1] + skipped * SKIP_COST * 1000 / BANDWIDTH_WEIGHT)
        states.append(triples)
        widths.append(bw)

    # Each frame's triples as rows; row 0 is the unlabeled state (NaN), which costs MISSING_COST and moves for free.
    rows = [np.array([(np.nan,) * 3] + [list(t) for t in triples[1:]], dtype=float) for triples in states]

    def local(frame):
        c = (REF_WEIGHT * np.sum(np.abs(rows[frame] - ref) / ref, axis=1)
             + BANDWIDTH_WEIGHT * np.array(widths[frame]) / 1000)
        c[0] = MISSING_COST
        return c

    cost = local(0)
    back = []
    for frame in range(1, n):
        move = MOVE_WEIGHT * np.sum(np.abs(rows[frame - 1][:, None, :] - rows[frame][None, :, :]) / ref, axis=2)
        move[0, :] = 0.0
        move[:, 0] = 0.0
        options = cost[:, None] + move  # [previous state, this state]
        best = np.argmin(options, axis=0)
        cost = options[best, np.arange(len(best))] + local(frame)
        back.append(best)
    i = int(np.argmin(cost))
    for frame in range(n - 1, -1, -1):
        t = states[frame][i]
        if t is not None:
            out[frame] = t
        if frame:
            i = back[frame - 1][i]
    return out


def pitch_of(frame: np.ndarray, floor: float = 0.0) -> float:
    """F0 by normalized autocorrelation, or NaN when the frame is quiet or not clearly voiced."""
    f = frame - frame.mean()
    if not f.any() or np.sqrt(np.mean(f * f)) < floor:
        return np.nan
    lo, hi = int(RATE / F0_MAX), int(RATE / F0_MIN)
    if hi >= len(f):
        return np.nan
    # Normalized cross-correlation (as in RAPT): each lag compares two equal-energy stretches, so short lags are not
    # favoured. The plain autocorrelation picked an adult's third harmonic (410 Hz for a 137 Hz voice, Nov 11).
    n = len(f)
    num = np.correlate(f, f, "full")[n - 1:]
    cum = np.concatenate(([0.0], np.cumsum(f * f)))
    k = np.arange(n)
    ac = num / np.sqrt(np.maximum(cum[n - k] * (cum[n] - cum[k]), 1e-12))
    seg = ac[lo:hi]
    # The first peak near the best one: a child's high voice also peaks at twice its period.
    peaks = [i for i in range(1, len(seg) - 1) if seg[i] >= seg[i - 1] and seg[i] >= seg[i + 1]]
    best = max((seg[i] for i in peaks), default=0.0)
    lag = lo + next((i for i in peaks if seg[i] >= 0.9 * best), int(np.argmax(seg)))
    # A peak at the edge of the search range is the range, not the voice.
    if lag <= lo or lag >= hi - 1 or ac[lag] < VOICING:
        return np.nan
    return RATE / lag


def clean_pitch(f0: np.ndarray) -> np.ndarray:
    """Fix harmonic jumps (2x to 4x) against the median, then drop isolated voiced frames."""
    out = f0.copy()
    voiced = out[~np.isnan(out)]
    if len(voiced) == 0:
        return out
    med = np.median(voiced)
    for i, v in enumerate(out):
        if np.isnan(v):
            continue
        if v > 1.55 * med:  # a harmonic: twice, three or four times the voice (an adult's third harmonic, Nov 11)
            out[i] = v / min(4, max(2, round(v / med)))
        elif v < 0.55 * med:
            out[i] = v * 2
    for i in range(len(out)):
        near = out[max(0, i - 2):i + 3]
        if not np.isnan(out[i]) and np.sum(~np.isnan(near)) < 3:
            out[i] = np.nan
    return out


# Where in the word to look for the r, as a share of the word's length, by the word list's position.
STRONG = 0.3  # a frame must reach this share of the word's loudest to set the F3-F2 gap
R_WINDOW = {"start": (0.0, 0.45), "middle": (0.25, 0.75), "end": (0.55, 1.0)}


WAVE_BUCKETS = 1200


def outline(word: np.ndarray, buckets: int = WAVE_BUCKETS) -> np.ndarray:
    """Min and max of the waveform in equal time buckets: enough to draw it at any zoom on a screen."""
    if len(word) == 0:
        return np.zeros((0, 2))
    edges = np.linspace(0, len(word), min(buckets, len(word)) + 1).astype(int)
    return np.array([(word[a:b].min(), word[a:b].max()) for a, b in zip(edges[:-1], edges[1:]) if b > a])



NO_GAP = ("No voiced frames with all three formants where the r should be: "
          "the F3-F2 gap could not be measured.")


def _search_gap(result: "Analysis") -> None:
    """Set gap_min, gap_time and at_gap from the formants inside result.window (the whole word without one)."""
    result.gap_min = result.gap_time = result.at_gap = None
    result.notes = [n for n in result.notes if n != NO_GAP]
    gap = result.formants[:, 2] - result.formants[:, 1] if len(result.formants) else np.zeros(0)
    # Median over 5 frames (25 ms) so one mistracked frame cannot set the minimum.
    smooth = np.array([np.nanmedian(gap[max(0, i - 2):i + 3]) if not np.all(np.isnan(gap[max(0, i - 2):i + 3]))
                       else np.nan for i in range(len(gap))])
    # Only frames where all three formants were found can be the reported moment, and only strong ones:
    # onsets and fades are weak and noisy, and there the tracker read a wide "wabbit" gap as narrow.
    if len(smooth):
        smooth[np.isnan(gap)] = np.nan
    rms = np.asarray(result.rms, dtype=float)
    if len(rms) == len(smooth) and len(rms) and rms.max() > 0:
        smooth[rms < STRONG * rms.max()] = np.nan
    if result.window and len(smooth):
        lo, hi = result.window
        smooth[(result.times < lo) | (result.times > hi)] = np.nan
    if len(smooth) and np.any(~np.isnan(smooth)):
        i = int(np.nanargmin(smooth))
        result.gap_min, result.gap_time = float(smooth[i]), float(result.times[i])
        result.at_gap = tuple(float(v) for v in result.formants[i])
    else:
        result.notes.append(NO_GAP)


MIN_WINDOW = 0.02  # the shortest target window the SLP can set, in seconds


def with_window(a: "Analysis", window: tuple[float, float] | None) -> "Analysis":
    """A copy of `a` with its target window set by the SLP (None: back to the automatic one, which is
    a.auto_window) and every measure that depends on it searched again. The cached original is not touched."""
    auto = a.auto_window if a.auto_window is not None else a.window
    b = replace(a, notes=list(a.notes), auto_window=auto)
    if window is None:
        b.window = auto
    else:
        lo, hi = sorted(float(v) for v in window)
        lo = max(0.0, min(lo, a.spec_seconds - MIN_WINDOW))
        hi = min(a.spec_seconds, max(hi, lo + MIN_WINDOW))
        b.window = (round(lo, 4), round(hi, 4))
    _search_gap(b)
    return b

def roughness(forms: np.ndarray) -> float:
    """How jumpy a word's formant tracks are: mean squared second difference of log frequency over the labelled
    frames, plus a cost for frames left unlabelled. Lower is smoother."""
    ok = ~np.isnan(forms).any(axis=1)
    if ok.sum() < 5:
        return 9.0
    d2 = np.diff(np.log(forms[ok]), 2, axis=0)
    return float(np.mean(d2 ** 2)) * 1e3 + 2.0 * (1 - ok.mean())


def analyse(path: Path, position: str | None = None) -> Analysis:
    """position: where the target r sits in the word (start, middle, end); the F3-F2 gap is searched there."""
    from speakup import audio
    full, rate = audio.read(path)
    x = audio.to_16k(full, rate)
    a, b = find_word(x)
    word = x[a:b]
    # The picture uses the recording as made: at 48 kHz it shows up to SPEC_TOP_MAX, at 16 kHz up to 8 kHz.
    spec_top = min(SPEC_TOP_MAX, rate / 2)
    k = rate / RATE
    full_word = full[int(a * k):int(b * k)]
    win, hop = int(LPC_WINDOW * RATE), int(LPC_HOP * RATE)
    pitch_win = int(0.04 * RATE)  # pitch needs 2+ periods of the lowest F0
    pre = np.append(word[0], word[1:] - 0.63 * word[:-1]) if len(word) else word
    # Quiet frames are not voice: the floor is a fraction of the word's loudest 40 ms.
    floor = 0.0
    if len(word) >= pitch_win:
        loud = max(np.sqrt(np.mean(word[s:s + pitch_win] ** 2)) for s in range(0, len(word) - pitch_win + 1, hop))
        floor = loud * 0.1
    times, f0, cands, rms = [], [], [], []
    for s in range(0, max(0, len(word) - pitch_win) + 1, hop):
        centre = s + pitch_win // 2
        times.append(centre / RATE)
        f0.append(pitch_of(word[s:s + pitch_win], floor))
        rms.append(float(np.sqrt(np.mean(word[s:s + pitch_win] ** 2))) if len(word) else 0.0)
    f0 = clean_pitch(np.array(f0))
    frames = []
    for t, p in zip(times, f0):
        centre = int(t * RATE)
        lpc_frame = pre[max(0, centre - win // 2):centre + win // 2]
        frames.append(lpc_frame if not np.isnan(p) and len(lpc_frame) == win else None)
    voiced = f0[~np.isnan(f0)]
    ref = reference_for(float(np.median(voiced)) if len(voiced) else None)
    tracks = [track([candidates(fr, order) if fr is not None else [] for fr in frames], ref) for order in LPC_ORDERS]
    forms = min(tracks, key=roughness) if tracks else np.full((0, 3), np.nan)
    result = Analysis(
        start=a / RATE, end=b / RATE, times=np.array(times), f0=f0,
        formants=forms.reshape(-1, 3), spec_db=spectrogram(full_word, rate, spec_top), spec_seconds=len(word) / RATE,
        rms=np.array(rms), wave=outline(word), peak=float(np.max(np.abs(word))) if len(word) else 0.0,
        clip_seconds=len(x) / RATE, spec_top=spec_top, rate=rate,
    )
    voiced = result.f0[~np.isnan(result.f0)]
    if len(voiced):
        result.f0_median = float(np.median(voiced))
    if position in R_WINDOW and len(result.times):
        result.window = result.auto_window = tuple(share * result.spec_seconds for share in R_WINDOW[position])
    _search_gap(result)
    if result.f0_median and result.f0_median > 300:
        result.notes.append("High voice (F0 above 300 Hz): formant tracks are less reliable.")
    return result
