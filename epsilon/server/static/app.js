/* ===================================================================
 * Epsilon — the workbench.
 *
 * A general-purpose programming IDE for Python and C++ that runs in the
 * browser. Everything routes through the core registries (core.js): one
 * command registration serves the palette, the menu bar, the keyboard,
 * the buttons and the context menus, and a command that cannot run here
 * always says why.
 *
 * The mathematics workbench is preserved, isolated, in ./math/ — the
 * engine behind it stays live and tested; its UI returns later as
 * context-aware tools inside this programming workflow.
 * =================================================================== */
(function () {
  "use strict";

  const { Settings, Commands, Keys, Menus, ContextMenus, Diagnostics,
          fuzzy, isMac } = EpsilonCore;
  const { CodeEditor } = EpsilonEditor;

  /* ---------------- tiny helpers ---------------- */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  /* =================================================================
   * Icons
   *
   * One coherent stroked set, drawn on a 24-unit grid at a single
   * weight. Emoji were standing in before, and they are the wrong tool:
   * every platform draws them differently, they carry their own colour,
   * and no two line up on the same optical baseline.
   * ================================================================= */
  const ICONS = {
    files: '<path d="M8.5 3.5h4.7L17 7.3v9.2a1.5 1.5 0 0 1-1.5 1.5H8.5A1.5 1.5 0 0 1 7 16.5V5a1.5 1.5 0 0 1 1.5-1.5Z"/><path d="M13 3.6V7.5h3.9"/><path d="M4.3 8.4v11.1a1.5 1.5 0 0 0 1.5 1.5h7.4"/>',
    search: '<circle cx="10.7" cy="10.7" r="6.2"/><path d="M15.3 15.3l4.4 4.4"/>',
    branch: '<circle cx="7" cy="5.6" r="2.3"/><circle cx="7" cy="18.4" r="2.3"/><circle cx="17" cy="8.6" r="2.3"/><path d="M7 7.9v8.2"/><path d="M17 10.9c0 3.3-3 4.4-6.2 4.9"/>',
    debug: '<circle cx="12" cy="12" r="8.3"/><path d="M10.3 8.7l5.4 3.3-5.4 3.3V8.7Z" fill="currentColor" stroke="none"/>',
    gear: '<circle cx="12" cy="12" r="2.9"/><path d="M19 13.9a1.5 1.5 0 0 0 .3 1.7l.1.1a1.8 1.8 0 1 1-2.6 2.6l-.1-.1a1.5 1.5 0 0 0-2.6 1.1v.3a1.8 1.8 0 1 1-3.6 0v-.2a1.5 1.5 0 0 0-2.6-1.1l-.1.1a1.8 1.8 0 1 1-2.6-2.6l.1-.1A1.5 1.5 0 0 0 4.9 13H4.6a1.8 1.8 0 1 1 0-3.6h.2a1.5 1.5 0 0 0 1.1-2.6l-.1-.1a1.8 1.8 0 1 1 2.6-2.6l.1.1A1.5 1.5 0 0 0 11 5.1v-.3a1.8 1.8 0 1 1 3.6 0V5a1.5 1.5 0 0 0 2.6 1.1l.1-.1a1.8 1.8 0 1 1 2.6 2.6l-.1.1a1.5 1.5 0 0 0 1.1 2.6h.3a1.8 1.8 0 1 1 0 3.6h-.3Z"/>',
    plus: '<path d="M12 5.6v12.8M5.6 12h12.8"/>',
    minus: '<path d="M5.6 12h12.8"/>',
    folderPlus: '<path d="M4 7.2A1.6 1.6 0 0 1 5.6 5.6h3.2l1.7 2.2h7.9A1.6 1.6 0 0 1 20 9.4v7.9a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 17.3V7.2Z"/><path d="M12 11.4v4.4M9.8 13.6h4.4"/>',
    refresh: '<path d="M19.4 12a7.4 7.4 0 1 1-2.2-5.2"/><path d="M19.7 5.2v4.2h-4.2"/>',
    close: '<path d="M6.8 6.8l10.4 10.4M17.2 6.8L6.8 17.2"/>',
    chevronRight: '<path d="M9.8 6.2l5.8 5.8-5.8 5.8"/>',
    chevronDown: '<path d="M6.2 9.8l5.8 5.8 5.8-5.8"/>',
    pin: '<path d="M9 3.8h6l-.8 5.1 3 3.1H6.8l3-3.1L9 3.8Z"/><path d="M12 12v8.2"/>',
    splitRight: '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.4"/><path d="M12 4.6v14.8"/>',
    splitDown: '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.4"/><path d="M3.6 12h16.8"/>',
    maximize: '<path d="M9.4 4.6H6a1.4 1.4 0 0 0-1.4 1.4v3.4M14.6 4.6H18A1.4 1.4 0 0 1 19.4 6v3.4M9.4 19.4H6A1.4 1.4 0 0 1 4.6 18v-3.4M14.6 19.4H18a1.4 1.4 0 0 0 1.4-1.4v-3.4"/>',
    restore: '<rect x="4.6" y="4.6" width="14.8" height="14.8" rx="2.2"/><path d="M8.6 8.6h6.8v6.8"/>',
    error: '<circle cx="12" cy="12" r="8.2"/><path d="M12 7.7v5M12 15.6v.7"/>',
    warning: '<path d="M10.7 4.9 3.6 17.3a1.5 1.5 0 0 0 1.3 2.2h14.2a1.5 1.5 0 0 0 1.3-2.2L13.3 4.9a1.5 1.5 0 0 0-2.6 0Z"/><path d="M12 9.6v3.8M12 16.3v.7"/>',
    terminal: '<rect x="3.6" y="4.9" width="16.8" height="14.2" rx="2.4"/><path d="M7.6 10l2.6 2.6-2.6 2.6M12.8 15.6h4"/>',
    bolt: '<path d="M13.4 3.6 6.2 13.2h5.1l-.7 7.2 7.2-9.6h-5.1l.7-7.2Z"/>',
    cloud: '<path d="M7.6 18.6a4.1 4.1 0 0 1 .4-8.1 5.1 5.1 0 0 1 9.7.9 3.6 3.6 0 0 1-.9 7.2H7.6Z"/>',
    check: '<path d="M5.2 12.4 9.7 17 18.8 7.4"/>',
    play: '<path d="M7.6 4.9 19 12 7.6 19.1V4.9Z" fill="currentColor" stroke="none"/>',
    resume: '<path d="M6.4 5.2v13.6" /><path d="M10.4 5.6 19.6 12l-9.2 6.4V5.6Z" fill="currentColor" stroke="none"/>',
    stop: '<rect x="6.6" y="6.6" width="10.8" height="10.8" rx="2" fill="currentColor" stroke="none"/>',
    pause: '<path d="M9.2 5.6v12.8M14.8 5.6v12.8"/>',
    stepOver: '<path d="M4.8 9.6a8 8 0 0 1 14.4 3.2"/><path d="M19.4 8.4v4.6h-4.6"/><circle cx="12" cy="18" r="2.1" fill="currentColor" stroke="none"/>',
    stepInto: '<path d="M12 4.4v8.4"/><path d="M8.6 9.6 12 13l3.4-3.4"/><circle cx="12" cy="18.4" r="2.1" fill="currentColor" stroke="none"/>',
    stepOut: '<path d="M12 13v-8.4"/><path d="M8.6 8 12 4.6 15.4 8"/><circle cx="12" cy="18.4" r="2.1" fill="currentColor" stroke="none"/>',
    file: '<path d="M13.2 3.6H7.6A1.6 1.6 0 0 0 6 5.2v13.6a1.6 1.6 0 0 0 1.6 1.6h8.8a1.6 1.6 0 0 0 1.6-1.6V8.4l-4.8-4.8Z"/><path d="M13.2 3.7v4.6h4.6"/>',
    folder: '<path d="M4 7.2A1.6 1.6 0 0 1 5.6 5.6h3.2l1.7 2.2h7.9A1.6 1.6 0 0 1 20 9.4v7.9a1.6 1.6 0 0 1-1.6 1.6H5.6A1.6 1.6 0 0 1 4 17.3V7.2Z"/>',
    fn: '<path d="M14.6 5.2h-1.2a2.6 2.6 0 0 0-2.6 2.6v9a2.6 2.6 0 0 1-2.6 2.6H7"/><path d="M7.4 11.6h7.2"/>',
    cube: '<path d="M12 3.8 20 8v8l-8 4.2L4 16V8l8-4.2Z"/><path d="M4 8l8 4.2L20 8M12 12.2v8"/>',
    dot: '<circle cx="12" cy="12" r="3.4" fill="currentColor" stroke="none"/>',
  };

  const SVG_NS = "http://www.w3.org/2000/svg";

  /** An icon element. `size` is the box; the grid inside is always 24. */
  function icon(name, size) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size || 16));
    svg.setAttribute("height", String(size || 16));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.6");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.classList.add("wb-i");
    svg.innerHTML = ICONS[name] || "";
    return svg;
  }

  /** A button whose whole content is one icon. */
  function iconButton(name, title, run, cls, size) {
    const b = el("button", cls || "wb-icon-btn");
    b.appendChild(icon(name, size));
    b.title = title;
    b.setAttribute("aria-label", title);
    if (run) b.onclick = run;
    return b;
  }

  const esc = (s) => String(s).replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const readJSON = (key, fallback) => {
    try {
      const raw = localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  };
  const writeJSON = (key, value) => {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) {}
  };

  async function api(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(path, opts);
    } catch (e) {
      notify(String(e.message || e), "err");
      throw e;
    }
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("json") ? await res.json() : await res.text();
    if (!res.ok && data && typeof data === "object") {
      if (!("ok" in data)) data.ok = false;
      if (!data._quiet && res.status !== 501) {
        notify(data.detail || data.message || `Request failed (${res.status})`,
               "err");
      }
    }
    return data;
  }

  /* ---------------- notifications ---------------- */
  function notify(message, tone, actions) {
    const stack = $("#toastStack");
    if (!stack) return;
    const box = el("div", "toast " + (tone || "info"));
    box.setAttribute("role", tone === "err" ? "alert" : "status");
    box.appendChild(el("span", "toast-msg", message));
    (actions || []).forEach((a) => {
      const b = el("button", "toast-act", a.label);
      b.onclick = () => { box.remove(); a.run(); };
      box.appendChild(b);
    });
    const close = iconButton("close", "Dismiss", () => box.remove(),
                             "toast-x", 13);
    box.appendChild(close);
    stack.appendChild(box);
    if (!actions) setTimeout(() => box.remove(), tone === "err" ? 9000 : 4500);
  }

  /* ---------------- shared state ---------------- */
  const state = {
    entries: [],                 // workspace listing
    active: null,                // active file path
    dirty: new Map(),            // path -> content differs from saved
    caps: null,                  // /api/capabilities
    recentFiles: readJSON("epsilon.recentFiles.v1", []),
    closedTabs: [],              // for Reopen Closed Editor
    navStack: [], navIndex: -1,  // go back / forward
    breakpoints: readJSON("epsilon.breakpoints.v1", {}),  // path -> [lines]
  };

  const EXT_LANGUAGE = {
    epsl: "epsilon", py: "python", pyi: "python",
    cpp: "cpp", cc: "cpp", cxx: "cpp", c: "cpp", h: "cpp", hpp: "cpp",
    md: "markdown", json: "json", toml: "toml", ini: "toml", cfg: "toml",
    yaml: "yaml", yml: "yaml", tex: "latex", js: "javascript",
    ts: "javascript", html: "html", css: "css", sh: "shell",
  };
  const LANGUAGE_LABEL = {
    python: "Python", cpp: "C++", epsilon: "Epsilon", markdown: "Markdown",
    json: "JSON", toml: "TOML", yaml: "YAML", latex: "LaTeX",
    javascript: "JavaScript", shell: "Shell", html: "HTML", css: "CSS",
    plain: "Plain Text",
  };
  function languageOf(path) {
    const dot = path.lastIndexOf(".");
    return (dot < 0 ? "" : EXT_LANGUAGE[path.slice(dot + 1).toLowerCase()])
      || "plain";
  }
  const RUNNABLE = new Set(["python", "cpp"]);

  /* =================================================================
   * Settings schema
   * ================================================================= */
  function registerSettings() {
    const S = Settings.register;
    // Text Editor
    S({ id: "editor.fontSize", title: "Font Size", category: "Text Editor",
        type: "number", default: 13, min: 8, max: 32,
        description: "Editor font size in pixels." });
    S({ id: "editor.fontFamily", title: "Font Family", category: "Text Editor",
        type: "string", default: "",
        description: "Overrides the editor font stack when set." });
    S({ id: "editor.lineHeight", title: "Line Height", category: "Text Editor",
        type: "number", default: 1.55, min: 1.1, max: 2.4,
        description: "Line height as a multiple of the font size." });
    S({ id: "editor.tabSize", title: "Tab Size", category: "Text Editor",
        type: "number", default: 4, min: 1, max: 8,
        description: "Spaces per indentation level." });
    S({ id: "editor.insertSpaces", title: "Insert Spaces",
        category: "Text Editor", type: "boolean", default: true,
        description: "Indent with spaces instead of tab characters." });
    S({ id: "editor.wordWrap", title: "Word Wrap", category: "Text Editor",
        type: "boolean", default: false,
        description: "Wrap long lines instead of scrolling horizontally." });
    S({ id: "editor.lineNumbers", title: "Line Numbers",
        category: "Text Editor", type: "boolean", default: true });
    S({ id: "editor.renderWhitespace", title: "Render Whitespace",
        category: "Text Editor", type: "enum", default: "none",
        options: ["none", "boundary", "all"],
        description: "Show spaces and tabs in the editor overlay." });
    S({ id: "editor.cursorStyle", title: "Cursor Style",
        category: "Text Editor", type: "enum", default: "line",
        options: ["line", "block", "underline"] });
    S({ id: "editor.cursorBlinking", title: "Cursor Blinking",
        category: "Text Editor", type: "enum", default: "smooth",
        options: ["blink", "smooth", "expand", "solid"] });
    S({ id: "editor.autoClosingBrackets", title: "Auto Closing Brackets",
        category: "Text Editor", type: "boolean", default: true });
    S({ id: "editor.formatOnSave", title: "Format On Save",
        category: "Text Editor", type: "boolean", default: false,
        description: "Run the formatter every time a file is saved." });
    // Workbench
    S({ id: "workbench.activityBar", title: "Activity Bar",
        category: "Workbench", type: "boolean", default: true });
    S({ id: "workbench.statusBar", title: "Status Bar",
        category: "Workbench", type: "boolean", default: true });
    S({ id: "workbench.sidebarWidth", title: "Sidebar Width",
        category: "Workbench", type: "number", default: 260, min: 160,
        max: 600 });
    S({ id: "workbench.panelHeight", title: "Panel Height",
        category: "Workbench", type: "number", default: 240, min: 100,
        max: 800 });
    S({ id: "workbench.theme", title: "Color Theme", category: "Workbench",
        type: "enum", default: "dark",
        options: ["dark", "light", "high-contrast"] });
    S({ id: "workbench.reducedMotion", title: "Reduced Motion",
        category: "Workbench", type: "boolean", default: false,
        description: "Disable animations regardless of system preference." });
    // Terminal
    S({ id: "terminal.fontSize", title: "Terminal Font Size",
        category: "Terminal", type: "number", default: 12.5, min: 8,
        max: 24 });
    // Run
    S({ id: "run.saveBeforeRun", title: "Save Before Run", category: "Run",
        type: "boolean", default: true });
    S({ id: "run.timeout", title: "Run Timeout (seconds)", category: "Run",
        type: "number", default: 10, min: 1, max: 60 });
  }

  /* =================================================================
   * Editor groups — panes.js hosts one view per open file
   * ================================================================= */
  const editors = new Map();     // path -> {editor: CodeEditor, host}
  const SPECIAL = new Map();     // special tabs: settings://, shortcuts://…

  function currentEditor() {
    return state.active ? editors.get(state.active) : null;
  }
  function currentLanguage() {
    return state.active && !SPECIAL.has(state.active)
      ? languageOf(state.active) : "plain";
  }

  function tabTitle(path) {
    if (SPECIAL.has(path)) return SPECIAL.get(path).title;
    return path.split("/").pop();
  }

  async function openFile(path, opts = {}) {
    if (SPECIAL.has(path)) {
      EpsilonPanes.openView(path);
      state.active = path;
      refreshChrome();
      return;
    }
    if (!editors.has(path)) {
      const r = await api("GET", "/api/file?path=" + encodeURIComponent(path));
      if (r && r.ok === false) return;
      const host = el("div", "wb-editor-host");
      const language = languageOf(path);
      const ed = new CodeEditor(host, {
        language,
        value: r.content || "",
        path,
        settings: (id) => Settings.get(id),
        onChange: () => {
          const entry = editors.get(path);
          const dirty = entry.editor.getValue() !== entry.saved;
          if (state.dirty.get(path) !== dirty) {
            state.dirty.set(path, dirty);
            EpsilonPanes.setDirty(path, dirty);
            renderExplorer();
            refreshChrome();
          }
        },
        onCursor: () => { if (path === state.active) updateCursorStatus(); },
        completions: async (ctx) => {
          // the API speaks jedi's convention: 1-based line, 0-based column
          const reply = await api("POST", "/api/complete", {
            language: ctx.language, code: ctx.code, line: ctx.line,
            col: ctx.col, path: ctx.path,
          });
          return (reply && reply.items) || [];
        },
        onBreakpoints: (lines) => {
          state.breakpoints[path] = lines;
          writeJSON("epsilon.breakpoints.v1", state.breakpoints);
          renderRunDebug();
        },
      });
      (state.breakpoints[path] || []).forEach((line) =>
        ed.breakpoints.add(line));
      editors.set(path, { editor: ed, host, saved: r.content || "" });
      EpsilonPanes.registerView(path, {
        title: tabTitle(path), element: host, closable: true,
        icon: "",
        onShow: () => {
          state.active = path;
          pushNav(path);
          refreshChrome();
          ed.setDiagnostics(Diagnostics.forPath(path));
          setTimeout(() => ed.focus(), 0);
        },
        onClose: () => closeFile(path, { keepValue: true }),
      });
    }
    EpsilonPanes.openView(path, opts);
    state.active = path;
    state.recentFiles = [path,
      ...state.recentFiles.filter((p) => p !== path)].slice(0, 15);
    writeJSON("epsilon.recentFiles.v1", state.recentFiles);
    pushNav(path);
    refreshChrome();
  }

  function closeFile(path, opts = {}) {
    const entry = editors.get(path);
    if (entry) {
      state.closedTabs.push(path);
      entry.editor.destroy();
      editors.delete(path);
      state.dirty.delete(path);
    }
    if (SPECIAL.has(path) && !SPECIAL.get(path).permanent) SPECIAL.delete(path);
    if (state.active === path) {
      state.active = EpsilonPanes.activeView() || null;
      refreshChrome();
    }
  }

  async function saveFile(path) {
    const entry = editors.get(path);
    if (!entry) return;
    let content = entry.editor.getValue();
    if (Settings.get("editor.formatOnSave") &&
        state.caps && state.caps.format &&
        state.caps.format[languageOf(path)]) {
      const r = await api("POST", "/api/format",
                          { language: languageOf(path), code: content });
      if (r.ok) {
        content = r.code;
        const [s, e] = entry.editor.getSelection();
        entry.editor.setValue(content);
        entry.editor.setSelection(Math.min(s, content.length),
                                  Math.min(e, content.length));
      }
    }
    const w = await api("PUT", "/api/file", { path, content });
    if (w && w.ok === false) return;
    entry.saved = content;
    state.dirty.set(path, false);
    EpsilonPanes.setDirty(path, false);
    renderExplorer();
    refreshChrome();
    refreshGit();
    notify("Saved " + tabTitle(path), "ok");
  }

  /* ---------------- navigation history ---------------- */
  function pushNav(path) {
    const cursor = editors.has(path)
      ? editors.get(path).editor.cursor() : { line: 1, col: 1 };
    const top = state.navStack[state.navIndex];
    if (top && top.path === path && Math.abs(top.line - cursor.line) < 5) {
      top.line = cursor.line;
      return;
    }
    state.navStack = state.navStack.slice(0, state.navIndex + 1);
    state.navStack.push({ path, line: cursor.line, col: cursor.col });
    if (state.navStack.length > 100) state.navStack.shift();
    state.navIndex = state.navStack.length - 1;
  }

  function navGo(delta) {
    const idx = state.navIndex + delta;
    if (idx < 0 || idx >= state.navStack.length) return;
    state.navIndex = idx;
    const loc = state.navStack[idx];
    openFile(loc.path).then(() => {
      const entry = editors.get(loc.path);
      if (entry) entry.editor.revealLine(loc.line, loc.col);
    });
  }

  /* =================================================================
   * Chrome refresh (title, statusbar, run button)
   * ================================================================= */
  function refreshChrome() {
    renderStatusbar();
    renderRunButton();
    renderOutline();
    persistWorkspace();
    document.title = state.active
      ? `${state.dirty.get(state.active) ? "● " : ""}${tabTitle(state.active)}` +
        " — Epsilon" : "Epsilon";
  }

  /* =================================================================
   * Explorer (primary sidebar view)
   * ================================================================= */
  const COLLAPSE_KEY = "epsilon.explorer.collapsed.v1";
  const collapsed = new Set(readJSON(COLLAPSE_KEY, []));
  const persistCollapsed = () =>
    writeJSON(COLLAPSE_KEY, Array.from(collapsed));

  //: a two-or-three letter monogram, tinted per language. A row of
  //: identical grey document icons tells you nothing; the colour is
  //: what lets you find the C++ file in a folder of Python at a glance.
  const FILE_GLYPH = {
    python: "PY", cpp: "C++", epsilon: "ε", markdown: "MD", json: "{}",
    toml: "TOM", yaml: "YML", latex: "TeX", javascript: "JS", html: "<>",
    css: "CSS", shell: "SH", plain: "TXT",
  };

  async function loadFiles() {
    const r = await api("GET", "/api/files");
    state.entries = r.entries || [];
    renderExplorer();
  }

  function fileTree(entries) {
    const rootNode = { children: new Map() };
    entries.forEach((entry) => {
      const parts = entry.path.split("/");
      let node = rootNode;
      parts.forEach((part, i) => {
        const here = parts.slice(0, i + 1).join("/");
        if (!node.children.has(part)) {
          node.children.set(part, {
            name: part, path: here, children: new Map(),
            kind: i === parts.length - 1 ? entry.kind : "folder",
            entry: i === parts.length - 1 ? entry : null,
          });
        }
        node = node.children.get(part);
      });
    });
    return rootNode;
  }

  function renderExplorer() {
    const list = $("#explorerList");
    if (!list) return;
    list.innerHTML = "";
    const needle = (state.fileFilter || "").trim().toLowerCase();
    const rootNode = fileTree(state.entries);
    const matches = (node) => !needle ||
      node.path.toLowerCase().includes(needle) ||
      Array.from(node.children.values()).some(matches);
    const sorted = (node) => Array.from(node.children.values()).sort((a, b) =>
      (a.kind === b.kind ? 0 : a.kind === "folder" ? -1 : 1) ||
      a.name.localeCompare(b.name));
    const walk = (node, depth) => {
      sorted(node).forEach((child) => {
        if (!matches(child)) return;
        list.appendChild(explorerRow(child, depth));
        if (child.kind === "folder" && (needle || !collapsed.has(child.path))) {
          walk(child, depth + 1);
        }
      });
    };
    walk(rootNode, 0);
    if (!list.children.length) {
      list.appendChild(el("li", "wb-empty",
        needle ? "No file matches the filter." : "No files yet."));
    }
  }

  function explorerRow(node, depth) {
    const item = el("li",
      "wb-file" + (node.kind === "folder" ? " folder" : ""));
    item.style.paddingLeft = 10 + depth * 12 + "px";
    item.dataset.path = node.path;
    item.dataset.kind = node.kind;
    item.title = node.path;
    item.tabIndex = 0;
    item.setAttribute("role", "treeitem");
    if (node.kind === "folder") {
      if (!collapsed.has(node.path)) item.classList.add("open");
      const twisty = el("span", "wb-twisty");
      twisty.appendChild(icon("chevronRight", 13));
      item.appendChild(twisty);
      const fico = el("span", "wb-glyph folder");
      fico.appendChild(icon("folder", 15));
      item.appendChild(fico);
    } else {
      const lang = (node.entry && node.entry.language) || "plain";
      item.appendChild(el("span", "wb-glyph lang-" + lang,
                          FILE_GLYPH[lang] || "TXT"));
    }
    item.appendChild(el("span", "wb-file-name", node.name));
    if (state.dirty.get(node.path)) item.appendChild(el("span", "wb-dot"));
    if (node.path === state.active) item.classList.add("active");
    const activate = () => {
      if (node.kind === "folder") {
        if (collapsed.has(node.path)) collapsed.delete(node.path);
        else collapsed.add(node.path);
        persistCollapsed();
        renderExplorer();
      } else if (node.entry && node.entry.editable === false) {
        notify(node.name + " is not a text file", "warn");
      } else {
        openFile(node.path);
      }
    };
    item.onclick = activate;
    item.onkeydown = (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); activate(); }
    };
    item.oncontextmenu = (ev) => {
      ev.preventDefault();
      showContextMenu("explorer", ev.clientX, ev.clientY, { node });
    };
    wireExplorerDrag(item, node);
    return item;
  }

  function wireExplorerDrag(item, node) {
    item.draggable = true;
    item.addEventListener("dragstart", (ev) => {
      ev.dataTransfer.setData("text/epsilon-path", node.path);
      ev.dataTransfer.effectAllowed = "move";
    });
    if (node.kind !== "folder") return;
    item.addEventListener("dragover", (ev) => {
      if (!ev.dataTransfer.types.includes("text/epsilon-path")) return;
      ev.preventDefault();
      item.classList.add("drop");
    });
    item.addEventListener("dragleave", () => item.classList.remove("drop"));
    item.addEventListener("drop", (ev) => {
      ev.preventDefault();
      item.classList.remove("drop");
      const from = ev.dataTransfer.getData("text/epsilon-path");
      if (from) moveEntry(from, node.path + "/" + from.split("/").pop());
    });
  }

  const joinPath = (dir, name) => (dir ? dir + "/" + name : name);
  function folderOf(node) {
    if (node) {
      return node.kind === "folder" ? node.path
        : node.path.split("/").slice(0, -1).join("/");
    }
    if (state.active && !SPECIAL.has(state.active)) {
      return state.active.split("/").slice(0, -1).join("/");
    }
    return "";
  }

  async function moveEntry(from, to) {
    if (!to || from === to) return;
    const r = await api("POST", "/api/rename", { path: from, to });
    if (r && r.ok === false) return;
    if (editors.has(from)) {
      const entry = editors.get(from);
      editors.delete(from);
      editors.set(to, entry);
      EpsilonPanes.renameView(from, to, tabTitle(to));
      if (state.active === from) state.active = to;
    }
    await loadFiles();
    refreshGit();
  }

  async function newFile(node) {
    const name = prompt("New file name:", "untitled.py");
    if (!name) return;
    const path = joinPath(folderOf(node),
      /\.[^./]+$/.test(name) ? name : name + ".py");
    const r = await api("POST", "/api/file", { path, content: "" });
    if (r && r.ok === false) return;
    await loadFiles();
    openFile(path);
  }

  async function newFolder(node) {
    const name = prompt("New folder name:", "src");
    if (!name) return;
    await api("POST", "/api/folder", { path: joinPath(folderOf(node), name) });
    await loadFiles();
  }

  async function newProject() {
    const name = prompt("New project name:", "my-project");
    if (!name) return;
    await api("POST", "/api/folder", { path: name });
    const main = name + "/main.py";
    await api("POST", "/api/file", {
      path: main,
      content: '"""' + name + '"""\n\n\ndef main() -> None:\n    print("hello from ' + name + '")\n\n\nif __name__ == "__main__":\n    main()\n' });
    await loadFiles();
    openFile(main);
    notify("Project " + name + " created", "ok");
  }

  async function renameEntry(node) {
    const name = prompt("Rename " + node.name + " to:", node.name);
    if (!name || name === node.name) return;
    const dir = node.path.split("/").slice(0, -1).join("/");
    await moveEntry(node.path, joinPath(dir, name));
  }

  async function deleteEntry(node) {
    const what = node.kind === "folder"
      ? 'Delete the folder "' + node.name + '" and everything in it?'
      : 'Delete "' + node.name + '"?';
    if (!confirm(what)) return;
    if (node.kind === "folder") {
      await api("DELETE", "/api/folder?path=" + encodeURIComponent(node.path));
      Array.from(editors.keys())
        .filter((p) => p.startsWith(node.path + "/"))
        .forEach((p) => { EpsilonPanes.closeView(p); closeFile(p); });
    } else {
      await api("DELETE", "/api/file?path=" + encodeURIComponent(node.path));
      EpsilonPanes.closeView(node.path);
      closeFile(node.path);
    }
    await loadFiles();
    refreshGit();
  }

  /* =================================================================
   * Bottom panel — Terminal · Problems · Output · Debug Console
   * ================================================================= */
  const panel = {
    open: readJSON("epsilon.panel.open.v1", true),
    active: readJSON("epsilon.panel.active.v1", "terminal"),
    tabs: [
      { id: "terminal", title: "Terminal" },
      { id: "problems", title: "Problems" },
      { id: "output", title: "Output" },
      { id: "debug", title: "Debug Console" },
    ],
  };

  function showPanel(tabId, focus) {
    panel.open = true;
    if (tabId) panel.active = tabId;
    writeJSON("epsilon.panel.open.v1", true);
    writeJSON("epsilon.panel.active.v1", panel.active);
    renderPanel();
    if (focus && panel.active === "terminal") term.focusInput();
  }

  function togglePanel(tabId) {
    if (panel.open && (!tabId || panel.active === tabId)) {
      panel.open = false;
      writeJSON("epsilon.panel.open.v1", false);
      renderPanel();
    } else {
      showPanel(tabId, true);
    }
  }

  function renderPanel() {
    const host = $("#panel");
    host.classList.toggle("collapsed", !panel.open);
    $("#panelSash").classList.toggle("collapsed", !panel.open);
    if (!panel.open) return;
    const tabs = $("#panelTabs");
    tabs.innerHTML = "";
    const counts = Diagnostics.count();
    panel.tabs.forEach((t) => {
      const tab = el("button",
        "wb-panel-tab" + (t.id === panel.active ? " active" : ""), t.title);
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-selected", String(t.id === panel.active));
      if (t.id === "problems" && counts.errors + counts.warnings > 0) {
        tab.appendChild(el("span", "wb-badge" +
          (counts.errors ? " err" : " warn"),
          String(counts.errors + counts.warnings)));
      }
      tab.onclick = () => showPanel(t.id, true);
      tabs.appendChild(tab);
    });
    tabs.appendChild(el("span", "wb-panel-spacer"));
    tabs.appendChild(iconButton("close", "Close panel",
                                () => togglePanel(), "wb-icon-btn", 14));
    $$(".wb-panel-view").forEach((v) =>
      v.classList.toggle("hidden", v.dataset.panel !== panel.active));
    if (panel.active === "problems") renderProblems();
    if (panel.active === "terminal") term.ensure();
  }

  /* ---------------- problems ---------------- */
  function renderProblems() {
    const host = $("#panelProblems");
    host.innerHTML = "";
    const all = Diagnostics.all();
    if (!all.size) {
      host.appendChild(el("div", "wb-empty", "No problems detected."));
      return;
    }
    all.forEach((diags, path) => {
      const group = el("div", "wb-prob-file");
      group.appendChild(el("div", "wb-prob-head", path));
      diags.forEach((d) => {
        const row = el("div", "wb-prob-row");
        row.appendChild(el("span",
          "wb-prob-sev " + d.severity));
        row.appendChild(el("span", "wb-prob-msg", d.message));
        row.appendChild(el("span", "wb-prob-loc",
          d.span[0] + ":" + ((d.span[1] || 0) + 1)));
        row.tabIndex = 0;
        const jump = () => openFile(path).then(() => {
          const entry = editors.get(path);
          if (entry) entry.editor.revealLine(d.span[0], (d.span[1] || 0) + 1);
        });
        row.onclick = jump;
        row.onkeydown = (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); jump(); }
        };
        group.appendChild(row);
      });
      host.appendChild(group);
    });
  }

  Diagnostics.onChange(() => {
    renderPanel();
    editors.forEach((entry, path) =>
      entry.editor.setDiagnostics(Diagnostics.forPath(path)));
    renderStatusbar();
  });

  /* ---------------- output channel ---------------- */
  const output = {
    write(text, cls) {
      const host = $("#panelOutput");
      const block = el("pre", "wb-out" + (cls ? " " + cls : ""), text);
      host.appendChild(block);
      host.scrollTop = host.scrollHeight;
    },
    clear() { $("#panelOutput").innerHTML = ""; },
  };

  /* =================================================================
   * Terminal — a real shell over the PTY sessions (server build)
   * ================================================================= */
  const ESC = "\x1b";
  const term = {
    sessions: [],
    active: null,
    timer: null,

    supported() { return state.caps && state.caps.terminal; },

    async ensure() {
      const screen = $("#termScreen");
      if (!state.caps) {
        screen.innerHTML = "";
        screen.appendChild(el("div", "wb-empty",
          "Detecting what this machine can do…"));
        return;
      }
      if (!this.supported()) {
        screen.innerHTML = "";
        screen.appendChild(el("div", "wb-empty",
          "There is no operating system to give a shell to in the browser " +
          "build. Run the local server build (pip install epsilon-math; " +
          "epsilon serve) for real terminals. The Debug Console offers a " +
          "Python session here."));
        $("#termInputRow").classList.add("hidden");
        return;
      }
      $("#termInputRow").classList.remove("hidden");
      if (!this.sessions.length) await this.create();
      this.renderTabs();
      this.startPolling();
    },

    async create() {
      const r = await api("POST", "/api/terminal");
      if (!r || !r.id) return;
      this.sessions.push({ id: r.id, name: "bash " + r.id.slice(1),
                           cursor: 0, lines: [""], dead: false });
      this.active = r.id;
      await api("POST", "/api/terminal/" + r.id + "/resize",
                { rows: 24, cols: this.cols() });
      this.renderTabs();
      this.renderScreen();
    },

    cols() {
      const screen = $("#termScreen");
      return Math.max(20, Math.floor(((screen && screen.clientWidth) || 640) / 7.2));
    },

    session() { return this.sessions.find((s) => s.id === this.active); },

    async kill(id) {
      await api("DELETE", "/api/terminal/" + id);
      this.sessions = this.sessions.filter((s) => s.id !== id);
      if (this.active === id) {
        this.active = this.sessions.length
          ? this.sessions[this.sessions.length - 1].id : null;
      }
      this.renderTabs();
      this.renderScreen();
    },

    startPolling() {
      if (this.timer) return;
      const poll = async () => {
        const s = this.session();
        if (s && panel.open && panel.active === "terminal" && !s.dead) {
          try {
            const r = await api("GET",
              "/api/terminal/" + s.id + "?since=" + s.cursor);
            if (r && typeof r.cursor === "number") {
              if (r.data) this.feed(s, r.data);
              s.cursor = r.cursor;
              if (!r.alive && !s.dead) {
                s.dead = true;
                this.feed(s, "\n[shell exited: " + r.exit_code + "]\n");
              }
            }
          } catch (e) { /* next poll */ }
        }
        this.timer = setTimeout(poll, 140);
      };
      poll();
    },

    /** PTY bytes through a small line discipline: SGR colours kept, CR
        overwrites the line, other control sequences dropped. Full-screen
        curses programs are out of scope, and that is stated, not hidden. */
    feed(s, data) {
      let text = data.replace(new RegExp(ESC + "\\][^\\x07]*(\\x07|" + ESC + "\\\\)", "g"), "");
      let line = s.lines.pop() || "";
      let i = 0;
      while (i < text.length) {
        const ch = text[i];
        if (ch === "\n") { s.lines.push(line); line = ""; i += 1; continue; }
        if (ch === "\r") { line = ""; i += 1; continue; }
        if (ch === "\b") { line = line.slice(0, -1); i += 1; continue; }
        if (ch === "\x07") { i += 1; continue; }
        if (ch === ESC) {
          const m = /^\[([0-9;?]*)([A-Za-z])/.exec(text.slice(i + 1));
          if (m) {
            if (m[2] === "m") line += "\x00[" + m[1] + "m";
            i += 1 + m[0].length;
            continue;
          }
          i += 2;
          continue;
        }
        line += ch;
        i += 1;
      }
      s.lines.push(line);
      if (s.lines.length > 2000) s.lines = s.lines.slice(-2000);
      this.renderScreen();
    },

    ansiToHtml(line) {
      const COLORS = ["#3b4048", "#e06c75", "#98c379", "#e5c07b", "#61afef",
                      "#c678dd", "#56b6c2", "#d4d4d4"];
      let html = "";
      let open = false;
      line.split("\x00").forEach((part, idx) => {
        if (idx === 0) { html += esc(part); return; }
        const m = /^\[([0-9;]*)m([\s\S]*)$/.exec(part);
        if (!m) { html += esc(part); return; }
        if (open) { html += "</span>"; open = false; }
        const codes = m[1].split(";").filter(Boolean).map(Number);
        const styles = [];
        codes.forEach((c) => {
          if (c >= 30 && c <= 37) styles.push("color:" + COLORS[c - 30]);
          if (c >= 90 && c <= 97) styles.push("color:" + COLORS[c - 90]);
          if (c === 1) styles.push("font-weight:600");
          if (c === 4) styles.push("text-decoration:underline");
        });
        if (styles.length) {
          html += '<span style="' + styles.join(";") + '">';
          open = true;
        }
        html += esc(m[2]);
      });
      if (open) html += "</span>";
      return html;
    },

    renderTabs() {
      const host = $("#termTabs");
      if (!host) return;
      host.innerHTML = "";
      this.sessions.forEach((s) => {
        const tab = el("button",
          "wb-term-tab" + (s.id === this.active ? " active" : ""), s.name);
        tab.onclick = () => { this.active = s.id; this.renderTabs();
                              this.renderScreen(); this.focusInput(); };
        const x = el("span", "wb-term-x");
        x.appendChild(icon("close", 12));
        x.onclick = (ev) => { ev.stopPropagation(); this.kill(s.id); };
        tab.appendChild(x);
        host.appendChild(tab);
      });
      const plus = iconButton("plus", "New Terminal", null, "wb-icon-btn", 14);
      plus.title = "New terminal";
      plus.onclick = () => Commands.execute("terminal.new");
      host.appendChild(plus);
    },

    renderScreen() {
      const screen = $("#termScreen");
      if (!screen) return;
      const s = this.session();
      if (!s) {
        screen.innerHTML = "";
        screen.appendChild(el("div", "wb-empty",
          "No terminal — open one with Terminal → New Terminal."));
        return;
      }
      screen.innerHTML = s.lines.map((l) =>
        '<div class="wb-term-line">' + (this.ansiToHtml(l) || "&nbsp;") + "</div>")
        .join("");
      screen.scrollTop = screen.scrollHeight;
    },

    async send(data) {
      const s = this.session();
      if (!s || s.dead) return;
      await api("POST", "/api/terminal/" + s.id + "/input", { data });
    },

    focusInput() {
      const input = $("#termInput");
      if (input && this.supported()) input.focus();
    },

    clear() {
      const s = this.session();
      if (s) { s.lines = [""]; this.renderScreen(); }
      this.send("clear\n");
    },
  };

  /* =================================================================
   * Run — execution flows into the panel, not a separate app
   * ================================================================= */
  const runState = { busy: false };

  function canRun() { return RUNNABLE.has(currentLanguage()); }
  function runDisabledReason() {
    if (!state.active || SPECIAL.has(state.active)) return "no file is active";
    const lang = currentLanguage();
    if (!RUNNABLE.has(lang)) {
      return (LANGUAGE_LABEL[lang] || lang) + " files are not runnable — " +
        "Python and C++ are";
    }
    if (state.caps && state.caps.run && state.caps.run[lang] === false) {
      return lang === "cpp"
        ? "C++ needs a compiler; the browser build has none (use the " +
          "server build)"
        : lang + " is not runnable in this environment";
    }
    return null;
  }

  async function runCurrentFile() {
    const path = state.active;
    const entry = editors.get(path);
    if (!entry || runState.busy) return;
    const language = languageOf(path);
    if (Settings.get("run.saveBeforeRun") && state.dirty.get(path)) {
      await saveFile(path);
    }
    runState.busy = true;
    renderRunButton();
    showPanel("output");
    output.clear();
    output.write("\u203a " + path + "  (" + LANGUAGE_LABEL[language] + ")",
                 "dim");
    let r;
    try {
      r = await api("POST", "/api/run", {
        language, code: entry.editor.getValue(),
        timeout: Settings.get("run.timeout"),
        filename: path.split("/").pop(),
      });
    } finally {
      runState.busy = false;
      renderRunButton();
    }
    if (r.message) output.write(r.message, "err");
    if (r.stdout) output.write(r.stdout);
    if (r.stderr) output.write(r.stderr, "err");
    if (!r.message && !r.stdout && !r.stderr) output.write("(no output)", "dim");
    const bits = [];
    if (r.phase === "compile") bits.push("failed to compile");
    else if (r.exit_code != null) bits.push("exit " + r.exit_code);
    if (r.duration_ms != null) bits.push(r.duration_ms + " ms");
    output.write(bits.join(" · "), r.ok ? "ok" : "err");
    Diagnostics.set("run", path, r.diagnostics || []);
    if ((r.diagnostics || []).some((d) => d.severity === "error")) {
      showPanel("problems");
    }
  }

  /* =================================================================
   * Debug — bdb sessions surfaced in the Run & Debug view
   * ================================================================= */
  const dbg = {
    id: null, cursor: 0, timer: null, stopped: null, path: null,

    reason() {
      if (!state.caps) return "still loading capabilities";
      if (currentLanguage() === "cpp") {
        return "C++ debugging needs a gdb integration that does not exist " +
          "yet — Python debugging works";
      }
      if (currentLanguage() !== "python") return "debugging applies to Python files";
      if (!state.caps.debug || !state.caps.debug.python) {
        return "debugging needs a process that can be suspended; the " +
          "browser build cannot do that — use the server build";
      }
      return null;
    },

    async start() {
      const path = state.active;
      const entry = editors.get(path);
      if (!entry) return;
      if (Settings.get("run.saveBeforeRun") && state.dirty.get(path)) {
        await saveFile(path);
      }
      this.stop();
      const r = await api("POST", "/api/debug", {
        code: entry.editor.getValue(),
        filename: path.split("/").pop(),
        breakpoints: state.breakpoints[path] || [],
      });
      if (!r || !r.id) return;
      this.id = r.id;
      this.cursor = 0;
      this.path = path;
      this.stopped = null;
      $("#dbgLog").innerHTML = "";
      showPanel("debug");
      this.log("debugging " + path + " — breakpoints: " +
        ((state.breakpoints[path] || []).join(", ") || "none"), "dim");
      renderRunDebug();
      this.poll();
    },

    async poll() {
      if (!this.id) return;
      let r;
      try {
        r = await api("GET", "/api/debug/" + this.id + "?since=" + this.cursor);
      } catch (e) { r = null; }
      if (!this.id) return;
      if (r && r.events) {
        this.cursor = r.cursor;
        r.events.forEach((ev) => this.handle(ev));
      }
      if (this.id) this.timer = setTimeout(() => this.poll(), 160);
    },

    handle(ev) {
      if (ev.event === "output") {
        this.log(ev.data.replace(/\n$/, ""),
                 ev.stream === "stderr" ? "err" : "");
      } else if (ev.event === "stopped") {
        this.stopped = ev;
        this.log("⏸ stopped at line " + ev.line + " (" + ev.reason + ")", "warn");
        const entry = editors.get(this.path);
        if (entry) {
          openFile(this.path).then(() => entry.editor.revealLine(ev.line, 1));
        }
        renderRunDebug();
      } else if (ev.event === "eval") {
        this.log((ev.ok ? "= " : "! ") + ev.value, ev.ok ? "ok" : "err");
      } else if (ev.event === "exited") {
        this.log("exited with code " + ev.code, ev.code === 0 ? "ok" : "err");
        this.id = null;
        this.stopped = null;
        renderRunDebug();
      }
    },

    command(op, extra) {
      if (!this.id) return;
      this.stopped = null;
      renderRunDebug();
      api("POST", "/api/debug/" + this.id + "/cmd", { op, ...(extra || {}) });
    },

    stop() {
      if (this.timer) clearTimeout(this.timer);
      if (this.id) api("DELETE", "/api/debug/" + this.id);
      this.id = null;
      this.stopped = null;
      renderRunDebug();
    },

    log(text, cls) {
      const host = $("#dbgLog");
      if (!host || text === "") return;
      host.appendChild(el("div", "wb-out " + (cls || ""), text));
      host.scrollTop = host.scrollHeight;
    },
  };

  /* the Run & Debug sidebar view */
  function renderRunDebug() {
    const host = $("#runDebugBody");
    if (!host) return;
    host.innerHTML = "";

    const controls = el("div", "wb-dbg-controls");
    const btn = (ico, label, title, run, disabled, cls) => {
      const b = el("button", "wb-btn" + (cls ? " " + cls : ""));
      if (ico) b.appendChild(icon(ico, 14));
      if (label) b.appendChild(el("span", "", label));
      b.title = title;
      b.disabled = !!disabled;
      b.onclick = run;
      controls.appendChild(b);
    };
    if (!dbg.id) {
      const reason = dbg.reason();
      btn("play", "Start Debugging", reason || "F6",
          () => Commands.execute("debug.start"), !!reason,
          reason ? "" : "primary");
      if (reason) controls.appendChild(el("div", "wb-hint", reason));
    } else if (dbg.stopped) {
      btn("resume", "", "Continue (F5)", () => dbg.command("continue"));
      btn("stepOver", "", "Step Over (F10)", () => dbg.command("next"));
      btn("stepInto", "", "Step Into (F11)", () => dbg.command("step"));
      btn("stepOut", "", "Step Out (Shift+F11)", () => dbg.command("return"));
      btn("stop", "", "Stop (Shift+F6)", () => dbg.stop(), false, "danger");
    } else {
      controls.appendChild(el("span", "wb-hint", "running…"));
      btn("stop", "", "Stop", () => dbg.stop(), false, "danger");
    }
    host.appendChild(controls);

    if (dbg.stopped) {
      const vars = el("div", "wb-dbg-section");
      vars.appendChild(el("div", "wb-side-head", "Variables"));
      Object.entries(dbg.stopped.locals || {}).forEach(([k, v]) => {
        const row = el("div", "wb-dbg-var");
        row.appendChild(el("span", "wb-dbg-k", k));
        row.appendChild(el("span", "wb-dbg-v", v));
        vars.appendChild(row);
      });
      host.appendChild(vars);

      const stack = el("div", "wb-dbg-section");
      stack.appendChild(el("div", "wb-side-head", "Call Stack"));
      (dbg.stopped.stack || []).forEach((f) => {
        stack.appendChild(el("div", "wb-dbg-frame",
          f.name + "  :" + f.line));
      });
      host.appendChild(stack);

      const evalRow = el("div", "wb-dbg-evalrow");
      const input = el("input", "wb-input");
      input.placeholder = "evaluate in this frame…";
      input.onkeydown = (ev) => {
        if (ev.key === "Enter" && input.value.trim()) {
          dbg.log("? " + input.value, "dim");
          dbg.command("eval", { expr: input.value });
          input.value = "";
        }
      };
      evalRow.appendChild(input);
      host.appendChild(evalRow);
    }

    const bps = el("div", "wb-dbg-section");
    bps.appendChild(el("div", "wb-side-head", "Breakpoints"));
    let any = false;
    Object.entries(state.breakpoints).forEach(([path, lines]) => {
      (lines || []).forEach((line) => {
        any = true;
        const row = el("div", "wb-dbg-bp");
        row.appendChild(el("span", "wb-dbg-bpdot"));
        row.appendChild(el("span", null, path + ":" + line));
        row.onclick = () => openFile(path).then(() => {
          const entry = editors.get(path);
          if (entry) entry.editor.revealLine(line, 1);
        });
        const x = iconButton("close", "Remove breakpoint", null,
                             "wb-icon-btn", 13);
        x.onclick = (ev) => {
          ev.stopPropagation();
          const entry = editors.get(path);
          if (entry) entry.editor.toggleBreakpoint(line);
          else {
            state.breakpoints[path] =
              (state.breakpoints[path] || []).filter((l) => l !== line);
            writeJSON("epsilon.breakpoints.v1", state.breakpoints);
            renderRunDebug();
          }
        };
        row.appendChild(x);
        bps.appendChild(row);
      });
    });
    if (!any) bps.appendChild(el("div", "wb-hint",
      "Click in the editor gutter, left of a line number, to set one."));
    host.appendChild(bps);
  }

  /* =================================================================
   * Search view (find & replace in files)
   * ================================================================= */
  const searchState = { query: "", replace: "", regex: false, case: false,
                        word: false, results: [], truncated: false };

  async function runSearch() {
    if (!searchState.query) {
      searchState.results = [];
      renderSearchResults();
      return;
    }
    const r = await api("POST", "/api/search", {
      query: searchState.query, regex: searchState.regex,
      case: searchState.case, word: searchState.word,
    });
    if (r.ok === false) {
      searchState.results = [];
      renderSearchResults(r.message);
      return;
    }
    searchState.results = r.results || [];
    searchState.truncated = !!r.truncated;
    renderSearchResults();
  }

  function renderSearchResults(errorMessage) {
    const host = $("#searchResults");
    if (!host) return;
    host.innerHTML = "";
    if (errorMessage) {
      host.appendChild(el("div", "wb-hint err", errorMessage));
      return;
    }
    const results = searchState.results;
    if (!results.length) {
      host.appendChild(el("div", "wb-empty",
        searchState.query ? "No results." : "Type to search the workspace."));
      return;
    }
    const byFile = new Map();
    results.forEach((r) => {
      if (!byFile.has(r.path)) byFile.set(r.path, []);
      byFile.get(r.path).push(r);
    });
    const summary = el("div", "wb-hint",
      results.length + " result" + (results.length === 1 ? "" : "s") +
      " in " + byFile.size + " file" + (byFile.size === 1 ? "" : "s") +
      (searchState.truncated ? " (truncated at 2000)" : ""));
    host.appendChild(summary);
    byFile.forEach((rows, path) => {
      const group = el("div", "wb-search-file");
      const head = el("div", "wb-prob-head", path);
      head.appendChild(el("span", "wb-badge", String(rows.length)));
      group.appendChild(head);
      rows.slice(0, 200).forEach((r) => {
        const row = el("div", "wb-search-row");
        row.tabIndex = 0;
        const pre = r.preview;
        const before = esc(pre.slice(0, r.col));
        const match = esc(pre.slice(r.col, r.col + r.length));
        const after = esc(pre.slice(r.col + r.length));
        row.innerHTML = '<span class="wb-search-ln">' + r.line + "</span>" +
          '<span class="wb-search-text">' + before +
          "<mark>" + match + "</mark>" + after + "</span>";
        const jump = () => openFile(path).then(() => {
          const entry = editors.get(path);
          if (entry) {
            entry.editor.revealLine(r.line, r.col + 1);
            const at = entry.editor.input.selectionStart;
            entry.editor.setSelection(at, at + r.length);
          }
        });
        row.onclick = jump;
        row.onkeydown = (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); jump(); }
        };
        group.appendChild(row);
      });
      host.appendChild(group);
    });
  }

  async function replaceAllInFiles() {
    if (!searchState.query) return;
    const count = searchState.results.length;
    if (!count) return;
    if (!confirm("Replace " + count + " occurrence" +
        (count === 1 ? "" : "s") + " across the workspace?")) return;
    const r = await api("POST", "/api/replace", {
      query: searchState.query, replacement: searchState.replace,
      regex: searchState.regex, case: searchState.case,
      word: searchState.word,
    });
    if (r.ok === false) return;
    notify("Replaced " + r.replacements + " occurrences in " +
      Object.keys(r.files || {}).length + " files", "ok");
    // reload any open editors whose file changed under them
    for (const path of Object.keys(r.files || {})) {
      const entry = editors.get(path);
      if (entry && !state.dirty.get(path)) {
        const f = await api("GET", "/api/file?path=" + encodeURIComponent(path));
        entry.editor.setValue(f.content || "");
        entry.saved = f.content || "";
      }
    }
    runSearch();
    refreshGit();
  }

  /* =================================================================
   * Source Control view
   * ================================================================= */
  const git = { status: null, log: [] };

  async function refreshGit() {
    if (!state.caps || !state.caps.git) { renderGit(); return; }
    git.status = await api("GET", "/api/git/status");
    if (git.status && git.status.repo) {
      const lg = await api("GET", "/api/git/log?limit=12");
      git.log = (lg && lg.entries) || [];
    }
    renderGit();
    renderStatusbar();
  }

  function renderGit() {
    const host = $("#scmBody");
    if (!host) return;
    host.innerHTML = "";
    if (!state.caps || !state.caps.git) {
      host.appendChild(el("div", "wb-empty",
        "Git is not available in the browser build — the server build " +
        "(epsilon serve) has full source control."));
      return;
    }
    const st = git.status;
    if (!st) { host.appendChild(el("div", "wb-empty", "…")); return; }
    if (!st.repo) {
      const b = el("button", "wb-btn wide", "Initialize Repository");
      b.onclick = async () => {
        await api("POST", "/api/git/init");
        refreshGit();
      };
      host.appendChild(b);
      return;
    }

    const msgRow = el("div", "wb-scm-commitrow");
    const msg = el("textarea", "wb-input wb-scm-msg");
    msg.placeholder = "Commit message (Ctrl+Enter to commit staged)";
    msg.rows = 2;
    msg.value = git.pendingMessage || "";
    msg.oninput = () => { git.pendingMessage = msg.value; };
    msg.onkeydown = (ev) => {
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "Enter") {
        ev.preventDefault();
        commitStaged();
      }
    };
    msgRow.appendChild(msg);
    const commitBtn = el("button", "wb-btn primary wide");
    commitBtn.appendChild(icon("check", 14));
    commitBtn.appendChild(el("span", "", "Commit"));
    commitBtn.onclick = commitStaged;
    msgRow.appendChild(commitBtn);
    host.appendChild(msgRow);

    const staged = (st.changes || []).filter((c) => c.staged);
    const unstaged = (st.changes || []).filter((c) => c.unstaged || !c.staged);
    const section = (title, items, stagedList) => {
      if (!items.length) return;
      const box = el("div", "wb-scm-section");
      const head = el("div", "wb-side-head", title);
      head.appendChild(el("span", "wb-badge", String(items.length)));
      box.appendChild(head);
      items.forEach((c) => {
        const row = el("div", "wb-scm-row");
        row.appendChild(el("span", "wb-scm-status s-" +
          (c.status || "M").slice(0, 1), (c.status || "M").slice(0, 2)));
        const name = el("span", "wb-scm-path", c.path);
        name.title = "Show diff";
        name.onclick = () => showDiff(c.path, stagedList);
        row.appendChild(name);
        const act = iconButton(stagedList ? "minus" : "plus",
                               stagedList ? "Unstage" : "Stage", null,
                               "wb-icon-btn", 14);
        act.title = stagedList ? "Unstage" : "Stage";
        act.onclick = async () => {
          await api("POST", "/api/git/" + (stagedList ? "unstage" : "stage"),
                    { paths: [c.path] });
          refreshGit();
        };
        row.appendChild(act);
        if (!stagedList) {
          const undo = el("button", "wb-icon-btn", "↺");
          undo.title = "Discard changes";
          undo.onclick = async () => {
            if (!confirm("Discard changes to " + c.path + "? This cannot " +
                         "be undone.")) return;
            await api("POST", "/api/git/discard", { paths: [c.path] });
            const entry = editors.get(c.path);
            if (entry) {
              const f = await api("GET",
                "/api/file?path=" + encodeURIComponent(c.path));
              if (f && f.content != null) {
                entry.editor.setValue(f.content);
                entry.saved = f.content;
                state.dirty.set(c.path, false);
                EpsilonPanes.setDirty(c.path, false);
              }
            }
            refreshGit();
          };
          row.appendChild(undo);
        }
        box.appendChild(row);
      });
      host.appendChild(box);
    };
    section("Staged Changes", staged, true);
    section("Changes", unstaged, false);
    if (!st.changes.length) {
      host.appendChild(el("div", "wb-hint", "Nothing to commit — clean."));
    }

    if (git.log.length) {
      const box = el("div", "wb-scm-section");
      box.appendChild(el("div", "wb-side-head", "History"));
      git.log.forEach((entry) => {
        const row = el("div", "wb-scm-log");
        row.appendChild(el("code", "wb-scm-hash", entry.hash));
        row.appendChild(el("span", "wb-scm-sub", entry.subject));
        row.title = entry.author + ", " + entry.date;
        box.appendChild(row);
      });
      host.appendChild(box);
    }
  }

  async function commitStaged() {
    const message = (git.pendingMessage || "").trim();
    if (!message) { notify("A commit needs a message", "warn"); return; }
    const r = await api("POST", "/api/git/commit", { message });
    if (r.ok) {
      git.pendingMessage = "";
      notify("Committed " + r.hash, "ok");
      refreshGit();
    }
  }

  async function showDiff(path, staged) {
    const r = await api("GET", "/api/git/diff?path=" +
      encodeURIComponent(path) + (staged ? "&staged=true" : ""));
    if (!r.ok) return;
    openSpecial("diff://" + path, "Δ " + path.split("/").pop(), (host) => {
      const pre = el("pre", "wb-diff");
      (r.diff || "(no differences)").split("\n").forEach((line) => {
        const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
          : line.startsWith("-") && !line.startsWith("---") ? "del"
          : line.startsWith("@@") ? "hunk" : "";
        pre.appendChild(el("div", "wb-diff-line " + cls, line || " "));
      });
      host.appendChild(pre);
    }, { refresh: true });
  }

  /* =================================================================
   * Special tabs (settings, shortcuts, diffs) — views in the editor area
   * ================================================================= */
  function openSpecial(id, title, build, opts = {}) {
    if (SPECIAL.has(id) && !opts.refresh) {
      EpsilonPanes.openView(id);
      state.active = id;
      refreshChrome();
      return;
    }
    let record = SPECIAL.get(id);
    if (!record) {
      const host = el("div", "wb-special");
      record = { title, host };
      SPECIAL.set(id, record);
      EpsilonPanes.registerView(id, {
        title, element: host, closable: true,
        onShow: () => { state.active = id; refreshChrome(); },
        onClose: () => SPECIAL.delete(id),
      });
    }
    record.host.innerHTML = "";
    build(record.host);
    EpsilonPanes.openView(id);
    state.active = id;
    refreshChrome();
  }

  /* =================================================================
   * Settings UI — a searchable editor-area tab
   * ================================================================= */
  function openSettingsUI(filter) {
    openSpecial("epsilon://settings", "Settings", (host) => {
      host.classList.add("wb-settings");
      const top = el("div", "wb-settings-top");
      const search = el("input", "wb-input");
      search.placeholder = "Search settings";
      search.value = filter || "";
      search.setAttribute("aria-label", "Search settings");
      top.appendChild(search);
      host.appendChild(top);

      const layout = el("div", "wb-settings-layout");
      const nav = el("nav", "wb-settings-nav");
      const body = el("div", "wb-settings-body");
      layout.appendChild(nav);
      layout.appendChild(body);
      host.appendChild(layout);

      const render = () => {
        const needle = search.value.trim().toLowerCase();
        nav.innerHTML = "";
        body.innerHTML = "";
        const cats = Settings.categories();
        const visible = Settings.all().filter((d) =>
          !needle || (d.title + " " + d.id + " " + (d.description || ""))
            .toLowerCase().includes(needle));
        cats.forEach((cat) => {
          const items = visible.filter((d) => d.category === cat);
          if (!items.length) return;
          const link = el("button", "wb-settings-cat", cat);
          link.onclick = () => {
            const target = body.querySelector('[data-cat="' + cat + '"]');
            if (target) target.scrollIntoView({ block: "start" });
          };
          nav.appendChild(link);
          const section = el("section");
          section.dataset.cat = cat;
          section.appendChild(el("h2", "wb-settings-h", cat));
          items.forEach((d) => section.appendChild(settingRow(d)));
          body.appendChild(section);
        });
        if (!visible.length) {
          body.appendChild(el("div", "wb-empty",
            "No setting matches “" + search.value + "”."));
        }
      };
      search.oninput = render;
      render();
      setTimeout(() => search.focus(), 0);
    }, { refresh: true });
  }

  function settingRow(d) {
    const row = el("div", "wb-setting");
    const label = el("div", "wb-setting-label");
    label.appendChild(el("span", "wb-setting-title", d.title));
    if (Settings.isModified(d.id)) {
      const reset = el("button", "wb-setting-reset", "reset");
      reset.title = "Back to the default (" + d.default + ")";
      reset.onclick = () => { Settings.reset(d.id); openSettingsUI(); };
      label.appendChild(reset);
    }
    row.appendChild(label);
    if (d.description) row.appendChild(el("div", "wb-setting-desc", d.description));

    const value = Settings.get(d.id);
    let control;
    if (d.type === "boolean") {
      control = el("input");
      control.type = "checkbox";
      control.checked = !!value;
      control.onchange = () => Settings.set(d.id, control.checked);
    } else if (d.type === "enum") {
      control = el("select", "wb-input");
      (d.options || []).forEach((opt) => {
        const o = el("option", null, opt);
        o.value = opt;
        if (opt === value) o.selected = true;
        control.appendChild(o);
      });
      control.onchange = () => Settings.set(d.id, control.value);
    } else {
      control = el("input", "wb-input");
      control.type = d.type === "number" ? "number" : "text";
      control.value = value == null ? "" : value;
      control.onchange = () => Settings.set(d.id, control.value);
    }
    control.setAttribute("aria-label", d.title);
    const controlRow = el("div", "wb-setting-control");
    controlRow.appendChild(control);
    row.appendChild(controlRow);
    return row;
  }

  /* =================================================================
   * Keyboard shortcuts UI — rebind by capturing the next chord
   * ================================================================= */
  function openShortcutsUI() {
    openSpecial("epsilon://shortcuts", "Keyboard Shortcuts", (host) => {
      host.classList.add("wb-shortcuts");
      const top = el("div", "wb-settings-top");
      const search = el("input", "wb-input");
      search.placeholder = "Search commands";
      top.appendChild(search);
      host.appendChild(top);
      const list = el("div", "wb-keys-list");
      host.appendChild(list);

      const render = () => {
        const needle = search.value.trim().toLowerCase();
        list.innerHTML = "";
        const head = el("div", "wb-keys-row head");
        head.appendChild(el("span", null, "Command"));
        head.appendChild(el("span", null, "Keybinding"));
        head.appendChild(el("span", null, ""));
        list.appendChild(head);
        Commands.all()
          .filter((c) => !needle ||
            (c.title + " " + c.id).toLowerCase().includes(needle))
          .sort((a, b) => a.title.localeCompare(b.title))
          .forEach((c) => {
            const row = el("div", "wb-keys-row");
            const name = el("span", "wb-keys-name", c.title);
            name.title = c.id;
            row.appendChild(name);
            const chord = Keys.chordOf(c.id);
            const key = el("button", "wb-keys-chord" +
              (Keys.isUser(c.id) ? " user" : ""), chord || "—");
            key.title = "Click, then press the new keybinding " +
              "(Escape cancels, Backspace unbinds)";
            key.onclick = () => captureChord(c.id, key, render);
            row.appendChild(key);
            const reset = el("button", "wb-icon-btn", "↺");
            reset.title = "Reset to default";
            reset.style.visibility = Keys.isUser(c.id) ? "" : "hidden";
            reset.onclick = () => { Keys.resetUser(c.id); render(); };
            row.appendChild(reset);
            list.appendChild(row);
          });
      };
      search.oninput = render;
      render();
      setTimeout(() => search.focus(), 0);
    }, { refresh: true });
  }

  function captureChord(commandId, button, done) {
    button.textContent = "press keys…";
    button.classList.add("capturing");
    const onKey = (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      if (ev.key === "Escape") { cleanup(); done(); return; }
      if (ev.key === "Backspace") {
        Keys.setUser(commandId, null);
        cleanup(); done(); return;
      }
      const chord = Keys.fromEvent(ev);
      if (!chord) return;                 // a bare modifier: keep waiting
      const holder = Keys.resolve(chord);
      if (holder && holder !== commandId) {
        const other = Commands.get(holder);
        if (!confirm('"' + chord + '" is bound to “' +
            (other ? other.title : holder) + "”. Move it here?")) {
          cleanup(); done(); return;
        }
        Keys.setUser(holder, null);
      }
      Keys.setUser(commandId, chord);
      cleanup();
      done();
    };
    const cleanup = () => {
      window.removeEventListener("keydown", onKey, true);
      button.classList.remove("capturing");
    };
    window.addEventListener("keydown", onKey, true);
  }

  /* =================================================================
   * Command palette & quick open
   * ================================================================= */
  const palette = { open: false, mode: "cmd", sel: 0, items: [] };

  function openPalette(mode, preset) {
    palette.open = true;
    palette.mode = mode;
    palette.sel = 0;
    const overlay = $("#paletteOverlay");
    overlay.classList.remove("hidden");
    const input = $("#paletteInput");
    input.value = preset != null ? preset : (mode === "cmd" ? ">" : "");
    input.placeholder = mode === "cmd"
      ? "Type a command…" : "Go to file (: for line, @ for symbol)…";
    input.focus();
    renderPalette();
  }

  function closePalette() {
    palette.open = false;
    $("#paletteOverlay").classList.add("hidden");
    const entry = currentEditor();
    if (entry) entry.editor.focus();
  }

  function paletteQuery() {
    const raw = $("#paletteInput").value;
    if (raw.startsWith(">")) return { kind: "cmd", q: raw.slice(1).trim() };
    if (raw.startsWith("@")) return { kind: "symbol", q: raw.slice(1).trim() };
    const gotoMatch = /^:(\d+)$/.exec(raw.trim());
    if (gotoMatch) return { kind: "line", q: gotoMatch[1] };
    const fileLine = /^([^:]+):(\d+)$/.exec(raw.trim());
    if (fileLine) return { kind: "file", q: fileLine[1], line: +fileLine[2] };
    return { kind: "file", q: raw.trim() };
  }

  function paletteItems() {
    const { kind, q, line } = paletteQuery();
    if (kind === "line") {
      return [{ label: "Go to line " + q, hint: "", run: () => {
        const entry = currentEditor();
        if (entry) entry.editor.revealLine(Number(q), 1);
      } }];
    }
    if (kind === "symbol") {
      return documentSymbols().map((s) => ({
        label: s.name, hint: s.kind + "  :" + s.line, run: () => {
          const entry = currentEditor();
          if (entry) entry.editor.revealLine(s.line, 1);
        },
        score: q ? (fuzzy(q, s.name) || { score: -1 }).score : 0,
      })).filter((i) => i.score >= 0);
    }
    if (kind === "cmd") {
      const source = q ? Commands.all()
        : Commands.recentIds().map((id) => Commands.get(id))
            .concat(Commands.all().filter((c) =>
              !Commands.recentIds().includes(c.id)));
      return source
        .filter((c) => c && c.inPalette)
        .map((c) => {
          const text = c.category + ": " + c.title;
          const m = q ? fuzzy(q, text) || fuzzy(q, c.aliases.join(" "))
            : { score: 0, positions: [] };
          if (!m) return null;
          const reason = c.whyDisabled();
          return {
            label: text, key: Keys.label(c.id), disabled: !!reason,
            hint: reason || c.description || "", score: m.score,
            run: () => Commands.execute(c.id),
          };
        })
        .filter(Boolean);
    }
    return state.entries
      .filter((entry) => entry.kind === "file")
      .map((entry) => {
        const m = q ? fuzzy(q, entry.path) : { score: 0 };
        if (!m) return null;
        return { label: entry.path, hint: "", score: m.score,
                 run: () => openFile(entry.path).then(() => {
                   if (line) {
                     const ed = editors.get(entry.path);
                     if (ed) ed.editor.revealLine(line, 1);
                   }
                 }) };
      })
      .filter(Boolean);
  }

  function renderPalette() {
    const list = $("#paletteList");
    list.innerHTML = "";
    palette.items = paletteItems()
      .sort((a, b) => (b.score || 0) - (a.score || 0))
      .slice(0, 40);
    if (palette.sel >= palette.items.length) palette.sel = 0;
    palette.items.forEach((item, i) => {
      const row = el("div", "wb-pal-item" +
        (i === palette.sel ? " sel" : "") + (item.disabled ? " disabled" : ""));
      row.setAttribute("role", "option");
      const label = el("span", "wb-pal-label", item.label);
      row.appendChild(label);
      if (item.key) row.appendChild(el("span", "wb-pal-key", item.key));
      if (item.hint) row.appendChild(el("span", "wb-pal-hint", item.hint));
      row.onmousedown = (ev) => {
        ev.preventDefault();
        palette.sel = i;
        acceptPalette();
      };
      list.appendChild(row);
    });
    if (!palette.items.length) {
      list.appendChild(el("div", "wb-empty", "No matches."));
    }
  }

  function acceptPalette() {
    const item = palette.items[palette.sel];
    if (!item) return;
    if (item.disabled) {
      notify(item.hint || "That command is not available here", "warn");
      return;
    }
    closePalette();
    item.run();
  }

  /** Lexical document symbols: def/class/function per language. */
  function documentSymbols() {
    const entry = currentEditor();
    if (!entry) return [];
    const text = entry.editor.getValue();
    const lang = currentLanguage();
    const out = [];
    const push = (name, kind, line) => out.push({ name, kind, line });
    text.split("\n").forEach((lineText, i) => {
      if (lang === "python") {
        const m = /^\s*(def|class)\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(lineText);
        if (m) push(m[2], m[1] === "def" ? "function" : "class", i + 1);
      } else if (lang === "cpp" || lang === "javascript") {
        let m = /^\s*(?:class|struct)\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(lineText);
        if (m) { push(m[1], "class", i + 1); return; }
        m = /^[A-Za-z_][\w:<>,*&\s]*\s+([A-Za-z_][A-Za-z0-9_]*)\s*\([^;]*$/
          .exec(lineText);
        if (m && !/^\s*(if|for|while|switch|return)\b/.test(lineText)) {
          push(m[1], "function", i + 1);
        }
        m = /^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)/.exec(lineText);
        if (m) push(m[1], "function", i + 1);
      }
    });
    return out;
  }

  /* =================================================================
   * Dependency graph
   *
   * What refers to what inside the active file. It opens as an editor
   * tab rather than a side panel because a graph needs room, and it
   * reads the buffer on demand rather than on every keystroke — laying
   * out a graph while someone is typing is work nobody asked for.
   * ================================================================= */
  const graphState = {
    kinds: new Set(readJSON("epsilon.graph.kinds.v1",
      ["module", "class", "function", "variable", "import"])),
    handle: null,
  };

  function graphDisabledReason() {
    if (!state.active || SPECIAL.has(state.active)) return "no file is active";
    const lang = currentLanguage();
    if (lang === "python" || lang === "cpp") return null;
    return "dependency analysis reads Python with its own parser and C++ " +
      "lexically; " + (LANGUAGE_LABEL[lang] || lang) + " has neither yet";
  }

  function openGraph(forPath) {
    const path = forPath || state.active;
    const entry = editors.get(path);
    if (!entry) return;
    openSpecial("epsilon://graph", "Dependencies", (host) => {
      host.className = "wb-special wb-graph";
      const bar = el("div", "wb-graph-bar");
      const title = el("div", "wb-graph-title");
      title.appendChild(el("span", "wb-graph-file", tabTitle(path)));
      const level = el("span", "wb-graph-level");
      title.appendChild(level);
      bar.appendChild(title);

      EpsilonGraph.KIND_ORDER.forEach((kind) => {
        const on = graphState.kinds.has(kind);
        const chip = el("button",
          "wb-chip wb-graph-kind kind-" + kind + (on ? " active" : ""),
          EpsilonGraph.KIND_LABEL[kind]);
        chip.setAttribute("aria-pressed", String(on));
        chip.onclick = () => {
          if (on) graphState.kinds.delete(kind);
          else graphState.kinds.add(kind);
          writeJSON("epsilon.graph.kinds.v1", Array.from(graphState.kinds));
          openGraph(path);
        };
        bar.appendChild(chip);
      });
      bar.appendChild(iconButton("refresh", "Rebuild from the current buffer",
                                 () => openGraph(path), "wb-icon-btn", 15));
      host.appendChild(bar);

      const canvas = el("div", "wb-graph-canvas");
      const legend = el("div", "wb-graph-legend");
      host.appendChild(canvas);
      host.appendChild(legend);
      canvas.appendChild(el("div", "wb-empty", "Reading the file…"));

      api("POST", "/api/graph", {
        language: languageOf(path), code: entry.editor.getValue(),
        line: 1, col: 0, path,
      }).then((data) => {
        if (!data) return;
        level.className = "wb-graph-level " + (data.level || "");
        level.textContent = data.level === "lexical"
          ? "lexical — without a compiler front-end, overloads and scope "
            + "are not resolved"
          : data.level === "semantic"
            ? "read with the language's own parser" : "";
        canvas.innerHTML = "";
        if (data.ok === false) {
          canvas.appendChild(el("div", "wb-empty",
            data.message || "This file could not be analysed."));
          return;
        }
        graphState.handle = EpsilonGraph.render(canvas, data, {
          filter: graphState.kinds,
          onSelect: (node) => openFile(path).then(() => {
            const target = editors.get(path);
            if (target) target.editor.revealLine(node.line, 1);
          }),
        });
        legend.innerHTML = "";
        const counts = (graphState.handle && graphState.handle.counts) || {};
        EpsilonGraph.KIND_ORDER.forEach((kind) => {
          if (!counts[kind]) return;
          const item = el("span", "wb-graph-legend-item kind-" + kind);
          item.appendChild(el("i", "wb-graph-swatch"));
          item.appendChild(el("span", "", counts[kind] + " " +
            EpsilonGraph.KIND_LABEL[kind] + (counts[kind] === 1 ? "" : "s")));
          legend.appendChild(item);
        });
        const edges = (data.edges || []).length;
        legend.appendChild(el("span", "wb-graph-legend-item dim",
          edges + " reference" + (edges === 1 ? "" : "s")));
      });
    }, { refresh: true });
  }

  /* =================================================================
   * Commands — the single registry every surface reads
   * ================================================================= */
  function editorCmd(id, title, action, chord, category) {
    Commands.register({
      id, title, category: category || "Edit",
      run: () => {
        const entry = currentEditor();
        if (entry) entry.editor.exec(action);
      },
      whyDisabled: () => currentEditor() ? null : "no editor is active",
    });
    if (chord) Keys.registerDefault(id, chord);
  }

  function needsEditor() {
    return currentEditor() ? null : "no editor is active";
  }

  function registerCommands() {
    const C = Commands.register;
    const K = Keys.registerDefault;

    /* ---- File ---- */
    C({ id: "file.new", title: "New File…", category: "File",
        run: () => newFile() });
    K("file.new", "Mod+N");
    C({ id: "file.newFolder", title: "New Folder…", category: "File",
        run: () => newFolder() });
    C({ id: "file.newProject", title: "New Project…", category: "File",
        run: newProject });
    C({ id: "file.open", title: "Go to File… (Quick Open)", category: "File",
        aliases: ["open file"], run: () => openPalette("file") });
    K("file.open", "Mod+P");
    C({ id: "file.save", title: "Save", category: "File",
        run: () => state.active && saveFile(state.active),
        whyDisabled: () => state.active && editors.has(state.active)
          ? null : "no file is active" });
    K("file.save", "Mod+S");
    C({ id: "file.saveAll", title: "Save All", category: "File",
        run: async () => {
          for (const [path, dirty] of state.dirty) {
            if (dirty) await saveFile(path);
          }
        } });
    K("file.saveAll", "Mod+Alt+S");
    C({ id: "file.close", title: "Close Editor", category: "File",
        run: () => state.active && EpsilonPanes.closeView(state.active),
        whyDisabled: () => state.active ? null : "nothing is open" });
    K("file.close", "Mod+W");
    C({ id: "file.reopenClosed", title: "Reopen Closed Editor",
        category: "File",
        run: () => {
          const path = state.closedTabs.pop();
          if (path) openFile(path);
        },
        whyDisabled: () => state.closedTabs.length
          ? null : "no editor has been closed" });
    K("file.reopenClosed", "Mod+Shift+T");
    C({ id: "file.closeAll", title: "Close All Editors", category: "File",
        run: () => Array.from(editors.keys())
          .forEach((p) => EpsilonPanes.closeView(p)) });
    C({ id: "file.exportDownload", title: "Export: Download Active File",
        category: "File",
        run: () => {
          const entry = currentEditor();
          if (!entry) return;
          const blob = new Blob([entry.editor.getValue()],
                                { type: "text/plain" });
          const a = document.createElement("a");
          a.href = URL.createObjectURL(blob);
          a.download = tabTitle(state.active);
          a.click();
          URL.revokeObjectURL(a.href);
        },
        whyDisabled: needsEditor });

    /* ---- Edit ---- */
    C({ id: "edit.undo", title: "Undo", category: "Edit",
        run: () => { const entry = currentEditor();
          if (entry) { entry.editor.focus(); document.execCommand("undo"); } },
        whyDisabled: needsEditor });
    C({ id: "edit.redo", title: "Redo", category: "Edit",
        run: () => { const entry = currentEditor();
          if (entry) { entry.editor.focus(); document.execCommand("redo"); } },
        whyDisabled: needsEditor });
    C({ id: "edit.cut", title: "Cut", category: "Edit",
        run: () => document.execCommand("cut"), whyDisabled: needsEditor });
    C({ id: "edit.copy", title: "Copy", category: "Edit",
        run: () => document.execCommand("copy"), whyDisabled: needsEditor });
    C({ id: "edit.paste", title: "Paste", category: "Edit",
        run: async () => {
          const entry = currentEditor();
          if (!entry || !navigator.clipboard) return;
          try {
            const text = await navigator.clipboard.readText();
            entry.editor.insertText(text);
          } catch (e) {
            notify("The browser refused clipboard access — use " +
                   (isMac ? "⌘V" : "Ctrl+V"), "warn");
          }
        }, whyDisabled: needsEditor });
    editorCmd("edit.selectAll", "Select All", "selectAll");
    editorCmd("edit.find", "Find", "find", "Mod+F");
    editorCmd("edit.replace", "Replace", "replace", "Mod+H");
    editorCmd("edit.findNext", "Find Next", "findNext", "F3");
    editorCmd("edit.findPrevious", "Find Previous", "findPrevious", "Shift+F3");
    C({ id: "edit.findInFiles", title: "Find in Files", category: "Edit",
        run: () => { showSidebar("search");
          setTimeout(() => $("#searchInput") && $("#searchInput").focus(), 0); } });
    K("edit.findInFiles", "Mod+Shift+F");
    C({ id: "edit.replaceInFiles", title: "Replace in Files", category: "Edit",
        run: () => { showSidebar("search");
          setTimeout(() => $("#searchReplace") && $("#searchReplace").focus(), 0); } });
    K("edit.replaceInFiles", "Mod+Shift+H");
    editorCmd("edit.toggleComment", "Toggle Line Comment", "toggleComment",
              "Mod+/");
    editorCmd("edit.indent", "Indent Lines", "indent");
    editorCmd("edit.dedent", "Outdent Lines", "dedent");
    editorCmd("edit.moveLinesUp", "Move Lines Up", "moveLinesUp", "Alt+ArrowUp");
    editorCmd("edit.moveLinesDown", "Move Lines Down", "moveLinesDown",
              "Alt+ArrowDown");
    editorCmd("edit.duplicateLines", "Duplicate Lines", "duplicateLines",
              "Mod+Shift+D");
    editorCmd("edit.deleteLines", "Delete Lines", "deleteLines", "Mod+Shift+K");
    C({ id: "edit.format", title: "Format Document", category: "Edit",
        run: async () => {
          const entry = currentEditor();
          if (!entry) return;
          const language = currentLanguage();
          const r = await api("POST", "/api/format",
                              { language, code: entry.editor.getValue() });
          if (!r.ok) { notify(r.message || "Could not format", "warn"); return; }
          const [s] = entry.editor.getSelection();
          entry.editor.setValue(r.code);
          entry.editor.setSelection(Math.min(s, r.code.length));
          entry.editor._afterEdit();
          notify("Formatted", "ok");
        },
        whyDisabled: () => {
          if (!currentEditor()) return "no editor is active";
          const language = currentLanguage();
          const tool = language === "python" ? "black"
            : language === "cpp" ? "clang-format" : null;
          if (!tool) return "no formatter exists for " +
            (LANGUAGE_LABEL[language] || language);
          if (state.caps && state.caps.format &&
              !state.caps.format[language]) {
            return tool + " is not available " +
              (state.caps.terminal ? "on this machine"
               : "in the browser build — use the server build");
          }
          return null;
        } });
    K("edit.format", "Shift+Alt+F");
    C({ id: "edit.autocomplete", title: "Trigger Suggest", category: "Edit",
        run: () => { const entry = currentEditor();
          if (entry) entry.editor.openCompletion(true); },
        whyDisabled: needsEditor });
    K("edit.autocomplete", "Mod+Space");

    /* ---- Selection ---- */
    editorCmd("selection.line", "Select Line", "selectLine", "Mod+L",
              "Selection");
    editorCmd("selection.word", "Select Word", "selectWord", null, "Selection");
    editorCmd("selection.nextOccurrence", "Select Next Occurrence",
              "selectNextOccurrence", "Mod+D", "Selection");
    const needsCursors = () => "multiple cursors need a custom text " +
      "surface the editor does not have yet (the platform textarea keeps " +
      "IME and accessibility working; a custom surface is planned)";
    C({ id: "selection.addCursorAbove", title: "Add Cursor Above",
        category: "Selection", run: () => {}, whyDisabled: needsCursors });
    C({ id: "selection.addCursorBelow", title: "Add Cursor Below",
        category: "Selection", run: () => {}, whyDisabled: needsCursors });
    C({ id: "selection.selectAllOccurrences",
        title: "Select All Occurrences", category: "Selection",
        run: () => {}, whyDisabled: needsCursors });

    /* ---- View ---- */
    C({ id: "view.commandPalette", title: "Command Palette",
        category: "View", run: () => openPalette("cmd") });
    K("view.commandPalette", "Mod+Shift+P");
    C({ id: "view.explorer", title: "Explorer", category: "View",
        run: () => showSidebar("explorer") });
    K("view.explorer", "Mod+Shift+E");
    C({ id: "view.search", title: "Search", category: "View",
        run: () => showSidebar("search") });
    C({ id: "view.scm", title: "Source Control", category: "View",
        run: () => showSidebar("scm") });
    K("view.scm", "Mod+Shift+G");
    C({ id: "view.runDebug", title: "Run and Debug", category: "View",
        run: () => showSidebar("rundebug") });
    C({ id: "view.extensions", title: "Extensions", category: "View",
        run: () => {},
        whyDisabled: () => "there is no extension host yet — extensions " +
          "are a later phase, and a fake marketplace would be worse than " +
          "none" });
    C({ id: "view.terminal", title: "Terminal", category: "View",
        run: () => togglePanel("terminal") });
    K("view.terminal", "Mod+`");
    C({ id: "view.problems", title: "Problems", category: "View",
        run: () => togglePanel("problems") });
    K("view.problems", "Mod+Shift+M");
    C({ id: "view.output", title: "Output", category: "View",
        run: () => togglePanel("output") });
    C({ id: "view.debugConsole", title: "Debug Console", category: "View",
        run: () => togglePanel("debug") });
    C({ id: "view.togglePanel", title: "Toggle Panel", category: "View",
        run: () => togglePanel() });
    K("view.togglePanel", "Mod+J");
    C({ id: "view.toggleSidebar", title: "Toggle Primary Sidebar",
        category: "View", run: toggleSidebar });
    K("view.toggleSidebar", "Mod+B");
    C({ id: "view.toggleAux", title: "Toggle Secondary Sidebar",
        category: "View", run: toggleAux });
    C({ id: "view.toggleStatusBar", title: "Toggle Status Bar",
        category: "View",
        run: () => Settings.set("workbench.statusBar",
          !Settings.get("workbench.statusBar")) });
    C({ id: "view.toggleActivityBar", title: "Toggle Activity Bar",
        category: "View",
        run: () => Settings.set("workbench.activityBar",
          !Settings.get("workbench.activityBar")) });
    C({ id: "view.splitRight", title: "Split Editor Right", category: "View",
        run: () => EpsilonPanes.splitPane("row"), whyDisabled: needsAnyTab });
    K("view.splitRight", "Mod+\\");
    C({ id: "view.splitDown", title: "Split Editor Down", category: "View",
        run: () => EpsilonPanes.splitPane("col"), whyDisabled: needsAnyTab });
    C({ id: "view.joinEditors", title: "Join All Editor Groups",
        category: "View", run: () => EpsilonPanes.joinAll() });
    C({ id: "view.fullscreen", title: "Full Screen", category: "View",
        run: () => document.fullscreenElement
          ? document.exitFullscreen()
          : document.documentElement.requestFullscreen() });
    K("view.fullscreen", "F11");
    C({ id: "view.zenMode", title: "Zen Mode", category: "View",
        run: toggleZen });
    K("view.zenMode", "Mod+K");
    C({ id: "view.theme", title: "Change Color Theme", category: "View",
        run: () => {
          const order = ["dark", "light", "high-contrast"];
          const current = Settings.get("workbench.theme");
          Settings.set("workbench.theme",
            order[(order.indexOf(current) + 1) % order.length]);
        } });

    function needsAnyTab() {
      return state.active ? null : "nothing is open to split";
    }

    /* ---- Go ---- */
    C({ id: "go.file", title: "Go to File…", category: "Go",
        run: () => openPalette("file"),
        description: "Jump to any file by name; ':42' goes to a line" });
    K("go.file", "Mod+P");
    C({ id: "go.symbol", title: "Go to Symbol in Editor…", category: "Go",
        run: () => openPalette("file", "@"), whyDisabled: needsEditor });
    K("go.symbol", "Mod+Shift+O");
    C({ id: "go.line", title: "Go to Line…", category: "Go",
        run: () => openPalette("file", ":"), whyDisabled: needsEditor });
    K("go.line", "Mod+G");
    C({ id: "view.graph", title: "Show Dependency Graph", category: "Go",
        run: () => openGraph(), whyDisabled: graphDisabledReason,
        description: "Which symbols in this file refer to which" });
    K("view.graph", "Mod+Shift+D");
    C({ id: "go.definition", title: "Go to Definition", category: "Go",
        run: goToDefinition, whyDisabled: () =>
          currentLanguage() === "python" ? null
            : "definition lookup is semantic for Python (jedi); other " +
              "languages have no language service yet" });
    K("go.definition", "F12");
    C({ id: "go.back", title: "Go Back", category: "Go",
        run: () => navGo(-1),
        whyDisabled: () => state.navIndex > 0 ? null : "no earlier location" });
    K("go.back", "Alt+ArrowLeft");
    C({ id: "go.forward", title: "Go Forward", category: "Go",
        run: () => navGo(1),
        whyDisabled: () => state.navIndex < state.navStack.length - 1
          ? null : "no later location" });
    K("go.forward", "Alt+ArrowRight");

    /* ---- Run ---- */
    C({ id: "run.file", title: "Run File", category: "Run",
        run: runCurrentFile, whyDisabled: runDisabledReason,
        description: "Run the active Python or C++ file" });
    K("run.file", "F5");
    C({ id: "run.withoutDebugging", title: "Run Without Debugging",
        category: "Run", run: runCurrentFile, whyDisabled: runDisabledReason });
    K("run.withoutDebugging", "Mod+F5");
    C({ id: "debug.start", title: "Start Debugging", category: "Run",
        run: () => dbg.start(), whyDisabled: () => dbg.reason() });
    K("debug.start", "F6");
    C({ id: "debug.stop", title: "Stop Debugging", category: "Run",
        run: () => dbg.stop(),
        whyDisabled: () => dbg.id ? null : "nothing is being debugged" });
    K("debug.stop", "Shift+F6");
    C({ id: "debug.continue", title: "Debug: Continue", category: "Run",
        run: () => dbg.command("continue"), whyDisabled: needsStopped });
    C({ id: "debug.stepOver", title: "Debug: Step Over", category: "Run",
        run: () => dbg.command("next"), whyDisabled: needsStopped });
    K("debug.stepOver", "F10");
    C({ id: "debug.stepInto", title: "Debug: Step Into", category: "Run",
        run: () => dbg.command("step"), whyDisabled: needsStopped });
    K("debug.stepInto", "F11");
    C({ id: "debug.stepOut", title: "Debug: Step Out", category: "Run",
        run: () => dbg.command("return"), whyDisabled: needsStopped });
    K("debug.stepOut", "Shift+F11");
    C({ id: "run.restart", title: "Restart Run", category: "Run",
        run: runCurrentFile, whyDisabled: runDisabledReason });
    C({ id: "run.configure", title: "Configure Run (timeout, save)",
        category: "Run", run: () => openSettingsUI("Run") });

    function needsStopped() {
      return dbg.id && dbg.stopped ? null
        : "the debugger is not stopped at a line";
    }

    /* ---- Terminal ---- */
    const noShell = () => state.caps && state.caps.terminal ? null
      : "there is no operating system to give a shell to in the browser " +
        "build — the server build has real terminals";
    C({ id: "terminal.new", title: "New Terminal", category: "Terminal",
        run: async () => { showPanel("terminal"); await term.create();
                           term.focusInput(); },
        whyDisabled: noShell });
    K("terminal.new", "Mod+Shift+`");
    C({ id: "terminal.kill", title: "Kill Terminal", category: "Terminal",
        run: () => term.active && term.kill(term.active),
        whyDisabled: () => term.active ? null : "no terminal is open" });
    C({ id: "terminal.clear", title: "Clear Terminal", category: "Terminal",
        run: () => term.clear(),
        whyDisabled: () => term.active ? null : "no terminal is open" });

    /* ---- Tools ---- */
    C({ id: "tools.settings", title: "Settings", category: "Tools",
        run: () => openSettingsUI() });
    K("tools.settings", "Mod+,");
    C({ id: "tools.shortcuts", title: "Keyboard Shortcuts", category: "Tools",
        run: openShortcutsUI });
    C({ id: "tools.reloadFiles", title: "Reload File Explorer",
        category: "Tools", run: loadFiles });

    /* ---- Help ---- */
    C({ id: "help.about", title: "About Epsilon", category: "Help",
        run: () => notify("Epsilon — a programming IDE in the browser. " +
          "Python and C++, for real. Mathematics returns as tooling later.",
          "info", [{ label: "Source",
            run: () => window.open("https://github.com/igangwoo/Epsilon") }]) });
  }

  /* =================================================================
   * Menu bar
   * ================================================================= */
  function registerMenus() {
    const M = Menus;
    M.addMenu("file", "File", 1);
    ["file.new", "file.newFolder", "file.newProject", null,
     "file.open", "recent", null,
     "file.save", "file.saveAll", null,
     "file.close", "file.closeAll", "file.reopenClosed", null,
     "file.exportDownload"].forEach((id) => M.addItem("file",
      id === null ? { separator: true }
        : id === "recent" ? { submenu: "Open Recent", recent: true }
        : { command: id }));

    M.addMenu("edit", "Edit", 2);
    ["edit.undo", "edit.redo", null, "edit.cut", "edit.copy", "edit.paste",
     "edit.selectAll", null, "edit.find", "edit.replace", "edit.findInFiles",
     "edit.replaceInFiles", null, "edit.toggleComment", "edit.format",
     "edit.autocomplete"].forEach((id) => M.addItem("edit",
      id === null ? { separator: true } : { command: id }));

    M.addMenu("selection", "Selection", 3);
    ["selection.line", "selection.word", "selection.nextOccurrence", null,
     "selection.selectAllOccurrences", "selection.addCursorAbove",
     "selection.addCursorBelow", null, "edit.moveLinesUp",
     "edit.moveLinesDown", "edit.duplicateLines", "edit.deleteLines"]
      .forEach((id) => M.addItem("selection",
        id === null ? { separator: true } : { command: id }));

    M.addMenu("view", "View", 4);
    ["view.commandPalette", null, "view.explorer", "view.search", "view.scm",
     "view.runDebug", "view.extensions", null, "view.terminal",
     "view.problems", "view.output", "view.debugConsole", null,
     "view.togglePanel", "view.toggleSidebar", "view.toggleAux",
     "view.toggleStatusBar", "view.toggleActivityBar", null,
     "view.splitRight", "view.splitDown", "view.joinEditors", null,
     "view.theme", "view.fullscreen", "view.zenMode"]
      .forEach((id) => M.addItem("view",
        id === null ? { separator: true } : { command: id }));

    M.addMenu("go", "Go", 5);
    ["go.back", "go.forward", null, "go.file", "go.symbol", "go.line",
     "view.graph", null,
     "go.definition"].forEach((id) => M.addItem("go",
      id === null ? { separator: true } : { command: id }));

    M.addMenu("run", "Run", 6);
    ["run.file", "run.withoutDebugging", "debug.start", "debug.stop",
     "run.restart", null, "debug.continue", "debug.stepOver",
     "debug.stepInto", "debug.stepOut", null, "run.configure"]
      .forEach((id) => M.addItem("run",
        id === null ? { separator: true } : { command: id }));

    M.addMenu("terminal", "Terminal", 7);
    ["terminal.new", "terminal.clear", "terminal.kill"]
      .forEach((id) => M.addItem("terminal", { command: id }));

    M.addMenu("tools", "Tools", 8);
    ["view.commandPalette", "tools.settings", "tools.shortcuts",
     "view.extensions", "tools.reloadFiles"]
      .forEach((id) => M.addItem("tools", { command: id }));

    M.addMenu("help", "Help", 9);
    ["help.about"].forEach((id) => M.addItem("help", { command: id }));
  }

  let openMenu = null;
  function renderMenubar() {
    const bar = $("#menubar");
    bar.innerHTML = "";
    Menus.bar().forEach((menu) => {
      const btn = el("button", "wb-menu-btn", menu.title);
      btn.setAttribute("aria-haspopup", "true");
      btn.setAttribute("role", "menuitem");
      btn.dataset.menu = menu.id;
      btn.onclick = (ev) => {
        ev.stopPropagation();
        if (openMenu === menu.id) hideMenus();
        else showMenu(menu, btn);
      };
      btn.onmouseenter = () => {
        if (openMenu && openMenu !== menu.id) showMenu(menu, btn);
      };
      // keyboard-only: ←/→ walk the bar, ↓ opens and enters the menu
      btn.onkeydown = (ev) => {
        const buttons = $$(".wb-menu-btn", bar);
        const i = buttons.indexOf(btn);
        if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {
          ev.preventDefault();
          const next = buttons[(i + (ev.key === "ArrowRight" ? 1 : buttons.length - 1))
                               % buttons.length];
          next.focus();
          if (openMenu) next.click();
        } else if (ev.key === "ArrowDown") {
          ev.preventDefault();
          if (openMenu !== menu.id) showMenu(menu, btn);
          focusFirstMenuItem();
        }
      };
      bar.appendChild(btn);
    });
  }

  /** Move focus into the open dropdown, so a menu is usable without a mouse. */
  function focusFirstMenuItem() {
    const first = $("#menuDrop .wb-menu-item:not(.disabled)");
    if (first) first.focus();
  }

  /** ↑/↓ inside a dropdown; Escape hands focus back to the menu bar. */
  function wireMenuKeys(drop, anchor) {
    drop.onkeydown = (ev) => {
      const items = $$(".wb-menu-item:not(.disabled)", drop);
      const i = items.indexOf(document.activeElement);
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const step = ev.key === "ArrowDown" ? 1 : items.length - 1;
        const next = items[(Math.max(0, i) + step) % items.length];
        if (next) next.focus();
      } else if (ev.key === "Enter" || ev.key === " ") {
        ev.preventDefault();
        if (document.activeElement) document.activeElement.click();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        hideMenus();
        if (anchor) anchor.focus();
      }
    };
  }

  function showMenu(menu, anchor) {
    hideMenus();
    openMenu = menu.id;
    anchor.classList.add("open");
    const drop = el("div", "wb-menu-drop");
    drop.setAttribute("role", "menu");
    menu.items.forEach((item) => {
      if (item.separator) {
        drop.appendChild(el("div", "wb-menu-sep"));
        return;
      }
      if (item.recent) {
        const sub = el("div", "wb-menu-item sub");
        sub.appendChild(el("span", "wb-menu-label", item.submenu));
        const chev = el("span", "wb-menu-key");
        chev.appendChild(icon("chevronRight", 13));
        sub.appendChild(chev);
        const subDrop = el("div", "wb-menu-drop nested");
        (state.recentFiles.length ? state.recentFiles : []).forEach((p) => {
          const row = el("div", "wb-menu-item");
          row.tabIndex = -1;
          row.appendChild(el("span", "wb-menu-label", p));
          row.onclick = () => { hideMenus(); openFile(p); };
          subDrop.appendChild(row);
        });
        if (!state.recentFiles.length) {
          subDrop.appendChild(el("div", "wb-menu-item disabled"))
            .appendChild(el("span", "wb-menu-label", "nothing yet"));
        }
        sub.appendChild(subDrop);
        drop.appendChild(sub);
        return;
      }
      const c = Commands.get(item.command);
      if (!c) return;
      const reason = c.whyDisabled();
      const row = el("div", "wb-menu-item" + (reason ? " disabled" : ""));
      row.setAttribute("role", "menuitem");
      if (!reason) row.tabIndex = -1;          // focusable by arrow keys only
      row.appendChild(el("span", "wb-menu-label", c.title));
      const key = Keys.label(c.id);
      if (key) row.appendChild(el("span", "wb-menu-key", key));
      if (reason) row.title = reason;
      row.onclick = () => {
        if (reason) { notify(reason, "warn"); return; }
        hideMenus();
        Commands.execute(c.id);
      };
      drop.appendChild(row);
    });
    const rect = anchor.getBoundingClientRect();
    drop.style.left = rect.left + "px";
    drop.style.top = rect.bottom + 2 + "px";
    drop.id = "menuDrop";
    document.body.appendChild(drop);
    wireMenuKeys(drop, anchor);
  }

  function hideMenus() {
    openMenu = null;
    $$(".wb-menu-btn.open").forEach((b) => b.classList.remove("open"));
    const drop = $("#menuDrop");
    if (drop) drop.remove();
  }
  document.addEventListener("mousedown", (ev) => {
    if (openMenu && !ev.target.closest("#menuDrop") &&
        !ev.target.closest(".wb-menu-btn")) hideMenus();
    if (!ev.target.closest("#ctxMenu")) hideContextMenu();
  });

  /* =================================================================
   * Context menus
   * ================================================================= */
  function registerContextMenus() {
    ContextMenus.register("explorer", ({ node }) => {
      const items = [
        { label: "New File…", run: () => newFile(node) },
        { label: "New Folder…", run: () => newFolder(node) },
      ];
      if (node && node.path) {
        items.push({ separator: true });
        if (node.kind !== "folder") {
          items.push({ label: "Open", run: () => openFile(node.path) });
          items.push({ label: "Open to the Side", run: () => {
            EpsilonPanes.splitPane("row");
            openFile(node.path);
          } });
        }
        items.push({ label: "Rename…", run: () => renameEntry(node) });
        items.push({ label: "Duplicate", run: async () => {
          await api("POST", "/api/duplicate", { path: node.path });
          loadFiles();
        } });
        items.push({ label: "Copy Path", run: () => {
          if (navigator.clipboard) navigator.clipboard.writeText(node.path);
          notify("Copied " + node.path, "ok");
        } });
        items.push({ separator: true });
        items.push({ label: "Delete", danger: true,
                     run: () => deleteEntry(node) });
      }
      return items;
    });

    ContextMenus.register("editor", () => [
      { command: "go.definition" },
      { command: "go.symbol" },
      { command: "view.graph" },
      { separator: true },
      { command: "edit.cut" }, { command: "edit.copy" },
      { command: "edit.paste" },
      { separator: true },
      { command: "edit.format" },
      { command: "edit.toggleComment" },
      { separator: true },
      { command: "run.file" },
      { command: "debug.start" },
      { separator: true },
      { command: "view.commandPalette" },
    ]);

    ContextMenus.register("tab", ({ path }) => [
      { label: "Close", run: () => EpsilonPanes.closeView(path) },
      { label: "Close Others", run: () => EpsilonPanes.closeOthers(path) },
      { label: "Close to the Right",
        run: () => EpsilonPanes.closeToTheRight(path) },
      { label: "Close All", run: () => Commands.execute("file.closeAll") },
      { separator: true },
      { label: EpsilonPanes.isPinned(path) ? "Unpin" : "Pin",
        run: () => EpsilonPanes.togglePin(path) },
      { label: "Split Right", run: () => {
        EpsilonPanes.splitPane("row", path);
      } },
      { separator: true },
      { label: "Copy Path", run: () => {
        if (navigator.clipboard) navigator.clipboard.writeText(path);
      } },
      { label: "Reveal in Explorer", run: () => {
        showSidebar("explorer");
        const row = $('#explorerList [data-path="' + path + '"]');
        if (row) { row.scrollIntoView({ block: "center" }); row.focus(); }
      } },
    ]);

    // the ▾ next to the Run button
    ContextMenus.register("run", () => [
      { command: "run.file" },
      { command: "run.withoutDebugging" },
      { command: "debug.start" },
      { separator: true },
      { command: "run.configure" },
    ]);

    // the ⚙ at the bottom of the activity bar
    ContextMenus.register("gear", () => [
      { command: "view.commandPalette" },
      { separator: true },
      { command: "tools.settings" },
      { command: "tools.shortcuts" },
      { command: "view.theme" },
    ]);
  }

  function showContextMenu(contextId, x, y, ctx) {
    hideContextMenu();
    const items = ContextMenus.itemsFor(contextId, ctx);
    if (!items.length) return;
    const menu = el("div", "wb-menu-drop");
    menu.id = "ctxMenu";
    menu.setAttribute("role", "menu");
    items.forEach((item) => {
      if (item.separator) {
        menu.appendChild(el("div", "wb-menu-sep"));
        return;
      }
      let label = item.label, run = item.run, reason = null, key = "";
      if (item.command) {
        const c = Commands.get(item.command);
        if (!c) return;
        label = c.title;
        reason = c.whyDisabled();
        key = Keys.label(c.id);
        run = () => Commands.execute(c.id);
      }
      const row = el("div", "wb-menu-item" +
        (reason ? " disabled" : "") + (item.danger ? " danger" : ""));
      row.setAttribute("role", "menuitem");
      row.appendChild(el("span", "wb-menu-label", label));
      if (key) row.appendChild(el("span", "wb-menu-key", key));
      if (reason) row.title = reason;
      row.onclick = () => {
        if (reason) { notify(reason, "warn"); return; }
        hideContextMenu();
        run();
      };
      menu.appendChild(row);
    });
    document.body.appendChild(menu);
    const rect = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, window.innerWidth - rect.width - 8) + "px";
    menu.style.top = Math.min(y, window.innerHeight - rect.height - 8) + "px";
  }

  function hideContextMenu() {
    const menu = $("#ctxMenu");
    if (menu) menu.remove();
  }

  /* =================================================================
   * Status bar — every segment is a live control, not a decoration
   * ================================================================= */
  function sbSegment(text, title, run, cls, ico) {
    const b = el("button", "wb-sb-seg" + (cls ? " " + cls : ""));
    if (ico) b.appendChild(icon(ico, 13));
    b.appendChild(el("span", "", text));
    b.title = title || "";
    if (run) b.onclick = run;
    else b.disabled = true;
    return b;
  }

  /**
   * The caret moves far more often than anything else on this bar, so it
   * gets its own path: patch the one segment that changed instead of
   * rebuilding every button and its icon on each keystroke.
   */
  function updateCursorStatus() {
    const seg = statusEls.position;
    const entry = currentEditor();
    if (!seg || !entry || !entry.editor.cursorPosition) return renderStatusbar();
    const pos = entry.editor.cursorPosition();
    const text = "Ln " + pos.line + ", Col " + pos.col +
      (pos.selected ? " (" + pos.selected + " selected)" : "");
    if (seg.textContent !== text) seg.textContent = text;
  }

  const statusEls = { position: null };

  function renderStatusbar() {
    const bar = $("#statusbar");
    if (!bar) return;
    statusEls.position = null;
    bar.classList.toggle("hidden", !Settings.get("workbench.statusBar"));
    bar.innerHTML = "";
    const left = el("div", "wb-sb-side");
    const right = el("div", "wb-sb-side");

    // branch — click opens Source Control
    if (git.status && git.status.branch) {
      left.appendChild(sbSegment(git.status.branch,
        "Source Control (" + (git.status.changes || []).length + " changed)",
        () => Commands.execute("view.scm"), "", "branch"));
    }
    // diagnostics — click opens the Problems panel
    const counts = Diagnostics.count();
    const diag = el("button", "wb-sb-seg wb-sb-diag" +
      (counts.errors ? " err" : counts.warnings ? " warn" : ""));
    diag.title = "Problems — click to open";
    diag.onclick = () => showPanel("problems");
    diag.appendChild(icon("error", 13));
    diag.appendChild(el("span", "", String(counts.errors)));
    diag.appendChild(icon("warning", 13));
    diag.appendChild(el("span", "", String(counts.warnings)));
    left.appendChild(diag);
    if (runState.busy) {
      left.appendChild(sbSegment("running…", "A run is in progress", null,
                                 "busy", "refresh"));
    }
    if (dbg.id) {
      left.appendChild(sbSegment(
        dbg.stopped ? "paused" : "debugging",
        "Debug session — click for Run and Debug",
        () => Commands.execute("view.runDebug"), "dbg",
        dbg.stopped ? "pause" : "play"));
    }

    const entry = currentEditor();
    if (entry) {
      const pos = entry.editor.cursorPosition
        ? entry.editor.cursorPosition() : null;
      if (pos) {
        const seg = sbSegment(
          "Ln " + pos.line + ", Col " + pos.col +
            (pos.selected ? " (" + pos.selected + " selected)" : ""),
          "Go to Line…", () => Commands.execute("go.line"));
        statusEls.position = seg.querySelector("span");
        right.appendChild(seg);
      }
      right.appendChild(sbSegment(
        (Settings.get("editor.insertSpaces") ? "Spaces: " : "Tab Size: ") +
          Settings.get("editor.tabSize"),
        "Indentation — click to change in Settings",
        () => openSettingsUI("indent")));
      right.appendChild(sbSegment("UTF-8",
        "Files are read and written as UTF-8; other encodings are not " +
        "supported yet", null));
      right.appendChild(sbSegment(
        LANGUAGE_LABEL[currentLanguage()] || "Plain Text",
        "Language is detected from the file extension; a manual override " +
        "does not exist yet", null));
    }
    right.appendChild(sbSegment(
      state.caps ? (state.caps.terminal ? "local server" : "browser") : "…",
      state.caps
        ? (state.caps.terminal
           ? "Full toolchain: shell, git, debugger, formatter"
           : "Browser build: Python runs via Pyodide; shell, git, debugger " +
             "and C++ need the local server (pip install epsilon-math; " +
             "epsilon ide)")
        : "Detecting capabilities…",
      () => notify(capabilitySummary(), "info"), "caps",
      state.caps ? (state.caps.terminal ? "bolt" : "cloud") : "cloud"));

    bar.appendChild(left);
    bar.appendChild(right);
  }

  function capabilitySummary() {
    const c = state.caps;
    if (!c) return "Capabilities are still loading.";
    const yes = (v) => (v ? "yes" : "no");
    return "This build — Python: " + yes(c.run && c.run.python) +
      " · C++: " + yes(c.run && c.run.cpp) +
      " · terminal: " + yes(c.terminal) +
      " · debugger: " + yes(c.debug && c.debug.python) +
      " · git: " + yes(c.git) +
      " · formatter: " + yes(c.format && (c.format.python || c.format.cpp)) +
      " · completions: " + ((c.completions && c.completions.python) || "lexical");
  }

  /* =================================================================
   * Run button — context-aware, with a dropdown of run actions
   * ================================================================= */
  function renderRunButton() {
    const host = $("#runControls");
    if (!host) return;
    host.innerHTML = "";
    if (runState.busy) {
      const stop = el("button", "wb-run-btn busy");
      stop.appendChild(icon("refresh", 14));
      stop.appendChild(el("span", "", "Running…"));
      stop.title = "A run is in progress (runs are bounded by the Run " +
        "Timeout setting)";
      stop.disabled = true;
      host.appendChild(stop);
      return;
    }
    const reason = runDisabledReason();
    const main = el("button", "wb-run-btn" + (reason ? " disabled" : ""));
    main.appendChild(icon("play", 13));
    main.appendChild(el("span", "wb-run-label",
      canRun() ? tabTitle(state.active) : "Run"));
    main.title = reason || "Run File (" + Keys.label("run.file") + ")";
    main.onclick = () => {
      const r = Commands.execute("run.file");
      if (!r.ok) notify(r.reason, "warn");
    };
    host.appendChild(main);

    const caret = el("button", "wb-run-caret");
    caret.appendChild(icon("chevronDown", 13));
    caret.title = "More run actions";
    caret.setAttribute("aria-label", "More run actions");
    caret.onclick = (ev) => {
      ev.stopPropagation();
      const rect = caret.getBoundingClientRect();
      showContextMenu("run", rect.right - 220, rect.bottom + 4, {});
    };
    host.appendChild(caret);
  }

  /* =================================================================
   * Activity bar + primary sidebar
   * ================================================================= */
  const sidebar = {
    open: readJSON("epsilon.sidebar.open.v1", true),
    view: readJSON("epsilon.sidebar.view.v1", "explorer"),
    views: [
      { id: "explorer", title: "Explorer", glyph: "files",
        command: "view.explorer" },
      { id: "search", title: "Search", glyph: "search",
        command: "view.search" },
      { id: "scm", title: "Source Control", glyph: "branch",
        command: "view.scm" },
      { id: "rundebug", title: "Run and Debug", glyph: "debug",
        command: "view.runDebug" },
    ],
  };

  function renderActivity() {
    const bar = $("#activitybar");
    if (!bar) return;
    bar.classList.toggle("hidden",
      !Settings.get("workbench.activityBar"));
    bar.innerHTML = "";
    sidebar.views.forEach((v) => {
      const b = el("button", "wb-act-btn" +
        (sidebar.open && sidebar.view === v.id ? " active" : ""));
      b.appendChild(icon(v.glyph, 19));
      b.title = v.title + " (" + (Keys.label(v.command) || "") + ")";
      b.setAttribute("aria-label", v.title);
      if (v.id === "scm" && git.status && git.status.changes &&
          git.status.changes.length) {
        b.appendChild(el("span", "wb-act-badge",
          String(git.status.changes.length)));
      }
      if (v.id === "rundebug" && dbg.id) {
        b.appendChild(el("span", "wb-act-badge dbg", "●"));
      }
      b.onclick = () => {
        if (sidebar.open && sidebar.view === v.id) toggleSidebar();
        else showSidebar(v.id);
      };
      bar.appendChild(b);
    });
    const spacer = el("div", "wb-act-spacer");
    bar.appendChild(spacer);
    const gear = el("button", "wb-act-btn");
    gear.appendChild(icon("gear", 19));
    gear.title = "Settings (" + Keys.label("tools.settings") + ")";
    gear.setAttribute("aria-label", "Settings");
    gear.onclick = (ev) => {
      ev.stopPropagation();
      const rect = gear.getBoundingClientRect();
      showContextMenu("gear", rect.right + 4, rect.top - 8, {});
    };
    bar.appendChild(gear);
  }

  function showSidebar(view) {
    sidebar.open = true;
    if (view) sidebar.view = view;
    writeJSON("epsilon.sidebar.open.v1", true);
    writeJSON("epsilon.sidebar.view.v1", sidebar.view);
    const side = $("#sidebar");
    side.classList.remove("collapsed");
    $("#sideSash").classList.remove("collapsed");
    const spec = sidebar.views.find((v) => v.id === sidebar.view);
    $("#sidebarTitle").textContent = spec ? spec.title.toUpperCase() : "";
    $$(".wb-side-view").forEach((v) =>
      v.classList.toggle("hidden", v.dataset.view !== sidebar.view));
    if (sidebar.view === "explorer") renderExplorer();
    if (sidebar.view === "search") renderSearchResults();
    if (sidebar.view === "scm") refreshGit();
    if (sidebar.view === "rundebug") renderRunDebug();
    renderActivity();
  }

  function toggleSidebar() {
    if (sidebar.open) {
      sidebar.open = false;
      writeJSON("epsilon.sidebar.open.v1", false);
      $("#sidebar").classList.add("collapsed");
      $("#sideSash").classList.add("collapsed");
      renderActivity();
    } else {
      showSidebar();
    }
  }

  /* ---------------- secondary sidebar: outline ---------------- */
  const aux = { open: readJSON("epsilon.aux.open.v1", false) };

  function toggleAux() {
    aux.open = !aux.open;
    writeJSON("epsilon.aux.open.v1", aux.open);
    $("#auxbar").classList.toggle("collapsed", !aux.open);
    if (aux.open) renderOutline();
  }

  function renderOutline() {
    if (!aux.open) return;
    const host = $("#outlineList");
    if (!host) return;
    host.innerHTML = "";
    const symbols = documentSymbols();
    if (!symbols.length) {
      host.appendChild(el("div", "wb-empty",
        currentEditor()
          ? "No symbols found in this file."
          : "The outline shows the functions and classes of the active " +
            "editor."));
      return;
    }
    symbols.forEach((s) => {
      const row = el("div", "wb-outline-item");
      const mark = el("span", "wb-sym-kind " + s.kind);
      mark.appendChild(icon(s.kind === "class" ? "cube" : "fn", 14));
      row.appendChild(mark);
      row.appendChild(el("span", "", s.name));
      row.onclick = () => {
        const entry = currentEditor();
        if (entry) entry.editor.revealLine(s.line, 1);
      };
      host.appendChild(row);
    });
  }

  /* ---------------- zen mode ---------------- */
  let zenSaved = null;

  function toggleZen() {
    const on = !document.body.classList.contains("wb-zen");
    document.body.classList.toggle("wb-zen", on);
    if (on) {
      zenSaved = { sidebar: sidebar.open, panel: panel.open };
      if (sidebar.open) toggleSidebar();
      if (panel.open) togglePanel();
      notify("Zen mode — " + Keys.label("view.zenMode") + " brings " +
        "everything back", "info");
    } else if (zenSaved) {
      if (zenSaved.sidebar) showSidebar();
      if (zenSaved.panel) showPanel();
      zenSaved = null;
    }
  }

  /* =================================================================
   * Go to Definition — semantic, via jedi on the backend
   * ================================================================= */
  async function goToDefinition() {
    const entry = currentEditor();
    if (!entry) return;
    const pos = entry.editor.cursorPosition();
    const r = await api("POST", "/api/definition", {
      language: currentLanguage(), code: entry.editor.getValue(),
      line: pos.line, col: pos.col - 1, path: state.active,
    });
    if (!r || r.ok === false) {
      notify((r && r.message) || "Definition lookup failed", "warn");
      return;
    }
    if (!r.found) {
      notify(r.message || "No definition found for the symbol under the " +
        "cursor", "info");
      return;
    }
    if (r.path && r.path !== state.active) {
      await openFile(r.path);
      const target = editors.get(r.path);
      if (target) target.editor.revealLine(r.line, r.col || 1);
    } else {
      entry.editor.revealLine(r.line, r.col || 1);
    }
  }

  /* =================================================================
   * Layout: theme, sizes, sashes
   * ================================================================= */
  function applyTheme() {
    const theme = Settings.get("workbench.theme");
    document.documentElement.dataset.theme = theme;
    document.body.classList.toggle("wb-reduced-motion",
      Settings.get("workbench.reducedMotion"));
  }

  function applyLayout() {
    const root = document.documentElement;
    root.style.setProperty("--sidebar-w",
      Settings.get("workbench.sidebarWidth") + "px");
    root.style.setProperty("--panel-h",
      Settings.get("workbench.panelHeight") + "px");
    root.style.setProperty("--term-font",
      Settings.get("terminal.fontSize") + "px");
    renderActivity();
    renderStatusbar();
  }

  /** Sidebar/panel sashes: measure on pointerdown, write styles directly
      during the drag, persist to Settings on release (which re-applies). */
  function wireLayoutSash(sashEl, opts) {
    if (!sashEl) return;
    sashEl.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      sashEl.setPointerCapture(ev.pointerId);
      const start = opts.horizontal ? ev.clientX : ev.clientY;
      const base = Settings.get(opts.setting);
      let value = base;
      let raf = 0;
      const move = (e) => {
        const now = opts.horizontal ? e.clientX : e.clientY;
        const delta = (now - start) * (opts.invert ? -1 : 1);
        value = Math.round(Math.min(opts.max, Math.max(opts.min, base + delta)));
        if (!raf) {
          raf = requestAnimationFrame(() => {
            raf = 0;
            document.documentElement.style.setProperty(opts.cssVar,
              value + "px");
          });
        }
      };
      const up = () => {
        sashEl.removeEventListener("pointermove", move);
        sashEl.removeEventListener("pointerup", up);
        sashEl.removeEventListener("pointercancel", up);
        Settings.set(opts.setting, value);
      };
      sashEl.addEventListener("pointermove", move);
      sashEl.addEventListener("pointerup", up);
      sashEl.addEventListener("pointercancel", up);
    });
    sashEl.addEventListener("dblclick", () => Settings.reset(opts.setting));
  }

  /* =================================================================
   * Global keyboard dispatch — one path from key to command
   * ================================================================= */
  function onGlobalKey(ev) {
    if (ev.defaultPrevented) return;
    if (ev.key === "Escape") {
      if (palette.open) { ev.preventDefault(); closePalette(); return; }
      if (openMenu) { ev.preventDefault(); hideMenus(); return; }
      if ($("#ctxMenu")) { ev.preventDefault(); hideContextMenu(); return; }
    }
    const chord = Keys.fromEvent(ev);
    if (!chord) return;
    const commandId = Keys.resolve(chord);
    if (!commandId) return;
    // plain printable keys stay typing, never commands
    if (!ev.ctrlKey && !ev.metaKey && !ev.altKey && chord.length === 1) return;
    ev.preventDefault();
    const r = Commands.execute(commandId);
    if (!r.ok && r.reason) {
      const c = Commands.get(commandId);
      notify((c ? c.title : commandId) + ": " + r.reason, "warn");
    }
  }

  function wirePalette() {
    const input = $("#paletteInput");
    input.addEventListener("input", () => { palette.sel = 0; renderPalette(); });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
        ev.preventDefault();
        const n = palette.items.length;
        if (n) {
          palette.sel = (palette.sel + (ev.key === "ArrowDown" ? 1 : n - 1)) % n;
          renderPalette();
        }
      } else if (ev.key === "Enter") {
        ev.preventDefault();
        acceptPalette();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        closePalette();
      }
    });
    $("#paletteOverlay").addEventListener("mousedown", (ev) => {
      if (ev.target === ev.currentTarget) closePalette();
    });
  }

  function wireSearchView() {
    const input = $("#searchInput");
    const replace = $("#searchReplace");
    if (!input) return;
    let debounce = 0;
    input.addEventListener("input", () => {
      searchState.query = input.value;
      clearTimeout(debounce);
      debounce = setTimeout(runSearch, 250);
    });
    input.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") { ev.preventDefault(); runSearch(); }
    });
    if (replace) {
      replace.addEventListener("input", () => {
        searchState.replace = replace.value;
      });
    }
    $$(".wb-search-opt").forEach((btn) => {
      btn.onclick = () => {
        const opt = btn.dataset.opt;
        searchState[opt] = !searchState[opt];
        btn.classList.toggle("active", searchState[opt]);
        btn.setAttribute("aria-pressed", String(searchState[opt]));
        runSearch();
      };
    });
    const replaceAll = $("#searchReplaceAll");
    if (replaceAll) replaceAll.onclick = replaceAllInFiles;
  }

  function wireDebugConsole() {
    const input = $("#dbgInput");
    if (!input) return;
    input.placeholder = "Evaluate an expression (needs the debugger " +
      "stopped at a breakpoint)";
    input.addEventListener("keydown", (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      const expr = input.value.trim();
      if (!expr) return;
      if (!dbg.id || !dbg.stopped) {
        notify("The debugger is not stopped at a line — set a breakpoint " +
          "in the gutter and press " + Keys.label("debug.start"), "warn");
        return;
      }
      dbg.log("› " + expr, "dim");
      dbg.command("eval", { expr });
      input.value = "";
    });
  }

  /* =================================================================
   * Workspace persistence — reloading must not feel like a reset
   * ================================================================= */
  const WORKSPACE_KEY = "epsilon.session.v1";

  function persistWorkspace() {
    writeJSON(WORKSPACE_KEY, {
      open: Array.from(editors.keys()),
      active: state.active && editors.has(state.active) ? state.active : null,
    });
  }

  async function restoreWorkspace() {
    const saved = readJSON(WORKSPACE_KEY, null);
    const wanted = saved && Array.isArray(saved.open) ? saved.open : [];
    const present = new Set(state.entries.map((e) => e.path));
    for (const path of wanted) {
      if (present.has(path)) {
        try { await openFile(path); } catch (e) { /* file went away */ }
      }
    }
    if (editors.size) {
      EpsilonPanes.restoreLayout();
      if (saved.active && editors.has(saved.active)) {
        await openFile(saved.active);
      }
      return;
    }
    // first visit: open the entry file so the IDE never starts on a void
    const first = state.entries.find((e) => e.path === "main.py")
      || state.entries.find((e) => RUNNABLE.has(e.language || ""));
    if (first) await openFile(first.path);
  }

  /* =================================================================
   * Boot
   * ================================================================= */
  async function init() {
    registerSettings();
    registerCommands();
    registerContextMenus();
    registerMenus();

    applyTheme();
    applyLayout();

    EpsilonPanes.init({
      host: "#editorArea",
      vault: "#viewVault",
      profile: "empty",
      onChange: () => {
        const active = EpsilonPanes.activeView();
        if (active && active !== state.active &&
            (editors.has(active) || SPECIAL.has(active))) {
          state.active = active;
        }
        refreshChrome();
      },
      onTabContext: (viewId, x, y) =>
        showContextMenu("tab", x, y, { path: viewId }),
    });

    renderMenubar();
    renderActivity();
    renderPanel();
    renderStatusbar();
    renderRunButton();

    wirePalette();
    wireSearchView();
    wireDebugConsole();
    const wire = (sel, ico, fn) => {
      const b = $(sel);
      if (!b) return;
      b.appendChild(icon(ico, 15));
      b.onclick = fn;
    };
    const omni = $("#quickOpen");
    if (omni) {
      omni.onclick = () => openPalette("file");
      const chord = Keys.label("go.file");
      const chip = $(".wb-omni-key", omni);
      if (chip && chord) chip.textContent = chord;
    }
    wire("#explorerNewFile", "plus", () => newFile(null));
    wire("#explorerNewFolder", "folderPlus", () => newFolder(null));
    wire("#explorerRefresh", "refresh", () => loadFiles());
    $$(".wb-search-opt").forEach((b) => b.classList.add("wb-chip"));
    wireLayoutSash($("#sideSash"), {
      horizontal: true, setting: "workbench.sidebarWidth",
      cssVar: "--sidebar-w", min: 160, max: 600,
    });
    wireLayoutSash($("#panelSash"), {
      horizontal: false, invert: true, setting: "workbench.panelHeight",
      cssVar: "--panel-h", min: 100, max: 800,
    });

    window.addEventListener("keydown", onGlobalKey);
    window.addEventListener("resize", () => EpsilonPanes.render());
    window.addEventListener("beforeunload", (ev) => {
      if (Array.from(state.dirty.values()).some(Boolean)) {
        ev.preventDefault();
        ev.returnValue = "";
      }
    });
    const editorArea = $("#editorArea");
    editorArea.addEventListener("contextmenu", (ev) => {
      if (ev.target.closest(".wb-editor-host")) {
        ev.preventDefault();
        showContextMenu("editor", ev.clientX, ev.clientY, {});
      }
    });

    Settings.onChange("*", (value, id) => {
      if (id.startsWith("editor.")) {
        editors.forEach((entry) => entry.editor.applySettings());
      }
      if (id === "workbench.theme" || id === "workbench.reducedMotion") {
        applyTheme();
      }
      if (id.startsWith("workbench.") || id.startsWith("terminal.")) {
        applyLayout();
      }
      renderStatusbar();
    });

    Diagnostics.onChange(() => {
      renderPanel();
      renderStatusbar();
      editors.forEach((entry, path) =>
        entry.editor.setDiagnostics(Diagnostics.forPath(path)));
    });

    // capabilities decide what the UI can honestly offer
    try {
      state.caps = await api("GET", "/api/capabilities");
    } catch (e) { state.caps = null; }
    renderPanel();          // the terminal view depends on what caps said

    await loadFiles();
    if (sidebar.open) showSidebar(sidebar.view);
    else { $("#sidebar").classList.add("collapsed");
           $("#sideSash").classList.add("collapsed"); }
    // only now may the shell animate — a layout that animates itself
    // into place on load reads as slow, not as polished
    requestAnimationFrame(() => document.body.classList.add("wb-ready"));
    if (aux.open) $("#auxbar").classList.remove("collapsed");

    await restoreWorkspace();
    if (state.caps && state.caps.git) refreshGit();
    refreshChrome();
  }

  window.EpsilonIDE = {
    init, openFile, notify,
    commands: Commands, settings: Settings, keys: Keys,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      init().catch((e) => {
        console.error(e);
        notify("Epsilon failed to start: " + e.message, "error");
      });
    });
  } else {
    init().catch((e) => {
      console.error(e);
      notify("Epsilon failed to start: " + e.message, "error");
    });
  }
})();
