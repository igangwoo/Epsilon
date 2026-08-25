#!/usr/bin/env python3
"""Stamp the browser build so a cached page can never load a stale script.

`web/` is authored directly — there is no compilation step and nothing to
copy. The one thing that does need doing is cache busting: index.html and
the scripts it names are separate files with separate lifetimes, so a
returning visitor can hold yesterday's HTML together with today's
JavaScript. Giving every asset URL a query string derived from the
contents makes that pairing impossible: change a byte, change the URL.

Run it after editing anything under `web/`, and commit the result. The
Pages workflow runs it too and fails if the output differs, which is what
keeps the committed site honest.
"""

from __future__ import annotations

import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: everything index.html may reference, in load order
ASSETS = ("epsilon.css", "editor.js", "app.js")

_REF = re.compile(r'((?:href|src)=")(' + "|".join(map(re.escape, ASSETS))
                  + r')(?:\?v=[0-9a-f]+)?(")')


def build_id() -> str:
    """A short hash over every asset, so any edit moves every URL."""
    digest = hashlib.sha256()
    for name in ASSETS:
        digest.update(name.encode())
        digest.update((WEB / name).read_bytes())
    return digest.hexdigest()[:12]


def stamp(html: str, version: str) -> str:
    return _REF.sub(lambda m: f"{m.group(1)}{m.group(2)}?v={version}{m.group(3)}",
                    html)


def main() -> int:
    missing = [n for n in ASSETS if not (WEB / n).exists()]
    if missing:
        raise SystemExit(f"web/ is missing {', '.join(missing)}")
    index = WEB / "index.html"
    if not index.exists():
        raise SystemExit("web/index.html is missing")

    version = build_id()
    html = index.read_text()
    stamped = stamp(html, version)

    for name in ASSETS:
        if f'"{name}?v={version}"' not in stamped:
            raise SystemExit(f"index.html never references {name}")

    if stamped != html:
        index.write_text(stamped)
        print(f"  stamp  build {version}")
    else:
        print(f"  ok     build {version} (already stamped)")
    print(f"web build ready in {WEB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
