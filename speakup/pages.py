"""The session's HTML pages (#5), from mockups/issue-5/c3-bubble.html, and the session log pages (#6), from
mockups/issue-6/c-chart.html. One document each, CSS inline, no JavaScript and nothing fetched from anywhere,
so the page works on the board with no internet."""

from dataclasses import dataclass, replace
from datetime import datetime
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from speakup import backnav, calibration, coach, evidence, lexicon, proof, selectview
from speakup.bank import LEVELS
from speakup.practice import Practice
from speakup.result import ERROR_WORDS, Result
from speakup.age_norms import explain
from speakup.clipcheck import ClipCheck
from speakup.session import Attempt, Session, agreement, arti_p_wrong, format_age, position_tally, tally
from speakup.words import Word
from speakup.store import LastTime, SavedSession
from speakup.words import POSITIONS
from speakup import summary
from speakup.summary import pass_or_refer

CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; padding: 40px 16px; background: #fbfbf8; color: #1b1b18;
         font: 16px/1.5 ui-rounded, "SF Pro Rounded", "Arial Rounded MT Bold", "Nunito", system-ui, sans-serif; }
  .screen { max-width: 860px; margin: 0 auto; background: #fff; border: 1px solid #e2e2da; border-radius: 20px; padding: 24px 32px 28px; }
  .top { display: flex; justify-content: space-between; font-size: 14px; color: #6d6d63; margin-bottom: 16px; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; padding-bottom: 20px; border-bottom: 1px solid #ececE4; }
  .chip { font-size: 14px; padding: 4px 12px; border-radius: 999px; border: 1px solid #d6d6cc; color: #9a9a8f; }
  .chip.ok { background: #e7f1e4; border-color: #c4dcbe; color: #2e5a26; }
  .chip.normal { background: #f3efe0; border-color: #e2d9b8; color: #6b5a1c; }
  .chip.flag { background: #f8dfd6; border-color: #eab9a8; color: #8b2b10; font-weight: 600; }
  .chip.current { border: 2px solid #1b1b18; color: #1b1b18; font-weight: 600; }
  .stage { text-align: center; padding: 36px 0 8px; }
  .word { font-size: 104px; font-weight: 700; line-height: 1; letter-spacing: -.02em; }
  .heard { font-size: 20px; margin: 24px 0 4px; }
  .flagline { font-weight: 600; }
  .flagline.yes { color: #8b2b10; }
  .flagline.no { color: #6b5a1c; }
  .error { color: #8b2b10; font-weight: 600; margin: 16px 0 0; }
  .buttons { display: flex; justify-content: center; gap: 12px; margin-top: 28px; }
  .buttons form { margin: 0; }
  button { font: inherit; font-weight: 600; padding: 14px 32px; border-radius: 14px; border: 1px solid #4f7cff; cursor: pointer; }
  .primary { background: #4f7cff; color: #fff; }
  .secondary { background: #fff; color: #2c4fc4; }
  h1 { font-size: 26px; margin: 0 0 4px; }
  .logo { display: inline-flex; align-items: center; gap: 10px; }
  .logo i { position: relative; width: 30px; height: 24px; border-radius: 12px; background: #4f7cff; }
  .logo i::after { content: ""; position: absolute; left: 5px; bottom: -6px; border: 6px solid transparent; border-top-color: #4f7cff; border-left-color: #4f7cff; }
  .word.line { font-size: 44px; }
  .start { display: grid; grid-template-columns: 2fr 1fr 1fr auto auto; gap: 16px; align-items: end; margin-top: 20px; }
  label { display: block; font-weight: 600; font-size: 14px; margin-bottom: 6px; }
  .hint { color: #8b8b80; font-size: 14px; margin: 0; }
  input { width: 100%; font: inherit; padding: 11px 12px; border: 1px solid #cfcfc4; border-radius: 14px; }
  .bubble { position: relative; display: inline-block; padding: 14px 44px 20px; border: 3px solid #1b1b18; border-radius: 40px; background: #fff; }
  .bubble::before { content: ""; position: absolute; left: 56px; top: 100%; border-style: solid; border-width: 22px 16px 0 0; border-color: #1b1b18 transparent transparent transparent; }
  .bubble::after { content: ""; position: absolute; left: 59px; top: calc(100% - 4px); border-style: solid; border-width: 19px 12px 0 0; border-color: #fff transparent transparent transparent; }
  .verdict { font-weight: 700; margin: 24px 0 34px; }
  .verdict.bubble { display: block; font-size: 20px; padding: 16px 24px 18px; border-radius: 24px; }
  .verdict.bubble::before { left: 40px; }
  .verdict.bubble::after { left: 43px; }
  .verdict.refer { background: #fff4f0; border-color: #8b2b10; }
  .verdict.refer::before { border-top-color: #8b2b10; }
  .verdict.refer::after { border-top-color: #fff4f0; }
  .note { margin: 0 0 12px; }
  .tally { color: #6d6d63; margin: 0 0 20px; }
  table { width: 100%; border-collapse: collapse; font-size: 15px; }
  th { text-align: left; font-size: 13px; text-transform: uppercase; letter-spacing: .05em; color: #8b8b80; border-bottom: 1px solid #d6d6cc; padding: 8px 6px; }
  td { padding: 8px 6px; border-bottom: 1px solid #ececE4; }
  td.f { color: #8b2b10; font-weight: 600; }
  footer { margin-top: 24px; font-size: 13px; color: #a3a398; }
"""


LOG_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; padding: 40px 24px 80px; background: #f6f6f4; color: #1b1b18;
         font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; font-variant-numeric: tabular-nums; }
  .screen { max-width: 1080px; margin: 0 auto; background: #fff; border: 1px solid #e2e2da; border-radius: 16px; overflow: hidden; }
  .bar-top { display: flex; justify-content: space-between; align-items: center; padding: 14px 24px; border-bottom: 1px solid #ececE4; }
  .crumbs { color: #8b8b80; display: flex; gap: 10px; }
  .crumbs a { color: #4a4a43; text-decoration: none; }
  .crumbs b { color: #1b1b18; font-weight: 500; }
  .seg { display: inline-flex; background: #f3f3ef; border: 1px solid #e2e2da; border-radius: 10px; padding: 3px; }
  .seg a { color: #6d6d63; text-decoration: none; padding: 4px 12px; border-radius: 7px; }
  .seg a.on { background: #fff; color: #1b1b18; box-shadow: 0 0 0 1px #e2e2da; }
  .body { padding: 32px 64px 48px; }
  .big { font-size: 44px; font-weight: 600; letter-spacing: .01em; line-height: 1.1; color: #1b1b18; }
  .sub { color: #6d6d63; font-size: 14px; margin-top: 4px; }
  h2 { font-size: 15px; font-weight: 600; color: #1b1b18; margin: 40px 0 14px; }
  .hero h2 { margin-top: 0; }
  .totals { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }
  .totals span { display: block; color: #6d6d63; font-size: 13px; }
  .totals strong { font-size: 18px; font-weight: 500; color: #1b1b18; }
  .hero { display: grid; grid-template-columns: 280px 1fr; gap: 40px; align-items: start; }
  .empty { color: #6d6d63; }
  table { width: 100%; border-collapse: collapse; }
  th { text-align: left; font-size: 13px; font-weight: 400; color: #8b8b80; padding: 8px 12px 8px 0; border-bottom: 1px solid #d6d6cc; }
  td { padding: 14px 12px 12px 0; border-bottom: 1px solid #ececE4; vertical-align: top; }
  th.n, td.n { text-align: right; }
  td.rank { color: #8b8b80; width: 28px; font-size: 13px; padding-top: 16px; }
  td.when, td.age { white-space: nowrap; }
  .time { color: #8b8b80; margin-left: 6px; }
  td.hot { color: #8b2b10; font-weight: 600; }
  .share { display: block; height: 2px; background: #c4532f; margin-top: 8px; min-width: 8px; }
  a.id { color: #1b1b18; text-decoration: none; border-bottom: 1px solid #b5b5aa; }
  .chips { display: flex; flex-wrap: wrap; gap: 4px; }
  .chip { font-size: 13px; padding: 1px 10px; border-radius: 999px; border: 1px solid #d6d6cc; color: #9a9a8f; }
  .chip.ok { background: #e7f1e4; border-color: #c4dcbe; color: #2e5a26; }
  .chip.normal { background: #f3efe0; border-color: #e2d9b8; color: #6b5a1c; }
  .chip.flag { background: #f8dfd6; border-color: #eab9a8; color: #8b2b10; font-weight: 600; }
  .legend { margin: 0 0 10px; }
  .chart { display: block; width: 100%; height: auto; }
  .chart text { font-size: 12px; fill: #6d6d63; }
  .chart .grid-line { stroke: #ececE4; }
  .chart .line { fill: none; stroke: #c4532f; stroke-width: 2; }
  .chart .area { fill: #f8dfd6; fill-opacity: .6; }
  .chart circle { fill: #c4532f; }
"""

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


CSS += """
  .slp-grid { display: grid; grid-template-columns: 220px 1fr; gap: 28px; padding-top: 22px; align-items: start; }
  .target { text-align: center; background: #fff8ec; border: 1px solid #f0dcb8; border-radius: 18px; padding: 18px 12px; }
  .pic { width: 120px; height: 120px; }
  .tword { font-size: 30px; font-weight: 700; margin-top: 6px; }
  .tpos { font-size: 13px; color: #8a7a5c; }
  .panel .hint { color: #6d6d63; font-size: 14px; }
  button.big { font-size: 20px; padding: 14px 40px; }
  .arti { border-radius: 16px; padding: 16px 18px; border: 1px solid #e2e2da; background: #fafaf6; }
  .arti.off { border-color: #eab9a8; background: #fff6f2; }
  .arti.ok { border-color: #bfdcc6; background: #f3faf4; }
  .arti-head { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: #6d6d63; }
  .call { font-size: 22px; font-weight: 700; margin: 2px 0 10px; }
  .conf { height: 8px; background: #e6e6de; border-radius: 99px; overflow: hidden; }
  .conf span { display: block; height: 100%; background: #1f4e79; }
  .conflabel { font-size: 13px; color: #6d6d63; margin-top: 4px; }
  .would { font-size: 13px; margin-top: 6px; color: #8b2b10; }
  .replay { width: 100%; margin-top: 12px; }
  .noclip { font-size: 12px; color: #9a9a8f; margin-top: 10px; }
  .verdict-row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-top: 14px; }
  .verdict-row form { margin: 0; }
  .vbtn { width: 100%; font-size: 20px; font-weight: 700; padding: 14px 10px; border-radius: 14px; cursor: pointer;
          border: 2px solid #d6d6cc; background: #fff; color: #1b1b18; }
  .vbtn small { display: block; font-size: 12px; font-weight: 400; color: #6d6d63; }
  .vbtn.ok.suggested { border-color: #2e7d32; background: #eef8ef; }
  .vbtn.off.suggested { border-color: #8b2b10; background: #fff1ec; }
  footer a { color: #1f4e79; }
  .col { display: grid; gap: 12px; }
  .box { border-radius: 14px; padding: 12px 14px; border: 1px solid #e2e2da; background: #fff; font-size: 14px; }
  .box b { display: block; font-size: 13px; margin-bottom: 4px; }
  .box ul { margin: 4px 0 0 18px; padding: 0; }
  .rec.good { border-color: #bfdcc6; background: #f3faf4; }
  .rec.warn { border-color: #f0c36d; background: #fff8e6; }
  .rec.none { color: #8a8a80; }
  .panel > * + * { margin-top: 12px; }
  .side span { color: #4b4b44; }
  .mini { width: 100%; border-collapse: collapse; margin: 4px 0 6px; font-size: 13px; }
  .mini td { padding: 3px 0; border-bottom: 1px solid #f0f0ea; }
  .agree { display: block; font-size: 13px; }
  .why { font-size: 14px; margin-top: 8px; color: #3a3a33; }
  .arti.doubt { opacity: .55; border-style: dashed; background: #fafaf6; }
  .soundpic .ax { font-size: 10px; fill: #555; } .soundpic .lab { font-size: 12px; font-weight: 700; }
  .soundpic .t { font-size: 12px; fill: #333; }
  .box.sound svg { width: 100%; height: auto; margin: 4px 0; border-radius: 8px; }
  .box.sound a { color: #1f4e79; font-weight: 600; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: #555; margin: 6px 0; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }
  .decide { font-size: 12px; color: #6d6d63; margin: 6px 0 0; text-align: center; }
"""


def _page(title: str, body: str, css: str = CSS, head: str = "") -> str:
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n{head}'
        f"<title>{escape(title)}, Speak Up</title>\n<style>{css}</style>\n</head>\n"
        f'<body>\n<div class="screen">\n{body}\n</div>\n</body>\n</html>\n'
    )


def _error(message: str | None) -> str:
    return f'<p class="error">{escape(message)}</p>' if message else ""


def _heard(attempt: Attempt) -> str:
    r = attempt.result
    if r.error_type == "off":
        return ERROR_WORDS["off"]
    return f"{r.heard_phone or 'not named'} ({r.error_type or 'correct'})"


def _button(action: str, label: str, kind: str) -> str:
    return f'<form method="post" action="{action}"><button class="{kind}">{label}</button></form>'


def _top(session: Session, right: str) -> str:
    return (f'<div class="top"><span>{escape(session.child_id)}, age {format_age(session.age_months)}</span>'
            f"<span>{escape(right)}</span></div>")


def _state_of(a: Attempt | None) -> str:
    if a is None:
        return ""
    return "flag" if a.flagged else "normal" if a.result.error_type else "ok"


def _chips(session: Session) -> str:
    chips = []
    for i, word in enumerate(session.words):
        current = "current" if i == session.index else ""
        chips.append(f'<span class="chip {_state_of(session.slot(i))} {current}">{escape(word.word)}</span>')
    return f'<div class="chips">{"".join(chips)}</div>'


# The SLP side (lab, Nov 4): a clinical layout. A patient banner on top (who, age, what, voice setting), the
# word list down the left (any word can be reopened), the work in the middle, the context on the right.
# Restrained colour: navy for actions, red only for a flag, amber only for "check this".
SLP_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; background: #f3f5f8; color: #16202c;
         font: 15px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; font-variant-numeric: tabular-nums; }
  a { color: #1d4f91; }
  .banner { display: flex; align-items: center; gap: 22px; background: #fff; border-bottom: 1px solid #d9dfe7;
            padding: 10px 24px; position: sticky; top: 0; z-index: 2; }
  .brand { font-weight: 700; color: #1d4f91; letter-spacing: .01em; }
  .who { display: flex; gap: 22px; flex: 1; }
  .who div { display: grid; }
  .who small { font-size: 11px; text-transform: uppercase; letter-spacing: .06em; color: #6b7785; }
  .who b { font-size: 15px; font-weight: 600; }
  .tag { display: inline-block; font-size: 12px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
         background: #e8eef7; color: #1d4f91; }
  .tag.adult { background: #fff1d6; color: #7a4b00; }
  .links { display: flex; gap: 14px; font-size: 13px; }
  .shell { display: grid; grid-template-columns: 210px 1fr 300px; gap: 18px; padding: 18px 24px 40px; max-width: 1500px; margin: 0 auto; }
  .card { background: #fff; border: 1px solid #d9dfe7; border-radius: 8px; padding: 14px 16px; }
  .card + .card { margin-top: 14px; }
  .card h3 { margin: 0 0 8px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #6b7785; font-weight: 600; }
  .rail { padding: 6px; }
  .rail h3 { padding: 8px 10px 4px; }
  .rail form { margin: 0; }
  /* #45: on the word and practice pages the word card leads; the context column is plain text under thin rules. */
  .shell .card h3 { text-transform: none; letter-spacing: 0; font-size: 14px; color: #16202c; }
  .shell .target { border-color: #cfd7e1; box-shadow: 0 1px 2px rgba(22, 32, 44, .05), 0 6px 18px rgba(22, 32, 44, .07); }
  .context .card { background: none; border: 0; border-top: 1px solid #d9dfe7; border-radius: 0; padding: 12px 0 14px; }
  .context .card + .card { margin-top: 0; }
  /* Before Record the help text sits in the slot the question card will fill; 360 px ends it level with the word
     list at 1440 px wide. */
  .target + .card:last-child { min-height: 360px; display: grid; place-items: center; text-align: center;
                               background: none; border: 2px dashed #d3dae3; }
  .target + .card:last-child .hint { max-width: 440px; font-size: 15px; color: #44505e; }
  .wrow { width: 100%; display: grid; grid-template-columns: 22px 1fr auto; align-items: center; gap: 6px; text-align: left;
          font: inherit; background: none; border: 0; border-radius: 6px; padding: 7px 10px; cursor: pointer; color: inherit; }
  .wrow:hover { background: #f0f4fa; }
  .wrow.current { background: #e8eef7; box-shadow: inset 3px 0 0 #1d4f91; font-weight: 600; }
  .wrow .n { color: #8a95a3; font-size: 12px; }
  .pill { font-size: 11px; font-weight: 600; padding: 1px 7px; border-radius: 10px; background: #eef1f5; color: #6b7785; }
  .pill.ok { background: #e3f2e6; color: #23633a; }
  .pill.normal { background: #f6efd9; color: #6b5300; }
  .pill.flag { background: #fbe3dd; color: #9b2c13; }
  .pill.slp::after { content: " ✓"; }
  .finish { margin: 10px 8px 6px; }
  .target { display: grid; grid-template-columns: auto 1fr auto; gap: 18px; align-items: center; }
  .target img { width: 88px; height: 88px; }
  .tword { font-size: 40px; font-weight: 700; line-height: 1.1; }
  .tline { font-size: 26px; font-weight: 650; line-height: 1.2; }
  .tpos { color: #6b7785; font-size: 13px; }
  button { font: inherit; font-weight: 600; border-radius: 6px; cursor: pointer; padding: 10px 18px; border: 1px solid #1d4f91; }
  .primary { background: #1d4f91; color: #fff; }
  .primary:hover { background: #163f75; }
  .secondary { background: #fff; color: #1d4f91; }
  .quiet { background: #fff; color: #44505e; border-color: #c4ccd6; font-weight: 500; }
  .big { font-size: 18px; padding: 14px 28px; }
  .wide { width: 100%; }
  /* .wide is also the analysis page's wrapper (below); a wide button must not take its margin and side padding. */
  button.wide { margin: 0; max-width: none; padding: 10px 18px; } button.big.wide { padding: 14px 28px; }
  form { margin: 0; }
  .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .hint { color: #6b7785; font-size: 13px; margin: 8px 0 0; }
  .error { color: #9b2c13; font-weight: 600; margin: 0 0 10px; }
  .rec { display: flex; gap: 10px; align-items: flex-start; font-size: 14px; }
  .rec b { display: block; }
  .rec ul { margin: 4px 0 0 18px; padding: 0; }
  .dot { width: 10px; height: 10px; border-radius: 50%; margin-top: 5px; flex: none; background: #9aa5b1; }
  .dot.good { background: #2e8b57; } .dot.warn { background: #d08b00; }
  audio { width: 100%; margin-top: 10px; height: 36px; }
  .meta { font-size: 13px; color: #44505e; margin-top: 6px; }
  .why { font-size: 13px; color: #44505e; margin-top: 8px; padding-top: 8px; border-top: 1px solid #edf0f4; }
  .next { margin-top: 12px; }
  .note { font-size: 12px; color: #6b7785; margin: 8px 0 0; }
  .voice { margin-top: 14px; }
  .voice.warn { border-color: #e7c27a; background: #fffaf0; }
  .voice p { margin: 0 0 6px; font-size: 14px; }
  .sound { position: relative; margin-top: 14px; }
  .sound svg { width: 100%; height: auto; display: block; border-radius: 6px; }
  .expand { position: absolute; top: 4px; right: 12px; font-size: 26px; line-height: 1; text-decoration: none;
            color: #1d4f91; padding: 4px; border: 0; background: none; }
  .expand:hover { color: #0f2f5c; }
  .sound .picture { display: block; cursor: zoom-in; position: relative; }
  body.fv-open { overflow: hidden; }
  .fullview { position: fixed; inset: 0; z-index: 1000; background: #fff; display: flex; flex-direction: column; }
  .fv-head { display: flex; align-items: center; gap: 14px; padding: 8px 14px; border-bottom: 1px solid #d9dfe7;
             background: #f6f8fb; font-size: 14px; }
  .fv-head .fv-say { color: #6b7785; font-size: 13px; flex: 1; }
  .fv-head .fv-own, .fv-head .fv-book { font-size: 13px; }
  .fv-head .fv-book { font-weight: 600; }
  .fv-x { font-size: 22px; line-height: 1; padding: 4px 12px; border: 1px solid #c4ccd6; border-radius: 6px; background: #fff;
          color: #16202c; cursor: pointer; }
  .fv-x:hover { background: #fbe9e7; color: #b42318; }
  .fullview iframe { flex: 1; width: 100%; border: 0; }
  .soundpic .ax { font-size: 10px; fill: #555; } .soundpic .lab { font-size: 12px; font-weight: 700; }
  .soundpic .t { font-size: 12px; fill: #333; }
  .legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: #555; margin: 6px 0; }
  .legend i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 5px; vertical-align: -1px; }
  .mini { width: 100%; border-collapse: collapse; font-size: 13px; }
  .mini td { padding: 4px 0; border-bottom: 1px solid #edf0f4; }
  .mini td + td { text-align: right; }
  .side p { margin: 0; font-size: 14px; }
  table.list { width: 100%; border-collapse: collapse; font-size: 14px; }
  table.list th { text-align: left; font-size: 12px; text-transform: uppercase; letter-spacing: .05em; color: #6b7785;
                  font-weight: 600; border-bottom: 1px solid #d9dfe7; padding: 8px 8px 8px 0; }
  table.list td { padding: 9px 8px 9px 0; border-bottom: 1px solid #edf0f4; }
  td.f { color: #9b2c13; font-weight: 600; }
  .verdict { font-size: 22px; font-weight: 700; margin: 0 0 6px; }
  .verdict.refer { color: #9b2c13; }
  .checked { margin: 4px 0 0; }
  p.listen { color: #7a4b00; font-weight: 600; margin: 8px 0 0; }  /* the end screen only (#45) */
  .aid { font-size: 12px; color: #6b7785; }
  .bigpic svg, .pair svg { width: 100%; height: auto; border: 1px solid #d9dfe7; border-radius: 6px; }
  .pair { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .measure { border-collapse: collapse; margin-top: 10px; font-size: 14px; }
  .measure td, .measure th { padding: 4px 14px 4px 0; border-bottom: 1px solid #edf0f4; text-align: left; }
  .one { max-width: 1100px; margin: 18px auto 40px; padding: 0 24px; }
  .wide { max-width: 1400px; margin: 18px auto 40px; padding: 0 24px; }
  .wide .card { margin-bottom: 16px; }
  .groups { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 6px 28px; }
  .groups h4 { margin: 8px 0 2px; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; color: #6b7785; }
  .groups .measure { width: 100%; margin-top: 0; }
  .groups .measure td + td { text-align: right; font-variant-numeric: tabular-nums; }
  .listing { margin-top: 14px; font-size: 14px; }
  .listing summary { cursor: pointer; color: #1d4f91; font-weight: 600; }
  .frames { border-collapse: collapse; font-size: 12px; margin-top: 8px; font-variant-numeric: tabular-nums; }
  .frames th, .frames td { padding: 2px 12px 2px 0; text-align: right; border-bottom: 1px solid #edf0f4; }
  .limits { font-size: 13px; color: #44505e; background: #f7f9fb; border: 1px solid #e3e8ee; border-radius: 6px; padding: 10px 12px; }
  @media (max-width: 1100px) { .shell { grid-template-columns: 190px 1fr; } .context { grid-column: 1 / -1; } }
"""

START_CSS = """
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f3f5f8; color: #16202c;
         font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; padding: 24px 16px; }
  .start { width: 100%; max-width: 520px; background: #fff; border: 1px solid #d9dfe7; border-radius: 10px; padding: 32px 36px 26px; }
  .brand { font-size: 28px; font-weight: 750; color: #1d4f91; margin: 0; }
  .lead { color: #44505e; margin: 2px 0 22px; }
  label { display: block; font-weight: 600; font-size: 14px; margin: 14px 0 5px; }
  input, select { width: 100%; font: inherit; font-size: 18px; padding: 11px 12px; border: 1px solid #c4ccd6; border-radius: 6px; background: #fff; }
  input:focus, select:focus { outline: 3px solid #c9d8ee; border-color: #1d4f91; }
  .field-hint { margin: 4px 0 0; font-size: 12px; color: #6b7785; }
  fieldset { border: 0; padding: 0; margin: 14px 0 0; }
  legend { font-weight: 600; font-size: 14px; margin-bottom: 5px; }
  .choice { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .choice label { margin: 0; font-weight: 500; border: 1px solid #c4ccd6; border-radius: 6px; padding: 10px 12px; cursor: pointer; display: flex; gap: 8px; align-items: flex-start; }
  .choice input { width: auto; margin-top: 4px; }
  .choice small { display: block; color: #6b7785; font-size: 12px; font-weight: 400; }
  .actions { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 22px; }
  .actions.one { grid-template-columns: 1fr; }
  button { font: inherit; font-weight: 650; font-size: 17px; border-radius: 6px; cursor: pointer; padding: 13px; border: 1px solid #1d4f91; }
  .primary { background: #1d4f91; color: #fff; }
  .secondary { background: #fff; color: #1d4f91; }
  .error { color: #9b2c13; font-weight: 600; margin: 14px 0 0; }
  footer { margin-top: 18px; font-size: 13px; color: #6b7785; display: flex; justify-content: space-between; }
  footer a { color: #1d4f91; }
"""


def start_page(error: str | None = None, student_id: str = "", birth_date: str = "", practice: bool = True,
               stretch: bool = False, voice_mode: str = "child") -> str:
    today = datetime.now().date().isoformat()
    adult = voice_mode == "adult"
    voice_box = ""
    if stretch:
        voice_box = f"""
    <fieldset>
      <legend>Who is speaking</legend>
      <div class="choice">
        <label><input type="radio" name="voice" value="child" {"" if adult else "checked"}><span>A child<small>Arti as trained.</small></span></label>
        <label><input type="radio" name="voice" value="adult" {"checked" if adult else ""}><span>An adult (demo)<small>Adjusts for an adult voice. Not for screening.</small></span></label>
      </div>
    </fieldset>"""
    practice_button = ('<button class="secondary" name="mode" value="practice">Practice</button>' if practice else "")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Start, Speak Up</title>
<style>{START_CSS}</style>
</head>
<body>
<form class="start" method="post" action="/start">
  <h1 class="brand">Speak Up</h1>
  <p class="lead">r screening and practice</p>
  <label for="student_id">Student ID</label>
  <input id="student_id" name="student_id" value="{escape(student_id)}" autocomplete="off" required autofocus>
  <p class="field-hint">Letters, numbers and hyphens. No names.</p>
  <label for="birth_date">Date of birth</label>
  <input id="birth_date" name="birth_date" type="date" max="{today}" value="{escape(birth_date)}" required>
  <p class="field-hint">Used only to work out the age. It is not saved.</p>
  {voice_box}
  {_error(error)}
  <div class="actions {"" if practice else "one"}">
    <button class="primary" name="mode" value="screen">Start screening</button>
    {practice_button}
  </div>
  <footer><a href="/kid" target="_blank">Open the child screen</a><a href="/look">Look of the child screen</a><a href="/sessions">Past sessions</a></footer>
</form>
</body>
</html>
"""


LOOK_CSS = START_CSS + """
  .start { max-width: 820px; }
  h2 { font-size: 15px; margin: 18px 0 8px; }
  .pick { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
  .pick button { padding: 6px 6px 8px; background: #fff; color: #16202c; border: 2px solid #d9dfe7; font-size: 15px; text-transform: capitalize; }
  .pick button[aria-pressed="true"] { border-color: #1d4f91; background: #e8eef7; color: #1d4f91; }
  .pick img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: contain; border-radius: 4px; margin-bottom: 6px; }
  @media (max-width: 560px) { .pick { grid-template-columns: 1fr 1fr; } }
"""


def look_page(looks: dict[str, list[str]], look: dict[str, str], error: str | None = None) -> str:
    """The child screen's world and buddy, each picked with one press; the screen follows at once."""
    def pick(kind: str, src) -> str:
        return "".join(f'<button name="{kind}" value="{escape(n)}" aria-pressed="{str(n == look[kind]).lower()}">'
                       f'<img src="{src(n)}" alt="">{escape(n)}</button>' for n in looks[kind])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Look, Speak Up</title>
<style>{LOOK_CSS}</style>
</head>
<body>
<form class="start" method="post" action="/look">
  <h1 class="brand">Look</h1>
  <p class="lead">The child screen's world and buddy. Any buddy goes in any world; the screen changes at once.</p>
  <h2>World</h2>
  <div class="pick">{pick("world", lambda n: f"/felt/thumb-{n}.webp")}</div>
  <h2>Buddy</h2>
  <div class="pick">{pick("buddy", lambda n: f"/felt/{n}-spin-000.webp")}</div>
  {_error(error)}
  <footer><a href="/">Back to the start</a><a href="/kid" target="_blank">Open the child screen</a></footer>
</form>
</body>
</html>
"""


@dataclass(frozen=True)
class TryInfo:
    """What the app learned from one recording besides Arti's answer."""
    word: Word
    clip: Path | None = None
    check: ClipCheck | None = None  # the recording check
    f0: float | None = None  # median pitch of the clip, Hz
    reading: object | None = None  # voice.Reading when the adult-voice adjustment was on
    # Nov 4: `clip` is the whole recording; `word_clip` is the selected target word cropped from it
    # (<clip stem>-word.wav), the audio Arti scored and the analysis shows.
    word_clip: Path | None = None
    selection: tuple[float, float] | None = None  # (start, end) in s within `clip`
    auto_selected: bool = True  # False once the SLP has moved the box
    method: str | None = None  # how the app picked it: segment.Selection.method
    line: str | None = None  # what the child was asked to say (the word, or a practice line)
    # Nov 5: the target-sound window the SLP dragged on the analysis viewer, (start, end) in s from the word
    # start; None means the app's automatic window. Dropped whenever the word box moves (a new crop).
    target_window: tuple[float, float] | None = None


@dataclass(frozen=True)
class WordView:
    """Everything the SLP screen shows about the current item beyond the session itself."""
    key: str | None = None  # s3 / p5: the try's key for its audio and analysis links
    info: TryInfo | None = None
    last: LastTime | None = None  # this child's most recent saved result on this word
    picture: str | None = None  # URL of the word's picture
    analysis: object | None = None  # acoustics.Analysis of the clip, when numpy is there and a clip exists
    voice_mode: str = "child"
    stretch_available: bool = False
    wave: tuple[float, list[float]] | None = None  # (seconds, peaks) of the whole recording, for the box
    quiet_s: float = 2.0  # how long a quiet stretch ends a recording (--silence)
    qwen_line: bool = False  # the practice line on screen is one Qwen wrote at start-up
    mode: str | None = None  # --replay: says the clips are saved ones, not the mic

    @property
    def check(self) -> ClipCheck | None:
        return self.info.check if self.info else None

    @property
    def clip(self) -> Path | None:
        return self.info.clip if self.info else None


def not_found_page() -> str:
    return _slp_page("Not found", "", '<main class="one"><div class="card"><h3>Page not found</h3>'
                     '<p><a href="/">Start a session</a></p></div></main>')


def _when_short(iso: str) -> str:
    try:
        when = datetime.fromisoformat(iso)
    except ValueError:
        return iso[:10]
    return f"{when:%b} {when.day}"


def _slp_page(title: str, banner: str, body: str, head: str = "") -> str:
    proof_bar = proof.bar_html(proof.LIVE.snapshot()) if banner else ""  # every page with the SLP header (#38)
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        f'<meta name="viewport" content="width=device-width, initial-scale=1">\n{head}'
        f"<title>{escape(title)}, Speak Up</title>\n<style>{SLP_CSS}</style>\n</head>\n"
        f"<body>\n{banner}\n{body}\n{proof_bar}</body>\n</html>\n"
    )


def _book_link(owner, what: str, word: str | None) -> str:
    """The banner's Sound book link, opened for the word on screen: the word given, else the analysed word named in
    `what` ("Sound analysis: rabbit"), else the owner's current word; a practice line adds its sounds too."""
    if word is None and what.startswith("Sound analysis: "):
        word = what.removeprefix("Sound analysis: ")
    line = None
    if word is None:
        current = getattr(owner, "current_word", None)
        word = current.word if current is not None else None
        line = getattr(owner, "line", None)
    if not word:
        return "/book"
    query = {"word": word}
    if line and line.strip().lower().rstrip(".") != word.lower():
        query["line"] = line
    age = getattr(owner, "age_months", None)
    if isinstance(age, int):  # the book's computer-made pictures then show a speaker of the child's age
        query["age"] = str(age)
    return "/book?" + urlencode(query)


def _mode_tag(mode: str | None) -> str:
    if not mode:
        return ""
    return f'\n    <div><small>Mode</small><b><span class="tag adult">{escape(mode)}</span></b></div>'


def _banner(owner, what: str, view: WordView | None = None, word: str | None = None,
            mode: str | None = None) -> str:
    """mode: the Replay tag, for the pages that have no WordView; a view brings its own."""
    adult = view is not None and view.voice_mode == "adult"
    voice_tag = '<span class="tag adult">Adult voice (demo)</span>' if adult else '<span class="tag">Child voice</span>'
    return f"""<header class="banner">
  <span class="brand">Speak Up</span>
  <div class="who">
    <div><small>Student</small><b>{escape(owner.child_id)}</b></div>
    <div><small>Age</small><b>{format_age(owner.age_months)}</b></div>
    <div><small>Now</small><b>{escape(what)}</b></div>
    <div><small>Voice</small><b>{voice_tag}</b></div>{_mode_tag(view.mode if view is not None else mode)}
  </div>
  <nav class="links"><a href="{escape(_book_link(owner, what, word))}" data-book>Sound book</a><a href="/kid" target="_blank">Child screen</a><a href="/sessions">Past sessions</a><a href="/">New</a></nav>
</header>
<script>{BOOKLINK_JS}</script>"""


# The Sound book opens in the same tab. Before leaving, the page notes exactly where the SLP was (this page, its
# scroll, and the full view with its own scroll when it is open) in its history entry and in the book's back=
# address, so the book's "Back to where you were" button, or the browser's Back, returns to that spot.
BOOKLINK_JS = r"""
(function () {
  if (window.BookLink) return;
  function spot() {
    const fv = window.FullView && window.FullView.isOpen() ? window.FullView.url() : null;
    return { y: Math.round(window.scrollY || 0), fv: fv, fy: fv ? window.FullView.scrollY() : 0 };
  }
  function backUrl(s) {
    return location.pathname + location.search + "#back:y=" + s.y +
      (s.fv ? "&fv=" + encodeURIComponent(s.fv) + "&fy=" + s.fy : "");
  }
  document.addEventListener("click", function (e) {
    const a = e.target.closest && e.target.closest("a[data-book]");
    if (!a || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    const s = spot(), back = backUrl(s), u = new URL(a.getAttribute("href"), location.href);
    try { history.replaceState(Object.assign({}, history.state, { spot: s }), ""); } catch (err) { /* old browser */ }
    u.searchParams.set("back", back);
    try { sessionStorage.setItem("speakup.bookFrom", back); } catch (err) { /* private window: the link still works */ }
    location.assign(u.pathname + u.search);
  });
  function restore(s) {
    if (!s) return;
    if (s.fv && window.FullView && !window.FullView.isOpen()) window.FullView.open(s.fv, s.fy || 0);
    window.scrollTo(0, s.y || 0);
  }
  // Back from the book by its button when the browser had no history to go back to: the spot is in the address.
  function fromHash() {
    const m = /^#back:(.*)$/.exec(location.hash);
    if (!m) return null;
    const q = new URLSearchParams(m[1]);
    history.replaceState(history.state, "", location.pathname + location.search);
    return { y: +q.get("y") || 0, fv: q.get("fv"), fy: +q.get("fy") || 0 };
  }
  window.addEventListener("load", function () {
    const h = fromHash();
    if (h) restore(h);
    else if (history.state && history.state.spot) {
      restore(history.state.spot);
      const st = Object.assign({}, history.state); delete st.spot;  // used once: a later reload keeps its own place
      history.replaceState(st, "");
    }
  });
  window.BookLink = { spot: spot };
})();
"""


def _status(a: Attempt | None) -> tuple[str, str]:
    if a is None:
        return "", "not yet"
    off = a.result.error_type is not None
    who = "slp" if a.slp else ""
    text = ("flag" if a.flagged else "watch" if a.watched else "off") if off else "right"
    return f"{_state_of(a)} {who}", text


def _rail(session: Session) -> str:
    rows = []
    for i, word in enumerate(session.words):
        cls, text = _status(session.slot(i))
        current = "current" if i == session.index else ""
        rows.append(
            f'<form method="post" action="/go"><input type="hidden" name="i" value="{i}">'
            f'<button class="wrow {current}"><span class="n">{i + 1}</span><span>{escape(word.word)}</span>'
            f'<span class="pill {cls}">{text}</span></button></form>')
    finish = ""
    if session.attempts:
        finish = (f'<form class="finish" method="post" action="/finish"><button class="quiet wide">'
                  f'Finish with {len(session.attempts)} of {len(session.words)}</button></form>')
    return (f'<aside class="card rail"><h3>Words</h3>{"".join(rows)}{finish}'
            '<p class="note" style="padding:0 10px">✓ = checked by you. Click a word to go back to it.</p></aside>')


def _recording_card(view: WordView, base: str = "") -> str:
    c = view.check
    if c is None:
        body = ('<div class="rec"><span class="dot"></span><div><b>No clip on this machine</b>No recording to check (laptop test mode), so this page leaves out '
                'Listen to the box, the recording check, the waveform, the measured F3-F2 gap and the sound picture. '
                'To see them, start the app with <code style="white-space:nowrap">--sample-clip rabbit.wav</code> (see the README).</div></div>')
    elif c.ok:
        body = (f'<div class="rec"><span class="dot good"></span><div><b>Recording OK</b>{c.speech_seconds:.1f} s of speech, '
                f"loudest point {c.peak:,} of 32,767.</div></div>")
    else:
        items = "".join(f"<li>{escape(p)}</li>" for p in c.problems)
        body = f'<div class="rec"><span class="dot warn"></span><div><b>Check the recording before trusting Arti</b><ul>{items}</ul></div></div>'
    info = view.info
    if view.key and info is not None and info.selection and view.wave and view.wave[1]:
        start, end = info.selection
        return body + selectview.selection_card(view.key, base, view.wave[0], view.wave[1], start, end,
                                                info.auto_selected, info.method)
    replay = f'<audio controls preload="none" src="/audio/{view.key}.wav"></audio>' if view.clip and view.key else ""
    return body + replay


def _unsure(view: WordView) -> bool:
    r = view.info.reading if view.info else None
    return r is not None and not r.stable


# Round 3 (#37), the owner's pick from mockups/round3-slp-view/c-question-card.html: one card asks whether the SLP
# agrees with Arti. Disagree and Agree are two buttons; L plays the evidence box (Listen to the box).
QUESTION_CSS = """
  .q { padding: 0; overflow: hidden; margin-top: 14px; }
  .qhead { text-align: center; padding: 14px 20px 0; }
  .qword { font-size: 34px; font-weight: 700; line-height: 1.1; }
  .ask { font-size: 21px; margin-top: 8px; }
  .ask b.off { color: #9b2c13; } .ask b.ok { color: #23633a; }
  .doubt .ask b { color: #6b7785; }
  .qhead .why { text-align: left; }
  .measured { margin: 10px auto 0; max-width: 560px; text-align: left; font-size: 13px; color: #3d4a5c;
              background: #eef3f8; border-radius: 8px; padding: 8px 12px; }
  .measured.differs { background: #fff4d6; color: #6b4a00; }
  .unsure { margin: 12px auto 0; max-width: 420px; background: #fff4d6; color: #6b4a00; font-weight: 700;
            padding: 8px 12px; border-radius: 999px; border: 1px solid #f0d58a; }
  .choose { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin: 16px 16px 0; }
  .choose form { display: grid; margin: 0; }
  .half { border: 2px solid; border-radius: 12px; background: #fff; padding: 12px 8px; font-size: 20px; font-weight: 700;
          touch-action: manipulation; }
  .half small { display: block; font-size: 12px; font-weight: 500; color: #44505e; }
  .half.disagree { color: #9b2c13; border-color: #e7a99a; }
  .half.agree { color: #23633a; border-color: #9fd0ae; }
  .half.disagree.on { background: #fbe3dd; border-color: #9b2c13; }
  .half.agree.on { background: #e3f2e6; border-color: #23633a; }
  .saved { text-align: center; color: #44505e; padding: 10px; margin: 0; }
  .q .next { margin: 0; padding: 0 16px 16px; }
  .evidence { margin-top: 14px; }
  .evidence > summary { cursor: pointer; font-size: 12px; text-transform: uppercase; letter-spacing: .06em;
                        color: #6b7785; font-weight: 600; padding: 4px 2px; }
  .evidence > .card:first-of-type { margin-top: 8px; }
"""

# A agrees, D disagrees, L presses Listen to the box. Not while typing, not with ctrl, cmd or alt (the browser's own
# shortcuts), not on a held key, and not while the full sound analysis is open over the page.
SLP_KEYS_JS = r"""
(function () {
  const card = document.getElementById("slp-q");
  if (!card) return;
  document.addEventListener("keydown", e => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.repeat || e.defaultPrevented || !/^[adl]$/i.test(e.key)) return;
    const t = e.target;
    if (t.isContentEditable || (t.closest && t.closest("input, textarea, select"))) return;
    if (window.FullView && window.FullView.isOpen()) return;
    const k = e.key.toLowerCase();
    const b = k === "l" ? document.getElementById("sel-listen") : card.querySelector('[data-key="' + k + '"]');
    if (!b || b.disabled) return;
    e.preventDefault();
    b.click();
  });
})();
"""


def _question_card(owner, attempt: Attempt, i: int, view: WordView, base: str, next_label: str) -> str:
    """Arti's call as a yes or no question, the SLP's two answers, and Next."""
    arti = attempt.arti or attempt.result
    off = arti.error_type is not None
    bad_clip = view.check is not None and not view.check.ok
    head = "Arti suggests"
    if bad_clip:
        head = "Arti's guess on a problem recording: don't rely on it"
    elif _unsure(view):
        head = "Arti is unsure (the voice adjustment changes its answer)"
    doubtful = bad_clip or _unsure(view)
    sure = ""
    if arti.confidence is not None:
        sure = f"{arti.confidence:.0%} sure{'. Listen closely before you decide' if arti.confidence < 0.7 else ''}. "
    shown = attempt if attempt.arti is None else replace(attempt, result=arti)
    flag = ""
    if arti.error_type and attempt.slp is None:
        word = "Flagged" if attempt.flagged else "Keep an eye on it" if attempt.watched else "Normal"
        flag = f" {word} for age {format_age(owner.age_months)}."
    why = explain(arti.error_type, arti.target_sound, owner.age_months)
    why_html = f'<div class="why">{escape(why)}</div>' if why else ""
    p_wrong = arti_p_wrong(attempt)
    is_unsure = p_wrong is not None and calibration.unsure(p_wrong)
    pill = '<div class="unsure">Unsure, SLP please listen</div>' if is_unsure else ""
    measured = ""
    if view.analysis is not None:
        line = evidence.gap_line(view.analysis.gap_min, owner.current_word.position, off)
        if line:
            measured = f'<div class="measured{"" if line[1] else " differs"}">{escape(line[0])}</div>'

    heard = "the r sounded off" if off else "the r sounded right"
    other = "the r sounded right" if off else "the r sounded off"
    agreed = None if attempt.slp is None else attempt.slp == attempt.arti_call

    # Each half posts the call it shows, not agree or disagree: a try recorded again under this page must not flip it (#56).
    # It also names the session and the try it shows, so a press in a second tab still on an older card
    # saves onto that try, or onto nothing if that session is gone (#78).
    def half(kind: str, call: str, key: str, label: str, says: str, on: bool) -> str:
        return (f'<form method="post" action="{base}/verify">'
                f'<input type="hidden" name="started" value="{escape(owner.started_at)}"><input type="hidden" name="i" value="{i}">'
                f'<input type="hidden" name="verdict" value="{call}">'
                f'<button type="submit" class="half {kind}{" on" if on else ""}" data-key="{key}">'
                f'{label}<small>{says[0].upper()}{says[1:]} ({key.upper()})</small></button></form>')

    if agreed is None:
        state = "Not checked yet. Next keeps Arti's call."
    elif agreed:
        state = f"You agreed with Arti: {heard}. Your call is saved; you can change it until you finish."
    else:
        state = f"You disagreed with Arti: {other}. Your call is saved; you can change it until you finish."
    if attempt.arti_call_checked not in (None, attempt.arti_call):
        state = f"Arti changed its answer after you moved the box. {state}"
    return f"""<style>{QUESTION_CSS}</style>
<div class="card q{" doubt" if doubtful else ""}{" unsure-on" if is_unsure else ""}" id="slp-q">
  <div class="qhead"><h3>{escape(head, quote=False)}</h3>
    <div class="qword">{escape(owner.current_word.word)}</div>
    <div class="ask">Arti heard: <b class="{"off" if off else "ok"}">{heard}</b>. Do you agree?</div>
    <div class="meta">{sure}Heard: {escape(_heard(shown))}.{flag} Model: {escape(arti.model)}.</div>{why_html}{measured}{pill}
  </div>
  <div class="choose">
    {half("disagree", "correct" if off else "wrong", "d", "Disagree", other, agreed is False)}
    {half("agree", "wrong" if off else "correct", "a", "Agree", heard, agreed is True)}
  </div>
  <p class="saved">{state}</p>
  <form class="next" method="post" action="{base}/next"><button class="primary big wide">{escape(next_label)} →</button></form>
</div>
<script id="slp-keys">{SLP_KEYS_JS}</script>"""


def _voice_card(view: WordView) -> str:
    info = view.info
    if info is None or info.f0 is None:
        return ""
    from speakup import voice  # numpy is here whenever there is a pitch
    r = info.reading
    pitch = f"Pitch of this clip: {info.f0:,.0f} Hz."
    if view.voice_mode == "adult" and r is not None:
        plain = "off" if r.plain >= 0.5 else "right"
        near = ", ".join(f"×{a:.2f}: {'off' if p >= 0.5 else 'right'}" for a, p in r.neighbours)
        stable = ("Same answer at the neighbouring settings." if r.stable
                  else "The answer changes at a neighbouring setting: decide by ear.")
        return f"""<div class="card voice {"" if r.stable else "warn"}"><h3>Adult voice adjustment</h3>
  <p>Arti listened with the voice's resonances raised ×{r.alpha:.2f}, set from the speaker's pitch (never from Arti's answer).</p>
  <p class="meta">{pitch} Without the adjustment Arti said: {plain}. {escape(near)}.</p>
  <p class="meta"><b>{stable}</b></p></div>"""
    if view.voice_mode == "child" and voice.hint(info.f0) == "adult-man":
        extra = (" Start a new session with “An adult (demo)” to adjust for it." if view.stretch_available else "")
        return f"""<div class="card voice warn"><h3>Voice check</h3>
  <p>{pitch} That is in an adult man's range (children 4 to 12 average 240 to 280 Hz). Arti learned from children
  and misses r errors in adult voices.{extra}</p></div>"""
    return ""


def gap_text(a) -> str:
    """The one-line F3-F2 reading under the small picture; says so when the SLP moved the target window."""
    moved = (a.window is not None and getattr(a, "auto_window", None) is not None
             and tuple(a.window) != tuple(a.auto_window))
    if a.gap_min is None:
        return "F3-F2 gap: not measured on this clip." + (" The target window was moved by you." if moved else "")
    where = "in the target window you set" if moved else "where the r should be"
    return f"F3-F2 gap {where}: {a.gap_min:,.0f} Hz (experimental)."


def _sound_card(view: WordView) -> str:
    a = view.analysis
    if a is None:
        return ""
    from speakup import soundpic  # needs numpy; imported only when there is an analysis to draw
    href = f"/analysis/{view.key}"
    tip = "Open the full sound analysis"
    return (f'<div class="card sound"><h3>Sound picture (estimate)</h3>'
            f'<a class="expand" href="{href}" data-full="{href}" title="{tip}" aria-label="{tip}">⤢</a>'
            f'<a class="picture" href="{href}" data-full="{href}" title="{tip}" aria-label="{tip}">'
            f'{soundpic.svg(a, width=640, compact=True)}</a>'
            f'<p class="meta" id="sound-gap">{escape(gap_text(a))}</p></div>'
            f'<script>{FULLVIEW_JS}</script>')


# The full analysis opens over the word or practice page (an overlay with the viewer in a frame), so the SLP never
# loses the page. The x or Esc closes it; it is a history entry, so the browser's Back closes it too.
# /analysis/<key> still works as its own page (ctrl-click, a new tab, or "Open as its own page").
FULLVIEW_JS = r"""
(function () {
  if (window.FullView) return;
  let ov = null, back = null, cur = null;
  function open(url, push, fy) {
    if (ov) return;
    cur = url;
    back = document.activeElement;
    const book = document.querySelector(".banner a[data-book]");
    ov = document.createElement("div");
    ov.className = "fullview"; ov.setAttribute("role", "dialog"); ov.setAttribute("aria-modal", "true");
    ov.setAttribute("aria-label", "Full sound analysis");
    ov.innerHTML = '<div class="fv-head"><b>Full sound analysis</b><span class="fv-say">Esc, Back or the x returns to this page.</span>' +
      (book ? '<a class="fv-book" href="' + book.getAttribute("href") + '" data-book>Sound book</a>' : "") +
      '<a class="fv-own" href="' + url + '" target="_blank" rel="noopener">Open as its own page</a>' +
      '<button type="button" class="fv-x" aria-label="Close the full view" title="Close (Esc)">×</button></div>';
    const fr = document.createElement("iframe");  // src set before it joins the page: no extra history entry
    fr.src = url + "?embed=1"; fr.title = "Full sound analysis";
    ov.appendChild(fr);
    document.body.appendChild(ov); document.body.classList.add("fv-open");
    if (push) history.pushState({ fullview: url }, "");
    ov.querySelector(".fv-x").addEventListener("click", () => close(true));
    fr.addEventListener("load", () => {
      try { if (fy) fr.contentWindow.scrollTo(0, fy); fr.contentWindow.focus(); } catch (e) { /* same origin */ }
    });
    ov.querySelector(".fv-x").focus();
  }
  function close(viaHistory) {
    if (!ov) return;
    if (viaHistory && history.state && history.state.fullview) { history.back(); return; }  // popstate removes it
    ov.remove(); ov = null; cur = null; document.body.classList.remove("fv-open");
    if (back && back.focus) back.focus();
  }
  document.querySelectorAll("[data-full]").forEach(a => a.addEventListener("click", e => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;  // a new tab still gets the page
    e.preventDefault(); open(a.dataset.full, true);
  }));
  window.addEventListener("popstate", () => {
    const st = history.state;
    if (st && st.fullview) open(st.fullview, false, st.spot && st.spot.fy); else close(false);
  });
  document.addEventListener("keydown", e => { if (e.key === "Escape" && ov) { e.preventDefault(); close(true); } });
  window.addEventListener("message", e => {
    if (e.origin !== location.origin || !e.data) return;
    if (e.data.type === "sv-close") close(true);
    if (e.data.type === "sv-window" && e.data.gapText) { const g = document.getElementById("sound-gap"); if (g) g.textContent = e.data.gapText; }
  });
  // A reload, or Back from the sound book, with it open: reopen it where it was.
  if (history.state && history.state.fullview) open(history.state.fullview, false, history.state.spot && history.state.spot.fy);
  function scrollY() { const fr = ov && ov.querySelector("iframe"); try { return fr ? Math.round(fr.contentWindow.scrollY) : 0; } catch (e) { return 0; } }
  window.FullView = { open: (url, fy) => open(url, true, fy), close: () => close(true), isOpen: () => !!ov,
                      url: () => cur, scrollY };
})();
"""


def _last_card(view: WordView) -> str:
    if view.last is None:
        return '<div class="card side"><h3>Last time</h3><p>No earlier result for this student on this word.</p></div>'
    r = view.last.result
    call = "the r sounded off" if r.error_type else "the r sounded right"
    checked = "checked by the SLP" if view.last.slp_checked else "Arti only, not checked"
    return f'<div class="card side"><h3>Last time</h3><p>{_when_short(view.last.started_at)}: {call} ({checked}).</p></div>'


def _tally_card(attempts: list[Attempt], words: list[Word], title: str) -> str:
    counts = position_tally(attempts)
    rows = "".join(
        f"<tr><td>r at the {escape(pos)}</td><td>{counts.get(pos, (0, 0))[0]} right, {counts.get(pos, (0, 0))[1]} off</td></tr>"
        for pos in POSITIONS if any(w.position == pos for w in words)
    )
    agreed, checked = agreement(attempts)
    agree = f"You agreed with Arti on {agreed} of {checked} checked words." if checked else "Nothing checked yet."
    return (f'<div class="card side"><h3>{escape(title)}</h3><table class="mini">{rows}</table>'
            f'<p class="meta">{agree}</p></div>')


def _work(owner, attempt: Attempt | None, i: int, view: WordView, base: str, item_html: str, next_label: str,
          record_hint: str, error: str | None) -> str:
    """The middle column: the item, Record, and once recorded the evidence and the SLP's call."""
    record = f"<style>{selectview.SELECT_CSS}</style>" + selectview.record_controls(base, attempt is not None, view.quiet_s)
    picture = f'<img src="{escape(view.picture)}" alt="">' if view.picture else "<span></span>"
    head = f'<div class="card target">{picture}<div>{item_html}</div><div>{record}</div></div>'
    if attempt is None:
        return (f'{_error(error)}{head}<div class="card"><p class="hint" style="margin:0">{escape(record_hint)}</p></div>')
    return (f'{_error(error)}{head}{_question_card(owner, attempt, i, view, base, next_label)}'
            '<details class="evidence" open><summary>Evidence: recording, voice, sound picture</summary>'
            f'<div class="card">{_recording_card(view, base)}</div>{_voice_card(view)}{_sound_card(view)}</details>')


def word_page(session: Session, error: str | None = None, view: WordView | None = None) -> str:
    view = view or WordView()
    word = session.current_word
    attempt = session.current_attempt
    remaining = [i for i in range(len(session.words)) if session.slot(i) is None and i != session.index]
    next_label = "Next word" if remaining else "Finish"
    item = (f'<div class="tword">{escape(word.word)}</div><div class="tpos">r at the {escape(word.position)}, '
            f'word {session.index + 1} of {len(session.words)}</div>')
    work = _work(session, attempt, session.index, view, "", item, next_label,
                 "The child screen shows the picture. Press Record: the mic keeps recording until the child "
                 f"has been quiet for {selectview.quiet_text(view.quiet_s)}, or until you press Stop. The app then picks out "
                 "the word.", error)
    return _slp_page(word.word, _banner(session, f"Word {session.index + 1} of {len(session.words)}", view), f"""
<main class="shell">
  {_rail(session)}
  <section>{work}</section>
  <aside class="context">{_last_card(view)}{_tally_card(session.attempts, session.words, "This session, your checks")}
    <p class="aid">Screening aid, not a diagnosis. The SLP decides.</p></aside>
</main>""")


def _coach_note(practice, attempt) -> str:
    """What the coach is doing, for the SLP: the weak position it is drilling, the tip on screen, a near miss."""
    bits = []
    if attempt is not None and coach.almost(attempt.result):
        bits.append("<b>Almost there:</b> a near miss, worth praising the effort.")
    weak = coach.weakest(practice.attempts)
    if weak:
        bits.append(f"Coach is drilling r at the {escape(weak)}.")
    if practice.tip:
        bits.append(f"Tip on the child's screen: “{escape(practice.tip)}”")
    return f'<div class="tpos">{" ".join(bits)}</div>' if bits else ""


def practice_page(practice: Practice, error: str | None = None, view: WordView | None = None) -> str:
    view = view or WordView()
    attempt = practice.current_attempt
    word = practice.current_word
    ladder = " › ".join(f"<b>{lv.capitalize()}</b>" if lv == practice.level else lv.capitalize() for lv in LEVELS)
    by_qwen = " Line written by Qwen on the board." if view.qwen_line else ""
    item = (f'<div class="tpos">Practice: {ladder}</div>'
            f'<div class="tline">{escape(practice.line)}</div><div class="tpos">{escape(practice.level.capitalize())} level, '
            f'try {practice.turn + 1}. Target word {escape(word.word)}, r at the {escape(word.position)}.{by_qwen}</div>'
            + _coach_note(practice, attempt))
    work = _work(practice, attempt, practice.turn, view, "/practice", item, "Next",
                 "The child screen shows the line. Press Record and have the child say it. "
                 "A right answer moves up a level (word, phrase, sentence); a miss moves down. Your call overrides Arti's.",
                 error)
    levels = "".join(
        f'<tr><td>{i}</td><td>{escape(a.level.capitalize())}</td><td>{"off" if a.result.error_type else "right"}{" ✓" if a.slp else ""}</td></tr>'
        for i, a in enumerate(practice.attempts, 1))
    history = (f'<div class="card side"><h3>Tries so far</h3><table class="mini">{levels}</table></div>'
               if levels else "")
    end = '<form method="post" action="/practice/end"><button class="quiet wide">End practice</button></form>'
    return _slp_page("Practice", _banner(practice, f"Practice, {practice.level.capitalize()} level, try {practice.turn + 1}", view), f"""
<main class="shell" style="grid-template-columns: 1fr 300px">
  <section>{work}</section>
  <aside class="context">{_last_card(view)}{history}<div class="card">{end}</div>
    <p class="aid">{_AID} A tracker, not therapy.</p></aside>
</main>""")


def _rows(rows) -> str:
    return "".join(f"<tr><td>{escape(k)}</td><td>{escape(v)}</td></tr>" for k, v in rows)


def _measure_groups(a, info: "TryInfo | None") -> list[tuple[str, list[tuple[str, str]]]]:
    """Everything the recording and the tracks give, grouped. Values only: the reader is the SLP."""
    import numpy as np
    from speakup import voice

    rec = []
    if a.clip_seconds:
        rec.append(("Recording length", f"{a.clip_seconds:.2f} s"))
    rec.append(("Word found at", f"{a.start:.2f} to {a.end:.2f} s in the recording"))
    rec.append(("Word length", f"{a.duration:.2f} s"))
    if a.peak:
        rec.append(("Loudest sample", f"{a.peak * 32767:,.0f} of 32,767 ({20 * np.log10(a.peak):.1f} dBFS)"))
    if info and info.check:
        c = info.check
        rec.append(("Speech in the recording", f"{c.speech_seconds:.2f} s"))
        rec.append(("Clipped samples", f"{c.clipped_share:.1%}"))
        rec.append(("Recording check", "OK" if c.ok else "; ".join(c.problems)))

    f0 = a.f0[~np.isnan(a.f0)]
    pitch = []
    if len(f0):
        lo, hi = float(f0.min()), float(f0.max())
        pitch += [("F0 median", f"{float(np.median(f0)):,.0f} Hz"),
                  ("F0 lowest, highest", f"{lo:,.0f}, {hi:,.0f} Hz"),
                  ("F0 range", f"{hi - lo:,.0f} Hz ({12 * np.log2(hi / lo):.1f} semitones)"),
                  ("F0 spread (SD)", f"{float(np.std(f0)):,.1f} Hz")]
        hint = {"adult-man": "adult man's range (below 165 Hz)",
                "child-or-woman": "child's or woman's range (above 200 Hz)",
                "unclear": "between ranges (165 to 200 Hz)"}[voice.hint(float(np.median(f0)))]
        pitch.append(("Voice range", hint))
    voiced_share = len(f0) / len(a.f0) if len(a.f0) else 0
    pitch.append(("Voiced frames", f"{voiced_share:.0%} of the word"))
    reading = getattr(info, "reading", None) if info else None
    if reading is not None:
        pitch.append(("Adult-voice adjustment", f"x{reading.alpha:.2f}, Arti p(wrong) {reading.p_wrong:.2f} "
                                                f"(unadjusted {reading.plain:.2f}), {'stable' if reading.stable else 'unsure'}"))

    res = []
    for k, name in enumerate(("F1", "F2", "F3")):
        col = a.formants[:, k]
        col = col[~np.isnan(col)]
        if len(col):
            res.append((f"{name} median (lowest to highest)",
                        f"{float(np.median(col)):,.0f} Hz ({col.min():,.0f} to {col.max():,.0f})"))
    gaps = a.formants[:, 2] - a.formants[:, 1]
    gaps = gaps[~np.isnan(gaps)]
    if len(gaps):
        res.append(("F3-F2 median over the word", f"{float(np.median(gaps)):,.0f} Hz"))
    moved = a.window is not None and getattr(a, "auto_window", None) is not None and tuple(a.window) != tuple(a.auto_window)
    if a.gap_min is not None:
        where = "in the target window you set" if moved else "where the r should be"
        res.append((f"F3-F2 narrowest {where} (experimental)", f"{a.gap_min:,.0f} Hz at {a.gap_time:.3f} s"))
        f1, f2, f3 = a.at_gap
        res.append(("F1, F2, F3 at that moment", f"{f1:,.0f}, {f2:,.0f}, {f3:,.0f} Hz"))
    if a.window:
        res.append(("Target sound window" + (" (moved by you)" if moved else " (automatic)"),
                    f"{a.window[0]:.2f} to {a.window[1]:.2f} s"))
    tracked = int(np.sum(~np.isnan(a.formants).any(axis=1))) if len(a.formants) else 0
    res.append(("Frames with all three formants", f"{tracked} of {len(a.formants)}"))

    loud = []
    if len(a.rms) and a.rms.max() > 0:
        db = 20 * np.log10(np.maximum(a.rms, 1e-9))
        i = int(np.argmax(db))
        loud += [("Intensity peak", f"{db[i]:.1f} dB (re full scale) at {a.times[i]:.3f} s"),
                 ("Intensity median", f"{float(np.median(db[a.rms > 0])):.1f} dB")]
    groups = [("Recording", rec), ("Voice", pitch), ("Resonances", res), ("Loudness", loud)]
    return [(name, rows) for name, rows in groups if rows]


def measures_html(a, info: "TryInfo | None") -> str:
    """The Measures card's groups, also sent back when the SLP moves the target window."""
    return "".join(f'<div><h4>{escape(name)}</h4><table class="measure">{_rows(rows)}</table></div>'
                   for name, rows in _measure_groups(a, info))


def _frame_table(a) -> str:
    import numpy as np

    def cell(v):
        return "" if v is None or np.isnan(v) else f"{v:,.0f}"

    head = "<tr><th>Time (s)</th><th>F0</th><th>F1</th><th>F2</th><th>F3</th><th>F3-F2</th><th>dB</th></tr>"
    rows = []
    for i, t in enumerate(a.times):
        f1, f2, f3 = a.formants[i]
        db = 20 * np.log10(a.rms[i]) if i < len(a.rms) and a.rms[i] > 0 else np.nan
        rows.append(f"<tr><td>{t:.3f}</td><td>{cell(a.f0[i])}</td><td>{cell(f1)}</td><td>{cell(f2)}</td>"
                    f"<td>{cell(f3)}</td><td>{cell(f3 - f2)}</td><td>{'' if np.isnan(db) else f'{db:.1f}'}</td></tr>")
    return f'<table class="frames">{head}{"".join(rows)}</table>'


def _compare_line(current, reference) -> str:
    if current is None or reference is None or current.gap_min is None or reference.gap_min is None:
        return ""
    diff = current.gap_min - reference.gap_min
    if abs(diff) < 150:
        return f"The gap is about the same as in that correct production ({diff:+,.0f} Hz)."
    side = "wider" if diff > 0 else "narrower"
    return f"The gap is {abs(diff):,.0f} Hz {side} than in that correct production."


def _hz(v) -> str:
    return "not measured" if v is None else f"{v:,.0f} Hz"


def analysis_page(owner, word: Word, current, reference, available: bool = True, back: str = "/word",
                  info: TryInfo | None = None, audio_url: str | None = None, key: str | None = None,
                  embed: bool = False, mode: str | None = None) -> str:
    """The full sound analysis of one try for the SLP: an interactive viewer of everything the recording gives,
    the measures, the frame-by-frame listing, and, once there is one, this student's own last production of the
    word that the SLP called correct. reference: (started_at, Analysis or None) or None. key: the try's key (s3,
    p5) for the target-window endpoint; embed: drawn inside the word page's full-view overlay (no banner, no Back
    link, an Esc the viewer does not use asks the page around it to close)."""
    if available:
        from speakup import soundpic, soundview  # needs numpy; the server says whether it is there
    if not available:
        body = '<p class="hint">The sound analysis needs numpy, which this machine does not have.</p>'
    elif current is None:
        body = '<p class="hint">No clip to analyse. On a laptop in test mode there is no recording.</p>'
    else:
        notes = "".join(f"<li>{escape(n)}</li>" for n in current.notes)
        groups = measures_html(current, info)
        step = (current.times[1] - current.times[0]) * 1000 if len(current.times) > 1 else 0
        target = lexicon.target_of(word.word)
        body = (soundview.viewer(current, audio_url, target=target, age_months=getattr(owner, "age_months", None),
                                 context=lexicon.target_context(word.word), word=word.word, key=key,
                                 sex=getattr(owner, "sex", None))
                + f'<ul class="notes" id="sv-notes"{"" if notes else " hidden"}>{notes}</ul>'
                + f'</div><div class="card"><h3>Measures</h3><div class="groups" id="sv-measures">{groups}</div>'
                + f'<details class="listing"><summary>Frame by frame ({len(current.times)} frames, every {step:.0f} ms)'
                  f'</summary>{_frame_table(current)}</details>'
                + '<p class="limits">Estimates: formant and pitch tracks are automatic and can mistrack, '
                  'most on high voices. Screening aid, not a diagnosis.</p>')
    compare = ""
    if available and reference is not None:
        if reference[1] is None:
            inner = '<p class="hint">The reference recording could not be analysed.</p>'
        else:
            ref = reference[1]
            line = _compare_line(current, ref)
            mine = soundpic.svg(current, width=460, compact=True, title="This recording") if current else ""
            theirs = soundpic.svg(ref, width=460, compact=True, title=f"Correct on {_when_short(reference[0])}")
            inner = (f'<div class="pair"><div>{mine}</div><div>{theirs}</div></div>'
                     + (f'<p><b>{escape(line)}</b></p>' if line else "")
                     + f'<table class="measure"><tr><th></th><th>This recording</th><th>Correct on {_when_short(reference[0])}</th></tr>'
                     + f'<tr><td>F3-F2 gap</td><td>{_hz(current.gap_min if current else None)}</td><td>{_hz(ref.gap_min)}</td></tr>'
                     + f'<tr><td>Pitch (F0)</td><td>{_hz(current.f0_median if current else None)}</td><td>{_hz(ref.f0_median)}</td></tr></table>')
        compare = f'<div class="card"><h3>Compared with this student\'s own correct production</h3>{inner}</div>'
    css = soundview.CSS if available else ""
    banner = "" if embed else _banner(owner, f"Sound analysis: {word.word}", word=word.word, mode=mode)
    # The page's own Back, above the recording: inside the overlay it closes the overlay, on its own page it goes back.
    back_link = ('<nav class="backnav-bar">' + (backnav.html("#", "Back to the word", data_close_full="1") if embed
                 else backnav.html(back, "Back to the word")) + "</nav>")
    # Inside the overlay: an Esc the viewer did not use closes the overlay (the page around it listens).
    embed_js = ("<script>document.body.classList.add('embed');document.addEventListener('keydown',function(e){"
                "if(e.key==='Escape'&&!e.defaultPrevented&&window.parent!==window)"
                "window.parent.postMessage({type:'sv-close'},location.origin);});"
                "document.querySelectorAll('[data-close-full]').forEach(function(a){a.addEventListener('click',function(e){"
                "e.preventDefault();window.parent.postMessage({type:'sv-close'},location.origin);});});</script>") if embed else ""
    return _slp_page(f"Sound analysis: {word.word}", banner, f"""<style>{css}{backnav.CSS}</style>
<main class="wide">
{back_link}
<div class="card"><h3>This recording: {escape(word.word)}, /{escape(lexicon.target_of(word.word))}/ at the {escape(word.position)}</h3>{body}</div>
{compare}
</main>{embed_js}""")


def _flagged_cell(a: Attempt) -> str:
    text = "yes" if a.flagged else "no, keep an eye on it" if a.watched else "no, normal for age" if a.result.error_type else "no"
    return f'<td class="{"f" if a.flagged else ""}">{text}</td>'


def _flag_counts(counts: dict[str, int]) -> str:
    """Only the kinds that were flagged: Arti names no kind, so "gliding 0, distortion 0" was always noise."""
    return ", ".join(f"{escape(ERROR_WORDS[t])} {n}" for t, n in counts.items() if n) or "none"


CHECKED = '<span class="pill ok">✓ every number checked by code</span>'
LANG_NAMES = {"en": "English", "es": "Español"}


def _family_card(notes: dict[str, tuple[str, bool]]) -> str:
    """The family practice note (#39), one paragraph per language, each shown as it arrives."""
    paras = []
    for lang, name in LANG_NAMES.items():
        if lang not in notes:
            paras.append(f'<p lang="{lang}"><b>{name}</b><br>Qwen writes it after the note.</p>')
            continue
        text, by_qwen = notes[lang]
        label = f"{name}, by Qwen</b> {CHECKED}" if by_qwen else f"{name}, fixed note filled in by code</b>"
        paras.append(f'<p lang="{lang}"><b>{label}<br>{escape(text)}</p>')
    return f'<div class="card family">\n  <h3>Practice note for the family</h3>\n  {"".join(paras)}\n</div>'


def summary_page(session: Session, save_error: str | None = None, note: str | None = None,
                 note_pending: bool = False, family: dict[str, tuple[str, bool]] | None = None,
                 mode: str | None = None) -> str:
    attempts = session.attempts
    counts = tally(attempts)
    verdict = pass_or_refer([a.result for a in attempts], session.age_months)
    refer = "refer" if any(a.flagged for a in attempts) else ""
    rows = "".join(
        f'<tr><td>{escape(a.word.word)}</td>'
        f'<td>{"off" if (a.arti or a.result).error_type else "right"}'
        f'{"" if (a.arti or a.result).confidence is None else f" ({(a.arti or a.result).confidence:.0%})"}</td>'
        f'<td>{escape(a.slp or "not checked")}</td>{_flagged_cell(a)}</tr>'
        for a in attempts
    )
    skipped = len(session.words) - len(attempts)
    unsaved = ""
    if save_error:
        unsaved = (_error(f"Not saved: {save_error}. The results below are not stored.")
                   + f'<form method="post" action="/save"><button class="primary">Save again</button></form>')
    note_line = ""
    if note:
        # A note reaches the page only after summary.check_reply passed, so a shown note always has the check.
        note_line = (f'<p class="note"><b>Note by Qwen, a small language model running on the board:</b> {escape(note)}</p>'
                     f'\n  <p class="checked">{CHECKED}</p>')
    listen = summary.listen_words(attempts)
    listen_line = f'<p class="listen">SLP please listen: {escape(", ".join(listen))}</p>' if listen else ""
    head = ""
    family_pending = family is not None and len(family) < len(LANG_NAMES)
    if note_pending or family_pending:
        # url= is needed: the failed-save page is the body of POST /next, and a bare refresh would GET /next.
        head = '<meta http-equiv="refresh" content="3; url=/summary">\n'
    if note_pending:
        note_line = '<p class="note">Qwen, a small language model on the board, is writing a note on these results.</p>'
    return _slp_page("Summary", _banner(session, "Screening done", mode=mode), f"""
<main class="one">
{unsaved}
<div class="card">
  <h3>Result</h3>
  <p class="verdict {refer}">{escape(verdict)}</p>
  {listen_line}
  {note_line}
  <p class="meta">Flagged: {_flag_counts(counts)}{f". {skipped} word(s) not recorded." if skipped else ""}</p>
</div>
{_family_card(family) if family is not None else ""}
<div class="card">
  <table class="list">
    <tr><th>Word</th><th>Arti</th><th>SLP</th><th>Flagged</th></tr>
    {rows}
  </table>
  <p class="meta">model: {escape(attempts[-1].result.model)}</p>
</div>
<p class="aid">Screening aid, not a diagnosis. <a href="/">New session</a>, <a href="/sessions">Past sessions</a></p>
</main>""", head=head)


# The practice pages (#21) reuse the screen's parts. A practice is a screening aid and a tracker, not therapy.

_AID = "Screening aid, not a diagnosis. The therapist always decides."


def practice_summary_page(practice: Practice, save_error: str | None = None, mode: str | None = None) -> str:
    attempts = practice.attempts
    counts = tally(attempts)
    verdict = pass_or_refer([a.result for a in attempts], practice.age_months)
    refer = "refer" if any(a.flagged for a in attempts) else ""
    rows = "".join(
        f"<tr><td>{i}</td><td>{escape(a.level.capitalize())}</td><td>{escape(a.line)}</td>"
        f"<td>{escape(_heard(a))}{' (SLP)' if a.slp else ''}</td>{_flagged_cell(a)}</tr>"
        for i, a in enumerate(attempts, 1)
    )
    unsaved = ""
    if save_error:
        unsaved = (_error(f"Not saved: {save_error}. The results below are not stored.")
                   + f'<form method="post" action="/practice/save"><button class="primary">Save again</button></form>')
    return _slp_page("Practice summary", _banner(practice, "Practice done", mode=mode), f"""
<main class="one">
{unsaved}
<div class="card"><h3>Result</h3><p class="verdict {refer}">{escape(verdict)}</p>
<p class="meta">Flagged: {_flag_counts(counts)}</p></div>
<div class="card"><table class="list">
  <tr><th>Try</th><th>Level</th><th>Line</th><th>Heard</th><th>Flagged</th></tr>
  {rows}
</table><p class="meta">model: {escape(attempts[-1].result.model)}</p></div>
<p class="aid">{_AID} <a href="/">New session</a></p>
</main>""")


# The session log pages (#6). Flags come from SavedSession, which runs today's age rule on the stored results.

def _day(started_at: str) -> str:
    d = datetime.fromisoformat(started_at)
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def _when(started_at: str) -> str:
    return f'{_day(started_at)}<span class="time">{datetime.fromisoformat(started_at):%H:%M}</span>'


def _state(s: SavedSession, r: Result) -> str:
    return "flag" if s.is_flagged(r) else "normal" if r.error_type else "ok"


def _word_chips(s: SavedSession) -> str:
    return "".join(f'<span class="chip {_state(s, r)}">{escape(r.word)}</span>' for r in s.results)


def _share(s: SavedSession, most: int) -> str:
    return f'<span class="share" style="width:{s.flag_count() / most * 100:.0f}%"></span>'


def _hot(s: SavedSession) -> str:
    return "n hot" if s.flag_count() else "n"


def _log_page(title: str, crumbs: str, body: str) -> str:
    return _page(title, f"""<div class="bar-top"><div class="crumbs">{crumbs}</div>
<div class="seg"><a class="on" href="/sessions">Past sessions</a><a href="/">New session</a></div></div>
<div class="body">{body}</div>""", LOG_CSS)


def sessions_page(sessions: list[SavedSession]) -> str:
    most = max((s.flag_count() for s in sessions), default=0) or 1
    rows = "".join(
        f'<tr><td class="rank">{i}</td><td class="when">{_when(s.started_at)}{_share(s, most)}</td>'
        f'<td><a class="id" href="/child/{escape(s.child_id)}">{escape(s.child_id)}</a></td>'
        f'<td class="age">{format_age(s.age_months)}</td><td class="{_hot(s)}">{s.flag_count()}</td></tr>'
        for i, s in enumerate(reversed(sessions), 1)
    )
    table = (
        f"<table><tr><th></th><th>Date</th><th>Child ID</th><th>Age</th><th class=\"n\">Flags</th></tr>{rows}</table>"
        if sessions else '<p class="empty">No sessions saved yet.</p>'
    )
    return _log_page("Past sessions", '<a href="/">Speak Up</a><span>/</span><b>Past sessions</b>', f"""
<div class="big">{len(sessions)}</div><div class="sub">sessions saved on this board</div>
<h2>Totals</h2>
<div class="totals">
  <div><span>Sessions</span><strong>{len(sessions)}</strong></div>
  <div><span>Children</span><strong>{len({s.child_id for s in sessions})}</strong></div>
  <div><span>Flags</span><strong>{sum(s.flag_count() for s in sessions)}</strong></div>
  <div><span>Sessions with a flag</span><strong>{sum(1 for s in sessions if s.flag_count())}</strong></div>
</div>
<h2>Sessions, newest first</h2>
{table}""")


def _chart(sessions: list[SavedSession]) -> str:
    width, height, top, base, left, right = 640, 240, 20, 196, 28, 600
    most = max(s.flag_count() for s in sessions) or 1
    step = (right - left) / max(len(sessions) - 1, 1)
    points = [(left + i * step, base - s.flag_count() / most * (base - top)) for i, s in enumerate(sessions)]
    line = f"M{points[0][0]:.1f},{points[0][1]:.1f}"
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        mid = (x0 + x1) / 2
        line += f" C{mid:.1f},{y0:.1f} {mid:.1f},{y1:.1f} {x1:.1f},{y1:.1f}"
    area = f"{line} L{points[-1][0]:.1f},{base} L{points[0][0]:.1f},{base} Z"
    ticks = "".join(
        f'<line class="grid-line" x1="{left}" y1="{base - t / most * (base - top):.1f}" x2="{right}" y2="{base - t / most * (base - top):.1f}"></line>'
        f'<text x="0" y="{base - t / most * (base - top) + 4:.1f}">{t}</text>'
        for t in sorted({0, (most + 1) // 2, most})
    )
    labels = ""
    for i, (s, (x, y)) in enumerate(zip(sessions, points)):
        anchor = "start" if i == 0 else "end" if i == len(points) - 1 else "middle"
        labels += (
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4"></circle>'
            f'<text x="{x:.1f}" y="{base + 20}" text-anchor="{anchor}">{_day(s.started_at)}</text>'
            f'<text x="{x:.1f}" y="{base + 36}" text-anchor="{anchor}">{format_age(s.age_months)}</text>'
        )
    return (f'<svg class="chart" viewBox="0 0 {width} {height}" role="img" aria-label="Flags per session">'
            f'{ticks}<path class="area" d="{area}"></path><path class="line" d="{line}"></path>{labels}</svg>')


def child_page(child_id: str, sessions: list[SavedSession]) -> str:
    first, last = sessions[0], sessions[-1]
    when = f"{_day(last.started_at)}, age {format_age(last.age_months)}"
    if len(sessions) == 1:
        sub = f"flags in the one session so far ({when})"
    else:
        trend = "down from" if last.flag_count() < first.flag_count() else "up from" if last.flag_count() > first.flag_count() else "the same as"
        sub = f"flags in the last session ({when}), {trend} {first.flag_count()} in the first"
    most = max(s.flag_count() for s in sessions) or 1
    rows = "".join(
        f'<tr class="session"><td class="rank">{i}</td><td class="when">{_when(s.started_at)}{_share(s, most)}</td>'
        f'<td class="age">{format_age(s.age_months)}</td><td class="{_hot(s)}">{s.flag_count()}</td>'
        f'<td><div class="chips">{_word_chips(s)}</div></td></tr>'
        for i, s in enumerate(sessions, 1)
    )
    crumbs = f'<a href="/">Speak Up</a><span>/</span><a href="/sessions">Past sessions</a><span>/</span><b>{escape(child_id)}</b>'
    return _log_page(child_id, crumbs, f"""
<div class="hero">
  <div><div class="big">{last.flag_count()}</div><div class="sub">{sub}</div></div>
  <div><h2>Flags per session</h2>{_chart(sessions)}</div>
</div>
<h2>Sessions, oldest first</h2>
<div class="chips legend"><span class="chip ok">correct</span><span class="chip normal">wrong, not flagged for age</span><span class="chip flag">flagged</span></div>
<table>
  <tr><th></th><th>Date</th><th>Age</th><th class="n">Flags</th><th>Words</th></tr>
  {rows}
</table>""")


# The child screen (/kid): what the child looks at on the board's monitor while the SLP works the session on
# another screen. It shows the picture, the word and whether the app is listening, and it praises every try the
# same way. It never shows a result, a flag or the child's ID: during a screening the child gets no right or wrong.
# The look is felt and cut paper: speakup/static/felt/ holds the pre-rendered layers, kid.js and kid.css.
def kid_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Speak Up</title>
<link rel="stylesheet" href="/felt/kid.css">
</head>
<body>
<div id="stage"></div>
<script src="/felt/kid.js"></script>
</body>
</html>
"""
