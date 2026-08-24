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
    version = build_web.build_id()
    assert build_web.build_index(version) == (WEB / "index.html").read_text(), (
        "web/index.html is stale; run `python3 scripts/build_web.py`")


def test_assets_carry_the_build_id():
    """A cached script must never pair with a differently-built page."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_web
    finally:
        sys.path.pop(0)
    version = build_web.build_id()
    html = (WEB / "index.html").read_text()
    for name in ("app.css", "boot.js", "panes.js", "vfs.js", "web.css"):
        assert f"{name}?v={version}" in html, f"{name} is not cache-busted"
    # app.js is loaded by boot.js rather than by a tag, and gets the same id
    boot = (WEB / "boot.js").read_text()
    assert f'const BUILD_ID = "{version}";' in boot
    assert 'app.src = "./app.js" + CACHE_BUST;' in boot


def test_the_build_id_is_stable():
    """Two builds of the same sources must produce the same id."""
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_web
    finally:
        sys.path.pop(0)
    assert build_web.build_id() == build_web.build_id()


def test_boot_loads_its_own_dependencies():
    """boot.js is the one script a cached index.html is sure to reference,
    so it must not depend on that page having any other tag."""
    boot = (WEB / "boot.js").read_text()
    for src, name in (("./vfs.js", "EpsilonVFS"), ("./panes.js", "EpsilonPanes")):
        assert f'ensureScript("{src}", "{name}")' in boot, (
            f"boot.js does not ensure {src} is loaded")


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
