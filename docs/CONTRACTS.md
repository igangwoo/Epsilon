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

GET  /api/run/languages -> {"languages": {"python": bool, "cpp": bool,
                                          "java": bool}}
   (what this machine can actually run: python always, cpp if g++ or clang++
    is on PATH, java if both javac and java are. The deployed browser build
    calls this same path against its own origin to find out whether it has a
    compiler behind it at all - on GitHub Pages it 404s, and the page says so
    rather than pretending.)
POST /api/run {language, code, stdin?, timeout?, filename?} -> {
  "ok", "language", "phase": "run"|"compile", "stdout", "stderr",
  "exit_code", "duration_ms", "message",
  "diagnostics": [...]           # compiler/traceback errors, checker-shaped,
}                                # so the gutter works for all three languages
   (real execution: a fresh subprocess per run (Pyodide's own interpreter in
    the browser build), wall-clock timeout, output cap. Cross-origin calls
    are refused with 403 - a web page must not be able to execute code on
    the user's machine. Served over Pages there is no server to call, and
    the page refuses in words rather than mocking a result.)
POST /api/pyrepl {code, reset?} -> {"ok", "output", "error", "reset"?}
   (the persistent Python console: state survives between calls; server-side
    it lives in a child process - a runaway input kills and respawns it and
    the reply says the session was reset. Same-origin only, as /api/run.)

POST /api/mathify {expr, language?} -> {"ok", "source", "latex", "mathml",
                                        "python"} | {"ok": false, "message"}
   (a Python/C++ arithmetic expression read into a kernel Term and typeset.
    Only the shared arithmetic subset; anything else is refused - wrong
    mathematics on screen would be worse than none. `source` is the Epsilon
    reading, which the CAS pane accepts directly.)

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

## IDE services API (the programming-IDE phase)

All code-executing or workspace-mutating endpoints are guarded by
`_require_same_origin`: a request whose Origin header names another site is
refused with 403, so a drive-by page cannot reach a local server through the
browser. Same-origin pages and non-browser clients (no Origin header) pass.

```
GET  /api/capabilities -> {"run": {python, cpp}, "terminal": bool,
                           "debug": {python, cpp}, "format": {python, cpp},
                           "completions": {python: "semantic"|"lexical",
                                           cpp: "lexical"},
                           "definitions": {python: bool, cpp: false},
                           "git": bool}
      (the truth about THIS machine; the UI disables what is absent and says
    why. The browser build's bridge returns its own, smaller truth.
    `graph` reports the analysis level available per language.)

POST /api/complete {language, code, line, col, path?}
   -> {"level": "semantic"|"lexical", "items": [{name, kind, detail, insert}]}
   (line is 1-based, col 0-based - jedi's convention. Python is semantic
    when jedi is installed; C++ is lexical: keywords, curated std::, buffer
    identifiers. The reply's `level` says which produced it.)
POST /api/graph {language, code, path?}
   -> {"ok", "level": "semantic"|"lexical",
       "nodes": [{id, name, kind, line, detail, refs}],
       "edges": [{from, to, kind}], "note"?, "message"?}
   (what refers to what inside one file. Python is read with `ast`, so a
    name used inside a function is attributed to that function and
    resolved against the module's own definitions; C++ is a lexical pass
    and says so. kind: module|class|function|variable|import. A syntax
    error comes back ok=false with the line, never as an empty picture.)
POST /api/definition {language, code, line, col, path?}
   -> {"found": bool, "path"?, "line"?, "col"?, "message"?}
   (Python via jedi goto. A definition in an installed module is named,
    not opened - the workspace holds only the user's files.)
POST /api/format {language, code} -> {"ok", "code"} | {"ok": false, "message"}
   (black / clang-format CLIs; absence is a refusal naming the tool)
POST /api/search {query, regex?, case?, word?}
   -> {"results": [{path, line, col, length, preview}], "files", "truncated"}
POST /api/replace {query, replacement, regex?, case?, word?, paths?}
   -> {"ok", "replacements", "files": {path: count}}

POST   /api/terminal            -> {"id", "title"}       (a real PTY + bash)
GET    /api/terminal/{id}?since -> {"data", "cursor", "alive", "exit_code"}
POST   /api/terminal/{id}/input {data} / .../resize {rows, cols}
DELETE /api/terminal/{id}

POST   /api/debug {code, filename?, breakpoints: [line]} -> {"id"}
GET    /api/debug/{id}?since    -> {"events": [...], "cursor"}
   (events: stopped{reason,line,stack,locals}, output{stream,data},
    eval{ok,value}, exited{code} - a bdb child process, JSON-lines protocol)
POST   /api/debug/{id}/cmd {op: continue|step|next|return|setbp|eval, ...}
DELETE /api/debug/{id}

GET/POST /api/git/{status,init,stage,unstage,discard,commit,diff,log,
                   branches,checkout}
   (status -> {"ok", "repo", "branch", "changes": [{path, staged, unstaged,
    status}]}; commit refuses an empty message)
```

Runs execute with `python -I` in a subprocess: the server's own modules and
a caller's PYTHONPATH are not importable from user code; installed packages
are, by design.

## Web IDE - `epsilon/server/static/`

Files: `index.html`, `app.css`, `app.js`, `core.js`, `editor.js`, `panes.js`
(NO external CDNs; self-contained). Talks only to the REST API above. The
current UI is a general-purpose programming workbench for Python and C++;
the mathematics workbench is preserved, not deleted, under `static/math/`
(`legacy-workbench.js`, `legacy-index.html`, `legacy-app.css`, `README.md`)
and returns as context-aware tooling in a later phase.

`core.js` holds the registries every surface reads - one registration
serves the menu bar, command palette, keybindings, buttons and context
menus alike (`EpsilonCore = {Settings, Commands, Keys, Menus, ContextMenus,
Diagnostics, fuzzy}`). A command carries `whyDisabled()`; every surface
shows the reason instead of a dead control. User keybindings shadow
defaults and persist; settings are typed, validated, persisted, observable.

`editor.js` is the code editor (`EpsilonEditor.CodeEditor`): a native
textarea for input/IME/undo/a11y with a highlight layer behind it, the
textarea being the one real scroller (gutter and highlight follow by
transform). Pure editing operations live in `EpsilonEditor.EditorOps` and
are node-tested.

Three things keep it fast on a long file, and each is load-bearing:

* **Passes, not repaints.** `render(flags)` requests TEXT / GUTTER /
  CURSOR / WINDOW and coalesces them into one animation frame. Moving
  the caret does not re-tokenise anything.
* **Only the visible lines are in the document.** The textarea holds and
  scrolls the whole text; the painted layers render a window around the
  viewport and are offset to sit under it. Soft wrap breaks that
  arithmetic, so that mode renders everything and takes the cost.
* **Decorations are drawn, not injected.** Occurrence, bracket and find
  ranges are positioned boxes in `.ed-decor`, costing the number of
  ranges rather than a re-parse of the file.

The caret is drawn too, so the cursor style and blink settings mean
something. It is moved by a `requestAnimationFrame` lerp rather than a
CSS transition: a transition restarts from zero velocity on every
keystroke, which is what makes a caret read as steppy while typing. The
easing constant is raised to `dt / 16.667` so it feels the same at 60 or
144 Hz, the loop stops once it arrives, and the blink lives on a child
element so the two never both write `transform`.

`graph.js` renders the dependency graph — a small deterministic force
layout and plain SVG. It knows nothing about the workbench: give it a
container, `{nodes, edges}` and an `onSelect`, and it returns a handle.

`panes.js` owns the editor groups - a binary split tree of tabbed panes.
Views are *existing* DOM elements, re-parented rather than re-created;
elements not currently placed are parked in `#viewVault` (hidden) so they
stay queryable.

```js
EpsilonPanes.init({host, vault, profile, views?, onChange, onTabContext})
EpsilonPanes.openView(id) / closeView(id) / isOpen(id) / activeView()
EpsilonPanes.closeOthers(id) / closeToTheRight(id) / joinAll()
EpsilonPanes.isPinned(id) / togglePin(id)      // pins survive close-others
EpsilonPanes.setDirty(id, bool) / renameView(old, new, title?)
EpsilonPanes.splitPane("row"|"col", viewId?) / toggleMaximize(leafId?)
EpsilonPanes.moveView(viewId, targetLeafId, zone)   // zone: tab|left|right|up|down
EpsilonPanes.setBadge(id, text, tone)               // tone: "err"|"warn"|""
EpsilonPanes.applyProfile(name) / profileNames() / reset()
EpsilonPanes.restoreLayout()   // re-apply the saved tree once views exist
```
Layouts persist in `localStorage["epsilon.workspace.v1"]`. A saved layout or
profile naming a view that is not registered is pruned, never rendered blank.

`app.js` is the workbench: menu bar, command palette/quick open, activity
bar + explorer/search/source-control/run-and-debug sidebars, unified bottom
panel (Terminal | Problems | Output | Debug Console), clickable status bar,
settings and keyboard-shortcuts editors as tabs, theme tokens
(dark/light/high-contrast), and workspace persistence - open tabs, active
file, layout, sidebar, panel, and settings all survive a reload.

## Browser build - `web/`

The deployed page is one editor and nothing around it: no file tree, no
tabs, no panels. Four authored files, under 140 KB in total, no build
step, no wheel, no bridge, no engine.

    index.html    the page
    epsilon.css   ink on paper, light and dark
    editor.js     the editor component and the three language tables
    app.js        the buffers, what can run, run, output

`python3 scripts/build_web.py` does one job: stamp `?v=<hash>` onto each
asset URL, where the hash is taken over the asset contents. index.html
and the scripts have separate cache lifetimes, so a returning visitor
could otherwise hold yesterday's HTML with today's JavaScript; changing
a byte changes every URL, which makes that pairing impossible. The
deploy workflow re-runs it and fails if the committed site differs.

### Three languages, and only one of them runs in a browser

Python, C++ and Java are all fully edited — highlighting, indentation,
comment toggling, bracket pairing and completion each follow the
language, from one table per language in `editor.js`. What can *run* is
decided at boot and never assumed:

* **Python** runs in the tab, on Pyodide. Nothing else is involved.
* **C++ and Java** need a compiler, and a browser has none. At boot the
  page makes one same-origin `GET /api/run/languages`. On GitHub Pages
  that 404s and the page learns it has no compiler; Run is then disabled
  and the output area says which tool is missing and that `epsilon serve`
  on the reader's own machine will compile and run the file for real.
  Served *by* that server — `epsilon serve` mounts this same build at
  `/lite` — the probe answers, and Run posts to `/api/run`, which really
  invokes `g++` and `javac`. Compiler diagnostics come back in the
  checker's shape, so the gutter marks the failing line in all three
  languages.

The refusal is on the page, not only in a tooltip: a greyed-out button
whose reason is hidden is the same as no reason at all.

Two limits are stated in the product rather than hidden:

* Python runs on the page's only thread. A long loop freezes the tab, so
  the UI paints "running" and yields a frame before handing over — the
  pause is the same length either way, but it is legible instead of
  looking like a hang.
* Each language's buffer lives in this browser's localStorage. Nothing
  is synced, and clearing site data removes it.

**Nothing on the typing path may enter Python or the network.**
Completion comes from the buffer's own words and the language's own word
lists, computed in JavaScript. This is not an optimisation, it is the
reason the build exists: an earlier deploy asked a language service per
keystroke and measured 527 ms on the worst key. Measured on this build,
in a 1200-line file with completion on: **16.6 ms median, 18.9 ms worst**
— one frame — and `#include <iostream>`, the line that used to lock the
page, types at 16.7 ms median.

The editor carries three techniques worth keeping:

* a keystroke repaints, a caret move does not — highlighting is cached
  against the exact source it was built from;
* only the visible lines are in the document, offset under the textarea
  that holds and scrolls the whole file;
* the caret is interpolated in a frame loop, not by a CSS transition. A
  transition restarts from zero velocity on every keystroke, which is
  what makes a caret read as steppy. The easing is raised to
  `dt / 16.667` so it feels the same at 60 or 144 Hz, the loop stops on
  arrival, and the blink lives on a child element so the two never both
  write `transform`.

### Ligatures

A rendering layer, never an edit. The file still holds `>=`, and every
keystroke, selection and column number is computed from that text; only
what the eye is shown changes.

The rule that shapes the whole feature is **width**. The textarea
underneath owns hit testing and selection, and it lays every character
on a uniform monospace grid — so a ligature may occupy exactly as many
cells as the source it stands for. Each one is drawn in a fixed `Nch`
box, and a browser test measures the painted line against the grid it
must sit on.

The set is five, and that is the whole set:

    >=  ≥      <=  ≤      !=  ≠      ==  ≡      ->  →

Each means the same thing in all three languages and none of them is
ambiguous. What is deliberately *not* drawn matters as much: `<-` is a
comparison against a negative number, `//` is a comment in two of the
three languages, `<<` is how C++ prints, and `1/2` in source is a
division and not a half. A glyph for any of those would be a claim about
the program that the program does not make. A ligature is also refused
when an operator character sits on either side of it, so `>>=`, `<=>`
and `!==` stay text. Strings and comments are never touched: their
contents are data.

`tests/test_lite_web.py` covers both halves: static checks on the four
files, then the real site in a headless browser with CPython standing in
for Pyodide — boot, run, an error that names its line, per-language
buffers surviving a reload, the honest C++ refusal, completion, and a
typing-latency budget for both Python and C++.

## The full workbench (not deployed)

The pane workbench — menu bar, command palette, terminal, debugger,
source control, dependency graph — is `epsilon/server/static/`, served
by `epsilon serve`. Its browser shell (the wheel, `bridge.py`, `vfs.js`)
is preserved under `archive/browser-full/` and still tested; see the
README there for why the deploy moved off it.

## CLI - `epsilon/cli.py`

`epsilon <cmd>` and `3psilon <cmd>`: new, check, build (=check), run (=check
+ print eval/plot artifacts), test (run `example`/`#check` files under
tests/), repl, prove (=check, theorem report + axiom listing), fmt (v0.1:
normalize line endings/trailing ws only), graph (export SVG plots), export
(--latex|--markdown|--json|--python|--mathml, -o out), docs (markdown docs),
serve (uvicorn launch of epsilon.server.app:app), version.
Manifest: `epsilon.toml` `[project] name/version/description` +
`[dependencies]` (paths). `epsilon new NAME` scaffolds project + example.

## Runtime - `epsilon/runtime/`

```python
run_code(language, code, *, stdin="", timeout=10, filename="") -> RunResult
#   language "python"|"cpp". Fresh subprocess in a temp dir; python runs -I
#   (no PYTHONPATH/script-dir injection); cpp compiles with g++/clang++ then
#   runs. Timeout and 200KB output cap, both reported honestly.
#   RunResult: ok, language, phase, stdout, stderr, exit_code, duration_ms,
#              diagnostics (checker-shaped), message; .as_dict()
available_languages() -> {"python": bool, "cpp": bool}   # the truth only
# pyrepl.PythonRepl: the console's interpreter in a child process - real
#   state between requests, real isolation from the server, JSON-lines
#   protocol on stdout (user output is captured, so it cannot corrupt it),
#   kill-and-respawn on a runaway input.
```

## Cross-pane data model (section 35 / phase 4)

Panes talk through documented spec shapes, never through each other's DOM:

* **plot spec** `{kind, var, lo, hi, series: [{label, x, y}]}` - produced by
  the `plot` command (graphing), by `epsilon.plot()` in a running Python
  program (stdout marker `##epsilon:plot##{json}`, one series per line,
  lifted out of the run output by the run panel), and consumed by the one
  plot renderer.
* **diagnostics** `{severity, message, span, module}` - produced by the
  Epsilon checker, the C++ compiler and Python tracebacks alike; consumed by
  the gutter and the Problems panel.
* **term forms** `{source, latex, mathml, python}` - one term in every form
  a pane needs: `source` is valid Epsilon (CAS input, editor insertion),
  `latex`/`mathml` are display, `python` is runnable (math backend).
  Produced by /api/cas, /api/render, /api/mathify.

`epsilon.plot(x, y=None, *, label="")` lives in the installed package, so a
program using it runs identically inside the IDE (server subprocess or
Pyodide) and outside it - outside, the markers are just lines on stdout.

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
