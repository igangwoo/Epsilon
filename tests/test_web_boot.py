"""The browser build must boot, including for people who have used it before.

index.html and the scripts it references are separate files with separate
cache lifetimes. A returning visitor can hold an older index.html together
with a fresh boot.js, so a build that depends on index.html's `<script>` tags
works for a new visitor and is dead for everyone else — which is exactly what
happened when `vfs.js` was split out.

These tests run the real `web/` build in a headless browser, with CPython
standing in for Pyodide, against an index.html stripped of every optional
script tag. Skipped where node, Playwright or Chromium are unavailable.
"""

import json
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NODE = shutil.which("node")
PLAYWRIGHT = pathlib.Path("/opt/node22/lib/node_modules/playwright")
CHROMIUM = pathlib.Path("/opt/pw-browsers")

pytestmark = pytest.mark.skipif(
    not (NODE and PLAYWRIGHT.exists() and CHROMIUM.exists() and WEB.exists()),
    reason="needs node, Playwright and a browser")


# --------------------------------------------------------------------------
# CPython standing in for Pyodide
# --------------------------------------------------------------------------

PYODIDE_STUB = """
(function () {
  function post(path, body) {
    const x = new XMLHttpRequest();
    x.open("POST", path, false);          // runPython is synchronous
    x.setRequestHeader("content-type", "application/json");
    x.send(JSON.stringify(body));
    return JSON.parse(x.responseText);
  }
  function run(code) {
    const r = post("/__py/run", { code });
    if (!r.ok) throw new Error(r.error);
    return r.value;
  }
  window.loadPyodide = async function () {
    return {
      loadPackage: async () => {},
      runPython: run,
      runPythonAsync: async (code) => run(code),
      globals: { set: (name, value) => post("/__py/set", { name, value }) },
      FS: { writeFile: () => {} },
    };
  };
})();
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _make_server(directory, port):
    """Serve `directory`, and run its Python through this interpreter."""
    import ast
    import types
    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

    sys.path.insert(0, str(WEB))
    sys.path.insert(0, str(ROOT))
    micropip = types.ModuleType("micropip")

    async def _install(*a, **kw):
        return None                      # the wheel's contents are importable

    micropip.install = _install
    sys.modules.setdefault("micropip", micropip)

    ns = {"__name__": "__main__"}

    def run_code(code):
        if "await " in code:             # runPythonAsync takes top-level await
            import asyncio
            body = "\n".join("    " + line for line in code.splitlines())
            exec(compile(f"async def __top():\n{body}\n", "<py>", "exec"), ns)
            return asyncio.new_event_loop().run_until_complete(ns["__top"]())
        tree = ast.parse(code)
        if tree.body and isinstance(tree.body[-1], ast.Expr):
            head, tail = tree.body[:-1], tree.body[-1]
            if head:
                exec(compile(ast.Module(body=head, type_ignores=[]),
                             "<py>", "exec"), ns)
            return eval(compile(ast.Expression(tail.value), "<py>", "eval"), ns)
        exec(compile(tree, "<py>", "exec"), ns)
        return None

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(directory), **kw)

        def log_message(self, *a):
            pass

        def _json(self, obj, status=200):
            body = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            import traceback
            n = int(self.headers.get("content-length") or 0)
            req = json.loads(self.rfile.read(n) or b"{}")
            if self.path == "/__py/set":
                ns[req["name"]] = req["value"]
                return self._json({"ok": True})
            if self.path == "/__py/run":
                try:
                    return self._json({"ok": True, "value": run_code(req["code"])})
                except Exception:
                    return self._json({"ok": False, "error": traceback.format_exc()})
            self._json({"detail": "not found"}, 404)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


DRIVER = """
const {{ chromium }} = require({playwright!r});
const STUB = {stub};
(async () => {{
  const errs = [];
  const b = await chromium.launch();
  const pg = await b.newPage({{ viewport: {{ width: 1400, height: 900 }} }});
  pg.on('pageerror', (e) => errs.push(String(e.message)));
  await pg.route('**/cdn.jsdelivr.net/**', (r) =>
    r.fulfill({{ status: 200, contentType: 'application/javascript', body: STUB }}));
  await pg.goto('http://127.0.0.1:{port}/index.html', {{ waitUntil: 'domcontentloaded' }});
  await pg.waitForTimeout({wait});
  const out = await pg.evaluate(`({{
    bootGone: !document.querySelector('#boot'),
    bootError: (document.querySelector('.boot-error') || {{}}).textContent || '',
    panes: document.querySelectorAll('.pane[data-leaf]').length,
    files: document.querySelectorAll('#fileList .file-item').length,
    check: (document.querySelector('#checkState') || {{}}).textContent || '',
    theorems: document.querySelectorAll('#thmList .thm-item').length,
  }})`);
  out.errors = errs;
  await b.close();
  console.log(JSON.stringify(out));
}})();
"""


def boot_site(tmp_path, index_html=None, wait=30000):
    """Serve a copy of `web/` (optionally with a doctored index.html) and boot it."""
    site = tmp_path / "site"
    shutil.copytree(WEB, site)
    if index_html is not None:
        (site / "index.html").write_text(index_html)

    port = _free_port()
    server = _make_server(site, port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        driver = tmp_path / "drive.cjs"
        driver.write_text(DRIVER.format(playwright=str(PLAYWRIGHT),
                                        stub=json.dumps(PYODIDE_STUB),
                                        port=port, wait=wait))
        r = subprocess.run([NODE, str(driver)], capture_output=True, text=True,
                           timeout=180)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()


# --------------------------------------------------------------------------

def test_the_site_boots(tmp_path):
    out = boot_site(tmp_path)
    assert out["errors"] == [], out["errors"]
    assert out["bootError"] == ""
    assert out["bootGone"], "the boot overlay never cleared"
    assert out["panes"] >= 1
    assert out["files"] >= 1
    assert out["check"].startswith("✓")
    assert out["theorems"] >= 1


def test_it_boots_with_a_cached_index_from_an_earlier_build(tmp_path):
    """The failure this test exists for.

    A returning visitor's index.html predates the scripts this build added
    and carries no cache-busting query strings. boot.js has to load what it
    needs itself rather than trusting the page's tags.
    """
    html = (WEB / "index.html").read_text()
    html = re.sub(r'[ \t]*<script src="(vfs|panes)\.js[^"]*"></script>\n', "", html)
    html = re.sub(r"\?v=[0-9a-f]+", "", html)
    tags = re.findall(r'<script src="([^"]+)"', html)
    assert tags == ["boot.js"], f"expected only boot.js to be loaded, got {tags}"

    out = boot_site(tmp_path, index_html=html)
    assert out["errors"] == [], out["errors"]
    assert out["bootGone"], "an older cached index.html left the page dead"
    assert out["panes"] >= 1
    assert out["check"].startswith("✓")


def test_a_missing_asset_is_reported_on_the_page(tmp_path):
    """A dead page with no message is the worst possible failure."""
    site = tmp_path / "site"
    shutil.copytree(WEB, site)
    (site / "vfs.js").unlink()
    port = _free_port()
    server = _make_server(site, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        driver = tmp_path / "drive.cjs"
        driver.write_text(DRIVER.format(playwright=str(PLAYWRIGHT),
                                        stub=json.dumps(PYODIDE_STUB),
                                        port=port, wait=8000))
        r = subprocess.run([NODE, str(driver)], capture_output=True, text=True,
                           timeout=120)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert "Could not start Epsilon" in out["bootError"]
    assert "vfs.js" in out["bootError"]
