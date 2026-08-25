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
GRAPH = STATIC / "graph.js"


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
    for f in (HTML, APP, STATIC / "app.css", PANES, CORE, EDITOR, GRAPH):
        text = f.read_text()
        for m in re.findall(r'(?:src|href)="(https?://[^"]+)"', text):
            assert m.startswith("https://github.com/"), \
                f"{f.name} references an external resource: {m}"


@pytest.mark.parametrize("name", ["panes.js", "app.js", "app.css",
                                  "index.html", "core.js", "editor.js",
                                  "graph.js"])
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

def strip_comments(js):
    """Comments discuss what the code avoids; only the code is evidence."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$|(?<=\s)//[^\n]*", "", js, flags=re.M)


def test_the_graph_layout_is_deterministic():
    """The same file must draw the same picture every time it is opened;
    a layout seeded by chance makes the view useless as a reference."""
    graph = strip_comments(GRAPH.read_text())
    assert "Math.random" not in graph, (
        "the graph layout must not be seeded randomly")
    assert "Date.now" not in graph


def test_motion_waits_for_the_first_layout():
    """A workbench that animates itself into place on load reads as slow."""
    css = (STATIC / "app.css").read_text()
    assert ".wb-ready" in css
    assert "wb-ready" in APP.read_text()


def test_the_editor_does_not_repaint_the_whole_file_to_move_the_caret():
    """Re-tokenising and re-parsing the document on every cursor move is
    what the typing lag was; the passes must stay separable."""
    editor = EDITOR.read_text()
    assert "const TEXT = 1" in editor and "CURSOR = 4" in editor
    assert "render(CURSOR)" in editor, (
        "caret movement must request the cursor pass, not a full repaint")
    assert "requestAnimationFrame" in editor, "paints must be coalesced"


def test_panels_do_not_re_blur_the_backdrop():
    """backdrop-filter on the full-size panels made the browser re-blur
    five regions on every repaint — ten times the cost of typing."""
    css = (STATIC / "app.css").read_text()
    block = re.search(r"\.wb-activitybar, \.wb-sidebar.*?\n\}", css, re.S)
    assert block, "the shared panel rule was not found"
    assert "backdrop-filter" not in block.group(0)

def editor_methods():
    return set(re.findall(r"^    (?:async )?([A-Za-z_]\w*)\(",
                          EDITOR.read_text(), re.M))


def test_every_editor_method_the_workbench_calls_exists():
    """`entry.editor.setDiagnostics(...)` for a method that is not there
    throws only when that path runs — often long after the edit that
    removed it. Check the whole surface statically."""
    app = APP.read_text()
    called = set(re.findall(r"\.editor\.([A-Za-z_]\w*)\(", app))
    called |= set(re.findall(r"\bed\.([A-Za-z_]\w*)\(", app))
    known = editor_methods() | {"constructor"}
    missing = sorted(called - known)
    assert not missing, f"app.js calls editor methods that do not exist: {missing}"


def test_the_caret_is_not_animated_by_a_css_transition():
    """A transition restarts from zero velocity on every keystroke, which
    is what makes a caret read as steppy while typing. The glide loop in
    editor.js keeps its velocity across retargets instead."""
    css = (STATIC / "app.css").read_text()
    block = re.search(r"\.ed-caret \{(.*?)\}", css, re.S)
    assert block, ".ed-caret rule not found"
    assert "transition" not in block.group(1)
    editor = EDITOR.read_text()
    assert "_glide()" in editor
    # frame-rate independence: the easing is raised to dt/16.667
    assert "Math.pow(1 - EASE_X" in editor
    # and it must stop once it has arrived
    assert "this._caretRaf = 0;" in editor


def test_the_caret_blink_cannot_fight_its_own_motion():
    """Position is written to the wrapper every frame; the blink lives on
    the bar inside it. One element would mean both writing `transform`."""
    css = (STATIC / "app.css").read_text()
    assert ".ed-caret-bar" in css
    for blink in ("caret-hard", "caret-soft", "caret-grow"):
        assert f".ed-caret-bar {{ animation: {blink}" in css or \
               f'.ed-caret-bar {{ animation: {blink}' in css, blink

def test_the_language_service_is_not_asked_on_every_keystroke():
    """A language service on the keystroke path froze the page for 527ms
    on the worst key when the runtime shared the UI thread. The local
    half stays instant; only the round trip waits for a pause.

    (The deployed build now runs no language service at all — see
    `tests/test_lite_web.py`. This guards the local server workbench,
    where the call is cheap but still worth not making per key.)"""
    editor = EDITOR.read_text()
    assert "SEMANTIC_DELAY" in editor
    assert "_semanticCompletion" in editor, (
        "the instant and the round-trip halves must be separable")
    block = re.search(r"openCompletion\(explicit\) \{(.*?)\n    \}",
                      editor, re.S)
    assert block, "openCompletion not found"
    body = block.group(1)
    assert "setTimeout(ask, SEMANTIC_DELAY)" in body
    assert "_localCompletions" in body      # the instant half still runs


def test_the_status_bar_is_patched_not_rebuilt_while_typing():
    """The caret moves far more often than anything else on that bar."""
    app = APP.read_text()
    assert "updateCursorStatus" in app
    assert ("onCursor: () => { if (path === state.active) "
            "updateCursorStatus(); }") in app

