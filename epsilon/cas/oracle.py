"""The CAS oracle: closes goals the CAS can decide symbolically.

A goal closed here is `✓ Symbolically Verified`, never `✓ Formally Proven`.
The oracle returns `(True, "")` only when it is confident; every uncertain
case returns `(False, reason)` so the proof simply fails rather than being
wrongly accepted (the honesty rule, section 27).
"""

from __future__ import annotations

from typing import Callable

from ..kernel.env import Environment
from ..kernel.reduce import whnf
from ..kernel.term import Term, Const, App, Lam, Lit, unfold_app, instantiate
from .engine import (symbolic_eq, differentiate, limit_of, _numeric_type,
                     simplify)


def _unfold_defs(env: Environment, t: Term) -> Term:
    """Unfold definitional wrappers around a head so `sin` (defined as
    Real.sin) matches `Real.sin`."""
    head, args = unfold_app(t)
    if isinstance(head, Const):
        d = env.get(head.name)
        if d is not None and d.value is not None and d.reducible \
                and d.kind.value == "definition":
            from ..kernel.term import mk_app
            return _unfold_defs(env, mk_app(d.value, *args))
    return t


def cas_oracle(env: Environment, prop: Term) -> tuple[bool, str]:
    """Decide `prop` symbolically, or explain why it cannot."""
    p = whnf(env, prop, delta=False)
    head, args = unfold_app(p)
    if not isinstance(head, Const):
        return (False, "cas: goal is not an equational proposition")

    name = head.name

    # a = b
    if name == "Eq" and len(args) == 3:
        _, a, b = args
        if symbolic_eq(env, a, b):
            return (True, "")
        return (False, "cas: the two sides are not symbolically equal")

    # HasLimitAt f a L  /  limit f a = L
    if name == "HasLimitAt" and len(args) == 3:
        f, a, L = args
        return _check_limit(env, f, a, L)

    if name == "Eq" and len(args) == 3:  # handled above; kept for clarity
        pass

    # deriv f = g  (pointwise symbolic)
    if name == "Eq" and len(args) == 3:
        return (False, "cas: unsupported equality")

    return (False, f"cas: cannot decide a goal headed by '{name}'")


def _check_limit(env: Environment, f: Term, a: Term, L: Term) -> tuple[bool, str]:
    f = _as_lam(env, f)
    if f is None:
        return (False, "cas: limit target is not a function")
    try:
        val = limit_of(env, f, a)
    except Exception as e:  # noqa: BLE001
        return (False, f"cas: limit computation failed ({e})")
    if val is None:
        return (False, "cas: could not compute the limit symbolically")
    if symbolic_eq(env, val, L):
        return (True, "")
    return (False, "cas: the computed limit differs from the claimed value")


def _as_lam(env: Environment, f: Term):
    f = whnf(env, f, delta=True)
    if isinstance(f, Lam):
        return f
    return None
