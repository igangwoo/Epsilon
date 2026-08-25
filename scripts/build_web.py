#!/usr/bin/env python3
"""Build the browser-only deploy in `web/` from the server IDE sources.

The browser build is not a fork of the IDE: it is `epsilon/server/static/`
plus a thin shell (a boot overlay, web-only CSS overrides and `boot.js`,
which starts Pyodide and then loads the *unmodified* `app.js`). Keeping the
copy mechanical means an IDE change can never land in one build and not the
other.

    python3 scripts/build_web.py [--wheel]

`--wheel` also rebuilds `epsilon_math-*.whl`, which `boot.js` installs into
Pyodide with micropip.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "epsilon" / "server" / "static"
WEB = ROOT / "web"
SHELL = WEB / "shell"

#: copied verbatim - the browser build shares these byte for byte
VERBATIM = ("app.js", "app.css", "panes.js", "core.js", "editor.js")


#: assets whose URLs carry the build id, and where each one comes from
STAMPED_FROM_STATIC = ("app.js", "app.css", "panes.js",
                       "core.js", "editor.js")
STAMPED_FROM_WEB = ("vfs.js", "boot.js", "web.css")

_BUILD_ID_LINE = re.compile(r'const BUILD_ID = "[^"]*";')


def build_id() -> str:
    """A short hash over everything the page loads.

    index.html and the scripts it references are separate files with
    separate cache lifetimes, so a returning visitor can otherwise hold an
    older index.html together with a fresh script - which is how a page that
    works for a new visitor is dead for everyone who used it before. Putting
    the id in every asset URL makes a stale pairing impossible.

    boot.js carries the id it is hashed into, so that one line is normalised
    out; without it every build would produce a different id from the same
    sources.
    """
    h = hashlib.sha256()
    sources = [(STATIC / n) for n in STAMPED_FROM_STATIC]
    sources += [(WEB / n) for n in STAMPED_FROM_WEB]
    sources += [SHELL / "head.html", SHELL / "body.html", STATIC / "index.html"]
    for path in sorted(sources):
        if not path.exists():
            continue
        data = path.read_bytes()
        if path.name == "boot.js":
            data = _BUILD_ID_LINE.sub('const BUILD_ID = "";',
                                      data.decode()).encode()
        h.update(path.name.encode())
        h.update(data)
    return h.hexdigest()[:12]


def stamp(html: str, version: str) -> str:
    """Add `?v=<build id>` to every local asset URL in the page."""
    def sub(match: re.Match) -> str:
        attr, url = match.group(1), match.group(2)
        if url.startswith(("http://", "https://", "data:", "#")) or "?" in url:
            return match.group(0)
        return f'{attr}="{url}?v={version}"'

    return re.sub(r'\b(src|href)="([^"]+\.(?:js|css))"', sub, html)


def build_index(version: str) -> str:
    """Splice the web shell into the server's index.html."""
    html = (STATIC / "index.html").read_text()
    head = (SHELL / "head.html").read_text()
    body = (SHELL / "body.html").read_text()

    if "</head>" not in html:
        raise SystemExit("index.html has no </head>")
    html = html.replace("</head>", head + "</head>", 1)

    marker = '  <div id="workbench"'
    if marker not in html:
        raise SystemExit("index.html has no #workbench anchor for the boot overlay")
    html = html.replace(marker, body + marker, 1)

    # boot.js pulls in app.js itself once the runtime is up
    if '<script src="app.js"></script>' not in html:
        raise SystemExit("index.html does not load app.js")
    html = html.replace('<script src="app.js"></script>',
                        '<script src="boot.js"></script>', 1)
    return stamp(html, version)


def build_wheel() -> None:
    for old in WEB.glob("epsilon_math-*.whl"):
        old.unlink()
    dist = ROOT / "dist"
    before = set(dist.glob("*.whl")) if dist.exists() else set()
    subprocess.run([sys.executable, "-m", "build", "--wheel", "--outdir", str(dist)],
                   cwd=ROOT, check=True)
    built = sorted(set(dist.glob("*.whl")) - before) or sorted(dist.glob("*.whl"))
    if not built:
        raise SystemExit("no wheel produced")
    wheel = max(built, key=lambda p: p.stat().st_mtime)
    shutil.copy2(wheel, WEB / wheel.name)
    print(f"  wheel  {wheel.name}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wheel", action="store_true",
                    help="also rebuild the Python wheel micropip installs")
    args = ap.parse_args()

    for name in VERBATIM:
        shutil.copy2(STATIC / name, WEB / name)
        print(f"  copy   {name}")

    version = build_id()
    boot = (WEB / "boot.js").read_text()
    boot = _BUILD_ID_LINE.sub(f'const BUILD_ID = "{version}";', boot, count=1)
    (WEB / "boot.js").write_text(boot)
    print(f"  stamp  build {version}")

    (WEB / "index.html").write_text(build_index(version))
    print("  build  index.html")

    if args.wheel:
        build_wheel()

    print(f"web build ready in {WEB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
