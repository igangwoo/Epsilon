"""Lexer for the Epsilon language.

Full Unicode mathematical notation with ASCII fallbacks for every symbol:

    Unicode   ASCII        meaning
    →         ->           function type / implication
    ↔         <->          iff
    ∀         forall       universal quantifier
    ∃         exists       existential quantifier
    λ         fun          lambda
    ∧         /\           conjunction
    ∨         \/           disjunction
    ¬         not          negation
    ≠         !=           inequality
    ≤         <=           less-or-equal
    ≥         >=           greater-or-equal
    ∈         in           membership
    ⊆         subseteq     subset
    ←         <-           reverse-rewrite marker
    ×         ><           product type
    ·         *            multiplication
    ⟨ ⟩       << >>? (no)  anonymous constructor brackets
    ∘         circ         function composition

Comments: `--` to end of line, nestable block comments `/- ... -/`,
doc comments `/-- ... -/` (attached to the next declaration).
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Optional


class LexError(Exception):
    def __init__(self, msg: str, line: int, col: int) -> None:
        super().__init__(f"{line}:{col}: {msg}")
        self.msg, self.line, self.col = msg, line, col


@dataclass(frozen=True)
class Token:
    kind: str          # IDENT NUM STR SYM KW DOC EOF
    text: str
    line: int          # 1-based
    col: int           # 1-based
    value: Optional[object] = None  # Fraction for NUM, str for STR/DOC

    def __repr__(self) -> str:
        return f"{self.kind}({self.text!r})@{self.line}:{self.col}"


KEYWORDS = {
    "def", "define", "axiom", "constant", "theorem", "lemma", "proposition",
    "corollary", "example", "inductive", "structure", "import", "namespace",
    "end", "open", "by", "fun", "forall", "exists", "not", "in", "with",
    "notation", "infixl", "infixr", "prefix", "postfix",
    "plot", "calc", "at", "where", "then", "else", "if", "match", "sorry",
}

# multi-char ASCII symbols, longest first
MULTI = [
    ":=", "->", "<->", "<-", "=>", "==", "!=", "<=", ">=", "/\\", "\\/",
    "><", "@[", "..", "∘",
]
MULTI.sort(key=len, reverse=True)

# Unicode symbol -> canonical symbol text
UNI = {
    "→": "->", "⟶": "->", "↔": "<->", "←": "<-", "⇒": "=>",
    "∧": "/\\", "∨": "\\/", "¬": "¬", "≠": "!=", "≤": "<=", "≥": ">=",
    "∀": "∀", "∃": "∃", "λ": "λ", "∈": "∈", "∉": "∉", "⊆": "⊆",
    "×": "><", "·": "*", "⟨": "⟨", "⟩": "⟩", "∘": "∘", "√": "√",
    "≔": ":=",
}

SINGLE = set("()[]{},:;=+-*/%^<>|_.@!#⟨⟩∀∃λ∈∉⊆¬∘√")

# characters allowed to CONTINUE an identifier beyond isalpha/isdigit/_
IDENT_EXTRA = set("_'₀₁₂₃₄₅₆₇₈₉ₐₑᵢⱼₖₗₘₙₚₛₜ")
# standalone symbol identifiers (mathematical constants/aliases)
SYMBOL_IDENTS = set("∞⊤⊥ℕℤℚℝℂπΩ∅")


def _is_ident_start(ch: str) -> bool:
    return ch.isalpha() or ch == "_" or ch in SYMBOL_IDENTS


def _is_ident_cont(ch: str) -> bool:
    return ch.isalpha() or ch.isdigit() or ch in IDENT_EXTRA or ch in SYMBOL_IDENTS


def tokenize(src: str) -> list[Token]:
    toks: list[Token] = []
    i, line, col = 0, 1, 1
    n = len(src)

    def advance(k: int = 1) -> None:
        nonlocal i, line, col
        for _ in range(k):
            if i < n and src[i] == "\n":
                line += 1
                col = 1
            else:
                col += 1
            i += 1

    while i < n:
        ch = src[i]

        # whitespace
        if ch in " \t\r\n":
            advance()
            continue

        # line comment
        if src.startswith("--", i):
            while i < n and src[i] != "\n":
                advance()
            continue

        # block / doc comment (nestable)
        if src.startswith("/-", i):
            is_doc = src.startswith("/--", i)
            l0, c0 = line, col
            depth = 0
            start = i
            while i < n:
                if src.startswith("/-", i):
                    depth += 1
                    advance(2)
                elif src.startswith("-/", i):
                    depth -= 1
                    advance(2)
                    if depth == 0:
                        break
                else:
                    advance()
            if depth != 0:
                raise LexError("unterminated block comment", l0, c0)
            if is_doc:
                body = src[start + 3: i - 2].strip()
                toks.append(Token("DOC", body, l0, c0, body))
            continue

        # string literal
        if ch == '"':
            l0, c0 = line, col
            advance()
            buf = []
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    esc = src[i + 1]
                    buf.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(esc, esc))
                    advance(2)
                else:
                    buf.append(src[i])
                    advance()
            if i >= n:
                raise LexError("unterminated string", l0, c0)
            advance()
            s = "".join(buf)
            toks.append(Token("STR", s, l0, c0, s))
            continue

        # number: 123, 3.14  (exact: decimals become exact fractions)
        if ch.isdigit():
            l0, c0 = line, col
            start = i
            while i < n and src[i].isdigit():
                advance()
            is_dec = False
            if i + 1 < n and src[i] == "." and src[i + 1].isdigit():
                is_dec = True
                advance()
                while i < n and src[i].isdigit():
                    advance()
            text = src[start:i]
            value = Fraction(text) if is_dec else Fraction(int(text))
            toks.append(Token("NUM", text, l0, c0, value))
            continue

        # unicode symbols (canonicalized)
        if ch in UNI and ch not in SYMBOL_IDENTS:
            toks.append(Token("SYM", UNI[ch], line, col))
            advance()
            continue

        # identifiers / keywords (Greek letters, ℕ/ℝ/π/∞ included)
        if _is_ident_start(ch):
            l0, c0 = line, col
            start = i
            advance()
            while i < n and _is_ident_cont(src[i]):
                advance()
            text = src[start:i]
            if text in KEYWORDS:
                toks.append(Token("KW", text, l0, c0))
            else:
                toks.append(Token("IDENT", text, l0, c0))
            continue

        # multi-char ASCII symbols
        matched = False
        for m in MULTI:
            if src.startswith(m, i):
                toks.append(Token("SYM", m, line, col))
                advance(len(m))
                matched = True
                break
        if matched:
            continue

        if ch in SINGLE:
            toks.append(Token("SYM", ch, line, col))
            advance()
            continue

        # any other Unicode math/symbol character lexes as a SYM token, so
        # user-defined operators (⊕, ⊗, ≈, ...) work out of the box
        import unicodedata
        if unicodedata.category(ch).startswith("S"):
            toks.append(Token("SYM", ch, line, col))
            advance()
            continue

        raise LexError(f"unexpected character {ch!r}", line, col)

    toks.append(Token("EOF", "", line, col))
    return toks
