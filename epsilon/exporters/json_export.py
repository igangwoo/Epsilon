"""JSON exporter: total, lossless `Term <-> JSON` (product spec section 25 -
the "JSON mathematical representation" interoperability format).

Every kernel term node has exactly one JSON shape, keyed by `"k"`:

    {"k": "var",   "idx": int}
    {"k": "const", "name": str}
    {"k": "sort",  "level": int}
    {"k": "app",   "fn": <term>, "arg": <term>}
    {"k": "lam",   "name": str, "ty": <term>, "body": <term>, "implicit": bool}
    {"k": "pi",    "name": str, "ty": <term>, "body": <term>, "implicit": bool}
    {"k": "lit",   "num": int, "den": int, "ty": "Nat"|"Int"|"Rat"|"Real"}
    {"k": "str",   "v": str}

`Lam` carries no `implicit` flag in the kernel (only `Pi` binders can be
implicit); it is always written `False` there so "lam"/"pi" share one
schema, and `term_from_json` ignores it for "lam". `term_to_json` /
`term_from_json` round-trip every field, including `Pi.implicit` - which
matters here even though the kernel's own `Pi.__eq__` does not compare it
(implicitness is elaboration metadata, irrelevant to definitional
equality of the *type*, but it is exactly the kind of thing a JSON
interoperability format must not silently drop).

`module_to_json` dumps a module's declarations - kinds, types, values,
verification statuses, axiom dependencies, content hashes - as one JSON
object, built from the same `Session` introspection the IDE and CLI use.
Verification-status honesty (section 27): `status`/`status_label` are
only ever populated for THEOREM declarations. An axiom is assumed, not
proven, and a definition is not a truth-claim at all, so both get
`status: null` rather than a label that could be misread as a proof.
"""

from __future__ import annotations

from fractions import Fraction
from typing import Optional

from ..kernel.env import DeclKind, Environment
from ..kernel.term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar,
)
from ..elab.context import LOCAL_MARK
from ..project import STATUS_LABELS


class JsonExportError(Exception):
    """A term/declaration cannot be represented in the JSON schema."""


# ---------------------------------------------------------------------------
# Term <-> JSON
# ---------------------------------------------------------------------------

def term_to_json(t: Term) -> dict:
    """Lossless `Term -> JSON`. Total over every *finished* term (no
    metavariables - those are elaboration-only and the kernel itself
    rejects them; see `MVar`'s docstring)."""
    if isinstance(t, Var):
        return {"k": "var", "idx": t.idx}
    if isinstance(t, Const):
        return {"k": "const", "name": t.name}
    if isinstance(t, Sort):
        return {"k": "sort", "level": t.level}
    if isinstance(t, App):
        return {"k": "app", "fn": term_to_json(t.fn), "arg": term_to_json(t.arg)}
    if isinstance(t, Lam):
        return {"k": "lam", "name": t.name, "ty": term_to_json(t.ty),
                "body": term_to_json(t.body), "implicit": False}
    if isinstance(t, Pi):
        return {"k": "pi", "name": t.name, "ty": term_to_json(t.ty),
                "body": term_to_json(t.body), "implicit": bool(t.implicit)}
    if isinstance(t, Lit):
        return {"k": "lit", "num": t.value.numerator, "den": t.value.denominator,
                "ty": t.tyname}
    if isinstance(t, StrLit):
        return {"k": "str", "v": t.value}
    if isinstance(t, MVar):
        raise JsonExportError(
            f"cannot export a term containing metavariable ?m{t.id} - "
            "metavariables are elaboration-only; call Elaborator.finalize "
            "(or resolve/reject them) before exporting")
    raise JsonExportError(f"unknown term node: {type(t).__name__!r}")


_KIND_ARITY_CHECK = {
    "var": ("idx",), "const": ("name",), "sort": ("level",),
    "app": ("fn", "arg"), "lam": ("name", "ty", "body"),
    "pi": ("name", "ty", "body"), "lit": ("num", "den", "ty"), "str": ("v",),
}


def term_from_json(d: dict) -> Term:
    """Inverse of `term_to_json`. Raises `JsonExportError` on anything that
    is not a well-formed encoding of a `Term` - this never guesses at a
    malformed payload."""
    if not isinstance(d, dict) or "k" not in d:
        raise JsonExportError(f"not a term JSON object: {d!r}")
    k = d["k"]
    required = _KIND_ARITY_CHECK.get(k)
    if required is None:
        raise JsonExportError(f"unknown JSON term kind: {k!r}")
    missing = [f for f in required if f not in d]
    if missing:
        raise JsonExportError(f"{k!r} term JSON is missing field(s) {missing}")

    if k == "var":
        return Var(int(d["idx"]))
    if k == "const":
        return Const(str(d["name"]))
    if k == "sort":
        return Sort(int(d["level"]))
    if k == "app":
        return App(term_from_json(d["fn"]), term_from_json(d["arg"]))
    if k == "lam":
        return Lam(str(d["name"]), term_from_json(d["ty"]), term_from_json(d["body"]))
    if k == "pi":
        return Pi(str(d["name"]), term_from_json(d["ty"]), term_from_json(d["body"]),
                  implicit=bool(d.get("implicit", False)))
    if k == "lit":
        try:
            value = Fraction(int(d["num"]), int(d["den"]))
        except ZeroDivisionError as e:
            raise JsonExportError(f"lit with zero denominator: {d!r}") from e
        return Lit(value, str(d["ty"]))
    if k == "str":
        return StrLit(str(d["v"]))
    raise JsonExportError(f"unknown JSON term kind: {k!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Module -> JSON
# ---------------------------------------------------------------------------

#: declaration kinds worth exporting - constructors/recursors are the
#: auto-generated substructure of an INDUCTIVE decl, already implied by it
#: (mirrors the filtering `Session.dependency_graph` already applies).
_EXPORT_KINDS = (DeclKind.THEOREM, DeclKind.DEFINITION, DeclKind.AXIOM,
                 DeclKind.OPAQUE, DeclKind.INDUCTIVE)


def _decl_to_json(env: Environment, name: str) -> dict:
    d = env.expect(name)
    out: dict = {
        "name": name,
        "kind": d.kind.value,
        "module": d.module,
        "doc": d.doc,
        "type": term_to_json(d.type),
        "value": term_to_json(d.value) if d.value is not None else None,
        "hash": d.hash(),
        "status": None,
        "status_label": None,
        "axioms": [],
    }
    if d.kind == DeclKind.THEOREM:
        status = env.verification_status(name)
        out["status"] = status
        out["status_label"] = STATUS_LABELS[status]
        out["axioms"] = sorted(a for a in env.axioms_of(name)
                               if a not in env.trust_axioms)
    return out


def module_to_json(session, module: Optional[str] = None) -> dict:
    """Dump a module's declarations as one JSON object: kinds, types,
    values (terms as JSON), verification statuses, axiom dependencies,
    and content hashes - the interoperability format other tools (or a
    different Epsilon build) can round-trip through `term_from_json`."""
    from .. import __version__, LANGUAGE_VERSION
    env = session.env
    names = [n for n in env.order
             if env.decls[n].kind in _EXPORT_KINDS
             and env.decls[n].module not in (None,)
             and LOCAL_MARK not in n and not n.startswith("$")
             and (module is None or env.decls[n].module == module)]
    return {
        "epsilon_version": __version__,
        "language_version": LANGUAGE_VERSION,
        "module": module,
        "decls": [_decl_to_json(env, n) for n in names],
    }
