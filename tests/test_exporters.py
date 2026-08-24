"""Tests for the exporters subsystem (epsilon.exporters): LaTeX, MathML,
Markdown, JSON."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from epsilon.kernel.env import DeclKind, STATUS_ORDER
from epsilon.kernel.term import (
    App, Const, Lam, Lit, MVar, Pi, Sort, StrLit, Var, mk_app, real_lit,
)
from epsilon.project import STATUS_LABELS, Session

from epsilon.exporters.latex import (
    LatexExportError, decl_to_latex, module_to_latex, term_to_latex,
)
from epsilon.exporters.mathml import (
    MathMLExportError, term_to_mathml,
)
from epsilon.exporters.markdown import module_to_markdown
from epsilon.exporters.json_export import (
    JsonExportError, module_to_json, term_from_json, term_to_json,
)


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


def elab_prop(session: Session, src: str):
    """Elaborate a surface expression as a Prop (contract recipe)."""
    from epsilon.elab.elaborator import Elaborator
    from epsilon.syntax.parser import parse_expression
    el = Elaborator(session.env, session.ctx)
    t = el.elab_prop(parse_expression(src, extra_ops=dict(session.extra_ops)))
    return el.finalize(t)


def _deep_eq(a, b) -> bool:
    """Structural equality that (unlike `Term.__eq__`) also compares
    `Pi.implicit` - the dataclass marks that field `compare=False` since it
    is irrelevant to definitional equality of the type, but a JSON
    interoperability round-trip must not silently drop it."""
    if type(a) is not type(b):
        return False
    if isinstance(a, Pi):
        return (a.name == b.name and a.implicit == b.implicit
                and _deep_eq(a.ty, b.ty) and _deep_eq(a.body, b.body))
    if isinstance(a, (Lam,)):
        return a.name == b.name and _deep_eq(a.ty, b.ty) and _deep_eq(a.body, b.body)
    if isinstance(a, App):
        return _deep_eq(a.fn, b.fn) and _deep_eq(a.arg, b.arg)
    return a == b


def _all_export_decls(env):
    """Every declaration name of a kind the exporters render (mirrors the
    filtering `json_export.module_to_json` / `Session.definition_list`
    already apply)."""
    kinds = (DeclKind.THEOREM, DeclKind.AXIOM, DeclKind.DEFINITION,
            DeclKind.OPAQUE, DeclKind.INDUCTIVE)
    return [n for n in env.order if env.decls[n].kind in kinds]


# ---------------------------------------------------------------------------
# latex: golden strings for representative terms
# ---------------------------------------------------------------------------

class TestLatexTerms:
    def test_arithmetic_and_precedence(self, session, env):
        assert term_to_latex(env, elab(session, "2 + 3 * 4")) == \
            "2 + 3 \\cdot 4"
        assert term_to_latex(env, elab(session, "(2 + 3) * 4")) == \
            "\\left(2 + 3\\right) \\cdot 4"

    def test_division_is_a_frac(self, session, env):
        assert term_to_latex(env, elab(session, "1/2 + 1/4")) == \
            "\\frac{1}{2} + \\frac{1}{4}"

    def test_literal_fraction_and_negative(self, env):
        assert term_to_latex(env, Lit(Fraction(-3, 4), "Rat")) == \
            "-\\frac{3}{4}"
        assert term_to_latex(env, Lit(Fraction(-5), "Int")) == "-5"

    def test_power(self, session, env):
        assert term_to_latex(env, elab(session, "2 ^ 10")) == "2^{10}"

    def test_power_parenthesizes_compound_base(self, session, env):
        assert term_to_latex(env, elab(session, "(1 + 2) ^ 3")) == \
            "\\left(1 + 2\\right)^{3}"

    def test_trig_function_and_pi(self, session, env):
        # `sin`/`π` are prelude aliases (Const("sin")/Const("π")) for
        # Real.sin/Real.pi, not delta-reduced before printing - this
        # exercises that alias recognition, not just the canonical names.
        assert term_to_latex(env, elab(session, "sin(π)")) == \
            "\\sin\\!\\left(\\pi\\right)"

    def test_sqrt(self, session, env):
        assert term_to_latex(env, elab(session, "sqrt(2)")) == "\\sqrt{2}"

    def test_forall(self, session, env):
        t = elab_prop(session, "∀ (x : ℝ), x = x")
        assert term_to_latex(env, t) == "\\forall (x : \\mathbb{R}),\\ x = x"

    def test_exists(self, session, env):
        t = elab_prop(session, "∃ (x : ℝ), x = 0")
        assert term_to_latex(env, t) == "\\exists (x : \\mathbb{R}),\\ x = 0"

    def test_land_and_leq(self, session, env):
        t = elab_prop(session, "(0:ℝ) ≤ 1 ∧ 1 ≤ 2")
        assert term_to_latex(env, t) == "0 \\leq 1 \\land 1 \\leq 2"

    def test_lor_and_lnot(self, session, env):
        t = elab_prop(session, "∀ (P : Prop), ¬P ∨ P")
        assert term_to_latex(env, t) == \
            "\\forall (P : \\mathrm{Prop}),\\ \\lnot P \\lor P"

    def test_neq(self, session, env):
        t = elab_prop(session, "(1:ℝ) ≠ 2")
        assert term_to_latex(env, t) == "1 \\neq 2"

    def test_iff(self, session, env):
        t = elab_prop(session, "∀ (P Q : Prop), P ↔ Q")
        assert term_to_latex(env, t) == (
            "\\forall (P : \\mathrm{Prop}),\\ \\forall (Q : \\mathrm{Prop}),"
            "\\ P \\leftrightarrow Q")

    def test_arrow(self, session, env):
        t = elab_prop(session, "∀ (P Q : Prop), P → Q")
        assert term_to_latex(env, t) == (
            "\\forall (P : \\mathrm{Prop}),\\ \\forall (Q : \\mathrm{Prop}),"
            "\\ P \\to Q")

    def test_subscripted_name(self, session, env):
        t = elab_prop(session, "∀ (a1 : ℝ), a1 = a1")
        assert term_to_latex(env, t) == \
            "\\forall (a_{1} : \\mathbb{R}),\\ a_{1} = a_{1}"

    def test_lambda(self, session, env):
        t = elab(session, "fun (x : ℝ) => x + 1")
        assert term_to_latex(env, t) == "\\lambda (x : \\mathbb{R}),\\ x + 1"

    def test_unary_neg(self, session, env):
        t = elab_prop(session, "∀ (x : ℝ), -x + x = 0")
        assert term_to_latex(env, t) == \
            "\\forall (x : \\mathbb{R}),\\ -x + x = 0"

    def test_integral(self, session, env):
        t = elab(session, "integral(sin, 0, π)")
        assert term_to_latex(env, t) == \
            "\\int_{0}^{\\pi} \\sin\\!\\left(x\\right) \\, dx"

    def test_limit(self, session, env):
        t = elab(session, "limit(fun (x : ℝ) => x, 0)")
        assert term_to_latex(env, t) == "\\lim_{x \\to 0} x"

    def test_has_limit_at(self, session, env):
        t = elab_prop(session, "HasLimitAt(fun (x : ℝ) => sin(x)/x, 0, 1)")
        assert term_to_latex(env, t) == \
            "\\lim_{x \\to 0} \\frac{\\sin\\!\\left(x\\right)}{x} = 1"

    def test_blackboard_bold_numeric_types(self, env):
        assert term_to_latex(env, Const("Nat")) == "\\mathbb{N}"
        assert term_to_latex(env, Const("Int")) == "\\mathbb{Z}"
        assert term_to_latex(env, Const("Rat")) == "\\mathbb{Q}"
        assert term_to_latex(env, Const("Real")) == "\\mathbb{R}"
        assert term_to_latex(env, Const("Complex")) == "\\mathbb{C}"
        # prelude's unicode aliases (def ℝ := Real, ...) render identically
        assert term_to_latex(env, Const("ℝ")) == "\\mathbb{R}"
        assert term_to_latex(env, Const("ℕ")) == "\\mathbb{N}"

    def test_sort(self, env):
        assert term_to_latex(env, Sort(0)) == "\\mathrm{Prop}"
        assert term_to_latex(env, Sort(1)) == "\\mathrm{Type}"
        assert term_to_latex(env, Sort(2)) == "\\mathrm{Type}\\ 1"

    def test_string_literal(self, env):
        assert term_to_latex(env, StrLit("hi")) == "\\text{``hi''}"

    def test_generic_const_headed_application(self, env):
        t = mk_app(Const("congrArg"), real_lit(1), real_lit(2))
        assert term_to_latex(env, t) == \
            "\\operatorname{congrArg}\\left(1, 2\\right)"

    def test_generic_var_headed_application(self, env):
        # a locally-bound function `f` applied to an argument
        t = App(Var(0), real_lit(5))
        assert term_to_latex(env, t, names=["f"]) == "f\\left(5\\right)"

    def test_mvar_is_rejected_not_guessed_at(self, env):
        with pytest.raises(LatexExportError):
            term_to_latex(env, MVar(3))


# ---------------------------------------------------------------------------
# latex: declarations / module document
# ---------------------------------------------------------------------------

class TestLatexDecl:
    def test_theorem_block_has_status_comment_and_env(self, env):
        out = decl_to_latex(env, "Nat.add_comm")
        status = env.verification_status("Nat.add_comm")
        assert f"% Nat.add_comm \u2014 {STATUS_LABELS[status]}" in out
        assert "\\begin{theorem}[Nat.add\\_comm]" in out
        assert "\\end{theorem}" in out
        assert "\\[" in out and "\\]" in out

    def test_theorem_doc_comment_is_visible_prose(self, env):
        out = decl_to_latex(env, "Nat.add_comm")
        assert "\\textit{" in out
        assert "Commutativity of addition" in out

    def test_axiom_is_never_labeled_as_proven(self, env):
        """Verification-status honesty (section 27): an axiom is assumed,
        not proven, so it must never carry a proven/symbolic/numeric/
        heuristic STATUS_LABELS badge - only theorems get one."""
        out = decl_to_latex(env, "Real.add_comm")
        assert "\\begin{axiom}[Real.add\\_comm]" in out
        assert "assumed; not proven" in out
        for label in STATUS_LABELS.values():
            assert label not in out

    def test_definition_shows_value(self, env):
        out = decl_to_latex(env, "sqrt")
        assert "\\begin{definition}[sqrt]" in out
        assert ":=" in out
        assert "\\sqrt{\\cdot}" in out  # bare (unapplied) Real.sqrt value
        for label in STATUS_LABELS.values():
            assert label not in out

    def test_distinct_namespaces_get_distinct_titles(self, env):
        """Real.add_comm / Int.add_comm / Rat.add_comm must not collapse
        onto one amsthm title."""
        real = decl_to_latex(env, "Real.add_comm")
        intg = decl_to_latex(env, "Int.add_comm")
        assert "[Real.add\\_comm]" in real
        assert "[Int.add\\_comm]" in intg
        assert real != intg

    def test_unknown_declaration_raises(self, env):
        from epsilon.kernel.env import KernelError
        with pytest.raises(KernelError):
            decl_to_latex(env, "NoSuchDeclaration")


class TestLatexModule:
    @staticmethod
    def _assert_balanced(doc: str) -> None:
        depth = 0
        for ch in doc:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                assert depth >= 0, "unbalanced closing brace"
        assert depth == 0, "unbalanced braces overall"

        stack = []
        for kind, envname in re.findall(r"\\(begin|end)\{([a-zA-Z*]+)\}", doc):
            if kind == "begin":
                stack.append(envname)
            else:
                assert stack and stack[-1] == envname, \
                    f"mismatched \\end{{{envname}}}"
                stack.pop()
        assert not stack, f"unclosed environments: {stack}"

    def test_document_preamble_and_structure(self, session):
        doc = module_to_latex(session, "algebra")
        assert doc.startswith("\\documentclass{article}")
        assert "\\usepackage{amsmath}" in doc
        assert "\\usepackage{amssymb}" in doc
        assert "\\usepackage{amsthm}" in doc
        assert doc.count("\\begin{document}") == 1
        assert doc.count("\\end{document}") == 1
        assert doc.index("\\begin{document}") < doc.index("\\end{document}")
        self._assert_balanced(doc)

    def test_sections_present_for_algebra(self, session):
        doc = module_to_latex(session, "algebra")
        assert "\\section*{Axioms}" in doc
        assert "\\section*{Theorems}" in doc  # add_comm_three is proven there

    def test_whole_environment_is_well_balanced(self, session):
        # module=None: every loaded declaration, including kernel core -
        # the harder structural stress test.
        doc = module_to_latex(session, None)
        self._assert_balanced(doc)
        assert doc.count("\\begin{document}") == 1

    def test_empty_module_still_produces_a_document(self, session):
        doc = module_to_latex(session, "no-such-module")
        assert doc.startswith("\\documentclass{article}")
        self._assert_balanced(doc)


# ---------------------------------------------------------------------------
# mathml
# ---------------------------------------------------------------------------

def _mml_root(s: str) -> ET.Element:
    root = ET.fromstring(s)  # raises on malformed XML
    assert root.tag == "{http://www.w3.org/1998/Math/MathML}math"
    return root


class TestMathML:
    def test_well_formed_for_representative_terms(self, session, env):
        srcs = [
            ("2 + 3 * 4", False), ("1/2 + 1/4", False), ("2 ^ 10", False),
            ("sin(π)", False), ("sqrt(2)", False),
            ("∀ (x : ℝ), x = x", True), ("∃ (x : ℝ), x = 0", True),
            ("(0:ℝ) ≤ 1 ∧ 1 ≤ 2", True),
            ("integral(sin, 0, π)", False),
            ("HasLimitAt(fun (x : ℝ) => sin(x)/x, 0, 1)", True),
            ("fun (x : ℝ) => x + 1", False),
        ]
        for src, prop in srcs:
            t = elab_prop(session, src) if prop else elab(session, src)
            _mml_root(term_to_mathml(env, t))

    def test_division_uses_mfrac(self, session, env):
        t = elab(session, "1/2 + 1/4")
        root = _mml_root(term_to_mathml(env, t))
        assert root.find(".//{*}mfrac") is not None

    def test_power_uses_msup(self, session, env):
        t = elab(session, "2 ^ 10")
        root = _mml_root(term_to_mathml(env, t))
        assert root.find(".//{*}msup") is not None

    def test_sqrt_uses_msqrt(self, session, env):
        t = elab(session, "sqrt(2)")
        root = _mml_root(term_to_mathml(env, t))
        assert root.find(".//{*}msqrt") is not None

    def test_subscripted_name_uses_msub(self, session, env):
        t = elab_prop(session, "∀ (a1 : ℝ), a1 = a1")
        root = _mml_root(term_to_mathml(env, t))
        assert root.find(".//{*}msub") is not None

    def test_double_struck_numeric_types(self, env):
        """Blackboard bold comes out as the character, not as a variant.

        `mathvariant="double-struck"` is deprecated in MathML Core and
        browsers honour it inconsistently — ℝ rendered as an italic R. The
        literal character always renders.
        """
        root = _mml_root(term_to_mathml(env, Const("Real")))
        mi = root.find(".//{*}mi")
        assert mi is not None
        assert mi.text == "ℝ"
        assert mi.get("mathvariant") is None
        # prelude alias renders the same way
        root2 = _mml_root(term_to_mathml(env, Const("ℝ")))
        assert root2.find(".//{*}mi").text == "ℝ"

    @pytest.mark.parametrize("name,char", [
        ("Nat", "ℕ"), ("Int", "ℤ"), ("Rat", "ℚ"), ("Real", "ℝ"),
        ("Complex", "ℂ"),
    ])
    def test_every_numeric_type_renders_as_its_character(self, env, name, char):
        root = _mml_root(term_to_mathml(env, Const(name)))
        assert root.find(".//{*}mi").text == char

    def test_string_literal_uses_mtext(self, env):
        root = _mml_root(term_to_mathml(env, StrLit("hi")))
        mt = root.find(".//{*}mtext")
        assert mt is not None and mt.text == '"hi"'

    def test_integral_uses_msubsup(self, session, env):
        t = elab(session, "integral(sin, 0, π)")
        root = _mml_root(term_to_mathml(env, t))
        assert root.find(".//{*}msubsup") is not None

    def test_mvar_is_rejected_not_guessed_at(self, env):
        with pytest.raises(MathMLExportError):
            term_to_mathml(env, MVar(3))

    def test_full_stdlib_sweep_is_well_formed(self, env):
        """Every stdlib declaration's type, across every loaded module
        (including kernel core), round-trips through ET.fromstring."""
        n = 0
        for name in _all_export_decls(env):
            root = _mml_root(term_to_mathml(env, env.decls[name].type))
            assert root is not None
            n += 1
        assert n > 100  # sanity: we actually exercised a lot of content


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------

class TestMarkdown:
    def test_header_and_sections(self, session):
        md = module_to_markdown(session, "algebra")
        assert md.startswith("# algebra")
        assert "## Definitions" in md or "## Axioms" in md
        assert "## Theorems" in md

    def test_status_badges_use_project_status_labels(self, session):
        md = module_to_markdown(session, "algebra")
        # add_comm_three is a real proof in algebra.epsl (see the .epsl
        # source): its status label must be the exact project string.
        assert STATUS_LABELS["proven"] in md

    def test_every_status_label_reachable_across_full_env(self, session):
        """Sanity: STATUS_LABELS is actually being used to render the
        statuses Session computes, not a hand-rolled duplicate string."""
        md = module_to_markdown(session, None)
        seen_any = False
        for label in STATUS_LABELS.values():
            if label in md:
                seen_any = True
        assert seen_any

    def test_statements_are_inline_code_pp_output(self, session):
        from epsilon.elab.pp import pp
        md = module_to_markdown(session, "algebra")
        d = session.env.decls["Real.add_comm"]
        expected = pp(session.env, d.type)
        assert f"`{expected}`" in md

    def test_doc_comments_included(self, session):
        # algebra.epsl's own declarations carry no doc comments; prelude's
        # do (e.g. `/-- Symmetry of equality. -/ theorem Eq.symm ...`).
        md = module_to_markdown(session, "prelude")
        assert "Symmetry of equality." in md
        assert "Commutativity of addition on ℕ, proved by induction." in md

    def test_theorem_axiom_dependencies_listed(self, session):
        md = module_to_markdown(session, "algebra")
        # add_comm_three depends on Real.add_comm / Real.add_assoc
        idx = md.find("add_comm_three")
        assert idx != -1
        tail = md[idx:idx + 800]
        assert "**Axioms used:**" in tail
        assert "Real.add_comm" in tail

    def test_axioms_never_show_a_theorem_status_badge(self, session):
        """Verification-status honesty: the Axioms section lists axioms as
        assumed, never with a proven/symbolic/... badge (those apply only
        to theorems)."""
        md = module_to_markdown(session, "algebra")
        axioms_start = md.index("## Axioms")
        axioms_end = md.index("## Theorems") if "## Theorems" in md else len(md)
        section = md[axioms_start:axioms_end]
        assert "*axiom*" in section
        for label in STATUS_LABELS.values():
            assert label not in section

    def test_empty_module_is_handled(self, session):
        md = module_to_markdown(session, "no-such-module")
        assert "No declarations" in md

    def test_whole_environment_does_not_crash(self, session):
        md = module_to_markdown(session, None)
        assert "## Theorems" in md
        assert len(md) > 0


# ---------------------------------------------------------------------------
# json_export
# ---------------------------------------------------------------------------

class TestJsonExportRoundTrip:
    def test_schema_shapes(self):
        assert term_to_json(Var(2)) == {"k": "var", "idx": 2}
        assert term_to_json(Const("Real.sin")) == \
            {"k": "const", "name": "Real.sin"}
        assert term_to_json(Sort(1)) == {"k": "sort", "level": 1}
        assert term_to_json(StrLit("hi")) == {"k": "str", "v": "hi"}
        assert term_to_json(Lit(Fraction(3, 4), "Rat")) == \
            {"k": "lit", "num": 3, "den": 4, "ty": "Rat"}
        assert term_to_json(Lit(Fraction(-5), "Int")) == \
            {"k": "lit", "num": -5, "den": 1, "ty": "Int"}
        j = term_to_json(App(Const("f"), Var(0)))
        assert j == {"k": "app", "fn": {"k": "const", "name": "f"},
                    "arg": {"k": "var", "idx": 0}}
        j = term_to_json(Lam("x", Const("Real"), Var(0)))
        assert j["k"] == "lam" and j["implicit"] is False
        j = term_to_json(Pi("x", Const("Real"), Var(0), implicit=True))
        assert j["k"] == "pi" and j["implicit"] is True

    def test_round_trip_basic_terms(self):
        terms = [
            Var(0), Const("Real.pi"), Sort(0), Sort(1), StrLit("epsilon"),
            Lit(Fraction(7), "Nat"), Lit(Fraction(-3, 8), "Rat"),
            App(Const("f"), Const("g")),
            Lam("x", Const("Real"), Var(0)),
            Pi("x", Const("Real"), Var(0), implicit=False),
            Pi("A", Sort(1), Var(0), implicit=True),
        ]
        for t in terms:
            assert _deep_eq(term_from_json(term_to_json(t)), t)

    def test_implicit_flag_is_preserved_losslessly(self):
        """`Pi.implicit` is marked `compare=False` on the kernel dataclass
        (irrelevant to definitional type-equality), so a naive `==` round
        trip check would not actually prove this is lossless."""
        explicit = Pi("A", Sort(1), Var(0), implicit=False)
        implicit = Pi("A", Sort(1), Var(0), implicit=True)
        assert explicit == implicit  # kernel's own notion of equality...
        # ... but the JSON encodings, and a strict structural check, differ:
        assert term_to_json(explicit) != term_to_json(implicit)
        assert term_from_json(term_to_json(implicit)).implicit is True
        assert term_from_json(term_to_json(explicit)).implicit is False

    def test_round_trip_every_stdlib_theorem_statement(self, env):
        """Contract requirement: round-trip test on every stdlib theorem
        statement (Session().env)."""
        names = [n for n in env.order if env.decls[n].kind == DeclKind.THEOREM]
        assert len(names) > 10
        for name in names:
            t = env.decls[name].type
            back = term_from_json(term_to_json(t))
            assert _deep_eq(back, t), f"round-trip mismatch for {name}"

    def test_round_trip_every_stdlib_declaration_type_and_value(self, env):
        """Broader sweep: every exportable declaration's type (and value,
        where present) across every loaded module, including core."""
        n = 0
        for name in _all_export_decls(env):
            d = env.decls[name]
            assert _deep_eq(term_from_json(term_to_json(d.type)), d.type)
            if d.value is not None:
                assert _deep_eq(term_from_json(term_to_json(d.value)), d.value)
            n += 1
        assert n > 100

    def test_mvar_is_rejected_not_guessed_at(self):
        with pytest.raises(JsonExportError):
            term_to_json(MVar(1))

    def test_malformed_json_is_rejected(self):
        with pytest.raises(JsonExportError):
            term_from_json({"k": "not-a-real-kind"})
        with pytest.raises(JsonExportError):
            term_from_json({"k": "var"})  # missing "idx"
        with pytest.raises(JsonExportError):
            term_from_json({"nope": "no k field at all"})
        with pytest.raises(JsonExportError):
            term_from_json({"k": "lit", "num": 1, "den": 0, "ty": "Rat"})


class TestModuleToJson:
    def test_is_json_serializable(self, session):
        mj = module_to_json(session, "algebra")
        json.dumps(mj)  # must not raise

    def test_top_level_shape(self, session):
        mj = module_to_json(session, "algebra")
        assert set(mj.keys()) == {"epsilon_version", "language_version",
                                  "module", "decls"}
        assert mj["module"] == "algebra"
        assert isinstance(mj["decls"], list) and mj["decls"]

    def test_decl_shape_and_term_round_trips(self, session):
        mj = module_to_json(session, "algebra")
        by_name = {d["name"]: d for d in mj["decls"]}
        d = by_name["Real.add_comm"]
        assert d["kind"] == "axiom"
        t = term_from_json(d["type"])
        assert _deep_eq(t, session.env.decls["Real.add_comm"].type)

    def test_theorem_gets_status_axiom_and_definition_do_not(self, session):
        """Verification-status honesty (section 27): only THEOREM entries
        carry a status/status_label; an axiom is assumed (not proven) and
        a definition is not a truth-claim, so both must report status:
        null rather than something that could be misread as a proof."""
        mj = module_to_json(session, "algebra")
        by_name = {d["name"]: d for d in mj["decls"]}

        axiom = by_name["Real.add_comm"]
        assert axiom["kind"] == "axiom"
        assert axiom["status"] is None
        assert axiom["status_label"] is None
        assert axiom["axioms"] == []

        theorem = by_name["Real.add_comm_three"]
        assert theorem["kind"] == "theorem"
        assert theorem["status"] in STATUS_ORDER
        assert theorem["status_label"] == STATUS_LABELS[theorem["status"]]
        assert "Real.add_comm" in theorem["axioms"]

    def test_module_none_covers_everything_and_filters_locals(self, session):
        mj = module_to_json(session, None)
        assert mj["module"] is None
        names = {d["name"] for d in mj["decls"]}
        assert "Real.add_comm" in names
        assert not any("\u2726" in n for n in names)  # no LOCAL_MARK leakage

    def test_module_filter_is_exact(self, session):
        mj_alg = module_to_json(session, "algebra")
        assert all(d["module"] == "algebra" for d in mj_alg["decls"])


# ---------------------------------------------------------------------------
# package wiring
# ---------------------------------------------------------------------------

class TestPackageInit:
    def test_public_api_importable_without_python_ast(self):
        """python_ast.py belongs to a different agent and may not exist in
        this checkout; the package must still import and expose the rest
        of the contract's public functions."""
        import epsilon.exporters as ex
        for name in ("term_to_latex", "decl_to_latex", "module_to_latex",
                    "term_to_mathml", "module_to_markdown",
                    "term_to_json", "term_from_json", "module_to_json"):
            assert hasattr(ex, name)
            assert name in ex.__all__
