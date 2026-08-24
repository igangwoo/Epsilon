"""The CAS as the IDE's CAS pane uses it: source text in, labelled result out.

The status labels carry the product's central promise. A CAS answer is
symbolically verified and a sampled value is numerically verified; neither is
ever a formal proof, because the kernel is not involved in either.
"""

import pytest

from epsilon.cas.workbench import (CASRequestError, OPERATIONS, free_identifiers,
                                   parse_term, run)
from epsilon.project import Session
from epsilon.syntax.parser import parse_expression


@pytest.fixture(scope="module")
def sess():
    return Session()


def source(sess, term):
    from epsilon.elab.pp import pp
    return pp(sess.env, term)


# --------------------------------------------------------------------------
# free variables
# --------------------------------------------------------------------------

def test_free_identifiers_in_source_order():
    e = parse_expression("a * x + b")
    assert free_identifiers(e) == ["a", "x", "b"]


def test_unknown_identifiers_become_real_variables(sess):
    term, variables = parse_term(sess, "a * x + b")
    assert variables == ["a", "x", "b"]
    assert source(sess, term) == "a * x + b"


def test_known_names_are_not_treated_as_variables(sess):
    _, variables = parse_term(sess, "Real.sin(x) + Real.pi")
    assert variables == ["x"]


def test_an_expression_with_no_variables_still_elaborates(sess):
    term, variables = parse_term(sess, "2 + 3 * 4")
    assert variables == []
    assert term is not None


# --------------------------------------------------------------------------
# operations
# --------------------------------------------------------------------------

@pytest.mark.parametrize("op,expr,expected", [
    ("expand", "(x + 1) * (x - 1)", "x ^ 2 - 1"),
    ("simplify", "2*x + 3*x", "5 * x"),
    ("simplify", "x - x", "0"),
    ("derivative", "x^3", "3 * x ^ 2"),
    ("derivative", "Real.sin(x)", "Real.cos x"),
    ("integral", "2*x", "x ^ 2"),
    ("limit", "Real.sin(x) / x", "1"),
])
def test_operation_result(sess, op, expr, expected):
    r = run(sess, op, expr)
    assert source(sess, r.result) == expected


def test_solve_returns_every_root(sess):
    r = run(sess, "solve", "x^2 - 4")
    assert sorted(source(sess, t) for t in r.results) == ["-2", "2"]


def test_taylor_expansion(sess):
    r = run(sess, "taylor", "Real.exp(x)", point="0", order=3)
    text = source(sess, r.result)
    assert "1" in text and "x ^ 2" in text and "x ^ 3" in text


def test_evaluate_is_numeric_not_symbolic(sess):
    r = run(sess, "evaluate", "x^2 + 1", point="3")
    assert r.status == "numeric"
    assert source(sess, r.result) == "10"


# --------------------------------------------------------------------------
# status honesty (section 27)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("op,expr", [
    ("simplify", "x + x"), ("expand", "(x+1)^2"), ("derivative", "x^2"),
    ("integral", "x"), ("limit", "Real.sin(x)/x"), ("solve", "x - 1"),
])
def test_symbolic_operations_are_never_proven(sess, op, expr):
    assert run(sess, op, expr).status == "symbolic"


def test_no_operation_can_report_proven(sess):
    """There is no code path from the CAS pane to a formal-proof label."""
    import inspect
    from epsilon.cas import workbench
    assert '"proven"' not in inspect.getsource(workbench)


# --------------------------------------------------------------------------
# honest failure
# --------------------------------------------------------------------------

def test_unknown_operation_is_refused(sess):
    with pytest.raises(CASRequestError):
        run(sess, "teleport", "x")


def test_a_parse_error_is_reported_not_swallowed(sess):
    with pytest.raises(CASRequestError):
        run(sess, "simplify", "x +")


def test_empty_input_is_refused(sess):
    with pytest.raises(CASRequestError):
        run(sess, "simplify", "   ")


def test_an_unknown_antiderivative_is_admitted(sess):
    """Better to say so than to return something that is not one."""
    with pytest.raises(CASRequestError, match="antiderivative"):
        run(sess, "integral", "Real.tan(x) * Real.exp(x^2)")


def test_every_operation_is_described(sess):
    for op, (label, _needs_var, description) in OPERATIONS.items():
        assert label and description, op
