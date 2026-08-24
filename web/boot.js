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
  const LS_FILES = "epsilon.files.v1";

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

  /* -------- localStorage virtual filesystem -------- */
  function loadFiles() {
    try {
      const raw = localStorage.getItem(LS_FILES);
      if (raw) return JSON.parse(raw);
    } catch (e) {}
    return null;
  }
  function saveFiles(files) {
    try { localStorage.setItem(LS_FILES, JSON.stringify(files)); } catch (e) {}
  }
  let FILES = loadFiles();
  if (!FILES || !Object.keys(FILES).length) {
    FILES = { "main.epsl": WELCOME };
    saveFiles(FILES);
  }

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

    if (path === "/api/files") {
      const files = Object.keys(FILES).sort().map((p) => ({
        name: p.split("/").pop(), path: p }));
      return jsonResponse({ files });
    }

    if (path === "/api/file") {
      const p = u.searchParams.get("path") || body.path;
      if (method === "GET") {
        if (!(p in FILES)) return jsonResponse({ detail: "not found" }, 404);
        return jsonResponse({ path: p, content: FILES[p] });
      }
      if (method === "PUT") { FILES[body.path] = body.content; saveFiles(FILES);
        return jsonResponse({ ok: true }); }
      if (method === "POST") {
        if (!(body.path in FILES)) { FILES[body.path] = body.content || ""; saveFiles(FILES); }
        return jsonResponse({ ok: true }); }
      if (method === "DELETE") { delete FILES[p]; saveFiles(FILES);
        return jsonResponse({ ok: true }); }
    }

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

    if (path === "/api/export") {
      const content = body.content != null ? body.content : (FILES[body.path] || "");
      const module = (body.path || "main").split("/").pop().replace(/\.epsl$/, "");
      PY.globals.set("_c", content);
      PY.globals.set("_f", body.format || "latex");
      PY.globals.set("_m", module);
      const out = PY.runPython("import bridge; bridge.export(_c, _f, _m)");
      return jsonResponse(JSON.parse(out));
    }

    if (path === "/api/completions") {
      PY.globals.set("_p", u.searchParams.get("prefix") || "");
      const out = PY.runPython("import bridge; bridge.completions(_p)");
      return jsonResponse(JSON.parse(out));
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
  async function main() {
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
