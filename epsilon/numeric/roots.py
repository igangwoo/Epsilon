"""Root finding: bracket scan + bisection, polished by Newton's method.

Heuristic numerics (assumes the function is continuous on the bracket);
results are floats, never presented as exact. Undefined sample points
(poles etc.) are skipped honestly during the scan.
"""

from __future__ import annotations

from typing import Optional

from ..kernel.env import Environment
from ..kernel.term import Term
from .evaluator import EvalError, eval_function

_SCAN_POINTS = 256
_MAX_BISECT = 200
_MAX_NEWTON = 25


def find_root(env: Environment, f: Term, lo: float, hi: float,
              tol: float = 1e-12) -> Optional[float]:
    """Find one root of `f` (a unary function Term) in ``[lo, hi]``.

    Scans for a sign change, bisects it down to `tol`, then polishes with
    Newton iterations using a numeric derivative. Returns ``None`` when no
    sign change is found among the evaluable sample points.
    """
    if hi < lo:
        lo, hi = hi, lo

    def g(x: float) -> float:
        return eval_function(env, f, x)

    # -- bracket scan ------------------------------------------------------
    samples: list[tuple[float, float]] = []
    n = _SCAN_POINTS
    for i in range(n + 1):
        x = lo + (hi - lo) * i / n if n else lo
        try:
            fx = g(x)
        except EvalError:
            continue
        if fx == 0.0:
            return x
        samples.append((x, fx))

    bracket: Optional[tuple[float, float, float, float]] = None
    for (x0, f0), (x1, f1) in zip(samples, samples[1:]):
        if f0 * f1 < 0:
            bracket = (x0, f0, x1, f1)
            break
    if bracket is None:
        return None

    # -- bisection ---------------------------------------------------------
    a, fa, b, fb = bracket
    for _ in range(_MAX_BISECT):
        m = 0.5 * (a + b)
        if m == a or m == b or (b - a) <= tol * max(1.0, abs(m)):
            break
        try:
            fm = g(m)
        except EvalError:
            return None      # a pole inside the bracket: no honest answer
        if fm == 0.0:
            return m
        if fa * fm < 0:
            b, fb = m, fm
        else:
            a, fa = m, fm
    root = 0.5 * (a + b)

    # -- Newton polish (numeric central-difference derivative) -------------
    try:
        best, fbest = root, abs(g(root))
    except EvalError:
        return root
    x = root
    for _ in range(_MAX_NEWTON):
        h = 1e-7 * max(1.0, abs(x))
        try:
            fx = g(x)
            d = (g(x + h) - g(x - h)) / (2.0 * h)
        except EvalError:
            break
        if d == 0.0 or not (lo - tol <= x <= hi + tol):
            break
        if abs(fx) < fbest:
            best, fbest = x, abs(fx)
        step = fx / d
        x_new = x - step
        if abs(step) <= tol * max(1.0, abs(x)):
            x = x_new
            try:
                if abs(g(x)) <= fbest:
                    best, fbest = x, abs(g(x))
            except EvalError:
                pass
            break
        x = x_new
    return best
