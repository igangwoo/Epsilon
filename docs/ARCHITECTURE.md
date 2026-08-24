# Epsilon architecture

Epsilon is layered so that a small, auditable **trusted kernel** is the only
component that can certify a proof. Everything above it is convenience and
automation that must, in the end, hand the kernel a proof term it accepts.

```
  surface syntax   ──lex/parse──▶  surface AST (CST)
        │                                │
        │                          elaboration          ← untrusted
        │                     (implicits, coercions,
        │                      unification, tactics)
        ▼                                │
   one shared Term IR  ◀─────────────────┘
        │
        ▼
  ┌───────────────┐   the trust boundary: add_decl type-checks every
  │ trusted kernel │   declaration; nothing enters the environment
  └───────────────┘   without passing the kernel type checker
        │
   ┌────┴─────┬──────────┬───────────┬──────────┐
   ▼          ▼          ▼           ▼          ▼
 Proof      CAS      Numerics    Compiler    Graphing
 trees   (symbolic) (≈ results) (Python AST) (sampling)
```

## The trusted kernel (`epsilon/kernel/`)

This is the only trusted code. It is deliberately small.

- **`term.py`** — one term language for expressions, types, propositions,
  and proofs (propositions-as-types). de Bruijn indices; `Sort 0 = Prop`,
  `Sort 1 = Type`, …; numeric literals `Lit(Fraction, tyname)`.
- **`env.py`** — declarations, environments, and transitive axiom-dependency
  tracking. `verification_status` is derived here from the axiom set.
- **`reduce.py`** — β/δ/ι reduction, definitional equality with η, and exact
  rational arithmetic on numeric literals.
- **`typecheck.py`** — the type checker. `add_decl` is the trust boundary:
  every definition, axiom, and theorem is checked here before it is added.
- **`inductive.py`** — inductive type declarations with a strict-positivity
  check and generated recursors, following CIC's large-elimination rule.
- **`bootstrap.py`** — the core objects (Bool, Nat, Eq, logic connectives,
  Prod/Sum/List, numeric towers, analysis constants), all kernel-checked on
  startup.

### What is trusted, precisely

The kernel trusts: term representation and substitution, reduction, the type
checker, the inductive schema, and **one documented extension** — exact
rational arithmetic on `Nat`/`Int`/`Rat`/`Real` literals inside the reducer
(the analogue of Lean's kernel-accelerated `Nat` literals). Everything else
is outside the trust boundary.

### What is NOT trusted

The elaborator, the tactic engine, automated proof search, the CAS, the
numerical engine, the exporters, and any AI/plugin suggestion. These build
candidate terms; the kernel is the judge. A bug in a tactic can at worst
produce a term the kernel *rejects* — it cannot make the kernel accept a
false theorem.

## Elaboration (`epsilon/elab/`)

Turns surface AST into kernel terms.

- **`context.py`** — locals (as fresh opaque constants), metavariables,
  first-order unification with **Miller-pattern (higher-order) unification**
  for the `?f x = t` fragment, and numeric-tower coercions
  (Nat → Int → Rat → Real → Complex).
- **`elaborator.py`** — expression elaboration with implicit-argument
  insertion, operator resolution by type, and command processing.
- **`tactics.py`** — the tactic engine. Tactics manipulate a goal state and
  *construct* a proof term with one metavariable per open goal; the finished
  term is handed to the kernel. Oracle tactics (`cas`, `numeric`) close goals
  with tracked trust axioms so the result is honestly labeled.
- **`commands.py`** — the single command processor shared by CLI, REPL,
  server, and IDE.

## Tactic → kernel flow

1. A theorem's `by` block runs tactics, producing a proof term with holes
   (`MVar`s) for the remaining goals.
2. When every goal is closed, the term is fully instantiated and handed to
   `add_decl`.
3. `add_decl` type-checks the term against the theorem statement. If it type
   checks, the theorem is added and its verification status is computed from
   the axioms it transitively depends on.
4. If the kernel rejects the term, the theorem is *not* proven — the tactic
   engine gets no special privilege.

## Oracle tactics and tracked trust

`cas` and `numeric` cannot produce kernel proofs. Instead each closes its
goal with a *trust axiom* (`Epsilon.trustedCAS`, `Epsilon.trustedNumeric`),
registered in the environment with the status it caps results at. Any
theorem that transitively uses such an axiom is reported as Symbolically /
Numerically Verified — never Formally Proven. `sorry` works the same way
(`Epsilon.sorry` → Heuristic). Plugins register their own oracle axioms the
same way and are subject to the same rule.

## Session and modules (`epsilon/project.py`)

`Session` is the one shared pipeline. It owns the kernel environment, loads
the standard library, resolves `import`s, checks source with per-command
error recovery, and exposes the theorem list, definition list, dependency
graph, and reproducibility info that the CLI/REPL/server/IDE all consume.

## Subsystem map

| Area | Package | Notes |
|------|---------|-------|
| Kernel | `epsilon/kernel` | trusted |
| Syntax | `epsilon/syntax` | lexer, surface AST, Pratt parser |
| Elaboration | `epsilon/elab` | untrusted; tactics, unification |
| Pipeline | `epsilon/project.py` | shared Session |
| Automation | `epsilon/automation.py` | proof search, suggestions, error explain |
| CAS | `epsilon/cas` | symbolic math |
| Numerics | `epsilon/numeric` | arbitrary precision + float |
| Exporters | `epsilon/exporters` | LaTeX, MathML, Markdown, JSON, Python AST |
| Interop | `epsilon/interop` | Lean 4 export/import/re-check |
| Graphing | `epsilon/graphing` | sampling, SVG |
| Proof viz | `epsilon/prooftree.py` | text / sequent / SVG / LaTeX |
| Editor intel | `epsilon/intelligence.py` | completions, hover, search |
| Incremental | `epsilon/incremental.py` | prefix-hash reuse, memoization |
| Security | `epsilon/security.py` | resource limits, import policy, audits |
| Packaging | `epsilon/package.py` | manifests, semver, lockfiles |
| Plugins | `epsilon/plugins.py` | tactics/oracles/backends registry |
| Pretty math | `epsilon/prettymath.py` | 2D Unicode layout |
| CLI / REPL | `epsilon/cli.py`, `repl.py` | |
| Server / IDE | `epsilon/server` | FastAPI + vanilla-JS IDE |

The precise inter-subsystem interfaces are in
[CONTRACTS.md](CONTRACTS.md).
