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
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "epsilon" / "server" / "static"
WEB = ROOT / "web"
SHELL = WEB / "shell"

#: copied verbatim - the browser build shares these byte for byte
VERBATIM = ("app.js", "app.css", "panes.js")


def build_index() -> str:
    """Splice the web shell into the server's index.html."""
    html = (STATIC / "index.html").read_text()
    head = (SHELL / "head.html").read_text()
    body = (SHELL / "body.html").read_text()

    if "</head>" not in html:
        raise SystemExit("index.html has no </head>")
    html = html.replace("</head>", head + "</head>", 1)

    marker = '  <div class="bg-mesh"'
    if marker not in html:
        raise SystemExit("index.html has no .bg-mesh anchor for the boot overlay")
    html = html.replace(marker, body + marker, 1)

    # boot.js pulls in app.js itself once the runtime is up
    if '<script src="app.js"></script>' not in html:
        raise SystemExit("index.html does not load app.js")
    html = html.replace('<script src="app.js"></script>',
                        '<script src="boot.js"></script>', 1)
    return html


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

    (WEB / "index.html").write_text(build_index())
    print("  build  index.html")

    if args.wheel:
        build_wheel()

    print(f"web build ready in {WEB}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
