"""Lexer and parser tests."""

from fractions import Fraction

import pytest

from epsilon.syntax.lexer import tokenize, LexError
from epsilon.syntax.parser import parse_module, parse_expression, ParseError
from epsilon.syntax import sast as S


# ---------------------------------------------------------------------------
# lexer
# ---------------------------------------------------------------------------

def test_unicode_ascii_equivalence():
    # ∀ and forall, ∧ and /\ tokenize the same way
    a = parse_expression("∀ (p : Prop), p ∧ p")
    b = parse_expression("forall (p : Prop), p /\\ p")
    assert type(a) is type(b) is S.SForall


def test_numbers():
    toks = tokenize("42 3.14")
    nums = [t for t in toks if t.kind == "NUM"]
    assert nums[0].value == Fraction(42)
    assert nums[1].value == Fraction(157, 50)  # 3.14 exact


def test_string_escapes():
    toks = tokenize('"a\\nb"')
    s = [t for t in toks if t.kind == "STR"][0]
    assert s.value == "a\nb"


def test_line_comment():
    toks = tokenize("def x -- comment\n:= 1")
    assert not any(t.kind == "IDENT" and t.text == "comment" for t in toks)


def test_nested_block_comment():
    toks = tokenize("/- outer /- inner -/ still -/ def")
    assert [t.text for t in toks if t.kind == "KW"] == ["def"]


def test_doc_comment():
    toks = tokenize("/-- doc text -/ def f")
    docs = [t for t in toks if t.kind == "DOC"]
    assert docs and docs[0].value == "doc text"


def test_unterminated_comment_raises():
    with pytest.raises(LexError):
        tokenize("/- never closed")


# ---------------------------------------------------------------------------
# expression parsing / precedence
# ---------------------------------------------------------------------------

def test_precedence_mul_over_add():
    e = parse_expression("a + b * c")
    assert isinstance(e, S.SBinOp) and e.op == "+"
    assert isinstance(e.rhs, S.SBinOp) and e.rhs.op == "*"


def test_pow_right_associative():
    e = parse_expression("a ^ b ^ c")
    assert isinstance(e, S.SBinOp) and e.op == "^"
    assert isinstance(e.rhs, S.SBinOp) and e.rhs.op == "^"


def test_arrow_right_associative():
    e = parse_expression("a -> b -> c")
    assert isinstance(e, S.SArrow)
    assert isinstance(e.rhs, S.SArrow)


def test_application_vs_paren_call():
    juxta = parse_expression("f x y")
    call = parse_expression("f(x, y)")
    assert isinstance(juxta, S.SApp) and len(juxta.args) == 2
    assert isinstance(call, S.SApp) and len(call.args) == 2


def test_parse_error_has_position():
    with pytest.raises(ParseError) as ei:
        parse_expression("(a +")
    assert ei.value.line >= 1 and ei.value.col >= 1


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def test_parse_definition_with_doc():
    m = parse_module("/-- doc -/\ndef f (x : Nat) : Nat := x")
    assert isinstance(m.commands[0], S.CDef)
    assert m.commands[0].doc == "doc"


def test_parse_theorem_with_tactics():
    m = parse_module("theorem t (a : Nat) : a = a := by rfl")
    thm = m.commands[0]
    assert isinstance(thm, S.CTheorem)
    assert isinstance(thm.proof, S.TacticProof)
    assert thm.proof.tactics[0].name == "rfl"


def test_parse_induction_with_cases():
    src = ("theorem t (n : Nat) : n = n := by\n"
           "  induction n with\n"
           "  | zero => rfl\n"
           "  | succ k ih => rfl")
    m = parse_module(src)
    tac = m.commands[0].proof.tactics[0]
    assert tac.name == "induction"
    assert [c.ctor for c in tac.cases] == ["zero", "succ"]


def test_parse_calc():
    src = ("theorem t (a b : Nat) (h : a = b) : a = b := by\n"
           "  calc a = a := by rfl\n"
           "       _ = b := by exact h")
    m = parse_module(src)
    tac = m.commands[0].proof.tactics[0]
    assert tac.name == "calc"
    assert len(tac.calc_steps) == 2


def test_user_notation_usable_same_source():
    m = parse_module('infixl 65 "⊕" := Nat.add\ndef g : Nat := 3 ⊕ 4')
    assert isinstance(m.commands[0], S.CNotation)
    # the operator parses as a binary operator with the custom symbol; the
    # elaborator maps it to Nat.add via the registered notation
    g = m.commands[1]
    assert isinstance(g.value, S.SBinOp) and g.value.op == "⊕"


def test_layout_separates_commands():
    m = parse_module("def a : Nat := 1\ndef b : Nat := 2")
    assert len(m.commands) == 2


def test_spans_are_one_based():
    m = parse_module("def a : Nat := 1")
    assert m.commands[0].span[0] == 1


def test_plot_range_clause():
    m = parse_module("plot Real.sin, x ∈ [-6, 6]")
    plot = m.commands[0]
    assert isinstance(plot, S.CPlot) and plot.var == "x"
    assert plot.lo is not None and plot.hi is not None
