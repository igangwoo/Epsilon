"""Running Python and C++ — real subprocesses, honest reporting."""

import shutil

import pytest

from epsilon.runtime import available_languages, run_code
from epsilon.runtime.pyrepl import PythonRepl

HAS_CXX = shutil.which("g++") or shutil.which("clang++")
needs_cxx = pytest.mark.skipif(not HAS_CXX, reason="no C++ compiler")


# --------------------------------------------------------------------------
# python
# --------------------------------------------------------------------------

def test_python_runs_and_captures_both_streams():
    r = run_code("python", "print(2+3)\nimport sys; print('e', file=sys.stderr)")
    assert r.ok and r.exit_code == 0
    assert r.stdout == "5\n"
    assert r.stderr == "e\n"
    assert r.duration_ms >= 0


def test_python_reads_stdin():
    r = run_code("python", "print(int(input()) * 2)", stdin="21\n")
    assert r.stdout == "42\n"


def test_python_failure_reports_exit_code_and_line():
    r = run_code("python", "def f():\n    return 1/0\nf()")
    assert not r.ok and r.exit_code == 1
    assert "ZeroDivisionError" in r.stderr
    [d] = r.diagnostics
    assert d["span"][0] == 2                     # the frame inside f()
    assert "ZeroDivisionError" in d["message"]


def test_python_timeout_is_reported_not_hung():
    r = run_code("python", "while True: pass", timeout=1)
    assert not r.ok
    assert "did not finish" in r.message
    assert r.duration_ms < 5000


def test_python_ignores_injected_import_paths(tmp_path, monkeypatch):
    """`-I` isolation: a PYTHONPATH pointed at attacker-controlled code must
    not be honoured. (Installed packages *are* importable — a real Python
    run importing `math` or `numpy` is the point, not a leak.)"""
    (tmp_path / "sneaky.py").write_text("VALUE = 1")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    r = run_code("python", "import sneaky")
    assert not r.ok
    assert "ModuleNotFoundError" in r.stderr


def test_output_is_capped_not_unbounded():
    r = run_code("python", "print('x' * 1_000_000)")
    assert "truncated" in r.stdout
    assert len(r.stdout) < 300_000


# --------------------------------------------------------------------------
# c++
# --------------------------------------------------------------------------

@needs_cxx
def test_cpp_compiles_and_runs():
    r = run_code("cpp", '#include <cstdio>\nint main(){printf("hi\\n");}')
    assert r.ok and r.phase == "run"
    assert r.stdout == "hi\n"


@needs_cxx
def test_cpp_reads_stdin():
    src = ('#include <cstdio>\nint main(){int x; scanf("%d", &x); '
           'printf("%d\\n", x * x);}')
    assert run_code("cpp", src, stdin="9").stdout == "81\n"


@needs_cxx
def test_cpp_compile_error_maps_to_the_source_line():
    r = run_code("cpp", "int main() {\n  return x;\n}")
    assert not r.ok and r.phase == "compile"
    [d] = [d for d in r.diagnostics if d["severity"] == "error"]
    assert d["span"][0] == 2
    assert "x" in d["message"]


@needs_cxx
def test_cpp_runtime_failure_reports_exit_code():
    r = run_code("cpp", "int main(){ return 3; }")
    assert not r.ok and r.phase == "run" and r.exit_code == 3


def test_unknown_language_is_refused_plainly():
    r = run_code("rust", "fn main() {}")
    assert not r.ok and "not a runnable language" in r.message


def test_available_languages_tells_the_truth():
    langs = available_languages()
    assert langs["python"] is True
    assert langs["cpp"] == bool(HAS_CXX)


# --------------------------------------------------------------------------
# the python console
# --------------------------------------------------------------------------

@pytest.fixture()
def repl():
    r = PythonRepl()
    yield r
    r.reset()


def test_console_state_persists_between_inputs(repl):
    repl.run("x = 21")
    assert repl.run("x * 2")["output"] == "42\n"


def test_console_echoes_bare_expressions(repl):
    assert repl.run("1 + 1")["output"] == "2\n"


def test_console_survives_an_exception_with_state_intact(repl):
    repl.run("x = 5")
    r = repl.run("1/0")
    assert not r["ok"] and "ZeroDivisionError" in r["error"]
    assert repl.run("x")["output"] == "5\n"


def test_console_traceback_hides_the_harness_frame(repl):
    assert "_pyrepl_child" not in repl.run("1/0")["error"]


def test_console_incomplete_input_detection(repl):
    assert repl.is_incomplete("def f():") is True
    assert repl.is_incomplete("2 + 2") is False


def test_console_output_never_corrupts_the_protocol(repl):
    """A print that *looks* like protocol JSON is just output."""
    r = repl.run('print(\'{"ok": false}\')')
    assert r["ok"] is True
    assert r["output"] == '{"ok": false}\n'
    assert repl.run("40 + 2")["output"] == "42\n"


# --------------------------------------------------------------------------
# the preserved full-engine browser build (archive/browser-full/bridge.py,
# run here under CPython). It is off the deployed page but still in the
# repository, so it stays tested rather than quietly rotting.
# --------------------------------------------------------------------------

import json
import pathlib
import sys


@pytest.fixture(scope="module")
def bridge():
    web = str(pathlib.Path(__file__).resolve().parent.parent
              / "archive" / "browser-full")
    sys.path.insert(0, web)
    try:
        import bridge as b
        yield b
    finally:
        sys.path.remove(web)


def test_browser_python_run_matches_the_server_shape(bridge):
    r = json.loads(bridge.run_program("python", "print(int(input())*2)",
                                      stdin="21"))
    assert r["ok"] is True and r["stdout"] == "42\n" and r["exit_code"] == 0
    server = run_code("python", "print(int(input())*2)", stdin="21").as_dict()
    assert set(r) == set(server), "the two builds' run replies have drifted"


def test_browser_python_failure_carries_diagnostics(bridge):
    r = json.loads(bridge.run_program("python", "def f():\n    return 1/0\nf()"))
    assert not r["ok"]
    assert r["diagnostics"][0]["span"][0] == 2
    assert "run_program" not in r["stderr"], "harness frames leak into the trace"


def test_browser_cpp_is_an_honest_refusal_not_a_mock(bridge):
    r = json.loads(bridge.run_program("cpp", "int main(){}"))
    assert r["ok"] is False
    assert "compiler" in r["message"]
    assert r["stdout"] == "" and r["diagnostics"] == []


def test_browser_console_state_persists(bridge):
    bridge.pyrepl("", reset=True)
    bridge.pyrepl("q = 6")
    assert json.loads(bridge.pyrepl("q * 7"))["output"] == "42\n"
    bridge.pyrepl("", reset=True)
