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


def completions(prefix=""):
    global _completion_session
    if _completion_session is None:
        _completion_session = Session()
    from epsilon.intelligence import completions as get
    items = get(_completion_session, prefix, limit=100)
    return json.dumps({"items": [{"name": i["name"], "kind": i["kind"],
                                  "type": i.get("type", ""),
                                  "display_name": i.get("display_name"),
                                  "title": i.get("title") or i["name"]}
                                 for i in items]})
