"""Basic mathematical pretty-printer for kernel terms.

Renders kernel terms back into Epsilon surface notation (Unicode). The
full-featured layout printer (fractions, matrices, aligned equations) lives
in epsilon.exporters; this one is for diagnostics, proof states, and the
console, and must stay dependency-free.
"""

from __future__ import annotations

from fractions import Fraction

from ..kernel.env import Environment
from ..kernel.term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar, unfold_app,
    instantiate,
)
from .context import LOCAL_MARK

# operator display: function name -> (symbol, precedence, assoc)
INFIX = {}
for T in ("Nat", "Int", "Rat", "Real", "Complex"):
    INFIX[f"{T}.add"] = ("+", 65, "left")
    INFIX[f"{T}.sub"] = ("-", 65, "left")
    INFIX[f"{T}.mul"] = ("*", 70, "left")
    # `/` is exact division; ℕ/ℤ division is floor division and prints `//`
    INFIX[f"{T}.div"] = ("//" if T in ("Nat", "Int") else "/", 70, "left")
    INFIX[f"{T}.mod"] = ("%", 70, "left")
    INFIX[f"{T}.pow"] = ("^", 80, "right")
    INFIX[f"{T}.le"] = ("≤", 50, "none")
    INFIX[f"{T}.lt"] = ("<", 50, "none")
    INFIX[f"{T}.beq"] = ("==", 50, "none")
INFIX["And"] = ("∧", 35, "right")
INFIX["Or"] = ("∨", 30, "right")
INFIX["Iff"] = ("↔", 20, "right")
INFIX["Prod"] = ("×", 72, "right")
INFIX["String.append"] = ("++", 65, "left")

PRETTY_CONST = {
    "Real.pi": "π", "Nat": "ℕ", "Int": "ℤ", "Rat": "ℚ", "Real": "ℝ",
    "Complex": "ℂ", "True": "True", "False": "False",
}

_APP_PREC = 100


def pp(env: Environment, t: Term, prec: int = 0, names: list[str] | None = None) -> str:
    names = names or []
    return _pp(env, t, prec, names)


def _name_of_local(name: str) -> str:
    return name.split(LOCAL_MARK)[0]


def _pp(env: Environment, t: Term, prec: int, names: list[str]) -> str:
    if isinstance(t, Var):
        if t.idx < len(names):
            return names[t.idx]
        return f"#{t.idx}"
    if isinstance(t, Const):
        if t.name in PRETTY_CONST:
            return PRETTY_CONST[t.name]
        return _name_of_local(t.name)
    if isinstance(t, Sort):
        return "Prop" if t.level == 0 else ("Type" if t.level == 1 else f"Type {t.level-1}")
    if isinstance(t, Lit):
        v: Fraction = t.value
        if v.denominator == 1:
            return str(v.numerator)
        return f"{v.numerator}/{v.denominator}"
    if isinstance(t, StrLit):
        return repr(t.value)
    if isinstance(t, MVar):
        return f"?m{t.id}"

    if isinstance(t, App):
        head, args = unfold_app(t)
        if isinstance(head, Const):
            n = head.name
            # infix operators
            if n in INFIX and len(args) >= 2:
                sym, p, assoc = INFIX[n]
                if len(args) == 2:
                    lp = p if assoc == "left" else p + 1
                    rp = p + 1 if assoc in ("left", "none") else p
                    right = args[1]
                    # `a + -1` reads as `a - 1`; the CAS produces the former
                    # constantly, and nobody writes mathematics that way
                    if sym in ("+", "-") and isinstance(right, Lit) \
                            and right.value < 0:
                        sym = "-" if sym == "+" else "+"
                        right = Lit(-right.value, right.tyname)
                    s = (f"{_pp(env, args[0], lp, names)} {sym} "
                         f"{_pp(env, right, rp, names)}")
                    return _paren(s, p < prec)
            # Eq / Ne with implicit type arg
            if n == "Eq" and len(args) == 3:
                s = f"{_pp(env, args[1], 51, names)} = {_pp(env, args[2], 51, names)}"
                return _paren(s, 50 < prec)
            if n == "Ne" and len(args) == 3:
                s = f"{_pp(env, args[1], 51, names)} ≠ {_pp(env, args[2], 51, names)}"
                return _paren(s, 50 < prec)
            if n == "Not" and len(args) == 1:
                return _paren(f"¬{_pp(env, args[0], 40, names)}", 40 < prec)
            if n == "Exists" and len(args) == 2 and isinstance(args[1], Lam):
                lam = args[1]
                bn = _fresh_display(lam.name, names)
                body = _pp(env, lam.body, 0, [bn] + names)
                tystr = _pp(env, lam.ty, 0, names)
                return _paren(f"∃ ({bn} : {tystr}), {body}", 0 < prec)
            if n == "Set.mem" and len(args) == 3:
                s = f"{_pp(env, args[1], 51, names)} ∈ {_pp(env, args[2], 51, names)}"
                return _paren(s, 50 < prec)
            if n.endswith(".neg") and len(args) == 1:
                return _paren(f"-{_pp(env, args[0], 75, names)}", 75 < prec)
        s = _pp(env, head, _APP_PREC, names)
        for a in args:
            s += " " + _pp(env, a, _APP_PREC + 1, names)
        return _paren(s, _APP_PREC < prec)

    if isinstance(t, Lam):
        bn = _fresh_display(t.name, names)
        body = _pp(env, t.body, 0, [bn] + names)
        tystr = _pp(env, t.ty, 0, names)
        return _paren(f"λ ({bn} : {tystr}), {body}", 0 < prec)

    if isinstance(t, Pi):
        from ..kernel.term import has_var
        if not has_var(t.body, 0):
            # non-dependent: arrow / implication
            lhs = _pp(env, t.ty, 26, names)
            rhs = _pp(env, t.body, 25, ["_"] + names)
            return _paren(f"{lhs} → {rhs}", 25 < prec)
        bn = _fresh_display(t.name, names)
        body = _pp(env, t.body, 0, [bn] + names)
        tystr = _pp(env, t.ty, 0, names)
        b, e = ("{", "}") if t.implicit else ("(", ")")
        return _paren(f"∀ {b}{bn} : {tystr}{e}, {body}", 0 < prec)

    return repr(t)


def _fresh_display(base: str, names: list[str]) -> str:
    base = _name_of_local(base) or "x"
    if base not in names:
        return base
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


def _paren(s: str, need: bool) -> str:
    return f"({s})" if need else s
