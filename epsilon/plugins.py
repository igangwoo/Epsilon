"""The plugin system (product spec section 34).

Extension points, each a registry a plugin writes into:

- **tactics**      - custom tactics, callable from `by ...`
- **oracles**      - decision procedures behind `cas` / `numeric`-style
                     tactics, each bound to a tracked trust axiom
- **exporters**    - new output formats for `epsilon export`
- **backends**     - compiler backends (Python, C, ...) and proof backends
                     (e.g. re-checking a theorem with Lean)
- **visualizers**  - renderers for plots, proof trees, dependency graphs

The trust rule holds for plugins exactly as for built-ins: a plugin tactic
constructs a proof term and the kernel checks it. A plugin that wants to
assert something it cannot prove must register an *oracle* with its own
axiom, which then shows up in every dependent theorem's axiom list - a
plugin cannot quietly turn an unproven claim into "Formally Proven".
"""

from __future__ import annotations

import importlib
import importlib.metadata
from dataclasses import dataclass, field
from typing import Callable, Optional

from .kernel.env import Declaration, DeclKind, Environment, KernelError
from .kernel.term import Term, Const, App, Pi
from .kernel.typecheck import add_decl

ENTRY_POINT_GROUP = "epsilon.plugins"


class PluginError(Exception):
    pass


@dataclass
class PluginInfo:
    name: str
    version: str = "0.0.0"
    description: str = ""
    author: str = ""
    provides: list[str] = field(default_factory=list)


class Registry:
    """Global extension registries. Populated at import time by plugins."""

    def __init__(self) -> None:
        self.plugins: dict[str, PluginInfo] = {}
        self.tactics: dict[str, Callable] = {}
        self.tactic_docs: dict[str, str] = {}
        self.oracles: dict[str, tuple[Callable, str]] = {}  # name -> (fn, axiom)
        self.oracle_status: dict[str, str] = {}
        self.oracle_docs: dict[str, str] = {}
        self.exporters: dict[str, Callable] = {}
        self.backends: dict[str, Callable] = {}
        self.visualizers: dict[str, Callable] = {}
        self._loaded_modules: set[str] = set()
        self._current_plugin: Optional[str] = None

    # ------------------------------------------------------------------
    def register_tactic(self, name: str, fn: Callable, doc: str = "",
                        plugin: Optional[str] = None) -> None:
        """Register a tactic. `fn(state, tac)` follows the built-in protocol
        in `epsilon.elab.tactics`: mutate the goal state, close goals with
        terms, raise TacticError on failure."""
        from .elab import tactics as T
        if name in T._HANDLERS and name not in self.tactics:
            raise PluginError(f"tactic '{name}' would shadow a built-in")
        self.tactics[name] = fn
        self.tactic_docs[name] = doc
        T._HANDLERS[name] = fn
        owner = plugin or self._current_plugin
        if owner:
            self.plugins.setdefault(
                owner, PluginInfo(owner)).provides.append(f"tactic:{name}")

    def register_oracle(self, name: str, fn: Callable, axiom: str,
                        doc: str = "", plugin: Optional[str] = None,
                        status: str = "symbolic") -> None:
        """Register a decision procedure with the trust axiom it stands on.

        `fn(env, prop) -> (ok: bool, reason: str)`. Every theorem closed by
        this oracle depends on `axiom`, and the axiom is registered as a
        trust axiom capping those theorems at `status` - so an oracle can
        never make a result read as Formally Proven, which is the honest
        outcome for a procedure Epsilon's kernel did not verify.

        `status` is one of "symbolic", "numeric", "heuristic".
        """
        self.oracles[name] = (fn, axiom)
        self.oracle_status[name] = status
        self.oracle_docs[name] = doc
        owner = plugin or self._current_plugin
        if owner:
            self.plugins.setdefault(
                owner, PluginInfo(owner)).provides.append(f"oracle:{name}")

    def register_exporter(self, fmt: str, fn: Callable,
                          plugin: Optional[str] = None) -> None:
        """`fn(session, module=None) -> str`."""
        self.exporters[fmt] = fn
        owner = plugin or self._current_plugin
        if owner:
            self.plugins.setdefault(
                owner, PluginInfo(owner)).provides.append(f"export:{fmt}")

    def register_backend(self, name: str, fn: Callable,
                         plugin: Optional[str] = None) -> None:
        """A compiler or proof backend. `fn(session, **options)`."""
        self.backends[name] = fn
        owner = plugin or self._current_plugin
        if owner:
            self.plugins.setdefault(
                owner, PluginInfo(owner)).provides.append(f"backend:{name}")

    def register_visualizer(self, name: str, fn: Callable,
                            plugin: Optional[str] = None) -> None:
        self.visualizers[name] = fn
        owner = plugin or self._current_plugin
        if owner:
            self.plugins.setdefault(
                owner, PluginInfo(owner)).provides.append(f"viz:{name}")

    def declare(self, info: PluginInfo) -> None:
        existing = self.plugins.get(info.name)
        if existing is not None:
            info.provides = existing.provides + info.provides
        self.plugins[info.name] = info

    # ------------------------------------------------------------------
    def load_module(self, module_name: str) -> PluginInfo:
        """Import a Python module and run its `register(registry)` hook."""
        if module_name in self._loaded_modules:
            return self.plugins.get(module_name, PluginInfo(module_name))
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            raise PluginError(f"cannot import plugin '{module_name}': {e}")
        hook = getattr(mod, "register", None)
        if hook is None:
            raise PluginError(
                f"plugin '{module_name}' has no register(registry) function")
        previous = self._current_plugin
        self._current_plugin = module_name
        try:
            info = hook(self)
        finally:
            self._current_plugin = previous
        self._loaded_modules.add(module_name)
        if isinstance(info, PluginInfo):
            self.declare(info)
            return info
        found = self.plugins.get(module_name)
        if found is None:
            found = PluginInfo(module_name)
            self.declare(found)
        return found

    def discover(self) -> list[PluginInfo]:
        """Load every plugin advertised through the `epsilon.plugins`
        entry-point group of installed distributions."""
        out: list[PluginInfo] = []
        try:
            eps = importlib.metadata.entry_points()
            group = (eps.select(group=ENTRY_POINT_GROUP)
                     if hasattr(eps, "select") else eps.get(ENTRY_POINT_GROUP, []))
        except Exception:  # noqa: BLE001 - discovery must never break a session
            return out
        for ep in group:
            try:
                out.append(self.load_module(ep.value.split(":")[0]))
            except PluginError:
                continue
        return out

    def describe(self) -> list[dict]:
        return [{"name": p.name, "version": p.version,
                 "description": p.description, "author": p.author,
                 "provides": sorted(set(p.provides))}
                for p in sorted(self.plugins.values(), key=lambda p: p.name)]


REGISTRY = Registry()


# ---------------------------------------------------------------------------
# Session wiring
# ---------------------------------------------------------------------------

def install_axiom(env: Environment, axiom: str, doc: str = "",
                  status: str = "symbolic") -> None:
    """Declare a plugin's trust axiom `axiom : ∀ (p : Prop), p` and register
    it as a trust axiom capping dependent theorems at `status`.

    This is the shape every oracle axiom has: it lets the oracle assert any
    proposition, which is precisely why depending on it must be visible -
    and why registering the trust level is not optional.
    """
    env.register_trust_axiom(axiom, status)
    if env.contains(axiom):
        return
    from .kernel.inductive import close_pi, ph
    from .kernel.term import PROP
    add_decl(env, Declaration(
        axiom, DeclKind.AXIOM, close_pi([("p", PROP)], ph("p")),
        doc=doc or f"Trust axiom for the '{axiom}' oracle. Theorems depending "
                   f"on it are NOT Formally Proven.",
        module="plugin"))


def apply_to_session(session, registry: Registry = REGISTRY) -> None:
    """Make registered oracles available to a session and declare their
    axioms, and register plugin tactic bridges for them."""
    from .elab import tactics as T

    for name, (fn, axiom) in registry.oracles.items():
        install_axiom(session.env, axiom,
                      doc=registry.oracle_docs.get(name, ""),
                      status=registry.oracle_status.get(name, "symbolic"))
        session.oracles[name] = fn
        if name in T._HANDLERS:
            continue

        def make_handler(oracle_name: str, ax: str):
            def handler(state, tac):
                T._oracle_close(state, tac, oracle_name, ax)
            return handler

        T._HANDLERS[name] = make_handler(name, axiom)

    for name, fn in registry.tactics.items():
        T._HANDLERS.setdefault(name, fn)


def load_plugins(session, module_names: list[str],
                 registry: Registry = REGISTRY) -> list[PluginInfo]:
    """Load plugins by module name and wire them into `session`."""
    infos = [registry.load_module(n) for n in module_names]
    apply_to_session(session, registry)
    return infos


# ---------------------------------------------------------------------------
# Proof backends (section 28: Lean interoperability architecture)
# ---------------------------------------------------------------------------

@dataclass
class ProofBackendResult:
    accepted: bool
    backend: str
    detail: str = ""
    external_id: Optional[str] = None


class ProofBackend:
    """Base class for an external proof checker.

    A backend re-checks an Epsilon theorem in another system. Acceptance by
    an external backend is *corroboration*, not an Epsilon kernel proof:
    `Session.verification_status` is unchanged by it, and a theorem that
    only an external backend accepts must be reported as such. Backends are
    how Lean interoperability plugs in (see docs/ARCHITECTURE.md).
    """

    name = "abstract"

    def export_theorem(self, session, name: str) -> str:
        """Render a theorem in the backend's input language."""
        raise NotImplementedError

    def check_theorem(self, session, name: str) -> ProofBackendResult:
        raise NotImplementedError

    def import_theorem(self, session, source: str) -> list[str]:
        """Bring external statements in as *axioms* (they are unproven here),
        returning the declared names. Never as theorems: importing a claim is
        assuming it."""
        raise NotImplementedError
