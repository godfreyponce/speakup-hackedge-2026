"""The Sound Book (#R19 to R29): the in-app guide to reading the sound picture for every English sound.

Content is speakup/data/sound_book.json (written outside the repo by the book build, copied in) and its figures in
speakup/static/book/figures/. Everything is rendered here on the server so the page works offline, with no outside
files, and still reads without JavaScript; the small script only adds search and the index highlight.

Context mode: /book?word=rabbit (and &line=<practice line>) lists the sounds of that word at the top and highlights
their sections. Every section stays on the page so the SLP can compare with the sound the child may have made.
Sound-general: the sounds come from the lexicon, nothing here is r-only."""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from speakup import backnav, lexicon, synthview

BOOK_PATH = Path(__file__).with_name("data") / "sound_book.json"
FIGURES = Path(__file__).with_name("static") / "book" / "figures"
FIGURE_NAME = re.compile(r"[a-z0-9-]+\.png")

# What a section body may contain (the content contract in PLAN-tools-and-book.md, 3b).
ALLOWED_TAGS = frozenset("p h3 h4 ul ol li table thead tbody tr th td b i em strong code sub sup br figure img "
                         "figcaption a span".split())


class BookError(Exception):
    """The book file is missing or broken; the page says so instead of showing half a book."""


@lru_cache(maxsize=4)
def load(path: str = str(BOOK_PATH)) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            book = json.load(f)
    except FileNotFoundError:
        raise BookError(f"The sound book file is not on this machine ({Path(path).name}).") from None
    except (OSError, json.JSONDecodeError) as e:
        raise BookError(f"The sound book file could not be read: {e}") from None
    if not isinstance(book, dict) or not isinstance(book.get("sections"), list):
        raise BookError("The sound book file has no sections.")
    return book


def ordered(book: dict) -> list[tuple[dict, int]]:
    """Every section in reading order with its depth (1 = a top-level part), parents before children."""
    kids: dict[str | None, list[dict]] = {}
    for s in book["sections"]:
        kids.setdefault(s.get("parent"), []).append(s)
    for group in kids.values():
        group.sort(key=lambda s: s.get("order", 0))
    out: list[tuple[dict, int]] = []

    def walk(parent, depth):
        for s in kids.get(parent, []):
            out.append((s, depth))
            walk(s["id"], depth + 1)

    walk(None, 1)
    return out


def home_section(book: dict, phoneme: str) -> dict | None:
    """The sound entry for a phoneme: the snd- section tagged with it that covers the fewest sounds (so eɪ goes to
    its own entry, not the diphthongs table). Falls back to any section tagged with it."""
    tagged = [s for s, _ in ordered(book) if phoneme in s.get("phonemes", [])]
    sounds = [s for s in tagged if s["id"].startswith("snd-")]
    pool = sounds or tagged
    return min(pool, key=lambda s: len(s["phonemes"])) if pool else None


@dataclass
class Sound:
    phoneme: str
    section: dict | None
    target: bool = False


@dataclass
class Context:
    word: str = ""
    line: str = ""
    known: bool = False
    sounds: list[Sound] = field(default_factory=list)
    group: str = synthview.DEFAULT_GROUP  # speaker group for the computer-made pictures
    age_months: int | None = None
    sex_known: bool = False

    @property
    def home_ids(self) -> set[str]:
        return {s.section["id"] for s in self.sounds if s.section}

    @property
    def targets(self) -> list[str]:
        return [s.phoneme for s in self.sounds if s.target]


def picture_group(age: str = "", sex: str = "") -> tuple[str, int | None, bool]:
    """The picture group for ?age= (months) and ?sex= (female or male), the age in months (None when not given) and
    whether the sex was known."""
    from speakup.synth_book import group_for
    try:
        months = int(age) if age.strip() else None
    except ValueError:
        months = None
    sex = sex.strip().lower()
    sex = {"f": "female", "girl": "female", "m": "male", "boy": "male"}.get(sex, sex)
    sex = sex if sex in ("female", "male") else ""
    if months is None and not sex:
        return synthview.DEFAULT_GROUP, None, False
    groups = group_for(months if months is not None else 72, sex or "female")
    return (groups[0] if groups else synthview.DEFAULT_GROUP), months, bool(sex)


def context_for(book: dict, word: str = "", line: str = "", age: str = "", sex: str = "") -> Context:
    """The sounds of the word (or of the whole practice line), first-seen order, each with its section."""
    word, line = word.strip().lower(), line.strip()
    group, age_months, sex_known = picture_group(age, sex)
    if not word and not line:
        return Context(group=group, age_months=age_months, sex_known=sex_known)
    entry = lexicon.entry(word) if word else None
    targets = {t["phoneme"] for t in (entry or {}).get("targets", [])}
    phonemes = lexicon.phonemes_of(line) if line else []
    for p in (entry or {}).get("ipa", []):
        if p not in phonemes:
            phonemes.append(p)
    if line and word and entry:  # the word's own sounds first, then the rest of the line
        own = entry["ipa"]
        phonemes = [p for p in own if p in phonemes] + [p for p in phonemes if p not in own]
        phonemes = list(dict.fromkeys(phonemes))
    sounds = [Sound(p, home_section(book, p), p in targets) for p in phonemes]
    return Context(word=word, line=line, known=bool(phonemes), sounds=sounds, group=group, age_months=age_months,
                   sex_known=sex_known)


def _body(html: str) -> str:
    """Figures are served from /book/figures/ wherever the page is opened."""
    return html.replace('src="figures/', 'src="/book/figures/')


def _ipa(p: str) -> str:
    return f"/{escape(p)}/"


def _sources(book: dict, keys: list[str]) -> str:
    refs = book.get("references", {})
    items = []
    for k in keys:
        r = refs.get(k)
        if r is None:
            continue
        text = escape(r.get("text", k))
        if r.get("doi"):
            text += f" DOI {escape(r['doi'])}."
        if not r.get("verified", True):
            text += ' <span class="unverified">UNVERIFIED</span>'
        items.append(f"<li>{text}</li>")
    if not items:
        return ""
    return f'<details class="src"><summary>Sources ({len(items)})</summary><ol>{"".join(items)}</ol></details>'


def _section(book: dict, s: dict, depth: int, titles: dict[str, str], ctx: Context) -> str:
    sid = escape(s["id"])
    classes = [f"sec d{min(depth, 4)}"]
    note = ""
    mine = [x.phoneme for x in ctx.sounds if x.section and x.section["id"] == s["id"]]
    if mine:
        classes.append("ctx-home")
        who = " ".join(_ipa(p) for p in mine)
        note = f'<p class="ctx-note">In {escape(ctx.word or "this line")}: {who}</p>'
    elif ctx.targets and set(ctx.targets) & set(s.get("phonemes", [])):
        classes.append("ctx-rel")
    tags = ""
    if s.get("phonemes"):
        tags = '<p class="tags">Sounds: ' + " ".join(f"<span>{_ipa(p)}</span>" for p in s["phonemes"]) + "</p>"
    compare = ""
    links = [c for c in s.get("confused_with", []) if c in titles]
    if links:
        compare = ('<p class="compare"><b>Often confused with:</b> '
                   + ", ".join(f'<a href="#{escape(c)}">{escape(titles[c])}</a>' for c in links) + "</p>")
    heading = f'<h2>{escape(s["title"])}</h2>'
    return (f'<section id="{sid}" class="{" ".join(classes)}" data-kw="{escape(" ".join(s.get("keywords", [])))}" '
            f'data-ph="{escape(" ".join(s.get("phonemes", [])))}">{heading}{note}{tags}'
            f'<div class="body">{_body(s.get("body_html", ""))}</div>{synthview.viewer(book, s["id"], ctx.group)}'
            f'{compare}{_sources(book, s.get("refs", []))}'
            f"</section>")


def _index(tree: list[tuple[dict, int]], ctx: Context) -> str:
    homes, out = ctx.home_ids, []
    rel = set(ctx.targets)
    for s, depth in tree:
        cls = f"i{min(depth, 3)}"
        if s["id"] in homes:
            cls += " ctx-home"
        elif rel & set(s.get("phonemes", [])):
            cls += " ctx-rel"
        out.append(f'<li class="{cls}"><a href="#{escape(s["id"])}">{escape(s["title"])}</a></li>')
    key = ""
    if homes:
        what = escape(ctx.word or "this line")
        also = " ".join(_ipa(p) for p in ctx.targets)
        key = (f'<p class="key"><span class="dot"></span>Sounds in {what}'
               + (f'<br><span class="star">*</span> Also about {also}' if also else "") + "</p>")
    return f'{key}<ul class="toc">{"".join(out)}</ul>'


def _context_panel(book: dict, ctx: Context, titles: dict[str, str]) -> str:
    if not ctx.word and not ctx.line:
        return ""
    label = f"For this word: {escape(ctx.word)}" if ctx.word else "For this line"
    line = f'<p class="ctx-line">Line: {escape(ctx.line)}</p>' if ctx.line else ""
    if not ctx.known:
        return (f'<div class="ctx card" id="for-this-word"><h2>{label}</h2>{line}<p class="hint">This word is not in '
                "the word list yet, so no sounds are highlighted. Use the index or search to find a sound.</p></div>")
    chips = []
    for x in ctx.sounds:
        tgt = '<small>Target</small>' if x.target else ""
        if x.section:
            chips.append(f'<a class="chip{" tgt" if x.target else ""}" href="#{escape(x.section["id"])}">'
                         f'<b>{_ipa(x.phoneme)}</b><span>{escape(x.section["title"])}</span>{tgt}</a>')
        else:
            chips.append(f'<span class="chip none"><b>{_ipa(x.phoneme)}</b><span>No entry yet</span></span>')
    extra = ""
    for x in ctx.sounds:
        if not (x.target and x.section):
            continue
        conf = [c for c in x.section.get("confused_with", []) if c in titles]
        errs = [s for s, _ in ordered(book) if s["id"].startswith("err-") and x.phoneme in s.get("phonemes", [])]
        bits = []
        if conf:
            bits.append("<b>Compare with:</b> " + ", ".join(f'<a href="#{escape(c)}">{escape(titles[c])}</a>'
                                                            for c in conf))
        if errs:
            bits.append("<b>Errors to check:</b> " + ", ".join(f'<a href="#{escape(e["id"])}">{escape(e["title"])}</a>'
                                                              for e in errs))
        if bits:
            extra += f'<p class="ctx-more">For {_ipa(x.phoneme)}: ' + "<br>".join(bits) + "</p>"
    strip = synthview.context_strip(book, [x.phoneme for x in ctx.sounds], ctx.word, ctx.group, ctx.sex_known,
                                    ctx.age_months)
    return (f'<div class="ctx card" id="for-this-word"><h2>{label}</h2>{line}<div class="chips">{"".join(chips)}</div>'
            f"{extra}{strip}<p class=\"hint\">These sections are highlighted below. Every other section is still here: search "
            "or use the index to look up the sound you think the child actually made and compare.</p></div>")


BOOK_CSS = """
  * { box-sizing: border-box; }
  html { scroll-padding-top: 76px; }
  body { margin: 0; background: #f3f5f8; color: #16202c;
         font: 15px/1.55 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; font-variant-numeric: tabular-nums; }
  a { color: #1d4f91; }
  .top { position: sticky; top: 0; z-index: 5; display: flex; align-items: center; gap: 18px; background: #fff;
         border-bottom: 1px solid #d9dfe7; padding: 10px 24px; }
  .brand { font-weight: 700; color: #1d4f91; white-space: nowrap; }
  .brand span { color: #16202c; font-weight: 600; }
  .search { position: relative; flex: 1; max-width: 560px; }
  .search input { width: 100%; font: inherit; padding: 8px 12px; border: 1px solid #c4ccd6; border-radius: 6px; }
  .search input:focus { outline: 2px solid #1d4f91; outline-offset: -1px; border-color: #1d4f91; }
  .results { position: absolute; left: 0; right: 0; top: 42px; background: #fff; border: 1px solid #d9dfe7;
             border-radius: 8px; box-shadow: 0 8px 24px rgba(20,32,44,.14); max-height: 70vh; overflow: auto; display: none; }
  .results.open { display: block; }
  .results .count { font-size: 12px; color: #6b7785; padding: 8px 12px; border-bottom: 1px solid #edf0f4; }
  .results a { display: block; padding: 8px 12px; text-decoration: none; color: inherit; border-bottom: 1px solid #f0f2f5; }
  .results a:hover, .results a.sel { background: #e8eef7; }
  .results b { display: block; font-size: 14px; color: #1d4f91; }
  .results small { display: block; font-size: 11px; color: #6b7785; text-transform: uppercase; letter-spacing: .04em; }
  .results span { display: block; font-size: 13px; color: #44505e; }
  .links { display: flex; gap: 14px; font-size: 13px; white-space: nowrap; }
  .layout { display: grid; grid-template-columns: 290px 1fr; gap: 24px; max-width: 1400px; margin: 0 auto; padding: 18px 24px 60px; }
  nav.index { position: sticky; top: 70px; max-height: calc(100vh - 86px); overflow: auto; background: #fff;
              border: 1px solid #d9dfe7; border-radius: 8px; padding: 8px 6px; font-size: 13px; }
  nav.index h3 { margin: 4px 8px 6px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #6b7785; }
  .toc { list-style: none; margin: 0; padding: 0; }
  .toc a { display: block; padding: 3px 8px; border-radius: 5px; text-decoration: none; color: #2b3746; }
  .toc a:hover { background: #f0f4fa; }
  .toc .i1 a { font-weight: 700; color: #16202c; margin-top: 8px; }
  .toc .i2 a { padding-left: 16px; }
  .toc .i3 a { padding-left: 30px; color: #44505e; }
  .toc .here a { background: #e8eef7; box-shadow: inset 3px 0 0 #1d4f91; }
  .toc .ctx-home a { color: #7a4b00; font-weight: 700; }
  .toc .ctx-home a::before { content: ""; display: inline-block; width: 8px; height: 8px; border-radius: 50%;
                             background: #d08b00; margin-right: 6px; vertical-align: 1px; }
  .toc .ctx-rel a::after { content: " *"; color: #d08b00; }
  .key { margin: 0 8px 6px; font-size: 12px; color: #6b7785; }
  .key .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #d08b00; margin-right: 6px; }
  .key .star { color: #d08b00; font-weight: 700; margin: 0 4px 0 1px; }
  .toc .hit a { background: #fff4c2; }
  .toc .miss a { opacity: .45; }
  main { min-width: 0; }
  .card { background: #fff; border: 1px solid #d9dfe7; border-radius: 8px; padding: 14px 18px; }
  .ctx { border-color: #e7c27a; background: #fffaf0; margin-bottom: 18px; }
  .ctx h2 { margin: 0 0 6px; font-size: 22px; }
  .ctx-line { margin: 0 0 8px; color: #44505e; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
  .chip { display: grid; grid-template-columns: auto; padding: 6px 12px; border: 1px solid #e0c58d; border-radius: 8px;
          background: #fff; text-decoration: none; color: #16202c; min-width: 110px; }
  .chip b { font-size: 20px; }
  .chip span { font-size: 12px; color: #44505e; }
  .chip small { font-size: 11px; font-weight: 700; color: #7a4b00; text-transform: uppercase; letter-spacing: .05em; }
  .chip.tgt { border: 2px solid #d08b00; }
  .chip.none { opacity: .6; }
  .ctx-more { font-size: 14px; margin: 8px 0; }
  .hint { color: #6b7785; font-size: 13px; margin: 8px 0 0; }
  .sec { background: #fff; border: 1px solid #d9dfe7; border-radius: 8px; padding: 6px 22px 14px; margin-bottom: 14px; }
  .sec.d1 { background: #1d4f91; color: #fff; border-color: #1d4f91; padding: 14px 22px; margin-top: 30px; }
  .sec.d1 a { color: #dfe9f7; }
  .sec.d1 h2 { font-size: 24px; }
  .sec h2 { font-size: 20px; margin: 10px 0 6px; }
  .sec.d4 { margin-left: 22px; }
  .sec.d4 h2 { font-size: 17px; }
  .sec.ctx-home { border: 2px solid #d08b00; box-shadow: inset 6px 0 0 #d08b00; }
  .sec.ctx-rel { box-shadow: inset 4px 0 0 #f0d9a4; }
  .sec.flash { animation: flash 1.4s ease-out; }
  @keyframes flash { from { background: #fff1c2; } to { background: #fff; } }
  .ctx-note { display: inline-block; margin: 0 0 6px; font-size: 12px; font-weight: 700; color: #7a4b00;
              background: #fff1d6; padding: 2px 8px; border-radius: 4px; }
  .tags { margin: 0 0 6px; font-size: 13px; color: #6b7785; }
  .tags span { display: inline-block; background: #eef1f5; color: #16202c; border-radius: 4px; padding: 0 6px; margin-right: 4px; }
  .body h3 { font-size: 15px; margin: 16px 0 4px; color: #1d4f91; }
  .body h4 { font-size: 14px; margin: 12px 0 4px; }
  .body p, .body li { max-width: 78ch; }
  .sec, .ctx, .results { overflow-wrap: anywhere; }
  .body table { border-collapse: collapse; font-size: 13px; margin: 8px 0; display: block; overflow-x: auto; }
  .body th, .body td { border-bottom: 1px solid #e3e7ec; padding: 5px 12px 5px 0; text-align: left; vertical-align: top; }
  .body th { font-size: 12px; color: #44505e; border-bottom-color: #c4ccd6; }
  .body figure { margin: 12px 0; }
  .body img { max-width: min(100%, 900px); height: auto; border: 1px solid #e3e7ec; border-radius: 6px; background: #fff; }
  .body figcaption { font-size: 13px; color: #44505e; margin-top: 4px; max-width: 78ch; }
  .unverified { font-size: 11px; font-weight: 700; color: #9b2c13; background: #fbe3dd; border-radius: 3px; padding: 0 4px; }
  .compare { font-size: 14px; background: #f3f6fa; border-radius: 6px; padding: 8px 12px; margin: 12px 0 0; }
  details.src { font-size: 13px; color: #44505e; margin-top: 10px; }
  details.src summary { cursor: pointer; color: #1d4f91; }
  details.src ol { margin: 6px 0 0 18px; padding: 0; }
  mark { background: #ffe58a; color: inherit; padding: 0 1px; border-radius: 2px; }
  .problem { max-width: 700px; margin: 60px auto; }
  @media (max-width: 860px) {
    .layout { grid-template-columns: 1fr; padding: 12px 16px 40px; }
    nav.index { position: static; max-height: 40vh; }
    .top { flex-wrap: wrap; padding: 10px 16px; }
    .sec { padding: 6px 14px 12px; }
    .sec.d4 { margin-left: 0; }
  }
  @media print {
    .top, nav.index, details.src summary { display: none; }
    .layout { display: block; padding: 0; }
    .sec, .sec.d1 { border: 0; box-shadow: none; background: #fff; color: #16202c; }
  }
"""

BOOK_JS = r"""
(() => {
  const box = document.getElementById("q"), out = document.getElementById("results");
  const secs = [...document.querySelectorAll("main section.sec")];
  const tocLinks = new Map([...document.querySelectorAll(".toc a")].map(a => [a.getAttribute("href").slice(1), a.parentNode]));
  const parentTitle = {};
  let part = "";
  secs.forEach(s => { if (s.classList.contains("d1")) part = s.querySelector("h2").textContent; parentTitle[s.id] = part; });
  const textOf = el => {  // text with a space between nodes, so "Gliding" and "Sounds" do not run together
    const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT), parts = [];
    let block = null;
    while (w.nextNode()) {
      const b = w.currentNode.parentNode.closest("p, li, h2, h3, h4, td, th, figcaption, summary");
      if (b !== block) parts.push(" ");
      block = b;
      parts.push(w.currentNode.nodeValue);
    }
    return parts.join("").replace(/\s+/g, " ").trim();
  };
  const items = secs.map(s => ({ s, id: s.id, title: s.querySelector("h2").textContent,
    kw: (s.dataset.kw + " " + s.dataset.ph).toLowerCase(), text: textOf(s.querySelector(".body") || s),
    all: textOf(s) }));
  items.forEach(it => { it.low = it.text.toLowerCase(); it.allLow = it.all.toLowerCase(); });
  const esc = t => t.replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const reEsc = t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  let sel = -1, shown = [];

  function clearMarks() {
    document.querySelectorAll("main mark").forEach(m => { const p = m.parentNode; p.replaceChild(document.createTextNode(m.textContent), m); p.normalize(); });
  }
  function markIn(el, re) {
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, { acceptNode: n =>
      n.parentNode.closest("summary") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT });
    const nodes = [];
    while (walk.nextNode()) nodes.push(walk.currentNode);
    nodes.forEach(n => {
      re.lastIndex = 0;
      if (!re.test(n.nodeValue)) return;
      re.lastIndex = 0;
      const frag = document.createDocumentFragment();
      let last = 0, m;
      while ((m = re.exec(n.nodeValue))) {
        frag.append(n.nodeValue.slice(last, m.index));
        const mk = document.createElement("mark"); mk.textContent = m[0]; frag.append(mk);
        last = m.index + m[0].length;
        if (!m[0].length) re.lastIndex++;
      }
      frag.append(n.nodeValue.slice(last));
      n.parentNode.replaceChild(frag, n);
    });
  }
  function snippet(it, words) {
    const i = Math.max(0, ...words.map(w => it.low.indexOf(w)).filter(i => i >= 0).slice(0, 1));
    const a = Math.max(0, i - 50), b = Math.min(it.text.length, i + 110);
    let t = esc((a ? "..." : "") + it.text.slice(a, b) + (b < it.text.length ? "..." : ""));
    const re = new RegExp("(" + words.map(w => reEsc(esc(w))).join("|") + ")", "gi");
    return t.replace(re, "<mark>$1</mark>");
  }
  function search() {
    const q = box.value.trim().toLowerCase();
    clearMarks();
    tocLinks.forEach(li => li.classList.remove("hit", "miss"));
    sel = -1;
    if (q.length < 2) { out.classList.remove("open"); out.innerHTML = ""; shown = []; return; }
    const words = q.split(/\s+/).filter(Boolean);
    shown = items.map(it => {
      if (!words.every(w => it.allLow.includes(w) || it.kw.includes(w))) return null;
      let score = 0;
      words.forEach(w => {
        if (it.title.toLowerCase().includes(w)) score += 50;
        if (it.kw.includes(w)) score += 20;
        score += Math.min(20, it.allLow.split(w).length - 1);
      });
      return { it, score };
    }).filter(Boolean).sort((x, y) => y.score - x.score);
    const ids = new Set(shown.map(r => r.it.id));
    tocLinks.forEach((li, id) => li.classList.add(ids.has(id) ? "hit" : "miss"));
    const re = new RegExp(words.map(reEsc).join("|"), "gi");
    shown.slice(0, 40).forEach(r => markIn(r.it.s.querySelector(".body") || r.it.s, re));
    out.innerHTML = `<div class="count">${shown.length ? shown.length + " section" + (shown.length > 1 ? "s" : "") + " match. Enter opens the first, arrows move." : "No section matches."}</div>` +
      shown.slice(0, 60).map((r, i) => `<a href="#${r.it.id}" data-i="${i}"><small>${esc(parentTitle[r.it.id] || "")}</small><b>${esc(r.it.title)}</b><span>${snippet(r.it, words)}</span></a>`).join("");
    out.classList.add("open");
  }
  function go(id) {
    const s = document.getElementById(id);
    if (!s) return;
    history.replaceState(null, "", location.search + "#" + id);
    s.scrollIntoView({ block: "start" });
    const m = s.querySelector("mark");
    if (m) m.scrollIntoView({ block: "center" });
    s.classList.remove("flash"); void s.offsetWidth; s.classList.add("flash");
    out.classList.remove("open");
  }
  function pick(i) {
    const links = out.querySelectorAll("a");
    links.forEach(a => a.classList.remove("sel"));
    if (links[i]) { links[i].classList.add("sel"); links[i].scrollIntoView({ block: "nearest" }); }
    sel = i;
  }
  let timer;
  box.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(search, 120); });
  box.addEventListener("focus", () => { if (shown.length) out.classList.add("open"); });
  box.addEventListener("keydown", e => {
    const n = Math.min(shown.length, 60);
    if (e.key === "ArrowDown" && n) { e.preventDefault(); pick((sel + 1) % n); }
    else if (e.key === "ArrowUp" && n) { e.preventDefault(); pick((sel - 1 + n) % n); }
    else if (e.key === "Enter" && n) { e.preventDefault(); go(shown[Math.max(sel, 0)].it.id); }
    else if (e.key === "Escape") { box.value = ""; search(); }
  });
  out.addEventListener("click", e => { const a = e.target.closest("a"); if (a) { e.preventDefault(); go(a.getAttribute("href").slice(1)); } });
  document.addEventListener("click", e => { if (!e.target.closest(".search")) out.classList.remove("open"); });
  document.addEventListener("keydown", e => {
    if (e.key === "/" && document.activeElement !== box) { e.preventDefault(); box.focus(); box.select(); }
  });
  document.querySelectorAll(".toc a, main a[href^='#']").forEach(a => a.addEventListener("click", e => {
    e.preventDefault(); go(a.getAttribute("href").slice(1));
  }));
  // Index follows the reading position.
  let here = null;
  const spy = new IntersectionObserver(es => {
    es.forEach(en => { if (en.isIntersecting) {
      const li = tocLinks.get(en.target.id);
      if (!li || li === here) return;
      if (here) here.classList.remove("here");
      here = li; li.classList.add("here");
      const nav = document.querySelector("nav.index"), r = li.getBoundingClientRect(), nr = nav.getBoundingClientRect();
      if (r.top < nr.top || r.bottom > nr.bottom) nav.scrollTop += r.top - nr.top - nr.height / 3;
    } });
  }, { rootMargin: "-80px 0px -70% 0px" });
  secs.forEach(s => spy.observe(s));
  if (location.hash.length > 1) setTimeout(() => go(decodeURIComponent(location.hash.slice(1))), 0);
})();
"""


def _page(title: str, top: str, body: str, script: str = "") -> str:
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
            f"<title>{escape(title)}, Speak Up</title>\n<style>{BOOK_CSS}{backnav.CSS}{synthview.CSS}</style>\n</head>\n<body>\n{top}\n{body}\n"
            + (f"<script>{script}</script>\n" if script else "") + "</body>\n</html>\n")


def problem_page(message: str) -> str:
    return _page("Sound book", '<header class="top"><span class="brand">Speak Up <span>Sound Book</span></span></header>',
                 f'<div class="card problem"><h2>The sound book cannot open</h2><p>{escape(message)}</p></div>')


def safe_back(back: str) -> str:
    """The app page the book returns to, or "" when it is not a plain path on this server (never another site)."""
    back = (back or "").strip()
    if not back.startswith("/") or back.startswith("//") or any(c in back for c in "\\\r\n\t<>\"'"):
        return ""
    return back if len(back) <= 600 else ""


BACK_JS = r"""
(() => {
  // Back to where you were: when the book was opened from that spot in this tab, go back in history, so the page comes
  // back exactly as it was (full view open, scroll kept); otherwise open the page from the address the link carries.
  const b = document.getElementById("book-back");
  if (!b) return;
  b.addEventListener("click", e => {
    let from = null;
    try { from = sessionStorage.getItem("speakup.bookFrom"); } catch (err) { /* private window */ }
    if (from === b.dataset.back && history.length > 1) { e.preventDefault(); history.back(); }
  });
})();
"""


def book_page(word: str = "", line: str = "", book: dict | None = None, age: str = "", sex: str = "",
              back: str = "") -> str:
    """The whole book, with an index, search and, when a word is given, the "For this word" panel. age (months) and
    sex choose the speaker of the computer-made pictures. back: the app page it was opened from (with the spot to
    restore after a #), shown as a "Back to where you were" button."""
    book = book if book is not None else load()
    back = safe_back(back)
    ctx = context_for(book, word, line, age, sex)
    tree = ordered(book)
    titles = {s["id"]: s["title"] for s, _ in tree}
    sections = "".join(_section(book, s, d, titles, ctx) for s, d in tree)
    q = {}
    if ctx.word:
        q["word"] = ctx.word
    if back:
        q["back"] = back
    back_btn = backnav.html(back, "Back to where you were", id="book-back", data_back=back) if back else ""
    print_link = '<a href="/book/print" target="_blank">Printable version</a>'
    this_word = '<a href="#for-this-word">This word</a>' if ctx.word or ctx.line else ""
    top = (f'<header class="top">{back_btn}<a class="brand" href="/book{"?" + escape(urlencode(q)) if q else ""}" '
           'style="text-decoration:none">'
           'Speak Up <span>Sound Book</span></a>'
           '<div class="search"><input id="q" type="search" placeholder="Search the book, for example gliding, F3, burst, lisp"'
           ' autocomplete="off" aria-label="Search the sound book"><div id="results" class="results" role="listbox"></div></div>'
           f'<nav class="links">{this_word}{print_link}</nav></header>')
    body = (f'<div class="layout"><nav class="index" aria-label="Index"><h3>Index</h3>{_index(tree, ctx)}</nav>'
            f"<main>{_context_panel(book, ctx, titles)}{sections}</main></div>")
    title = f"Sound book: {ctx.word}" if ctx.word else "Sound book"
    return _page(title, top, body, f"window.SV_DATA = {synthview.data_json(book)};\n{BOOK_JS}\n{BACK_JS}\n{synthview.JS}")


PRINT_CSS = """
  body { background: #fff; }
  .layout { display: block; max-width: 900px; padding: 18px 24px 40px; }
  .sec, .sec.d1 { background: #fff; color: #16202c; border: 0; border-bottom: 1px solid #d9dfe7; border-radius: 0; margin: 0; }
  .sec.d1 { border-bottom: 3px solid #1d4f91; margin-top: 18px; }
  .sec.d1 h2 { color: #1d4f91; }
  .sec.d4 { margin-left: 0; }
  details.src[open] summary { display: none; }
  .printtoc { columns: 2; font-size: 13px; }
  .printtoc a { color: #1d4f91; }
  @media print { .noprint { display: none; } .sec.d1 { break-before: page; } .sec { break-inside: auto; } }
"""


def print_page(book: dict | None = None) -> str:
    """Every section in order, no search, sources open: for paper or Save as PDF."""
    book = book if book is not None else load()
    tree = ordered(book)
    titles = {s["id"]: s["title"] for s, _ in tree}
    ctx = Context()
    sections = "".join(_section(book, s, d, titles, ctx).replace('<details class="src">', '<details class="src" open>')
                       for s, d in tree)
    toc = "".join(f'<li style="margin-left:{(d - 1) * 14}px"><a href="#{escape(s["id"])}">{escape(s["title"])}</a></li>'
                  for s, d in tree if d <= 2)
    body = (f'<div class="layout"><h1>{escape(book.get("title", "Sound Book"))}</h1>'
            '<p class="noprint"><button onclick="window.print()">Print</button> <a href="/book">Back to the book</a></p>'
            f'<h2>Contents</h2><ul class="printtoc" style="list-style:none;padding:0">{toc}</ul>{sections}</div>')
    return _page("Sound book, printable", f"<style>{PRINT_CSS}</style>", body)


def figure_path(name: str) -> Path | None:
    """The figure file for /book/figures/<name>, or None for anything that is not a plain figure name."""
    return FIGURES / name if FIGURE_NAME.fullmatch(name) else None
