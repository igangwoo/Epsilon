"""Read the mathematics out of a Python or C++ expression.

The overlay's engine: a selected `math.sin(x)/x` or `std::pow(x, 2) + 1`
becomes a kernel Term, which the existing exporters then typeset. This is a
*reader* for the arithmetic subset the two languages share — numbers, names,
calls, parentheses, unary minus, `+ - * / %` and `**`/`pow` — not a compiler
for either language. Anything outside that subset is refused, and the
overlay simply does not appear; guessing at semantics would put wrong
mathematics on screen, which is worse than none.

The source is never modified; this reads it. Rendering stays a separate
layer (design principles 5 and 6).
"""

from __future__ import annotations

import re
from fractions import Fraction

from ..kernel.term import Const, Lit, Term, mk_app

#: function names both languages use for the elementary functions ->
#: the shared IR's constants. `f`-suffixed C float variants included.
_FUNCTIONS = {}
for _name in ("sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh",
              "tanh", "exp", "log", "sqrt"):
    _FUNCTIONS[_name] = f"Real.{_name}"
    _FUNCTIONS[_name + "f"] = f"Real.{_name}"
_FUNCTIONS["fabs"] = "Real.abs"
_FUNCTIONS["abs"] = "Real.abs"

_CONSTANTS = {"pi": "Real.pi", "M_PI": "Real.pi", "e": "Real.euler",
              "M_E": "Real.euler", "tau": None, "inf": None, "nan": None}

#: namespace prefixes that mean "the maths library" in each language
_MATH_PREFIXES = ("math.", "np.", "numpy.", "std::", "cmath.")

_TOKEN = re.compile(r"""
    (?P<num>\d+\.\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|\d+(?:[eE][+-]?\d+)?)
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:(?:\.|::)[A-Za-z_][A-Za-z0-9_]*)*)
  | (?P<op>\*\*|[-+*/%(),])
  | (?P<ws>\s+)
""", re.X)


class MathExprError(ValueError):
    """The selection is not (only) mathematics; the overlay stays away."""


def _tokens(src: str) -> list[str]:
    out, i = [], 0
    while i < len(src):
        m = _TOKEN.match(src, i)
        if not m:
            raise MathExprError(f"not a mathematical expression (at {src[i]!r})")
        i = m.end()
        if not m.group("ws"):
            out.append(m.group(0))
    return out


def _strip_math(name: str) -> str:
    for prefix in _MATH_PREFIXES:
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


class _Parser:
    def __init__(self, tokens: list[str]) -> None:
        self.toks = tokens
        self.i = 0

    def peek(self) -> str | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> str:
        tok = self.peek()
        if tok is None:
            raise MathExprError("expression ends too early")
        self.i += 1
        return tok

    def expect(self, tok: str) -> None:
        if self.take() != tok:
            raise MathExprError(f"expected {tok!r}")

    # additive -> multiplicative -> unary -> power -> atom
    def additive(self) -> Term:
        t = self.multiplicative()
        while self.peek() in ("+", "-"):
            op = self.take()
            rhs = self.multiplicative()
            t = mk_app(Const("Real.add" if op == "+" else "Real.sub"), t, rhs)
        return t

    def multiplicative(self) -> Term:
        t = self.unary()
        while self.peek() in ("*", "/", "%"):
            op = self.take()
            rhs = self.unary()
            name = {"*": "Real.mul", "/": "Real.div", "%": "Real.mod"}[op]
            t = mk_app(Const(name), t, rhs)
        return t

    def unary(self) -> Term:
        if self.peek() == "-":
            self.take()
            return mk_app(Const("Real.neg"), self.unary())
        if self.peek() == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self) -> Term:
        base = self.atom()
        if self.peek() == "**":       # right-associative, as in Python
            self.take()
            return mk_app(Const("Real.pow"), base, self.unary())
        return base

    def atom(self) -> Term:
        tok = self.take()
        if tok == "(":
            t = self.additive()
            self.expect(")")
            return t
        if re.fullmatch(r"[\d.].*", tok):
            try:
                value = Fraction(tok)
            except ValueError:
                raise MathExprError(f"bad number {tok!r}")
            return Lit(value, "Nat" if value.denominator == 1 and "." not in tok
                       and "e" not in tok.lower() else "Real")
        # a name: maths function, constant, pow(), or a free variable
        name = _strip_math(tok)
        if self.peek() == "(":
            self.take()
            args = []
            if self.peek() != ")":
                args.append(self.additive())
                while self.peek() == ",":
                    self.take()
                    args.append(self.additive())
            self.expect(")")
            if name == "pow" and len(args) == 2:
                return mk_app(Const("Real.pow"), *args)
            if name in _FUNCTIONS and len(args) == 1:
                return mk_app(Const(_FUNCTIONS[name]), args[0])
            raise MathExprError(f"unknown function {tok!r}")
        if name in _CONSTANTS:
            mapped = _CONSTANTS[name]
            if mapped is None:
                raise MathExprError(f"{tok!r} has no finite reading")
            return Const(mapped)
        if "." in tok or "::" in tok:
            raise MathExprError(f"unknown name {tok!r}")
        return Const(name)            # a free variable, rendered as itself


def parse_math_expr(src: str) -> Term:
    """The selection as a kernel Term, or MathExprError if it is not maths."""
    src = src.strip().rstrip(";")
    if not src:
        raise MathExprError("nothing selected")
    parser = _Parser(_tokens(src))
    term = parser.additive()
    if parser.peek() is not None:
        raise MathExprError(f"trailing {parser.peek()!r}")
    return term
