"""LaTeX exporter (product spec section 25: publication-quality export).

A precedence-aware printer that mirrors the operator tables in
``epsilon.elab.pp`` (read that file first - this module keeps the same
operator set, precedences and associativities) but emits LaTeX instead of
Epsilon's own Unicode surface syntax: ``\\frac`` for division, ``^{}`` for
powers, ``\\sin``/``\\cos``/... for the elementary Real functions, the
logical connectives, ``\\mathbb{}`` for the numeric towers, ``\\sqrt``,
``\\int`` for `integral(f, a, b)`, and ``\\lim`` for `limit`/`HasLimitAt`.

Two output shapes:
  * ``term_to_latex``  - one kernel `Term` as a LaTeX math fragment.
  * ``decl_to_latex``  - one declaration as an amsthm-style block, with its
    Epsilon verification status attached as a leading LaTeX *comment*
    (never as a claim inside the typeset math - section 27: an axiom is
    assumed, not proven, and a definition is not a truth-claim at all, so
    neither gets a proven/symbolic/numeric/heuristic label).
  * ``module_to_latex`` - a complete, compilable ``article`` document
    covering a module's definitions/axioms/theorems (from `Session`'s own
    lists, so this always matches what the IDE and CLI report).

Every public function is total over any *finished* kernel term (no
metavariables) - it never invents a parallel expression type; it only
walks `epsilon.kernel.term.Term`.
"""

from __future__ import annotations

import re
from fractions import Fraction
from typing import Callable, Optional

from ..kernel.env import Environment, DeclKind, KernelError
from ..kernel.term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar, unfold_app,
    has_var, lift,
)
from ..elab.context import LOCAL_MARK
from ..project import STATUS_LABELS


class LatexExportError(Exception):
    """A term/declaration cannot be rendered as LaTeX."""


# ---------------------------------------------------------------------------
# Identifier rendering: Greek letters, subscripts, escaping
# ---------------------------------------------------------------------------

_GREEK = {
    "α": "\\alpha", "β": "\\beta", "γ": "\\gamma", "δ": "\\delta",
    "ε": "\\varepsilon", "ζ": "\\zeta", "η": "\\eta", "θ": "\\theta",
    "ι": "\\iota", "κ": "\\kappa", "λ": "\\lambda", "μ": "\\mu",
    "ν": "\\nu", "ξ": "\\xi", "π": "\\pi", "ρ": "\\rho", "ς": "\\varsigma",
    "σ": "\\sigma", "τ": "\\tau", "υ": "\\upsilon", "φ": "\\varphi",
    "χ": "\\chi", "ψ": "\\psi", "ω": "\\omega",
    "Γ": "\\Gamma", "Δ": "\\Delta", "Θ": "\\Theta", "Λ": "\\Lambda",
    "Ξ": "\\Xi", "Π": "\\Pi", "Σ": "\\Sigma", "Φ": "\\Phi", "Ψ": "\\Psi",
    "Ω": "\\Omega",
}

# Other Unicode math glyphs the lexer accepts in source (see
# epsilon.syntax.lexer.UNI / SYMBOL_IDENTS) that can end up inside plain
# prose (doc comments) - translated to inline math for a compilable doc.
_PROSE_MATH = {
    "→": "\\to", "↔": "\\leftrightarrow", "∧": "\\land", "∨": "\\lor",
    "¬": "\\lnot", "≠": "\\neq", "≤": "\\leq", "≥": "\\geq",
    "∀": "\\forall", "∃": "\\exists", "∈": "\\in", "∉": "\\notin",
    "⊆": "\\subseteq", "×": "\\times", "∘": "\\circ", "√": "\\sqrt{}",
    "∞": "\\infty", "⊤": "\\top", "⊥": "\\bot", "∅": "\\emptyset",
    "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}", "ℚ": "\\mathbb{Q}",
    "ℝ": "\\mathbb{R}", "ℂ": "\\mathbb{C}", "Ω": "\\Omega",
    "∫": "\\int", "≈": "\\approx",
}
_PROSE_MATH.update({g: cmd for g, cmd in _GREEK.items()})

_SUBSCRIPT_CHARS = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9", "ₐ": "a", "ₑ": "e",
    "ᵢ": "i", "ⱼ": "j", "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n",
    "ₚ": "p", "ₛ": "s", "ₜ": "t",
}
_TRAILING_SUB_RE = re.compile(
    r"^(.+?)_?([0-9]+|[" + "".join(_SUBSCRIPT_CHARS) + r"]+)$")

_LATEX_SPECIAL_CHARS = {
    "\\": r"\textbackslash{}", "_": r"\_", "$": r"\$", "%": r"\%",
    "#": r"\#", "&": r"\&", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_TRANSLATE = str.maketrans(_LATEX_SPECIAL_CHARS)


def _split_subscript(name: str) -> tuple[str, Optional[str]]:
    """Split a trailing numeric/subscript-glyph suffix, e.g. "a1"/"a_1" ->
    ("a", "1"), for rendering as LaTeX `a_{1}`. Names without such a
    suffix (including ordinary snake_case names like "add_comm") pass
    through unchanged."""
    m = _TRAILING_SUB_RE.match(name)
    if not m:
        return name, None
    base, sub = m.group(1), m.group(2)
    sub = "".join(_SUBSCRIPT_CHARS.get(c, c) for c in sub)
    return base, sub


def _escape_text(s: str) -> str:
    """Escape plain text for LaTeX text mode (titles, identifiers)."""
    return s.translate(_LATEX_TRANSLATE)


def _escape_prose(s: str) -> str:
    """Render doc-comment prose for a compilable document: escape LaTeX
    specials, drop recognized math glyphs into inline `$...$`, and quietly
    drop any other non-ASCII character rather than emit something
    ``inputenc`` would reject. Stdlib doc comments freely mix in symbols
    like δ, ε, ℕ, ∫; this keeps `module_to_latex`'s output compilable
    without a Unicode-aware LaTeX engine."""
    s = re.sub(r"\s+", " ", s).strip()
    out: list[str] = []
    for ch in s:
        if ch in _PROSE_MATH:
            out.append(f"${_PROSE_MATH[ch]}$")
        elif ch in _LATEX_SPECIAL_CHARS:
            out.append(_LATEX_SPECIAL_CHARS[ch])
        elif ord(ch) < 128:
            out.append(ch)
        # else: unmapped Unicode - drop rather than break the build
    return "".join(out)


def _latex_ident(name: str, call_style: str = "mathit") -> str:
    """LaTeX for a bound-variable or constant display name."""
    base = name.split(LOCAL_MARK)[0] or "x"
    if base in _GREEK:
        return _GREEK[base]
    stem, sub = _split_subscript(base)
    stem = stem or "x"
    if stem in _GREEK:
        core = _GREEK[stem]
    elif len(stem) <= 1:
        core = stem
    else:
        wrapper = "operatorname" if call_style == "operatorname" else "mathit"
        core = f"\\{wrapper}{{{_escape_text(stem)}}}"
    return f"{core}_{{{sub}}}" if sub else core


def _fresh_display(base: str, names: list[str]) -> str:
    base = base.split(LOCAL_MARK)[0] or "x"
    if base == "_":
        base = "x"
    if base not in names:
        return base
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


def _paren(s: str, need: bool) -> str:
    return f"\\left({s}\\right)" if need else s


# ---------------------------------------------------------------------------
# Operator tables (mirrors epsilon.elab.pp.INFIX / PRETTY_CONST)
# ---------------------------------------------------------------------------

NUMERIC_TYPES = ("Nat", "Int", "Rat", "Real", "Complex")

#: name -> (symbol, precedence, associativity). `.div` and `.pow` are
#: deliberately absent - they get \frac{}{} / ^{} instead of a generic
#: infix symbol (handled directly in `_to_latex`).
INFIX_LATEX: dict[str, tuple[str, int, str]] = {}
for _T in NUMERIC_TYPES:
    INFIX_LATEX[f"{_T}.add"] = ("+", 65, "left")
    INFIX_LATEX[f"{_T}.sub"] = ("-", 65, "left")
    INFIX_LATEX[f"{_T}.mul"] = ("\\cdot", 70, "left")
    INFIX_LATEX[f"{_T}.mod"] = ("\\bmod", 70, "left")
    INFIX_LATEX[f"{_T}.le"] = ("\\leq", 50, "none")
    INFIX_LATEX[f"{_T}.lt"] = ("<", 50, "none")
    INFIX_LATEX[f"{_T}.beq"] = ("\\overset{?}{=}", 50, "none")
INFIX_LATEX["And"] = ("\\land", 35, "right")
INFIX_LATEX["Or"] = ("\\lor", 30, "right")
INFIX_LATEX["Iff"] = ("\\leftrightarrow", 20, "right")
INFIX_LATEX["Prod"] = ("\\times", 72, "right")
INFIX_LATEX["String.append"] = ("\\mathbin{+\\!\\!+}", 65, "left")

#: exact division renders as a fraction; ℕ/ℤ division is *floor* division
#: and must not be drawn as one, or the export would overstate the result
DIV_OPS = {f"{T}.div" for T in NUMERIC_TYPES if T not in ("Nat", "Int")}
FLOOR_DIV_OPS = {"Nat.div", "Int.div"}
POW_OPS = {f"{T}.pow" for T in NUMERIC_TYPES}
_POW_BASE_PREC = 81  # forces parens around a base that is itself +,-,*,/,^

#: Real.<f> -> (apply-to-one-arg, bare-value-with-no-args)
REAL_FUNC_LATEX: dict[str, tuple[Callable[[str], str], str]] = {
    "sin": (lambda a: f"\\sin\\!\\left({a}\\right)", "\\sin"),
    "cos": (lambda a: f"\\cos\\!\\left({a}\\right)", "\\cos"),
    "tan": (lambda a: f"\\tan\\!\\left({a}\\right)", "\\tan"),
    "asin": (lambda a: f"\\arcsin\\!\\left({a}\\right)", "\\arcsin"),
    "acos": (lambda a: f"\\arccos\\!\\left({a}\\right)", "\\arccos"),
    "atan": (lambda a: f"\\arctan\\!\\left({a}\\right)", "\\arctan"),
    "sinh": (lambda a: f"\\sinh\\!\\left({a}\\right)", "\\sinh"),
    "cosh": (lambda a: f"\\cosh\\!\\left({a}\\right)", "\\cosh"),
    "tanh": (lambda a: f"\\tanh\\!\\left({a}\\right)", "\\tanh"),
    "exp": (lambda a: f"\\exp\\!\\left({a}\\right)", "\\exp"),
    "log": (lambda a: f"\\log\\!\\left({a}\\right)", "\\log"),
    "sqrt": (lambda a: f"\\sqrt{{{a}}}", "\\sqrt{\\cdot}"),
    "abs": (lambda a: f"\\left|{a}\\right|", "|\\cdot|"),
    "floor": (lambda a: f"\\left\\lfloor {a}\\right\\rfloor", "\\lfloor\\cdot\\rfloor"),
    "ceil": (lambda a: f"\\left\\lceil {a}\\right\\rceil", "\\lceil\\cdot\\rceil"),
}

PRETTY_CONST_LATEX = {
    "Real.pi": "\\pi", "Real.euler": "e",
    "Nat": "\\mathbb{N}", "Int": "\\mathbb{Z}", "Rat": "\\mathbb{Q}",
    "Real": "\\mathbb{R}", "Complex": "\\mathbb{C}",
    "True": "\\mathrm{True}", "False": "\\mathrm{False}",
    # epsilon/lib/prelude.epsl's unicode-alias `def`s for the same things -
    # ordinary source (and every stdlib theorem) writes `ℝ`/`π`/... rather
    # than `Real`/`Real.pi`/..., and those `def`s are NOT unfolded before
    # printing (this printer mirrors pp.py: no delta-reduction), so the
    # raw term head really is `Const("ℝ")`/`Const("π")`/... - these must
    # be recognized directly or the pretty rendering below would almost
    # never fire on real content.
    "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}", "ℚ": "\\mathbb{Q}",
    "ℝ": "\\mathbb{R}", "ℂ": "\\mathbb{C}", "π": "\\pi",
    "⊤": "\\mathrm{True}", "⊥": "\\mathrm{False}",
}

#: prelude.epsl shorthand `def`s -> the REAL_FUNC_LATEX key they alias
#: (same reasoning as PRETTY_CONST_LATEX above: `sin(x)` elaborates to
#: `Const("sin")` applied, not `Const("Real.sin")`).
_PRELUDE_FUNC_ALIAS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "asin": "asin",
    "acos": "acos", "atan": "atan", "sinh": "sinh", "cosh": "cosh",
    "tanh": "tanh", "exp": "exp", "log": "log", "ln": "log",
    "sqrt": "sqrt", "abs": "abs",
}


def _real_func_key(name: str) -> Optional[str]:
    """REAL_FUNC_LATEX key for `name`, whether it is the canonical
    `Real.<f>` constant or one of the prelude's bare-name aliases."""
    if name.startswith("Real.") and name[5:] in REAL_FUNC_LATEX:
        return name[5:]
    return _PRELUDE_FUNC_ALIAS.get(name)


_APP_PREC = 100


# ---------------------------------------------------------------------------
# Term -> LaTeX
# ---------------------------------------------------------------------------

def term_to_latex(env: Environment, t: Term, prec: int = 0,
                  names: Optional[list[str]] = None) -> str:
    """Render one kernel term as a LaTeX math fragment (no surrounding
    `$`/`\\[...\\]` - callers place it in whatever math context they need)."""
    names = names or []
    return _to_latex(env, t, prec, names)


def _head_ident(head: Term, names: list[str]) -> Optional[str]:
    """LaTeX for a Const/Var used as a function-application head."""
    if isinstance(head, Const):
        return _latex_ident(head.name, "operatorname")
    if isinstance(head, Var):
        nm = names[head.idx] if head.idx < len(names) else f"x_{{{head.idx}}}"
        return _latex_ident(nm, "operatorname")
    return None


def _apply_to_fresh(env: Environment, f: Term,
                    names: list[str]) -> tuple[str, str]:
    """Render `f` applied to a fresh bound variable, for \\int / \\lim
    notation: returns (variable-latex, body-latex)."""
    if isinstance(f, Lam):
        bn = _fresh_display(f.name, names)
        body = _to_latex(env, f.body, 0, [bn] + names)
        return _latex_ident(bn), body
    bn = _fresh_display("x", names)
    applied = App(lift(f, 1), Var(0))
    body = _to_latex(env, applied, 0, [bn] + names)
    return _latex_ident(bn), body


def _to_latex(env: Environment, t: Term, prec: int, names: list[str]) -> str:
    if isinstance(t, Var):
        if t.idx < len(names):
            return _latex_ident(names[t.idx])
        return f"\\#{t.idx}"
    if isinstance(t, Const):
        if t.name in PRETTY_CONST_LATEX:
            return PRETTY_CONST_LATEX[t.name]
        fkey = _real_func_key(t.name)
        if fkey is not None:
            return REAL_FUNC_LATEX[fkey][1]
        return _latex_ident(t.name)
    if isinstance(t, Sort):
        if t.level == 0:
            return "\\mathrm{Prop}"
        if t.level == 1:
            return "\\mathrm{Type}"
        return f"\\mathrm{{Type}}\\ {t.level - 1}"
    if isinstance(t, Lit):
        v: Fraction = t.value
        if v.denominator == 1:
            return str(v.numerator)
        sign = "-" if v.numerator < 0 else ""
        return f"{sign}\\frac{{{abs(v.numerator)}}}{{{v.denominator}}}"
    if isinstance(t, StrLit):
        return f"\\text{{``{_escape_prose(t.value)}''}}"
    if isinstance(t, MVar):
        raise LatexExportError(
            "cannot export a term containing a metavariable ?m"
            f"{t.id} (elaboration-only; call Elaborator.finalize first)")

    if isinstance(t, App):
        head, args = unfold_app(t)
        if isinstance(head, Const):
            n = head.name
            if n in DIV_OPS and len(args) == 2:
                num = _to_latex(env, args[0], 0, names)
                den = _to_latex(env, args[1], 0, names)
                return f"\\frac{{{num}}}{{{den}}}"
            if n in FLOOR_DIV_OPS and len(args) == 2:
                num = _to_latex(env, args[0], 0, names)
                den = _to_latex(env, args[1], 0, names)
                return (f"\\left\\lfloor \\frac{{{num}}}{{{den}}} "
                        f"\\right\\rfloor")
            if n in POW_OPS and len(args) == 2:
                base = _to_latex(env, args[0], _POW_BASE_PREC, names)
                exp = _to_latex(env, args[1], 0, names)
                return f"{base}^{{{exp}}}"
            if n == "Eq" and len(args) == 3:
                s = (f"{_to_latex(env, args[1], 51, names)} = "
                     f"{_to_latex(env, args[2], 51, names)}")
                return _paren(s, 50 < prec)
            if n == "Ne" and len(args) == 3:
                s = (f"{_to_latex(env, args[1], 51, names)} \\neq "
                     f"{_to_latex(env, args[2], 51, names)}")
                return _paren(s, 50 < prec)
            if n == "Not" and len(args) == 1:
                return _paren(f"\\lnot {_to_latex(env, args[0], 40, names)}",
                              40 < prec)
            if n == "Exists" and len(args) == 2 and isinstance(args[1], Lam):
                lam = args[1]
                bn = _fresh_display(lam.name, names)
                body = _to_latex(env, lam.body, 0, [bn] + names)
                ty = _to_latex(env, lam.ty, 0, names)
                s = f"\\exists ({_latex_ident(bn)} : {ty}),\\ {body}"
                return _paren(s, 0 < prec)
            if n == "Set.mem" and len(args) == 3:
                s = (f"{_to_latex(env, args[1], 51, names)} \\in "
                     f"{_to_latex(env, args[2], 51, names)}")
                return _paren(s, 50 < prec)
            if n.endswith(".neg") and len(args) == 1:
                return _paren(f"-{_to_latex(env, args[0], 75, names)}",
                              75 < prec)
            if n == "integral" and len(args) == 3:
                var, body = _apply_to_fresh(env, args[0], names)
                lo = _to_latex(env, args[1], 0, names)
                hi = _to_latex(env, args[2], 0, names)
                return (f"\\int_{{{lo}}}^{{{hi}}} {body} "
                        f"\\, d{var}")
            if n == "limit" and len(args) == 2:
                var, body = _apply_to_fresh(env, args[0], names)
                at = _to_latex(env, args[1], 0, names)
                return f"\\lim_{{{var} \\to {at}}} {body}"
            if n == "HasLimitAt" and len(args) == 3:
                var, body = _apply_to_fresh(env, args[0], names)
                at = _to_latex(env, args[1], 0, names)
                L = _to_latex(env, args[2], 51, names)
                s = f"\\lim_{{{var} \\to {at}}} {body} = {L}"
                return _paren(s, 50 < prec)
            fkey = _real_func_key(n)
            if fkey is not None and len(args) == 1:
                return REAL_FUNC_LATEX[fkey][0](
                    _to_latex(env, args[0], 0, names))
            if n in INFIX_LATEX and len(args) == 2:
                sym, p, assoc = INFIX_LATEX[n]
                lp = p if assoc == "left" else p + 1
                rp = p + 1 if assoc in ("left", "none") else p
                right = args[1]
                # `a + -1` is written `a - 1` in mathematics
                if sym in ("+", "-") and isinstance(right, Lit) \
                        and right.value < 0:
                    sym = "-" if sym == "+" else "+"
                    right = Lit(-right.value, right.tyname)
                s = (f"{_to_latex(env, args[0], lp, names)} {sym} "
                     f"{_to_latex(env, right, rp, names)}")
                return _paren(s, p < prec)
        hs = _head_ident(head, names)
        if hs is None:
            hs = _to_latex(env, head, _APP_PREC, names)
        arg_strs = [_to_latex(env, a, 0, names) for a in args]
        s = f"{hs}\\left({', '.join(arg_strs)}\\right)"
        return _paren(s, _APP_PREC < prec)

    if isinstance(t, Lam):
        bn = _fresh_display(t.name, names)
        body = _to_latex(env, t.body, 0, [bn] + names)
        ty = _to_latex(env, t.ty, 0, names)
        s = f"\\lambda ({_latex_ident(bn)} : {ty}),\\ {body}"
        return _paren(s, 0 < prec)

    if isinstance(t, Pi):
        if not has_var(t.body, 0):
            lhs = _to_latex(env, t.ty, 26, names)
            rhs = _to_latex(env, t.body, 25, ["_"] + names)
            return _paren(f"{lhs} \\to {rhs}", 25 < prec)
        bn = _fresh_display(t.name, names)
        body = _to_latex(env, t.body, 0, [bn] + names)
        ty = _to_latex(env, t.ty, 0, names)
        ob, cb = ("\\{", "\\}") if t.implicit else ("(", ")")
        s = f"\\forall {ob}{_latex_ident(bn)} : {ty}{cb},\\ {body}"
        return _paren(s, 0 < prec)

    raise LatexExportError(f"cannot export term node {type(t).__name__!r}")


# ---------------------------------------------------------------------------
# Declaration / module -> LaTeX
# ---------------------------------------------------------------------------

_STATEMENT_ENV = {"theorem": "theorem", "lemma": "lemma",
                  "proposition": "proposition", "corollary": "corollary"}


def decl_to_latex(env: Environment, name: str) -> str:
    """Render one declaration as an amsthm-style LaTeX block.

    Verification-status honesty (section 27): only THEOREM declarations
    carry a proven/symbolic/numeric/heuristic label (as a leading LaTeX
    comment, from `epsilon.project.STATUS_LABELS`). An axiom is assumed,
    not proven; a definition is not a truth-claim at all - neither is
    ever printed with a status label that could read as a proof. The doc
    comment, if any, is rendered as visible italic prose ahead of the
    block (a reader of the compiled PDF should see it, not just a reader
    of the .tex source).
    """
    d = env.expect(name)
    title = _escape_text(name)  # full qualified name: distinct Real/Int/...
                                 # namespaces must not collapse to one title
    doc = f"\\textit{{{_escape_prose(d.doc)}}}\\par\n" if d.doc else ""
    ty_latex = term_to_latex(env, d.type)

    if d.kind == DeclKind.THEOREM:
        status = env.verification_status(name)
        note = f"% {name} \u2014 {STATUS_LABELS[status]}\n"
        envname = _STATEMENT_ENV.get(d.statement_kind or "theorem", "theorem")
        return (f"{note}{doc}\\begin{{{envname}}}[{title}]\n"
                f"  \\[ {ty_latex} \\]\n\\end{{{envname}}}")

    if d.kind == DeclKind.AXIOM:
        note = f"% {name} \u2014 axiom (assumed; not proven by the kernel)\n"
        return (f"{note}{doc}\\begin{{axiom}}[{title}]\n"
                f"  \\[ {ty_latex} \\]\n\\end{{axiom}}")

    if d.kind in (DeclKind.DEFINITION, DeclKind.OPAQUE):
        kind_note = ("definition" if d.kind == DeclKind.DEFINITION
                     else "opaque constant (no reduction rule)")
        note = f"% {name} \u2014 {kind_note}\n"
        math_name = _latex_ident(name)
        value = (f" := {term_to_latex(env, d.value)}"
                 if d.value is not None else "")
        return (f"{note}{doc}\\begin{{definition}}[{title}]\n"
                f"  \\[ {math_name} : {ty_latex}{value} \\]\n"
                f"\\end{{definition}}")

    if d.kind == DeclKind.INDUCTIVE:
        note = f"% {name} \u2014 inductive type\n"
        math_name = _latex_ident(name)
        return (f"{note}{doc}\\begin{{definition}}[{title}]\n"
                f"  \\[ {math_name} : {ty_latex} \\]\n\\end{{definition}}")

    return f"% {name}: declaration kind {d.kind.value!r} is not rendered"


_PREAMBLE = """\\documentclass{article}
\\usepackage[utf8]{inputenc}
\\usepackage{amsmath}
\\usepackage{amssymb}
\\usepackage{amsthm}

\\newtheorem{theorem}{Theorem}
\\newtheorem{lemma}[theorem]{Lemma}
\\newtheorem{proposition}[theorem]{Proposition}
\\newtheorem{corollary}[theorem]{Corollary}
\\newtheorem{axiom}[theorem]{Axiom}
\\theoremstyle{definition}
\\newtheorem{definition}[theorem]{Definition}
"""


def module_to_latex(session, module: Optional[str] = None) -> str:
    """Render a complete, compilable LaTeX ``article`` document covering a
    module's definitions/axioms/theorems, as enumerated by `Session`'s own
    introspection lists (so this always matches the IDE/CLI report for the
    same module)."""
    from .. import __version__
    env = session.env

    def_names = [d["name"] for d in session.definition_list(module)]
    thm_names = [d["name"] for d in session.theorem_list(module)]
    axiom_names = [n for n in def_names if env.decls[n].kind == DeclKind.AXIOM]
    other_def_names = [n for n in def_names if n not in axiom_names]

    out = [_PREAMBLE]
    out.append(f"\\title{{Epsilon export: {_escape_text(module or 'all modules')}}}")
    out.append(f"\\author{{Generated by Epsilon {__version__}}}")
    out.append("\\date{}")
    out.append("")
    out.append("\\begin{document}")
    out.append("\\maketitle")
    out.append("")

    def _section(title: str, names: list[str]) -> None:
        if not names:
            return
        out.append(f"\\section*{{{title}}}")
        out.append("")
        for n in names:
            try:
                out.append(decl_to_latex(env, n))
            except (LatexExportError, KernelError) as e:
                out.append(f"% could not export {n}: {_escape_text(str(e))}")
            out.append("")

    _section("Definitions", other_def_names)
    _section("Axioms", axiom_names)
    _section("Theorems", thm_names)

    out.append("\\end{document}")
    return "\n".join(out)
