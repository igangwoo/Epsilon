"""Notation must be syntactically explicit.

Each test here pins one rule: a symbol has a single syntactic role, and an
expression's meaning never depends on context that is invisible at the use
site (in particular, never on the *values* of its operands).
"""

import pytest

from epsilon.project import Session
from epsilon.syntax.parser import parse_expression, ParseError
from epsilon.syntax.lexer import tokenize, WORD_OPERATORS
from epsilon.syntax import sast as S


def _check(src, module="m"):
    return Session().check_source(src, module)


def _type_of(src):
    r = _check(f"#check {src}")
    msgs = [x.message for x in r.results if x.kind == "check"]
    assert msgs, [d.format() for d in r.diagnostics]
    return msgs[0].rsplit(" : ", 1)[1]


def _errors(src):
    return [d.message for d in _check(src).diagnostics if d.severity == "error"]


# ---------------------------------------------------------------------------
# word-shaped ASCII operators have exactly one role
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("word,symbol", sorted(WORD_OPERATORS.items()))
def test_word_operator_parses_as_its_symbol(word, symbol):
    """`a in b` must mean membership, not the application `a(in, b)`."""
    ascii_ast = parse_expression(f"a {word} b")
    uni_ast = parse_expression(f"a {symbol} b")
    assert isinstance(ascii_ast, S.SBinOp), \
        f"'{word}' parsed as {type(ascii_ast).__name__}, not an operator"
    assert ascii_ast.op == uni_ast.op == symbol


@pytest.mark.parametrize("word", sorted(WORD_OPERATORS))
def test_word_operator_lexes_as_a_symbol_token(word):
    toks = [t for t in tokenize(f"a {word} b") if t.kind != "EOF"]
    kinds = [t.kind for t in toks]
    assert kinds == ["IDENT", "SYM", "IDENT"], kinds


def test_membership_ascii_and_unicode_agree_semantically():
    src = ("def s : Set(Nat) := setOf(Nat, λ (n : Nat) => n = n)\n"
           "theorem a (x : Nat) (h : x ∈ s) : x in s := by exact h")
    assert _check(src).ok, _errors(src)


# ---------------------------------------------------------------------------
# division: the operator fixes the meaning, values never do
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("src", ["6 / 3", "7 / 2", "1 / 2", "8 / 4"])
def test_exact_division_always_yields_rationals(src):
    """The result type must not depend on whether the literals divide."""
    assert _type_of(src) == "ℚ"


@pytest.mark.parametrize("src", ["(6:Nat) / (3:Nat)", "(7:Nat) / (2:Nat)"])
def test_exact_division_on_annotated_naturals_is_still_rational(src):
    assert _type_of(src) == "ℚ"


@pytest.mark.parametrize("src", ["6 // 3", "7 // 2"])
def test_floor_division_yields_naturals(src):
    assert _type_of(src) == "ℕ"


def test_floor_division_computes():
    r = _check("#eval 7 // 2")
    assert [x.message for x in r.results if x.kind == "eval"] == ["3"]


def test_exact_division_computes():
    r = _check("#eval 7 / 2")
    assert [x.message for x in r.results if x.kind == "eval"] == ["7/2"]


def test_real_division_stays_real():
    assert _type_of("(1:Real) / 2") == "ℝ"


def test_floor_division_rejected_on_reals_with_guidance():
    errs = _errors("#check (1:Real) // 2")
    assert errs and "//" in errs[0] and "/" in errs[0]


def test_exact_division_where_natural_expected_suggests_floor_division():
    errs = _errors("def d : Nat := 6 / 3")
    assert errs and "//" in errs[0]


def test_modulo_still_integer_only():
    assert _type_of("7 % 2") == "ℕ"
    assert _errors("#check (1:Real) % 2")


# ---------------------------------------------------------------------------
# `=` relates elements, `↔` relates propositions
# ---------------------------------------------------------------------------

def test_equality_on_propositions_is_rejected_with_guidance():
    errs = _errors("theorem t (p q : Prop) : p = q := by sorry")
    assert errs and "↔" in errs[0]


def test_iff_on_propositions_is_accepted():
    assert _check("theorem t (p q : Prop) : p ↔ q := by sorry").ok


def test_equality_on_values_is_unaffected():
    assert _check("theorem t (a : Nat) : a = a := by rfl").ok


def test_bool_valued_equation_still_coerces_to_a_proposition():
    """`==` is decidable Bool equality and keeps its own role; a Bool in a
    proposition position still coerces, so rejecting `=` on Prop did not
    disturb it."""
    r = _check("theorem t : (2 == 2) := by decide")
    assert r.ok, [d.format() for d in r.diagnostics]


# ---------------------------------------------------------------------------
# precedence and roles that must not have regressed
# ---------------------------------------------------------------------------

def test_floor_division_has_multiplicative_precedence():
    e = parse_expression("a + b // c")
    assert isinstance(e, S.SBinOp) and e.op == "+"
    assert isinstance(e.rhs, S.SBinOp) and e.rhs.op == "//"


def test_line_comment_still_wins_over_floor_division():
    """`--` opens a comment; `//` must not have disturbed that."""
    toks = [t for t in tokenize("a -- // not code\n") if t.kind != "EOF"]
    assert [t.text for t in toks] == ["a"]


def test_conjunction_ascii_unaffected_by_floor_division():
    e = parse_expression("p /\\ q")
    assert isinstance(e, S.SBinOp) and e.op == "/\\"
