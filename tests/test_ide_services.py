"""The programming-IDE backend: terminal, debug, completion, format, search,
git — every one the real thing, with an honest capability report."""

import time

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EPSILON_WORKSPACE", str(tmp_path / "ws"))
    from epsilon.server.app import create_app
    c = TestClient(create_app())
    c.get("/api/files")
    return c


# --------------------------------------------------------------------------
# capabilities
# --------------------------------------------------------------------------

def test_capabilities_report_only_the_truth(client):
    caps = client.get("/api/capabilities").json()
    assert caps["run"]["python"] is True
    assert caps["terminal"] is True
    assert caps["debug"]["python"] is True
    assert caps["debug"]["cpp"] is False           # no gdb integration yet
    assert caps["completions"]["python"] in ("semantic", "lexical")
    assert caps["completions"]["cpp"] == "lexical"  # no compiler front-end
    assert isinstance(caps["git"], bool)


# --------------------------------------------------------------------------
# completion / format
# --------------------------------------------------------------------------

def test_python_completion_of_module_members(client):
    r = client.post("/api/complete", json={
        "language": "python", "code": "import math\nmath.",
        "line": 2, "col": 5}).json()
    names = {i["name"] for i in r["items"]}
    assert "sqrt" in names and "pi" in names


def test_go_to_definition_finds_a_symbol_in_the_buffer(client):
    code = "def helper(x):\n    return x * 2\n\n\nprint(helper(21))\n"
    r = client.post("/api/definition", json={
        "language": "python", "code": code, "line": 5, "col": 8}).json()
    assert r["found"] is True
    assert r["line"] == 1
    assert r["name"] == "helper"


def test_a_definition_outside_the_workspace_is_named_not_faked(client):
    """The workspace holds only the user's files; jumping into an installed
    module would open nothing. Say where it lives instead."""
    r = client.post("/api/definition", json={
        "language": "python", "code": "import os\nos.path.join\n",
        "line": 2, "col": 4}).json()
    assert r["found"] is False
    # it names the module the symbol really lives in, not a guess
    assert "os" in r["message"] and "outside the workspace" in r["message"]


def test_definition_refuses_languages_with_no_language_service(client):
    r = client.post("/api/definition", json={
        "language": "cpp", "code": "int main(){}", "line": 1, "col": 5}).json()
    assert r["found"] is False
    assert "Python" in r["message"]


def test_capabilities_state_whether_definitions_are_semantic(client):
    caps = client.get("/api/capabilities").json()
    assert isinstance(caps["definitions"]["python"], bool)
    assert caps["definitions"]["cpp"] is False


def test_cpp_std_completion(client):
    r = client.post("/api/complete", json={
        "language": "cpp", "code": "int main(){ std::v", "line": 1,
        "col": 18}).json()
    assert r["level"] == "lexical"                 # says what it is
    assert "vector" in {i["name"] for i in r["items"]}


def test_format_python(client):
    caps = client.get("/api/capabilities").json()
    if not caps["format"]["python"]:
        pytest.skip("black not on this machine")
    r = client.post("/api/format", json={
        "language": "python", "code": "def  f( x ):\n  return(x+1)\n"}).json()
    assert r["ok"] and r["code"] == "def f(x):\n    return x + 1\n"


def test_format_refusal_names_the_reason(client):
    r = client.post("/api/format",
                    json={"language": "rust", "code": ""}).json()
    assert r["ok"] is False and "rust" in r["message"]


# --------------------------------------------------------------------------
# search / replace
# --------------------------------------------------------------------------

def test_search_finds_and_locates(client):
    client.put("/api/file", json={"path": "one.py",
                                  "content": "alpha = 1\nbeta = alpha\n"})
    r = client.post("/api/search", json={"query": "alpha"}).json()
    assert r["ok"] and len(r["results"]) == 2
    first = r["results"][0]
    assert first["path"] == "one.py" and first["line"] == 1 and first["col"] == 0


def test_search_regex_and_bad_pattern(client):
    client.put("/api/file", json={"path": "t.py", "content": "x1 x2 xa\n"})
    r = client.post("/api/search", json={"query": r"x\d", "regex": True}).json()
    assert len(r["results"]) == 2
    r = client.post("/api/search", json={"query": "(", "regex": True}).json()
    assert r["ok"] is False and "pattern" in r["message"]


def test_replace_in_files_respects_the_path_filter(client):
    client.put("/api/file", json={"path": "a.py", "content": "name = 1\n"})
    client.put("/api/file", json={"path": "b.py", "content": "name = 2\n"})
    r = client.post("/api/replace", json={
        "query": "name", "replacement": "value", "paths": ["a.py"]}).json()
    assert r["files"] == {"a.py": 1}
    assert "name" in client.get("/api/file", params={"path": "b.py"}).json()["content"]


def test_replace_is_same_origin_only(client):
    r = client.post("/api/replace", json={"query": "x", "replacement": "y"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# terminal
# --------------------------------------------------------------------------

def test_terminal_runs_a_real_shell(client):
    sid = client.post("/api/terminal").json()["id"]
    client.post(f"/api/terminal/{sid}/input",
                json={"data": "echo $((6*7))\n"})
    out = ""
    for _ in range(40):
        r = client.get(f"/api/terminal/{sid}").json()
        out += r["data"]
        if "42" in out:
            break
        time.sleep(0.1)
    assert "42" in out
    client.delete(f"/api/terminal/{sid}")
    assert not any(t["id"] == sid
                   for t in client.get("/api/terminal").json()["terminals"])


def test_terminal_read_is_incremental(client):
    sid = client.post("/api/terminal").json()["id"]
    time.sleep(0.4)
    r1 = client.get(f"/api/terminal/{sid}").json()
    r2 = client.get(f"/api/terminal/{sid}",
                    params={"since": r1["cursor"]}).json()
    assert r2["data"] == ""                        # nothing new since cursor
    client.delete(f"/api/terminal/{sid}")


def test_terminal_creation_is_same_origin_only(client):
    r = client.post("/api/terminal",
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# debugging
# --------------------------------------------------------------------------

def _drain(client, sid, until, timeout=8.0):
    events, since = [], 0
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = client.get(f"/api/debug/{sid}", params={"since": since}).json()
        events += r["events"]
        since = r["cursor"]
        if any(e["event"] == until for e in r["events"]):
            return events
        time.sleep(0.05)
    raise AssertionError(f"never saw {until}: {events}")


def test_debug_breakpoint_step_and_locals(client):
    sid = client.post("/api/debug", json={
        "code": "a = 10\nb = a * 2\nprint(b)\n",
        "breakpoints": [2]}).json()["id"]
    events = _drain(client, sid, "stopped")
    stop = [e for e in events if e["event"] == "stopped"][-1]
    assert stop["line"] == 2 and stop["locals"]["a"] == "10"

    client.post(f"/api/debug/{sid}/cmd", json={"op": "eval", "expr": "a + 5"})
    events = _drain(client, sid, "eval")
    assert [e for e in events if e["event"] == "eval"][-1]["value"] == "15"

    client.post(f"/api/debug/{sid}/cmd", json={"op": "continue"})
    events = _drain(client, sid, "exited")
    output = "".join(e["data"] for e in events if e["event"] == "output"
                     and e.get("stream") == "stdout")
    assert "20" in output
    client.delete(f"/api/debug/{sid}")


def test_debug_is_same_origin_only(client):
    r = client.post("/api/debug", json={"code": "pass"},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


# --------------------------------------------------------------------------
# git
# --------------------------------------------------------------------------

def test_git_full_cycle(client):
    caps = client.get("/api/capabilities").json()
    if not caps["git"]:
        pytest.skip("git not on this machine")
    assert client.get("/api/git/status").json()["repo"] is False
    assert client.post("/api/git/init").json()["ok"] is True

    client.put("/api/file", json={"path": "hello.py", "content": "print(1)\n"})
    st = client.get("/api/git/status").json()
    assert st["repo"] and any(c["path"] == "hello.py" for c in st["changes"])

    client.post("/api/git/stage", json={"paths": ["hello.py", "main.py"]})
    r = client.post("/api/git/commit", json={"message": "first"}).json()
    assert r["ok"] and r["hash"]
    assert client.get("/api/git/status").json()["changes"] == []

    client.put("/api/file", json={"path": "hello.py", "content": "print(2)\n"})
    d = client.get("/api/git/diff", params={"path": "hello.py"}).json()
    assert "+print(2)" in d["diff"]

    log = client.get("/api/git/log").json()["entries"]
    assert log[0]["subject"] == "first"

    client.post("/api/git/discard", json={"paths": ["hello.py"]})
    assert "print(1)" in client.get("/api/file",
                                    params={"path": "hello.py"}).json()["content"]


def test_git_commit_without_message_is_refused(client):
    client.post("/api/git/init")
    r = client.post("/api/git/commit", json={"message": "  "}).json()
    assert r["ok"] is False and "message" in r["message"]


def test_git_mutations_are_same_origin_only(client):
    for path in ("/api/git/init", "/api/git/commit"):
        r = client.post(path, json={"message": "x"},
                        headers={"Origin": "https://evil.example"})
        assert r.status_code == 403, path

# --------------------------------------------------------------------------
# dependency graph
# --------------------------------------------------------------------------

def test_python_graph_links_a_function_to_what_it_uses(client):
    code = ("import math\n\n\nSCALE = 2\n\n\n"
            "def area(r):\n    return math.pi * r * r * SCALE\n\n\n"
            "print(area(1))\n")
    r = client.post("/api/graph", json={
        "language": "python", "code": code, "line": 1, "col": 0}).json()
    assert r["ok"] and r["level"] == "semantic"
    kinds = {n["name"]: n["kind"] for n in r["nodes"]}
    assert kinds["area"] == "function"
    assert kinds["SCALE"] == "variable"
    assert kinds["math"] == "import"
    edges = {(e["from"], e["to"]) for e in r["edges"]}
    assert ("area", "math") in edges
    assert ("area", "SCALE") in edges
    # the module body uses the function, which is what "who calls this" means
    assert ("<module>", "area") in edges


def test_graph_counts_incoming_references(client):
    code = "def a():\n    pass\n\n\ndef b():\n    a()\n\n\ndef c():\n    a()\n"
    r = client.post("/api/graph", json={
        "language": "python", "code": code, "line": 1, "col": 0}).json()
    refs = {n["name"]: n["refs"] for n in r["nodes"]}
    assert refs["a"] == 2 and refs["b"] == 0


def test_graph_reports_a_syntax_error_rather_than_an_empty_picture(client):
    r = client.post("/api/graph", json={
        "language": "python", "code": "def broken(\n", "line": 1,
        "col": 0}).json()
    assert r["ok"] is False and "line" in r["message"]


def test_cpp_graph_is_lexical_and_says_so(client):
    code = ("int add(int a){ return a; }\n"
            "int twice(int x){ return add(x) + add(x); }\n"
            "int main(){ return twice(2); }\n")
    r = client.post("/api/graph", json={
        "language": "cpp", "code": code, "line": 1, "col": 0}).json()
    assert r["level"] == "lexical"
    assert "no compiler front-end" in r["note"]
    edges = {(e["from"], e["to"]) for e in r["edges"]}
    assert ("twice", "add") in edges and ("main", "twice") in edges
    # a body ends where the next signature starts, not where it ends
    assert ("add", "twice") not in edges


def test_graph_refuses_a_language_it_cannot_read(client):
    r = client.post("/api/graph", json={
        "language": "markdown", "code": "# hi", "line": 1, "col": 0}).json()
    assert r["ok"] is False
    assert "Python" in r["message"] and r["nodes"] == []


def test_capabilities_state_the_graph_level_per_language(client):
    caps = client.get("/api/capabilities").json()
    assert caps["graph"] == {"python": "semantic", "cpp": "lexical"}
