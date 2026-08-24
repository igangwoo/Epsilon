"""Tests for the numerical engine (epsilon.numeric)."""

from __future__ import annotations

import math
from fractions import Fraction

import pytest

from epsilon.kernel.term import Const, Lit, mk_app, real_lit
from epsilon.numeric import (EvalError, eval_term, eval_function, find_root,
                             integrate_numeric, solve_ode, numeric_oracle)
from epsilon.project import Session


@pytest.fixture(scope="module")
def session() -> Session:
    return Session()


@pytest.fixture(scope="module")
def env(session):
    return session.env


def elab(session: Session, src: str):
    """Elaborate a surface expression to a kernel Term (contract recipe)."""
    from epsilon.elab.elaborator import Elaborator
    from epsilon.syntax.parser import parse_expression
    el = Elaborator(session.env, session.ctx)
    t = el.elab_expr(parse_expression(src, extra_ops=dict(session.extra_ops)),
                     None)
    return el.finalize(t)


# ---------------------------------------------------------------------------
# evaluator
# ---------------------------------------------------------------------------

class TestEvaluator:
    def test_literals(self, env):
        assert eval_term(env, Lit(Fraction(5), "Nat")) == 5.0
        assert eval_term(env, Lit(Fraction(-7), "Int")) == -7.0
        assert eval_term(env, Lit(Fraction(3, 4), "Rat")) == 0.75
        assert eval_term(env, real_lit(Fraction(1, 3))) == pytest.approx(1 / 3)

    def test_rational_arithmetic(self, session, env):
        assert eval_term(env, elab(session, "1/2 + 1/4")) == 0.75
        assert eval_term(env, elab(session, "2 ^ 10")) == 1024.0
        assert eval_term(env, elab(session, "7 % 3")) == 1.0

    def test_stdlib_constants_and_functions(self, session, env):
        assert eval_term(env, elab(session, "π")) == pytest.approx(math.pi)
        assert eval_term(env, elab(session, "Real.euler")) == pytest.approx(math.e)
        assert eval_term(env, elab(session, "sin(π)")) == pytest.approx(0.0, abs=1e-12)
        assert eval_term(env, elab(session, "exp(1) * cos(0)")) == pytest.approx(math.e)
        assert eval_term(env, elab(session, "sqrt(2)")) == pytest.approx(math.sqrt(2))

    def test_division_by_zero_is_an_error_not_zero(self, session, env):
        # honesty: the kernel's total-function 1/0 = 0 convention is NOT used
        with pytest.raises(EvalError):
            eval_term(env, elab(session, "1/0"))
        with pytest.raises(EvalError):
            eval_term(env, mk_app(Const("Real.inv"), real_lit(0)))
        with pytest.raises(EvalError):
            eval_term(env, mk_app(Const("Real.div"), real_lit(1), real_lit(0)))

    def test_domain_errors(self, env):
        with pytest.raises(EvalError):
            eval_term(env, mk_app(Const("Real.log"), real_lit(0)))
        with pytest.raises(EvalError):
            eval_term(env, mk_app(Const("Real.sqrt"), real_lit(-1)))

    def test_subst_binds_const_names(self, env):
        t = mk_app(Const("Real.mul"), Const("x?loc"), Const("x?loc"))
        assert eval_term(env, t, subst={"x?loc": 3.0}) == 9.0
        with pytest.raises(EvalError):
            eval_term(env, t)  # opaque without the substitution

    def test_opaque_constant_is_error(self, env):
        with pytest.raises(EvalError):
            eval_term(env, mk_app(Const("integral"), Const("Real.sin"),
                                  real_lit(0), real_lit(1)))

    def test_bools_and_lazy_ite(self, env):
        assert eval_term(env, Const("Bool.true")) is True
        assert eval_term(env, mk_app(Const("Real.blt"), real_lit(0),
                                     real_lit(1))) is True
        # the untaken 1/0 branch must never be evaluated
        poison = mk_app(Const("Real.div"), real_lit(1), real_lit(0))
        t = mk_app(Const("ite"), Const("Real"), Const("Bool.true"),
                   real_lit(42), poison)
        assert eval_term(env, t) == 42.0

    def test_ite_via_elaborator(self, session, env):
        t = elab(session, "if Real.blt(0, 1) then 1 else 2")
        assert eval_term(env, t) == 1.0

    def test_eval_function_sinc(self, session, env):
        f = elab(session, "fun (x : ℝ) => sin(x)/x")
        assert eval_function(env, f, 1.0) == pytest.approx(math.sin(1.0))
        assert eval_function(env, f, 0.5) == pytest.approx(math.sin(0.5) / 0.5)
        with pytest.raises(EvalError):
            eval_function(env, f, 0.0)   # honest pole, not 0

    def test_eval_function_on_bare_const(self, env):
        assert eval_function(env, Const("Real.sin"), math.pi / 2) == pytest.approx(1.0)

    def test_eval_function_on_prelude_definition(self, session, env):
        # `sin` is a prelude def whose value is Real.sin
        assert eval_function(env, elab(session, "sin"), 0.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# roots
# ---------------------------------------------------------------------------

class TestRoots:
    def test_sqrt2(self, session, env):
        f = elab(session, "fun (x : ℝ) => x^2 - 2")
        r = find_root(env, f, 0.0, 2.0)
        assert r is not None
        assert r == pytest.approx(math.sqrt(2), abs=1e-9)

    def test_cos_root_is_half_pi(self, env):
        r = find_root(env, Const("Real.cos"), 0.0, 3.0)
        assert r is not None
        assert r == pytest.approx(math.pi / 2, abs=1e-9)

    def test_no_root(self, session, env):
        f = elab(session, "fun (x : ℝ) => x^2 + 1")
        assert find_root(env, f, -1.0, 1.0) is None


# ---------------------------------------------------------------------------
# integrate
# ---------------------------------------------------------------------------

class TestIntegrate:
    def test_sin_over_0_pi(self, env):
        v = integrate_numeric(env, Const("Real.sin"), 0.0, math.pi)
        assert v == pytest.approx(2.0, abs=1e-8)

    def test_polynomial(self, session, env):
        f = elab(session, "fun (x : ℝ) => x^2")
        assert integrate_numeric(env, f, 0.0, 1.0) == pytest.approx(1 / 3, abs=1e-10)

    def test_reversed_bounds(self, env):
        v = integrate_numeric(env, Const("Real.sin"), math.pi, 0.0)
        assert v == pytest.approx(-2.0, abs=1e-8)

    def test_undefined_point_raises(self, session, env):
        f = elab(session, "fun (x : ℝ) => 1/x")
        with pytest.raises(EvalError, match="undefined at"):
            integrate_numeric(env, f, 0.0, 1.0)


# ---------------------------------------------------------------------------
# ode
# ---------------------------------------------------------------------------

class TestODE:
    def test_exponential_growth(self, session, env):
        f2 = elab(session, "fun (x : ℝ) => fun (y : ℝ) => y")
        traj = solve_ode(env, f2, 0.0, 1.0, 1.0, 100)
        assert len(traj) == 101
        assert traj[0] == (0.0, 1.0)
        x_end, y_end = traj[-1]
        assert x_end == pytest.approx(1.0)
        assert y_end == pytest.approx(math.e, abs=1e-7)

    def test_rhs_uses_x(self, session, env):
        # y' = 2x from (0,0): y(2) = 4
        f2 = elab(session, "fun (x : ℝ) => fun (y : ℝ) => 2 * x")
        _, y_end = solve_ode(env, f2, 0.0, 0.0, 2.0, 50)[-1]
        assert y_end == pytest.approx(4.0, abs=1e-9)

    def test_bad_steps(self, session, env):
        f2 = elab(session, "fun (x : ℝ) => fun (y : ℝ) => y")
        with pytest.raises(ValueError):
            solve_ode(env, f2, 0.0, 1.0, 1.0, 0)


# ---------------------------------------------------------------------------
# oracle
# ---------------------------------------------------------------------------

class TestOracle:
    def test_scalar_eq_true(self, session, env):
        ok, reason = numeric_oracle(env, elab(session, "sin(π) = 0"))
        assert ok, reason
        ok, _ = numeric_oracle(env, elab(session, "2 + 2 = 4"))
        assert ok

    def test_scalar_eq_false_is_rejected(self, session, env):
        ok, reason = numeric_oracle(env, elab(session, "2 + 2 = 5"))
        assert not ok
        assert reason  # honest explanation
        ok, _ = numeric_oracle(env, elab(session, "sin(1) = 1"))
        assert not ok

    def test_function_eq_pythagorean(self, session, env):
        prop = elab(session,
                    "(fun (x : ℝ) => sin(x)^2 + cos(x)^2)"
                    " = (fun (x : ℝ) => (1 : ℝ))")
        ok, reason = numeric_oracle(env, prop)
        assert ok, reason

    def test_function_eq_false(self, session, env):
        prop = elab(session,
                    "(fun (x : ℝ) => sin(x)) = (fun (x : ℝ) => x)")
        ok, reason = numeric_oracle(env, prop)
        assert not ok
        assert "differ" in reason

    def test_function_eq_with_poles_skips_points(self, session, env):
        # sinc(x) == sin(x)/x has a pole at a sample point? [-3,3] grid does
        # not hit 0 exactly, but 1/x vs itself exercises skipping around
        # heavy cancellation; identical functions must verify.
        prop = elab(session,
                    "(fun (x : ℝ) => sin(x)/x) = (fun (x : ℝ) => sin(x)/x)")
        ok, reason = numeric_oracle(env, prop)
        assert ok, reason

    def test_unevaluable_function_eq_rejected(self, session, env):
        # deriv is opaque: no sample point evaluates -> honest rejection
        prop = elab(session, "deriv(sin) = cos")
        ok, reason = numeric_oracle(env, prop)
        assert not ok
        assert reason

    def test_le_lt(self, session, env):
        ok, _ = numeric_oracle(env, elab(session, "(0 : ℝ) < 1"))
        assert ok
        ok, _ = numeric_oracle(env, elab(session, "(1 : ℝ) <= 1"))
        assert ok
        ok, reason = numeric_oracle(env, elab(session, "(1 : ℝ) < 0"))
        assert not ok
        ok, reason = numeric_oracle(env, elab(session, "(2 : ℝ) <= 1"))
        assert not ok

    def test_lt_within_tolerance_not_certified(self, env):
        # a strict inequality that only holds by 1e-15 is not certifiable
        prop = mk_app(Const("Real.lt"), real_lit(0),
                      real_lit(Fraction(1, 10 ** 15)))
        ok, reason = numeric_oracle(env, prop)
        assert not ok
        assert "tolerance" in reason

    def test_limit_sinc(self, session, env):
        prop = elab(session, "HasLimitAt(fun (x : ℝ) => sin(x)/x, 0, 1)")
        ok, reason = numeric_oracle(env, prop)
        assert ok, reason

    def test_limit_wrong_value_rejected(self, session, env):
        prop = elab(session, "HasLimitAt(fun (x : ℝ) => sin(x)/x, 0, 2)")
        ok, reason = numeric_oracle(env, prop)
        assert not ok

    def test_unsupported_prop_rejected(self, session, env):
        ok, reason = numeric_oracle(env, elab(session, "Continuous(sin)"))
        assert not ok
        assert reason

    def test_session_wires_numeric_oracle(self, session):
        assert "numeric" in session.oracles
