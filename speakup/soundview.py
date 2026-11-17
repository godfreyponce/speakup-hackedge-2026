"""The interactive sound viewer on the full analysis page: waveform, spectrogram with formant dots, pitch and
intensity on one shared time axis, a spectrum at the cursor, and a toolbar of tools the SLP turns on and off.
Built the way Praat's editor works, because that is the tool SLPs and phoneticians already read.

Nothing is imposed: by default the mouse only reads values into the readout and draws nothing. Tools:

Pointer tools (exactly one active)
- Move: drag pans, wheel zooms time, Shift+wheel zooms frequency, double-click shows everything. At the zoom
  limits (20 ms of time, 400 Hz of frequency, or everything) more zooming does nothing: no pan, no shift.
  The target sound window is a box: drag it on the waveform to slide it, drag an edge to resize it; the server
  then searches the F3-F2 gap again inside it and the measures follow ("Reset target window" undoes it).
- Cursor: option Lines (Time only, Hz only, Time and Hz). A click places a cursor that stays; the mouse does not
  carry it afterwards. "Add cursor" arms the next click. Up to 6, each its own color and number; drag to move,
  Delete or the x in the readout removes one; the readout lists each one and the differences between them.
- Scrub: hold and move; the recording plays from under the pointer at its own speed and pitch, re-joined to the
  pointer with a waveform-matched crossfade when it drifts (speakup/scrub.py); holding still stops the sound;
  dragging left plays forward pieces (or, as an option, backwards). "Play what is shown" also plays at half or
  quarter speed, same pitch.

Overlay tools (each on or off)
- Formants: the F1, F2, F3 dots and the target window box.
- Target sound: fades everything outside the target window and emphasises the formants that define the sound.
- Age ranges (off by default): published ranges for the child's age behind the target sound's formants, drawn
  only inside the target sound window and labelled "Typical F3 during a correct /ɹ/" (boys and girls apart when
  the source splits them), and the exact numbers in the readout, with the source on hover.
- Lines: join the formant points (dots, straight lines, smoothed, fitted curve), per formant; never across a
  gap of more than 3 missing frames.

Compare (a button in the toolbar)
- A small pop-up asks what to compare with (the target sound, its common errors, or any sound by search) and the
  speaker (age group, girl or boy), then draws that reference's F1, F2 and F3 curves on the spectrogram
  (speakup/compare.py). Two at most, told apart by line style. With Move, drag a curve or its bar to slide it in
  time, drag the bar's ends to stretch it; frequency is fixed. Reset alignment lines it up with the target window.

Plain JavaScript and canvas, no library, so it runs offline on the board. The spectrogram image is the same PNG
the small picture uses; the spectrum at the cursor is read back from its pixels.
"""

import base64
import json

import numpy as np

from speakup import scrub
from speakup.acoustics import TOP_HZ, Analysis
from speakup.soundpic import COLORS, DYNAMIC_DB, PITCH_COLOR, _spectrogram_png

CURSOR_COLORS = ("#e4572e", "#17bebb", "#ffc914", "#76b041", "#9c4f96", "#2e86ab")
MAX_CURSORS = len(CURSOR_COLORS)
GAP_FRAMES = 3  # the Lines tool never joins points across more missing frames than this


def _num(v, digits: int = 1):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), digits)


def _ranges(target: str | None, age_months: int | None, context: str | None) -> dict:
    from speakup import norms
    return norms.ranges_json(target, age_months, context)


def viewer_data(a: Analysis, audio_url: str | None = None, target: str | None = None,
                age_months: int | None = None, context: str | None = None, word: str | None = None,
                key: str | None = None, sex: str | None = None) -> str:
    """The analysis as JSON for the viewer script."""
    rms = a.rms if len(a.rms) == len(a.times) else np.full(len(a.times), np.nan)
    db = [None if not (r > 0) else round(20 * float(np.log10(r)), 1) for r in rms]
    data = {
        "dur": a.spec_seconds,
        "start": a.start,
        "top": a.spec_top,
        "view_top": min(TOP_HZ, a.spec_top),
        "range_db": DYNAMIC_DB,
        "t": [round(float(t), 4) for t in a.times],
        "f": [[_num(v) for v in row] for row in a.formants],
        "f0": [_num(v) for v in a.f0],
        "db": db,
        "wave": [[round(float(lo), 4), round(float(hi), 4)] for lo, hi in a.wave],
        "png": base64.b64encode(_spectrogram_png(a)).decode(),
        "gap": None if a.gap_time is None else {"t": a.gap_time, "v": a.gap_min, "f": list(a.at_gap or ())},
        "win": list(a.window) if a.window else None,
        "win_auto": list(a.auto_window) if a.auto_window else (list(a.window) if a.window else None),
        "win_manual": bool(a.window and a.auto_window and tuple(a.window) != tuple(a.auto_window)),
        "win_url": f"/analysis/{key}/window" if key else None,
        "word": word,
        "key": key,
        "sex": sex if sex in ("female", "male") else None,
        "colors": list(COLORS),
        "pitch": PITCH_COLOR,
        "audio": audio_url,
        "target": target,
        "age_months": age_months,
        "context": context,
        "ranges": _ranges(target, age_months, context),
        "cursor_colors": list(CURSOR_COLORS),
        "gap_frames": GAP_FRAMES,
    }
    # </script> can never appear in numbers, but escape the slash anyway so the JSON is safe inside a script tag.
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")


CSS = """
  .sv { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 16px; align-items: start; }
  .sv-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 14px; margin: 0 0 8px; font-size: 13px; }
  .sv-bar button, .sv-tools button, .sv-tools select { font: inherit; font-size: 13px; padding: 5px 10px;
                   border: 1px solid #c4ccd6; border-radius: 6px; background: #fff; color: #16202c; cursor: pointer; }
  .sv-bar button:hover, .sv-tools button:hover { background: #f0f4fa; }
  .sv-tools select { padding: 4px 6px; }
  .sv-bar .grp { display: inline-flex; gap: 6px; align-items: center; }
  .sv-bar .sep { width: 1px; height: 20px; background: #d9dfe7; }
  .sv-tools { border: 1px solid #d9dfe7; border-radius: 8px; background: #fbfcfd; padding: 8px 10px; margin: 0 0 10px;
              font-size: 13px; display: grid; gap: 8px; }
  .sv-row { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
  .sv-row > .lab { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #6b7785; width: 64px; }
  .sv-seg { display: inline-flex; }
  .sv-seg button { border-radius: 0; margin-left: -1px; }
  .sv-seg button:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
  .sv-seg button:last-child { border-radius: 0 6px 6px 0; }
  .sv-tools button[aria-pressed="true"] { background: #1d4f91; border-color: #1d4f91; color: #fff; }
  .sv-tools button:disabled { opacity: .45; cursor: default; }
  .sv-opts { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; color: #33404e; }
  .sv-opts label, .sv-tool label { display: inline-flex; align-items: center; gap: 5px; cursor: pointer; }
  .sv-tool { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px; padding: 3px 8px;
             border: 1px solid #e3e8ee; border-radius: 6px; background: #fff; }
  .sv-tool.on { border-color: #9fb6d6; background: #f3f7fc; }
  .sv-tool > label { font-weight: 600; color: #16202c; }
  .sv-tool .sv-opts { font-size: 12px; }
  .sv-tool:not(.on) .sv-opts { display: none; }
  .sv-opts i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; }
  .sv-status { color: #6b7785; font-size: 12px; }
  .sv-plot { position: relative; }
  .sv-plot canvas { display: block; width: 100%; border: 1px solid #d9dfe7; border-radius: 6px; cursor: default;
                    touch-action: none; outline: none; }
  .sv-plot canvas:focus-visible { border-color: #1d4f91; }
  .sv-plot canvas.grab { cursor: grabbing; }
  .sv-plot canvas.place { cursor: crosshair; }
  .sv-plot canvas.ew { cursor: ew-resize; }
  .sv-plot canvas.ns { cursor: ns-resize; }
  .sv-plot canvas.move { cursor: move; }
  .sv-plot canvas.scrub { cursor: col-resize; }
  .sv-tip { position: absolute; z-index: 2; max-width: 340px; pointer-events: none; font-size: 12px; line-height: 1.4;
            background: #16202c; color: #fff; padding: 7px 9px; border-radius: 6px; display: none; }
  .sv-read { font-size: 13px; border: 1px solid #d9dfe7; border-radius: 8px; padding: 12px 14px; background: #fbfcfd;
             position: sticky; top: 12px; }
  .sv-read h4 { margin: 0 0 6px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #6b7785; }
  .sv-read table { width: 100%; border-collapse: collapse; margin-bottom: 10px; }
  .sv-read td, .sv-read th { padding: 3px 0; border-bottom: 1px solid #edf0f4; font-variant-numeric: tabular-nums; }
  .sv-read th { text-align: right; font-size: 11px; color: #6b7785; font-weight: 600; }
  .sv-read th:first-child { text-align: left; }
  .sv-read td + td { text-align: right; font-weight: 600; }
  .sv-read .near { font-size: 15px; font-weight: 700; min-height: 22px; margin: 0 0 8px; }
  .sv-read .muted { font-size: 12px; color: #6b7785; margin: 0 0 10px; }
  .sv-read .warn { font-size: 12px; color: #7a4b00; background: #fff6e0; border: 1px solid #f0d9a8; border-radius: 6px;
                   padding: 6px 8px; margin: 0 0 8px; }
  .sv-read .src { font-size: 11px; color: #6b7785; margin: -4px 0 10px; }
  .sv-cur { border: 1px solid #e3e8ee; border-radius: 6px; padding: 6px 8px; margin: 0 0 8px; background: #fff; }
  .sv-cur.sel { border-color: #1d4f91; box-shadow: 0 0 0 1px #1d4f91; }
  .sv-cur header { display: flex; align-items: center; gap: 6px; font-weight: 700; cursor: pointer; }
  .sv-cur header b { display: inline-grid; place-items: center; width: 18px; height: 18px; border-radius: 50%;
                     color: #fff; font-size: 11px; text-shadow: 0 0 2px rgba(0,0,0,.5); }
  .sv-cur header span { font-weight: 400; color: #6b7785; font-size: 12px; flex: 1; }
  .sv-cur header button { border: 0; background: none; font-size: 15px; line-height: 1; padding: 2px 5px; cursor: pointer;
                          color: #6b7785; border-radius: 4px; }
  .sv-cur header button:hover { background: #fbe9e7; color: #b42318; }
  .sv-cur table { margin: 4px 0 0; }
  .sv-slice { margin-top: 14px; }
  .sv-slice canvas { display: block; width: 100%; border: 1px solid #d9dfe7; border-radius: 6px; }
  .sv-keys { font-size: 12px; color: #6b7785; margin: 8px 0 0; min-height: 18px; }
  .sv-bar .speed { display: inline-flex; align-items: center; gap: 5px; color: #33404e; }
  .sv-bar .speed select { font: inherit; font-size: 13px; padding: 4px 6px; border: 1px solid #c4ccd6; border-radius: 6px; }
  .sv-bar #sv-winreset { border-color: #1f4e79; color: #1f4e79; }
  .sv-toolwrap { position: relative; }
  .sv-tools .sv-cmp-btn { font-weight: 600; border-color: #1d4f91; color: #1d4f91; }
  .sv-tools .sv-cmp-btn[aria-expanded="true"] { background: #1d4f91; color: #fff; }
  .sv-tools .sv-cmp-btn small { font-weight: 400; }
  .sv-pop { position: absolute; z-index: 40; width: min(380px, 100%); background: #fff; border: 1px solid #c4ccd6; border-radius: 10px;
            box-shadow: 0 10px 28px rgba(22,32,44,.18); padding: 12px 14px; font-size: 13px; }
  .sv-pop h4 { margin: 0 0 6px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #6b7785; }
  .sv-pop-list { display: grid; gap: 2px; margin: 0 0 8px; }
  .sv-pop-opt { display: flex; align-items: center; gap: 7px; padding: 4px 6px; border-radius: 6px; cursor: pointer; }
  .sv-pop-opt:hover { background: #f0f4fa; }
  .sv-pop-opt .tag { font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .04em; color: #1d4f91;
                     background: #e6eef8; border-radius: 3px; padding: 1px 5px; }
  .sv-pop-search { display: flex; align-items: center; gap: 8px; margin: 0 0 6px; color: #33404e; }
  .sv-pop-search input { flex: 1; min-width: 0; font: inherit; padding: 5px 8px; border: 1px solid #c4ccd6; border-radius: 6px; }
  .sv-pop-who { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; margin: 8px 0; }
  .sv-pop-who select { font: inherit; padding: 4px 6px; border: 1px solid #c4ccd6; border-radius: 6px; }
  .sv-pop .sv-seg button { font: inherit; padding: 4px 12px; border: 1px solid #c4ccd6; background: #fff; cursor: pointer; }
  .sv-pop .sv-seg button[aria-pressed="true"] { background: #1d4f91; border-color: #1d4f91; color: #fff; }
  .sv-pop .note { margin: 0 0 6px; font-size: 12px; color: #44505e; }
  .sv-pop .warn, .sv-pop .err { margin: 0 0 6px; font-size: 12px; color: #7a4b00; background: #fff6e0; border: 1px solid #f0d9a8;
                                border-radius: 6px; padding: 6px 8px; }
  .sv-pop .muted { margin: 0; color: #6b7785; }
  .sv-pop-act { display: flex; gap: 8px; margin-top: 10px; }
  .sv-pop-act button { font: inherit; padding: 6px 12px; border: 1px solid #c4ccd6; border-radius: 6px; background: #fff; cursor: pointer; }
  .sv-pop-act .go { background: #1d4f91; border-color: #1d4f91; color: #fff; font-weight: 600; }
  .sv-pop-act .go:disabled { opacity: .5; cursor: default; }
  .sv-refs { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 12px; margin: 8px 0 0; font-size: 12.5px; }
  .sv-refs .lab { font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #6b7785; }
  .sv-ref { display: inline-flex; align-items: center; gap: 6px; padding: 3px 4px 3px 8px; border: 1px solid #d9dfe7;
            border-radius: 6px; background: #fff; }
  .sv-ref small { color: #7a4b00; }
  .sv-ref button { font: inherit; font-size: 12px; padding: 2px 8px; border: 1px solid #c4ccd6; border-radius: 5px; background: #fff; cursor: pointer; }
  .sv-ref button.x { border: 0; font-size: 15px; color: #6b7785; padding: 0 6px; }
  .sv-ref button.x:hover { background: #fbe9e7; color: #b42318; }
  .sv-ref-help { color: #6b7785; font-size: 12px; flex-basis: 100%; }
  @media (max-width: 1000px) { .sv { grid-template-columns: 1fr; } .sv-read { position: static; } }
"""


def viewer(a: Analysis, audio_url: str | None = None, target: str | None = None, age_months: int | None = None,
           context: str | None = None, word: str | None = None, key: str | None = None, sex: str | None = None) -> str:
    """The viewer's HTML and script. Needs CSS (above) on the page. target: the IPA sound the word tests
    (lexicon.target_of), age_months: the child's age, context: where the sound sits in the word, word: the word
    said, key: the try's key (s3, p5; the target window is saved through /analysis/<key>/window), sex: "female",
    "male" or None when the app does not know it (today it never does)."""
    wide = a.spec_top > TOP_HZ
    all_note = f" (0 to {a.spec_top / 1000:.0f} kHz)" if wide else ""
    r6k = '<button type="button" data-act="r6k">0 to 6 kHz</button>' if wide else ""
    zoom_target = (f'<button type="button" data-act="rwin">Zoom to /{target}/</button>' if a.window and target
                   else '<button type="button" data-act="rwin">Zoom to the target window</button>' if a.window else "")
    play = ('<span class="sep"></span><span class="grp"><button type="button" data-act="play">'
            '▶ Play what is shown</button><label class="speed">Speed <select id="sv-speed" '
            'title="Slower speeds keep the pitch (time-stretched, WSOLA)">'
            '<option value="1">Normal</option><option value="0.5">Half speed</option>'
            '<option value="0.25">Quarter speed</option></select></label></span>') if audio_url else ""
    reset_win = ('<button type="button" data-act="winreset" id="sv-winreset" hidden '
                 'title="Put the target sound window back where the app placed it">Reset target window</button>'
                 if a.window else "")
    return f"""<div class="sv-bar">
  <span class="grp"><button type="button" data-act="in">Zoom in</button><button type="button" data-act="out">Zoom out</button>
  <button type="button" data-act="all">Show all{all_note}</button>{r6k}{zoom_target}{reset_win}</span>{play}
</div>
<div class="sv-toolwrap"><div class="sv-tools" id="sv-tools" role="toolbar" aria-label="Viewer tools"></div>
<div class="sv-pop" id="sv-cmp-pop" role="dialog" aria-label="Compare with" hidden><form></form></div></div>
<div class="sv">
  <div>
    <div class="sv-plot"><canvas id="sv-main" tabindex="0" aria-label="Sound viewer: waveform, spectrogram with formants, pitch and intensity"></canvas>
      <div class="sv-tip" id="sv-tip" role="tooltip"></div></div>
    <div class="sv-refs" id="sv-refs" aria-live="polite" hidden></div>
    <p class="sv-keys" id="sv-keys"></p>
    <div class="sv-slice"><canvas id="sv-slice" aria-label="Spectrum at the cursor"></canvas></div>
  </div>
  <aside class="sv-read" aria-live="polite">
    <h4>Pointer</h4>
    <p class="near" id="sv-near">Point at the picture</p>
    <table id="sv-cur"></table>
    <div id="sv-cursors"></div>
    <div id="sv-ranges"></div>
    <h4>Shown</h4>
    <table id="sv-view"></table>
  </aside>
</div>
{f'<audio id="sv-audio" preload="auto" src="{audio_url}"></audio>' if audio_url else ''}
<script id="sv-data" type="application/json">{viewer_data(a, audio_url, target, age_months, context, word, key, sex)}</script>
<script src="/js/signalsmith-stretch.js"></script>
<script>{scrub.JS}</script>
<script>{_JS}</script>"""


_JS = r"""
(function () {
  const D = JSON.parse(document.getElementById("sv-data").textContent);
  const cv = document.getElementById("sv-main"), sc = document.getElementById("sv-slice");
  const ctx = cv.getContext("2d"), sctx = sc.getContext("2d");
  const audio = document.getElementById("sv-audio"), tip = document.getElementById("sv-tip");
  const N = D.t.length, FRAME = N > 1 ? D.t[1] - D.t[0] : 0.005;
  const L = 60, R = 14;
  const STRIPS = [
    { k: "wave", h: 70, label: "Waveform" },
    { k: "spec", h: 340, label: "Spectrogram" },
    { k: "pitch", h: 96, label: "Pitch (F0)" },
    { k: "int", h: 76, label: "Intensity" },
  ];
  const GAP = 10, AXIS = 26;
  let y = 22;  // room above the waveform for cursor numbers
  for (const s of STRIPS) { s.y = y; y += s.h + GAP; }
  const H = y - GAP + AXIS, TOPY = 22;
  const BASE = STRIPS[STRIPS.length - 1].y + STRIPS[STRIPS.length - 1].h;
  const v = { t0: 0, t1: D.dur, f0: 0, f1: D.view_top || D.top };
  let hover = null, drag = null, play = null;

  const f0s = D.f0.filter(x => x != null), dbs = D.db.filter(x => x != null);
  const pLo = f0s.length ? Math.max(50, Math.floor(Math.min(...f0s) * 0.8 / 10) * 10) : 75;
  const pHi = f0s.length ? Math.ceil(Math.max(...f0s) * 1.2 / 10) * 10 : 500;
  const dHi = dbs.length ? Math.ceil(Math.max(...dbs) / 5) * 5 : 0, dLo = dHi - 50;
  const wMax = Math.max(1e-6, ...D.wave.map(w => Math.max(-w[0], w[1])));

  const img = new Image();
  let pix = null;
  img.onload = () => {
    const off = document.createElement("canvas");
    off.width = img.width; off.height = img.height;
    const o = off.getContext("2d");
    o.drawImage(img, 0, 0);
    pix = o.getImageData(0, 0, img.width, img.height);
    draw();
  };
  img.src = "data:image/png;base64," + D.png;

  let W = 800, PW = 700, dpr = 1;
  function size() {
    dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth || 800; PW = W - L - R;
    cv.width = W * dpr; cv.height = H * dpr; cv.style.height = H + "px";
    const sw = sc.clientWidth || 800, sh = 190;
    sc.width = sw * dpr; sc.height = sh * dpr; sc.style.height = sh + "px";
    draw();
  }

  const strip = k => STRIPS.find(s => s.k === k);
  const xOf = t => L + (t - v.t0) / (v.t1 - v.t0) * PW;
  const tOf = x => v.t0 + (x - L) / PW * (v.t1 - v.t0);
  const yHz = f => { const s = strip("spec"); return s.y + s.h * (1 - (f - v.f0) / (v.f1 - v.f0)); };
  const hzOf = py => { const s = strip("spec"); return v.f0 + (1 - (py - s.y) / s.h) * (v.f1 - v.f0); };
  const yP = f => { const s = strip("pitch"); return s.y + s.h * (1 - (f - pLo) / (pHi - pLo)); };
  const yD = d => { const s = strip("int"); return s.y + s.h * (1 - (d - dLo) / (dHi - dLo)); };
  const frameAt = t => Math.max(0, Math.min(N - 1, Math.round((t - D.t[0]) / FRAME)));
  const fmt = (x, d = 0) => x == null || isNaN(x) ? "–" : x.toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });
  const esc = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const row = (k, val) => "<tr><td>" + k + "</td><td>" + val + "</td></tr>";
  const fname = k => '<span style="color:' + D.colors[k] + '">F' + (k + 1) + "</span>";
  // A value in a strip's own units, and back: Hz on the spectrogram and pitch, dB on intensity.
  const yUnits = { spec: [yHz, py => hzOf(py), "Hz", 0], pitch: [yP, py => pLo + (1 - (py - strip("pitch").y) / strip("pitch").h) * (pHi - pLo), "Hz", 0],
                   int: [yD, py => dLo + (1 - (py - strip("int").y) / strip("int").h) * (dHi - dLo), "dB", 1] };
  const win = () => D.win || [0, D.dur];
  const store = {
    get(k) { try { return JSON.parse(localStorage.getItem("sv." + k)); } catch (e) { return null; } },
    set(k, val) { try { localStorage.setItem("sv." + k, JSON.stringify(val)); } catch (e) { /* per-viewer convenience only */ } },
  };

  function nice(span, px, minPx) {
    const raw = span * minPx / px, p = Math.pow(10, Math.floor(Math.log10(raw)));
    for (const m of [1, 2, 5, 10]) if (m * p >= raw) return m * p;
    return 10 * p;
  }

  function clampView() {
    const span = Math.min(D.dur, Math.max(0.02, v.t1 - v.t0));
    v.t0 = Math.max(0, Math.min(D.dur - span, v.t0)); v.t1 = v.t0 + span;
    const fs = Math.min(D.top, Math.max(400, v.f1 - v.f0));
    v.f0 = Math.max(0, Math.min(D.top - fs, v.f0)); v.f1 = v.f0 + fs;
  }

  // ---- The tool registry -------------------------------------------------------------------------------------
  const SV = window.SV = {
    tools: {}, order: [], pointer: "move", opts: {}, status: "",
    register(t) {
      this.tools[t.id] = t; this.order.push(t.id);
      t.active = t.kind === "pointer" ? t.id === this.pointer : !!t.default;
      for (const o of t.options || []) this.opts[t.id + "." + o.id] = o.value;
      const saved = store.get("tool." + (t.storeKey || t.id));
      if (saved && t.kind === "overlay") {
        if (typeof saved.on === "boolean") t.active = saved.on;
        for (const o of t.options || []) if (saved.opts && o.id in saved.opts) this.opts[t.id + "." + o.id] = saved.opts[o.id];
      }
    },
    save(t) {
      const opts = {};
      for (const o of t.options || []) opts[o.id] = this.opts[t.id + "." + o.id];
      store.set("tool." + (t.storeKey || t.id), { on: t.active, opts });
    },
    setPointer(id) {
      if (!this.tools[id] || this.tools[id].kind !== "pointer") return;
      const old = this.tools[this.pointer];
      if (old && old.id !== id) { old.active = false; old.off && old.off(); }
      this.status = "";
      this.pointer = id; this.tools[id].active = true; this.tools[id].on && this.tools[id].on();
      bar(); draw();
    },
    toggle(id, on) {
      const t = this.tools[id]; if (!t || t.kind !== "overlay") return;
      t.active = on === undefined ? !t.active : !!on;
      (t.active ? t.on : t.off) && (t.active ? t.on : t.off).call(t);
      this.save(t); bar(); draw();
    },
    opt(tid, oid) { return this.opts[tid + "." + oid]; },
    setOpt(tid, oid, val) { this.opts[tid + "." + oid] = val; const t = this.tools[tid]; if (t && t.kind === "overlay") this.save(t); bar(); draw(); },
    say(msg) { this.status = msg || ""; help(); },
  };

  // ---- Base picture ------------------------------------------------------------------------------------------
  function drawBase() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.font = "11px system-ui, sans-serif";
    for (const s of STRIPS) { ctx.fillStyle = s.k === "spec" ? "#fff" : "#fcfcfd"; ctx.fillRect(L, s.y, PW, s.h); }
    let s = strip("wave"), mid = s.y + s.h / 2;
    ctx.save(); ctx.beginPath(); ctx.rect(L, s.y, PW, s.h); ctx.clip();
    ctx.strokeStyle = "#d9dfe7"; ctx.beginPath(); ctx.moveTo(L, mid); ctx.lineTo(L + PW, mid); ctx.stroke();
    ctx.strokeStyle = "#33404e"; ctx.beginPath();
    const nb = D.wave.length;
    for (let i = 0; i < nb; i++) {
      const t = (i + 0.5) / nb * D.dur; if (t < v.t0 || t > v.t1) continue;
      const x = xOf(t);
      ctx.moveTo(x, mid - D.wave[i][1] / wMax * s.h / 2); ctx.lineTo(x, mid - D.wave[i][0] / wMax * s.h / 2 + 0.5);
    }
    ctx.stroke(); ctx.restore();
    s = strip("spec");
    if (img.complete && img.width) {
      ctx.imageSmoothingEnabled = true;
      const sx = v.t0 / D.dur * img.width, sw = (v.t1 - v.t0) / D.dur * img.width;
      const sy = (1 - v.f1 / D.top) * img.height, sh = (v.f1 - v.f0) / D.top * img.height;
      ctx.drawImage(img, sx, sy, sw, sh, L, s.y, PW, s.h);
    }
    s = strip("pitch");
    ctx.save(); ctx.beginPath(); ctx.rect(L, s.y, PW, s.h); ctx.clip();
    ctx.fillStyle = D.pitch;
    for (let i = 0; i < N; i++) {
      const f = D.f0[i]; if (f == null || D.t[i] < v.t0 || D.t[i] > v.t1) continue;
      ctx.beginPath(); ctx.arc(xOf(D.t[i]), yP(f), 2.2, 0, 7); ctx.fill();
    }
    ctx.restore();
    s = strip("int");
    ctx.save(); ctx.beginPath(); ctx.rect(L, s.y, PW, s.h); ctx.clip();
    ctx.strokeStyle = "#2a6f97"; ctx.lineWidth = 1.6; ctx.beginPath();
    let on = false;
    for (let i = 0; i < N; i++) {
      const d = D.db[i]; if (d == null) { on = false; continue; }
      const x = xOf(D.t[i]), yy = yD(Math.max(dLo, d));
      on ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy); on = true;
    }
    ctx.stroke(); ctx.restore(); ctx.lineWidth = 1;
  }

  function drawAxes() {
    ctx.strokeStyle = "#b8c1cc";
    for (const st of STRIPS) ctx.strokeRect(L + 0.5, st.y + 0.5, PW - 1, st.h - 1);
    ctx.fillStyle = "#55606d"; ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.font = "11px system-ui, sans-serif";
    let s = strip("spec");
    const fStep = nice(v.f1 - v.f0, s.h, 40);
    for (let f = Math.ceil(v.f0 / fStep) * fStep; f <= v.f1 + 1e-6; f += fStep) {
      const yy = yHz(f);
      ctx.fillText(f >= 1000 ? (f / 1000).toFixed(fStep < 1000 ? 1 : 0) + "k" : f.toFixed(0), L - 6, yy);
      ctx.beginPath(); ctx.moveTo(L - 4, yy); ctx.lineTo(L, yy); ctx.stroke();
    }
    s = strip("pitch");
    const pStep = nice(pHi - pLo, s.h, 28);
    for (let f = Math.ceil(pLo / pStep) * pStep; f <= pHi; f += pStep) {
      const yy = yP(f); if (yy > s.y + 6 && yy < s.y + s.h - 6) ctx.fillText(f.toFixed(0), L - 6, yy);
    }
    for (let d = dLo + 10; d < dHi; d += 10) ctx.fillText(d.toFixed(0), L - 6, yD(d));
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    const units = { wave: "", spec: "Hz", pitch: "Hz", int: "dB" };
    for (const st of STRIPS) {
      const w = ctx.measureText(st.label).width + 10;
      ctx.fillStyle = "rgba(255,255,255,.85)"; ctx.fillRect(L + 4, st.y + 4, w, 16);
      ctx.fillStyle = "#33404e"; ctx.fillText(st.label, L + 9, st.y + 6);
      if (units[st.k]) { ctx.save(); ctx.translate(12, st.y + st.h / 2); ctx.rotate(-Math.PI / 2);
        ctx.textAlign = "center"; ctx.fillStyle = "#8a95a3"; ctx.fillText(units[st.k], 0, 0); ctx.restore(); }
    }
    const tStep = nice(v.t1 - v.t0, PW, 70);
    ctx.textAlign = "center"; ctx.fillStyle = "#55606d";
    for (let t = Math.ceil(v.t0 / tStep) * tStep; t <= v.t1 + 1e-9; t += tStep) {
      const x = xOf(t);
      ctx.beginPath(); ctx.moveTo(x, BASE); ctx.lineTo(x, BASE + 4); ctx.stroke();
      ctx.fillText(t.toFixed(tStep < 0.01 ? 3 : 2) + " s", x, BASE + 7);
    }
  }

  function clipSpec(fn) { const s = strip("spec"); ctx.save(); ctx.beginPath(); ctx.rect(L, s.y, PW, s.h); ctx.clip(); fn(s); ctx.restore(); }

  function playhead(t, color) {
    const x = xOf(t); if (x < L || x > L + PW) return;
    ctx.strokeStyle = color; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.moveTo(x, TOPY); ctx.lineTo(x, BASE); ctx.stroke(); ctx.lineWidth = 1;
  }

  // Painting is coalesced to one per frame (the board's A53 cores can't redraw everything per event). The picture is
  // cached in `still`; play and scrub only redraw their lines over it, the pointer adds its ghost and the panels.
  const still = document.createElement("canvas");
  let want = 0;  // 1: lines over the cached picture, 2: also the pointer's ghost and the panels, 3: everything
  const ask = k => { if (!want) requestAnimationFrame(paint); want = Math.max(want, k); };
  function draw() { ask(3); }
  const drawLines = () => ask(1), drawPointer = () => ask(2);
  function paint() {
    const k = want; want = 0;
    if (k === 3) {
      drawBase();
      for (const id of ["ranges", "layers", "lines", "target"]) { const t = SV.tools[id]; if (t && t.active) t.draw(); }
      drawRefs();
      drawWinBox();
      drawBandLabels();
      drawAxes();
      SV.tools.cursor.draw();  // placed cursors stay on the picture whatever the pointer tool
      if (still.width !== cv.width || still.height !== cv.height) { still.width = cv.width; still.height = cv.height; }
      still.getContext("2d").drawImage(cv, 0, 0);
    } else {
      ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.drawImage(still, 0, 0); ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    SV.tools.scrub.draw();
    if (play != null) playhead(play, "#e07b00");
    const p = SV.tools[SV.pointer];
    if (p.ghost) p.ghost();
    if (k >= 2) { readout(); slice(); }
  }
  const setHtml = (el, h) => { if (el.innerHTML !== h) el.innerHTML = h; };

  // ---- Formants (layers) -------------------------------------------------------------------------------------
  const visible = k => SV.tools.layers.active && SV.opt("layers", "show")[k];
  SV.register({
    id: "layers", label: "Formants", kind: "overlay", default: true,
    options: [{ id: "show", label: "Show", kind: "checks",
                choices: [{ v: 0, label: "F1", color: D.colors[0] }, { v: 1, label: "F2", color: D.colors[1] },
                          { v: 2, label: "F3", color: D.colors[2] }, { v: "win", label: "Target window", color: "#1f4e79" }],
                value: { 0: true, 1: true, 2: true, win: true } }],
    draw() {
      clipSpec(s => {
        if (D.gap) {
          ctx.setLineDash([4, 3]); ctx.strokeStyle = "#111";
          ctx.beginPath(); ctx.moveTo(xOf(D.gap.t), s.y); ctx.lineTo(xOf(D.gap.t), s.y + s.h); ctx.stroke(); ctx.setLineDash([]);
        }
        if (!dotsShown()) return;
        const r = dotR();
        for (let k = 0; k < 3; k++) {
          if (!visible(k)) continue;
          ctx.fillStyle = D.colors[k];
          for (let i = 0; i < N; i++) {
            const f = D.f[i][k]; if (f == null || D.t[i] < v.t0 || D.t[i] > v.t1) continue;
            ctx.beginPath(); ctx.arc(xOf(D.t[i]), yHz(f), r, 0, 7); ctx.fill();
          }
        }
      });
    },
  });
  const dotR = () => Math.max(1.8, Math.min(4, 2.2 * Math.sqrt(D.dur / (v.t1 - v.t0))));
  const dotsShown = () => !(SV.tools.lines && SV.tools.lines.active && SV.opt("lines", "join") !== "dots" && !SV.opt("lines", "dots"));

  // ---- Lines: ways to join the formant points ----------------------------------------------------------------
  // Runs of tracked frames for one formant; a gap of more than D.gap_frames missing frames starts a new run.
  function runs(k) {
    const out = []; let cur = [], last = -99;
    for (let i = 0; i < N; i++) {
      if (D.f[i][k] == null) continue;
      if (i - last - 1 > D.gap_frames && cur.length) { out.push(cur); cur = []; }
      cur.push(i); last = i;
    }
    if (cur.length) out.push(cur);
    return out;
  }
  function median(a) { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
  // Least-squares polynomial through one run (degree 1 to 3 by length), sampled finely for drawing.
  function fit(ts, fs) {
    const n = ts.length, d = n >= 12 ? 3 : n >= 6 ? 2 : 1, a = ts[0], b = ts[n - 1], span = (b - a) || 1;
    const xs = ts.map(t => 2 * (t - a) / span - 1), m = d + 1;
    const A = Array.from({ length: m }, () => new Array(m + 1).fill(0));
    for (let i = 0; i < n; i++) {
      const p = []; for (let j = 0; j < m; j++) p.push(Math.pow(xs[i], j));
      for (let r = 0; r < m; r++) { for (let c = 0; c < m; c++) A[r][c] += p[r] * p[c]; A[r][m] += p[r] * fs[i]; }
    }
    for (let c = 0; c < m; c++) {  // Gaussian elimination with partial pivoting
      let piv = c; for (let r = c + 1; r < m; r++) if (Math.abs(A[r][c]) > Math.abs(A[piv][c])) piv = r;
      [A[c], A[piv]] = [A[piv], A[c]];
      if (Math.abs(A[c][c]) < 1e-12) return null;
      for (let r = 0; r < m; r++) if (r !== c) { const f = A[r][c] / A[c][c]; for (let j = c; j <= m; j++) A[r][j] -= f * A[c][j]; }
    }
    const coef = A.map((r, i) => r[m] / r[i]);
    const pts = [], steps = Math.max(8, n * 3);
    for (let s = 0; s <= steps; s++) {
      const x = -1 + 2 * s / steps; let val = 0;
      for (let j = 0; j < m; j++) val += coef[j] * Math.pow(x, j);
      pts.push([a + (x + 1) / 2 * span, val]);
    }
    return pts;
  }
  function linePoints(k, run, how) {
    const ts = run.map(i => D.t[i]), fs = run.map(i => D.f[i][k]);
    if (how === "straight") return ts.map((t, j) => [t, fs[j]]);
    if (how === "smooth") return ts.map((t, j) => [t, median(fs.slice(Math.max(0, j - 2), j + 3))]);
    if (how === "fit") return run.length >= 3 ? fit(ts, fs) : ts.map((t, j) => [t, fs[j]]);
    return [];
  }
  SV.register({
    id: "lines", label: "Lines", kind: "overlay",
    options: [{ id: "join", label: "Join points", kind: "select", value: "straight",
                choices: [{ v: "dots", label: "Dots only" }, { v: "straight", label: "Straight lines" },
                          { v: "smooth", label: "Smoothed (5-frame median)" }, { v: "fit", label: "Fitted curve" }] },
              { id: "which", label: "Formants", kind: "checks",
                choices: [{ v: 0, label: "F1", color: D.colors[0] }, { v: 1, label: "F2", color: D.colors[1] }, { v: 2, label: "F3", color: D.colors[2] }],
                value: { 0: true, 1: true, 2: true } },
              { id: "dots", label: "Keep the dots", kind: "toggle", value: true }],
    draw() {
      const how = SV.opt("lines", "join"); if (how === "dots") return;
      clipSpec(() => {
        ctx.lineWidth = 2; ctx.lineJoin = "round";
        for (let k = 0; k < 3; k++) {
          if (!SV.opt("lines", "which")[k]) continue;
          ctx.strokeStyle = D.colors[k];
          for (const run of runs(k)) {
            const pts = linePoints(k, run, how); if (!pts || pts.length < 2) continue;
            ctx.beginPath(); pts.forEach(([t, f], j) => j ? ctx.lineTo(xOf(t), yHz(f)) : ctx.moveTo(xOf(t), yHz(f))); ctx.stroke();
          }
        }
        ctx.lineWidth = 1;
      });
    },
  });

  // ---- Target sound highlight --------------------------------------------------------------------------------
  const cue = (D.ranges && D.ranges.cue) || { key: [], measure: "", say: "" };
  const keyIdx = (cue.key || []).map(k => ({ F1: 0, F2: 1, F3: 2 })[k]).filter(k => k != null);
  SV.register({
    id: "target", label: "Target sound", kind: "overlay",
    draw() {
      if (!D.target) return;
      const [a, b] = win();
      clipSpec(s => {
        // Fade everything outside the target window so the window stands out.
        ctx.fillStyle = "rgba(255,255,255,.5)";
        ctx.fillRect(L, s.y, Math.max(0, xOf(a) - L), s.h);
        ctx.fillRect(xOf(b), s.y, Math.max(0, L + PW - xOf(b)), s.h);
        // (The Nov 4 yellow shading between the key formants is gone: the owner found it did not help.)
        const r = dotR() + 1.6;
        for (const k of keyIdx) {
          for (let i = 0; i < N; i++) {
            const f = D.f[i][k]; if (f == null || D.t[i] < a || D.t[i] > b) continue;
            ctx.beginPath(); ctx.arc(xOf(D.t[i]), yHz(f), r, 0, 7);
            ctx.fillStyle = D.colors[k]; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = "#111"; ctx.stroke();
          }
        }
        ctx.lineWidth = 1;
        const lab = "/" + D.target + "/: " + (cue.key && cue.key.length ? cue.key.join(" and ") : "no formants named") +
                    (cue.say ? ". " + cue.say : "") + (D.win ? "" : " (whole word: no target window)");
        ctx.font = "bold 12px system-ui, sans-serif";
        const w = Math.min(PW - 12, ctx.measureText(lab).width + 12), x = Math.max(L + 4, Math.min(L + PW - w - 4, xOf(a)));
        ctx.fillStyle = "rgba(22,32,44,.85)"; ctx.fillRect(x, s.y + s.h - 26, w, 20);
        ctx.fillStyle = "#fff"; ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillText(lab, x + 6, s.y + s.h - 16, w - 12);
        ctx.font = "11px system-ui, sans-serif";
      });
    },
  });

  // ---- The target sound window: a box the SLP can drag -------------------------------------------------------
  // Drawn over the waveform and the spectrogram. With the Move tool: drag the box on the waveform to slide it,
  // drag either edge (waveform or spectrogram) to resize it. On release the server searches the F3-F2 gap again
  // inside the new window and sends back the measures; "Reset target window" asks for the app's own window.
  const MIN_WIN = 0.02, EDGE = 6;
  const winShown = () => !!D.win && ((SV.tools.layers.active && SV.opt("layers", "show").win) || SV.tools.target.active);
  function drawWinBox() {
    if (!winShown()) return;
    const [a, b] = D.win, xa = xOf(a), xb = xOf(b), w = strip("wave"), s = strip("spec");
    const live = drag && drag.kind === "win", col = D.win_manual || live ? "#b45309" : "#1f4e79";
    ctx.save(); ctx.beginPath(); ctx.rect(L, TOPY, PW, s.y + s.h - TOPY); ctx.clip();
    ctx.fillStyle = hexA(col, live ? 0.18 : 0.10); ctx.fillRect(xa, w.y, xb - xa, w.h);
    ctx.strokeStyle = col; ctx.lineWidth = 2; ctx.strokeRect(xa, w.y + 1, xb - xa, w.h - 2);
    ctx.lineWidth = 1.5; ctx.setLineDash([5, 4]);
    ctx.beginPath(); ctx.moveTo(xa, s.y); ctx.lineTo(xa, s.y + s.h); ctx.moveTo(xb, s.y); ctx.lineTo(xb, s.y + s.h); ctx.stroke();
    ctx.setLineDash([]);
    for (const x of [xa, xb]) { ctx.fillStyle = col; ctx.fillRect(x - 3, w.y + w.h / 2 - 11, 6, 22); }  // grips
    const lab = (D.target ? "/" + D.target + "/ window" : "Target window") + (D.win_manual ? ", moved by you" : ", automatic");
    ctx.font = "bold 11px system-ui, sans-serif"; ctx.textAlign = "left"; ctx.textBaseline = "middle";
    const tw = ctx.measureText(lab).width + 10, tx = Math.max(L + 2, Math.min(L + PW - tw - 2, xa + 6));
    ctx.fillStyle = "rgba(255,255,255,.92)"; ctx.fillRect(tx, w.y + w.h - 18, tw, 15);  // bottom: the strip name is top left
    ctx.fillStyle = col; ctx.fillText(lab, tx + 5, w.y + w.h - 10);
    ctx.restore(); ctx.font = "11px system-ui, sans-serif"; ctx.lineWidth = 1;
  }
  function hitWin(p) {
    if (!winShown() || !D.win || SV.pointer !== "move") return null;
    if (p.strip !== "wave" && p.strip !== "spec") return null;
    const xa = xOf(D.win[0]), xb = xOf(D.win[1]);
    if (Math.abs(p.x - xa) <= EDGE) return "l";
    if (Math.abs(p.x - xb) <= EDGE) return "r";
    if (p.strip === "wave" && p.x > xa && p.x < xb) return "move";
    return null;
  }
  function dragWin(d, p) {
    const dt = p.t - d.t, len = d.b - d.a;
    let a = d.a, b = d.b;
    if (d.mode === "move") { a = Math.max(0, Math.min(D.dur - len, d.a + dt)); b = a + len; }
    else if (d.mode === "l") a = Math.max(0, Math.min(d.b - MIN_WIN, d.a + dt));
    else b = Math.min(D.dur, Math.max(d.a + MIN_WIN, d.b + dt));
    D.win = [a, b];
  }
  function applyWindow(j) {
    D.win = j.window; D.gap = j.gap; D.win_manual = !!j.manual;
    for (const r of refs) if (!r.manual) autoFit(r);  // references not moved by hand follow the window
    legend();
    const m = document.getElementById("sv-measures"); if (m && j.measures_html != null) m.innerHTML = j.measures_html;
    const n = document.getElementById("sv-notes");
    if (n && j.notes) { n.innerHTML = j.notes.map(t => "<li>" + esc(t) + "</li>").join(""); n.hidden = !j.notes.length; }
    winButtons(); draw();
    if (window.parent !== window) window.parent.postMessage({ type: "sv-window", gapText: j.gap_text }, location.origin);
  }
  function sendWindow(fields) {
    if (!D.win_url) { SV.say("This view is not tied to a try, so the window is not saved and the measures stay as they were."); draw(); return; }
    SV.say("Measuring again inside the new window...");
    fetch(D.win_url, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
                       body: new URLSearchParams(fields).toString() })
      .then(r => { if (!r.ok) throw new Error("the server answered HTTP " + r.status); return r.json(); })
      .then(j => { if (!j.ok) throw new Error(j.error || "the server refused it"); applyWindow(j); SV.say(j.manual ? "Target window moved. The F3-F2 gap and the measures now use it." : "Target window back where the app put it."); })
      .catch(err => { SV.say("Could not save the target window: " + err.message + ". The measures below did not change."); });
  }
  function winButtons() { const b = document.getElementById("sv-winreset"); if (b) b.hidden = !D.win_manual; }
  winButtons();

  // ---- Compare: reference F1, F2, F3 curves drawn on the spectrogram ------------------------------------------
  // (research: Speak-Up-Docs/Archive/Research/compare-overlay-research.md). The Compare tool opens a small pop-up that asks
  // what to compare with (the target sound, its common errors, or any sound by search) and the speaker (age group,
  // girl or boy). The reference's formant curves (speakup/compare.py, /compare/curves/<item>-<group>.json, the same
  // data behind the sound book's pictures) are drawn in the formant colors as thick, see-through, dashed or dotted
  // lines. They start lined up with the target window (the reference's own sound stretched over the window). With
  // the Move tool the SLP slides a reference left or right (drag a curve or its bar at the top of the spectrogram)
  // and stretches it in time (drag either end of the bar). Frequency is fixed: a reference never moves up or down.
  const REF_STYLES = [{ dash: [11, 6], cap: "butt", name: "dashed" }, { dash: [1, 7], cap: "round", name: "dotted" }];
  const refs = [];  // { n, item, group, d (curves), a (s, where its sound starts), k (stretch), manual, style }
  const CMP = { data: null, loading: null, pop: document.getElementById("sv-cmp-pop"), btn: null, choice: null, band: null, sex: null, q: "" };
  // Revision 5 (research: Speak-Up-Docs/Archive/Research/r-tracking-and-compare.md): a reference is drawn as its whole
  // syllable (its sound plus the vowel next to it), and its frequencies are sized to this speaker: every value is
  // multiplied by r.s = this speaker's vowel F3 / the reference's vowel F3, measured on the same vowel. The SLP still
  // never moves it up or down by hand; with no clear vowel it stays at the group's values ("not sized").
  const SP = r => r.d.span || r.d.focus;                             // the reference time span that is drawn
  const refSpan = r => Math.max(0.005, SP(r)[1] - SP(r)[0]);
  const refX = (r, tr) => r.a + (tr - SP(r)[0]) * r.k;               // reference time to viewer time
  const refStep = r => r.d.t.length > 1 ? r.d.t[1] - r.d.t[0] : 0.005;
  function refAt(r, t) {  // the reference's F1, F2, F3 (sized) at viewer time t, or null
    const tr = SP(r)[0] + (t - r.a) / r.k;
    if (tr < SP(r)[0] - 1e-6 || tr > SP(r)[1] + 1e-6) return null;
    const F = r.d.f[Math.round((tr - r.d.t[0]) / refStep(r))];
    return F ? F.map(x => x == null ? null : x * (r.s || 1)) : null;
  }
  const isR = r => /[ɹɝɚ]/.test((r.d.sound || "") + " " + (r.d.title || "")) || /rabbit|carrot|-r$|-er$/.test(r.item);
  function refName(r) {
    const it = CMP.data && CMP.data.items.find(x => x.id === r.item);
    return (it ? it.title : r.d.title) + ", " + r.d.group_label.toLowerCase();
  }
  function autoAlign(r) {
    // Line the reference's own sound up with the target window: it starts there and is stretched to its length.
    if (D.win) { r.k = (D.win[1] - D.win[0]) / Math.max(0.005, r.d.focus[1] - r.d.focus[0]); r.a = D.win[0] - (r.d.focus[0] - SP(r)[0]) * r.k; }
    else {
      const first = D.t.find((t, i) => D.f[i].some(x => x != null));
      r.a = first != null ? first : 0; r.k = 1;
    }
    r.manual = false;
  }
  function fitOnce(r, fixedScale) {
    // Slide and stretch the reference's syllable over the recording, near the target window, and keep the place where
    // its F1, F2, F3 follow the measured dots best (mean distance in log Hz, F1 counting half; frames with no dots
    // cost a little). With fixedScale null each place also gets its own best overall size (0.55 to 1.6, a man against a 6-year-old is about 0.68), so the
    // shape decides the place, not the speaker's size. Only a shift and one even stretch: the curves are never bent.
    const span = refSpan(r), s0 = SP(r)[0], step = refStep(r), fl = Math.max(0.005, r.d.focus[1] - r.d.focus[0]);
    const wl = D.win ? D.win[1] - D.win[0] : null;
    const lo = D.win ? Math.max(0, D.win[0] - 0.15) : 0, hi = D.win ? Math.min(D.dur, D.win[1] + 0.3) : D.dur;
    const kMin = wl ? 0.5 * wl / fl : 0.4, kMax = wl ? 2 * wl / fl : 3;
    let best = null;
    for (let ki = 0; ki <= 24; ki++) {
      const k = kMin * Math.pow(kMax / kMin, ki / 24), len = span * k;
      // Only the reference's r has to land inside: its vowels may hang past a short, cropped word (Nov 11).
      const fa = (r.d.focus[0] - s0) * k, fk = fl * k;
      if (fk > hi - lo) break;
      for (let a = lo - fa; a + fa + fk <= hi + 1e-9; a += 0.005) {
        const pairs = [];
        let tot = 0;
        for (let i = frameAt(a); i < N && D.t[i] <= a + len; i++) {
          if (D.t[i] < a) continue;
          tot++;
          const F = r.d.f[Math.round((s0 + (D.t[i] - a) / k - r.d.t[0]) / step)];
          if (!F) continue;
          for (let q = 0; q < 3; q++) {
            const m = D.f[i][q], f = F[q];
            if (m != null && f != null && m > 0 && f > 0) pairs.push([Math.log(m / f), q === 0 ? 0.5 : 1, i]);
          }
        }
        const n = new Set(pairs.map(x => x[2])).size;
        if (n < 4) continue;
        const w = pairs.reduce((z, x) => z + x[1], 0);
        let ls = fixedScale != null ? Math.log(fixedScale) : pairs.reduce((z, x) => z + x[0] * x[1], 0) / w;
        ls = Math.max(Math.log(0.55), Math.min(Math.log(1.6), ls));
        const err = pairs.reduce((z, x) => z + Math.abs(x[0] - ls) * x[1], 0) / w;
        const score = err + 0.25 * (1 - n / tot) + 0.03 * Math.abs(Math.log(wl ? k * fl / wl : k));
        if (!best || score < best.score) best = { a, k, score, s: Math.exp(ls) };
      }
    }
    return best;
  }
  function speakerVowelF3(r) {
    // This speaker's F3 on the reference's own vowel (its steady half), where the fitted reference puts it.
    if (!r.d.vowel || !r.d.vowel_f3) return null;
    const t0 = refX(r, r.d.vowel.t0), t1 = refX(r, r.d.vowel.t1), f3 = [];
    for (let i = frameAt(t0); i < N && D.t[i] <= t1; i++) if (D.t[i] >= t0 && D.f[i][2] != null) f3.push(D.f[i][2]);
    if (f3.length < 3) return null;
    f3.sort((x, y) => x - y);
    return f3[Math.floor(f3.length / 2)];
  }
  function autoFit(r) {
    // Place it by shape first, then size it to the speaker's own vowel, then place it again at that size.
    r.s = 1; r.spkF3 = null; r.sized = false;
    const first = fitOnce(r, null);
    if (!first) { autoAlign(r); r.fitted = false; r.manual = false; return; }
    r.a = first.a; r.k = first.k; r.fitted = true;
    const v = speakerVowelF3(r);
    if (v) {
      r.s = Math.max(0.55, Math.min(1.6, v / r.d.vowel_f3)); r.spkF3 = v; r.sized = true;
      const again = fitOnce(r, r.s);
      if (again) { r.a = again.a; r.k = again.k; }
    }
    r.manual = false;
  }
  function drawRBand() {
    // A correct /ɹ/: F3 drops to about two thirds of the speaker's own vowel F3 (0.66 for men and women, 0.67 to
    // 0.69 for children 10 to 12; Hagiwara: 60 to 80%). Shaded at the reference's r, with a line at two thirds.
    const r = refs.find(x => x.sized && isR(x));
    if (!r) return;
    const xa = xOf(refX(r, r.d.focus[0])), xb = xOf(refX(r, r.d.focus[1]));
    const yTop = yHz(0.8 * r.spkF3), yBot = yHz(0.6 * r.spkF3), yMid = yHz(0.66 * r.spkF3);
    ctx.save();
    ctx.fillStyle = hexA(D.colors[2], 0.13); ctx.fillRect(xa, yTop, xb - xa, yBot - yTop);
    ctx.strokeStyle = hexA(D.colors[2], 0.75); ctx.lineWidth = 1; ctx.setLineDash([]);
    ctx.strokeRect(xa + 0.5, yTop + 0.5, xb - xa - 1, yBot - yTop - 1);
    ctx.setLineDash([2, 3]); ctx.beginPath(); ctx.moveTo(xa, yMid); ctx.lineTo(xb, yMid); ctx.stroke();
    ctx.restore();
    if (xb - xa > 40) bandTag("r target F3", xa + 2, yTop - 9, D.colors[2], false);
  }
  function refBarY(i) { return strip("spec").y + 24 + i * 18; }  // under the strip's name
  function drawRefs() {
    if (!refs.length) return;
    clipSpec(s => {
      drawRBand();
      refs.forEach((r, i) => {
        const sty = REF_STYLES[r.style], fa = SP(r)[0], fb = SP(r)[1], sc = r.s || 1;
        for (let k = 0; k < 3; k++) {
          // One set of lines: the reference's syllable, its sound plus the vowel next to it, sized to the speaker.
          // A pale halo first so the line reads on dark and light, then the colored line.
          for (const [col, w, alpha] of [["#ffffff", 7, 0.6], [D.colors[k], 3.5, 0.9]]) {
            ctx.save(); ctx.globalAlpha = alpha; ctx.strokeStyle = col; ctx.lineWidth = w; ctx.setLineDash(sty.dash);
            ctx.lineCap = sty.cap; ctx.lineJoin = "round"; ctx.beginPath();
            let on = false;
            r.d.f.forEach((F, j) => {
              const tr = r.d.t[j], f = F[k];
              if (f == null || tr < fa - 1e-6 || tr > fb + 1e-6) { on = false; return; }
              const x = xOf(refX(r, tr)), yy = yHz(f * sc);
              on ? ctx.lineTo(x, yy) : ctx.moveTo(x, yy); on = true;
            });
            ctx.stroke(); ctx.restore();
          }
        }
        // The bar at the top: the reference's time span, with a round handle at each end to stretch it.
        const y = refBarY(i), xa = xOf(refX(r, fa)), xb = xOf(refX(r, fb));
        const live = drag && drag.kind === "ref" && drag.r === r, ink = live ? "rgb(180,83,9)" : "#16202c";
        ctx.fillStyle = live ? "rgba(180,83,9,.9)" : "rgba(22,32,44,.78)";
        ctx.fillRect(xa, y + 3, Math.max(2, xb - xa), 8);
        for (const x of [xa, xb]) {
          ctx.beginPath(); ctx.arc(x, y + 7, 7, 0, 7); ctx.fillStyle = "#fff"; ctx.fill();
          ctx.lineWidth = 2.5; ctx.strokeStyle = ink; ctx.stroke();
          ctx.fillStyle = ink; ctx.fillRect(x - 0.75, y + 3.5, 1.5, 7);
        }
        ctx.font = "bold 10px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        const lab = String(r.n);
        if (xb - xa > 30) { ctx.fillStyle = "#fff"; ctx.fillText(lab, (xa + xb) / 2, y + 7.5); }
        else { ctx.textAlign = "left"; ctx.fillStyle = "rgba(22,32,44,.9)"; ctx.fillText(lab, xb + 10, y + 7.5); }
        ctx.lineWidth = 1; ctx.font = "11px system-ui, sans-serif";
      });
    });
  }
  function hitRef(p) {
    if (!refs.length || SV.pointer !== "move" || p.strip !== "spec") return null;
    const GRIP = 10;
    for (let i = 0; i < refs.length; i++) {
      const r = refs[i], y = refBarY(i);
      if (p.y >= y - 4 && p.y <= y + 18) {
        const xa = xOf(refX(r, SP(r)[0])), xb = xOf(refX(r, SP(r)[1]));
        if (Math.abs(p.x - xa) <= GRIP) return { r, mode: "l" };
        if (Math.abs(p.x - xb) <= GRIP) return { r, mode: "r" };
        if (p.x > xa && p.x < xb) return { r, mode: "move" };
      }
    }
    for (const r of refs) {  // on one of its curves: slide it; near either end of the curves: stretch it
      const xa = xOf(refX(r, SP(r)[0])), xb = xOf(refX(r, SP(r)[1]));
      if (p.x < xa - GRIP || p.x > xb + GRIP) continue;
      for (const dx of [-2, 0, 2]) {
        const F = refAt(r, tOf(Math.max(xa, Math.min(xb, p.x + dx)))); if (!F) continue;
        for (let k = 0; k < 3; k++) if (F[k] != null && Math.abs(yHz(F[k]) - p.y) <= 7) {
          if (xb - xa > 3 * GRIP && Math.abs(p.x - xa) <= GRIP) return { r, mode: "l" };
          if (xb - xa > 3 * GRIP && Math.abs(p.x - xb) <= GRIP) return { r, mode: "r" };
          return { r, mode: "move" };
        }
      }
    }
    return null;
  }
  function dragRef(d, p) {
    const r = d.r, span = refSpan(r), start = d.a, end = d.a + span * d.k, dt = p.t - d.t;
    if (d.mode === "move") r.a = d.a + dt;  // time only: the frequencies never change
    else if (d.mode === "l") { const ns = Math.min(end - MIN_WIN, start + dt); r.k = (end - ns) / span; r.a = ns; }
    else { const ne = Math.max(start + MIN_WIN, end + dt); r.k = (ne - start) / span; }
  }
  const refsEl = document.getElementById("sv-refs");
  function legend() {
    if (!refs.length) { refsEl.hidden = true; refsEl.innerHTML = ""; return; }
    refsEl.hidden = false;
    refsEl.innerHTML = '<span class="lab">Reference</span>' + refs.map(r => {
      const sty = REF_STYLES[r.style];
      return '<span class="sv-ref" data-n="' + r.n + '"><svg width="38" height="12" aria-hidden="true"><line x1="2" y1="6" x2="36" y2="6" stroke="#16202c" stroke-width="3.5" stroke-linecap="' +
        sty.cap + '" stroke-dasharray="' + sty.dash.join(" ") + '"/></svg><b>' + r.n + "</b> " + esc(refName(r)) +
        (r.d.estimated ? ' <small title="Values estimated from published data for an older group or by scaling">estimated</small>' : "") +
        (r.sized ? ' <small title="Every frequency times ' + r.s.toFixed(2) + ': this speaker\'s vowel F3 (' + fmt(r.spkF3) + ' Hz) over the reference\'s (' + fmt(r.d.vowel_f3) + ' Hz)">sized to this speaker (x' + r.s.toFixed(2) + ')</small>'
                 : ' <small title="No clear vowel next to the sound to measure, so these are the group\'s own values">not sized to this speaker</small>') +
        (r.manual ? ' <small>moved by you</small>' : r.fitted ? ' <small>fitted automatically</small>' : ' <small>no dots to fit, placed on the target window</small>') +
        '<button type="button" data-ref-reset="' + r.n + '" title="Find the best spot and length again">Fit again</button>' +
        '<button type="button" class="x" data-ref-x="' + r.n + '" aria-label="Remove reference ' + r.n + '" title="Remove">×</button></span>';
    }).join("") + '<span class="sv-ref-help">Colors are F1, F2, F3 as on the dots. The curves show the sound and the vowel next to it, sized to this speaker\'s own vowel and placed where they match the dots best. For an r, the shaded band is where a correct r\'s F3 dips: 60 to 80% of this speaker\'s vowel F3 (dotted line at two thirds). Drag the curves or the bar to slide them; drag a round handle (or either end of the curves) to stretch or squeeze them in time. Up and down stay fixed.</span>';
  }
  refsEl.addEventListener("click", e => {
    const x = e.target.closest("[data-ref-x]"), rs = e.target.closest("[data-ref-reset]");
    if (x) { const i = refs.findIndex(r => r.n === +x.dataset.refX); if (i >= 0) refs.splice(i, 1); legend(); bar(); draw(); }
    else if (rs) { const r = refs.find(r => r.n === +rs.dataset.refReset); if (r) { autoFit(r); legend(); draw(); } }
  });
  async function addRef(item, group) {
    const r0 = refs.find(r => r.item === item && r.group === group);
    if (r0) { autoFit(r0); legend(); draw(); return r0; }
    const res = await fetch("/compare/curves/" + encodeURIComponent(item + "-" + group) + ".json");
    const d = await res.json().catch(() => ({ error: "the server sent no data" }));
    if (!res.ok || d.error) throw new Error(d.error || "HTTP " + res.status);
    if (refs.length >= 2) refs.shift();  // two at most: the older one makes way
    const used = refs.map(r => r.style), n = [1, 2].find(k => !refs.some(r => r.n === k));
    const r = { n, item, group, d, a: 0, k: 1, manual: false, style: used.includes(0) ? 1 : 0 };
    autoFit(r); refs.push(r); refs.sort((x, y) => x.n - y.n);
    legend(); bar(); draw();
    return r;
  }

  // The pop-up.
  function cmpUrl() {
    const q = new URLSearchParams({ target: D.target || "", age_months: D.age_months == null ? "" : String(D.age_months),
                                    sex: D.sex || "", context: D.context || "", word: D.word || "" });
    return "/compare/data?" + q.toString();
  }
  function loadCmp() {
    if (!CMP.loading) CMP.loading = fetch(cmpUrl()).then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(d => { CMP.data = d; return d; }, e => { CMP.loading = null; throw e; });
    return CMP.loading;
  }
  const sexWords = band => band === "adult" ? [["female", "Woman"], ["male", "Man"]] : [["female", "Girl"], ["male", "Boy"]];
  function popHtml() {
    const d = CMP.data, df = d.defaults, items = d.items, byId = Object.fromEntries(items.map(i => [i.id, i]));
    const first = df.item ? [[df.item, "Target"], ...df.compare.map(c => [c, "Error"])] : [];
    if (df.item) for (const rel of (byId[df.item].related || [])) if (byId[rel] && byId[rel].kind === "error" && !first.some(f => f[0] === rel)) first.push([rel, "Error"]);
    // Search: every word must match; a sound typed on its own (w, sh, ee) ranks first, then words that start with it.
    const STOP = ["in", "as", "a", "an", "the", "with", "of", "said", "sound"];
    const q = CMP.q.trim().toLowerCase(), words = q.replace(/[\/"]/g, " ").split(/\s+/).filter(w => w && !STOP.includes(w));
    const score = i => {
      const tokens = (i.title + " " + (i.word || "")).toLowerCase().replace(/[\/"(),]/g, " ").split(/\s+/).filter(Boolean);
      let total = 0;
      for (const w of words) {
        const s = i.sound.toLowerCase() === w ? 100 : tokens.includes(w) ? 60 : w.length > 2 && tokens.some(t => t.startsWith(w)) ? 30 : (i.word || "").toLowerCase().startsWith(w) ? 20
                : w.length > 2 && (i.title + " " + i.id).toLowerCase().includes(w) ? 10 : 0;
        if (!s) return 0;
        total += s;
      }
      return total;
    };
    const found = words.length ? items.filter(i => !first.some(f => f[0] === i.id)).map(i => [i, score(i)]).filter(x => x[1] > 0)
      .sort((a, b) => b[1] - a[1]).slice(0, 6).map(x => x[0]) : [];
    if (!CMP.choice || !byId[CMP.choice]) CMP.choice = first.length ? first[0][0] : null;
    const radio = (id, tag) => '<label class="sv-pop-opt"><input type="radio" name="sv-cmp-item" value="' + esc(id) + '"' +
      (CMP.choice === id ? " checked" : "") + ">" + (tag ? '<span class="tag">' + tag + "</span>" : "") + esc(byId[id].title) + "</label>";
    let h = '<h4 id="sv-cmp-title">Compare with</h4>';
    if (df.missing) h += '<p class="warn">' + esc(df.missing) + "</p>";
    h += '<div class="sv-pop-list" role="radiogroup" aria-labelledby="sv-cmp-title">' + first.map(([id, tag]) => radio(id, tag)).join("") + "</div>";
    h += '<label class="sv-pop-search">Other sound <input type="search" id="sv-cmp-q" value="' + esc(CMP.q) +
         '" placeholder="Search, for example w, l, s, heed" autocomplete="off"></label>';
    h += '<div class="sv-pop-list" id="sv-cmp-found">' + (words.length ? (found.length ? found.map(i => radio(i.id, "")).join("") : '<p class="muted">No sound matches.</p>') : "") + "</div>";
    const band = CMP.band, sex = CMP.sex;
    h += '<div class="sv-pop-who"><label>Age <select id="sv-cmp-band">' + d.bands.map(b => '<option value="' + b.band + '"' + (b.band === band ? " selected" : "") + ">" +
         esc(b.band === "adult" ? "Adults" : b.label) + "</option>").join("") + '</select></label><span class="sv-seg" role="group" aria-label="Sex">' +
         sexWords(band).map(([v, l]) => '<button type="button" data-sex="' + v + '" aria-pressed="' + (sex === v) + '">' + l + "</button>").join("") + "</span></div>";
    const notes = [band === df.band ? df.warning : null, df.sex_known ? null : df.sex_note,
                   refs.length >= 2 ? "Two references are on the picture, so this one replaces reference " + refs[0].n + "." : null].filter(Boolean);
    h += notes.map(t => '<p class="note">' + esc(t) + "</p>").join("");
    h += '<p class="err" id="sv-cmp-err" hidden></p><div class="sv-pop-act"><button type="submit" class="go"' + (CMP.choice ? "" : " disabled") +
         '>Draw the curves</button><button type="button" data-close>Cancel</button></div>';
    return h;
  }
  function renderPop() { CMP.pop.querySelector("form").innerHTML = popHtml(); }
  function placePop() {
    const wrap = CMP.pop.parentNode, b = toolsEl.querySelector("[data-compare]") || CMP.btn, wb = wrap.getBoundingClientRect(), bb = b.getBoundingClientRect();
    CMP.pop.style.top = (bb.bottom - wb.top + 6) + "px";
    CMP.pop.style.left = Math.max(0, Math.min(wb.width - CMP.pop.offsetWidth, bb.left - wb.left)) + "px";
  }
  function openPop() {
    CMP.btn = toolsEl.querySelector("[data-compare]");
    CMP.pop.hidden = false; CMP.pop.querySelector("form").innerHTML = '<p class="muted">Loading the sounds...</p>'; placePop();
    loadCmp().then(d => {
      if (CMP.band == null) { CMP.band = d.defaults.band; CMP.sex = d.defaults.sex; }
      renderPop(); placePop();
      const f = CMP.pop.querySelector("input[name=sv-cmp-item]:checked") || CMP.pop.querySelector("#sv-cmp-q"); if (f) f.focus();
    }, e => { CMP.pop.querySelector("form").innerHTML = '<p class="warn">Could not load the sounds to compare with: ' + esc(e.message) +
                                                         '.</p><div class="sv-pop-act"><button type="button" data-close>Close</button></div>'; });
    bar();
  }
  function closePop() { if (CMP.pop.hidden) return; CMP.pop.hidden = true; bar(); const b = toolsEl.querySelector("[data-compare]"); if (b) b.focus(); }
  CMP.pop.addEventListener("click", e => {
    if (e.target.closest("[data-close]")) closePop();
    const s = e.target.closest("[data-sex]"); if (s) { CMP.sex = s.dataset.sex; renderPop(); }
  });
  CMP.pop.addEventListener("change", e => {
    if (e.target.name === "sv-cmp-item") { CMP.choice = e.target.value; CMP.pop.querySelector(".go").disabled = false; }
    if (e.target.id === "sv-cmp-band") { CMP.band = e.target.value; renderPop(); }
  });
  CMP.pop.addEventListener("input", e => {
    if (e.target.id !== "sv-cmp-q") return;
    CMP.q = e.target.value; const pos = e.target.selectionStart; renderPop();
    const q = CMP.pop.querySelector("#sv-cmp-q"); q.focus(); q.setSelectionRange(pos, pos);
  });
  CMP.pop.addEventListener("keydown", e => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); closePop(); } });
  CMP.pop.querySelector("form").addEventListener("submit", e => {
    e.preventDefault();
    const d = CMP.data; if (!d || !CMP.choice) return;
    const group = d.group_of[CMP.band + "|" + CMP.sex], err = CMP.pop.querySelector("#sv-cmp-err");
    const go = CMP.pop.querySelector(".go"); go.disabled = true; go.textContent = "Drawing...";
    addRef(CMP.choice, group).then(() => { closePop(); SV.say(""); },
      ex => { err.hidden = false; err.textContent = "Could not draw it: " + ex.message + "."; go.disabled = false; go.textContent = "Draw the curves"; });
  });
  document.addEventListener("pointerdown", e => {
    if (!CMP.pop.hidden && !CMP.pop.contains(e.target) && !e.target.closest("[data-compare]")) closePop();
  });
  function refRows(t) {
    return refs.map(r => {
      const F = refAt(r, t);
      return row("Reference " + r.n, F && F.some(x => x != null) ? fmt(F[0]) + ", " + fmt(F[1]) + ", " + fmt(F[2]) + " Hz" : "no formants here");
    }).join("");
  }

  // ---- Age ranges (published ranges for this age) ------------------------------------------------------------
  const RG = D.ranges || { status: "nofile", message: "No range data on this machine", bands: [] };
  const bandColor = m => ({ F1: D.colors[0], F2: D.colors[1], F3: D.colors[2], F0: D.pitch })[m] || "#6b4c9a";
  // Draw the key formants' bands; a sound with no formant key (s, sh) draws its noise bands.
  const drawn = () => RG.bands.filter(b => (cue.key && cue.key.length ? cue.key.includes(b.measure) :
                                           ["spectral_peak", "spectral_mean"].includes(b.measure)) || b.measure === "F0");
  let bandBoxes = [];
  function hexA(hex, a) { const n = parseInt(hex.slice(1), 16); return "rgba(" + (n >> 16) + "," + (n >> 8 & 255) + "," + (n & 255) + "," + a + ")"; }
  // "6 to 7" for whole years (72 to 95 months), else the source's own label ("6;3 to 7;2").
  const ageWords = bd => bd.age_min != null && bd.age_max != null && bd.age_min % 12 === 0 && bd.age_max % 12 === 11
    ? (bd.age_min / 12 === (bd.age_max - 11) / 12 ? String(bd.age_min / 12) : bd.age_min / 12 + " to " + (bd.age_max - 11) / 12) : bd.age;
  let bandLabels = [];
  // The band labels are drawn last, over the dots, so they stay readable.
  function drawBandLabels() { if (SV.tools.ranges.active) for (const l of bandLabels) bandTag(...l); }
  function bandTag(text, x, y, col, right) {
    ctx.font = "bold 10px system-ui, sans-serif"; ctx.textBaseline = "middle"; ctx.textAlign = "left";
    const w = ctx.measureText(text).width + 8, x0 = right ? x - w : x;
    ctx.fillStyle = "rgba(255,255,255,.92)"; ctx.fillRect(x0, y - 7, w, 14);
    ctx.fillStyle = col; ctx.fillText(text, x0 + 4, y);
  }
  SV.register({
    // Parked (Nov 5): the owner found it gave almost no useful information, so it is off and not in the toolbar
    // (SV.overlays below) until it is wanted again. The code stays so it can come back by adding "ranges" there.
    id: "ranges", label: "Age ranges", kind: "overlay", default: false, storeKey: "ranges.parked",
    options: [{ id: "show", label: "Show", kind: "select", value: "both",
                choices: [{ v: "bands", label: "Bands" }, { v: "numbers", label: "Numbers" }, { v: "both", label: "Both" }] }],
    draw() {
      bandBoxes = []; bandLabels = [];
      // The band means "during a correct target sound", so it is drawn only inside the target sound window.
      if (RG.status !== "ok" || SV.opt("ranges", "show") === "numbers" || !D.win) return;
      const [a, b] = D.win, x0 = Math.max(L, xOf(a)), x1 = Math.min(L + PW, xOf(b));
      if (x1 <= x0) return;
      for (const bd of drawn()) {
        const pitch = bd.measure === "F0", yy = pitch ? yP : yHz, st = strip(pitch ? "pitch" : "spec"), col = bandColor(bd.measure);
        const parts = bd.boys && bd.girls ? [["boys", bd.boys, []], ["girls", bd.girls, [5, 3]]] : [["boys and girls together", bd.together, [2, 3]]];
        ctx.save(); ctx.beginPath(); ctx.rect(L, st.y, PW, st.h); ctx.clip();
        for (const [who, r, dash] of parts) {
          const ya = yy(r.hi), yb = yy(r.lo);
          ctx.fillStyle = hexA(col, parts.length > 1 ? 0.11 : 0.16); ctx.fillRect(x0, ya, x1 - x0, yb - ya);
          ctx.strokeStyle = hexA(col, 0.85); ctx.setLineDash(dash); ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.moveTo(x0, ya); ctx.lineTo(x1, ya); ctx.moveTo(x0, yb); ctx.lineTo(x1, yb); ctx.stroke();
          ctx.setLineDash([]);
          bandBoxes.push({ x0, x1, y0: ya, y1: yb, bd, who, r });
        }
        // Plain labels: what the band is above it, then who each edge is for, boys at the left, girls at the right.
        const top = Math.min(...parts.map(p => yy(p[1].hi))), clipY = [st.y, st.h];
        const tag = (text, x, y, c, right) => bandLabels.push([text, x, Math.max(clipY[0] + 8, Math.min(clipY[0] + clipY[1] - 8, y)), c, right]);
        tag("Typical " + bd.label + " during a correct /" + (D.target || "?") + "/", x0 + 2, top - 9, col, false);
        if (parts.length > 1) {
          tag("boys, age " + ageWords(bd) + " (solid)", x0 + 2, yy(bd.boys.hi) + 9, col, false);
          tag("girls, age " + ageWords(bd) + " (dashed)", x1 - 2, yy(bd.girls.hi) + (Math.abs(yy(bd.girls.hi) - yy(bd.boys.hi)) < 16 ? 25 : 9), col, true);
        } else tag("boys and girls together, age " + ageWords(bd), x0 + 2, top + 9, col, false);
        ctx.restore(); ctx.lineWidth = 1;
      }
    },
  });
  function bandTip(p) {
    if (!SV.tools.ranges.active || drag) return null;
    const hit = bandBoxes.filter(b => p.x >= b.x0 && p.x <= b.x1 && p.y >= b.y0 - 2 && p.y <= b.y1 + 2);
    if (!hit.length) return null;
    return hit.map(h => "<b>" + esc(h.bd.label) + ", " + esc(h.bd.age) + ", " + esc(h.who) + ":</b> " + fmt(h.r.lo) + " to " + fmt(h.r.hi) +
      " Hz" + (h.r.mean != null ? " (mean " + fmt(h.r.mean) + (h.r.sd != null ? ", SD " + fmt(h.r.sd) : "") + ")" : "")).join("<br>") +
      "<br>Source: " + esc(hit[0].bd.cite);
  }
  // "Surname 2012", "Surname and Other 2012" or "Surname et al. 2012" from an APA-style citation.
  function shortCite(c) {
    const year = (c.match(/\((\d{4})\)/) || ["", ""])[1], part = c.split("(")[0].replace(/,?\s*Jr\.,?/g, "");
    const names = part.split(/\.,\s+(?:and\s+)?|\.\s+and\s+/).map(a => a.split(",")[0].trim()).filter(Boolean);
    const who = names.length > 2 ? names[0] + " et al." : names.join(" and ");
    return who + (year ? " " + year : "");
  }
  function rangeCell(r) { return r ? fmt(r.lo) + " to " + fmt(r.hi) : "–"; }
  function rangesHtml() {
    const t = SV.tools.ranges;
    if (!t.active || SV.opt("ranges", "show") === "bands") return "";
    let h = "<h4>Typical values during a correct /" + esc(D.target || "?") + "/" + (D.age_months != null ? ", child " + Math.floor(D.age_months / 12) + ";" + (D.age_months % 12) : "") + "</h4>";
    if (RG.status !== "ok") return h + '<p class="warn">' + esc(RG.message) + "</p>";
    if (!D.win && SV.opt("ranges", "show") !== "numbers") h += '<p class="warn">This word has no target sound window, so no band is drawn on the picture. The numbers still apply.</p>';
    if (RG.warning) h += '<p class="warn">' + esc(RG.warning) + "</p>";
    const split = RG.bands.some(b => b.boys && b.girls);
    h += "<table><tr><th></th>" + (split ? "<th>Boys</th><th>Girls</th>" : "<th>Range</th>") + "</tr>";
    const srcs = [];
    for (const b of RG.bands) {
      const cells = b.boys && b.girls ? "<td>" + rangeCell(b.boys) + "</td><td>" + rangeCell(b.girls) + "</td>"
                  : split ? '<td colspan="2" title="The source does not split boys and girls">' + rangeCell(b.together) + " (together)</td>"
                  : "<td>" + rangeCell(b.together) + "</td>";
      h += '<tr title="' + esc(b.age + ". " + b.cite + (b.note ? " " + b.note : "")) + '"><td>' +
           '<span style="color:' + bandColor(b.measure) + '">' + esc(b.label) + "</span></td>" + cells + "</tr>";
      if (!srcs.find(s => s.cite === b.cite)) srcs.push(b);
    }
    h += "</table>";
    if (split) h += '<p class="src">On the picture, inside the target window only: solid edges are boys, dashed edges are girls.</p>';
    for (const m of RG.missing || []) h += '<p class="warn">' + esc(m) + ": no published range found for children.</p>";
    if (!split && RG.bands.length) h += '<p class="src">Boys and girls together: the source does not split them.</p>';
    h += '<p class="src">Hz, mean plus or minus 1 SD (about 2 in 3 typical speakers fall inside). Outside the range is not "wrong". ' +
         srcs.map(s => '<span title="' + esc(s.cite) + '">' + esc(shortCite(s.cite)) + "</span>, " + esc(s.age)).join("; ") + ". Point at a band for the full source.</p>";
    return h;
  }

  // ---- Cursor tool -------------------------------------------------------------------------------------------
  const cursors = [];  // { n, color, mode: "x" | "y" | "xy", t, strip, val }
  let armed = false, selected = null;
  const MODES = { x: "Time only", y: "Hz only", xy: "Time and Hz" };
  const hasX = c => c.mode !== "y", hasY = c => c.mode !== "x" && c.strip && yUnits[c.strip] && c.val != null;
  const cy = c => yUnits[c.strip][0](c.val);
  function nextNumber() { for (let n = 1; n <= D.cursor_colors.length; n++) if (!cursors.find(c => c.n === n)) return n; return null; }
  function arm() {
    if (nextNumber() == null) { SV.say("At most " + D.cursor_colors.length + " cursors. Remove one first."); return; }
    armed = true; if (SV.pointer !== "cursor") SV.setPointer("cursor"); else { bar(); draw(); }
  }
  function place(p) {
    const n = nextNumber(); if (n == null) return;
    const mode = SV.opt("cursor", "lines");
    const st = yUnits[p.strip] ? p.strip : null;
    const c = { n, color: D.cursor_colors[n - 1], mode: mode !== "x" && !st ? "x" : mode, t: p.t, strip: st,
                val: st ? yUnits[st][1](p.y) : null };
    cursors.push(c); cursors.sort((a, b) => a.n - b.n); selected = c; armed = false;
    if (mode !== "x" && !st) SV.say("That spot has no Hz or dB scale, so cursor " + n + " is a time line only.");
    else SV.say("");
    bar(); draw();
  }
  function removeCursor(c) {
    const i = cursors.indexOf(c); if (i < 0) return;
    cursors.splice(i, 1); if (selected === c) selected = cursors[cursors.length - 1] || null; bar(); draw();
  }
  function hitCursor(p) {
    let best = null, bd = 6;
    for (const c of cursors) {
      if (hasX(c)) { const d = Math.abs(p.x - xOf(c.t)); if (d < bd) { bd = d; best = { c, axis: "x" }; } }
      if (hasY(c) && p.strip === c.strip) { const d = Math.abs(p.y - cy(c)); if (d < bd) { bd = d; best = { c, axis: "y" }; } }
    }
    if (best && best.c.mode === "xy" && hasY(best.c) && p.strip === best.c.strip &&
        Math.abs(p.x - xOf(best.c.t)) < 6 && Math.abs(p.y - cy(best.c)) < 6) best.axis = "xy";
    return best;
  }
  function drawCursorLines(c, ghost) {
    const col = ghost ? "#7b8794" : c.color, wide = !ghost && c === selected;
    ctx.save(); ctx.strokeStyle = col; ctx.lineWidth = wide ? 2.2 : 1.5; ctx.setLineDash(ghost ? [4, 3] : []);
    if (hasX(c)) {
      const x = xOf(c.t);
      if (x >= L && x <= L + PW) {
        ctx.beginPath(); ctx.moveTo(x + 0.5, TOPY); ctx.lineTo(x + 0.5, BASE); ctx.stroke();
        if (!ghost) {  // number above the waveform, time under the axis
          ctx.setLineDash([]); ctx.fillStyle = col; ctx.beginPath(); ctx.arc(x, TOPY - 10, 9, 0, 7); ctx.fill();
          ctx.fillStyle = "#fff"; ctx.font = "bold 11px system-ui, sans-serif"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.strokeStyle = "rgba(0,0,0,.35)"; ctx.lineWidth = 2; ctx.strokeText(String(c.n), x, TOPY - 9.5); ctx.fillText(String(c.n), x, TOPY - 9.5);
          const tl = c.t.toFixed(3) + " s"; ctx.font = "bold 11px system-ui, sans-serif";
          const tw = ctx.measureText(tl).width + 8;
          ctx.fillStyle = col; ctx.fillRect(Math.min(L + PW - tw, Math.max(L, x - tw / 2)), BASE + 4, tw, 17);
          ctx.fillStyle = "#111"; ctx.textBaseline = "top"; ctx.fillText(tl, Math.min(L + PW - tw / 2, Math.max(L + tw / 2, x)), BASE + 7);
        }
      }
    }
    if (hasY(c)) {
      const st = strip(c.strip), yy = cy(c);
      if (yy >= st.y && yy <= st.y + st.h) {
        ctx.strokeStyle = col; ctx.lineWidth = wide ? 2.2 : 1.5; ctx.setLineDash(ghost ? [4, 3] : []);
        ctx.beginPath(); ctx.moveTo(L, yy + 0.5); ctx.lineTo(L + PW, yy + 0.5); ctx.stroke();
        const u = yUnits[c.strip], lab = (ghost ? "" : c.n + ": ") + fmt(c.val, u[3]) + " " + u[2];
        ctx.setLineDash([]); ctx.font = "bold 11px system-ui, sans-serif";
        const w = ctx.measureText(lab).width + 8;
        ctx.fillStyle = col; ctx.fillRect(L + PW - w - 2, yy - 8, w, 16);  // inside the picture, on the right edge
        ctx.fillStyle = ghost ? "#fff" : "#111"; ctx.textAlign = "right"; ctx.textBaseline = "middle"; ctx.fillText(lab, L + PW - 6, yy);
      }
    }
    if (!ghost && hasX(c)) {  // ring the formants of the frame the readout uses
      const i = frameAt(c.t);
      for (let k = 0; k < 3; k++) {
        const f = D.f[i][k]; if (f == null || !visible(k) || f < v.f0 || f > v.f1) continue;
        ctx.strokeStyle = D.colors[k]; ctx.lineWidth = 2; ctx.setLineDash([]);
        ctx.beginPath(); ctx.arc(xOf(D.t[i]), yHz(f), 5.5, 0, 7); ctx.stroke();
      }
    }
    ctx.restore(); ctx.font = "11px system-ui, sans-serif";
  }
  SV.register({
    id: "cursor", label: "Cursor", kind: "pointer",
    options: [{ id: "lines", label: "Lines", kind: "select", value: "xy",
                choices: [{ v: "x", label: "Time only" }, { v: "y", label: "Hz only" }, { v: "xy", label: "Time and Hz" }] }],
    actions: [{ id: "add", label: "Add cursor", run: arm, disabled: () => nextNumber() == null || armed },
              { id: "clear", label: "Remove all", run: () => { cursors.length = 0; selected = null; armed = SV.pointer === "cursor"; bar(); draw(); },
                disabled: () => !cursors.length }],
    on() { if (!cursors.length) armed = true; },
    off() { armed = false; },
    draw() { for (const c of cursors) drawCursorLines(c, false); },
    ghost() {
      if (!armed || !hover) return;
      const mode = SV.opt("cursor", "lines"), st = yUnits[hover.strip] ? hover.strip : null;
      drawCursorLines({ mode: mode !== "x" && !st ? "x" : mode, t: hover.t, strip: st, val: st ? yUnits[st][1](hover.y) : null }, true);
    },
    help() {
      return armed ? "Click the picture to place cursor " + nextNumber() + " (" + MODES[SV.opt("cursor", "lines")] + "). Esc cancels."
        : "Drag a cursor to move it. Click a cursor or press 1 to " + D.cursor_colors.length +
          " to pick it; arrow keys move it, Delete removes it. Add cursor places another.";
    },
  });

  // ---- Scrub tool (Web Audio) --------------------------------------------------------------------------------
  // The engine is speakup/scrub.py (window.SVScrub; research: Speak-Up-Docs/Archive/Research/scrub-rethink.md). Revision 5:
  // one continuous stream, time-stretched so its speed follows the hand while the pitch stays the recording's own;
  // slow hand, slow sound; fast hand, fast sound; holding still glides to silence. It never waits and never jumps.
  // Dragging left plays the recording backwards by default. The playhead shows where the sound is, not the pointer.
  // If the stretcher cannot load (no AudioWorklet), the older "follow" engine is used and the viewer says so.
  const S = { ac: null, P: null, loading: null, timer: null, E: null, t: null, slow: null, N: null, making: null,
              old: false, drawn: null,
              stats: { forward: 0, reversed: 0, starts: 0, jumps: 0, stops: 0, slow: 0, turns: 0, fallback: 0 } };
  function audioCtx() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error("This browser has no Web Audio, so scrubbing cannot play.");
    if (!S.ac) S.ac = new AC();
    if (S.ac.state === "suspended") S.ac.resume();
    return S.ac;
  }
  function loadAudio() {
    if (!D.audio) return Promise.reject(new Error("No sound file for this try."));
    if (!S.loading) {
      S.loading = (async () => {
        const r = await fetch(D.audio);
        if (!r.ok) throw new Error("Could not load the sound (HTTP " + r.status + ").");
        S.P = window.SVScrub.prepare(await audioCtx().decodeAudioData(await r.arrayBuffer()));
      })();
      S.loading.catch(e => { S.loading = null; SV.say(e.message); });
    }
    return S.loading;
  }
  function stretchReady() {
    // The two stretchers are made once per sound (a WASM AudioWorklet, about 0.1 s the first time) and kept.
    if (S.N || S.old) return Promise.resolve();
    if (!S.making) {
      S.making = window.SVScrub.stretchers(S.ac, S.P).then(N => { S.N = N; }, err => {
        S.old = true; S.stats.fallback++;
        console.warn("Scrub: smooth scrubbing is unavailable, using the older engine:", err);
        SV.say("Smooth scrubbing could not start (" + err.message + "), so the older scrub is used.");
      });
    }
    return S.making;
  }
  function startEngine() {
    if (!S.P || S.t == null || S.E) return;
    if (!S.N && !S.old) { stretchReady().then(startEngine); return; }
    const back = SV.opt("scrub", "back");
    S.E = S.N ? window.SVScrub.stretchEngine(S.ac, S.P, S.N, { back, stats: S.stats })
              : window.SVScrub.engine(S.ac, S.P, { back, stats: S.stats });
    S.E.down(D.start + S.t, S.ac.currentTime); S.E.tick(S.ac.currentTime);
    if (!S.timer) S.timer = setInterval(() => {
      if (!S.E) return;
      const m = S.E.mode(); S.E.tick(S.ac.currentTime);
      const h = S.E.heard ? S.E.heard() : null;
      if (S.E.mode() !== m || (h != null && (S.drawn == null || Math.abs(xOf(h - D.start) - xOf(S.drawn - D.start)) >= 1))) drawLines();
    }, 15);
  }
  function stopScrub() {
    if (S.timer) clearInterval(S.timer);
    if (S.E) S.E.up(S.ac.currentTime);
    S.timer = null; S.t = null; S.E = null; S.drawn = null;
  }
  // Slow motion of the visible part at 0.5x or 0.25x with the pitch kept: WSOLA, rendered ahead of time.
  const SLOW = { grain: 0.046, hop: 0.023, tol: 0.012 };
  function stretched(t0, t1, speed) {
    const P = S.P, sr = P.sr, x = P.mono, n = Math.round(SLOW.grain * sr), hop = Math.round(SLOW.hop * sr), tol = Math.round(SLOW.tol * sr);
    const a = Math.max(0, Math.round(t0 * sr)), b = Math.min(x.length, Math.round(t1 * sr));
    const len = Math.max(n, Math.ceil((b - a) / speed)), out = new Float32Array(len + n), wsum = new Float32Array(len + n);
    const w = new Float32Array(n).map((_, i) => 0.5 - 0.5 * Math.cos(2 * Math.PI * i / n));  // sums to 1 at half overlap
    let nat = null;
    for (let o = 0; o < len; o += hop) {
      const tg = a + Math.round(o * speed);
      if (tg >= b) break;
      const st = window.SVScrub.bestStart(P, false, nat, tg, n, tol, false);
      for (let i = 0; i < n && st + i < x.length; i++) { out[o + i] += x[st + i] * w[i]; wsum[o + i] += w[i]; }
      nat = st + hop;
    }
    for (let i = 0; i < out.length; i++) if (wsum[i] > 1) out[i] /= wsum[i];
    return out.subarray(0, len);
  }
  function stopSlow() { if (S.slow) { const src = S.slow.src; S.slow = null; play = null; src.stop(); } }
  function playSlow(speed) {
    stopSlow();
    try { audioCtx(); } catch (err) { SV.say(err.message); return; }
    SV.say("Preparing slow motion...");
    loadAudio().then(() => {
      const t0 = D.start + v.t0, t1 = D.start + v.t1, data = stretched(t0, t1, speed);
      const out = S.ac.createBuffer(1, data.length, S.P.sr); out.getChannelData(0).set(data);
      const src = S.ac.createBufferSource(); src.buffer = out; src.connect(S.ac.destination);
      const began = S.ac.currentTime + 0.02; src.start(began);
      S.slow = { src, began, speed, t0: v.t0, t1: v.t1, seconds: data.length / S.P.sr };
      S.stats.slow++;
      SV.say("Playing at " + (speed === 0.5 ? "half" : "quarter") + " speed, same pitch.");
      src.onended = () => { if (S.slow && S.slow.src === src) { S.slow = null; play = null; SV.say(""); draw(); } };
      const follow = () => {
        if (!S.slow || S.slow.src !== src) return;
        play = Math.min(S.slow.t1, S.slow.t0 + Math.max(0, S.ac.currentTime - began) * speed); drawLines(); requestAnimationFrame(follow);
      };
      requestAnimationFrame(follow);
    }, err => SV.say("Could not play slow motion: " + err.message));
  }
  SV.register({
    id: "scrub", label: "Scrub", kind: "pointer",
    storeKey: "scrub.v4",  // revision 4 changed the default for dragging left
    options: [{ id: "back", label: "Dragging left", kind: "select", value: "reverse",
                choices: [{ v: "reverse", label: "Plays it backwards" }, { v: "forward", label: "Plays short pieces forward" }] }],
    on() { if (!D.audio) SV.say("No sound file for this try, so there is nothing to scrub."); },
    off() { stopScrub(); SV.say(""); },
    down(e, p) {
      try { audioCtx(); } catch (err) { SV.say(err.message); return; }
      stopSlow();
      S.t = p.t;
      if (!S.P) SV.say("Loading the sound...");
      loadAudio().then(() => { if (!S.old) SV.say(""); startEngine(); }, () => {});
      startEngine(); draw();
    },
    move(e, p) {
      if (S.t == null) return;
      S.t = p.t;
      if (S.E) { S.E.move(D.start + p.t, S.ac.currentTime); S.E.tick(S.ac.currentTime); }
      drawLines();
    },
    up() { stopScrub(); draw(); },
    draw() {
      if (S.t == null || SV.pointer !== "scrub") return;
      const h = S.E && S.E.heard ? S.E.heard() : null;  // the stretcher's place in the recording: what you hear now
      S.drawn = h;
      playhead(h != null ? h - D.start : S.t, "#c2185b");
    },
    help() {
      return "Hold the button and move across the picture: the recording plays as fast as you move, slow or quick, " +
             "always at its own pitch. The pink line shows where the sound is. Stop moving and it fades out. " +
             "Speed in the top bar plays what is shown slower without changing the pitch.";
    },
  });

  // ---- Move tool ---------------------------------------------------------------------------------------------
  SV.register({
    id: "move", label: "Move", kind: "pointer",
    help() {
      return "Drag to move around. Wheel zooms time, Shift+wheel zooms frequency. Double-click shows everything. Drag a placed cursor to move it. " +
             "Drag the target sound window on the waveform to slide it, or its edges to resize it." +
             (refs.length ? " Drag a reference curve or its bar to slide it in time, the bar's ends to stretch it." : "");
    },
  });
  // Toolbar order: pointer tools as Move, Cursor. Scrub is off the toolbar until it works on the board (Nov 11).
  SV.pointers = ["move", "cursor"];
  SV.overlays = ["layers", "target", "lines"];  // "ranges" parked, see the Age ranges tool

  // ---- Toolbar -----------------------------------------------------------------------------------------------
  const toolsEl = document.getElementById("sv-tools");
  function optHtml(t, o) {
    const val = SV.opt(t.id, o.id), name = t.id + "." + o.id;
    if (o.kind === "select")
      return '<label>' + esc(o.label) + ' <select data-opt="' + name + '">' + o.choices.map(c =>
        '<option value="' + c.v + '"' + (c.v === val ? " selected" : "") + ">" + esc(c.label) + "</option>").join("") + "</select></label>";
    if (o.kind === "checks")
      return o.choices.map(c => '<label><input type="checkbox" data-check="' + name + '" data-v="' + c.v + '"' + (val[c.v] ? " checked" : "") + ">" +
        (c.color ? '<i style="background:' + c.color + '"></i>' : "") + esc(c.label) + "</label>").join("");
    if (o.kind === "toggle")
      return '<label><input type="checkbox" data-toggle="' + name + '"' + (val ? " checked" : "") + ">" + esc(o.label) + "</label>";
    return "";
  }
  function bar() {
    const p = SV.tools[SV.pointer];
    let h = '<div class="sv-row"><span class="lab">Pointer</span><span class="sv-seg">' + SV.pointers.map(id =>
      '<button type="button" data-pointer="' + id + '" aria-pressed="' + (SV.pointer === id) + '">' + esc(SV.tools[id].label) + "</button>").join("") + "</span>";
    h += '<span class="sv-opts">' + (p.options || []).map(o => optHtml(p, o)).join("") +
         (p.actions || []).map(a => '<button type="button" data-action="' + a.id + '"' + (a.disabled && a.disabled() ? " disabled" : "") + ">" + esc(a.label) + "</button>").join("") +
         "</span></div>";
    h += '<div class="sv-row"><span class="lab">Show</span>' + SV.overlays.map(id => {
      const t = SV.tools[id];
      return '<span class="sv-tool' + (t.active ? " on" : "") + '"><label><input type="checkbox" data-tool="' + id + '"' + (t.active ? " checked" : "") + ">" +
        esc(t.label) + '</label><span class="sv-opts">' + (t.options || []).map(o => optHtml(t, o)).join("") + "</span></span>";
    }).join("") + '<button type="button" class="sv-cmp-btn" data-compare aria-haspopup="dialog" aria-expanded="' + !CMP.pop.hidden +
      '" title="Draw the F1, F2 and F3 curves of a typical sound on the spectrogram">Compare' +
      (refs.length ? " <small>(" + refs.length + " shown)</small>" : "") + "</button></div>";
    toolsEl.innerHTML = h;
    help();
  }
  toolsEl.addEventListener("click", e => {
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.pointer) SV.setPointer(b.dataset.pointer);
    else if (b.dataset.compare !== undefined) { if (CMP.pop.hidden) openPop(); else closePop(); }
    else if (b.dataset.action) { const a = (SV.tools[SV.pointer].actions || []).find(a => a.id === b.dataset.action); if (a) a.run(); }
  });
  toolsEl.addEventListener("change", e => {
    const el = e.target;
    if (el.dataset.tool) SV.toggle(el.dataset.tool, el.checked);
    else if (el.dataset.opt) { const [t, o] = el.dataset.opt.split("."); SV.setOpt(t, o, el.value); }
    else if (el.dataset.toggle) { const [t, o] = el.dataset.toggle.split("."); SV.setOpt(t, o, el.checked); }
    else if (el.dataset.check) { const [t, o] = el.dataset.check.split("."); SV.setOpt(t, o, { ...SV.opt(t, o), [el.dataset.v]: el.checked }); }
  });
  function help() {
    const p = SV.tools[SV.pointer];
    document.getElementById("sv-keys").textContent = (SV.status ? SV.status + " " : "") + (p.help ? p.help() : "") + " Keys: + and - zoom, 0 shows everything.";
  }

  // ---- Readout -----------------------------------------------------------------------------------------------
  function valueAt(c) {
    const u = yUnits[c.strip]; return u ? fmt(u[1](c.y), u[3]) + " " + u[2] : "";
  }
  function nearest(c) {
    let best = null, bd = 100;
    const consider = (t, yy, what, val) => {
      const dx = xOf(t) - xOf(c.t), dy = yy - c.y, d = dx * dx + dy * dy;
      if (d < bd) { bd = d; best = { t, what, val }; }
    };
    const i0 = frameAt(tOf(xOf(c.t) - 12)), i1 = frameAt(tOf(xOf(c.t) + 12));
    for (let i = i0; i <= i1; i++) {
      if (c.strip === "spec") for (let k = 0; k < 3; k++) {
        const f = D.f[i][k]; if (f != null && visible(k)) consider(D.t[i], yHz(f), "F" + (k + 1), f);
      }
      if (c.strip === "pitch" && D.f0[i] != null) consider(D.t[i], yP(D.f0[i]), "F0 (pitch)", D.f0[i]);
      if (c.strip === "int" && D.db[i] != null) consider(D.t[i], yD(D.db[i]), "Intensity", D.db[i]);
    }
    return best;
  }
  function frameRows(t) {
    const i = frameAt(t), F = D.f[i];
    return row("Frame", D.t[i].toFixed(3) + " s") +
      row(fname(0) + ", " + fname(1) + ", " + fname(2), fmt(F[0]) + ", " + fmt(F[1]) + ", " + fmt(F[2]) + " Hz") +
      row("F3-F2", fmt(F[1] != null && F[2] != null ? F[2] - F[1] : null) + " Hz") +
      row('<span style="color:' + D.pitch + '">Pitch</span>', fmt(D.f0[i]) + " Hz") +
      row("Intensity", fmt(D.db[i], 1) + " dB");
  }
  function cursorsHtml() {
    if (!cursors.length) return "";
    let h = "<h4>Placed cursors</h4>";
    for (const c of cursors) {
      let rows = "";
      if (hasX(c)) rows += row("Time", c.t.toFixed(3) + " s") ;
      if (hasY(c)) rows += row(c.strip === "spec" ? "Frequency" : c.strip === "pitch" ? "Pitch line" : "Intensity line", fmt(c.val, yUnits[c.strip][3]) + " " + yUnits[c.strip][2]);
      if (hasX(c)) rows += frameRows(c.t);
      h += '<div class="sv-cur' + (c === selected ? " sel" : "") + '" data-n="' + c.n + '"><header data-pick="' + c.n + '"><b style="background:' + c.color + '">' + c.n +
           "</b>Cursor " + c.n + "<span>" + MODES[c.mode] + '</span><button type="button" data-del="' + c.n + '" aria-label="Remove cursor ' + c.n + '">×</button></header>' +
           "<table>" + rows + "</table></div>";
    }
    if (cursors.length > 1) {
      let rows = "";
      // Every pair that can be compared: time between two time lines, Hz (or dB) between two lines on one strip.
      for (let i = 0; i < cursors.length; i++) for (let j = i + 1; j < cursors.length; j++) {
        const a = cursors[i], b = cursors[j], bits = [];
        if (hasX(a) && hasX(b)) bits.push((b.t - a.t >= 0 ? "+" : "") + fmt((b.t - a.t) * 1000, 0) + " ms");
        if (hasY(a) && hasY(b) && a.strip === b.strip) bits.push((b.val - a.val >= 0 ? "+" : "") + fmt(b.val - a.val, yUnits[a.strip][3]) + " " + yUnits[a.strip][2]);
        if (bits.length) rows += row(a.n + " to " + b.n, bits.join(", "));
      }
      h += "<h4>Between cursors</h4>" + (rows ? "<table>" + rows + "</table>" : '<p class="muted">These cursors measure different things (time and Hz), so there is nothing to subtract.</p>');
    }
    return h;
  }
  document.getElementById("sv-cursors").addEventListener("click", e => {
    const del = e.target.closest("[data-del]"), pick = e.target.closest("[data-pick]");
    if (del) { removeCursor(cursors.find(c => c.n === +del.dataset.del)); cv.focus({ preventScroll: true }); }
    else if (pick) { selected = cursors.find(c => c.n === +pick.dataset.pick) || null; draw(); cv.focus({ preventScroll: true }); }
  });
  function readout() {
    const near = document.getElementById("sv-near");
    setHtml(document.getElementById("sv-view"), row("Time", v.t0.toFixed(3) + " to " + v.t1.toFixed(3) + " s") +
      row("Frequency", fmt(v.f0) + " to " + fmt(v.f1) + " Hz") + row("Zoom", (D.dur / (v.t1 - v.t0)).toFixed(1) + "x"));
    setHtml(document.getElementById("sv-cursors"), cursorsHtml());
    setHtml(document.getElementById("sv-ranges"), SV.overlays.includes("ranges") ? rangesHtml() : "");
    const c = hover;
    if (!c) { near.textContent = "Point at the picture"; document.getElementById("sv-cur").innerHTML = ""; return; }
    const n = nearest(c);
    if (n) {
      const unit = n.what === "Intensity" ? " dB" : " Hz";
      near.innerHTML = '<span style="color:' + (n.what[0] === "F" && n.what[1] !== "0" ? D.colors[+n.what[1] - 1] : n.what === "F0 (pitch)" ? D.pitch : "#2a6f97") +
        '">' + n.what + "</span> " + fmt(n.val, unit === " dB" ? 1 : 0) + unit + " at " + n.t.toFixed(3) + " s";
    } else {
      near.textContent = c.strip === "spec" ? fmt(hzOf(c.y)) + " Hz at " + c.t.toFixed(3) + " s" : c.t.toFixed(3) + " s";
    }
    let cur = row("Time", c.t.toFixed(3) + " s") + row("In the clip", (D.start + c.t).toFixed(3) + " s");
    const val = valueAt(c); if (val) cur += row("Under the pointer", val);
    setHtml(document.getElementById("sv-cur"), cur + frameRows(c.t) + refRows(c.t));
  }

  // ---- Spectrum at the cursor --------------------------------------------------------------------------------
  function slice() {
    const xc = hover ? { t: hover.t, y: hover.y, strip: hover.strip, who: "the pointer" }
             : selected && hasX(selected) ? { t: selected.t, strip: null, who: "cursor " + selected.n } : null;
    const sw = sc.width / dpr, sh = sc.height / dpr, l = 48, r = 12, top = 22, bot = 24, pw = sw - l - r, ph = sh - top - bot;
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    sctx.clearRect(0, 0, sw, sh);
    sctx.font = "11px system-ui, sans-serif"; sctx.fillStyle = "#33404e"; sctx.textBaseline = "top"; sctx.textAlign = "left";
    sctx.fillText(xc ? "Spectrum at " + xc.t.toFixed(3) + " s, " + xc.who + " (top " + D.range_db + " dB, relative)" : "Spectrum: point at the picture or place a cursor", l, 4);
    sctx.strokeStyle = "#b8c1cc"; sctx.strokeRect(l + 0.5, top + 0.5, pw - 1, ph - 1);
    sctx.fillStyle = "#55606d"; sctx.textAlign = "center";
    const fx = f => l + f / D.top * pw;
    for (let f = 0; f <= D.top; f += 1000) sctx.fillText((f / 1000) + "k", fx(f), top + ph + 6);
    sctx.textAlign = "right"; sctx.textBaseline = "middle";
    for (let d = 0; d >= -D.range_db; d -= 10) sctx.fillText(d + "", l - 6, top + ph * (-d / D.range_db));
    if (!xc || !pix) return;
    const col = Math.max(0, Math.min(pix.width - 1, Math.round(xc.t / D.dur * (pix.width - 1))));
    sctx.strokeStyle = "#16202c"; sctx.lineWidth = 1.4; sctx.beginPath();
    for (let rr = 0; rr < pix.height; rr++) {
      const f = (1 - rr / (pix.height - 1)) * D.top;
      const level = 1 - pix.data[(rr * pix.width + col) * 4] / 255;
      const x = fx(f), yy = top + ph * (1 - level);
      rr ? sctx.lineTo(x, yy) : sctx.moveTo(x, yy);
    }
    sctx.stroke(); sctx.lineWidth = 1;
    const F = D.f[frameAt(xc.t)];
    sctx.textAlign = "center"; sctx.textBaseline = "top"; sctx.font = "bold 11px system-ui, sans-serif";
    for (let k = 0; k < 3; k++) {
      if (F[k] == null) continue;
      sctx.strokeStyle = D.colors[k]; sctx.setLineDash([4, 3]);
      sctx.beginPath(); sctx.moveTo(fx(F[k]), top); sctx.lineTo(fx(F[k]), top + ph); sctx.stroke();
      sctx.setLineDash([]); sctx.fillStyle = D.colors[k]; sctx.fillText("F" + (k + 1), fx(F[k]), top + 2);
    }
    if (xc.strip === "spec") {
      const f = hzOf(xc.y); sctx.strokeStyle = "#7b8794";
      sctx.beginPath(); sctx.moveTo(fx(f), top); sctx.lineTo(fx(f), top + ph); sctx.stroke();
    }
  }

  // ---- Pointer events ----------------------------------------------------------------------------------------
  function at(e) {
    const b = cv.getBoundingClientRect(), x = e.clientX - b.left, yy = e.clientY - b.top;
    const st = STRIPS.find(s => yy >= s.y && yy <= s.y + s.h);
    return { x, y: yy, t: Math.max(0, Math.min(D.dur, tOf(Math.max(L, Math.min(L + PW, x))))), strip: st ? st.k : null };
  }
  function setMouse(p) {
    let cls = "";
    if (drag && drag.moved && drag.kind === "pan") cls = "grab";
    else if (drag && drag.kind === "win") cls = drag.mode === "move" ? "move" : "ew";
    else if (drag && drag.kind === "ref") cls = drag.mode === "move" ? "move" : "ew";
    else if (SV.pointer === "scrub") cls = "scrub";
    else if (SV.pointer === "cursor" && armed) cls = "place";
    else {
      const h = !drag && p && hitCursor(p);
      let h2 = null;
      if (h) cls = h.axis === "x" ? "ew" : h.axis === "y" ? "ns" : "move";
      else if (!drag && p && (h2 = hitRef(p))) cls = h2.mode === "move" ? "move" : "ew";
      else { const w = !drag && p && hitWin(p); if (w) cls = w === "move" ? "move" : "ew"; }
    }
    cv.className = cls;
  }
  function showTip(p) {
    let html = p && bandTip(p);
    const rh = !html && p && !drag && hitRef(p);
    if (rh) html = rh.mode === "move" ? "Reference " + rh.r.n + ": drag to slide it left or right. Its frequencies stay fixed."
                                      : "Reference " + rh.r.n + ": drag to stretch or squeeze it in time.";
    const w = !html && !rh && p && !drag && hitWin(p);
    if (w) html = w === "move" ? "Drag to slide the target sound window. The measures follow it." : "Drag to resize the target sound window.";
    if (!html) { tip.style.display = "none"; return; }
    tip.innerHTML = html; tip.style.display = "block";
    const left = Math.min(p.x + 14, cv.clientWidth - tip.offsetWidth - 4);
    tip.style.left = Math.max(0, left) + "px"; tip.style.top = (p.y + 14) + "px";
  }
  cv.addEventListener("pointermove", e => {
    const p = at(e);
    if (drag) {
      const dx = p.x - drag.x, dy = p.y - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      if (drag.kind === "pan" && drag.moved) {
        const span = drag.v.t1 - drag.v.t0;
        v.t0 = drag.v.t0 - dx / PW * span; v.t1 = v.t0 + span;
        if (drag.strip === "spec") { const fs = drag.v.f1 - drag.v.f0; v.f0 = drag.v.f0 + dy / strip("spec").h * fs; v.f1 = v.f0 + fs; }
        clampView();
      } else if (drag.kind === "win" && drag.moved) dragWin(drag, p);
      else if (drag.kind === "ref" && drag.moved) dragRef(drag, p);
      else if (drag.kind === "cursor") {
        const c = drag.c;
        if (drag.axis !== "y") c.t = p.t;
        if (drag.axis !== "x" && c.strip) { const st = strip(c.strip); c.val = yUnits[c.strip][1](Math.max(st.y, Math.min(st.y + st.h, p.y))); }
      } else if (drag.kind === "tool" && drag.tool.move) drag.tool.move(e, p);
    }
    hover = p.x >= L && p.x <= L + PW && p.y >= TOPY - 20 && p.y <= BASE ? p : null;
    setMouse(p);
    if (!drag) drawPointer(); else if (drag.kind !== "tool") draw();
    showTip(hover);
  });
  cv.addEventListener("pointerleave", () => { hover = null; tip.style.display = "none"; draw(); });
  cv.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    cv.setPointerCapture(e.pointerId);
    const p = at(e), tool = SV.tools[SV.pointer];
    tip.style.display = "none";
    if (SV.pointer === "scrub") { drag = { kind: "tool", tool, x: p.x, y: p.y }; tool.down(e, p); return; }
    const hit = SV.pointer === "cursor" && armed ? null : hitCursor(p);
    if (hit) { selected = hit.c; drag = { kind: "cursor", c: hit.c, axis: hit.axis, x: p.x, y: p.y }; draw(); return; }
    const rh = hitRef(p);
    if (rh) { drag = { kind: "ref", r: rh.r, mode: rh.mode, a: rh.r.a, k: rh.r.k, t: p.t, x: p.x, y: p.y, moved: false }; draw(); return; }
    const w = hitWin(p);
    if (w) { drag = { kind: "win", mode: w, a: D.win[0], b: D.win[1], t: p.t, x: p.x, y: p.y, moved: false }; draw(); return; }
    drag = { kind: "pan", x: p.x, y: p.y, v: { ...v }, moved: false, strip: p.strip };
  });
  cv.addEventListener("pointerup", e => {
    const p = at(e), d = drag; drag = null;
    if (d && d.kind === "tool") { if (d.tool.up) d.tool.up(e, p); }
    else if (d && d.kind === "win") { if (d.moved) sendWindow({ start: D.win[0].toFixed(4), end: D.win[1].toFixed(4) }); }
    else if (d && d.kind === "ref") { if (d.moved) { d.r.manual = true; legend(); } }
    else if (d && d.kind === "pan" && !d.moved && SV.pointer === "cursor" && armed && p.x >= L && p.x <= L + PW) place(p);
    cv.focus({ preventScroll: true }); setMouse(p); bar(); draw();
  });
  function dropDrag(e) {
    // A lost pointer (touch cancel, focus change) ends any drag cleanly, so a tool never keeps playing or moving.
    const d = drag; drag = null;
    if (d && d.kind === "tool" && d.tool.up) d.tool.up(e, at(e));
    if (d && d.kind === "win" && d.moved) { D.win = [d.a, d.b]; draw(); }  // a cancelled window drag goes back
    if (d && d.kind === "ref" && d.moved) { d.r.a = d.a; d.r.k = d.k; draw(); }
  }
  cv.addEventListener("pointercancel", dropDrag);
  cv.addEventListener("lostpointercapture", e => { if (drag) dropDrag(e); });
  cv.addEventListener("dblclick", () => { if (SV.pointer === "move") reset(); });

  // ---- Zoom: at a limit, more zooming does nothing at all (no pan, no shift) ---------------------------------
  const MIN_SPAN = 0.02, MIN_HZ = 400;
  const maxZoom = () => D.dur / Math.min(D.dur, MIN_SPAN);
  // Zoom time by k around the time `c` (kept still on the screen). Returns false, and changes nothing, when the
  // view is already at the limit in that direction.
  function zoomTime(c, k) {
    const span = v.t1 - v.t0, ns = Math.min(D.dur, Math.max(MIN_SPAN, span * k));
    if (Math.abs(ns - span) < 1e-9 * Math.max(1, D.dur)) {
      SV.say(k < 1 ? "Zoomed in as far as it goes (" + maxZoom().toFixed(0) + "x, " + (MIN_SPAN * 1000).toFixed(0) + " ms shown)." : "");
      return false;
    }
    c = Math.max(v.t0, Math.min(v.t1, c));  // the anchor stays on screen, so zooming in never moves the view away
    const kk = ns / span;
    v.t0 = c - (c - v.t0) * kk; v.t1 = v.t0 + ns;
    clampView(); if (SV.status.startsWith("Zoomed")) SV.say(""); draw(); return true;
  }
  function zoomFreq(f, k) {
    const span = v.f1 - v.f0, ns = Math.min(D.top, Math.max(MIN_HZ, span * k));
    if (Math.abs(ns - span) < 1e-6) {
      SV.say(k < 1 ? "Frequency is zoomed in as far as it goes (" + MIN_HZ + " Hz shown)." : "");
      return false;
    }
    f = Math.max(v.f0, Math.min(v.f1, f));
    const kk = ns / span;
    v.f0 = f - (f - v.f0) * kk; v.f1 = v.f0 + ns;
    clampView(); if (SV.status.startsWith("Frequency is")) SV.say(""); draw(); return true;
  }
  cv.addEventListener("wheel", e => {
    // Shift+wheel arrives as a sideways scroll (deltaX) in some browsers; a pure sideways scroll without Shift
    // is not a zoom and is ignored.
    const d = e.shiftKey ? (e.deltaY || e.deltaX) : e.deltaY;
    if (!d) return;
    e.preventDefault();
    const p = at(e), k = d > 0 ? 1.25 : 0.8;
    if (e.shiftKey && p.strip === "spec") zoomFreq(hzOf(p.y), k);
    else zoomTime(p.t, k);
  }, { passive: false });
  cv.addEventListener("keydown", e => {
    const c = selected;
    if (/^[1-6]$/.test(e.key) && cursors.find(x => x.n === +e.key)) { selected = cursors.find(x => x.n === +e.key); draw(); e.preventDefault(); }
    else if ((e.key === "ArrowLeft" || e.key === "ArrowRight") && c && hasX(c)) {
      const i = frameAt(c.t) + (e.key === "ArrowRight" ? 1 : -1) * (e.shiftKey ? 10 : 1);
      c.t = D.t[Math.max(0, Math.min(N - 1, i))];
      if (c.t < v.t0 || c.t > v.t1) { const span = v.t1 - v.t0; v.t0 = c.t - span / 2; v.t1 = v.t0 + span; clampView(); }
      draw(); e.preventDefault();
    } else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && c && hasY(c)) {
      const step = (c.strip === "int" ? 0.5 : 10) * (e.shiftKey ? 10 : 1);
      c.val += e.key === "ArrowUp" ? step : -step; draw(); e.preventDefault();
    } else if ((e.key === "Delete" || e.key === "Backspace") && c) { removeCursor(c); e.preventDefault(); }
    else if (e.key === "+" || e.key === "=") { zoom(0.5); e.preventDefault(); }
    else if (e.key === "-" || e.key === "_") { zoom(2); e.preventDefault(); }
    else if (e.key === "0") { reset(); e.preventDefault(); }
    else if (e.key === "Escape") {
      // Esc first cancels what the viewer is doing; only an Esc it did not use closes the full view around it.
      if (armed) { armed = false; bar(); e.preventDefault(); }
      else if (selected) { selected = null; e.preventDefault(); }
      draw();
    }
  });

  function zoom(k) {
    const c = selected && hasX(selected) && selected.t >= v.t0 && selected.t <= v.t1 ? selected.t : (v.t0 + v.t1) / 2;
    zoomTime(c, k);
  }
  function reset() { v.t0 = 0; v.t1 = D.dur; v.f0 = 0; v.f1 = D.top; SV.say(""); draw(); }
  function resetR() { v.t0 = 0; v.t1 = D.dur; v.f0 = 0; v.f1 = D.view_top || D.top; SV.say(""); draw(); }

  document.querySelectorAll(".sv-bar [data-act]").forEach(b => b.addEventListener("click", () => {
    const a = b.dataset.act;
    if (a === "in") zoom(0.5);
    else if (a === "out") zoom(2);
    else if (a === "all") reset();
    else if (a === "r6k") resetR();
    else if (a === "rwin" && D.win) { const pad = (D.win[1] - D.win[0]) * 0.15; v.t0 = D.win[0] - pad; v.t1 = D.win[1] + pad; clampView(); draw(); }
    else if (a === "winreset") sendWindow({ reset: "1" });
    else if (a === "play" && audio) {
      const sp = document.getElementById("sv-speed"), speed = sp ? +sp.value : 1;
      stopSlow(); audio.pause();
      if (speed < 1) { playSlow(speed); return; }
      audio.currentTime = D.start + v.t0; const end = D.start + v.t1;
      audio.play().catch(err => SV.say("Could not play: " + err.message));
      const follow = () => {
        if (audio.paused || audio.currentTime >= end) { audio.pause(); play = null; draw(); return; }
        play = audio.currentTime - D.start; drawLines(); requestAnimationFrame(follow);
      };
      requestAnimationFrame(follow);
    }
  }));
  // Test and debugging handles: the placed cursors and the state, read-only by convention.
  SV.cursors = cursors;
  SV.state = () => ({ armed, selected: selected && selected.n, view: { ...v }, win: D.win, win_manual: !!D.win_manual,
                      gap: D.gap, scrub: { loaded: !!S.P, t: S.t, mode: S.E ? S.E.mode() : "idle", stats: { ...S.stats },
                               engine: S.N ? "stretch" : S.old ? "follow" : "none",
                               heard: S.E && S.E.heard ? S.E.heard() : null },
                      slow: S.slow ? { speed: S.slow.speed, seconds: S.slow.seconds } : null,
                      refs: refs.map(r => ({ n: r.n, item: r.item, group: r.group, a: r.a, k: r.k, manual: r.manual,
                                             style: REF_STYLES[r.style].name })),
                      compareOpen: !CMP.pop.hidden });
  SV.stretched = (t0, t1, speed) => S.P ? stretched(t0, t1, speed) : null;  // test handle: the slow-motion render
  SV.scrubAudio = () => loadAudio().then(() => S.P);  // test handle: the prepared sound for offline scrub renders
  SV.compare = { open: openPop, close: closePop, add: addRef, refAt: (n, t) => { const r = refs.find(r => r.n === n); return r ? refAt(r, t) : null; },
                 x: (n, tr) => { const r = refs.find(r => r.n === n); return r ? xOf(refX(r, tr)) : null; } };
  SV.arm = arm; SV.redraw = () => draw();
  window.addEventListener("resize", size);
  bar(); size();
})();
"""
