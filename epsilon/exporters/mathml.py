"""Presentation MathML exporter (product spec section 25).

Renders one kernel `Term` as a `<math>` fragment of W3C Presentation
MathML: ``mfrac`` for division, ``msup`` for powers, ``msqrt`` for
``Real.sqrt``, ``munder``/``mo`` for limits, ``msubsup`` for the definite
integral, and ``mi``/``mn``/``mo`` leaves everywhere else - built with
`xml.etree.ElementTree` so well-formedness is structural, not something
this module has to get right by hand-escaping strings.

The operator set, precedences and associativities mirror
`epsilon.elab.pp` / `epsilon.exporters.latex`, so the same term reads the
same way (up to notation) across the plain-text, LaTeX and MathML
printers.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from fractions import Fraction
from typing import Callable, Optional

from ..kernel.env import Environment
from ..kernel.term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar, unfold_app,
    has_var, lift,
)
from ..elab.context import LOCAL_MARK

MATHML_NS = "http://www.w3.org/1998/Math/MathML"


class MathMLExportError(Exception):
    """A term cannot be rendered as Presentation MathML."""


# ---------------------------------------------------------------------------
# Element builders
# ---------------------------------------------------------------------------

def _el(tag: str, *children: ET.Element, text: Optional[str] = None,
       **attrib: str) -> ET.Element:
    e = ET.Element(tag, attrib)
    if text is not None:
        e.text = text
    for c in children:
        e.append(c)
    return e


def _mi(text: str, **attrib: str) -> ET.Element:
    return _el("mi", text=text, **attrib)


def _mn(text: str) -> ET.Element:
    return _el("mn", text=text)


def _mo(text: str, **attrib: str) -> ET.Element:
    return _el("mo", text=text, **attrib)


def _mrow(*children: ET.Element) -> ET.Element:
    return _el("mrow", *children)


def _group(need_parens: bool, *children: ET.Element) -> ET.Element:
    """Wrap `children` in visible parentheses when `need_parens`, else
    collapse to a single element (or an `mrow` of several)."""
    if need_parens:
        return _mrow(_mo("("), *children, _mo(")"))
    if len(children) == 1:
        return children[0]
    return _mrow(*children)


# ---------------------------------------------------------------------------
# Identifiers (mirrors epsilon.exporters.latex._split_subscript)
# ---------------------------------------------------------------------------

_SUBSCRIPT_CHARS = {
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "₆": "6", "₇": "7", "₈": "8", "₉": "9", "ₐ": "a", "ₑ": "e",
    "ᵢ": "i", "ⱼ": "j", "ₖ": "k", "ₗ": "l", "ₘ": "m", "ₙ": "n",
    "ₚ": "p", "ₛ": "s", "ₜ": "t",
}
_TRAILING_SUB_RE = re.compile(
    r"^(.+?)_?([0-9]+|[" + "".join(_SUBSCRIPT_CHARS) + r"]+)$")


def _split_subscript(name: str) -> tuple[str, Optional[str]]:
    m = _TRAILING_SUB_RE.match(name)
    if not m:
        return name, None
    base, sub = m.group(1), m.group(2)
    sub = "".join(_SUBSCRIPT_CHARS.get(c, c) for c in sub)
    return base, sub


def _mml_ident(name: str) -> ET.Element:
    """`<mi>` (or `<msub>` for a trailing-digit subscript) for a bound
    variable / constant display name. MathML needs no LaTeX-style macro
    table for Greek letters or blackboard-bold - the raw Unicode
    character is already valid Presentation MathML content."""
    base = name.split(LOCAL_MARK)[0] or "x"
    stem, sub = _split_subscript(base)
    stem = stem or "x"
    if sub:
        return _el("msub", _mi(stem), _mn(sub))
    return _mi(stem)


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


# ---------------------------------------------------------------------------
# Operator tables (mirrors epsilon.elab.pp.INFIX)
# ---------------------------------------------------------------------------

NUMERIC_TYPES = ("Nat", "Int", "Rat", "Real", "Complex")

INFIX_MML: dict[str, tuple[str, int, str]] = {}
for _T in NUMERIC_TYPES:
    INFIX_MML[f"{_T}.add"] = ("+", 65, "left")
    INFIX_MML[f"{_T}.sub"] = ("−", 65, "left")
    INFIX_MML[f"{_T}.mul"] = ("⋅", 70, "left")       # cdot
    INFIX_MML[f"{_T}.mod"] = ("mod", 70, "left")
    INFIX_MML[f"{_T}.le"] = ("≤", 50, "none")
    INFIX_MML[f"{_T}.lt"] = ("<", 50, "none")
    INFIX_MML[f"{_T}.beq"] = ("=?", 50, "none")
INFIX_MML["And"] = ("∧", 35, "right")
INFIX_MML["Or"] = ("∨", 30, "right")
INFIX_MML["Iff"] = ("↔", 20, "right")
INFIX_MML["Prod"] = ("×", 72, "right")
INFIX_MML["String.append"] = ("++", 65, "left")

#: exact division renders as a fraction; ℕ/ℤ division is *floor* division
#: and gets floor brackets, so the markup does not overstate the result
DIV_OPS = {f"{T}.div" for T in NUMERIC_TYPES if T not in ("Nat", "Int")}
FLOOR_DIV_OPS = {"Nat.div", "Int.div"}
POW_OPS = {f"{T}.pow" for T in NUMERIC_TYPES}
_POW_BASE_PREC = 81

FUNC_APPLY = "⁡"  # invisible function application

#: Real.<f> -> element builder for one argument
REAL_FUNC_MML: dict[str, Callable[[ET.Element], ET.Element]] = {
    "sin": lambda a: _mrow(_mi("sin"), _mo(FUNC_APPLY), _group(True, a)),
    "cos": lambda a: _mrow(_mi("cos"), _mo(FUNC_APPLY), _group(True, a)),
    "tan": lambda a: _mrow(_mi("tan"), _mo(FUNC_APPLY), _group(True, a)),
    "asin": lambda a: _mrow(_mi("arcsin"), _mo(FUNC_APPLY), _group(True, a)),
    "acos": lambda a: _mrow(_mi("arccos"), _mo(FUNC_APPLY), _group(True, a)),
    "atan": lambda a: _mrow(_mi("arctan"), _mo(FUNC_APPLY), _group(True, a)),
    "sinh": lambda a: _mrow(_mi("sinh"), _mo(FUNC_APPLY), _group(True, a)),
    "cosh": lambda a: _mrow(_mi("cosh"), _mo(FUNC_APPLY), _group(True, a)),
    "tanh": lambda a: _mrow(_mi("tanh"), _mo(FUNC_APPLY), _group(True, a)),
    "exp": lambda a: _mrow(_mi("exp"), _mo(FUNC_APPLY), _group(True, a)),
    "log": lambda a: _mrow(_mi("log"), _mo(FUNC_APPLY), _group(True, a)),
    "sqrt": lambda a: _el("msqrt", a),
    "abs": lambda a: _mrow(_mo("|"), a, _mo("|")),
    "floor": lambda a: _mrow(_mo("⌊"), a, _mo("⌋")),
    "ceil": lambda a: _mrow(_mo("⌈"), a, _mo("⌉")),
}
REAL_FUNC_BARE = {
    "sin": "sin", "cos": "cos", "tan": "tan", "asin": "arcsin",
    "acos": "arccos", "atan": "arctan", "sinh": "sinh", "cosh": "cosh",
    "tanh": "tanh", "exp": "exp", "log": "log",
}

#: prelude.epsl shorthand `def`s (e.g. `sin(x)` elaborates to `Const("sin")`
#: applied, not `Const("Real.sin")` - this printer does not delta-reduce,
#: same as pp.py) -> the REAL_FUNC_MML key they alias.
_PRELUDE_FUNC_ALIAS = {
    "sin": "sin", "cos": "cos", "tan": "tan", "asin": "asin",
    "acos": "acos", "atan": "atan", "sinh": "sinh", "cosh": "cosh",
    "tanh": "tanh", "exp": "exp", "log": "log", "ln": "log",
    "sqrt": "sqrt", "abs": "abs",
}

#: prelude.epsl's unicode type/constant aliases (`def ℝ := Real`, etc.) ->
#: the same rendering as their canonical Const name.
_PRELUDE_CONST_ALIAS = {
    "ℕ": "N", "ℤ": "Z", "ℚ": "Q", "ℝ": "R", "ℂ": "C",
}


def _real_func_key(name: str) -> Optional[str]:
    if name.startswith("Real.") and name[5:] in REAL_FUNC_MML:
        return name[5:]
    return _PRELUDE_FUNC_ALIAS.get(name)


_APP_PREC = 100


# ---------------------------------------------------------------------------
# Term -> MathML
# ---------------------------------------------------------------------------

def term_to_mathml(env: Environment, t: Term, prec: int = 0,
                   names: Optional[list[str]] = None) -> str:
    """Render one kernel term as a Presentation MathML `<math>` document
    fragment (well-formed XML - see `xml.etree.ElementTree.fromstring`)."""
    names = names or []
    root = _el("math", _to_mml(env, t, prec, names), xmlns=MATHML_NS)
    return ET.tostring(root, encoding="unicode")


def _head_ident(head: Term, names: list[str]) -> Optional[ET.Element]:
    if isinstance(head, Const):
        return _mml_ident(head.name)
    if isinstance(head, Var):
        nm = names[head.idx] if head.idx < len(names) else f"#{head.idx}"
        return _mml_ident(nm)
    return None


def _apply_to_fresh(env: Environment, f: Term,
                    names: list[str]) -> tuple[ET.Element, ET.Element]:
    """`f` applied to a fresh bound variable, for integral/limit notation:
    returns (variable-element, body-element)."""
    if isinstance(f, Lam):
        bn = _fresh_display(f.name, names)
        body = _to_mml(env, f.body, 0, [bn] + names)
        return _mml_ident(bn), body
    bn = _fresh_display("x", names)
    applied = App(lift(f, 1), Var(0))
    body = _to_mml(env, applied, 0, [bn] + names)
    return _mml_ident(bn), body


def _to_mml(env: Environment, t: Term, prec: int,
           names: list[str]) -> ET.Element:
    if isinstance(t, Var):
        if t.idx < len(names):
            return _mml_ident(names[t.idx])
        return _mi(f"#{t.idx}")
    if isinstance(t, Const):
        if t.name in ("Real.pi", "π"):
            return _mi("π")
        if t.name == "Real.euler":
            return _mi("e")
        if t.name in ("Nat", "Int", "Rat", "Real", "Complex"):
            letter = {"Nat": "N", "Int": "Z", "Rat": "Q", "Real": "R",
                     "Complex": "C"}[t.name]
            return _mi(letter, mathvariant="double-struck")
        if t.name in _PRELUDE_CONST_ALIAS:
            return _mi(_PRELUDE_CONST_ALIAS[t.name], mathvariant="double-struck")
        if t.name in ("True", "False", "⊤", "⊥"):
            word = {"⊤": "True", "⊥": "False"}.get(t.name, t.name)
            return _mi(word)
        fkey = _real_func_key(t.name)
        if fkey is not None and fkey in REAL_FUNC_BARE:
            return _mi(REAL_FUNC_BARE[fkey])
        return _mml_ident(t.name)
    if isinstance(t, Sort):
        if t.level == 0:
            return _mi("Prop")
        if t.level == 1:
            return _mi("Type")
        return _mrow(_mi("Type"), _mn(str(t.level - 1)))
    if isinstance(t, Lit):
        v: Fraction = t.value
        if v.denominator == 1:
            return _mn(str(v.numerator))
        frac = _el("mfrac", _mn(str(abs(v.numerator))), _mn(str(v.denominator)))
        if v.numerator < 0:
            return _mrow(_mo("-"), frac)
        return frac
    if isinstance(t, StrLit):
        return _el("mtext", text=f'"{t.value}"')
    if isinstance(t, MVar):
        raise MathMLExportError(
            "cannot export a term containing a metavariable ?m"
            f"{t.id} (elaboration-only; call Elaborator.finalize first)")

    if isinstance(t, App):
        head, args = unfold_app(t)
        if isinstance(head, Const):
            n = head.name
            if n in DIV_OPS and len(args) == 2:
                num = _to_mml(env, args[0], 0, names)
                den = _to_mml(env, args[1], 0, names)
                return _el("mfrac", num, den)
            if n in FLOOR_DIV_OPS and len(args) == 2:
                num = _to_mml(env, args[0], 0, names)
                den = _to_mml(env, args[1], 0, names)
                return _mrow(_mo("⌊"), _el("mfrac", num, den),
                             _mo("⌋"))
            if n in POW_OPS and len(args) == 2:
                base = _to_mml(env, args[0], _POW_BASE_PREC, names)
                exp = _to_mml(env, args[1], 0, names)
                return _el("msup", base, exp)
            if n == "Eq" and len(args) == 3:
                lhs = _to_mml(env, args[1], 51, names)
                rhs = _to_mml(env, args[2], 51, names)
                return _group(50 < prec, lhs, _mo("="), rhs)
            if n == "Ne" and len(args) == 3:
                lhs = _to_mml(env, args[1], 51, names)
                rhs = _to_mml(env, args[2], 51, names)
                return _group(50 < prec, lhs, _mo("≠"), rhs)
            if n == "Not" and len(args) == 1:
                arg = _to_mml(env, args[0], 40, names)
                return _group(40 < prec, _mo("¬"), arg)
            if n == "Exists" and len(args) == 2 and isinstance(args[1], Lam):
                lam = args[1]
                bn = _fresh_display(lam.name, names)
                body = _to_mml(env, lam.body, 0, [bn] + names)
                ty = _to_mml(env, lam.ty, 0, names)
                binder = _mrow(_mo("("), _mml_ident(bn), _mo(":"), ty, _mo(")"))
                return _group(0 < prec, _mo("∃"), binder, _mo(","), body)
            if n == "Set.mem" and len(args) == 3:
                lhs = _to_mml(env, args[1], 51, names)
                rhs = _to_mml(env, args[2], 51, names)
                return _group(50 < prec, lhs, _mo("∈"), rhs)
            if n.endswith(".neg") and len(args) == 1:
                arg = _to_mml(env, args[0], 75, names)
                return _group(75 < prec, _mo("-"), arg)
            if n == "integral" and len(args) == 3:
                var, body = _apply_to_fresh(env, args[0], names)
                lo = _to_mml(env, args[1], 0, names)
                hi = _to_mml(env, args[2], 0, names)
                integ = _el("msubsup", _mo("∫"), lo, hi)
                return _group(0 < prec, integ, body, _mo(FUNC_APPLY),
                             _mi("d"), var)
            if n == "limit" and len(args) == 2:
                var, body = _apply_to_fresh(env, args[0], names)
                at = _to_mml(env, args[1], 0, names)
                under = _mrow(var, _mo("→"), at)
                lim = _el("munder", _mo("lim", movablelimits="true"), under)
                return _group(0 < prec, lim, body)
            if n == "HasLimitAt" and len(args) == 3:
                var, body = _apply_to_fresh(env, args[0], names)
                at = _to_mml(env, args[1], 0, names)
                L = _to_mml(env, args[2], 51, names)
                under = _mrow(var, _mo("→"), at)
                lim = _el("munder", _mo("lim", movablelimits="true"), under)
                return _group(50 < prec, lim, body, _mo("="), L)
            fkey = _real_func_key(n)
            if fkey is not None and len(args) == 1:
                return REAL_FUNC_MML[fkey](_to_mml(env, args[0], 0, names))
            if n in INFIX_MML and len(args) == 2:
                sym, p, assoc = INFIX_MML[n]
                lp = p if assoc == "left" else p + 1
                rp = p + 1 if assoc in ("left", "none") else p
                lhs = _to_mml(env, args[0], lp, names)
                rhs = _to_mml(env, args[1], rp, names)
                return _group(p < prec, lhs, _mo(sym), rhs)
        hs = _head_ident(head, names)
        if hs is None:
            hs = _to_mml(env, head, _APP_PREC, names)
        call = [_mo("(")]
        for i, a in enumerate(args):
            if i:
                call.append(_mo(","))
            call.append(_to_mml(env, a, 0, names))
        call.append(_mo(")"))
        return _group(_APP_PREC < prec, hs, _mo(FUNC_APPLY), _mrow(*call))

    if isinstance(t, Lam):
        bn = _fresh_display(t.name, names)
        body = _to_mml(env, t.body, 0, [bn] + names)
        ty = _to_mml(env, t.ty, 0, names)
        binder = _mrow(_mo("("), _mml_ident(bn), _mo(":"), ty, _mo(")"))
        return _group(0 < prec, _mo("λ"), binder, _mo(","), body)

    if isinstance(t, Pi):
        if not has_var(t.body, 0):
            lhs = _to_mml(env, t.ty, 26, names)
            rhs = _to_mml(env, t.body, 25, ["_"] + names)
            return _group(25 < prec, lhs, _mo("→"), rhs)
        bn = _fresh_display(t.name, names)
        body = _to_mml(env, t.body, 0, [bn] + names)
        ty = _to_mml(env, t.ty, 0, names)
        ob, cb = ("{", "}") if t.implicit else ("(", ")")
        binder = _mrow(_mo(ob), _mml_ident(bn), _mo(":"), ty, _mo(cb))
        return _group(0 < prec, _mo("∀"), binder, _mo(","), body)

    raise MathMLExportError(f"cannot export term node {type(t).__name__!r}")
