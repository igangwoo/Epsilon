"""Symbol dependency graphs for the IDE.

What refers to what, inside one file. Python is analysed properly — the
`ast` module gives real scopes, so a name used inside a function is
attributed to that function and resolved against the module's own
definitions rather than guessed at. C++ has no front-end here, so it gets
a lexical pass and the reply says so; a graph that quietly mixed the two
would be worse than one that admits which it is.

Nodes are the things a file defines: functions, classes, module-level
variables, and imports. An edge means "the source's body mentions the
target", which is the relation someone reading the file actually wants —
where is this used, and what would break if I changed it.
"""

from __future__ import annotations

import ast
import re

MAX_NODES = 220


def _kind_of(node) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "function"
    if isinstance(node, ast.ClassDef):
        return "class"
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return "import"
    return "variable"


def _names_used(node) -> set[str]:
    """Every bare name and attribute root mentioned inside `node`."""
    used: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            used.add(child.id)
        elif isinstance(child, ast.Attribute):
            root = child
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
    return used


def _python_graph(code: str) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return {"ok": False, "level": "semantic",
                "message": f"line {exc.lineno}: {exc.msg}",
                "nodes": [], "edges": []}

    nodes: dict[str, dict] = {}
    bodies: dict[str, object] = {}

    def add(name, kind, line, detail=""):
        if name in nodes or len(nodes) >= MAX_NODES:
            return
        nodes[name] = {"id": name, "name": name, "kind": kind,
                       "line": line, "detail": detail}

    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = ", ".join(a.arg for a in stmt.args.args)
            add(stmt.name, "function", stmt.lineno, f"({args})")
            bodies[stmt.name] = stmt
        elif isinstance(stmt, ast.ClassDef):
            add(stmt.name, "class", stmt.lineno, "")
            bodies[stmt.name] = stmt
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Name):
                        add(sub.id, "variable", stmt.lineno, "")
                        bodies.setdefault(sub.id, stmt)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            add(stmt.target.id, "variable", stmt.lineno, "")
            bodies.setdefault(stmt.target.id, stmt)
        elif isinstance(stmt, (ast.Import, ast.ImportFrom)):
            module = getattr(stmt, "module", "") or ""
            for alias in stmt.names:
                local = alias.asname or alias.name.split(".")[0]
                origin = f"{module}.{alias.name}" if module else alias.name
                add(local, "import", stmt.lineno, origin)

    edges = []
    seen = set()

    def link(src, dst, kind):
        key = (src, dst)
        if src == dst or dst not in nodes or key in seen:
            return
        seen.add(key)
        edges.append({"from": src, "to": dst, "kind": kind})

    for name, body in bodies.items():
        if name not in nodes:
            continue
        for used in _names_used(body):
            link(name, used, "uses")
    # a class lists its bases as inheritance rather than plain use
    for stmt in tree.body:
        if isinstance(stmt, ast.ClassDef):
            for base in stmt.bases:
                if isinstance(base, ast.Name):
                    link(stmt.name, base.id, "inherits")

    # top-level code that is not itself a definition still uses things
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Import, ast.ImportFrom, ast.Assign,
                             ast.AnnAssign)):
            continue
        for used in _names_used(stmt):
            if used in nodes:
                edges.append({"from": "<module>", "to": used, "kind": "uses"})
    if any(e["from"] == "<module>" for e in edges):
        nodes["<module>"] = {"id": "<module>", "name": "module body",
                             "kind": "module", "line": 1, "detail": ""}

    # how many things point at each node — the renderer sizes by this
    for node in nodes.values():
        node["refs"] = sum(1 for e in edges if e["to"] == node["id"])
    return {"ok": True, "level": "semantic",
            "nodes": list(nodes.values()), "edges": edges}


_CPP_DEF = re.compile(
    r"^[A-Za-z_][\w:<>,*&\s]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*(?:const\s*)?\{",
    re.M)
_CPP_CLASS = re.compile(r"^\s*(?:class|struct)\s+([A-Za-z_]\w*)", re.M)
_CPP_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_CPP_NOT_A_NAME = {"if", "for", "while", "switch", "return", "sizeof",
                   "catch", "throw"}


def _cpp_graph(code: str) -> dict:
    """A lexical pass: definitions by shape, edges by call site.

    Without a compiler front-end this cannot resolve overloads, templates
    or scope, and the reply says `lexical` so nobody reads more into the
    picture than is there.
    """
    lines = code.split("\n")
    nodes: dict[str, dict] = {}

    def line_of(pos):
        return code.count("\n", 0, pos) + 1

    for m in _CPP_CLASS.finditer(code):
        nodes[m.group(1)] = {"id": m.group(1), "name": m.group(1),
                             "kind": "class", "line": line_of(m.start()),
                             "detail": ""}
    spans = []
    for m in _CPP_DEF.finditer(code):
        name = m.group(1)
        if name in _CPP_NOT_A_NAME:
            continue
        nodes.setdefault(name, {"id": name, "name": name, "kind": "function",
                                "line": line_of(m.start()), "detail": "()"})
        # (body start, where the *next* definition begins) — a body ends
        # where the following signature starts, not where it ends
        spans.append((name, m.end(), m.start()))

    edges = []
    seen = set()
    for i, (name, start, _) in enumerate(spans):
        end = spans[i + 1][2] if i + 1 < len(spans) else len(code)
        for call in _CPP_CALL.finditer(code[start:end]):
            target = call.group(1)
            if (target in nodes and target != name
                    and (name, target) not in seen):
                seen.add((name, target))
                edges.append({"from": name, "to": target, "kind": "calls"})
    for node in nodes.values():
        node["refs"] = sum(1 for e in edges if e["to"] == node["id"])
    return {"ok": True, "level": "lexical",
            "nodes": list(nodes.values())[:MAX_NODES], "edges": edges,
            "note": "lexical: no compiler front-end, so overloads, templates "
                    "and scope are not resolved"}


def graph(language: str, code: str, path: str = "") -> dict:
    """Symbols and the references between them, for one file."""
    if language == "python":
        return _python_graph(code)
    if language == "cpp":
        return _cpp_graph(code)
    return {"ok": False, "level": "none", "nodes": [], "edges": [],
            "message": f"no dependency analysis for {language or 'this file'} "
                       "— Python is analysed with its own parser, C++ "
                       "lexically"}
