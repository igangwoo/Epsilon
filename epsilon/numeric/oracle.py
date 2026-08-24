"""The numeric verification oracle.

Decides a small class of propositions by floating-point sampling. A `True`
answer here is *numerical evidence only*: the tactic layer records it under
the ``Epsilon.trustedNumeric`` axiom so the theorem is labeled
"≈ Numerically Verified", never "Formally Proven" (section 27).

Honest failures: whenever the proposition is outside the supported shapes,
a side cannot be evaluated, or the margin is inside floating-point
tolerance, the oracle answers ``(False, reason)`` instead of guessing.
"""

from __future__ import annotations

import math

from ..kernel.env import Environment, KernelError
from ..kernel.reduce import whnf
from ..kernel.term import Term, Const, Lam, Pi, unfold_app
from .evaluator import EvalError, eval_term, eval_function

#: Relative comparison tolerance: |a - b| <= TOL * max(1, |a|, |b|).
TOL = 1e-9

_NUMERIC_TYPES = ("Nat", "Int", "Rat", "Real")
_SAMPLES = 32          # equality-of-functions sample points over [-3, 3]
_MIN_POINTS = 8        # minimum evaluable points for a function verdict
_LIMIT_KS = range(3, 8)  # HasLimitAt probes at a ± 10^-k


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= TOL * max(1.0, abs(a), abs(b))


def numeric_oracle(env: Environment, prop: Term) -> tuple[bool, str]:
    """Numerically check `prop`. Returns ``(ok, reason)``.

    Supported shapes: ``Eq`` of scalars, ``Eq`` of unary real functions
    (sampled at 32 points on [-3, 3]), ``<T>.le`` / ``<T>.lt``, and
    ``HasLimitAt(f, a, L)`` (shrinking two-sided deltas). Everything else
    is honestly rejected.
    """
    try:
        verdict = _dispatch(env, prop)
        if verdict is None:
            # one head-normalization step may expose a supported shape
            # (e.g. a definition abbreviating an equality)
            try:
                reduced = whnf(env, prop)
            except KernelError:
                reduced = prop
            if reduced != prop:
                verdict = _dispatch(env, reduced)
        if verdict is None:
            head, _ = unfold_app(prop)
            return (False, f"numeric oracle cannot decide propositions with "
                           f"head '{head!r}'")
        return verdict
    except EvalError as e:
        return (False, f"numeric evaluation failed: {e}")


# ---------------------------------------------------------------------------

def _dispatch(env: Environment, prop: Term) -> tuple[bool, str] | None:
    head, args = unfold_app(prop)
    if not isinstance(head, Const):
        return None
    if head.name == "Eq" and len(args) == 3:
        return _check_eq(env, args[0], args[1], args[2])
    if head.name == "HasLimitAt" and len(args) == 3:
        return _check_limit(env, args[0], args[1], args[2])
    parts = head.name.rsplit(".", 1)
    if (len(parts) == 2 and parts[0] in _NUMERIC_TYPES
            and parts[1] in ("le", "lt") and len(args) == 2):
        return _check_cmp(env, parts[1], args[0], args[1])
    return None


def _is_function_eq(env: Environment, ty: Term, lhs: Term, rhs: Term) -> bool:
    if isinstance(lhs, Lam) or isinstance(rhs, Lam):
        return True
    try:
        return isinstance(whnf(env, ty), Pi)
    except KernelError:
        return False


def _check_eq(env: Environment, ty: Term, lhs: Term,
              rhs: Term) -> tuple[bool, str]:
    if _is_function_eq(env, ty, lhs, rhs):
        return _check_fun_eq(env, lhs, rhs)
    try:
        a = eval_term(env, lhs)
        b = eval_term(env, rhs)
    except EvalError as e:
        return (False, f"cannot evaluate equation side numerically: {e}")
    if isinstance(a, bool) or isinstance(b, bool):
        if bool(a) == bool(b):
            return (True, f"both sides evaluate to {a!r}")
        return (False, f"sides evaluate to {a!r} vs {b!r}")
    if _close(a, b):
        return (True, f"|{a!r} - {b!r}| within tolerance {TOL}")
    return (False, f"sides differ numerically: {a!r} vs {b!r} "
                   f"(|Δ| = {abs(a - b):.3g} > tol)")


def _check_fun_eq(env: Environment, lhs: Term,
                  rhs: Term) -> tuple[bool, str]:
    evaluated = 0
    for i in range(_SAMPLES):
        x = -3.0 + 6.0 * i / (_SAMPLES - 1)
        try:
            a = eval_function(env, lhs, x)
            b = eval_function(env, rhs, x)
        except EvalError:
            continue      # undefined point (pole/domain edge): skip honestly
        evaluated += 1
        if not _close(a, b):
            return (False, f"functions differ at x = {x:.6g}: "
                           f"{a!r} vs {b!r}")
    if evaluated < _MIN_POINTS:
        return (False, f"only {evaluated}/{_SAMPLES} sample points were "
                       f"evaluable (need >= {_MIN_POINTS}) - cannot verify")
    return (True, f"functions agree at {evaluated} sample points on [-3, 3] "
                  f"(tol {TOL})")


def _check_cmp(env: Environment, op: str, lhs: Term,
               rhs: Term) -> tuple[bool, str]:
    try:
        a = eval_term(env, lhs)
        b = eval_term(env, rhs)
    except EvalError as e:
        return (False, f"cannot evaluate comparison side numerically: {e}")
    margin = TOL * max(1.0, abs(a), abs(b))
    if op == "le":
        if a <= b + margin:
            return (True, f"{a!r} <= {b!r} (tol {TOL})")
        return (False, f"{a!r} > {b!r} numerically")
    # strict <: demand a margin, refuse to certify ties within tolerance
    if a < b - margin:
        return (True, f"{a!r} < {b!r} with margin > {TOL}")
    if a < b:
        return (False, f"{a!r} < {b!r} only within floating-point tolerance "
                       f"- cannot honestly certify a strict inequality")
    return (False, f"{a!r} >= {b!r} numerically")


def _check_limit(env: Environment, f: Term, a: Term,
                 L: Term) -> tuple[bool, str]:
    try:
        a0 = eval_term(env, a)
        L0 = eval_term(env, L)
    except EvalError as e:
        return (False, f"cannot evaluate limit point / limit value: {e}")
    scale = max(1.0, abs(L0))
    errs: list[float] = []
    for k in _LIMIT_KS:
        d = 10.0 ** (-k)
        pts: list[float] = []
        for x in (a0 + d, a0 - d):
            try:
                pts.append(eval_function(env, f, x))
            except EvalError:
                continue
        if pts:
            errs.append(max(abs(v - L0) for v in pts))
    if len(errs) < 3:
        return (False, "function is not evaluable near the limit point "
                       "at enough delta scales - cannot verify")
    if not math.isfinite(errs[-1]):
        return (False, "function values diverge near the limit point")
    if errs[-1] <= 1e-6 * scale and errs[-1] <= errs[0] + TOL * scale:
        return (True, f"|f(a ± δ) - L| shrinks to {errs[-1]:.3g} as "
                      f"δ -> 10^-{_LIMIT_KS[-1]}")
    return (False, f"no numeric convergence to {L0!r}: errors "
                   f"{[f'{e:.3g}' for e in errs]} for δ = 10^-3..10^-7")
