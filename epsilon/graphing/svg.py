"""Render a plot spec (see `epsilon.graphing.sample.plot_spec`) to a
standalone, self-contained SVG string.

No external assets, stylesheets, or fonts - only inline attributes on plain
SVG elements - so the output is safe to embed directly in the web IDE or
write to a `.svg` file on its own. Colors are picked from a fixed,
colorblind-checked categorical palette with separate light/dark chrome, so
the same plot stays legible whichever `dark` flag it was rendered with.
"""

from __future__ import annotations

import math
from typing import Optional
from xml.sax.saxutils import escape

# ---------------------------------------------------------------------------
# Palette (validated categorical order + light/dark chart chrome)
# ---------------------------------------------------------------------------

_LIGHT = {
    "surface": "#fcfcfb",
    "text_primary": "#0b0b0b",
    "text_secondary": "#52514e",
    "text_muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "border": "rgba(11,11,11,0.10)",
}

_DARK = {
    "surface": "#1a1a19",
    "text_primary": "#ffffff",
    "text_secondary": "#c3c2b7",
    "text_muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "border": "rgba(255,255,255,0.10)",
}

# Fixed categorical order (blue, orange, aqua, yellow, magenta, green,
# violet, red) - cycled only if a plot has more than 8 series.
_SERIES_LIGHT = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100",
                 "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
_SERIES_DARK = ["#3987e5", "#d95926", "#199e70", "#c98500",
                "#d55181", "#008300", "#9085e9", "#e66767"]


def render_svg(spec: dict, width: int = 800, height: int = 500,
               dark: bool = False) -> str:
    """Render `spec` (a `plot_spec` output) to a standalone SVG document.

    Draws a background, a light grid with numeric tick labels, bold axes
    through zero when zero is within range, one `<polyline>` per series
    (broken into separate polylines at `None` gaps, isolated single points
    drawn as dots), and a small legend. Pure, self-contained markup - no
    external assets.
    """
    theme = _DARK if dark else _LIGHT
    series_colors = _SERIES_DARK if dark else _SERIES_LIGHT

    var = spec.get("var") or "x"
    series = spec.get("series") or []

    xlo, xhi = _axis_range(spec.get("lo"), spec.get("hi"), series, "x")
    ylo, yhi = _axis_range(None, None, series, "y")

    margin_left, margin_right = 54.0, 24.0
    margin_top, margin_bottom = 20.0, 40.0
    plot_x0, plot_y0 = margin_left, margin_top
    plot_x1 = max(float(width) - margin_right, plot_x0 + 10.0)
    plot_y1 = max(float(height) - margin_bottom, plot_y0 + 10.0)
    plot_w, plot_h = plot_x1 - plot_x0, plot_y1 - plot_y0

    def x_to_px(x: float) -> float:
        return plot_x0 + (x - xlo) / (xhi - xlo) * plot_w

    def y_to_px(y: float) -> float:
        return plot_y1 - (y - ylo) / (yhi - ylo) * plot_h

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height}" viewBox="0 0 {width} {height}" '
        f'font-family="ui-sans-serif, system-ui, -apple-system, sans-serif">'
    )
    parts.append(f'<rect x="0" y="0" width="{width}" height="{height}" '
                 f'fill="{theme["surface"]}"/>')

    clip_id = "epsilon-plot-clip"
    parts.append(f'<clipPath id="{clip_id}"><rect x="{plot_x0:.2f}" '
                 f'y="{plot_y0:.2f}" width="{plot_w:.2f}" '
                 f'height="{plot_h:.2f}"/></clipPath>')

    # -- grid + tick labels --------------------------------------------
    for tx in _nice_ticks(xlo, xhi):
        px = x_to_px(tx)
        parts.append(f'<line x1="{px:.2f}" y1="{plot_y0:.2f}" '
                     f'x2="{px:.2f}" y2="{plot_y1:.2f}" '
                     f'stroke="{theme["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{px:.2f}" y="{plot_y1 + 16:.2f}" '
                     f'text-anchor="middle" font-size="11" '
                     f'fill="{theme["text_muted"]}">{_fmt_num(tx)}</text>')
    for ty in _nice_ticks(ylo, yhi):
        py = y_to_px(ty)
        parts.append(f'<line x1="{plot_x0:.2f}" y1="{py:.2f}" '
                     f'x2="{plot_x1:.2f}" y2="{py:.2f}" '
                     f'stroke="{theme["grid"]}" stroke-width="1"/>')
        parts.append(f'<text x="{plot_x0 - 8:.2f}" y="{py + 3.5:.2f}" '
                     f'text-anchor="end" font-size="11" '
                     f'fill="{theme["text_muted"]}">{_fmt_num(ty)}</text>')

    parts.append(f'<rect x="{plot_x0:.2f}" y="{plot_y0:.2f}" '
                 f'width="{plot_w:.2f}" height="{plot_h:.2f}" fill="none" '
                 f'stroke="{theme["border"]}" stroke-width="1"/>')

    # -- axes through zero, when in range --------------------------------
    if xlo <= 0.0 <= xhi:
        px = x_to_px(0.0)
        parts.append(f'<line x1="{px:.2f}" y1="{plot_y0:.2f}" '
                     f'x2="{px:.2f}" y2="{plot_y1:.2f}" '
                     f'stroke="{theme["axis"]}" stroke-width="1.5"/>')
    if ylo <= 0.0 <= yhi:
        py = y_to_px(0.0)
        parts.append(f'<line x1="{plot_x0:.2f}" y1="{py:.2f}" '
                     f'x2="{plot_x1:.2f}" y2="{py:.2f}" '
                     f'stroke="{theme["axis"]}" stroke-width="1.5"/>')

    # -- axis variable labels --------------------------------------------
    parts.append(f'<text x="{plot_x1:.2f}" y="{plot_y1 + 34:.2f}" '
                 f'text-anchor="end" font-size="12" '
                 f'fill="{theme["text_secondary"]}">{escape(str(var))}</text>')
    parts.append(f'<text x="{plot_x0:.2f}" y="{plot_y0 - 6:.2f}" '
                 f'text-anchor="start" font-size="12" '
                 f'fill="{theme["text_secondary"]}">y</text>')

    # -- series: one polyline per contiguous finite run ------------------
    legend_entries: list[tuple[str, str]] = []
    parts.append(f'<g clip-path="url(#{clip_id})">')
    for i, s in enumerate(series):
        color = series_colors[i % len(series_colors)]
        label = str(s.get("label") or f"f{i + 1}")
        legend_entries.append((label, color))
        xs = s.get("x") or []
        ys = s.get("y") or []
        run: list[tuple[float, float]] = []
        for x, y in zip(xs, ys):
            if y is None:
                _emit_run(parts, run, color, theme["surface"])
                run = []
                continue
            run.append((x_to_px(x), y_to_px(y)))
        _emit_run(parts, run, color, theme["surface"])
    parts.append("</g>")

    # -- small legend, top-right -----------------------------------------
    if legend_entries:
        parts.append(_legend_svg(legend_entries, plot_x0, plot_y0, plot_x1,
                                 theme))

    parts.append("</svg>")
    return "".join(parts)


def _emit_run(parts: list[str], run: list[tuple[float, float]],
              color: str, surface: str) -> None:
    """Append one series' contiguous pixel-space run as a `<polyline>`
    (or a single dot when the run is one isolated point)."""
    if len(run) >= 2:
        pts = " ".join(f"{px:.2f},{py:.2f}" for px, py in run)
        parts.append(f'<polyline points="{pts}" fill="none" '
                     f'stroke="{color}" stroke-width="2" '
                     f'stroke-linecap="round" stroke-linejoin="round"/>')
    elif len(run) == 1:
        px, py = run[0]
        parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="3" '
                     f'fill="{color}" stroke="{surface}" '
                     f'stroke-width="1.5"/>')


def _legend_svg(entries: list[tuple[str, str]], plot_x0: float,
                plot_y0: float, plot_x1: float, theme: dict) -> str:
    row_h, pad = 16.0, 8.0
    text_w = max(len(lbl) for lbl, _ in entries) * 6.2 + 22.0
    box_w = max(60.0, text_w)
    box_h = pad * 2 + row_h * len(entries)
    box_x = max(plot_x0 + 4.0, plot_x1 - box_w - 8.0)
    box_y = plot_y0 + 8.0
    out = [f'<rect x="{box_x:.2f}" y="{box_y:.2f}" width="{box_w:.2f}" '
          f'height="{box_h:.2f}" rx="4" fill="{theme["surface"]}" '
          f'fill-opacity="0.92" stroke="{theme["border"]}" '
          f'stroke-width="1"/>']
    for j, (lbl, color) in enumerate(entries):
        ly = box_y + pad + j * row_h + row_h * 0.5
        out.append(f'<rect x="{box_x + pad:.2f}" y="{ly - 5:.2f}" '
                   f'width="10" height="10" rx="2" fill="{color}"/>')
        out.append(f'<text x="{box_x + pad + 16:.2f}" y="{ly + 4:.2f}" '
                   f'font-size="11" fill="{theme["text_secondary"]}">'
                   f'{escape(lbl)}</text>')
    return "".join(out)


# ---------------------------------------------------------------------------
# Range / tick helpers
# ---------------------------------------------------------------------------

def _axis_range(lo: Optional[float], hi: Optional[float],
                series: list[dict], axis: str) -> tuple[float, float]:
    """The [lo, hi] range for `axis` ('x' uses the spec's own lo/hi when
    given; 'y' is always inferred from the finite sample values), padded by
    10% so curves never touch the plot-area edge, with a safe fallback
    when there is no finite data to look at."""
    if axis == "x" and lo is not None and hi is not None and hi > lo:
        span = hi - lo
        return lo - span * 0.05, hi + span * 0.05
    values: list[float] = []
    for s in series:
        for v in (s.get(axis) or []):
            if v is not None and math.isfinite(v):
                values.append(v)
    if not values:
        return (-1.0, 1.0) if axis == "y" else (-10.0, 10.0)
    vlo, vhi = min(values), max(values)
    if vhi - vlo < 1e-9:
        pad = max(abs(vlo), 1.0)
        return vlo - pad, vhi + pad
    pad = (vhi - vlo) * 0.1
    return vlo - pad, vhi + pad


def _nice_ticks(lo: float, hi: float, target: int = 6) -> list[float]:
    """A handful of evenly spaced 'nice' (1/2/5 x 10^k) tick values
    covering `[lo, hi]`."""
    if not (math.isfinite(lo) and math.isfinite(hi)) or hi <= lo:
        return []
    span = hi - lo
    raw_step = span / max(target, 1)
    mag = 10.0 ** math.floor(math.log10(raw_step))
    step = mag
    for m in (1.0, 2.0, 5.0, 10.0):
        step = m * mag
        if step >= raw_step:
            break
    start = math.ceil(lo / step) * step
    ticks: list[float] = []
    v = start
    limit = target * 4 + 10
    while v <= hi + step * 1e-6 and len(ticks) < limit:
        ticks.append(0.0 if abs(v) < step * 1e-9 else round(v / step) * step)
        v += step
    return ticks


def _fmt_num(v: float) -> str:
    """Compact display form of a tick value: plain integers stay bare,
    everything else is trimmed to a handful of significant digits."""
    if abs(v) < 1e-9:
        v = 0.0
    if abs(v - round(v)) < 1e-9 * max(1.0, abs(v)):
        return str(int(round(v)))
    return f"{v:.4g}"
