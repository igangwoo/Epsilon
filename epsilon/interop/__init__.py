"""Interoperability with other mathematical systems (spec section 28).

- `lean`: export Epsilon statements to Lean 4 and re-check them with an
  external `lake env lean`, plus import Lean declarations as tracked axioms.

Interoperability never launders trust: a statement another system accepts
is corroboration, and a statement imported from another system is an
assumption here. Only Epsilon's own kernel produces `✓ Formally Proven`.
"""

from .lean import (LeanBackend, term_to_lean, decl_to_lean, module_to_lean,
                   import_lean_declarations)

__all__ = ["LeanBackend", "term_to_lean", "decl_to_lean", "module_to_lean",
           "import_lean_declarations"]
