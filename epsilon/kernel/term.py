"""Kernel term representation.

One unified term language for everything: expressions, types, propositions
and proofs are all `Term`s (propositions-as-types). Binders use de Bruijn
indices; the `name` on Lam/Pi is only a pretty-printing hint.

Universe levels are a simple non-polymorphic hierarchy:
    Sort 0 = Prop, Sort 1 = Type, Sort 2 = Type 1, ...
Pi-types use the CIC "imax" rule so Prop is impredicative.

Numeric literals: `Lit(value, tyname)` carries an exact `Fraction` and the
name of its numeric type ("Nat" | "Int" | "Rat" | "Real"). The kernel gives
these definitional arithmetic (see reduce.py) - a deliberate, documented
trusted extension mirroring Lean's kernel-accelerated Nat literals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Iterator


class TermBase:
    """Base class for all kernel terms."""

    __slots__ = ()

    # -- convenience -------------------------------------------------------
    def __call__(self, *args: "Term") -> "Term":
        return mk_app(self, *args)


@dataclass(frozen=True)
class Var(TermBase):
    """Bound variable, de Bruijn index (0 = innermost binder)."""
    idx: int

    def __repr__(self) -> str:
        return f"#{self.idx}"


@dataclass(frozen=True)
class Const(TermBase):
    """Reference to a global declaration by fully-qualified name."""
    name: str

    def __repr__(self) -> str:
        return self.name


@dataclass(frozen=True)
class Sort(TermBase):
    """Sort 0 = Prop, Sort 1 = Type, Sort 2 = Type 1, ..."""
    level: int

    def __repr__(self) -> str:
        if self.level == 0:
            return "Prop"
        if self.level == 1:
            return "Type"
        return f"Type {self.level - 1}"


@dataclass(frozen=True)
class App(TermBase):
    fn: "Term"
    arg: "Term"

    def __repr__(self) -> str:
        return f"({self.fn!r} {self.arg!r})"


@dataclass(frozen=True)
class Lam(TermBase):
    name: str
    ty: "Term"
    body: "Term"

    def __repr__(self) -> str:
        return f"(λ {self.name} : {self.ty!r} => {self.body!r})"


@dataclass(frozen=True)
class Pi(TermBase):
    name: str
    ty: "Term"
    body: "Term"
    implicit: bool = field(default=False, compare=False)

    def __repr__(self) -> str:
        b = "{" if self.implicit else "("
        e = "}" if self.implicit else ")"
        return f"(Π {b}{self.name} : {self.ty!r}{e}, {self.body!r})"


@dataclass(frozen=True)
class Lit(TermBase):
    """Exact numeric literal. tyname in {"Nat","Int","Rat","Real"}."""
    value: Fraction
    tyname: str

    def __post_init__(self) -> None:
        if self.tyname in ("Nat", "Int") and self.value.denominator != 1:
            raise ValueError(f"non-integer literal for {self.tyname}: {self.value}")
        if self.tyname == "Nat" and self.value < 0:
            raise ValueError(f"negative Nat literal: {self.value}")

    def __repr__(self) -> str:
        if self.value.denominator == 1:
            return f"{self.value.numerator}:{self.tyname}"
        return f"{self.value.numerator}/{self.value.denominator}:{self.tyname}"


@dataclass(frozen=True)
class StrLit(TermBase):
    value: str

    def __repr__(self) -> str:
        return repr(self.value)


@dataclass(frozen=True)
class MVar(TermBase):
    """Metavariable - elaboration only. The kernel REJECTS terms with mvars."""
    id: int

    def __repr__(self) -> str:
        return f"?m{self.id}"


Term = TermBase

PROP = Sort(0)
TYPE = Sort(1)


# ---------------------------------------------------------------------------
# Structural helpers
# ---------------------------------------------------------------------------

def mk_app(fn: Term, *args: Term) -> Term:
    t = fn
    for a in args:
        t = App(t, a)
    return t


def unfold_app(t: Term) -> tuple[Term, list[Term]]:
    """Return (head, [arg0, arg1, ...]) for a (possibly nested) application."""
    args: list[Term] = []
    while isinstance(t, App):
        args.append(t.arg)
        t = t.fn
    args.reverse()
    return t, args


def app_head(t: Term) -> Term:
    while isinstance(t, App):
        t = t.fn
    return t


def lift(t: Term, amount: int, cutoff: int = 0) -> Term:
    """Shift free de Bruijn indices >= cutoff by `amount`."""
    if amount == 0:
        return t
    if isinstance(t, Var):
        return Var(t.idx + amount) if t.idx >= cutoff else t
    if isinstance(t, App):
        fn = lift(t.fn, amount, cutoff)
        arg = lift(t.arg, amount, cutoff)
        return t if fn is t.fn and arg is t.arg else App(fn, arg)
    if isinstance(t, Lam):
        ty = lift(t.ty, amount, cutoff)
        body = lift(t.body, amount, cutoff + 1)
        return t if ty is t.ty and body is t.body else Lam(t.name, ty, body)
    if isinstance(t, Pi):
        ty = lift(t.ty, amount, cutoff)
        body = lift(t.body, amount, cutoff + 1)
        return t if ty is t.ty and body is t.body else Pi(t.name, ty, body, t.implicit)
    return t


def instantiate(t: Term, value: Term, idx: int = 0) -> Term:
    """Substitute `value` for de Bruijn variable `idx` in `t` (and lower others)."""
    if isinstance(t, Var):
        if t.idx == idx:
            return lift(value, idx)
        if t.idx > idx:
            return Var(t.idx - 1)
        return t
    if isinstance(t, App):
        fn = instantiate(t.fn, value, idx)
        arg = instantiate(t.arg, value, idx)
        return t if fn is t.fn and arg is t.arg else App(fn, arg)
    if isinstance(t, Lam):
        ty = instantiate(t.ty, value, idx)
        body = instantiate(t.body, value, idx + 1)
        return t if ty is t.ty and body is t.body else Lam(t.name, ty, body)
    if isinstance(t, Pi):
        ty = instantiate(t.ty, value, idx)
        body = instantiate(t.body, value, idx + 1)
        return t if ty is t.ty and body is t.body else Pi(t.name, ty, body, t.implicit)
    return t


def abstract_const(t: Term, name: str, depth: int = 0) -> Term:
    """Replace occurrences of Const(name) with Var(depth). Used to build binders
    from named local constants during elaboration."""
    if isinstance(t, Const):
        return Var(depth) if t.name == name else t
    if isinstance(t, Var):
        return Var(t.idx + 1) if t.idx >= depth else t
    if isinstance(t, App):
        return App(abstract_const(t.fn, name, depth), abstract_const(t.arg, name, depth))
    if isinstance(t, Lam):
        return Lam(t.name, abstract_const(t.ty, name, depth),
                   abstract_const(t.body, name, depth + 1))
    if isinstance(t, Pi):
        return Pi(t.name, abstract_const(t.ty, name, depth),
                  abstract_const(t.body, name, depth + 1), t.implicit)
    return t


def replace_term(t: Term, target: Term, replacement: Term, depth: int = 0) -> Term:
    """Replace closed subterm `target` with `replacement` everywhere in `t`.

    `target` and `replacement` must be closed (no free de Bruijn variables);
    both are compared/inserted unshifted, which is only sound because closed
    terms are invariant under lifting.
    """
    if t == target:
        return replacement
    if isinstance(t, App):
        return App(replace_term(t.fn, target, replacement, depth),
                   replace_term(t.arg, target, replacement, depth))
    if isinstance(t, Lam):
        return Lam(t.name, replace_term(t.ty, target, replacement, depth),
                   replace_term(t.body, target, replacement, depth + 1))
    if isinstance(t, Pi):
        return Pi(t.name, replace_term(t.ty, target, replacement, depth),
                  replace_term(t.body, target, replacement, depth + 1), t.implicit)
    return t


def has_var(t: Term, idx: int = 0) -> bool:
    if isinstance(t, Var):
        return t.idx == idx
    if isinstance(t, App):
        return has_var(t.fn, idx) or has_var(t.arg, idx)
    if isinstance(t, (Lam, Pi)):
        return has_var(t.ty, idx) or has_var(t.body, idx + 1)
    return False


def is_closed(t: Term, depth: int = 0) -> bool:
    if isinstance(t, Var):
        return t.idx < depth
    if isinstance(t, App):
        return is_closed(t.fn, depth) and is_closed(t.arg, depth)
    if isinstance(t, (Lam, Pi)):
        return is_closed(t.ty, depth) and is_closed(t.body, depth + 1)
    return True


def has_mvar(t: Term) -> bool:
    if isinstance(t, MVar):
        return True
    if isinstance(t, App):
        return has_mvar(t.fn) or has_mvar(t.arg)
    if isinstance(t, (Lam, Pi)):
        return has_mvar(t.ty) or has_mvar(t.body)
    return False


def constants_of(t: Term) -> Iterator[str]:
    """Yield names of all global constants referenced by `t`."""
    stack = [t]
    while stack:
        s = stack.pop()
        if isinstance(s, Const):
            yield s.name
        elif isinstance(s, App):
            stack.append(s.fn)
            stack.append(s.arg)
        elif isinstance(s, (Lam, Pi)):
            stack.append(s.ty)
            stack.append(s.body)


def nat_lit(n: int) -> Lit:
    return Lit(Fraction(n), "Nat")


def int_lit(n: int) -> Lit:
    return Lit(Fraction(n), "Int")


def rat_lit(v) -> Lit:
    return Lit(Fraction(v), "Rat")


def real_lit(v) -> Lit:
    return Lit(Fraction(v), "Real")
