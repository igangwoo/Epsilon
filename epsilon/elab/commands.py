"""Command processing: turn parsed commands into checked declarations.

The single entry point `CommandProcessor.process` is shared by the file
checker, the REPL, the server, and the CLI - one pipeline, one data model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..kernel.env import Environment, Declaration, DeclKind, KernelError
from ..kernel.inductive import InductiveSpec, ConstructorSpec, declare_inductive
from ..kernel.reduce import normalize, whnf
from ..kernel.term import (Term, Const, Sort, App, Lam, Pi, mk_app, unfold_app,
                           abstract_const, instantiate, constants_of, PROP, TYPE)
from ..kernel.typecheck import add_decl, infer_type
from ..syntax import sast as S
from .context import ElabContext, ElabError
from .elaborator import Elaborator, CmdResult
from .pp import pp
from . import tactics as T


class CommandProcessor:
    def __init__(self, env: Environment, ctx: Optional[ElabContext] = None,
                 oracles: Optional[dict[str, Callable]] = None,
                 module: str = "<main>") -> None:
        self.env = env
        self.ctx = ctx or ElabContext(env)
        self.elab = Elaborator(env, self.ctx)
        self.oracles = oracles or {}
        self.module = module
        self._example_count = 0

    # ------------------------------------------------------------------
    def process(self, cmd: S.Command) -> list[CmdResult]:
        try:
            return self._process_inner(cmd)
        finally:
            if not self.ctx.namespaces:  # only sweep at true top level
                self.ctx.sweep_stray_locals()

    def _process_inner(self, cmd: S.Command) -> list[CmdResult]:
        if isinstance(cmd, S.CDef):
            return [self._do_def(cmd)]
        if isinstance(cmd, S.CConstant):
            return [self._do_constant(cmd)]
        if isinstance(cmd, S.CAxiom):
            return [self._do_axiom(cmd)]
        if isinstance(cmd, S.CTheorem):
            return [self._do_theorem(cmd)]
        if isinstance(cmd, S.CInductive):
            return [self._do_inductive(cmd)]
        if isinstance(cmd, S.CStructure):
            return [self._do_structure(cmd)]
        if isinstance(cmd, S.CCheck):
            return [self._do_check(cmd)]
        if isinstance(cmd, S.CEval):
            return [self._do_eval(cmd)]
        if isinstance(cmd, S.CPlot):
            return [self._do_plot(cmd)]
        if isinstance(cmd, S.CNotation):
            self.ctx.notations[cmd.symbol] = cmd.target
            return [CmdResult("notation", name=cmd.symbol,
                              message=f"{cmd.fixity} {cmd.precedence} "
                                      f"\"{cmd.symbol}\" := {cmd.target}",
                              span=cmd.span)]
        if isinstance(cmd, S.CNamespace):
            self.ctx.namespaces.append(cmd.name)
            results: list[CmdResult] = []
            try:
                for sub in cmd.body:
                    results.extend(self._process_inner(sub))
            finally:
                self.ctx.namespaces.pop()
            return results
        if isinstance(cmd, S.COpen):
            self.ctx.opens.append(cmd.name)
            return [CmdResult("open", name=cmd.name, span=cmd.span)]
        if isinstance(cmd, S.CImport):
            # imports are resolved by the project loader before processing
            return [CmdResult("import", name=cmd.module, span=cmd.span)]
        raise ElabError(f"unsupported command {type(cmd).__name__}", cmd.span)

    # ------------------------------------------------------------------
    def _apply_display_name(self, name: str, cmd: S.Command) -> Optional[str]:
        """Register the `@[name "..."]` mathematical name, if the command
        carries one. Returns the registered name, or None."""
        display = cmd.attr("name")
        if display is None:
            return None
        try:
            self.env.register_display_name(name, display)
        except KernelError as e:
            raise ElabError(str(e), cmd.span)
        return display

    def _with_binders(self, binders: list[S.SBinder]):
        base = len(self.ctx.locals)
        lf = self.elab.elab_command_binders(binders)
        return base, lf

    def _do_def(self, cmd: S.CDef) -> CmdResult:
        name = self.ctx.qualify(cmd.name)
        base, lf = self._with_binders(cmd.binders)
        try:
            ty = self.elab.elab_type(cmd.ty) if cmd.ty is not None else None
            value = self.elab.elab_expr(cmd.value, ty)
            value = self.elab.finalize(value, cmd.span)
            if name in set(constants_of(value)):
                raise ElabError(
                    f"'{cmd.name}' is recursive; use an inductive definition "
                    f"or explicit recursion via `Nat.rec`", cmd.span)
            if ty is None:
                ty = self.ctx.infer(value)
                ty = self.elab.finalize(ty, cmd.span)
            closed_val = self.elab.close_over(lf, value, as_pi=False)
            closed_ty = self.elab.close_over(lf, ty, as_pi=True)
        finally:
            self.ctx.pop_locals_to(base)
        decl = Declaration(name, DeclKind.DEFINITION, closed_ty, value=closed_val,
                           doc=cmd.doc, module=self.module, span=cmd.span,
                           attrs=cmd.flags())
        add_decl(self.env, decl)
        self._apply_display_name(name, cmd)
        return CmdResult("def", name=name, type=closed_ty, span=cmd.span,
                         message=f"{name} : {pp(self.env, closed_ty)}")

    def _do_constant(self, cmd: S.CConstant) -> CmdResult:
        name = self.ctx.qualify(cmd.name)
        ty = self.elab.elab_type(cmd.ty)
        ty = self.elab.finalize(ty, cmd.span)
        add_decl(self.env, Declaration(name, DeclKind.OPAQUE, ty, doc=cmd.doc,
                                       module=self.module, span=cmd.span))
        return CmdResult("constant", name=name, type=ty, span=cmd.span)

    def _do_axiom(self, cmd: S.CAxiom) -> CmdResult:
        name = self.ctx.qualify(cmd.name)
        base, lf = self._with_binders(cmd.binders)
        try:
            ty = self.elab.elab_prop(cmd.ty)
            ty = self.elab.finalize(ty, cmd.span)
            closed = self.elab.close_over(lf, ty, as_pi=True)
        finally:
            self.ctx.pop_locals_to(base)
        add_decl(self.env, Declaration(name, DeclKind.AXIOM, closed, doc=cmd.doc,
                                       module=self.module, span=cmd.span,
                                       attrs=cmd.flags()))
        self._apply_display_name(name, cmd)
        return CmdResult("axiom", name=name, type=closed, span=cmd.span,
                         message=f"axiom {name} : {pp(self.env, closed)}")

    def _do_theorem(self, cmd: S.CTheorem) -> CmdResult:
        if cmd.kind == "example":
            self._example_count += 1
            name = self.ctx.qualify(f"example_{self._example_count}")
        else:
            name = self.ctx.qualify(cmd.name)
        base, lf = self._with_binders(cmd.binders)
        trace = None
        try:
            statement = self.elab.elab_prop(cmd.statement)
            statement = self.elab.finalize(statement, cmd.span)
            if cmd.proof is None:
                raise ElabError(f"theorem '{cmd.name}' has no proof "
                                f"(use `:= by ...` or `:= sorry`)", cmd.span)
            if isinstance(cmd.proof, S.TermProof):
                proof = self.elab.elab_expr(cmd.proof.term, statement)
                proof = self.elab.finalize(proof, cmd.span)
            else:
                state = T.ProofState(self.elab, statement, oracles=self.oracles)
                T.run_tactics(state, cmd.proof.tactics)
                proof = state.finalize()
                trace = state.trace
            closed_stmt = self.elab.close_over(lf, statement, as_pi=True)
            closed_proof = self.elab.close_over(lf, proof, as_pi=False)
        finally:
            self.ctx.pop_locals_to(base)

        decl = Declaration(name, DeclKind.THEOREM, closed_stmt, value=closed_proof,
                           doc=cmd.doc, module=self.module, span=cmd.span,
                           statement_kind=cmd.kind, attrs=cmd.flags(),
                           reducible=False)
        add_decl(self.env, decl)  # THE trust step: kernel checks the proof
        self._apply_display_name(name, cmd)
        status = self.env.verification_status(name)
        return CmdResult("theorem", name=name, type=closed_stmt, span=cmd.span,
                         status=status, trace=trace,
                         message=f"{cmd.kind} {name} : {pp(self.env, closed_stmt)}")

    def _do_inductive(self, cmd: S.CInductive) -> CmdResult:
        name = self.ctx.qualify(cmd.name)
        base, lf = self._with_binders(cmd.binders)
        try:
            ind_sort = self.elab.elab_type(cmd.ty) if cmd.ty is not None else TYPE
            ind_ty = self.elab.close_over(lf, ind_sort, as_pi=True)
            # make the inductive visible while elaborating constructor types
            marker = len(self.env.order)
            self.env.add_unchecked(Declaration(name, DeclKind.OPAQUE, ind_ty))
            ctor_specs: list[ConstructorSpec] = []
            param_terms = [Const(ld.uname) for ld, _ in lf]
            self_applied = mk_app(Const(name), *param_terms)
            for c in cmd.ctors:
                cname = f"{name}.{c.name}"
                cty = self.elab.elab_type(c.ty)
                cty = self.elab.finalize(cty, cmd.span)
                closed_cty = self.elab.close_over(lf, cty, as_pi=True)
                ctor_specs.append(ConstructorSpec(cname, closed_cty))
            self.env.rollback_to(marker)
        finally:
            self.ctx.pop_locals_to(base)
        spec = InductiveSpec(name, ind_ty, len(lf), ctor_specs)
        declare_inductive(self.env, spec)
        d = self.env.expect(name)
        d.doc, d.module, d.span = cmd.doc, self.module, cmd.span
        self._apply_display_name(name, cmd)
        return CmdResult("inductive", name=name, type=ind_ty, span=cmd.span,
                         message=f"inductive {name} with "
                                 f"{len(ctor_specs)} constructors")

    def _do_structure(self, cmd: S.CStructure) -> CmdResult:
        name = self.ctx.qualify(cmd.name)
        base, lf = self._with_binders(cmd.binders)
        try:
            ind_ty = self.elab.close_over(lf, TYPE, as_pi=True)
            marker = len(self.env.order)
            self.env.add_unchecked(Declaration(name, DeclKind.OPAQUE, ind_ty))
            param_terms = [Const(ld.uname) for ld, _ in lf]
            self_applied = mk_app(Const(name), *param_terms)
            field_tys: list[tuple[str, Term]] = []
            fbase = len(self.ctx.locals)
            for f in cmd.fields:
                fty = self.elab.elab_type(f.ty)
                for prev_name, _ in field_tys:
                    pass  # dependency check below
                field_tys.append((f.name, fty))
            self.ctx.pop_locals_to(fbase)
            # constructor: mk : Π params, T1 → ... → Tn → S params
            cty: Term = self_applied
            for fname, fty in reversed(field_tys):
                from ..kernel.term import lift
                cty = Pi(fname, fty, lift(cty, 1))
            closed_cty = self.elab.close_over(lf, cty, as_pi=True)
            self.env.rollback_to(marker)
        finally:
            self.ctx.pop_locals_to(base)
        spec = InductiveSpec(name, ind_ty, len(lf),
                             [ConstructorSpec(f"{name}.mk", closed_cty)])
        declare_inductive(self.env, spec)
        # projections (non-dependent fields only)
        self._make_projections(name, len(lf), field_tys)
        d = self.env.expect(name)
        d.doc, d.module, d.span = cmd.doc, self.module, cmd.span
        self._apply_display_name(name, cmd)
        return CmdResult("structure", name=name, type=ind_ty, span=cmd.span,
                         message=f"structure {name} with {len(field_tys)} fields")

    def _make_projections(self, name: str, num_params: int,
                          field_tys: list[tuple[str, Term]]) -> None:
        if num_params > 0:
            return  # parameterized structure projections: future work
        rec = f"{name}.rec"
        if not self.env.contains(rec):
            return
        Sty = Const(name)
        k = len(field_tys)
        for i, (fname, fty) in enumerate(field_tys):
            if any(_mentions_local(fty) for _ in [0]):
                continue
            # λ (s : S), S.rec (λ _, Ti) (λ f1...fk, fi) s
            motive = Lam("_", Sty, _lift(fty))
            minor: Term = _var_at(k, i)
            for j, (fn2, ft2) in enumerate(reversed(field_tys)):
                minor = Lam(fn2, _lift_n(ft2, k - 1 - j), minor)
            body = mk_app(Const(rec), motive, minor, _Var0())
            proj = Lam("s", Sty, body)
            try:
                add_decl(self.env, Declaration(
                    f"{name}.{fname}", DeclKind.DEFINITION,
                    Pi("s", Sty, _lift(fty)), value=proj, module=self.module))
            except KernelError:
                continue

    # ------------------------------------------------------------------
    def _do_check(self, cmd: S.CCheck) -> CmdResult:
        t = self.elab.elab_expr(cmd.expr, None)
        t = self.elab.finalize(t, cmd.span)
        ty = self.ctx.infer(t)
        msg = f"{pp(self.env, t)} : {pp(self.env, ty)}"
        return CmdResult("check", message=msg, term=t, type=ty, span=cmd.span)

    def _do_eval(self, cmd: S.CEval) -> CmdResult:
        t = self.elab.elab_expr(cmd.expr, None)
        t = self.elab.finalize(t, cmd.span)
        ty = self.ctx.infer(t)
        nf = normalize(self.env, t)
        msg = pp(self.env, nf)
        return CmdResult("eval", message=msg, term=nf, type=ty, span=cmd.span,
                         extra={"input": t,
                                "mode": cmd.attrs[0].key if cmd.attrs else "eval"})

    def _do_plot(self, cmd: S.CPlot) -> CmdResult:
        R = Const("Real")
        fns: list[Term] = []
        labels: list[str] = []
        for e in cmd.exprs:
            fn = self._as_real_function(e, cmd.var)
            fns.append(fn)
            labels.append(_label_of(e))
        lo = self.elab.finalize(self.elab.elab_expr(cmd.lo, R), cmd.span) \
            if cmd.lo is not None else None
        hi = self.elab.finalize(self.elab.elab_expr(cmd.hi, R), cmd.span) \
            if cmd.hi is not None else None
        return CmdResult("plot", span=cmd.span,
                         extra={"functions": fns, "labels": labels,
                                "var": cmd.var, "lo": lo, "hi": hi})

    def _as_real_function(self, e: S.Expr, var: str) -> Term:
        R = Const("Real")
        # try: the expression already is a function ℝ → ℝ
        try:
            t = self.elab.elab_expr(e, None)
            t = self.elab.finalize(t, None)
            ty = self.ctx._safe_whnf(self.ctx.infer(t))
            if isinstance(ty, Pi):
                return t
        except ElabError:
            pass
        # else: an expression in the plot variable
        base = len(self.ctx.locals)
        try:
            ld = self.ctx.push_local(var, R)
            body = self.elab.elab_expr(e, R)
            body = self.elab.finalize(body, None)
            return Lam(var, R, abstract_const(body, ld.uname))
        finally:
            self.ctx.pop_locals_to(base)


def _label_of(e: S.Expr) -> str:
    if isinstance(e, S.SIdent):
        return e.name
    return "f"


def _mentions_local(t: Term) -> bool:
    from ..kernel.term import is_closed
    return not is_closed(t)


def _lift(t: Term) -> Term:
    from ..kernel.term import lift
    return lift(t, 1)


def _lift_n(t: Term, n: int) -> Term:
    from ..kernel.term import lift
    return lift(t, n)


def _var_at(total: int, index: int):
    from ..kernel.term import Var
    # fields bound outermost-first: f_index is Var(total - 1 - index)
    return Var(total - 1 - index)


def _Var0():
    from ..kernel.term import Var
    return Var(0)
