"""The word page's recording controls (Nov 4): Record and Stop without leaving the page, and the selection box
on the waveform that says which part of the recording is the target word.

The box works like cropping a photo: drag its left or right edge to grow or shrink that side, drag its middle
to slide it. On release the page posts the new start and end, the server crops that part and Arti scores it
again. Listen plays only the box, Play all the whole recording. Mouse, pen and touch all go through pointer
events. Element ids start with sel-; nothing here touches the analysis viewer (speakup/soundview.py).
"""

import json
from html import escape

SELECT_CSS = """
  .sel { margin-top: 12px; }
  .sel-wave { position: relative; }
  #sel-canvas { width: 100%; height: 110px; display: block; border: 1px solid #d9dfe7; border-radius: 6px;
                background: #f7f9fb; touch-action: none; cursor: default; }
  #sel-canvas:focus-visible { outline: 3px solid #c9d8ee; }
  .sel-head { display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap; margin-bottom: 6px; }
  .sel-label { font-size: 13px; font-weight: 600; padding: 2px 8px; border-radius: 4px; background: #fff1d6; color: #7a4b00; }
  .sel-label.moved { background: #e8eef7; color: #1d4f91; }
  .sel-label.busy { background: #eef1f5; color: #44505e; }
  .sel-times { font-size: 13px; color: #44505e; }
  .sel-row { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; align-items: center; }
  .sel-row button { padding: 7px 14px; }
  .sel-help { font-size: 12px; color: #6b7785; margin: 6px 0 0; }
  .sel-err { color: #9b2c13; font-weight: 600; font-size: 13px; }
  .rec-live { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .rec-live[hidden], #rec-form[hidden] { display: none; }
  .rec-dot { width: 12px; height: 12px; border-radius: 50%; background: #c0392b; animation: sel-pulse 1s infinite; }
  @keyframes sel-pulse { 50% { opacity: .3; } }
  .rec-status { font-size: 13px; color: #44505e; }
  .stop { background: #9b2c13; border-color: #9b2c13; color: #fff; }
"""

LABELS = {
    "auto": "Picked automatically, listen to check",
    "whole": "No clear word found, the whole recording is selected. Listen and move the box",
    "moved": "Moved by you",
}


def label_for(auto: bool, method: str | None) -> tuple[str, str]:
    """(text, css class) for the box's label."""
    if not auto:
        return LABELS["moved"], "moved"
    if method == "whole":
        return LABELS["whole"], ""
    return LABELS["auto"], ""


def selection_card(key: str, base: str, duration: float, peaks: list[float], start: float, end: float,
                   auto: bool, method: str | None) -> str:
    """The waveform with the selection box, its label, Listen, Play all and Pick again."""
    text, cls = label_for(auto, method)
    data = {
        "dur": round(duration, 3), "peaks": peaks, "start": start, "end": end,
        "post": f"{base}/select", "audio": f"/audio/{key}-full.wav",
    }
    reset = ("" if auto else
             f'<form method="post" action="{base}/select"><input type="hidden" name="reset" value="1">'
             '<button class="quiet" id="sel-reset">Pick again automatically</button></form>')
    return f"""<div class="sel" id="sel-box" data-sel="{escape(json.dumps(data))}">
  <div class="sel-head"><span class="sel-label {cls}" id="sel-label">{escape(text)}</span>
    <span class="sel-times" id="sel-times">{start:.2f} s to {end:.2f} s ({end - start:.2f} s) of {duration:.2f} s</span></div>
  <div class="sel-wave"><canvas id="sel-canvas" tabindex="0" aria-label="Recording waveform. The shaded box is the part Arti scores. Left and right arrows slide it."></canvas></div>
  <div class="sel-row">
    <button type="button" class="primary" id="sel-listen">▶ Listen to the box</button>
    <button type="button" class="quiet" id="sel-all">Play all</button>
    {reset}
    <span class="sel-err" id="sel-err" role="alert"></span>
  </div>
  <p class="sel-help">Arti scored only the shaded box. Drag an edge to make that side bigger or smaller, drag the middle to slide it. Arti listens again when you let go.</p>
</div>
<script>{SELECT_JS}</script>"""


SELECT_JS = r"""
(function () {
  const root = document.getElementById("sel-box");
  if (!root) return;
  const D = JSON.parse(root.dataset.sel);
  const cv = document.getElementById("sel-canvas"), ctx = cv.getContext("2d");
  const label = document.getElementById("sel-label"), times = document.getElementById("sel-times");
  const err = document.getElementById("sel-err");
  const H = 110, MIN = 0.05;
  let s = D.start, e = D.end, drag = null, head = null, busy = false;
  let actx = null, buf = null, src = null, t0 = 0, from = 0, to = 0;

  const W = () => cv.clientWidth || 1;
  const t2x = t => t / D.dur * W();
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  function size() {
    const r = window.devicePixelRatio || 1;
    cv.width = Math.round(W() * r); cv.height = Math.round(H * r);
    ctx.setTransform(r, 0, 0, r, 0, 0);
    draw();
  }
  function draw() {
    const w = W(), n = D.peaks.length, mid = H / 2;
    ctx.clearRect(0, 0, w, H);
    const xs = t2x(s), xe = t2x(e);
    ctx.fillStyle = "rgba(29, 79, 145, 0.12)";
    ctx.fillRect(xs, 0, xe - xs, H);
    for (let i = 0; i < n; i++) {
      const x = i / n * w, bw = Math.max(1, w / n), hgt = Math.max(1, D.peaks[i] * (mid - 6));
      const inside = x + bw >= xs && x <= xe;
      ctx.fillStyle = inside ? "#1d4f91" : "#a9b4c2";
      ctx.fillRect(x, mid - hgt, bw, 2 * hgt);
    }
    ctx.strokeStyle = "#1d4f91"; ctx.lineWidth = 2;
    ctx.strokeRect(xs + 1, 1, Math.max(1, xe - xs - 2), H - 2);
    for (const x of [xs, xe]) {  // grips on both edges
      ctx.fillStyle = "#1d4f91";
      ctx.fillRect(x - 4, mid - 18, 8, 36);
      ctx.fillStyle = "#fff";
      ctx.fillRect(x - 1, mid - 10, 2, 20);
    }
    if (head !== null) {
      ctx.strokeStyle = "#c0392b"; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(t2x(head), 0); ctx.lineTo(t2x(head), H); ctx.stroke();
    }
  }
  function showTimes() {
    times.textContent = s.toFixed(2) + " s to " + e.toFixed(2) + " s (" + (e - s).toFixed(2) + " s) of " + D.dur.toFixed(2) + " s";
  }
  function hit(x, touch) {
    const xs = t2x(s), xe = t2x(e), tol = touch ? 20 : 10;
    const ds = Math.abs(x - xs), de = Math.abs(x - xe);
    if (ds <= tol && ds <= de) return "start";
    if (de <= tol) return "end";
    if (x > xs && x < xe) return "move";
    return null;
  }
  function px(ev) { return ev.clientX - cv.getBoundingClientRect().left; }

  cv.addEventListener("pointerdown", ev => {
    if (busy) return;
    const x = px(ev), kind = hit(x, ev.pointerType === "touch");
    if (!kind) return;
    drag = { kind, x0: x, s0: s, e0: e };
    cv.setPointerCapture(ev.pointerId);
    ev.preventDefault();
  });
  cv.addEventListener("pointermove", ev => {
    const x = px(ev);
    if (!drag) {
      const k = hit(x, ev.pointerType === "touch");
      cv.style.cursor = k === "move" ? "grab" : k ? "ew-resize" : "default";
      return;
    }
    const dt = (x - drag.x0) / W() * D.dur;
    if (drag.kind === "start") s = clamp(drag.s0 + dt, 0, e - MIN);
    else if (drag.kind === "end") e = clamp(drag.e0 + dt, s + MIN, D.dur);
    else {
      const len = drag.e0 - drag.s0;
      s = clamp(drag.s0 + dt, 0, D.dur - len); e = s + len;
    }
    cv.style.cursor = drag.kind === "move" ? "grabbing" : "ew-resize";
    showTimes(); draw();
  });
  function release() {
    if (!drag) return;
    const moved = Math.abs(s - drag.s0) > 0.001 || Math.abs(e - drag.e0) > 0.001;
    drag = null;
    if (moved) commit();
  }
  cv.addEventListener("pointerup", release);
  cv.addEventListener("pointercancel", release);

  let keyTimer = null;
  cv.addEventListener("keydown", ev => {
    if (busy || (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight")) return;
    const step = (ev.shiftKey ? 0.05 : 0.01) * (ev.key === "ArrowLeft" ? -1 : 1), len = e - s;
    s = clamp(s + step, 0, D.dur - len); e = s + len;
    showTimes(); draw(); ev.preventDefault();
    clearTimeout(keyTimer); keyTimer = setTimeout(commit, 700);
  });

  function commit() {
    busy = true; stop();
    label.textContent = "Moved by you, Arti is listening again";
    label.className = "sel-label busy"; err.textContent = "";
    const body = "start=" + s.toFixed(3) + "&end=" + e.toFixed(3);
    fetch(D.post, { method: "POST", body, headers: { "Content-Type": "application/x-www-form-urlencoded", "X-Select": "json" } })
      .then(r => r.json())
      .then(j => { if (j.ok) location.reload(); else fail(j.error || "Arti could not score that part."); })
      .catch(() => fail("The board did not answer. Try again."));
  }
  function fail(msg) {
    busy = false; err.textContent = msg;
    label.textContent = "Moved by you"; label.className = "sel-label moved";
  }

  function load() {
    if (buf) return Promise.resolve(buf);
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    return fetch(D.audio).then(r => r.arrayBuffer()).then(a => actx.decodeAudioData(a)).then(b => (buf = b));
  }
  function stop() {
    if (src) { try { src.stop(); } catch (_) {} src = null; }
    head = null; draw();
  }
  function play(a, b) {
    stop();
    load().then(() => {
      actx.resume();
      src = actx.createBufferSource(); src.buffer = buf; src.connect(actx.destination);
      from = a; to = Math.min(b, buf.duration); t0 = actx.currentTime;
      src.start(0, from, Math.max(0.01, to - from));
      const me = src;
      src.onended = () => { if (src === me) { src = null; head = null; draw(); } };
      (function tick() {
        if (src !== me) return;
        head = from + (actx.currentTime - t0); draw();
        if (head < to) requestAnimationFrame(tick);
      })();
    }).catch(() => { err.textContent = "Could not play the recording in this browser."; });
  }
  document.getElementById("sel-listen").addEventListener("click", () => play(s, e));
  document.getElementById("sel-all").addEventListener("click", () => play(0, D.dur));
  window.addEventListener("resize", size);
  size();
})();
"""


def quiet_text(seconds: float) -> str:
    """3.0 -> "3 s", 2.5 -> "2.5 s"."""
    return f"{seconds:g} s"


def record_controls(base: str, attempt_exists: bool, quiet_s: float = 2.0) -> str:
    """Record (and, while the mic listens, Stop) for the item card. Without JavaScript the plain form still
    records, waiting on the server as before."""
    label = "Record again" if attempt_exists else "Record"
    kind = "secondary" if attempt_exists else "primary big"
    return (f'<form method="post" action="{base}/record" id="rec-form">'
            f'<button class="{kind}" id="rec-go">● {label}</button></form>'
            '<div class="rec-live" id="rec-live" hidden><span class="rec-dot"></span>'
            '<button type="button" class="stop big" id="rec-stop">■ Stop</button></div>'
            '<p class="rec-status" id="rec-status" role="status"></p>'
            f"<script>{RECORD_JS.replace('__QUIET__', quiet_text(quiet_s))}</script>")


RECORD_JS = r"""
(function () {
  const form = document.getElementById("rec-form");
  if (!form) return;
  const live = document.getElementById("rec-live"), status = document.getElementById("rec-status");
  const stopBtn = document.getElementById("rec-stop");
  function show(listening) { form.hidden = listening; live.hidden = !listening; }
  function poll() {
    fetch("/api/record", { cache: "no-store" }).then(r => r.json()).then(j => {
      if (j.state === "listening") {
        status.textContent = "Listening. It stops __QUIET__ after the child goes quiet, or press Stop.";
        setTimeout(poll, 250);
      } else if (j.state === "thinking") {
        show(false); form.querySelector("button").disabled = true;
        status.textContent = "Finding the word and asking Arti.";
        setTimeout(poll, 250);
      } else if (j.state === "error") {
        show(false); form.querySelector("button").disabled = false;
        status.textContent = j.error || "Recording failed.";
        status.className = "rec-status sel-err";
      } else {
        location.replace(j.go || location.pathname);
      }
    }).catch(() => setTimeout(poll, 500));
  }
  form.addEventListener("submit", ev => {
    ev.preventDefault();
    status.className = "rec-status"; status.textContent = "Starting the mic.";
    show(true);
    fetch(form.action, { method: "POST", headers: { "X-Record": "background" } })
      .then(r => r.json())
      .then(j => { if (j.ok) poll(); else { show(false); status.textContent = j.error || "Could not start recording."; } })
      .catch(() => { show(false); status.textContent = "The board did not answer. Try again."; });
  });
  stopBtn.addEventListener("click", () => {
    stopBtn.disabled = true; status.textContent = "Stopping, keeping what was recorded.";
    fetch("/stop", { method: "POST" }).catch(() => {});
  });
  // A page opened while a recording runs (a reload) picks it up again.
  fetch("/api/record", { cache: "no-store" }).then(r => r.json()).then(j => {
    if (j.state === "listening" || j.state === "thinking") { show(j.state === "listening"); poll(); }
  }).catch(() => {});
})();
"""
