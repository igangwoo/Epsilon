# Epsilon IDE — feature and implementation plan

The product goal is one environment that carries a piece of work along the
whole chain:

```
mathematical thinking → definition → proof / formal verification →
symbolic computation → numerical computation → visualization →
algorithm design → Python / C++ implementation → testing → LaTeX export
```

Mathematics is the primary identity. Python and C++ are not export targets
bolted on the side; they are first-class execution environments for the
numerical and general-purpose programming parts of that chain.

## Design principles

These bind every feature below.

1. Mathematics is the primary identity of Epsilon.
2. Python and C++ are first-class coding environments, not merely export
   targets.
3. The IDE is modular and pane-based.
4. No ad-hoc UI system per feature — every tool uses the same pane and
   workspace infrastructure.
5. Mathematical notation is rendered beautifully, but source code stays
   valid source code.
6. Source is never modified in order to render notation. Rendering is a
   separate visual layer.
7. Internal theorem identifiers stay separate from human-readable
   mathematical names.
8. Formal verification and CAS computation stay explicitly
   distinguishable — a CAS result is never shown as a formal proof.
9. Expensive computation runs off the UI thread.
10. Features communicate through a common workspace data model, not
    through tightly coupled UI components.
11. Real, extensible implementations — not mocks.
12. Existing compiler and language functionality is not rewritten unless
    the architecture requires it.
13. Existing functionality and tests are preserved.
14. The default screen stays simple despite the number of available tools.
15. Advanced functionality is discoverable through panes, the command
    palette, context menus and contextual suggestions.

## Pane kinds

One infrastructure hosts all of them:

```
Editor · Proof · CAS · Graph · Console · Dependency Graph · File Explorer
Problems · Documentation · LaTeX Preview · Python · C++ · Data Viewer
Algorithm · Notes · Terminal
```

Every pane supports: create, close, reopen, move, resize, split
(horizontal / vertical), tabs, float, maximize, restore, pin, and state
persistence. Workspace layouts can be saved, restored and reset, with
multiple named profiles (Mathematics, Algorithm, Python Development,
Research).

## Phases

Built in this order rather than all at once.

**Phase 1 — IDE foundation.** Pane system · workspace layout · file
explorer · universal editor · command palette · problems panel.

**Phase 2 — Mathematics.** Proof explorer · theorem search ·
human-readable stdlib names · LaTeX rendering · proof tree · dependency
graph · CAS pane · graph pane.

**Phase 3 — Programming.** Python runtime, console and editor · C++
compiler, runner and console.

**Phase 4 — Integration.** Python ↔ Graph · Python ↔ CAS · Epsilon ↔ CAS ·
Epsilon → Python · code → LaTeX · mathematical expression overlay ·
cross-pane data model.

**Phase 5 — Algorithms.** Algorithm workspace · pseudocode · complexity
panel · test cases · Python/C++ comparison · correctness-proof
integration.

**Phase 6 — Polish.** Persistence · keyboard shortcuts · performance ·
accessibility · error handling · documentation · UI polish.

## Status

Tracked here as each piece lands; `docs/ROADMAP.md` covers the language
and engine side.

| Area | State |
|------|-------|
| Human-readable stdlib names (Phase 2) | done — `@[name "..."]`, 128 library results named, shown in the IDE and searchable |
| Theorem search (Phase 2) | done — search by mathematical words |
| Dependency graph (Phase 2) | done — relaxing layout, filters, click-to-inspect |
| Proof tree (Phase 2) | done — recorded tactic traces rendered per theorem |
| Problems panel (Phase 1) | done — unified diagnostics, click to jump |
| Command palette (Phase 1) | done — commands, files, exports |
| Universal editor (Phase 1) | done — Epsilon, Python, C++, Markdown, JSON/YAML/TOML, LaTeX, JS, shell |
| File explorer (Phase 1) | done — folder tree, rename, duplicate, delete, drag-to-move, type icons, filter |
| Pane system (Phase 1) | done — split/tab/move/maximize, saved layouts, 4 profiles |
| CAS pane (Phase 2) | done — 9 operations, MathML results, insert into editor, status-labelled |
| Rendered mathematics (Phase 2) | done — MathML typesetting of the checked file, LaTeX export |
| Proof explorer (Phase 2) | pending |
| Python, C++, data, algorithm panes | pending |

Mathematical status labels stay exactly as the engine reports them:
`✓ Formally Proven`, `✓ Symbolically Verified`, `≈ Numerically Verified`,
`⚠ Heuristic Result`. The IDE never promotes one to another.
