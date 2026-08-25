"""The workbench core (core.js) — the registries every surface speaks
through. One command registration must serve the palette, menus, keyboard
and buttons alike, and a disabled command must be able to say why.

Driven under node; skipped where node is unavailable.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORE = ROOT / "epsilon" / "server" / "static" / "core.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run_js(body: str) -> dict:
    src = (f"const core = require({str(CORE)!r});\n"
           f"const out = (() => {{ {body} }})();\n"
           f"console.log(JSON.stringify(out));")
    r = subprocess.run([NODE, "-e", src], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def test_one_registration_serves_every_surface():
    out = run_js("""
      core.Commands.register({id: 'a.b', title: 'Do Thing', category: 'Test',
                              run: () => 42});
      core.Keys.registerDefault('a.b', 'Mod+K');
      return {
        exec: core.Commands.execute('a.b'),
        byKey: core.Keys.resolve(core.Keys.normalize('Ctrl+K')),
        title: core.Commands.get('a.b').title,
        chord: core.Keys.chordOf('a.b'),
      };
    """)
    assert out["exec"] == {"ok": True, "value": 42}
    assert out["byKey"] == "a.b"
    assert out["title"] == "Do Thing"
    assert out["chord"] in ("Ctrl+K", "Meta+K")


def test_a_disabled_command_explains_itself():
    out = run_js("""
      core.Commands.register({id: 'x', title: 'X', run: () => 1,
        whyDisabled: () => 'debugging needs the server build'});
      return core.Commands.execute('x');
    """)
    assert out == {"ok": False, "reason": "debugging needs the server build"}


def test_executing_an_unknown_command_reports_not_throws():
    out = run_js("return core.Commands.execute('no.such');")
    assert out["ok"] is False and "unknown" in out["reason"]


# --------------------------------------------------------------------------
# keybindings
# --------------------------------------------------------------------------

def test_chords_normalise_to_one_spelling():
    out = run_js("""
      return [core.Keys.normalize('shift+ctrl+p'),
              core.Keys.normalize('Ctrl+Shift+p'),
              core.Keys.normalize('F5'),
              core.Keys.normalize('alt+ArrowUp')];
    """)
    assert out[0] == out[1] == "Ctrl+Shift+P"
    assert out[2] == "F5"
    assert out[3] == "Alt+ArrowUp"


def test_a_user_rebinding_shadows_the_default_completely():
    out = run_js("""
      core.Commands.register({id: 'c', title: 'C', run: () => 1});
      core.Keys.registerDefault('c', 'Ctrl+J');
      core.Keys.setUser('c', 'F9');
      return {newKey: core.Keys.resolve('F9'),
              oldKey: core.Keys.resolve('Ctrl+J'),
              marked: core.Keys.isUser('c')};
    """)
    assert out == {"newKey": "c", "oldKey": None, "marked": True}


def test_unbinding_and_reset():
    out = run_js("""
      core.Keys.registerDefault('c', 'Ctrl+J');
      core.Keys.setUser('c', null);                 // explicitly unbound
      const unbound = core.Keys.resolve('Ctrl+J');
      core.Keys.resetUser('c');
      return {unbound, restored: core.Keys.resolve('Ctrl+J')};
    """)
    assert out == {"unbound": None, "restored": "c"}


# --------------------------------------------------------------------------
# settings
# --------------------------------------------------------------------------

def test_settings_validate_clamp_and_notify():
    out = run_js("""
      core.Settings.register({id: 's.n', title: 'N', category: 'Editor',
                              type: 'number', default: 4, min: 1, max: 8});
      core.Settings.register({id: 's.e', title: 'E', category: 'Editor',
                              type: 'enum', default: 'a', options: ['a','b']});
      const seen = [];
      core.Settings.onChange('s.n', (v) => seen.push(v));
      core.Settings.set('s.n', 99);
      core.Settings.set('s.e', 'nope');            // invalid: ignored
      return {n: core.Settings.get('s.n'), e: core.Settings.get('s.e'),
              seen, modified: core.Settings.isModified('s.n')};
    """)
    assert out == {"n": 8, "e": "a", "seen": [8], "modified": True}


# --------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------

def test_diagnostics_merge_owners_per_file():
    out = run_js("""
      core.Diagnostics.set('check', 'a.py',
        [{severity: 'error', message: 'x', span: [1,1,1,1]}]);
      core.Diagnostics.set('run', 'a.py',
        [{severity: 'warning', message: 'y', span: [2,1,2,1]}]);
      core.Diagnostics.clear('run');
      return {forA: core.Diagnostics.forPath('a.py').length,
              count: core.Diagnostics.count()};
    """)
    assert out == {"forA": 1, "count": {"errors": 1, "warnings": 0}}


# --------------------------------------------------------------------------
# fuzzy
# --------------------------------------------------------------------------

def test_fuzzy_prefers_word_starts_and_rejects_non_subsequences():
    out = run_js("""
      const strong = core.fuzzy('rpf', 'Run Python File');
      const weak = core.fuzzy('rpf', 'wrap fn');
      return {ordered: strong.score > weak.score,
              positions: strong.positions,
              miss: core.fuzzy('zzz', 'Run Python File')};
    """)
    assert out["ordered"] is True
    assert out["positions"] == [0, 4, 11]
    assert out["miss"] is None
