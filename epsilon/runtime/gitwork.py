"""Git for the workspace — the real git, spoken to over subprocess.

Everything here shells out to the `git` on this machine against the
workspace directory; nothing reimplements version control. A workspace that
is not a repository says so, and the browser build — which has no git at
all — refuses honestly rather than imitating one.
"""

from __future__ import annotations

import os
import shutil
import subprocess

GIT = shutil.which("git")


class GitError(RuntimeError):
    pass


def _run(root: str, *args: str, check: bool = True) -> str:
    if GIT is None:
        raise GitError("git is not installed on this machine")
    proc = subprocess.run([GIT, "-C", root, *args],
                          capture_output=True, text=True, timeout=30)
    if check and proc.returncode != 0:
        raise GitError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def available() -> bool:
    return GIT is not None


def is_repo(root: str) -> bool:
    return GIT is not None and os.path.isdir(os.path.join(root, ".git"))


def init(root: str) -> None:
    _run(root, "init", "-b", "main")
    # commits need an identity; a workspace-local one keeps global config alone
    _run(root, "config", "user.email", "epsilon@localhost")
    _run(root, "config", "user.name", "Epsilon")


def status(root: str) -> dict:
    if not is_repo(root):
        return {"ok": True, "repo": False, "changes": [], "branch": None}
    branch = _run(root, "rev-parse", "--abbrev-ref", "HEAD",
                  check=False).strip() or "main"
    changes = []
    out = _run(root, "status", "--porcelain=v1", "-z", check=False)
    for entry in out.split("\0"):
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        changes.append({
            "path": path,
            "staged": x not in (" ", "?"),
            "unstaged": y != " ",
            "status": (x + y).strip() or "??",
        })
    return {"ok": True, "repo": True, "branch": branch, "changes": changes}


def stage(root: str, paths: list[str]) -> None:
    if paths:
        _run(root, "add", "--", *paths)


def unstage(root: str, paths: list[str]) -> None:
    if paths:
        _run(root, "restore", "--staged", "--", *paths)


def discard(root: str, paths: list[str]) -> None:
    """Throw away unstaged edits to `paths`. Destructive — the UI confirms."""
    if not paths:
        return
    tracked, untracked = [], []
    for p in paths:
        probe = _run(root, "ls-files", "--", p, check=False)
        (tracked if probe.strip() else untracked).append(p)
    if tracked:
        _run(root, "checkout", "--", *tracked)
    for p in untracked:
        full = os.path.join(root, p)
        if os.path.isfile(full):
            os.remove(full)


def commit(root: str, message: str) -> str:
    if not message.strip():
        raise GitError("a commit needs a message")
    _run(root, "commit", "-m", message)
    return _run(root, "rev-parse", "--short", "HEAD").strip()


def diff(root: str, path: str | None = None, staged: bool = False) -> str:
    args = ["diff", "--no-color"]
    if staged:
        args.append("--cached")
    if path:
        args += ["--", path]
    return _run(root, *args, check=False)


def log(root: str, limit: int = 30) -> list[dict]:
    if not is_repo(root):
        return []
    out = _run(root, "log", f"-{max(1, min(200, limit))}",
               "--pretty=format:%h%x00%s%x00%an%x00%ad", "--date=relative",
               check=False)
    entries = []
    for line in out.splitlines():
        parts = line.split("\0")
        if len(parts) == 4:
            entries.append({"hash": parts[0], "subject": parts[1],
                            "author": parts[2], "date": parts[3]})
    return entries


def branches(root: str) -> dict:
    if not is_repo(root):
        return {"current": None, "branches": []}
    current = _run(root, "rev-parse", "--abbrev-ref", "HEAD",
                   check=False).strip()
    names = [b.strip().lstrip("* ").strip() for b in
             _run(root, "branch", "--list", check=False).splitlines()]
    return {"current": current, "branches": [n for n in names if n]}


def checkout(root: str, ref: str, create: bool = False) -> None:
    if create:
        _run(root, "checkout", "-b", ref)
    else:
        _run(root, "checkout", ref)
