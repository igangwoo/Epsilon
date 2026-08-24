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
    files = client.get("/api/files").json()["files"]
    assert any(f["name"] == "main.epsl" for f in files)


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
