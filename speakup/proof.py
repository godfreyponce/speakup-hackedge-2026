"""The live proof banner on the SLP pages (#38). Every number is measured on the machine running the app, or typed
by a person from the USB-C meter; a value not measured yet is None, and the page says "not measured yet".
Standard library only, so it runs on the board."""

import math
import re
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from html import escape
from pathlib import Path

try:
    import resource
except ImportError:  # pragma: no cover  (Windows)
    resource = None

NOT_MEASURED = "not measured yet"

_LLAMA_SPEED = re.compile(r"\b(prompt eval|eval) time\s*=.*?([0-9.]+|inf|nan) tokens per second")
_WATTS = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")
_RTF_UP = 0x0001
_RTF_REJECT = 0x0200


def llama_speeds(log: str) -> tuple[float | None, float | None]:
    """(generation, prompt) tokens per second from llama.cpp's own timing lines on stderr; the last real one of each
    wins. A -nan or inf speed is not a speed."""
    speeds: dict[str, float | None] = {"eval": None, "prompt eval": None}
    for line in log.splitlines():
        m = _LLAMA_SPEED.search(line)
        if m:
            value = float(m.group(2))
            if math.isfinite(value) and value > 0:
                speeds[m.group(1)] = value
    return speeds["eval"], speeds["prompt eval"]


def meminfo(text: str) -> tuple[int, int] | None:
    """(used, total) in kB from /proc/meminfo, used being MemTotal - MemAvailable."""
    fields = dict(re.findall(r"^(\w+):\s+(\d+) kB", text, re.M))
    if "MemTotal" not in fields or "MemAvailable" not in fields:
        return None
    total = int(fields["MemTotal"])
    return total - int(fields["MemAvailable"]), total


def default_route(route: str, ipv6_route: str) -> bool:
    """True when /proc/net/route or /proc/net/ipv6_route holds a working default route, the way out to the internet."""
    for line in route.splitlines()[1:]:
        cols = line.split()
        if len(cols) >= 8 and cols[1] == "00000000" and cols[7] == "00000000":
            flags = int(cols[3], 16)
            if flags & _RTF_UP and not flags & _RTF_REJECT:
                return True
    for line in ipv6_route.splitlines():
        cols = line.split()
        if len(cols) < 10 or cols[0] != "0" * 32 or cols[1] != "00" or cols[9] == "lo":
            continue
        flags = int(cols[8], 16)
        if flags & _RTF_UP and not flags & _RTF_REJECT:
            return True
    return False


def _peak_rss_kb() -> int | None:
    """This app's own peak resident memory (the main process; worker processes and llama.cpp not counted)."""
    if resource is None:
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak // 1024 if sys.platform == "darwin" else peak  # bytes on macOS, kB on Linux


def _read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


@dataclass(frozen=True)
class Snapshot:
    arti_last_ms: float | None
    arti_median_ms: float | None
    arti_words: int
    qwen_tps: float | None
    qwen_prompt_tps: float | None
    ram_kb: tuple[int, int] | None  # (used, total); None when /proc/meminfo is missing
    peak_rss_kb: int | None
    online: bool | None  # None when /proc/net/route is missing
    watts: str | None  # as the person typed it


class Proof:
    """The numbers behind the banner. Arti and llm.py add to it as they run; the page reads a snapshot."""

    def __init__(self, meminfo_path: Path = Path("/proc/meminfo"), route_path: Path = Path("/proc/net/route"),
                 ipv6_route_path: Path = Path("/proc/net/ipv6_route")):
        self._paths = meminfo_path, route_path, ipv6_route_path
        self._lock = threading.Lock()
        self._arti_ms: list[float] = []
        self._qwen: tuple[float | None, float | None] = (None, None)
        self._watts: str | None = None

    def add_arti_ms(self, ms: float) -> None:
        with self._lock:
            self._arti_ms.append(ms)

    @contextmanager
    def arti_timer(self):
        """Times one word's Arti call; a call that raises is not counted."""
        start = time.perf_counter()
        yield
        self.add_arti_ms((time.perf_counter() - start) * 1000)

    def add_llama_log(self, log: str) -> None:
        """A call without a real generation speed keeps the last call's speeds, so the tile never mixes calls."""
        speeds = llama_speeds(log)
        if speeds[0] is not None:
            with self._lock:
                self._qwen = speeds

    def new_session(self) -> None:
        with self._lock:
            self._arti_ms = []

    def set_watts(self, text: str) -> str | None:
        """Keep the watts the person typed from the meter, or clear them on a blank. Returns the error to show."""
        text = text.strip()
        if text and (not _WATTS.fullmatch(text) or float(text) <= 0):
            return f"Watts: type the number on the meter, such as 3.4 (got {text!r})."
        with self._lock:
            self._watts = text.removesuffix(".") or None
        return None

    def snapshot(self) -> Snapshot:
        meminfo_path, route_path, ipv6_path = self._paths
        mem = _read(meminfo_path)
        route = _read(route_path)
        with self._lock:
            arti = list(self._arti_ms)
            qwen, watts = self._qwen, self._watts
        return Snapshot(
            arti_last_ms=arti[-1] if arti else None,
            arti_median_ms=statistics.median(arti) if arti else None,
            arti_words=len(arti),
            qwen_tps=qwen[0],
            qwen_prompt_tps=qwen[1],
            ram_kb=meminfo(mem) if mem is not None else None,
            peak_rss_kb=_peak_rss_kb(),
            online=default_route(route, _read(ipv6_path) or "") if route is not None else None,
            watts=watts,
        )


LIVE = Proof()


# The owner's pick of three shapes (mockups/round3-proof-banner/c-tile-bar.html): five tiles fixed to the bottom of
# the screen. BAR_JS keeps the page's bottom padding equal to the bar's height, so the bar never covers anything.
BAR_CSS = """
  body { padding-bottom: 124px; }  /* five tiles at 1280 px wide (#49), in case BAR_JS does not run */
  .proof { position: fixed; left: 0; right: 0; bottom: 0; z-index: 3; background: #fff; border-top: 2px solid #1d4f91;
           box-shadow: 0 -2px 10px rgba(22, 32, 44, .08); padding: 10px 24px; }
  .proof .tiles { display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; max-width: 1500px; margin: 0 auto; }
  .proof .tile { border: 1px solid #d9dfe7; border-radius: 8px; padding: 8px 12px; min-width: 0; }
  .proof small { display: block; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #6b7785; font-weight: 600; }
  .proof .big { font-size: 30px; font-weight: 750; line-height: 1.1; padding: 0; }  /* not the page's .big button */
  .proof .big span { font-size: 15px; font-weight: 600; color: #44505e; margin-left: 3px; }
  .proof .sub { font-size: 12px; color: #6b7785; }
  .proof .tile.off { background: #e3f2e6; border-color: #9fd0ae; }
  .proof .tile.off .big { color: #23633a; }
  .proof .tile.on { background: #fbe3dd; border-color: #e7a99a; }
  .proof .tile.on .big { color: #9b2c13; }
  .proof form { display: flex; gap: 6px; margin: 2px 0; }
  .proof .tile form { margin: 0; height: 33px; }  /* the height of a .big line, 30px x 1.1, so Watts is no taller */
  .proof input { width: 90px; font: inherit; font-size: 20px; font-weight: 700; padding: 2px 8px; border: 1px solid #c4ccd6; border-radius: 6px; }
  .proof button { font: inherit; font-weight: 600; padding: 2px 12px; border-radius: 6px; border: 1px solid #1d4f91; background: #1d4f91; color: #fff; }
  .proof .sub.bad { color: #9b2c13; font-weight: 600; }
  .proof:not(:has(.tiles)) { border-top-width: 1px; border-top-color: #d9dfe7; box-shadow: none; padding: 6px 24px; }
  .proof .unmeasured { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 18px; max-width: 1500px;
                       margin: 0 auto; font-size: 13px; color: #6b7785; }
  .proof .tiles + .unmeasured { margin-top: 6px; }
  .proof .unmeasured b { font-weight: 600; color: #44505e; }
  .proof .meter { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  .proof .meter input { width: 64px; font-size: 14px; font-weight: 600; padding: 1px 6px; }
  .proof .meter button { font-size: 13px; padding: 1px 10px; }
  @media (max-width: 900px) { .proof .tiles { grid-template-columns: repeat(3, 1fr); gap: 8px; } .proof .big { font-size: 24px; }
                              .proof .tile form { height: 26px; } }
"""

# Watts go in with fetch, so typing them never leaves the page (or a recording in progress).
BAR_JS = r"""
(function () {
  var bar = document.querySelector("footer.proof");
  function fit() { document.body.style.paddingBottom = bar.offsetHeight + "px"; }
  fit();
  if (window.ResizeObserver) new ResizeObserver(fit).observe(bar); else window.addEventListener("resize", fit);
  var form = bar.querySelector("form.watts"), sub = bar.querySelector(".watts-sub");
  form.addEventListener("submit", function (e) {
    e.preventDefault();
    fetch("/proof/watts", { method: "POST", body: new URLSearchParams(new FormData(form)) })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        sub.classList.toggle("bad", !d.ok);
        sub.textContent = d.ok ? (d.watts ? "typed by a person, never by the app" : "not measured yet") : d.error;
        if (d.ok) form.watts.value = d.watts || "";
      })
      .catch(function () { sub.classList.add("bad"); sub.textContent = "The app did not answer. Press Set again."; });
  });
})();
"""


def _tile(label: str, big: str, sub: str, kind: str = "") -> str:
    return f'<div class="tile {kind}"><small>{label}</small><div class="big">{big}</div><div class="sub">{sub}</div></div>'


def _mb(kb: int) -> str:
    return f"{kb / 1024:,.0f}"


def _unmeasured(missing: list[tuple[str, str]], meter: str) -> str:
    """The quiet line under the tiles: what is not measured yet, each with the machine's reason when there is one."""
    names = ", ".join(f"<b>{name}</b>" + (f" ({why})" if why else "") for name, why in missing)
    said = f"<span>{NOT_MEASURED.capitalize()}: {names}.</span>" if names else ""
    return f'<div class="unmeasured">{said}{meter}</div>'


def bar_html(s: Snapshot) -> str:
    """The bar for the bottom of an SLP page: its style, a tile per measured value, one quiet line for the rest,
    and its script."""
    tiles, missing = [], []
    if s.arti_last_ms is None:
        missing.append(("Arti", ""))
    else:
        words = "1 try" if s.arti_words == 1 else f"{s.arti_words} tries"
        tiles.append(_tile("Arti, last word", f"{s.arti_last_ms:.0f}<span>ms</span>",
                           f"median {s.arti_median_ms:.0f} ms over {words} this session"))
    if s.qwen_tps is None:
        missing.append(("Qwen", ""))
    else:
        prompt = f"prompt {s.qwen_prompt_tps:.1f} tokens/s, " if s.qwen_prompt_tps is not None else ""
        tiles.append(_tile("Qwen, writing", f"{s.qwen_tps:.1f}<span>tokens/s</span>",
                           f"{prompt}llama.cpp's timing, last call"))
    peak = f"app peak {_mb(s.peak_rss_kb)} MB, main process" if s.peak_rss_kb is not None else ""
    if s.ram_kb is None:
        missing.append(("Memory", "no usable /proc/meminfo on this machine" + (f", {peak}" if peak else "")))
    else:
        used, total = s.ram_kb
        tiles.append(_tile("Memory used", f"{_mb(used)}<span>of {_mb(total)} MB</span>", peak))
    if s.online is None:
        missing.append(("Network", "no /proc/net/route on this machine"))
    elif s.online:
        tiles.append(_tile("Network", "Online", "a default route is up", "on"))
    else:
        tiles.append(_tile("Network", "Offline", "no default route", "off"))
    form = (f'<form class="watts"><input name="watts" value="{escape(s.watts or "")}" inputmode="decimal" '
            f'aria-label="Watts from the meter"><button>Set</button></form>')
    if s.watts and tiles:  # alone, a Watts tile would add a row of tiles to the folded bar
        tiles.append(f'<div class="tile"><small>Watts, USB-C meter</small>{form}'
                     '<div class="sub watts-sub">typed by a person, never by the app</div></div>')
        meter = ""
    else:
        meter = f'<span class="meter">Watts from the USB-C meter {form}<span class="sub watts-sub"></span></span>'
    line = _unmeasured(missing, meter) if missing or meter else ""
    grid = f'<div class="tiles">{"".join(tiles)}</div>' if tiles else ""
    return (f'<style>{BAR_CSS}</style>\n<footer class="proof" aria-label="Measured on this machine">'
            f'{grid}{line}</footer>\n<script>{BAR_JS}</script>\n')
