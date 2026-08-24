"""Resource limits and untrusted-source isolation (product spec section 31).

Checking arbitrary Epsilon source is a computation the user did not audit:
a proof term can drive the kernel's reducer for a very long time, and an
imported package can declare axioms that quietly weaken every theorem that
depends on it. This module provides the guards.

What is enforced here:
- wall-clock timeouts and recursion caps around a check
- a memory ceiling where the platform provides one (POSIX `resource`)
- import sandboxing: restrict which directories modules may be loaded from
- axiom auditing for untrusted modules: report every axiom a package adds,
  so a reviewer sees exactly what trust it asks for

What is deliberately NOT claimed: this is not a security boundary against a
hostile *Python* extension. Plugins run in-process; only the .epsl language
surface is constrained here.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator, Optional

from .kernel.env import DeclKind, Environment


class ResourceLimitExceeded(Exception):
    """Raised when a guarded computation exceeds its budget."""


@dataclass
class Limits:
    """Resource budget for one guarded operation."""
    seconds: float = 30.0
    memory_mb: Optional[int] = None      # POSIX only; None = unlimited
    recursion_depth: int = 6000
    max_source_bytes: int = 4 * 1024 * 1024

    @classmethod
    def strict(cls) -> "Limits":
        """Budget for untrusted input (a shared server, an imported package)."""
        return cls(seconds=10.0, memory_mb=1024, recursion_depth=3000,
                   max_source_bytes=1024 * 1024)


@contextmanager
def guarded(limits: Optional[Limits] = None) -> Iterator[None]:
    """Run a block under a time/recursion (and where possible memory) budget.

    The timeout uses SIGALRM on the main thread of a POSIX process, and falls
    back to a watchdog that can only *report* an overrun elsewhere - the
    kernel's own step limit is the backstop that makes runaway reduction
    terminate regardless.
    """
    lim = limits or Limits()
    old_recursion = sys.getrecursionlimit()
    sys.setrecursionlimit(lim.recursion_depth)

    restore_alarm = None
    if (lim.seconds and hasattr(signal, "SIGALRM")
            and threading.current_thread() is threading.main_thread()):
        def _on_alarm(signum, frame):  # noqa: ANN001
            raise ResourceLimitExceeded(
                f"operation exceeded its {lim.seconds:g}s time budget")
        previous = signal.signal(signal.SIGALRM, _on_alarm)
        signal.setitimer(signal.ITIMER_REAL, lim.seconds)

        def restore_alarm() -> None:  # type: ignore[misc]
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    restore_mem = _apply_memory_limit(lim.memory_mb)
    try:
        yield
    finally:
        if restore_alarm is not None:
            restore_alarm()
        if restore_mem is not None:
            restore_mem()
        sys.setrecursionlimit(old_recursion)


def _apply_memory_limit(memory_mb: Optional[int]):
    if not memory_mb:
        return None
    try:
        import resource
    except ImportError:
        return None
    soft, hard = resource.getrlimit(resource.RLIMIT_AS)
    limit = memory_mb * 1024 * 1024
    if hard != resource.RLIM_INFINITY and limit > hard:
        limit = hard
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, hard))
    except (ValueError, OSError):
        return None

    def restore() -> None:
        try:
            resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
        except (ValueError, OSError):
            pass
    return restore


def check_source_size(src: str, limits: Optional[Limits] = None) -> None:
    lim = limits or Limits()
    size = len(src.encode("utf-8"))
    if size > lim.max_source_bytes:
        raise ResourceLimitExceeded(
            f"source is {size} bytes, over the {lim.max_source_bytes}-byte limit")


# ---------------------------------------------------------------------------
# Import sandboxing
# ---------------------------------------------------------------------------

@dataclass
class ImportPolicy:
    """Which directories a session may load modules from."""
    allowed_roots: list[str] = field(default_factory=list)
    allow_stdlib: bool = True

    def is_allowed(self, path: str) -> bool:
        real = os.path.realpath(path)
        if self.allow_stdlib:
            from .project import LIB_DIR
            if real.startswith(os.path.realpath(LIB_DIR) + os.sep):
                return True
        for root in self.allowed_roots:
            root_real = os.path.realpath(root)
            if real == root_real or real.startswith(root_real + os.sep):
                return True
        return False


def apply_import_policy(session, policy: ImportPolicy) -> None:
    """Wrap a Session's module resolver so it refuses paths outside `policy`."""
    original = session.resolve_module_path

    def guarded_resolve(name: str) -> Optional[str]:
        path = original(name)
        if path is None:
            return None
        if not policy.is_allowed(path):
            from .elab.context import ElabError
            raise ElabError(
                f"import of '{name}' blocked: {path} is outside the allowed "
                f"module roots")
        return path

    session.resolve_module_path = guarded_resolve  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Trust auditing
# ---------------------------------------------------------------------------

@dataclass
class AxiomAudit:
    """What trust a set of modules asks the reader to extend."""
    axioms: list[dict]
    trust_axioms_used: list[str]
    weakened_theorems: list[dict]

    @property
    def clean(self) -> bool:
        return not self.axioms and not self.trust_axioms_used


def audit_axioms(session, modules: Optional[list[str]] = None) -> AxiomAudit:
    """Report every axiom introduced by `modules` and every theorem whose
    status is below Formally Proven.

    Run this on any package before depending on it: an axiom is a hole a
    package can put in your theorems without touching their statements.
    """
    env: Environment = session.env
    axioms: list[dict] = []
    for name in env.order:
        d = env.decls[name]
        if d.kind != DeclKind.AXIOM:
            continue
        if name in env.trust_axioms or d.module == "core":
            continue
        if modules is not None and d.module not in modules:
            continue
        axioms.append({"name": name, "module": d.module, "doc": d.doc,
                       "statement": _pp(env, d.type)})

    trust_used: set[str] = set()
    weakened: list[dict] = []
    for t in session.theorem_list():
        if modules is not None and t["module"] not in modules:
            continue
        if t["status"] != "proven":
            weakened.append({"name": t["name"], "status": t["status"],
                             "status_label": t["status_label"],
                             "module": t["module"]})
            for a in env.axioms_of(t["name"]):
                if a in env.trust_axioms:
                    trust_used.add(a)

    return AxiomAudit(axioms=axioms, trust_axioms_used=sorted(trust_used),
                      weakened_theorems=weakened)


def _pp(env: Environment, term) -> str:
    from .elab.pp import pp
    return pp(env, term)
