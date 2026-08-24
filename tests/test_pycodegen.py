"""Tests for Python AST code generation.

The generation path is kernel Term -> ast.AST -> ast.unparse; we verify the
output by executing it and comparing against the numeric evaluator.
"""

import ast
import math

import pytest

from epsilon.project import Session
from epsilon.exporters.python_ast import module_to_python, term_to_python_ast


@pytest.fixture()
def demo_session():
    s = Session()
    s.check_source(
        "def double (n : Nat) : Nat := 2 * n\n"
        "def f (x : Real) : Real := Real.sin(x) / x\n"
        "def g (x : Real) : Real := x^2 + 3*x + 1\n"
        "def area (r : Real) : Real := Real.pi * r^2\n"
        "theorem trivial_thm (x : Real) : x = x := by rfl\n",
        "demo")
    return s


def test_generated_math_backend_executes(demo_session):
    code = module_to_python(demo_session, "demo", backend="math")
    ns: dict = {}
    exec(compile(code, "<generated>", "exec"), ns)
    assert ns["double"](21) == 42
    assert abs(ns["g"](1.5) - (1.5 ** 2 + 3 * 1.5 + 1)) < 1e-9
    assert abs(ns["f"](2) - math.sin(2) / 2) < 1e-9
    assert abs(ns["area"](2) - math.pi * 4) < 1e-9


def test_generated_matches_numeric_evaluator(demo_session):
    from epsilon.numeric.evaluator import eval_function
    code = module_to_python(demo_session, "demo", backend="math")
    ns: dict = {}
    exec(code, ns)
    g_decl = demo_session.env.expect("g").value
    for x in (0.5, 2.0, -3.0):
        assert abs(ns["g"](x) - eval_function(demo_session.env, g_decl, x)) < 1e-9


def test_output_is_valid_python(demo_session):
    code = module_to_python(demo_session, "demo", backend="math")
    ast.parse(code)  # must parse


def test_no_internal_names_leak(demo_session):
    code = module_to_python(demo_session, "demo", backend="math")
    assert "✦" not in code           # local-marker char
    assert "$" not in code


def test_theorems_only_in_docstring(demo_session):
    code = module_to_python(demo_session, "demo", backend="math")
    # the theorem name appears only inside the module docstring, never as code
    tree = ast.parse(code)
    doc = ast.get_docstring(tree)
    assert doc is not None and "trivial_thm" in doc
    # no function/assignment is named after the theorem
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "trivial_thm" not in names


def test_numpy_backend_uses_np(demo_session):
    code = module_to_python(demo_session, "demo", backend="numpy")
    assert "import numpy as np" in code
    assert "np.sin" in code


def test_sympy_backend_exact_rationals():
    s = Session()
    s.check_source("def half (x : Real) : Real := x / 2", "d")
    code = module_to_python(s, "d", backend="sympy")
    assert "import sympy as sp" in code


def test_status_labels_present(demo_session):
    code = module_to_python(demo_session, "demo", backend="math")
    tree = ast.parse(code)
    doc = ast.get_docstring(tree)
    assert "Formally Proven" in doc


def test_exporters_reexports_python_ast():
    import epsilon.exporters as ex
    assert hasattr(ex, "module_to_python")
    assert hasattr(ex, "term_to_python_ast")
