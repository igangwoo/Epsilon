"""Which library results could close this goal?

The proof explorer's engine. Given a goal — a proposition, plus the
hypotheses in scope — it looks through the environment for declarations
whose conclusion can be made to match, and reports them with the tactic that
would use them.

Matching is the same test `apply` performs: peel the result's Π binders into
metavariables and unify the conclusion with the goal. A suggestion therefore
means "this really does apply", not "this looks related". A suggestion is
still only a suggestion — nothing here proves anything, and running the
tactic is what puts the result through the kernel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .elab.context import ElabContext
from .elab.pp import pp
from .kernel.env import Declaration, Environment
from .kernel.term import (App, Const, Lam, MVar, Pi, Term, instantiate,
                          unfold_app)

#: how many side goals a suggestion may leave behind before it stops being
#: help. `apply` on a result with five unproved side conditions is not a
#: step forward.
MAX_SIDE_GOALS = 3

#: a goal shaped like `Eq _ lhs rhs` invites rewriting as well as applying
_REWRITABLE = ("Eq",)

#: precedence for a term in argument position, so `Real.sin x` comes out as
#: `(Real.sin x)` where it is passed to something else
_ARG_PREC = 101

#: what may be offered as a proof step. Definitions and recursors are not
#: proofs; constructors are — `Eq.refl` closes `a = a`.
_CANDIDATE_KINDS = frozenset({"theorem", "axiom", "constructor"})

#: never suggested. `sorry` and the trust axioms close any goal at all, which
#: is exactly why they must not be offered as proof steps: the product's
#: whole point is that a result carries an honest verification status, and
#: nothing helps a user reach one by proposing they assume it.
_NEVER_SUGGEST = frozenset({
    "Epsilon.sorry", "Epsilon.trustedCAS", "Epsilon.trustedNumeric",
})


@dataclass
class Suggestion:
    name: str
    display_name: Optional[str]
    title: str
    statement: str
    kind: str
    status: str
    tactic: str
    side_goals: int
    score: float
    why: str

    def as_dict(self) -> dict:
        return {
            "name": self.name, "display_name": self.display_name,
            "title": self.title, "statement": self.statement,
            "kind": self.kind, "status": self.status, "tactic": self.tactic,
            "side_goals": self.side_goals, "why": self.why,
            "score": round(self.score, 2),
        }


def _open_conclusion(ctx: ElabContext, ty: Term,
                     limit: int = 24) -> tuple[Term, list[MVar]]:
    """Peel Π binders into metavariables, as `apply` does.

    Returns the conclusion and the metavariables introduced, so the caller
    can tell an argument the unifier worked out from a side goal it did not.
    """
    holes: list[MVar] = []
    for _ in range(limit):
        tyw = ctx._safe_whnf(ty)
        if not isinstance(tyw, Pi):
            break
        mv = ctx.fresh_mvar(tyw.ty)
        holes.append(mv)
        ty = instantiate(tyw.body, mv)
    return ty, holes


def _head_name(t: Term) -> Optional[str]:
    head, _ = unfold_app(t)
    return head.name if isinstance(head, Const) else None


def _subterms(t: Term):
    yield t
    if isinstance(t, App):
        yield from _subterms(t.fn)
        yield from _subterms(t.arg)
    elif isinstance(t, (Lam, Pi)):
        yield from _subterms(t.ty)
        yield from _subterms(t.body)


def _is_proposition(env: Environment, ctx: ElabContext, conclusion: Term) -> bool:
    """Does this conclusion state a proposition?

    Asked of the conclusion's head rather than the conclusion itself: at this
    point the conclusion still holds unassigned metavariables (`Eq ?A ?a ?a`)
    and cannot be type-inferred, but `Eq`'s own declared type ends in Prop
    and `Nat`'s does not, which is the question being asked.
    """
    from .kernel.term import Sort
    name = _head_name(conclusion)
    if name is None:
        return False
    decl = env.get(name)
    if decl is None:
        return False
    ty = decl.type
    for _ in range(24):
        tyw = ctx._safe_whnf(ty)
        if not isinstance(tyw, Pi):
            break
        ty = tyw.body          # the codomain's sort does not depend on the
                               # argument, so an uninstantiated body is fine
    return isinstance(ctx._safe_whnf(ty), Sort) and ctx._safe_whnf(ty).level == 0


def _mentions(goal: Term, name: str) -> bool:
    return any(isinstance(s, Const) and s.name == name for s in _subterms(goal))


def suggest(session, goal: Term, *, limit: int = 12,
            include_axioms: bool = True) -> list[Suggestion]:
    """Results whose conclusion can be made to match `goal`, best first."""
    env = session.env
    out: list[Suggestion] = []
    goal_head = _head_name(goal)

    for name, decl in env.decls.items():
        kind = getattr(decl.kind, "value", str(decl.kind))
        # constructors count: `Eq.refl` is how a goal `a = a` closes, and
        # leaving it out means the explorer misses the most basic step there is
        if kind not in _CANDIDATE_KINDS or name in _NEVER_SUGGEST:
            continue
        if kind == "axiom" and not include_axioms:
            continue

        # a fresh context per candidate: metavariable assignments from one
        # trial must not leak into the next
        ctx = ElabContext(env)
        try:
            conclusion, holes = _open_conclusion(ctx, decl.type)
        except Exception:  # noqa: BLE001 - an untypeable declaration is no lemma
            continue

        # a conclusion that is just a variable unifies with everything and so
        # says nothing about this goal
        if isinstance(ctx.resolve_mvars(conclusion), MVar):
            continue
        # `Nat.succ` is a constructor but not a proof; only propositions
        # close a goal
        if kind == "constructor" and not _is_proposition(env, ctx, conclusion):
            continue

        found = _try_apply(env, ctx, conclusion, holes, goal, name) \
            or _try_rewrite(env, ctx, conclusion, goal, name)
        if found is None:
            continue
        tactic, side_goals, why = found
        if side_goals > MAX_SIDE_GOALS:
            continue

        try:
            status = env.verification_status(name)
        except Exception:  # noqa: BLE001 - status is informational here
            status = ""

        out.append(Suggestion(
            name=name,
            display_name=decl.display_name,
            title=decl.display_name or name,
            statement=pp(env, decl.type),
            kind=kind,
            status=status,
            tactic=tactic,
            side_goals=side_goals,
            score=_score(name, kind, side_goals, why, goal_head),
            why=why,
        ))

    out.sort(key=lambda s: (-s.score, s.side_goals, s.name))
    return out[:limit]


def _try_apply(env: Environment, ctx: ElabContext, conclusion: Term,
               holes: list[MVar], goal: Term, name: str
               ) -> Optional[tuple[str, int, str]]:
    """Can this result's conclusion be unified with the goal?

    The viability test is exactly the one `apply` performs, so a suggestion
    that survives it is one the tactic will accept. In particular an argument
    the unifier could not work out has to become a side *goal*, and it can
    only do that if its own type is fully determined — `Nat.le_trans` on
    `a ≤ c` leaves the middle term open, and `apply` rejects it.
    """
    try:
        if not ctx.unify(conclusion, goal):
            return None
    except Exception:  # noqa: BLE001 - a failed trial is just a non-match
        return None

    side_goals = 0
    for hole in holes:
        info = ctx.mvars[hole.id]
        if info.assignment is not None:
            continue
        ty = ctx.resolve_mvars(info.ty) if info.ty is not None else None
        if ty is None or ctx.has_unassigned_mvar(ty):
            return None          # apply would refuse this too
        side_goals += 1

    if side_goals:
        return f"apply {name}", side_goals, "conclusion matches, with side goals"

    # `rfl` is how anyone writes reflexivity; `exact Eq.refl ℝ (sin x)` is
    # the same step spelled out, and nobody spells it out
    if name == "Eq.refl":
        return "rfl", 0, "the two sides are the same"

    resolved = [ctx.resolve_mvars(h) for h in holes]
    if not resolved:
        return f"exact {name}", 0, "proves the goal exactly"
    # argument position: anything applied needs its own parentheses
    args = " ".join(pp(env, r, _ARG_PREC) for r in resolved)
    return f"exact {name} {args}", 0, "proves the goal exactly"


def _try_rewrite(env: Environment, ctx: ElabContext, conclusion: Term,
                 goal: Term, name: str) -> Optional[tuple[str, int, str]]:
    """An equation whose left side really occurs in the goal.

    Head-symbol agreement is not enough: `Nat.add_assoc` mentions `Nat.add`
    but its pattern `?a + ?b + ?c` does not occur in `a + b = b + a`, and
    suggesting a rewrite that fails is worse than suggesting nothing. The
    test is the one `rw` uses — a strict, syntactic match against a subterm.
    """
    if _head_name(conclusion) not in _REWRITABLE:
        return None
    _, args = unfold_app(conclusion)
    if len(args) != 3:
        return None
    lhs = args[1]
    lhs_head = _head_name(lhs)
    if not lhs_head or not _mentions(goal, lhs_head):
        return None
    for sub in _subterms(goal):
        if sub is goal:
            continue
        probe = ElabContext(env)
        probe.mvars = dict(ctx.mvars)
        try:
            if probe.unify(lhs, sub, strict=True):
                return f"rw [{name}]", 0, f"rewrites {pp(env, probe.resolve_mvars(lhs))}"
        except Exception:  # noqa: BLE001 - a failed probe is just a non-match
            continue
    return None


def _score(name: str, kind: str, side_goals: int, why: str,
           goal_head: Optional[str]) -> float:
    """Rank: an exact proof beats a rewrite beats something with side goals."""
    score = 10.0
    if why.startswith("proves"):
        score += 8.0
    elif why.startswith("rewrites"):
        score += 3.0
    score -= 2.5 * side_goals
    # an axiom closes the goal by assumption rather than by proof, so it is
    # offered but never preferred over a proved result
    if kind == "axiom":
        score -= 3.0
    # a result in the goal's own namespace is more likely the intended one
    if goal_head and "." in goal_head and name.startswith(goal_head.split(".")[0] + "."):
        score += 1.5
    return score


#: when a goal is typed with bare variables, these types are tried in order.
#: A goal is usually about the simplest structure it can be about, and a
#: reader who means something else can write the binders themselves.
_DEFAULT_TYPES = ("Nat", "Int", "Real", "Prop")


def _open_binders(term: Term) -> Term:
    while isinstance(term, Pi):
        term = instantiate(term.body, Const(term.name))
    return term


def suggest_for_text(session, goal_src: str, *, hypotheses=None,
                     limit: int = 12) -> list[Suggestion]:
    """Suggestions for a goal written as source text.

    The proof tree prints each step's target with the same pretty-printer
    that produces Epsilon source, so a target read off the tree parses back
    here, and its hypotheses come along as `(name, type-source)` pairs.

    Typed by hand, a goal may have bare variables and no hypotheses to
    explain them (`a + b = b + a`). Rather than refuse, each default type is
    tried in turn; writing the binders (`∀ (a b : Real), …`) picks one
    explicitly.
    """
    from .elab.elaborator import Elaborator
    from .syntax.parser import parse_expression
    from .cas.workbench import free_identifiers

    goal_src = (goal_src or "").strip()
    if not goal_src:
        raise ValueError("no goal given")

    def elaborate(text: str) -> Term:
        el = Elaborator(session.env, session.ctx)
        return el.finalize(el.elab_expr(
            parse_expression(text, extra_ops=dict(session.extra_ops)), None))

    binders = " ".join(f"({n} : {t})" for n, t in (hypotheses or []) if n and t)
    if binders:
        return suggest(session, _open_binders(
            elaborate(f"forall {binders}, {goal_src}")), limit=limit)

    try:
        return suggest(session, _open_binders(elaborate(goal_src)), limit=limit)
    except Exception as first:  # noqa: BLE001 - probably free variables
        expr = parse_expression(goal_src, extra_ops=dict(session.extra_ops))
        unknown = [n for n in free_identifiers(expr)
                   if not session.env.contains(n)
                   and session.env.resolve_display_name(n) is None]
        if not unknown:
            raise
        for ty in _DEFAULT_TYPES:
            guess = " ".join(f"({n} : {ty})" for n in unknown)
            try:
                return suggest(session, _open_binders(
                    elaborate(f"forall {guess}, {goal_src}")), limit=limit)
            except Exception:  # noqa: BLE001 - try the next type
                continue
        raise first
