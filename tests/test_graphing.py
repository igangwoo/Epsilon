"""Tests for the graphing subsystem (epsilon.graphing)."""

from __future__ import annotations

import math
from xml.sax.saxutils import escape

import pytest

from epsilon.graphing import sample_function, plot_spec, render_svg
from epsilon.kernel.term import Const
from epsilon.project import Session


@pytest.fixture(scope="module")
def session() -> Session:
    return Session()


@pytest.fixture(scope="module")
def env(session):
    return session.env


def elab(session: Session, src: str):
    """Elaborate a surface expression to a kernel Term (contract recipe)."""
    from epsilon.elab.elaborator import Elaborator
    from epsilon.syntax.parser import parse_expression
    el = Elaborator(session.env, session.ctx)
    t = el.elab_expr(parse_expression(src, extra_ops=dict(session.extra_ops)),
                     None)
    return el.finalize(t)


# ---------------------------------------------------------------------------
# sample_function
# ---------------------------------------------------------------------------

class TestSampleFunction:
    def test_sin_over_pi(self, session, env):
        f = elab(session, "fun (x : ℝ) => sin(x)")
        result = sample_function(env, f, -math.pi, math.pi, n=200)
        assert len(result["x"]) == 201
        assert len(result["y"]) == 201
        assert result["x"][0] == pytest.approx(-math.pi)
        assert result["x"][-1] == pytest.approx(math.pi)
        assert all(y is not None for y in result["y"])
        for x, y in zip(result["x"], result["y"]):
            assert y == pytest.approx(math.sin(x), abs=1e-9)
        assert max(result["y"]) <= 1.0 + 1e-9
        assert min(result["y"]) >= -1.0 - 1e-9

    def test_pole_masking_one_over_x(self, session, env):
        f = elab(session, "fun (x : ℝ) => 1/x")
        result = sample_function(env, f, -2.0, 2.0, n=400)
        zero_idx = result["x"].index(0.0)
        assert result["y"][zero_idx] is None
        for x, y in zip(result["x"], result["y"]):
            if x == 0.0:
                continue
            assert y is not None
            assert y == pytest.approx(1.0 / x)

    def test_sinc_masks_zero_plots_elsewhere(self, session, env):
        f = elab(session, "fun (x : ℝ) => sin(x)/x")
        result = sample_function(env, f, -4.0, 4.0, n=400)
        zero_idx = result["x"].index(0.0)
        assert result["y"][zero_idx] is None
        defined = [(x, y) for x, y in zip(result["x"], result["y"])
                  if y is not None]
        assert len(defined) == 400   # every point but the pole at x=0
        for x, y in defined:
            assert y == pytest.approx(math.sin(x) / x, abs=1e-9)

    def test_wild_jump_masks_pole_between_samples(self, session, env):
        # 1/x sampled so the pole falls exactly between two grid points:
        # both neighbors are large, finite, sub-blowup, and opposite-signed
        # - the wild-jump heuristic must break the series there too.
        f = elab(session, "fun (x : ℝ) => 1/x")
        h = 1e-5
        result = sample_function(env, f, -h, h, n=9)
        ys = result["y"]
        mid = len(ys) // 2
        assert ys[mid - 1] is not None
        assert abs(ys[mid - 1]) > 1e5
        assert ys[mid] is None

    def test_invalid_n_raises(self, env):
        with pytest.raises(ValueError):
            sample_function(env, Const("Real.sin"), 0.0, 1.0, n=0)

    def test_reversed_bounds_normalized(self, session, env):
        f = elab(session, "fun (x : ℝ) => x")
        result = sample_function(env, f, 1.0, -1.0, n=4)
        assert result["x"][0] == pytest.approx(-1.0)
        assert result["x"][-1] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# plot_spec
# ---------------------------------------------------------------------------

class TestPlotSpec:
    def test_from_session_plots(self, session):
        src = "plot sin, x ∈ [-6, 6]"
        result = session.check_source(src, "<plottest1>")
        assert result.ok, [d.format() for d in result.diagnostics]
        entry = session.plots[-1]
        assert entry["var"] == "x"
        spec = plot_spec(session.env, entry)
        assert spec["kind"] == "plot2d"
        assert spec["var"] == "x"
        assert spec["lo"] == pytest.approx(-6.0)
        assert spec["hi"] == pytest.approx(6.0)
        assert len(spec["series"]) == 1
        s0 = spec["series"][0]
        assert s0["label"] == "sin"
        assert len(s0["x"]) == len(s0["y"]) == 401
        for x, y in zip(s0["x"], s0["y"]):
            if y is not None:
                assert y == pytest.approx(math.sin(x), abs=1e-9)

    def test_default_bounds_when_no_range_given(self, session):
        result = session.check_source("plot cos", "<plottest2>")
        assert result.ok, [d.format() for d in result.diagnostics]
        entry = session.plots[-1]
        spec = plot_spec(session.env, entry)
        assert spec["lo"] == pytest.approx(-10.0)
        assert spec["hi"] == pytest.approx(10.0)

    def test_custom_defaults(self, session):
        result = session.check_source("plot sin", "<plottest3>")
        assert result.ok, [d.format() for d in result.diagnostics]
        entry = session.plots[-1]
        spec = plot_spec(session.env, entry, default_lo=-1.0, default_hi=1.0)
        assert spec["lo"] == pytest.approx(-1.0)
        assert spec["hi"] == pytest.approx(1.0)

    def test_multi_function_plot_labels(self, session):
        result = session.check_source("plot sin, cos, x ∈ [0, 1]",
                                      "<plottest4>")
        assert result.ok, [d.format() for d in result.diagnostics]
        entry = session.plots[-1]
        spec = plot_spec(session.env, entry)
        assert len(spec["series"]) == 2
        labels = [s["label"] for s in spec["series"]]
        assert labels == ["sin", "cos"]

    def test_expression_bound(self, session):
        # bounds can be arbitrary Real expressions, not just literals
        result = session.check_source("plot sin, x ∈ [0, 2 * π]",
                                      "<plottest5>")
        assert result.ok, [d.format() for d in result.diagnostics]
        entry = session.plots[-1]
        spec = plot_spec(session.env, entry)
        assert spec["lo"] == pytest.approx(0.0)
        assert spec["hi"] == pytest.approx(2 * math.pi)


# ---------------------------------------------------------------------------
# render_svg
# ---------------------------------------------------------------------------

class TestRenderSvg:
    def test_basic_structure(self, session):
        result = session.check_source("plot sin, x ∈ [-6, 6]", "<svgtest1>")
        assert result.ok, [d.format() for d in result.diagnostics]
        spec = plot_spec(session.env, session.plots[-1])
        svg = render_svg(spec)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert "<polyline" in svg
        assert "points=" in svg
        assert "<text" in svg
        assert ">x<" in svg          # x-axis variable label
        assert ">0<" in svg          # a numeric tick label (0 is in range)

    def test_dark_and_light_both_render(self, session):
        result = session.check_source("plot sin, x ∈ [-6, 6]", "<svgtest2>")
        assert result.ok, [d.format() for d in result.diagnostics]
        spec = plot_spec(session.env, session.plots[-1])
        light = render_svg(spec, dark=False)
        dark = render_svg(spec, dark=True)
        assert light.startswith("<svg") and dark.startswith("<svg")
        assert light != dark
        assert "#fcfcfb" in light    # light chart surface
        assert "#1a1a19" in dark     # dark chart surface

    def test_legend_present_for_multi_series(self, session):
        result = session.check_source("plot sin, cos, x ∈ [-6, 6]",
                                      "<svgtest3>")
        assert result.ok, [d.format() for d in result.diagnostics]
        spec = plot_spec(session.env, session.plots[-1])
        svg = render_svg(spec)
        for s in spec["series"]:
            assert escape(s["label"]) in svg

    def test_pole_breaks_polyline_into_segments(self):
        spec = {"kind": "plot2d", "var": "x", "lo": -2.0, "hi": 2.0,
               "series": [{"label": "1/x",
                           "x": [-2.0, -1.0, 0.0, 1.0, 2.0],
                           "y": [-0.5, -1.0, None, 1.0, 0.5]}]}
        svg = render_svg(spec)
        assert svg.count("<polyline") == 2

    def test_custom_dimensions(self, session):
        result = session.check_source("plot sin, x ∈ [-6, 6]", "<svgtest4>")
        assert result.ok, [d.format() for d in result.diagnostics]
        spec = plot_spec(session.env, session.plots[-1])
        svg = render_svg(spec, width=400, height=300)
        assert 'width="400"' in svg
        assert 'height="300"' in svg

    def test_sinc_plot_end_to_end(self, session):
        # sin(x)/x plotted through a range straddling 0: masks the pole,
        # still renders the rest of the curve as real polyline segments.
        result = session.check_source(
            "plot fun (x : ℝ) => sin(x)/x, x ∈ [-4, 4]", "<svgtest5>")
        assert result.ok, [d.format() for d in result.diagnostics]
        spec = plot_spec(session.env, session.plots[-1])
        ys = spec["series"][0]["y"]
        assert None in ys             # the pole at x=0 is masked
        assert any(y is not None for y in ys)   # but plots elsewhere
        svg = render_svg(spec)
        assert "<polyline" in svg
        # a masked point splits one series into at least two polylines
        assert svg.count("<polyline") >= 2

    def test_empty_series_still_renders_axes(self):
        spec = {"kind": "plot2d", "var": "x", "lo": -5.0, "hi": 5.0,
               "series": []}
        svg = render_svg(spec)
        assert svg.startswith("<svg")
        assert svg.rstrip().endswith("</svg>")
        assert "<polyline" not in svg
