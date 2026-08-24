"""The Python console's interpreter, run as a child process.

One JSON request per stdin line, one JSON reply per stdout line. The
*user's* stdout/stderr are captured into the reply, never written to the
real streams — the real stdout carries only protocol, so a stray print can
never corrupt it. State (the interpreter's namespace) lives here and
survives between requests; killing this process is how a session resets.
"""

import codeop
import contextlib
import io
import json
import sys
import traceback

_ns = {"__name__": "__console__", "__doc__": None}


def _execute(source):
    out, err = io.StringIO(), io.StringIO()
    ok = True
    try:
        # "single" echoes bare-expression values, the way a console should
        code = compile(source, "<console>", "single")
    except SyntaxError:
        try:
            code = compile(source, "<console>", "exec")
        except SyntaxError:
            return {"ok": False, "output": "",
                    "error": traceback.format_exc(limit=0)}
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            exec(code, _ns)
        except SystemExit:
            raise
        except BaseException:
            ok = False
            # frame 0 is this exec call, not the user's code
            etype, evalue, tb = sys.exc_info()
            err.write("".join(traceback.format_exception(
                etype, evalue, tb.tb_next)))
    return {"ok": ok, "output": out.getvalue(), "error": err.getvalue()}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        source = req.get("source", "")
        if req.get("op") == "complete":
            # is this input a finished statement? (None => keep typing)
            try:
                finished = codeop.compile_command(source) is not None
            except SyntaxError:
                finished = True     # let execution report the error
            reply = {"ok": True, "incomplete": not finished}
        else:
            try:
                reply = _execute(source)
            except SystemExit:
                break
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
