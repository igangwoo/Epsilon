# Epsilon subsystem contracts (v0.1)

Interfaces between subsystems. Every subsystem operates on the **shared
kernel Term IR** (`epsilon.kernel.term`) - no subsystem invents its own
expression type (section 36 of the product spec).

## Kernel term quick reference

```python
from epsilon.kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit,
                                 StrLit, mk_app, unfold_app, instantiate)
# Lit(value: Fraction, tyname: "Nat"|"Int"|"Rat"|"Real")
# Numeric ops appear as Const("Real.add") etc. applied via App (curried).
# unfold_app(t) -> (head, [args]); mk_app(head, *args)
# Real functions: Const("Real.sin"), ... ; constants Const("Real.pi")
# Equality proposition: mk_app(Const("Eq"), TypeTerm, lhs, rhs)
# whnf/normalize: from epsilon.kernel.reduce import whnf, normalize
#   (pass delta=False to avoid unfolding definitions)
# Environment lookup: env.get(name) -> Declaration (.value is the body)
```

`epsilon.project.Session` is the shared pipeline:
```python
s = Session()                      # loads stdlib prelude
r = s.check_source(src, "<main>")  # CheckResult: .results, .diagnostics, .ok
s.env, s.ctx                       # kernel environment / elab context
s.theorem_list() -> list[dict]     # name, statement, status, axioms, span...
s.definition_list() -> list[dict]
s.dependency_graph() -> {"nodes": [...], "edges": [{"from","to"}]}
s.plots -> list[dict]              # {"functions":[Term],"labels",[str],"var","lo","hi","module","span"}
s.traces -> dict[str, list[TraceStep]]  # proof traces per theorem
```
`CmdResult` fields: kind, name, message, term, type, status, span, extra, trace.
`Diagnostic`: severity, message, span=(l0,c0,l1,c1) 1-based, module; .format().
`TraceStep` (epsilon.elab.tactics): goal_id, tactic, before_hyps [(name,ty_str)],
before_target (str), after_goals [ids], span, rule.

Elaborate an expression programmatically:
```python
from epsilon.elab.elaborator import Elaborator
el = Elaborator(s.env, s.ctx)
t = el.elab_expr(parse_expression(src_str, extra_ops=dict(s.extra_ops)), None)
t = el.finalize(t)
```

## CAS - `epsilon/cas/`

```python
# engine.py
simplify(env, t: Term) -> Term            # algebraic normal form
expand(env, t: Term) -> Term
differentiate(env, f: Term) -> Term       # f : Lam over Real -> body; returns Lam
integrate(env, f: Term) -> Optional[Term] # antiderivative as Lam, None if unknown
limit_of(env, f: Term, a: Term) -> Optional[Term]  # a: Lit or Const("Real.pi")...
taylor(env, f: Term, a: Term, order: int) -> Optional[Term]
solve_eq(env, lhs: Term, rhs: Term, var_hint="x") -> Optional[list[Term]]
symbolic_eq(env, a: Term, b: Term) -> bool   # simplify(a - b) == 0 style
# oracle.py
cas_oracle(env, prop: Term) -> tuple[bool, str]
#  handles: Eq _ a b (symbolic_eq), HasLimitAt(f,a,L), Eq(limit(f,a), L),
#  Eq(deriv(f), g) pointwise-symbolically, Continuous(f) for elementary f.
#  Returns (ok, reason-string-when-not-ok).
```
Internal representation MAY be a private polynomial/rational form, but all
public inputs/outputs are kernel Terms.

## Numeric - `epsilon/numeric/`

```python
# evaluator.py
eval_term(env, t: Term, subst: dict[str, float] | None = None) -> float
  # subst maps *Const names* (locals appear as Const) to values;
  # raises EvalError (subclass ValueError) on non-numeric/opaque terms
eval_function(env, f: Term, x: float) -> float   # f a Lam or unary Const chain
# roots.py:  find_root(env, f, lo, hi, tol=1e-12) -> Optional[float] (bisection+newton)
# integrate.py: integrate_numeric(env, f, a, b, n=1000) -> float (adaptive simpson)
# ode.py: solve_ode(env, f2, x0, y0, x1, steps) -> list[tuple[float,float]] (RK4,
#         f2 : Term of type Real -> Real -> Real, dy/dx = f2(x, y))
# oracle.py
numeric_oracle(env, prop: Term) -> tuple[bool, str]
#  Eq _ a b -> |a-b| <= 1e-9 (sampling over 32 points when functions),
#  le/lt on evaluables, HasLimitAt via shrinking deltas. Honest failures.
```

## Graphing - `epsilon/graphing/`

```python
# sample.py
sample_function(env, f: Term, lo: float, hi: float, n: int = 400) -> dict
#   {"x": [...], "y": [...]}  y=None where undefined (poles); uses numeric engine
plot_spec(env, plot_entry: dict, default_lo=-10.0, default_hi=10.0) -> dict
#   plot_entry from Session.plots; evaluates lo/hi Terms via numeric engine.
#   Returns the PLOT SPEC (shared with the web IDE):
#   {"kind": "plot2d", "var": "x", "lo": f, "hi": f,
#    "series": [{"label": str, "x": [...], "y": [...]}]}
# svg.py
render_svg(spec: dict, width=800, height=500, dark=False) -> str  # standalone SVG
```

## Exporters - `epsilon/exporters/`

```python
latex.term_to_latex(env, t: Term) -> str         # \frac, ^, \sin, \forall ...
latex.decl_to_latex(env, name: str) -> str       # theorem/def as LaTeX block
latex.module_to_latex(session, module: str|None) -> str  # full document
mathml.term_to_mathml(env, t: Term) -> str       # Presentation MathML <math>...
markdown.module_to_markdown(session, module=None) -> str # doc gen w/ statuses
json_export.term_to_json(t: Term) -> dict        # lossless round-trip
json_export.term_from_json(d: dict) -> Term
json_export.module_to_json(session, module=None) -> dict
python_ast.term_to_python_ast(env, t: Term, backend="math") -> ast.expr
python_ast.module_to_python(session, module=None, backend="math") -> str
#  MUST build a Python `ast` tree and ast.unparse() it - never string paste.
#  backend "math": pure stdlib math;  "numpy"/"sympy": generate the
#  corresponding imports and calls. Definitions become Python defs;
#  theorems become comments with status labels.
```

## Server REST API - `epsilon/server/app.py` (FastAPI)

Workspace = a directory of .epsl files (default `./workspace`, override with
env var EPSILON_WORKSPACE). Server keeps ONE Session per workspace check run
(rebuild Session on each /api/check for consistency; keep a REPL Session for
/api/eval persistence). Static files served at `/` from `epsilon/server/static`.

All responses JSON. Spans are `[l0,c0,l1,c1]` 1-based.

```
GET  /api/files                 -> {"files": [{"name": "main.epsl", "path": "main.epsl"}]}
GET  /api/file?path=..          -> {"path":.., "content": str}
PUT  /api/file  {path, content} -> {"ok": true}
POST /api/file  {path}          -> {"ok": true}          (create empty)
DELETE /api/file?path=..        -> {"ok": true}

POST /api/check {path?, content?} -> {
  "ok": bool,
  "diagnostics": [{"severity","message","span","module"}],
  "results": [{"kind","name","message","status","span"}],
  "theorems": [ ...Session.theorem_list()... ],
  "definitions": [ ...Session.definition_list()... ],
  "plots": [plot specs (graphing.plot_spec output) + {"span": span}],
  "traces": {name: [{"goal_id","tactic","before_hyps","before_target",
                      "after_goals","rule","span"}]},
  "deps": Session.dependency_graph()
}

POST /api/eval {code}          -> {"ok", "output": str, "diagnostics": [...]}
   (persistent REPL session; `code` is one or more commands OR a bare
    expression - try commands first, fall back to wrapping in #eval)
POST /api/export {path?, format: "latex"|"markdown"|"json"|"python"|
                  "python-numpy"|"mathml"|"svg-plots"} -> {"ok","content": str}
GET  /api/completions?prefix=  -> {"items":[{"name","kind","type"}]}
GET  /api/meta                 -> {"version","language_version","brand"}
```

## Web IDE - `epsilon/server/static/`

Files: `index.html`, `app.css`, `app.js` (NO external CDNs; self-contained).
Talks only to the REST API above. VS Code-like layout with Apple glass
(translucent, blurred) styling. Details in the frontend task brief.

## CLI - `epsilon/cli.py`

`epsilon <cmd>` and `3psilon <cmd>`: new, check, build (=check), run (=check
+ print eval/plot artifacts), test (run `example`/`#check` files under
tests/), repl, prove (=check, theorem report + axiom listing), fmt (v0.1:
normalize line endings/trailing ws only), graph (export SVG plots), export
(--latex|--markdown|--json|--python|--mathml, -o out), docs (markdown docs),
serve (uvicorn launch of epsilon.server.app:app), version.
Manifest: `epsilon.toml` `[project] name/version/description` +
`[dependencies]` (paths). `epsilon new NAME` scaffolds project + example.

## Statuses (never conflate - section 27)

`proven / symbolic / numeric / heuristic` with labels
`✓ Formally Proven / ✓ Symbolically Verified / ≈ Numerically Verified /
⚠ Heuristic Result` - from `epsilon.project.STATUS_LABELS`.
