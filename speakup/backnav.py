"""The one Back control used across the SLP pages (analysis page, full view, sound book), so every place that
returns somewhere looks and behaves the same: a round navy arrow with a plain label, on the page itself, above the
content it leaves. html() gives the link, CSS its look (include CSS once per page)."""
from html import escape

CSS = """
  .backnav-bar { margin: 0 0 12px; }
  .backnav { display: inline-flex; align-items: center; gap: 10px; padding: 4px 16px 4px 4px; border-radius: 999px;
             border: 1px solid #d9dfe7; background: #fff; color: #16202c; font: 600 14px/1.2 system-ui, -apple-system,
             "Segoe UI", Roboto, sans-serif; text-decoration: none; cursor: pointer; white-space: nowrap;
             box-shadow: 0 1px 2px rgba(20,32,44,.06); transition: border-color .15s, background .15s; }
  .backnav .ic { width: 30px; height: 30px; border-radius: 50%; background: #1d4f91; display: grid; place-items: center;
                 flex: none; transition: transform .15s; }
  .backnav .ic svg { display: block; }
  .backnav:hover { border-color: #1d4f91; background: #f0f5fb; color: #16202c; }
  .backnav:hover .ic { transform: translateX(-2px); }
  .backnav:focus-visible { outline: 3px solid #f2b84b; outline-offset: 2px; }
  @media (prefers-reduced-motion: reduce) { .backnav, .backnav .ic { transition: none; } }
"""

ARROW = ('<svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="#fff" '
         'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 8H3.5M7.5 3.5 3 8l4.5 4.5"/></svg>')


def html(href: str, label: str, **attrs: str) -> str:
    """A Back link to href with this label. attrs become HTML attributes (id, data-*), underscores as dashes."""
    extra = "".join(f' {k.replace("_", "-")}="{escape(v)}"' for k, v in attrs.items())
    return (f'<a class="backnav" href="{escape(href)}"{extra}><span class="ic">{ARROW}</span>'
            f'<span>{escape(label)}</span></a>')
