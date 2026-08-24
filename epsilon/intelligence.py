"""Editor intelligence: completions, hover, go-to-definition, search.

Shared by the web IDE (through the server) and the REPL. Everything is
derived from the live kernel environment, so it is always in sync with what
has actually been checked - no separate index to go stale.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

from .kernel.env import DeclKind
from .elab.context import LOCAL_MARK
from .elab.pp import pp
from .naming import humanize
from .project import Session, STATUS_LABELS

TACTIC_DOCS = {
    "intro": "introduce a ∀/→ binder into the context",
    "intros": "introduce every leading binder",
    "exact": "close the goal with a term of exactly its type",
    "apply": "apply a lemma, leaving its hypotheses as goals",
    "assumption": "close the goal with a matching hypothesis",
    "rfl": "close a = / ↔ goal by definitional equality",
    "symm": "turn a = b into b = a",
    "constructor": "apply the first matching constructor",
    "split": "split a conjunction / iff into its parts",
    "left": "prove the left disjunct",
    "right": "prove the right disjunct",
    "exists": "supply a witness for an ∃ goal",
    "cases": "case-split on an inductive hypothesis",
    "induction": "induct on an inductive hypothesis (with IH)",
    "rw": "rewrite with equalities: rw [h, ← h2]",
    "simp": "normalize and rewrite with @[simp] lemmas",
    "unfold": "unfold definitions by name",
    "decide": "close a decidable goal by computation",
    "norm_num": "close a numeric goal by computation",
    "have": "introduce a proved intermediate fact",
    "show": "restate the goal in a definitionally equal form",
    "calc": "chained equational reasoning",
    "trivial": "try rfl / assumption / decide",
    "exfalso": "reduce any goal to False",
    "contradiction": "close a goal from contradictory hypotheses",
    "cas": "close via the CAS oracle → Symbolically Verified",
    "numeric": "close via the numeric oracle → Numerically Verified",
    "ring": "commutative-ring normalization (falls back to the CAS oracle)",
    "sorry": "admit the goal → Heuristic Result (never proven)",
    "clear": "drop hypotheses from the context",
    "auto": "search for a proof from hypotheses and library lemmas",
}

KEYWORD_DOCS = {
    "def": "define a function, constant, or notation target",
    "theorem": "a proved statement", "lemma": "an auxiliary proved statement",
    "proposition": "a proved statement", "corollary": "a consequence",
    "example": "an anonymous checked statement",
    "axiom": "an assumed statement (tracked in every dependent theorem)",
    "constant": "an opaque constant with no definition",
    "inductive": "an inductive type with constructors",
    "structure": "a record type with projections",
    "import": "load another module", "namespace": "open a name scope",
    "open": "bring a namespace's names into scope",
    "by": "start a tactic proof", "plot": "plot expressions over a range",
    "infixl": "declare a left-associative operator",
    "infixr": "declare a right-associative operator",
    "prefix": "declare a prefix operator",
}


@dataclass
class CompletionItem:
    name: str
    kind: str
    type: str = ""
    doc: str = ""
    status: Optional[str] = None
    #: user-facing mathematical name, and the label to show for it
    display_name: Optional[str] = None
    title: str = ""


def completions(session: Session, prefix: str = "",
                limit: int = 200) -> list[dict]:
    """Name completions from the live environment plus tactics/keywords."""
    prefix_l = prefix.lower()
    items: list[CompletionItem] = []

    for name in session.env.order:
        d = session.env.decls[name]
        if LOCAL_MARK in name or name.startswith("$"):
            continue
        display = d.display_name
        # a search for "commutativity" must find `Nat.add_comm`, so the
        # mathematical name and its humanized label are part of the haystack
        searchable = name.lower()
        if display:
            searchable += "\n" + display.lower() + "\n" + humanize(display).lower()
        if prefix and prefix_l not in searchable:
            continue
        short = name.rsplit(".", 1)[-1]
        if prefix and not (name.lower().startswith(prefix_l)
                           or short.lower().startswith(prefix_l)):
            # keep fuzzy substring matches, but rank them lower
            pass
        status = (session.env.verification_status(name)
                  if d.kind == DeclKind.THEOREM else None)
        items.append(CompletionItem(
            name=name, kind=d.kind.value, type=pp(session.env, d.type),
            doc=d.doc or "", status=status, display_name=display,
            title=humanize(display) if display else name))

    for tac, doc in TACTIC_DOCS.items():
        if not prefix or tac.lower().startswith(prefix_l):
            items.append(CompletionItem(name=tac, kind="tactic", doc=doc))
    for kw, doc in KEYWORD_DOCS.items():
        if not prefix or kw.lower().startswith(prefix_l):
            items.append(CompletionItem(name=kw, kind="keyword", doc=doc))

    def rank(it: CompletionItem) -> tuple:
        short = it.name.rsplit(".", 1)[-1].lower()
        exact = 0 if short == prefix_l else 1
        starts = 0 if short.startswith(prefix_l) else 1
        core = 1 if it.kind in ("constructor", "recursor") else 0
        return (exact, starts, core, len(it.name), it.name)

    items.sort(key=rank)
    return [asdict(i) for i in items[:limit]]


def hover(session: Session, name: str) -> Optional[dict]:
    """Type, documentation, status, and axioms for a name."""
    resolved = session.ctx.resolve_global(name) or name
    d = session.env.get(resolved)
    if d is None:
        if name in TACTIC_DOCS:
            return {"name": name, "kind": "tactic", "doc": TACTIC_DOCS[name]}
        if name in KEYWORD_DOCS:
            return {"name": name, "kind": "keyword", "doc": KEYWORD_DOCS[name]}
        return None
    status = (session.env.verification_status(resolved)
              if d.kind == DeclKind.THEOREM else None)
    axioms = sorted(a for a in session.env.axioms_of(resolved)
                    if a not in session.env.trust_axioms)
    return {
        "name": resolved,
        "display_name": d.display_name,
        "title": humanize(d.display_name) if d.display_name else resolved,
        "kind": d.kind.value,
        "type": pp(session.env, d.type),
        "doc": d.doc or "",
        "module": d.module,
        "span": d.span,
        "status": status,
        "status_label": STATUS_LABELS[status] if status else None,
        "axioms": axioms,
        "hash": d.hash(),
    }


def goto_definition(session: Session, name: str) -> Optional[dict]:
    """Source location of a declaration, when it came from a source file."""
    resolved = session.ctx.resolve_global(name) or name
    d = session.env.get(resolved)
    if d is None or d.span is None or d.module in (None, "core"):
        return None
    return {"name": resolved, "module": d.module, "span": d.span}


def find_references(session: Session, name: str) -> list[dict]:
    """Declarations whose statement or proof mentions `name`."""
    resolved = session.ctx.resolve_global(name) or name
    out = []
    for other in session.env.order:
        if other == resolved or LOCAL_MARK in other:
            continue
        if resolved in session.env.direct_deps_of(other):
            d = session.env.decls[other]
            out.append({"name": other, "kind": d.kind.value,
                        "module": d.module, "span": d.span})
    return out


def search(session: Session, query: str, limit: int = 50) -> list[dict]:
    """Search theorems and definitions by name, statement, or doc text."""
    q = query.lower().strip()
    if not q:
        return []
    results: list[dict] = []
    for name in session.env.order:
        d = session.env.decls[name]
        if LOCAL_MARK in name or name.startswith("$"):
            continue
        stmt = pp(session.env, d.type)
        display = d.display_name
        haystack = (f"{name}\n{stmt}\n{d.doc or ''}\n"
                    f"{display or ''}\n{humanize(display) if display else ''}"
                    ).lower()
        if q not in haystack:
            continue
        status = (session.env.verification_status(name)
                  if d.kind == DeclKind.THEOREM else None)
        results.append({
            "name": name, "kind": d.kind.value, "statement": stmt,
            "display_name": display,
            "title": humanize(display) if display else name,
            "module": d.module, "doc": d.doc, "span": d.span,
            "status": status,
            "status_label": STATUS_LABELS[status] if status else None,
        })
        if len(results) >= limit:
            break
    return results
