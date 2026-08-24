"""Computer algebra system (product spec section 12).

Operates on the shared kernel `Term` IR: every public function takes and
returns kernel Terms. Internally it uses a private multivariate-polynomial /
rational normal form over a set of opaque "atoms" (variables, sin(x),
exp(x), ... - any non-arithmetic subterm), converts a Term into that form,
manipulates it, and converts back.

The CAS is *untrusted*. Nothing it does is a proof. When a CAS result is
used to close a goal (the `cas` tactic / `cas_oracle`), the theorem is
labeled `✓ Symbolically Verified`, never `✓ Formally Proven` - the honest
distinction the product requires (section 27).
"""

from .engine import (simplify, expand, factor, collect, substitute,
                     differentiate, integrate, limit_of, taylor, solve_eq,
                     symbolic_eq, series_expansion, partial_fraction)
from .oracle import cas_oracle

__all__ = [
    "simplify", "expand", "factor", "collect", "substitute",
    "differentiate", "integrate", "limit_of", "taylor", "solve_eq",
    "symbolic_eq", "series_expansion", "partial_fraction", "cas_oracle",
]
