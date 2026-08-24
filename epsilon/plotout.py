"""Plotting from a running program — the Python ↔ Graph bridge.

A program cannot reach into the IDE, but its stdout reaches the run panel.
`epsilon.plot(x, y)` prints one marker line carrying the series as JSON; the
run panel lifts marker lines out of the output and hands them to the same
plot renderer the `plot` command feeds, in the same spec shape
(docs/CONTRACTS.md, graphing section). The program stays an ordinary program
— run it outside the IDE and the markers are just lines on stdout.

    from epsilon import plot
    xs = [i / 10 for i in range(100)]
    plot(xs, [x * x for x in xs], label="x²")

Works identically in the server build (the subprocess's stdout) and the
browser build (the wheel is installed in Pyodide, stdout is captured).
"""

from __future__ import annotations

import json

#: one marker per line; unusual on purpose, so ordinary output never
#: collides with it
PLOT_MARKER = "##epsilon:plot##"


def plot(x, y=None, *, label: str = "") -> None:
    """Emit one series for the IDE's plot pane.

    `plot(ys)` uses indices for x; `plot(xs, ys)` plots pairs. Values must
    be finite numbers or None (a gap in the curve, e.g. a pole).
    """
    xs = list(x)
    if y is None:
        ys = [float(v) if v is not None else None for v in xs]
        xs = list(range(len(ys)))
    else:
        ys = [float(v) if v is not None else None for v in y]
        xs = [float(v) for v in xs]
    if len(xs) != len(ys):
        raise ValueError(f"x has {len(xs)} points but y has {len(ys)}")
    print(PLOT_MARKER + json.dumps(
        {"label": label, "x": xs, "y": ys}, separators=(",", ":")))
