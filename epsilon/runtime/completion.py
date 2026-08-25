"""Code completion for the programming IDE.

Python completions are semantic, through jedi, when it is installed: real
members of real modules, with kinds and signatures. Without jedi — and for
C++, where no compiler front-end is embedded — completion falls back to an
honest lexical level: keywords, a curated standard-library table, and the
identifiers already in the buffer. The reply says which level produced it
(`semantic` / `lexical`), because the difference matters to the person
trusting the list.
"""

from __future__ import annotations

import keyword
import re
import textwrap

try:
    import jedi
    HAS_JEDI = True
except ImportError:              # pragma: no cover - environment-dependent
    jedi = None
    HAS_JEDI = False

MAX_ITEMS = 80

_PY_BUILTINS = [n for n in dir(__builtins__ if isinstance(__builtins__, dict)
                               else __builtins__)
                if not n.startswith("_")]
if isinstance(__builtins__, dict):       # pragma: no cover - import context
    _PY_BUILTINS = [n for n in __builtins__ if not n.startswith("_")]

_CPP_KEYWORDS = """
alignas alignof auto bool break case catch char class const constexpr
const_cast continue decltype default delete do double dynamic_cast else enum
explicit export extern false final float for friend goto if inline int long
mutable namespace new noexcept nullptr operator override private protected
public register reinterpret_cast return short signed sizeof static
static_assert static_cast struct switch template this throw true try typedef
typeid typename union unsigned using virtual void volatile while
""".split()

#: the parts of the standard library a person reaches for constantly —
#: curated, not exhaustive; lexical completion never pretends otherwise
_CPP_STD = {
    "vector": "template class", "string": "class", "array": "template class",
    "map": "template class", "unordered_map": "template class",
    "set": "template class", "unordered_set": "template class",
    "pair": "template class", "tuple": "template class",
    "deque": "template class", "queue": "template class",
    "stack": "template class", "list": "template class",
    "optional": "template class", "variant": "template class",
    "cout": "ostream", "cerr": "ostream", "cin": "istream",
    "endl": "manipulator", "getline": "function", "to_string": "function",
    "stoi": "function", "stod": "function", "sort": "function",
    "find": "function", "count": "function", "min": "function",
    "max": "function", "abs": "function", "swap": "function",
    "accumulate": "function", "unique": "function", "reverse": "function",
    "lower_bound": "function", "upper_bound": "function",
    "make_pair": "function", "make_tuple": "function", "move": "function",
    "size_t": "type", "int64_t": "type", "uint64_t": "type",
}

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

_KIND_MAP = {"module": "module", "class": "class", "function": "function",
             "instance": "variable", "statement": "variable",
             "param": "parameter", "keyword": "keyword",
             "property": "property", "path": "text"}


def _lexical(code: str, prefix: str, words: dict[str, str],
             kinds: dict[str, str] | None = None) -> list[dict]:
    seen: dict[str, dict] = {}
    kinds = kinds or {}
    for name, detail in words.items():
        seen[name] = {"name": name, "kind": kinds.get(name, "keyword"),
                      "detail": detail, "insert": name}
    for token in _IDENT.findall(code):
        if token not in seen:
            seen[token] = {"name": token, "kind": "text",
                           "detail": "in this file", "insert": token}
    prefix_lower = prefix.lower()
    items = [item for name, item in seen.items()
             if name.lower().startswith(prefix_lower) and name != prefix]
    items.sort(key=lambda i: (i["kind"] == "text", i["name"].lower()))
    return items[:MAX_ITEMS]


def _prefix_at(code: str, line: int, col: int) -> str:
    lines = code.split("\n")
    if not 1 <= line <= len(lines):
        return ""
    text = lines[line - 1][:col]
    match = re.search(r"[A-Za-z_][A-Za-z0-9_]*$", text)
    return match.group(0) if match else ""


def complete_python(code: str, line: int, col: int,
                    path: str = "main.py") -> dict:
    """Completions at (line 1-based, col 0-based)."""
    if HAS_JEDI:
        try:
            script = jedi.Script(code, path=path)
            items = []
            for c in script.complete(line, col):
                if c.name.startswith("__") and not (
                        _prefix_at(code, line, col).startswith("__")):
                    continue
                detail = ""
                try:
                    sigs = c.get_signatures()
                    if sigs:
                        detail = sigs[0].to_string()[:100]
                except Exception:
                    pass
                if not detail:
                    detail = c.type
                items.append({"name": c.name,
                              "kind": _KIND_MAP.get(c.type, c.type),
                              "detail": detail,
                              "insert": c.name})
                if len(items) >= MAX_ITEMS:
                    break
            return {"level": "semantic", "items": items}
        except Exception:        # noqa: BLE001 - jedi can choke; fall back
            pass
    words = {k: "keyword" for k in keyword.kwlist}
    words.update({b: "builtin" for b in _PY_BUILTINS})
    kinds = {b: "function" for b in _PY_BUILTINS}
    kinds.update({k: "keyword" for k in keyword.kwlist})
    return {"level": "lexical",
            "items": _lexical(code, _prefix_at(code, line, col), words, kinds)}


def complete_cpp(code: str, line: int, col: int) -> dict:
    """Lexical C++ completion — keywords, curated std::, buffer identifiers.

    Honest about its level: without a compiler front-end there is no
    semantic member lookup, and the reply says `lexical`.
    """
    lines = code.split("\n")
    before = lines[line - 1][:col] if 1 <= line <= len(lines) else ""
    prefix = _prefix_at(code, line, col)
    if re.search(r"std\s*::\s*[A-Za-z_]*$", before):
        items = [{"name": n, "kind": "class" if "class" in d or d == "type"
                  else "function" if d == "function" else "variable",
                  "detail": f"std::{n} — {d}", "insert": n}
                 for n, d in _CPP_STD.items()
                 if n.startswith(prefix)]
        items.sort(key=lambda i: i["name"])
        return {"level": "lexical", "items": items[:MAX_ITEMS]}
    words = {k: "keyword" for k in _CPP_KEYWORDS}
    words.update({f"std::{n}": d for n, d in _CPP_STD.items()})
    return {"level": "lexical", "items": _lexical(code, prefix, words)}


def complete(language: str, code: str, line: int, col: int,
             path: str = "") -> dict:
    if language == "python":
        return complete_python(code, line, col, path or "main.py")
    if language == "cpp":
        return complete_cpp(code, line, col)
    return {"level": "lexical",
            "items": _lexical(code, _prefix_at(code, line, col), {})}


def definition(language: str, code: str, line: int, col: int,
               path: str = "") -> dict:
    """Where the symbol at (1-based line, 0-based col) is defined.

    Semantic for Python via jedi. Definitions inside the given buffer come
    back as a jump target; definitions that live in installed modules are
    named but not opened — the workspace only contains the user's files.
    """
    if language != "python":
        return {"found": False,
                "message": "definition lookup is semantic and exists for "
                           "Python only"}
    if not HAS_JEDI:
        return {"found": False,
                "message": "definition lookup needs jedi "
                           "(pip install 'epsilon-math[ide]')"}
    try:
        script = jedi.Script(code, path=path or "main.py")
        defs = script.goto(line, col, follow_imports=True)
    except Exception as exc:     # noqa: BLE001 - jedi internal errors
        return {"found": False, "message": f"lookup failed: {exc}"}
    if not defs:
        return {"found": False,
                "message": "no definition found for the symbol under "
                           "the cursor"}
    d = defs[0]
    in_buffer = d.module_path is None or str(d.module_path).endswith(
        path or "main.py")
    if in_buffer and d.line:
        return {"found": True, "path": None, "line": d.line,
                "col": (d.column or 0) + 1, "name": d.name}
    return {"found": False,
            "message": f"{d.name} is defined in {d.module_name} "
                       "(an installed module, outside the workspace)"}
