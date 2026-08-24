# Epsilon roadmap & feature status

Honest status of every area from the product specification.
✅ works today · 🔶 partial · 📋 planned.

## 1. Mathematics language
✅ DSL, lexer, parser, AST, Unicode + ASCII syntax, operator precedence,
user-defined operators, function/variable/constant/anonymous-function
definitions, pattern-ish `cases`, conditionals, recursion (via recursors),
modules/import, namespace, attributes (`@[simp]`), notation/fixity.
🔶 macro system / syntax-extension (notation only). 📋 general CST↔AST
round-trip, full pattern matching.

## 2. Type system
✅ Nat, Int, Rat, Real, Complex, Bool, String, Set, Function, Tuple (Prod),
Vector/Matrix/Sequence (opaque), record/structure, ADTs (inductive),
dependent types, universe hierarchy, type inference, numeric coercion,
typeclass-style resolution via implicits. 🔶 generics/polymorphism (implicit
type args, no universe polymorphism), subtype/refinement (via propositions).
📋 first-class typeclasses, definitional refinement types.

## 3. Foundations
✅ classical + constructive logic, propositional + first-order logic,
equality, quantifiers, user-defined axioms, axiom-dependency tracking,
consistency-relevant metadata, per-theorem axiom reporting. 🔶 set theory
(typed sets; not ZF/ZFC object theory). 📋 foundation-selection system,
foundation-specific compatibility flags.

## 4. Definitions
✅ definition, recursive/inductive definition (via recursors), structure
definition, notation definition, unfold, definition search, dependency
graph, documentation. 🔶 fold. 

## 5. Proposition / lemma / theorem
✅ proposition/lemma/theorem/corollary/example, namespaces, metadata,
tagging (`@[simp]`, attrs), search, indexing, dependency tracking. Same core
representation for statements and proofs (propositions-as-types).

## 6. Proof kernel
✅ minimal trusted kernel, proof terms, proof checking, inference rules,
substitution, unification, definitional equality, normalization/reduction,
equality reasoning, contradiction, implication, conjunction, disjunction,
quantifier intro/elim, equality intro/elim, induction, recursion, dependent
elimination, kernel soundness tests. Automation cannot make the kernel
accept a false proof.

## 7. Proof language
✅ term-style + tactic-style, natural-deduction tactics, apply/exact/intro/
assumption/constructor/rewrite/simp/rw/cases/induction/exists/have/show/calc,
automated proof search (`auto`), custom-tactic API (plugins). 🔶 `simp`/`rw`
at hypotheses. 📋 richer tactic combinators.

## 8. Proof visualization
✅ proof tree, natural-deduction / sequent style, inference-rule labels,
premise/conclusion links, node collapse/expand, source↔node spans, failed/
open-proof nodes, SVG + LaTeX (bussproofs) + JSON export, IDE canvas trees.
🔶 proof animation. 

## 9. Proof dependency graph
✅ theorem/lemma/definition/axiom DAG, imported-theorem edges, transitive
dependency, theorem→axiom tracing, interactive force-directed IDE graph,
filtering by module/kind. 🔶 unused/circular-dependency detection surfaced
in UI (data available).

## 10. Mathematical library
✅ basic logic, natural numbers (proved), integer/rational/real/complex
arithmetic (axiomatized field structure), sets. 🔶 algebra/groups/rings/
fields, linear algebra, topology, analysis (axiomatized starting points).
📋 measure theory, probability, number theory, geometry, combinatorics as
developed theories.

## 11. Calculus engine
✅ symbolic limits (with L'Hôpital), continuity predicates, derivatives,
integrals (definite/indefinite), Taylor series, ε-δ definitions
(axiomatized). 🔶 partial/directional derivatives, gradient/Jacobian/Hessian,
multiple/line/surface integrals, Fourier series, convergence tests.

## 12. CAS
✅ simplify, expand, factor (partial), collect, substitute, solve (linear +
quadratic), differentiate, integrate, limit, series expansion, exact
arithmetic. 🔶 polynomial systems, inequalities, partial fractions, symbolic
linear algebra, eigen-decomposition, symbolic assumptions.

## 13. Numerical engine
✅ arbitrary precision, floating point, numerical differentiation/
integration, root finding, ODE solver (RK4). 🔶 interval arithmetic, PDE
framework, optimization, interpolation, numerical linear algebra, Monte
Carlo, distributions.

## 14. Graphing
✅ 2D Cartesian, function plots, ranges, pole masking, SVG + canvas render,
crosshair readout, legends, axes/grid. 🔶 parametric/polar/implicit/contour/
surface/3D, vector fields, statistical/data plots, animation, sliders,
zoom/pan (graph view), export PDF.

## 15. Geometry
🔶 points/vectors/coordinate systems (via structures). 📋 lines, segments,
circles, polygons, conics, transformations, constraints, dynamic geometry,
construction history, geometric proof support.

## 16. REPL / console
✅ REPL, variable/type inspection, symbolic + numerical evaluation, theorem
checking, proof experimentation, history, multi-line input, pretty-printing,
console↔editor via the shared session. 🔶 autocomplete in the terminal REPL
(available in the IDE console).

## 17. Compiler
✅ lexer, parser, elaborator, type checker, IR (kernel terms), incremental
compilation, caching/memoization. 🔶 optimizer, constant folding, DCE,
symbolic/numeric optimization passes, pluggable backends.

## 18. Python backend
✅ Python-AST generation (real `ast` nodes → `ast.unparse`, never string
templating), Python source export, math/NumPy/SymPy backends, automatic
imports, type/function conversion, numeric + symbolic code, executable
output. 🔶 matrix/plot conversion, full project export.

## 19. Other export
✅ LaTeX, MathML (presentation), Markdown, JSON mathematical representation,
Python, SVG, Lean. 🔶 HTML, PDF, Jupyter notebook.

## 20-21. IDE & editor intelligence
✅ project explorer, editor, tabs, symbol/theorem/proof/graph/console/
problems panels, command palette, shortcuts, dark/light theme, syntax +
semantic highlighting, hover type/doc, go-to-definition, find-references,
rename-ready symbol index, diagnostics, proof-state display, math rendering.
🔶 split editor, inline code actions/quick-fixes, full rename refactor.

## 22. Pretty printer
✅ source↔pretty notation, fractions, super/subscripts, matrices, integrals,
sums/products, limits, Greek letters, set/logic/vector notation, cases,
2D Unicode layout. 🔶 aligned equations, automatic reflow.

## 23. Documentation system
✅ doc comments, theorem/definition docs, generated Markdown API docs,
notation rendering, cross-references, source + dependency links, searchable.

## 24-25. Package manager & project management
✅ manifest (`epsilon.toml`), dependency declaration, semantic versioning,
resolution with cycle/conflict detection, lockfile, local + git deps,
project creation/templates, modules/namespaces/imports, build/test/format/
lint, configuration, reproducible metadata. 🔶 registry, binary cache.

## 26. Testing
✅ unit/parser/typechecker/kernel/proof/CAS/numeric/compiler/Python-export/
graphing tests, golden + regression tests, 270+ passing. 🔶 fuzz +
property-based testing.

## 27. Reproducibility / verification
✅ compiler/language/library version recording, foundation + axiom-dependency
recording, theorem + proof hashes, deterministic checking, the four honest
verification statuses (never conflated). 🔶 fully deterministic multi-machine
builds.

## 28. Interoperability
✅ Lean import/export architecture, Lean proof-backend hook, MathML, LaTeX,
Python, SymPy/NumPy codegen, JSON, web API. 🔶 SciPy, Jupyter, CSV. Lean
acceptance is corroboration, not an Epsilon kernel proof.

## 29. AI integration
✅ proof suggestion, tactic suggestion, error explanation (rule-based),
theorem/definition search, proof search, code generation, Python conversion.
📋 natural-language → math/theorem, graph explanation (LLM-backed). Any
AI-proposed proof is Formally Proven **only** if the kernel checks it.

## 30. Collaboration
✅ Git-friendly text format, mathematical diff (statement vs proof changes,
status regressions, new axiom dependencies), theorem/proof/dependency diff.
🔶 conflict resolution helpers, comments, review system. 📋 collaborative
editing.

## 31. Security
✅ resource limits (time/memory/recursion), source-size limits, import
sandboxing, untrusted-theorem isolation via axiom audit, dependency-integrity
via hashes. 🔶 full sandboxed code execution, package permission system.

## 32. Performance
✅ incremental parsing/type-checking/proof-checking (prefix-hash reuse),
memoization, lazy evaluation, dependency-graph optimization. 🔶 parallel
theorem checking, CAS caching tuning, GPU/numerical acceleration.

## 33. CLI
✅ new, build, run, check, test, fmt, lint, repl, prove, graph, export,
docs, serve, version. `3psilon` alias included.

## 34. Plugin system
✅ plugin API, custom tactics, CAS/oracle plugins, compiler/proof backend
plugins, visualization plugins, entry-point discovery. 🔶 editor/package
plugins.

## 35-37. UI/UX & unified experience
✅ modern glass IDE, mathematical typography, responsive panels, keyboard-
first workflow, command palette, searchable everything, theming, one shared
mathematical object model feeding kernel/CAS/compiler/visualization, and the
end-to-end single-file experience (define → check → prove → compute → plot →
run → export) demonstrated in `examples/showcase.epsl`. 🔶 accessibility
polish, customizable workspace layout.
