"""The CAS as an interactive service.

`epsilon.cas.engine` operates on kernel terms. The IDE's CAS pane works in
source text, so this module is the layer between: it parses an expression,
binds its free variables, runs one named operation, and reports the result
in every form the front end needs (Epsilon source, LaTeX, MathML).

The verification status is part of the answer, not decoration. A CAS result
is `symbolic` and a sampled value is `numeric`; neither is ever `proven`.
Only the kernel proves things, and it is not involved here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from ..elab.elaborator import Elaborator
from ..kernel.term import Const, Lam, Term, instantiate
from ..syntax import sast
from ..syntax.parser import parse_expression
from . import engine

#: `simplify(x)` is not a proof that the answer equals the input in the
#: kernel's sense; it is an algebraic normalisation the CAS vouches for.
SYMBOLIC = "symbolic"
NUMERIC = "numeric"


class CASRequestError(ValueError):
    """The request could not be carried out (bad input, or op not applicable)."""


@dataclass
class CASResult:
    op: str
    status: str
    input: Term
    result: Optional[Term] = None
    results: list[Term] = field(default_factory=list)
    variable: str = "x"
    note: str = ""


# ---------------------------------------------------------------------------
# parsing with free variables
# ---------------------------------------------------------------------------

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def free_identifiers(expr: sast.Expr) -> list[str]:
    """Identifiers in `expr` that no declaration defines, in source order.

    These are the expression's variables: in `a*x + b` over an environment
    that knows neither, all three are. Order is source order so `x` in
    `x + a` is still the first variable, which is what a reader expects.
    """
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, sast.SIdent):
            if node.name not in found:
                found.append(node.name)
            return
        for value in vars(node).values():
            if isinstance(value, sast.Node):
                walk(value)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    if isinstance(item, sast.Node):
                        walk(item)

    walk(expr)
    return found


def parse_term(session, src: str, variables: Optional[list[str]] = None
               ) -> tuple[Term, list[str]]:
    """Elaborate `src`, binding its free variables as reals.

    Returns the term (free variables appearing as `Const`) and the variable
    names in source order.
    """
    src = src.strip()
    if not src:
        raise CASRequestError("nothing to compute")
    try:
        expr = parse_expression(src, extra_ops=dict(session.extra_ops))
    except Exception as e:  # noqa: BLE001 - surface the parse error as text
        raise CASRequestError(str(e)) from e

    known = free_identifiers(expr)
    unknown = [n for n in known if not _resolves(session, n)]
    if variables:
        for v in variables:
            if v not in unknown:
                unknown.append(v)

    el = Elaborator(session.env, session.ctx)
    if not unknown:
        try:
            return el.finalize(el.elab_expr(expr, None)), []
        except Exception as e:  # noqa: BLE001
            raise CASRequestError(str(e)) from e

    binders = " ".join(f"({n} : Real)" for n in unknown)
    try:
        lam = el.finalize(el.elab_expr(
            parse_expression(f"fun {binders} => {src}",
                             extra_ops=dict(session.extra_ops)), None))
    except Exception as e:  # noqa: BLE001
        raise CASRequestError(str(e)) from e

    term = lam
    for name in unknown:
        if not isinstance(term, Lam):
            break
        term = instantiate(term.body, Const(name))
    return term, unknown


def _resolves(session, name: str) -> bool:
    try:
        return session.ctx.resolve_global(name) is not None
    except Exception:  # noqa: BLE001 - an unresolvable name is a variable
        return False


def as_function(term: Term, var: str) -> Term:
    """Re-abstract `term` over `var`, the form the calculus operations take."""
    from ..kernel.term import abstract_const
    return Lam(var, Const("Real"), abstract_const(term, var))


# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------

#: op -> (label, needs a variable, one-line description)
OPERATIONS = {
    "simplify":    ("Simplify", False, "algebraic normal form"),
    "expand":      ("Expand", False, "multiply out products and powers"),
    "factor":      ("Factor", False, "pull out common factors"),
    "derivative":  ("Derivative", True, "d/dx of the expression"),
    "integral":    ("Antiderivative", True, "∫ f dx, without the constant"),
    "limit":       ("Limit", True, "limit as the variable approaches a point"),
    "taylor":      ("Taylor series", True, "series expansion about a point"),
    "solve":       ("Solve", True, "solutions of expression = 0"),
    "evaluate":    ("Evaluate", True, "numeric value at a point"),
}


def run(session, op: str, src: str, *, variable: Optional[str] = None,
        point: str = "0", order: int = 5) -> CASResult:
    """Run one CAS operation over an expression written as source text."""
    if op not in OPERATIONS:
        raise CASRequestError(f"unknown operation '{op}'")

    env = session.env
    term, variables = parse_term(session, src,
                                 [variable] if variable else None)
    var = variable or (variables[0] if variables else "x")

    if op == "simplify":
        return CASResult(op, SYMBOLIC, term, engine.simplify(env, term), variable=var)
    if op == "expand":
        return CASResult(op, SYMBOLIC, term, engine.expand(env, term), variable=var)
    if op == "factor":
        return CASResult(op, SYMBOLIC, term, engine.factor(env, term), variable=var)

    if op == "derivative":
        d = engine.differentiate(env, as_function(term, var))
        body = instantiate(d.body, Const(var)) if isinstance(d, Lam) else d
        return CASResult(op, SYMBOLIC, term, engine.simplify(env, body), variable=var)

    if op == "integral":
        anti = engine.integrate(env, as_function(term, var))
        if anti is None:
            raise CASRequestError(
                "no antiderivative found for this expression — the CAS says so "
                "rather than guessing")
        body = instantiate(anti.body, Const(var)) if isinstance(anti, Lam) else anti
        return CASResult(op, SYMBOLIC, term, engine.simplify(env, body),
                         variable=var, note="constant of integration omitted")

    if op == "limit":
        at, _ = parse_term(session, point)
        value = engine.limit_of(env, as_function(term, var), at)
        if value is None:
            raise CASRequestError(f"the limit at {point} could not be determined")
        return CASResult(op, SYMBOLIC, term, value, variable=var)

    if op == "taylor":
        at, _ = parse_term(session, point)
        series = engine.taylor(env, as_function(term, var), at, max(1, int(order)))
        if series is None:
            raise CASRequestError("no series expansion found at that point")
        body = instantiate(series.body, Const(var)) if isinstance(series, Lam) else series
        return CASResult(op, SYMBOLIC, term, engine.simplify(env, body), variable=var,
                         note=f"about {point}, to order {order}")

    if op == "solve":
        from ..kernel.term import Lit
        roots = engine.solve_eq(env, term, Lit(0, "Real"), var_hint=var)
        if roots is None:
            raise CASRequestError(
                "the CAS cannot solve this equation — it says so rather than "
                "returning a value it cannot justify")
        return CASResult(op, SYMBOLIC, term, None, list(roots), variable=var,
                         note="solutions of expression = 0")

    # evaluate
    from ..numeric.evaluator import eval_term
    from ..kernel.term import Lit
    from fractions import Fraction
    at_term, _ = parse_term(session, point)
    try:
        at_value = eval_term(env, at_term)
        value = eval_term(env, term, {var: at_value})
    except Exception as e:  # noqa: BLE001 - honest failure beats a fake number
        raise CASRequestError(str(e)) from e
    return CASResult("evaluate", NUMERIC, term,
                     Lit(Fraction(value).limit_denominator(10 ** 12), "Real"),
                     variable=var,
                     note=f"floating-point value at {var} = {point}")
