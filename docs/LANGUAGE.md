# The Epsilon language

A reference for the surface syntax as implemented in `epsilon/syntax` and
elaborated by `epsilon/elab`.

## Lexical structure

### Unicode and ASCII

Every mathematical symbol has an ASCII fallback that lexes identically:

| Unicode | ASCII | Meaning |
|---------|-------|---------|
| `→` | `->` | function type / implication |
| `↔` | `<->` | iff |
| `∀` | `forall` | universal quantifier |
| `∃` | `exists` | existential quantifier |
| `λ` | `fun` | lambda |
| `∧` | `/\` | conjunction |
| `∨` | `\/` | disjunction |
| `¬` | `not` | negation |
| `≠` | `!=` | inequality |
| `≤` `≥` | `<=` `>=` | order |
| `∈` `∉` | `in` | membership |
| `⊆` | `subseteq` | subset |
| `×` | `><` | product type |
| `·` | `*` | multiplication |
| `∘` | `circ` | composition |
| `←` | `<-` | reverse-rewrite marker |
| `√` | | square root |

Greek letters (`α`, `β`, `π`, …), blackboard types (`ℕ ℤ ℚ ℝ ℂ`), and
subscripts are valid in identifiers. Any Unicode symbol character can be
used as a user-defined operator.

### Comments

- `-- line comment`
- `/- block comment, /- nestable -/ -/`
- `/-- doc comment -/` — attaches to the following declaration.

### Literals

- Integers: `42`. Decimals: `3.14` (stored as an **exact** `Fraction`,
  so `3.14 = 157/50`).
- Strings: `"…"` with `\n \t \" \\` escapes.
- A bare numeric literal defaults to `Nat`; in a `Real`/`Rat`/… position it
  is retyped by coercion, and a decimal defaults to `Rat`.

## Commands

```
def name (binders) : Type := expr        -- definition (define is a synonym)
constant name : Type                     -- opaque constant
axiom name (binders) : Prop              -- assumed statement (tracked)
theorem name (binders) : Prop := proof   -- also lemma/proposition/corollary
example : Prop := proof                   -- anonymous checked statement
inductive Name where | c1 : T1 | ...     -- inductive type
structure Name where field : T ...        -- record type (+ projections)
notation:  infixl P "op" := target        -- also infixr / prefix
import module.path                        -- load a module
namespace N ... end N                     -- name scope
open N                                     -- bring names into scope
plot e1, e2, x ∈ [lo, hi]                 -- register plots
#check e     #eval e                       -- inspect / evaluate
```

Binders come in explicit `(x : T)` and implicit `{x : T}` forms; multiple
names share a type: `(a b c : Nat)`.

## Expressions and precedence

From loosest to tightest binding:

| Prec | Operators | Assoc |
|------|-----------|-------|
| 20 | `↔` | right |
| 25 | `→` | right |
| 30 | `∨` | right |
| 35 | `∧` | right |
| 40 | `¬` (prefix) | |
| 50 | `= ≠ < ≤ > ≥ ∈ ⊆ ==` | none |
| 65 | `+ -` | left |
| 70 | `* / %` | left |
| 72 | `×` | right |
| 75 | unary `-` | |
| 76 | `∘` | right |
| 80 | `^` | right |
| 85 | `√` (prefix) | |
| 100 | application `f x`, `f(x, y)` | left |

Binders: `∀ (x : T), p` · `∃ (x : T), p` · `λ (x : T) => e` (or `, e`).
Other forms: `if c then a else e`, tuples `(a, b)`, anonymous constructors
`⟨a, b⟩`, set-builder `{ x : T | p }`, type ascription `(e : T)`.

User-defined operators declared with `infixl`/`infixr`/`prefix` are usable
immediately, in the same file and in later sessions.

## Proofs

A proof is either a **term** (`:= expr`) or a **tactic block** (`:= by …`).
Tactics on the same line are separated by `;`; otherwise the block continues
on lines indented deeper than the tactic (the layout rule).

### Tactic reference

| Tactic | Effect | Example |
|--------|--------|---------|
| `intro h` / `intros` | introduce ∀/→ binders | `intro h` |
| `exact e` | close with a term of the goal's type | `exact hp` |
| `apply f` | apply a lemma, leaving its hypotheses | `apply h` |
| `assumption` | close from a matching hypothesis | `assumption` |
| `rfl` | close `=`/`↔` by definitional equality | `rfl` |
| `symm` | turn `a = b` into `b = a` | `symm` |
| `rw [h, ← h2]` | rewrite with equations (← reverses) | `rw [ih]` |
| `simp [lemmas]` | normalize + rewrite with `@[simp]` lemmas | `simp` |
| `unfold f` | unfold definitions | `unfold double` |
| `induction x with` | induct with per-constructor cases + IH | see below |
| `cases h with` | case-split an inductive hypothesis | see below |
| `constructor` / `split` | apply the matching constructor | `split` |
| `left` / `right` | prove a disjunct | `left` |
| `exists w` | supply an ∃ witness | `exists 3` |
| `have h : P := …` | introduce a proved fact | `have h : … := by …` |
| `show P` | restate the goal definitionally | `show a = a` |
| `calc … := …` | chained equational reasoning | see below |
| `decide` / `norm_num` | close a decidable goal by computation | `decide` |
| `trivial` | try rfl / assumption / decide | `trivial` |
| `exfalso` | reduce any goal to `False` | `exfalso` |
| `contradiction` | close from contradictory hypotheses | `contradiction` |
| `auto` | search for a proof from hypotheses + lemmas | `auto` |
| `cas` | close via the CAS oracle → Symbolically Verified | `cas` |
| `numeric` | close via the numeric oracle → Numerically Verified | `numeric` |
| `ring` / `linarith` | ring/linear normalization (fall back to CAS) | `ring` |
| `sorry` | admit → Heuristic Result (never proven) | `sorry` |
| `clear h` | drop hypotheses | `clear h` |

```
theorem add_comm (a b : Nat) : a + b = b + a := by
  induction b with
  | zero => rw [Nat.add_zero, Nat.zero_add]
  | succ n ih => rw [Nat.add_succ, Nat.succ_add, ih]

theorem chain (a b c : Nat) (h1 : a = b) (h2 : b = c) : a = c := by
  calc a = b := by exact h1
       _ = c := by exact h2
```

## Known limitations (v0.1)

These are honest gaps, not bugs — the messages come straight from the code:

- No universe polymorphism (a fixed `Prop`/`Type n` hierarchy).
- `Eq` is over `Type`; equality of large types is not universe-polymorphic.
- `rw`/`simp` **at a hypothesis** is not yet supported (goal only).
- Higher-order unification is limited to the Miller pattern fragment, so
  `apply` on genuinely ambiguous higher-order goals (e.g. `Continuous.comp`
  without explicit functions) needs the functions supplied.
- Indexed inductive families beyond the built-in `Eq` are not supported.
- `calc` supports `=` chains (mixed-relation chains are future work).
- Parameterized-structure projections are limited.
- Recursive definitions are written via `Nat.rec`/recursors, not by
  self-reference (which the kernel rejects).

See `docs/ROADMAP.md` for the roadmap.
