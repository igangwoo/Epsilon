"""Internal normal form for the CAS: rational functions over opaque atoms.

An *atom* is any subterm the arithmetic layer treats as a black box: a
variable (local Const), or a function application such as sin(x), exp(x),
sqrt(x+1). Numeric literals are coefficients, not atoms.

- A monomial is a product of atoms raised to integer powers, keyed by a
  sorted tuple of (atom_key, exponent).
- A polynomial is a dict {monomial_key: Fraction coefficient}.
- A rational is numerator_poly / denominator_poly.

This form gives a canonical representative for the commutative-ring /
field fragment, which is what powers `simplify`, `expand`, and
`symbolic_eq`. Anything outside that fragment stays wrapped in an atom, so
correctness is preserved even when the CAS cannot simplify.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from ..kernel.term import (Term, Const, App, Lit, mk_app, unfold_app)

NUMERIC_TYPES = ("Nat", "Int", "Rat", "Real", "Complex")
ARITH_SUFFIXES = {"add", "sub", "mul", "div", "neg", "inv", "pow"}


class CASError(Exception):
    pass


@dataclass
class Atom:
    key: str
    term: Term


class AtomTable:
    """Interns atoms so equal subterms share a key and an ordering."""

    def __init__(self) -> None:
        self._by_key: dict[str, Atom] = {}

    def intern(self, term: Term) -> str:
        key = repr(term)
        if key not in self._by_key:
            self._by_key[key] = Atom(key, term)
        return key

    def term(self, key: str) -> Term:
        return self._by_key[key].term

    def order(self) -> list[str]:
        return sorted(self._by_key)


MonoKey = tuple  # sorted tuple of (atom_key, exponent)


@dataclass
class Poly:
    """A multivariate polynomial: monomial_key -> coefficient."""
    terms: dict[MonoKey, Fraction] = field(default_factory=dict)

    @staticmethod
    def zero() -> "Poly":
        return Poly({})

    @staticmethod
    def constant(c) -> "Poly":
        c = Fraction(c)
        return Poly({(): c}) if c != 0 else Poly({})

    @staticmethod
    def atom(key: str, exp: int = 1) -> "Poly":
        if exp == 0:
            return Poly.constant(1)
        return Poly({((key, exp),): Fraction(1)})

    def is_zero(self) -> bool:
        return not self.terms

    def is_constant(self) -> bool:
        return all(k == () for k in self.terms)

    def constant_value(self) -> Optional[Fraction]:
        if self.is_zero():
            return Fraction(0)
        if self.is_constant():
            return self.terms.get((), Fraction(0))
        return None

    def _add_mono(self, key: MonoKey, coeff: Fraction) -> None:
        new = self.terms.get(key, Fraction(0)) + coeff
        if new == 0:
            self.terms.pop(key, None)
        else:
            self.terms[key] = new

    def __add__(self, other: "Poly") -> "Poly":
        out = Poly(dict(self.terms))
        for k, c in other.terms.items():
            out._add_mono(k, c)
        return out

    def __neg__(self) -> "Poly":
        return Poly({k: -c for k, c in self.terms.items()})

    def __sub__(self, other: "Poly") -> "Poly":
        return self + (-other)

    def scale(self, c: Fraction) -> "Poly":
        if c == 0:
            return Poly.zero()
        return Poly({k: v * c for k, v in self.terms.items()})

    def __mul__(self, other: "Poly") -> "Poly":
        out = Poly.zero()
        for k1, c1 in self.terms.items():
            for k2, c2 in other.terms.items():
                out._add_mono(_mono_mul(k1, k2), c1 * c2)
        return out

    def pow_int(self, n: int) -> "Poly":
        if n < 0:
            raise CASError("negative polynomial power")
        result = Poly.constant(1)
        base = self
        while n:
            if n & 1:
                result = result * base
            base = base * base
            n >>= 1
        return result

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Poly) and self.terms == other.terms

    def __hash__(self):  # not hashable in general; used only for sets of ids
        return id(self)


def _mono_mul(k1: MonoKey, k2: MonoKey) -> MonoKey:
    d: dict[str, int] = {}
    for a, e in k1:
        d[a] = d.get(a, 0) + e
    for a, e in k2:
        d[a] = d.get(a, 0) + e
    return tuple(sorted((a, e) for a, e in d.items() if e != 0))


@dataclass
class Rational:
    """num / den, both polynomials. den is never the zero polynomial."""
    num: Poly
    den: Poly

    @staticmethod
    def from_poly(p: Poly) -> "Rational":
        return Rational(p, Poly.constant(1))

    @staticmethod
    def constant(c) -> "Rational":
        return Rational(Poly.constant(c), Poly.constant(1))

    def __add__(self, other: "Rational") -> "Rational":
        return Rational(self.num * other.den + other.num * self.den,
                        self.den * other.den).reduced()

    def __neg__(self) -> "Rational":
        return Rational(-self.num, self.den)

    def __sub__(self, other: "Rational") -> "Rational":
        return self + (-other)

    def __mul__(self, other: "Rational") -> "Rational":
        return Rational(self.num * other.num, self.den * other.den).reduced()

    def inv(self) -> "Rational":
        if self.num.is_zero():
            # inverse of zero: kept symbolic by the caller (total-inv is a
            # kernel convention, not a CAS identity)
            raise CASError("inverse of zero in CAS normal form")
        return Rational(self.den, self.num)

    def div(self, other: "Rational") -> "Rational":
        return self * other.inv()

    def reduced(self) -> "Rational":
        """Cancel a common constant factor and normalize the denominator sign.
        (Full polynomial GCD cancellation is intentionally limited to the
        constant/common-monomial case to stay fast and total.)"""
        if self.num.is_zero():
            return Rational(Poly.zero(), Poly.constant(1))
        num, den = self.num, self.den
        # pull out a common monomial gcd
        g = _content_gcd(num, den)
        if g is not None:
            num = _divide_by_mono(num, g)
            den = _divide_by_mono(den, g)
        # normalize by leading denominator coefficient
        dconst = den.constant_value()
        if dconst is not None and dconst != 0:
            return Rational(num.scale(Fraction(1) / dconst),
                            Poly.constant(1))
        return Rational(num, den)

    def is_polynomial(self) -> bool:
        return self.den.constant_value() == 1

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Rational):
            return False
        # cross-multiply: a/b == c/d  iff  a*d == c*b
        return (self.num * other.den) == (other.num * self.den)

    def __hash__(self):
        return id(self)


def _content_gcd(num: Poly, den: Poly) -> Optional[MonoKey]:
    """Greatest common monomial dividing every term of both polynomials."""
    all_keys = list(num.terms) + list(den.terms)
    if not all_keys:
        return None
    common: Optional[dict[str, int]] = None
    for k in all_keys:
        d = dict(k)
        if common is None:
            common = d
        else:
            common = {a: min(common.get(a, 0), d.get(a, 0))
                      for a in set(common) & set(d)}
    if not common:
        return None
    g = tuple(sorted((a, e) for a, e in common.items() if e > 0))
    return g if g else None


def _divide_by_mono(p: Poly, g: MonoKey) -> Poly:
    gd = dict(g)
    out = Poly.zero()
    for k, c in p.terms.items():
        kd = dict(k)
        for a, e in gd.items():
            kd[a] = kd.get(a, 0) - e
        newk = tuple(sorted((a, e) for a, e in kd.items() if e != 0))
        out._add_mono(newk, c)
    return out
