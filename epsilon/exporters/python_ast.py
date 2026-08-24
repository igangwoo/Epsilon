"""Python code generation via the `ast` module (product spec section 18).

HARD REQUIREMENT (from the spec): generation goes
    kernel Term  ->  Python `ast` nodes  ->  ast.unparse
No string templating of code fragments. Everything below builds real
`ast.AST` objects; only docstring/comment *content* is string data.

Backends:
- "math"   : pure-stdlib `math` (default)
- "numpy"  : `numpy as np`
- "sympy"  : `sympy as sp`, with exact `sp.Rational` literals

Definitions whose type is numeric-valued become Python `def`s (function
types) or assignments (scalars). Propositions and proofs are not executable
and are emitted only as commented statements carrying their verification
status - never as if they were computable claims (the honesty rule).
"""

from __future__ import annotations

import ast
from fractions import Fraction
from typing import Optional

from ..kernel.env import Environment, DeclKind
from ..kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit,
                           unfold_app, instantiate)
from ..elab.context import LOCAL_MARK

# Epsilon function const -> (module attribute) per backend
_FUNCS = {
    "Real.sin": "sin", "Real.cos": "cos", "Real.tan": "tan",
    "Real.asin": "asin", "Real.acos": "acos", "Real.atan": "atan",
    "Real.sinh": "sinh", "Real.cosh": "cosh", "Real.tanh": "tanh",
    "Real.exp": "exp", "Real.log": "log", "Real.sqrt": "sqrt",
}
_ABS = {"Real.abs", "Int.natAbs", "Complex.abs"}
_CONSTS = {"Real.pi": "pi", "Real.euler": "e"}

_BINOP = {"add": ast.Add, "sub": ast.Sub, "mul": ast.Mult,
          "div": ast.Div, "mod": ast.Mod, "pow": ast.Pow}
_CMP = {"beq": ast.Eq, "ble": ast.LtE, "blt": ast.Lt,
        "le": ast.LtE, "lt": ast.Lt}

_COERCIONS = {"Int.ofNat", "Rat.ofNat", "Rat.ofInt", "Real.ofNat",
              "Real.ofInt", "Real.ofRat", "Complex.ofReal"}


class PyCodegenError(Exception):
    pass


class _Ctx:
    def __init__(self, env: Environment, backend: str) -> None:
        self.env = env
        self.backend = backend
        self.binders: list[str] = []      # de Bruijn -> python arg name
        self.used_math = False
        self.used_rational = False

    def module_name(self) -> str:
        return {"math": "math", "numpy": "np", "sympy": "sp"}[self.backend]


def term_to_python_ast(env: Environment, t: Term, backend: str = "math",
                       ctx: Optional[_Ctx] = None) -> ast.expr:
    ctx = ctx or _Ctx(env, backend)
    return _expr(ctx, t)


def _num_const(ctx: _Ctx, value: Fraction) -> ast.expr:
    if value.denominator == 1:
        return ast.Constant(int(value.numerator))
    if ctx.backend == "sympy":
        ctx.used_rational = True
        return ast.Call(
            func=ast.Attribute(value=ast.Name(id="sp", ctx=ast.Load()),
                               attr="Rational", ctx=ast.Load()),
            args=[ast.Constant(int(value.numerator)),
                  ast.Constant(int(value.denominator))], keywords=[])
    # math / numpy: use a float division to stay exact-ish and readable
    return ast.BinOp(left=ast.Constant(int(value.numerator)), op=ast.Div(),
                     right=ast.Constant(int(value.denominator)))


def _mod_attr(ctx: _Ctx, attr: str) -> ast.expr:
    ctx.used_math = True
    return ast.Attribute(value=ast.Name(id=ctx.module_name(), ctx=ast.Load()),
                         attr=attr, ctx=ast.Load())


def _expr(ctx: _Ctx, t: Term) -> ast.expr:
    if isinstance(t, Lit):
        return _num_const(ctx, t.value)
    if isinstance(t, StrLit):
        return ast.Constant(t.value)
    if isinstance(t, Var):
        if t.idx < len(ctx.binders):
            return ast.Name(id=ctx.binders[-(t.idx + 1)] if False
                            else ctx.binders[len(ctx.binders) - 1 - t.idx],
                            ctx=ast.Load())
        raise PyCodegenError(f"unbound variable #{t.idx}")
    if isinstance(t, Const):
        return _const(ctx, t.name)
    if isinstance(t, Lam):
        return _lambda(ctx, t)
    if isinstance(t, App):
        return _app(ctx, t)
    if isinstance(t, (Pi, Sort)):
        raise PyCodegenError("types/props are not executable Python")
    raise PyCodegenError(f"cannot generate Python for {type(t).__name__}")


def _const(ctx: _Ctx, name: str) -> ast.expr:
    if name in _CONSTS:
        return _mod_attr(ctx, _CONSTS[name])
    if name in ("Nat.zero",):
        return ast.Constant(0)
    if name == "Bool.true":
        return ast.Constant(True)
    if name == "Bool.false":
        return ast.Constant(False)
    if name in _FUNCS or name in _ABS:
        # bare function reference
        return _mod_attr(ctx, _FUNCS.get(name, "fabs"))
    # reference to another Epsilon definition -> a Python name
    return ast.Name(id=_py_name(name), ctx=ast.Load())


def _py_name(name: str) -> str:
    return name.replace(".", "_").replace(LOCAL_MARK, "_")


def _lambda(ctx: _Ctx, t: Lam) -> ast.expr:
    argname = _fresh_arg(ctx, t.name)
    ctx.binders.append(argname)
    try:
        body = _expr(ctx, t.body)
    finally:
        ctx.binders.pop()
    return ast.Lambda(
        args=ast.arguments(posonlyargs=[], args=[ast.arg(arg=argname)],
                           vararg=None, kwonlyargs=[], kw_defaults=[],
                           kwarg=None, defaults=[]),
        body=body)


def _fresh_arg(ctx: _Ctx, hint: str) -> str:
    base = (hint or "x").split(LOCAL_MARK)[0]
    if base in ("_", ""):
        base = "x"
    name = base
    i = 1
    while name in ctx.binders:
        name = f"{base}{i}"
        i += 1
    return name


def _app(ctx: _Ctx, t: App) -> ast.expr:
    head, args = unfold_app(t)
    if isinstance(head, Const):
        name = head.name
        suffix = name.rsplit(".", 1)[-1]
        prefix = name.rsplit(".", 1)[0]

        if name in _COERCIONS and len(args) == 1:
            return _expr(ctx, args[0])
        if name in _FUNCS and len(args) == 1:
            return ast.Call(func=_mod_attr(ctx, _FUNCS[name]),
                            args=[_expr(ctx, args[0])], keywords=[])
        if name in _ABS and len(args) == 1:
            return ast.Call(func=ast.Name(id="abs", ctx=ast.Load()),
                            args=[_expr(ctx, args[0])], keywords=[])
        if prefix in ("Nat", "Int", "Rat", "Real", "Complex"):
            if suffix in _BINOP and len(args) == 2:
                op = _BINOP[suffix]()
                left, right = _expr(ctx, args[0]), _expr(ctx, args[1])
                if suffix == "div" and prefix in ("Nat", "Int"):
                    op = ast.FloorDiv()
                return ast.BinOp(left=left, op=op, right=right)
            if suffix == "neg" and len(args) == 1:
                return ast.UnaryOp(op=ast.USub(), operand=_expr(ctx, args[0]))
            if suffix == "inv" and len(args) == 1:
                return ast.BinOp(left=ast.Constant(1), op=ast.Div(),
                                 right=_expr(ctx, args[0]))
            if suffix in _CMP and len(args) == 2:
                return ast.Compare(left=_expr(ctx, args[0]),
                                   ops=[_CMP[suffix]()],
                                   comparators=[_expr(ctx, args[1])])
        if name == "ite" and len(args) == 4:
            return ast.IfExp(test=_expr(ctx, args[1]),
                             body=_expr(ctx, args[2]),
                             orelse=_expr(ctx, args[3]))
        if name == "Nat.succ" and len(args) == 1:
            return ast.BinOp(left=_expr(ctx, args[0]), op=ast.Add(),
                             right=ast.Constant(1))

    func = _expr(ctx, head)
    return ast.Call(func=func, args=[_expr(ctx, a) for a in args], keywords=[])


# ---------------------------------------------------------------------------
# Whole-module generation
# ---------------------------------------------------------------------------

def _is_numeric_type(env: Environment, ty: Term) -> bool:
    """True when ty is a numeric scalar or an arrow chain ending in one."""
    t = ty
    while isinstance(t, Pi):
        t = t.body
    head, _ = unfold_app(t)
    return isinstance(head, Const) and head.name in (
        "Nat", "Int", "Rat", "Real", "Complex", "Bool")


def _def_statement(ctx: _Ctx, name: str, decl) -> Optional[ast.stmt]:
    """Build a `def` (function) or assignment (scalar) for one definition."""
    if decl.value is None:
        return None
    ty = decl.type
    # collect leading Pi binders as function parameters
    params: list[str] = []
    value = decl.value
    while isinstance(value, Lam):
        params.append(_fresh_arg_static(params, value.name))
        value = value.body
    pyname = _py_name(name)

    saved = ctx.binders
    ctx.binders = list(params)
    try:
        body_expr = _expr(ctx, value)
    finally:
        ctx.binders = saved

    if params:
        return ast.FunctionDef(
            name=pyname,
            args=ast.arguments(posonlyargs=[],
                               args=[ast.arg(arg=p) for p in params],
                               vararg=None, kwonlyargs=[], kw_defaults=[],
                               kwarg=None, defaults=[]),
            body=[ast.Return(value=body_expr)],
            decorator_list=[], returns=None)
    return ast.Assign(targets=[ast.Name(id=pyname, ctx=ast.Store())],
                      value=body_expr)


def _fresh_arg_static(existing: list[str], hint: str) -> str:
    base = (hint or "x").split(LOCAL_MARK)[0]
    if base in ("_", ""):
        base = "x"
    name = base
    i = 1
    while name in existing:
        name = f"{base}{i}"
        i += 1
    return name


def module_to_python(session, module: Optional[str] = None,
                     backend: str = "math") -> str:
    """Render a module's numeric definitions as an importable Python file."""
    from .. import __version__
    from ..project import STATUS_LABELS
    env = session.env
    ctx = _Ctx(env, backend)

    body: list[ast.stmt] = []
    comments: list[str] = []  # collected theorem status lines (as module doc)

    for name in env.order:
        decl = env.decls[name]
        if decl.module in (None, "core", "plugin"):
            continue
        if module is not None and decl.module != module:
            continue
        if LOCAL_MARK in name or name.startswith("$"):
            continue
        if decl.kind == DeclKind.THEOREM:
            status = env.verification_status(name)
            comments.append(f"{name}: {STATUS_LABELS[status]}")
            continue
        if decl.kind == DeclKind.DEFINITION and _is_numeric_type(env, decl.type):
            try:
                stmt = _def_statement(ctx, name, decl)
                if stmt is not None:
                    body.append(stmt)
            except PyCodegenError:
                continue

    # module docstring
    doc_lines = [f"Generated by Epsilon {__version__} ({backend} backend).",
                 f"Source module: {module or '<all>'}.", ""]
    if comments:
        doc_lines.append("Theorems in this module (NOT executable; status "
                         "shown for reference):")
        doc_lines.extend(f"  - {c}" for c in comments)
    docstring = ast.Expr(value=ast.Constant("\n".join(doc_lines)))

    imports: list[ast.stmt] = []
    if backend == "math" and ctx.used_math:
        imports.append(ast.Import(names=[ast.alias(name="math")]))
    elif backend == "numpy":
        imports.append(ast.Import(names=[ast.alias(name="numpy", asname="np")]))
    elif backend == "sympy":
        imports.append(ast.Import(names=[ast.alias(name="sympy", asname="sp")]))

    module_ast = ast.Module(body=[docstring] + imports + body, type_ignores=[])
    ast.fix_missing_locations(module_ast)
    return ast.unparse(module_ast) + "\n"
