"""Epsilon exporters: LaTeX, MathML, Markdown, JSON, Python-AST codegen.

Every exporter renders (or parses, for JSON) the shared kernel `Term` IR
(`epsilon.kernel.term`) - none of them invent a parallel expression type.
See ``docs/CONTRACTS.md`` for the full public interface.

    latex.term_to_latex(env, t) -> str
    latex.decl_to_latex(env, name) -> str
    latex.module_to_latex(session, module=None) -> str
    mathml.term_to_mathml(env, t) -> str
    markdown.module_to_markdown(session, module=None) -> str
    json_export.term_to_json(t) -> dict
    json_export.term_from_json(d) -> Term
    json_export.module_to_json(session, module=None) -> dict
    python_ast.term_to_python_ast(env, t, backend="math") -> ast.expr
    python_ast.module_to_python(session, module=None, backend="math") -> str
"""

from .latex import term_to_latex, decl_to_latex, module_to_latex
from .mathml import term_to_mathml
from .markdown import module_to_markdown
from .json_export import term_to_json, term_from_json, module_to_json

__all__ = [
    "term_to_latex", "decl_to_latex", "module_to_latex",
    "term_to_mathml",
    "module_to_markdown",
    "term_to_json", "term_from_json", "module_to_json",
]

# `python_ast.py` is a sibling agent's file (Python-AST codegen backend);
# it may not exist yet in this checkout. Import it the same optional way
# `epsilon.project._default_oracles` picks up `epsilon.cas`/`epsilon.numeric`
# - present -> re-exported here too; absent -> the rest of this package
# still imports and works fine without it.
try:
    from .python_ast import term_to_python_ast, module_to_python  # noqa: F401
    __all__ += ["term_to_python_ast", "module_to_python"]
except ImportError:
    pass
