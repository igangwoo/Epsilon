"""The browser build in `web/` must stay in sync with the IDE sources.

The web deploy is `epsilon/server/static/` plus a thin shell. It used to be
hand-copied, which let the two builds drift; these tests fail the moment they
do, and `python3 scripts/build_web.py` is the fix.
"""

import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "epsilon" / "server" / "static"
WEB = ROOT / "web"

pytestmark = pytest.mark.skipif(not WEB.exists(), reason="no web build in this checkout")


@pytest.mark.parametrize("name", ["app.js", "app.css", "panes.js"])
def test_shared_assets_are_identical(name):
    assert (WEB / name).read_bytes() == (STATIC / name).read_bytes(), (
        f"web/{name} has drifted from the IDE source; "
        f"run `python3 scripts/build_web.py`")


def test_generated_index_matches_the_build_script():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_web
    finally:
        sys.path.pop(0)
    assert build_web.build_index() == (WEB / "index.html").read_text(), (
        "web/index.html is stale; run `python3 scripts/build_web.py`")


def test_build_script_runs_clean():
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "build_web.py")],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_web_build_drops_the_native_window_chrome():
    """A close button that closes nothing has no place in a browser tab."""
    boot = (WEB / "boot.js").read_text()
    assert "applyWebChrome" in boot
    assert ".traffic" in (WEB / "web.css").read_text()


def test_shared_markup_keeps_the_desktop_chrome():
    """The native builds still need it, so it stays in the shared source."""
    assert 'class="traffic"' in (STATIC / "index.html").read_text()
