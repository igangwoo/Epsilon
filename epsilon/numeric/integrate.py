"""Numeric definite integration: adaptive Simpson's rule.

Approximate quadrature. If the integrand is undefined anywhere the rule
needs to sample, this raises :class:`EvalError` with the offending point -
it never invents a value for an undefined integrand (honesty over
convenience).
"""

from __future__ import annotations

from ..kernel.env import Environment
from ..kernel.term import Term
from .evaluator import EvalError, eval_function

_MAX_DEPTH = 24
_TOL = 1e-10


def integrate_numeric(env: Environment, f: Term, a: float, b: float,
                      n: int = 1000) -> float:
    """Approximate ``∫_a^b f(x) dx`` by adaptive Simpson quadrature.

    `f` is a unary function Term. `n` is a work hint: the interval is first
    cut into ``~n/100`` slices, each refined adaptively (recursion depth
    capped at 24). Raises :class:`EvalError` naming the sample point if the
    integrand is undefined somewhere in ``[a, b]``.
    """
    a, b = float(a), float(b)
    if a == b:
        return 0.0

    def g(x: float) -> float:
        try:
            return eval_function(env, f, x)
        except EvalError as e:
            raise EvalError(
                f"integrand is undefined at x = {x!r} inside "
                f"[{min(a, b)}, {max(a, b)}]: {e}") from None

    slices = max(2, min(64, int(n) // 100 if n else 2))
    width = (b - a) / slices
    total = 0.0
    for i in range(slices):
        x0 = a + i * width
        x1 = a + (i + 1) * width if i + 1 < slices else b
        m = 0.5 * (x0 + x1)
        f0, fm, f1 = g(x0), g(m), g(x1)
        whole = _simpson(x0, x1, f0, fm, f1)
        total += _adaptive(g, x0, x1, f0, fm, f1, whole,
                           _TOL / slices, _MAX_DEPTH)
    return total


def _simpson(a: float, b: float, fa: float, fm: float, fb: float) -> float:
    return (b - a) / 6.0 * (fa + 4.0 * fm + fb)


def _adaptive(g, a: float, b: float, fa: float, fm: float, fb: float,
              whole: float, tol: float, depth: int) -> float:
    m = 0.5 * (a + b)
    lm, rm = 0.5 * (a + m), 0.5 * (m + b)
    flm, frm = g(lm), g(rm)
    left = _simpson(a, m, fa, flm, fm)
    right = _simpson(m, b, fm, frm, fb)
    delta = left + right - whole
    if depth <= 0 or abs(delta) <= 15.0 * tol:
        return left + right + delta / 15.0   # Richardson correction
    return (_adaptive(g, a, m, fa, flm, fm, left, tol / 2.0, depth - 1)
            + _adaptive(g, m, b, fm, frm, fb, right, tol / 2.0, depth - 1))
