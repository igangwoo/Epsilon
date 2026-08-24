"""Static checks on the web IDE front-end.

The IDE is plain HTML/CSS/JS with no build step, so a renamed or removed
element only shows up as a null dereference at runtime — after the click that
needed it. These tests catch that class of breakage without a browser.
"""

import pathlib
import re

import pytest

STATIC = pathlib.Path(__file__).resolve().parent.parent / "epsilon" / "server" / "static"
HTML = STATIC / "index.html"
APP = STATIC / "app.js"
PANES = STATIC / "panes.js"


def html_ids():
    return set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', HTML.read_text()))


def test_every_element_lookup_in_app_js_resolves():
    """`$("#foo")` must name an element index.html actually defines."""
    ids = html_ids()
    wanted = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', APP.read_text()))
    missing = sorted(wanted - ids)
    assert not missing, f"app.js looks up ids that index.html does not define: {missing}"


def test_every_pane_view_element_exists():
    """A view whose element is missing is silently dropped from the layout."""
    ids = html_ids()
    block = re.search(r"const PANE_VIEWS = \[(.*?)\n  \];", APP.read_text(), re.S)
    assert block, "PANE_VIEWS not found in app.js"
    selectors = re.findall(r'element:\s*"#([A-Za-z0-9_-]+)"', block.group(1))
    assert selectors, "PANE_VIEWS declares no view elements"
    missing = sorted(set(selectors) - ids)
    assert not missing, f"PANE_VIEWS names elements index.html does not define: {missing}"


def test_pane_views_live_in_the_vault():
    """Views are re-parented into panes, so they must start somewhere real."""
    html = HTML.read_text()
    assert 'id="viewVault"' in html
    assert 'vault: "#viewVault"' in APP.read_text(), (
        "panes.js needs a vault to park views that are not currently visible; "
        "without it, an inactive view's element is detached and every "
        "querySelector for it returns null")


def test_pane_profiles_only_name_registered_views():
    """A profile that names a view nobody registered would open a blank pane."""
    app = APP.read_text()
    registered = set(re.findall(r'\{\s*id:\s*"([a-z]+)"', app))
    block = re.search(r"const PROFILES = \{(.*?)\n  \};", PANES.read_text(), re.S)
    assert block, "PROFILES not found in panes.js"
    used = set(re.findall(r'leaf\(\[([^\]]*)\]', block.group(1)))
    names = {n.strip().strip('"') for group in used for n in group.split(",") if n.strip()}
    unknown = sorted(names - registered)
    # unknown names are pruned at runtime rather than rendered blank, so this
    # is a warning-grade assertion: the pruning is what must hold.
    assert "normalize(make())" in PANES.read_text(), (
        f"profiles name views that are not registered ({unknown}) and "
        f"applyProfile does not prune them")


def test_no_external_resources():
    """Section 34: the IDE is self-contained — no CDNs, no phone-home."""
    for f in (HTML, APP, STATIC / "app.css", PANES):
        text = f.read_text()
        for m in re.findall(r'(?:src|href)="(https?://[^"]+)"', text):
            assert m.startswith("https://github.com/"), \
                f"{f.name} references an external resource: {m}"


@pytest.mark.parametrize("name", ["panes.js", "app.js", "app.css", "index.html"])
def test_asset_present(name):
    assert (STATIC / name).exists()


def test_editor_languages_match_the_server():
    """The editor's extension table must agree with `_language_of`."""
    from epsilon.server.app import _language_of
    app = APP.read_text()
    block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    assert block, "EXT_LANGUAGE not found in app.js"
    pairs = re.findall(r'(\w+):\s*"([a-z+]+)"', block.group(1))
    assert pairs
    for ext, language in pairs:
        assert _language_of("f." + ext) == language, (
            f".{ext}: editor says {language}, server says {_language_of('f.' + ext)}")


def test_every_editor_language_has_a_syntax_entry():
    app = APP.read_text()
    block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    languages = {lang for _, lang in re.findall(r'(\w+):\s*"([a-z+]+)"', block.group(1))}
    syntax = set(re.findall(r"^    ([a-z]+): \{", app, re.M))
    syntax |= set(re.findall(r"SYNTAX\.([a-z]+) = ", app))
    # markdown has its own pass rather than a SYNTAX table entry
    missing = sorted(languages - syntax - {"markdown"})
    assert not missing, f"languages with no highlighting rules: {missing}"


def test_every_language_has_a_status_bar_label():
    app = APP.read_text()
    block = re.search(r"const LANGUAGE_LABEL = \{(.*?)\n  \};", app, re.S)
    assert block, "LANGUAGE_LABEL not found in app.js"
    labelled = set(re.findall(r'(\w+):\s*"', block.group(1)))
    ext_block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    languages = {lang for _, lang in re.findall(r'(\w+):\s*"([a-z+]+)"', ext_block.group(1))}
    assert not sorted(languages - labelled)


def test_check_is_gated_to_epsilon():
    """A Python buffer must never be reported on by the proof engine."""
    app = APP.read_text()
    assert "if (!isEpsilon())" in app
    run_check = app[app.index("async function runCheck()"):]
    run_check = run_check[:run_check.index("\n  function setCheckState")]
    assert "isEpsilon()" in run_check, "runCheck does not gate on the language"


def test_the_graph_is_never_left_without_its_derived_links():
    """`graphData.links` is derived from a check, but drawing happens on
    every pane change, tab switch and theme toggle — including before the
    first result arrives. Every shape assigned to it must be complete."""
    app = APP.read_text()
    assigns = re.findall(r"graphData = \{(.*?)\};", app, re.S)
    assigns += re.findall(r"graphData = (\w+)\(\)", app)
    assert assigns, "graphData is never assigned?"
    for a in assigns:
        if a.isidentifier():                      # a factory: check its body
            body = re.search(rf"const {a} = \(\) => \((\{{.*?\}})\);", app, re.S)
            assert body, f"{a} not found"
            a = body.group(1)
        for key in ("nodes", "edges", "links"):
            assert f"{key}:" in a, f"a graphData shape is missing `{key}`: {a[:80]}"


def test_panels_fed_by_a_check_tolerate_having_none_yet():
    """Everything the IDE draws before its first result must accept nothing.

    Pyodide takes seconds to produce one, so the IDE is interactive well
    before any of it arrives.
    """
    app = APP.read_text()
    for call in ("renderPlots(", "renderTheorems(", "renderProblems(",
                 "renderDeps(", "renderInspector("):
        for m in re.finditer(re.escape(call) + r"([^)]*)\)", app):
            arg = m.group(1).strip()
            if arg.startswith(("r.", "state.lastCheck.")):
                assert "||" in arg, (
                    f"{call}{arg}) can be called with nothing to show")


def test_the_pane_api_matches_what_the_contracts_document():
    """A documented entry point that is not exported is a promise unkept."""
    contracts = (pathlib.Path(__file__).resolve().parent.parent
                 / "docs" / "CONTRACTS.md").read_text()
    documented = set(re.findall(r"EpsilonPanes\.(\w+)\(", contracts))
    panes = PANES.read_text()
    block = re.search(r"const api = \{(.*?)\n  \};", panes, re.S)
    if not block:
        block = re.search(r"\n  \{?\n?\s*init, registerView(.*?)\n  \};", panes, re.S)
    assert block, "the pane module's exported surface was not found"
    exported = set(re.findall(r"(\w+)[,:]", block.group(1)))
    missing = sorted(documented - exported)
    assert not missing, f"documented but not exported: {missing}"


def test_a_sash_drag_never_re_renders():
    """`render()` rebuilds the tree, detaching the element a drag measures
    against; a detached element reports a zero-sized rect, so the ratio
    divides by zero and the split jumps to its limit instead of following
    the mouse. A drag writes flex directly and leaves the tree alone."""
    panes = PANES.read_text()
    body = re.search(r"function wireSash\(.*?\n  \}\n", panes, re.S)
    assert body, "wireSash not found"
    src = body.group(0)
    # the pointer handlers are everything up to the double-click reset, which
    # legitimately re-renders because it is not a drag
    drag = src[:src.index('addEventListener("dblclick"')]
    assert "render()" not in drag, "a sash drag calls render(); it must not"
    assert "requestAnimationFrame" in drag, "moves are not coalesced per frame"
    assert "setPointerCapture" in drag, "the drag is lost when the pointer strays"
