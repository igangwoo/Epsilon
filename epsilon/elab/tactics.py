"""The tactic engine.

Tactics manipulate a goal state and *construct* candidate proof terms; they
prove nothing by themselves - the finished term is handed to the kernel
type checker, which is the only judge. Oracle tactics (`cas`, `numeric`)
close goals with tracked trust axioms so the resulting theorem is honestly
labeled Symbolically/Numerically Verified rather than Formally Proven.

Proof terms under construction may contain:
- MVar(id)  : one per open goal (assigned when the goal is closed)
- LBind     : a binder over a named local, converted to a de Bruijn Lam
              during finalization (delayed abstraction)
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from fractions import Fraction
from typing import Callable, Optional

from ..kernel.env import (Environment, KernelError, DeclKind,
                          TRUSTED_CAS_AXIOM, TRUSTED_NUMERIC_AXIOM, SORRY_AXIOM)
from ..kernel.inductive import close_lam, ph
from ..kernel.reduce import whnf, def_eq, normalize
from ..kernel.term import (Term, TermBase, Var, Const, Sort, App, Lam, Pi, Lit,
                           MVar, mk_app, unfold_app, instantiate,
                           abstract_const, replace_term, PROP)
from ..syntax import sast as S
from .context import ElabContext, ElabError, LocalDecl
from .pp import pp


class TacticError(Exception):
    def __init__(self, msg: str, span=None) -> None:
        super().__init__(msg)
        self.msg, self.span = msg, span


@dataclass(frozen=True)
class LBind(TermBase):
    """Delayed-abstraction lambda over the named local `uname`."""
    uname: str
    username: str
    ty: Term
    body: Term


@dataclass
class Goal:
    id: int
    mvar_id: int
    locals: list[LocalDecl]
    target: Term
    name: str = ""


@dataclass
class TraceStep:
    goal_id: int
    tactic: str
    before_hyps: list[tuple[str, str]]
    before_target: str
    after_goals: list[int]
    span: S.Span = (0, 0, 0, 0)
    rule: str = ""     # inference-rule label for the proof tree


class ProofState:
    def __init__(self, elab, statement: Term, oracles: Optional[dict] = None) -> None:
        self.elab = elab
        self.ctx: ElabContext = elab.ctx
        self.env: Environment = elab.env
        self.oracles: dict[str, Callable] = oracles or {}
        self._next_goal = 0
        root_mv = self.ctx.fresh_mvar(statement)
        self.root = MVar(root_mv.id)
        g = self._mk_goal(list(self.ctx.locals), statement, root_mv.id)
        self.goals: list[Goal] = [g]
        self.trace: list[TraceStep] = []
        self.used_oracles: set[str] = set()

    # ------------------------------------------------------------------
    def _mk_goal(self, locals_: list[LocalDecl], target: Term,
                 mvar_id: Optional[int] = None) -> Goal:
        if mvar_id is None:
            mv = self.ctx.fresh_mvar(target)
            mvar_id = mv.id
        self._next_goal += 1
        return Goal(self._next_goal, mvar_id, locals_, target)

    def current(self) -> Goal:
        if not self.goals:
            raise TacticError("no goals remaining")
        return self.goals[0]

    def close(self, goal: Goal, proof: Term) -> None:
        self.ctx.assign(goal.mvar_id, proof)
        self.goals.remove(goal)

    def replace_goal(self, goal: Goal, new_goals: list[Goal]) -> None:
        idx = self.goals.index(goal)
        self.goals[idx:idx + 1] = new_goals

    def _record(self, goal: Goal, tactic_str: str, after: list[Goal],
                span=None, rule: str = "") -> None:
        self.trace.append(TraceStep(
            goal_id=goal.id, tactic=tactic_str,
            before_hyps=[(ld.username, pp(self.env, ld.ty)) for ld in goal.locals],
            before_target=pp(self.env, goal.target),
            after_goals=[g.id for g in after],
            span=span or (0, 0, 0, 0), rule=rule))

    # ------------------------------------------------------------------
    # Term elaboration inside a goal's context
    # ------------------------------------------------------------------
    def elab_in(self, goal: Goal, e: S.Expr, expected: Optional[Term]) -> Term:
        saved = self.ctx.locals
        self.ctx.locals = list(goal.locals)
        try:
            return self.elab.elab_expr(e, expected)
        finally:
            self.ctx.locals = saved

    def push_goal_local(self, goal: Goal, username: str, ty: Term) -> LocalDecl:
        saved = self.ctx.locals
        self.ctx.locals = list(goal.locals)
        try:
            return self.ctx.push_local(username, ty)
        finally:
            self.ctx.locals = saved

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------
    def finalize(self) -> Term:
        if self.goals:
            g = self.goals[0]
            raise TacticError(
                f"unsolved goals ({len(self.goals)} remaining); "
                f"first: ⊢ {pp(self.env, g.target)}")
        t = self._resolve(self.root)
        return self._strip(t)

    def _resolve(self, t: Term, depth: int = 0) -> Term:
        if depth > 10_000:
            raise TacticError("proof term too deep")
        if isinstance(t, MVar):
            info = self.ctx.mvars.get(t.id)
            if info is None or info.assignment is None:
                raise TacticError("internal: unassigned metavariable in proof")
            return self._resolve(info.assignment, depth + 1)
        if isinstance(t, App):
            return App(self._resolve(t.fn, depth + 1), self._resolve(t.arg, depth + 1))
        if isinstance(t, Lam):
            return Lam(t.name, self._resolve(t.ty, depth + 1),
                       self._resolve(t.body, depth + 1))
        if isinstance(t, Pi):
            return Pi(t.name, self._resolve(t.ty, depth + 1),
                      self._resolve(t.body, depth + 1), t.implicit)
        if isinstance(t, LBind):
            return LBind(t.uname, t.username, self._resolve(t.ty, depth + 1),
                         self._resolve(t.body, depth + 1))
        return t

    def _strip(self, t: Term) -> Term:
        if isinstance(t, LBind):
            body = self._strip(t.body)
            return Lam(t.username, self._strip(t.ty), abstract_const(body, t.uname))
        if isinstance(t, App):
            return App(self._strip(t.fn), self._strip(t.arg))
        if isinstance(t, Lam):
            return Lam(t.name, self._strip(t.ty), self._strip(t.body))
        if isinstance(t, Pi):
            return Pi(t.name, self._strip(t.ty), self._strip(t.body), t.implicit)
        return t


# ===========================================================================
# Tactic implementations
# ===========================================================================

def run_tactics(state: ProofState, tactics: list[S.Tactic]) -> None:
    for tac in tactics:
        run_tactic(state, tac)


def run_tactic(state: ProofState, tac: S.Tactic) -> None:
    name = tac.name
    handler = _HANDLERS.get(name)
    if handler is None:
        raise TacticError(f"unknown tactic '{name}'", tac.span)
    try:
        handler(state, tac)
    except (ElabError, KernelError) as e:
        raise TacticError(f"{name}: {e}", tac.span)


def _tac_intro(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    names = tac.idents or ["_"]
    for nm in names:
        goal = state.current()
        tgt = whnf(state.env, goal.target)
        if not isinstance(tgt, Pi):
            raise TacticError(f"intro: goal is not a ∀/→ "
                              f"(⊢ {pp(state.env, goal.target)})", tac.span)
        ld = state.push_goal_local(goal, nm if nm != "_" else tgt.name or "h", tgt.ty)
        new_target = instantiate(tgt.body, Const(ld.uname))
        g2 = state._mk_goal(goal.locals + [ld], new_target)
        state._record(goal, f"intro {ld.username}", [g2], tac.span, rule="→I/∀I")
        state.close(goal, LBind(ld.uname, ld.username, tgt.ty, MVar(
            state.ctx.mvars[g2.mvar_id].id)))
        state.goals.insert(0, g2)


def _tac_intros(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    while isinstance(whnf(state.env, state.current().target), Pi):
        _tac_intro(state, S.Tactic(name="intro", idents=["_"], span=tac.span))
        if state.current().id == goal.id:
            break


def _tac_exact(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    t = state.elab_in(goal, tac.terms[0], goal.target)
    t = state.elab.finalize(t, tac.span)
    state._record(goal, "exact", [], tac.span, rule="exact")
    state.close(goal, t)


def _tac_apply(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    t = state.elab_in(goal, tac.terms[0], None)
    ty = state.ctx.infer(t)
    added: list[MVar] = []
    guard = 0
    while True:
        guard += 1
        if guard > 64:
            raise TacticError("apply: could not match goal", tac.span)
        if state.ctx.unify(ty, goal.target):
            break
        tyw = state.ctx._safe_whnf(ty)
        if isinstance(tyw, Pi):
            mv = state.ctx.fresh_mvar(tyw.ty)
            added.append(mv)
            t = App(t, mv)
            ty = instantiate(tyw.body, mv)
            continue
        raise TacticError(
            f"apply: cannot unify conclusion with goal\n  conclusion: "
            f"{pp(state.env, state.ctx.resolve_mvars(ty))}\n  goal:       "
            f"{pp(state.env, goal.target)}", tac.span)

    new_goals: list[Goal] = []
    for mv in added:
        info = state.ctx.mvars[mv.id]
        if info.assignment is not None:
            continue
        mty = state.ctx.resolve_mvars(info.ty) if info.ty is not None else None
        if mty is None or state.ctx.has_unassigned_mvar(mty):
            raise TacticError("apply: cannot infer an argument "
                              "(try supplying it explicitly)", tac.span)
        g = state._mk_goal(list(goal.locals), mty, mv.id)
        new_goals.append(g)
    state._record(goal, "apply", new_goals, tac.span, rule="apply")
    state.ctx.assign(goal.mvar_id, t)
    state.replace_goal(goal, new_goals)


def _tac_assumption(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    for ld in reversed(goal.locals):
        try:
            if def_eq(state.env, ld.ty, goal.target):
                state._record(goal, f"assumption ({ld.username})", [], tac.span,
                              rule="hyp")
                state.close(goal, Const(ld.uname))
                return
        except KernelError:
            continue
    raise TacticError("assumption: no hypothesis matches the goal", tac.span)


def _eq_parts(state: ProofState, t: Term):
    t = whnf(state.env, t)
    h, args = unfold_app(t)
    if isinstance(h, Const) and h.name == "Eq" and len(args) == 3:
        return args[0], args[1], args[2]
    return None


def _tac_rfl(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    parts = _eq_parts(state, goal.target)
    if parts is not None:
        A, a, b = parts
        if def_eq(state.env, a, b):
            state._record(goal, "rfl", [], tac.span, rule="=I")
            state.close(goal, mk_app(Const("Eq.refl"), A, a))
            return
        raise TacticError(
            f"rfl: sides are not definitionally equal\n  {pp(state.env, a)}\n"
            f"  {pp(state.env, b)}", tac.span)
    tgt = whnf(state.env, goal.target)
    h, args = unfold_app(tgt)
    if isinstance(h, Const) and h.name == "Iff" and len(args) == 2 \
            and def_eq(state.env, args[0], args[1]):
        p = args[0]
        idfn = Lam("h", p, Var(0))
        state._record(goal, "rfl", [], tac.span, rule="↔I")
        state.close(goal, mk_app(Const("Iff.intro"), args[0], args[1], idfn, idfn))
        return
    raise TacticError("rfl: goal is not an equality", tac.span)


def _symm_term(A: Term, a: Term, b: Term, p: Term, ctx: ElabContext) -> Term:
    """From p : a = b build a term proving b = a."""
    x = ctx.fresh_name("x")
    e = ctx.fresh_name("e")
    motive = close_lam([(x, A), (e, mk_app(Const("Eq"), A, a, ph(x)))],
                       mk_app(Const("Eq"), A, ph(x), a))
    return mk_app(Const("Eq.ind"), A, a, motive,
                  mk_app(Const("Eq.refl"), A, a), b, p)


def _trans_term(A: Term, a: Term, b: Term, c: Term, p1: Term, p2: Term,
                ctx: ElabContext) -> Term:
    """From p1 : a = b, p2 : b = c build a = c."""
    x = ctx.fresh_name("x")
    e = ctx.fresh_name("e")
    motive = close_lam([(x, A), (e, mk_app(Const("Eq"), A, b, ph(x)))],
                       mk_app(Const("Eq"), A, a, ph(x)))
    return mk_app(Const("Eq.ind"), A, b, motive, p1, c, p2)


def _tac_symm(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    parts = _eq_parts(state, goal.target)
    if parts is None:
        raise TacticError("symm: goal is not an equality", tac.span)
    A, a, b = parts
    g2 = state._mk_goal(list(goal.locals), mk_app(Const("Eq"), A, b, a))
    state._record(goal, "symm", [g2], tac.span, rule="=sym")
    state.close(goal, _symm_term(A, b, a, MVar(g2.mvar_id), state.ctx))
    state.goals.insert(0, g2)


def _tac_constructor(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    tgt = whnf(state.env, goal.target)
    h, args = unfold_app(tgt)
    if not isinstance(h, Const) or h.name not in state.env.inductives:
        raise TacticError("constructor: goal is not an inductive proposition",
                          tac.span)
    info = state.env.inductives[h.name]
    last_err = None
    for cname in info.constructors:
        snapshot = {mid: i.assignment for mid, i in state.ctx.mvars.items()}
        ngoals_before = list(state.goals)
        try:
            _apply_const(state, goal, cname, tac)
            return
        except TacticError as e:
            last_err = e
            for mid, asg in snapshot.items():
                state.ctx.mvars[mid].assignment = asg
            state.goals = ngoals_before
    raise last_err or TacticError("constructor: no constructor applies", tac.span)


def _apply_const(state: ProofState, goal: Goal, cname: str, tac: S.Tactic) -> None:
    fake = S.Tactic(name="apply", terms=[S.SIdent(name=cname, span=tac.span)],
                    span=tac.span)
    _tac_apply(state, fake)


def _tac_split(state: ProofState, tac: S.Tactic) -> None:
    _tac_constructor(state, tac)


def _tac_left(state: ProofState, tac: S.Tactic) -> None:
    _apply_const(state, state.current(), "Or.inl", tac)


def _tac_right(state: ProofState, tac: S.Tactic) -> None:
    _apply_const(state, state.current(), "Or.inr", tac)


def _tac_exists(state: ProofState, tac: S.Tactic) -> None:
    for w in tac.terms:
        goal = state.current()
        tgt = whnf(state.env, goal.target)
        h, args = unfold_app(tgt)
        if not (isinstance(h, Const) and h.name == "Exists" and len(args) == 2):
            raise TacticError("exists: goal is not an ∃", tac.span)
        A, pred = args
        witness = state.elab_in(goal, w, A)
        witness = state.elab.finalize(witness, tac.span)
        new_target = whnf(state.env, App(pred, witness))
        g2 = state._mk_goal(list(goal.locals), new_target)
        state._record(goal, "exists", [g2], tac.span, rule="∃I")
        state.close(goal, mk_app(Const("Exists.intro"), A, pred, witness,
                                 MVar(g2.mvar_id)))
        state.goals.insert(0, g2)
    # close the residual goal automatically when it is trivial (rfl/decide)
    if state.goals:
        try:
            _tac_trivial(state, S.Tactic(name="trivial", span=tac.span))
        except TacticError:
            pass


# ---------------------------------------------------------------------------
# cases / induction
# ---------------------------------------------------------------------------

def _tac_cases(state: ProofState, tac: S.Tactic) -> None:
    _elim(state, tac, use_ih=False)


def _tac_induction(state: ProofState, tac: S.Tactic) -> None:
    _elim(state, tac, use_ih=True)


def _elim(state: ProofState, tac: S.Tactic, use_ih: bool) -> None:
    goal = state.current()
    h = state.elab_in(goal, tac.terms[0], None)
    h = state.elab.finalize(h, tac.span)
    h_ty = whnf(state.env, state.ctx.infer(h))
    head, iargs = unfold_app(h_ty)
    if not isinstance(head, Const) or head.name not in state.env.inductives:
        raise TacticError(
            f"{tac.name}: hypothesis is not of an inductive type "
            f"({pp(state.env, h_ty)})", tac.span)
    if head.name == "Eq":
        raise TacticError("use `rw` to eliminate equalities", tac.span)
    info = state.env.inductives[head.name]
    params = iargs[:info.num_params]

    # motive: dependent when eliminating a plain variable that occurs in goal
    dependent = (isinstance(h, Const) and use_ih) or (
        isinstance(h, Const) and _occurs_const(goal.target, h.name))
    if dependent and isinstance(h, Const):
        motive = Lam(_display(h.name), h_ty, abstract_const(goal.target, h.name))
    else:
        motive = Lam("_", h_ty, goal.target)

    rec_name = f"{head.name}.ind"
    if rec_name not in state.env.decls:
        raise TacticError(f"{tac.name}: no eliminator for {head.name}", tac.span)

    case_names: dict[str, list[str]] = {}
    case_tactics: dict[str, list[S.Tactic]] = {}
    if tac.cases:
        for c in tac.cases:
            short = c.ctor.split(".")[-1]
            case_names[short] = c.names
            case_tactics[short] = c.tactics
    flat_names = list(tac.idents)

    minors: list[Term] = []
    new_goals: list[Goal] = []
    goal_tactics: list[list[S.Tactic]] = []
    for cname in info.constructors:
        short = cname.split(".")[-1]
        ctor_ty = state.env.expect(cname).type
        for p in params:
            ctor_ty = whnf(state.env, ctor_ty, delta=False)
            assert isinstance(ctor_ty, Pi)
            ctor_ty = instantiate(ctor_ty.body, p)
        # walk fields
        fields: list[LocalDecl] = []
        ihs: list[LocalDecl] = []
        locals2 = list(goal.locals)
        auto_names = list(case_names.get(short, []))
        ctor_ty_cur = ctor_ty
        binder_terms: list[tuple[LocalDecl, Optional[LocalDecl]]] = []
        while True:
            ctor_ty_cur = whnf(state.env, ctor_ty_cur, delta=False)
            if not isinstance(ctor_ty_cur, Pi):
                break
            fname = auto_names.pop(0) if auto_names else (
                flat_names.pop(0) if flat_names else (ctor_ty_cur.name or "a"))
            saved = state.ctx.locals
            state.ctx.locals = locals2
            fld = state.ctx.push_local(fname, ctor_ty_cur.ty)
            state.ctx.locals = saved
            locals2 = locals2 + [fld]
            fields.append(fld)
            ih_ld: Optional[LocalDecl] = None
            fh, fargs = unfold_app(whnf(state.env, ctor_ty_cur.ty, delta=False))
            if use_ih and isinstance(fh, Const) and fh.name == head.name:
                ih_name = auto_names.pop(0) if auto_names else (
                    flat_names.pop(0) if flat_names else "ih")
                ih_ty = whnf(state.env, App(motive, Const(fld.uname)))
                saved = state.ctx.locals
                state.ctx.locals = locals2
                ih_ld = state.ctx.push_local(ih_name, ih_ty)
                state.ctx.locals = saved
                locals2 = locals2 + [ih_ld]
                ihs.append(ih_ld)
            binder_terms.append((fld, ih_ld))
            ctor_ty_cur = instantiate(ctor_ty_cur.body, Const(fld.uname))

        built = mk_app(Const(cname), *params, *[Const(f.uname) for f in fields])
        new_target = whnf(state.env, App(motive, built), delta=False)
        g2 = state._mk_goal(locals2, new_target, None)
        g2.name = short
        new_goals.append(g2)
        goal_tactics.append(case_tactics.get(short, []))

        minor: Term = MVar(g2.mvar_id)
        for fld, ih_ld in reversed(binder_terms):
            if ih_ld is not None:
                minor = LBind(ih_ld.uname, ih_ld.username, ih_ld.ty, minor)
            minor = LBind(fld.uname, fld.username, fld.ty, minor)
        minors.append(minor)

    proof = mk_app(Const(rec_name), *params, motive, *minors, h)
    rule = "induction" if use_ih else "cases"
    state._record(goal, f"{tac.name} {pp(state.env, h)}", new_goals, tac.span,
                  rule=rule)
    state.ctx.assign(goal.mvar_id, proof)
    state.replace_goal(goal, new_goals)

    # run per-case tactic blocks (with | c => ... syntax)
    if tac.cases:
        for g2, tacs in zip(new_goals, goal_tactics):
            if not tacs:
                continue
            if g2 in state.goals:
                state.goals.remove(g2)
                state.goals.insert(0, g2)
                n0 = len(state.goals)
                run_tactics(state, tacs)
                if len(state.goals) >= n0:
                    open_g = state.goals[0]
                    raise TacticError(
                        f"case '{g2.name}': unsolved goal remains "
                        f"(⊢ {pp(state.env, open_g.target)})", tac.span)


def _occurs_const(t: Term, name: str) -> bool:
    from ..kernel.term import constants_of
    return name in set(constants_of(t))


def _display(uname: str) -> str:
    from .context import LOCAL_MARK
    return uname.split(LOCAL_MARK)[0]


# ---------------------------------------------------------------------------
# rewriting
# ---------------------------------------------------------------------------

def _subterms(t: Term):
    yield t
    if isinstance(t, App):
        yield from _subterms(t.fn)
        yield from _subterms(t.arg)
    # do not descend under binders: occurrences there may capture variables


def _tac_rw(state: ProofState, tac: S.Tactic) -> None:
    if tac.idents:
        raise TacticError("rw at hypothesis is not supported yet", tac.span)
    for case in tac.cases:
        step = case.tactics[0]
        _rw_once(state, step.terms[0], step.reverse, tac.span)
    # After rewriting, close by rfl if the goal became trivial
    goal = state.goals[0] if state.goals else None
    if goal is not None:
        parts = _eq_parts(state, goal.target)
        if parts is not None:
            A, a, b = parts
            try:
                if def_eq(state.env, a, b):
                    state._record(goal, "rfl", [], tac.span, rule="=I")
                    state.close(goal, mk_app(Const("Eq.refl"), A, a))
            except KernelError:
                pass


def _rw_once(state: ProofState, h_expr: S.Expr, reverse: bool, span) -> None:
    goal = state.current()
    t = state.elab_in(goal, h_expr, None)
    ty = state.ctx.infer(t)
    # strip Pis, inserting mvars for the lemma's arguments
    guard = 0
    while True:
        guard += 1
        if guard > 64:
            raise TacticError("rw: lemma has too many arguments", span)
        tyw = state.ctx._safe_whnf(ty)
        if isinstance(tyw, Pi):
            mv = state.ctx.fresh_mvar(tyw.ty)
            t = App(t, mv)
            ty = instantiate(tyw.body, mv)
            continue
        break
    tyr = state.ctx.resolve_mvars(ty)
    h, args = unfold_app(state.ctx._safe_whnf(tyr))
    if not (isinstance(h, Const) and h.name == "Eq" and len(args) == 3):
        raise TacticError(
            f"rw: expected an equality, got {pp(state.env, tyr)}", span)
    A, lhs, rhs = args
    pattern = rhs if reverse else lhs
    replacement = lhs if reverse else rhs

    found = None
    # pass 1: strict syntactic matching; pass 2: allow reduction fallbacks
    for strict in (True, False):
        for sub in _subterms(goal.target):
            snapshot = {mid: i.assignment for mid, i in state.ctx.mvars.items()}
            if state.ctx.unify(pattern, sub, strict=strict):
                found = sub  # the syntactic occurrence (def-eq to the pattern)
                break
            for mid, asg in snapshot.items():
                state.ctx.mvars[mid].assignment = asg
        if found is not None:
            break
    if found is None:
        raise TacticError(
            f"rw: pattern `{pp(state.env, state.ctx.resolve_mvars(pattern))}` "
            f"not found in goal `{pp(state.env, goal.target)}`", span)

    t = state.ctx.resolve_mvars(t)
    A = state.ctx.resolve_mvars(A)
    b_inst = state.ctx.resolve_mvars(replacement)
    if state.ctx.has_unassigned_mvar(t) or state.ctx.has_unassigned_mvar(b_inst):
        raise TacticError("rw: could not infer all lemma arguments", span)

    # p : found = b_inst (in rewrite direction)
    p = t if not reverse else _symm_term(A, b_inst, found, t, state.ctx)

    new_target = replace_term(goal.target, found, b_inst)
    g2 = state._mk_goal(list(goal.locals), new_target)

    # Eq.ind A b (λ x _, C[x]) (m : C[b]) found (h' : b = found) : C[found]
    xn = state.ctx.fresh_name("x")
    en = state.ctx.fresh_name("e")
    motive = close_lam([(xn, A), (en, mk_app(Const("Eq"), A, b_inst, ph(xn)))],
                       replace_term(goal.target, found, ph(xn)))
    h_rev = _symm_term(A, found, b_inst, p, state.ctx)
    proof = mk_app(Const("Eq.ind"), A, b_inst, motive, MVar(g2.mvar_id),
                   found, h_rev)
    state._record(goal, ("rw ←" if reverse else "rw"), [g2], span, rule="=E")
    state.close(goal, proof)
    state.goals.insert(0, g2)


# ---------------------------------------------------------------------------
# simp / computation
# ---------------------------------------------------------------------------

def _simp_lemmas(state: ProofState) -> list[str]:
    return [n for n, d in state.env.decls.items()
            if "simp" in d.attrs and d.kind in (DeclKind.THEOREM, DeclKind.AXIOM)]


def _tac_simp(state: ProofState, tac: S.Tactic) -> None:
    if tac.idents:
        raise TacticError("simp at hypothesis is not supported yet", tac.span)
    goal = state.current()

    # 1. definitional normalization (no user-def unfolding)
    t2 = normalize(state.env, goal.target, delta=False)
    if t2 != goal.target:
        g2 = state._mk_goal(list(goal.locals), t2, goal.mvar_id)
        state._record(goal, "simp (normalize)", [g2], tac.span, rule="defeq")
        state.replace_goal(goal, [g2])
        goal = g2

    # 2. rewrite with simp lemmas + user-supplied lemmas, to fixpoint
    lemma_exprs: list[S.Expr] = list(tac.terms)
    lemma_exprs += [S.SIdent(name=n) for n in _simp_lemmas(state)]
    changed, rounds = True, 0
    while changed and rounds < 32 and state.goals:
        changed = False
        rounds += 1
        for le in lemma_exprs:
            try:
                _rw_once(state, le, False, tac.span)
                changed = True
            except TacticError:
                continue

    if not state.goals:
        return
    goal = state.current()
    # 3. close if trivial
    tgt = whnf(state.env, goal.target)
    if isinstance(tgt, Const) and tgt.name == "True":
        state._record(goal, "simp (True)", [], tac.span, rule="⊤I")
        state.close(goal, Const("True.intro"))
        return
    parts = _eq_parts(state, goal.target)
    if parts is not None:
        A, a, b = parts
        try:
            if def_eq(state.env, a, b):
                state._record(goal, "simp (rfl)", [], tac.span, rule="=I")
                state.close(goal, mk_app(Const("Eq.refl"), A, a))
                return
        except KernelError:
            pass
    # otherwise simp leaves the simplified goal open (progress, not failure)


def _tac_unfold(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    target = goal.target
    for name in tac.idents:
        full = state.ctx.resolve_global(name)
        if full is None:
            raise TacticError(f"unfold: unknown definition '{name}'", tac.span)
        decl = state.env.expect(full)
        if decl.value is None:
            raise TacticError(f"unfold: '{name}' has no definition", tac.span)
        target = replace_term(target, Const(full), decl.value)
    target = normalize(state.env, target, delta=False)
    g2 = state._mk_goal(list(goal.locals), target, goal.mvar_id)
    state._record(goal, f"unfold {' '.join(tac.idents)}", [g2], tac.span,
                  rule="defeq")
    state.replace_goal(goal, [g2])


def _tac_decide(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    tgt = whnf(state.env, goal.target, delta=False)
    parts = _eq_parts(state, goal.target)
    if parts is not None:
        A, a, b = parts
        if def_eq(state.env, a, b):
            state._record(goal, "decide", [], tac.span, rule="compute")
            state.close(goal, mk_app(Const("Eq.refl"), A, a))
            return
        raise TacticError("decide: equality is false or not computable", tac.span)

    h, args = unfold_app(tgt)
    if isinstance(h, Const) and len(args) == 2:
        # comparisons on literals via the ble/blt bridge axioms
        for prop_op, bridge in (("le", "le_of_ble"), ("lt", "lt_of_blt")):
            for T in ("Nat", "Int", "Rat", "Real"):
                if h.name == f"{T}.{prop_op}":
                    ax = f"{T}.{bridge}"
                    if state.env.contains(ax):
                        bexpr = mk_app(Const(f"{T}.{'ble' if prop_op=='le' else 'blt'}"),
                                       args[0], args[1])
                        if def_eq(state.env, bexpr, Const("Bool.true")):
                            prf = mk_app(Const(ax), args[0], args[1],
                                         mk_app(Const("Eq.refl"), Const("Bool"),
                                                Const("Bool.true")))
                            state._record(goal, "decide", [], tac.span, rule="compute")
                            state.close(goal, prf)
                            return
                    # Nat.le is genuinely defined: prove ∃ c, a + c = b directly
                    if T == "Nat" and prop_op == "le":
                        av, bv = whnf(state.env, args[0]), whnf(state.env, args[1])
                        if isinstance(av, Lit) and isinstance(bv, Lit) \
                                and av.value <= bv.value:
                            diff = Lit(bv.value - av.value, "Nat")
                            pred = state.ctx._safe_whnf(
                                mk_app(Const("Nat.le"), av, bv))
                            _, pargs = unfold_app(pred)
                            witness_pred = pargs[1]
                            prf = mk_app(Const("Exists.intro"), Const("Nat"),
                                         witness_pred, diff,
                                         mk_app(Const("Eq.refl"), Const("Nat"), bv))
                            state._record(goal, "decide", [], tac.span,
                                          rule="compute")
                            state.close(goal, prf)
                            return
    raise TacticError("decide: cannot decide this goal by computation", tac.span)


# ---------------------------------------------------------------------------
# structure: have / show / calc
# ---------------------------------------------------------------------------

def _tac_have(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    hname = tac.idents[0]
    P = state.elab_in(goal, tac.terms[0], None)
    P = state.elab.finalize(P, tac.span)
    proof_term = _elab_proof_like(state, goal, tac.sub, P, tac.span)
    ld = state.push_goal_local(goal, hname, P)
    g2 = state._mk_goal(goal.locals + [ld], goal.target)
    state._record(goal, f"have {hname}", [g2], tac.span, rule="cut")
    state.close(goal, App(LBind(ld.uname, ld.username, P, MVar(g2.mvar_id)),
                          proof_term))
    state.goals.insert(0, g2)


def _elab_proof_like(state: ProofState, goal: Goal, sub, expected: Term,
                     span) -> Term:
    if isinstance(sub, S.TermProof):
        t = state.elab_in(goal, sub.term, expected)
        return state.elab.finalize(t, span)
    if isinstance(sub, S.TacticProof):
        g = state._mk_goal(list(goal.locals), expected)
        saved_goals = state.goals
        state.goals = [g]
        try:
            run_tactics(state, sub.tactics)
            if state.goals:
                raise TacticError("unsolved sub-proof goals", span)
        finally:
            remaining = state.goals
            state.goals = saved_goals
            if remaining:
                state.goals = remaining + saved_goals
        return MVar(g.mvar_id)
    raise TacticError("have: missing proof", span)


def _tac_show(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    P = state.elab_in(goal, tac.terms[0], None)
    P = state.elab.finalize(P, tac.span)
    if not def_eq(state.env, P, goal.target):
        raise TacticError(
            f"show: `{pp(state.env, P)}` is not the current goal "
            f"`{pp(state.env, goal.target)}`", tac.span)
    g2 = state._mk_goal(list(goal.locals), P, goal.mvar_id)
    state._record(goal, "show", [g2], tac.span, rule="defeq")
    state.replace_goal(goal, [g2])


def _tac_calc(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    if not tac.calc_steps:
        raise TacticError("calc: no steps", tac.span)
    first = state.elab_in(goal, tac.terms[0], None)
    first = state.elab.finalize(first, tac.span)
    A = state.ctx.infer(first)
    cur = first
    total: Optional[Term] = None
    total_lhs = first
    for op, rhs_e, prf in tac.calc_steps:
        if op != "=":
            raise TacticError("calc: only `=` chains are supported for now",
                              tac.span)
        rhs = state.elab_in(goal, rhs_e, A)
        rhs = state.elab.finalize(rhs, tac.span)
        step_ty = mk_app(Const("Eq"), A, cur, rhs)
        p = _elab_proof_like(state, goal, prf, step_ty, tac.span)
        if total is None:
            total = p
        else:
            total = _trans_term(A, total_lhs, cur, rhs, total, p, state.ctx)
        cur = rhs
    final_ty = mk_app(Const("Eq"), A, total_lhs, cur)
    if not def_eq(state.env, final_ty, goal.target):
        raise TacticError(
            f"calc: proves `{pp(state.env, final_ty)}` but the goal is "
            f"`{pp(state.env, goal.target)}`", tac.span)
    state._record(goal, "calc", [], tac.span, rule="=trans")
    state.close(goal, total)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# logic closers
# ---------------------------------------------------------------------------

def _tac_trivial(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    tgt = whnf(state.env, goal.target)
    if isinstance(tgt, Const) and tgt.name == "True":
        state._record(goal, "trivial", [], tac.span, rule="⊤I")
        state.close(goal, Const("True.intro"))
        return
    for t in (_tac_rfl, _tac_assumption, _tac_decide):
        try:
            t(state, tac)
            return
        except TacticError:
            continue
    raise TacticError("trivial: could not close the goal", tac.span)


def _tac_exfalso(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    g2 = state._mk_goal(list(goal.locals), Const("False"))
    motive = Lam("_", Const("False"), goal.target)
    state._record(goal, "exfalso", [g2], tac.span, rule="⊥E")
    state.close(goal, mk_app(Const("False.ind"), motive, MVar(g2.mvar_id)))
    state.goals.insert(0, g2)


def _tac_contradiction(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    motive = Lam("_", Const("False"), goal.target)
    # direct False hypothesis
    for ld in goal.locals:
        try:
            if def_eq(state.env, ld.ty, Const("False")):
                state._record(goal, "contradiction", [], tac.span, rule="⊥E")
                state.close(goal, mk_app(Const("False.ind"), motive,
                                         Const(ld.uname)))
                return
        except KernelError:
            continue
    # h : ¬p together with h2 : p
    for ld in goal.locals:
        ty = whnf(state.env, ld.ty)
        if isinstance(ty, Pi):
            body = whnf(state.env, ty.body) if not isinstance(ty.body, Const) \
                else ty.body
            if isinstance(body, Const) and body.name == "False":
                p = ty.ty
                for ld2 in goal.locals:
                    try:
                        if def_eq(state.env, ld2.ty, p):
                            fp = App(Const(ld.uname), Const(ld2.uname))
                            state._record(goal, "contradiction", [], tac.span,
                                          rule="⊥E")
                            state.close(goal, mk_app(Const("False.ind"),
                                                     motive, fp))
                            return
                    except KernelError:
                        continue
    raise TacticError("contradiction: no contradictory hypotheses found",
                      tac.span)


# ---------------------------------------------------------------------------
# oracles (tracked trust) and sorry
# ---------------------------------------------------------------------------

def _oracle_close(state: ProofState, tac: S.Tactic, oracle_name: str,
                  axiom: str) -> None:
    goal = state.current()
    oracle = state.oracles.get(oracle_name)
    if oracle is None:
        raise TacticError(
            f"{tac.name}: no {oracle_name} oracle available in this session",
            tac.span)
    ok, why = oracle(state.env, goal.target)
    if not ok:
        raise TacticError(f"{tac.name}: {why}", tac.span)
    state.used_oracles.add(oracle_name)
    state._record(goal, tac.name, [], tac.span, rule=f"oracle:{oracle_name}")
    state.close(goal, App(Const(axiom), goal.target))


def _tac_cas(state: ProofState, tac: S.Tactic) -> None:
    _oracle_close(state, tac, "cas", TRUSTED_CAS_AXIOM)


def _tac_numeric(state: ProofState, tac: S.Tactic) -> None:
    _oracle_close(state, tac, "numeric", TRUSTED_NUMERIC_AXIOM)


def _tac_ring(state: ProofState, tac: S.Tactic) -> None:
    try:
        _tac_rfl(state, tac)
        return
    except TacticError:
        pass
    _tac_cas(state, tac)


def _tac_sorry(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    state._record(goal, "sorry", [], tac.span, rule="sorry")
    state.close(goal, App(Const(SORRY_AXIOM), goal.target))


def _tac_clear(state: ProofState, tac: S.Tactic) -> None:
    goal = state.current()
    keep = [ld for ld in goal.locals if ld.username not in tac.idents]
    g2 = state._mk_goal(keep, goal.target, goal.mvar_id)
    state.replace_goal(goal, [g2])


_HANDLERS = {
    "intro": _tac_intro,
    "intros": _tac_intros,
    "exact": _tac_exact,
    "apply": _tac_apply,
    "assumption": _tac_assumption,
    "rfl": _tac_rfl,
    "symm": _tac_symm,
    "constructor": _tac_constructor,
    "split": _tac_split,
    "left": _tac_left,
    "right": _tac_right,
    "exists": _tac_exists,
    "cases": _tac_cases,
    "induction": _tac_induction,
    "rw": _tac_rw,
    "rewrite": _tac_rw,
    "simp": _tac_simp,
    "unfold": _tac_unfold,
    "decide": _tac_decide,
    "norm_num": _tac_decide,
    "have": _tac_have,
    "show": _tac_show,
    "calc": _tac_calc,
    "trivial": _tac_trivial,
    "exfalso": _tac_exfalso,
    "contradiction": _tac_contradiction,
    "cas": _tac_cas,
    "numeric": _tac_numeric,
    "ring": _tac_ring,
    "linarith": _tac_ring,
    "sorry": _tac_sorry,
    "clear": _tac_clear,
}
