# Epsilon (엡실론)

> **지금 배포되는 Epsilon은 브라우저에서 도는 아주 가벼운 코드 편집기입니다.**
> 파일 트리도, 탭도, 패널도 없습니다 — 코드를 쓰는 곳, 입력, 출력. 그게
> 전부이고, 네 개 파일 140KB 아래입니다.
>
> **Python · C++ · Java** 세 언어를 편집합니다. 문법 강조, 들여쓰기, 주석
> 토글, 괄호 짝, 자동완성이 언어마다 따로 붙어 있습니다. 다만 *실행*은
> 정직하게 갈립니다: Python은 Pyodide로 이 탭 안에서 실제로 돌아가고,
> C++과 Java는 컴파일러가 필요한데 브라우저에는 없습니다. 그래서 배포된
> 페이지에서는 무엇이 없는지 말하고 실행을 거절합니다 — 흉내내지 않습니다.
> 같은 페이지를 `epsilon serve`로 띄우면 `/lite` 에서 g++·javac 를 진짜로
> 불러 세 언어 모두 실행됩니다.
>
> 메뉴 바·커맨드 팔레트·터미널·디버거·소스 컨트롤·의존성 그래프를 갖춘
> 전체 워크벤치는 `epsilon/server/static/`에 그대로 있고 `epsilon serve`로
> 띄웁니다. 수학 서브시스템도 `epsilon/server/static/math/` 아래에
> 보존되어 있습니다. 지운 것은 없습니다 — 페이지에서 내렸을 뿐입니다.

**수학을 하나의 언어로 — 작성하고, 타입 검사하고, 증명하고, 계산하고, 시각화하고, 내보내는 통합 수학 컴퓨팅 환경.**

Epsilon is a mathematics-first language and environment. You write mathematics
in one language, and the same source is simultaneously type-checked, proved by
a trusted kernel, computed with (CAS + numerics), graphed, and exported to
Python / LaTeX / MathML / Lean / JSON — all from one shared mathematical
intermediate representation.

> 브랜드는 **Epsilon**입니다. 내부 Python 구현은 코드네임 *PEpsilon* 이지만,
> 사용자에게 노출되는 이름은 언제나 Epsilon 입니다.

---

## 한눈에 보기 (Korean)

하나의 `.epsl` 파일에서 이 모든 것이 동시에 일어납니다:

```
def f (x : Real) : Real := Real.sin(x) / x

theorem add_comm (a b : Nat) : a + b = b + a := by
  induction b with
  | zero => rw [Nat.add_zero, Nat.zero_add]
  | succ n ih => rw [Nat.add_succ, Nat.succ_add, ih]

theorem sinc_limit : HasLimitAt(f, 0, 1) := by cas

#eval 2 + 3 * 4          -- 14
plot f, x ∈ [-15, 15]
```

- `add_comm` 은 커널이 검증 → **✓ Formally Proven**
- `sinc_limit` 은 CAS가 계산 → **✓ Symbolically Verified** (형식 증명이 *아님*)
- `f(2)` 는 콘솔에서 실행, `f` 는 그래프로, 그리고 Python·LaTeX 로 내보내기 가능

Epsilon 은 **수치적으로 확인한 것과 형식적으로 증명한 것을 절대 같은 것으로
표시하지 않습니다.** 이것이 이 프로젝트의 핵심 가치입니다.

---

## Try it in your browser — no install, no server

The `web/` folder is a **static site**: fork the repo, enable GitHub Pages,
and you have a live editor at your own URL. Four files, no build step.

It edits **Python, C++ and Java**, and it is honest about which of them it
can run. Python runs in the tab, on Pyodide. C++ and Java need a compiler,
which a browser does not have, so there Run is disabled and the page names
the missing tool instead of faking a result. Run `epsilon serve` on your own
machine and open `/lite` and the same page compiles and runs all three for
real, because then there is a `g++` and a `javac` behind it.

## Quickstart (local, with Python)

```bash
pip install -e ".[server,dev]"

epsilon new demo            # scaffold a project
cd demo
epsilon check               # type-check + prove
epsilon prove               # report every theorem's verification status
epsilon repl                # interactive console
epsilon serve               # launch the web IDE at http://127.0.0.1:8000
```

The web IDE is a VS-Code-style editor with an Apple-glass aesthetic: live
checking, a theorem panel with status badges, clickable proof trees, plots,
a dependency graph, and a REPL console — all in the browser.

---

## A short language tour

```
-- definitions
def double (n : Nat) : Nat := 2 * n
def f (x : Real) : Real := Real.sin(x) / x

-- proofs by induction (Formally Proven)
theorem zero_add (a : Nat) : 0 + a = a := by
  induction a with
  | zero => rfl
  | succ n ih => rw [Nat.add_succ, ih]

-- logic with natural-deduction tactics
theorem and_comm (p q : Prop) : p ∧ q → q ∧ p := by
  intro h
  cases h with
  | intro hp hq => split; exact hq; exact hp

-- inductive types, structures, and user-defined operators
inductive Color where
  | red : Color
  | green : Color
  | blue : Color

structure Point where
  x : Real
  y : Real

infixl 65 "⊕" := Nat.add

-- computation, inspection, plotting
#check f                     -- f : ℝ → ℝ
#eval double(21)             -- 42
plot f, x ∈ [-15, 15]
```

Unicode mathematical notation has a full ASCII fallback for every symbol
(`∀`/`forall`, `→`/`->`, `∧`/`/\`, `≤`/`<=`, `λ`/`fun`, …), so you can type
in whichever you prefer.

---

## Verification statuses — never conflated

Every theorem carries an honest label derived from the *axioms its proof
actually depends on*:

| Label | Meaning |
|-------|---------|
| **✓ Formally Proven** | Checked by the trusted kernel. Ordinary mathematical axioms (e.g. classical logic) are listed separately, as in Lean's `#print axioms`. |
| **✓ Symbolically Verified** | Established by the computer-algebra system. Sound in practice, but *not* a kernel proof. |
| **≈ Numerically Verified** | Supported by numerical evidence (sampling, tolerance). Evidence, not proof. |
| **⚠ Heuristic Result** | Contains `sorry` or an unfinished step. |

A proof that touches several trust axioms takes the **worst** of them. A
plugin can add its own decision procedure, but it can never make a result
read as *Formally Proven* — that label means exactly one thing.

---

## Architecture

```
                        ┌──────────────────────┐
                        │   Mathematical IR     │   (epsilon.kernel.term)
                        │  one shared Term type │
                        └───────────┬───────────┘
          ┌─────────────┬───────────┼───────────┬──────────────┐
          ↓             ↓           ↓           ↓              ↓
      Proof kernel     CAS      Numerics    Compiler       Graphing
      (trusted)     (untrusted) (untrusted) (Python AST)   (sampling)
          ↓             ↓           ↓           ↓              ↓
      Proof trees   Symbolic    ≈ results   Python /       SVG / canvas
      + dep graph    math                   LaTeX / Lean
```

The **trusted kernel** (`epsilon/kernel/`) is small and auditable: terms,
reduction, definitional equality, the type checker, and inductive types.
Everything else — the elaborator, tactics, automation, CAS, numerics, AI
suggestions — is *untrusted*: it proposes proof terms, and only the kernel
decides whether a proof is accepted. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

- `docs/LANGUAGE.md` — full surface-syntax and tactic reference
- `docs/TRUST.md` — verification statuses, axiom tracking, reproducibility
- `docs/ROADMAP.md` — status of every feature area
- `docs/CONTRACTS.md` — internal subsystem interfaces

---

## What works today

A trusted dependent-type-theory kernel; a surface language with Unicode +
ASCII notation and user-defined operators; an elaborator with implicit
arguments, numeric-tower coercions, and higher-order pattern unification;
30+ tactics including `induction`, `rw`, `simp`, `calc`, and an `auto`
proof-search tactic; a standard library of logic and arithmetic proved
in-system; a CAS (simplify, differentiate, integrate, limits, Taylor,
solve); an arbitrary-precision numerical engine; exporters to Python (via
real `ast` nodes, never string templating), LaTeX, MathML, JSON, and Lean 4;
2D/graph plotting; a CLI, a REPL, a FastAPI server, and a browser IDE.
Incremental checking, packaging, security limits, and a plugin system round
it out. 270+ tests pass. See `docs/ROADMAP.md` for the honest per-area
status, including what is still axiomatized or planned.

---

## License

Epsilon is released under the **Epsilon Source-Available License (ESAL) v1.0**
(see [LICENSE](LICENSE)):

- **Free** for personal, educational, and academic-research use.
- **No modification** and **no redistribution** (unmodified mirrors excepted).
- **Commercial use requires a paid license.** Contact **igangwoo.unite@gmail.com**.

© 2026 igangwoo. All rights reserved.
