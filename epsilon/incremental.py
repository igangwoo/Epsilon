"""Incremental checking and caching (product spec section 32).

Checking a file re-runs every command, which is wasteful in an editor where
one line changes between keystrokes. This module adds a per-command cache
keyed on the *prefix* of the file: a command's result is reusable only when
every command before it - and the command itself - is byte-identical to the
cached run, because a declaration's meaning depends on the environment it
was checked in.

That prefix rule is what makes the cache sound. It means an edit at the top
of a file invalidates everything below, which matches how a dependent-type
checker actually works, while an edit at the bottom (the common case while
writing a proof) reuses the whole prefix.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Optional

from .kernel.env import Environment
from .project import Session, CheckResult, Diagnostic
from .syntax import sast as S
from .syntax.parser import Parser, ParseError
from .syntax.lexer import LexError
from .elab.commands import CommandProcessor
from .elab.context import ElabError
from .elab.tactics import TacticError
from .kernel.env import KernelError


def _command_source(src_lines: list[str], cmd: S.Command) -> str:
    """The source text a command spans (used as its cache key material)."""
    l0, _, l1, _ = cmd.span
    if not l0:
        return repr(cmd)
    return "\n".join(src_lines[l0 - 1:l1])


@dataclass
class CacheEntry:
    prefix_hash: str
    results: list
    diagnostics: list[Diagnostic]
    env_size: int


@dataclass
class IncrementalChecker:
    """Checks a module, reusing the unchanged prefix of the previous run.

    One instance per open file. It owns its own Session, because reuse means
    holding on to the environment produced by the cached prefix.
    """

    module: str = "<main>"
    project_root: Optional[str] = None
    session: Session = field(default=None)  # type: ignore[assignment]
    _entries: list[CacheEntry] = field(default_factory=list)
    _base_env_size: int = 0
    stats: dict = field(default_factory=lambda: {"reused": 0, "rechecked": 0})

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = Session(project_root=self.project_root)
        self._base_env_size = self.session.env.snapshot_len()

    # ------------------------------------------------------------------
    def check(self, src: str) -> CheckResult:
        out = CheckResult(module=self.module)
        try:
            module = self.session.parse(src)
        except (ParseError, LexError) as e:
            line, col = getattr(e, "line", 0), getattr(e, "col", 0)
            out.diagnostics.append(Diagnostic(
                "error", getattr(e, "msg", str(e)), (line, col, line, col),
                self.module))
            # a parse error invalidates nothing structurally, but we cannot
            # know where the damage starts, so drop the cache
            self._reset()
            return out

        lines = src.split("\n")
        proc = CommandProcessor(self.session.env, self.session.ctx,
                                oracles=self.session.oracles, module=self.module)

        # rolling prefix hashes: entry i covers commands 0..i inclusive
        running = hashlib.sha256()
        hashes: list[str] = []
        for cmd in module.commands:
            running.update(_command_source(lines, cmd).encode())
            running.update(b"\x00")
            hashes.append(running.hexdigest())

        reuse_upto = 0
        for i, h in enumerate(hashes):
            if i < len(self._entries) and self._entries[i].prefix_hash == h:
                reuse_upto = i + 1
            else:
                break

        # roll the environment back to the end of the reusable prefix
        if reuse_upto:
            self.session.env.rollback_to(self._entries[reuse_upto - 1].env_size)
        else:
            self.session.env.rollback_to(self._base_env_size)
        self.session.ctx.pop_locals_to(0)
        self.session.ctx.sweep_stray_locals()
        del self._entries[reuse_upto:]

        for e in self._entries[:reuse_upto]:
            out.results.extend(e.results)
            out.diagnostics.extend(e.diagnostics)
        self.stats["reused"] += reuse_upto

        for i in range(reuse_upto, len(module.commands)):
            cmd = module.commands[i]
            before = len(out.results), len(out.diagnostics)
            self.session._run_command(proc, cmd, out)
            self._entries.append(CacheEntry(
                prefix_hash=hashes[i],
                results=out.results[before[0]:],
                diagnostics=out.diagnostics[before[1]:],
                env_size=self.session.env.snapshot_len()))
            self.stats["rechecked"] += 1

        return out

    def _reset(self) -> None:
        self._entries.clear()
        self.session.env.rollback_to(self._base_env_size)
        self.session.ctx.pop_locals_to(0)
        self.session.ctx.sweep_stray_locals()


# ---------------------------------------------------------------------------
# Memoization for expensive pure computations (CAS / numeric / rendering)
# ---------------------------------------------------------------------------

class TermCache:
    """Bounded memo table keyed on kernel terms.

    Kernel terms are frozen dataclasses, so they hash structurally - which
    is exactly the identity CAS and numeric backends want.
    """

    def __init__(self, capacity: int = 4096) -> None:
        self.capacity = capacity
        self._data: dict[tuple, object] = {}
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: tuple, compute):
        try:
            hit = self._data.get(key, _MISS)
        except TypeError:  # unhashable key: skip caching entirely
            return compute()
        if hit is not _MISS:
            self.hits += 1
            return hit
        self.misses += 1
        value = compute()
        if len(self._data) >= self.capacity:
            # cheap eviction: drop the oldest eighth
            for k in list(self._data)[: self.capacity // 8]:
                self._data.pop(k, None)
        self._data[key] = value
        return value

    def clear(self) -> None:
        self._data.clear()
        self.hits = self.misses = 0


_MISS = object()
