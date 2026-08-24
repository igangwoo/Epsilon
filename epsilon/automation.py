"""Automated proof search and tactic suggestion.

This is untrusted automation, like every tactic: it searches for a *tactic
script* whose resulting proof term the kernel then checks. If the kernel
rejects what the search produced, the theorem is not proven - the search
gets no special privileges.

Two public entry points:

- `search_proof(session, statement_src, ...)` - find a tactic script that
  closes a goal, returning it as source text ready to paste.
- `suggest_tactics(state)` - rank plausible next tactics for an open goal,
  used by the IDE's proof panel and by the error explainer.

Also here: `explain_error`, which turns kernel/elaboration errors into
actionable advice (section 29's "error explanation", done with rules rather
than a language model so it is deterministic and offline).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Optional

from .kernel.env import DeclKind, KernelError
from .kernel.reduce import whnf, def_eq
from .kernel.term import Term, Const, Pi, unfold_app, instantiate
from .syntax import sast as S
from .syntax.parser import parse_expression
from .elab.context import ElabError, LOCAL_MARK
from .elab.elaborator import Elaborator
from .elab.pp import pp
from .elab import tactics as T

# Tactics tried by the search, cheapest and most-likely first.
CLOSERS = ["rfl", "assumption", "trivial", "decide", "simp", "contradiction"]
SPLITTERS = ["intro", "split", "constructor", "left", "right", "exfalso"]

MAX_DEPTH = 6
MAX_NODES = 400


@dataclass
class SearchResult:
    found: bool
    script: list[str] = field(default_factory=list)
    reason: str = ""

    def as_source(self, indent: str = "  ") -> str:
        if not self.found:
            return ""
        return "\n".join(indent + line for line in self.script)


def _clone_state(state: T.ProofState) -> tuple[T.ProofState, dict]:
    """Snapshot the parts of a proof state that tactics mutate."""
    snapshot = {
        "goals": list(state.goals),
        "assignments": {mid: info.assignment
                        for mid, info in state.ctx.mvars.items()},
        "trace_len": len(state.trace),
        "oracles": set(state.used_oracles),
    }
    return state, snapshot


def _restore(state: T.ProofState, snapshot: dict) -> None:
    state.goals = list(snapshot["goals"])
    for mid, asg in snapshot["assignments"].items():
        if mid in state.ctx.mvars:
            state.ctx.mvars[mid].assignment = asg
    for mid, info in state.ctx.mvars.items():
        if mid not in snapshot["assignments"]:
            info.assignment = None
    del state.trace[snapshot["trace_len"]:]
    state.used_oracles = set(snapshot["oracles"])


def _try_tactic(state: T.ProofState, tac: S.Tactic) -> bool:
    try:
        T.run_tactic(state, tac)
        return True
    except (T.TacticError, ElabError, KernelError):
        return False
    except RecursionError:
        return False


def _relevant_lemmas(state: T.ProofState, limit: int = 40) -> list[str]:
    """Lemmas whose conclusion could plausibly close the current goal.

    Ranks by head-symbol agreement between the goal and the lemma's
    conclusion - the cheap version of a discrimination-tree index.
    """
    goal = state.goals[0]
    ghead, _ = unfold_app(whnf(state.env, goal.target, delta=False))
    gname = ghead.name if isinstance(ghead, Const) else None
    scored: list[tuple[int, str]] = []
    for name in state.env.order:
        d = state.env.decls[name]
        if d.kind not in (DeclKind.THEOREM, DeclKind.AXIOM):
            continue
        if LOCAL_MARK in name:
            continue
        concl = d.type
        arity = 0
        while isinstance(concl, Pi):
            concl = concl.body
            arity += 1
            if arity > 12:
                break
        chead, _ = unfold_app(concl)
        cname = chead.name if isinstance(chead, Const) else None
        if gname is not None and cname == gname:
            scored.append((arity, name))
    scored.sort()
    return [n for _, n in scored[:limit]]


def _local_hyp_names(state: T.ProofState) -> list[str]:
    return [ld.username for ld in state.goals[0].locals]


def _inductive_hyps(state: T.ProofState) -> list[tuple[str, Term]]:
    """Hypotheses of an inductive type worth case-splitting on (∧, ∨, ∃)."""
    out: list[tuple[str, Term]] = []
    for ld in reversed(state.goals[0].locals):
        try:
            ty = whnf(state.env, ld.ty, delta=False)
        except KernelError:
            continue
        head, _ = unfold_app(ty)
        if not isinstance(head, Const):
            continue
        info = state.env.inductives.get(head.name)
        if info is None or head.name == "Eq":
            continue
        # only split things that actually carry structure
        if info.constructors and any(info.ctor_arg_counts.get(c, 0)
                                     for c in info.constructors):
            out.append((ld.username, ld.ty))
    return out


def suggest_tactics(state: T.ProofState, limit: int = 8) -> list[dict]:
    """Rank next tactics for the current goal (no state mutation)."""
    if not state.goals:
        return []
    goal = state.goals[0]
    target = whnf(state.env, goal.target, delta=False)
    head, args = unfold_app(target)
    hname = head.name if isinstance(head, Const) else None
    out: list[dict] = []

    def add(text: str, why: str, confidence: float) -> None:
        out.append({"tactic": text, "why": why, "confidence": confidence})

    if isinstance(target, Pi):
        add("intro h", "the goal is a ∀/→; introduce its binder", 0.9)
    if hname == "Eq":
        add("rfl", "both sides may already be definitionally equal", 0.8)
        add("simp", "normalize and apply @[simp] lemmas", 0.6)
        add("rw [h]", "rewrite with an equation from the context", 0.5)
    if hname == "And":
        add("split", "an ∧ goal splits into its two parts", 0.9)
    if hname == "Or":
        add("left", "prove the left disjunct", 0.6)
        add("right", "prove the right disjunct", 0.6)
    if hname == "Iff":
        add("split", "an ↔ goal splits into both implications", 0.9)
    if hname == "Exists":
        add("exists ?w", "supply a witness for the ∃", 0.85)
    if hname == "False":
        add("contradiction", "derive False from contradictory hypotheses", 0.7)
    if hname in ("Nat.le", "Nat.lt", "Real.le", "Real.lt", "Int.le", "Int.lt"):
        add("decide", "close a numeric comparison by computation", 0.7)

    for ld in reversed(goal.locals):
        try:
            if def_eq(state.env, ld.ty, goal.target):
                add(f"exact {ld.username}",
                    f"hypothesis `{ld.username}` already has this type", 0.99)
                break
        except KernelError:
            continue

    for name in _relevant_lemmas(state, limit=6):
        add(f"apply {name}",
            f"`{name}` concludes with the same head symbol", 0.45)

    if state.oracles.get("cas"):
        add("cas", "close via the CAS oracle (→ Symbolically Verified, "
                   "NOT formally proven)", 0.3)
    if state.oracles.get("numeric"):
        add("numeric", "close via the numeric oracle (→ Numerically Verified, "
                       "NOT formally proven)", 0.2)

    out.sort(key=lambda d: -d["confidence"])
    return out[:limit]


def _search(state: T.ProofState, depth: int, budget: list[int],
            script: list[str]) -> bool:
    """Depth-first search over tactic scripts. Returns True when all goals
    of the *sub-tree entered at this call* are closed."""
    if not state.goals:
        return True
    if depth <= 0 or budget[0] <= 0:
        return False
    budget[0] -= 1

    goal = state.goals[0]
    n_goals = len(state.goals)

    # 1. closers (never branch)
    for name in CLOSERS:
        _, snap = _clone_state(state)
        if _try_tactic(state, S.Tactic(name=name)):
            if len(state.goals) < n_goals:
                script.append(name)
                if _search(state, depth - 1, budget, script):
                    return True
                script.pop()
            _restore(state, snap)
        else:
            _restore(state, snap)

    # 2. exact <hypothesis>
    for hname in reversed(_local_hyp_names(state)):
        _, snap = _clone_state(state)
        tac = S.Tactic(name="exact", terms=[S.SIdent(name=hname)])
        if _try_tactic(state, tac) and len(state.goals) < n_goals:
            script.append(f"exact {hname}")
            if _search(state, depth - 1, budget, script):
                return True
            script.pop()
        _restore(state, snap)

    # 3. structural tactics
    target = whnf(state.env, goal.target, delta=False)
    head, _ = unfold_app(target)
    hname = head.name if isinstance(head, Const) else None
    structural: list[str] = []
    if isinstance(target, Pi):
        structural.append("intro")
    if hname in ("And", "Iff", "True"):
        structural.append("split")
    if hname == "Or":
        structural.extend(["left", "right"])
    for name in structural:
        _, snap = _clone_state(state)
        tac = S.Tactic(name=name, idents=["h"] if name == "intro" else [])
        if _try_tactic(state, tac):
            script.append("intro h" if name == "intro" else name)
            if _search(state, depth - 1, budget, script):
                return True
            script.pop()
        _restore(state, snap)

    # 4. case-split on inductive hypotheses (∧, ∨, ∃, ...)
    for hname, hty in _inductive_hyps(state):
        _, snap = _clone_state(state)
        tac = S.Tactic(name="cases", terms=[S.SIdent(name=hname)])
        if _try_tactic(state, tac):
            script.append(f"cases {hname}")
            if _search(state, depth - 1, budget, script):
                return True
            script.pop()
        _restore(state, snap)

    # 5. apply relevant lemmas / hypotheses
    candidates = _local_hyp_names(state) + _relevant_lemmas(state, limit=12)
    for name in candidates:
        _, snap = _clone_state(state)
        tac = S.Tactic(name="apply", terms=[S.SIdent(name=name)])
        if _try_tactic(state, tac):
            script.append(f"apply {name}")
            if _search(state, depth - 1, budget, script):
                return True
            script.pop()
        _restore(state, snap)

    # 6. rewrite with equational hypotheses and lemmas
    for name in _local_hyp_names(state):
        for reverse in (False, True):
            _, snap = _clone_state(state)
            step = S.Tactic(name="rw_step", terms=[S.SIdent(name=name)],
                            reverse=reverse)
            tac = S.Tactic(name="rw",
                           cases=[S.TacticCase(ctor="", tactics=[step])])
            if _try_tactic(state, tac):
                script.append(f"rw [{'← ' if reverse else ''}{name}]")
                if _search(state, depth - 1, budget, script):
                    return True
                script.pop()
            _restore(state, snap)

    return False


def search_proof(session, statement_src: str, binders_src: str = "",
                 depth: int = MAX_DEPTH, nodes: int = MAX_NODES) -> SearchResult:
    """Search for a tactic proof of `statement_src` in `session`.

    Returns the tactic script as source lines. The caller is expected to
    paste it into a theorem and re-check it - the search's own success is
    not evidence, only the kernel's acceptance is.
    """
    from .elab.commands import CommandProcessor
    proc = CommandProcessor(session.env, session.ctx, oracles=session.oracles,
                            module="<search>")
    base = len(session.ctx.locals)
    try:
        binders: list[S.SBinder] = []
        if binders_src.strip():
            from .syntax.parser import Parser
            p = Parser(binders_src)
            binders = p.parse_binders((":",))
        lf = proc.elab.elab_command_binders(binders)
        stmt_ast = parse_expression(statement_src,
                                    extra_ops=dict(session.extra_ops))
        statement = proc.elab.elab_prop(stmt_ast)
        statement = proc.elab.finalize(statement)
        state = T.ProofState(proc.elab, statement, oracles={})
        script: list[str] = []
        budget = [nodes]
        ok = _search(state, depth, budget, script)
        if ok and not state.goals:
            try:
                state.finalize()
            except T.TacticError as e:
                return SearchResult(False, [], f"search produced an incomplete "
                                              f"proof term: {e}")
            return SearchResult(True, script,
                                f"found in {nodes - budget[0]} search steps")
        return SearchResult(False, [], (
            f"no proof found within depth {depth} / {nodes} steps"))
    except (ElabError, KernelError) as e:
        return SearchResult(False, [], f"could not elaborate the statement: {e}")
    finally:
        session.ctx.pop_locals_to(base)
        session.ctx.sweep_stray_locals()


# ---------------------------------------------------------------------------
# Error explanation (rule-based, deterministic)
# ---------------------------------------------------------------------------

_EXPLANATIONS: list[tuple[str, str]] = [
    ("unknown identifier",
     "The name is not in scope. Check spelling, whether the declaration "
     "comes later in the file (Epsilon checks top to bottom), or whether it "
     "needs `import`/`open` of its namespace."),
    ("type mismatch",
     "The term's type is not the expected one. If numeric, remember that "
     "literals default to ℕ - annotate with `(x : ℝ)` or use a decimal to "
     "land in ℚ/ℝ."),
    ("unsolved goals",
     "The tactic block ended with goals still open. Add tactics for the "
     "remaining goals, or use `sorry` to admit them (which marks the result "
     "as ⚠ Heuristic, never proven)."),
    ("rfl: sides are not definitionally equal",
     "`rfl` only closes goals that compute to the same normal form. Use "
     "`rw` with the relevant equations, `simp`, or `induction` first."),
    ("pattern",
     "`rw` could not find the left-hand side of the equation in the goal. "
     "Check the direction (`rw [← h]` rewrites right-to-left) and whether "
     "the goal needs `simp`/`unfold` first to expose the pattern."),
    ("apply: cannot unify",
     "The lemma's conclusion does not match the goal. Check its argument "
     "order, or supply the implicit arguments explicitly."),
    ("binder", "Add a type annotation to the binder: `(x : ℝ)`."),
    ("no proof",
     "Every theorem needs `:= by <tactics>` or `:= <term>`."),
    ("cannot infer all implicit arguments",
     "Elaboration could not determine some implicit arguments. Supply them "
     "explicitly, or add a type ascription `(e : T)`."),
    ("is recursive",
     "Recursive definitions are written with an `inductive` type plus its "
     "recursor (e.g. `Nat.rec`), not by self-reference."),
    ("no cas oracle", "The CAS oracle is unavailable in this session."),
]


def explain_error(message: str) -> Optional[str]:
    """Turn a diagnostic message into actionable advice, or None."""
    low = message.lower()
    for needle, advice in _EXPLANATIONS:
        if needle.lower() in low:
            return advice
    return None
