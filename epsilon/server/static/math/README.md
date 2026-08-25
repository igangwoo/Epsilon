# The mathematics workbench (isolated)

This directory preserves the mathematics-first IDE front end exactly as it
last shipped: theorem list, proof explorer, CAS pane, rendered mathematics,
dependency graph, plot pane, the ε> console and the math expression overlay
(`legacy-workbench.js`, formerly `app.js`).

It is **not loaded** by the current build. The visible product is, for this
phase, a general-purpose Python/C++ programming IDE; mathematics returns
later as context-aware tools inside the programming workflow, backed by the
still-fully-tested engine (`epsilon/kernel`, `epsilon/cas`, `epsilon/elab`,
…) and its live API endpoints (`/api/check`, `/api/cas`, `/api/render`,
`/api/suggest`, `/api/mathify` — see `docs/CONTRACTS.md`).

Nothing here is dead code to clean up: it is a subsystem waiting for its
second act.
