"""Raf's seam (#37): where Arti's p(wrong) is too close to call, so the word card asks the SLP to listen.

Raf sets UNSURE_BAND from his calibration on real clips, as (low, high) with both ends included. The app never
sets it and never moves Arti's 0.5 threshold; while it is None, no word is marked unsure."""

UNSURE_BAND: tuple[float, float] | None = None


def unsure(p_wrong: float) -> bool:
    if UNSURE_BAND is None:
        return False
    low, high = UNSURE_BAND
    return low <= p_wrong <= high
