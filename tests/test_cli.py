"""Tests for the CLI and REPL."""

import os

import pytest

from epsilon.cli import main
from epsilon.repl import Repl, classify_line, needs_continuation


# ---------------------------------------------------------------------------
# REPL helpers
# ---------------------------------------------------------------------------

def test_classify_command():
    assert classify_line("def f (x : Nat) : Nat := x") == "command"
    assert classify_line("theorem t : p := by rfl") == "command"
    assert classify_line("#check foo") == "command"


def test_classify_expression():
    assert classify_line("2 + 3 * 4") == "expr"
    assert classify_line("Real.sin(x)") == "expr"


def test_needs_continuation():
    assert needs_continuation("theorem t : p := by")
    assert needs_continuation("def f (x : Nat) :=")
    assert not needs_continuation("x = x")


def test_repl_eval():
    r = Repl()
    assert r.run_input("2 + 3 * 4") == "14"


def test_repl_definition_then_use():
    r = Repl()
    r.run_input("def sq (n : Nat) : Nat := n * n")
    assert r.run_input("sq(7)") == "49"


def test_repl_theorem_status():
    r = Repl()
    out = r.run_input("theorem tt (a : Nat) : a + 0 = a := by rfl")
    assert "Formally Proven" in out


def test_repl_meta_type():
    r = Repl()
    out = r.run_input(":type Nat.add_comm")
    assert "Nat.add_comm" in out and "→" in out or "∀" in out


def test_repl_error_reported():
    r = Repl()
    out = r.run_input("theorem bad : 1 = 2 := by rfl")
    assert "error" in out.lower()


# ---------------------------------------------------------------------------
# CLI (subprocess-free: call main directly with a tmp project)
# ---------------------------------------------------------------------------

def test_version(capsys):
    rc = main(["version"])
    assert rc == 0
    assert "Epsilon" in capsys.readouterr().out


def test_new_and_check(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["new", "demo"]) == 0
    assert (tmp_path / "demo" / "epsilon.toml").is_file()
    assert (tmp_path / "demo" / "src" / "main.epsl").is_file()
    monkeypatch.chdir(tmp_path / "demo")
    assert main(["check"]) == 0     # scaffold must check cleanly


def test_check_reports_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "bad.epsl").write_text("theorem oops : 1 = 2 := by rfl\n")
    rc = main(["check", "bad.epsl"])
    assert rc == 1


def test_prove_prints_statuses(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "p.epsl").write_text(
        "theorem good (a : Nat) : a + 0 = a := by rfl\n")
    main(["prove", "p.epsl"])
    out = capsys.readouterr().out
    assert "Formally Proven" in out


def test_fmt_fixes_trailing_whitespace(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    f = tmp_path / "f.epsl"
    f.write_text("def x : Nat := 1   \n\n")  # trailing ws
    main(["fmt", "f.epsl"])
    assert "   \n" not in f.read_text()


def test_export_latex(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.epsl").write_text(
        "theorem t (a : Nat) : a + 0 = a := by rfl\n")
    rc = main(["export", "m.epsl", "--format", "latex"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "\\documentclass" in out or "theorem" in out.lower()


def test_export_json(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.epsl").write_text("def d : Nat := 5\n")
    rc = main(["export", "m.epsl", "--json"])
    assert rc == 0
    import json
    out = capsys.readouterr().out
    json.loads(out)  # must be valid JSON


def test_export_python(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "m.epsl").write_text("def sq (x : Real) : Real := x * x\n")
    rc = main(["export", "m.epsl", "--python"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "def sq" in out


def test_run_prints_eval(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "r.epsl").write_text("#eval 2 + 3 * 4\n")
    main(["run", "r.epsl"])
    assert "14" in capsys.readouterr().out
