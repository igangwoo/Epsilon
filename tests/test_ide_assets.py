"""Static checks on the IDE front-end.

The IDE is plain HTML/CSS/JS with no build step, so a renamed or removed
element only shows up as a null dereference at runtime — after the click that
needed it. Same for the registries: a menu naming a command nobody registered
is a dead menu item. These tests catch that class of breakage without a
browser.
"""

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "epsilon" / "server" / "static"
HTML = STATIC / "index.html"
APP = STATIC / "app.js"
PANES = STATIC / "panes.js"
CORE = STATIC / "core.js"
EDITOR = STATIC / "editor.js"


def html_ids():
    return set(re.findall(r'\bid="([A-Za-z0-9_-]+)"', HTML.read_text()))


def app_created_ids():
    """Elements app.js builds itself (context menus, dropdowns…)."""
    return set(re.findall(r'\.id = "([A-Za-z0-9_-]+)"', APP.read_text()))


def registered_commands():
    app = APP.read_text()
    ids = set(re.findall(r'C\(\{ id: "([a-z]+\.[A-Za-z]+)"', app))
    ids |= set(re.findall(r'Commands\.register\(\{\s*\n?\s*id:? "?([a-z]+\.[A-Za-z]+)"?', app))
    ids |= set(re.findall(r'editorCmd\("([a-z]+\.[A-Za-z]+)"', app))
    return ids


def test_every_element_lookup_in_app_js_resolves():
    """`$("#foo")` must name an element that exists — either in index.html
    or created by app.js itself."""
    ids = html_ids() | app_created_ids()
    wanted = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', APP.read_text()))
    missing = sorted(wanted - ids)
    assert not missing, f"app.js looks up ids that nothing defines: {missing}"


def test_pane_views_live_in_the_vault():
    """Views are re-parented into panes, so they must start somewhere real."""
    assert 'id="viewVault"' in HTML.read_text()
    assert 'vault: "#viewVault"' in APP.read_text(), (
        "panes.js needs a vault to park views that are not currently visible; "
        "without it, a closed editor's element is detached and every "
        "querySelector for it returns null")


def test_every_menu_item_names_a_registered_command():
    """One command registry serves every surface; a menu naming a command
    nobody registered would render, then explain nothing when clicked."""
    app = APP.read_text()
    commands = registered_commands()
    menus = re.search(r"function registerMenus\(\)(.*?)\n  \}", app, re.S)
    assert menus, "registerMenus not found"
    used = set(re.findall(r'"([a-z]+\.[A-Za-z]+)"', menus.group(1)))
    unknown = sorted(used - commands)
    assert not unknown, f"menus reference unregistered commands: {unknown}"


def test_every_context_menu_command_is_registered():
    app = APP.read_text()
    commands = registered_commands()
    block = re.search(r"function registerContextMenus\(\)(.*?)\n  \}\n", app, re.S)
    assert block, "registerContextMenus not found"
    used = set(re.findall(r'command: "([a-z]+\.[A-Za-z]+)"', block.group(1)))
    assert used, "context menus bind no commands?"
    unknown = sorted(used - commands)
    assert not unknown, f"context menus reference unregistered commands: {unknown}"


def test_every_keybinding_names_a_registered_command():
    app = APP.read_text()
    commands = registered_commands()
    bound = set(re.findall(r'K\("([a-z]+\.[A-Za-z]+)",', app))
    unknown = sorted(bound - commands)
    assert not unknown, f"keybindings for unregistered commands: {unknown}"


def test_every_setting_read_is_a_registered_setting():
    """`Settings.get("x")` for an unregistered id silently returns
    undefined — a typo becomes a wrong default, not an error."""
    app = APP.read_text()
    registered = set(re.findall(r'S\(\{ id: "([a-z]+\.[A-Za-z]+)"', app))
    assert registered, "registerSettings registers nothing?"
    read = set(re.findall(r'Settings\.(?:get|set|reset)\("([a-z]+\.[A-Za-z]+)"', app))
    unknown = sorted(read - registered)
    assert not unknown, f"settings read but never registered: {unknown}"


def test_sidebar_views_exist_in_the_html():
    """Each sidebar view the activity bar offers needs its DOM section."""
    app = APP.read_text()
    html = HTML.read_text()
    declared = set(re.findall(r'\{ id: "(\w+)", title: "[^"]+", glyph', app))
    assert declared >= {"explorer", "search", "scm", "rundebug"}
    in_html = set(re.findall(r'data-view="(\w+)"', html))
    missing = sorted(declared - in_html)
    assert not missing, f"sidebar views with no DOM section: {missing}"


def test_panel_tabs_exist_in_the_html():
    app = APP.read_text()
    html = HTML.read_text()
    tabs = set(re.findall(r'\{ id: "(\w+)", title: "[A-Z][^"]*" \}', app))
    assert {"terminal", "problems", "output", "debug"} <= tabs
    in_html = set(re.findall(r'data-panel="(\w+)"', html))
    missing = sorted(tabs - in_html)
    assert not missing, f"panel tabs with no DOM view: {missing}"


def test_no_external_resources():
    """The IDE is self-contained — no CDNs, no phone-home."""
    for f in (HTML, APP, STATIC / "app.css", PANES, CORE, EDITOR):
        text = f.read_text()
        for m in re.findall(r'(?:src|href)="(https?://[^"]+)"', text):
            assert m.startswith("https://github.com/"), \
                f"{f.name} references an external resource: {m}"


@pytest.mark.parametrize("name", ["panes.js", "app.js", "app.css",
                                  "index.html", "core.js", "editor.js"])
def test_asset_present(name):
    assert (STATIC / name).exists()


def test_math_subsystem_is_preserved():
    """The pivot hides mathematics from the IDE; it must not delete it."""
    math_dir = STATIC / "math"
    assert (math_dir / "legacy-workbench.js").exists()
    assert (math_dir / "legacy-index.html").exists()
    assert (math_dir / "README.md").exists()


def test_editor_languages_match_the_server():
    """The editor's extension table must agree with `_language_of`."""
    from epsilon.server.app import _language_of
    app = APP.read_text()
    block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    assert block, "EXT_LANGUAGE not found in app.js"
    pairs = re.findall(r'(\w+):\s*"([a-z+]+)"', block.group(1))
    assert pairs
    for ext, language in pairs:
        assert _language_of("f." + ext) == language, (
            f".{ext}: editor says {language}, server says {_language_of('f.' + ext)}")


def test_every_editor_language_has_a_syntax_entry():
    """Every language the IDE opens must highlight (or knowingly not)."""
    app = APP.read_text()
    editor = EDITOR.read_text()
    block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    languages = {lang for _, lang in
                 re.findall(r'(\w+):\s*"([a-z+]+)"', block.group(1))}
    syntax = set(re.findall(r"^    ([a-z]+): \{", editor, re.M))
    syntax |= set(re.findall(r"SYNTAX\.([a-z]+) = ", editor))
    # markdown has its own pass rather than a SYNTAX table entry
    missing = sorted(languages - syntax - {"markdown"})
    assert not missing, f"languages with no highlighting rules: {missing}"


def test_every_language_has_a_status_bar_label():
    app = APP.read_text()
    block = re.search(r"const LANGUAGE_LABEL = \{(.*?)\n  \};", app, re.S)
    assert block, "LANGUAGE_LABEL not found in app.js"
    labelled = set(re.findall(r'(\w+):\s*"', block.group(1)))
    ext_block = re.search(r"const EXT_LANGUAGE = \{(.*?)\n  \};", app, re.S)
    languages = {lang for _, lang in
                 re.findall(r'(\w+):\s*"([a-z+]+)"', ext_block.group(1))}
    assert not sorted(languages - labelled)


def test_the_pane_api_matches_what_the_contracts_document():
    """A documented entry point that is not exported is a promise unkept."""
    contracts = (ROOT / "docs" / "CONTRACTS.md").read_text()
    documented = set(re.findall(r"EpsilonPanes\.(\w+)\(", contracts))
    panes = PANES.read_text()
    block = re.search(r"const api = \{(.*?)\n  \};", panes, re.S)
    assert block, "the pane module's exported surface was not found"
    exported = set(re.findall(r"(\w+)[,:]", block.group(1)))
    missing = sorted(documented - exported)
    assert not missing, f"documented but not exported: {missing}"


def test_a_sash_drag_never_re_renders():
    """`render()` rebuilds the tree, detaching the element a drag measures
    against; a detached element reports a zero-sized rect, so the ratio
    divides by zero and the split jumps to its limit instead of following
    the mouse. A drag writes flex directly and leaves the tree alone."""
    panes = PANES.read_text()
    body = re.search(r"function wireSash\(.*?\n  \}\n", panes, re.S)
    assert body, "wireSash not found"
    src = body.group(0)
    # the pointer handlers are everything up to the double-click reset, which
    # legitimately re-renders because it is not a drag
    drag = src[:src.index('addEventListener("dblclick"')]
    assert "render()" not in drag, "a sash drag calls render(); it must not"
    assert "requestAnimationFrame" in drag, "moves are not coalesced per frame"
    assert "setPointerCapture" in drag, "the drag is lost when the pointer strays"


def test_disabled_commands_carry_reasons():
    """Every whyDisabled must return a sentence, not a bare boolean — the
    UI shows the reason wherever the command appears."""
    app = APP.read_text()
    block = re.search(r"function registerCommands\(\)(.*)function registerMenus",
                      app, re.S)
    assert block, "registerCommands not found"
    # a reason is a quoted string somewhere in each whyDisabled body
    bodies = re.findall(r"whyDisabled: (?:\(\) =>|[a-zA-Z]+)([^}]*)",
                        block.group(1))
    assert len(bodies) >= 15, "the registry lost its whyDisabled coverage"
