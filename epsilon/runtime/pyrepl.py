"""A persistent Python console, held in a child process.

The interpreter must not live in the server's own process — user code there
could corrupt the server — and must survive between HTTP requests, or it is
not a console. A child process gives both: real state, real isolation, and a
hard reset (kill and respawn) when an input runs away.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

_CHILD = os.path.join(os.path.dirname(__file__), "_pyrepl_child.py")

#: one input may run this long before the session is reset
EXEC_TIMEOUT = 15.0


class PythonRepl:
    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def _ensure(self) -> subprocess.Popen:
        if self._proc is None or self._proc.poll() is not None:
            self._proc = subprocess.Popen(
                [sys.executable, "-I", _CHILD],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        return self._proc

    def reset(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            self._proc.kill()
            self._proc.wait()
        self._proc = None

    def _roundtrip(self, request: dict) -> dict:
        proc = self._ensure()
        try:
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError):
            self.reset()
            proc = self._ensure()
            proc.stdin.write(json.dumps(request) + "\n")
            proc.stdin.flush()

        import threading
        reply: list[str] = []

        def read():
            reply.append(proc.stdout.readline())

        t = threading.Thread(target=read, daemon=True)
        t.start()
        t.join(EXEC_TIMEOUT)
        if t.is_alive() or not reply or not reply[0]:
            # a runaway input: the only honest recovery is a fresh session
            self.reset()
            return {"ok": False, "output": "",
                    "error": f"stopped after {EXEC_TIMEOUT:g}s — the console "
                             "was reset (its variables are gone)",
                    "reset": True}
        return json.loads(reply[0])

    def run(self, source: str) -> dict:
        """Execute one console input; state persists to the next call."""
        if not source.strip():
            return {"ok": True, "output": "", "error": ""}
        return self._roundtrip({"source": source})

    def is_incomplete(self, source: str) -> bool:
        """Does this input still need more lines?"""
        r = self._roundtrip({"op": "complete", "source": source})
        return bool(r.get("incomplete"))
