"""The editor's text operations (editor.js EditorOps) — pure functions,
tested under node exactly as they run in the page.

These are the behaviours that make an editor an editor rather than a text
field: language-aware indentation, block indent/dedent, comment toggling,
line moves, bracket matching, smart Home.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
EDITOR = ROOT / "epsilon" / "server" / "static" / "editor.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

PY_OPTS = {"language": "python", "tabSize": 4, "insertSpaces": True}
CPP_OPTS = {"language": "cpp", "tabSize": 4, "insertSpaces": True}


def op(name, *args):
    src = (f"const {{ EditorOps }} = require({str(EDITOR)!r});\n"
           f"console.log(JSON.stringify("
           f"EditorOps.{name}(...{json.dumps(list(args))}) ?? null));")
    r = subprocess.run([NODE, "-e", src], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# automatic indentation
# --------------------------------------------------------------------------

def test_enter_inherits_indentation():
    text = "def f():\n    x = 1"
    r = op("newlineIndent", text, len(text), PY_OPTS)
    assert r["insert"] == "\n    "


def test_enter_after_a_colon_indents_one_more_level():
    text = "if cond:"
    r = op("newlineIndent", text, len(text), PY_OPTS)
    assert r["insert"] == "\n    "


def test_enter_between_braces_pushes_the_closer_down():
    text = "int main() {}"
    r = op("newlineIndent", text, len(text) - 1, CPP_OPTS)
    assert r["insert"] == "\n    "
    assert r["after"] == "\n"


def test_enter_in_the_middle_of_plain_text_keeps_indent_only():
    text = "    value = compute()"
    r = op("newlineIndent", text, len(text), PY_OPTS)
    assert r == {"insert": "\n    ", "after": ""}


# --------------------------------------------------------------------------
# block indent / dedent
# --------------------------------------------------------------------------

def test_indent_block_touches_every_selected_line():
    text = "a\nb\nc"
    r = op("indentBlock", text, 0, len(text), PY_OPTS)
    assert r["text"] == "    a\n    b\n    c"


def test_dedent_block_removes_up_to_one_unit():
    text = "    a\n  b\nc"
    r = op("dedentBlock", text, 0, len(text), PY_OPTS)
    assert r["text"] == "a\nb\nc"


def test_indent_skips_empty_lines():
    r = op("indentBlock", "a\n\nb", 0, 4, PY_OPTS)
    assert r["text"] == "    a\n\n    b"


# --------------------------------------------------------------------------
# comments
# --------------------------------------------------------------------------

def test_toggle_comment_python_round_trip():
    text = "x = 1\ny = 2"
    on = op("toggleComment", text, 0, len(text), PY_OPTS)
    assert on["text"] == "# x = 1\n# y = 2"
    off = op("toggleComment", on["text"], 0, len(on["text"]), PY_OPTS)
    assert off["text"] == text


def test_toggle_comment_cpp_uses_slashes():
    r = op("toggleComment", "int x;", 0, 6, CPP_OPTS)
    assert r["text"] == "// int x;"


def test_toggle_comment_preserves_indentation():
    r = op("toggleComment", "    call()", 4, 4, PY_OPTS)
    assert r["text"] == "    # call()"


def test_toggle_comment_mixed_block_comments_everything():
    text = "# a\nb"
    r = op("toggleComment", text, 0, len(text), PY_OPTS)
    assert r["text"] == "# # a\n# b"


# --------------------------------------------------------------------------
# line operations
# --------------------------------------------------------------------------

def test_move_lines_down_and_up_are_inverse():
    text = "one\ntwo\nthree"
    down = op("moveLines", text, 0, 0, 1)
    assert down["text"] == "two\none\nthree"
    up = op("moveLines", down["text"], down["selStart"], down["selEnd"], -1)
    assert up["text"] == text


def test_move_first_line_up_is_a_no_op():
    assert op("moveLines", "a\nb", 0, 0, -1) is None


def test_duplicate_and_delete_lines():
    dup = op("duplicateLines", "a\nb", 0, 0)
    assert dup["text"] == "a\na\nb"
    cut = op("deleteLines", "a\nb\nc", 2, 2)
    assert cut["text"] == "a\nc"


def test_delete_the_last_line_takes_its_newline_with_it():
    assert op("deleteLines", "a\nb", 2, 2)["text"] == "a"


# --------------------------------------------------------------------------
# brackets, words, home
# --------------------------------------------------------------------------

def test_bracket_matching_nests():
    text = "f(g(x), y)"
    assert op("matchBracket", text, 1) == [1, 9]
    assert op("matchBracket", text, 4) == [3, 5]
    assert op("matchBracket", "no brackets", 3) is None


def test_smart_home_toggles_between_indent_and_column_zero():
    text = "    value"
    assert op("smartHome", text, 9) == 4
    assert op("smartHome", text, 4) == 0
    assert op("smartHome", text, 0) == 4


def test_word_at_and_next_occurrence():
    text = "total = total + 1"
    assert op("wordAt", text, 2) == [0, 5]
    assert op("nextOccurrence", text, 0, 5) == [8, 13]
    # wraps around from the last occurrence back to the first
    assert op("nextOccurrence", text, 8, 13) == [0, 5]
