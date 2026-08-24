"""Two-dimensional mathematical layout (product spec section 22).

`epsilon.elab.pp` prints terms on one line, which is right for diagnostics.
This module lays terms out the way they are written on paper - fractions
stacked over a bar, superscripts raised, integrals and sums with their
limits above and below - using a small box-layout algebra rendered into
Unicode text. The console and CLI use it; the same boxes could drive an
SVG or canvas renderer.

A `Box` is a rectangle of text lines plus a *baseline*: the row that lines
up with its neighbours. Composition is then just alignment arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from .kernel.env import Environment
from .kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit,
                          MVar, unfold_app, has_var)
from .elab.context import LOCAL_MARK

SUPERSCRIPT = str.maketrans("0123456789+-=()n·xyzabcijk",
                            "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿ˙ˣʸᶻᵃᵇᶜⁱʲᵏ")
SUBSCRIPT = str.maketrans("0123456789+-=()aeioxhklmnpst",
                          "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₐₑᵢₒₓₕₖₗₘₙₚₛₜ")

GREEK = {"alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ",
         "epsilon": "ε", "eps": "ε", "zeta": "ζ", "eta": "η", "theta": "θ",
         "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ", "pi": "π",
         "rho": "ρ", "sigma": "σ", "tau": "τ", "phi": "φ", "chi": "χ",
         "psi": "ψ", "omega": "ω", "Gamma": "Γ", "Delta": "Δ",
         "Theta": "Θ", "Lambda": "Λ", "Sigma": "Σ", "Phi": "Φ",
         "Psi": "Ψ", "Omega": "Ω"}

PRETTY_CONST = {"Real.pi": "π", "Real.euler": "e", "Complex.I": "i",
                "Nat": "ℕ", "Int": "ℤ", "Rat": "ℚ", "Real": "ℝ",
                "Complex": "ℂ", "Bool": "𝔹", "True": "⊤", "False": "⊥"}

FUNCTION_NAMES = {
    "Real.sin": "sin", "Real.cos": "cos", "Real.tan": "tan",
    "Real.asin": "arcsin", "Real.acos": "arccos", "Real.atan": "arctan",
    "Real.sinh": "sinh", "Real.cosh": "cosh", "Real.tanh": "tanh",
    "Real.exp": "exp", "Real.log": "ln", "Real.abs": "abs",
    "Complex.abs": "abs", "Complex.re": "Re", "Complex.im": "Im",
    "Complex.conj": "conj", "Int.natAbs": "abs",
}

BIN_SYMBOLS = {"add": "+", "sub": "−", "mul": "·", "mod": "mod",
               "le": "≤", "lt": "<", "beq": "=", "ble": "≤", "blt": "<"}


@dataclass
class Box:
    """A rectangle of text with a baseline row."""
    lines: list[str] = field(default_factory=lambda: [""])
    baseline: int = 0

    @property
    def width(self) -> int:
        return max((len(l) for l in self.lines), default=0)

    @property
    def height(self) -> int:
        return len(self.lines)

    def padded(self, width: Optional[int] = None) -> list[str]:
        w = width if width is not None else self.width
        return [l.ljust(w) for l in self.lines]

    def render(self) -> str:
        return "\n".join(l.rstrip() for l in self.padded()).rstrip("\n")

    def __str__(self) -> str:
        return self.render()


def text_box(s: str) -> Box:
    return Box([s], 0)


def hcat(*boxes: Box) -> Box:
    """Horizontal composition, aligned on baselines."""
    boxes = tuple(b for b in boxes if b is not None)
    if not boxes:
        return text_box("")
    above = max(b.baseline for b in boxes)
    below = max(b.height - b.baseline - 1 for b in boxes)
    height = above + below + 1
    rows = [""] * height
    for b in boxes:
        top_pad = above - b.baseline
        padded = b.padded()
        for i in range(height):
            j = i - top_pad
            rows[i] += padded[j] if 0 <= j < len(padded) else " " * b.width
    return Box(rows, above)


def frac(num: Box, den: Box) -> Box:
    width = max(num.width, den.width) + 2
    bar = "─" * width
    lines = [_center(l, width) for l in num.padded()]
    lines.append(bar)
    baseline = len(lines) - 1
    lines.extend(_center(l, width) for l in den.padded())
    return Box(lines, baseline)


def parenthesize(b: Box) -> Box:
    if b.height == 1:
        return text_box("(" + b.lines[0] + ")")
    left = ["⎛"] + ["⎜"] * (b.height - 2) + ["⎝"]
    right = ["⎞"] + ["⎟"] * (b.height - 2) + ["⎠"]
    if b.height == 2:
        left, right = ["⎛", "⎝"], ["⎞", "⎠"]
    rows = [l + m + r for l, m, r in zip(left, b.padded(), right)]
    return Box(rows, b.baseline)


def superscript(base: Box, exp: Box) -> Box:
    """Raise `exp` above the baseline of `base`."""
    if exp.height == 1 and _translatable(exp.lines[0], SUPERSCRIPT):
        return hcat(base, text_box(exp.lines[0].translate(SUPERSCRIPT)))
    lifted = Box(exp.lines + [" " * exp.width] * (base.baseline + 1),
                 exp.height + base.baseline)
    return hcat(base, lifted)


def _translatable(s: str, table: dict) -> bool:
    return all(ord(ch) in table for ch in s)


def _center(s: str, width: int) -> str:
    pad = width - len(s)
    left = pad // 2
    return " " * left + s + " " * (pad - left)


def big_operator(symbol: str, lower: Optional[Box], upper: Optional[Box],
                 body: Box, tall_symbol: Optional[list[str]] = None) -> Box:
    """Σ / Π / ∫ with limits above and below."""
    sym_lines = tall_symbol or [symbol]
    sym = Box(sym_lines, len(sym_lines) // 2)
    parts: list[str] = []
    width = max(sym.width, upper.width if upper else 0,
                lower.width if lower else 0)
    if upper:
        parts.extend(_center(l, width) for l in upper.padded())
    baseline = len(parts) + sym.baseline
    parts.extend(_center(l, width) for l in sym.padded())
    if lower:
        parts.extend(_center(l, width) for l in lower.padded())
    op = Box(parts, baseline)
    return hcat(op, text_box(" "), body)


# ---------------------------------------------------------------------------
# Term -> Box
# ---------------------------------------------------------------------------

_APP = 100


def layout(env: Environment, t: Term, prec: int = 0,
           names: Optional[list[str]] = None) -> Box:
    names = names or []
    return _layout(env, t, prec, names)


def pretty(env: Environment, t: Term) -> str:
    """Render a term as multi-line mathematical notation."""
    return layout(env, t).render()


def _paren_if(b: Box, need: bool) -> Box:
    return parenthesize(b) if need else b


def _display_name(name: str) -> str:
    base = name.split(LOCAL_MARK)[0]
    if base in PRETTY_CONST:
        return PRETTY_CONST[base]
    short = base.rsplit(".", 1)[-1]
    if short in GREEK:
        return GREEK[short]
    # x_1 / x1 -> subscripts
    if "_" in short:
        head, _, tail = short.partition("_")
        if tail and _translatable(tail, SUBSCRIPT):
            return head + tail.translate(SUBSCRIPT)
    return base


def _layout(env: Environment, t: Term, prec: int, names: list[str]) -> Box:
    if isinstance(t, Var):
        return text_box(names[t.idx] if t.idx < len(names) else f"#{t.idx}")
    if isinstance(t, Const):
        return text_box(_display_name(t.name))
    if isinstance(t, Sort):
        return text_box("Prop" if t.level == 0
                        else ("Type" if t.level == 1 else f"Type {t.level-1}"))
    if isinstance(t, Lit):
        v: Fraction = t.value
        if v.denominator == 1:
            return text_box(str(v.numerator))
        return frac(text_box(str(abs(v.numerator))), text_box(str(v.denominator))) \
            if v.numerator >= 0 else hcat(
                text_box("−"), frac(text_box(str(abs(v.numerator))),
                                    text_box(str(v.denominator))))
    if isinstance(t, StrLit):
        return text_box(f'"{t.value}"')
    if isinstance(t, MVar):
        return text_box(f"?m{t.id}")

    if isinstance(t, App):
        return _layout_app(env, t, prec, names)

    if isinstance(t, Lam):
        bn = _fresh(t.name, names)
        body = _layout(env, t.body, 0, [bn] + names)
        head = hcat(text_box(f"λ{_display_name(bn)}. "), body)
        return _paren_if(head, prec > 0)

    if isinstance(t, Pi):
        if not has_var(t.body, 0):
            lhs = _layout(env, t.ty, 26, names)
            rhs = _layout(env, t.body, 25, ["_"] + names)
            return _paren_if(hcat(lhs, text_box(" → "), rhs), prec > 25)
        bn = _fresh(t.name, names)
        dom = _layout(env, t.ty, 0, names)
        body = _layout(env, t.body, 0, [bn] + names)
        head = hcat(text_box(f"∀{_display_name(bn)}∈"), dom, text_box(". "), body)
        return _paren_if(head, prec > 0)

    return text_box(repr(t))


def _layout_app(env: Environment, t: App, prec: int, names: list[str]) -> Box:
    head, args = unfold_app(t)
    if isinstance(head, Const):
        n = head.name
        short = n.rsplit(".", 1)[-1]

        # division renders as a stacked fraction
        if short == "div" and len(args) == 2:
            box = frac(_layout(env, args[0], 0, names),
                       _layout(env, args[1], 0, names))
            return _paren_if(box, prec > 70)
        if short == "inv" and len(args) == 1:
            return _paren_if(frac(text_box("1"),
                                  _layout(env, args[0], 0, names)), prec > 70)
        if short == "pow" and len(args) == 2:
            base = _layout(env, args[0], 81, names)
            return _paren_if(superscript(base,
                                         _layout(env, args[1], 0, names)),
                             prec > 80)
        if short == "neg" and len(args) == 1:
            return _paren_if(hcat(text_box("−"),
                                  _layout(env, args[0], 76, names)), prec > 75)
        if n == "Real.sqrt" and len(args) == 1:
            inner = _layout(env, args[0], 0, names)
            if inner.height == 1:
                return text_box(f"√({inner.lines[0]})" if len(inner.lines[0]) > 1
                                else f"√{inner.lines[0]}")
            return hcat(text_box("√"), parenthesize(inner))

        if short in BIN_SYMBOLS and len(args) == 2 and "." in n:
            sym = BIN_SYMBOLS[short]
            p = {"add": 65, "sub": 65, "mul": 70, "mod": 70}.get(short, 50)
            lhs = _layout(env, args[0], p, names)
            rhs = _layout(env, args[1], p + 1, names)
            return _paren_if(hcat(lhs, text_box(f" {sym} "), rhs), prec > p)

        # logical connectives
        LOGIC = {"And": ("∧", 35), "Or": ("∨", 30), "Iff": ("↔", 20),
                 "Prod": ("×", 72)}
        if n in LOGIC and len(args) == 2:
            sym, p = LOGIC[n]
            return _paren_if(
                hcat(_layout(env, args[0], p + 1, names), text_box(f" {sym} "),
                     _layout(env, args[1], p + 1, names)), prec > p)
        if n == "Eq" and len(args) == 3:
            return _paren_if(
                hcat(_layout(env, args[1], 51, names), text_box(" = "),
                     _layout(env, args[2], 51, names)), prec > 50)
        if n == "Ne" and len(args) == 3:
            return _paren_if(
                hcat(_layout(env, args[1], 51, names), text_box(" ≠ "),
                     _layout(env, args[2], 51, names)), prec > 50)
        if n == "Not" and len(args) == 1:
            return _paren_if(hcat(text_box("¬"),
                                  _layout(env, args[0], 41, names)), prec > 40)
        if n == "Set.mem" and len(args) == 3:
            return _paren_if(
                hcat(_layout(env, args[1], 51, names), text_box(" ∈ "),
                     _layout(env, args[2], 51, names)), prec > 50)
        if n == "Exists" and len(args) == 2 and isinstance(args[1], Lam):
            lam = args[1]
            bn = _fresh(lam.name, names)
            body = _layout(env, lam.body, 0, [bn] + names)
            return _paren_if(
                hcat(text_box(f"∃{_display_name(bn)}. "), body), prec > 0)

        # calculus: ∫, limits, derivatives
        if n == "integral" and len(args) == 3:
            f, a, b = args
            body = _integrand(env, f, names)
            return big_operator(
                "∫", _layout(env, a, 0, names), _layout(env, b, 0, names),
                body, tall_symbol=["⌠", "⎮", "⌡"])
        if n in ("limit", "HasLimitAt") and len(args) >= 2:
            f, a = args[0], args[1]
            var, body = _lambda_parts(env, f, names)
            sub = hcat(text_box(f"{var}→"), _layout(env, a, 0, names))
            lim = Box(["lim", sub.lines[0]], 0)
            out = hcat(lim, text_box(" "), body)
            if n == "HasLimitAt" and len(args) >= 3:
                out = hcat(out, text_box(" = "),
                           _layout(env, args[2], 0, names))
            return _paren_if(out, prec > 50)
        if n == "deriv" and len(args) >= 1:
            var, body = _lambda_parts(env, args[0], names)
            d = frac(text_box("d"), text_box(f"d{var}"))
            out = hcat(d, text_box(" "), body)
            if len(args) == 2:
                out = hcat(out, text_box(" at "), _layout(env, args[1], 0, names))
            return _paren_if(out, prec > 70)

        if n in FUNCTION_NAMES and len(args) == 1:
            inner = _layout(env, args[0], 0, names)
            return hcat(text_box(FUNCTION_NAMES[n]), parenthesize(inner))

    # generic application: f(a, b)
    box = _layout(env, head, _APP, names)
    if args:
        inner = _layout(env, args[0], 0, names)
        for a in args[1:]:
            inner = hcat(inner, text_box(", "), _layout(env, a, 0, names))
        box = hcat(box, parenthesize(inner))
    return box


def _lambda_parts(env: Environment, f: Term, names: list[str]) -> tuple[str, Box]:
    if isinstance(f, Lam):
        bn = _fresh(f.name, names)
        return _display_name(bn), _layout(env, f.body, 71, [bn] + names)
    box = _layout(env, f, _APP, names)
    return "x", hcat(box, text_box("(x)"))


def _integrand(env: Environment, f: Term, names: list[str]) -> Box:
    if isinstance(f, Lam):
        bn = _fresh(f.name, names)
        body = _layout(env, f.body, 0, [bn] + names)
        return hcat(body, text_box(f" d{_display_name(bn)}"))
    return hcat(_layout(env, f, _APP, names), text_box("(x) dx"))


def _fresh(base: str, names: list[str]) -> str:
    base = base.split(LOCAL_MARK)[0] or "x"
    if base not in names:
        return base
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


# ---------------------------------------------------------------------------
# Matrices / vectors (rendered from a list of rows of terms)
# ---------------------------------------------------------------------------

def matrix_box(env: Environment, rows: list[list[Term]]) -> Box:
    """Bracketed matrix layout from a grid of terms."""
    if not rows:
        return text_box("[ ]")
    cells = [[_layout(env, t, 0, []) for t in row] for row in rows]
    widths = [max(cells[r][c].width for r in range(len(cells)))
              for c in range(len(cells[0]))]
    lines: list[str] = []
    for row in cells:
        parts = [b.lines[b.baseline].center(w) for b, w in zip(row, widths)]
        lines.append("  ".join(parts))
    height = len(lines)
    if height == 1:
        return text_box(f"[ {lines[0]} ]")
    left = ["⎡"] + ["⎢"] * (height - 2) + ["⎣"]
    right = ["⎤"] + ["⎥"] * (height - 2) + ["⎦"]
    width = max(len(l) for l in lines)
    body = [l.ljust(width) for l in lines]
    return Box([f"{l} {m} {r}" for l, m, r in zip(left, body, right)],
               height // 2)


def cases_box(branches: list[tuple[str, str]]) -> Box:
    """A `cases` layout: value if condition, one branch per line."""
    if not branches:
        return text_box("{}")
    width = max(len(v) for v, _ in branches)
    lines = [f"{v.ljust(width)}   if {c}" for v, c in branches]
    height = len(lines)
    if height == 1:
        return text_box("{ " + lines[0] + " }")
    left = ["⎧"] + ["⎪"] * (height - 2) + ["⎩"]
    return Box([f"{l} {m}" for l, m in zip(left, lines)], height // 2)
