"""Epsilon numerical engine.

Floating-point evaluation of kernel Terms plus classic numerical methods
(root finding, adaptive quadrature, RK4) and the numeric verification
oracle. Everything here is *approximate*: results are honest floats, never
presented as symbolic or proven facts (section 27). Theorems certified via
this engine acquire the ``Epsilon.trustedNumeric`` axiom and therefore the
"numeric" status.
"""

from .evaluator import EvalError, eval_term, eval_function
from .roots import find_root
from .integrate import integrate_numeric
from .ode import solve_ode
from .oracle import numeric_oracle

__all__ = [
    "EvalError",
    "eval_term",
    "eval_function",
    "find_root",
    "integrate_numeric",
    "solve_ode",
    "numeric_oracle",
]
