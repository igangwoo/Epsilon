/* ===================================================================
 * Epsilon — a Python workbench that runs in the browser.
 *
 * Pyodide and nothing else. No wheel, no bridge, no server: the page
 * loads a Python, hands it your file, and shows what came back. That is
 * the whole product surface, and keeping it that small is what makes it
 * start in seconds and stay out of the way.
 *
 * Two honest limits, stated rather than hidden:
 *   · Python runs on the page's only thread, so a long loop freezes the
 *     tab. The UI paints "running" before handing over, so the pause is
 *     legible instead of looking like a hang.
 *   · Files live in this browser's localStorage. They are not synced
 *     anywhere and clearing site data removes them.
 * =================================================================== */
(function () {
  "use strict";

  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
  const KEY_FILES = "epsilon.lite.files.v1";
  const KEY_OPEN = "epsilon.lite.open.v1";
  const KEY_THEME = "epsilon.lite.theme.v1";
  const KEY_LIG = "epsilon.lite.ligatures.v1";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const WELCOME = `"""Epsilon — Python, in your browser.

Press Run (or Ctrl/Cmd + Enter). Everything below runs here; there is
no server, and your files stay in this browser.
"""

import math


def sinc(x):
    """sin(x)/x, with the removable singularity filled in."""
    return math.sin(x) / x if x else 1.0


for i in range(8):
    x = i * 0.5
    print(f"sinc({x:3.1f})  " + "#" * round(38 * abs(sinc(x))))
`;

  /* ---- storage: a plain {path: text} map ------------------------- */

  const read = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); }
    catch (e) { /* private mode: this session only */ }
  };

  let files = read(KEY_FILES, null);
  if (!files || !Object.keys(files).length) files = { "main.py": WELCOME };
  let open = read(KEY_OPEN, null);
  if (!open || !(open in files)) open = Object.keys(files)[0];

  /* ---- theme: follow the system until told otherwise ------------- */

  let choice = read(KEY_THEME, null);
  const systemDark = window.matchMedia
    ? matchMedia("(prefers-color-scheme: dark)")
    : { matches: false, addEventListener: null };
  const isDark = () => (choice ? choice === "dark" : systemDark.matches);

  function applyTheme() {
    if (choice) document.documentElement.setAttribute("data-theme", choice);
    else document.documentElement.removeAttribute("data-theme");
    $("theme").textContent = isDark() ? "light" : "dark";  // offers the other
    if (editor) editor.refresh();
  }
  $("theme").addEventListener("click", () => {
    choice = isDark() ? "light" : "dark";
    write(KEY_THEME, choice);
    applyTheme();
  });
  if (systemDark.addEventListener) {
    systemDark.addEventListener("change", applyTheme);
  }

  /* ---- ligatures: a rendering choice, remembered ------------------ */

  let ligatures = read(KEY_LIG, true);

  function drawLigButton() {
    const b = $("lig");
    b.setAttribute("aria-pressed", String(ligatures));
    b.style.color = ligatures ? "var(--accent)" : "";
  }

  $("lig").addEventListener("click", () => {
    ligatures = !ligatures;
    write(KEY_LIG, ligatures);
    drawLigButton();
    editor.repaint();
    editor.focus();
  });

  /* ---- editor ---------------------------------------------------- */

  let editor = null;
  let dirty = false;

  editor = EpsilonEditor.Editor({
    textarea: $("code"),
    paint: $("paint"),
    gutter: $("gutter"),
    caret: $("caret"),
    hints: $("hints"),
    ligatures: () => ligatures,
    onChange() {
      files[open] = editor.value;
      if (!dirty) { dirty = true; drawTabs(); }
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, 400);
    },
    onCursor(p) {
      $("mPos").textContent = "Ln " + p.line + ", Col " + p.col;
    },
    onGutter(line) { editor.goToLine(line); },
  });

  let saveTimer = 0;
  function save() {
    files[open] = editor.value;
    write(KEY_FILES, files);
    write(KEY_OPEN, open);
    if (dirty) { dirty = false; drawTabs(); }
  }

  /* ---- files ----------------------------------------------------- */

  function drawTabs() {
    const host = $("files");
    host.innerHTML = "";
    Object.keys(files).forEach((path) => {
      const tab = el("button", "tab" + (path === open ? " on" : "") +
        (path === open && dirty ? " dirty" : ""), path);
      tab.addEventListener("click", () => openFile(path));
      tab.addEventListener("auxclick", (ev) => {
        if (ev.button === 1) { ev.preventDefault(); removeFile(path); }
      });
      tab.addEventListener("contextmenu", (ev) => {
        ev.preventDefault();
        removeFile(path);
      });
      tab.title = path + " — middle-click or right-click to delete";
      host.appendChild(tab);
    });
  }

  function openFile(path) {
    if (!(path in files) || path === open) return;
    save();
    open = path;
    editor.value = files[path];
    write(KEY_OPEN, open);
    drawTabs();
    editor.focus();
  }

  function removeFile(path) {
    if (Object.keys(files).length === 1) {
      return say("That is the only file — Epsilon keeps at least one.", "note");
    }
    if (!confirm("Delete " + path + "? This browser has the only copy.")) return;
    delete files[path];
    if (open === path) open = Object.keys(files)[0];
    editor.value = files[open];
    save();
    drawTabs();
  }

  $("newFile").addEventListener("click", () => {
    let name = prompt("New file", "untitled.py");
    if (!name) return;
    name = name.trim();
    if (!name.endsWith(".py")) name += ".py";
    if (name in files) return openFile(name);
    files[name] = "";
    open = name;
    editor.value = "";
    save();
    drawTabs();
    editor.focus();
  });

  /* ---- output ---------------------------------------------------- */

  function clearOut() { $("out").innerHTML = ""; }

  function say(text, cls) {
    if (text === "") return;
    const line = el("div", "line " + (cls || ""), text);
    $("out").appendChild(line);
    $("out").scrollTop = $("out").scrollHeight;
    return line;
  }

  /** A traceback, with the line that failed made clickable. */
  function sayError(text, line) {
    const box = el("div", "line bad");
    box.textContent = text.replace(/\n+$/, "");
    $("out").appendChild(box);
    if (line) {
      const jump = el("div", "line");
      const link = el("span", "jump", "go to line " + line);
      link.addEventListener("click", () => editor.goToLine(line));
      jump.appendChild(link);
      $("out").appendChild(jump);
      editor.markBad(line);
    }
    $("out").scrollTop = $("out").scrollHeight;
  }

  function state(text, cls) {
    const node = $("mState");
    node.textContent = text;
    node.className = cls || "";
  }

  /* ---- the runtime ----------------------------------------------- */

  let py = null;
  let busy = false;

  // One preamble, installed once. Running a file is then a single call
  // with no string building at the JS end — and the traceback is
  // trimmed to the user's own frames, because Epsilon's plumbing is not
  // part of their bug.
  const PREAMBLE = `
import io, sys, time, traceback, json

def _epsilon_run(src, stdin_text, filename="main.py"):
    out, err = io.StringIO(), io.StringIO()
    keep = sys.stdout, sys.stderr, sys.stdin
    sys.stdout, sys.stderr, sys.stdin = out, err, io.StringIO(stdin_text)
    ns = {"__name__": "__main__", "__file__": filename}
    started = time.perf_counter()
    status, line = "ok", None
    try:
        exec(compile(src, filename, "exec"), ns)
    except SyntaxError as e:
        status, line = "error", e.lineno
        err.write("".join(traceback.format_exception_only(type(e), e)))
    except SystemExit as e:
        if e.code not in (0, None):
            status = "error"
            err.write(f"SystemExit: {e.code}\\n")
    except BaseException as e:
        status = "error"
        tb = e.__traceback__
        while tb:
            if tb.tb_frame.f_code.co_filename == filename:
                line = tb.tb_lineno
            tb = tb.tb_next
        err.write("".join(traceback.format_exception(
            type(e), e, e.__traceback__.tb_next)))
    finally:
        sys.stdout, sys.stderr, sys.stdin = keep
    return json.dumps({"status": status, "out": out.getvalue(),
                       "err": err.getvalue(), "line": line,
                       "ms": round((time.perf_counter() - started) * 1000)})
`;

  async function run() {
    if (busy || !py) return;
    busy = true;
    save();
    clearOut();
    editor.markBad(0);
    $("run").disabled = true;
    $("rule").classList.add("busy");
    state("running", "busy");

    // paint the "running" state before handing the thread to Python:
    // the pause is the same length either way, but this way it is
    // legible rather than looking like the page died
    await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

    let reply;
    try {
      py.globals.set("_src", editor.value);
      py.globals.set("_stdin", $("stdin").value || "");
      py.globals.set("_name", open);
      reply = JSON.parse(py.runPython("_epsilon_run(_src, _stdin, _name)"));
    } catch (e) {
      reply = { status: "error", out: "", err: String(e), line: null, ms: 0 };
    }

    $("rule").classList.remove("busy");
    $("run").disabled = false;
    busy = false;

    if (reply.out) say(reply.out.replace(/\n+$/, ""));
    if (reply.err) sayError(reply.err, reply.line);
    if (!reply.out && !reply.err) say("no output", "note");
    const seconds = reply.ms >= 1000 ? (reply.ms / 1000).toFixed(2) + " s"
                                     : reply.ms + " ms";
    state(reply.status === "ok" ? "ok · " + seconds : "error · " + seconds,
          reply.status === "ok" ? "ok" : "bad");
    editor.focus();
  }

  $("run").addEventListener("click", run);
  $("stdinToggle").addEventListener("click", () => {
    const row = $("stdinRow");
    row.hidden = !row.hidden;
    if (!row.hidden) $("stdin").focus();
  });

  window.addEventListener("keydown", (ev) => {
    if ((ev.metaKey || ev.ctrlKey) && ev.key === "Enter") {
      ev.preventDefault();
      run();
    }
    if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === "s") {
      ev.preventDefault();
      save();
      state("saved", "");
    }
  });

  // the window can lose focus with no visible sign; say so
  const focusState = () =>
    document.body.classList.toggle("away", !document.hasFocus());
  window.addEventListener("blur", focusState);
  window.addEventListener("focus", focusState);

  window.addEventListener("beforeunload", (ev) => {
    save();
    if (busy) { ev.preventDefault(); ev.returnValue = ""; }
  });

  /* ---- boot ------------------------------------------------------ */

  function step(msg, pct) {
    $("bootMsg").textContent = msg;
    $("bootBar").style.width = pct + "%";
  }

  function bootFailed(err, hint) {
    $("bootMsg").textContent = "Could not start.";
    $("bootHint").innerHTML = "";
    $("bootHint").appendChild(el("div", "", String((err && err.message) || err)));
    if (hint) $("bootHint").appendChild(el("div", "", hint));
    state("offline", "bad");
  }

  async function boot() {
    applyTheme();
    drawLigButton();
    drawTabs();
    editor.value = files[open];
    $("run").disabled = true;
    state("loading python", "busy");

    try {
      step("Fetching Python…", 12);
      $("bootHint").textContent =
        "The first visit downloads Python (about 10 MB) and caches it.";
      await new Promise((resolve, reject) => {
        const tag = document.createElement("script");
        tag.src = PYODIDE + "pyodide.js";
        tag.onload = resolve;
        tag.onerror = () => reject(new Error("could not reach the Pyodide CDN"));
        document.head.appendChild(tag);
      });

      step("Starting Python…", 55);
      py = await window.loadPyodide({ indexURL: PYODIDE });

      step("Ready.", 100);
      py.runPython(PREAMBLE);
      $("bootHint").textContent = "";
      $("run").disabled = false;
      state("ready", "");
      $("boot").classList.add("gone");
      setTimeout(() => $("boot").remove(), 500);
      editor.focus();
    } catch (err) {
      bootFailed(err, "This page needs one-time access to cdn.jsdelivr.net. " +
        "If your network blocks it, try another connection.");
    }
  }

  window.Epsilon = { run, save, openFile, get files() { return files; } };
  boot();
})();
