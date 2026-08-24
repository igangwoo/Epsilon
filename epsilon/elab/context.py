"""Elaboration context: locals, metavariables, name resolution, unification.

Design: local variables are represented as *temporary opaque constants* in
the kernel environment, with unique mangled names ("x✦17"). This lets every
kernel operation (whnf, def_eq, infer_type) treat locals uniformly; binders
are reconstructed with `abstract_const` when a scope closes, and the
temporary declarations are rolled back afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..kernel.env import Environment, Declaration, DeclKind, KernelError
from ..kernel.reduce import whnf, def_eq
from ..kernel.term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar,
    mk_app, unfold_app, instantiate, abstract_const,
)
from ..kernel.typecheck import infer_type

LOCAL_MARK = "✦"   # cannot appear in user identifiers


class ElabError(Exception):
    def __init__(self, msg: str, span=None) -> None:
        super().__init__(msg)
        self.msg = msg
        self.span = span


@dataclass
class LocalDecl:
    uname: str        # mangled unique constant name
    username: str     # what the user called it
    ty: Term


@dataclass
class MVarInfo:
    id: int
    ty: Optional[Term]      # may be None for type-level unknowns
    assignment: Optional[Term] = None


NUMERIC_ORDER = ["Nat", "Int", "Rat", "Real", "Complex"]
COERCE_FN = {
    ("Nat", "Int"): ["Int.ofNat"],
    ("Nat", "Rat"): ["Rat.ofNat"],
    ("Nat", "Real"): ["Real.ofNat"],
    ("Nat", "Complex"): ["Real.ofNat", "Complex.ofReal"],
    ("Int", "Rat"): ["Rat.ofInt"],
    ("Int", "Real"): ["Real.ofInt"],
    ("Int", "Complex"): ["Real.ofInt", "Complex.ofReal"],
    ("Rat", "Real"): ["Real.ofRat"],
    ("Rat", "Complex"): ["Real.ofRat", "Complex.ofReal"],
    ("Real", "Complex"): ["Complex.ofReal"],
}


class ElabContext:
    """Shared state for one elaboration session (one module / REPL)."""

    def __init__(self, env: Environment) -> None:
        self.env = env
        self.locals: list[LocalDecl] = []
        self.mvars: dict[int, MVarInfo] = {}
        self._fresh = 0
        self.namespaces: list[str] = []       # current namespace stack
        self.opens: list[str] = []            # opened namespaces
        self.notations: dict[str, str] = {}   # op symbol -> target function

    # ------------------------------------------------------------------
    # Locals
    # ------------------------------------------------------------------
    def fresh_name(self, base: str) -> str:
        self._fresh += 1
        return f"{base}{LOCAL_MARK}{self._fresh}"

    def push_local(self, username: str, ty: Term) -> LocalDecl:
        uname = self.fresh_name(username if username != "_" else "x")
        decl = Declaration(uname, DeclKind.OPAQUE, ty)
        try:
            self.env.add_unchecked(decl)
        except KernelError as e:
            raise ElabError(str(e))
        ld = LocalDecl(uname, username, ty)
        self.locals.append(ld)
        return ld

    def pop_locals_to(self, n: int) -> list[LocalDecl]:
        """Remove locals beyond index n (and their env decls). Returns removed."""
        removed = []
        while len(self.locals) > n:
            ld = self.locals.pop()
            removed.append(ld)
            self.env.decls.pop(ld.uname, None)
            if ld.uname in self.env.order:
                self.env.order.remove(ld.uname)
        self.env._axiom_cache.clear()
        removed.reverse()
        return removed

    def lookup_local(self, username: str) -> Optional[LocalDecl]:
        for ld in reversed(self.locals):
            if ld.username == username:
                return ld
        return None

    def local_by_uname(self, uname: str) -> Optional[LocalDecl]:
        for ld in reversed(self.locals):
            if ld.uname == uname:
                return ld
        return None

    def sweep_stray_locals(self) -> None:
        """Remove temporary local constants left in the environment by proof
        search (goal-scoped locals are not tracked on self.locals)."""
        live = {ld.uname for ld in self.locals}
        stray = [n for n in self.env.order if LOCAL_MARK in n and n not in live]
        if not stray:
            return
        for n in stray:
            self.env.decls.pop(n, None)
        stray_set = set(stray)
        self.env.order = [n for n in self.env.order if n not in stray_set]
        self.env._axiom_cache.clear()

    # ------------------------------------------------------------------
    # Name resolution
    # ------------------------------------------------------------------
    def resolve_global(self, name: str) -> Optional[str]:
        """Resolve a (possibly short) name against namespaces and opens."""
        # innermost namespace first: a.b.c, a.b, a
        for i in range(len(self.namespaces), 0, -1):
            cand = ".".join(self.namespaces[:i]) + "." + name
            if self.env.contains(cand):
                return cand
        for ns in reversed(self.opens):
            cand = ns + "." + name
            if self.env.contains(cand):
                return cand
        if self.env.contains(name):
            return name
        return None

    def qualify(self, name: str) -> str:
        """Full name for a new declaration in the current namespace."""
        if self.namespaces:
            return ".".join(self.namespaces) + "." + name
        return name

    # ------------------------------------------------------------------
    # Metavariables
    # ------------------------------------------------------------------
    def fresh_mvar(self, ty: Optional[Term]) -> MVar:
        self._fresh += 1
        mid = self._fresh
        self.mvars[mid] = MVarInfo(mid, ty)
        return MVar(mid)

    def assign(self, mid: int, value: Term) -> None:
        info = self.mvars[mid]
        if info.assignment is not None:
            raise ElabError(f"metavariable ?m{mid} assigned twice")
        info.assignment = value

    def resolve_mvars(self, t: Term) -> Term:
        """Substitute assigned metavariables (deep)."""
        if isinstance(t, MVar):
            info = self.mvars.get(t.id)
            if info and info.assignment is not None:
                return self.resolve_mvars(info.assignment)
            return t
        if isinstance(t, App):
            return App(self.resolve_mvars(t.fn), self.resolve_mvars(t.arg))
        if isinstance(t, Lam):
            return Lam(t.name, self.resolve_mvars(t.ty), self.resolve_mvars(t.body))
        if isinstance(t, Pi):
            return Pi(t.name, self.resolve_mvars(t.ty), self.resolve_mvars(t.body),
                      t.implicit)
        return t

    def _occurs(self, mid: int, t: Term) -> bool:
        if isinstance(t, MVar):
            if t.id == mid:
                return True
            info = self.mvars.get(t.id)
            if info and info.assignment is not None:
                return self._occurs(mid, info.assignment)
            return False
        if isinstance(t, App):
            return self._occurs(mid, t.fn) or self._occurs(mid, t.arg)
        if isinstance(t, (Lam, Pi)):
            return self._occurs(mid, t.ty) or self._occurs(mid, t.body)
        return False

    def has_unassigned_mvar(self, t: Term) -> bool:
        t = self.resolve_mvars(t)
        if isinstance(t, MVar):
            return True
        if isinstance(t, App):
            return self.has_unassigned_mvar(t.fn) or self.has_unassigned_mvar(t.arg)
        if isinstance(t, (Lam, Pi)):
            return self.has_unassigned_mvar(t.ty) or self.has_unassigned_mvar(t.body)
        return False

    # ------------------------------------------------------------------
    # Unification (first-order, with whnf)
    # ------------------------------------------------------------------
    def unify(self, a: Term, b: Term, _depth: int = 0, *,
              strict: bool = False) -> bool:
        """First-order unification. Tries *syntactic* congruence before any
        reduction, so patterns match terms in their surface form (essential
        for rewriting); reduction and definitional equality are fallbacks.

        strict=True disables the reduction/def-eq fallbacks entirely - used
        by rewriting to prefer clean syntactic matches (a whnf-based match
        can leak recursor forms into metavariable assignments)."""
        if _depth > 256:
            return False
        a = self.resolve_mvars(a)
        b = self.resolve_mvars(b)
        if a == b:
            return True

        if isinstance(a, MVar):
            if self._occurs(a.id, b):
                return False
            self.assign(a.id, b)
            return True
        if isinstance(b, MVar):
            if self._occurs(b.id, a):
                return False
            self.assign(b.id, a)
            return True

        if isinstance(a, Sort) and isinstance(b, Sort):
            return a.level == b.level
        if isinstance(a, Lit) and isinstance(b, Lit):
            return a.value == b.value and a.tyname == b.tyname
        if isinstance(a, StrLit) and isinstance(b, StrLit):
            return a.value == b.value

        # bridge Nat literals with constructor forms: 3 =?= succ ?n, 0 =?= zero
        for x, y in ((a, b), (b, a)):
            if isinstance(x, Lit) and x.tyname == "Nat":
                yh, yargs = unfold_app(y)
                if isinstance(yh, Const):
                    if yh.name == "Nat.succ" and len(yargs) == 1 and x.value > 0:
                        return self.unify(Lit(x.value - 1, "Nat"), yargs[0],
                                          _depth + 1, strict=strict)
                    if yh.name == "Nat.zero" and not yargs and x.value == 0:
                        return True

        if isinstance(a, Pi) and isinstance(b, Pi):
            if not self.unify(a.ty, b.ty, _depth + 1, strict=strict):
                return False
            ld = self.push_local("u", self.resolve_mvars(a.ty))
            try:
                return self.unify(instantiate(a.body, Const(ld.uname)),
                                  instantiate(b.body, Const(ld.uname)),
                                  _depth + 1, strict=strict)
            finally:
                self.pop_locals_to(len(self.locals) - 1)
        if isinstance(a, Lam) and isinstance(b, Lam):
            ld = self.push_local("u", self.resolve_mvars(a.ty))
            try:
                return self.unify(instantiate(a.body, Const(ld.uname)),
                                  instantiate(b.body, Const(ld.uname)),
                                  _depth + 1, strict=strict)
            finally:
                self.pop_locals_to(len(self.locals) - 1)

        # syntactic congruence on the terms AS GIVEN (no reduction yet)
        ah, aargs = unfold_app(a)
        bh, bargs = unfold_app(b)
        if ah == bh and aargs and len(aargs) == len(bargs) \
                and not isinstance(ah, MVar):
            snapshot = {mid: info.assignment for mid, info in self.mvars.items()}
            if all(self.unify(x, y, _depth + 1, strict=strict)
                   for x, y in zip(aargs, bargs)):
                return True
            for mid, asg in snapshot.items():
                self.mvars[mid].assignment = asg

        if strict:
            return False

        # reduce and retry
        a_w = self._safe_whnf(a)
        b_w = self._safe_whnf(b)
        if a_w != a or b_w != b:
            return self.unify(a_w, b_w, _depth + 1)

        # last resort: definitional equality (only for mvar-free terms)
        if not self.has_unassigned_mvar(a) and not self.has_unassigned_mvar(b):
            try:
                return def_eq(self.env, self.resolve_mvars(a), self.resolve_mvars(b))
            except KernelError:
                return False
        return False

    def _safe_whnf(self, t: Term) -> Term:
        from ..kernel.term import has_mvar
        if has_mvar(t):
            # only beta-reduce heads that don't need the kernel
            h, args = unfold_app(t)
            if isinstance(h, Lam) and args:
                return self._safe_whnf(mk_app(instantiate(h.body, args[0]), *args[1:]))
            return t
        try:
            return whnf(self.env, t)
        except KernelError:
            return t

    # ------------------------------------------------------------------
    # Typing and coercion
    # ------------------------------------------------------------------
    def infer(self, t: Term) -> Term:
        t = self.resolve_mvars(t)
        if isinstance(t, MVar):
            info = self.mvars.get(t.id)
            if info and info.ty is not None:
                return info.ty
            raise ElabError("cannot infer type of metavariable")
        try:
            return infer_type(self.env, t)
        except KernelError as e:
            raise ElabError(str(e))

    def numeric_name(self, ty: Term) -> Optional[str]:
        ty = self._safe_whnf(self.resolve_mvars(ty))
        if isinstance(ty, Const) and ty.name in NUMERIC_ORDER:
            return ty.name
        return None

    def coerce(self, term: Term, actual: Term, expected: Term) -> Optional[Term]:
        """Try to coerce `term : actual` to type `expected`. None if impossible."""
        an = self.numeric_name(actual)
        en = self.numeric_name(expected)
        if an is None or en is None or an == en:
            return None
        ai, ei = NUMERIC_ORDER.index(an), NUMERIC_ORDER.index(en)
        if ai > ei:
            return None
        term_r = self.resolve_mvars(term)
        if isinstance(term_r, Lit) and en != "Complex":
            return Lit(term_r.value, en)  # retype literal directly (def-eq)
        chain = COERCE_FN.get((an, en))
        if chain is None:
            return None
        out = term
        for fn in chain:
            out = App(Const(fn), out)
        return out

    def ensure_type(self, term: Term, expected: Term, span=None,
                    what: str = "expression") -> Term:
        actual = self.infer(term)
        if self.unify(actual, expected):
            return term
        coerced = self.coerce(term, actual, expected)
        if coerced is not None:
            return coerced
        from .pp import pp
        raise ElabError(
            f"type mismatch in {what}: expected `{pp(self.env, self.resolve_mvars(expected))}`, "
            f"got `{pp(self.env, self.resolve_mvars(actual))}`", span)
