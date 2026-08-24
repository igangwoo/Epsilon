"""Elaboration: surface AST -> kernel terms, plus the tactic engine.

Everything in this package is *untrusted* automation: it constructs kernel
terms and proof candidates, but the final word on every declaration is the
kernel type checker (epsilon.kernel.typecheck.add_decl).
"""

from .context import ElabContext, ElabError
from .elaborator import Elaborator

__all__ = ["ElabContext", "ElabError", "Elaborator"]
