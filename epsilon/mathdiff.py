"""Mathematical diff (product spec section 30).

A textual diff tells you a line changed. For mathematics you want to know
something sharper: did the *statement* change, or only its proof? Did a
theorem lose its Formally Proven status? Did a dependency on a new axiom
appear? Those are the questions a reviewer of a mathematics repository
actually asks, and they are all answerable from the checked environment
rather than from the source text.

Comparison is between two `Session`s (typically: the working tree and a
checked-out revision), by declaration name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .kernel.env import DeclKind, Environment
from .elab.context import LOCAL_MARK
from .elab.pp import pp
from .project import Session, STATUS_LABELS

# Ordered worst-to-best so a status change can be called a regression.
STATUS_RANK = {"heuristic": 0, "numeric": 1, "symbolic": 2, "proven": 3}


@dataclass
class DeclDiff:
    name: str
    change: str                      # added | removed | statement | proof | status | unchanged
    kind: str = ""
    module: Optional[str] = None
    old_statement: Optional[str] = None
    new_statement: Optional[str] = None
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    added_axioms: list[str] = field(default_factory=list)
    removed_axioms: list[str] = field(default_factory=list)
    old_hash: Optional[str] = None
    new_hash: Optional[str] = None

    @property
    def is_regression(self) -> bool:
        """True when the change weakens what the repository already proved.

        A newly added declaration is never a regression, however many axioms
        it needs - it took nothing away. What counts is an existing result
        disappearing, dropping below the status it had, or picking up an
        axiom dependency it did not have before.
        """
        if self.change == "added":
            return False
        if self.change == "removed":
            return True
        if self.old_status and self.new_status:
            if STATUS_RANK.get(self.new_status, 0) < STATUS_RANK.get(
                    self.old_status, 0):
                return True
        return bool(self.added_axioms)

    def describe(self) -> str:
        if self.change == "added":
            label = STATUS_LABELS.get(self.new_status or "", "")
            line = f"+ {self.name} : {self.new_statement}  {label}".rstrip()
            if self.added_axioms:
                line += f"\n    uses axioms: {', '.join(self.added_axioms)}"
            return line
        if self.change == "removed":
            return f"- {self.name} : {self.old_statement}"
        if self.change == "statement":
            return (f"~ {self.name} STATEMENT CHANGED\n"
                    f"    was: {self.old_statement}\n"
                    f"    now: {self.new_statement}")
        bits = []
        if self.change == "proof":
            what = "definition body" if self.kind == "definition" else "proof"
            bits.append(f"~ {self.name} {what} changed "
                        f"(statement identical)")
        if self.old_status != self.new_status:
            bits.append(f"  status: {STATUS_LABELS.get(self.old_status or '', '?')}"
                        f" → {STATUS_LABELS.get(self.new_status or '', '?')}")
        if self.added_axioms:
            bits.append(f"  NEW AXIOM DEPENDENCIES: {', '.join(self.added_axioms)}")
        if self.removed_axioms:
            bits.append(f"  axioms no longer needed: "
                        f"{', '.join(self.removed_axioms)}")
        return "\n".join(bits) if bits else f"= {self.name}"


@dataclass
class MathDiff:
    decls: list[DeclDiff] = field(default_factory=list)

    @property
    def added(self) -> list[DeclDiff]:
        return [d for d in self.decls if d.change == "added"]

    @property
    def removed(self) -> list[DeclDiff]:
        return [d for d in self.decls if d.change == "removed"]

    @property
    def changed(self) -> list[DeclDiff]:
        return [d for d in self.decls
                if d.change not in ("added", "removed", "unchanged")]

    @property
    def regressions(self) -> list[DeclDiff]:
        return [d for d in self.decls if d.is_regression]

    def summary(self) -> str:
        lines = [
            f"{len(self.added)} added, {len(self.removed)} removed, "
            f"{len(self.changed)} changed"
        ]
        if self.regressions:
            lines.append(f"⚠ {len(self.regressions)} regression(s): "
                         f"{', '.join(d.name for d in self.regressions)}")
        return "\n".join(lines)

    def format(self, include_unchanged: bool = False) -> str:
        out = []
        for d in self.decls:
            if d.change == "unchanged" and not include_unchanged:
                continue
            out.append(d.describe())
        out.append("")
        out.append(self.summary())
        return "\n".join(out)

    def to_dict(self) -> dict:
        return {
            "decls": [
                {"name": d.name, "change": d.change, "kind": d.kind,
                 "module": d.module,
                 "old_statement": d.old_statement,
                 "new_statement": d.new_statement,
                 "old_status": d.old_status, "new_status": d.new_status,
                 "added_axioms": d.added_axioms,
                 "removed_axioms": d.removed_axioms,
                 "regression": d.is_regression}
                for d in self.decls if d.change != "unchanged"
            ],
            "summary": {"added": len(self.added), "removed": len(self.removed),
                        "changed": len(self.changed),
                        "regressions": len(self.regressions)},
        }


def _visible_decls(session: Session,
                   modules: Optional[list[str]] = None) -> dict[str, dict]:
    env: Environment = session.env
    out: dict[str, dict] = {}
    for name in env.order:
        d = env.decls[name]
        if LOCAL_MARK in name or name.startswith("$"):
            continue
        if d.module in (None, "core"):
            continue
        if modules is not None and d.module not in modules:
            continue
        if d.kind in (DeclKind.CONSTRUCTOR, DeclKind.RECURSOR):
            continue
        status = (env.verification_status(name)
                  if d.kind == DeclKind.THEOREM else None)
        out[name] = {
            "kind": d.kind.value,
            "module": d.module,
            "statement": pp(env, d.type),
            "value_hash": d.hash(),
            "status": status,
            "axioms": sorted(a for a in env.axioms_of(name)
                             if a not in env.trust_axioms),
            "type_repr": repr(d.type),
        }
    return out


def diff_sessions(old: Session, new: Session,
                  modules: Optional[list[str]] = None) -> MathDiff:
    """Compare two checked sessions declaration by declaration."""
    old_decls = _visible_decls(old, modules)
    new_decls = _visible_decls(new, modules)
    result = MathDiff()

    for name in sorted(set(old_decls) | set(new_decls)):
        o, n = old_decls.get(name), new_decls.get(name)
        if o is None:
            result.decls.append(DeclDiff(
                name=name, change="added", kind=n["kind"], module=n["module"],
                new_statement=n["statement"], new_status=n["status"],
                added_axioms=n["axioms"], new_hash=n["value_hash"]))
            continue
        if n is None:
            result.decls.append(DeclDiff(
                name=name, change="removed", kind=o["kind"], module=o["module"],
                old_statement=o["statement"], old_status=o["status"],
                old_hash=o["value_hash"]))
            continue

        added_ax = [a for a in n["axioms"] if a not in o["axioms"]]
        removed_ax = [a for a in o["axioms"] if a not in n["axioms"]]
        statement_changed = o["type_repr"] != n["type_repr"]
        proof_changed = o["value_hash"] != n["value_hash"]

        if statement_changed:
            change = "statement"
        elif proof_changed:
            change = "proof"
        elif o["status"] != n["status"] or added_ax or removed_ax:
            change = "status"
        else:
            change = "unchanged"

        result.decls.append(DeclDiff(
            name=name, change=change, kind=n["kind"], module=n["module"],
            old_statement=o["statement"], new_statement=n["statement"],
            old_status=o["status"], new_status=n["status"],
            added_axioms=added_ax, removed_axioms=removed_ax,
            old_hash=o["value_hash"], new_hash=n["value_hash"]))

    return result


def diff_sources(old_src: str, new_src: str, module: str = "<diff>",
                 project_root: Optional[str] = None) -> MathDiff:
    """Convenience: check two source strings and diff the results."""
    s_old = Session(project_root=project_root)
    s_old.check_source(old_src, module)
    s_new = Session(project_root=project_root)
    s_new.check_source(new_src, module)
    return diff_sessions(s_old, s_new, modules=[module])


def dependency_diff(old: Session, new: Session) -> dict:
    """Which dependency edges appeared or disappeared between two sessions."""
    def edge_set(s: Session) -> set[tuple[str, str]]:
        g = s.dependency_graph()
        return {(e["from"], e["to"]) for e in g["edges"]}

    old_edges, new_edges = edge_set(old), edge_set(new)
    return {
        "added": sorted(f"{a} → {b}" for a, b in new_edges - old_edges),
        "removed": sorted(f"{a} → {b}" for a, b in old_edges - new_edges),
    }
