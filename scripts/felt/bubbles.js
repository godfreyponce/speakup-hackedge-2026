// Bakes each speech bubble (9-slice body, tail, stitch and its lines) into one transparent PNG, offline on the laptop.
// node bubbles.js <art folder> <spec.json> <out dir>   spec: [{id, lines: [text...], tip: x, centre: x, bottom: y}]
// Writes <out>/<id>.png and <out>/bubbles.json ({id: [x, y, w, h]} in screen px). Layout rules: art/ui/ui.json and demo.js.
const fs = require("fs"), path = require("path");
const [ART, SPEC, OUT] = process.argv.slice(2).map((p) => path.resolve(p));
const { chromium } = require(process.env.PLAYWRIGHT_PATH || "C:/Users/rafam/aris2/app/node_modules/playwright");
const ui = require(path.join(ART, "art/ui/ui.json")), b = ui.bubble;
const sitePath = path.join(ART, "site/src/baked/text.json");
const site = fs.existsSync(sitePath) ? require(sitePath).phrases : {};
const url = (base, f) => "file:///" + path.join(ART, base, f).split(path.sep).join("/");
const phrases = {};  // text -> baked line PNG: the UI kit's first, then the prototype's own lines
for (const p of Object.values(site)) phrases[p.text] = { ...p, src: url("site/src", p.file) };
for (const p of Object.values(b.phrases.lines)) phrases[p.text.replace("\u2019", "'")] = { ...p, src: url("art/ui", p.file) };
const img = (e, src, x, y) => `<img src="${src}" style="left:${x + e.off[0]}px;top:${y + e.off[1]}px;width:${e.w}px;height:${e.h}px">`;
const nine = (e, x, y, w, h, rep) => `<div style="left:${x + e.inset[3]}px;top:${y + e.inset[0]}px;width:${w - e.inset[1] - e.inset[3]}px;height:${h - e.inset[0] - e.inset[2]}px;box-sizing:border-box;border:solid transparent;border-width:${e.slice.join("px ")}px;border-image:url(${url("art/ui", e.file)}) ${e.slice.join(" ")} fill / ${e.slice.join("px ")}px ${rep}"></div>`;
const LW = b.phrases.lineBox[0], PADX = 40, PADT = 30, PADB = 80;
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME_PATH || "C:/Program Files/Google/Chrome/Application/chrome.exe" });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const css = "html,body{margin:0;background:transparent}body>*{position:absolute;margin:0}";
  // a line the kit has not baked: flat ink type drawn the way the kit draws its own (30 px, baseline 29 in a 300 x 38 box)
  const type = (t, x = 0, y = 0) => `<svg style="left:${x}px;top:${y}px;overflow:visible" width="${LW}" height="38"><text x="${LW / 2}" y="29" text-anchor="middle" font-family="Arial Rounded MT, Arial Rounded MT Bold, Segoe UI, sans-serif" font-size="30" fill="#4B2E83">${t}</text></svg>`;
  const measure = async (t) => { await page.setContent(type(t)); return page.evaluate(() => document.querySelector("text").getComputedTextLength()); };
  const out = {};
  for (const s of JSON.parse(fs.readFileSync(SPEC, "utf8"))) {
    const ph = [];
    for (const t of s.lines) ph.push(phrases[t] || { text: t, w: Math.ceil(await measure(t)) });
    const w = Math.min(b.maxWidth, Math.max(b.min[0], Math.max(...ph.map((p) => p.w)) + 2 * b.pad[0]));
    const h = Math.max(b.min[1], ph.length * b.lineHeight + 2 * b.pad[1]), side = s.tip >= s.centre ? "right" : "left", t = b.tails[side];
    const x = Math.round((w < 170 ? s.tip + t.root - t.tip[0] : s.centre) - w / 2), y = s.bottom - h, m = b.radius + 26;
    const root = Math.min(w - m, Math.max(m, s.tip - x + t.root - t.tip[0])), ty = y + (h - ph.length * b.lineHeight) / 2, lx = x + (w - LW) / 2;
    const html = nine(b.body, x, y, w, h, "stretch") + img(t, url("art/ui", t.file), x + root - t.root, y + h - t.overlap) + nine(b.stitch, x, y, w, h, "round") +
      ph.map((p, i) => (p.src ? img(p, p.src, lx, ty + i * b.lineHeight) : type(p.text, lx, ty + i * b.lineHeight))).join("");
    fs.writeFileSync(path.join(OUT, "_bubble.html"), `<!doctype html><style>${css}</style>${html}`);  // a file, so file: images load
    await page.goto("file:///" + path.join(OUT, "_bubble.html").split(path.sep).join("/"), { waitUntil: "load" });
    const clip = { x: x - PADX, y: y - PADT, width: w + 2 * PADX, height: h + PADT + PADB };
    await page.screenshot({ path: path.join(OUT, s.id + ".png"), clip, omitBackground: true });
    out[s.id] = [clip.x, clip.y, clip.width, clip.height];
  }
  fs.writeFileSync(path.join(OUT, "bubbles.json"), JSON.stringify(out));
  await browser.close();
})();
