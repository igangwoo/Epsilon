"""Proof visualization (product spec section 8).

Turns the tactic trace produced while checking a theorem into a proof tree
and renders it as:

- plain text (REPL / CLI)
- natural-deduction / sequent style (premises above a rule bar)
- SVG (IDE panel, file export)
- LaTeX (`bussproofs`-style, for papers)

The tree is derived from `epsilon.elab.tactics.TraceStep` records, which
carry the goal each tactic acted on, the goals it produced, and an
inference-rule label. Failed proofs are representable too: a node whose
goal was never closed is marked `open`, so the IDE can show where a proof
stops rather than only that it failed.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Iterable, Optional

RULE_NAMES = {
    "→I/∀I": "→I / ∀I",
    "∃I": "∃I",
    "=I": "refl",
    "=E": "subst",
    "=sym": "symm",
    "=trans": "trans",
    "⊤I": "⊤I",
    "⊥E": "⊥E",
    "hyp": "hyp",
    "cut": "cut",
    "defeq": "≡",
    "compute": "compute",
    "search": "auto",
    "sorry": "sorry",
}


@dataclass
class ProofNode:
    goal_id: int
    tactic: str
    rule: str
    target: str
    hyps: list[tuple[str, str]] = field(default_factory=list)
    children: list["ProofNode"] = field(default_factory=list)
    span: tuple[int, int, int, int] = (0, 0, 0, 0)
    open: bool = False          # goal never closed (failed / partial proof)
    oracle: Optional[str] = None  # "cas" / "numeric" when closed by an oracle

    def walk(self) -> Iterable["ProofNode"]:
        yield self
        for c in self.children:
            yield from c.walk()

    def depth(self) -> int:
        return 1 + max((c.depth() for c in self.children), default=0)

    def size(self) -> int:
        return 1 + sum(c.size() for c in self.children)


def build_tree(trace: list) -> Optional[ProofNode]:
    """Build the proof tree from a theorem's trace (root = first goal)."""
    if not trace:
        return None
    by_goal: dict[int, ProofNode] = {}
    order: list[ProofNode] = []
    for step in trace:
        rule = getattr(step, "rule", "") or ""
        node = ProofNode(
            goal_id=step.goal_id,
            tactic=step.tactic,
            rule=rule,
            target=step.before_target,
            hyps=list(step.before_hyps),
            span=tuple(step.span) if step.span else (0, 0, 0, 0),
            oracle=(rule.split(":", 1)[1] if rule.startswith("oracle:") else None),
        )
        # a goal acted on twice (e.g. simp then rfl) keeps the first node as
        # the parent and chains the later ones underneath
        if step.goal_id in by_goal:
            by_goal[step.goal_id].children.append(node)
        by_goal[step.goal_id] = node
        order.append(node)

    root = order[0]
    for step, node in zip(trace, order):
        for gid in step.after_goals:
            child = by_goal.get(gid)
            if child is not None and child is not node and child not in node.children:
                node.children.append(child)

    # goals that appear as produced but never acted on are still open
    produced = {gid for step in trace for gid in step.after_goals}
    acted = {step.goal_id for step in trace}
    for gid in sorted(produced - acted):
        placeholder = ProofNode(goal_id=gid, tactic="", rule="", target="(open)",
                                open=True)
        for step, node in zip(trace, order):
            if gid in step.after_goals:
                node.children.append(placeholder)
                break
    return root


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def render_text(root: Optional[ProofNode], show_hyps: bool = False,
                indent: str = "") -> str:
    """Indented tree, the shape the CLI and REPL print."""
    if root is None:
        return "(no proof steps)"
    lines: list[str] = []

    def emit(node: ProofNode, prefix: str, is_last: bool, is_root: bool) -> None:
        connector = "" if is_root else ("└─ " if is_last else "├─ ")
        rule = RULE_NAMES.get(node.rule, node.rule)
        tag = f"[{rule}] " if rule else ""
        mark = "  ⚠ open" if node.open else ""
        label = node.tactic or "(unfinished)"
        lines.append(f"{prefix}{connector}{tag}{label}{mark}")
        body_prefix = prefix + ("" if is_root else ("   " if is_last else "│  "))
        lines.append(f"{body_prefix}   ⊢ {node.target}")
        if show_hyps and node.hyps:
            for name, ty in node.hyps:
                lines.append(f"{body_prefix}   {name} : {ty}")
        for i, child in enumerate(node.children):
            emit(child, body_prefix, i == len(node.children) - 1, False)

    emit(root, indent, True, True)
    return "\n".join(lines)


def render_sequent(root: Optional[ProofNode]) -> str:
    """Natural-deduction style: premises above a rule bar, conclusion below.

    Rendered bottom-up the way a derivation is written on paper, with the
    root (the theorem) at the bottom.
    """
    if root is None:
        return "(no proof steps)"

    def block(node: ProofNode) -> list[str]:
        conclusion = f"⊢ {node.target}"
        if not node.children:
            leaf = f"{conclusion}"
            rule = RULE_NAMES.get(node.rule, node.rule) or node.tactic
            bar = "─" * max(len(leaf), 8)
            note = "  ⚠ open" if node.open else f"  ({rule})"
            return [bar, leaf + note]
        child_blocks = [block(c) for c in node.children]
        gap = "   "
        height = max(len(b) for b in child_blocks)
        widths = [max(len(l) for l in b) for b in child_blocks]
        rows: list[str] = []
        for i in range(height):
            parts = []
            for b, w in zip(child_blocks, widths):
                pad_top = height - len(b)
                line = b[i - pad_top] if i >= pad_top else ""
                parts.append(line.ljust(w))
            rows.append(gap.join(parts).rstrip())
        rule = RULE_NAMES.get(node.rule, node.rule) or node.tactic
        width = max([len(r) for r in rows] + [len(conclusion)])
        rows.append("─" * width + f"  ({rule})")
        rows.append(conclusion)
        return rows

    return "\n".join(block(root))


# ---------------------------------------------------------------------------
# SVG rendering
# ---------------------------------------------------------------------------

_LIGHT = {"bg": "#ffffff", "fg": "#1d1d1f", "muted": "#6e6e73",
          "line": "#c7c7cc", "node": "#f5f5f7", "open": "#d93025",
          "oracle": "#b26a00", "accent": "#5856d6"}
_DARK = {"bg": "#1c1c1e", "fg": "#f5f5f7", "muted": "#98989d",
         "line": "#48484a", "node": "#2c2c2e", "open": "#ff6961",
         "oracle": "#ffb340", "accent": "#a5a3ff"}


def render_svg(root: Optional[ProofNode], dark: bool = False,
               char_width: float = 7.4, line_height: int = 22,
               v_gap: int = 46, h_gap: int = 26) -> str:
    """Layered SVG of the proof tree: rule chip, tactic, and goal per node."""
    palette = _DARK if dark else _LIGHT
    if root is None:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="320" '
                f'height="60"><rect width="320" height="60" fill="'
                f'{palette["bg"]}"/><text x="16" y="34" font-family="ui-sans-'
                f'serif,system-ui" font-size="14" fill="{palette["muted"]}">'
                f'no proof steps</text></svg>')

    pad_x, pad_y = 12, 8

    def node_label(n: ProofNode) -> tuple[str, str]:
        rule = RULE_NAMES.get(n.rule, n.rule)
        head = f"{n.tactic or '(unfinished)'}"
        if rule:
            head = f"{head}   [{rule}]"
        return head, f"⊢ {n.target}"

    def node_size(n: ProofNode) -> tuple[float, float]:
        head, goal = node_label(n)
        w = max(len(head), len(goal)) * char_width + 2 * pad_x
        return max(w, 120.0), 2 * line_height + 2 * pad_y

    # first pass: subtree widths
    widths: dict[int, float] = {}

    def measure(n: ProofNode) -> float:
        own, _ = node_size(n)
        if not n.children:
            widths[id(n)] = own
            return own
        total = sum(measure(c) for c in n.children) + h_gap * (len(n.children) - 1)
        w = max(own, total)
        widths[id(n)] = w
        return w

    total_width = measure(root)

    placed: list[tuple[ProofNode, float, float, float, float]] = []
    edges: list[tuple[float, float, float, float]] = []

    def place(n: ProofNode, left: float, top: float) -> tuple[float, float]:
        own_w, own_h = node_size(n)
        span = widths[id(n)]
        cx = left + span / 2
        x = cx - own_w / 2
        placed.append((n, x, top, own_w, own_h))
        child_top = top + own_h + v_gap
        cursor = left + max(0.0, (span - (
            sum(widths[id(c)] for c in n.children)
            + h_gap * (len(n.children) - 1))) / 2) if n.children else left
        for c in n.children:
            ccx, ctop = place(c, cursor, child_top)
            edges.append((cx, top + own_h, ccx, ctop))
            cursor += widths[id(c)] + h_gap
        return cx, top

    place(root, 0.0, 0.0)
    height = max(top + h for _, _, top, _, h in placed) + 24
    width = total_width + 24

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
        f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'font-family="ui-monospace,SFMono-Regular,Menlo,monospace">',
        f'<rect width="{width:.0f}" height="{height:.0f}" fill="{palette["bg"]}"/>',
        '<g stroke-width="1.5" fill="none">',
    ]
    for x1, y1, x2, y2 in edges:
        my = (y1 + y2) / 2
        parts.append(
            f'<path d="M {x1+12:.1f} {y1+12:.1f} C {x1+12:.1f} {my:.1f} '
            f'{x2+12:.1f} {my:.1f} {x2+12:.1f} {y2+12:.1f}" '
            f'stroke="{palette["line"]}"/>')
    parts.append("</g>")

    for n, x, y, w, h in placed:
        head, goal = node_label(n)
        stroke = palette["open"] if n.open else (
            palette["oracle"] if n.oracle else palette["line"])
        parts.append(
            f'<rect x="{x+12:.1f}" y="{y+12:.1f}" width="{w:.1f}" '
            f'height="{h:.1f}" rx="10" fill="{palette["node"]}" '
            f'stroke="{stroke}" stroke-width="1.25"/>')
        head_fill = palette["open"] if n.open else (
            palette["oracle"] if n.oracle else palette["accent"])
        parts.append(
            f'<text x="{x + pad_x + 12:.1f}" y="{y + pad_y + 15 + 12:.1f}" '
            f'font-size="12.5" fill="{head_fill}">{html.escape(head)}</text>')
        parts.append(
            f'<text x="{x + pad_x + 12:.1f}" '
            f'y="{y + pad_y + line_height + 15 + 12:.1f}" font-size="12.5" '
            f'fill="{palette["fg"]}">{html.escape(goal)}</text>')

    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# LaTeX rendering
# ---------------------------------------------------------------------------

def render_latex(root: Optional[ProofNode], standalone: bool = False) -> str:
    """A `bussproofs` derivation. Goals are typeset verbatim, since the
    surface notation is already mathematical."""
    if root is None:
        return "% no proof steps"

    lines: list[str] = []

    def emit(n: ProofNode) -> None:
        for c in n.children:
            emit(c)
        rule = RULE_NAMES.get(n.rule, n.rule) or n.tactic or "?"
        concl = _latex_escape(n.target)
        if not n.children:
            lines.append(f"\\AxiomC{{$\\vdash {concl}$}}")
            if n.open:
                lines.append("\\RightLabel{\\scriptsize open}")
                lines.append(f"\\UnaryInfC{{$\\vdash {concl}$}}")
            return
        lines.append(f"\\RightLabel{{\\scriptsize {_latex_escape(rule)}}}")
        arity = {1: "Unary", 2: "Binary", 3: "Trinary"}.get(len(n.children))
        if arity is None:
            lines.append(f"\\noLine\\UnaryInfC{{$\\vdash {concl}$}}")
            return
        lines.append(f"\\{arity}InfC{{$\\vdash {concl}$}}")

    emit(root)
    body = ("\\begin{prooftree}\n" + "\n".join(lines) + "\n\\end{prooftree}")
    if not standalone:
        return body
    return ("\\documentclass{article}\n"
            "\\usepackage{amsmath,amssymb,bussproofs}\n"
            "\\begin{document}\n" + body + "\n\\end{document}\n")


def _latex_escape(s: str) -> str:
    out = s
    for a, b in (("\\", "\\textbackslash{}"), ("&", "\\&"), ("%", "\\%"),
                 ("$", "\\$"), ("#", "\\#"), ("_", "\\_"), ("{", "\\{"),
                 ("}", "\\}"), ("~", "\\textasciitilde{}"),
                 ("^", "\\textasciicircum{}")):
        out = out.replace(a, b)
    replacements = {
        "∀": "\\forall ", "∃": "\\exists ", "λ": "\\lambda ", "→": "\\to ",
        "↔": "\\leftrightarrow ", "∧": "\\land ", "∨": "\\lor ",
        "¬": "\\lnot ", "≤": "\\leq ", "≥": "\\geq ", "≠": "\\neq ",
        "∈": "\\in ", "⊆": "\\subseteq ", "×": "\\times ", "π": "\\pi ",
        "ℕ": "\\mathbb{N}", "ℤ": "\\mathbb{Z}", "ℚ": "\\mathbb{Q}",
        "ℝ": "\\mathbb{R}", "ℂ": "\\mathbb{C}", "⊢": "\\vdash ",
        "≡": "\\equiv ", "⊤": "\\top ", "⊥": "\\bot ",
    }
    for a, b in replacements.items():
        out = out.replace(a, b)
    return out


# ---------------------------------------------------------------------------
# JSON (for the IDE proof panel)
# ---------------------------------------------------------------------------

def to_dict(node: Optional[ProofNode]) -> Optional[dict]:
    if node is None:
        return None
    return {
        "goal_id": node.goal_id,
        "tactic": node.tactic,
        "rule": node.rule,
        "rule_label": RULE_NAMES.get(node.rule, node.rule),
        "target": node.target,
        "hyps": [{"name": n, "type": t} for n, t in node.hyps],
        "span": list(node.span),
        "open": node.open,
        "oracle": node.oracle,
        "children": [to_dict(c) for c in node.children],
    }
