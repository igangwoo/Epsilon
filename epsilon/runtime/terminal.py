"""Real shell terminals for the IDE, one PTY per session.

A session is a shell running on a pseudo-terminal: full job control, colors,
curses programs — everything a terminal means. The transport is deliberately
plain polling (write input / read output since a cursor) so it works over
the same HTTP the rest of the API uses, with no websocket dependency; at
IDE keystroke rates that is indistinguishable from streaming.

Nothing here exists in the browser build — there is no operating system to
give a shell to — and the front end says so instead of imitating one.
"""

from __future__ import annotations

import fcntl
import os
import pty
import shutil
import signal
import struct
import subprocess
import termios
import threading
import time

#: per-session scrollback kept server-side; the client keeps its own too
MAX_BUFFER = 400_000

#: sessions idle longer than this are reaped
IDLE_REAP = 3600.0


def _shell() -> list[str]:
    for candidate in (os.environ.get("SHELL"), "/bin/bash", "/bin/sh"):
        if candidate and shutil.which(candidate):
            return [candidate]
    return ["/bin/sh"]


class TerminalSession:
    """One shell on one PTY. Output accumulates; clients read from an offset."""

    def __init__(self, session_id: str, cwd: str) -> None:
        self.id = session_id
        self.cwd = cwd
        self._master, slave = pty.openpty()
        self._proc = subprocess.Popen(
            _shell(), stdin=slave, stdout=slave, stderr=slave,
            cwd=cwd, start_new_session=True,
            env={**os.environ, "TERM": "xterm-256color"},
        )
        os.close(slave)
        self._buf = bytearray()
        self._base = 0                     # offset of _buf[0] in the stream
        self._lock = threading.Lock()
        self.last_used = time.monotonic()
        self._reader = threading.Thread(target=self._pump, daemon=True)
        self._reader.start()

    def _pump(self) -> None:
        while True:
            try:
                chunk = os.read(self._master, 65536)
            except OSError:
                break
            if not chunk:
                break
            with self._lock:
                self._buf.extend(chunk)
                if len(self._buf) > MAX_BUFFER:
                    drop = len(self._buf) - MAX_BUFFER
                    del self._buf[:drop]
                    self._base += drop

    def read(self, since: int) -> tuple[str, int]:
        """Everything the shell wrote at or after stream offset `since`."""
        self.last_used = time.monotonic()
        with self._lock:
            start = max(0, since - self._base)
            data = bytes(self._buf[start:])
            return data.decode("utf-8", "replace"), self._base + len(self._buf)

    def write(self, data: str) -> None:
        self.last_used = time.monotonic()
        os.write(self._master, data.encode())

    def resize(self, rows: int, cols: int) -> None:
        rows = max(2, min(500, int(rows)))
        cols = max(10, min(1000, int(cols)))
        fcntl.ioctl(self._master, termios.TIOCSWINSZ,
                    struct.pack("HHHH", rows, cols, 0, 0))
        os.killpg(self._proc.pid, signal.SIGWINCH)

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    @property
    def exit_code(self) -> int | None:
        return self._proc.poll()

    def kill(self) -> None:
        if self.alive:
            try:
                os.killpg(self._proc.pid, signal.SIGHUP)
                self._proc.wait(timeout=2)
            except (subprocess.TimeoutExpired, ProcessLookupError):
                try:
                    os.killpg(self._proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        try:
            os.close(self._master)
        except OSError:
            pass


class TerminalManager:
    def __init__(self) -> None:
        self._sessions: dict[str, TerminalSession] = {}
        self._next = 0
        self._lock = threading.Lock()

    def create(self, cwd: str) -> TerminalSession:
        self.reap()
        with self._lock:
            self._next += 1
            sid = f"t{self._next}"
            session = TerminalSession(sid, cwd)
            self._sessions[sid] = session
            return session

    def get(self, sid: str) -> TerminalSession | None:
        return self._sessions.get(sid)

    def list(self) -> list[dict]:
        return [{"id": s.id, "alive": s.alive, "cwd": s.cwd}
                for s in self._sessions.values()]

    def kill(self, sid: str) -> None:
        session = self._sessions.pop(sid, None)
        if session:
            session.kill()

    def reap(self) -> None:
        """Drop dead shells and shells nobody has touched for an hour."""
        now = time.monotonic()
        for sid, s in list(self._sessions.items()):
            if not s.alive or now - s.last_used > IDLE_REAP:
                self.kill(sid)

    def kill_all(self) -> None:
        for sid in list(self._sessions):
            self.kill(sid)
