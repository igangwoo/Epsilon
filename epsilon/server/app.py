"""FastAPI application for the Epsilon web IDE.

Implements the REST API in docs/CONTRACTS.md. A fresh `Session` is built per
`/api/check` (so results never leak between requests), while `/api/eval`
keeps one persistent REPL session. Static files (the IDE) are served from
`epsilon/server/static`.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
from typing import Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import __version__, LANGUAGE_VERSION, BRAND
from ..project import Session, STATUS_LABELS
from ..repl import Repl

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
WELCOME = """\
-- Welcome to Epsilon. Press ▶ Check (or Ctrl/Cmd+Enter) to verify.

/-- The sinc function, f(x) = sin(x)/x. -/
def f (x : Real) : Real := Real.sin(x) / x

/-- Addition on ℕ is commutative — proved by induction. -/
theorem add_comm (a b : Nat) : a + b = b + a := by
  induction b with
  | zero => rw [Nat.add_zero, Nat.zero_add]
  | succ n ih => rw [Nat.add_succ, Nat.succ_add, ih]

theorem two_le_three : 2 ≤ 3 := by decide

#check f
#eval 2 + 3 * 4

plot Real.sin, x ∈ [-6, 6]
"""


# ---------------------------------------------------------------------------
# workspace helpers
# ---------------------------------------------------------------------------

def _workspace() -> str:
    ws = os.environ.get("EPSILON_WORKSPACE", os.path.join(os.getcwd(),
                                                          "workspace"))
    os.makedirs(ws, exist_ok=True)
    return ws


def _safe_path(rel: str) -> str:
    ws = _workspace()
    full = os.path.realpath(os.path.join(ws, rel))
    if full != os.path.realpath(ws) and not full.startswith(
            os.path.realpath(ws) + os.sep):
        raise HTTPException(status_code=400, detail="path escapes workspace")
    return full


#: files the explorer will open in the editor. Everything else in the
#: workspace is listed but not editable text.
TEXT_SUFFIXES = frozenset({
    ".epsl", ".py", ".pyi", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".c",
    ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv", ".tex",
    ".ini", ".cfg", ".sh", ".js", ".ts", ".html", ".css",
})

#: never listed: version control, caches, editor droppings
IGNORED_DIRS = frozenset({".git", "__pycache__", ".venv", "node_modules",
                          ".mypy_cache", ".pytest_cache", ".idea", ".vscode"})

MAX_TEXT_BYTES = 4 * 1024 * 1024


def _language_of(rel: str) -> str:
    """The editor mode for a path - `plain` when there is no better guess."""
    ext = os.path.splitext(rel)[1].lower()
    return {
        ".epsl": "epsilon",
        ".py": "python", ".pyi": "python",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
        ".c": "cpp", ".h": "cpp", ".hpp": "cpp",
        ".md": "markdown",
        ".json": "json",
        ".toml": "toml", ".ini": "toml", ".cfg": "toml",
        ".yaml": "yaml", ".yml": "yaml",
        ".tex": "latex",
        ".js": "javascript", ".ts": "javascript",
        ".html": "html", ".css": "css",
        ".sh": "shell",
    }.get(ext, "plain")


def _entries() -> list[dict]:
    """Every file and folder in the workspace, as a flat sorted list.

    Flat rather than nested: the tree is a presentation choice, and a flat
    list keeps the response shape stable for callers that only want files
    (the check pipeline) as well as the explorer.
    """
    ws = _workspace()
    out: list[dict] = []
    for root, dirs, names in os.walk(ws):
        dirs[:] = sorted(d for d in dirs
                         if d not in IGNORED_DIRS and not d.startswith("."))
        for d in dirs:
            rel = os.path.relpath(os.path.join(root, d), ws)
            out.append({"name": d, "path": rel.replace(os.sep, "/"),
                        "kind": "folder"})
        for n in sorted(names):
            if n.startswith("."):
                continue
            full = os.path.join(root, n)
            rel = os.path.relpath(full, ws).replace(os.sep, "/")
            ext = os.path.splitext(n)[1].lower()
            try:
                size = os.path.getsize(full)
            except OSError:
                continue
            out.append({
                "name": n, "path": rel, "kind": "file",
                "language": _language_of(rel),
                "size": size,
                "editable": ext in TEXT_SUFFIXES and size <= MAX_TEXT_BYTES,
            })
    return sorted(out, key=lambda e: (e["path"].count("/"), e["path"]))


def _unique_path(full: str) -> str:
    """`a.epsl` -> `a copy.epsl` -> `a copy 2.epsl`, never clobbering."""
    if not os.path.exists(full):
        return full
    stem, ext = os.path.splitext(full)
    candidate = f"{stem} copy{ext}"
    n = 2
    while os.path.exists(candidate):
        candidate = f"{stem} copy {n}{ext}"
        n += 1
    return candidate


def _ensure_welcome() -> None:
    ws = _workspace()
    if not any(f.endswith(".epsl") for f in os.listdir(ws)):
        with open(os.path.join(ws, "main.epsl"), "w", encoding="utf-8") as fh:
            fh.write(WELCOME)


# ---------------------------------------------------------------------------
# serialization
# ---------------------------------------------------------------------------

def _result_dict(r) -> dict:
    return {"kind": r.kind, "name": r.name, "message": r.message,
            "status": r.status, "span": list(r.span)}


def _diag_dict(d) -> dict:
    return {"severity": d.severity, "message": d.message,
            "span": list(d.span), "module": d.module}


def _trace_dict(steps) -> list:
    out = []
    for s in steps or []:
        out.append({
            "goal_id": s.goal_id, "tactic": s.tactic, "rule": s.rule,
            "before_hyps": [{"name": n, "type": t} for n, t in s.before_hyps],
            "before_target": s.before_target,
            "after_goals": s.after_goals, "span": list(s.span)})
    return out


def _build_check_response(session: Session, module: str) -> dict:
    from ..graphing import plot_spec
    plots = []
    for entry in session.plots:
        try:
            plots.append({**plot_spec(session.env, entry),
                          "span": list(entry.get("span", (0, 0, 0, 0)))})
        except Exception as e:  # noqa: BLE001 - one bad plot must not 500
            plots.append({"error": str(e),
                          "span": list(entry.get("span", (0, 0, 0, 0)))})
    # scope to the checked module so the IDE shows the user's work, not the
    # whole standard library (which is always loaded underneath)
    theorems = session.theorem_list(module)
    definitions = session.definition_list(module)
    thm_names = {t["name"] for t in theorems}
    traces = {name: _trace_dict(steps)
              for name, steps in session.traces.items() if name in thm_names}
    return {
        "theorems": theorems,
        "definitions": definitions,
        "plots": plots,
        "traces": traces,
        "deps": session.dependency_graph(),
    }


def _term_forms(env, t) -> dict:
    """One term in every form the front end needs.

    `source` is valid Epsilon that can be pasted back into a file; `latex`
    and `mathml` are for display only. Rendering never replaces the source.
    """
    from ..elab.pp import pp
    from ..exporters import latex, mathml
    out = {"source": pp(env, t)}
    try:
        out["latex"] = latex.term_to_latex(env, t)
    except Exception:  # noqa: BLE001 - display is best-effort
        out["latex"] = ""
    try:
        out["mathml"] = mathml.term_to_mathml(env, t)
    except Exception:  # noqa: BLE001
        out["mathml"] = ""
    try:
        import ast as _ast
        from ..exporters.python_ast import term_to_python_ast
        out["python"] = _ast.unparse(term_to_python_ast(env, t))
    except Exception:  # noqa: BLE001 - not every term is runnable code
        out["python"] = ""
    return out


# ---------------------------------------------------------------------------
# request models
# ---------------------------------------------------------------------------

class FileWrite(BaseModel):
    path: str
    content: str = ""


class FileMove(BaseModel):
    path: str
    to: str


class FilePath(BaseModel):
    path: str


class CASRequest(BaseModel):
    op: str
    expr: str
    variable: Optional[str] = None
    point: str = "0"
    order: int = 5


class SuggestRequest(BaseModel):
    goal: str
    hypotheses: list[list[str]] = []
    limit: int = 12


class CheckRequest(BaseModel):
    path: Optional[str] = None
    content: Optional[str] = None


class MathifyRequest(BaseModel):
    expr: str
    language: str = "python"


class RunRequest(BaseModel):
    language: str
    code: str
    stdin: str = ""
    timeout: float = 10.0
    filename: str = ""


class PyReplRequest(BaseModel):
    code: str
    reset: bool = False


class EvalRequest(BaseModel):
    code: str


class ExportRequest(BaseModel):
    path: Optional[str] = None
    format: str = "latex"


def _require_same_origin(request: Request) -> None:
    """Refuse cross-site calls to endpoints that execute code.

    The CORS middleware is deliberately permissive for the read/check API,
    but /api/run and /api/pyrepl execute real programs with the server's
    privileges. Without this check, any web page the user visits could POST
    here and run code on their machine. A browser stamps cross-site requests
    with an Origin header; one that does not match the host this server is
    being addressed as is refused before anything runs. Requests without an
    Origin (curl, scripts) are the user's own and pass.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", "")
    from urllib.parse import urlsplit
    if urlsplit(origin).netloc != host:
        raise HTTPException(status_code=403,
                            detail="cross-origin code execution is refused")


# ---------------------------------------------------------------------------
# app factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title=f"{BRAND} IDE", version=__version__)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    from ..runtime.pyrepl import PythonRepl
    repl_state = {"repl": Repl(), "pyrepl": PythonRepl()}

    # -------------------- files --------------------
    @app.get("/api/files")
    def list_files() -> dict:
        """Everything in the workspace.

        `files` stays Epsilon-only so existing callers see what they always
        did; `entries` carries the full tree (folders included) the explorer
        needs, each file tagged with its editor language.
        """
        _ensure_welcome()
        entries = _entries()
        files = [{"name": e["name"], "path": e["path"]}
                 for e in entries
                 if e["kind"] == "file" and e["path"].endswith(".epsl")]
        return {"files": files, "entries": entries}

    @app.get("/api/file")
    def read_file(path: str) -> dict:
        full = _safe_path(path)
        if not os.path.isfile(full):
            raise HTTPException(status_code=404, detail="not found")
        with open(full, encoding="utf-8") as fh:
            return {"path": path, "content": fh.read()}

    @app.put("/api/file")
    def write_file(req: FileWrite) -> dict:
        full = _safe_path(req.path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(req.content)
        return {"ok": True}

    @app.post("/api/file")
    def create_file(req: FileWrite) -> dict:
        full = _safe_path(req.path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if not os.path.exists(full):
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(req.content)
        return {"ok": True}

    @app.delete("/api/file")
    def delete_file(path: str) -> dict:
        full = _safe_path(path)
        if os.path.isfile(full):
            os.remove(full)
        return {"ok": True}

    @app.post("/api/folder")
    def create_folder(req: FilePath) -> dict:
        full = _safe_path(req.path)
        if os.path.isfile(full):
            raise HTTPException(status_code=409, detail="a file is already there")
        os.makedirs(full, exist_ok=True)
        return {"ok": True, "path": req.path}

    @app.delete("/api/folder")
    def delete_folder(path: str) -> dict:
        """Remove a folder and everything under it.

        Guarded twice: `_safe_path` keeps the target inside the workspace,
        and the workspace root itself is never removable.
        """
        full = _safe_path(path)
        if os.path.realpath(full) == os.path.realpath(_workspace()):
            raise HTTPException(status_code=400,
                                detail="the workspace root cannot be deleted")
        if os.path.isdir(full):
            shutil.rmtree(full)
        return {"ok": True}

    @app.post("/api/rename")
    def rename_entry(req: FileMove) -> dict:
        """Rename or move a file or folder within the workspace."""
        src = _safe_path(req.path)
        dst = _safe_path(req.to)
        if not os.path.exists(src):
            raise HTTPException(status_code=404, detail="not found")
        if os.path.realpath(src) == os.path.realpath(_workspace()):
            raise HTTPException(status_code=400,
                                detail="the workspace root cannot be renamed")
        if os.path.exists(dst):
            raise HTTPException(status_code=409,
                                detail=f"{req.to} already exists")
        if os.path.isdir(src) and os.path.realpath(dst).startswith(
                os.path.realpath(src) + os.sep):
            raise HTTPException(status_code=400,
                                detail="a folder cannot move inside itself")
        os.makedirs(os.path.dirname(dst) or _workspace(), exist_ok=True)
        os.rename(src, dst)
        return {"ok": True, "path": req.to}

    @app.post("/api/duplicate")
    def duplicate_entry(req: FilePath) -> dict:
        """Copy a file or folder beside itself, under a free name."""
        src = _safe_path(req.path)
        if not os.path.exists(src):
            raise HTTPException(status_code=404, detail="not found")
        dst = _unique_path(src)
        if os.path.isdir(src):
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        rel = os.path.relpath(dst, _workspace()).replace(os.sep, "/")
        return {"ok": True, "path": rel}

    # -------------------- check --------------------
    @app.post("/api/check")
    def check(req: CheckRequest) -> dict:
        module = "main"
        if req.content is not None:
            content = req.content
            if req.path:
                module = os.path.splitext(os.path.basename(req.path))[0]
        elif req.path:
            full = _safe_path(req.path)
            if not os.path.isfile(full):
                raise HTTPException(status_code=404, detail="not found")
            with open(full, encoding="utf-8") as fh:
                content = fh.read()
            module = os.path.splitext(os.path.basename(req.path))[0]
        else:
            raise HTTPException(status_code=400, detail="path or content required")

        session = Session()
        try:
            result = session.check_source(content, module)
            payload = {
                "ok": result.ok,
                "diagnostics": [_diag_dict(d) for d in result.diagnostics],
                "results": [_result_dict(r) for r in result.results],
            }
            payload.update(_build_check_response(session, module))
            return payload
        except Exception as e:  # noqa: BLE001 - never 500 on user input
            return {"ok": False,
                    "diagnostics": [{"severity": "error",
                                     "message": f"internal: {e}",
                                     "span": [0, 0, 0, 0], "module": module}],
                    "results": [], "theorems": [], "definitions": [],
                    "plots": [], "traces": {}, "deps": {"nodes": [], "edges": []}}

    # -------------------- eval (persistent) --------------------
    # -------------------- running programs --------------------
    @app.get("/api/run/languages")
    def run_languages() -> dict:
        from ..runtime import available_languages
        return {"languages": available_languages()}

    @app.post("/api/run")
    def run_program(req: RunRequest, request: Request) -> dict:
        """Run a Python or C++ program for real, in a fresh subprocess.

        The result is exactly what happened: stdout, stderr, exit code,
        duration, and compiler/runtime diagnostics in the same shape the
        Epsilon checker reports, so the editor gutter works for all three
        languages. Nothing here can mark anything proven.
        """
        _require_same_origin(request)
        from ..runtime import run_code
        return run_code(req.language, req.code, stdin=req.stdin,
                        timeout=req.timeout, filename=req.filename).as_dict()

    @app.post("/api/pyrepl")
    def python_console(req: PyReplRequest, request: Request) -> dict:
        """One input to the persistent Python console.

        State survives between calls (it is a console); a runaway input
        resets the session and the reply says so.
        """
        _require_same_origin(request)
        repl = repl_state["pyrepl"]
        if req.reset:
            repl.reset()
            return {"ok": True, "output": "", "error": "", "reset": True}
        return repl.run(req.code)

    @app.post("/api/eval")
    def eval_code(req: EvalRequest) -> dict:
        try:
            output = repl_state["repl"].run_input(req.code)
        except EOFError:
            repl_state["repl"] = Repl()
            output = "session reset"
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "output": "", "diagnostics": [str(e)]}
        return {"ok": True, "output": output, "diagnostics": []}

    # -------------------- export --------------------
    # -------------------- computer algebra --------------------
    @app.get("/api/cas/operations")
    def cas_operations() -> dict:
        from ..cas.workbench import OPERATIONS
        return {"operations": [
            {"op": op, "label": label, "needs_variable": needs_var,
             "description": desc}
            for op, (label, needs_var, desc) in OPERATIONS.items()]}

    @app.post("/api/cas")
    def cas(req: CASRequest) -> dict:
        """Run one CAS operation and report it with its verification status.

        A CAS answer is `symbolic` and a sampled value is `numeric`. Neither
        is `proven`: the kernel is not involved here, and the IDE must never
        show an algebra result as a formal proof.
        """
        from ..cas.workbench import OPERATIONS, run
        session = repl_state["repl"].session
        try:
            r = run(session, req.op, req.expr, variable=req.variable,
                    point=req.point, order=req.order)
        except Exception as e:  # noqa: BLE001 - user input never 500s
            label = OPERATIONS.get(req.op, (req.op, False, ""))[0]
            return {"ok": False, "op": req.op, "label": label,
                    "message": str(e)}

        label, _, description = OPERATIONS[r.op]
        return {
            "ok": True,
            "op": r.op,
            "label": label,
            "description": description,
            "variable": r.variable,
            "status": r.status,
            "status_label": STATUS_LABELS[r.status],
            "note": r.note,
            "input": _term_forms(session.env, r.input),
            "result": _term_forms(session.env, r.result) if r.result is not None else None,
            "results": [_term_forms(session.env, t) for t in r.results],
        }

    # -------------------- proof explorer --------------------
    @app.post("/api/suggest")
    def suggest_tactics(req: SuggestRequest) -> dict:
        """Library results that could act on this goal.

        Each suggestion has been checked against the same conditions the
        tactic itself enforces, so it will apply. It is still a suggestion:
        nothing here proves anything, and running the tactic is what puts
        the result through the kernel.
        """
        from ..suggest import suggest_for_text
        session = repl_state["repl"].session
        try:
            found = suggest_for_text(
                session, req.goal,
                hypotheses=[(h[0], h[1]) for h in req.hypotheses if len(h) >= 2],
                limit=max(1, min(50, req.limit)))
        except Exception as e:  # noqa: BLE001 - a goal we cannot read is not a 500
            return {"ok": False, "goal": req.goal, "message": str(e),
                    "suggestions": []}
        return {"ok": True, "goal": req.goal,
                "suggestions": [s.as_dict() for s in found]}

    @app.post("/api/mathify")
    def mathify(req: MathifyRequest) -> dict:
        """A Python/C++ arithmetic expression, typeset.

        Reads the shared arithmetic subset into a kernel Term and renders it
        with the same exporters everything else uses. A selection that is
        not (only) mathematics is refused with ok=false — wrong mathematics
        on screen would be worse than none.
        """
        from ..interop.mathexpr import MathExprError, parse_math_expr
        session = repl_state["repl"].session
        try:
            term = parse_math_expr(req.expr)
        except MathExprError as e:
            return {"ok": False, "message": str(e)}
        forms = _term_forms(session.env, term)
        return {"ok": True, **forms}

    # -------------------- rendered mathematics --------------------
    @app.post("/api/render")
    def render(req: CheckRequest) -> dict:
        """The current file's declarations as typeset mathematics.

        The source is never rewritten to make this render; it is a separate
        layer over the same declarations the kernel checked, and every block
        carries the status the engine reports.
        """
        from ..exporters.render import render_module
        module = "main"
        if req.content is not None:
            content = req.content
            if req.path:
                module = os.path.splitext(os.path.basename(req.path))[0]
        else:
            _ensure_welcome()
            path = req.path or "main.epsl"
            full = _safe_path(path)
            if not os.path.isfile(full):
                raise HTTPException(status_code=404, detail="not found")
            module = os.path.splitext(os.path.basename(path))[0]
            with open(full, encoding="utf-8") as fh:
                content = fh.read()
        session = Session()
        result = session.check_source(content, module)
        out = render_module(session, module)
        out["ok"] = result.ok
        out["diagnostics"] = [_diag_dict(d) for d in result.diagnostics]
        return out

    @app.post("/api/export")
    def export(req: ExportRequest) -> dict:
        session = Session()
        module = None
        if req.path:
            full = _safe_path(req.path)
            if os.path.isfile(full):
                with open(full, encoding="utf-8") as fh:
                    src = fh.read()
                module = os.path.splitext(os.path.basename(req.path))[0]
                session.check_source(src, module)
        try:
            content = _export(session, req.format, module)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "content": f"export failed: {e}"}
        return {"ok": True, "content": content}

    # -------------------- completions --------------------
    @app.get("/api/completions")
    def completions(prefix: str = "") -> dict:
        from ..intelligence import completions as get_completions
        session = _completion_session()
        items = get_completions(session, prefix, limit=100)
        return {"items": [{"name": i["name"], "kind": i["kind"],
                           "type": i.get("type", ""),
                           "display_name": i.get("display_name"),
                           "title": i.get("title") or i["name"]}
                          for i in items]}

    # -------------------- editor intelligence --------------------
    @app.get("/api/hover")
    def hover_info(name: str) -> dict:
        from ..intelligence import hover as get_hover
        info = get_hover(_completion_session(), name)
        return {"info": info}

    @app.get("/api/definition")
    def definition(name: str) -> dict:
        from ..intelligence import goto_definition, hover as get_hover
        session = _completion_session()
        loc = goto_definition(session, name)
        # a library symbol has no workspace file to open, so return enough
        # for the caller to show it inline instead of navigating nowhere
        return {"location": loc, "info": get_hover(session, name)}

    # -------------------- meta --------------------
    @app.get("/api/meta")
    def meta() -> dict:
        return {"version": __version__, "language_version": LANGUAGE_VERSION,
                "brand": BRAND}

    # -------------------- static IDE --------------------
    if os.path.isdir(STATIC_DIR):
        app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    else:
        @app.get("/")
        def _no_static() -> JSONResponse:
            return JSONResponse({"message": f"{BRAND} API up; static IDE not "
                                            f"built"})

    return app


_COMPLETION_SESSION: Optional[Session] = None


def _completion_session() -> Session:
    global _COMPLETION_SESSION
    if _COMPLETION_SESSION is None:
        _COMPLETION_SESSION = Session()
    return _COMPLETION_SESSION


def _export(session: Session, fmt: str, module: Optional[str]) -> str:
    if fmt == "latex":
        from ..exporters.latex import module_to_latex
        return module_to_latex(session, module)
    if fmt == "markdown":
        from ..exporters.markdown import module_to_markdown
        return module_to_markdown(session, module)
    if fmt == "json":
        import json
        from ..exporters.json_export import module_to_json
        return json.dumps(module_to_json(session, module), indent=2)
    if fmt in ("python", "python-numpy", "python-sympy"):
        from ..exporters.python_ast import module_to_python
        backend = {"python": "math", "python-numpy": "numpy",
                   "python-sympy": "sympy"}[fmt]
        return module_to_python(session, module, backend=backend)
    if fmt == "mathml":
        from ..exporters.mathml import term_to_mathml
        parts = [term_to_mathml(session.env, session.env.expect(t["name"]).type)
                 for t in session.theorem_list(module)]
        return "\n".join(parts)
    if fmt == "lean":
        from ..interop.lean import module_to_lean
        return module_to_lean(session, module)
    if fmt == "svg-plots":
        from ..graphing import plot_spec
        from ..graphing.svg import render_svg
        svgs = []
        for entry in session.plots:
            try:
                svgs.append(render_svg(plot_spec(session.env, entry)))
            except Exception:  # noqa: BLE001
                continue
        return "\n".join(svgs)
    raise ValueError(f"unknown export format: {fmt}")


app = create_app()
