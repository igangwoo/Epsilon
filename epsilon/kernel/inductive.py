"""Inductive type declarations and recursor generation.

Supports parameterized, non-indexed inductive types with a simple strict
positivity check: an inductive `I` may occur in a constructor field only as
exactly `I` applied to the inductive's parameters. (`Eq` is the one indexed
family, hard-coded in `declare_eq`; its iota rule lives in reduce.py.)

For every inductive we generate:
- `I.ind` : eliminator with a Prop-valued motive (used by `induction`/`cases`)
- `I.rec` : eliminator with a Type-valued motive (used for recursion /
            transport), only when large elimination is allowed - i.e. the
            inductive lives in Type, or is a subsingleton Prop (single
            constructor, all fields propositions), per CIC.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .env import Environment, Declaration, DeclKind, InductiveInfo, KernelError
from .term import (
    Term, Var, Const, Sort, App, Lam, Pi, mk_app, unfold_app,
    abstract_const, instantiate, PROP, TYPE,
)


# ---------------------------------------------------------------------------
# Named-placeholder telescope helpers
# ---------------------------------------------------------------------------
# We build binder telescopes using unique placeholder constants ("$name") and
# then abstract them into de Bruijn binders; this is far less error-prone
# than juggling indices by hand.

def ph(name: str) -> Const:
    return Const("$" + name)


def close_pi(binders: list[tuple[str, Term]], body: Term) -> Term:
    """binders outermost-first; types/body may reference ph(name) placeholders."""
    result = body
    for name, ty in reversed(binders):
        result = Pi(name, ty, abstract_const(result, "$" + name))
    return result


def close_lam(binders: list[tuple[str, Term]], body: Term) -> Term:
    result = body
    for name, ty in reversed(binders):
        result = Lam(name, ty, abstract_const(result, "$" + name))
    return result


def open_pi(ty: Term, prefix: str) -> tuple[list[tuple[str, Term]], Term]:
    """Open a Pi telescope, instantiating each binder with a fresh placeholder.
    Returns (binders as [(placeholder_base_name, type)], body)."""
    binders: list[tuple[str, Term]] = []
    i = 0
    while isinstance(ty, Pi):
        name = f"{prefix}{i}"
        binders.append((name, ty.ty))
        ty = instantiate(ty.body, ph(name))
        i += 1
    return binders, ty


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

@dataclass
class ConstructorSpec:
    name: str
    type: Term  # closed Pi-term; first num_params binders are the parameters


@dataclass
class InductiveSpec:
    name: str
    type: Term  # closed; e.g. Type, or Prop -> Prop -> Prop
    num_params: int
    constructors: list[ConstructorSpec] = field(default_factory=list)


def _sort_of_inductive(spec: InductiveSpec) -> int:
    ty = spec.type
    while isinstance(ty, Pi):
        ty = ty.body
    if not isinstance(ty, Sort):
        raise KernelError(f"inductive '{spec.name}' must land in a sort")
    return ty.level


def declare_inductive(env: Environment, spec: InductiveSpec) -> None:
    from .typecheck import add_decl, infer_type  # avoid import cycle

    sort_level = _sort_of_inductive(spec)
    add_decl(env, Declaration(spec.name, DeclKind.INDUCTIVE, spec.type))

    ctor_arg_counts: dict[str, int] = {}
    ctor_recursive_args: dict[str, list[int]] = {}
    all_fields_props = True

    for ctor in spec.constructors:
        binders, body = open_pi(ctor.type, f"a")
        if len(binders) < spec.num_params:
            raise KernelError(f"constructor '{ctor.name}' missing parameters")
        params = binders[:spec.num_params]
        fields = binders[spec.num_params:]

        # the constructor must build exactly `I params`
        bh, bargs = unfold_app(body)
        if not (isinstance(bh, Const) and bh.name == spec.name):
            raise KernelError(f"constructor '{ctor.name}' must construct {spec.name}")
        if bargs != [ph(n) for n, _ in params]:
            raise KernelError(
                f"constructor '{ctor.name}': indexed families are not supported "
                f"(result must be {spec.name} applied to the parameters)")

        rec_idxs: list[int] = []
        for fi, (fname, fty) in enumerate(fields):
            fh, fargs = unfold_app(fty)
            occurs = spec.name in set(_consts_in(fty))
            if isinstance(fh, Const) and fh.name == spec.name:
                if fargs != [ph(n) for n, _ in params]:
                    raise KernelError(
                        f"constructor '{ctor.name}': recursive field must be "
                        f"{spec.name} applied to the parameters")
                rec_idxs.append(fi)
            elif occurs:
                raise KernelError(
                    f"constructor '{ctor.name}': non-positive occurrence of "
                    f"{spec.name} in field '{fname}'")
            else:
                # subsingleton criterion needs field types that are Props
                try:
                    fsort = infer_type(env, _close_placeholder_ctx(
                        params + fields[:fi], fty))
                    if not _lands_in_prop(fsort):
                        all_fields_props = False
                except KernelError:
                    all_fields_props = False

        ctor_arg_counts[ctor.name] = len(fields)
        ctor_recursive_args[ctor.name] = rec_idxs
        add_decl(env, Declaration(ctor.name, DeclKind.CONSTRUCTOR, ctor.type,
                                  inductive=spec.name))

    allow_large = (sort_level >= 1) or (
        len(spec.constructors) <= 1 and all_fields_props and not ctor_recursive_args.get(
            spec.constructors[0].name if spec.constructors else "", []))

    recursors: list[str] = []
    for suffix, motive_sort in (("ind", PROP), ("rec", TYPE)):
        if suffix == "rec" and not allow_large:
            continue
        rec_name = f"{spec.name}.{suffix}"
        rec_ty = _recursor_type(env, spec, motive_sort)
        add_decl(env, Declaration(rec_name, DeclKind.RECURSOR, rec_ty,
                                  inductive=spec.name, reducible=False))
        recursors.append(rec_name)
        env.recursor_of[rec_name] = spec.name

    info = InductiveInfo(
        name=spec.name,
        num_params=spec.num_params,
        constructors=[c.name for c in spec.constructors],
        recursors=recursors,
        sort_level=sort_level,
        allow_large_elim=allow_large,
        ctor_arg_counts=ctor_arg_counts,
        ctor_recursive_args=ctor_recursive_args,
    )
    env.inductives[spec.name] = info
    for c in spec.constructors:
        env.ctor_of[c.name] = spec.name


def _consts_in(t: Term):
    from .term import constants_of
    return constants_of(t)


def _close_placeholder_ctx(binders: list[tuple[str, Term]], t: Term) -> Term:
    """Close over placeholder binders with Pi so the term is closed for
    type-inference purposes."""
    return close_pi(list(binders), t)


def _lands_in_prop(sort_ty: Term) -> bool:
    # after closing with close_pi, the sort of the closed Pi obeys imax;
    # it is Prop iff the innermost codomain was a Prop
    return isinstance(sort_ty, Sort) and sort_ty.level == 0


def _recursor_type(env: Environment, spec: InductiveSpec, motive_sort: Sort) -> Term:
    # open the inductive's own telescope to get parameter binders
    param_binders, _ = open_pi(spec.type, "P")
    param_binders = param_binders[:spec.num_params]
    if len(param_binders) < spec.num_params:
        raise KernelError(f"inductive '{spec.name}': malformed parameter telescope")
    param_phs = [ph(n) for n, _ in param_binders]
    I_applied = mk_app(Const(spec.name), *param_phs)

    motive_ty = Pi("t", I_applied, motive_sort)

    binders: list[tuple[str, Term]] = list(param_binders)
    binders.append(("motive", motive_ty))

    for ci, ctor in enumerate(spec.constructors):
        cbinders, _ = open_pi(ctor.type, f"c{ci}f")
        cparams = cbinders[:spec.num_params]
        cfields = cbinders[spec.num_params:]
        # rename constructor's own parameter placeholders to the shared ones
        ren = {"$" + old: new for (old, _), new in zip(cparams, param_phs)}
        case_binders: list[tuple[str, Term]] = []
        rec_idxs = []
        for fi, (fname, fty) in enumerate(cfields):
            fty2 = _rename_phs(fty, ren)
            case_binders.append((fname, fty2))
            fh, fargs = unfold_app(fty2)
            if isinstance(fh, Const) and fh.name == spec.name:
                rec_idxs.append(fi)
                case_binders.append(
                    (fname + "_ih", App(ph("motive"), ph(fname))))
        built = mk_app(Const(ctor.name), *param_phs,
                       *[ph(n) for n, _ in cfields])
        case_ty = close_pi(case_binders, App(ph("motive"), built))
        binders.append((f"case_{ctor.name.split('.')[-1]}", case_ty))

    binders.append(("t", I_applied))
    return close_pi(binders, App(ph("motive"), ph("t")))


def _rename_phs(t: Term, ren: dict[str, Term]) -> Term:
    if isinstance(t, Const) and t.name in ren:
        return ren[t.name]
    if isinstance(t, App):
        return App(_rename_phs(t.fn, ren), _rename_phs(t.arg, ren))
    if isinstance(t, Lam):
        return Lam(t.name, _rename_phs(t.ty, ren), _rename_phs(t.body, ren))
    if isinstance(t, Pi):
        return Pi(t.name, _rename_phs(t.ty, ren), _rename_phs(t.body, ren), t.implicit)
    return t


# ---------------------------------------------------------------------------
# Eq: the one hard-coded indexed family
# ---------------------------------------------------------------------------

def declare_eq(env: Environment) -> None:
    from .typecheck import add_decl

    A, a = ph("A"), ph("a")
    # Eq : Π (A : Type), A → A → Prop
    eq_ty = close_pi([("A", TYPE), ("a", A), ("b", A)], PROP)
    add_decl(env, Declaration("Eq", DeclKind.INDUCTIVE, eq_ty))

    refl_ty = close_pi([("A", TYPE), ("a", A)], mk_app(Const("Eq"), A, a, a))
    add_decl(env, Declaration("Eq.refl", DeclKind.CONSTRUCTOR, refl_ty,
                              inductive="Eq"))

    recursors = []
    for suffix, motive_sort in (("ind", PROP), ("rec", TYPE)):
        motive_ty = close_pi(
            [("b", A), ("h", mk_app(Const("Eq"), A, a, ph("b")))], motive_sort)
        rec_ty = close_pi(
            [("A", TYPE), ("a", A), ("motive", motive_ty),
             ("m", mk_app(ph("motive"), a, mk_app(Const("Eq.refl"), A, a))),
             ("b", A), ("h", mk_app(Const("Eq"), A, a, ph("b")))],
            mk_app(ph("motive"), ph("b"), ph("h")))
        name = f"Eq.{suffix}"
        add_decl(env, Declaration(name, DeclKind.RECURSOR, rec_ty,
                                  inductive="Eq", reducible=False))
        env.recursor_of[name] = "Eq"
        recursors.append(name)

    env.inductives["Eq"] = InductiveInfo(
        name="Eq", num_params=2, constructors=["Eq.refl"], recursors=recursors,
        sort_level=0, allow_large_elim=True,
        ctor_arg_counts={"Eq.refl": 0}, ctor_recursive_args={"Eq.refl": []})
    env.ctor_of["Eq.refl"] = "Eq"
