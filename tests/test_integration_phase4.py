"""Phase 4: the panes talk to each other through shared, honest shapes.

Python ↔ Graph goes through stdout markers; Python/C++ ↔ mathematics goes
through a reader for the arithmetic subset the languages share; CAS results
carry a runnable Python form. In every direction the data is one of the
documented spec shapes — that is the cross-pane data model.
"""

import json

import pytest

from epsilon.interop.mathexpr import MathExprError, parse_math_expr
from epsilon.plotout import PLOT_MARKER, plot
from epsilon.project import Session


@pytest.fixture(scope="module")
def sess():
    return Session()


# --------------------------------------------------------------------------
# epsilon.plot — the Python ↔ Graph bridge
# --------------------------------------------------------------------------

def test_plot_emits_one_marker_line(capsys):
    plot([1, 2, 3], [1, 4, 9], label="sq")
    line = capsys.readouterr().out.strip()
    assert line.startswith(PLOT_MARKER)
    data = json.loads(line[len(PLOT_MARKER):])
    assert data == {"label": "sq", "x": [1.0, 2.0, 3.0], "y": [1.0, 4.0, 9.0]}


def test_plot_without_x_uses_indices(capsys):
    plot([5, 6])
    data = json.loads(capsys.readouterr().out.strip()[len(PLOT_MARKER):])
    assert data["x"] == [0, 1]


def test_plot_none_is_a_gap_not_an_error(capsys):
    plot([0, 1, 2], [1, None, 3])
    data = json.loads(capsys.readouterr().out.strip()[len(PLOT_MARKER):])
    assert data["y"][1] is None


def test_plot_length_mismatch_is_refused():
    with pytest.raises(ValueError):
        plot([1, 2], [1])


def test_a_run_really_carries_the_marker():
    """The whole chain: a program using epsilon.plot, run by the runner."""
    from epsilon.runtime import run_code
    r = run_code("python",
                 "from epsilon import plot\n"
                 "plot([0, 1, 2], [0, 1, 4], label='sq')\n"
                 "print('done')\n")
    assert r.ok, r.stderr
    marker = [l for l in r.stdout.splitlines() if l.startswith(PLOT_MARKER)]
    assert len(marker) == 1
    assert "done" in r.stdout


# --------------------------------------------------------------------------
# the maths inside Python/C++ source
# --------------------------------------------------------------------------

@pytest.mark.parametrize("src,latex", [
    ("math.sin(x)/x", r"\frac{\sin\!\left(x\right)}{x}"),
    ("std::pow(x, 2) + 1", "x^{2} + 1"),
    ("x**2 - 4*x + 4", r"x^{2} - 4 \cdot x + 4"),
    ("sqrt(x*x + y*y)", r"\sqrt{x \cdot x + y \cdot y}"),
    ("math.pi * r ** 2", r"\pi \cdot r^{2}"),
    ("M_PI / 2", r"\frac{\pi}{2}"),
    ("np.exp(-t)", r"\exp\!\left(-t\right)"),
])
def test_shared_arithmetic_reads_as_mathematics(sess, src, latex):
    from epsilon.exporters.latex import term_to_latex
    assert term_to_latex(sess.env, parse_math_expr(src)) == latex


@pytest.mark.parametrize("src", [
    "print(1)",            # a statement, not mathematics
    "x = 2",               # assignment
    "foo.bar(x)",          # an unknown qualified call
    "f(x, y)",             # an unknown function: guessing would lie
    "a ^ b",               # C++ xor is not exponentiation
    "xs[0] + 1",           # indexing is outside the subset
    "",
])
def test_non_mathematics_is_refused_not_guessed(src):
    with pytest.raises(MathExprError):
        parse_math_expr(src)


def test_power_is_right_associative():
    from epsilon.kernel.term import unfold_app
    head, args = unfold_app(parse_math_expr("a ** b ** c"))
    assert head.name == "Real.pow"
    inner_head, _ = unfold_app(args[1])
    assert inner_head.name == "Real.pow"
