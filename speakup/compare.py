"""Compare: reference formant curves drawn on the child's spectrogram in the analysis viewer.

The viewer's Compare tool opens a small pop-up that asks what to compare with: the target sound (for /ɹ/ in rabbit, a
correct "rabbit"), its common errors (gliding "wabbit", the derhotacized r) or any other sound by a short search, and
the speaker (age group, girl or boy). The choice is drawn as reference F1, F2 and F3 curves directly on the spectrogram,
which the SLP can slide left and right and stretch in time, never up or down (research and the reasons:
Speak-Up-Docs/Archive/Research/compare-overlay-research.md).

The curves are the formant tracks of the sound book's computer-made sounds (speakup.synth_book: the values published
for that age and sex, joined by the transitions the synthesizer uses), the same data behind the book's pictures. Only
the parts where the voice or the breath sounds through the formants are given; closures and fricative noise are gaps.

Server side (this module): the pop-up's defaults (defaults()), its sound list (data(), at /compare/data) and one
reference's curves (curves(), at /compare/curves/<item>-<group>.json). The pop-up and the drawing are in
speakup.soundview. Nothing is fetched from outside.
"""

import re
from functools import lru_cache

from speakup import synthview

DEFAULT_COMPARE = 2  # how many of the target's errors the pop-up offers first
MAX_REFERENCES = 2  # reference curves on the picture at once
STEP_MS = 5  # one curve point every 5 ms
GROUP_OF = {("6", "female"): "girl6", ("6", "male"): "boy6", ("10-12", "female"): "girl10",
            ("10-12", "male"): "boy10", ("adult", "female"): "woman", ("adult", "male"): "man"}
# /ɹ/ has three references; which one fits depends on where the sound sits in the word.
R_BY_CONTEXT = {"intervocalic": "c-r", "postvocalic": "v-er"}  # anything else (start, cluster): "rabbit"
CURVE_NAME = re.compile(r"([a-z0-9-]+?)-((?:girl|boy)(?:6|10)|woman|man)")
# Formants are drawn where the voice (60 dB is a full vowel) or the breath (/h/, aspiration) excites them; a voice bar
# in a stop closure or the voicing under a fricative's noise is too weak to show formants on a spectrogram.
VOICED_DB, BREATH_DB = 48.0, 40.0
# The reference is drawn as the whole syllable, its sound plus the vowel next to it (research, Nov 5:
# Speak-Up-Docs/Archive/Research/r-tracking-and-compare.md; what an SLP judges in /ɹ/ is F3 dipping toward F2 and rising
# into the vowel, which a flat hold cannot show). The neighbouring vowel's F3 also sizes the reference to the speaker.
VOWELS = set("iɪeɛæaɑɒɔoʊuʌəɝɚyø")


def _syllable(segs: list[dict], focus: list[float]) -> tuple[list[float], dict | None]:
    """The span to draw (the focus sound plus the vowel right after it, or right before it when none follows) and
    the vowel used to size the reference: {t0, t1} of the half of that vowel farther from the sound (the steady
    part), or None when the sound has no vowel next to it."""
    def vowel(sg):
        return sg is not None and sg["label"] and all(c in VOWELS or c == "ː" for c in sg["label"])
    i = next((k for k, sg in enumerate(segs) if abs(sg["t0"] - focus[0]) < 1e-3), None)
    if i is None:
        return focus, None
    j = next((k for k in range(i, len(segs)) if abs(segs[k]["t1"] - focus[1]) < 1e-3), i)
    after = segs[j + 1] if j + 1 < len(segs) else None
    before = segs[i - 1] if i > 0 else None
    if vowel(after):  # between two vowels (carrot) the dip is drawn whole, from vowel to vowel
        mid = (after["t0"] + after["t1"]) / 2
        return [before["t0"] if vowel(before) else focus[0], after["t1"]], {"t0": round(mid, 4), "t1": after["t1"]}
    if vowel(before):
        mid = (before["t0"] + before["t1"]) / 2
        return [before["t0"], focus[1]], {"t0": before["t0"], "t1": round(mid, 4)}
    return focus, None


def _years(months: int) -> str:
    y, m = divmod(int(months), 12)
    return f"{y};{m}"


def band_label(band: dict) -> str:
    """'6;0 to 7;11', '10;0 to 12;11' or 'adults', the way SLPs write ages (and the Age ranges tool does)."""
    lo, hi = band["from_months"], band["to_months"]
    return "adults" if hi is None else f"{_years(lo)} to {_years(hi)}"


def item_for(target: str | None, context: str | None = None, word: str | None = None) -> str | None:
    """The picture item for the sound a word tests (IPA, an item id or an error variant name), or None."""
    idx = synthview.index()
    if idx is None or not target:
        return None
    target = "ɹ" if target == "r" else target
    items = idx["item_by_id"]
    if target in items:
        return target
    if word:  # a word the book has its own picture of ("rabbit")
        for it in idx["items"]:
            if it["kind"] != "error" and it["word"] == word.strip().lower() and it["sound"] == target:
                return it["id"]
    if target == "ɹ":
        return R_BY_CONTEXT.get(context or "", "w-rabbit")
    return idx["by_sound"].get(target) or idx["variants"].get(target)


def related(item: str) -> list[str]:
    """Pictures to compare an item with, most likely first: the error versions of its sound (for an error version,
    its target), then the book's error pairs, then its "often confused with" list."""
    idx = synthview.index()
    items = idx["item_by_id"]
    it = items[item]
    if it["error_of"]:
        first = [it["error_of"]]
    else:
        first = [i["id"] for i in idx["items"] if i["error_of"] and items[i["error_of"]]["sound"] == it["sound"]]
    pairs = [b for prs in idx["pairs"].values() for a, b in prs if a == item]
    return [i for i in dict.fromkeys(first + pairs + it["confusable"]) if i != item and i in items]


def _band(age_months: int | None, bands: list[dict]) -> tuple[dict, str | None]:
    """The picture band for an age and the warning when none covers it (nearest older band, as norms.py does)."""
    if age_months is None:
        return bands[0], f"Age not recorded; showing {band_label(bands[0])}."
    for b in bands:
        if age_months >= b["from_months"] and (b["to_months"] is None or age_months <= b["to_months"]):
            return b, None
    older = [b for b in bands if b["from_months"] > age_months]
    pick = older[0] if older else bands[-1]
    tail = ("Younger children usually have higher formants." if older
            else "Older children and adults usually have lower formants.")
    return pick, f"No published range for age {_years(age_months)}; showing {band_label(pick)}. {tail}"


def defaults(target: str | None, age_months: int | None = None, sex: str | None = None, context: str | None = None,
             word: str | None = None) -> dict:
    """What the pop-up offers first. item: the target's reference (None: none for that sound, see missing);
    compare: its common errors; band and warning: the age band (nearest older when none covers the age); sex: the
    reference speaker's sex (girl when not recorded, with sex_note)."""
    idx = synthview.index()
    shown = f"/{target}/" if target else "this sound"
    if idx is None:
        return {"target": target, "item": None, "compare": [], "band": "6", "warning": None, "sex": "female",
                "sex_known": False, "sex_note": "", "top_hz": 6000,
                "missing": "The reference data is not on this machine, so there is nothing to compare with."}
    band, warning = _band(age_months, idx["age_bands"])
    known = sex in ("female", "male")
    item = item_for(target, context, word)
    compare = []
    if item:
        rel = related(item)
        errors = [i for i in rel if idx["item_by_id"][i]["kind"] == "error" or idx["item_by_id"][item]["error_of"]]
        compare = errors[:DEFAULT_COMPARE] if errors else rel[:1]
    tops = [p["top_hz"] for p in idx["pictures"] if p["item"] in [item, *compare]]
    return {
        "target": target, "item": item, "compare": compare, "band": band["band"], "warning": warning,
        "sex": sex if known else "female", "sex_known": known,
        "sex_note": "" if known else "Sex not recorded, so a girl is chosen first. Switch to boy if needed.",
        "top_hz": max(tops) if tops else 6000,
        "missing": None if item else f"No reference for {shown} yet. Search for another sound below.",
    }


def data(target: str | None, age_months: int | None = None, sex: str | None = None, context: str | None = None,
         word: str | None = None) -> dict:
    """Everything the pop-up needs: the defaults, every sound it can draw (for the search) and the speakers."""
    idx = synthview.index()
    out = {"defaults": defaults(target, age_months, sex, context, word), "items": [], "bands": [], "groups": {},
           "max_references": MAX_REFERENCES}
    if idx is None:
        return out
    order = {"approximant": 0, "r-vowel": 1, "error": 2}
    out["items"] = [{"id": i["id"], "title": i["title"], "sound": i["sound"], "kind": i["kind"], "word": i["word"],
                     "look": i.get("look_for", ""), "section": i["section"], "related": related(i["id"])}
                    for i in sorted(idx["items"], key=lambda i: (order.get(i["kind"], 3), i["id"]))]
    out["bands"] = [{"band": b["band"], "label": band_label(b)} for b in idx["age_bands"]]
    out["groups"] = {g["id"]: {"band": g["age_band"], "sex": g["sex"], "label": g["label"]} for g in idx["groups"]}
    out["group_of"] = {f"{b}|{s}": g for (b, s), g in GROUP_OF.items()}
    return out


def _db(lin):
    import numpy as np
    return 20 * np.log10(np.maximum(lin, 1e-9))


@lru_cache(maxsize=64)
def curves(name: str) -> dict | None:
    """One reference as curves: name '<item>-<group>' ("w-rabbit-girl6"). t: seconds from the start of the sound (one
    point every STEP_MS), f: [F1, F2, F3] per point in Hz, None where no formants show (closures, fricative noise,
    the silence around it); focus: [start, end] of the sound the reference is about (the /ɹ/ of rabbit), which the
    viewer lines up with the target window; segs: each sound's span and label. None for an unknown name."""
    from speakup import synth, synth_book
    import numpy as np

    m = CURVE_NAME.fullmatch(name)
    if not m or m.group(1) not in synth_book.ITEMS or m.group(2) not in synth_book.GROUP:
        return None
    item, gid = m.group(1), m.group(2)
    built = synth_book.build(item, gid)
    tr = synth._tracks(built.plan)
    n = int(tr["n"][0])
    shows = (_db(tr["av"]) >= VOICED_DB) | (_db(tr["ah"]) >= BREATH_DB)
    idx = np.arange(0, n, STEP_MS)
    f = [[round(float(tr[f"F{k + 1}"][i])) if shows[i] else None for k in range(3)] for i in idx]
    bounds = built.plan.bounds()
    focus = [i for i, sg in enumerate(built.plan.segs) if sg.focus] or [0]
    segs = [{"t0": round(a, 4), "t1": round(b, 4), "label": sg.label or sg.name}
            for (a, b), sg in zip(bounds, built.plan.segs) if (sg.label or sg.name)]
    focus_span = [round(bounds[focus[0]][0], 4), round(bounds[focus[-1]][1], 4)]
    span, vowel = _syllable(segs, focus_span)
    vowel_f3 = None
    if vowel:
        f3 = [row[2] for t, row in zip(idx, f) if row[2] is not None and vowel["t0"] <= t / 1000 <= vowel["t1"]]
        vowel_f3 = round(float(np.median(f3))) if f3 else None
    info = (synthview.index() or {}).get("item_by_id", {}).get(item, {})
    group = synth_book.GROUP[gid]
    return {
        "item": item, "group": gid, "title": synth_book.ITEMS[item].title, "group_label": group.label,
        "sound": synth_book.ITEMS[item].sound, "seconds": round(n / 1000, 4),
        "t": [round(i / 1000, 4) for i in idx], "f": f,
        "focus": focus_span, "segs": segs, "span": [round(x, 4) for x in span], "vowel": vowel, "vowel_f3": vowel_f3,
        "targets": [{"k": k, "v": v} for k, v, _, _ in built.marks if k in ("F1", "F2", "F3")],
        "estimated": built.estimated, "look": info.get("look_for", ""), "section": info.get("section"),
        "kind": synth_book.ITEMS[item].kind,
    }
