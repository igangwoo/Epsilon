"""The user-facing mathematical naming layer.

Epsilon keeps two names for every library result:

* the **internal identifier** (`Nat.add_comm`) - short, stable, what the
  kernel stores and what proofs have always been able to cite; and
* the **mathematical name** (`NaturalNumbers.Addition.Commutativity`) -
  what someone who knows mathematics but not this prover would look for.

Neither replaces the other. The internal identifier stays because it is
what the implementation, the axiom tracker, and existing proofs use; the
mathematical name exists so nobody has to memorise `le_of_lt` to find
"the weak order follows from the strict one".

Library results declare their mathematical name in source, next to the
theorem, with `@[name "..."]`. Objects the kernel creates in Python
(constructors, primitive operations) have no source line to carry an
attribute, so their names live in `CORE_NAMES` below and are applied when
a session starts - which also keeps presentation concerns out of the
trusted kernel.
"""

from __future__ import annotations

import re

#: Mathematical names for objects declared by the kernel bootstrap, which
#: have no `.epsl` source line to carry an `@[name ...]` attribute.
CORE_NAMES: dict[str, str] = {
    # natural numbers
    "Nat": "NaturalNumbers",
    "Nat.zero": "NaturalNumbers.Zero",
    "Nat.succ": "NaturalNumbers.Successor",
    "Nat.add": "NaturalNumbers.Addition",
    "Nat.sub": "NaturalNumbers.TruncatedSubtraction",
    "Nat.mul": "NaturalNumbers.Multiplication",
    "Nat.div": "NaturalNumbers.FloorDivision",
    "Nat.mod": "NaturalNumbers.Remainder",
    "Nat.pow": "NaturalNumbers.Power",
    "Nat.le": "NaturalNumbers.LessThanOrEqual",
    "Nat.lt": "NaturalNumbers.LessThan",
    "Nat.gcd": "NaturalNumbers.GreatestCommonDivisor",
    # other number systems
    "Int": "Integers",
    "Rat": "Rationals",
    "Real": "RealNumbers",
    "Complex": "ComplexNumbers",
    "Real.pi": "RealNumbers.Pi",
    "Real.euler": "RealNumbers.EulerNumber",
    "Real.sqrt": "RealNumbers.SquareRoot",
    "Real.abs": "RealNumbers.AbsoluteValue",
    "Real.exp": "Exponential",
    "Real.log": "Logarithm",
    "Real.sin": "Trigonometry.Sine",
    "Real.cos": "Trigonometry.Cosine",
    "Real.tan": "Trigonometry.Tangent",
    "Complex.re": "ComplexNumbers.RealPart",
    "Complex.im": "ComplexNumbers.ImaginaryPart",
    "Complex.conj": "ComplexNumbers.Conjugate",
    "Complex.abs": "ComplexNumbers.Modulus",
    "Complex.I": "ComplexNumbers.ImaginaryUnit",
    # logic
    "Eq": "Equality",
    "Eq.refl": "Equality.Reflexivity",
    "Ne": "Inequality",
    "Not": "Negation",
    "And": "Conjunction",
    "And.intro": "Conjunction.Introduction",
    "Or": "Disjunction",
    "Or.inl": "Disjunction.LeftIntroduction",
    "Or.inr": "Disjunction.RightIntroduction",
    "Iff": "Equivalence",
    "Iff.intro": "Equivalence.Introduction",
    "Exists": "ExistentialQuantifier",
    "Exists.intro": "ExistentialQuantifier.Introduction",
    "True": "Truth",
    "False": "Falsity",
    "Bool": "Booleans",
    # analysis primitives
    "limit": "Limits.Value",
    "HasLimitAt": "Limits.TendsTo",
    "deriv": "Derivative",
    "HasDerivAt": "Derivative.HasDerivativeAt",
    "integral": "Integration.DefiniteIntegral",
    "Continuous": "Continuity",
    "ContinuousAt": "Continuity.AtAPoint",
    # sets and functions
    "Set": "Sets",
    "Set.mem": "Sets.Membership",
    "Set.subset": "Sets.Subset",
    "setOf": "Sets.Builder",
    "Function.comp": "Functions.Composition",
    "Function.id": "Functions.Identity",
    "Vector": "LinearAlgebra.Vector",
    "Matrix": "LinearAlgebra.Matrix",
}

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def humanize(display_name: str) -> str:
    """Turn a mathematical name into a human-readable label.

    ``"NaturalNumbers.Addition.Commutativity"`` becomes
    ``"Natural Numbers · Addition Commutativity"``: dots separate the
    subject from the property, and run-together words are split apart.
    """
    if not display_name:
        return ""
    segments = display_name.split(".")
    if len(segments) > 1:
        subject = _split_words(segments[0])
        rest = " ".join(_split_words(s) for s in segments[1:])
        return f"{subject} · {rest}"
    return _split_words(segments[0])


def _split_words(segment: str) -> str:
    return _CAMEL_BOUNDARY.sub(" ", segment)


def apply_core_names(env) -> None:
    """Register `CORE_NAMES` for the declarations that exist in `env`.

    Silently skips names whose declaration is absent (a trimmed-down
    bootstrap is still a valid environment) and names that would collide,
    since a presentation layer must never be able to break a session.
    """
    from .kernel.env import KernelError
    for internal, display in CORE_NAMES.items():
        if not env.contains(internal):
            continue
        try:
            env.register_display_name(internal, display)
        except KernelError:
            continue
