"""Published formant ranges by sound and age, for the Hz ranges tool on the analysis page.

The data is speakup/data/formant_norms.json (built by research track T3; every range entry is verified against
its source, see NORMS-README.md in the lab folder). The app never makes a range up: when nothing covers the child
it says so, and when the file is missing or broken it says that too.

How a range is picked for one child, one sound, one formant (owner and Lexi decisions, Nov 4):
- Only verified entries for that sound. A matching word position (context) wins; failing that an "any" entry;
  when neither exists the sound has no range for that position (r in carrot or car has no child data).
- Each formant comes from the narrowest age band that HAS that formant (so ɝ at 10 to 12 keeps Hillenbrand's
  F1, F2, F3 even though Flipsen's one-year band only has F3-F2).
- When no band covers the child's age, the nearest older band is shown with a warning (younger children usually
  have higher formants); past the last band, the nearest younger one, also with a warning.
- Boys and girls are kept apart whenever the source splits them. The app does not know the child's sex, so both
  are shown side by side. Where the source does not split them, the combined range is shown and labelled so.

Sound-general: nothing here knows about r except cue_for's stated fallback.
"""

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

NORMS_PATH = Path(__file__).with_name("data") / "formant_norms.json"
FORMANTS = ("F1", "F2", "F3", "F3_F2")
NO_FILE = "No range data on this machine"
LABELS = {"F3_F2": "F3-F2", "spectral_peak": "Noise peak", "spectral_mean": "Noise mean", "F0": "Pitch (F0)"}


class NormsUnavailable(Exception):
    """The norms file is missing or cannot be read."""


@dataclass(frozen=True)
class Range:
    lo: float
    hi: float
    mean: float | None = None
    sd: float | None = None
    n: int | None = None


@dataclass(frozen=True)
class Band:
    """One measure (F1, F2, F3, F3_F2 or an extra such as spectral_peak) for one sound at one age."""
    measure: str
    age_min: int
    age_max: int
    context: str
    source: str
    cite: str
    spread: str
    note: str
    together: Range  # boys and girls together (the source's pooled entry, or computed from the two)
    boys: Range | None = None  # set only when the source splits by sex
    girls: Range | None = None
    pooled_by_source: bool = True  # False when "together" was built here as min of lo, max of hi


@dataclass
class Norm:
    phoneme: str
    age_months: int
    context: str | None
    bands: dict = field(default_factory=dict)  # measure -> Band
    exact_age: bool = True  # False when the bands are borrowed from the nearest band that has data
    warning: str | None = None
    missing: list = field(default_factory=list)  # cue formants with no range at all


def _years(months: int) -> str:
    y, m = divmod(int(months), 12)
    return f"{y};{m}"


def age_label(lo: int, hi: int) -> str:
    """Years;months, as SLPs write ages: '6;0 to 11;9', or 'adults' for the open-ended adult bands."""
    if lo >= 216 and hi >= 1000:
        return "adults"
    return f"{_years(lo)} to {_years(hi)}"


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data.get("norms"), list):
            raise ValueError("no norms list")
        return data
    except (OSError, ValueError) as e:
        raise NormsUnavailable(f"{NO_FILE} ({e.__class__.__name__})") from e


def load(path: Path | str = NORMS_PATH) -> dict:
    return _load(str(path))


def cue_for(phoneme: str, path: Path | str = NORMS_PATH) -> dict:
    """{"key": [...formants...], "measure", "say"} for the sound. Fallback (stated): consonant r uses F2 and F3."""
    try:
        cue = load(path).get("cues", {}).get(phoneme)
    except NormsUnavailable:
        cue = None
    if cue:
        return cue
    if phoneme == "ɹ":  # the one stated fallback: today Arti scores only r
        return {"key": ["F2", "F3"], "measure": "F3-F2", "say": "F3 dips low, toward F2"}
    return {"key": [], "measure": "", "say": ""}


def _range(d: dict | None, n=None) -> Range | None:
    if not d or d.get("lo") is None or d.get("hi") is None:
        return None
    return Range(lo=d["lo"], hi=d["hi"], mean=d.get("mean"), sd=d.get("sd"), n=n)


def _measure(entry: dict, m: str) -> dict | None:
    return entry.get(m) if m in FORMANTS else (entry.get("extra") or {}).get(m)


def _candidates(data: dict, phoneme: str, context: str | None) -> list[dict]:
    rows = [e for e in data["norms"] if e.get("verified") and e.get("phoneme") == phoneme]
    if context is None:
        return rows
    exact = [e for e in rows if e.get("context") == context]
    return exact or [e for e in rows if e.get("context") == "any"]


def _band(group: list[dict], m: str, sources: dict) -> Band | None:
    by_sex = {e.get("sex"): e for e in group if _range(_measure(e, m))}
    if not by_sex:
        return None
    first = next(iter(by_sex.values()))
    boys = _range(_measure(by_sex["male"], m), by_sex["male"].get("n")) if "male" in by_sex else None
    girls = _range(_measure(by_sex["female"], m), by_sex["female"].get("n")) if "female" in by_sex else None
    if "any" in by_sex:
        together, pooled = _range(_measure(by_sex["any"], m), by_sex["any"].get("n")), True
    else:  # the source gave only the two groups: cover both
        parts = [r for r in (boys, girls) if r]
        together, pooled = Range(lo=min(r.lo for r in parts), hi=max(r.hi for r in parts)), False
    src = first.get("source", "")
    return Band(measure=m, age_min=first["age_min_months"], age_max=first["age_max_months"],
                context=first.get("context", "any"), source=src,
                cite=(sources.get(src) or {}).get("cite", src), spread=first.get("spread", ""),
                note=(by_sex.get("any") or first).get("note", ""), together=together, boys=boys, girls=girls,
                pooled_by_source=pooled)


def norms_for(phoneme: str, age_months: int, context: str | None = None, path: Path | str = NORMS_PATH,
              measures=None) -> Norm | None:
    """The ranges for this sound at this age, or None when the file has nothing at all for the sound (in that
    position). Raises NormsUnavailable when the file is missing or broken, so the caller can say so."""
    data = load(path)
    rows = _candidates(data, phoneme, context)
    if not rows:
        return None
    sources = data.get("sources", {})
    groups: dict[tuple, list[dict]] = {}
    for e in rows:
        groups.setdefault((e.get("source"), e.get("context"), e["age_min_months"], e["age_max_months"]), []).append(e)
    if measures is None:
        seen = []
        for e in rows:
            for m in list(FORMANTS) + list((e.get("extra") or {}).keys()):
                if _measure(e, m) and m not in seen:
                    seen.append(m)
        measures = seen
    norm = Norm(phoneme=phoneme, age_months=age_months, context=context)
    for m in measures:
        having = [(k, g) for k, g in groups.items() if any(_range(_measure(e, m)) for e in g)]
        if not having:
            continue
        covering = [(k, g) for k, g in having if k[2] <= age_months <= k[3]]
        if covering:
            pick = min(covering, key=lambda kg: (kg[0][3] - kg[0][2], kg[0][1] != context))
        else:
            older = [(k, g) for k, g in having if k[2] > age_months]
            pool = older or having
            near = (lambda kg: kg[0][2]) if older else (lambda kg: -kg[0][3])
            best = min(near(kg) for kg in pool)
            pick = min((kg for kg in pool if near(kg) == best), key=lambda kg: kg[0][3] - kg[0][2])
            norm.exact_age = False
        band = _band(pick[1], m, sources)
        if band:
            norm.bands[m] = band
    if not norm.bands:
        return None
    if not norm.exact_age:
        shown = sorted({(b.age_min, b.age_max) for b in norm.bands.values()})
        lo = shown[0][0]
        older = lo > age_months
        where = ", ".join(age_label(a, b) for a, b in shown)
        norm.warning = (f"No published range for age {_years(age_months)}; showing {where}. "
                        + ("Younger children usually have higher formants." if older
                           else "Older children and adults usually have lower formants."))
    cue = cue_for(phoneme, path)
    norm.missing = [k for k in cue.get("key", []) if k not in norm.bands]
    return norm


def _r(r: Range | None):
    return None if r is None else {"lo": r.lo, "hi": r.hi, "mean": r.mean, "sd": r.sd, "n": r.n}


def ranges_json(phoneme: str | None, age_months: int | None, context: str | None = None,
                path: Path | str = NORMS_PATH) -> dict:
    """Everything the viewer's Hz ranges tool needs, as plain data. status: ok, nofile, noage, nosound."""
    out = {"phoneme": phoneme, "age_months": age_months, "context": context, "bands": [], "warning": None,
           "missing": [], "cue": cue_for(phoneme, path) if phoneme else {"key": [], "measure": "", "say": ""}}
    if not phoneme:
        return {**out, "status": "nosound", "message": "No target sound for this word"}
    if age_months is None:
        return {**out, "status": "noage", "message": "No age for this child, so no range is shown"}
    try:
        norm = norms_for(phoneme, age_months, context, path)
    except NormsUnavailable as e:
        return {**out, "status": "nofile", "message": str(e)}
    if norm is None:
        where = {"prevocalic": " at the start of a word", "intervocalic": " in the middle of a word",
                 "postvocalic": " at the end of a word", "cluster": " in a cluster"}.get(context or "", "")
        return {**out, "status": "nosound", "message": f"No published range for /{phoneme}/{where}"}
    bands = []
    for m, b in norm.bands.items():
        bands.append({"measure": m, "label": LABELS.get(m, m),
                      "age": age_label(b.age_min, b.age_max), "age_min": b.age_min, "age_max": b.age_max,
                      "context": b.context, "source": b.source, "cite": b.cite, "spread": b.spread, "note": b.note,
                      "together": _r(b.together), "boys": _r(b.boys), "girls": _r(b.girls),
                      "pooled_by_source": b.pooled_by_source})
    return {**out, "status": "ok", "message": None, "bands": bands, "warning": norm.warning,
            "missing": norm.missing}
