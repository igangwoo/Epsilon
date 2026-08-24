"""The browser workspace must behave like the server's.

The web build has no server: `web/vfs.js` reimplements the file API against
localStorage. Two implementations of one contract drift unless something
compares them, so these tests run the *same* request sequence through both
and assert the same answers.

Skipped when node is unavailable.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
VFS = ROOT / "web" / "vfs.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = """
const {{ create }} = require({vfs!r});
// a localStorage stand-in; the real one is the browser's
const mem = {{}};
const store = {{
  getItem: (k) => (k in mem ? mem[k] : null),
  setItem: (k, v) => {{ mem[k] = String(v); }},
}};
const vfs = create(store, "-- welcome\\n");
const out = [];
for (const step of {steps}) {{
  const r = vfs.handle(step.path, step.method, step.body, step.params);
  out.push(r === null ? {{ status: 404, body: {{ detail: "unhandled" }} }} : r);
}}
console.log(JSON.stringify(out));
"""


def run_js(steps):
    src = DRIVER.format(vfs=str(VFS), steps=json.dumps(steps))
    r = subprocess.run([NODE, "-e", src], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EPSILON_WORKSPACE", str(tmp_path / "ws"))
    from epsilon.server.app import create_app
    c = TestClient(create_app())
    c.get("/api/files")  # materialise the welcome file
    return c


def run_server(client, steps):
    out = []
    for s in steps:
        r = client.request(s["method"], s["path"], json=s.get("body"),
                           params=s.get("params"))
        out.append({"status": r.status_code, "body": r.json()})
    return out


def compare(client, steps, keys=("ok", "path", "detail")):
    """Both backends must agree on status and on the fields callers read."""
    js = run_js(steps)
    py = run_server(client, steps)
    assert len(js) == len(py)
    for step, a, b in zip(steps, js, py):
        label = f"{step['method']} {step['path']} {step.get('body') or step.get('params')}"
        assert a["status"] == b["status"], (
            f"{label}: browser {a['status']} vs server {b['status']} "
            f"({a['body']} / {b['body']})")
        for k in keys:
            if k in a["body"] or k in b["body"]:
                assert a["body"].get(k) == b["body"].get(k), f"{label}: field {k}"


def _steps(*items):
    out = []
    for method, path, payload in items:
        step = {"method": method, "path": path}
        if method in ("GET", "DELETE"):
            step["params"] = payload
        else:
            step["body"] = payload
        out.append(step)
    return out


def test_create_rename_read(client):
    compare(client, _steps(
        ("PUT", "/api/file", {"path": "old.epsl", "content": "def a : Nat := 1"}),
        ("POST", "/api/rename", {"path": "old.epsl", "to": "new.epsl"}),
        ("GET", "/api/file", {"path": "old.epsl"}),
        ("GET", "/api/file", {"path": "new.epsl"}),
    ), keys=("ok", "path", "detail", "content"))


def test_rename_conflict_agrees(client):
    compare(client, _steps(
        ("PUT", "/api/file", {"path": "a.epsl", "content": "a"}),
        ("PUT", "/api/file", {"path": "b.epsl", "content": "b"}),
        ("POST", "/api/rename", {"path": "a.epsl", "to": "b.epsl"}),
        ("POST", "/api/rename", {"path": "missing.epsl", "to": "z.epsl"}),
    ))


def test_rename_escape_is_refused_by_both(client):
    compare(client, _steps(
        ("PUT", "/api/file", {"path": "a.epsl", "content": "a"}),
        ("POST", "/api/rename", {"path": "a.epsl", "to": "../escaped.epsl"}),
    ))


def test_folder_cannot_move_inside_itself_in_both(client):
    compare(client, _steps(
        ("POST", "/api/folder", {"path": "outer"}),
        ("POST", "/api/rename", {"path": "outer", "to": "outer/inner"}),
    ))


def test_duplicate_naming_agrees(client):
    compare(client, _steps(
        ("PUT", "/api/file", {"path": "thm.epsl", "content": "body"}),
        ("POST", "/api/duplicate", {"path": "thm.epsl"}),
        ("POST", "/api/duplicate", {"path": "thm.epsl"}),
        ("POST", "/api/duplicate", {"path": "nope.epsl"}),
    ))


def test_folder_delete_is_recursive_in_both(client):
    compare(client, _steps(
        ("POST", "/api/folder", {"path": "tmp"}),
        ("PUT", "/api/file", {"path": "tmp/x.epsl", "content": "x"}),
        ("DELETE", "/api/folder", {"path": "tmp"}),
        ("GET", "/api/file", {"path": "tmp/x.epsl"}),
    ))


def test_workspace_root_is_protected_in_both(client):
    compare(client, _steps(
        ("DELETE", "/api/folder", {"path": "."}),
    ))


def test_language_tagging_agrees(client):
    steps = _steps(
        ("PUT", "/api/file", {"path": "solve.py", "content": "x = 1"}),
        ("PUT", "/api/file", {"path": "notes.md", "content": "# hi"}),
        ("PUT", "/api/file", {"path": "fast.cpp", "content": "int main(){}"}),
        ("GET", "/api/files", {}),
    )
    js_entries = {e["path"]: e for e in run_js(steps)[-1]["body"]["entries"]}
    py_entries = {e["path"]: e for e in run_server(client, steps)[-1]["body"]["entries"]}
    for path in ("solve.py", "notes.md", "fast.cpp", "main.epsl"):
        assert js_entries[path]["language"] == py_entries[path]["language"], path


def test_files_key_is_epsilon_only_in_both(client):
    steps = _steps(
        ("PUT", "/api/file", {"path": "notes.md", "content": "# hi"}),
        ("GET", "/api/files", {}),
    )
    js_files = {f["path"] for f in run_js(steps)[-1]["body"]["files"]}
    py_files = {f["path"] for f in run_server(client, steps)[-1]["body"]["files"]}
    assert js_files == py_files
    assert all(p.endswith(".epsl") for p in js_files)
