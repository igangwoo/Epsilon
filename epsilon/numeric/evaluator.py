"""Floating-point interpreter over kernel Terms.

A small recursive evaluator: literals become floats, ``Const`` heads are
dispatched through tables of stdlib-``math`` implementations, definitions
are unfolded from the environment, and lambdas become Python closures.

DELIBERATE DIVERGENCE FROM THE KERNEL - division by zero:
    the kernel's definitional arithmetic uses the total-function convention
    (``x / 0 = 0``, ``inv 0 = 0``; see ``kernel/reduce.py``), which is sound
    for stating field axioms with ``x ≠ 0`` hypotheses. Reproducing that
    convention here would let the *numeric* engine silently report ``1/0``
    as ``0`` - a lie about real-number arithmetic. Honesty over convenience:
    this evaluator raises :class:`EvalError` for division/inverse/modulo by
    zero and for any domain error (``log`` of a non-positive number,
    ``sqrt`` of a negative, overflow, ...). Callers that want the kernel's
    convention must go through ``kernel.reduce.normalize`` instead.
"""

from __future__ import annotations

import math
from fractions import Fraction
from typing import Callable, Optional, Union

from ..kernel.env import Environment
from ..kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit,
                           MVar, mk_app, unfold_app, instantiate)


class EvalError(ValueError):
    """A term has no honest floating-point value (opaque, non-numeric,
    out of domain, or division by zero)."""


#: What the interpreter produces: a number, a Bool, or a Python closure
#: (for function-valued terms; closures take and return `Value`s).
Value = Union[float, bool, Callable]


# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------

_CONSTS: dict[str, float] = {
    "Real.pi": math.pi,
    "Real.euler": math.e,
}

_UNARY: dict[str, Callable[[float], float]] = {
    "Real.sin": math.sin, "Real.cos": math.cos, "Real.tan": math.tan,
    "Real.asin": math.asin, "Real.acos": math.acos, "Real.atan": math.atan,
    "Real.sinh": math.sinh, "Real.cosh": math.cosh, "Real.tanh": math.tanh,
    "Real.exp": math.exp, "Real.log": math.log, "Real.sqrt": math.sqrt,
    "Real.abs": abs,
    "Real.floor": lambda x: float(math.floor(x)),
    "Real.ceil": lambda x: float(math.ceil(x)),
    "Int.natAbs": abs,
    "Nat.pred": lambda x: max(x - 1.0, 0.0),
}

# numeric coercions are identity on floats
_COERCE = {"Int.ofNat", "Rat.ofNat", "Rat.ofInt",
           "Real.ofNat", "Real.ofInt", "Real.ofRat", "Complex.ofReal"}


def _div_exact(a: float, b: float) -> float:
    if b == 0:
        raise EvalError("division by zero")
    return a / b


def _div_floor(a: float, b: float) -> float:
    if b == 0:
        raise EvalError("division by zero")
    return float(math.floor(a / b))


def _mod(a: float, b: float) -> float:
    if b == 0:
        raise EvalError("modulo by zero")
    return a - b * math.floor(a / b)


def _inv(a: float) -> float:
    if a == 0:
        raise EvalError("inverse of zero")
    return 1.0 / a


def _pow(a: float, b: float) -> float:
    try:
        return math.pow(a, b)
    except ValueError:
        raise EvalError(f"pow: domain error for {a!r} ^ {b!r}") from None
    except OverflowError:
        raise EvalError(f"pow: overflow for {a!r} ^ {b!r}") from None


def _nat_sub(a: float, b: float) -> float:
    return max(a - b, 0.0)   # kernel monus semantics (no zero involved)


# name -> (arity, implementation); comparisons return Python bools.
_ARITH: dict[str, tuple[int, Callable]] = {}


def _register(prefix: str, *, monus: bool, floordiv: bool) -> None:
    _ARITH[f"{prefix}.add"] = (2, lambda a, b: a + b)
    _ARITH[f"{prefix}.sub"] = (2, _nat_sub if monus else (lambda a, b: a - b))
    _ARITH[f"{prefix}.mul"] = (2, lambda a, b: a * b)
    _ARITH[f"{prefix}.div"] = (2, _div_floor if floordiv else _div_exact)
    _ARITH[f"{prefix}.mod"] = (2, _mod)
    _ARITH[f"{prefix}.neg"] = (1, lambda a: -a)
    _ARITH[f"{prefix}.inv"] = (1, _inv)
    _ARITH[f"{prefix}.pow"] = (2, _pow)
    _ARITH[f"{prefix}.beq"] = (2, lambda a, b: a == b)
    _ARITH[f"{prefix}.ble"] = (2, lambda a, b: a <= b)
    _ARITH[f"{prefix}.blt"] = (2, lambda a, b: a < b)


_register("Nat", monus=True, floordiv=True)
_register("Int", monus=False, floordiv=True)
_register("Rat", monus=False, floordiv=False)
_register("Real", monus=False, floordiv=False)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _as_number(v: Value, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise EvalError(f"{what}: argument is not a number ({v!r})")
    if not math.isfinite(v):
        raise EvalError(f"{what}: non-finite value {v!r}")
    return float(v)


def _lit_of(x: float) -> Lit:
    if not math.isfinite(x):
        raise EvalError(f"cannot substitute non-finite value {x!r}")
    return Lit(Fraction(x), "Real")


def _closure(env: Environment, lam: Lam, subst: dict[str, float]) -> Callable:
    """Turn a Lam into a Python closure over a float argument."""
    def call(x: float) -> Value:
        return _eval(env, instantiate(lam.body, _lit_of(float(x))), subst)
    return call


def _eval(env: Environment, t: Term, subst: dict[str, float]) -> Value:
    """Evaluate `t` to a float / bool / closure. Iterative on the app spine
    so definition unfolding and beta steps do not grow the Python stack."""
    while True:
        head, args = unfold_app(t)

        if isinstance(head, Lit):
            if args:
                raise EvalError(f"number {head!r} applied as a function")
            return float(head.value)
        if isinstance(head, StrLit):
            raise EvalError(f"string literal {head!r} is not a number")
        if isinstance(head, Lam):
            if args:                       # beta (call-by-name)
                t = mk_app(instantiate(head.body, args[0]), *args[1:])
                continue
            return _closure(env, head, subst)
        if isinstance(head, Var):
            raise EvalError("open term: unbound variable cannot be evaluated")
        if isinstance(head, (Sort, Pi)):
            raise EvalError(f"{head!r} is a type, not a number")
        if isinstance(head, MVar):
            raise EvalError("term contains an unsolved metavariable")

        assert isinstance(head, Const)
        name = head.name

        if name in _CONSTS:
            if args:
                raise EvalError(f"constant {name} applied as a function")
            return _CONSTS[name]

        if name in ("Bool.true", "Bool.false"):
            if args:
                raise EvalError(f"{name} applied as a function")
            return name == "Bool.true"

        if name == "Nat.zero":
            if args:
                raise EvalError("Nat.zero applied as a function")
            return 0.0
        if name == "Nat.succ":
            if len(args) != 1:
                raise EvalError("Nat.succ expects exactly one argument")
            return _as_number(_eval(env, args[0], subst), "Nat.succ") + 1.0

        # lazy if-then-else: evaluate the condition, keep the untaken
        # branch unevaluated (it may be undefined, e.g. a guarded 1/x).
        if name == "ite":                  # ite A c t e
            if len(args) < 4:
                raise EvalError("partially applied ite")
            c = _eval(env, args[1], subst)
            if not isinstance(c, bool):
                raise EvalError(f"ite condition is not a Bool ({c!r})")
            t = mk_app(args[2] if c else args[3], *args[4:])
            continue
        if name == "Bool.rec":             # Bool.rec motive false-case true-case c
            if len(args) < 4:
                raise EvalError("partially applied Bool.rec")
            c = _eval(env, args[3], subst)
            if not isinstance(c, bool):
                raise EvalError(f"Bool.rec major premise is not a Bool ({c!r})")
            t = mk_app(args[2] if c else args[1], *args[4:])
            continue

        if name in _UNARY:
            fn = _UNARY[name]
            if not args:
                return lambda x, _f=fn, _n=name: _apply(_n, _f, float(x))
            if len(args) > 1:
                raise EvalError(f"{name} result applied as a function")
            return _apply(name, fn, _as_number(_eval(env, args[0], subst), name))

        entry = _ARITH.get(name)
        if entry is not None:
            arity, fn = entry
            if len(args) > arity:
                raise EvalError(f"{name} result applied as a function")
            if len(args) == arity:
                vals = [_as_number(_eval(env, a, subst), name) for a in args]
                return _apply(name, fn, *vals)
            if arity == 2 and len(args) == 1:   # curried partial application
                a0 = _as_number(_eval(env, args[0], subst), name)
                return lambda b, _f=fn, _n=name, _a=a0: _apply(_n, _f, _a, float(b))
            if arity == 2:
                return lambda a, _f=fn, _n=name: (
                    lambda b, _a=float(a): _apply(_n, _f, _a, float(b)))
            return lambda a, _f=fn, _n=name: _apply(_n, _f, float(a))

        if name in _COERCE:                # identity on floats
            if not args:
                return lambda x: float(x)
            t = mk_app(args[0], *args[1:])
            continue

        decl = env.get(name)
        if decl is not None and decl.value is not None:
            t = mk_app(decl.value, *args)  # delta: unfold and keep going
            continue

        if subst is not None and name in subst:
            if args:
                raise EvalError(
                    f"'{name}' is substituted by a number but applied to arguments")
            return _as_number(subst[name], f"substitution for '{name}'")

        raise EvalError(f"cannot numerically evaluate opaque constant '{name}'")


def _apply(name: str, fn: Callable, *xs: float) -> Value:
    """Apply a table function, converting math-domain failures to EvalError."""
    try:
        r = fn(*xs)
    except EvalError:
        raise
    except ZeroDivisionError:
        raise EvalError(f"{name}: division by zero") from None
    except (ValueError, OverflowError) as e:
        raise EvalError(f"{name}: {e}") from None
    if isinstance(r, bool):
        return r
    if not math.isfinite(r):
        raise EvalError(f"{name}: non-finite result {r!r}")
    return float(r)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def eval_term(env: Environment, t: Term,
              subst: Optional[dict[str, float]] = None) -> float:
    """Evaluate a closed kernel Term to a float (Bool terms yield a bool).

    `subst` maps *Const names* to values - elaborator locals appear as
    Consts, so this is how free numeric variables get bound. Raises
    :class:`EvalError` for opaque/non-numeric terms, domain errors, and
    division by zero (see module docstring for the deliberate divergence
    from the kernel's total-function convention).
    """
    v = _eval(env, t, subst or {})
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    raise EvalError("term evaluates to a function, not a number")


def eval_function(env: Environment, f: Term, x: float,
                  subst: Optional[dict[str, float]] = None) -> float:
    """Evaluate the unary function term `f` at the float `x`.

    `f` may be a Lam (its body is instantiated directly) or any term that
    can head an application (e.g. ``Const("Real.sin")`` or a definition
    unfolding to a Lam).
    """
    if isinstance(f, Lam):
        return eval_term(env, instantiate(f.body, _lit_of(float(x))), subst)
    return eval_term(env, App(f, _lit_of(float(x))), subst)
