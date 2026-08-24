"""The interactive Epsilon console (REPL).

One persistent `Session`. Commands (def/theorem/#check/...) are run through
the shared pipeline; a bare expression is evaluated by wrapping it in
`#eval`. Meta-commands start with `:`.
"""

from __future__ import annotations

import sys
from typing import Optional

from . import __version__, BRAND
from .project import Session, STATUS_LABELS

PROMPT = "ε> "
CONT = ".. "

COMMAND_STARTERS = (
    "def", "define", "theorem", "lemma", "proposition", "corollary",
    "example", "axiom", "constant", "inductive", "structure", "import",
    "namespace", "open", "notation", "infixl", "infixr", "prefix", "plot",
    "#check", "#eval", "#simplify", "#normalize", "end",
)


def classify_line(line: str) -> str:
    """'command' if the line begins a command; 'expr' otherwise."""
    stripped = line.strip()
    if not stripped:
        return "empty"
    if stripped.startswith("#"):
        return "command"
    first = stripped.split()[0]
    if first in COMMAND_STARTERS:
        return "command"
    return "expr"


def needs_continuation(buffer: str) -> bool:
    """Heuristic: does the accumulated input expect more lines?"""
    stripped = buffer.rstrip()
    if stripped.endswith((":=", "by", "with", "=>", "where", ",", "(", "[", "{")):
        return True
    # unbalanced brackets
    opens = sum(buffer.count(c) for c in "([{")
    closes = sum(buffer.count(c) for c in ")]}")
    if opens > closes:
        return True
    # a proof block that has started but might continue with indented lines
    if "by" in stripped.split() and stripped.endswith(("by",)):
        return True
    return False


class Repl:
    def __init__(self, session: Optional[Session] = None) -> None:
        self.session = session or Session()
        self.history: list[str] = []

    # ------------------------------------------------------------------
    def run_input(self, text: str) -> str:
        """Process one complete input (command block or expression). Returns
        the text to display."""
        text = text.rstrip()
        if not text:
            return ""
        if text.startswith(":"):
            return self._meta(text)
        self.history.append(text)
        kind = classify_line(text)
        source = text if kind == "command" else f"#eval {text}"
        res = self.session.check_source(source, "<repl>")
        out: list[str] = []
        for d in res.diagnostics:
            out.append(f"error: {d.message}")
        for r in res.results:
            if r.message:
                if r.kind == "theorem" and r.status:
                    out.append(f"{STATUS_LABELS[r.status]}  {r.message}")
                else:
                    out.append(r.message)
            elif r.kind == "plot":
                out.append(f"(plot registered: {len(r.extra.get('functions', []))} "
                           f"function(s))")
        return "\n".join(out)

    # ------------------------------------------------------------------
    def _meta(self, text: str) -> str:
        parts = text[1:].split(maxsplit=1)
        cmd = parts[0] if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in ("q", "quit", "exit"):
            raise EOFError
        if cmd in ("h", "help", "?"):
            return _HELP
        if cmd == "env":
            return self._list_env()
        if cmd in ("theorems", "thms"):
            return self._list_theorems()
        if cmd == "type":
            res = self.session.check_source(f"#check {arg}", "<repl>")
            return "\n".join(r.message for r in res.results if r.message) or \
                "\n".join(f"error: {d.message}" for d in res.diagnostics)
        if cmd == "axioms":
            return self._axioms(arg.strip())
        if cmd == "clear":
            self.session = Session()
            return "session reset"
        if cmd == "search":
            from .intelligence import search
            hits = search(self.session, arg, limit=15)
            return "\n".join(f"  {h['name']} : {h['statement']}" for h in hits) \
                or "no matches"
        return f"unknown meta-command ':{cmd}' (try :help)"

    def _list_env(self) -> str:
        from .elab.context import LOCAL_MARK
        rows = []
        for name in self.session.env.order:
            d = self.session.env.decls[name]
            if d.module in (None, "core", "plugin") or LOCAL_MARK in name:
                continue
            rows.append(f"  {d.kind.value:11s} {name}")
        return "\n".join(rows) or "(no user declarations)"

    def _list_theorems(self) -> str:
        rows = []
        for t in self.session.theorem_list():
            if t["module"] in ("prelude", "algebra", "analysis", "sets"):
                continue
            rows.append(f"  {t['status_label']:24s} {t['name']}")
        return "\n".join(rows) or "(no user theorems)"

    def _axioms(self, name: str) -> str:
        resolved = self.session.ctx.resolve_global(name) or name
        if not self.session.env.contains(resolved):
            return f"unknown: {name}"
        axs = sorted(self.session.env.axioms_of(resolved))
        status = self.session.env.verification_status(resolved) \
            if self.session.env.expect(resolved).kind.value == "theorem" else None
        head = f"{STATUS_LABELS[status]}\n" if status else ""
        return head + ("axioms: " + ", ".join(axs) if axs
                       else "depends on no axioms")


_HELP = """\
Epsilon REPL commands:
  <expr>              evaluate an expression (e.g. 2 + 3 * 4)
  def / theorem / ... run a declaration
  #check <expr>       show the type of an expression
  :type <expr>        same as #check
  :env                list user declarations
  :theorems           list user theorems with verification status
  :axioms <name>      show a theorem's axiom dependencies
  :search <text>      search the library
  :clear              reset the session
  :help               this message
  :quit               exit
Multi-line input continues until a blank line when a block is open."""


def run_repl(session: Optional[Session] = None) -> int:
    try:
        import readline  # noqa: F401  (enables history/editing when present)
    except ImportError:
        pass
    repl = Repl(session)
    print(f"{BRAND} {__version__} — interactive console.  :help for help, "
          f":quit to exit.")
    buffer = ""
    while True:
        try:
            prompt = CONT if buffer else PROMPT
            line = input(prompt)
        except EOFError:
            print()
            break
        except KeyboardInterrupt:
            print("^C")
            buffer = ""
            continue

        if buffer:
            if line.strip() == "":
                text, buffer = buffer, ""
            else:
                buffer += "\n" + line
                continue
        else:
            if needs_continuation(line) and not line.startswith(":"):
                buffer = line
                continue
            text = line

        try:
            output = repl.run_input(text)
        except EOFError:
            break
        if output:
            print(output)
    return 0


if __name__ == "__main__":
    sys.exit(run_repl())
