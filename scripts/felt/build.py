"""Copies the felt art the child screen uses into speakup/static/felt/ as WebP and writes felt.json and README.md.

Runs on the laptop, never on the board: python scripts/felt/build.py [art folder]
It needs Pillow, and Node with Playwright and Chrome for the speech bubbles and the sentence strip (see bubbles.js).
The art folder is the Speak Up felt art (BRIEF.md, art/, rig/, tools/); every buddy and every play world are copied,
and the SLP picks one of each on /look. The picker scene is not a play world (no card or strip room), so it is left out.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ART = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FELT_ART", "C:/Users/rafam/Documents/SpeakUp-Felt-Art"))
HERE = Path(__file__).parent
OUT = HERE.parents[1] / "speakup" / "static" / "felt"
BUDDIES = ("patch", "dusty", "juniper", "toffee")
# Each play world: its "all done" line and its moving bits in paint order (from its NOTES.md), each as
# "group:class": the bit's CSS class in kid.css, inside a moving wrapper of that group's class if it has one.
WORLDS = {
    "meadow": ("Picnic party!", {"cloud-2": "drift-r", "cloud-1": "drift-l", "tree-l": "sway leaves", "tree-r": "sway leaves",
                                 "tree-top": "sway leaves", "butterfly-wings": "fly:flap", "butterfly-body": "fly:",
                                 "flower-pink": "sway", "flower-nod": "sway"}),
    "garden": ("Garden party!", {**{f"flower-{n}": "sway" for n in ("coral", "pink", "lilac", "small", "nod")},
                                 **{f"drop-{n}": "drop" for n in (1, 2, 3)}, "bee-wings": "bee:whirr", "bee": "bee:",
                                 "butterfly-wing-l": "flutter:flap", "butterfly-wing-r": "flutter:flap", "butterfly-body": "flutter:"}),
    # the flame in four bands, base to tip, in one group: kid.css runs a lick up the bands and stretches each (see .flame)
    "bakery": ("Cookie party!", {"oven-glow": "glow", **{f"flame-{n}": f"fire:flame f{n}" for n in (1, 2, 3, 4)},
                                 "steam-1": "steam", "steam-2": "steam", "steam-3": "steam"}),
    # the cottage's smoke puffs and "z z" each in one group, so kid.css can run them one after the other
    "night": ("Star party!", {"star-swing-1": "sway", "star-swing-3": "sway", "twinkle-1": "twinkle", "twinkle-2": "twinkle",
                              **{f"smoke-{n}": f"smoke:puff l{n}" for n in (1, 2, 3)}, **{f"zz-{n}": f"zz:doze l{n}" for n in (1, 2)},
                              "lantern-glow": "lamp", "firefly-1": "firefly", "firefly-2": "firefly", "firefly-3": "firefly"}),
}
LISTEN_YAW = "030"  # the puppet set that looks at the card (the card is on the left; positive yaw turns left)
FACE = {"eyes-happy", "mouth-open"}  # the face on the spin stills
WAIT_X, TURN_X, FEET_Y = 640, 975, 600  # where the buddy stands (listening: on the blanket between the plate and the basket)
# Every bubble the screen can show. Lines the kit or the prototype baked are used as they are; the rest are typeset alike.
BUBBLES = {
    "hi": (["Hi!", "Ready to play?"], WAIT_X), "ready": (["Get ready..."], WAIT_X),
    "next": (["Ready for", "the next one?"], WAIT_X),
    "praise-0": (["Nice try!"], WAIT_X), "praise-1": (["Thank you!"], WAIT_X), "praise-2": (["Yum, great try!"], WAIT_X),
    "praise-3": (["You did it!"], WAIT_X), "praise-4": (["Yay!"], WAIT_X),
    **{f"done-{w}": ([line], WAIT_X) for w, (line, _) in WORLDS.items()},
    "turn": (["Your turn!"], TURN_X), "hear": (["I'm listening!"], TURN_X),
    "nudge": (["Take your time!", "You can do it!"], TURN_X), "think": (["Hmm..."], TURN_X),
}

ui = json.loads((ART / "art/ui/ui.json").read_text(encoding="utf-8"))
tmp = Path(tempfile.mkdtemp(prefix="felt-"))
sizes: dict[str, int] = {}


def save(im: Image.Image, name: str, quality: int = 90) -> str:
    im.save(OUT / name, "WEBP", quality=quality, method=6, alpha_quality=100)
    sizes[name] = (OUT / name).stat().st_size
    return name


def kit(entry: dict, name: str, x: float = 0, y: float = 0) -> dict:
    """A UI kit piece placed with its design box at (x, y)."""
    f = save(Image.open(ART / "art/ui" / entry["file"]).convert("RGBA"), name + ".webp")
    return {"f": f, "x": x + entry["off"][0], "y": y + entry["off"][1], "w": entry["w"], "h": entry["h"]}


def onto(canvas: Image.Image, im: Image.Image, x: int, y: int) -> None:
    """im composited with its top-left at (x, y); what falls outside the canvas is cut off."""
    box = (max(0, -x), max(0, -y), min(im.width, canvas.width - x), min(im.height, canvas.height - y))
    if box[0] < box[2] and box[1] < box[3]:
        canvas.alpha_composite(im.crop(box), (max(0, x), max(0, y)))


def scene(world: str) -> dict:
    """The still layers flattened into one opaque picture (one texture for the board's GPU), plus the few moving bits.
    A still layer that should cover a bit (the counter over the oven glow) comes back as a small lid cut to the bit's box."""
    d = ART / "art/scenes" / world
    items = sorted(json.loads((d / "manifest.json").read_text(encoding="utf-8"))["items"], key=lambda i: i["z"])
    moving = WORLDS[world][1]
    layer = {i["name"]: Image.open(d / (i.get("file") or i["png"])).convert("RGBA") for i in items}
    still = [i for i in items if i["name"] not in moving]
    back = Image.new("RGBA", (1280, 720))
    for i in still:
        onto(back, layer[i["name"]], i["frameX"], i["y"])
    out = {"back": save(back.convert("RGB"), f"{world}.webp", 88), "bits": []}
    save(back.convert("RGB").resize((320, 180), Image.LANCZOS), f"thumb-{world}.webp", 82)
    for i in items:
        if i["name"] not in moving:
            continue
        g, _, a = moving[i["name"]].rpartition(":")
        bit = {"f": save(layer[i["name"]], f"{world}-{i['name']}.webp"), "x": i["frameX"], "y": i["y"], "w": i["w"], "h": i["h"], "a": a}
        if g:
            bit["g"] = g
        if "pivotLocal" in i:
            bit["p"] = i["pivotLocal"]  # in the bit's own pixels
        m = 24  # room for the bit's motion
        x, y = max(0, i["frameX"] - m), max(0, i["y"] - m)
        lid = Image.new("RGBA", (min(1280, i["frameX"] + i["w"] + m) - x, min(720, i["y"] + i["h"] + m) - y))
        for s in still:
            if s["z"] > i["z"]:
                onto(lid, layer[s["name"]], s["frameX"] - x, s["y"] - y)
        if lid.getbbox():
            l, t, r, b = lid.getbbox()
            bit["lid"] = {"f": save(lid.crop((l, t, r, b)), f"{world}-{i['name']}-lid.webp"), "x": x + l, "y": y + t, "w": r - l, "h": b - t}
        out["bits"].append(bit)
    return out


def strip_blank() -> dict:
    """A blank stitched paper strip for a practice sentence, cut by papercut the way the prototype cuts its ten."""
    w, h, x, y = 472, 98, 44, 322  # on the card; it covers the word pill
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + 60} {h + 60}"><g data-layer="strip" transform="translate(30 30)">'
           f'<rect data-mat="paper" data-depth="15" data-lift="0.7" data-rough="0.6" data-stitch="6,5,4" width="{w}" height="{h}" rx="40" '
           f'fill="#FFE3A6" transform="rotate(0.5 {w / 2} {h / 2})"/></g></svg>')
    (tmp / "strip.svg").write_text(svg, encoding="utf-8")
    subprocess.run(["node", str(ART / "tools/papercut.js"), "render", str(tmp / "strip.svg"), "--out", str(tmp / "strip")], check=True,
                   stdout=subprocess.DEVNULL)
    it = next(i for i in json.loads((tmp / "strip/manifest.json").read_text())["items"] if i["name"] == "strip")
    c = ui["card"]["screen"]
    return {"f": save(Image.open(tmp / "strip" / it["file"]).convert("RGBA"), "sentence.webp"),
            "x": c["x"] + x + it["x"] - 30, "y": c["y"] + y + it["y"] - 30, "w": it["w"], "h": it["h"],
            "text": [c["x"] + x, c["y"] + y, w, h]}


def bubbles() -> dict:
    b = ui["bubble"]["screen"]
    spec = [{"id": k, "lines": lines, "tip": at, "centre": at - (60 if at == TURN_X else 0), "bottom": b["bottom"]}
            for k, (lines, at) in BUBBLES.items()]
    (tmp / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    subprocess.run(["node", str(HERE / "bubbles.js"), str(ART), str(tmp / "spec.json"), str(tmp)], check=True)
    boxes = json.loads((tmp / "bubbles.json").read_text())
    out = {}
    for k, (x, y, w, h) in boxes.items():
        im = Image.open(tmp / f"{k}.png").convert("RGBA")
        l, t, r, bt = im.getbbox()
        out[k] = {"f": save(im.crop((l, t, r, bt)), f"bubble-{k}.webp"), "x": x + l, "y": y + t, "w": r - l, "h": bt - t}
    return out


def bunny(buddy: str) -> dict:
    src = ART / "art/turn/board" / buddy  # the turnaround's final board-size puppet parts, one set per yaw
    first = json.loads((src / "000/manifest.json").read_text())
    out = {"dy": ui["bubble"]["screen"]["buddyDy"][buddy],  # taller ears lift the bubbles
           "w": first["width"], "h": first["height"], "feet": [round(180 * first["unit"], 1), round(400 * first["unit"], 1)],
           "sets": {}, "spin": []}
    for yaw in sorted(p.name for p in src.iterdir() if p.is_dir()):
        m = json.loads((src / yaw / "manifest.json").read_text())
        if yaw in ("000", LISTEN_YAW):
            parts = []
            for it in m["items"]:
                part = {"n": it["name"], "f": save(Image.open(src / yaw / it["file"]).convert("RGBA"), f"{buddy}-{yaw}-{it['name']}.webp", 92),
                        "x": it["x"], "y": it["y"], "w": it["w"], "h": it["h"]}
                if "pivot" in it:
                    part["p"] = it["pivot"]
                parts.append(part)
            out["sets"]["front" if yaw == "000" else "listen"] = parts
        # one flat still per yaw for the praise spin (no shadow: the page keeps the shadow on the ground)
        still = Image.new("RGBA", (m["width"], m["height"]))
        for it in m["items"]:
            n = it["name"]
            if n == "shadow" or (n.startswith(("eyes-", "mouth-")) and n not in FACE):
                continue
            still.alpha_composite(Image.open(src / yaw / it["file"]).convert("RGBA"), (it["x"], it["y"]))
        out["spin"].append(save(still, f"{buddy}-spin-{yaw}.webp", 86))
    return out


def main() -> None:
    for old in OUT.glob("*.webp"):
        old.unlink()
    OUT.mkdir(parents=True, exist_ok=True)
    card, prog = ui["card"], ui["progress"]
    cx, cy = card["screen"]["x"], card["screen"]["y"]
    px, py = prog["screen"]["x"], prog["screen"]["y"]
    half = prog["itemBox"] / 2
    rib, lab = ui["ribbon"]["lg"], ui["labels"]["allDone"]
    rx, ry = (1280 - rib["box"][0]) / 2, 34

    def world(w: str) -> dict:
        item = prog["strips"][w]["item"]
        return {"scene": scene(w), "card": kit(card["variants"][w], f"card-{w}", cx, cy),
                "strip": kit(prog["strips"][w], f"strip-{w}", px, py),
                "item": kit(prog["items"][item]["on"], f"item-{item}"), "big": kit(prog["items"][item]["big"], f"item-{item}-big")}

    data = {
        "spots": {"wait": WAIT_X, "turn": TURN_X, "feet": FEET_Y},
        "worlds": {w: world(w) for w in WORLDS},
        "pics": {w: kit(e, f"pic-{w}", cx + card["picture"]["x"], cy + card["picture"]["y"]) for w, e in ui["pictures"].items()},
        "words": {w: kit(e, f"word-{w}", cx + card["word"]["x"], cy + card["word"]["y"]) for w, e in ui["words"].items()},
        "label": [cx + card["word"]["x"], cy + card["word"]["y"], card["word"]["w"], card["word"]["h"]],
        "sentence": strip_blank(),
        "mic": [kit(e, f"mic-{i}", 604 - 75, 474 - 75) for i, e in enumerate(ui["mic"]["frames"])],
        "slots": [[px + sx - half, py + prog["slotY"] - half] for sx in prog["slots"]],
        "pop": kit(ui["bursts"]["top"], "burst-top"),
        "ribbon": kit(rib, "ribbon", rx, ry),
        "allDone": kit(lab, "label-all-done", rx + rib["text"]["x"] + (rib["text"]["w"] - lab["box"][0]) / 2,
                       ry + rib["text"]["y"] + (rib["text"]["h"] - lab["box"][1]) / 2),
        "confetti": [kit(e, f"confetti-{i + 1:02d}") for i, e in enumerate(ui["confetti"][:8])],
        "bubbles": bubbles(),
        "buddies": {b: bunny(b) for b in BUDDIES},
    }
    (OUT / "felt.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8", newline="\n")
    groups: dict[str, list[int]] = {}
    for name, size in sizes.items():
        head = name.split("-")[0].split(".")[0]
        group = (f"world: {head}" if head in WORLDS else "world thumbnails" if head == "thumb" else
                 f"buddy: {head}" if head in BUDDIES else "speech bubbles" if head == "bubble" else
                 "word pictures and words" if head in ("pic", "word") else "card, strip, mic, ribbon, marks")
        groups.setdefault(group, []).append(size)
    total = sum(sizes.values())
    rows = "\n".join(f"| {g} | {len(v)} | {sum(v) / 1024:.0f} |" for g, v in groups.items())
    (OUT / "README.md").write_text(f"""# Felt look of the child screen

Pre-rendered WebP layers for `/kid`, served at `/felt/<name>`. The page (`kid.js`, `kid.css`) only places them and moves
them with CSS `transform` and `opacity`: no filters, blend modes, blur, canvas or WebGL run on the board.

Buddies: {", ".join(BUDDIES)} (parts from `art/turn/board`). Worlds: {", ".join(WORLDS)}. The page loads only the pair
the SLP picked on `/look`; a world's own card, strip and item files are listed with the marks.

| Group | Files | KB |
|---|---|---|
{rows}
| **all images** | **{len(sizes)}** | **{total / 1024:.0f}** |

`felt.json` holds every piece's place on the 1280 x 720 stage. Do not edit the images or `felt.json` by hand:
`python scripts/felt/build.py <art folder>` rebuilds them on the laptop from the felt art sources (Pillow, Node,
Playwright and Chrome; nothing here is needed on the board).

Licence: original art made for Speak Up by the team (cut-paper and felt renders from the team's own SVG sources).
No third-party pictures, fonts or code are in this folder.
""", encoding="utf-8", newline="\n")
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"{len(sizes)} images, {total / 1024:.0f} KB")


main()
