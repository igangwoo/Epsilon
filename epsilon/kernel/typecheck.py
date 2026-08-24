"""The kernel type checker.

`infer_type` computes the type of a kernel term in a local context;
`check_type` verifies a term against an expected type up to definitional
equality. `add_decl` is the only checked way to extend an environment.

The checker rejects metavariables outright: elaboration must fully solve
a term before the kernel will look at it.
"""

from __future__ import annotations

from typing import Optional

from .env import Environment, Declaration, DeclKind, KernelError
from .reduce import whnf, def_eq
from .term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar,
    instantiate, lift, has_mvar,
)

# Local context: list of types, innermost (Var 0) first.
Ctx = list[Term]


def infer_type(env: Environment, t: Term, ctx: Optional[Ctx] = None) -> Term:
    ctx = ctx if ctx is not None else []
    return _infer(env, t, ctx)


def _infer(env: Environment, t: Term, ctx: Ctx) -> Term:
    if isinstance(t, MVar):
        raise KernelError("kernel refuses terms containing metavariables")

    if isinstance(t, Var):
        if t.idx >= len(ctx):
            raise KernelError(f"unbound variable #{t.idx}")
        # types in ctx are expressed in the context where they were bound;
        # shift into the current context
        return lift(ctx[t.idx], t.idx + 1)

    if isinstance(t, Const):
        decl = env.get(t.name)
        if decl is None:
            raise KernelError(f"unknown constant '{t.name}'")
        return decl.type

    if isinstance(t, Sort):
        return Sort(t.level + 1)

    if isinstance(t, Lit):
        if t.tyname not in ("Nat", "Int", "Rat", "Real"):
            raise KernelError(f"bad literal type '{t.tyname}'")
        if not env.contains(t.tyname):
            raise KernelError(f"literal type '{t.tyname}' not declared")
        return Const(t.tyname)

    if isinstance(t, StrLit):
        if not env.contains("String"):
            raise KernelError("String type not declared")
        return Const("String")

    if isinstance(t, Lam):
        _ensure_sort(env, _infer(env, t.ty, ctx), "binder type")
        body_ty = _infer(env, t.body, [t.ty] + ctx)
        return Pi(t.name, t.ty, body_ty)

    if isinstance(t, Pi):
        s1 = _ensure_sort(env, _infer(env, t.ty, ctx), "Pi domain")
        s2 = _ensure_sort(env, _infer(env, t.body, [t.ty] + ctx), "Pi codomain")
        # imax: Prop is impredicative
        level = 0 if s2.level == 0 else max(s1.level, s2.level)
        return Sort(level)

    if isinstance(t, App):
        fn_ty = whnf(env, _infer(env, t.fn, ctx))
        if not isinstance(fn_ty, Pi):
            raise KernelError(
                f"cannot apply non-function (type is {fn_ty!r}) in {t!r}")
        arg_ty = _infer(env, t.arg, ctx)
        if not def_eq(env, arg_ty, fn_ty.ty):
            raise KernelError(
                f"type mismatch in application:\n  function expects {fn_ty.ty!r}\n"
                f"  argument has type {arg_ty!r}")
        return instantiate(fn_ty.body, t.arg)

    raise KernelError(f"cannot infer type of {t!r}")


def _ensure_sort(env: Environment, ty: Term, what: str) -> Sort:
    ty = whnf(env, ty)
    if not isinstance(ty, Sort):
        raise KernelError(f"{what} must be a sort, got {ty!r}")
    return ty


def check_type(env: Environment, t: Term, expected: Term,
               ctx: Optional[Ctx] = None) -> None:
    actual = infer_type(env, t, ctx)
    if not def_eq(env, actual, expected):
        raise KernelError(
            f"type mismatch:\n  expected {expected!r}\n  actual   {actual!r}")


def add_decl(env: Environment, decl: Declaration) -> None:
    """Type-check a declaration and add it to the environment.

    This is the trust boundary: every definition, axiom, and theorem enters
    the environment through this function.
    """
    if has_mvar(decl.type) or (decl.value is not None and has_mvar(decl.value)):
        raise KernelError(f"declaration '{decl.name}' contains metavariables")

    ty_sort = infer_type(env, decl.type)
    _ensure_sort(env, ty_sort, f"type of '{decl.name}'")

    if decl.kind in (DeclKind.DEFINITION, DeclKind.THEOREM):
        if decl.value is None:
            raise KernelError(f"'{decl.name}' ({decl.kind.value}) needs a body")
        check_type(env, decl.value, decl.type)
    elif decl.kind in (DeclKind.AXIOM, DeclKind.OPAQUE):
        if decl.value is not None:
            raise KernelError(f"'{decl.name}' ({decl.kind.value}) cannot have a body")
    elif decl.kind in (DeclKind.INDUCTIVE, DeclKind.CONSTRUCTOR, DeclKind.RECURSOR):
        # produced only by inductive.declare_inductive, which constructs
        # these by schema; their types are still checked above
        pass
    else:  # pragma: no cover
        raise KernelError(f"unknown declaration kind {decl.kind}")

    env.add_unchecked(decl)
