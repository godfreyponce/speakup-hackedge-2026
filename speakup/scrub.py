"""The Scrub tool's sound engine (Web Audio), as a script the analysis viewer includes before its own.

Revision 5 (Nov 5, research: Speak-Up-Docs/Archive/Research/scrub-rethink.md): the default is now method "stretch", one
continuous stream whose speed follows the hand while the pitch and formants stay the recording's own (DiMaß, Lee and
Borchers 2006). The owner heard revision 4 "cut off" and "not smooth": playing at exactly 1x has to wait for a slow
hand (silence) or skip to a fast one (a jump), so it can never be continuous. Here:
- the pointer goes through a 1€ filter (Casiez, Roussel and Vogel 2012): position x and speed v, little jitter;
- every 15 ms the play rate moves toward v + (x - a) / catchUp, where a is where the sound is in the recording,
  smoothed by the viscosity mu (DiMaß: users chose 0.5 to 0.9), never against the hand's direction, at most 3x;
- the stream is time-stretched at that rate by Signalsmith Stretch (MIT, vendored as /js/signalsmith-stretch.js),
  which runs in an AudioWorklet on the audio thread, so page work cannot open gaps;
- below 0.04x it is silent and it fades in up to 0.12x, so holding still is silent and stopping glides out;
- dragging left plays the recording backwards (a second stretcher reads a reversed copy), or with back "forward",
  the same stretcher runs at a negative rate, which gives forward-sounding pieces stepping back.
Without AudioWorklet or the library, the viewer falls back to method "follow" below and says so.

Revision 4's notes follow.

How it sounds, and why (measured, see Speak-Up-Docs/Archive/Research/scrub-research.md): while the pointer moves, the
recording plays continuously from under the pointer at its own speed, exactly as recorded. Nothing is ever played
twice during a drag in one direction (revision 4, Nov 5: the owner heard "ra ra ra" on slow drags, because the old
rule jumped the sound back to a pointer it had run ahead of):
- the sound runs ahead of a slow pointer: it fades out where it is and waits, silent, until the pointer reaches
  that spot, then carries on from exactly there;
- the pointer runs ahead of the sound (a fast drag): it jumps forward to the pointer with a 20 ms crossfade whose
  new start is chosen where the waveform matches the old one (the WSOLA search, Verhelst and Roelands 1993);
- dragging left plays the recording backwards by default, under the same rules mirrored.
Each piece lasts at least 60 ms. When the pointer stops, the sound fades out over 30 ms and stays silent.

The older method (46 ms WSOLA grains, half overlapping, looping a slice under a still pointer) is still here as
method "wsola" with its own options: the slow-motion playback uses the same search, and the measurement page renders
both methods offline (window.SVScrub.render) to compare them with the original recording.

Everything takes the audio clock's time (`now`), so the same engine runs live (AudioContext) and offline
(OfflineAudioContext with a scripted drag).
"""

JS = r"""
window.SVScrub = (function () {
  "use strict";
  const curve = (n, f) => { const w = new Float32Array(n); for (let i = 0; i < n; i++) w[i] = f(i / (n - 1)); return w; };
  const HANN = curve(128, x => Math.pow(Math.sin(Math.PI * x), 2));
  const RISE = curve(64, x => Math.pow(Math.sin(Math.PI / 2 * x), 2));   // with FALL: the two always sum to 1
  const FALL = curve(64, x => Math.pow(Math.cos(Math.PI / 2 * x), 2));

  // A mono copy averaged down to about 12 kHz: the waveform search reads it first, coarse and fast.
  function decimate(x, k) {
    const n = Math.floor(x.length / k), d = new Float32Array(n);
    for (let i = 0; i < n; i++) { let s = 0; for (let j = 0; j < k; j++) s += x[i * k + j]; d[i] = s / k; }
    return d;
  }
  // Once per sound: mono forward and reversed buffers and the copies the search reads.
  function prepare(b) {
    const n = b.length, chs = b.numberOfChannels, sr = b.sampleRate, mono = new Float32Array(n);
    for (let ch = 0; ch < chs; ch++) { const src = b.getChannelData(ch); for (let i = 0; i < n; i++) mono[i] += src[i] / chs; }
    const monoRev = mono.slice().reverse();
    const mk = data => { const a = new AudioBuffer({ length: n, sampleRate: sr, numberOfChannels: 1 }); a.copyToChannel(data, 0); return a; };
    const k = Math.max(1, Math.round(sr / 12000));
    return { sr, dur: n / sr, n, mono, monoRev, fwd: mk(mono), rev: mk(monoRev), k, dec: decimate(mono, k), decRev: decimate(monoRev, k) };
  }
  // WSOLA's search: the start near `target` (samples) whose first n samples best match the ones at `natural`
  // (where the sound playing now would carry on). Normalised cross-correlation on the coarse copy, every 2nd sample,
  // then, with fine, sample by sample at the full rate around the best coarse match.
  function bestStart(P, rev, natural, target, n, tol, fine) {
    const dec = rev ? P.decRev : P.dec, x = rev ? P.monoRev : P.mono, k = P.k;
    const clampS = s => Math.max(0, Math.min(P.n - n, s));
    if (natural == null) return clampS(target);
    const nn = Math.floor(n / k), tg = Math.round(target / k), tl = Math.round(tol / k), nat = Math.round(natural / k);
    const lo = Math.max(0, tg - tl), hi = Math.min(dec.length - nn, tg + tl);
    if (hi < lo || nat < 0 || nat + nn > dec.length) return clampS(target);
    let best = tg, bv = -Infinity;
    for (let s = lo; s <= hi; s++) {
      let c = 0, e = 1e-9;
      for (let i = 0; i < nn; i += 2) { const q = dec[s + i]; c += dec[nat + i] * q; e += q * q; }
      const score = c / Math.sqrt(e); if (score > bv) { bv = score; best = s; }
    }
    let out = best * k;
    if (fine && k > 1 && natural + n <= x.length) {
      let fb = out, fv = -Infinity;
      for (let s = Math.max(0, out - k); s <= Math.min(x.length - n, out + k); s++) {
        let c = 0, e = 1e-9;
        for (let i = 0; i < n; i += 2) { const q = x[s + i]; c += x[natural + i] * q; e += q * q; }
        const score = c / Math.sqrt(e); if (score > fv) { fv = score; fb = s; }
      }
      out = fb;
    }
    return clampS(out);
  }

  const DEFAULTS = {
    method: "follow",   // "follow": play the recording from the pointer, re-join when it drifts; "wsola": grains
    back: "reverse",    // dragging left: "reverse" (the recording backwards), or "forward" pieces at the pointer
    stillAfter: 0.09,   // s without movement that counts as holding still
    lat: 0.03,          // s between a decision and the sound it schedules (the audio clock must not pass it)
    jump: 0.05, ahead: 0.06, xf: 0.02, minSeg: 0.06, fade: 0.03, tol: 0.012, fine: true, settle: 0.04,  // follow
    grain: 0.046, overlap: 0.5, look: 0.06, glide: 0.04, still: "silent", slice: 0.15,  // wsola
  };

  function engine(ac, P, opts) {
    const o = Object.assign({}, DEFAULTS, opts || {});
    const out = o.destination || ac.destination;
    const stats = o.stats || {};
    const bump = k => { stats[k] = (stats[k] || 0) + 1; };
    const st = { pos: null, moveAt: 0, prevPos: 0, prevAt: 0, vel: 0, dir: 1, mode: "idle",
                 voice: null, next: 0, read: null, lastNat: null, lastRev: false, loopPh: 0, resume: null, gateDir: 0 };
    const clampPos = p => Math.max(0, Math.min(P.dur, p));

    function down(pos, now) {
      Object.assign(st, { pos, moveAt: now, prevPos: pos, prevAt: now, vel: 0, dir: 1, mode: "move",
                          next: now + 0.01, read: null, lastNat: null, resume: null, gateDir: 0 });
    }
    function move(pos, now) {
      if (st.pos == null) return;
      if (Math.abs(pos - st.pos) > 1e-6) {
        const dt = Math.max(0.001, now - st.prevAt), inst = (pos - st.prevPos) / dt;
        st.vel = 0.6 * st.vel + 0.4 * inst;
        if (Math.abs(st.vel) > 0.02) st.dir = st.vel < 0 ? -1 : 1;
        st.moveAt = now; st.prevPos = pos; st.prevAt = now;
      }
      st.pos = pos;
    }

    // ---- follow: one continuous voice, re-joined to the pointer when it drifts ----
    const inBuf = (v, when) => v.off + (when - v.start);                      // s, in the voice's own buffer
    const fwdPos = (v, when) => v.rev ? P.dur - inBuf(v, when) : inBuf(v, when); // s, in the recording
    function startVoice(pos, rev, when, prev) {
      const sr = P.sr;
      let off = rev ? P.dur - pos : pos;
      if (prev && prev.rev === rev) {  // start where the waveform continues the one that fades out
        const n = Math.round(o.xf * sr), nat = Math.round(inBuf(prev, when) * sr);
        off = bestStart(P, rev, nat >= 0 && nat + n < P.n ? nat : null, Math.round(off * sr), n, Math.round(o.tol * sr), o.fine) / sr;
      }
      off = Math.max(0, Math.min(P.dur - 0.005, off));
      const src = ac.createBufferSource(), g = ac.createGain();
      src.buffer = rev ? P.rev : P.fwd; g.gain.value = 0;
      g.gain.setValueCurveAtTime(RISE, when, o.xf);
      src.connect(g).connect(out); src.start(when, off);
      bump(rev ? "reversed" : "forward");
      return { src, g, start: when, off, rev, until: when + o.xf };
    }
    function endVoice(v, when, len) {
      const t = Math.max(when, v.until);
      v.g.gain.setValueCurveAtTime(FALL, t, len);
      try { v.src.stop(t + len + 0.005); } catch (e) { /* already stopped */ }
      v.until = Infinity;
    }
    function tickFollow(now) {
      const when = now + o.lat;
      if (now - st.moveAt > o.stillAfter) {  // held still: fade out and stay silent
        if (st.voice) { st.resume = fwdPos(st.voice, when); endVoice(st.voice, when, o.fade); st.voice = null; bump("stops"); }
        st.mode = "still"; return;
      }
      st.mode = "move";
      const rev = st.dir < 0 && o.back === "reverse", want = clampPos(st.pos), v = st.voice;
      // gated: the sound runs the same way as the hand, so it never jumps back over what it has played
      const gated = st.dir > 0 || rev;
      if (st.gateDir !== st.dir) { st.resume = null; st.gateDir = st.dir; }  // a new direction starts fresh
      if (!v) {
        let from = want;
        if (gated && st.resume != null) {
          const lead = (st.resume - want) * st.dir;  // > 0: the pointer has not yet reached where the sound stopped
          if (lead > 0) return;                       // wait, silent
          if (-lead < o.jump) from = st.resume;       // carry on from exactly there
        }
        st.voice = startVoice(from, rev, when, null); st.resume = null; bump("starts");
        if (stats.offsets) stats.offsets.push([when, from]);
        return;
      }
      if (when < v.until || when - v.start < o.minSeg) return;  // a piece plays at least minSeg, its fade first
      if (now - st.moveAt > o.settle) return;  // the hand is stopping: no new piece just before the fade-out
      const at = fwdPos(v, when);
      if (v.rev !== rev) { endVoice(v, when, o.xf); st.voice = startVoice(want, rev, when, v); bump("jumps"); return; }
      if (gated) {
        const ahead = (at - want) * st.dir;
        if (ahead > o.ahead) {  // ran ahead of a slow hand: stop here and wait for it
          endVoice(v, when, o.fade); st.voice = null; st.resume = clampPos(at + st.dir * o.fade / 2); bump("waits"); return;
        }
        if (-ahead > o.jump) {  // the hand is far ahead: skip forward to it
          endVoice(v, when, o.xf); st.voice = startVoice(want, rev, when, v); bump("jumps");
          if (stats.offsets) stats.offsets.push([when, want]);
        }
      } else if (Math.abs(at - want) > o.jump) {  // "forward" pieces while dragging left
        endVoice(v, when, o.xf); st.voice = startVoice(want, rev, when, v); bump("jumps");
      }
    }

    // ---- wsola: grains scheduled ahead, each joined where the waveform continues ----
    function grain(when, s, rev, n, gain) {
      const src = ac.createBufferSource(), g = ac.createGain();
      src.buffer = rev ? P.rev : P.fwd; g.gain.value = 0;
      g.gain.setValueCurveAtTime(gain === 1 ? HANN : HANN.map(x => x * gain), when, n / P.sr);
      src.connect(g).connect(out); src.start(when, s / P.sr, n / P.sr);
      bump("grains"); bump(rev ? "reversed" : "forward");
    }
    function tickWsola(now) {
      const sr = P.sr, n = Math.round(o.grain * sr), hop = o.grain * (1 - o.overlap), gain = Math.min(1, 2 * hop / o.grain);
      if (st.next < now) { st.next = now + 0.005; st.lastNat = null; }
      if (st.read == null) st.read = clampPos(st.pos);
      while (st.next < now + o.look) {
        const still = now - st.moveAt > o.stillAfter, want = clampPos(st.pos);
        let target;
        if (still && o.still === "silent") { st.mode = "still"; st.lastNat = null; st.read = want; st.next += hop; continue; }
        if (still) {  // "loop": the slice around the pointer, walked through at normal speed
          const len = o.slice, a = Math.max(0, Math.min(P.dur - len, want - len / 2));
          if (st.mode !== "loop") st.loopPh = Math.max(0, Math.min(len, st.read - a));
          st.mode = "loop"; st.loopPh += hop; if (st.loopPh >= len) st.loopPh -= len;
          target = a + st.loopPh; bump("loop");
        } else {
          st.mode = "move";
          const gap = want - st.read;
          target = Math.abs(gap) > 0.25 ? want : st.read + gap * (1 - Math.exp(-hop / o.glide));
        }
        st.read = target;
        const rev = st.mode === "move" && st.dir < 0 && o.back === "reverse";
        if (rev !== st.lastRev) st.lastNat = null;
        st.lastRev = rev;
        const centre = rev ? P.dur - target : target;
        const s = bestStart(P, rev, st.lastNat, Math.round((centre - o.grain / 2) * sr), n, Math.round(o.tol * sr), o.fine);
        grain(st.next, s, rev, n, gain);
        st.lastNat = s + Math.round(hop * sr); st.next += hop;
      }
    }

    function tick(now) { if (st.pos == null) return; (o.method === "wsola" ? tickWsola : tickFollow)(now); }
    function up(now) {
      if (st.voice) { endVoice(st.voice, now + 0.005, o.fade); st.voice = null; bump("stops"); }
      st.pos = null; st.mode = "idle";
    }
    return { down, move, tick, up, stats, mode: () => st.mode, opts: o };
  }

  // Render a scripted drag offline. path(t) gives the pointer's place in the recording (s) at t seconds after the
  // button went down, or null once it is released. Pointer events come every `every` s, ticks every 15 ms, as live.
  async function render(P, opts, path, seconds, every) {
    every = every || 0.01;
    const oac = new OfflineAudioContext(1, Math.ceil((seconds + 0.4) * P.sr), P.sr);
    const E = engine(oac, P, Object.assign({}, opts, { stats: {} }));
    const ev = [];
    for (let t = every; t <= seconds + 1e-9; t += every) ev.push([t, "move"]);
    for (let t = 0.015; t <= seconds + 1e-9; t += 0.015) ev.push([t, "tick"]);
    ev.sort((a, b) => a[0] - b[0] || (a[1] === "move" ? -1 : 1));
    E.down(path(0), 0); E.tick(0);
    let down = true;
    for (const [t, what] of ev) {
      if (!down) break;
      if (what === "move") { const p = path(t); if (p == null) { E.up(t); down = false; } else E.move(p, t); }
      else E.tick(t);
    }
    if (down) E.up(seconds);
    const buf = await oac.startRendering();
    return { samples: buf.getChannelData(0), stats: E.stats };
  }

  // ---- stretch (revision 5): one continuous, pitch-kept stream whose speed follows the hand ----
  const STRETCH = {
    back: "reverse", mu: 0.7, catchUp: 0.1, maxRate: 3, quiet: 0.04, loud: 0.12, still: 0.09,
    minCut: 3, beta: 3, dCut: 4,         // 1€ filter: Hz at rest, Hz added per 1x of speed; speed low-pass (Hz)
    blockMs: 60, intervalMs: 15,         // stretcher analysis block: shorter than its 120 ms default, for speech
  };
  function oneEuro(minCut, beta, dCut) {
    // Casiez, Roussel and Vogel (CHI 2012): a low-pass whose cutoff rises with speed, so a slow hand loses its
    // jitter and a fast one does not lag.
    // dx here is the hand's speed, measured from raw positions and low-passed at dCut. (The published filter takes
    // the speed against the previous *filtered* position, which only tunes its cutoff; as a speed it reads far too
    // high while the filter lags, which made the sound run ahead at the start of a drag.)
    const alpha = (cut, dt) => 1 / (1 + 1 / (2 * Math.PI * cut * dt));
    const f = { x: null, raw: null, dx: 0, t: 0 };
    f.reset = (v, now) => { f.x = v; f.raw = v; f.dx = 0; f.t = now; };
    f.step = (v, now) => {
      if (f.x == null) { f.reset(v, now); return; }
      // Events closer than 5 ms (the audio clock moves in 2.7 ms steps, and browsers bunch pointer events) would
      // make a huge, false speed: wait and take the newest position at the next step instead.
      if (now - f.t < 0.005) return;
      const dt = now - f.t; f.t = now;
      f.dx += alpha(dCut, dt) * ((v - f.raw) / dt - f.dx); f.raw = v;
      f.x += alpha(minCut + beta * Math.abs(f.dx), dt) * (v - f.x);
    };
    return f;
  }
  // The two stretchers for a sound (forward and reversed copies), made once per audio context and kept.
  async function stretchers(ac, P, opts) {
    const o = Object.assign({}, STRETCH, opts || {});
    if (!window.SignalsmithStretch) throw new Error("the time-stretcher (signalsmith-stretch.js) did not load");
    if (!ac.audioWorklet) throw new Error("this browser has no AudioWorklet");
    P.stretch = P.stretch || new Map();
    if (P.stretch.has(ac)) return P.stretch.get(ac);
    const out = o.destination || ac.destination;
    const mk = async data => {
      const node = await window.SignalsmithStretch(ac, { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      await node.configure({ blockMs: o.blockMs, intervalMs: o.intervalMs });
      await node.addBuffers([data.slice()]);
      const gain = ac.createGain(); gain.gain.value = 0;
      node.connect(gain).connect(out);
      return { node, gain, on: false };
    };
    const N = { fwd: await mk(P.mono), rev: await mk(P.monoRev) };
    N.latency = await N.fwd.node.latency();
    P.stretch.set(ac, N);
    return N;
  }
  function stretchEngine(ac, P, N, opts) {
    const o = Object.assign({}, STRETCH, opts || {});
    const stats = o.stats || {};
    const bump = k => { stats[k] = (stats[k] || 0) + 1; };
    const f = oneEuro(o.minCut, o.beta, o.dCut);
    const st = { pos: null, a: 0, r: 0, t: 0, moveAt: 0, dir: 1, voice: null, mode: "idle", quietFor: 0 };
    const clampPos = p => Math.max(0, Math.min(P.dur, p));
    const sched = (v, obj, now) => v.node.schedule(Object.assign({ output: now, outputTime: now }, obj));
    function voiceOff(v, now) {
      if (!v.on) return null;
      v.on = false;
      v.gain.gain.cancelScheduledValues(now); v.gain.gain.setTargetAtTime(0, now, 0.01);
      return sched(v, { active: false }, now + 0.08);
    }
    function down(pos, now) {
      f.reset(pos, now);
      Object.assign(st, { pos, a: clampPos(pos), r: 0, t: now, moveAt: now, dir: 1, voice: null, mode: "move", quietFor: 0 });
    }
    function move(pos, now) {
      if (st.pos == null) return;
      f.step(pos, now);
      if (Math.abs(pos - st.pos) > 1e-6) {
        st.moveAt = now;
        if (Math.abs(f.dx) > 0.02) st.dir = f.dx < 0 ? -1 : 1;
      }
      st.pos = pos;
    }
    function tick(now) {
      if (st.pos == null) return null;
      const dt = Math.min(0.05, Math.max(0, now - st.t));
      st.a = clampPos(st.a + st.r * dt); st.t = now;
      const still = now - st.moveAt > o.still;
      if (still) f.step(st.pos, now);  // no events while the hand rests: let the filter settle on the pointer
      const v = still ? 0 : f.dx;
      let want = v + (f.x - st.a) / o.catchUp;
      if (want * st.dir < 0) want = 0;   // never against the hand: no overshoot and wobble back (DiMaß)
      const mu = Math.pow(o.mu, dt / 0.015);
      st.r = Math.max(-o.maxRate, Math.min(o.maxRate, mu * st.r + (1 - mu) * want));
      if ((st.a <= 0 && st.r < 0) || (st.a >= P.dur && st.r > 0)) st.r = 0;
      const speed = Math.abs(st.r), level = Math.max(0, Math.min(1, (speed - o.quiet) / (o.loud - o.quiet)));
      st.mode = level > 0 ? "move" : "still";
      const rev = st.r < 0 && o.back === "reverse", v1 = rev ? N.rev : N.fwd, v0 = rev ? N.fwd : N.rev;
      const input = rev ? P.dur - st.a : st.a, rate = rev ? speed : st.r;
      st.quietFor = level > 0 ? 0 : st.quietFor + dt;
      const jobs = [];
      if (level === 0 && st.quietFor > 0.15) {  // quiet for a while: stop the stretchers (no frozen sound, less work)
        jobs.push(voiceOff(N.fwd, now), voiceOff(N.rev, now)); st.voice = null;
        return Promise.all(jobs);
      }
      if (v0.on) { jobs.push(voiceOff(v0, now)); bump("turns"); }
      if (!v1.on) { v1.on = true; bump("starts"); }
      st.voice = rev ? "rev" : "fwd";
      jobs.push(sched(v1, { active: true, input, rate }, now));
      v1.gain.gain.setTargetAtTime(level, now, 0.012);
      return Promise.all(jobs);
    }
    function up(now) {
      const jobs = [voiceOff(N.fwd, now), voiceOff(N.rev, now)];
      st.pos = null; st.mode = "idle"; st.voice = null; st.r = 0;
      bump("stops");
      return Promise.all(jobs);
    }
    // Where the sound is now, in the recording (s): the playhead follows this, not the pointer.
    const heard = () => (st.pos == null ? null : st.a);
    return { down, move, tick, up, heard, stats, mode: () => st.mode, rate: () => st.r, opts: o };
  }
  // Render a scripted drag offline through the stretchers: the control code runs at each tick while the offline
  // context is suspended there, as the live 15 ms timer would.
  async function renderStretch(P, opts, path, seconds, every) {
    every = every || 0.01;
    const oac = new OfflineAudioContext(1, Math.ceil((seconds + 0.6) * P.sr), P.sr);
    const N = await stretchers(oac, P, opts);
    const E = stretchEngine(oac, P, N, Object.assign({}, opts, { stats: {} }));
    const trace = [], q = 128 / P.sr, stops = [];
    for (let k = 1; k * q <= seconds + 0.3; k++) if ((k * q) % 0.015 < q) stops.push(k * q);
    let down = true, lastMove = 0;
    E.down(path(0), 0); await E.tick(0);
    for (const ts of stops) {
      oac.suspend(ts).then(async () => {
        while (down && lastMove + every <= ts + 1e-9) {
          lastMove += every;
          const p = lastMove <= seconds ? path(lastMove) : null;
          if (p == null) { await E.up(ts); down = false; } else E.move(p, lastMove);
        }
        if (down) { await E.tick(ts); trace.push([ts, E.heard(), E.rate()]); }
        oac.resume();
      });
    }
    const buf = await oac.startRendering();
    return { samples: buf.getChannelData(0), stats: E.stats, trace };
  }

  return { prepare, engine, bestStart, render, DEFAULTS, STRETCH, oneEuro, stretchers, stretchEngine, renderStretch };
})();
"""
