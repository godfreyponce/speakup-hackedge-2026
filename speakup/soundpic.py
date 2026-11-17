"""Draws an Analysis as an SVG for the SLP: the spectrogram in Praat's style (dark = energy, white = quiet),
the formant tracks on top (F1 blue, F2 green, F3 red), a pitch strip under it, and a dashed line where
F3 comes closest to F2. The spectrogram is a grayscale PNG built here with zlib, so nothing needs a
plotting library on the board."""

import base64
import struct
import zlib
from html import escape

import numpy as np

from speakup.acoustics import F0_MAX, F0_MIN, TOP_HZ, Analysis

DYNAMIC_DB = 50.0  # show the top 50 dB of the word's energy, like Praat's default
COLORS = ("#1f77b4", "#2ca02c", "#d62728")  # F1, F2, F3
PITCH_COLOR = "#e07b00"


def png_gray(pixels: np.ndarray) -> bytes:
    """8-bit grayscale PNG from a 2-D uint8 array (first row = top of the image)."""
    h, w = pixels.shape
    raw = b"".join(b"\x00" + pixels[y].tobytes() for y in range(h))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _spectrogram_png(a: Analysis, top_hz: float | None = None) -> bytes:
    """top_hz: crop to this frequency (the compact picture stops at TOP_HZ); None keeps every row."""
    db = a.spec_db
    if top_hz is not None and top_hz < a.spec_top and len(db):
        db = db[:int(round(len(db) * top_hz / a.spec_top))]
    top = db.max() if db.size else 0.0
    level = np.clip((db - (top - DYNAMIC_DB)) / DYNAMIC_DB, 0, 1)
    pixels = (255 * (1 - level)).astype(np.uint8)[::-1]  # high frequencies at the top
    return png_gray(np.ascontiguousarray(pixels))


def svg(a: Analysis, width: int = 760, compact: bool = False, title: str = "") -> str:
    left, right, top_pad = 46, 10, (22 if title else 8)
    spec_h = 150 if compact else 260
    pitch_h = 0 if compact else 70
    gap_between = 0 if compact else 26
    bottom = 22
    height = top_pad + spec_h + gap_between + pitch_h + bottom
    plot_w = width - left - right
    dur = max(a.spec_seconds, 1e-6)

    def x_at(t: float) -> float:
        return left + t / dur * plot_w

    def y_hz(f: float) -> float:
        return top_pad + spec_h * (1 - f / TOP_HZ)

    img = base64.b64encode(_spectrogram_png(a, TOP_HZ)).decode()
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" class="soundpic" '
             f'role="img" aria-label="Spectrogram with formant tracks">',
             f'<rect x="0" y="0" width="{width}" height="{height}" fill="#fff"/>']
    if title:
        parts.append(f'<text x="{left}" y="15" class="t">{escape(title)}</text>')
    parts.append(f'<image x="{left}" y="{top_pad}" width="{plot_w}" height="{spec_h}" preserveAspectRatio="none" '
                 f'href="data:image/png;base64,{img}"/>')
    parts.append(f'<rect x="{left}" y="{top_pad}" width="{plot_w}" height="{spec_h}" fill="none" stroke="#999"/>')
    for khz in range(0, int(TOP_HZ / 1000) + 1, 1 if not compact else 2):
        y = y_hz(khz * 1000)
        parts.append(f'<line x1="{left - 4}" y1="{y:.1f}" x2="{left}" y2="{y:.1f}" stroke="#999"/>'
                     f'<text x="{left - 6}" y="{y + 3:.1f}" class="ax" text-anchor="end">{khz}k</text>')
    # Formant tracks as dots, the way Praat draws them.
    for i, color in enumerate(COLORS):
        for t, f in zip(a.times, a.formants[:, i]):
            if not np.isnan(f) and 0 < f < TOP_HZ:
                parts.append(f'<circle cx="{x_at(t):.1f}" cy="{y_hz(f):.1f}" r="{1.6 if compact else 2.2}" fill="{color}"/>')
    if a.window is not None:
        x0, x1 = x_at(a.window[0]), x_at(a.window[1])
        parts.append(f'<rect x="{x0:.1f}" y="{top_pad}" width="{x1 - x0:.1f}" height="4" fill="#1f4e79" opacity=".55"/>')
    if a.gap_time is not None:
        x = x_at(a.gap_time)
        parts.append(f'<line x1="{x:.1f}" y1="{top_pad}" x2="{x:.1f}" y2="{top_pad + spec_h}" stroke="#111" '
                     f'stroke-dasharray="4 3"/>')
        if a.at_gap:
            y2, y3 = y_hz(a.at_gap[1]), y_hz(a.at_gap[2])
            parts.append(f'<line x1="{x + 5:.1f}" y1="{y3:.1f}" x2="{x + 5:.1f}" y2="{y2:.1f}" stroke="#111" stroke-width="2"/>')
        # The value sits in the top-left corner, on a white tag, so it never covers the bands it measures.
        parts.append(f'<rect x="{left + 4}" y="{top_pad + 6}" width="138" height="20" rx="4" fill="#fff" opacity=".9"/>'
                     f'<text x="{left + 10}" y="{top_pad + 20}" class="lab">F3-F2 gap {a.gap_min:,.0f} Hz</text>')
    base = top_pad + spec_h
    ticks = [t / 10 for t in range(0, int(dur * 10) + 1)]
    for t in ticks:
        x = x_at(t)
        parts.append(f'<line x1="{x:.1f}" y1="{base}" x2="{x:.1f}" y2="{base + 4}" stroke="#999"/>')
    if not compact:
        p_top = base + gap_between
        parts.append(f'<rect x="{left}" y="{p_top}" width="{plot_w}" height="{pitch_h}" fill="#fcfcfa" stroke="#ddd"/>')
        parts.append(f'<text x="{left - 6}" y="{p_top + 10}" class="ax" text-anchor="end">{F0_MAX:.0f}</text>'
                     f'<text x="{left - 6}" y="{p_top + pitch_h}" class="ax" text-anchor="end">{F0_MIN:.0f}</text>'
                     f'<text x="{left + 4}" y="{p_top + 11}" class="ax">pitch (F0), Hz</text>')
        pts = [(x_at(t), p_top + pitch_h * (1 - (f - F0_MIN) / (F0_MAX - F0_MIN)))
               for t, f in zip(a.times, a.f0) if not np.isnan(f)]
        for x, y in pts:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.8" fill="{PITCH_COLOR}"/>')
        base = p_top + pitch_h
    for t in ticks:
        parts.append(f'<text x="{x_at(t):.1f}" y="{base + 16}" class="ax" text-anchor="middle">{t:.1f} s</text>')
    parts.append("</svg>")
    return "".join(parts)


LEGEND = ('<div class="legend"><span><i style="background:#1f77b4"></i>F1</span>'
          '<span><i style="background:#2ca02c"></i>F2</span><span><i style="background:#d62728"></i>F3</span>'
          '<span><i style="background:#e07b00"></i>pitch</span><span><i style="background:#1f4e79"></i>where the r '
          'should be</span><span>dark = more energy</span></div>')
