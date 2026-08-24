"""Markdown documentation generator (product spec section 25).

Turns one module (or, with `module=None`, everything currently loaded)
into a Markdown page: a Definitions section, an Axioms section, and a
Theorems section with verification-status badges. All statements are
taken from `Session.definition_list` / `Session.theorem_list`, which
already render them through `epsilon.elab.pp.pp` - so the Markdown, the
IDE, and the CLI always show the exact same statement text for a given
declaration - and are shown in inline code.

Verification-status honesty (section 27, `epsilon.project.STATUS_LABELS`):
only theorems get a proven/symbolic/numeric/heuristic badge. Definitions
and axioms are not proof-carrying, so they are never labeled with one;
an axiom is instead marked plainly as assumed.
"""

from __future__ import annotations

from typing import Optional

from ..project import STATUS_LABELS

_KIND_WORD = {
    "definition": "definition", "opaque": "opaque constant",
    "inductive": "inductive type", "axiom": "axiom",
}


def module_to_markdown(session, module: Optional[str] = None) -> str:
    """Generate a Markdown documentation page for `module` (every loaded
    module when `module` is None)."""
    env = session.env
    defs = session.definition_list(module)
    thms = session.theorem_list(module)
    axioms = [d for d in defs if d["kind"] == "axiom"]
    other_defs = [d for d in defs if d["kind"] != "axiom"]

    out = [f"# {module or 'All Modules'}", ""]
    if not defs and not thms:
        out.append("_No declarations in this module._")
        return "\n".join(out) + "\n"

    if other_defs:
        out.append("## Definitions")
        out.append("")
        for d in other_defs:
            out.extend(_definition_section(d))

    if axioms:
        out.append("## Axioms")
        out.append("")
        out.append("Assumed, not proven by the kernel; every theorem that "
                   "depends on one lists it below.")
        out.append("")
        for d in axioms:
            out.extend(_definition_section(d))

    if thms:
        out.append("## Theorems")
        out.append("")
        for t in thms:
            out.extend(_theorem_section(env, t))

    return "\n".join(out) + "\n"


def _definition_section(d: dict) -> list[str]:
    kind_word = _KIND_WORD.get(d["kind"], d["kind"])
    lines = [f"### `{d['name']}`", "", f"*{kind_word}* &nbsp; `{d['type']}`", ""]
    if d["doc"]:
        lines.append(d["doc"])
        lines.append("")
    return lines


def _theorem_section(env, t: dict) -> list[str]:
    label = STATUS_LABELS[t["status"]]
    lines = [f"### `{t['name']}` — **{label}**", "",
             f"`{t['statement']}`", ""]
    if t["doc"]:
        lines.append(t["doc"])
        lines.append("")

    axioms = t["axioms"]
    if axioms:
        lines.append("**Axioms used:** " + ", ".join(f"`{a}`" for a in axioms))
    else:
        lines.append("**Axioms used:** none")

    trust_used = sorted(a for a in env.axioms_of(t["name"])
                        if a in env.trust_axioms)
    if trust_used:
        lines.append("**Trust basis:** " + ", ".join(f"`{a}`" for a in trust_used))

    lines.append("")
    return lines
