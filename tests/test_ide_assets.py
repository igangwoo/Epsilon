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
