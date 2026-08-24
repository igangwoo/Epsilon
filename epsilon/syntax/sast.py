"""Surface AST (concrete-ish syntax tree).

Every node carries a source span for diagnostics, IDE hover, and
source <-> proof-node navigation. The elaborator (epsilon/elab) turns
this into kernel terms; exporters and the pretty-printer can work from
either level.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional, Union

Span = tuple[int, int, int, int]  # line0, col0, line1, col1  (1-based, inclusive start)


@dataclass
class Node:
    span: Span = field(default=(0, 0, 0, 0), kw_only=True)


# ---------------------------------------------------------------------------
# Expressions
# ---------------------------------------------------------------------------

@dataclass
class Expr(Node):
    pass


@dataclass
class SIdent(Expr):
    name: str = ""


@dataclass
class SNum(Expr):
    value: Fraction = Fraction(0)
    is_decimal: bool = False


@dataclass
class SStr(Expr):
    value: str = ""


@dataclass
class SApp(Expr):
    """Application: f(a, b) or juxtaposition f a b (both normalize here)."""
    fn: Expr = None  # type: ignore[assignment]
    args: list[Expr] = field(default_factory=list)


@dataclass
class SBinOp(Expr):
    op: str = ""     # canonical symbol text: + - * / ^ = != <= ... /\ \/ <-> ∈ ⊆ ><
    lhs: Expr = None  # type: ignore[assignment]
    rhs: Expr = None  # type: ignore[assignment]


@dataclass
class SUnOp(Expr):
    op: str = ""     # - ¬ √
    operand: Expr = None  # type: ignore[assignment]


@dataclass
class SBinder(Node):
    name: str = "_"
    ty: Optional[Expr] = None
    implicit: bool = False


@dataclass
class SLambda(Expr):
    binders: list[SBinder] = field(default_factory=list)
    body: Expr = None  # type: ignore[assignment]


@dataclass
class SForall(Expr):
    binders: list[SBinder] = field(default_factory=list)
    body: Expr = None  # type: ignore[assignment]


@dataclass
class SExists(Expr):
    binders: list[SBinder] = field(default_factory=list)
    body: Expr = None  # type: ignore[assignment]


@dataclass
class SArrow(Expr):
    lhs: Expr = None  # type: ignore[assignment]
    rhs: Expr = None  # type: ignore[assignment]


@dataclass
class SAnonCtor(Expr):
    """⟨a, b, ...⟩ - elaborated against the expected type's constructor."""
    args: list[Expr] = field(default_factory=list)


@dataclass
class STuple(Expr):
    """(a, b) pairs; elaborates to Prod.mk (or nested)."""
    args: list[Expr] = field(default_factory=list)


@dataclass
class SIf(Expr):
    cond: Expr = None   # type: ignore[assignment]
    then: Expr = None   # type: ignore[assignment]
    els: Expr = None    # type: ignore[assignment]


@dataclass
class SSetOf(Expr):
    """{ x : T | p } set-builder."""
    binder: SBinder = None  # type: ignore[assignment]
    pred: Expr = None       # type: ignore[assignment]


@dataclass
class SSorry(Expr):
    pass


@dataclass
class SAscribe(Expr):
    """(e : T) type ascription."""
    expr: Expr = None  # type: ignore[assignment]
    ty: Expr = None    # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tactics
# ---------------------------------------------------------------------------

@dataclass
class Tactic(Node):
    name: str = ""
    # generic payload; interpretation is per-tactic
    terms: list[Expr] = field(default_factory=list)
    idents: list[str] = field(default_factory=list)
    reverse: bool = False          # rw [← h]
    cases: list["TacticCase"] = field(default_factory=list)  # with | ... => ...
    calc_steps: list[tuple[str, Expr, "ProofLike"]] = field(default_factory=list)
    sub: Optional["ProofLike"] = None   # have ... := by ...


@dataclass
class TacticCase(Node):
    ctor: str = ""
    names: list[str] = field(default_factory=list)
    tactics: list[Tactic] = field(default_factory=list)


@dataclass
class TermProof(Node):
    term: Expr = None  # type: ignore[assignment]


@dataclass
class TacticProof(Node):
    tactics: list[Tactic] = field(default_factory=list)


ProofLike = Union[TermProof, TacticProof]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass
class Command(Node):
    doc: Optional[str] = None
    attrs: list[str] = field(default_factory=list)


@dataclass
class CDef(Command):
    name: str = ""
    binders: list[SBinder] = field(default_factory=list)
    ty: Optional[Expr] = None
    value: Expr = None  # type: ignore[assignment]


@dataclass
class CConstant(Command):
    name: str = ""
    ty: Expr = None  # type: ignore[assignment]


@dataclass
class CAxiom(Command):
    name: str = ""
    binders: list[SBinder] = field(default_factory=list)
    ty: Expr = None  # type: ignore[assignment]


@dataclass
class CTheorem(Command):
    kind: str = "theorem"  # theorem | lemma | proposition | corollary | example
    name: str = ""
    binders: list[SBinder] = field(default_factory=list)
    statement: Expr = None  # type: ignore[assignment]
    proof: Optional[ProofLike] = None


@dataclass
class CInductiveCtor(Node):
    name: str = ""
    ty: Expr = None  # type: ignore[assignment]


@dataclass
class CInductive(Command):
    name: str = ""
    binders: list[SBinder] = field(default_factory=list)
    ty: Optional[Expr] = None
    ctors: list[CInductiveCtor] = field(default_factory=list)


@dataclass
class CStructureField(Node):
    name: str = ""
    ty: Expr = None  # type: ignore[assignment]


@dataclass
class CStructure(Command):
    name: str = ""
    binders: list[SBinder] = field(default_factory=list)
    fields: list[CStructureField] = field(default_factory=list)


@dataclass
class CImport(Command):
    module: str = ""


@dataclass
class CNamespace(Command):
    name: str = ""
    body: list[Command] = field(default_factory=list)


@dataclass
class COpen(Command):
    name: str = ""


@dataclass
class CCheck(Command):
    expr: Expr = None  # type: ignore[assignment]


@dataclass
class CEval(Command):
    expr: Expr = None  # type: ignore[assignment]


@dataclass
class CPlot(Command):
    exprs: list[Expr] = field(default_factory=list)
    var: str = "x"
    lo: Optional[Expr] = None
    hi: Optional[Expr] = None


@dataclass
class CNotation(Command):
    """infixl/infixr/prefix declarations: user-defined operators."""
    fixity: str = "infixl"
    precedence: int = 65
    symbol: str = ""
    target: str = ""   # function name the operator maps to


@dataclass
class CModule(Node):
    commands: list[Command] = field(default_factory=list)
