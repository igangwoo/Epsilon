"""Declarations, environments, and axiom-dependency tracking."""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .term import Term, constants_of


class KernelError(Exception):
    """Raised by the kernel when a term or declaration is rejected."""


class DeclKind(enum.Enum):
    AXIOM = "axiom"
    DEFINITION = "definition"
    THEOREM = "theorem"          # also lemma / proposition / corollary (see meta)
    INDUCTIVE = "inductive"
    CONSTRUCTOR = "constructor"
    RECURSOR = "recursor"
    OPAQUE = "opaque"            # constant with no value (e.g. sin, limit)


# Tracked "trust" axioms used by automation. A theorem whose proof depends on
# one of these is *not* Formally Proven; verification status is derived from
# exactly this transitive axiom set (section 27: never conflate them).
TRUSTED_CAS_AXIOM = "Epsilon.trustedCAS"
TRUSTED_NUMERIC_AXIOM = "Epsilon.trustedNumeric"
SORRY_AXIOM = "Epsilon.sorry"
TRUST_AXIOMS = {TRUSTED_CAS_AXIOM, TRUSTED_NUMERIC_AXIOM, SORRY_AXIOM}

# Verification statuses, worst first. A proof that touches several trust
# axioms takes the *worst* of them - trust does not average out.
STATUS_ORDER = ["heuristic", "numeric", "symbolic", "proven"]

# Built-in trust axiom -> the status it caps a theorem at. Plugins extend
# this per-environment through `Environment.register_trust_axiom`, so an
# oracle a plugin adds can never make its results read as Formally Proven.
BUILTIN_TRUST_STATUS = {
    SORRY_AXIOM: "heuristic",
    TRUSTED_NUMERIC_AXIOM: "numeric",
    TRUSTED_CAS_AXIOM: "symbolic",
}


@dataclass
class Declaration:
    name: str
    kind: DeclKind
    type: Term
    value: Optional[Term] = None       # body for definitions / proof term for theorems
    reducible: bool = True             # participates in delta reduction
    # ---- metadata (never consulted by the trusted checker) ----
    doc: Optional[str] = None
    module: Optional[str] = None
    span: Optional[tuple[int, int, int, int]] = None  # line0,col0,line1,col1
    tags: list[str] = field(default_factory=list)
    statement_kind: Optional[str] = None  # theorem|lemma|proposition|corollary
    attrs: list[str] = field(default_factory=list)     # e.g. ["simp"]
    inductive: Optional[str] = None    # owning inductive for ctors/recursors
    #: user-facing mathematical name, e.g. "Addition.Commutativity" for the
    #: internal identifier `Nat.add_comm`. Purely presentational: the kernel
    #: identifies declarations by `name` and never reads this.
    display_name: Optional[str] = None

    def hash(self) -> str:
        """Stable content hash of statement (+ proof) for reproducibility."""
        h = hashlib.sha256()
        h.update(self.name.encode())
        h.update(repr(self.type).encode())
        if self.value is not None:
            h.update(repr(self.value).encode())
        return h.hexdigest()[:16]


@dataclass
class InductiveInfo:
    name: str
    num_params: int
    constructors: list[str]
    recursors: list[str]           # e.g. ["Nat.rec", "Nat.ind"]
    sort_level: int                # sort the inductive lives in (0 = Prop)
    allow_large_elim: bool         # may eliminate into Type (not just Prop)
    ctor_arg_counts: dict[str, int] = field(default_factory=dict)
    ctor_recursive_args: dict[str, list[int]] = field(default_factory=dict)


class Environment:
    """An ordered map of checked declarations plus inductive metadata."""

    def __init__(self) -> None:
        self.decls: dict[str, Declaration] = {}
        self.order: list[str] = []
        self.inductives: dict[str, InductiveInfo] = {}
        self.ctor_of: dict[str, str] = {}       # constructor -> inductive
        self.recursor_of: dict[str, str] = {}   # recursor -> inductive
        self._axiom_cache: dict[str, frozenset[str]] = {}
        # axiom name -> worst status it forces on dependent theorems
        self.trust_status: dict[str, str] = dict(BUILTIN_TRUST_STATUS)
        # user-facing mathematical name -> internal identifier. A second,
        # purely presentational naming layer: `Addition.Commutativity` and
        # `Nat.add_comm` denote the same declaration, and the kernel only
        # ever knows the latter.
        self.by_display_name: dict[str, str] = {}

    def register_trust_axiom(self, name: str, status: str = "symbolic") -> None:
        """Mark an axiom as an *oracle* axiom, so theorems that depend on it
        are reported at `status` rather than Formally Proven.

        Every decision procedure Epsilon's kernel does not itself verify -
        built-in or from a plugin - must go through here. It is what keeps
        `✓ Formally Proven` meaning exactly one thing.
        """
        if status not in STATUS_ORDER:
            raise KernelError(
                f"unknown verification status {status!r}; "
                f"expected one of {STATUS_ORDER}")
        if status == "proven":
            raise KernelError(
                "a trust axiom cannot claim 'proven': that is the status "
                "reserved for kernel-checked proofs")
        self.trust_status[name] = status
        self._axiom_cache.clear()

    @property
    def trust_axioms(self) -> frozenset[str]:
        return frozenset(self.trust_status)

    # ------------------------------------------------------------------
    # User-facing mathematical names (presentation only)
    # ------------------------------------------------------------------
    def register_display_name(self, internal: str, display: str) -> None:
        """Give a declaration a user-facing mathematical name.

        The name becomes usable wherever the internal identifier is, so a
        proof may cite `Addition.Commutativity` instead of `Nat.add_comm`.
        Collisions are refused rather than silently shadowing something:
        a display name that is already a real declaration, or that already
        points at a different declaration, would make one written name mean
        two things depending on what happened to be loaded.
        """
        existing = self.by_display_name.get(display)
        if existing is not None and existing != internal:
            raise KernelError(
                f"mathematical name '{display}' is already the name of "
                f"'{existing}'; it cannot also name '{internal}'")
        if display in self.decls:
            raise KernelError(
                f"mathematical name '{display}' collides with the internal "
                f"identifier of an existing declaration")
        self.by_display_name[display] = internal
        decl = self.decls.get(internal)
        if decl is not None:
            decl.display_name = display

    def resolve_display_name(self, display: str) -> Optional[str]:
        """Internal identifier for a user-facing name, if one is registered."""
        return self.by_display_name.get(display)

    def display_name_of(self, internal: str) -> Optional[str]:
        decl = self.decls.get(internal)
        return decl.display_name if decl is not None else None

    # ------------------------------------------------------------------
    def contains(self, name: str) -> bool:
        return name in self.decls

    def get(self, name: str) -> Optional[Declaration]:
        return self.decls.get(name)

    def expect(self, name: str) -> Declaration:
        d = self.decls.get(name)
        if d is None:
            raise KernelError(f"unknown constant '{name}'")
        return d

    def add_unchecked(self, decl: Declaration) -> None:
        """Insert a declaration. Callers must have type-checked it first
        (typecheck.add_decl is the checked entry point)."""
        if decl.name in self.decls:
            raise KernelError(f"duplicate declaration '{decl.name}'")
        self.decls[decl.name] = decl
        self.order.append(decl.name)
        self._axiom_cache.clear()

    # ------------------------------------------------------------------
    # Axiom-dependency tracking (section 3/9/27)
    # ------------------------------------------------------------------
    def axioms_of(self, name: str, _visiting: Optional[set[str]] = None) -> frozenset[str]:
        """Transitive set of axiom names a declaration depends on."""
        cached = self._axiom_cache.get(name)
        if cached is not None:
            return cached
        decl = self.decls.get(name)
        if decl is None:
            return frozenset()
        if _visiting is None:
            _visiting = set()
        if name in _visiting:
            return frozenset()
        _visiting.add(name)
        out: set[str] = set()
        if decl.kind == DeclKind.AXIOM:
            out.add(name)
        refs: set[str] = set()
        refs.update(constants_of(decl.type))
        if decl.value is not None:
            refs.update(constants_of(decl.value))
        for ref in refs:
            if ref != name:
                out.update(self.axioms_of(ref, _visiting))
        _visiting.discard(name)
        result = frozenset(out)
        self._axiom_cache[name] = result
        return result

    def direct_deps_of(self, name: str) -> frozenset[str]:
        """Direct constant references from a declaration (statement + proof)."""
        decl = self.decls.get(name)
        if decl is None:
            return frozenset()
        refs: set[str] = set(constants_of(decl.type))
        if decl.value is not None:
            refs.update(constants_of(decl.value))
        refs.discard(name)
        return frozenset(refs)

    def verification_status(self, name: str) -> str:
        """Derive the honest verification status of a checked declaration.

        - "proven"    : kernel-checked, no trust axioms (Formally Proven;
                        ordinary mathematical axioms like choice are listed
                        separately, as in Lean's #print axioms)
        - "symbolic"  : proof relies on a symbolic decision procedure
        - "numeric"   : proof relies on numerical evidence
        - "heuristic" : proof contains sorry / unfinished parts

        When several trust axioms are involved the worst one wins.
        """
        worst = "proven"
        for ax in self.axioms_of(name):
            status = self.trust_status.get(ax)
            if status is not None and STATUS_ORDER.index(status) < \
                    STATUS_ORDER.index(worst):
                worst = status
        return worst

    # ------------------------------------------------------------------
    def theorems(self) -> list[Declaration]:
        return [self.decls[n] for n in self.order
                if self.decls[n].kind == DeclKind.THEOREM]

    def snapshot_len(self) -> int:
        return len(self.order)

    def rollback_to(self, n: int) -> None:
        """Drop declarations added after snapshot point n (REPL undo support)."""
        while len(self.order) > n:
            name = self.order.pop()
            self.decls.pop(name, None)
            info = self.inductives.pop(name, None)
            if info:
                for c in info.constructors:
                    self.ctor_of.pop(c, None)
                for r in info.recursors:
                    self.recursor_of.pop(r, None)
        self._axiom_cache.clear()
