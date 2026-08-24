"""The Epsilon trusted proof kernel.

Everything outside this package (tactics, CAS, automation, AI suggestions)
is *untrusted*: it may propose terms and proofs, but only the kernel's type
checker decides whether a proof is accepted. Keeping this package small and
auditable is a design requirement (see docs/ARCHITECTURE.md, section 6).

Trusted surface:
- term.py       : term representation and substitution
- env.py        : declarations, environments, axiom-dependency tracking
- reduce.py     : reduction (beta/delta/iota/literal) and definitional equality
- typecheck.py  : the type checker for kernel terms
- inductive.py  : inductive type declarations and recursor generation

Trusted extensions (documented, deliberate):
- exact rational literal arithmetic on Nat/Int/Rat/Real literals
  (the analogue of Lean's kernel GMP acceleration for Nat literals).
"""

from .term import (
    Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit, MVar,
    mk_app, unfold_app, instantiate, lift, abstract_const, PROP, TYPE,
)
from .env import Environment, Declaration, DeclKind, KernelError
from .reduce import whnf, def_eq, normalize
from .typecheck import infer_type, check_type
from .inductive import InductiveSpec, ConstructorSpec, declare_inductive

__all__ = [
    "Term", "Var", "Const", "Sort", "App", "Lam", "Pi", "Lit", "StrLit", "MVar",
    "mk_app", "unfold_app", "instantiate", "lift", "abstract_const", "PROP", "TYPE",
    "Environment", "Declaration", "DeclKind", "KernelError",
    "whnf", "def_eq", "normalize",
    "infer_type", "check_type",
    "InductiveSpec", "ConstructorSpec", "declare_inductive",
]
