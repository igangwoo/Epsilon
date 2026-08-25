"""Execute a Python, C++ or Java program and report honestly what happened.

One entry point, `run_code`, used by the server's /api/run. Programs run in
a fresh subprocess inside a temporary directory, with a wall-clock timeout
and a cap on captured output — an infinite loop or a firehose of prints ends
the run and says so, rather than hanging the IDE.

Compiler and runtime diagnostics are parsed back into the same
(line, column, message) shape the Epsilon checker reports, so the editor's
gutter and the Problems panel work identically for all three languages.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field

#: wall-clock ceiling per phase (compile and run each get their own)
DEFAULT_TIMEOUT = 10.0
MAX_TIMEOUT = 60.0

#: captured-output cap per stream; beyond this the run is stopped
MAX_OUTPUT = 200_000

_TRUNCATED = "\n… output truncated at {} bytes"


@dataclass
class RunResult:
    ok: bool
    language: str
    phase: str                    # "run", or "compile" when that is what failed
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    diagnostics: list[dict] = field(default_factory=list)
    message: str = ""             # non-program failures: timeout, no compiler

    def as_dict(self) -> dict:
        return {
            "ok": self.ok, "language": self.language, "phase": self.phase,
            "stdout": self.stdout, "stderr": self.stderr,
            "exit_code": self.exit_code, "duration_ms": self.duration_ms,
            "diagnostics": self.diagnostics, "message": self.message,
        }


def _cxx() -> str | None:
    for name in ("g++", "clang++"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _jdk() -> tuple[str, str] | None:
    """`(javac, java)` if both are here — a compiler without a runtime, or
    the other way round, cannot run anything."""
    javac, java = shutil.which("javac"), shutil.which("java")
    return (javac, java) if javac and java else None


def available_languages() -> dict[str, bool]:
    """What this machine can actually run. The UI shows only the truth."""
    return {"python": True, "cpp": _cxx() is not None,
            "java": _jdk() is not None}


def _cap(data: bytes) -> str:
    text = data.decode("utf-8", "replace")
    if len(text) > MAX_OUTPUT:
        return text[:MAX_OUTPUT] + _TRUNCATED.format(MAX_OUTPUT)
    return text


def _exec(cmd: list[str], *, cwd: str, stdin: str, timeout: float
          ) -> tuple[subprocess.CompletedProcess | None, int]:
    """Run one subprocess; None means it hit the timeout."""
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, input=stdin.encode(),
            capture_output=True, timeout=timeout,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    except subprocess.TimeoutExpired:
        return None, int((time.monotonic() - t0) * 1000)
    return proc, int((time.monotonic() - t0) * 1000)


# ---------------------------------------------------------------------------
# diagnostics: compiler/runtime text -> the checker's (line, col, message)
# ---------------------------------------------------------------------------

_GCC_LINE = re.compile(
    r"^(?P<file>[^:\n]+):(?P<line>\d+):(?:(?P<col>\d+):)?\s*"
    r"(?P<sev>error|warning|note):\s*(?P<msg>.*)$")

_PY_FRAME = re.compile(r'^\s*File "(?P<file>[^"]+)", line (?P<line>\d+)')


def gcc_diagnostics(stderr: str, filename: str) -> list[dict]:
    """g++/clang++ diagnostics for `filename`, as checker-shaped entries."""
    out = []
    for line in stderr.splitlines():
        m = _GCC_LINE.match(line)
        if not m or os.path.basename(m.group("file")) != os.path.basename(filename):
            continue
        sev = m.group("sev")
        if sev == "note":
            continue
        ln = int(m.group("line"))
        col = int(m.group("col") or 1)
        out.append({"severity": "error" if sev == "error" else "warning",
                    "message": m.group("msg").strip(),
                    "span": [ln, col, ln, col], "module": filename})
    return out


_JAVAC_LINE = re.compile(
    r"^(?P<file>[^:]+\.java):(?P<line>\d+):\s*(?P<sev>error|warning):\s*(?P<msg>.*)$")


def javac_diagnostics(stderr: str, filename: str) -> list[dict]:
    """javac diagnostics for `filename`, as checker-shaped entries.

    javac reports a line but no column; it marks the column with a caret on
    the following line, which is more than the gutter needs.
    """
    out = []
    for line in stderr.splitlines():
        m = _JAVAC_LINE.match(line.strip())
        if not m or os.path.basename(m.group("file")) != os.path.basename(filename):
            continue
        ln = int(m.group("line"))
        out.append({"severity": "error" if m.group("sev") == "error" else "warning",
                    "message": m.group("msg").strip(),
                    "span": [ln, 1, ln, 1], "module": filename})
    return out


def python_diagnostics(stderr: str, filename: str) -> list[dict]:
    """The last user-file frame of a traceback, as one checker-shaped error."""
    lines = stderr.splitlines()
    last_line = None
    for line in lines:
        m = _PY_FRAME.match(line)
        if m and os.path.basename(m.group("file")) == os.path.basename(filename):
            last_line = int(m.group("line"))
    if last_line is None:
        return []
    message = lines[-1].strip() if lines else "error"
    return [{"severity": "error", "message": message,
             "span": [last_line, 1, last_line, 1], "module": filename}]


# ---------------------------------------------------------------------------
# languages
# ---------------------------------------------------------------------------

def _run_python(code: str, stdin: str, timeout: float, filename: str) -> RunResult:
    with tempfile.TemporaryDirectory(prefix="epsilon-run-") as tmp:
        path = os.path.join(tmp, os.path.basename(filename) or "main.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(code)
        # -I: isolated - the program does not inherit this server's
        # sys.path or environment-variable hooks
        proc, ms = _exec([sys.executable, "-I", path],
                         cwd=tmp, stdin=stdin, timeout=timeout)
    if proc is None:
        return RunResult(False, "python", "run", duration_ms=ms,
                         message=f"stopped after {timeout:g}s — "
                                 "the program did not finish in time")
    stderr = _cap(proc.stderr)
    return RunResult(
        proc.returncode == 0, "python", "run",
        stdout=_cap(proc.stdout), stderr=stderr,
        exit_code=proc.returncode, duration_ms=ms,
        diagnostics=python_diagnostics(stderr, filename))


def _run_cpp(code: str, stdin: str, timeout: float, filename: str) -> RunResult:
    compiler = _cxx()
    if compiler is None:
        return RunResult(
            False, "cpp", "compile",
            message="no C++ compiler on this machine (looked for g++ and "
                    "clang++) — the IDE reports that rather than pretending")
    base = os.path.basename(filename) or "main.cpp"
    with tempfile.TemporaryDirectory(prefix="epsilon-run-") as tmp:
        src = os.path.join(tmp, base)
        exe = os.path.join(tmp, "a.out")
        with open(src, "w", encoding="utf-8") as fh:
            fh.write(code)

        proc, cms = _exec([compiler, "-std=c++17", "-O1", "-o", exe, base],
                          cwd=tmp, stdin="", timeout=timeout)
        if proc is None:
            return RunResult(False, "cpp", "compile", duration_ms=cms,
                             message=f"compilation stopped after {timeout:g}s")
        if proc.returncode != 0:
            stderr = _cap(proc.stderr)
            return RunResult(False, "cpp", "compile",
                             stderr=stderr, exit_code=proc.returncode,
                             duration_ms=cms,
                             diagnostics=gcc_diagnostics(stderr, base))
        warnings = gcc_diagnostics(_cap(proc.stderr), base)

        rproc, rms = _exec([exe], cwd=tmp, stdin=stdin, timeout=timeout)
        if rproc is None:
            return RunResult(False, "cpp", "run", duration_ms=cms + rms,
                             diagnostics=warnings,
                             message=f"stopped after {timeout:g}s — "
                                     "the program did not finish in time")
        return RunResult(
            rproc.returncode == 0, "cpp", "run",
            stdout=_cap(rproc.stdout), stderr=_cap(rproc.stderr),
            exit_code=rproc.returncode, duration_ms=cms + rms,
            diagnostics=warnings)


#: Java insists the file be named after its public class, so the name is
#: taken from the source rather than from whatever the editor called it
_JAVA_CLASS = re.compile(r"public\s+(?:final\s+|abstract\s+)?class\s+([A-Za-z_]\w*)")


#: The JVM announces its own environment on stderr before the program
#: starts. That line is the JVM talking about itself, never the user's
#: output, and leaving it in makes every Java run look like it printed
#: something it did not.
_JVM_NOISE = re.compile(r"^Picked up (?:_?JAVA_(?:TOOL_)?OPTIONS|JDK_JAVA_OPTIONS):.*$\n?",
                        re.M)


def _quiet_jvm(stderr: str) -> str:
    return _JVM_NOISE.sub("", stderr)


def _run_java(code: str, stdin: str, timeout: float, filename: str) -> RunResult:
    jdk = _jdk()
    if jdk is None:
        return RunResult(
            False, "java", "compile",
            message="no JDK on this machine (looked for javac and java) — "
                    "the IDE reports that rather than pretending")
    javac, java = jdk
    m = _JAVA_CLASS.search(code)
    if not m:
        # javac would say this too, but much later and less clearly
        return RunResult(
            False, "java", "compile",
            message="no public class found — Java runs `main` from a public "
                    "class, so the file needs one")
    name = m.group(1)
    base = name + ".java"
    with tempfile.TemporaryDirectory(prefix="epsilon-run-") as tmp:
        with open(os.path.join(tmp, base), "w", encoding="utf-8") as fh:
            fh.write(code)

        proc, cms = _exec([javac, "-nowarn", base], cwd=tmp, stdin="",
                          timeout=timeout)
        if proc is None:
            return RunResult(False, "java", "compile", duration_ms=cms,
                             message=f"compilation stopped after {timeout:g}s")
        if proc.returncode != 0:
            stderr = _quiet_jvm(_cap(proc.stderr))
            return RunResult(False, "java", "compile",
                             stderr=stderr, exit_code=proc.returncode,
                             duration_ms=cms,
                             diagnostics=javac_diagnostics(stderr, base))
        warnings = javac_diagnostics(_quiet_jvm(_cap(proc.stderr)), base)

        rproc, rms = _exec([java, "-XX:+UseSerialGC", "-Xshare:auto", name],
                           cwd=tmp, stdin=stdin, timeout=timeout)
        if rproc is None:
            return RunResult(False, "java", "run", duration_ms=cms + rms,
                             diagnostics=warnings,
                             message=f"stopped after {timeout:g}s — "
                                     "the program did not finish in time")
        return RunResult(
            rproc.returncode == 0, "java", "run",
            stdout=_cap(rproc.stdout), stderr=_quiet_jvm(_cap(rproc.stderr)),
            exit_code=rproc.returncode, duration_ms=cms + rms,
            diagnostics=warnings)


def run_code(language: str, code: str, *, stdin: str = "",
             timeout: float = DEFAULT_TIMEOUT,
             filename: str = "") -> RunResult:
    """Run one program. Never raises for anything the program itself does."""
    timeout = max(0.5, min(MAX_TIMEOUT, float(timeout or DEFAULT_TIMEOUT)))
    if language == "python":
        return _run_python(code, stdin, timeout, filename or "main.py")
    if language == "cpp":
        return _run_cpp(code, stdin, timeout, filename or "main.cpp")
    if language == "java":
        return _run_java(code, stdin, timeout, filename or "Main.java")
    return RunResult(False, language, "run",
                     message=f"'{language}' is not a runnable language here "
                             "(python, cpp and java are)")
