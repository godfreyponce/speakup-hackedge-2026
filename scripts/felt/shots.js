// Drives a whole demo session and screenshots the child screen at 1280 x 720 in every state.
// Start the app first:  python -m speakup --demo --host 127.0.0.1 --port 8041 --seconds 1
// node shots.js <out dir> [base url]   States the demo cannot reach (a voice heard, the long quiet, a practice
// sentence, a word with no felt picture) are shown by answering /api/state from here.
const fs = require("fs"), path = require("path");
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "C:/Users/rafam/aris2/app/node_modules/playwright");
const OUT = path.resolve(process.argv[2] || "kid-review"), BASE = process.argv[3] || "http://127.0.0.1:8041";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const post = (p, fields = {}, headers = {}) => fetch(BASE + p, { method: "POST", redirect: "manual", body: new URLSearchParams(fields),
  headers: { "Content-Type": "application/x-www-form-urlencoded", ...headers } });
const state = async () => (await fetch(BASE + "/api/state")).json();
const until = async (ok) => { for (let i = 0; i < 200 && !ok(await state()); i++) await sleep(50); };

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe" });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("requestfailed", (r) => errors.push("failed " + r.url()));
  page.on("response", (r) => { if (r.status() >= 400) errors.push(r.status() + " " + r.url()); });
  const shot = (name) => page.screenshot({ path: path.join(OUT, name + ".png") });
  const cardShown = () => page.evaluate(() => +getComputedStyle(document.getElementById("card")).opacity);

  // "load", not "networkidle": the page polls /api/state every 300 ms, so the network is never idle; the sleeps let it settle.
  await page.goto(BASE + "/kid", { waitUntil: "load" });
  await sleep(1500); await shot("01-hi");
  await post("/start", { student_id: "S-014", birth_date: "2018-11-01" });
  await sleep(1500); await shot("02-ready");
  if (await cardShown()) errors.push("card shown before Record");
  const total = (await state()).total;
  for (let i = 0; i < total; i++) {
    const n = String(i + 1).padStart(2, "0"), word = (await state()).word;
    await post("/record", {}, { "X-Record": "background" });
    await sleep(850); await shot(`03-turn-${n}-${word}`);
    if (!(await cardShown())) errors.push("card hidden while listening: " + word);
    await until((s) => s.phase === "idle" && s.tried);
    if (i === 0) { for (const ms of [250, 200, 200, 200]) { await sleep(ms); await shot("04-praise-spin-" + ms + "-" + Date.now() % 100000); } }
    else await sleep(700);
    await sleep(1100); await shot(`04-praise-${n}`);
    await sleep(2600); if (i < 2) await shot(`05-next-${n}`);
    if (await cardShown()) errors.push("card shown after the try: " + word);
    await post("/next");
    await sleep(500);
  }
  await sleep(1500); await shot("06-done");
  await sleep(1700); await shot("06-done-b");

  // states answered from here
  let fake = { session: false, phase: "idle", tries: 0, speaking: false };
  const mock = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  mock.on("pageerror", (e) => errors.push(String(e)));
  await mock.route("**/api/state", (r) => r.fulfill({ json: fake }));
  const turn = { session: true, done: false, total: 10, index: 3, word: "rocket", line: "rocket", picture: "/pics/rocket.svg", tried: false, tries: 3, speaking: false };
  const m = async (name, st, ms = 1700) => { fake = st; await sleep(ms); await mock.screenshot({ path: path.join(OUT, name + ".png") }); };
  await mock.goto(BASE + "/kid", { waitUntil: "load" });
  await m("10-ready-mid", { ...turn, phase: "idle" });
  await m("11-turn", { ...turn, phase: "listening" });
  await m("12-hear", { ...turn, phase: "listening", speaking: true });
  await m("13-nudge", { ...turn, phase: "listening" }, 8600);
  await m("14-think", { ...turn, phase: "thinking" });
  await m("15-praise", { ...turn, phase: "idle", tried: true, tries: 4 }, 2200);
  await m("16-next", { ...turn, phase: "idle", tried: true, tries: 4 }, 2200);
  await m("17-sentence", { ...turn, index: 4, tries: 4, phase: "listening", total: 5, line: "the little dog sees a big ring.", word: "ring", picture: "/pics/ring.svg" }, 2000);
  await m("18-idle-again", { ...turn, index: 4, tries: 4, phase: "idle", total: 5, line: "a big truck goes up the hill.", word: "truck" }, 1500);
  await m("19-short-sentence", { ...turn, index: 4, tries: 4, phase: "listening", total: 5, line: "a red car", word: "car" }, 2000);
  await m("20-idle-again", { ...turn, index: 5, tries: 4, phase: "idle", line: "cherry", word: "cherry" }, 1200);
  await m("21-no-felt-art", { ...turn, index: 5, tries: 4, phase: "listening", line: "cherry", word: "cherry", picture: "/pics/cherry.svg" }, 2000);
  await m("22-idle-again", { ...turn, index: 5, tries: 4, phase: "idle", line: "butterfly", word: "butterfly", picture: null }, 1200);
  await m("23-long-word-no-picture", { ...turn, index: 5, tries: 4, phase: "listening", line: "butterfly", word: "butterfly", picture: null }, 2000);
  await m("24-no-session", { session: false, phase: "idle", tries: 4, speaking: false });
  await browser.close();
  console.log(errors.length ? "PROBLEMS\n" + errors.join("\n") : "no page errors, card only while the mic is on");
  process.exit(errors.length ? 1 : 0);
})();
