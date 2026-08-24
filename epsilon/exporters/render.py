"""Render a checked module as displayable mathematics.

The IDE shows definitions and theorems as typeset mathematics beside the
source. Two rules govern this:

* The source is never modified to make the rendering work. Rendering is a
  separate layer over the same declarations the kernel checked.
* Every block carries the verification status the engine reports. A rendered
  theorem is not thereby a proved one; the label says which it is.

Output is MathML (browsers typeset it natively, so the IDE needs no external
typesetting library) alongside LaTeX for export.
"""

from __future__ import annotations

from typing import Any, Optional

from ..kernel.env import Environment
from ..kernel.term import Term
from . import latex, mathml


def _forms(env: Environment, t: Optional[Term]) -> dict:
    """One term as LaTeX and MathML. Failures are empty, never exceptions."""
    if t is None:
        return {"latex": "", "mathml": ""}
    out = {}
    try:
        out["latex"] = latex.term_to_latex(env, t)
    except Exception:  # noqa: BLE001 - display is best-effort
        out["latex"] = ""
    try:
        out["mathml"] = mathml.term_to_mathml(env, t)
    except Exception:  # noqa: BLE001
        out["mathml"] = ""
    return out


def render_module(session, module: Optional[str] = None) -> dict:
    """Every declaration of `module`, in source order, ready to display."""
    env = session.env
    entries: list[dict[str, Any]] = []
    entries += session.theorem_list(module)
    entries += session.definition_list(module)

    blocks = []
    for entry in entries:
        decl = env.get(entry["name"])
        if decl is None:
            continue
        block = {
            "name": entry["name"],
            "display_name": entry.get("display_name"),
            "title": entry.get("title") or entry["name"],
            "kind": entry.get("kind") or getattr(decl.kind, "value", str(decl.kind)),
            "status": entry.get("status"),
            "status_label": entry.get("status_label"),
            "doc": entry.get("doc") or decl.doc or "",
            "span": list(entry.get("span") or decl.span or (0, 0, 0, 0)),
            # a theorem's statement is its proposition; a definition's is
            # its type signature, which `definition_list` reports as `type`
            "statement": entry.get("statement") or entry.get("type") or "",
            "axioms": entry.get("axioms") or [],
            "type": _forms(env, decl.type),
        }
        # a definition's body is the interesting half; a theorem's proof term
        # is not something to typeset
        if block["kind"] != "theorem" and decl.value is not None:
            block["value"] = _forms(env, decl.value)
        blocks.append(block)

    blocks.sort(key=lambda b: (b["span"][0], b["span"][1]))
    try:
        document = latex.module_to_latex(session, module)
    except Exception:  # noqa: BLE001
        document = ""
    return {"blocks": blocks, "document_latex": document}
