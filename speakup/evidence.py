"""One line of measured evidence beside Arti's call: the clip's F3-F2 gap against what the gap measured in
PERCEPT-R's training children, for an r at the start or end of a word.

speakup/data/gap_reference.json holds only summary numbers (medians and one cutoff per position) written by
scripts/gap_baseline.py from training speakers, never from the test speakers. No audio, no per-clip values.
"""

import json
from functools import lru_cache
from pathlib import Path

REFERENCE_PATH = Path(__file__).with_name("data") / "gap_reference.json"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def gap_line(gap_hz: float | None, position: str, arti_off: bool, path: Path | str = REFERENCE_PATH) -> tuple[str, bool] | None:
    """(text, agrees) for the question card, or None when there is no gap or no reference for this position."""
    ref = _load(str(path)).get(position)
    if gap_hz is None or not ref:
        return None
    cut = ref["cutoff_hz"]
    measured_off = gap_hz > cut
    agrees = measured_off == arti_off
    side = "above" if measured_off else "at or below"
    verdict = ("The measurement agrees with Arti." if agrees
               else "The measurement points the other way: listen before you decide.")
    text = (f"Measured F3-F2 gap: {gap_hz:,.0f} Hz, {side} the {cut:,.0f} Hz line. In the training children, "
            f"a correct {position} r measured about {ref['median_gap_correct']:,.0f} Hz and an off one about "
            f"{ref['median_gap_wrong']:,.0f} Hz. {verdict}")
    return text, agrees
