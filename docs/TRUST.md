# Trust, verification, and reproducibility

Epsilon's central promise: **it never presents a numerically-checked or
heuristic result as a formal proof.** This document explains how that
promise is kept mechanically.

## The four verification statuses

Every theorem has exactly one status, derived from the axioms its proof
*transitively depends on*:

| Status | Label | What it means |
|--------|-------|---------------|
| `proven` | ✓ Formally Proven | The kernel type-checked the proof term. |
| `symbolic` | ✓ Symbolically Verified | A symbolic decision procedure (CAS) established it. |
| `numeric` | ≈ Numerically Verified | Numerical evidence supports it (sampling, tolerance). |
| `heuristic` | ⚠ Heuristic Result | The proof contains `sorry` or an unfinished step. |

The ordering, worst-to-best, is `heuristic < numeric < symbolic < proven`.
When a proof depends on several trust axioms, its status is the **worst** of
them — trust does not average out.

## How the status is computed

The kernel tracks, for every declaration, the transitive set of **axioms**
it depends on (`Environment.axioms_of`). Some axioms are marked as *trust
axioms* with the status they cap results at:

- `Epsilon.sorry` → `heuristic`
- `Epsilon.trustedNumeric` → `numeric`
- `Epsilon.trustedCAS` → `symbolic`

`verification_status(name)` walks the axiom set and returns the worst trust
level found; if none is present, the result is `proven`.

Ordinary *mathematical* axioms (the law of excluded middle, the field axioms
for ℝ, the axioms of the analysis library) are **not** trust axioms: a
theorem using them is still Formally Proven, and the axioms are listed
alongside it — exactly like Lean's `#print axioms`. This lets you see, for
any theorem, precisely which mathematical assumptions it rests on:

```
✓ Formally Proven  Classical.byContradiction
    depends on axioms: Classical.em
```

## Oracle tactics

`cas` and `numeric` do not produce kernel proofs. Each closes its goal by
applying its trust axiom to the goal proposition:

```
theorem sinc_limit : HasLimitAt(f, 0, 1) := by cas
--   ↓ elaborates to
theorem sinc_limit : HasLimitAt(f, 0, 1) := Epsilon.trustedCAS (HasLimitAt(f, 0, 1))
```

The kernel accepts this term (the axiom has type `∀ (p : Prop), p`), so the
theorem is added — but because `Epsilon.trustedCAS` is a trust axiom, the
theorem is reported as **✓ Symbolically Verified**, never Formally Proven.
The oracle only *fires* when the CAS is actually confident; otherwise it
returns a failure and the proof does not close.

## Plugins cannot launder trust

A plugin registers a decision procedure with `register_oracle(name, fn,
axiom, status=…)`. The axiom is installed as a trust axiom via
`Environment.register_trust_axiom`, which **refuses `status="proven"`**. So
no plugin — however it is written — can make its results read as Formally
Proven. The only path to that label is a term the kernel itself checked.

## Auditing a development

`epsilon.security.audit_axioms(session)` reports every axiom a set of modules
introduces and every theorem whose status is below Formally Proven — run it
before depending on a package, since an axiom is a hole a dependency can put
in your theorems without changing their statements. `Session.dependency_graph`
traces theorem → lemma → … → axiom so you can see exactly what a result rests
on.

## Reproducibility

`Session.reproducibility_info()` records:

- the Epsilon and language versions,
- the loaded modules,
- and, per theorem, a **content hash** (of its statement and proof term) plus
  its verification status.

Because the kernel is deterministic and the hash covers both statement and
proof, re-checking the same sources on the same version reproduces the same
hashes and statuses — a checkable record of what was proven and how.

Every GitHub / external-tool interaction preserves this discipline: Lean
export emits statements with `sorry` placeholders (an Epsilon proof term is
not a Lean proof); Lean *import* brings statements in as tracked axioms; and
an external Lean re-check is recorded as *corroboration*, not as an Epsilon
kernel proof.
