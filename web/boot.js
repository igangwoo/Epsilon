/* ===================================================================
 * Epsilon — in-browser boot.
 * Loads Pyodide, installs the Epsilon wheel, wires a fetch shim that
 * routes /api/* to the Python engine (bridge.py) and a localStorage-backed
 * virtual filesystem, then loads the (unmodified) IDE app.js.
 * No server. Everything runs in the browser.
 * =================================================================== */
(function () {
  "use strict";

  const PYODIDE_VERSION = "0.26.2";
  const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
  const WHEEL = "./epsilon_math-0.1.0-py3-none-any.whl";
  //!BUILD_ID — stamped by scripts/build_web.py from the asset contents,
  // so a fresh page can never pick up a stale cached script
  const BUILD_ID = "ec8ee5ed13b5";
  const CACHE_BUST = "?v=" + BUILD_ID;

  const realFetch = window.fetch.bind(window);
  const boot = document.getElementById("boot");
  const bootMsg = document.getElementById("bootMsg");
  const bootBar = document.getElementById("bootBar");
  const bootDetail = document.getElementById("bootDetail");
  function step(msg, pct) {
    if (bootMsg) bootMsg.textContent = msg;
    if (bootBar) bootBar.style.width = (pct || 0) + "%";
  }
  function detail(msg) { if (bootDetail) bootDetail.textContent = msg; }

  const WELCOME = `-- Welcome to Epsilon — running entirely in your browser.
-- No install, no server. Press ▶ Check (or Ctrl/Cmd+Enter) to verify.

/-- The sinc function, f(x) = sin(x)/x. -/
def f (x : Real) : Real := Real.sin(x) / x

/-- Addition on the naturals is commutative — proved by induction,
    checked by the trusted kernel: this is Formally Proven. -/
theorem add_comm (a b : Nat) : a + b = b + a := by
  induction b with
  | zero => rw [Nat.add_zero, Nat.zero_add]
  | succ n ih => rw [Nat.add_succ, Nat.succ_add, ih]

/-- The CAS computes lim_{x->0} sin(x)/x = 1. It is marked Symbolically
    Verified, never Formally Proven — Epsilon never conflates the two. -/
theorem sinc_limit : HasLimitAt(f, 0, 1) := by cas

theorem two_le_three : 2 ≤ 3 := by decide

#check f
#eval 2 + 3 * 4

plot Real.sin, x ∈ [-6, 6]
`;

  /* -------- the workspace (vfs.js) --------
     Built in main(), not here: nothing may run before the error handling
     below is in place, or a failure leaves a dead page with no message. */
  let VFS = null;
  let FILES = {};

  /* -------- JSON Response helper -------- */
  function jsonResponse(obj, status) {
    return new Response(JSON.stringify(obj),
      { status: status || 200, headers: { "content-type": "application/json" } });
  }

  /* -------- the /api/* shim -------- */
  let PY = null; // pyodide instance

  async function handleApi(url, opts) {
    const u = new URL(url, window.location.origin);
    const path = u.pathname;
    const method = (opts && opts.method) || "GET";
    const body = opts && opts.body ? JSON.parse(opts.body) : {};

    if (path === "/api/meta") {
      return jsonResponse(JSON.parse(PY.runPython("import bridge; bridge.meta()")));
    }

    // files, folders, rename, duplicate — all of it lives in vfs.js
    const fileOp = VFS.handle(path, method, body,
                              { path: u.searchParams.get("path") });
    if (fileOp) return jsonResponse(fileOp.body, fileOp.status);

    if (path === "/api/check") {
      const content = body.content != null ? body.content : (FILES[body.path] || "");
      const module = (body.path || "main").split("/").pop().replace(/\.epsl$/, "");
      PY.globals.set("_c", content);
      PY.globals.set("_m", module);
      const out = PY.runPython("import bridge; bridge.check(_c, _m)");
      return jsonResponse(JSON.parse(out));
    }

    if (path === "/api/eval") {
      PY.globals.set("_code", body.code || "");
      const out = PY.runPython("import bridge; bridge.eval_code(_code)");
      return jsonResponse(JSON.parse(out));
    }

    if (path === "/api/capabilities") {
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.ide_capabilities()")));
    }

    if (path === "/api/complete") {
      PY.globals.set("_lang", body.language || "");
      PY.globals.set("_code", body.code || "");
      PY.globals.set("_ln", body.line || 1);
      PY.globals.set("_col", body.col || 0);
      PY.globals.set("_pth", body.path || "");
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.complete(_lang, _code, _ln, _col, _pth)")));
    }

    if (path === "/api/format") {
      return jsonResponse({ ok: false, message:
        "formatters (black, clang-format) need the server build" });
    }

    if (path === "/api/search") {
      PY.globals.set("_files", JSON.stringify(FILES));
      PY.globals.set("_q", body.query || "");
      PY.globals.set("_re", !!body.regex);
      PY.globals.set("_cs", !!body.case);
      PY.globals.set("_wd", !!body.word);
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.search_files(_files, _q, _re, _cs, _wd)")));
    }

    if (path === "/api/replace") {
      PY.globals.set("_files", JSON.stringify(FILES));
      PY.globals.set("_q", body.query || "");
      PY.globals.set("_rep", body.replacement || "");
      PY.globals.set("_re", !!body.regex);
      PY.globals.set("_cs", !!body.case);
      PY.globals.set("_wd", !!body.word);
      PY.globals.set("_pths", body.paths ? JSON.stringify(body.paths) : "");
      const r = JSON.parse(PY.runPython(
        "import bridge; bridge.replace_files(_files, _q, _rep, _re, _cs, _wd, _pths or None)"));
      if (r.ok && r.changed) {
        Object.keys(r.changed).forEach((p) => {
          VFS.handle("/api/file", "PUT", { path: p, content: r.changed[p] }, {});
        });
        delete r.changed;
      }
      return jsonResponse(r);
    }

    if (path.startsWith("/api/terminal")) {
      return jsonResponse({ ok: false, message:
        "there is no operating system to give a shell to in the browser " +
        "build — the server build (epsilon serve) has real terminals" }, 501);
    }

    if (path.startsWith("/api/debug")) {
      return jsonResponse({ ok: false, message:
        "debugging needs a process that can be suspended; the browser " +
        "build cannot do that — use the server build" }, 501);
    }

    if (path.startsWith("/api/git")) {
      return jsonResponse({ ok: false, repo: false, message:
        "git is not available in the browser build — use the server " +
        "build for source control" }, 501);
    }

    if (path === "/api/run/languages") {
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.run_languages()")));
    }

    if (path === "/api/run") {
      PY.globals.set("_lang", body.language || "");
      PY.globals.set("_code", body.code || "");
      PY.globals.set("_in", body.stdin || "");
      PY.globals.set("_fn", body.filename || "");
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.run_program(_lang, _code, _in, _fn)")));
    }

    if (path === "/api/pyrepl") {
      PY.globals.set("_code", body.code || "");
      PY.globals.set("_rst", !!body.reset);
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.pyrepl(_code, _rst)")));
    }

    if (path === "/api/mathify") {
      PY.globals.set("_x", body.expr || "");
      PY.globals.set("_lang", body.language || "python");
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.mathify(_x, _lang)")));
    }

    if (path === "/api/suggest") {
      PY.globals.set("_g", body.goal || "");
      PY.globals.set("_h", (body.hypotheses || []));
      PY.globals.set("_l", body.limit == null ? 12 : body.limit);
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.suggest(_g, _h.to_py() if hasattr(_h,'to_py') else _h, _l)")));
    }

    if (path === "/api/render") {
      const content = body.content != null ? body.content : (FILES[body.path] || "");
      const module = (body.path || "main").split("/").pop().replace(/\.epsl$/, "");
      PY.globals.set("_c", content);
      PY.globals.set("_m", module);
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.render(_c, _m)")));
    }

    if (path === "/api/export") {
      const content = body.content != null ? body.content : (FILES[body.path] || "");
      const module = (body.path || "main").split("/").pop().replace(/\.epsl$/, "");
      PY.globals.set("_c", content);
      PY.globals.set("_f", body.format || "latex");
      PY.globals.set("_m", module);
      const out = PY.runPython("import bridge; bridge.export(_c, _f, _m)");
      return jsonResponse(JSON.parse(out));
    }

    if (path === "/api/cas/operations") {
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.cas_operations()")));
    }

    if (path === "/api/cas") {
      PY.globals.set("_op", body.op || "");
      PY.globals.set("_x", body.expr || "");
      PY.globals.set("_v", body.variable || "");
      PY.globals.set("_pt", body.point || "0");
      PY.globals.set("_ord", body.order == null ? 5 : body.order);
      return jsonResponse(JSON.parse(PY.runPython(
        "import bridge; bridge.cas(_op, _x, _v, _pt, _ord)")));
    }

    if (path === "/api/completions") {
      PY.globals.set("_p", u.searchParams.get("prefix") || "");
      const out = PY.runPython("import bridge; bridge.completions(_p)");
      return jsonResponse(JSON.parse(out));
    }

    if (path === "/api/hover") {
      PY.globals.set("_n", u.searchParams.get("name") || "");
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.hover(_n)")));
    }

    if (path === "/api/definition") {
      PY.globals.set("_n", u.searchParams.get("name") || "");
      return jsonResponse(JSON.parse(
        PY.runPython("import bridge; bridge.definition(_n)")));
    }

    return jsonResponse({ detail: "not found" }, 404);
  }

  function installShim() {
    window.fetch = function (url, opts) {
      try {
        const s = typeof url === "string" ? url : (url && url.url) || "";
        if (s.indexOf("/api/") !== -1) return handleApi(s, opts);
      } catch (e) {
        return jsonResponse({ ok: false,
          diagnostics: [{ severity: "error", message: String(e),
            span: [0, 0, 0, 0], module: "main" }], results: [], theorems: [],
          definitions: [], plots: [], traces: {}, deps: { nodes: [], edges: [] } });
      }
      return realFetch(url, opts);
    };
  }

  /* -------- boot sequence -------- */
  /* -------------------------------------------------------------------
   * Web-only title bar.
   *
   * index.html is generated from the shared IDE markup, which carries the
   * desktop window chrome (the macOS-style traffic lights). Those buttons
   * cannot do anything in a browser tab, so the web build swaps them for a
   * leading-edge wordmark and a link back to the source. Doing it here
   * rather than in a forked index.html keeps a single HTML source for both
   * builds; `web.css` holds the matching styling.
   * ----------------------------------------------------------------- */
  function applyWebChrome() {
    const left = document.querySelector(".titlebar .title-left");
    const center = document.querySelector(".titlebar .title-center");
    const right = document.querySelector(".titlebar .title-right");
    if (!left || !right) return;

    const traffic = left.querySelector(".traffic");
    if (traffic) traffic.remove();

    if (!left.querySelector(".wordmark")) {
      const wm = document.createElement("span");
      wm.className = "wordmark";
      wm.innerHTML = '<span class="mark" aria-hidden="true">\u03b5</span>' +
                     '<span class="name">Epsilon</span>';
      left.insertBefore(wm, left.firstChild);
    }

    // the version chip rides with the wordmark once the brand moves left
    const sub = document.getElementById("metaVersion");
    if (sub && sub.parentNode !== left) left.appendChild(sub);
    const brand = center && center.querySelector(".brand");
    if (brand) brand.remove();

    if (!right.querySelector(".repo-link")) {
      const a = document.createElement("a");
      a.className = "repo-link";
      a.href = "https://github.com/igangwoo/Epsilon";
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      a.title = "Source on GitHub";
      a.setAttribute("aria-label", "Source on GitHub");
      a.innerHTML = '<svg viewBox="0 0 16 16" width="16" height="16" fill="currentColor">' +
        '<path d="M8 0a8 8 0 00-2.53 15.59c.4.07.55-.17.55-.38l-.01-1.34c-2.23.48-2.7-1.07-2.7-1.07-.36-.93-.89-1.18-.89-1.18-.73-.5.05-.49.05-.49.8.06 1.23.83 1.23.83.72 1.23 1.88.87 2.34.67.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.83-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.6 7.6 0 014 0c1.53-1.03 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.52.56.83 1.28.83 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48l-.01 2.2c0 .21.15.46.55.38A8 8 0 008 0z"/></svg>';
      right.appendChild(a);
    }
  }

  /**
   * Make sure a script has run, loading it if the page did not.
   *
   * index.html and the scripts are separate files with separate cache
   * lifetimes, so a returning visitor can hold an older index.html — one
   * whose <script> tags predate a file this build needs — together with a
   * fresh boot.js. Depending on those tags therefore breaks the page for
   * exactly the people who have used it before. boot.js is the one file
   * any cached index.html references, so it loads what it needs itself.
   */
  function ensureScript(src, globalName) {
    if (window[globalName]) return Promise.resolve();
    const existing = Array.from(document.scripts)
      .find((s) => s.src && s.src.indexOf(src.replace("./", "")) !== -1);
    if (existing && window[globalName]) return Promise.resolve();
    return new Promise((resolve, reject) => {
      const el = document.createElement("script");
      el.src = src + CACHE_BUST;
      el.onload = () => window[globalName]
        ? resolve()
        : reject(new Error(src + " loaded but did not define " + globalName));
      el.onerror = () => reject(new Error("could not load " + src));
      document.head.appendChild(el);
    });
  }

  /**
   * Show a failure on the page. A dead page with no message helps nobody.
   *
   * A failure before the IDE is up and one after it are different events and
   * are reported differently: the first means Epsilon never started, the
   * second means something went wrong in a working IDE, and calling the
   * second one a startup failure sends the reader looking in the wrong place.
   * The second also names where it happened, so a report can be acted on.
   */
  function fail(err, hint) {
    const booting = !!document.getElementById("boot");
    const message = String(err && err.message ? err.message : err);
    const where = firstAppFrame(err);

    let host = document.getElementById("boot");
    if (booting) {
      step("Startup failed.", 100);
      detail("");
    } else {
      host = document.querySelector(".boot-banner");
      if (!host) {
        host = document.createElement("div");
        host.className = "boot-banner";
        document.body.appendChild(host);
      }
    }
    if (host.querySelector(".boot-error")) return;   // one report is enough

    const box = document.createElement("div");
    box.className = "boot-error";
    box.innerHTML =
      "<b>" + (booting ? "Could not start Epsilon."
                       : "Something went wrong.") + "</b><br>" +
      escapeHTML(message) +
      (where ? '<br><span class="boot-where">' + escapeHTML(where) + "</span>" : "") +
      (hint ? "<br><br>" + hint : "");

    const actions = document.createElement("div");
    const retry = document.createElement("button");
    retry.className = "boot-retry";
    retry.textContent = "Reload";
    retry.onclick = () => window.location.reload();
    actions.appendChild(retry);
    if (!booting) {
      const dismiss = document.createElement("button");
      dismiss.className = "boot-retry";
      dismiss.textContent = "Dismiss";
      dismiss.onclick = () => host.remove();
      actions.appendChild(dismiss);
    }
    box.appendChild(actions);
    host.appendChild(box);
    // eslint-disable-next-line no-console
    console.error(err);
  }

  /** The first stack frame in our own code — where a report should point. */
  function firstAppFrame(err) {
    const stack = err && err.stack;
    if (typeof stack !== "string") return "";
    const line = stack.split("\n")
      .find((l) => /\/(app|panes|vfs|boot)\.js/.test(l));
    if (!line) return "";
    const m = line.match(/((?:app|panes|vfs|boot)\.js[^):\s]*:\d+:\d+)/);
    return m ? m[1] : line.trim().slice(0, 120);
  }

  function escapeHTML(s) {
    return String(s).replace(/[&<>]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  window.addEventListener("error", (e) => {
    if (e && e.message) fail(e.error || e.message);
  });
  window.addEventListener("unhandledrejection", (e) => {
    if (e && e.reason) fail(e.reason);
  });

  async function main() {
    try {
      applyWebChrome();
      // vfs.js and panes.js may or may not be in this page's HTML
      await ensureScript("./vfs.js", "EpsilonVFS");
      VFS = EpsilonVFS.create(window.localStorage, WELCOME);
      FILES = VFS.contents();
      await ensureScript("./panes.js", "EpsilonPanes");
    } catch (err) {
      fail(err);
      return;
    }
    try {
      step("Loading the Python runtime (Pyodide)…", 8);
      detail("first load fetches ~10 MB and is cached afterwards");
      const s = document.createElement("script");
      s.src = PYODIDE_CDN + "pyodide.js";
      await new Promise((res, rej) => { s.onload = res; s.onerror =
        () => rej(new Error("could not load Pyodide from the CDN")); document.head.appendChild(s); });

      step("Starting Python…", 30);
      PY = await window.loadPyodide({ indexURL: PYODIDE_CDN });

      step("Installing the Epsilon engine…", 55);
      await PY.loadPackage("micropip");
      const wheelURL = new URL(WHEEL, window.location.href).href;
      PY.globals.set("_wheel", wheelURL);
      await PY.runPythonAsync(
        "import micropip\nawait micropip.install(_wheel)");

      step("Loading the bridge…", 78);
      // jedi ships with Pyodide; without it completions fall back to lexical
      try { await PY.loadPackage("jedi"); } catch (e) { /* lexical then */ }
      const bridgeSrc = await (await realFetch("./bridge.py")).text();
      PY.FS.writeFile("bridge.py", bridgeSrc);

      step("Warming up the kernel and standard library…", 88);
      // building a Session bootstraps the kernel and loads the stdlib once
      await PY.runPythonAsync("import bridge; bridge.meta()");

      step("Ready.", 100);
      installShim();

      // hand off to the (unmodified) IDE
      const app = document.createElement("script");
      app.src = "./app.js" + CACHE_BUST;
      app.onload = () => {
        if (boot) { boot.style.opacity = "0";
          setTimeout(() => boot.remove(), 400); }
      };
      document.body.appendChild(app);
    } catch (err) {
      fail(err, "This page needs one-time network access to the Pyodide CDN " +
                "(cdn.jsdelivr.net). If your network blocks it, try another " +
                "network or host Pyodide alongside these files.");
    }
  }

  main();
})();
