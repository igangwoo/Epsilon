"""Find and replace across the workspace's text files.

Plain results in checker-adjacent shape (path, 1-based line, 0-based column,
match length, the line as preview) so the search panel can jump the editor
to the exact range. Caps are explicit in the reply — a truncated search that
looks complete would misreport the workspace.
"""

from __future__ import annotations

import os
import re

MAX_RESULTS = 2000
MAX_FILE_BYTES = 2_000_000


class SearchError(ValueError):
    pass


def _compile(query: str, *, regex: bool, case: bool, word: bool) -> re.Pattern:
    if not query:
        raise SearchError("nothing to search for")
    pattern = query if regex else re.escape(query)
    if word:
        pattern = r"\b(?:" + pattern + r")\b"
    try:
        return re.compile(pattern, 0 if case else re.IGNORECASE)
    except re.error as e:
        raise SearchError(f"bad pattern: {e}") from e


def _iter_files(root: str, entries: list[dict]):
    for entry in entries:
        if entry.get("kind") != "file" or not entry.get("editable"):
            continue
        full = os.path.join(root, entry["path"])
        try:
            if os.path.getsize(full) > MAX_FILE_BYTES:
                continue
            with open(full, encoding="utf-8", errors="replace") as fh:
                yield entry["path"], fh.read()
        except OSError:
            continue


def search(root: str, entries: list[dict], query: str, *,
           regex: bool = False, case: bool = False,
           word: bool = False) -> dict:
    pat = _compile(query, regex=regex, case=case, word=word)
    results: list[dict] = []
    files_hit = 0
    truncated = False
    for path, text in _iter_files(root, entries):
        file_had = False
        for line_no, line in enumerate(text.split("\n"), 1):
            for m in pat.finditer(line):
                if len(results) >= MAX_RESULTS:
                    truncated = True
                    break
                results.append({"path": path, "line": line_no,
                                "col": m.start(),
                                "length": max(1, m.end() - m.start()),
                                "preview": line[:400]})
                file_had = True
                if m.start() == m.end():        # zero-width: don't spin
                    break
            if truncated:
                break
        files_hit += 1 if file_had else 0
        if truncated:
            break
    return {"ok": True, "results": results, "files": files_hit,
            "truncated": truncated}


def replace(root: str, entries: list[dict], query: str, replacement: str, *,
            regex: bool = False, case: bool = False, word: bool = False,
            paths: list[str] | None = None) -> dict:
    """Apply the replacement; returns per-file counts. Files not listed in
    `paths` (when given) are left alone, so the panel can offer per-file
    exclusion."""
    pat = _compile(query, regex=regex, case=case, word=word)
    if not regex:
        replacement = replacement.replace("\\", "\\\\")
    wanted = set(paths) if paths is not None else None
    changed: dict[str, int] = {}
    total = 0
    for path, text in _iter_files(root, entries):
        if wanted is not None and path not in wanted:
            continue
        new_text, n = pat.subn(replacement, text)
        if n:
            with open(os.path.join(root, path), "w", encoding="utf-8") as fh:
                fh.write(new_text)
            changed[path] = n
            total += n
    return {"ok": True, "replacements": total, "files": changed}
