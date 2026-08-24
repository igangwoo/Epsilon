"""In-browser bridge between the Epsilon IDE (JavaScript) and the Epsilon
engine (Python), running entirely inside Pyodide — no server.

The functions here mirror the FastAPI server's endpoints (docs/CONTRACTS.md)
and return JSON strings, so the existing `app.js` works unchanged behind a
`fetch` shim that routes `/api/*` here instead of to a network backend.
"""

import json

from epsilon import __version__, LANGUAGE_VERSION, BRAND
from epsilon.project import Session
from epsilon.repl import Repl

# one persistent REPL session for /api/eval; a fresh Session per /api/check
_repl = Repl()


def _diag(d):
    return {"severity": d.severity, "message": d.message,
            "span": list(d.span), "module": d.module}


def _result(r):
    return {"kind": r.kind, "name": r.name, "message": r.message,
            "status": r.status, "span": list(r.span)}


def _trace(steps):
    out = []
    for s in steps or []:
        out.append({
            "goal_id": s.goal_id, "tactic": s.tactic, "rule": s.rule,
            "before_hyps": [{"name": n, "type": t} for n, t in s.before_hyps],
            "before_target": s.before_target,
            "after_goals": s.after_goals, "span": list(s.span)})
    return out


def meta():
    return json.dumps({"version": __version__,
                       "language_version": LANGUAGE_VERSION, "brand": BRAND})


def check(content, module="main"):
    session = Session()
    try:
        result = session.check_source(content, module)
        from epsilon.graphing import plot_spec
        plots = []
        for entry in session.plots:
            try:
                spec = plot_spec(session.env, entry)
                spec["span"] = list(entry.get("span", (0, 0, 0, 0)))
                plots.append(spec)
            except Exception as e:  # noqa: BLE001
                plots.append({"error": str(e),
                              "span": list(entry.get("span", (0, 0, 0, 0)))})
        theorems = session.theorem_list(module)
        thm_names = {t["name"] for t in theorems}
        traces = {n: _trace(s) for n, s in session.traces.items()
                  if n in thm_names}
        payload = {
            "ok": result.ok,
            "diagnostics": [_diag(d) for d in result.diagnostics],
            "results": [_result(r) for r in result.results],
            "theorems": theorems,
            "definitions": session.definition_list(module),
            "plots": plots,
            "traces": traces,
            "deps": session.dependency_graph(),
        }
    except Exception as e:  # noqa: BLE001 - never throw into JS
        payload = {"ok": False, "diagnostics": [{
            "severity": "error", "message": f"internal: {e}",
            "span": [0, 0, 0, 0], "module": module}],
            "results": [], "theorems": [], "definitions": [], "plots": [],
            "traces": {}, "deps": {"nodes": [], "edges": []}}
    return json.dumps(payload)


def eval_code(code):
    global _repl
    try:
        output = _repl.run_input(code)
    except EOFError:
        _repl = Repl()
        output = "session reset"
    except Exception as e:  # noqa: BLE001
        return json.dumps({"ok": False, "output": "", "diagnostics": [str(e)]})
    return json.dumps({"ok": True, "output": output, "diagnostics": []})


def export(content, fmt, module="main"):
    session = Session()
    try:
        session.check_source(content, module)
        text = _run_export(session, fmt, module)
        return json.dumps({"ok": True, "content": text})
    except Exception as e:  # noqa: BLE001
        return json.dumps({"ok": False, "content": f"export failed: {e}"})


def _run_export(session, fmt, module):
    if fmt == "latex":
        from epsilon.exporters.latex import module_to_latex
        return module_to_latex(session, module)
    if fmt == "markdown":
        from epsilon.exporters.markdown import module_to_markdown
        return module_to_markdown(session, module)
    if fmt == "json":
        from epsilon.exporters.json_export import module_to_json
        return json.dumps(module_to_json(session, module), indent=2)
    if fmt in ("python", "python-numpy", "python-sympy"):
        from epsilon.exporters.python_ast import module_to_python
        backend = {"python": "math", "python-numpy": "numpy",
                   "python-sympy": "sympy"}[fmt]
        return module_to_python(session, module, backend=backend)
    if fmt == "mathml":
        from epsilon.exporters.mathml import term_to_mathml
        return "\n".join(term_to_mathml(session.env,
                                        session.env.expect(t["name"]).type)
                         for t in session.theorem_list(module))
    if fmt == "lean":
        from epsilon.interop.lean import module_to_lean
        return module_to_lean(session, module)
    raise ValueError(f"unknown export format: {fmt}")


_completion_session = None


def hover(name):
    from epsilon.intelligence import hover as get_hover
    return json.dumps({"info": get_hover(_shared_session(), name)})


def definition(name):
    from epsilon.intelligence import goto_definition, hover as get_hover
    s = _shared_session()
    return json.dumps({"location": goto_definition(s, name),
                       "info": get_hover(s, name)})


def _shared_session():
    global _completion_session
    if _completion_session is None:
        _completion_session = Session()
    return _completion_session


def completions(prefix=""):
    from epsilon.intelligence import completions as get
    items = get(_shared_session(), prefix, limit=100)
    return json.dumps({"items": [{"name": i["name"], "kind": i["kind"],
                                  "type": i.get("type", ""),
                                  "display_name": i.get("display_name"),
                                  "title": i.get("title") or i["name"]}
                                 for i in items]})


def cas_operations():
    from epsilon.cas.workbench import OPERATIONS
    return json.dumps({"operations": [
        {"op": op, "label": label, "needs_variable": needs_var,
         "description": desc}
        for op, (label, needs_var, desc) in OPERATIONS.items()]})


def cas(op, expr, variable=None, point="0", order=5):
    """One CAS operation, reported with its verification status.

    Mirrors the server's /api/cas. A CAS answer is `symbolic`, a sampled
    value is `numeric`; the kernel is not involved, so neither is `proven`.
    """
    from epsilon.cas.workbench import OPERATIONS, run
    from epsilon.project import STATUS_LABELS
    session = _shared_session()
    try:
        r = run(session, op, expr, variable=variable or None,
                point=point or "0", order=int(order or 5))
    except Exception as e:  # noqa: BLE001 - never raise into the browser
        label = OPERATIONS.get(op, (op, False, ""))[0]
        return json.dumps({"ok": False, "op": op, "label": label,
                           "message": str(e)})

    label, _, description = OPERATIONS[r.op]
    return json.dumps({
        "ok": True, "op": r.op, "label": label, "description": description,
        "variable": r.variable, "status": r.status,
        "status_label": STATUS_LABELS[r.status], "note": r.note,
        "input": _term_forms(session.env, r.input),
        "result": _term_forms(session.env, r.result) if r.result is not None else None,
        "results": [_term_forms(session.env, t) for t in r.results],
    })


def _term_forms(env, t):
    """One term as Epsilon source, LaTeX and MathML. Source stays canonical."""
    from epsilon.elab.pp import pp
    from epsilon.exporters import latex, mathml
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
        from epsilon.exporters.python_ast import term_to_python_ast
        out["python"] = _ast.unparse(term_to_python_ast(env, t))
    except Exception:  # noqa: BLE001 - not every term is runnable code
        out["python"] = ""
    return out


def render(content, module="main"):
    """The module's declarations as typeset mathematics. Mirrors /api/render."""
    from epsilon.exporters.render import render_module
    session = Session()
    result = session.check_source(content, module)
    out = render_module(session, module)
    out["ok"] = result.ok
    out["diagnostics"] = [_diag(d) for d in result.diagnostics]
    return json.dumps(out)


def suggest(goal, hypotheses=None, limit=12):
    """Library results that could act on this goal. Mirrors /api/suggest."""
    from epsilon.suggest import suggest_for_text
    try:
        found = suggest_for_text(
            _shared_session(), goal,
            hypotheses=[(h[0], h[1]) for h in (hypotheses or []) if len(h) >= 2],
            limit=max(1, min(50, int(limit or 12))))
    except Exception as e:  # noqa: BLE001 - never raise into the browser
        return json.dumps({"ok": False, "goal": goal, "message": str(e),
                           "suggestions": []})
    return json.dumps({"ok": True, "goal": goal,
                       "suggestions": [s.as_dict() for s in found]})


# ---------------------------------------------------------------------------
# running programs (browser build)
# ---------------------------------------------------------------------------
# Python runs for real, in this same Pyodide interpreter — a fresh namespace
# per run, streams captured, stdin served from the request. What cannot be
# faithfully reproduced here is said out loud instead of imitated: there is
# no subprocess, so no separate exit code beyond SystemExit, and a runaway
# loop cannot be preempted (Pyodide shares the page's only thread).

_py_console_ns = None


def _trim_traceback(limit_file="main.py"):
    """Format the active exception without the harness's own exec frame."""
    import sys
    import traceback
    etype, evalue, tb = sys.exc_info()
    if tb is not None and tb.tb_next is not None:
        tb = tb.tb_next
    return "".join(traceback.format_exception(etype, evalue, tb))


def run_program(language, code, stdin="", filename=""):
    import contextlib
    import io
    import time
    if language == "cpp":
        return json.dumps({
            "ok": False, "language": "cpp", "phase": "compile",
            "stdout": "", "stderr": "", "exit_code": None, "duration_ms": 0,
            "diagnostics": [],
            "message": "C++ needs a compiler, and this browser build has "
                       "none — run the local server build (`epsilon serve`) "
                       "for C++. Saying so beats pretending."})
    if language != "python":
        return json.dumps({
            "ok": False, "language": language, "phase": "run",
            "stdout": "", "stderr": "", "exit_code": None, "duration_ms": 0,
            "diagnostics": [], "message":
                f"'{language}' is not a runnable language here"})

    name = filename or "main.py"
    ns = {"__name__": "__main__", "__file__": name}
    out, err = io.StringIO(), io.StringIO()
    exit_code = 0
    ok = True
    t0 = time.time()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        old_stdin = None
        import sys as _sys
        old_stdin, _sys.stdin = _sys.stdin, io.StringIO(stdin or "")
        try:
            exec(compile(code, name, "exec"), ns)
        except SystemExit as e:
            exit_code = int(e.code or 0)
            ok = exit_code == 0
        except BaseException:
            ok = False
            exit_code = 1
            err.write(_trim_traceback(name))
        finally:
            _sys.stdin = old_stdin
    stderr = err.getvalue()
    from epsilon.runtime.runner import python_diagnostics
    return json.dumps({
        "ok": ok, "language": "python", "phase": "run",
        "stdout": out.getvalue(), "stderr": stderr,
        "exit_code": exit_code, "duration_ms": int((time.time() - t0) * 1000),
        "diagnostics": python_diagnostics(stderr, name),
        "message": ""})


def run_languages():
    return json.dumps({"languages": {"python": True, "cpp": False}})


def pyrepl(code, reset=False):
    """The persistent Python console — this interpreter's own namespace."""
    import contextlib
    import io
    global _py_console_ns
    if reset or _py_console_ns is None:
        _py_console_ns = {"__name__": "__console__", "__doc__": None}
        if reset:
            return json.dumps({"ok": True, "output": "", "error": "",
                               "reset": True})
    if not (code or "").strip():
        return json.dumps({"ok": True, "output": "", "error": ""})
    out, err = io.StringIO(), io.StringIO()
    ok = True
    try:
        compiled = compile(code, "<console>", "single")
    except SyntaxError:
        try:
            compiled = compile(code, "<console>", "exec")
        except SyntaxError:
            import traceback
            return json.dumps({"ok": False, "output": "",
                               "error": traceback.format_exc(limit=0)})
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(compiled, _py_console_ns)
        except BaseException:
            ok = False
            err.write(_trim_traceback("<console>"))
    return json.dumps({"ok": ok, "output": out.getvalue(),
                       "error": err.getvalue()})


def mathify(expr, language="python"):
    """A Python/C++ arithmetic expression, typeset. Mirrors /api/mathify."""
    from epsilon.interop.mathexpr import MathExprError, parse_math_expr
    session = _shared_session()
    try:
        term = parse_math_expr(expr)
    except MathExprError as e:
        return json.dumps({"ok": False, "message": str(e)})
    forms = _term_forms(session.env, term)
    return json.dumps({"ok": True, **forms})
