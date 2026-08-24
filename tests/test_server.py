"""Tests for the FastAPI server."""

import os

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("EPSILON_WORKSPACE", str(tmp_path / "ws"))
    # the workspace is resolved per-request from the env var, so a freshly
    # built app is bound to this test's temporary workspace
    from epsilon.server.app import create_app
    return TestClient(create_app())


def test_meta(client):
    r = client.get("/api/meta").json()
    assert r["brand"] == "Epsilon"
    assert "version" in r


def test_welcome_file_created(client):
    """A fresh workspace opens on a runnable Python file — the IDE's
    primary identity in this phase is programming, not mathematics."""
    entries = client.get("/api/files").json()["entries"]
    assert any(e["name"] == "main.py" for e in entries)


def test_file_crud_roundtrip(client):
    client.put("/api/file", json={"path": "a.epsl", "content": "def x : Nat := 1"})
    got = client.get("/api/file", params={"path": "a.epsl"}).json()
    assert got["content"] == "def x : Nat := 1"
    client.request("DELETE", "/api/file", params={"path": "a.epsl"})
    assert client.get("/api/file", params={"path": "a.epsl"}).status_code == 404


def test_path_traversal_rejected(client):
    r = client.get("/api/file", params={"path": "../../etc/passwd"})
    assert r.status_code == 400


def test_check_good_file(client):
    r = client.post("/api/check", json={
        "content": "theorem t (a : Nat) : a + 0 = a := by rfl\n"
                   "plot Real.sin, x ∈ [-3, 3]",
        "path": "m.epsl"}).json()
    assert r["ok"] is True
    assert any(t["name"] == "t" and t["status"] == "proven"
               for t in r["theorems"])
    assert len(r["plots"]) == 1
    assert r["plots"][0]["series"]
    assert "nodes" in r["deps"]


def test_check_bad_file_is_200_with_diagnostics(client):
    r = client.post("/api/check",
                    json={"content": "theorem bad : 1 = 2 := by rfl"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["diagnostics"]
    assert body["diagnostics"][0]["span"]


def test_check_numeric_status_honest(client):
    r = client.post("/api/check", json={
        "content": "theorem n : Real.sin(0) = 0 := by numeric"}).json()
    # numeric oracle => Numerically Verified, never proven
    if r["ok"]:
        assert r["theorems"][0]["status"] == "numeric"


def test_eval_persistence(client):
    assert client.post("/api/eval", json={"code": "2+2"}).json()["output"] == "4"
    client.post("/api/eval", json={"code": "def z : Nat := 9"})
    assert client.post("/api/eval", json={"code": "z"}).json()["output"] == "9"


def test_export_latex(client):
    r = client.post("/api/export", json={"format": "latex"}).json()
    assert r["ok"] is True


def test_export_python(client):
    client.put("/api/file",
               json={"path": "p.epsl", "content": "def sq (x : Real) : Real := x*x"})
    r = client.post("/api/export", json={"path": "p.epsl", "format": "python"}).json()
    assert r["ok"] is True
    assert "def sq" in r["content"]


def test_completions_prefix(client):
    items = client.get("/api/completions", params={"prefix": "add"}).json()["items"]
    assert any("add" in i["name"].lower() for i in items)


def test_serves_index_html(client):
    r = client.get("/")
    # either the IDE html or the API fallback
    assert r.status_code == 200


def test_hover_endpoint(client):
    r = client.get("/api/hover", params={"name": "Nat.add_comm"}).json()
    info = r["info"]
    assert info["name"] == "Nat.add_comm"
    assert info["title"] == "Natural Numbers · Addition Commutativity"
    assert info["status"] == "proven"


def test_hover_resolves_a_mathematical_name(client):
    r = client.get("/api/hover",
                   params={"name": "NaturalNumbers.Addition.Commutativity"}).json()
    assert r["info"]["name"] == "Nat.add_comm"


def test_hover_unknown_name_is_not_an_error(client):
    r = client.get("/api/hover", params={"name": "no_such_symbol_xyz"})
    assert r.status_code == 200
    assert r.json()["info"] is None


def test_definition_endpoint(client):
    r = client.get("/api/definition", params={"name": "Nat.add_comm"}).json()
    assert r["info"]["name"] == "Nat.add_comm"
    # a library result has a source span in its own module
    assert r["location"] is None or r["location"]["module"] == "prelude"


def test_completions_carry_mathematical_names(client):
    items = client.get("/api/completions",
                       params={"prefix": "add_comm"}).json()["items"]
    named = [i for i in items if i.get("display_name")]
    assert named, "expected at least one completion with a mathematical name"
    assert all("title" in i for i in items)


# --------------------------------------------------------------------------
# file explorer: folders, rename, duplicate
# --------------------------------------------------------------------------

def test_entries_list_folders_and_languages(client):
    client.post("/api/folder", json={"path": "algebra"})
    client.put("/api/file", json={"path": "algebra/rings.epsl", "content": ""})
    client.put("/api/file", json={"path": "solve.py", "content": "x = 1\n"})
    entries = client.get("/api/files").json()["entries"]
    by_path = {e["path"]: e for e in entries}
    assert by_path["algebra"]["kind"] == "folder"
    assert by_path["algebra/rings.epsl"]["language"] == "epsilon"
    assert by_path["solve.py"]["language"] == "python"
    assert by_path["solve.py"]["editable"] is True


def test_files_key_stays_epsilon_only(client):
    """Existing callers must keep seeing exactly what they saw before."""
    client.put("/api/file", json={"path": "notes.md", "content": "# hi"})
    files = client.get("/api/files").json()["files"]
    assert all(f["path"].endswith(".epsl") for f in files)


def test_rename_file(client):
    client.put("/api/file", json={"path": "old.epsl", "content": "def a : Nat := 1"})
    r = client.post("/api/rename", json={"path": "old.epsl", "to": "new.epsl"})
    assert r.json()["ok"] is True
    assert client.get("/api/file", params={"path": "old.epsl"}).status_code == 404
    assert client.get("/api/file",
                      params={"path": "new.epsl"}).json()["content"] == "def a : Nat := 1"


def test_rename_into_a_folder(client):
    client.post("/api/folder", json={"path": "sub"})
    client.put("/api/file", json={"path": "m.epsl", "content": "x"})
    client.post("/api/rename", json={"path": "m.epsl", "to": "sub/m.epsl"})
    assert client.get("/api/file", params={"path": "sub/m.epsl"}).json()["content"] == "x"


def test_rename_onto_an_existing_name_is_refused(client):
    client.put("/api/file", json={"path": "a.epsl", "content": "a"})
    client.put("/api/file", json={"path": "b.epsl", "content": "b"})
    r = client.post("/api/rename", json={"path": "a.epsl", "to": "b.epsl"})
    assert r.status_code == 409
    assert client.get("/api/file", params={"path": "b.epsl"}).json()["content"] == "b"


def test_rename_cannot_escape_the_workspace(client):
    client.put("/api/file", json={"path": "a.epsl", "content": "a"})
    r = client.post("/api/rename", json={"path": "a.epsl", "to": "../escaped.epsl"})
    assert r.status_code == 400


def test_folder_cannot_move_inside_itself(client):
    client.post("/api/folder", json={"path": "outer"})
    r = client.post("/api/rename", json={"path": "outer", "to": "outer/inner"})
    assert r.status_code == 400


def test_duplicate_file_picks_a_free_name(client):
    client.put("/api/file", json={"path": "thm.epsl", "content": "body"})
    first = client.post("/api/duplicate", json={"path": "thm.epsl"}).json()
    assert first["path"] == "thm copy.epsl"
    second = client.post("/api/duplicate", json={"path": "thm.epsl"}).json()
    assert second["path"] == "thm copy 2.epsl"
    assert client.get("/api/file",
                      params={"path": "thm copy.epsl"}).json()["content"] == "body"


def test_duplicate_folder_copies_contents(client):
    client.post("/api/folder", json={"path": "grp"})
    client.put("/api/file", json={"path": "grp/g.epsl", "content": "g"})
    dup = client.post("/api/duplicate", json={"path": "grp"}).json()["path"]
    assert client.get("/api/file",
                      params={"path": f"{dup}/g.epsl"}).json()["content"] == "g"


def test_delete_folder_is_recursive(client):
    client.post("/api/folder", json={"path": "tmp"})
    client.put("/api/file", json={"path": "tmp/x.epsl", "content": "x"})
    client.request("DELETE", "/api/folder", params={"path": "tmp"})
    paths = {e["path"] for e in client.get("/api/files").json()["entries"]}
    assert "tmp" not in paths and "tmp/x.epsl" not in paths


def test_workspace_root_is_not_deletable(client):
    r = client.request("DELETE", "/api/folder", params={"path": "."})
    assert r.status_code == 400


def test_hidden_and_cache_paths_are_not_listed(client):
    import os
    ws = client.get("/api/files")  # ensures the workspace exists
    assert ws.status_code == 200
    from epsilon.server.app import _workspace
    root = _workspace()
    os.makedirs(os.path.join(root, "__pycache__"), exist_ok=True)
    open(os.path.join(root, "__pycache__", "junk.pyc"), "w").close()
    open(os.path.join(root, ".secret"), "w").close()
    paths = {e["path"] for e in client.get("/api/files").json()["entries"]}
    assert not any(p.startswith("__pycache__") for p in paths)
    assert ".secret" not in paths


# --------------------------------------------------------------------------
# computer algebra
# --------------------------------------------------------------------------

def test_cas_operations_are_listed(client):
    ops = client.get("/api/cas/operations").json()["operations"]
    names = {o["op"] for o in ops}
    assert {"simplify", "expand", "derivative", "integral", "limit",
            "solve", "evaluate"} <= names
    assert all(o["label"] and o["description"] for o in ops)


def test_cas_expand(client):
    r = client.post("/api/cas", json={"op": "expand",
                                      "expr": "(x + 1) * (x - 1)"}).json()
    assert r["ok"] is True
    assert r["result"]["source"] == "x ^ 2 - 1"
    assert r["result"]["latex"]
    assert r["result"]["mathml"].startswith("<math")


def test_cas_result_is_symbolically_verified_never_proven(client):
    r = client.post("/api/cas", json={"op": "derivative", "expr": "x^3"}).json()
    assert r["status"] == "symbolic"
    assert r["status_label"] == "✓ Symbolically Verified"


def test_cas_evaluation_is_numeric(client):
    r = client.post("/api/cas", json={"op": "evaluate", "expr": "x^2 + 1",
                                      "point": "3"}).json()
    assert r["status"] == "numeric"
    assert r["status_label"] == "≈ Numerically Verified"


def test_cas_solve_returns_all_roots(client):
    r = client.post("/api/cas", json={"op": "solve", "expr": "x^2 - 4"}).json()
    assert sorted(x["source"] for x in r["results"]) == ["-2", "2"]


def test_cas_bad_input_is_200_with_a_message(client):
    r = client.post("/api/cas", json={"op": "simplify", "expr": "x +"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"]


def test_cas_unknown_antiderivative_is_admitted(client):
    r = client.post("/api/cas", json={
        "op": "integral", "expr": "Real.tan(x) * Real.exp(x^2)"}).json()
    assert r["ok"] is False
    assert "antiderivative" in r["message"]


# --------------------------------------------------------------------------
# rendered mathematics
# --------------------------------------------------------------------------

def test_render_returns_blocks_in_source_order(client):
    r = client.post("/api/render", json={"content":
        "def sq (x : Real) : Real := x * x\n"
        "theorem t (a : Nat) : a + 0 = a := by rfl"}).json()
    assert r["ok"] is True
    assert [b["name"] for b in r["blocks"]] == ["sq", "t"]


def test_render_carries_mathml_and_latex(client):
    r = client.post("/api/render", json={
        "content": "theorem t (a : Nat) : a + 0 = a := by rfl"}).json()
    block = r["blocks"][0]
    assert block["type"]["mathml"].startswith("<math")
    assert "\\forall" in block["type"]["latex"]
    assert r["document_latex"]


def test_render_keeps_the_engine_status(client):
    r = client.post("/api/render", json={
        "content": "theorem t (a : Nat) : a + 0 = a := by rfl\n"
                   "theorem n : Real.sin(0) = 0 := by numeric"}).json()
    by_name = {b["name"]: b for b in r["blocks"]}
    assert by_name["t"]["status_label"] == "✓ Formally Proven"
    assert by_name["n"]["status_label"] == "≈ Numerically Verified"


def test_render_shows_a_definition_body_but_not_a_proof_term(client):
    r = client.post("/api/render", json={
        "content": "def sq (x : Real) : Real := x * x\n"
                   "theorem t (a : Nat) : a + 0 = a := by rfl"}).json()
    by_name = {b["name"]: b for b in r["blocks"]}
    assert "value" in by_name["sq"]
    assert "value" not in by_name["t"]


def test_render_of_a_broken_file_reports_rather_than_500(client):
    r = client.post("/api/render", json={"content": "theorem bad : 1 = 2 := by rfl"})
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["diagnostics"]


# --------------------------------------------------------------------------
# proof explorer
# --------------------------------------------------------------------------

def test_suggest_finds_the_obvious_result(client):
    r = client.post("/api/suggest", json={
        "goal": "a + b = b + a",
        "hypotheses": [["a", "Nat"], ["b", "Nat"]], "limit": 5}).json()
    assert r["ok"] is True
    top = r["suggestions"][0]
    assert top["name"] == "Nat.add_comm"
    assert top["tactic"] == "exact Nat.add_comm a b"
    assert top["title"] == "NaturalNumbers.Addition.Commutativity"
    assert top["status"] == "proven"


def test_suggest_never_offers_sorry_or_a_trust_axiom(client):
    r = client.post("/api/suggest", json={
        "goal": "a + b = b + a",
        "hypotheses": [["a", "Nat"], ["b", "Nat"]], "limit": 50}).json()
    names = {s["name"] for s in r["suggestions"]}
    assert not (names & {"Epsilon.sorry", "Epsilon.trustedCAS",
                         "Epsilon.trustedNumeric"})


def test_suggest_on_an_unreadable_goal_is_200_with_a_message(client):
    r = client.post("/api/suggest", json={"goal": "nonsense ++"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["message"]
    assert body["suggestions"] == []


# --------------------------------------------------------------------------
# running programs
# --------------------------------------------------------------------------

def test_run_python(client):
    r = client.post("/api/run", json={"language": "python",
                                      "code": "print(6 * 7)"}).json()
    assert r["ok"] is True
    assert r["stdout"] == "42\n"
    assert r["exit_code"] == 0


def test_run_reports_failure_honestly(client):
    r = client.post("/api/run", json={"language": "python",
                                      "code": "1/0"}).json()
    assert r["ok"] is False
    assert "ZeroDivisionError" in r["stderr"]
    assert r["diagnostics"]


def test_run_languages_listed(client):
    langs = client.get("/api/run/languages").json()["languages"]
    assert langs["python"] is True
    assert "cpp" in langs


def test_pyrepl_state_persists_across_requests(client):
    client.post("/api/pyrepl", json={"code": "n = 6"})
    r = client.post("/api/pyrepl", json={"code": "n * 7"}).json()
    assert r["output"] == "42\n"


def test_pyrepl_reset(client):
    client.post("/api/pyrepl", json={"code": "n = 1"})
    client.post("/api/pyrepl", json={"code": "", "reset": True})
    r = client.post("/api/pyrepl", json={"code": "n"}).json()
    assert "NameError" in r["error"]


def test_code_execution_refuses_cross_origin_calls(client):
    """Any web page can POST to localhost; only same-origin (or no-origin,
    i.e. the user's own tools) may execute code."""
    evil = {"Origin": "https://evil.example"}
    for path, body in (("/api/run", {"language": "python", "code": "print(1)"}),
                       ("/api/pyrepl", {"code": "1"})):
        r = client.post(path, json=body, headers=evil)
        assert r.status_code == 403, path


def test_code_execution_allows_the_ide_itself(client):
    r = client.post("/api/run",
                    json={"language": "python", "code": "print(1)"},
                    headers={"Origin": "http://testserver"})
    assert r.status_code == 200


# --------------------------------------------------------------------------
# cross-pane integration (phase 4)
# --------------------------------------------------------------------------

def test_mathify_typesets_python_arithmetic(client):
    r = client.post("/api/mathify", json={"expr": "math.sin(x)/x"}).json()
    assert r["ok"] is True
    assert r["latex"] == "\\frac{\\sin\\!\\left(x\\right)}{x}"
    assert r["mathml"].startswith("<math")
    assert r["source"] == "Real.sin x / x"     # the Epsilon reading, for CAS


def test_mathify_refuses_non_mathematics(client):
    r = client.post("/api/mathify", json={"expr": "print(1)"}).json()
    assert r["ok"] is False and r["message"]


def test_cas_results_carry_runnable_python(client):
    r = client.post("/api/cas", json={"op": "derivative",
                                      "expr": "x^3 + Real.sin(x)"}).json()
    assert r["result"]["python"] == "3 * x ** 2 + math.cos(x)"


def test_exported_python_actually_runs(client):
    """Epsilon → Python → Run: the generated file must execute."""
    client.put("/api/file", json={
        "path": "sq.epsl", "content": "def sq (x : Real) : Real := x * x"})
    code = client.post("/api/export",
                       json={"path": "sq.epsl", "format": "python"}).json()["content"]
    r = client.post("/api/run", json={
        "language": "python", "code": code + "\nprint(sq(7))"}).json()
    assert r["ok"] is True, r["stderr"]
    assert r["stdout"].strip() == "49"
