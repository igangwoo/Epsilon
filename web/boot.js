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

  /* -------- the workspace (vfs.js) -------- */
  const VFS = EpsilonVFS.create(window.localStorage, WELCOME);
  const FILES = VFS.contents();

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

  async function main() {
    applyWebChrome();
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
      const bridgeSrc = await (await realFetch("./bridge.py")).text();
      PY.FS.writeFile("bridge.py", bridgeSrc);

      step("Warming up the kernel and standard library…", 88);
      // building a Session bootstraps the kernel and loads the stdlib once
      await PY.runPythonAsync("import bridge; bridge.meta()");

      step("Ready.", 100);
      installShim();

      // hand off to the (unmodified) IDE
      const app = document.createElement("script");
      app.src = "./app.js";
      app.onload = () => {
        if (boot) { boot.style.opacity = "0";
          setTimeout(() => boot.remove(), 400); }
      };
      document.body.appendChild(app);
    } catch (err) {
      step("Startup failed.", 100);
      detail("");
      if (boot) {
        const box = document.createElement("div");
        box.className = "boot-error";
        box.innerHTML = "<b>Could not start Epsilon.</b><br>" +
          String(err && err.message ? err.message : err) +
          "<br><br>This page needs one-time network access to the Pyodide CDN " +
          "(cdn.jsdelivr.net). If your network blocks it, try another network " +
          "or host Pyodide alongside these files.";
        boot.appendChild(box);
      }
      // eslint-disable-next-line no-console
      console.error(err);
    }
  }

  main();
})();
