"""Project manifests and package resolution (product spec sections 24-25).

An Epsilon project is a directory with an `epsilon.toml` manifest:

    [project]
    name = "my-analysis"
    version = "0.1.0"
    description = "Real analysis experiments"

    [dependencies]
    combinatorics = { path = "../combinatorics" }
    numbertheory  = { git = "https://example.com/nt.git", rev = "v1.2" }

    [build]
    source = "src"

Resolution is deterministic: dependencies are resolved depth-first, versions
are checked against declared requirements, and the resolved set is written to
`epsilon.lock` so a later build uses exactly the same inputs. Git
dependencies are recorded but not fetched here - fetching is the CLI's job,
and a locked revision is what makes the build reproducible.

Because a dependency can introduce axioms (which silently weaken every
theorem that uses it), `audit_project` reports the axioms each dependency
contributes - see epsilon.security.audit_axioms.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]

MANIFEST_NAME = "epsilon.toml"
LOCKFILE_NAME = "epsilon.lock"

_SEMVER = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.-]+))?$")


class PackageError(Exception):
    pass


@dataclass(frozen=True, order=True)
class Version:
    major: int = 0
    minor: int = 1
    patch: int = 0
    pre: str = ""

    @classmethod
    def parse(cls, text: str) -> "Version":
        m = _SEMVER.match(text.strip())
        if not m:
            raise PackageError(f"not a semantic version: {text!r}")
        return cls(int(m["major"]), int(m["minor"]), int(m["patch"]),
                   m["pre"] or "")

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.pre}" if self.pre else base

    def satisfies(self, requirement: str) -> bool:
        """Support `1.2.3`, `^1.2.3` (caret), `~1.2.3` (tilde), `>=1.2.3`, `*`."""
        req = requirement.strip()
        if req in ("*", ""):
            return True
        for op in (">=", "<=", ">", "<", "^", "~", "="):
            if req.startswith(op):
                target = Version.parse(req[len(op):])
                if op == ">=":
                    return self >= target
                if op == "<=":
                    return self <= target
                if op == ">":
                    return self > target
                if op == "<":
                    return self < target
                if op == "=":
                    return self == target
                if op == "^":  # compatible: same leading non-zero component
                    if target.major > 0:
                        return (self.major == target.major and self >= target)
                    if target.minor > 0:
                        return (self.major == 0 and self.minor == target.minor
                                and self >= target)
                    return (self.major == 0 and self.minor == 0
                            and self.patch == target.patch)
                if op == "~":  # same major.minor
                    return (self.major == target.major
                            and self.minor == target.minor and self >= target)
        return self == Version.parse(req)


@dataclass
class Dependency:
    name: str
    requirement: str = "*"
    path: Optional[str] = None
    git: Optional[str] = None
    rev: Optional[str] = None

    @property
    def kind(self) -> str:
        if self.path:
            return "path"
        if self.git:
            return "git"
        return "registry"


@dataclass
class Manifest:
    name: str
    version: Version = field(default_factory=Version)
    description: str = ""
    source_dir: str = "src"
    dependencies: list[Dependency] = field(default_factory=list)
    root: str = "."

    @classmethod
    def load(cls, project_dir: str) -> "Manifest":
        path = os.path.join(project_dir, MANIFEST_NAME)
        if not os.path.isfile(path):
            raise PackageError(f"no {MANIFEST_NAME} in {project_dir}")
        if tomllib is None:  # pragma: no cover
            raise PackageError("tomllib is unavailable; Python 3.11+ required")
        with open(path, "rb") as f:
            data = tomllib.load(f)
        proj = data.get("project", {})
        name = proj.get("name")
        if not name:
            raise PackageError(f"{path}: [project] needs a name")
        deps: list[Dependency] = []
        for dep_name, spec in (data.get("dependencies") or {}).items():
            if isinstance(spec, str):
                deps.append(Dependency(dep_name, requirement=spec))
            elif isinstance(spec, dict):
                deps.append(Dependency(
                    dep_name,
                    requirement=spec.get("version", "*"),
                    path=spec.get("path"), git=spec.get("git"),
                    rev=spec.get("rev")))
            else:
                raise PackageError(
                    f"{path}: dependency '{dep_name}' has an invalid spec")
        return cls(
            name=name,
            version=Version.parse(str(proj.get("version", "0.1.0"))),
            description=proj.get("description", ""),
            source_dir=(data.get("build", {}) or {}).get("source", "src"),
            dependencies=deps,
            root=os.path.abspath(project_dir))

    def source_paths(self) -> list[str]:
        src_root = os.path.join(self.root, self.source_dir)
        if not os.path.isdir(src_root):
            src_root = self.root
        out: list[str] = []
        for dirpath, _dirnames, filenames in os.walk(src_root):
            for fn in sorted(filenames):
                if fn.endswith(".epsl"):
                    out.append(os.path.join(dirpath, fn))
        return sorted(out)


@dataclass
class ResolvedPackage:
    name: str
    version: str
    kind: str
    location: str
    rev: Optional[str] = None


def resolve(manifest: Manifest, _seen: Optional[dict[str, ResolvedPackage]] = None,
            _chain: Optional[list[str]] = None) -> list[ResolvedPackage]:
    """Depth-first dependency resolution with cycle and conflict detection."""
    seen = _seen if _seen is not None else {}
    chain = _chain or [manifest.name]
    out: list[ResolvedPackage] = []

    for dep in manifest.dependencies:
        if dep.name in chain:
            raise PackageError(
                f"circular dependency: {' -> '.join(chain + [dep.name])}")

        if dep.kind == "path":
            dep_dir = os.path.normpath(os.path.join(manifest.root, dep.path))
            sub = Manifest.load(dep_dir)
            if not sub.version.satisfies(dep.requirement):
                raise PackageError(
                    f"{manifest.name} requires {dep.name} {dep.requirement}, "
                    f"but {dep_dir} provides {sub.version}")
            resolved = ResolvedPackage(sub.name, str(sub.version), "path",
                                       dep_dir)
            existing = seen.get(dep.name)
            if existing and existing.version != resolved.version:
                raise PackageError(
                    f"version conflict for '{dep.name}': "
                    f"{existing.version} vs {resolved.version}")
            if not existing:
                seen[dep.name] = resolved
                out.extend(resolve(sub, seen, chain + [dep.name]))
                out.append(resolved)
        else:
            resolved = ResolvedPackage(
                dep.name, dep.requirement, dep.kind,
                dep.git or "<registry>", dep.rev)
            existing = seen.get(dep.name)
            if existing and existing.rev != resolved.rev:
                raise PackageError(
                    f"revision conflict for '{dep.name}': "
                    f"{existing.rev} vs {resolved.rev}")
            if not existing:
                seen[dep.name] = resolved
                out.append(resolved)
    return out


def write_lockfile(manifest: Manifest, resolved: list[ResolvedPackage]) -> str:
    """Write epsilon.lock; returns its path. Deterministic ordering."""
    from . import __version__, LANGUAGE_VERSION
    data = {
        "lockfile_version": 1,
        "root": {"name": manifest.name, "version": str(manifest.version)},
        "epsilon": {"version": __version__,
                    "language_version": LANGUAGE_VERSION},
        "packages": [asdict(p) for p in sorted(resolved, key=lambda p: p.name)],
    }
    path = os.path.join(manifest.root, LOCKFILE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return path


def read_lockfile(project_dir: str) -> Optional[dict]:
    path = os.path.join(project_dir, LOCKFILE_NAME)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def module_search_paths(manifest: Manifest,
                        resolved: list[ResolvedPackage]) -> list[str]:
    """Directories a Session should resolve `import` against, in order."""
    paths = [os.path.join(manifest.root, manifest.source_dir), manifest.root]
    for p in resolved:
        if p.kind == "path":
            paths.append(os.path.join(p.location, "src"))
            paths.append(p.location)
    return [p for p in paths if os.path.isdir(p)]


def audit_project(session, manifest: Manifest,
                  resolved: list[ResolvedPackage]) -> dict:
    """Trust report for a project and its dependencies."""
    from .security import audit_axioms
    audit = audit_axioms(session)
    by_module: dict[str, list[str]] = {}
    for ax in audit.axioms:
        by_module.setdefault(ax["module"] or "<unknown>", []).append(ax["name"])
    return {
        "project": manifest.name,
        "version": str(manifest.version),
        "dependencies": [asdict(p) for p in resolved],
        "axioms_by_module": by_module,
        "trust_axioms_used": audit.trust_axioms_used,
        "weakened_theorems": audit.weakened_theorems,
        "clean": audit.clean,
    }
