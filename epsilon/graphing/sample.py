"""Uniform-grid sampling of kernel functions, and the shared plot spec.

Turns a unary kernel function `Term` into a `{"x": [...], "y": [...]}` point
series using the numeric engine (`epsilon.numeric.evaluator`), and turns one
`Session.plots` entry into the plot spec shared with the web IDE. Undefined
or unplottable points are recorded as `None` rather than guessed at - honest
gaps, never interpolated across or hidden (section 27: a numeric sample is
never dressed up as more than it is).
"""

from __future__ import annotations

import math
from typing import Optional

from ..kernel.env import Environment
from ..kernel.term import Term
from ..numeric.evaluator import EvalError, eval_function, eval_term

#: |y| beyond this is treated as unplottable (a pole / blow-up), not a value.
_BLOWUP = 1.0e6

#: Two adjacent *finite*, sub-blowup samples that flip sign while both sit
#: this close to the blow-up ceiling are almost certainly straddling a pole
#: the grid stepped over without landing on it (e.g. tan(x) wrapping through
#: pi/2) rather than an ordinary zero-crossing, whose neighboring samples
#: sit near zero, not near the ceiling - so the series is broken there too.
_WILD_JUMP_MAGNITUDE = 1.0e5

#: Default point count for plot_spec's per-series sampling.
_DEFAULT_N = 400


def sample_function(env: Environment, f: Term, lo: float, hi: float,
                    n: int = 400) -> dict:
    """Sample the unary function `f` on `n + 1` uniformly spaced points.

    Returns ``{"x": [...], "y": [...]}``. `y[i]` is `None` wherever `f` is
    undefined at `x[i]` (`EvalError` - division by zero, domain errors,
    an opaque subterm, ...), evaluates to a non-finite float, or exceeds the
    blow-up magnitude (1e6) - and also at the second point of any adjacent
    pair of finite samples that jump wildly across a huge, sign-flipped gap
    (an under-sampled pole the grid straddled without landing on it). This
    is heuristic gap detection for a legible plot, not a claim about exactly
    where `f` is mathematically defined.
    """
    if n < 1:
        raise ValueError("sample_function: n must be >= 1")
    if hi < lo:
        lo, hi = hi, lo
    xs: list[float] = []
    ys: list[Optional[float]] = []
    for i in range(n + 1):
        x = lo + (hi - lo) * i / n
        xs.append(x)
        try:
            y = eval_function(env, f, x)
        except EvalError:
            ys.append(None)
            continue
        if isinstance(y, bool) or not math.isfinite(y) or abs(y) > _BLOWUP:
            ys.append(None)
            continue
        ys.append(y)
    _mask_wild_jumps(ys)
    return {"x": xs, "y": ys}


def _mask_wild_jumps(ys: list[Optional[float]]) -> None:
    """Break the series (in place) between two finite samples that flip
    sign while both sit close to the blow-up ceiling - see module docstring
    on `_WILD_JUMP_MAGNITUDE` for why this targets poles, not ordinary
    zero-crossings."""
    for i in range(1, len(ys)):
        a, b = ys[i - 1], ys[i]
        if a is None or b is None:
            continue
        if a * b < 0 and min(abs(a), abs(b)) > _WILD_JUMP_MAGNITUDE:
            ys[i] = None


def plot_spec(env: Environment, plot_entry: dict,
             default_lo: float = -10.0, default_hi: float = 10.0) -> dict:
    """Turn one `Session.plots` entry into the shared plot-spec dict.

    `plot_entry` (see `epsilon.project.Session.plots`) carries `functions`
    (kernel `Term`s, each a unary Real -> Real function), `labels` (their
    display strings, same length/order as `functions`), `var` (the plotted
    variable's name), and `lo`/`hi` (kernel `Term`s or `None`). Bounds are
    evaluated with `eval_term` - so an expression like `2 * pi` works as a
    bound - and default to `default_lo`/`default_hi` when absent.

    Returns the plot spec shared with the web IDE::

        {"kind": "plot2d", "var": str, "lo": float, "hi": float,
         "series": [{"label": str, "x": [...], "y": [...]}, ...]}

    with one series per function, each sampled via `sample_function`.
    """
    var = plot_entry.get("var") or "x"
    lo_term = plot_entry.get("lo")
    hi_term = plot_entry.get("hi")
    lo = eval_term(env, lo_term) if lo_term is not None else default_lo
    hi = eval_term(env, hi_term) if hi_term is not None else default_hi
    functions = plot_entry.get("functions") or []
    labels = plot_entry.get("labels") or []
    series = []
    for i, fn in enumerate(functions):
        label = labels[i] if i < len(labels) else f"f{i + 1}"
        points = sample_function(env, fn, lo, hi, _DEFAULT_N)
        series.append({"label": label, "x": points["x"], "y": points["y"]})
    return {"kind": "plot2d", "var": var, "lo": lo, "hi": hi, "series": series}
