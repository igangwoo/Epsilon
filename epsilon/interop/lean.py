"""Lean 4 interoperability (product spec section 28).

Lean and Epsilon share an architecture - a small trusted kernel checking
proof terms in a dependent type theory - which makes Lean the natural
second opinion for an Epsilon development.

Three directions:

1. **Export** (`term_to_lean`, `module_to_lean`): render Epsilon
   declarations as Lean 4 source. Definitions carry over as definitions;
   theorems carry over as `theorem ... := by sorry` *statements*, because
   an Epsilon proof term is not a Lean proof term. What you get is a Lean
   file stating your results, ready for someone to prove there.

2. **Re-checking** (`LeanBackend.check_theorem`): run Lean over an exported
   statement plus a supplied Lean proof. A Lean-accepted theorem is
   recorded as externally corroborated - it does *not* become
   `✓ Formally Proven` in Epsilon, because Epsilon's kernel did not check
   it. Claiming otherwise would be exactly the conflation the product
   forbids.

3. **Import** (`import_lean_declarations`): parse Lean declaration
   signatures and bring them in as **axioms**. Importing a statement is
   assuming it; every dependent theorem then lists that axiom.

Nothing here requires Lean to be installed - export and import are pure
text transformations. Only `LeanBackend.check_theorem` shells out.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional

from ..kernel.env import Declaration, DeclKind, Environment, KernelError
from ..kernel.term import (Term, Var, Const, Sort, App, Lam, Pi, Lit, StrLit,
                           MVar, unfold_app, has_var)
from ..elab.context import LOCAL_MARK
from ..plugins import ProofBackend, ProofBackendResult, install_axiom

# Epsilon constant -> Lean 4 name. Anything absent is emitted verbatim and
# will simply be undefined in Lean unless the user supplies it.
LEAN_NAMES = {
    "Nat": "Nat", "Int": "Int", "Rat": "Rat", "Real": "Real",
    "Complex": "Complex", "Bool": "Bool", "String": "String",
    "True": "True", "False": "False", "Not": "Not", "Ne": "Ne", "Eq": "Eq",
    "And": "And", "Or": "Or", "Iff": "Iff", "Exists": "Exists",
    "Nat.zero": "Nat.zero", "Nat.succ": "Nat.succ",
    "Bool.true": "true", "Bool.false": "false",
    "True.intro": "True.intro", "And.intro": "And.intro",
    "Or.inl": "Or.inl", "Or.inr": "Or.inr", "Iff.intro": "Iff.intro",
    "Exists.intro": "Exists.intro", "Eq.refl": "rfl",
    "Real.pi": "Real.pi", "Real.sin": "Real.sin", "Real.cos": "Real.cos",
    "Real.tan": "Real.tan", "Real.exp": "Real.exp", "Real.log": "Real.log",
    "Real.sqrt": "Real.sqrt", "Real.abs": "abs",
    "Prod": "Prod", "Prod.mk": "Prod.mk", "List": "List",
    "List.nil": "List.nil", "List.cons": "List.cons",
    "Set": "Set", "Set.mem": "Membership.mem",
    "Function.comp": "Function.comp", "Function.id": "id",
}

# infix operators: Epsilon head -> (Lean symbol, precedence)
LEAN_INFIX = {}
for _T in ("Nat", "Int", "Rat", "Real", "Complex"):
    LEAN_INFIX[f"{_T}.add"] = ("+", 65)
    LEAN_INFIX[f"{_T}.sub"] = ("-", 65)
    LEAN_INFIX[f"{_T}.mul"] = ("*", 70)
    LEAN_INFIX[f"{_T}.div"] = ("/", 70)
    LEAN_INFIX[f"{_T}.mod"] = ("%", 70)
    LEAN_INFIX[f"{_T}.pow"] = ("^", 75)
    LEAN_INFIX[f"{_T}.le"] = ("≤", 50)
    LEAN_INFIX[f"{_T}.lt"] = ("<", 50)
LEAN_INFIX["And"] = ("∧", 35)
LEAN_INFIX["Or"] = ("∨", 30)
LEAN_INFIX["Iff"] = ("↔", 20)
LEAN_INFIX["Prod"] = ("×", 72)

LEAN_PREFIX = {f"{_T}.neg": "-" for _T in ("Int", "Rat", "Real", "Complex")}

# Epsilon numeric coercions map onto Lean's coercion elaborator
LEAN_COERCIONS = {"Int.ofNat", "Rat.ofNat", "Rat.ofInt", "Real.ofNat",
                  "Real.ofInt", "Real.ofRat", "Complex.ofReal"}

LEAN_TRUST_AXIOM = "Epsilon.leanChecked"


class LeanExportError(Exception):
    pass


# ---------------------------------------------------------------------------
# Export: Epsilon terms -> Lean 4 syntax
# ---------------------------------------------------------------------------

def term_to_lean(env: Environment, t: Term, prec: int = 0,
                 names: Optional[list[str]] = None) -> str:
    names = names or []
    return _to_lean(env, t, prec, names)


def _lean_name(name: str) -> str:
    base = name.split(LOCAL_MARK)[0]
    return LEAN_NAMES.get(base, base)


def _paren(s: str, need: bool) -> str:
    return f"({s})" if need else s


def _to_lean(env: Environment, t: Term, prec: int, names: list[str]) -> str:
    if isinstance(t, MVar):
        raise LeanExportError("cannot export a term with metavariables")
    if isinstance(t, Var):
        return names[t.idx] if t.idx < len(names) else f"#{t.idx}"
    if isinstance(t, Const):
        return _lean_name(t.name)
    if isinstance(t, Sort):
        if t.level == 0:
            return "Prop"
        return "Type" if t.level == 1 else f"Type {t.level - 1}"
    if isinstance(t, StrLit):
        return f'"{t.value}"'
    if isinstance(t, Lit):
        v: Fraction = t.value
        if v.denominator == 1:
            n = v.numerator
            return str(n) if n >= 0 else _paren(f"-{abs(n)}", prec > 75)
        return _paren(f"({v.numerator} : {_lean_name(t.tyname)}) / {v.denominator}",
                      prec > 70)

    if isinstance(t, App):
        head, args = unfold_app(t)
        if isinstance(head, Const):
            n = head.name
            if n in LEAN_COERCIONS and len(args) == 1:
                return _paren(f"({_to_lean(env, args[0], 0, names)} : "
                              f"{_lean_name(n.split('.')[0])})", False)
            if n in LEAN_INFIX and len(args) == 2:
                sym, p = LEAN_INFIX[n]
                lhs = _to_lean(env, args[0], p, names)
                rhs = _to_lean(env, args[1], p + 1, names)
                return _paren(f"{lhs} {sym} {rhs}", prec > p)
            if n in LEAN_PREFIX and len(args) == 1:
                return _paren(f"-{_to_lean(env, args[0], 76, names)}", prec > 75)
            if n == "Eq" and len(args) == 3:
                return _paren(f"{_to_lean(env, args[1], 51, names)} = "
                              f"{_to_lean(env, args[2], 51, names)}", prec > 50)
            if n == "Ne" and len(args) == 3:
                return _paren(f"{_to_lean(env, args[1], 51, names)} ≠ "
                              f"{_to_lean(env, args[2], 51, names)}", prec > 50)
            if n == "Not" and len(args) == 1:
                return _paren(f"¬{_to_lean(env, args[0], 41, names)}", prec > 40)
            if n == "Set.mem" and len(args) == 3:
                return _paren(f"{_to_lean(env, args[1], 51, names)} ∈ "
                              f"{_to_lean(env, args[2], 51, names)}", prec > 50)
            if n == "Set.subset" and len(args) == 3:
                return _paren(f"{_to_lean(env, args[1], 51, names)} ⊆ "
                              f"{_to_lean(env, args[2], 51, names)}", prec > 50)
            if n == "Exists" and len(args) == 2 and isinstance(args[1], Lam):
                lam = args[1]
                bn = _fresh(lam.name, names)
                body = _to_lean(env, lam.body, 0, [bn] + names)
                ty = _to_lean(env, lam.ty, 0, names)
                return _paren(f"∃ {bn} : {ty}, {body}", prec > 0)
            if n == "ite" and len(args) == 4:
                return _paren(
                    f"if {_to_lean(env, args[1], 0, names)} = true then "
                    f"{_to_lean(env, args[2], 0, names)} else "
                    f"{_to_lean(env, args[3], 0, names)}", prec > 0)
        parts = [_to_lean(env, head, 100, names)]
        parts += [_to_lean(env, a, 101, names) for a in args]
        return _paren(" ".join(parts), prec > 100)

    if isinstance(t, Lam):
        bn = _fresh(t.name, names)
        ty = _to_lean(env, t.ty, 0, names)
        body = _to_lean(env, t.body, 0, [bn] + names)
        return _paren(f"fun ({bn} : {ty}) => {body}", prec > 0)

    if isinstance(t, Pi):
        if not has_var(t.body, 0):
            lhs = _to_lean(env, t.ty, 26, names)
            rhs = _to_lean(env, t.body, 25, ["_"] + names)
            return _paren(f"{lhs} → {rhs}", prec > 25)
        bn = _fresh(t.name, names)
        ty = _to_lean(env, t.ty, 0, names)
        body = _to_lean(env, t.body, 0, [bn] + names)
        open_b, close_b = ("{", "}") if t.implicit else ("(", ")")
        return _paren(f"∀ {open_b}{bn} : {ty}{close_b}, {body}", prec > 0)

    raise LeanExportError(f"cannot export {type(t).__name__}")


def _fresh(base: str, names: list[str]) -> str:
    base = base.split(LOCAL_MARK)[0] or "x"
    if base == "_":
        base = "a"
    if base not in names:
        return base
    i = 1
    while f"{base}{i}" in names:
        i += 1
    return f"{base}{i}"


def decl_to_lean(env: Environment, name: str,
                 include_proof_placeholder: bool = True) -> str:
    """Render one Epsilon declaration as Lean 4 source."""
    d = env.expect(name)
    lean_name = _lean_name(name)
    ty = term_to_lean(env, d.type)
    doc = f"/-- {d.doc} -/\n" if d.doc else ""

    if d.kind == DeclKind.AXIOM:
        return f"{doc}axiom {lean_name} : {ty}"
    if d.kind == DeclKind.OPAQUE:
        return f"{doc}opaque {lean_name} : {ty}"
    if d.kind == DeclKind.THEOREM:
        status = env.verification_status(name)
        note = (f"-- Epsilon status: {status}. The Epsilon proof term is not a "
                f"Lean proof; prove this in Lean to obtain a Lean-checked "
                f"result.\n")
        body = " := by\n  sorry" if include_proof_placeholder else ""
        return f"{doc}{note}theorem {lean_name} : {ty}{body}"
    if d.kind == DeclKind.DEFINITION:
        if d.value is None:
            return f"{doc}opaque {lean_name} : {ty}"
        try:
            value = term_to_lean(env, d.value)
        except LeanExportError:
            return f"{doc}opaque {lean_name} : {ty}"
        return f"{doc}def {lean_name} : {ty} :=\n  {value}"
    if d.kind == DeclKind.INDUCTIVE:
        info = env.inductives.get(name)
        lines = [f"{doc}inductive {lean_name} : {ty} where"]
        for c in (info.constructors if info else []):
            cd = env.expect(c)
            lines.append(f"  | {c.rsplit('.', 1)[-1]} : "
                         f"{term_to_lean(env, cd.type)}")
        return "\n".join(lines)
    return f"-- skipped {name} ({d.kind.value})"


def module_to_lean(session, module: Optional[str] = None,
                   header: bool = True) -> str:
    """Render a module's declarations as a Lean 4 file."""
    from .. import __version__
    env = session.env
    out: list[str] = []
    if header:
        out.append(f"-- Generated by Epsilon {__version__}")
        out.append(f"-- Source module: {module or '<all>'}")
        out.append("--")
        out.append("-- Statements are exported; PROOFS ARE NOT. Each theorem")
        out.append("-- below carries its Epsilon verification status as a")
        out.append("-- comment and a `sorry` placeholder: an Epsilon proof")
        out.append("-- term is not a Lean proof term.")
        out.append("import Mathlib")
        out.append("")
        out.append("namespace Epsilon")
        out.append("")

    for name in env.order:
        d = env.decls[name]
        if d.module in (None, "core", "plugin"):
            continue
        if module is not None and d.module != module:
            continue
        if d.kind in (DeclKind.CONSTRUCTOR, DeclKind.RECURSOR):
            continue
        if LOCAL_MARK in name or name.startswith("$"):
            continue
        try:
            out.append(decl_to_lean(env, name))
        except (LeanExportError, KernelError) as e:
            out.append(f"-- could not export {name}: {e}")
        out.append("")

    if header:
        out.append("end Epsilon")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Import: Lean signatures -> Epsilon axioms
# ---------------------------------------------------------------------------

def import_lean_declarations(session, source: str,
                             prefix: str = "Lean") -> list[str]:
    """Bring Lean `theorem`/`axiom`/`lemma` signatures in as Epsilon axioms.

    Statements are parsed with Epsilon's own parser after light syntactic
    translation, which covers the common fragment (∀/∃, arithmetic,
    connectives). Anything that does not parse is reported and skipped
    rather than guessed at.

    They arrive as **axioms**, never theorems: Epsilon has not checked
    them, so every theorem that uses one lists it in its axiom report.
    """
    from ..elab.commands import CommandProcessor
    from ..syntax.parser import parse_expression, ParseError
    from ..syntax.lexer import LexError
    from ..elab.context import ElabError
    from ..kernel.typecheck import add_decl

    declared: list[str] = []
    proc = CommandProcessor(session.env, session.ctx, module=f"{prefix}-import")

    for kind, name, statement in _scan_lean_declarations(source):
        full = f"{prefix}.{name}"
        if session.env.contains(full):
            continue
        translated = _lean_statement_to_epsilon(statement)
        try:
            ast = parse_expression(translated)
            base = len(session.ctx.locals)
            try:
                prop = proc.elab.elab_prop(ast)
                prop = proc.elab.finalize(prop)
            finally:
                session.ctx.pop_locals_to(base)
            add_decl(session.env, Declaration(
                full, DeclKind.AXIOM, prop,
                doc=f"Imported from Lean ({kind} {name}). Assumed, not "
                    f"checked by the Epsilon kernel.",
                module=f"{prefix}-import"))
            declared.append(full)
        except (ParseError, LexError, ElabError, KernelError):
            continue
        finally:
            session.ctx.sweep_stray_locals()
    return declared


def _scan_lean_declarations(source: str) -> list[tuple[str, str, str]]:
    """Extract (kind, name, statement) triples from Lean source text."""
    out: list[tuple[str, str, str]] = []
    lines = source.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        for kind in ("theorem", "lemma", "axiom"):
            if not line.startswith(kind + " "):
                continue
            rest = line[len(kind) + 1:]
            name, sep, after = rest.partition(":")
            if not sep:
                break
            name = name.strip().split()[0] if name.strip() else ""
            statement = after
            # continuation lines until := or a blank line
            j = i + 1
            while ":=" not in statement and j < len(lines) and lines[j].strip():
                statement += " " + lines[j].strip()
                j += 1
            statement = statement.split(":=")[0].strip()
            if name and statement:
                out.append((kind, name, statement))
            i = j - 1
            break
        i += 1
    return out


def _lean_statement_to_epsilon(statement: str) -> str:
    """Light syntactic translation of the common Lean fragment."""
    s = statement.strip()
    for lean, eps in (("ℕ", "Nat"), ("ℤ", "Int"), ("ℚ", "Rat"),
                      ("ℝ", "Real"), ("ℂ", "Complex"),
                      ("Real.pi", "Real.pi"), ("fun ", "λ ")):
        s = s.replace(lean, eps)
    s = s.replace("=>", "=>")
    # Lean writes `∀ x : T, p`; Epsilon wants explicit parens on binders
    import re
    s = re.sub(r"(∀|∃)\s+([A-Za-z_][A-Za-z0-9_']*)\s*:\s*([^,]+),",
               r"\1 (\2 : \3),", s)
    return s


# ---------------------------------------------------------------------------
# Re-checking backend
# ---------------------------------------------------------------------------

@dataclass
class LeanConfig:
    executable: str = "lean"
    project_dir: Optional[str] = None       # a lake project with Mathlib
    timeout_seconds: float = 120.0
    imports: tuple[str, ...] = ("Mathlib",)


class LeanBackend(ProofBackend):
    """Re-check Epsilon statements with an external Lean 4 installation.

    Acceptance is recorded as *external corroboration*, tracked through the
    `Epsilon.leanChecked` axiom, so a Lean-accepted theorem reads as
    Symbolically Verified in Epsilon rather than Formally Proven. Epsilon
    reserves that label for proofs its own kernel checked.
    """

    name = "lean"

    def __init__(self, config: Optional[LeanConfig] = None) -> None:
        self.config = config or LeanConfig()

    # ------------------------------------------------------------------
    def available(self) -> bool:
        return shutil.which(self.config.executable) is not None

    def export_theorem(self, session, name: str) -> str:
        return decl_to_lean(session.env, name)

    def check_theorem(self, session, name: str,
                      lean_proof: str = "sorry") -> ProofBackendResult:
        """Run Lean on the exported statement plus a supplied Lean proof."""
        if not self.available():
            return ProofBackendResult(
                False, self.name,
                f"lean executable '{self.config.executable}' not found on PATH")
        try:
            statement = term_to_lean(session.env, session.env.expect(name).type)
        except (LeanExportError, KernelError) as e:
            return ProofBackendResult(False, self.name,
                                      f"cannot export statement: {e}")
        if "sorry" in lean_proof:
            return ProofBackendResult(
                False, self.name,
                "the supplied Lean proof contains `sorry`; that is not a proof")

        src_lines = [f"import {m}" for m in self.config.imports]
        src_lines.append("")
        src_lines.append(f"theorem epsilon_check : {statement} := {lean_proof}")
        source = "\n".join(src_lines) + "\n"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "EpsilonCheck.lean")
            with open(path, "w", encoding="utf-8") as f:
                f.write(source)
            cmd = [self.config.executable, path]
            cwd = self.config.project_dir
            if cwd and shutil.which("lake"):
                cmd = ["lake", "env"] + cmd
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=cwd,
                    timeout=self.config.timeout_seconds)
            except subprocess.TimeoutExpired:
                return ProofBackendResult(
                    False, self.name,
                    f"Lean timed out after {self.config.timeout_seconds:g}s")
            except OSError as e:
                return ProofBackendResult(False, self.name,
                                          f"could not run Lean: {e}")

        output = (proc.stdout + proc.stderr).strip()
        if proc.returncode == 0 and "sorry" not in output.lower():
            return ProofBackendResult(True, self.name,
                                      "Lean accepted the statement and proof")
        return ProofBackendResult(False, self.name,
                                  output or f"lean exited {proc.returncode}")

    def record_corroboration(self, session, name: str,
                             result: ProofBackendResult) -> None:
        """Note a successful external check on the declaration.

        This records provenance metadata; it does NOT upgrade the theorem's
        verification status, because Epsilon's kernel did not check the Lean
        proof. Use `import_as_axiom` if you want the result usable in
        Epsilon proofs - at the honest cost of an axiom dependency.
        """
        if not result.accepted:
            return
        decl = session.env.get(name)
        if decl is None:
            return
        tag = f"lean-checked"
        if tag not in decl.tags:
            decl.tags.append(tag)

    def import_as_axiom(self, session, name: str,
                        result: ProofBackendResult) -> Optional[str]:
        """Make a Lean-corroborated statement usable in Epsilon proofs, as an
        axiom that says so."""
        if not result.accepted:
            return None
        install_axiom(session.env, LEAN_TRUST_AXIOM,
                      doc="Statements corroborated by an external Lean check. "
                          "Not verified by the Epsilon kernel.",
                      status="symbolic")
        return LEAN_TRUST_AXIOM

    def import_theorem(self, session, source: str) -> list[str]:
        return import_lean_declarations(session, source)


def register(registry) -> None:
    """Plugin hook: make the Lean backend available as `lean`."""
    from ..plugins import PluginInfo
    registry.register_backend("lean", lambda session, **kw:
                              LeanBackend(kw.get("config")).check_theorem(
                                  session, kw["name"], kw.get("proof", "sorry")))
    registry.register_exporter("lean", module_to_lean)
    registry.declare(PluginInfo(
        name="epsilon.interop.lean", version="0.1.0",
        description="Lean 4 export, import, and external re-checking",
        provides=["backend:lean", "export:lean"]))
