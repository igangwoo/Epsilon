"""Epsilon: a unified mathematical computing environment.

Epsilon is a mathematics-first language and environment: write mathematics
in one language, then type-check it, prove it, compute with it, graph it,
and export it (Python / LaTeX / MathML / JSON) - all from a single shared
mathematical intermediate representation (the kernel Term IR).

Internal architecture note: this package is the Python implementation of
the Epsilon toolchain (internally "PEpsilon"). The public brand is Epsilon.

Layers
------
- ``epsilon.kernel``   : minimal trusted proof kernel (terms, reduction,
                         definitional equality, type checking, inductives).
- ``epsilon.syntax``   : lexer + parser for the surface language (Unicode
                         mathematical notation with full ASCII fallbacks).
- ``epsilon.elab``     : elaborator (surface AST -> kernel terms) and the
                         tactic engine. Tactics *construct* proof terms;
                         only the kernel decides whether a proof is valid.
- ``epsilon.cas``      : computer algebra on kernel terms.
- ``epsilon.numeric``  : arbitrary-precision / float numerical engine.
- ``epsilon.exporters``: LaTeX, MathML, Markdown, JSON, Python-AST codegen.
- ``epsilon.graphing`` : plot sampling / plot-spec generation.
- ``epsilon.project``  : the single check pipeline shared by CLI, REPL,
                         server and IDE (section 36: one common model).
"""

__version__ = "0.1.0"
BRAND = "Epsilon"
INTERNAL_CODENAME = "PEpsilon"
LANGUAGE_VERSION = "0.1"
FILE_EXTENSION = ".epsl"
