// The child screen. It builds a 1280 x 720 stage from felt.json (pre-rendered WebP layers) and follows /api/state.
// The world and the buddy are the SLP's pick (/look, sent in the state); a new pick reloads the page.
// Board rule: layers move only by CSS transform and opacity. It never gets or shows a result: every try is cheered alike.
const $ = (id) => document.getElementById(id);
const stage = $("stage");
// The card shows only while the mic is on (Nov 12): a child who sees the word says it at once, before Record.
// If no voice comes, the screen asks again after NUDGE_MS; the board keeps listening until it hears one.
const NUDGE_MS = 8000, CHEER_MS = 3400, PRAISES = 5, SLOTS = 10;
let D, W, look = "", lastTries = null, cheerUntil = 0, listenSince = 0, scene = "", line = null, filled = 0, doneRain = 0;

const px = (v) => v + "px";
const vary = (v, k = 0.3) => v * (1 - k + 2 * k * Math.random());  // v, give or take k of it
function img(e, cls, parent) {
  const i = document.createElement("img");
  i.src = "/felt/" + e.f; i.alt = ""; i.className = cls || "";
  place(i, e);
  (parent || stage).appendChild(i);
  return i;
}
function place(el, e) { Object.assign(el.style, { left: px(e.x), top: px(e.y), width: px(e.w), height: px(e.h) }); }
function box(id, parent) {
  const d = document.createElement("div");
  d.id = id; (parent || stage).appendChild(d);
  return d;
}
// A puppet: body parts in a group that turns about the feet, head parts in a group that turns about the neck.
function rig(parts, name, parent) {
  const r = box("", parent), body = box("", r), head = box("", body);
  r.className = "rig " + name; body.className = "g-body"; head.className = "g-head";
  let past = false;  // a body part painted after the head (Toffee's arms) stays in front of it
  for (const p of parts) {
    if (p.n === "shadow") continue;
    const inHead = /^(ear|sprout|head|cheeks|eyes|mouth)/.test(p.n);
    if (p.n === "head") past = true;
    if (!inHead) body.insertBefore(img(p, "p-" + p.n, body), past ? null : head);
    else img(p, "p-" + p.n, head);
    const el = (inHead ? head : body).querySelector(".p-" + p.n);
    if (p.p) el.style.transformOrigin = px(p.p[0] - p.x) + " " + px(p.p[1] - p.y);
    if (p.n === "body") body.style.transformOrigin = px(p.p[0]) + " " + px(p.p[1]);
    if (p.n === "head") head.style.transformOrigin = px(p.p[0]) + " " + px(p.p[1]);
  }
}

function build(world, buddy) {
  W = D.worlds[world];
  const s = W.scene, b = D.buddies[buddy], groups = {};
  img({ f: s.back, x: 0, y: 0, w: 1280, h: 720 }, "back");
  for (const e of s.bits) {  // the world's moving bits, in paint order; a lid is a still layer that covers its bit
    if (e.g && !groups[e.g]) { groups[e.g] = box(""); groups[e.g].className = e.g; life(groups[e.g]); }
    const el = img(e, e.a, groups[e.g]);
    if (!e.g) life(el);  // a group's parts share its life (two wings flap together, the lick runs up the flame's bands)
    else el.style.setProperty("--w", vary(1, 0.2));  // and each its own pace for what it does alone (a band's stretch)
    if (e.p) el.style.transformOrigin = px(e.p[0]) + " " + px(e.p[1]);  // a scene bit's pivot is in its own pixels
    if (e.lid) img(e.lid);
  }

  const strip = box("strip");
  img(W.strip, "", strip);
  D.slots.forEach(([x, y]) => img({ ...W.item, x: x + W.item.x, y: y + W.item.y }, "item", strip));
  img({ ...D.pop, x: 0, y: 0 }, "", strip).id = "pop";

  const card = box("card");
  img(W.card, "", card);
  const pic = img({ f: "", x: 0, y: 0, w: 0, h: 0 }, "", card); pic.id = "pic"; pic.removeAttribute("src");
  const word = img({ f: "", x: 0, y: 0, w: 0, h: 0 }, "", card); word.id = "word"; word.removeAttribute("src");
  img(D.sentence, "", card).id = "sentence";
  box("say", card);
  const mic = box("mic");
  D.mic.forEach((m, i) => img(m, "m" + i, mic));

  const done = box("done");
  img(D.ribbon, "", done); img(D.allDone, "", done);
  [-1, 1].forEach((side) => img({ ...W.big, x: D.spots.wait + side * 250 - 55 + W.big.x, y: 470 + W.big.y }, "big b" + (side + 1), done));

  const bunny = box("bunny"), hop = box("hop", bunny);
  bunny.style.left = px(D.spots.wait - b.feet[0]); bunny.style.top = px(D.spots.feet - b.feet[1]);
  bunny.style.setProperty("--turn", px(D.spots.turn - D.spots.wait));
  const shadow = b.sets.front.find((p) => p.n === "shadow");
  img(shadow, "shadow", bunny).style.transformOrigin = px(shadow.p[0] - shadow.x) + " " + px(shadow.p[1] - shadow.y);
  bunny.appendChild(hop);
  rig(b.sets.front, "front", hop); rig(b.sets.listen, "listen", hop);
  b.spin.forEach((f) => img({ f, x: 0, y: 0, w: b.w, h: b.h }, "still", hop));

  const bubble = box("bubble");
  bubble.style.top = px(b.dy);
  for (let [k, e] of Object.entries(D.bubbles)) {
    if (k.startsWith("done-")) { if (k !== "done-" + world) continue; k = "done"; }  // each world has its own party
    const i = img(e, "", bubble); i.dataset.k = k;
    i.style.transformOrigin = px((e.x + e.w / 2 > 800 ? D.spots.turn : D.spots.wait) - e.x) + " " + px(e.h);
  }
  box("confetti");
  if (stage.querySelector(".drop")) setTimeout(drip, vary(2) * 1000);
}

// Every moving bit gets its own pace (--v), start (--dl) and size (--k), and half of them kid.css's second pattern,
// so nothing moves in step and no loop looks like the last.
function life(el) {
  el.style.setProperty("--v", vary(1));
  el.style.setProperty("--dl", -Math.random() * 20 + "s");
  el.style.setProperty("--k", vary(1));
  el.classList.toggle("alt", Math.random() < 0.5);
}

// The garden's can drips now and then: one or two drops fall onto the bed and are gone where they land.
function drip() {
  const drops = [...stage.querySelectorAll(".drop")].sort(() => Math.random() - 0.5).slice(0, Math.random() < 0.4 ? 2 : 1);
  drops.forEach((d, i) => {
    d.classList.remove("go"); void d.offsetWidth;
    d.style.animationDelay = i * vary(0.5) + "s"; d.classList.add("go");
  });
  setTimeout(drip, vary(4.5, 0.45) * 1000);
}

function bubble(k) {
  for (const i of $("bubble").children) i.classList.toggle("on", i.dataset.k === k);
}

// The card's picture and line. Baked felt pictures and cut-out words where the kit has them; otherwise no picture
// (a flat one would break the felt look) and the line in cut-out type, so any word list and practice sentence still shows.
function setLine(st) {
  if (line === st.line) return;
  line = st.line;
  const pic = $("pic"), word = $("word"), say = $("say"), one = st.line === st.word;
  const p = D.pics[st.word], w = one && D.words[st.word];
  if (p) { place(pic, p); pic.src = "/felt/" + p.f; }
  pic.classList.toggle("off", !p);
  word.classList.toggle("off", !w);
  if (w) { place(word, w); word.src = "/felt/" + w.f; }
  $("sentence").classList.toggle("off", one);
  const [x, y, bw, bh] = one ? D.label : D.sentence.text;
  place(say, { x, y, w: bw, h: bh });
  say.textContent = w ? "" : st.line || "";
  say.className = one ? (st.line.length > 7 ? "small" : "") : st.line.length > 24 ? "line two" : "line";
}

function progress(st) {
  const n = !st.session ? 0 : st.done ? st.total : st.index + (st.tried ? 1 : 0);
  const now = st.session && st.total ? Math.round(SLOTS * n / st.total) : 0;
  const items = document.querySelectorAll("#strip .item");
  items.forEach((el, i) => {
    el.classList.toggle("on", i < now);
    el.classList.toggle("new", i < now && i >= filled && lastTries !== null);
  });
  if (now > filled && lastTries !== null) {  // the new item pops, with a little burst over it
    const [x, y] = D.slots[now - 1], pop = $("pop");
    place(pop, { x: x + 22 - 40 + D.pop.x, y: y - 44 + D.pop.y, w: D.pop.w, h: D.pop.h });
    pop.classList.remove("go"); void pop.offsetWidth; pop.classList.add("go");
  }
  filled = now;
}

function confetti(n, rain) {
  const c = $("confetti");
  if (!rain) c.innerHTML = "";
  for (let i = 0; i < n; i++) {
    const e = D.confetti[i % D.confetti.length], o = document.createElement("div"), r = Math.random;
    o.className = rain ? "rain" : "";
    o.style.left = px(rain ? 80 + r() * 1120 : D.spots.wait - 14 + (r() - 0.5) * 60);
    o.style.top = px(rain ? -40 : 360);
    o.style.setProperty("--x", px(rain ? (r() - 0.5) * 120 : (r() - 0.5) * 760));
    o.style.setProperty("--up", px(-(140 + r() * 210)));
    o.style.setProperty("--down", px(rain ? 620 + r() * 120 : 60 + r() * 240));
    o.style.setProperty("--r", (r() * 720 - 360) + "deg");
    o.style.animationDelay = o.style.animationDelay = (rain ? r() * 2.4 : r() * 0.18) + "s";
    const i2 = img({ ...e, x: e.x, y: e.y }, "", o);
    i2.style.animationDelay = o.style.animationDelay;
    o.addEventListener("animationend", () => o.remove());
    c.appendChild(o);
  }
}

// Praise: one jump with a full turn (a still per 15 degrees, swapped by opacity), then the buddy lands and cheers.
function spin() {
  const stills = [...document.querySelectorAll("#hop .still")], bunny = $("bunny"), t0 = performance.now(), MS = 780;
  bunny.classList.remove("jump"); void bunny.offsetWidth; bunny.classList.add("jump", "spin");
  let shown = -1;
  (function frame(t) {
    const k = Math.min(1, (t - t0) / MS), ease = k < 0.5 ? 2 * k * k : 1 - 2 * (1 - k) * (1 - k);
    const i = Math.round(ease * stills.length) % stills.length;
    if (i !== shown) { if (shown >= 0) stills[shown].classList.remove("on"); stills[i].classList.add("on"); shown = i; }
    if (k < 1) return requestAnimationFrame(frame);
    stills[shown].classList.remove("on"); bunny.classList.remove("spin");
  })(t0);
}

// Practice only: the coach panel beside the buddy (level steps, where the r is, a tip). Never a result or a flag.
const WHERE = { start: "at the start", middle: "in the middle", end: "at the end" };
function coachPanel(c, word) {
  let el = $("coach");
  if (!el) {
    el = box("coach");
    el.innerHTML = '<div class="steps"><span>word</span><span>phrase</span><span>sentence</span></div>' +
      '<div class="spot"></div><div class="where"></div><div class="help"></div>';
  }
  stage.classList.toggle("practice", !!c);
  if (!c) return;
  el.querySelectorAll(".steps span").forEach((s) => s.classList.toggle("on", s.textContent === c.level));
  el.querySelector(".spot").innerHTML = word.replace(/r+/g, "<b>$&</b>");
  el.querySelector(".where").textContent = "The r is " + WHERE[c.position];
  el.querySelector(".help").textContent = "💡 " + c.tip;
}

function show(st) {
  const now = Date.now();
  if (lastTries !== null && st.tries > lastTries) {
    cheerUntil = now + CHEER_MS;
    bubble("praise-" + st.tries % PRAISES); confetti(26); spin();
  }
  const cheering = now < cheerUntil;
  if (st.phase !== "listening") listenSince = 0; else if (!listenSince) listenSince = now;
  const nudge = st.phase === "listening" && !st.speaking && now - listenSince > NUDGE_MS;
  let next;
  if (cheering) next = "praise";
  else if (!st.session) next = "hi";
  else if (st.done) next = "done";
  else if (st.phase === "listening") next = st.speaking ? "hear" : nudge ? "nudge" : "turn";
  else if (st.phase === "thinking") next = "think";
  else next = st.tried ? "next" : "ready";
  if (st.session && !st.done) setLine(st);
  coachPanel(st.session && !st.done && st.practice, st.word);
  progress(st);
  lastTries = st.tries;
  if (next === scene) return;
  const aside = (s) => ["turn", "hear", "nudge", "think"].includes(s);
  if (scene && aside(next) !== aside(scene) && next !== "praise") {  // a hop carries the buddy to its other spot
    const b = $("bunny"); b.classList.remove("jump"); void b.offsetWidth; b.classList.add("jump");
  }
  scene = next;
  stage.dataset.s = scene;
  stage.classList.toggle("aside", aside(scene));
  stage.classList.toggle("session", !!st.session);
  if (scene !== "praise") bubble(scene);
  clearInterval(doneRain);
  if (scene === "done") { confetti(18, true); doneRain = setInterval(() => confetti(12, true), 3200); }
}

async function poll() {
  try {
    const st = await (await fetch("/api/state", { cache: "no-store" })).json(), pick = st.look.world + " " + st.look.buddy;
    if (look && pick !== look) return location.reload();
    if (!look) { look = pick; build(st.look.world, st.look.buddy); }
    show(st);
  } catch (e) {}
  setTimeout(poll, 300);
}
function fit() {
  const k = Math.min(innerWidth / 1280, innerHeight / 720);
  stage.style.transform = `translate(${(innerWidth - 1280 * k) / 2}px, ${(innerHeight - 720 * k) / 2}px) scale(${k})`;
}
addEventListener("resize", fit); fit();
fetch("/felt/felt.json").then((r) => r.json()).then((d) => { D = d; poll(); });
