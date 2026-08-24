"""The Python debugger, run as a child process.

A bdb.Bdb subclass executes the user's file; when it stops (a breakpoint or
a step), it emits a `stopped` event carrying the stack and the top frame's
locals, then blocks reading commands until told how to move. The user
program's stdout/stderr are wrapped so its output arrives as `output`
events — the real stdout carries only protocol JSON, one object per line.

Protocol in (stdin, one JSON per line):
  {"op": "start", "file": ..., "breakpoints": [ints]}
  {"op": "continue" | "step" | "next" | "return" | "quit"}
  {"op": "setbp", "breakpoints": [ints]}     # replace, any time stopped
  {"op": "eval", "expr": ...}                # in the current frame

Protocol out (stdout):
  {"event": "stopped", "reason", "line", "stack": [{name, file, line}],
   "locals": {name: repr}}
  {"event": "output", "data"}
  {"event": "eval", "ok", "value"}
  {"event": "exited", "code"} | {"event": "error", "message"}
"""

import bdb
import io
import json
import os
import sys
import traceback

_real_stdout = sys.stdout


def emit(obj):
    _real_stdout.write(json.dumps(obj) + "\n")
    _real_stdout.flush()


class _OutputPipe(io.TextIOBase):
    """The user program's stream, delivered as events."""

    def __init__(self, name):
        self._name = name

    def write(self, data):
        if data:
            emit({"event": "output", "stream": self._name, "data": data})
        return len(data)

    def writable(self):
        return True


def _read_command():
    line = sys.stdin.readline()
    if not line:
        return {"op": "quit"}
    try:
        return json.loads(line)
    except ValueError:
        return {"op": "quit"}


class Debugger(bdb.Bdb):
    def __init__(self, target):
        super().__init__()
        self.target = os.path.abspath(target)
        self.mode = "continue"          # how the next stop is decided

    def _should_show(self, frame):
        return os.path.abspath(frame.f_code.co_filename) == self.target

    def user_line(self, frame):
        if not self._should_show(frame):
            return
        if self.mode == "continue" and not self.break_here(frame):
            return
        self._interact(frame, "breakpoint" if self.break_here(frame) else "step")

    def user_exception(self, frame, exc_info):
        if self._should_show(frame):
            emit({"event": "output", "stream": "stderr",
                  "data": "".join(traceback.format_exception_only(*exc_info[:2]))})

    def _stack_of(self, frame):
        stack = []
        f = frame
        while f is not None:
            path = os.path.abspath(f.f_code.co_filename)
            if path == self.target:
                stack.append({"name": f.f_code.co_name or "<module>",
                              "line": f.f_lineno})
            f = f.f_back
        return stack

    def _locals_of(self, frame):
        out = {}
        for name, value in list(frame.f_locals.items()):
            if name.startswith("__") and name.endswith("__"):
                continue
            try:
                text = repr(value)
            except Exception:
                text = "<unrepresentable>"
            out[name] = text[:200]
        return out

    def _interact(self, frame, reason):
        emit({"event": "stopped", "reason": reason, "line": frame.f_lineno,
              "stack": self._stack_of(frame),
              "locals": self._locals_of(frame)})
        while True:
            cmd = _read_command()
            op = cmd.get("op")
            if op == "continue":
                self.mode = "continue"
                self.set_continue()
                return
            if op == "step":
                self.mode = "step"
                self.set_step()
                return
            if op == "next":
                self.mode = "step"
                self.set_next(frame)
                return
            if op == "return":
                self.mode = "step"
                self.set_return(frame)
                return
            if op == "setbp":
                self.clear_all_breaks()
                for line in cmd.get("breakpoints", []):
                    self.set_break(self.target, int(line))
                continue
            if op == "eval":
                try:
                    value = repr(eval(cmd.get("expr", ""),          # noqa: S307
                                      frame.f_globals, frame.f_locals))
                    emit({"event": "eval", "ok": True, "value": value[:500]})
                except Exception as e:
                    emit({"event": "eval", "ok": False,
                          "value": f"{type(e).__name__}: {e}"})
                continue
            if op == "quit":
                self.set_quit()
                raise bdb.BdbQuit


def main():
    start = _read_command()
    if start.get("op") != "start":
        return
    target = start["file"]
    dbg = Debugger(target)
    for line in start.get("breakpoints", []):
        dbg.set_break(dbg.target, int(line))

    sys.stdout = _OutputPipe("stdout")
    sys.stderr = _OutputPipe("stderr")
    code_globals = {"__name__": "__main__", "__file__": dbg.target}
    exit_code = 0
    try:
        with open(dbg.target, encoding="utf-8") as fh:
            source = fh.read()
        dbg.run(compile(source, dbg.target, "exec"), code_globals)
    except bdb.BdbQuit:
        exit_code = -1
    except SystemExit as e:
        exit_code = int(e.code or 0)
    except BaseException:
        sys.stderr.write(traceback.format_exc())
        exit_code = 1
    finally:
        sys.stdout, sys.stderr = _real_stdout, sys.__stderr__
        emit({"event": "exited", "code": exit_code})


if __name__ == "__main__":
    main()
