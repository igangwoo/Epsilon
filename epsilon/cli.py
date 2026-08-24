"""The Epsilon command-line interface.

    epsilon <command> [args]     (also available as `3psilon`)

Commands: new, check, build, run, test, fmt, lint, repl, prove, graph,
export, docs, serve, version. See `docs/CONTRACTS.md` for the full contract.
Every command drives the one shared `epsilon.project.Session` pipeline.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
from typing import Optional

from . import __version__, LANGUAGE_VERSION, BRAND
from .project import Session, STATUS_LABELS, Diagnostic


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _find_manifest(start: str) -> Optional[str]:
    d = os.path.abspath(start)
    while True:
        cand = os.path.join(d, "epsilon.toml")
        if os.path.isfile(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _project_sources(paths: list[str]) -> list[str]:
    """Resolve the source files to act on."""
    if paths:
        out: list[str] = []
        for p in paths:
            if os.path.isdir(p):
                out.extend(sorted(glob.glob(os.path.join(p, "**", "*.epsl"),
                                            recursive=True)))
            else:
                out.append(p)
        return out
    manifest = _find_manifest(os.getcwd())
    if manifest:
        root = os.path.dirname(manifest)
        src = os.path.join(root, "src")
        base = src if os.path.isdir(src) else root
        return sorted(glob.glob(os.path.join(base, "**", "*.epsl"),
                                recursive=True))
    return sorted(glob.glob("*.epsl"))


def _make_session(paths: list[str]) -> Session:
    manifest = _find_manifest(os.getcwd())
    root = os.path.dirname(manifest) if manifest else os.getcwd()
    return Session(project_root=root)


def _print_diagnostics(diags: list[Diagnostic]) -> int:
    errors = 0
    for d in diags:
        stream = sys.stderr if d.severity == "error" else sys.stdout
        print(d.format(), file=stream)
        if d.severity == "error":
            errors += 1
    return errors


def _check_files(session: Session, files: list[str]) -> tuple[int, dict]:
    """Check each file; return (error_count, {file: CheckResult})."""
    total_errors = 0
    results = {}
    for f in files:
        if not os.path.isfile(f):
            print(f"error: no such file: {f}", file=sys.stderr)
            total_errors += 1
            continue
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        module = os.path.splitext(os.path.basename(f))[0]
        res = session.check_source(src, module)
        results[f] = res
        total_errors += _print_diagnostics(res.diagnostics)
    return total_errors, results


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_version(args) -> int:
    print(f"{BRAND} {__version__} (language {LANGUAGE_VERSION})")
    return 0


def cmd_check(args) -> int:
    files = _project_sources(args.paths)
    if not files:
        print("no .epsl files found", file=sys.stderr)
        return 1
    session = _make_session(files)
    errors, results = _check_files(session, files)
    n_thm = len(session.theorem_list())
    counts = _status_counts(session)
    print(f"\n{'✓' if errors == 0 else '✗'} checked {len(files)} file(s), "
          f"{n_thm} theorem(s): {_format_counts(counts)}")
    if errors:
        print(f"{errors} error(s)", file=sys.stderr)
    return 1 if errors else 0


def cmd_prove(args) -> int:
    files = _project_sources(args.paths)
    session = _make_session(files)
    errors, _ = _check_files(session, files)
    print()
    for t in session.theorem_list():
        if args.module and t["module"] != args.module:
            continue
        label = t["status_label"]
        print(f"{label}  {t['name']}")
        print(f"    {t['statement']}")
        if t["axioms"]:
            print(f"    depends on axioms: {', '.join(t['axioms'])}")
    print(f"\n{_format_counts(_status_counts(session))}")
    return 1 if errors else 0


def cmd_run(args) -> int:
    files = _project_sources(args.paths)
    session = _make_session(files)
    errors = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        module = os.path.splitext(os.path.basename(f))[0]
        res = session.check_source(src, module)
        errors += _print_diagnostics(res.diagnostics)
        for r in res.results:
            if r.kind in ("eval", "check"):
                print(f"  {r.message}")
    # write plots as SVG
    if session.plots:
        try:
            from .graphing import plot_spec
            from .graphing.svg import render_svg
            for i, entry in enumerate(session.plots):
                spec = plot_spec(session.env, entry)
                out = f"plot_{entry.get('module', 'main')}_{i}.svg"
                with open(out, "w", encoding="utf-8") as fh:
                    fh.write(render_svg(spec))
                print(f"  wrote {out}")
        except ImportError:
            print("  (graphing backend unavailable; skipped plot rendering)")
    return 1 if errors else 0


def cmd_test(args) -> int:
    """Run test files: any .epsl under tests/ (or given), all must check."""
    paths = args.paths or (["tests"] if os.path.isdir("tests") else [])
    files = _project_sources(paths)
    if not files:
        print("no test files found", file=sys.stderr)
        return 1
    failed = 0
    for f in files:
        session = Session()
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        module = os.path.splitext(os.path.basename(f))[0]
        res = session.check_source(src, module)
        if res.ok:
            print(f"  ok   {f}")
        else:
            failed += 1
            print(f"  FAIL {f}")
            _print_diagnostics([d for d in res.diagnostics
                                if d.severity == "error"])
    print(f"\n{len(files) - failed}/{len(files)} passed")
    return 1 if failed else 0


def cmd_fmt(args) -> int:
    files = _project_sources(args.paths)
    changed = 0
    for f in files:
        with open(f, encoding="utf-8") as fh:
            src = fh.read()
        formatted = _format_source(src)
        if formatted != src:
            changed += 1
            if args.check:
                print(f"  would reformat {f}")
            else:
                with open(f, "w", encoding="utf-8") as fh:
                    fh.write(formatted)
                print(f"  reformatted {f}")
    if not changed:
        print("all files already formatted")
    return (1 if changed and args.check else 0)


def _format_source(src: str) -> str:
    lines = [line.rstrip() for line in src.split("\n")]
    text = "\n".join(lines)
    if not text.endswith("\n"):
        text += "\n"
    return text


def cmd_lint(args) -> int:
    args.check = True
    return cmd_fmt(args)


def cmd_export(args) -> int:
    files = _project_sources(args.paths)
    session = _make_session(files)
    _check_files(session, files)
    fmt = args.format
    module = None
    if len(files) == 1:
        module = os.path.splitext(os.path.basename(files[0]))[0]
    try:
        content = _run_export(session, fmt, module)
    except ImportError as e:
        print(f"error: exporter '{fmt}' unavailable: {e}", file=sys.stderr)
        return 1
    except Exception as e:  # noqa: BLE001
        print(f"error: export failed: {e}", file=sys.stderr)
        return 1
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(content)
        print(f"wrote {args.output}")
    else:
        print(content)
    return 0


def _run_export(session: Session, fmt: str, module: Optional[str]) -> str:
    if fmt == "latex":
        from .exporters.latex import module_to_latex
        return module_to_latex(session, module)
    if fmt == "markdown":
        from .exporters.markdown import module_to_markdown
        return module_to_markdown(session, module)
    if fmt == "json":
        import json
        from .exporters.json_export import module_to_json
        return json.dumps(module_to_json(session, module), indent=2)
    if fmt == "mathml":
        from .exporters.mathml import term_to_mathml
        parts = []
        for t in session.theorem_list(module):
            d = session.env.expect(t["name"])
            parts.append(term_to_mathml(session.env, d.type))
        return "\n".join(parts)
    if fmt in ("python", "python-numpy", "python-sympy"):
        from .exporters.python_ast import module_to_python
        backend = {"python": "math", "python-numpy": "numpy",
                   "python-sympy": "sympy"}[fmt]
        return module_to_python(session, module, backend=backend)
    if fmt == "lean":
        from .interop.lean import module_to_lean
        return module_to_lean(session, module)
    raise ValueError(f"unknown export format: {fmt}")


def cmd_docs(args) -> int:
    files = _project_sources(args.paths)
    session = _make_session(files)
    _check_files(session, files)
    from .exporters.markdown import module_to_markdown
    content = module_to_markdown(session, None)
    out = args.output or "DOCS.md"
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(content)
    print(f"wrote {out}")
    return 0


def cmd_graph(args) -> int:
    files = _project_sources(args.paths)
    session = _make_session(files)
    _check_files(session, files)
    if not session.plots:
        print("no plots in the given sources")
        return 0
    try:
        from .graphing import plot_spec
        from .graphing.svg import render_svg
    except ImportError:
        print("error: graphing backend unavailable", file=sys.stderr)
        return 1
    for i, entry in enumerate(session.plots):
        spec = plot_spec(session.env, entry)
        out = args.output or f"plot_{i}.svg"
        if len(session.plots) > 1 and args.output:
            base, ext = os.path.splitext(args.output)
            out = f"{base}_{i}{ext}"
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(render_svg(spec))
        print(f"wrote {out}")
    return 0


def cmd_repl(args) -> int:
    from .repl import run_repl
    return run_repl()


def cmd_serve(args) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print("error: the server needs fastapi + uvicorn "
              "(pip install 'epsilon-math[server]')", file=sys.stderr)
        return 1
    try:
        import uvicorn
        uvicorn.run("epsilon.server.app:app", host=args.host, port=args.port,
                    reload=False)
    except ModuleNotFoundError:
        print("error: server module not available in this build",
              file=sys.stderr)
        return 1
    return 0


def cmd_new(args) -> int:
    name = args.name
    root = os.path.abspath(name)
    if os.path.exists(root):
        print(f"error: '{name}' already exists", file=sys.stderr)
        return 1
    os.makedirs(os.path.join(root, "src"))
    _write(os.path.join(root, "epsilon.toml"),
           f'[project]\nname = "{name}"\nversion = "0.1.0"\n'
           f'description = "An Epsilon project"\n\n[dependencies]\n')
    _write(os.path.join(root, "src", "main.epsl"), _SCAFFOLD)
    _write(os.path.join(root, ".gitignore"), "*.svg\nDOCS.md\nepsilon.lock\n")
    _write(os.path.join(root, "README.md"),
           f"# {name}\n\nAn Epsilon project. Run `epsilon check` to verify.\n")
    print(f"created {name}/")
    print(f"  cd {name} && epsilon check")
    return 0


def _write(path: str, content: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


_SCAFFOLD = """\
-- Welcome to Epsilon. Run `epsilon check` to verify this file.

/-- The double of a natural number. -/
def double (n : Nat) : Nat := 2 * n

/-- A worked proof: addition on ℕ is commutative (proved by induction
    in the standard library; here we just use it). -/
theorem double_add (a b : Nat) : double(a + b) = double(a) + double(b) := by
  unfold double
  rw [Nat.left_distrib]

-- Evaluate expressions with #eval:
#eval double(21)
#eval 2 + 3 * 4

-- Plot a function:
plot Real.sin, x ∈ [-6, 6]
"""


# ---------------------------------------------------------------------------
# status helpers
# ---------------------------------------------------------------------------

def _status_counts(session: Session) -> dict:
    counts = {"proven": 0, "symbolic": 0, "numeric": 0, "heuristic": 0}
    for t in session.theorem_list():
        counts[t["status"]] = counts.get(t["status"], 0) + 1
    return counts


def _format_counts(counts: dict) -> str:
    parts = []
    labels = {"proven": "✓ proven", "symbolic": "✓ symbolic",
              "numeric": "≈ numeric", "heuristic": "⚠ heuristic"}
    for k in ("proven", "symbolic", "numeric", "heuristic"):
        if counts.get(k):
            parts.append(f"{counts[k]} {labels[k]}")
    return ", ".join(parts) if parts else "no theorems"


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="epsilon",
        description=f"{BRAND}: a unified mathematical computing environment")
    p.add_argument("--version", action="store_true",
                   help="print version and exit")
    sub = p.add_subparsers(dest="command")

    def add_paths(sp):
        sp.add_argument("paths", nargs="*", help="source files or directories")

    add_paths(sub.add_parser("check", help="type-check and prove"))
    add_paths(sub.add_parser("build", help="alias for check"))
    sp_run = sub.add_parser("run", help="check and print eval/plot results")
    add_paths(sp_run)
    add_paths(sub.add_parser("test", help="run test files"))

    sp_prove = sub.add_parser("prove", help="report every theorem's status")
    add_paths(sp_prove)
    sp_prove.add_argument("--module", help="restrict to one module")

    sp_fmt = sub.add_parser("fmt", help="format source files")
    add_paths(sp_fmt)
    sp_fmt.add_argument("--check", action="store_true",
                        help="report but do not modify")
    add_paths(sub.add_parser("lint", help="check formatting (fmt --check)"))

    sp_export = sub.add_parser("export", help="export to another format")
    add_paths(sp_export)
    sp_export.add_argument(
        "--format", "-f", default="latex",
        choices=["latex", "markdown", "json", "mathml", "python",
                 "python-numpy", "python-sympy", "lean"])
    sp_export.add_argument("--output", "-o", help="output file")
    # convenience flags
    for flag, fmt in (("--latex", "latex"), ("--markdown", "markdown"),
                      ("--json", "json"), ("--python", "python"),
                      ("--mathml", "mathml"), ("--lean", "lean")):
        sp_export.add_argument(flag, dest="fmt_flag", action="store_const",
                               const=fmt, help=f"shorthand for --format {fmt}")

    sp_docs = sub.add_parser("docs", help="generate markdown documentation")
    add_paths(sp_docs)
    sp_docs.add_argument("--output", "-o")

    sp_graph = sub.add_parser("graph", help="render plots to SVG")
    add_paths(sp_graph)
    sp_graph.add_argument("--output", "-o")

    sub.add_parser("repl", help="start the interactive console")

    sp_serve = sub.add_parser("serve", help="launch the web IDE server")
    sp_serve.add_argument("--host", default="127.0.0.1")
    sp_serve.add_argument("--port", type=int, default=8000)

    sp_new = sub.add_parser("new", help="scaffold a new project")
    sp_new.add_argument("name")

    sub.add_parser("version", help="print version")
    return p


_COMMANDS = {
    "check": cmd_check, "build": cmd_check, "run": cmd_run, "test": cmd_test,
    "prove": cmd_prove, "fmt": cmd_fmt, "lint": cmd_lint, "export": cmd_export,
    "docs": cmd_docs, "graph": cmd_graph, "repl": cmd_repl, "serve": cmd_serve,
    "new": cmd_new, "version": cmd_version,
}


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "version", False) or args.command == "version":
        return cmd_version(args)
    if args.command is None:
        parser.print_help()
        return 0
    # resolve export convenience flags
    if args.command == "export" and getattr(args, "fmt_flag", None):
        args.format = args.fmt_flag
    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
