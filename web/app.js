/* ===================================================================
 * Epsilon — three languages, one page.
 *
 * There is one buffer per language, a Run, and somewhere for the
 * program's input and output to go. That is the whole surface.
 *
 * What actually runs, and where, is decided honestly at boot:
 *
 *   · Python runs here, in this tab, on Pyodide. No server involved.
 *   · C++ and Java need a compiler, and a browser has none. If this
 *     page is being served by `epsilon serve` the Run button posts to
 *     that server, which really does invoke g++ / javac. On GitHub
 *     Pages there is no such server, so Run says exactly that instead
 *     of pretending — the editor still gives you the full language.
 *
 * Two limits worth stating rather than hiding:
 *   · Python holds the page's only thread, so a long loop freezes the
 *     tab. The UI paints "running" before handing over, so the pause is
 *     legible instead of looking like a hang.
 *   · Your code lives in this browser's localStorage. It is not synced
 *     anywhere, and clearing site data removes it.
 * =================================================================== */
(function () {
  "use strict";

  const PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/";
  const KEY_SRC = "epsilon.min.src.v1";
  const KEY_LANG = "epsilon.min.lang.v1";
  const KEY_THEME = "epsilon.min.theme.v1";
  const KEY_STDIN = "epsilon.min.stdin.v1";

  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  };

  const ORDER = ["python", "cpp", "java"];
  const SPEC = EpsilonEditor.LANGS;

  const STARTER = {
    python: `# Python runs right here in this tab.
# Press Run, or Cmd/Ctrl + Enter.

import math


def sinc(x):
    """sin(x)/x, with the removable singularity filled in."""
    return math.sin(x) / x if x else 1.0


for i in range(8):
    x = i * 0.5
    print(f"sinc({x:3.1f})  " + "#" * round(38 * abs(sinc(x))))
`,
    cpp: `// C++ needs a compiler, which a browser does not have.
// Run `+"`epsilon serve`"+` and open the page it prints, and this
// really compiles with g++. Here, it is an editor.

#include <iostream>
#include <vector>

int main() {
    std::vector<int> xs{1, 2, 3, 4, 5};
    long long total = 0;
    for (int x : xs) {
        total += 1LL * x * x;
    }
    std::cout << "sum of squares: " << total << std::endl;
    return 0;
}
`,
    java: `// Java needs a JDK, which a browser does not have.
// Run `+"`epsilon serve`"+` and open the page it prints, and this
// really compiles with javac. Here, it is an editor.

public class Main {
    static long squared(long n) {
        return n * n;
    }

    public static void main(String[] args) {
        long total = 0;
        for (int i = 1; i <= 5; i++) {
            total += squared(i);
        }
        System.out.println("sum of squares: " + total);
    }
}
`,
  };

  /* ---- storage --------------------------------------------------- */

  const read = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) { return fallback; }
  };
  const write = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); }
    catch (e) { /* private mode: this session only */ }
  };

  const stored = read(KEY_SRC, null) || {};
  const source = {};
  ORDER.forEach((id) => {
    source[id] = typeof stored[id] === "string" ? stored[id] : STARTER[id];
  });
  let lang = read(KEY_LANG, null);
  if (ORDER.indexOf(lang) === -1) lang = "python";

  /* ---- theme: follow the system until told otherwise ------------- */

  let choice = read(KEY_THEME, null);
  const systemDark = window.matchMedia
    ? matchMedia("(prefers-color-scheme: dark)")
    : { matches: false, addEventListener: null };
  const isDark = () => (choice ? choice === "dark" : systemDark.matches);

  function applyTheme() {
    if (choice) document.documentElement.setAttribute("data-theme", choice);
    else document.documentElement.removeAttribute("data-theme");
    $("theme").textContent = isDark() ? "light" : "dark";   // offers the other
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

  /* ---- editor ---------------------------------------------------- */

  let saveTimer = 0;
  const editor = EpsilonEditor.Editor({
    textarea: $("code"),
    paint: $("paint"),
    gutter: $("gutter"),
    caret: $("caret"),
    hints: $("hints"),
    language: lang,
    onChange() {
      source[lang] = editor.value;
      clearTimeout(saveTimer);
      saveTimer = setTimeout(save, 400);
    },
    onCursor(p) { $("pos").textContent = p.line + ":" + p.col; },
    onGutter(line) { editor.goToLine(line); },
  });

  function save() {
    source[lang] = editor.value;
    write(KEY_SRC, source);
    write(KEY_LANG, lang);
    write(KEY_STDIN, $("stdin").value);
  }

  /* ---- languages -------------------------------------------------- */

  function drawLangs() {
    const host = $("langs");
    host.innerHTML = "";
    ORDER.forEach((id) => {
      const b = el("button", "lang ui" + (id === lang ? " on" : ""),
                   SPEC[id].label);
      b.setAttribute("aria-pressed", String(id === lang));
      b.addEventListener("click", () => choose(id));
      host.appendChild(b);
    });
  }

  function choose(id) {
    if (id === lang) return editor.focus();
    save();
    lang = id;
    editor.setLanguage(id);
    editor.value = source[id];
    editor.markBad(0);
    write(KEY_LANG, lang);
    drawLangs();
    drawRun();
    clearOut();
    explain();
    editor.focus();
  }

  /* ---- output ---------------------------------------------------- */

  function clearOut() { $("out").innerHTML = ""; }

  function say(text, cls) {
    if (text === "") return null;
    const line = el("div", "line " + (cls || ""), text);
    $("out").appendChild(line);
    $("out").scrollTop = $("out").scrollHeight;
    return line;
  }

  /** An error, with the line that failed made clickable. */
  function sayError(text, line) {
    const box = el("div", "line bad");
    box.textContent = String(text).replace(/\n+$/, "");
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
    $("state").textContent = text;
    $("state").className = "ui quiet " + (cls || "");
  }

  const took = (ms) =>
    ms >= 1000 ? (ms / 1000).toFixed(2) + " s" : Math.round(ms) + " ms";

  /* ---- what can actually run -------------------------------------- */

  // python is answered by Pyodide in this tab; cpp and java are only
  // answered by a real compiler, which means a real server
  const can = { python: false, cpp: false, java: false };
  let server = false;

  /**
   * Is this page being served by `epsilon serve`?
   *
   * A plain same-origin GET. On GitHub Pages it 404s and we learn the
   * truth; on the local server it comes back with the languages that
   * machine can build. Nothing is assumed either way.
   */
  async function probeServer() {
    try {
      const res = await fetch("/api/run/languages", { cache: "no-store" });
      if (!res.ok) return;
      const body = await res.json();
      const langs = (body && body.languages) || {};
      server = true;
      can.cpp = !!langs.cpp;
      can.java = !!langs.java;
    } catch (e) { /* no server: that is the common case, and it is fine */ }
  }

  function drawRun() {
    const ok = can[lang];
    $("run").disabled = !ok;
    $("run").title = ok ? "" : whyNot(lang);
  }

  const NAME = { python: "Python", cpp: "C++", java: "Java" };

  function whyNot(id) {
    if (id === "python") {
      return "Python could not start, so it cannot run anything here.";
    }
    const tool = id === "cpp" ? "a C++ compiler" : "a JDK";
    if (server) return "This machine has no " + tool + " installed.";
    return NAME[id] + " needs " + (id === "cpp" ? "a compiler" : "a JDK") +
      " to run, and a browser has none — so this is an editor for it, not a " +
      "runtime. Run `epsilon serve` on your own machine and this same page " +
      "compiles and runs the file for real.";
  }

  /**
   * Say out loud what cannot happen and why.
   *
   * A greyed-out button with the reason hidden in a tooltip is the same
   * as no reason at all, and the starter comment disappears the moment
   * anyone edits the file.
   */
  function explain() {
    if (can[lang]) return state("ready", "");
    state("no " + (lang === "python" ? "python" : "compiler"), "");
    say(whyNot(lang), "why");
  }

  /* ---- Python, in this tab ---------------------------------------- */

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

  function runPythonHere() {
    try {
      py.globals.set("_src", editor.value);
      py.globals.set("_stdin", $("stdin").value || "");
      py.globals.set("_name", SPEC.python.file);
      return JSON.parse(py.runPython("_epsilon_run(_src, _stdin, _name)"));
    } catch (e) {
      return { status: "error", out: "", err: String(e), line: null, ms: 0 };
    }
  }

  /* ---- C++ and Java, on the server that is serving this page ------ */

  async function runOnServer() {
    const started = performance.now();
    try {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          language: lang, code: editor.value,
          stdin: $("stdin").value || "", filename: SPEC[lang].file,
        }),
      });
      if (!res.ok) {
        return { status: "error", out: "", ms: performance.now() - started,
                 err: "the server refused this run (" + res.status + ")",
                 line: null };
      }
      const r = await res.json();
      const first = (r.diagnostics || [])[0];
      return {
        status: r.ok ? "ok" : "error",
        out: r.stdout || "",
        err: r.stderr || r.message || "",
        line: first && first.span ? first.span[0] : null,
        ms: r.duration_ms || (performance.now() - started),
        phase: r.phase,
      };
    } catch (e) {
      return { status: "error", out: "", err: String(e), line: null,
               ms: performance.now() - started };
    }
  }

  /* ---- run --------------------------------------------------------- */

  async function run() {
    if (busy || !can[lang]) return;
    busy = true;
    save();
    clearOut();
    editor.markBad(0);
    $("run").disabled = true;
    $("rule").classList.add("busy");
    state("running", "busy");

    // paint the "running" state before handing the thread over: the
    // pause is the same length either way, but this way it is legible
    // rather than looking like the page died
    await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

    const reply = lang === "python" ? runPythonHere() : await runOnServer();

    $("rule").classList.remove("busy");
    busy = false;
    $("run").disabled = false;

    if (reply.out) say(reply.out.replace(/\n+$/, ""));
    if (reply.err) sayError(reply.err, reply.line);
    if (!reply.out && !reply.err) say("no output", "note");
    const label = reply.phase === "compile" ? "did not compile"
      : reply.status === "ok" ? "ok" : "error";
    state(label + " · " + took(reply.ms),
          reply.status === "ok" ? "ok" : "bad");
    editor.focus();
  }

  $("run").addEventListener("click", run);
  $("stdinBtn").addEventListener("click", () => {
    const wrap = $("stdinWrap");
    wrap.hidden = !wrap.hidden;
    $("stdinBtn").classList.toggle("on", !wrap.hidden);
    if (!wrap.hidden) $("stdin").focus();
    else editor.focus();
  });
  $("stdin").addEventListener("input", () => {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 400);
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

  /* ---- boot ------------------------------------------------------- */

  function step(msg, pct) {
    $("bootMsg").textContent = msg;
    $("bootBar").style.width = pct + "%";
  }

  function done() {
    $("boot").classList.add("gone");
    setTimeout(() => { const b = $("boot"); if (b) b.remove(); }, 480);
    editor.focus();
  }

  async function boot() {
    applyTheme();
    drawLangs();
    editor.value = source[lang];
    $("stdin").value = read(KEY_STDIN, "") || "";
    $("run").disabled = true;
    state("starting", "busy");

    step("looking for a compiler", 8);
    await probeServer();

    step("starting python", 30);
    try {
      await new Promise((resolve, reject) => {
        const tag = document.createElement("script");
        tag.src = PYODIDE + "pyodide.js";
        tag.onload = resolve;
        tag.onerror = () => reject(new Error("could not reach the Pyodide CDN"));
        document.head.appendChild(tag);
      });
      step("starting python", 60);
      py = await window.loadPyodide({ indexURL: PYODIDE });
      py.runPython(PREAMBLE);
      can.python = true;
      step("ready", 100);
      drawRun();
      explain();
      done();
    } catch (err) {
      // Python is the only thing that failed. If a server is here, C++
      // and Java still run, so the page is worth opening either way.
      step("python could not start", 100);
      drawRun();
      done();
      sayError("Python could not start: " +
        String((err && err.message) || err) +
        "\nThis page fetches Python once from cdn.jsdelivr.net. " +
        "If your network blocks it, the editor still works.", null);
      state("no python", "bad");
      if (lang !== "python" && !can[lang]) say(whyNot(lang), "why");
    }
  }

  window.Epsilon = {
    run, save, choose,
    get source() { return source; },
    get language() { return lang; },
    get capabilities() { return Object.assign({ server }, can); },
  };
  boot();
})();
