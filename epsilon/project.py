"""The Epsilon session: one shared pipeline for everything.

CLI `epsilon check`, the REPL, the web IDE, and exporters all drive this
module. It owns: the kernel environment, the standard-library loader,
import resolution, per-command error recovery, verification statuses, and
the dependency graph (section 36: one common mathematical object model).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import LANGUAGE_VERSION, __version__
from .kernel.bootstrap import bootstrap
from .kernel.env import Environment, DeclKind, KernelError
from .kernel.term import Term, App, Const
from .syntax import sast as S
from .syntax.lexer import LexError
from .syntax.parser import Parser, ParseError
from .elab.commands import CommandProcessor
from .elab.context import ElabContext, ElabError, LOCAL_MARK
from .elab.elaborator import CmdResult
from .elab.tactics import TacticError

LIB_DIR = os.path.join(os.path.dirname(__file__), "lib")

STATUS_LABELS = {
    "proven": "✓ Formally Proven",
    "symbolic": "✓ Symbolically Verified",
    "numeric": "≈ Numerically Verified",
    "heuristic": "⚠ Heuristic Result",
}


@dataclass
class Diagnostic:
    severity: str          # "error" | "warning" | "info"
    message: str
    span: S.Span = (0, 0, 0, 0)
    module: str = "<main>"

    def format(self) -> str:
        l0, c0, _, _ = self.span
        loc = f"{self.module}:{l0}:{c0}" if l0 else self.module
        return f"{loc}: {self.severity}: {self.message}"


@dataclass
class CheckResult:
    module: str
    results: list[CmdResult] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def _default_oracles() -> dict[str, Callable]:
    oracles: dict[str, Callable] = {}
    try:
        from .cas.oracle import cas_oracle
        oracles["cas"] = cas_oracle
    except ImportError:
        pass
    try:
        from .numeric.oracle import numeric_oracle
        oracles["numeric"] = numeric_oracle
    except ImportError:
        pass
    return oracles


class Session:
    """A persistent Epsilon session (environment + notation + modules)."""

    def __init__(self, project_root: Optional[str] = None,
                 load_prelude: bool = True) -> None:
        self.env: Environment = bootstrap()
        self.ctx = ElabContext(self.env)
        self.project_root = project_root or os.getcwd()
        self.loaded_modules: set[str] = set()
        self.extra_ops: dict[str, tuple[str, int, str]] = {}
        self.oracles = _default_oracles()
        self.plots: list[dict] = []
        self.traces: dict[str, object] = {}   # theorem name -> proof trace
        if load_prelude:
            self.import_module("prelude")

    # ------------------------------------------------------------------
    # Parsing / checking
    # ------------------------------------------------------------------
    def parse(self, src: str) -> S.CModule:
        parser = Parser(src, extra_ops=dict(self.extra_ops))
        module = parser.parse_module()
        return module

    def check_source(self, src: str, module_name: str = "<main>") -> CheckResult:
        out = CheckResult(module=module_name)
        try:
            module = self.parse(src)
        except (ParseError, LexError) as e:
            line = getattr(e, "line", 0)
            col = getattr(e, "col", 0)
            out.diagnostics.append(Diagnostic(
                "error", getattr(e, "msg", str(e)), (line, col, line, col),
                module_name))
            return out
        proc = CommandProcessor(self.env, self.ctx, oracles=self.oracles,
                                module=module_name)
        for cmd in module.commands:
            self._run_command(proc, cmd, out)
        return out

    def _run_command(self, proc: CommandProcessor, cmd: S.Command,
                     out: CheckResult) -> None:
        if isinstance(cmd, S.CImport):
            try:
                self.import_module(cmd.module)
                out.results.append(CmdResult("import", name=cmd.module,
                                             span=cmd.span))
            except Exception as e:  # noqa: BLE001 - surface as diagnostic
                out.diagnostics.append(Diagnostic(
                    "error", f"import {cmd.module}: {e}", cmd.span, out.module))
            return
        if isinstance(cmd, S.CNotation):
            self.extra_ops[cmd.symbol] = (cmd.fixity, cmd.precedence, cmd.target)
        try:
            results = proc.process(cmd)
            out.results.extend(results)
            for r in results:
                if r.kind == "plot":
                    self.plots.append({"module": out.module, **r.extra,
                                       "span": r.span})
                if r.kind == "theorem" and r.trace is not None and r.name:
                    self.traces[r.name] = r.trace
        except (ElabError, TacticError) as e:
            span = getattr(e, "span", None) or cmd.span
            out.diagnostics.append(Diagnostic("error", str(e), span, out.module))
            self._recover(cmd, out.module)
        except KernelError as e:
            out.diagnostics.append(Diagnostic(
                "error", f"kernel rejected declaration: {e}", cmd.span,
                out.module))
            self._recover(cmd, out.module)
        finally:
            self.ctx.pop_locals_to(0)
            self.ctx.sweep_stray_locals()

    def _recover(self, cmd: S.Command, module: str) -> None:
        """After a failed theorem, declare it via `sorry` so later commands
        can still refer to it - honestly labeled Heuristic."""
        if not isinstance(cmd, S.CTheorem) or not cmd.name:
            return
        try:
            from .kernel.env import Declaration, SORRY_AXIOM
            from .kernel.typecheck import add_decl
            proc = CommandProcessor(self.env, self.ctx, module=module)
            base = len(self.ctx.locals)
            lf = proc.elab.elab_command_binders(cmd.binders)
            try:
                stmt = proc.elab.elab_prop(cmd.statement)
                stmt = proc.elab.finalize(stmt, cmd.span)
                closed = proc.elab.close_over(lf, stmt, as_pi=True)
            finally:
                self.ctx.pop_locals_to(base)
            name = self.ctx.qualify(cmd.name)
            if self.env.contains(name):
                return
            # Π-statements need the sorry applied under binders: wrap each
            # binder with a Lam and apply the sorry axiom to the body
            from .kernel.term import Pi, Lam
            def wrap(t: Term, depth: int = 0) -> Term:
                if isinstance(t, Pi):
                    return Lam(t.name, t.ty, wrap(t.body, depth + 1))
                return App(Const(SORRY_AXIOM), t)
            add_decl(self.env, Declaration(
                name, DeclKind.THEOREM, closed, value=wrap(closed),
                module=module, span=cmd.span, statement_kind=cmd.kind,
                reducible=False))
        except Exception:  # noqa: BLE001 - recovery is best-effort
            pass
        finally:
            self.ctx.pop_locals_to(0)
            self.ctx.sweep_stray_locals()

    # ------------------------------------------------------------------
    # Imports
    # ------------------------------------------------------------------
    #: standard-library module names always resolve to LIB_DIR, so a user
    #: file that happens to be called analysis.epsl cannot shadow the
    #: library module the prelude imports.
    STDLIB_MODULES = frozenset({"prelude", "algebra", "analysis", "sets"})

    def resolve_module_path(self, name: str) -> Optional[str]:
        rel = name.replace(".", os.sep) + ".epsl"
        # library modules first for stdlib names, project first otherwise
        roots = ((LIB_DIR, self.project_root)
                 if name in self.STDLIB_MODULES
                 else (self.project_root, LIB_DIR))
        for root in roots:
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path
        return None

    def import_module(self, name: str) -> None:
        if name in self.loaded_modules:
            return
        path = self.resolve_module_path(name)
        if path is None:
            raise ElabError(f"module '{name}' not found "
                            f"(searched project and standard library)")
        self.loaded_modules.add(name)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        result = self.check_source(src, module_name=name)
        errors = [d for d in result.diagnostics if d.severity == "error"]
        if errors:
            raise ElabError(
                f"module '{name}' has errors: {errors[0].format()}")

    # ------------------------------------------------------------------
    # Introspection for IDE / server / docs
    # ------------------------------------------------------------------
    def theorem_list(self, module: Optional[str] = None) -> list[dict]:
        out = []
        for name in self.env.order:
            d = self.env.decls[name]
            if d.kind != DeclKind.THEOREM:
                continue
            if module is not None and d.module != module:
                continue
            status = self.env.verification_status(name)
            axioms = sorted(a for a in self.env.axioms_of(name)
                            if a not in self.env.trust_axioms)
            from .elab.pp import pp
            out.append({
                "name": name,
                "kind": d.statement_kind or "theorem",
                "statement": pp(self.env, d.type),
                "status": status,
                "status_label": STATUS_LABELS[status],
                "axioms": axioms,
                "module": d.module,
                "span": d.span,
                "doc": d.doc,
                "hash": d.hash(),
            })
        return out

    def definition_list(self, module: Optional[str] = None) -> list[dict]:
        from .elab.pp import pp
        out = []
        for name in self.env.order:
            d = self.env.decls[name]
            if d.kind not in (DeclKind.DEFINITION, DeclKind.OPAQUE,
                              DeclKind.AXIOM, DeclKind.INDUCTIVE):
                continue
            if module is not None and d.module != module:
                continue
            if LOCAL_MARK in name or name.startswith("$"):
                continue
            out.append({
                "name": name, "kind": d.kind.value,
                "type": pp(self.env, d.type),
                "module": d.module, "doc": d.doc, "span": d.span,
            })
        return out

    def dependency_graph(self, roots: Optional[list[str]] = None,
                         include_lib: bool = True) -> dict:
        """DAG of declaration dependencies (theorem -> lemma -> ... -> axiom)."""
        nodes: dict[str, dict] = {}
        edges: list[tuple[str, str]] = []
        names = roots if roots is not None else [
            n for n in self.env.order
            if self.env.decls[n].kind in (DeclKind.THEOREM, DeclKind.AXIOM,
                                          DeclKind.DEFINITION)
            and self.env.decls[n].module not in (None, "core")
        ]
        seen: set[str] = set()
        stack = list(names)
        while stack:
            n = stack.pop()
            if n in seen or LOCAL_MARK in n:
                continue
            seen.add(n)
            d = self.env.decls.get(n)
            if d is None:
                continue
            if not include_lib and d.module == "core":
                continue
            status = (self.env.verification_status(n)
                      if d.kind == DeclKind.THEOREM else None)
            nodes[n] = {"name": n, "kind": d.kind.value, "module": d.module,
                        "status": status}
            for dep in sorted(self.env.direct_deps_of(n)):
                dd = self.env.decls.get(dep)
                if dd is None or LOCAL_MARK in dep:
                    continue
                if dd.kind not in (DeclKind.THEOREM, DeclKind.AXIOM,
                                   DeclKind.DEFINITION, DeclKind.INDUCTIVE):
                    continue
                # kernel-core plumbing (Nat, Eq, Nat.add, ...) would swamp
                # the graph; keep core axioms, since those carry trust
                if dd.module == "core" and dd.kind != DeclKind.AXIOM:
                    continue
                edges.append((n, dep))
                stack.append(dep)
        edges = [e for e in edges if e[0] in nodes or e[0] in seen]
        return {"nodes": list(nodes.values()),
                "edges": [{"from": a, "to": b} for a, b in edges
                          if a in nodes and b in nodes]}

    def reproducibility_info(self) -> dict:
        return {
            "epsilon_version": __version__,
            "language_version": LANGUAGE_VERSION,
            "modules": sorted(self.loaded_modules),
            "theorems": {t["name"]: {"hash": t["hash"], "status": t["status"]}
                         for t in self.theorem_list()},
        }
