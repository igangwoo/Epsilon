"""ODE initial-value problems: classic fourth-order Runge-Kutta.

Solves ``dy/dx = f2(x, y)`` from ``(x0, y0)`` to ``x1`` with a fixed step
count. Purely numeric; the trajectory is an approximation, never a proof.
"""

from __future__ import annotations

from ..kernel.env import Environment
from ..kernel.term import Term, Lam, mk_app, instantiate
from .evaluator import EvalError, eval_term, _lit_of


def _eval2(env: Environment, f2: Term, x: float, y: float) -> float:
    """Apply the curried 2-argument function Term `f2` to floats (x, y)."""
    if isinstance(f2, Lam):
        inner = instantiate(f2.body, _lit_of(float(x)))
        if isinstance(inner, Lam):
            return eval_term(env, instantiate(inner.body, _lit_of(float(y))))
        return eval_term(env, mk_app(inner, _lit_of(float(y))))
    return eval_term(env, mk_app(f2, _lit_of(float(x)), _lit_of(float(y))))


def solve_ode(env: Environment, f2: Term, x0: float, y0: float, x1: float,
              steps: int) -> list[tuple[float, float]]:
    """Integrate ``dy/dx = f2(x, y)`` by classic RK4.

    `f2` is a curried Term of type ``Real -> Real -> Real``. Returns the
    full trajectory ``[(x0, y0), ..., (x1, y_n)]`` with ``steps + 1``
    points. Raises ValueError for ``steps < 1`` and :class:`EvalError`
    (with the failing point) when the right-hand side is undefined.
    """
    if steps < 1:
        raise ValueError(f"solve_ode: steps must be >= 1 (got {steps})")
    x, y = float(x0), float(y0)
    h = (float(x1) - x) / steps
    out: list[tuple[float, float]] = [(x, y)]
    for i in range(steps):
        try:
            k1 = _eval2(env, f2, x, y)
            k2 = _eval2(env, f2, x + h / 2.0, y + h * k1 / 2.0)
            k3 = _eval2(env, f2, x + h / 2.0, y + h * k2 / 2.0)
            k4 = _eval2(env, f2, x + h, y + h * k3)
        except EvalError as e:
            raise EvalError(
                f"ODE right-hand side undefined near (x={x!r}, y={y!r}): {e}"
            ) from None
        y = y + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)
        x = float(x0) + (i + 1) * h if i + 1 < steps else float(x1)
        out.append((x, y))
    return out
