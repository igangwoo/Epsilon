/* ===================================================================
 * Epsilon — the browser workspace.
 *
 * The web build has no server, so the workspace lives in localStorage.
 * This module is the whole of it: the same file operations the FastAPI
 * server exposes (`docs/CONTRACTS.md`), implemented against a flat
 * `{path: content}` map, with the same results for the same requests.
 *
 * It is deliberately free of DOM and Pyodide references so the semantics
 * can be tested directly (`tests/test_web_vfs.py` drives it under node).
 * =================================================================== */
(function (root) {
  "use strict";

  const LS_FILES = "epsilon.files.v1";
  /* Folders are implicit in file paths, so an *empty* folder would have
     nothing to exist as. Remembering them separately is what lets you make
     a folder and then put something in it. */
  const LS_DIRS = "epsilon.folders.v1";

  const LANGUAGES = {
    epsl: "epsilon", py: "python", pyi: "python",
    cpp: "cpp", cc: "cpp", cxx: "cpp", c: "cpp", h: "cpp", hpp: "cpp",
    md: "markdown", json: "json", toml: "toml", ini: "toml", cfg: "toml",
    yaml: "yaml", yml: "yaml", tex: "latex", js: "javascript",
    ts: "javascript", html: "html", css: "css", sh: "shell",
  };

  function languageOf(p) {
    const dot = p.lastIndexOf(".");
    return (dot < 0 ? "" : LANGUAGES[p.slice(dot + 1).toLowerCase()]) || "plain";
  }

  const under = (p, dir) => p === dir || p.startsWith(dir + "/");

  /** Reject anything that would climb out of the workspace. */
  function badPath(p) {
    if (!p || typeof p !== "string") return true;
    if (p.startsWith("/")) return true;
    return p.split("/").some((seg) => seg === ".." || seg === "" || seg === ".");
  }

  function createVFS(store, welcome) {
    const read = (key, fallback) => {
      try {
        const raw = store.getItem(key);
        return raw ? JSON.parse(raw) : fallback;
      } catch (e) { return fallback; }
    };
    const write = (key, value) => {
      try { store.setItem(key, JSON.stringify(value)); } catch (e) { /* private mode */ }
    };

    let files = read(LS_FILES, null);
    if (!files || !Object.keys(files).length) {
      files = { "main.py": welcome || "" };
      write(LS_FILES, files);
    }
    let dirs = read(LS_DIRS, []);

    const saveFiles = () => write(LS_FILES, files);
    const saveDirs = () => write(LS_DIRS, dirs);
    const isDir = (p) =>
      dirs.includes(p) || Object.keys(files).some((f) => f.startsWith(p + "/"));
    const taken = (p) => p in files || dirs.includes(p);

    /** `a.epsl` -> `a copy.epsl` -> `a copy 2.epsl`, never clobbering. */
    function uniquePath(p) {
      if (!taken(p)) return p;
      const dot = p.lastIndexOf(".");
      const slash = p.lastIndexOf("/");
      const stem = dot > slash ? p.slice(0, dot) : p;
      const ext = dot > slash ? p.slice(dot) : "";
      let candidate = `${stem} copy${ext}`;
      let n = 2;
      while (taken(candidate)) { candidate = `${stem} copy ${n}${ext}`; n += 1; }
      return candidate;
    }

    /** Every file plus every folder, explicit or implied by a file path. */
    function entries() {
      const folders = new Set(dirs);
      Object.keys(files).forEach((p) => {
        const parts = p.split("/");
        for (let i = 1; i < parts.length; i++) folders.add(parts.slice(0, i).join("/"));
      });
      const out = [];
      folders.forEach((d) => {
        if (d) out.push({ name: d.split("/").pop(), path: d, kind: "folder" });
      });
      Object.keys(files).forEach((p) => out.push({
        name: p.split("/").pop(), path: p, kind: "file",
        language: languageOf(p), size: (files[p] || "").length, editable: true,
      }));
      out.sort((a, b) => (a.path.split("/").length - b.path.split("/").length)
                         || a.path.localeCompare(b.path));
      return out;
    }

    const ok = (extra) => ({ status: 200, body: Object.assign({ ok: true }, extra) });
    const err = (status, detail) => ({ status, body: { detail } });

    /**
     * Handle one file-management request.
     * Returns `{status, body}`, or null when the path is not ours.
     */
    function handle(path, method, body, params) {
      body = body || {};
      params = params || {};
      const at = params.path || body.path;

      if (path === "/api/files") {
        return { status: 200, body: {
          files: Object.keys(files).sort().filter((p) => p.endsWith(".epsl"))
            .map((p) => ({ name: p.split("/").pop(), path: p })),
          entries: entries(),
        } };
      }

      if (path === "/api/file") {
        if (method === "GET") {
          if (!(at in files)) return err(404, "not found");
          return { status: 200, body: { path: at, content: files[at] } };
        }
        if (badPath(body.path || at)) return err(400, "path escapes workspace");
        if (method === "PUT") {
          files[body.path] = body.content;
          saveFiles();
          return ok();
        }
        if (method === "POST") {
          if (!(body.path in files)) { files[body.path] = body.content || ""; saveFiles(); }
          return ok();
        }
        if (method === "DELETE") { delete files[at]; saveFiles(); return ok(); }
        return err(405, "method not allowed");
      }

      if (path === "/api/folder") {
        if (method === "POST") {
          if (badPath(at)) return err(400, "path escapes workspace");
          if (at in files) return err(409, "a file is already there");
          if (!dirs.includes(at)) { dirs.push(at); saveDirs(); }
          return ok({ path: at });
        }
        if (method === "DELETE") {
          if (!at || at === "." || at === "/")
            return err(400, "the workspace root cannot be deleted");
          if (badPath(at)) return err(400, "path escapes workspace");
          Object.keys(files).forEach((f) => { if (under(f, at)) delete files[f]; });
          dirs = dirs.filter((d) => !under(d, at));
          saveFiles(); saveDirs();
          return ok();
        }
        return err(405, "method not allowed");
      }

      if (path === "/api/rename" && method === "POST") {
        const from = body.path, to = body.to;
        const dir = isDir(from);
        if (!(from in files) && !dir) return err(404, "not found");
        if (badPath(to)) return err(400, "path escapes workspace");
        if (taken(to)) return err(409, to + " already exists");
        if (dir && under(to, from)) return err(400, "a folder cannot move inside itself");
        if (dir) {
          Object.keys(files).forEach((f) => {
            if (under(f, from)) { files[to + f.slice(from.length)] = files[f]; delete files[f]; }
          });
          dirs = dirs.map((d) => (under(d, from) ? to + d.slice(from.length) : d));
        } else {
          files[to] = files[from];
          delete files[from];
        }
        saveFiles(); saveDirs();
        return ok({ path: to });
      }

      if (path === "/api/duplicate" && method === "POST") {
        const from = body.path;
        const dir = isDir(from);
        if (!(from in files) && !dir) return err(404, "not found");
        const to = uniquePath(from);
        if (dir) {
          Object.keys(files).forEach((f) => {
            if (under(f, from)) files[to + f.slice(from.length)] = files[f];
          });
          if (!dirs.includes(to)) dirs.push(to);
        } else {
          files[to] = files[from];
        }
        saveFiles(); saveDirs();
        return ok({ path: to });
      }

      return null;
    }

    return {
      handle,
      entries,
      languageOf,
      /** the raw map, for the endpoints that run Python over file contents */
      contents: () => files,
    };
  }

  root.EpsilonVFS = { create: createVFS, languageOf };
  if (typeof module === "object" && module.exports) module.exports = root.EpsilonVFS;
})(typeof globalThis !== "undefined" ? globalThis : this);
