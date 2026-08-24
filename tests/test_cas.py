"""Tests for the CAS engine and oracle."""

import pytest

from epsilon.project import Session
from epsilon.cas.engine import (simplify, expand, differentiate, integrate,
                                limit_of, taylor, solve_eq, symbolic_eq, factor)
from epsilon.syntax.parser import parse_expression
from epsilon.elab.elaborator import Elaborator
from epsilon.kernel.term import Const, Lit, instantiate, unfold_app
from fractions import Fraction


@pytest.fixture(scope="module")
def sess():
    return Session()


def _lam(s, src):
    el = Elaborator(s.env, s.ctx)
    return el.finalize(el.elab_expr(
        parse_expression(f"λ (x : Real) => {src}", extra_ops=dict(s.extra_ops)),
        None))


def _body(s, src):
    return instantiate(_lam(s, src).body, Const("x"))


def _e(s, src):
    el = Elaborator(s.env, s.ctx)
    return el.finalize(el.elab_expr(
        parse_expression(src, extra_ops=dict(s.extra_ops)), Const("Real")))


def _is_lit(t, value):
    return isinstance(t, Lit) and t.value == Fraction(value)


# ---------------------------------------------------------------------------
# simplify / expand / symbolic_eq
# ---------------------------------------------------------------------------

def test_simplify_cancellation(sess):
    assert _is_lit(simplify(sess.env, _body(sess, "x - x")), 0)


def test_simplify_collects_like_terms(sess):
    r = simplify(sess.env, _body(sess, "2*x + 3*x"))
    # 5 * x
    assert symbolic_eq(sess.env, r, _body(sess, "5*x"))


def test_expand_square(sess):
    assert symbolic_eq(sess.env, expand(sess.env, _body(sess, "(x+1)^2")),
                       _body(sess, "x^2 + 2*x + 1"))


def test_symbolic_eq_true(sess):
    assert symbolic_eq(sess.env, _body(sess, "(x+1)*(x-1)"),
                       _body(sess, "x^2 - 1"))


def test_symbolic_eq_false(sess):
    assert not symbolic_eq(sess.env, _body(sess, "x^2"), _body(sess, "x^3"))


def _open(term, consts):
    """Instantiate nested lambda binders with the given constants, outermost
    first (each binder's variable becomes the matching Const)."""
    from epsilon.kernel.term import Lam
    for c in consts:
        assert isinstance(term, Lam)
        term = instantiate(term.body, c)
    return term


def test_symbolic_eq_multivariate(sess):
    el = Elaborator(sess.env, sess.ctx)
    a = el.finalize(el.elab_expr(parse_expression(
        "λ (x y : Real) => (x + y)^2"), None))
    b = el.finalize(el.elab_expr(parse_expression(
        "λ (x y : Real) => x^2 + 2*x*y + y^2"), None))
    ab = _open(a, [Const("x"), Const("y")])
    bb = _open(b, [Const("x"), Const("y")])
    assert symbolic_eq(sess.env, ab, bb)


# ---------------------------------------------------------------------------
# differentiation
# ---------------------------------------------------------------------------

def test_diff_polynomial(sess):
    d = differentiate(sess.env, _lam(sess, "x^2 + 3*x + 1"))
    body = instantiate(d.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "2*x + 3"))


def test_diff_product_rule(sess):
    d = differentiate(sess.env, _lam(sess, "Real.sin(x) * Real.exp(x)"))
    body = instantiate(d.body, Const("x"))
    expected = _body(sess, "Real.cos(x)*Real.exp(x) + Real.sin(x)*Real.exp(x)")
    assert symbolic_eq(sess.env, body, expected)


def test_diff_chain_rule(sess):
    d = differentiate(sess.env, _lam(sess, "Real.sin(x^2)"))
    body = instantiate(d.body, Const("x"))
    expected = _body(sess, "2*x*Real.cos(x^2)")
    assert symbolic_eq(sess.env, body, expected)


def test_diff_exp(sess):
    d = differentiate(sess.env, _lam(sess, "Real.exp(x)"))
    body = instantiate(d.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "Real.exp(x)"))


# ---------------------------------------------------------------------------
# integration (round trips)
# ---------------------------------------------------------------------------

def test_integrate_power(sess):
    anti = integrate(sess.env, _lam(sess, "x^2"))
    assert anti is not None
    # d/dx of the antiderivative recovers x^2
    d = differentiate(sess.env, anti)
    body = instantiate(d.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "x^2"))


def test_integrate_cos(sess):
    anti = integrate(sess.env, _lam(sess, "Real.cos(x)"))
    assert anti is not None
    body = instantiate(anti.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "Real.sin(x)"))


def test_integrate_sum(sess):
    anti = integrate(sess.env, _lam(sess, "x^2 + x"))
    assert anti is not None
    d = differentiate(sess.env, anti)
    body = instantiate(d.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "x^2 + x"))


# ---------------------------------------------------------------------------
# limits
# ---------------------------------------------------------------------------

def test_limit_substitution(sess):
    lim = limit_of(sess.env, _lam(sess, "x^2 + 1"), _e(sess, "3"))
    assert _is_lit(lim, 10)


def test_limit_sinc(sess):
    lim = limit_of(sess.env, _lam(sess, "Real.sin(x)/x"), _e(sess, "0"))
    assert _is_lit(lim, 1)


def test_limit_rational_00(sess):
    lim = limit_of(sess.env, _lam(sess, "(x^2 - 1)/(x - 1)"), _e(sess, "1"))
    assert _is_lit(lim, 2)


# ---------------------------------------------------------------------------
# taylor
# ---------------------------------------------------------------------------

def test_taylor_exp(sess):
    t = taylor(sess.env, _lam(sess, "Real.exp(x)"), _e(sess, "0"), 3)
    body = instantiate(t.body, Const("x"))
    # 1 + x + x^2/2 + x^3/6
    assert symbolic_eq(sess.env, body,
                       _body(sess, "1 + x + x^2/2 + x^3/6"))


def test_taylor_sin(sess):
    t = taylor(sess.env, _lam(sess, "Real.sin(x)"), _e(sess, "0"), 5)
    body = instantiate(t.body, Const("x"))
    assert symbolic_eq(sess.env, body, _body(sess, "x - x^3/6 + x^5/120"))


# ---------------------------------------------------------------------------
# solve
# ---------------------------------------------------------------------------

def test_solve_linear(sess):
    sols = solve_eq(sess.env, _body(sess, "2*x + 4"), _e(sess, "0"))
    assert sols is not None and len(sols) == 1
    assert _is_lit(sols[0], -2)


def test_solve_quadratic(sess):
    sols = solve_eq(sess.env, _body(sess, "x^2 - 5*x + 6"), _e(sess, "0"))
    assert sols is not None
    values = {simplify(sess.env, s) for s in sols}
    lit_vals = {t.value for t in values if isinstance(t, Lit)}
    assert Fraction(3) in lit_vals and Fraction(2) in lit_vals


# ---------------------------------------------------------------------------
# oracle + honest statuses
# ---------------------------------------------------------------------------

def test_cas_oracle_proves_symbolically():
    s = Session()
    r = s.check_source(
        "theorem t (x : Real) : (x + 1)^2 = x^2 + 2*x + 1 := by cas\n"
        "theorem u (x : Real) : x = x := by rfl", "cas")
    assert r.ok, [d.format() for d in r.diagnostics]
    status = {t["name"]: t["status"] for t in s.theorem_list("cas")}
    assert status["t"] == "symbolic"   # NOT proven - honesty
    assert status["u"] == "proven"


def test_cas_oracle_rejects_falsehood():
    s = Session()
    r = s.check_source(
        "theorem bad (x : Real) : x^2 = x^3 := by cas", "cas")
    assert not r.ok
    assert any("cas" in d.message for d in r.diagnostics)


def test_cas_oracle_limit():
    s = Session()
    r = s.check_source(
        "theorem l : HasLimitAt(λ (x : Real) => Real.sin(x)/x, 0, 1) := by cas",
        "cas")
    assert r.ok, [d.format() for d in r.diagnostics]
    assert s.theorem_list("cas")[0]["status"] == "symbolic"
