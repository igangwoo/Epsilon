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

`epsilon/cas/workbench.py` is the CAS as a service: source text in, a named
operation, and a result carrying its verification status.
```python
OPERATIONS  # op -> (label, needs_variable, description)
run(session, op, src, *, variable=None, point="0", order=5) -> CASResult
#   CASResult: op, status ("symbolic"|"numeric"), input, result, results,
#              variable, note.  Raises CASRequestError - which the endpoints
#              turn into ok=false + message - rather than returning a value
#              the CAS cannot justify.
parse_term(session, src, variables=None) -> (Term, [variable names])
#   free identifiers become Real variables, in source order
```
A CAS answer is `symbolic` and a sampled value is `numeric`. Neither is ever
`proven`: the kernel is not involved, and no code path from the CAS reaches
a formal-proof label.

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
render.render_module(session, module=None) -> {"blocks": [...],
                                               "document_latex": str}
#  every declaration of the module, in source order, as LaTeX + MathML with
#  the status the engine reported. Feeds /api/render and the IDE's rendered-
#  mathematics pane. Rendering never rewrites the source it renders.
```
MathML emits blackboard-bold characters literally (ℝ, not
`mathvariant="double-struck"`, which MathML Core deprecates and browsers
honour inconsistently).

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
GET  /api/files                 -> {"files":   [{"name","path"}],          # .epsl only
                                    "entries": [{"name","path","kind",     # whole tree
                                                 "language","size","editable"}]}
   (kind: "file"|"folder"; language: epsilon/python/cpp/markdown/json/... ,
    "plain" when unknown; editable false for binaries and very large files)
GET  /api/file?path=..          -> {"path":.., "content": str}
PUT  /api/file  {path, content} -> {"ok": true}
POST /api/file  {path}          -> {"ok": true}          (create empty)
DELETE /api/file?path=..        -> {"ok": true}
POST /api/folder {path}         -> {"ok": true, "path": str}
DELETE /api/folder?path=..      -> {"ok": true}          (recursive; root refused)
POST /api/rename {path, to}     -> {"ok": true, "path": to}
   (404 unknown, 409 name taken, 400 outside the workspace or into itself)
POST /api/duplicate {path}      -> {"ok": true, "path": "<name> copy.<ext>"}

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
POST /api/cas {op, expr, variable?, point?, order?} -> {
  "ok": bool, "op", "label", "description", "variable",
  "status": "symbolic"|"numeric",        # NEVER "proven" - see below
  "status_label", "note",
  "input":   {"source","latex","mathml"},
  "result":  {...} | null,
  "results": [{...}]                     # solve returns every root
}
   (a refusal is 200 with ok=false and a `message`: bad input, or an
    operation the CAS cannot carry out. It says so rather than guessing.)
GET  /api/cas/operations       -> {"operations":[{"op","label",
                                    "needs_variable","description"}]}

POST /api/suggest {goal, hypotheses?: [[name, type]], limit?} -> {
  "ok": bool, "goal", "message"?,
  "suggestions": [{"name","display_name","title","statement","kind",
                   "status","tactic","side_goals","why","score"}]
}
   (each suggestion has passed the same viability test the tactic itself
    enforces, so it applies. `sorry` and the trust axioms are never
    suggested. A goal with bare variables is typed by trying Nat, Int, Real,
    Prop in turn; explicit binders override that.)

POST /api/render {path?, content?} -> {
  "ok", "diagnostics": [...],
  "blocks": [{"name","display_name","title","kind","status","status_label",
              "doc","span","statement","axioms",
              "type":  {"latex","mathml"},
              "value": {"latex","mathml"}   # definitions only, not proofs
             }],                            # source order
  "document_latex": str
}

GET  /api/completions?prefix=  -> {"items":[{"name","kind","type",
                                    "display_name","title"}]}
GET  /api/hover?name=          -> {"info": intelligence.hover(...) | null}
GET  /api/definition?name=     -> {"location": {"name","module","span"} | null,
                                   "info": intelligence.hover(...) | null}
   (location is null for library symbols with no workspace file; callers
    show `info` inline instead of navigating nowhere)
GET  /api/meta                 -> {"version","language_version","brand"}
```

## Web IDE - `epsilon/server/static/`

Files: `index.html`, `app.css`, `app.js`, `panes.js` (NO external CDNs;
self-contained). Talks only to the REST API above. VS Code-like layout with
Apple glass (translucent, blurred) styling. Details in the frontend task brief.

`panes.js` owns the workspace layout - a binary split tree of tabbed panes.
Views are the *existing* DOM elements, re-parented into panes rather than
re-created, so every `$("#thmList")`-style lookup in `app.js` keeps working.
Elements not currently placed in a pane are parked in `#viewVault` (hidden)
so they stay in the document and remain queryable.

```js
EpsilonPanes.init({host, vault, views: [{id, title, icon, element, onShow,
                                         closable}], onChange})
EpsilonPanes.openView(id) / closeView(id) / isOpen(id)
EpsilonPanes.splitPane("row"|"col", viewId?) / toggleMaximize(leafId?)
EpsilonPanes.moveView(viewId, targetLeafId, zone)   // zone: tab|left|right|up|down
EpsilonPanes.setBadge(id, text, tone)               // tone: "err"|"warn"|""
EpsilonPanes.applyProfile(name) / profileNames() / reset()
```
Layouts persist in `localStorage["epsilon.workspace.v1"]`. A saved layout or
profile naming a view that is not registered is pruned, never rendered blank.

## Browser build - `web/`

The browser-only deploy (Pyodide; no server, no install) is
`epsilon/server/static/` plus a thin shell: `web.css` overrides, a boot
overlay, and `boot.js`, which starts Pyodide, installs the wheel, shims
`fetch` to route `/api/*` at `bridge.py`, adjusts the title bar for a browser
tab, then loads the *unmodified* `app.js`.

`python3 scripts/build_web.py [--wheel]` regenerates it. `tests/test_web_build.py`
fails if the two builds drift.

`web/vfs.js` is the browser workspace: the file/folder/rename/duplicate half
of the API above, against a `{path: content}` map in localStorage, with the
same status codes for the same requests. `tests/test_web_vfs.py` runs the
same request sequences through both implementations and compares them.

## CLI - `epsilon/cli.py`

`epsilon <cmd>` and `3psilon <cmd>`: new, check, build (=check), run (=check
+ print eval/plot artifacts), test (run `example`/`#check` files under
tests/), repl, prove (=check, theorem report + axiom listing), fmt (v0.1:
normalize line endings/trailing ws only), graph (export SVG plots), export
(--latex|--markdown|--json|--python|--mathml, -o out), docs (markdown docs),
serve (uvicorn launch of epsilon.server.app:app), version.
Manifest: `epsilon.toml` `[project] name/version/description` +
`[dependencies]` (paths). `epsilon new NAME` scaffolds project + example.

## Proof explorer - `epsilon/suggest.py`

```python
suggest(session, goal: Term, *, limit=12, include_axioms=True) -> [Suggestion]
suggest_for_text(session, goal_src, *, hypotheses=None, limit=12)
#   Suggestion: name, display_name, title, statement, kind, status, tactic,
#               side_goals, score, why;  .as_dict() for the API
```
Matching is the test the tactics themselves perform - `apply`'s conclusion
unification (including its refusal when an argument cannot be inferred) and
`rw`'s strict pattern match against a subterm - so a suggestion applies. It
is still a suggestion: nothing here proves anything, and running the tactic
is what puts the result through the kernel.

Never suggested: `Epsilon.sorry` and the trust axioms (they close any goal,
which is precisely why offering them is wrong), and results whose conclusion
is a bare variable (they match everything and so say nothing).

## Statuses (never conflate - section 27)

`proven / symbolic / numeric / heuristic` with labels
`✓ Formally Proven / ✓ Symbolically Verified / ≈ Numerically Verified /
⚠ Heuristic Result` - from `epsilon.project.STATUS_LABELS`.
