"""The elaborator: surface AST -> kernel terms, and command processing.

Handles implicit-argument insertion (metavariables + first-order
unification), numeric-tower coercions (Nat -> Int -> Rat -> Real -> Complex),
operator resolution by type, binder management, and dispatch to the tactic
engine for `by` proofs. Every produced declaration is finally checked by the
kernel (`add_decl`) - elaboration is untrusted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from typing import Optional

from ..kernel.env import (Environment, Declaration, DeclKind, KernelError,
                          SORRY_AXIOM)
from ..kernel.inductive import (InductiveSpec, ConstructorSpec,
                                declare_inductive, close_pi, close_lam, ph)
from ..kernel.reduce import whnf, def_eq, normalize
from ..kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit,
                           MVar, mk_app, unfold_app, instantiate,
                           abstract_const, PROP, TYPE)
from ..kernel.typecheck import add_decl, infer_type
from ..syntax import sast as S
from .context import ElabContext, ElabError, LocalDecl, NUMERIC_ORDER

LOGIC_OPS = {"/\\": "And", "\\/": "Or", "<->": "Iff"}
ARITH_OPS = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "mod", "^": "pow"}
CMP_OPS = {"<": ("lt", False), "<=": ("le", False), ">": ("lt", True), ">=": ("le", True)}


@dataclass
class CmdResult:
    kind: str                      # def|theorem|axiom|check|eval|plot|...
    name: Optional[str] = None
    message: Optional[str] = None
    term: Optional[Term] = None
    type: Optional[Term] = None
    status: Optional[str] = None   # verification status for theorems
    span: S.Span = (0, 0, 0, 0)
    extra: dict = field(default_factory=dict)
    trace: Optional[object] = None  # proof trace for visualization


class Elaborator:
    def __init__(self, env: Environment, ctx: Optional[ElabContext] = None) -> None:
        self.env = env
        self.ctx = ctx or ElabContext(env)

    # ==================================================================
    # Expressions
    # ==================================================================
    def elab_expr(self, e: S.Expr, expected: Optional[Term] = None) -> Term:
        t = self._elab(e, expected)
        if expected is not None:
            t = self.ensure_expected(t, expected, e.span)
        return t

    def _elab(self, e: S.Expr, expected: Optional[Term]) -> Term:
        if isinstance(e, S.SNum):
            return self._elab_num(e, expected)
        if isinstance(e, S.SStr):
            return StrLit(e.value)
        if isinstance(e, S.SIdent):
            return self._elab_ident(e, expected)
        if isinstance(e, S.SApp):
            return self._elab_app(e, expected)
        if isinstance(e, S.SBinOp):
            return self._elab_binop(e, expected)
        if isinstance(e, S.SUnOp):
            return self._elab_unop(e, expected)
        if isinstance(e, S.SArrow):
            lhs = self.elab_type(e.lhs)
            rhs = self.elab_type(e.rhs)
            from ..kernel.term import lift
            return Pi("_", lhs, lift(rhs, 1))
        if isinstance(e, S.SForall):
            return self._elab_binder_scope(e.binders, e.body, "forall", expected)
        if isinstance(e, S.SExists):
            return self._elab_binder_scope(e.binders, e.body, "exists", expected)
        if isinstance(e, S.SLambda):
            return self._elab_binder_scope(e.binders, e.body, "lambda", expected)
        if isinstance(e, S.STuple):
            return self._elab_tuple(e, expected)
        if isinstance(e, S.SAnonCtor):
            return self._elab_anon_ctor(e, expected)
        if isinstance(e, S.SIf):
            return self._elab_if(e, expected)
        if isinstance(e, S.SSetOf):
            return self._elab_setof(e)
        if isinstance(e, S.SSorry):
            if expected is None:
                raise ElabError("`sorry` needs an expected proposition", e.span)
            return App(Const(SORRY_AXIOM), expected)
        if isinstance(e, S.SAscribe):
            ty = self.elab_type(e.ty)
            inner = self._elab(e.expr, ty)
            return self.ensure_expected(inner, ty, e.span, what="type ascription")
        raise ElabError(f"cannot elaborate {type(e).__name__}", getattr(e, "span", None))

    # ------------------------------------------------------------------
    def _elab_num(self, e: S.SNum, expected: Optional[Term]) -> Term:
        tyname = None
        if expected is not None:
            tyname = self.ctx.numeric_name(expected)
        if tyname == "Complex":
            return App(Const("Complex.ofReal"), Lit(e.value, "Real"))
        if tyname is None:
            tyname = "Rat" if e.is_decimal else "Nat"
        if tyname in ("Nat", "Int") and e.value.denominator != 1:
            tyname = "Rat"
        return Lit(e.value, tyname)

    def _elab_ident(self, e: S.SIdent, expected: Optional[Term]) -> Term:
        name = e.name
        if name == "_":
            return self.ctx.fresh_mvar(expected)
        if name == "Prop":
            return PROP
        if name == "Type":
            return TYPE
        ld = self.ctx.lookup_local(name)
        if ld is not None:
            return Const(ld.uname)
        # dotted locals like h.left? (not supported) -> resolve globally
        resolved = self.ctx.resolve_global(name)
        if resolved is None and "." in name:
            # try resolving the first segment as a namespace alias
            resolved = self.ctx.resolve_global(name)
        if resolved is None:
            raise ElabError(f"unknown identifier '{name}'", e.span)
        return Const(resolved)

    def _elab_app(self, e: S.SApp, expected: Optional[Term]) -> Term:
        fn = self._elab(e.fn, None)
        fn_ty = self.ctx.infer(fn)
        for sarg in e.args:
            fn, fn_ty = self._insert_implicits(fn, fn_ty)
            fn_ty = self.ctx._safe_whnf(fn_ty)
            if not isinstance(fn_ty, Pi):
                from .pp import pp
                raise ElabError(
                    f"too many arguments: `{pp(self.env, self.ctx.resolve_mvars(fn))}` "
                    f"has type `{pp(self.env, self.ctx.resolve_mvars(fn_ty))}`", e.span)
            dom = fn_ty.ty
            arg = self._elab(sarg, dom)
            arg = self.ensure_expected(arg, dom, sarg.span, what="argument")
            fn = App(fn, arg)
            fn_ty = instantiate(fn_ty.body, arg)
        return fn

    def _insert_implicits(self, term: Term, ty: Term) -> tuple[Term, Term]:
        ty = self.ctx._safe_whnf(ty)
        while isinstance(ty, Pi) and ty.implicit:
            mv = self.ctx.fresh_mvar(ty.ty)
            term = App(term, mv)
            ty = self.ctx._safe_whnf(instantiate(ty.body, mv))
        return term, ty

    def _elab_binop(self, e: S.SBinOp, expected: Optional[Term]) -> Term:
        op = e.op

        # user-defined operators
        target = self.ctx.notations.get(op)
        if target is not None:
            return self._elab_app(
                S.SApp(fn=S.SIdent(name=target, span=e.span),
                       args=[e.lhs, e.rhs], span=e.span), expected)

        if op in LOGIC_OPS:
            l = self.elab_prop(e.lhs)
            r = self.elab_prop(e.rhs)
            return mk_app(Const(LOGIC_OPS[op]), l, r)

        if op == "=":
            l, r, T = self._elab_homogeneous(e)
            sort = self.ctx._safe_whnf(self.ctx.infer(T))
            if isinstance(sort, Sort) and sort.level == 0:
                raise ElabError("use ↔ (iff) to relate propositions, not =", e.span)
            return mk_app(Const("Eq"), T, l, r)
        if op == "!=":
            l, r, T = self._elab_homogeneous(e)
            return mk_app(Const("Ne"), T, l, r)
        if op == "==":
            l, r, T = self._elab_homogeneous(e)
            tn = self.ctx.numeric_name(T)
            if tn is None:
                raise ElabError("== (boolean equality) needs numeric operands", e.span)
            return mk_app(Const(f"{tn}.beq"), l, r)

        if op in CMP_OPS:
            fn, swap = CMP_OPS[op]
            l, r, T = self._elab_homogeneous(e)
            tn = self.ctx.numeric_name(T)
            head = f"{tn}.{fn}" if tn else None
            if head is None or not self.env.contains(head):
                from .pp import pp
                raise ElabError(f"no order on type `{pp(self.env, T)}`", e.span)
            return mk_app(Const(head), r, l) if swap else mk_app(Const(head), l, r)

        if op in ARITH_OPS:
            return self._elab_arith(e, expected)

        if op == "∈":
            return self._elab_mem(e)
        if op == "∉":
            return App(Const("Not"), self._elab_mem(e))
        if op == "⊆":
            s = self._elab(e.lhs, None)
            sty = self.ctx._safe_whnf(self.ctx.infer(s))
            A = self._set_elem_type(sty, e.span)
            t = self.elab_expr(e.rhs, mk_app(Const("Set"), A))
            return mk_app(Const("Set.subset"), A, s, t)
        if op == "><":
            l = self.elab_type(e.lhs)
            r = self.elab_type(e.rhs)
            return mk_app(Const("Prod"), l, r)
        if op == "∘":
            g = self._elab(e.lhs, None)
            f = self._elab(e.rhs, None)
            A = self.ctx.fresh_mvar(TYPE)
            B = self.ctx.fresh_mvar(TYPE)
            C = self.ctx.fresh_mvar(TYPE)
            out = mk_app(Const("Function.comp"), A, B, C, g, f)
            self.ctx.infer(mk_app(Const("Function.comp"), A, B, C))  # force types
            gt = self.ctx.infer(g)
            ft = self.ctx.infer(f)
            if not (self.ctx.unify(gt, Pi("_", B, _lift1(C)))
                    and self.ctx.unify(ft, Pi("_", A, _lift1(B)))):
                raise ElabError("cannot compose: operand types do not match", e.span)
            return out

        raise ElabError(f"unknown operator '{op}'", e.span)

    def _elab_mem(self, e: S.SBinOp) -> Term:
        s = self._elab(e.rhs, None)
        sty = self.ctx._safe_whnf(self.ctx.infer(s))
        A = self._set_elem_type(sty, e.span)
        x = self.elab_expr(e.lhs, A)
        return mk_app(Const("Set.mem"), A, x, s)

    def _set_elem_type(self, sty: Term, span) -> Term:
        h, args = unfold_app(sty)
        if isinstance(h, Const) and h.name == "Set" and len(args) == 1:
            return args[0]
        from .pp import pp
        raise ElabError(f"expected a Set, got `{pp(self.env, sty)}`", span)

    def _elab_homogeneous(self, e: S.SBinOp) -> tuple[Term, Term, Term]:
        """Elaborate both sides to a common type (with numeric joining)."""
        l = self._elab(e.lhs, None)
        r = self._elab(e.rhs, None)
        lt = self.ctx.infer(l)
        rt = self.ctx.infer(r)
        if self.ctx.unify(lt, rt):
            return l, r, self.ctx.resolve_mvars(lt)
        ln, rn = self.ctx.numeric_name(lt), self.ctx.numeric_name(rt)
        if ln and rn:
            join = NUMERIC_ORDER[max(NUMERIC_ORDER.index(ln), NUMERIC_ORDER.index(rn))]
            J = Const(join)
            l2 = self.ctx.coerce(l, lt, J) if ln != join else l
            r2 = self.ctx.coerce(r, rt, J) if rn != join else r
            if l2 is not None and r2 is not None:
                return l2, r2, J
        from .pp import pp
        raise ElabError(
            f"operands have different types: `{pp(self.env, self.ctx.resolve_mvars(lt))}` "
            f"vs `{pp(self.env, self.ctx.resolve_mvars(rt))}`", e.span)

    def _elab_arith(self, e: S.SBinOp, expected: Optional[Term]) -> Term:
        op = e.op
        exp_num = self.ctx.numeric_name(expected) if expected is not None else None
        l = self._elab(e.lhs, Const(exp_num) if exp_num else None)
        r = self._elab(e.rhs, Const(exp_num) if exp_num else None)
        lt, rt = self.ctx.infer(l), self.ctx.infer(r)
        ln, rn = self.ctx.numeric_name(lt), self.ctx.numeric_name(rt)
        if ln is None or rn is None:
            # non-numeric: try T.op on the lhs type (vectors, matrices, ...)
            h, _ = unfold_app(self.ctx._safe_whnf(lt))
            if isinstance(h, Const):
                cand = f"{h.name}.{ARITH_OPS[op]}"
                if self.env.contains(cand):
                    return self._apply_checked(Const(cand), [l, r], e.span)
            from .pp import pp
            raise ElabError(
                f"operator '{op}' undefined for type "
                f"`{pp(self.env, self.ctx.resolve_mvars(lt))}`", e.span)
        join_i = max(NUMERIC_ORDER.index(ln), NUMERIC_ORDER.index(rn))
        if exp_num is not None:
            join_i = max(join_i, NUMERIC_ORDER.index(exp_num))
        # subtraction/division promote away from Nat when the user expects them
        join = NUMERIC_ORDER[join_i]
        if op == "/" and join in ("Nat", "Int") and not (
                isinstance(self.ctx.resolve_mvars(l), Lit)
                and isinstance(self.ctx.resolve_mvars(r), Lit)
                and (self.ctx.resolve_mvars(l).value % self.ctx.resolve_mvars(r).value == 0
                     if self.ctx.resolve_mvars(r).value != 0 else False)):
            # keep integer division only when it is exact on literals;
            # otherwise this is mathematics: 1/2 lives in ℚ
            if exp_num is None:
                join = "Rat"
                join_i = NUMERIC_ORDER.index("Rat")
        if op == "%" and join not in ("Nat", "Int"):
            raise ElabError("% is only defined on Nat and Int", e.span)
        J = Const(join)
        lj = self.ctx.coerce(l, lt, J) or l
        rj = self.ctx.coerce(r, rt, J) or r
        fn = f"{join}.{ARITH_OPS[op]}"
        if not self.env.contains(fn):
            raise ElabError(f"operator '{op}' undefined on {join}", e.span)
        return mk_app(Const(fn), lj, rj)

    def _apply_checked(self, fn: Term, args: list[Term], span) -> Term:
        ty = self.ctx.infer(fn)
        out = fn
        for a in args:
            out, ty = self._insert_implicits(out, ty)
            ty = self.ctx._safe_whnf(ty)
            if not isinstance(ty, Pi):
                raise ElabError("too many arguments", span)
            a2 = self.ensure_expected(a, ty.ty, span, what="argument")
            out = App(out, a2)
            ty = instantiate(ty.body, a2)
        return out

    def _elab_unop(self, e: S.SUnOp, expected: Optional[Term]) -> Term:
        if e.op == "¬":
            return App(Const("Not"), self.elab_prop(e.operand))
        if e.op == "-":
            x = self._elab(e.operand, expected)
            xt = self.ctx.infer(x)
            tn = self.ctx.numeric_name(xt)
            if tn is None:
                raise ElabError("unary minus needs a numeric operand", e.span)
            if tn == "Nat":  # ℕ has no negation: promote to ℤ
                x = self.ctx.coerce(x, xt, Const("Int")) or x
                tn = "Int"
            xr = self.ctx.resolve_mvars(x)
            if isinstance(xr, Lit):
                return Lit(-xr.value, xr.tyname)
            return App(Const(f"{tn}.neg"), x)
        if e.op == "√":
            x = self.elab_expr(e.operand, Const("Real"))
            return App(Const("Real.sqrt"), x)
        raise ElabError(f"unknown prefix operator '{e.op}'", e.span)

    def _elab_binder_scope(self, binders: list[S.SBinder], body: S.Expr,
                           kind: str, expected: Optional[Term]) -> Term:
        base = len(self.ctx.locals)
        entered: list[LocalDecl] = []
        exp = expected
        try:
            for b in binders:
                bty: Optional[Term] = None
                if b.ty is not None:
                    bty = self.elab_type(b.ty)
                elif kind == "lambda" and exp is not None:
                    ew = self.ctx._safe_whnf(exp)
                    if isinstance(ew, Pi):
                        bty = ew.ty
                if bty is None:
                    raise ElabError(
                        f"binder '{b.name}' needs a type annotation", b.span)
                ld = self.ctx.push_local(b.name, bty)
                entered.append(ld)
                if kind == "lambda" and exp is not None:
                    ew = self.ctx._safe_whnf(exp)
                    exp = instantiate(ew.body, Const(ld.uname)) if isinstance(ew, Pi) else None

            if kind == "forall":
                inner = self.elab_prop(body) if self._expect_prop(entered) else \
                    self.elab_expr(body, None)
                # ∀ over anything type-like: build Pi
                out = inner
                for ld in reversed(entered):
                    out = Pi(ld.username, ld.ty, abstract_const(out, ld.uname))
                return out
            if kind == "exists":
                inner = self.elab_prop(body)
                out = inner
                for ld in reversed(entered):
                    pred = Lam(ld.username, ld.ty, abstract_const(out, ld.uname))
                    out = mk_app(Const("Exists"), ld.ty, pred)
                return out
            # lambda
            inner = self.elab_expr(body, exp)
            out = inner
            for ld in reversed(entered):
                out = Lam(ld.username, ld.ty, abstract_const(out, ld.uname))
            return out
        finally:
            self.ctx.pop_locals_to(base)

    def _expect_prop(self, entered) -> bool:
        return True  # ∀-bodies are propositions in practice; harmless otherwise

    def _elab_tuple(self, e: S.STuple, expected: Optional[Term]) -> Term:
        # right-nested pairs
        parts = e.args
        exp = self.ctx._safe_whnf(expected) if expected is not None else None
        terms: list[Term] = []
        # try component-wise expectation for Prod
        if exp is not None:
            h, args = unfold_app(exp)
            if isinstance(h, Const) and h.name == "Prod" and len(args) == 2 and len(parts) == 2:
                a = self.elab_expr(parts[0], args[0])
                b = self.elab_expr(parts[1], args[1])
                return mk_app(Const("Prod.mk"), args[0], args[1], a, b)
        if len(parts) == 2:
            a = self._elab(parts[0], None)
            b = self._elab(parts[1], None)
            return mk_app(Const("Prod.mk"), self.ctx.infer(a), self.ctx.infer(b), a, b)
        # n-tuple: (a, b, c) = (a, (b, c))
        rest = S.STuple(args=parts[1:], span=e.span)
        return self._elab_tuple(S.STuple(args=[parts[0], rest], span=e.span), expected)

    def _elab_anon_ctor(self, e: S.SAnonCtor, expected: Optional[Term]) -> Term:
        if expected is None:
            raise ElabError("⟨...⟩ needs an expected type", e.span)
        exp = self.ctx._safe_whnf(self.ctx.resolve_mvars(expected))
        h, args = unfold_app(exp)
        if not isinstance(h, Const) or h.name not in self.env.inductives:
            from .pp import pp
            raise ElabError(
                f"⟨...⟩: expected type `{pp(self.env, exp)}` is not an inductive",
                e.span)
        info = self.env.inductives[h.name]
        if len(info.constructors) != 1:
            raise ElabError(
                f"⟨...⟩ needs a single-constructor type, but {h.name} has "
                f"{len(info.constructors)}", e.span)
        cname = info.constructors[0]
        fn: Term = Const(cname)
        ty = self.ctx.infer(fn)
        # apply parameters from the expected type
        for p in args[:info.num_params]:
            ty = self.ctx._safe_whnf(ty)
            if not isinstance(ty, Pi):
                raise ElabError("constructor arity mismatch", e.span)
            fn = App(fn, p)
            ty = instantiate(ty.body, p)
        for sarg in e.args:
            ty = self.ctx._safe_whnf(ty)
            if not isinstance(ty, Pi):
                raise ElabError("too many components in ⟨...⟩", e.span)
            a = self.elab_expr(sarg, ty.ty)
            fn = App(fn, a)
            ty = instantiate(ty.body, a)
        if isinstance(self.ctx._safe_whnf(ty), Pi):
            raise ElabError("not enough components in ⟨...⟩", e.span)
        return fn

    def _elab_if(self, e: S.SIf, expected: Optional[Term]) -> Term:
        cond = self._elab_bool_cond(e.cond)
        t = self._elab(e.then, expected)
        tty = self.ctx.infer(t)
        f = self.elab_expr(e.els, tty)
        return mk_app(Const("ite"), tty, cond, t, f)

    def _elab_bool_cond(self, e: S.Expr) -> Term:
        # decidable comparisons become Bool operations
        if isinstance(e, S.SBinOp) and e.op in ("<", "<=", ">", ">=", "=", "!=", "=="):
            l, r, T = self._elab_homogeneous(
                S.SBinOp(op=e.op, lhs=e.lhs, rhs=e.rhs, span=e.span))
            tn = self.ctx.numeric_name(T)
            if tn is None:
                raise ElabError("if-condition must be decidable (numeric)", e.span)
            table = {"<": ("blt", False), "<=": ("ble", False), ">": ("blt", True),
                     ">=": ("ble", True), "=": ("beq", False), "==": ("beq", False),
                     "!=": ("beq", False)}
            fn, swap = table[e.op]
            core = mk_app(Const(f"{tn}.{fn}"), *( [r, l] if swap else [l, r]))
            return core
        return self.elab_expr(e, Const("Bool"))

    def _elab_setof(self, e: S.SSetOf) -> Term:
        if e.binder.ty is None:
            raise ElabError("set-builder binder needs a type: { x : T | p }",
                            e.span)
        A = self.elab_type(e.binder.ty)
        base = len(self.ctx.locals)
        try:
            ld = self.ctx.push_local(e.binder.name, A)
            p = self.elab_prop(e.pred)
            pred = Lam(ld.username, A, abstract_const(p, ld.uname))
        finally:
            self.ctx.pop_locals_to(base)
        return mk_app(Const("setOf"), A, pred)

    # ------------------------------------------------------------------
    def elab_type(self, e: S.Expr) -> Term:
        t = self._elab(e, None)
        ty = self.ctx._safe_whnf(self.ctx.infer(t))
        if not isinstance(ty, Sort):
            from .pp import pp
            raise ElabError(f"expected a type, got value of type "
                            f"`{pp(self.env, ty)}`", getattr(e, "span", None))
        return self.ctx.resolve_mvars(t)

    def elab_prop(self, e: S.Expr) -> Term:
        t = self._elab(e, None)
        ty = self.ctx._safe_whnf(self.ctx.infer(t))
        if isinstance(ty, Sort) and ty.level == 0:
            return t
        # Bool-valued expressions coerce to Prop: b = true
        if isinstance(ty, Const) and ty.name == "Bool":
            return mk_app(Const("Eq"), Const("Bool"), t, Const("Bool.true"))
        if isinstance(ty, Sort):
            return t  # a Type used where a Prop is wanted: let ∀ handle it
        from .pp import pp
        raise ElabError(f"expected a proposition, got value of type "
                        f"`{pp(self.env, ty)}`", getattr(e, "span", None))

    def ensure_expected(self, term: Term, expected: Term, span=None,
                        what: str = "expression") -> Term:
        actual = self.ctx.infer(term)
        while True:
            if self.ctx.unify(actual, expected):
                return term
            aw = self.ctx._safe_whnf(actual)
            if isinstance(aw, Pi) and aw.implicit:
                mv = self.ctx.fresh_mvar(aw.ty)
                term = App(term, mv)
                actual = instantiate(aw.body, mv)
                continue
            coerced = self.ctx.coerce(term, actual, expected)
            if coerced is not None:
                return coerced
            from .pp import pp
            raise ElabError(
                f"type mismatch in {what}:\n  expected `"
                f"{pp(self.env, self.ctx.resolve_mvars(expected))}`\n  got      `"
                f"{pp(self.env, self.ctx.resolve_mvars(actual))}`", span)

    # ==================================================================
    # Binders for commands
    # ==================================================================
    def elab_command_binders(self, binders: list[S.SBinder]) -> list[LocalDecl]:
        out = []
        for b in binders:
            if b.ty is None:
                raise ElabError(f"parameter '{b.name}' needs a type annotation",
                                b.span)
            ty = self.elab_type(b.ty)
            ld = self.ctx.push_local(b.name, ty)
            ld_implicit = b.implicit
            out.append((ld, ld_implicit))
        return out

    def close_over(self, locals_flags, body: Term, as_pi: bool) -> Term:
        out = body
        for ld, implicit in reversed(locals_flags):
            abstracted = abstract_const(out, ld.uname)
            if as_pi:
                out = Pi(ld.username, ld.ty, abstracted, implicit=implicit)
            else:
                out = Lam(ld.username, ld.ty, abstracted)
        return out

    def finalize(self, t: Term, span=None) -> Term:
        t = self.ctx.resolve_mvars(t)
        if self.ctx.has_unassigned_mvar(t):
            raise ElabError("cannot infer all implicit arguments "
                            "(unresolved metavariables remain)", span)
        return t


def _lift1(t: Term) -> Term:
    from ..kernel.term import lift
    return lift(t, 1)
