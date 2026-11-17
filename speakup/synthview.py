"""The sound book's picture viewer: computer-made spectrograms (scripts/build_synth_pictures.py) for each sound and
error section, chosen by age and sex, with a side-by-side comparison. There is no Play button: the computer-made sound
was too rough to hear the differences between the sounds (owner, 2026-11-05), so only the pictures are shown.

Everything is rendered on the server for the default choice, so the pictures read without JavaScript; the small script
swaps pictures when a selector changes."""

import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

SYNTH_DIR = Path(__file__).with_name("static") / "book" / "synth"
INDEX_PATH = SYNTH_DIR / "index.json"
NAME = re.compile(r"([a-z0-9-]+?)-((?:girl|boy)(?:6|10)|woman|man)\.(png)")
DEFAULT_GROUP = "girl6"


@lru_cache(maxsize=2)
def index(path: str = str(INDEX_PATH)) -> dict | None:
    """The picture index, or None when the pictures are not on this machine (the book still works without them)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    data["by_key"] = {(p["item"], p["group"]): p for p in data["pictures"]}
    data["item_by_id"] = {i["id"]: i for i in data["items"]}
    data["group_by_id"] = {g["id"]: g for g in data["groups"]}
    return data


def short_cite(text: str) -> str:
    """'Hillenbrand, J., Getty, L. A., ... (1995). Title' -> 'Hillenbrand et al. 1995'."""
    m = re.match(r"(.+?)\((\d{4})\)", text)
    if not m:
        return text.split(".")[0]
    names = re.findall(r"([A-Z][A-Za-z'\- ]+?), (?:[A-Z]\.[ -]?)+", m.group(1))
    if not names:
        return f"{m.group(1).split(',')[0].strip()} {m.group(2)}"
    if len(names) == 1:
        who = names[0]
    elif len(names) == 2:
        who = f"{names[0]} and {names[1]}"
    else:
        who = f"{names[0]} et al."
    return f"{who} {m.group(2)}"


def _refs(book: dict, idx: dict) -> dict[str, str]:
    out = {k: short_cite(v["text"]) for k, v in idx.get("extra_refs", {}).items()}
    out.update({k: short_cite(v.get("text", k)) for k, v in book.get("references", {}).items()})
    return out


def caption(pic: dict, refs: dict[str, str]) -> str:
    """The plain caption under a picture."""
    src = ", ".join(refs.get(k, k) for k in pic["sources"])
    text = f"Computer-made from published averages ({src}), not a recording."
    if pic["estimated"]:
        text += " Estimated: " + "; ".join(pic["reasons"]) + "."
    return text


def values_table(pic: dict) -> str:
    rows = []
    for v in pic["values"]:
        if v["unit"] == "none":
            val = "no single peak" if "Noise" in v["what"] else "shaped by the vowel"
        else:
            val = f"{v['value']:,} {v['unit']}"
        st = '<span class="est">estimated</span>' if v["status"] == "estimated" else "published"
        rows.append(f"<tr><td>{escape(v['what'])}</td><td>{escape(val)}</td><td>{st}</td></tr>")
    return ('<table class="sv-values"><thead><tr><th>Value used</th><th></th><th>From</th></tr></thead>'
            f"<tbody>{''.join(rows)}</tbody></table>")


def figure(idx: dict, item: str, group: str, refs: dict[str, str], role: str = "") -> str:
    pic = idx["by_key"].get((item, group))
    if pic is None:
        return ""
    it, g = idx["item_by_id"][item], idx["group_by_id"][group]
    head = f"{escape(role)}: " if role else ""
    tag = '<span class="sv-tag est">Estimated</span>' if pic["estimated"] else \
        '<span class="sv-tag pub">From published averages</span>'
    return (f'<figure class="sv-fig" data-item="{escape(item)}" data-group="{escape(group)}">'
            f'<div class="sv-title"><b>{head}{escape(it["title"])}</b>, {escape(g["label"])} {tag}</div>'
            f'<img src="/book/synth/{escape(pic["file"])}" alt="Computer-made spectrogram: {escape(it["title"])}, '
            f'{escape(g["label"])}" loading="lazy" width="640" height="290">'
            f'<p class="sv-look"><b>Look for:</b> {escape(it.get("look_for", ""))}</p>'
            f'<figcaption>{escape(caption(pic, refs))}</figcaption>'
            f"<details class=\"sv-more\"><summary>Values used</summary>{values_table(pic)}</details></figure>")


def _options(pairs: list[tuple[str, str]], chosen: str) -> str:
    return "".join(f'<option value="{escape(v)}"{" selected" if v == chosen else ""}>{escape(t)}</option>'
                   for v, t in pairs)


def _compare_options(idx: dict, chosen: str) -> str:
    kinds = (("vowel", "Vowels"), ("r-vowel", "Vowels"), ("diphthong", "Vowels"), ("approximant", "r w l j"),
             ("stop", "Stops"), ("fricative", "Fricatives"), ("affricate", "Affricates"), ("nasal", "Nasals"),
             ("error", "Error versions"))
    groups: dict[str, list] = {}
    for kind, label in kinds:
        groups.setdefault(label, []).extend(i for i in idx["items"] if i["kind"] == kind)
    out = [f'<option value=""{" selected" if not chosen else ""}>Nothing (one picture)</option>']
    for label, items in groups.items():
        out.append(f'<optgroup label="{escape(label)}">'
                   + _options([(i["id"], i["title"]) for i in items], chosen) + "</optgroup>")
    return "".join(out)


def _group_selects(idx: dict, group: str) -> str:
    g = idx["group_by_id"][group]
    ages = list(dict.fromkeys((x["age_band"], x["age_label"]) for x in idx["groups"]))
    return (f'<label>Age <select class="sv-age">{_options(ages, g["age_band"])}</select></label>'
            f'<label>Sex <select class="sv-sex">{_options([("female", "Girl or woman"), ("male", "Boy or man")], g["sex"])}'
            "</select></label>")


def viewer(book: dict, section_id: str, group: str | None = None) -> str:
    """The picture viewer for one book section, or "" when the section has no pictures."""
    idx = index()
    if idx is None:
        return ""
    items = idx["sections"].get(section_id, {}).get("items", [])
    pairs = idx["pairs"].get(section_id, [])
    if not items and not pairs:
        return ""
    group = group if group in idx["group_by_id"] else DEFAULT_GROUP
    refs = _refs(book, idx)
    if pairs:
        first, compare = pairs[0]
        choices = list(dict.fromkeys([p[0] for p in pairs] + [p[1] for p in pairs]))
        intro = ("The usual sound on the left, the error on the right, both computer-made for the same speaker. "
                 "Change the age, the sex or either sound.")
    else:
        first, compare = items[0], ""
        choices = items
        intro = "Choose the speaker's age and sex. Compare puts a second sound beside this one."
    pick = ""
    if len(choices) > 1 or pairs:
        pick = (f'<label>Sound <select class="sv-item">'
                f'{_options([(i, idx["item_by_id"][i]["title"]) for i in choices], first)}</select></label>')
    figs = figure(idx, first, group, refs, "Target" if pairs else "") + \
        (figure(idx, compare, group, refs, "Error" if pairs else "Compare") if compare else "")
    return (f'<div class="sv" data-group="{escape(group)}">'
            f'<h3>Computer-made sound pictures</h3><p class="sv-intro">{intro}</p>'
            f'<div class="sv-controls">{pick}{_group_selects(idx, group)}'
            f'<label>Compare with <select class="sv-compare">{_compare_options(idx, compare)}</select></label></div>'
            f'<div class="sv-pics{" two" if compare else ""}">{figs}</div></div>')


def context_strip(book: dict, phonemes: list[str], word: str, group: str, sex_known: bool,
                  age_months: int | None) -> str:
    """Pictures of the word's sounds at the child's age (and sex when known), for the "For this word" panel."""
    from speakup.synth_book import PHONEME_ITEM
    idx = index()
    if idx is None:
        return ""
    refs = _refs(book, idx)
    figs, seen = [], set()
    for p in phonemes:
        item = PHONEME_ITEM.get(p)
        if item == "c-r" and any(i["word"] == word for i in idx["items"] if i["id"] == "w-rabbit"):
            item = "w-rabbit"  # the word itself is drawn: show it
        if not item or item in seen or (item, group) not in idx["by_key"]:
            continue
        seen.add(item)
        figs.append(figure(idx, item, group, refs))
    if not figs:
        return ""
    g = idx["group_by_id"][group]
    from speakup.synth_book import age_band
    if age_months is None:
        who = ["no age given, so 6 years is shown"]
    elif age_band(age_months)[1]:
        who = [f"no pictures for the child's exact age, so the nearest older band ({g['age_label'].lower()}) is shown"]
    else:
        who = [f"the child's age band, {g['age_label'].lower()}"]
    if not sex_known:
        who.append("the child's sex is not recorded, so a " + ("girl's" if g["sex"] == "female" else "boy's")
                   + " voice is shown (change it with Sex)")
    return (f'<div class="sv sv-ctx" data-group="{escape(group)}"><h3>Pictures of these sounds</h3>'
            f'<p class="sv-intro">Computer-made for a typical speaker: {escape("; ".join(who))}. Compare them with '
            f'the child\'s own recording.</p><div class="sv-controls">{_group_selects(idx, group)}</div>'
            f'<div class="sv-pics strip">{"".join(figs)}</div></div>')


def data_json(book: dict) -> str:
    """What the script needs to swap pictures: per picture its caption, tag and values, as compact JSON."""
    idx = index()
    if idx is None:
        return "null"
    refs = _refs(book, idx)
    pics = {}
    for p in idx["pictures"]:
        pics[f"{p['item']}|{p['group']}"] = {"f": p["file"], "e": p["estimated"], "c": caption(p, refs),
                                             "v": values_table(p)}
    data = {"pics": pics, "items": {i["id"]: i["title"] for i in idx["items"]},
            "look": {i["id"]: i.get("look_for", "") for i in idx["items"]},
            "groups": {g["id"]: {"age": g["age_band"], "sex": g["sex"], "label": g["label"]} for g in idx["groups"]}}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def png_path(name: str) -> Path | None:
    m = NAME.fullmatch(name)
    return SYNTH_DIR / name if m and m.group(3) == "png" else None


CSS = """
  .sv { margin: 16px 0 6px; padding: 12px 14px; background: #f7f9fc; border: 1px solid #d9dfe7; border-radius: 8px; }
  .sv h3 { margin: 0 0 4px !important; font-size: 15px; color: #1d4f91; }
  .sv-intro { margin: 0 0 8px; font-size: 13px; color: #44505e; }
  .sv-controls { display: flex; flex-wrap: wrap; gap: 8px 16px; font-size: 13px; margin-bottom: 8px; }
  .sv-controls label { display: flex; align-items: center; gap: 6px; color: #2b3746; }
  .sv-controls select { font: inherit; padding: 4px 6px; border: 1px solid #c4ccd6; border-radius: 5px; background: #fff;
                        max-width: 260px; }
  .sv-pics { display: grid; grid-template-columns: minmax(0, 660px); gap: 12px; }
  .sv-pics.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sv-pics.strip { grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
  .sv-fig { margin: 0; background: #fff; border: 1px solid #e3e7ec; border-radius: 6px; padding: 8px; min-width: 0; }
  .sv-fig img { width: 100%; height: auto; border: 0; display: block; }
  .sv-title { font-size: 13px; margin-bottom: 4px; }
  .sv-tag { font-size: 11px; font-weight: 700; border-radius: 3px; padding: 0 5px; margin-left: 4px; white-space: nowrap; }
  .sv-tag.est { color: #9b2c13; background: #fbe3dd; }
  .sv-tag.pub { color: #2b6a2b; background: #e3f2e3; }
  .sv-look { font-size: 13px; margin: 6px 0 0; color: #16202c; }
  .sv-fig figcaption { font-size: 12px; color: #44505e; margin-top: 4px; }
  .sv-more summary { cursor: pointer; font-size: 12px; color: #1d4f91; margin-top: 4px; }
  .sv-values { border-collapse: collapse; font-size: 12px; margin-top: 4px; }
  .sv-values td, .sv-values th { border-bottom: 1px solid #edf0f4; padding: 3px 10px 3px 0; text-align: left; }
  .sv-values .est { color: #9b2c13; font-weight: 600; }
  .sv-ctx { background: #fff; border-color: #e7c27a; }
  @media (max-width: 860px) { .sv-pics.two { grid-template-columns: 1fr; } }
  @media print { .sv-controls { display: none; } }
"""

JS = r"""
(() => {
  const D = window.SV_DATA;
  if (!D) return;
  const esc = t => String(t).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
  const groupOf = (age, sex) => Object.keys(D.groups).find(g => D.groups[g].age === age && D.groups[g].sex === sex);
  function fig(item, group, role) {
    const p = D.pics[item + "|" + group];
    if (!p) return "";
    const tag = p.e ? '<span class="sv-tag est">Estimated</span>' : '<span class="sv-tag pub">From published averages</span>';
    return `<figure class="sv-fig" data-item="${esc(item)}" data-group="${esc(group)}"><div class="sv-title"><b>${role ? esc(role) + ": " : ""}${esc(D.items[item])}</b>, ${esc(D.groups[group].label)} ${tag}</div>` +
      `<img src="/book/synth/${esc(p.f)}" alt="Computer-made spectrogram: ${esc(D.items[item])}, ${esc(D.groups[group].label)}" width="640" height="290">` +
      `<p class="sv-look"><b>Look for:</b> ${esc(D.look[item] || "")}</p><figcaption>${esc(p.c)}</figcaption>` +
      `<details class="sv-more"><summary>Values used</summary>${p.v}</details></figure>`;
  }
  function update(box) {
    const g = groupOf(box.querySelector(".sv-age").value, box.querySelector(".sv-sex").value);
    if (!g) return;
    box.dataset.group = g;
    const pics = box.querySelector(".sv-pics");
    if (box.classList.contains("sv-ctx")) {
      pics.innerHTML = [...pics.querySelectorAll(".sv-fig")].map(f => fig(f.dataset.item, g, "")).join("");
      return;
    }
    const sel = box.querySelector(".sv-item"), cmp = box.querySelector(".sv-compare").value;
    const first = sel ? sel.value : pics.querySelector(".sv-fig").dataset.item;
    const pair = box.dataset.pair === "1";
    pics.classList.toggle("two", !!cmp);
    pics.innerHTML = fig(first, g, pair ? "Target" : "") + (cmp ? fig(cmp, g, pair ? "Error" : "Compare") : "");
  }
  document.querySelectorAll(".sv").forEach(box => {
    if (box.querySelector(".sv-fig .sv-title b") && /^Target: /.test(box.querySelector(".sv-fig .sv-title b").textContent)) box.dataset.pair = "1";
    box.querySelectorAll("select").forEach(s => s.addEventListener("change", () => update(box)));
  });
})();
"""
