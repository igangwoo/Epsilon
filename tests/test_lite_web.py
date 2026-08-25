"""The browser build: three languages, one page, and nothing else in it.

`web/` is authored directly — no wheel, no bridge, no engine — so these
tests check the things that actually break a static site: an asset the
page names but does not have, a page that pairs cached HTML with a newer
script, and a claim the build cannot back up. The browser tests below
then boot the real thing with CPython standing in for Pyodide and drive
it the way a person does.
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

HTML = WEB / "index.html"
CSS = WEB / "epsilon.css"
EDITOR = WEB / "editor.js"
APP = WEB / "app.js"


def strip_comments(js: str) -> str:
    """Prose about `runPython` is not a call to it."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


# --------------------------------------------------------------------------
# static
# --------------------------------------------------------------------------

def test_the_site_is_four_files():
    """Weight is the feature. If this grows, it should be on purpose."""
    for f in (HTML, CSS, EDITOR, APP):
        assert f.exists(), f"{f.name} is missing"
    total = sum(f.stat().st_size for f in (HTML, CSS, EDITOR, APP))
    assert total < 140_000, f"the browser build has grown to {total} bytes"


def test_the_page_has_no_file_management():
    """The whole request was a page with somewhere to write, somewhere to
    read, and nothing else. A tab strip is how that comes back."""
    html = HTML.read_text()
    for gone in ("files", "newFile", "tabs", "sidebar", "explorer"):
        assert f'id="{gone}"' not in html, f"#{gone} is back on the page"


def test_every_element_the_scripts_look_up_exists():
    """`$("run")` for an id the page does not define fails only when that
    path runs, which can be long after the edit that removed it."""
    ids = set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', HTML.read_text()))
    wanted = set(re.findall(r'\$\("([A-Za-z0-9_-]+)"\)', APP.read_text()))
    missing = sorted(wanted - ids)
    assert not missing, f"app.js looks up ids the page does not define: {missing}"


def test_nothing_is_fetched_but_the_python_runtime():
    """Pyodide is the one thing this page cannot carry itself."""
    for f in (HTML, CSS, EDITOR, APP):
        for url in re.findall(r"https?://[^\s\"')]+", f.read_text()):
            assert ("cdn.jsdelivr.net/pyodide" in url
                    or "www.w3.org" in url), f"{f.name} reaches out to {url}"


def test_assets_carry_the_build_id():
    """index.html and the scripts have separate cache lifetimes, so a
    returning visitor can hold yesterday's HTML with today's script. A
    query string derived from the contents makes that pairing
    impossible."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_web

    version = build_web.build_id()
    html = HTML.read_text()
    for name in build_web.ASSETS:
        assert f'{name}?v={version}' in html, f"{name} is not stamped"


def test_the_build_script_is_idempotent():
    """The committed site must equal what the script produces, which is
    what the deploy workflow checks."""
    before = HTML.read_bytes()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_web.py")],
                   check=True, capture_output=True)
    assert HTML.read_bytes() == before, "web/ was not committed as built"


def test_the_typing_path_never_calls_python():
    """Python runs on the page's only thread. Anything on the keystroke
    path that crosses into it freezes the page while you type — which is
    exactly the bug this build exists to be free of."""
    editor = strip_comments(EDITOR.read_text())
    assert "runPython" not in editor, (
        "the editor must not reach the runtime; completion comes from the "
        "buffer's own words")
    assert "fetch(" not in editor, "the editor must not reach the network"
    app = strip_comments(APP.read_text())
    calls = re.findall(r"runPython\(", app)
    assert len(calls) <= 2, (
        f"Python is entered from {len(calls)} places; it should be the "
        "preamble and the run")


def test_completion_is_still_offered():
    """It was taken out once and asked for back. Keep it local — the
    buffer's own words plus a fixed list — but keep it."""
    editor = EDITOR.read_text()
    assert "function suggest(" in editor
    assert 'id="hints"' in HTML.read_text()


def test_the_caret_is_moved_by_a_frame_loop():
    """A CSS transition restarts from zero velocity on every keystroke,
    which is what makes a caret read as steppy while typing."""
    css = CSS.read_text()
    block = re.search(r"#caret \{(.*?)\}", css, re.S)
    assert block, "#caret rule not found"
    assert "transition: transform" not in block.group(1)
    editor = EDITOR.read_text()
    assert "requestAnimationFrame(step)" in editor
    assert "Math.pow(1 - ex" in editor, "the easing must be frame-rate free"
    assert "craf = 0; prev = 0;" in editor, "the loop must stop on arrival"


def test_the_full_workbench_is_preserved():
    """The pane workbench moved off the page, not out of the repository."""
    assert (ROOT / "epsilon" / "server" / "static" / "app.js").exists()
    archive = ROOT / "archive" / "browser-full"
    assert (archive / "bridge.py").exists()
    assert (archive / "vfs.js").exists()
    assert (archive / "README.md").exists()


# --------------------------------------------------------------------------
# languages
# --------------------------------------------------------------------------

LANG_PROBE = r"""
const g = globalThis;
require(process.argv[2]);
const E = g.EpsilonEditor;
const plain = (h) => h.replace(/<[^>]*>/g, "");
const paint = (src, lang) => E.paint(src, lang, true);
const out = {};
for (const id of ["python", "cpp", "java"]) {
  const s = E.LANGS[id];
  out[id] = { label: s.label, line: s.line, file: s.file,
              keywords: s.keywords.size, known: s.known.size };
}
out.cppComment = plain(paint("int x = 1;  // note", "cpp")[0]);
out.pythonHash = plain(paint("x = 1  # note", "python")[0]);
out.cppBlock = paint("/* one\ntwo */ int x;", "cpp").map(plain);
out.include = paint('#include <vector>\n#include "mine.h"', "cpp")[0]
  + "|" + paint('#include <vector>\n#include "mine.h"', "cpp")[1];
const q3 = String.fromCharCode(34).repeat(3);
out.pythonTriple = paint(q3 + "a" + String.fromCharCode(10) + "b" + q3,
                         "python").map(plain);
// a `#` is a preprocessor line in C++ and a comment in Python: the same
// text must not be painted the same way
out.hashInCpp = paint("#define N 3", "cpp")[0];
out.hashInPython = paint("#define N 3", "python")[0];
// indentation follows the language, not a global habit
const nl = (text, at, lang) => E.Ops.newline(text, at, E.LANGS[lang]);
out.newline = {
  python: nl("def f():", 8, "python"),
  cppOpen: nl("int main() {", 12, "cpp"),
  cppSplit: nl("int main() {}", 12, "cpp"),
  javaPlain: nl("    int x = 1;", 14, "java"),
};
out.comment = {
  python: E.Ops.comment("x = 1", 0, 5, E.LANGS.python.comment).text,
  java: E.Ops.comment("int x;", 0, 6, E.LANGS.java.comment).text,
};
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(not NODE, reason="needs node")
def test_each_language_is_lexed_as_itself(tmp_path):
    probe = tmp_path / "probe.cjs"
    probe.write_text(LANG_PROBE)
    r = subprocess.run([NODE, str(probe), str(EDITOR)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)

    assert [got[k]["label"] for k in ("python", "cpp", "java")] == \
        ["python", "c++", "java"]
    assert got["java"]["file"] == "Main.java"      # javac insists
    for lang in ("python", "cpp", "java"):
        assert got[lang]["keywords"] > 30, f"{lang} has no keyword list"
        assert got[lang]["known"] > 20, f"{lang} has no completion list"

    # `#` starts a comment in one language and a directive in another
    assert "#define" in got["hashInCpp"] and 'class="k"' in got["hashInCpp"]
    assert 'class="c"' in got["hashInPython"]
    assert "// note" in got["cppComment"]
    assert "# note" in got["pythonHash"]
    assert got["cppBlock"] == ["/* one", "two */ int x;"]
    assert got["pythonTriple"] == ['"""a', 'b"""']

    # Enter knows what opened the block
    assert got["newline"]["python"]["ins"] == "\n    "
    assert got["newline"]["cppOpen"]["ins"] == "\n    "
    assert got["newline"]["cppSplit"] == {"ins": "\n    \n", "back": 1}
    assert got["newline"]["javaPlain"]["ins"] == "\n    "

    assert got["comment"]["python"] == "# x = 1"
    assert got["comment"]["java"] == "// int x;"


# --------------------------------------------------------------------------
# browser
# --------------------------------------------------------------------------

pytestmark_browser = pytest.mark.skipif(
    not (NODE and PLAYWRIGHT.exists() and CHROMIUM.exists()),
    reason="needs node, Playwright and a browser")

#: CPython standing in for Pyodide, over synchronous XHR — which is also
#: how the real thing behaves: it holds the page's only thread.
STUB = """
(function () {
  function post(p, b) {
    const x = new XMLHttpRequest();
    x.open("POST", p, false);
    x.setRequestHeader("content-type", "application/json");
    x.send(JSON.stringify(b));
    return JSON.parse(x.responseText);
  }
  function run(c) {
    const r = post("/__py/run", { code: c });
    if (!r.ok) throw new Error(r.error);
    return r.value;
  }
  window.loadPyodide = async function () {
    return { loadPackage: async () => {}, runPython: run,
             runPythonAsync: async (c) => run(c),
             globals: { set: (n, v) => post("/__py/set", { name: n, value: v }) },
             FS: { writeFile: () => {} } };
  };
})();
"""


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _serve(directory, port):
    import ast
    from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

    ns = {"__name__": "__main__"}

    def run_code(code):
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

        def _json(self, obj):
            body = json.dumps(obj).encode()
            self.send_response(200)
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
            self._json({"detail": "not found"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


DRIVER = """
const {{ chromium }} = require({playwright!r});
(async () => {{
  const errs = [];
  const b = await chromium.launch();
  const pg = await b.newPage({{ viewport: {{ width: 1200, height: 820 }} }});
  pg.on('pageerror', (e) => errs.push(String(e.message)));
  await pg.route('**/cdn.jsdelivr.net/**', (r) => r.fulfill(
    {{ status: 200, contentType: 'application/javascript', body: {stub} }}));
  await pg.goto('http://127.0.0.1:{port}/index.html',
                {{ waitUntil: 'domcontentloaded' }});
  await pg.waitForFunction("window.Epsilon && !document.getElementById('boot')",
                           null, {{ timeout: 60000 }});
  await pg.waitForTimeout(300);
  {script}
  const out = await pg.evaluate(`{probe}`);
  out.errors = errs;
  await b.close();
  console.log(JSON.stringify(out));
}})();
"""


def drive(tmp_path, script="", probe="({})"):
    site = tmp_path / "site"
    shutil.copytree(WEB, site)
    port = _free_port()
    server = _serve(site, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        runner = tmp_path / "drive.cjs"
        runner.write_text(DRIVER.format(playwright=str(PLAYWRIGHT),
                                        stub=json.dumps(STUB), port=port,
                                        script=script, probe=probe))
        r = subprocess.run([NODE, str(runner)], capture_output=True,
                           text=True, timeout=180)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])
    finally:
        server.shutdown()


@pytestmark_browser
def test_it_boots_and_runs_python(tmp_path):
    out = drive(tmp_path, script="""
  await pg.click('#run');
  await pg.waitForFunction(
    "document.getElementById('out').textContent.includes('sinc')",
    null, { timeout: 30000 });
""", probe="""({
      output: document.getElementById('out').textContent,
      state: document.getElementById('state').textContent,
    })""")
    assert out["errors"] == [], out["errors"]
    assert "sinc(0.0)" in out["output"]
    assert out["state"].startswith("ok"), out["state"]


@pytestmark_browser
def test_an_error_names_the_line_and_offers_to_go_there(tmp_path):
    """A traceback that does not say where is a traceback you have to
    read twice."""
    out = drive(tmp_path, script="""
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.select();
    document.execCommand('insertText', false,
      ['x = 1', 'y = 0', 'print(x / y)'].join(String.fromCharCode(10)));
  })()`);
  await pg.waitForTimeout(250);
  await pg.click('#run');
  await pg.waitForFunction("document.querySelector('#out .jump')",
                           null, { timeout: 20000 });
""", probe="""({
      state: document.getElementById('state').textContent,
      jump: document.querySelector('#out .jump').textContent,
      marked: (document.querySelector('.ln.bad') || {}).textContent,
      trace: document.getElementById('out').textContent,
    })""")
    assert out["errors"] == [], out["errors"]
    assert out["state"].startswith("error")
    assert out["jump"] == "go to line 3"
    assert out["marked"] == "3"
    # the runner's own frames are not part of the user's bug
    assert "_epsilon_run" not in out["trace"]
    assert "ZeroDivisionError" in out["trace"]


@pytestmark_browser
def test_each_language_keeps_its_own_buffer_across_a_reload(tmp_path):
    """Three languages, three files, no file manager. Switching may not
    lose what you wrote, and neither may closing the tab."""
    out = drive(tmp_path, script="""
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.select();
    document.execCommand('insertText', false, 'answer = 42');
  })()`);
  await pg.waitForTimeout(200);
  await pg.click('#langs button:nth-child(2)');
  await pg.waitForTimeout(200);
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.select();
    document.execCommand('insertText', false, 'int answer = 42;');
  })()`);
  await pg.waitForTimeout(700);
  await pg.reload({ waitUntil: 'domcontentloaded' });
  await pg.waitForFunction("window.Epsilon && !document.getElementById('boot')",
                           null, { timeout: 60000 });
  await pg.waitForTimeout(300);
""", probe="""({
      language: window.Epsilon.language,
      cpp: document.getElementById('code').value.trim(),
      python: window.Epsilon.source.python.trim(),
      on: document.querySelector('#langs .on').textContent,
    })""")
    assert out["errors"] == [], out["errors"]
    assert out["language"] == "cpp"
    assert out["on"] == "c++"
    assert out["cpp"] == "int answer = 42;"
    assert out["python"] == "answer = 42"


@pytestmark_browser
def test_cpp_and_java_say_why_they_cannot_run_here(tmp_path):
    """A browser has no compiler. The honest thing is to name what is
    missing and stay a good editor, not to fake a result."""
    out = drive(tmp_path, script="""
  await pg.click('#langs button:nth-child(2)');
  await pg.waitForTimeout(250);
""", probe="""({
      disabled: document.getElementById('run').disabled,
      why: document.getElementById('run').title,
      state: document.getElementById('state').textContent,
      note: document.getElementById('out').textContent,
      caps: window.Epsilon.capabilities,
      highlighted: document.querySelectorAll('#paint .k').length,
      hints: !!document.getElementById('hints'),
    })""")
    assert out["errors"] == [], out["errors"]
    assert out["disabled"] is True
    assert "compiler" in out["why"] and "epsilon serve" in out["why"]
    assert out["state"] == "no compiler"
    # the reason belongs on the page, not only in a tooltip
    assert "compiler" in out["note"] and "epsilon serve" in out["note"]
    assert out["caps"]["server"] is False and out["caps"]["cpp"] is False
    assert out["caps"]["python"] is True
    # still a real editor for the language it cannot run
    assert out["highlighted"] > 3


@pytestmark_browser
def test_typing_stays_within_one_frame(tmp_path):
    """The whole reason this build exists. Anything that crosses into
    Python per keystroke shows up here as tens of milliseconds."""
    out = drive(tmp_path, script="""
  const perf = await pg.evaluate(async () => {
    const ta = document.getElementById('code');
    ta.focus();
    ta.setSelectionRange(0, 0);
    const each = [];
    for (const ch of 'import collections as c') {
      const t = performance.now();
      document.execCommand('insertText', false, ch);
      await new Promise((r) => requestAnimationFrame(r));
      each.push(performance.now() - t);
    }
    each.sort((a, b) => b - a);
    return { worst: +each[0].toFixed(1) };
  });
  await pg.evaluate((p) => { window.__perf = p; }, perf);
""", probe="""({ worst: window.__perf.worst })""")
    assert out["errors"] == [], out["errors"]
    assert out["worst"] < 60, f"a keystroke cost {out['worst']}ms"


@pytestmark_browser
def test_typing_cpp_includes_stays_within_one_frame(tmp_path):
    """`#include <iostream>` was the exact line that used to lock the
    page up, so it is the one measured here."""
    out = drive(tmp_path, script="""
  await pg.click('#langs button:nth-child(2)');
  await pg.waitForTimeout(250);
  const perf = await pg.evaluate(async () => {
    const ta = document.getElementById('code');
    ta.focus();
    ta.setSelectionRange(0, 0);
    const each = [];
    for (const ch of '#include <iostream>') {
      const t = performance.now();
      document.execCommand('insertText', false, ch);
      await new Promise((r) => requestAnimationFrame(r));
      each.push(performance.now() - t);
    }
    each.sort((a, b) => b - a);
    return { worst: +each[0].toFixed(1) };
  });
  await pg.evaluate((p) => { window.__perf = p; }, perf);
""", probe="""({ worst: window.__perf.worst })""")
    assert out["errors"] == [], out["errors"]
    assert out["worst"] < 60, f"a keystroke cost {out['worst']}ms"


@pytestmark_browser
def test_completion_comes_from_the_buffer(tmp_path):
    out = drive(tmp_path, script="""
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.select();
    document.execCommand('insertText', false, 'circumference = 1');
  })()`);
  await pg.waitForTimeout(200);
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.setSelectionRange(ta.value.length, ta.value.length);
    document.execCommand('insertText', false,
      String.fromCharCode(10) + 'circ');
  })()`);
  await pg.waitForTimeout(250);
""", probe="""({
      open: !document.getElementById('hints').hidden,
      first: (document.querySelector('.hint') || {}).textContent,
    })""")
    assert out["errors"] == [], out["errors"]
    assert out["open"] is True
    assert "circumference" in (out["first"] or "")


# --------------------------------------------------------------------------
# ligatures
# --------------------------------------------------------------------------

LIGATURE_PROBE = r"""
const g = globalThis;
require(process.argv[2]);
const E = g.EpsilonEditor;
const paint = (src, lang) => E.paint(src, lang || "python", true)[0];
const cells = (html) => {
  const out = [];
  const re = /<span class="lg[^"]*" style="width:(\d+)ch">([^<]*)<\/span>/g;
  let m;
  while ((m = re.exec(html))) out.push({ width: +m[1], glyph: m[2] });
  return out;
};
const plain = (html) => html.replace(/<[^>]*>/g, "");
const drawn = {};
for (const s of ["a >= b", "a <= b", "a != b", "a == b", "a -> b"]) {
  drawn[s] = cells(paint(s));
}
const left = {};
for (const s of ["a <- b", "a => b", "a <=> b", "a >>= b", "a !== b",
                 "a // b", "a << b", "a >> b", "a ... b", "a := b",
                 "a * b", "a / b", "a - b", "pi", "1/2", "x**2"]) {
  left[s] = { cells: cells(paint(s)), text: plain(paint(s)) };
}
console.log(JSON.stringify({
  drawn, left,
  string: plain(paint('s = "a >= b"')),
  comment: plain(paint("# a >= b")),
  cppComment: plain(paint("// a >= b", "cpp")),
  off: E.paint("a >= b", "python", false)[0],
  cpp: cells(paint("if (a >= b) p->q();", "cpp")),
  java: cells(paint("if (a != b) return x -> x;", "java")),
}));
"""


@pytest.mark.skipif(not NODE, reason="needs node")
def test_ligatures_never_change_the_grid(tmp_path):
    """The textarea underneath owns hit testing and lays every character
    on a uniform monospace grid. A ligature may therefore occupy exactly
    as many cells as the source it stands for — otherwise the caret and
    the glyphs drift apart."""
    probe = tmp_path / "probe.cjs"
    probe.write_text(LIGATURE_PROBE)
    r = subprocess.run([NODE, str(probe), str(EDITOR)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)

    for source, found in got["drawn"].items():
        assert len(found) == 1, f"{source} produced {found}"
        token = source.split(" ")[1]
        assert found[0]["width"] == len(token), (
            f"{token} was drawn {found[0]['width']} cells wide")

    assert [found[0]["glyph"] for found in got["drawn"].values()] == \
        ["≥", "≤", "≠", "≡", "→"]

    # the same five, in the two languages that also use them
    assert [c["glyph"] for c in got["cpp"]] == ["≥", "→"]
    assert [c["glyph"] for c in got["java"]] == ["≠", "→"]


@pytest.mark.skipif(not NODE, reason="needs node")
def test_only_the_basic_five_are_drawn(tmp_path):
    """Asked for, in these words: the basic ones, and everything else
    left as it is. `<-` is a comparison with a negative number, `//` is a
    comment in two of the three languages, and `<<` is how C++ prints —
    a glyph for any of them would be a lie about the program."""
    probe = tmp_path / "probe.cjs"
    probe.write_text(LIGATURE_PROBE)
    r = subprocess.run([NODE, str(probe), str(EDITOR)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)

    for source, found in got["left"].items():
        assert found["cells"] == [], f"{source} was ligated to {found['cells']}"
    assert got["left"]["a // b"]["text"] == "a // b"
    assert got["left"]["1/2"]["text"] == "1/2"
    assert got["left"]["x**2"]["text"] == "x**2"
    assert got["left"]["pi"]["text"] == "pi"

    editor = EDITOR.read_text()
    ops = re.search(r"const LIG_OPS = \[(.*?)\];", editor, re.S)
    assert ops, "LIG_OPS not found"
    assert len(re.findall(r'\["', ops.group(1))) == 5, "the set has grown"


@pytest.mark.skipif(not NODE, reason="needs node")
def test_ligatures_leave_meaning_alone(tmp_path):
    """The contents of a string are data — showing `>=` inside one as `≥`
    would misreport the program."""
    probe = tmp_path / "probe.cjs"
    probe.write_text(LIGATURE_PROBE)
    r = subprocess.run([NODE, str(probe), str(EDITOR)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout)

    for key in ("string", "comment", "cppComment"):
        assert "&gt;=" in got[key], f"{key} lost its source text"
        assert "≥" not in got[key], f"{key} was ligated"
    # and the whole layer is a choice, not a rewrite
    assert "≥" not in got["off"] and "&gt;=" in got["off"]


@pytestmark_browser
def test_the_painted_layer_sits_on_the_textarea_grid(tmp_path):
    """Measured, not assumed: every painted line must be exactly as wide
    as the same number of monospace cells."""
    out = drive(tmp_path, script="""
  await pg.evaluate(`(() => {
    const ta = document.getElementById('code');
    ta.select();
    document.execCommand('insertText', false, [
      'def f(v, hi, lo) -> bool:',
      '    if v >= hi and v <= lo:',
      '        return v != 0 and v == hi',
      '    return v // 2 >= lo -> 1'].join(String.fromCharCode(10)));
  })()`);
  await pg.waitForTimeout(400);
""", probe="""(() => {
      const ta = document.getElementById('code');
      const cs = getComputedStyle(ta);
      const probe = document.createElement('span');
      probe.style.cssText = 'position:absolute;visibility:hidden;white-space:pre';
      probe.style.font = cs.font;
      probe.textContent = '0'.repeat(40);
      document.body.appendChild(probe);
      const cell = probe.getBoundingClientRect().width / 40;
      probe.remove();
      const rows = document.querySelector('#paint code').innerHTML
        .split(String.fromCharCode(10));
      const src = ta.value.split(String.fromCharCode(10));
      const holder = document.createElement('div');
      holder.style.cssText = 'position:absolute;visibility:hidden;white-space:pre';
      holder.style.font = cs.font;
      document.body.appendChild(holder);
      let worst = 0;
      rows.forEach((html, i) => {
        if (!src[i] || !src[i].trim()) return;
        holder.innerHTML = html;
        worst = Math.max(worst, Math.abs(
          holder.getBoundingClientRect().width - cell * src[i].length));
      });
      holder.remove();
      return { worst: +worst.toFixed(2), cell: +cell.toFixed(2),
               ligated: document.querySelectorAll('#paint .lg').length };
    })()""")
    assert out["errors"] == [], out["errors"]
    assert out["ligated"] >= 6, f"only {out['ligated']} ligatures drawn"
    assert out["worst"] < 1.0, (
        f"the painted layer is {out['worst']}px off a {out['cell']}px grid")
