"""Project-pipeline tests: stdlib, dependency graph, imports, notation."""

import pytest

from epsilon.project import Session


def test_stdlib_loads_all_proven(stdlib_session):
    thms = stdlib_session.theorem_list()
    assert len(thms) >= 35
    assert all(t["status"] == "proven" for t in thms), \
        [t["name"] for t in thms if t["status"] != "proven"]


def test_dependency_graph_edges(stdlib_session):
    g = stdlib_session.dependency_graph()
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    assert ("Nat.add_comm", "Nat.succ_add") in edges


def test_dependency_graph_reaches_axioms(stdlib_session):
    g = stdlib_session.dependency_graph()
    edges = {(e["from"], e["to"]) for e in g["edges"]}
    # Classical.byContradiction depends on Classical.em
    assert ("Classical.byContradiction", "Classical.em") in edges


def test_missing_import_is_diagnostic_not_crash():
    s = Session()
    r = s.check_source("import nonexistent.module", "m")
    assert not r.ok
    assert any("not found" in d.message for d in r.diagnostics)


def test_plots_collected():
    s = Session()
    s.check_source("plot Real.sin, x ∈ [-3, 3]", "m")
    assert len(s.plots) == 1
    assert s.plots[0]["var"] == "x"


def test_reproducibility_info_has_hashes(stdlib_session):
    info = stdlib_session.reproducibility_info()
    assert info["language_version"]
    assert info["theorems"]
    for name, meta in info["theorems"].items():
        assert meta["hash"]
        assert meta["status"]


def test_theorem_spans_and_modules(stdlib_session):
    for t in stdlib_session.theorem_list("prelude"):
        assert t["module"] == "prelude"
        assert t["span"][0] >= 1


def test_notation_within_one_source():
    s = Session()
    r = s.check_source(
        'infixl 65 "⊕" := Nat.add\n#eval 3 ⊕ 4', "m")
    assert r.ok
    msg = [x.message for x in r.results if x.kind == "eval"][0]
    assert msg == "7"


def test_notation_persists_across_checks():
    s = Session()
    s.check_source('infixl 65 "⊗" := Nat.mul', "m1")
    r = s.check_source("#eval 6 ⊗ 7", "m2")
    assert r.ok
    msg = [x.message for x in r.results if x.kind == "eval"][0]
    assert msg == "42"


def test_verification_status_labels():
    s = Session()
    s.check_source(
        "theorem p (a : Nat) : a + 0 = a := by rfl\n"
        "theorem n : Real.sin(0) = 0 := by numeric\n"
        "theorem h : 1 = 2 := by sorry", "m")
    st = {t["name"]: t["status"] for t in s.theorem_list("m")}
    assert st["p"] == "proven"
    assert st["n"] == "numeric"
    assert st["h"] == "heuristic"


def test_definition_list(stdlib_session):
    defs = stdlib_session.definition_list("prelude")
    names = {d["name"] for d in defs}
    assert "Not" in names or "sin" in names


def test_incremental_checker_reuse():
    from epsilon.incremental import IncrementalChecker
    ic = IncrementalChecker(module="m")
    src = "theorem a (n : Nat) : n + 0 = n := by rfl\n"
    ic.check(src)
    ic.stats.update(reused=0, rechecked=0)
    ic.check(src)  # identical -> full reuse
    assert ic.stats["reused"] == 1
    assert ic.stats["rechecked"] == 0
