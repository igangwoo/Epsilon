"""Debug sessions over the bdb child (`_pydebug_child.py`).

The parent side: spawn a child per session, feed it commands, collect its
events on a reader thread, hand them to the client from an offset — the
same polling transport the terminal uses. Real debugging, real isolation,
and a hard stop (kill) always available.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time

_CHILD = os.path.join(os.path.dirname(__file__), "_pydebug_child.py")

#: an entire session may live this long before it is reaped
MAX_SESSION = 600.0


class DebugSession:
    def __init__(self, sid: str, code: str, filename: str,
                 breakpoints: list[int]) -> None:
        self.id = sid
        self.started = time.monotonic()
        self._dir = tempfile.mkdtemp(prefix="epsilon-debug-")
        self.path = os.path.join(self._dir, os.path.basename(filename) or "main.py")
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(code)
        self._proc = subprocess.Popen(
            [sys.executable, "-I", _CHILD],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, cwd=self._dir,
        )
        self._events: list[dict] = []
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()
        self._send({"op": "start", "file": self.path,
                    "breakpoints": [int(b) for b in breakpoints]})

    def _pump(self) -> None:
        for line in self._proc.stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            with self._lock:
                self._events.append(event)
        with self._lock:
            if not any(e.get("event") == "exited" for e in self._events):
                self._events.append({"event": "exited", "code": -9})

    def _send(self, obj: dict) -> None:
        try:
            self._proc.stdin.write(json.dumps(obj) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass

    def command(self, op: str, **kw) -> None:
        self._send({"op": op, **kw})

    def events(self, since: int) -> tuple[list[dict], int]:
        with self._lock:
            return self._events[since:], len(self._events)

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    def kill(self) -> None:
        if self.alive:
            self._proc.kill()
            self._proc.wait()


class DebugManager:
    def __init__(self) -> None:
        self._sessions: dict[str, DebugSession] = {}
        self._next = 0

    def start(self, code: str, filename: str,
              breakpoints: list[int]) -> DebugSession:
        self.reap()
        self._next += 1
        sid = f"d{self._next}"
        session = DebugSession(sid, code, filename, breakpoints)
        self._sessions[sid] = session
        return session

    def get(self, sid: str) -> DebugSession | None:
        return self._sessions.get(sid)

    def stop(self, sid: str) -> None:
        session = self._sessions.pop(sid, None)
        if session:
            session.kill()

    def reap(self) -> None:
        now = time.monotonic()
        for sid, s in list(self._sessions.items()):
            if not s.alive and not s.events(0)[0]:
                self.stop(sid)
            elif now - s.started > MAX_SESSION:
                self.stop(sid)
