"""CAS operations on kernel terms.

Public functions take and return kernel `Term`s. `differentiate`,
`integrate`, `limit_of`, and `taylor` work on unary functions represented
as `Lam` terms over a numeric type (usually Real).
"""

from __future__ import annotations

from fractions import Fraction
from typing import Optional

from ..kernel.env import Environment
from ..kernel.reduce import whnf
from ..kernel.term import (Term, Var, Const, App, Lam, Pi, Lit, mk_app,
                           unfold_app, instantiate, abstract_const)
from .normal import (Poly, Rational, AtomTable, CASError, NUMERIC_TYPES)

# functions with known derivatives / integrals
_ELEMENTARY = {"Real.sin", "Real.cos", "Real.tan", "Real.exp", "Real.log",
               "Real.sqrt", "Real.abs", "Real.sinh", "Real.cosh", "Real.tanh",
               "Real.asin", "Real.acos", "Real.atan"}


# ---------------------------------------------------------------------------
# type discovery
# ---------------------------------------------------------------------------

def _numeric_type(env: Environment, t: Term) -> str:
    """Best-effort numeric type of a term; defaults to Real."""
    head, args = unfold_app(t)
    if isinstance(head, Const):
        n = head.name
        for T in NUMERIC_TYPES:
            if n.startswith(T + "."):
                return T
        if n in NUMERIC_TYPES:
            return n
    if isinstance(t, Lit):
        return t.tyname
    for a in args:
        T = _numeric_type(env, a)
        if T not in ("Nat",):
            return T
    return "Real"


def _op(T: str, suffix: str) -> Const:
    return Const(f"{T}.{suffix}")


# ---------------------------------------------------------------------------
# Term  <->  Rational normal form
# ---------------------------------------------------------------------------

def _to_rational(env: Environment, t: Term, atoms: AtomTable,
                 T: str) -> Rational:
    t = _peel_coercions(t)
    if isinstance(t, Lit):
        return Rational.constant(t.value)
    head, args = unfold_app(t)
    if isinstance(head, Const):
        name = head.name
        suffix = name.rsplit(".", 1)[-1] if "." in name else ""
        prefix = name.rsplit(".", 1)[0] if "." in name else ""
        if prefix in NUMERIC_TYPES:
            try:
                if suffix == "add" and len(args) == 2:
                    return (_to_rational(env, args[0], atoms, T)
                            + _to_rational(env, args[1], atoms, T))
                if suffix == "sub" and len(args) == 2:
                    return (_to_rational(env, args[0], atoms, T)
                            - _to_rational(env, args[1], atoms, T))
                if suffix == "mul" and len(args) == 2:
                    return (_to_rational(env, args[0], atoms, T)
                            * _to_rational(env, args[1], atoms, T))
                if suffix == "neg" and len(args) == 1:
                    return -_to_rational(env, args[0], atoms, T)
                if suffix == "div" and len(args) == 2:
                    denom = _to_rational(env, args[1], atoms, T)
                    if denom.num.is_zero():
                        return _atom_rational(t, atoms)
                    return _to_rational(env, args[0], atoms, T).div(denom)
                if suffix == "inv" and len(args) == 1:
                    inner = _to_rational(env, args[0], atoms, T)
                    if inner.num.is_zero():
                        return _atom_rational(t, atoms)
                    return inner.inv()
                if suffix == "pow" and len(args) == 2:
                    exp = _peel_coercions(whnf(env, args[1]))
                    if isinstance(exp, Lit) and exp.value.denominator == 1:
                        e = int(exp.value)
                        base = _to_rational(env, args[0], atoms, T)
                        if e >= 0:
                            return Rational(base.num.pow_int(e),
                                            base.den.pow_int(e))
                        if not base.num.is_zero():
                            inv = base.inv()
                            return Rational(inv.num.pow_int(-e),
                                            inv.den.pow_int(-e))
            except CASError:
                return _atom_rational(t, atoms)
    folded = _fold_atom(env, t, T)
    if folded is not None:
        return folded
    return _atom_rational(t, atoms)


def _atom_rational(t: Term, atoms: AtomTable) -> Rational:
    key = atoms.intern(t)
    return Rational.from_poly(Poly.atom(key))


def _fold_atom(env: Environment, t: Term, T: str) -> Optional[Rational]:
    """If t is an elementary function with a foldable argument, return its
    value as a constant Rational; else None (caller interns it as an atom)."""
    head, args = unfold_app(t)
    if isinstance(head, Const) and head.name in _ELEMENTARY and len(args) == 1:
        folded = _simplify_atoms(env, t, T)
        if isinstance(folded, Lit):
            return Rational.constant(folded.value)
    return None


def _peel_coercions(t: Term) -> Term:
    """Drop transparent numeric coercions (Real.ofNat etc.) around literals
    and atoms, so 2 and (Real.ofNat 2) share a normal form."""
    from .normal import CASError  # noqa: F401
    head, args = unfold_app(t)
    if isinstance(head, Const) and len(args) == 1:
        coerce = {"Int.ofNat", "Rat.ofNat", "Rat.ofInt", "Real.ofNat",
                  "Real.ofInt", "Real.ofRat"}
        if head.name in coerce:
            inner = _peel_coercions(args[0])
            if isinstance(inner, Lit):
                target = head.name.split(".")[0]
                return Lit(inner.value, target)
            return inner
    return t


def _poly_to_term(env: Environment, p: Poly, atoms: AtomTable, T: str) -> Term:
    if p.is_zero():
        return _lit(0, T)
    monos = sorted(p.terms.items(),
                   key=lambda kv: (-_mono_degree(kv[0]), _mono_sort(kv[0])))
    result: Optional[Term] = None
    for key, coeff in monos:
        term = _mono_to_term(env, key, coeff, atoms, T)
        result = term if result is None else mk_app(_op(T, "add"), result, term)
    return result if result is not None else _lit(0, T)


def _mono_degree(key) -> int:
    return sum(e for _, e in key)


def _mono_sort(key):
    return tuple(sorted(key))


def _mono_to_term(env: Environment, key, coeff: Fraction, atoms: AtomTable,
                  T: str) -> Term:
    factors: list[Term] = []
    for atom_key, exp in sorted(key):
        atom = atoms.term(atom_key)
        if exp == 1:
            factors.append(atom)
        else:
            factors.append(mk_app(_op(T, "pow"), atom, _lit(exp, "Nat")))
    if not factors:
        return _lit(coeff, T)
    body = factors[0]
    for f in factors[1:]:
        body = mk_app(_op(T, "mul"), body, f)
    if coeff == 1:
        return body
    if coeff == -1:
        return mk_app(_op(T, "neg"), body)
    return mk_app(_op(T, "mul"), _lit(coeff, T), body)


def _rational_to_term(env: Environment, r: Rational, atoms: AtomTable,
                      T: str) -> Term:
    num = _poly_to_term(env, r.num, atoms, T)
    if r.den.constant_value() == 1:
        return num
    den = _poly_to_term(env, r.den, atoms, T)
    return mk_app(_op(T, "div"), num, den)


def _lit(v, T: str) -> Term:
    v = Fraction(v)
    if T == "Nat" and (v < 0 or v.denominator != 1):
        T = "Int" if v.denominator == 1 else "Rat"
    if T == "Int" and v.denominator != 1:
        T = "Rat"
    return Lit(v, T if T in ("Nat", "Int", "Rat", "Real") else "Real")


# ---------------------------------------------------------------------------
# Public: simplify / expand / factor / collect / substitute
# ---------------------------------------------------------------------------

def simplify(env: Environment, t: Term) -> Term:
    """Algebraic normal form of `t` (rational-function canonicalization)."""
    T = _numeric_type(env, t)
    atoms = AtomTable()
    try:
        # recursively simplify inside atoms (function arguments) first
        t2 = _simplify_atoms(env, t, T)
        r = _to_rational(env, t2, atoms, T)
        return _rational_to_term(env, r, atoms, T)
    except CASError:
        return t


# exact special values of elementary functions at simple arguments
_SPECIAL_VALUES = {
    ("Real.sin", 0): Fraction(0),
    ("Real.cos", 0): Fraction(1),
    ("Real.tan", 0): Fraction(0),
    ("Real.asin", 0): Fraction(0),
    ("Real.atan", 0): Fraction(0),
    ("Real.sinh", 0): Fraction(0),
    ("Real.cosh", 0): Fraction(1),
    ("Real.tanh", 0): Fraction(0),
    ("Real.exp", 0): Fraction(1),
    ("Real.log", 1): Fraction(0),
    ("Real.sqrt", 0): Fraction(0),
    ("Real.sqrt", 1): Fraction(1),
    ("Real.abs", 0): Fraction(0),
}


def _simplify_atoms(env: Environment, t: Term, T: str) -> Term:
    """Rebuild t with elementary-function arguments simplified in place, and
    fold known special values (sin 0 = 0, exp 0 = 1, sqrt 1 = 1, ...)."""
    head, args = unfold_app(t)
    if isinstance(head, Const) and head.name in _ELEMENTARY and len(args) == 1:
        arg = simplify(env, args[0])
        if isinstance(arg, Lit):
            val = _SPECIAL_VALUES.get((head.name, arg.value))
            if val is not None:
                return _lit(val, T)
            # perfect-square sqrt of an integer
            if head.name == "Real.sqrt" and arg.value >= 0 and \
                    arg.value.denominator == 1:
                root = _int_sqrt(int(arg.value))
                if root is not None:
                    return _lit(root, T)
        return App(head, arg)
    return t


def _int_sqrt(n: int) -> Optional[int]:
    if n < 0:
        return None
    r = int(n ** 0.5)
    for cand in (r - 1, r, r + 1):
        if cand >= 0 and cand * cand == n:
            return cand
    return None


def expand(env: Environment, t: Term) -> Term:
    """Expand products and powers into a flat sum of monomials."""
    T = _numeric_type(env, t)
    atoms = AtomTable()
    try:
        r = _to_rational(env, t, atoms, T)
        if r.den.constant_value() == 1:
            return _poly_to_term(env, r.num, atoms, T)
        return _rational_to_term(env, r, atoms, T)
    except CASError:
        return t


def factor(env: Environment, t: Term) -> Term:
    """Factor out the greatest common monomial (partial factoring)."""
    T = _numeric_type(env, t)
    atoms = AtomTable()
    try:
        r = _to_rational(env, t, atoms, T)
        if r.den.constant_value() != 1 or r.num.is_zero():
            return _rational_to_term(env, r, atoms, T)
        from .normal import _content_gcd, _divide_by_mono
        g = _content_gcd(r.num, r.num)
        if g is None:
            return _poly_to_term(env, r.num, atoms, T)
        rest = _divide_by_mono(r.num, g)
        gterm = _mono_to_term(env, g, Fraction(1), atoms, T)
        return mk_app(_op(T, "mul"), gterm, _poly_to_term(env, rest, atoms, T))
    except CASError:
        return t


def collect(env: Environment, t: Term, var: Term) -> Term:
    """Collect terms by powers of `var` (currently: simplify, which already
    groups by monomial)."""
    return simplify(env, t)


def substitute(env: Environment, t: Term, var: Term, value: Term) -> Term:
    """Replace every occurrence of the closed subterm `var` with `value`."""
    from ..kernel.term import replace_term
    return simplify(env, replace_term(t, var, value))


def symbolic_eq(env: Environment, a: Term, b: Term) -> bool:
    """Decide a == b as rational functions (simplify(a - b) == 0)."""
    T = _numeric_type(env, a)
    if T == "Nat":
        T = _numeric_type(env, b)
    atoms = AtomTable()
    try:
        ra = _to_rational(env, _simplify_atoms(env, a, T), atoms, T)
        rb = _to_rational(env, _simplify_atoms(env, b, T), atoms, T)
        return ra == rb
    except CASError:
        return False


# ---------------------------------------------------------------------------
# Differentiation
# ---------------------------------------------------------------------------

def differentiate(env: Environment, f: Term, var: Optional[Term] = None) -> Term:
    """Symbolic derivative.

    If `f` is a `Lam` over Real, returns a `Lam` of the derivative. If `f`
    is an expression and `var` is given, differentiates w.r.t. that Const.
    """
    if isinstance(f, Lam):
        marker = Const("$cas_diff_var")
        body = instantiate(f.body, marker)
        d = _diff(env, body, "$cas_diff_var")
        d = simplify(env, d)
        return Lam(f.name, f.ty, abstract_const(d, "$cas_diff_var"))
    if var is not None and isinstance(var, Const):
        return simplify(env, _diff(env, f, var.name))
    raise CASError("differentiate expects a Lam or an expression plus a var")


def _diff(env: Environment, t: Term, x: str) -> Term:
    T = "Real"
    if isinstance(t, Lit):
        return _lit(0, T)
    if isinstance(t, Const):
        return _lit(1, T) if t.name == x else _lit(0, T)
    head, args = unfold_app(t)
    if isinstance(head, Const):
        name = head.name
        suffix = name.rsplit(".", 1)[-1]
        prefix = name.rsplit(".", 1)[0]
        if prefix in NUMERIC_TYPES:
            if suffix == "add" and len(args) == 2:
                return _add(_diff(env, args[0], x), _diff(env, args[1], x))
            if suffix == "sub" and len(args) == 2:
                return _sub(_diff(env, args[0], x), _diff(env, args[1], x))
            if suffix == "neg" and len(args) == 1:
                return mk_app(_op(T, "neg"), _diff(env, args[0], x))
            if suffix == "mul" and len(args) == 2:
                u, v = args
                return _add(_mul(_diff(env, u, x), v),
                            _mul(u, _diff(env, v, x)))
            if suffix == "div" and len(args) == 2:
                u, v = args
                num = _sub(_mul(_diff(env, u, x), v), _mul(u, _diff(env, v, x)))
                return mk_app(_op(T, "div"), num, _mul(v, v))
            if suffix == "pow" and len(args) == 2:
                base, exp = args
                exp_w = _peel_coercions(whnf(env, exp))
                if isinstance(exp_w, Lit) and not _mentions(exp, x):
                    n = exp_w.value
                    # d/dx base^n = n * base^(n-1) * base'
                    new_pow = mk_app(_op(T, "pow"), base,
                                     _lit(n - 1, "Nat" if n - 1 >= 0 and
                                          (n - 1).denominator == 1 else "Real"))
                    return _mul(_mul(_lit(n, T), new_pow), _diff(env, base, x))
        d = _diff_elementary(env, name, args, x)
        if d is not None:
            return d
    if not _mentions(t, x):
        return _lit(0, T)
    raise CASError(f"cannot differentiate {t!r}")


def _diff_elementary(env: Environment, name: str, args: list[Term],
                     x: str) -> Optional[Term]:
    if len(args) != 1:
        return None
    u = args[0]
    du = _diff(env, u, x)
    T = "Real"
    table = {
        "Real.sin": lambda: App(Const("Real.cos"), u),
        "Real.cos": lambda: mk_app(_op(T, "neg"), App(Const("Real.sin"), u)),
        "Real.exp": lambda: App(Const("Real.exp"), u),
        "Real.log": lambda: mk_app(_op(T, "div"), _lit(1, T), u),
        "Real.tan": lambda: mk_app(_op(T, "div"), _lit(1, T),
                                   _mul(App(Const("Real.cos"), u),
                                        App(Const("Real.cos"), u))),
        "Real.sqrt": lambda: mk_app(_op(T, "div"), _lit(1, T),
                                    _mul(_lit(2, T), App(Const("Real.sqrt"), u))),
        "Real.sinh": lambda: App(Const("Real.cosh"), u),
        "Real.cosh": lambda: App(Const("Real.sinh"), u),
        "Real.atan": lambda: mk_app(_op(T, "div"), _lit(1, T),
                                    _add(_lit(1, T), _mul(u, u))),
    }
    if name in table:
        return _mul(table[name](), du)
    return None


def _mentions(t: Term, x: str) -> bool:
    from ..kernel.term import constants_of
    return x in set(constants_of(t))


def _add(a: Term, b: Term) -> Term:
    return mk_app(Const("Real.add"), a, b)


def _sub(a: Term, b: Term) -> Term:
    return mk_app(Const("Real.sub"), a, b)


def _mul(a: Term, b: Term) -> Term:
    return mk_app(Const("Real.mul"), a, b)


# ---------------------------------------------------------------------------
# Integration (pattern-based)
# ---------------------------------------------------------------------------

def integrate(env: Environment, f: Term, var: Optional[Term] = None) -> Optional[Term]:
    """Symbolic antiderivative. Returns a `Lam` if `f` is a `Lam`, else an
    expression (needs `var`). None when the integral is not known."""
    if isinstance(f, Lam):
        marker = "$cas_int_var"
        body = instantiate(f.body, Const(marker))
        anti = _integrate(env, body, marker)
        if anti is None:
            return None
        anti = simplify(env, anti)
        return Lam(f.name, f.ty, abstract_const(anti, marker))
    if var is not None and isinstance(var, Const):
        anti = _integrate(env, f, var.name)
        return simplify(env, anti) if anti is not None else None
    raise CASError("integrate expects a Lam or an expression plus a var")


def _integrate(env: Environment, t: Term, x: str) -> Optional[Term]:
    T = "Real"
    xc = Const(x)
    if not _mentions(t, x):
        return _mul(t, xc)  # ∫ c dx = c x
    head, args = unfold_app(t)
    if isinstance(head, Const):
        name = head.name
        suffix = name.rsplit(".", 1)[-1]
        prefix = name.rsplit(".", 1)[0]
        if prefix in NUMERIC_TYPES:
            if suffix == "add" and len(args) == 2:
                a, b = _integrate(env, args[0], x), _integrate(env, args[1], x)
                return _add(a, b) if a is not None and b is not None else None
            if suffix == "sub" and len(args) == 2:
                a, b = _integrate(env, args[0], x), _integrate(env, args[1], x)
                return _sub(a, b) if a is not None and b is not None else None
            if suffix == "neg" and len(args) == 1:
                a = _integrate(env, args[0], x)
                return mk_app(_op(T, "neg"), a) if a is not None else None
            if suffix == "mul" and len(args) == 2:
                # constant * f(x)
                a, b = args
                if not _mentions(a, x):
                    ib = _integrate(env, b, x)
                    return _mul(a, ib) if ib is not None else None
                if not _mentions(b, x):
                    ia = _integrate(env, a, x)
                    return _mul(ia, b) if ia is not None else None
            if suffix == "pow" and len(args) == 2:
                base, exp = args
                exp_w = _peel_coercions(whnf(env, exp))
                if (isinstance(base, Const) and base.name == x
                        and isinstance(exp_w, Lit)):
                    n = exp_w.value
                    if n != -1:
                        # ∫ x^n dx = x^(n+1)/(n+1)
                        newp = mk_app(_op(T, "pow"), xc,
                                      _lit(n + 1, "Nat" if (n + 1) >= 0 and
                                           (n + 1).denominator == 1 else "Real"))
                        return mk_app(_op(T, "div"), newp, _lit(n + 1, T))
                    return App(Const("Real.log"), xc)  # ∫ x^-1 = ln x
    # x itself
    if isinstance(t, Const) and t.name == x:
        return mk_app(_op(T, "div"), mk_app(_op(T, "pow"), xc, _lit(2, "Nat")),
                      _lit(2, T))
    # elementary f(x)
    anti = _integrate_elementary(env, head, args, x)
    if anti is not None:
        return anti
    return None


def _integrate_elementary(env, head, args, x) -> Optional[Term]:
    if not (isinstance(head, Const) and len(args) == 1):
        return None
    u = args[0]
    if not (isinstance(u, Const) and u.name == x):
        return None  # only ∫ f(x) dx, not chain forms
    T = "Real"
    table = {
        "Real.sin": mk_app(_op(T, "neg"), App(Const("Real.cos"), u)),
        "Real.cos": App(Const("Real.sin"), u),
        "Real.exp": App(Const("Real.exp"), u),
    }
    return table.get(head.name)


# ---------------------------------------------------------------------------
# Limits
# ---------------------------------------------------------------------------

def limit_of(env: Environment, f: Term, a: Term) -> Optional[Term]:
    """Limit of a unary function `f` (a Lam over Real) at point `a`."""
    if not isinstance(f, Lam):
        raise CASError("limit_of expects a Lam")
    return _limit_body(env, f, a, depth=0)


def _limit_body(env: Environment, f: Lam, a: Term, depth: int) -> Optional[Term]:
    if depth > 5:
        return None
    body = instantiate(f.body, a)
    val = simplify(env, body)
    if not _has_singularity(env, val):
        return val
    # 0/0 form? try L'Hopital when f is num/den
    marker = "$cas_lim_var"
    open_body = instantiate(f.body, Const(marker))
    head, args = unfold_app(open_body)
    if isinstance(head, Const) and head.name.endswith(".div") and len(args) == 2:
        num, den = args
        num_at = simplify(env, instantiate(f.body, a) if False else _subst_const(num, marker, a))
        den_at = simplify(env, _subst_const(den, marker, a))
        if _is_zero_lit(num_at) and _is_zero_lit(den_at):
            dnum = differentiate(env, Lam(f.name, f.ty,
                                          abstract_const(num, marker)))
            dden = differentiate(env, Lam(f.name, f.ty,
                                          abstract_const(den, marker)))
            new_f = Lam(f.name, f.ty,
                        abstract_const(mk_app(Const("Real.div"),
                                              instantiate(dnum.body, Const(marker)),
                                              instantiate(dden.body, Const(marker))),
                                       marker))
            return _limit_body(env, new_f, a, depth + 1)
    return None


def _subst_const(t: Term, name: str, value: Term) -> Term:
    from ..kernel.term import replace_term
    return replace_term(t, Const(name), value)


def _is_zero_lit(t: Term) -> bool:
    return isinstance(t, Lit) and t.value == 0


def _has_singularity(env: Environment, t: Term) -> bool:
    """True if t contains a division by something that simplified to 0."""
    head, args = unfold_app(t)
    if isinstance(head, Const) and head.name.endswith(".div") and len(args) == 2:
        d = simplify(env, args[1])
        if _is_zero_lit(d):
            return True
    for a in args:
        if _has_singularity(env, a):
            return True
    if isinstance(t, (Lam, Pi)):
        return _has_singularity(env, t.body)
    return False


# ---------------------------------------------------------------------------
# Taylor series
# ---------------------------------------------------------------------------

def taylor(env: Environment, f: Term, a: Term, order: int) -> Optional[Term]:
    """Taylor polynomial of `f` (a Lam over Real) around `a` up to `order`."""
    if not isinstance(f, Lam):
        raise CASError("taylor expects a Lam")
    T = "Real"
    marker = "$cas_taylor_var"
    xc = Const(marker)
    result: Optional[Term] = None
    fact = 1
    cur = f
    for k in range(order + 1):
        if k > 0:
            fact *= k
            cur = differentiate(env, cur)
        coeff = simplify(env, instantiate(cur.body, a))
        if _is_zero_lit(coeff):
            continue
        # coeff/k! * (x - a)^k
        term = mk_app(_op(T, "div"), coeff, _lit(fact, T)) if fact != 1 else coeff
        if k > 0:
            diff = mk_app(_op(T, "sub"), xc, a)
            powt = diff if k == 1 else mk_app(_op(T, "pow"), diff, _lit(k, "Nat"))
            term = _mul(term, powt) if fact == 1 else \
                mk_app(_op(T, "div"), _mul(coeff, powt), _lit(fact, T))
        result = term if result is None else _add(result, term)
    if result is None:
        result = _lit(0, T)
    return Lam(f.name, f.ty, abstract_const(simplify(env, result), marker))


def series_expansion(env: Environment, f: Term, a: Term,
                     order: int) -> Optional[Term]:
    return taylor(env, f, a, order)


# ---------------------------------------------------------------------------
# Equation solving
# ---------------------------------------------------------------------------

def solve_eq(env: Environment, lhs: Term, rhs: Term,
             var_hint: str = "x") -> Optional[list[Term]]:
    """Solve lhs = rhs for the variable named `var_hint`. Handles linear and
    quadratic equations. Returns a list of solution terms, or None."""
    T = _numeric_type(env, lhs)
    if T == "Nat":
        T = "Real"
    atoms = AtomTable()
    x = var_hint
    try:
        expr = _to_rational(env, mk_app(_op(T, "sub"), lhs, rhs), atoms, T)
        if expr.den.constant_value() != 1:
            expr = Rational.from_poly(expr.num)
        poly = expr.num
        coeffs = _univariate_coeffs(poly, atoms, x)
        if coeffs is None:
            return None
        return _solve_poly(env, coeffs, T)
    except CASError:
        return None


def _univariate_coeffs(poly: Poly, atoms: AtomTable,
                       x: str) -> Optional[dict[int, Fraction]]:
    """Extract coefficients by power of the variable x; None if other
    variables are present."""
    xkey = None
    for k in atoms.order():
        term = atoms.term(k)
        if isinstance(term, Const) and term.name == x:
            xkey = k
            break
    coeffs: dict[int, Fraction] = {}
    for mono, c in poly.terms.items():
        deg = 0
        for atom_key, exp in mono:
            if atom_key == xkey:
                deg = exp
            else:
                return None  # another variable present
        coeffs[deg] = coeffs.get(deg, Fraction(0)) + c
    return coeffs


def _solve_poly(env: Environment, coeffs: dict[int, Fraction],
                T: str) -> Optional[list[Term]]:
    deg = max(coeffs) if coeffs else 0
    if deg == 1:
        a = coeffs.get(1, Fraction(0))
        b = coeffs.get(0, Fraction(0))
        if a == 0:
            return None
        return [_lit(-b / a, T)]
    if deg == 2:
        a = coeffs.get(2, Fraction(0))
        b = coeffs.get(1, Fraction(0))
        c = coeffs.get(0, Fraction(0))
        if a == 0:
            return _solve_poly(env, {1: b, 0: c}, T)
        disc = b * b - 4 * a * c
        # -b/(2a) ± sqrt(disc)/(2a)
        base = mk_app(_op(T, "div"), _lit(-b, T), _lit(2 * a, T))
        if disc == 0:
            return [simplify(env, base)]
        sq = mk_app(_op(T, "div"),
                    App(Const("Real.sqrt"), _lit(disc, T)), _lit(2 * a, T))
        return [simplify(env, mk_app(_op(T, "add"), base, sq)),
                simplify(env, mk_app(_op(T, "sub"), base, sq))]
    return None


def partial_fraction(env: Environment, t: Term) -> Term:
    """Partial-fraction decomposition (v0.1: returns the simplified form;
    full decomposition is future work)."""
    return simplify(env, t)
