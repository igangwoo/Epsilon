"""Epsilon graphing: turn kernel functions into plottable point series and
render them as standalone SVG.

Everything here is built on the numeric engine (`epsilon.numeric`), so every
sample is an honest floating-point approximation - never presented as a
symbolic or proven fact (section 27). Points where a function is undefined,
non-finite, or blows up are masked as ``None`` rather than guessed at or
silently interpolated across.

Public interface (see ``docs/CONTRACTS.md``):
    sample_function(env, f, lo, hi, n=400) -> {"x": [...], "y": [...]}
    plot_spec(env, plot_entry, default_lo=-10.0, default_hi=10.0) -> dict
    render_svg(spec, width=800, height=500, dark=False) -> str
"""

from .sample import sample_function, plot_spec
from .svg import render_svg

__all__ = ["sample_function", "plot_spec", "render_svg"]
