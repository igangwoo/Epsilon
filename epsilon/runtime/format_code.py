"""Formatting through the real formatters, when the machine has them.

black for Python, clang-format for C++ — the actual tools, run over stdin,
never an imitation. A machine without one reports the capability as absent
and the IDE disables the command with that reason, rather than shipping a
half-formatter that disagrees with the real one.
"""

from __future__ import annotations

import os
import shutil
import subprocess

_BLACK_HINTS = ("/root/.local/bin/black",)


def _black() -> str | None:
    found = shutil.which("black")
    if found:
        return found
    for hint in _BLACK_HINTS:
        if os.path.exists(hint):
            return hint
    return None


def _clang_format() -> str | None:
    return shutil.which("clang-format")


def format_capabilities() -> dict[str, bool]:
    return {"python": _black() is not None, "cpp": _clang_format() is not None}


def format_code(language: str, code: str) -> dict:
    """{"ok", "code"} or {"ok": False, "message"} — never a guess."""
    if language == "python":
        tool = _black()
        if not tool:
            return {"ok": False, "message":
                    "black is not installed on this machine"}
        cmd = [tool, "-q", "-"]
    elif language == "cpp":
        tool = _clang_format()
        if not tool:
            return {"ok": False, "message":
                    "clang-format is not installed on this machine"}
        cmd = [tool, "--style", "{BasedOnStyle: LLVM, IndentWidth: 4}"]
    else:
        return {"ok": False,
                "message": f"no formatter for '{language}' here"}
    try:
        proc = subprocess.run(cmd, input=code.encode(), capture_output=True,
                              timeout=20)
    except subprocess.TimeoutExpired:
        return {"ok": False, "message": "the formatter did not finish in 20s"}
    if proc.returncode != 0:
        message = proc.stderr.decode("utf-8", "replace").strip()
        return {"ok": False, "message": message.splitlines()[-1] if message
                else "the formatter refused this input"}
    return {"ok": True, "code": proc.stdout.decode("utf-8", "replace")}
