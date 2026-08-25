"""The browser build must boot — and hold up as a daily programming tool.

index.html and the scripts it references are separate files with separate
cache lifetimes. A returning visitor can hold an older index.html together
with a fresh boot.js, so a build that depends on index.html's `<script>` tags
works for a new visitor and is dead for everyone else — which is exactly what
happened when `vfs.js` was split out.

These tests run the real `web/` build in a headless browser, with CPython
standing in for Pyodide, against the workbench UI: boot, edit, save, run,
palette, and the reload-and-continue guarantee. Skipped where node,
Playwright or Chromium are unavailable.
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


def _make_server(directory, port, slow_on="", slow_delay=0.0):
    """Serve `directory`, and run its Python through this interpreter.

    `slow_on` delays bridge calls containing that substring, the way the
    real Pyodide build is slow on a first run — which is what opens the
    window between the IDE appearing and its first data arriving.
    """
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
        if slow_on and slow_on in code:
            import time
            time.sleep(slow_delay)
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


PROBE = """({
    bootGone: !document.querySelector('#boot'),
    bootError: (document.querySelector('.boot-error') || {}).textContent || '',
    panes: document.querySelectorAll('.pane[data-leaf]').length,
    files: document.querySelectorAll('#explorerList .wb-file').length,
    tabs: Array.from(document.querySelectorAll('.pane-tab'))
      .map((t) => t.textContent),
    statusbar: (document.querySelector('#statusbar') || {}).textContent || '',
    output: (document.querySelector('#panelOutput') || {}).textContent || '',
    value: (document.querySelector('.ed-input') || {}).value || '',
    title: document.title,
    paletteOpen: !!document.querySelector('#paletteOverlay:not(.hidden)'),
    paletteItems: document.querySelectorAll('.wb-pal-item').length,
  })"""

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
  {script}
  await pg.waitForTimeout({wait});
  const out = await pg.evaluate(`{probe}`);
  out.errors = errs;
  await b.close();
  console.log(JSON.stringify(out));
}})();
"""

READY = ("await pg.waitForFunction(\"window.EpsilonIDE && "
         "document.querySelector('.pane-tab')\", null, { timeout: 60000 });\n")


def boot_site(tmp_path, index_html=None, wait=4000, script="",
              slow_on="", slow_delay=0.0):
    """Serve a copy of `web/` (optionally with a doctored index.html) and boot it."""
    site = tmp_path / "site"
    shutil.copytree(WEB, site)
    if index_html is not None:
        (site / "index.html").write_text(index_html)

    port = _free_port()
    server = _make_server(site, port, slow_on=slow_on, slow_delay=slow_delay)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        driver = tmp_path / "drive.cjs"
        driver.write_text(DRIVER.format(playwright=str(PLAYWRIGHT),
                                        stub=json.dumps(PYODIDE_STUB),
                                        port=port, wait=wait, script=script,
                                        probe=PROBE))
        r = subprocess.run([NODE, str(driver)], capture_output=True, text=True,
                           timeout=180)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()


# --------------------------------------------------------------------------


def test_the_site_boots(tmp_path):
    out = boot_site(tmp_path, script=READY)
    assert out["errors"] == [], out["errors"]
    assert out["bootError"] == ""
    assert out["bootGone"], "the boot overlay never cleared"
    assert out["panes"] >= 1
    assert out["files"] >= 1, "the explorer lists nothing"
    assert any("main.py" in t for t in out["tabs"]), (
        f"main.py did not open on first visit: {out['tabs']}")
    assert "main.py" in out["title"]
    assert "browser" in out["statusbar"], (
        "the status bar does not state the build's capabilities")


def test_it_boots_with_a_cached_index_from_an_earlier_build(tmp_path):
    """The failure this test exists for.

    A returning visitor's index.html predates the scripts this build added
    and carries no cache-busting query strings. boot.js has to load what it
    needs itself rather than trusting the page's tags.
    """
    html = (WEB / "index.html").read_text()
    html = re.sub(
        r'[ \t]*<script src="(vfs|panes|core|editor|graph)\.js[^"]*"></script>\n',
        "", html)
    html = re.sub(r"\?v=[0-9a-f]+", "", html)
    tags = re.findall(r'<script src="([^"]+)"', html)
    assert tags == ["boot.js"], f"expected only boot.js to be loaded, got {tags}"

    out = boot_site(tmp_path, index_html=html, script=READY)
    assert out["errors"] == [], out["errors"]
    assert out["bootGone"], "an older cached index.html left the page dead"
    assert out["panes"] >= 1
    assert any("main.py" in t for t in out["tabs"])


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
                                        port=port, wait=8000, script="",
                                        probe=PROBE))
        r = subprocess.run([NODE, str(driver)], capture_output=True, text=True,
                           timeout=120)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()
    assert "Could not start Epsilon" in out["bootError"]
    assert "vfs.js" in out["bootError"]


def test_edit_save_run_and_reload_continues_where_you_left_off(tmp_path):
    """The definition of done, as far as the browser build honestly goes:
    edit → save → run → see output → reload → continue exactly there."""
    script = READY + """
  // edit: type a comment at the top of main.py
  await pg.click('.ed-input');
  await pg.keyboard.press('Control+Home');
  await pg.keyboard.type('# edited in the E2E test');
  await pg.keyboard.press('Enter');
  await pg.waitForFunction("document.title.includes('\\u25cf')",
                           null, { timeout: 5000 });   // dirty dot
  // save
  await pg.keyboard.press('Control+s');
  await pg.waitForFunction("!document.title.includes('\\u25cf')",
                           null, { timeout: 5000 });
  // run from the Run button; output lands in the panel
  await pg.click('.wb-run-btn');
  await pg.waitForFunction(
    "(document.querySelector('#panelOutput')||{textContent:''}).textContent.includes('sinc(')",
    null, { timeout: 30000 });
  // the command palette answers the keyboard
  await pg.keyboard.press('Control+Shift+P');
  await pg.waitForFunction(
    "!document.querySelector('#paletteOverlay').classList.contains('hidden')",
    null, { timeout: 5000 });
  await pg.keyboard.type('Toggle Panel');
  await pg.waitForTimeout(300);
  // reload: the session must come back, not reset
  await pg.reload({ waitUntil: 'domcontentloaded' });
""" + READY + """
  await pg.waitForTimeout(800);
"""
    out = boot_site(tmp_path, script=script, wait=1500)
    assert out["errors"] == [], out["errors"]
    assert any("main.py" in t for t in out["tabs"]), (
        f"the open editor was forgotten across a reload: {out['tabs']}")
    assert "# edited in the E2E test" in out["value"], (
        "the saved edit did not survive the reload")


def test_interacting_before_capabilities_arrive(tmp_path):
    """Pyodide takes seconds on a first run, so the IDE is on screen and
    interactive before it knows what this build can do. Clicking around in
    that window must degrade to honest reasons, never exceptions."""
    script = READY + """
  await pg.keyboard.press('Control+Shift+P');       // palette
  await pg.keyboard.press('Escape');
  await pg.keyboard.press('Control+b');             // toggle sidebar
  await pg.keyboard.press('Control+b');
  await pg.click('.wb-run-btn');                    // run before caps: a reason, not a crash
  await pg.waitForTimeout(1200);
"""
    out = boot_site(tmp_path, script=script, wait=2000,
                    slow_on="ide_capabilities", slow_delay=5.0)
    assert out["errors"] == [], out["errors"]
    assert out["bootError"] == "", out["bootError"]
    assert out["panes"] >= 1


def test_a_runtime_error_is_not_reported_as_a_startup_failure(tmp_path):
    """Calling a failure in a working IDE a startup failure sends the reader
    looking in the wrong place; the report also has to say where it happened."""
    script = READY + """
  await pg.waitForTimeout(1000);
  await pg.evaluate("setTimeout(() => { window.__nope.forEach(() => {}); }, 0)");
  await pg.waitForTimeout(1200);
"""
    out = boot_site(tmp_path, script=script, wait=3000)
    assert "Something went wrong" in out["bootError"], out["bootError"]
    assert "Could not start Epsilon" not in out["bootError"]
    assert "Dismiss" in out["bootError"]

def test_the_whole_workbench_state_survives_a_reload(tmp_path):
    """Reloading the browser must not make the IDE feel reset: settings,
    a rebound key, the sidebar view, the panel tab and the layout all come
    back."""
    script = READY + """
  await pg.evaluate(`(() => {
    EpsilonIDE.settings.set('editor.fontSize', 17);
    EpsilonIDE.settings.set('workbench.theme', 'light');
    EpsilonIDE.keys.setUser('view.problems', 'Ctrl+Alt+P');
    EpsilonIDE.commands.execute('view.scm');
    EpsilonIDE.commands.execute('view.output');
    EpsilonIDE.commands.execute('view.splitRight');
  })()`);
  await pg.waitForTimeout(600);
  await pg.reload({ waitUntil: 'domcontentloaded' });
""" + READY + """
  await pg.waitForTimeout(800);
"""
    probe = """({
      fontSize: EpsilonIDE.settings.get('editor.fontSize'),
      theme: document.documentElement.dataset.theme,
      chord: EpsilonIDE.keys.chordOf('view.problems'),
      sidebar: (document.querySelector('#sidebarTitle')||{}).textContent,
      panelTab: (document.querySelector('.wb-panel-tab.active')||{}).textContent,
      panes: document.querySelectorAll('.pane[data-leaf]').length,
    })"""
    global PROBE
    saved, PROBE = PROBE, probe
    try:
        out = boot_site(tmp_path, script=script, wait=1200)
    finally:
        PROBE = saved
    assert out["fontSize"] == 17, "a settings change did not survive"
    assert out["theme"] == "light", "the theme reset itself"
    assert out["chord"] == "Ctrl+Alt+P", "a rebound key was forgotten"
    assert "SOURCE CONTROL" in out["sidebar"], out["sidebar"]
    assert "OUTPUT" in out["panelTab"].upper(), out["panelTab"]
    assert out["panes"] >= 2, "the editor split was forgotten"

def test_the_menu_bar_is_usable_without_a_mouse(tmp_path):
    """Keyboard-only paths are not optional: Alt-free arrow navigation
    walks the bar, opens a menu, and runs an item."""
    script = READY + """
  await pg.evaluate("document.querySelector('#menubar .wb-menu-btn').focus()");
  await pg.keyboard.press('ArrowRight');           // File -> Edit
  await pg.keyboard.press('ArrowDown');            // opens, enters the menu
  await pg.waitForTimeout(200);
  await pg.keyboard.press('ArrowDown');
  await pg.waitForTimeout(200);
"""
    probe = """({
      open: !!document.querySelector('#menuDrop'),
      focusedItem: (document.activeElement.className || ''),
      focusedText: (document.activeElement.textContent || '').slice(0, 40),
    })"""
    global PROBE
    saved, PROBE = PROBE, probe
    try:
        out = boot_site(tmp_path, script=script, wait=600)
    finally:
        PROBE = saved
    assert out["open"], "arrow keys did not open a menu"
    assert "wb-menu-item" in out["focusedItem"], (
        f"focus never entered the dropdown: {out}")

def test_the_dependency_graph_draws_what_the_file_refers_to(tmp_path):
    """A picture of the symbols and their references, built from the live
    buffer rather than from what was last saved."""
    script = READY + """
  await pg.evaluate(`(() => {
    const ed = document.querySelector('.ed-input');
    ed.value = ['import math', '', '', 'SCALE = 3', '', '',
                'def area(r):', '    return math.pi * r * r * SCALE', '', '',
                'print(area(2))'].join(String.fromCharCode(10));
    ed.dispatchEvent(new Event('input', { bubbles: true }));
  })()`);
  await pg.waitForTimeout(400);
  await pg.evaluate("EpsilonIDE.commands.execute('view.graph')");
  await pg.waitForFunction("document.querySelectorAll('.gr-node').length > 2",
                           null, { timeout: 20000 });
"""
    probe = """({
      nodes: [...document.querySelectorAll('.gr-node .gr-label')].map(t => t.textContent),
      edges: document.querySelectorAll('.gr-edge').length,
      level: (document.querySelector('.wb-graph-level') || {}).textContent || '',
      legend: (document.querySelector('.wb-graph-legend') || {}).textContent || '',
    })"""
    global PROBE
    saved, PROBE = PROBE, probe
    try:
        out = boot_site(tmp_path, script=script, wait=800)
    finally:
        PROBE = saved
    assert "area" in out["nodes"], out["nodes"]
    assert "SCALE" in out["nodes"], out["nodes"]
    assert "math" in out["nodes"], out["nodes"]
    assert out["edges"] >= 3, out
    assert "parser" in out["level"], out["level"]
    assert "reference" in out["legend"], out["legend"]

