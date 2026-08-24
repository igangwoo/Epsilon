"""Reduction and definitional equality.

Implements:
- beta   : (λ x, b) a  ~>  b[a/x]
- delta  : unfolding of reducible definitions
- iota   : recursor applied to a constructor (or numeric literal)
- lit    : exact arithmetic on Nat/Int/Rat/Real literals (trusted extension)
- eta    : (λ x, f x) == f  during definitional-equality checking

Division/inverse follow the total-function convention (x / 0 = 0, inv 0 = 0),
matching how the standard library states field axioms (with x ≠ 0 hypotheses).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Callable, Optional

from .env import Environment, DeclKind, KernelError
from .term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar,
    mk_app, unfold_app, instantiate, lift,
)

MAX_STEPS = 200_000

TRUE = Const("Bool.true")
FALSE = Const("Bool.false")


def _bool(b: bool) -> Term:
    return TRUE if b else FALSE


# ---------------------------------------------------------------------------
# Literal arithmetic (trusted extension)
# ---------------------------------------------------------------------------
# name -> (arity, result kind); functions receive Fractions and return either a
# Fraction (numeric result) or a bool (comparison result).

def _nat_sub(a: Fraction, b: Fraction) -> Fraction:
    return a - b if a >= b else Fraction(0)


def _floordiv(a: Fraction, b: Fraction) -> Fraction:
    if b == 0:
        return Fraction(0)
    return Fraction(int(a // b))


def _mod(a: Fraction, b: Fraction) -> Fraction:
    if b == 0:
        return a
    return a - b * Fraction(int(a // b))


def _inv(a: Fraction) -> Fraction:
    return Fraction(0) if a == 0 else 1 / a


def _div_total(a: Fraction, b: Fraction) -> Fraction:
    return Fraction(0) if b == 0 else a / b


def _pow(a: Fraction, b: Fraction) -> Optional[Fraction]:
    if b.denominator != 1:
        return None  # non-integer exponent: leave symbolic
    e = b.numerator
    if a == 0 and e < 0:
        return Fraction(0)  # 0^-n follows inv 0 = 0 convention
    if abs(e) > 4096 or (abs(a.numerator) > 10**6 and abs(e) > 64):
        return None  # avoid pathological blowup inside the kernel
    return a ** e


_ARITH: dict[str, tuple[int, str, Callable]] = {}


def _register(prefix: str, out: str) -> None:
    _ARITH[f"{prefix}.add"] = (2, out, lambda a, b: a + b)
    _ARITH[f"{prefix}.mul"] = (2, out, lambda a, b: a * b)
    _ARITH[f"{prefix}.beq"] = (2, "Bool", lambda a, b: a == b)
    _ARITH[f"{prefix}.ble"] = (2, "Bool", lambda a, b: a <= b)
    _ARITH[f"{prefix}.blt"] = (2, "Bool", lambda a, b: a < b)


_register("Nat", "Nat")
_ARITH["Nat.sub"] = (2, "Nat", _nat_sub)
_ARITH["Nat.div"] = (2, "Nat", _floordiv)
_ARITH["Nat.mod"] = (2, "Nat", _mod)
_ARITH["Nat.pow"] = (2, "Nat", _pow)
_ARITH["Nat.pred"] = (1, "Nat", lambda a: _nat_sub(a, Fraction(1)))

_register("Int", "Int")
_ARITH["Int.sub"] = (2, "Int", lambda a, b: a - b)
_ARITH["Int.neg"] = (1, "Int", lambda a: -a)
_ARITH["Int.div"] = (2, "Int", _floordiv)
_ARITH["Int.mod"] = (2, "Int", _mod)
_ARITH["Int.pow"] = (2, "Int", _pow)
_ARITH["Int.natAbs"] = (1, "Nat", lambda a: abs(a))

_register("Rat", "Rat")
_ARITH["Rat.sub"] = (2, "Rat", lambda a, b: a - b)
_ARITH["Rat.neg"] = (1, "Rat", lambda a: -a)
_ARITH["Rat.inv"] = (1, "Rat", _inv)
_ARITH["Rat.div"] = (2, "Rat", _div_total)
_ARITH["Rat.pow"] = (2, "Rat", _pow)

_register("Real", "Real")
_ARITH["Real.sub"] = (2, "Real", lambda a, b: a - b)
_ARITH["Real.neg"] = (1, "Real", lambda a: -a)
_ARITH["Real.inv"] = (1, "Real", _inv)
_ARITH["Real.div"] = (2, "Real", _div_total)
_ARITH["Real.pow"] = (2, "Real", _pow)

# numeric coercions on literals
_COERCE: dict[str, str] = {
    "Int.ofNat": "Int",
    "Rat.ofNat": "Rat",
    "Rat.ofInt": "Rat",
    "Real.ofNat": "Real",
    "Real.ofInt": "Real",
    "Real.ofRat": "Real",
    "Complex.ofReal": "Complex",  # no Complex literals; left unreduced
}


def _try_lit_step(name: str, args: list[Term]) -> Optional[Term]:
    """Reduce a fully-literal arithmetic application, or return None."""
    if name in _COERCE and len(args) >= 1 and isinstance(args[0], Lit):
        target = _COERCE[name]
        if target == "Complex":
            return None
        return mk_app(Lit(args[0].value, target), *args[1:])
    entry = _ARITH.get(name)
    if entry is None:
        return None
    arity, out, fn = entry
    if len(args) < arity:
        return None
    head_args = args[:arity]
    if not all(isinstance(a, Lit) for a in head_args):
        return None
    result = fn(*[a.value for a in head_args])  # type: ignore[union-attr]
    if result is None:
        return None
    rest = args[arity:]
    if out == "Bool":
        return mk_app(_bool(bool(result)), *rest)
    return mk_app(Lit(Fraction(result), out), *rest)


# ---------------------------------------------------------------------------
# WHNF
# ---------------------------------------------------------------------------

class _Fuel:
    __slots__ = ("n",)

    def __init__(self, n: int = MAX_STEPS) -> None:
        self.n = n

    def tick(self) -> None:
        self.n -= 1
        if self.n <= 0:
            raise KernelError("reduction step limit exceeded (possible non-termination)")


def whnf(env: Environment, t: Term, *, delta: bool = True,
         _fuel: Optional[_Fuel] = None) -> Term:
    """Weak-head normal form with beta/delta/iota/literal reduction."""
    fuel = _fuel or _Fuel()
    while True:
        fuel.tick()
        head, args = unfold_app(t)

        # beta
        if isinstance(head, Lam) and args:
            body = instantiate(head.body, args[0])
            t = mk_app(body, *args[1:])
            continue

        if isinstance(head, Const):
            name = head.name

            # constructor <-> literal normalization for Nat
            if name == "Nat.zero":
                t = mk_app(Lit(Fraction(0), "Nat"), *args)
                if not args:
                    return t
                continue
            if name == "Nat.succ" and args and isinstance(args[0], Lit):
                t = mk_app(Lit(args[0].value + 1, "Nat"), *args[1:])
                continue

            # literal arithmetic (evaluate argument heads first, lazily)
            if name in _ARITH or name in _COERCE:
                arity = _ARITH[name][0] if name in _ARITH else 1
                if len(args) >= arity:
                    changed = False
                    new_args = list(args)
                    for i in range(arity):
                        if not isinstance(new_args[i], Lit):
                            reduced = whnf(env, new_args[i], delta=delta, _fuel=fuel)
                            if reduced is not new_args[i]:
                                new_args[i] = reduced
                                changed = True
                    step = _try_lit_step(name, new_args)
                    if step is not None:
                        t = step
                        continue
                    if changed:
                        t = mk_app(head, *new_args)
                        # fall through to other rules with updated args
                        head, args = unfold_app(t)

            # iota: recursor applied to constructor / literal
            ind_name = env.recursor_of.get(name)
            if ind_name is not None:
                step = _iota_step(env, name, ind_name, args, fuel, delta)
                if step is not None:
                    t = step
                    continue

            # delta
            if delta:
                decl = env.get(name)
                if (decl is not None and decl.value is not None and decl.reducible
                        and decl.kind == DeclKind.DEFINITION):
                    t = mk_app(decl.value, *args)
                    continue

        return t


def _iota_step(env: Environment, rec_name: str, ind_name: str,
               args: list[Term], fuel: _Fuel, delta: bool) -> Optional[Term]:
    info = env.inductives.get(ind_name)
    if info is None:
        return None

    if ind_name == "Eq":
        # Eq.rec/Eq.ind layout: A a motive minor b h  (arity 6)
        if len(args) < 6:
            return None
        major = whnf(env, args[5], delta=delta, _fuel=fuel)
        mh, margs = unfold_app(major)
        if isinstance(mh, Const) and mh.name == "Eq.refl":
            return mk_app(args[3], *args[6:])
        return None

    p = info.num_params
    k = len(info.constructors)
    arity = p + 1 + k + 1  # params, motive, minors, major
    if len(args) < arity:
        return None
    major = whnf(env, args[arity - 1], delta=delta, _fuel=fuel)

    # Nat literals are constructors in disguise
    if ind_name == "Nat" and isinstance(major, Lit):
        n = int(major.value)
        motive, minors = args[p], args[p + 1: p + 1 + k]
        zero_case, succ_case = minors[0], minors[1]
        if n == 0:
            return mk_app(zero_case, *args[arity:])
        pred = Lit(Fraction(n - 1), "Nat")
        rec_pred = mk_app(Const(rec_name), motive, zero_case, succ_case, pred)
        return mk_app(succ_case, pred, rec_pred, *args[arity:])

    mh, margs = unfold_app(major)
    if not isinstance(mh, Const) or mh.name not in info.constructors:
        return None
    ci = info.constructors.index(mh.name)
    minor = args[p + 1 + ci]
    fields = margs[p:]  # constructor args after parameters
    rec_args = info.ctor_recursive_args.get(mh.name, [])
    params = args[:p]
    motive = args[p]
    minors = args[p + 1: p + 1 + k]
    out = minor
    for fi, fv in enumerate(fields):
        out = App(out, fv)
        if fi in rec_args:
            ih = mk_app(Const(rec_name), *params, motive, *minors, fv)
            out = App(out, ih)
    return mk_app(out, *args[arity:])


# ---------------------------------------------------------------------------
# Definitional equality
# ---------------------------------------------------------------------------

def def_eq(env: Environment, a: Term, b: Term,
           _fuel: Optional[_Fuel] = None, _depth: int = 0) -> bool:
    if a == b:
        return True
    if _depth > 512:
        raise KernelError("definitional equality recursion limit exceeded")
    fuel = _fuel or _Fuel()
    a = whnf(env, a, _fuel=fuel)
    b = whnf(env, b, _fuel=fuel)
    if a == b:
        return True

    if isinstance(a, Sort) and isinstance(b, Sort):
        return a.level == b.level
    if isinstance(a, Lit) and isinstance(b, Lit):
        return a.value == b.value and a.tyname == b.tyname

    # bridge Nat literals with constructor form: (n+1 : Lit) == Nat.succ m
    # iff n == m (compare the predecessor against succ's argument directly,
    # so whnf cannot re-collapse the expansion)
    for x, y in ((a, b), (b, a)):
        if isinstance(x, Lit) and x.tyname == "Nat" and x.value > 0:
            yh, yargs = unfold_app(y)
            if isinstance(yh, Const) and yh.name == "Nat.succ" and len(yargs) == 1:
                return def_eq(env, Lit(x.value - 1, "Nat"), yargs[0], fuel, _depth + 1)
    if isinstance(a, StrLit) and isinstance(b, StrLit):
        return a.value == b.value

    if isinstance(a, (Lam, Pi)) and isinstance(b, type(a)):
        if not def_eq(env, a.ty, b.ty, fuel, _depth + 1):
            return False
        return def_eq(env, a.body, b.body, fuel, _depth + 1)

    # eta
    if isinstance(a, Lam) and not isinstance(b, Lam):
        return def_eq(env, a, Lam(a.name, a.ty, App(lift(b, 1), Var(0))), fuel, _depth + 1)
    if isinstance(b, Lam) and not isinstance(a, Lam):
        return def_eq(env, Lam(b.name, b.ty, App(lift(a, 1), Var(0))), b, fuel, _depth + 1)

    ah, aargs = unfold_app(a)
    bh, bargs = unfold_app(b)
    if ah == bh and len(aargs) == len(bargs):
        if all(def_eq(env, x, y, fuel, _depth + 1) for x, y in zip(aargs, bargs)):
            return True
    return False


# ---------------------------------------------------------------------------
# Full normalization (for simp / display / CAS interchange)
# ---------------------------------------------------------------------------

def normalize(env: Environment, t: Term, *, delta: bool = True,
              _fuel: Optional[_Fuel] = None) -> Term:
    fuel = _fuel or _Fuel(50_000)
    t = whnf(env, t, delta=delta, _fuel=fuel)
    if isinstance(t, App):
        head, args = unfold_app(t)
        nargs = [normalize(env, a, delta=delta, _fuel=fuel) for a in args]
        renext = mk_app(head, *nargs)
        again = whnf(env, renext, delta=delta, _fuel=fuel)
        if again != renext:
            return normalize(env, again, delta=delta, _fuel=fuel)
        return renext
    if isinstance(t, Lam):
        return Lam(t.name, normalize(env, t.ty, delta=delta, _fuel=fuel),
                   normalize(env, t.body, delta=delta, _fuel=fuel))
    if isinstance(t, Pi):
        return Pi(t.name, normalize(env, t.ty, delta=delta, _fuel=fuel),
                  normalize(env, t.body, delta=delta, _fuel=fuel), t.implicit)
    return t
