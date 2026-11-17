"""Draw the sound book's computer-made spectrograms and check each one.

For every item and speaker group in speakup.synth_book: synthesize the sound (speakup.synth), run it back through the
app's own analysis (speakup.acoustics.analyse) and check that the measured F1 to F3 (or the noise peak, or the VOT)
land near the targets, then draw the picture in the app's spectrogram style (6 ms wideband, pre-emphasis, top 50 dB,
dark = energy) with the targets marked. Writes speakup/static/book/synth/*.png and index.json. Audio is never saved
(the WAVs live in a temporary folder while checking).

Needs matplotlib and Pillow on the machine that builds the pictures (not on the board).
Run: python scripts/build_synth_pictures.py [--only ITEM] [--group GROUP] [--no-png]"""

import argparse
import dataclasses
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from speakup import acoustics, synth, synth_book as sb  # noqa: E402

OUT = ROOT / "speakup" / "static" / "book" / "synth"
DYNAMIC_DB = 50.0
COLORS = {"F1": "#1f77b4", "F2": "#2ca02c", "F3": "#d62728", "peak": "#e07b00", "nasal": "#7b3fa0",
          "murmur": "#7b3fa0", "zero": "#555555"}
TOL_REL, TOL_ABS = 0.10, 100.0  # formants: within 10% or 100 Hz, whichever is larger
TOL_PEAK = 0.15  # noise peaks: within 15%
TOL_VOT = 30.0  # ms: the app's pitch frames are 40 ms long and report voicing 15 to 20 ms late, so this check
# mainly tells short-lag (b d g) from long-lag (p t k) VOT


def tolerance(target: float) -> float:
    return max(TOL_REL * target, TOL_ABS)


CHECK_PAD_MS = 300  # silence around the sound while checking, as a recording has: the app's word finder sets its
# noise floor from the quietest fifth of the clip, so a clip with almost no silence would set it too high


def check(built: sb.Built, wav: Path) -> dict:
    """Synthesize the plan with silence around it, measure it with the app's analysis, compare with the targets."""
    plan = dataclasses.replace(built.plan, pad_ms=CHECK_PAD_MS)
    wav.write_bytes(synth.wav_bytes(synth.synthesize(plan)))
    a = acoustics.analyse(wav)
    bounds = plan.bounds()
    focus = [i for i, s in enumerate(plan.segs) if s.focus]
    out = {"pass": True, "items": []}

    def add(what, target, measured, tol, unit="Hz"):
        ok = measured is not None and not np.isnan(measured) and abs(measured - target) <= tol
        out["items"].append({"what": what, "target": round(float(target)), "unit": unit,
                             "measured": None if measured is None or np.isnan(measured) else round(float(measured)),
                             "tolerance": round(float(tol)), "pass": bool(ok)})
        out["pass"] &= bool(ok)

    t_abs = a.times + a.start
    for kind, val, idx, _ in built.marks:
        t0, t1 = bounds[idx]
        if kind == "murmur":  # the tracker draws no dots in a murmur: the app's LPC, lowest resonance, mid-murmur
            add("murmur low resonance (lowest LPC resonance)", val, murmur_resonance(a, wav, t0, t1), tolerance(val))
        elif kind in ("F1", "F2", "F3"):
            i = {"F1": 0, "F2": 1, "F3": 2}[kind]
            # The middle of the segment: its target is held there (transitions sit at the edges).
            span = t1 - t0
            m = (t_abs >= t0 + 0.25 * span) & (t_abs <= t1 - 0.25 * span)
            if not m.any():
                m = (t_abs >= t0) & (t_abs <= t1)
            vals = a.formants[m, i]
            meas = float(np.nanmedian(vals)) if np.any(~np.isnan(vals)) else np.nan
            if kind == "F1" and any(k == "nasal" for k, *_ in built.marks):
                continue  # a nasalized vowel's F1 is deliberately disturbed; F2 and F3 are checked
            add(kind, val, meas, tolerance(val))
        elif kind == "peak":
            meas = noise_peak(a, t0, t1)
            add("noise peak", val, meas, TOL_PEAK * val)
        elif kind == "vot":
            on = voicing_onset(a, t0)
            add("VOT (burst to voicing)", val, None if on is None else on * 1000, TOL_VOT, "ms")
    # When the tracker's labels miss, look at the raw resonances the app's LPC finds in the same frames: if each
    # missed target has one nearby, the sound is right and the tracker mislabelled it (reported, not hidden).
    missed = [c for c in out["items"] if not c["pass"] and c["what"] in ("F1", "F2", "F3")]
    if missed:
        idx = next(i for k, _, i, _ in built.marks if k == missed[0]["what"])
        res = raw_resonances(wav, *bounds[idx])
        for c in missed:
            near = min(res, key=lambda f: abs(f - c["target"])) if res else None
            c["raw_lpc"] = None if near is None else round(near)
            c["raw_pass"] = near is not None and abs(near - c["target"]) <= c["tolerance"]
        if all(c["raw_pass"] for c in missed):
            out["pass"] = True
            out["note"] = ("The app's formant tracker mislabelled " + ", ".join(c["what"] for c in missed)
                           + " here; the app's own LPC resonances in the same frames are on target.")
    if not out["items"]:
        out["note"] = "Nothing measurable to check for this sound (flat noise or aspiration)."
        flat = None
        f_idx = focus[0] if focus else None
        if f_idx is not None and plan.segs[f_idx].af > synth.OFF:
            flat = flatness(a, *bounds[f_idx])
            ok = flat < 18.0
            out["items"].append({"what": "noise is flat (strongest band minus median, dB)", "target": 0, "unit": "dB",
                                 "measured": round(flat, 1), "tolerance": 18, "pass": bool(ok)})
            out["pass"] &= bool(ok)
    return out


def _spec_window(a: acoustics.Analysis, t0: float, t1: float) -> np.ndarray:
    cols = a.spec_db.shape[1]
    times = a.start + (np.arange(cols) * acoustics.SPEC_HOP + acoustics.SPEC_WINDOW / 2)
    span = t1 - t0
    m = (times >= t0 + 0.2 * span) & (times <= t1 - 0.2 * span)
    power = 10 ** (a.spec_db[:, m] / 10)
    db = 10 * np.log10(power.mean(axis=1) + 1e-12)
    hz = np.arange(len(db)) * a.spec_top / max(1, len(db) - 1)
    k = max(1, int(400 / (hz[1] - hz[0])))  # smooth over about 400 Hz
    return hz, np.convolve(db, np.ones(k) / k, mode="same")


def raw_resonances(wav: Path, t0: float, t1: float) -> list[float]:
    """Median frequency of each LPC resonance (the app's candidates) in the middle of a segment."""
    x = acoustics.read(wav)
    pre = np.append(x[0], x[1:] - 0.63 * x[:-1])
    win = int(acoustics.LPC_WINDOW * acoustics.RATE)
    span = t1 - t0
    frames = []
    for t in np.arange(t0 + 0.3 * span, t1 - 0.3 * span + 1e-9, 0.005):
        c = int(t * acoustics.RATE)
        frames.append([f for f, _ in acoustics.candidates(pre[c - win // 2:c + win // 2])])
    if not frames:
        return []
    k = min(len(f) for f in frames)
    return [float(np.median([f[i] for f in frames])) for i in range(k)]


def murmur_resonance(a, wav: Path, t0: float, t1: float) -> float:
    x = acoustics.read(wav)
    pre = np.append(x[0], x[1:] - 0.63 * x[:-1])
    win = int(acoustics.LPC_WINDOW * acoustics.RATE)
    lows = []
    span = t1 - t0
    for t in np.arange(t0 + 0.3 * span, t1 - 0.3 * span + 1e-9, 0.005):
        c = int(t * acoustics.RATE)
        cands = acoustics.candidates(pre[c - win // 2:c + win // 2])
        if cands:
            lows.append(cands[0][0])
    return float(np.median(lows)) if lows else np.nan


def noise_peak(a, t0, t1) -> float:
    hz, db = _spec_window(a, t0, t1)
    m = (hz >= 1500) & (hz <= a.spec_top - 300)
    return float(hz[m][np.argmax(db[m])])


def flatness(a, t0, t1) -> float:
    hz, db = _spec_window(a, t0, t1)
    m = (hz >= 1500) & (hz <= a.spec_top - 300)
    return float(db[m].max() - np.median(db[m]))


def voicing_onset(a, t_burst: float) -> float | None:
    t_abs = a.times + a.start
    after = (t_abs > t_burst) & ~np.isnan(a.f0)
    # The voiced frame closest after the burst whose window is at least half past the burst.
    if not after.any():
        return None
    first = t_abs[after][0]
    # A 40 ms pitch frame reports voicing once about half its window is voiced: its centre is the onset estimate.
    return first - t_burst


def draw(item: sb.Item, group: sb.Group, built: sb.Built, x: np.ndarray, path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image

    top = built.top_hz
    db = acoustics.spectrogram(x, synth.RATE, top)
    level = np.clip((db - (db.max() - DYNAMIC_DB)) / DYNAMIC_DB, 0, 1)
    secs = len(x) / synth.RATE
    fig = plt.figure(figsize=(6.4, 2.9), dpi=100)
    ax = fig.add_axes([0.085, 0.16, 0.775, 0.66])
    ax.imshow(level, origin="lower", aspect="auto", cmap="gray_r", vmin=0, vmax=1,
              extent=(0, secs, 0, top), interpolation="bilinear")
    ax.set_xlim(0, secs)
    ax.set_ylim(0, top)
    step = 1000 if top <= 6000 else 2000
    ax.set_yticks(range(0, top + 1, step))
    ax.set_yticklabels([f"{k // 1000}k" if k else "0" for k in range(0, top + 1, step)], fontsize=7.5)
    ax.set_xticks(np.arange(0, secs + 1e-6, 0.1))
    ax.set_xticklabels([f"{t:.1f}" for t in np.arange(0, secs + 1e-6, 0.1)], fontsize=7.5)
    ax.set_xlabel("time (s)", fontsize=7.5, labelpad=1)
    ax.set_ylabel("Hz", fontsize=7.5, labelpad=1)
    for s in ax.spines.values():
        s.set_color("#999")
    ax.tick_params(colors="#444", length=2)
    bounds = built.plan.bounds()
    for seg, (t0, t1) in zip(built.plan.segs, bounds):
        lab = seg.label if seg.label or seg.name == "" else seg.name
        if lab:
            ax.text((t0 + t1) / 2, top * 1.02, lab, ha="center", va="bottom", fontsize=9,
                    fontweight="bold" if seg.focus else "normal", color="#16202c" if seg.focus else "#555")
        ax.plot([t0, t0], [top, top * 1.02], color="#bbb", lw=0.6, clip_on=False)
    focus_bounds = [b for s, b in zip(built.plan.segs, bounds) if s.focus]
    if focus_bounds:
        ax.axvspan(focus_bounds[0][0], focus_bounds[-1][1], ymin=0.985, ymax=1.0, color="#d08b00", lw=0)
    label_slots = []
    for kind, val, idx, text in built.marks:
        t0, t1 = bounds[idx]
        if kind in ("vot", "burst"):
            continue
        c = COLORS.get(kind, "#333")
        ax.plot([t0, t1], [val, val], color=c, lw=1.2, ls=(0, (3, 3)))
        ax.plot([t0], [val], marker=">", color=c, ms=4.5, clip_on=False)
        if not text:
            continue
        y = val
        gap = top * (0.11 if "\n" in text else 0.06)
        for other in label_slots:  # keep labels apart
            if abs(y - other) < gap:
                y = other + gap
        label_slots.append(y)
        ax.text(1.008, y / top, text, transform=ax.transAxes, fontsize=7.2 if "\n" not in text else 6.8, color=c, va="center", ha="left",
                fontweight="bold", clip_on=False)
    for kind, val, idx, text in built.marks:
        if kind == "vot":
            t0 = bounds[idx][0]
            t1 = t0 + val / 1000
            y = top * 0.93
            if val >= 10:  # a short-lag VOT of a few ms is too narrow to draw as an arrow
                ax.annotate("", xy=(t1 + 0.0005, y), xytext=(t0, y),
                            arrowprops=dict(arrowstyle="<->", color="#e07b00", lw=1.3, shrinkA=0, shrinkB=0))
            ax.text(t1 + 0.006, y, text, fontsize=7.5, color="#b35f00", va="center", fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white", ec="none", alpha=0.85))
    group_txt = group.label
    fig.text(0.085, 0.955, f"{item.title}, {group_txt}", fontsize=9, fontweight="bold", color="#16202c", va="top")
    tag = "ESTIMATED" if built.estimated else "from published averages"
    fig.text(0.86, 0.955, tag, fontsize=7.5, ha="right", va="top", fontweight="bold",
             color="#9b2c13" if built.estimated else "#2b6a2b")
    fig.text(0.085, 0.02, "Computer-made, not a recording", fontsize=6.8, color="#6b7785")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB").quantize(palette=_palette(), dither=Image.Dither.NONE)
    img.save(path, optimize=True)


def _palette():
    """A fixed palette: 40 grays for the spectrogram and text, plus the exact mark colours (so they stay true)."""
    from PIL import Image
    cols = [(round(255 * i / 39),) * 3 for i in range(40)]
    for h in list(COLORS.values()) + ["#9b2c13", "#2b6a2b", "#b35f00", "#16202c", "#6b7785", "#d08b00"]:
        cols.append(tuple(int(h[i:i + 2], 16) for i in (1, 3, 5)))
    flat = [v for c in cols for v in c]
    pal = Image.new("P", (1, 1))
    pal.putpalette(flat + flat[-3:] * (256 - len(cols)))
    return pal


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--group", nargs="*")
    ap.add_argument("--no-png", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pictures, failures = [], []
    tmp = Path(tempfile.mkdtemp(prefix="speakup-synth-"))
    items = [i for i in sb.ITEMS.values() if not args.only or i.id in args.only]
    groups = [g for g in sb.GROUPS if not args.group or g.id in args.group]
    for item in items:
        for group in groups:
            built = sb.build(item.id, group.id)
            x = synth.synthesize(built.plan)
            wav = tmp / "check.wav"
            result = check(built, wav)
            name = sb.picture_name(item.id, group.id)
            if not args.no_png:
                draw(item, group, built, x, OUT / name)
            if not result["pass"]:
                failures.append((name, [c for c in result["items"] if not c["pass"]]))
            pictures.append({
                "file": name, "item": item.id, "group": group.id, "sound": item.sound, "context": item.context,
                "age_band": group.age, "sex": group.sex, "estimated": built.estimated, "reasons": built.reasons,
                "sources": built.sources,
                "values": [{"what": v.what, "value": v.hz, "unit": v.unit, "status": v.status, "source": v.source,
                            "how": v.how} for v in built.values],
                "top_hz": built.top_hz, "seconds": round(built.plan.seconds, 3), "check": result})
            status = ("ok*" if result.get("note", "").startswith("The app's formant tracker") else "ok ")                 if result["pass"] else "FAIL"
            print(status, name, "; ".join(f"{c['what']} {c['target']}->{c['measured']}" for c in result["items"]))
    wav.unlink(missing_ok=True)
    tmp.rmdir()
    if args.only or args.group:
        print("partial run: index.json not written")
    else:
        index = {
            "version": 1,
            "about": "Computer-made spectrograms for the sound book: synthesized from published averages with a "
                     "Klatt-style formant synthesizer (speakup/synth.py), not recordings. Built by "
                     "scripts/build_synth_pictures.py.",
            "tolerance": {"formant": f"within {int(TOL_REL * 100)}% or {int(TOL_ABS)} Hz, whichever is larger",
                          "noise_peak": f"within {int(TOL_PEAK * 100)}%", "vot": f"within {int(TOL_VOT)} ms"},
            "groups": [{"id": g.id, "label": g.label, "age_band": g.age, "age_label": g.age_label, "sex": g.sex,
                        "sex_label": g.sex_label, "age_months": list(g.age_months), "estimated": g.estimated}
                       for g in sb.GROUPS],
            "query": "Find a picture with speakup.synth_book.lookup(sound, sex, age_months) or by hand: by_sound (or "
                     "variants) gives the item, age_bands the band (no band covers the age: use the nearest older "
                     "band and say so), and the picture is file <item>-<group>.png with group from groups.",
            "age_bands": [{"band": b, "from_months": lo, "to_months": hi} for b, lo, hi in sb.AGE_BANDS],
            "by_sound": {ph: it for ph, it in sb.PHONEME_ITEM.items()},
            "variants": sb.VARIANTS,
            "items": [{"id": i.id, "sound": i.sound, "context": i.context, "word": i.word, "kind": i.kind,
                       "title": i.title, "error_of": i.error_of, "section": sb.home_section(i.id),
                       "look_for": sb.LOOK_FOR[i.id], "confusable": sb.confusable(i.id)} for i in sb.ITEMS.values()],
            "sections": {k: {"items": v} for k, v in sb.SECTION_ITEMS.items()},
            "pairs": {k: [list(p) for p in v] for k, v in sb.SECTION_PAIRS.items()},
            "extra_refs": sb.EXTRA_REFS,
            "pictures": pictures,
        }
        (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    total = sum(p.stat().st_size for p in OUT.glob("*.png"))
    print(f"\n{len(pictures)} pictures, {len(failures)} failed the check, PNG total {total / 1e6:.2f} MB")
    for name, bad in failures:
        print("  FAIL", name, "; ".join(f"{c['what']} target {c['target']} measured {c['measured']} "
                                        f"(tolerance {c['tolerance']})" for c in bad))


if __name__ == "__main__":
    main()
