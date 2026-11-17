"""Adult or child voice, and making an adult voice readable by Arti (lab, Nov 4).

Arti learned the r only from children (PERCEPT-R). An adult's longer vocal tract puts every resonance
(formant) lower, and Arti then calls a glided "wabbit" right. Children's formants run roughly 15 to 50%
above adults' (Potamianos & Narayanan 2003; Lee, Potamianos & Narayanan 1999).

The fix is vocal tract length normalization (VTLN; Lee & Rose 1998): stretch the frequency axis by a
factor alpha before Arti looks. Arti computes its own 40 log-mel bands inside the ONNX file
(`frontend.mel`, 40 x 201), so the stretch is done exactly there: each mel filter is moved down by
alpha, which reads the adult's spectrum at f/alpha. No audio is changed, the timing stays as spoken,
and the ONNX file is not edited: ONNX Runtime swaps the matrix in when it opens a session.

How alpha is chosen matters more than the stretch:
- Never from Arti's own answer. Picking the alpha that makes Arti most sure drifts toward "correct",
  which hides real errors (test-time entropy minimisation is known to over-trust itself).
- From the speaker's pitch, over the session so far (below). Formants were tried first: the lab's F3
  tracker read adult F3 too high and gave too small a stretch, so pitch it is.
- Then every word is also scored at alpha - 0.05 and alpha + 0.05. If the answer flips, the word is
  marked "unsure" for the SLP instead of trusting one setting.

Detection is only a hint: a median pitch under 165 Hz is almost surely an adult man (children 4 to 12
average about 243 to 277 Hz; men 115 Hz, women 199 Hz). Women and children overlap in pitch, so the
SLP, not the app, says who is speaking.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from speakup import acoustics

# Pitch bands (Hz) for the hint. Children 4-12: means 243-277 (Maturo et al. 2012); men 115 +- 21 and
# women 199 +- 28 (Leung et al. 2022), via the Sydney Voice Lab normative sheet.
ADULT_MAN_BELOW = 165.0
CHILD_ABOVE = 200.0

# The stretch comes from pitch (a pitch-predicted warp came close to the best searched one: Faria & Gelbart
# 2005): alpha = (CHILD_F0 / speaker's median F0) ** EXPONENT, kept within [1.0, 1.4].
# CHILD_F0 is the middle of the 4-12 year means. EXPONENT was fitted in the lab on two synthetic adult voices
# (Windows TTS, 128 words, half glided) and Raf's 4 labelled board clips: a man needs about 1.3, a woman
# about 1.1. A tuning on little data, not a validation: the stability check below is what keeps it honest.
CHILD_F0 = 250.0
EXPONENT = 0.3
ALPHA_MIN, ALPHA_MAX, ALPHA_STEP = 1.0, 1.4, 0.05
# What the app uses for an adult whose pitch could not be measured yet.
ALPHA_FALLBACK = 1.2
ALPHAS = tuple(round(ALPHA_MIN + i * ALPHA_STEP, 2) for i in range(int(round((ALPHA_MAX - ALPHA_MIN) / ALPHA_STEP)) + 1))


def snap(alpha: float) -> float:
    """The nearest alpha on the grid the board keeps sessions for."""
    return min(ALPHAS, key=lambda a: abs(a - alpha))


def mel_bank(alpha: float = 1.0, rate: int = 16000, n_fft: int = 400, n_mels: int = 40) -> np.ndarray:
    """Arti's mel matrix (bands x FFT bins), as torchaudio's melscale_fbanks builds it (HTK scale, no norm),
    with every triangle's corners moved from f to f / alpha and its height scaled by alpha.

    A band that was centred on f then reads the input around f / alpha: an adult's lower resonances land
    where a child's would. The factor alpha keeps each band's total weight, since it now spans 1/alpha as
    many bins. alpha 1.0 is the matrix inside arti-v0.onnx (tests check this against the file)."""
    freqs = np.linspace(0.0, rate / 2, n_fft // 2 + 1)
    top = 2595.0 * np.log10(1.0 + (rate / 2) / 700.0)
    corners = 700.0 * (10.0 ** (np.linspace(0.0, top, n_mels + 2) / 2595.0) - 1.0) / alpha
    diff = corners[1:] - corners[:-1]
    slopes = corners[None, :] - freqs[:, None]
    down = -slopes[:, :-2] / diff[:-1]
    up = slopes[:, 2:] / diff[1:]
    bank = np.maximum(0.0, np.minimum(down, up))
    return (alpha * bank.T).astype(np.float32)


def alpha_for(f0: float | None) -> float:
    """The stretch for a speaker of median pitch f0, on the grid; the fallback without a pitch."""
    if not f0:
        return ALPHA_FALLBACK
    return snap(min(max((CHILD_F0 / f0) ** EXPONENT, ALPHA_MIN), ALPHA_MAX))


def hint(f0: float | None) -> str:
    """adult-man, child-or-woman or unclear: a hint for the SLP, never a decision."""
    if not f0:
        return "unclear"
    if f0 < ADULT_MAN_BELOW:
        return "adult-man"
    if f0 > CHILD_ABOVE:
        return "child-or-woman"
    return "unclear"


def pitch(path: Path) -> float | None:
    """Median pitch (Hz) over the clearly voiced, loud frames of one recording; None if too little voice."""
    x = acoustics.read(path)
    start, end = acoustics.find_word(x)
    word = x[start:end]
    n, hop = int(acoustics.LPC_WINDOW * acoustics.RATE), int(acoustics.LPC_HOP * acoustics.RATE)
    frames = [word[i:i + n].astype(float) for i in range(0, max(len(word) - n, 0) + 1, hop)]
    if not frames:
        return None
    rms = np.array([np.sqrt(np.mean(f ** 2)) for f in frames])
    f0 = acoustics.clean_pitch(np.array([acoustics.pitch_of(f) for f in frames]))
    good = (f0 > 0) & (rms > 0.25 * (rms.max() or 1.0))
    if good.sum() < 10:  # 50 ms of clear voice
        return None
    return float(np.median(f0[good]))


@dataclass(frozen=True)
class Reading:
    """Arti's answer under the stretch, with the neighbours that check it."""
    alpha: float
    p_wrong: float  # at alpha
    neighbours: tuple[tuple[float, float], ...]  # (alpha, p_wrong) at alpha - step and alpha + step
    plain: float  # p_wrong with no stretch, for the SLP to compare

    @property
    def stable(self) -> bool:
        wrong = self.p_wrong >= 0.5
        return all((p >= 0.5) == wrong for _, p in self.neighbours)


class Stretcher:
    """Arti with the stretch: one ONNX Runtime session per alpha on the grid, each with the mel matrix swapped
    in by SessionOptions.add_initializer, so the model file is never edited. The file is about 1 MB, so nine
    sessions cost little; a word is run three or four times (about 0.06 s each on the board)."""

    MEL = "frontend.mel"

    def __init__(self, model_path: Path, threads: int = 4):
        import onnxruntime as ort

        self._sessions = {}
        self._keep = []  # OrtValues must outlive their sessions
        for alpha in ALPHAS:
            options = ort.SessionOptions()
            options.intra_op_num_threads = threads
            if alpha != 1.0:
                # ORT reads the matrix from our buffer, so both the array and its OrtValue must stay alive.
                mel = np.ascontiguousarray(mel_bank(alpha))
                value = ort.OrtValue.ortvalue_from_numpy(mel)
                self._keep += [mel, value]
                options.add_initializer(self.MEL, value)
            self._sessions[alpha] = ort.InferenceSession(str(model_path), options, providers=["CPUExecutionProvider"])

    def p_wrong(self, audio: np.ndarray, alpha: float) -> float:
        (p,) = self._sessions[snap(alpha)].run(["p_wrong"], {"audio": audio})
        return float(p[0])

    def read(self, audio: np.ndarray, alpha: float) -> Reading:
        alpha = snap(alpha)
        i = ALPHAS.index(alpha)
        near = [ALPHAS[j] for j in (i - 1, i + 1) if 0 <= j < len(ALPHAS)]
        plain = self.p_wrong(audio, 1.0)
        here = plain if alpha == 1.0 else self.p_wrong(audio, alpha)
        return Reading(alpha, here, tuple((a, plain if a == 1.0 else self.p_wrong(audio, a)) for a in near), plain)
