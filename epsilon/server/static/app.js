/* ===================================================================
 * Epsilon Web IDE — vanilla JS front-end.
 * Talks only to the REST API in docs/CONTRACTS.md. No external deps.
 * =================================================================== */
(function () {
  "use strict";

  /* ---------------- tiny helpers ---------------- */
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const el = (tag, cls, txt) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    return e;
  };
  const esc = (s) =>
    String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  const isMac = navigator.platform.toUpperCase().includes("MAC");

  /* localStorage that never throws: a private window simply forgets */
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
      toast("Network error: " + e.message, "err");
      throw e;
    }
    const ct = res.headers.get("content-type") || "";
    const data = ct.includes("json") ? await res.json() : await res.text();
    if (!res.ok && data && typeof data === "object") {
      // a refused request (a name collision, a path outside the workspace)
      // used to fail silently; say what happened and let callers see it
      if (!("ok" in data)) data.ok = false;
      toast(data.detail || `Request failed (${res.status})`, "err");
    }
    return data;
  }

  /* ---------------- state ---------------- */
  const state = {
    tabs: [], // {path, content, saved, dirty}
    active: null, // path
    lastCheck: null,
    selectedTheorem: null,
    meta: {},
  };

  /* ---------------- toasts ---------------- */
  function toast(msg, kind) {
    const stack = $("#toastStack");
    const t = el("div", "toast " + (kind || ""), msg);
    stack.appendChild(t);
    setTimeout(() => {
      t.style.opacity = "0";
      setTimeout(() => t.remove(), 200);
    }, 2600);
  }

  /* ===================================================================
   * Syntax highlighting
   *
   * One tokenizer, driven by a per-language table. Epsilon is the language
   * this IDE is for, but a workspace holds the Python and C++ that the same
   * piece of work turns into, plus the notes and data around it — so those
   * open as themselves rather than as mis-parsed Epsilon.
   * =================================================================== */
  const KEYWORDS = new Set(("def define theorem lemma proposition corollary " +
    "example axiom constant inductive structure where import namespace end " +
    "open by fun forall exists in with notation infixl infixr prefix postfix " +
    "plot calc if then else sorry match").split(" "));
  const TACTICS = new Set(("intro intros exact apply assumption rfl symm " +
    "constructor split left right exists cases induction rw rewrite simp " +
    "unfold decide norm_num have show calc trivial contradiction exfalso " +
    "cas numeric ring linarith sorry clear auto").split(" "));

  const words = (s) => new Set(s.split(" "));

  const SYNTAX = {
    epsilon: {
      line: ["--"], block: [["/-", "-/"]], nested: true,
      strings: ['"'], directive: "#",
      keywords: KEYWORDS, secondary: TACTICS,
      identStart: /[A-Za-z_\u2115\u2124\u211a\u211d\u2102\u03c0]/,
      identBody: /[A-Za-z0-9_'.\u2115\u2124\u211a\u211d\u2102\u03c0]/,
      isType: (w) => /^[A-Z\u2115\u2124\u211a\u211d\u2102]/.test(w)
        || /^[\u2115\u2124\u211a\u211d\u2102]/.test(w.split(".").pop()),
      ops: "\u2200\u2203\u03bb\u2192\u2194\u2227\u2228\u00ac\u2264\u2265\u2260\u2208\u2209\u2286\u00d7\u221a\u00b7\u2218+-*/^=<>|",
    },
    python: {
      line: ["#"], block: [['"""', '"""'], [", "]],
      strings: ['"', "'"],
      keywords: words("def class return if elif else for while break continue " +
        "import from as pass raise try except finally with lambda yield " +
        "global nonlocal assert del in is not and or None True False await async"),
      secondary: words("print len range int float str list dict set tuple bool " +
        "sum min max abs round sorted enumerate zip map filter open isinstance " +
        "type super self __init__"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~@",
    },
    cpp: {
      line: ["//"], block: [["/*", "*/"]],
      strings: ['"', "'"], directive: "#",
      keywords: words("auto break case catch class const constexpr continue " +
        "default delete do double else enum explicit extern false float for " +
        "friend goto if inline int long namespace new nullptr operator private " +
        "protected public return short signed sizeof static struct switch " +
        "template this throw true try typedef typename union unsigned using " +
        "virtual void volatile while bool char"),
      secondary: words("std cout cin endl vector string map set pair size_t " +
        "unique_ptr shared_ptr printf scanf malloc free"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~?:",
    },
    javascript: {
      line: ["//"], block: [["/*", "*/"]],
      strings: ['"', "'", "`"],
      keywords: words("async await break case catch class const continue " +
        "debugger default delete do else export extends finally for function " +
        "if import in instanceof let new of return static super switch this " +
        "throw try typeof var void while with yield true false null undefined"),
      secondary: words("console document window Math JSON Object Array Promise " +
        "Number String Boolean Set Map require module exports"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~?:",
    },
    shell: {
      line: ["#"], block: [], strings: ['"', "'"],
      keywords: words("if then else elif fi for while do done case esac " +
        "function return export local source exit set unset"),
      secondary: words("echo cd ls cat grep sed awk cp mv rm mkdir python pip git"),
      ops: "|&<>$=",
    },
    json: {
      line: [], block: [], strings: ['"'],
      keywords: words("true false null"),
      ops: ":,",
    },
    yaml: {
      line: ["#"], block: [], strings: ['"', "'"],
      keywords: words("true false null yes no on off"),
      ops: ":-|>",
    },
    toml: {
      line: ["#"], block: [], strings: ['"', "'"],
      keywords: words("true false"),
      ops: "=[]",
    },
    latex: {
      line: ["%"], block: [], strings: [],
      command: "\\",
      keywords: new Set(), ops: "^_&$",
    },
    plain: { line: [], block: [], strings: [], keywords: new Set(), ops: "" },
  };
  SYNTAX.html = SYNTAX.plain;
  SYNTAX.css = SYNTAX.plain;

  function syntaxFor(language) {
    return SYNTAX[language] || SYNTAX.plain;
  }

  function highlight(src, language) {
    if (language === "markdown") return highlightMarkdown(src);
    const spec = syntaxFor(language || "epsilon");
    const out = [];
    // block-comment / fenced-string state carried across lines
    const st = { depth: 0, closer: null };
    src.split("\n").forEach((line) => out.push(highlightLine(line, spec, st)));
    return out.join("\n");
  }

  function highlightLine(line, spec, st) {
    let res = "";
    let i = 0;
    const n = line.length;
    const span = (cls, text) => `<span class="${cls}">${esc(text)}</span>`;

    while (i < n) {
      // inside a multi-line comment or triple-quoted string
      if (st.depth > 0) {
        const end = line.indexOf(st.closer, i);
        if (end === -1) return res + span("tok-comment", line.slice(i));
        res += span("tok-comment", line.slice(i, end + st.closer.length));
        i = end + st.closer.length;
        st.depth -= 1;
        if (!st.depth) st.closer = null;
        continue;
      }

      const rest = line.slice(i);

      const lineComment = (spec.line || []).find((c) => rest.startsWith(c));
      if (lineComment) return res + span("tok-comment", rest);

      const opener = (spec.block || []).find(([o]) => rest.startsWith(o));
      if (opener) {
        const [open, close] = opener;
        const end = line.indexOf(close, i + open.length);
        if (end === -1) {
          st.depth = 1;
          st.closer = close;
          return res + span("tok-comment", rest);
        }
        // Epsilon nests its block comments; C-family ones do not
        if (spec.nested) {
          st.depth += 1;
          st.closer = close;
          res += span("tok-comment", line.slice(i, i + open.length));
          i += open.length;
          continue;
        }
        res += span("tok-comment", line.slice(i, end + close.length));
        i = end + close.length;
        continue;
      }

      const ch = line[i];

      if ((spec.strings || []).includes(ch)) {
        let j = i + 1;
        while (j < n && line[j] !== ch) { if (line[j] === "\\") j++; j++; }
        res += span("tok-string", line.slice(i, Math.min(j + 1, n)));
        i = j + 1;
        continue;
      }

      if (spec.command && ch === "\\") {
        let j = i + 1;
        while (j < n && /[A-Za-z]/.test(line[j])) j++;
        res += span("tok-keyword", line.slice(i, Math.max(j, i + 2)));
        i = Math.max(j, i + 2);
        continue;
      }

      if (spec.directive && ch === spec.directive) {
        let j = i + 1;
        while (j < n && /[a-zA-Z_]/.test(line[j])) j++;
        res += span("tok-directive", line.slice(i, j));
        i = j;
        continue;
      }

      if (/[0-9]/.test(ch)) {
        let j = i;
        while (j < n && /[0-9._a-fA-FxX]/.test(line[j])) j++;
        res += span("tok-num", line.slice(i, j));
        i = j;
        continue;
      }

      const startRe = spec.identStart || /[A-Za-z_]/;
      if (startRe.test(ch)) {
        const bodyRe = spec.identBody || /[A-Za-z0-9_]/;
        let j = i;
        while (j < n && bodyRe.test(line[j])) j++;
        const word = line.slice(i, j);
        let cls = "";
        if (spec.keywords && spec.keywords.has(word)) cls = "tok-keyword";
        else if (spec.secondary && spec.secondary.has(word)) cls = "tok-tactic";
        else if (spec.isType && spec.isType(word)) cls = "tok-type";
        res += cls ? span(cls, word) : esc(word);
        i = j;
        continue;
      }

      if ((spec.ops || "").includes(ch)) {
        res += span("tok-op", ch);
        i++;
        continue;
      }

      res += esc(ch);
      i++;
    }
    return res;
  }

  /** Markdown is prose with markup, not code — it gets its own pass. */
  function highlightMarkdown(src) {
    let fenced = false;
    return src.split("\n").map((line) => {
      if (/^\s*```/.test(line)) {
        fenced = !fenced;
        return `<span class="tok-directive">${esc(line)}</span>`;
      }
      if (fenced) return `<span class="tok-string">${esc(line)}</span>`;
      if (/^\s{0,3}#{1,6}\s/.test(line))
        return `<span class="tok-keyword">${esc(line)}</span>`;
      if (/^\s*>/.test(line)) return `<span class="tok-comment">${esc(line)}</span>`;
      if (/^\s*([-*+]|\d+\.)\s/.test(line)) {
        const m = line.match(/^(\s*([-*+]|\d+\.)\s)/);
        return `<span class="tok-op">${esc(m[1])}</span>` + inlineMarkdown(line.slice(m[1].length));
      }
      return inlineMarkdown(line);
    }).join("\n");
  }

  function inlineMarkdown(text) {
    let out = "";
    let i = 0;
    while (i < text.length) {
      const rest = text.slice(i);
      let m = rest.match(/^`[^`]+`/);
      if (m) { out += `<span class="tok-string">${esc(m[0])}</span>`; i += m[0].length; continue; }
      m = rest.match(/^\*\*[^*]+\*\*|^__[^_]+__/);
      if (m) { out += `<span class="tok-type">${esc(m[0])}</span>`; i += m[0].length; continue; }
      m = rest.match(/^\[[^\]]*\]\([^)]*\)/);
      if (m) { out += `<span class="tok-directive">${esc(m[0])}</span>`; i += m[0].length; continue; }
      out += esc(text[i]);
      i++;
    }
    return out;
  }

  /* ===================================================================
   * Editor
   * =================================================================== */
  const editor = $("#editor");
  const highlightCode = $("#highlightCode");
  const gutter = $("#gutter");
  const codeScroll = $("#codeScroll");
  let errorLines = new Set();

  function renderEditor() {
    const src = editor.value;
    const lang = currentLanguage();
    editor.dataset.language = lang;
    highlightCode.innerHTML = highlight(src, lang);
    const lineCount = src.split("\n").length;
    let g = "";
    for (let i = 1; i <= lineCount; i++) {
      g += errorLines.has(i)
        ? `<span class="gerr">${i}</span>\n`
        : `${i}\n`;
    }
    gutter.textContent = "";
    gutter.innerHTML = g;
    // size the textarea to content so the overlay lines up
    editor.style.height = "auto";
    editor.style.height = editor.scrollHeight + "px";
  }

  editor.addEventListener("input", () => {
    const tab = currentTab();
    if (tab) {
      tab.content = editor.value;
      tab.dirty = tab.content !== tab.saved;
      renderTabs();
      renderFileList();
    }
    renderEditor();
    scheduleCheck();
  });

  editor.addEventListener("scroll", () => {
    highlightCode.parentElement.style.transform =
      `translate(${-editor.scrollLeft}px, ${-editor.scrollTop}px)`;
    gutter.style.transform = `translateY(${-editor.scrollTop}px)`;
  });
  codeScroll.addEventListener("scroll", () => {
    gutter.scrollTop = codeScroll.scrollTop;
  });

  editor.addEventListener("keydown", (e) => {
    if (e.key === "Tab") {
      e.preventDefault();
      insertAtCursor("  ");
    }
    updateCursor();
  });
  editor.addEventListener("keyup", updateCursor);
  editor.addEventListener("click", updateCursor);

  // backslash unicode input: type \name then space
  const UNICODE_MAP = {
    to: "→", forall: "∀", exists: "∃", lambda: "λ", fun: "λ", le: "≤",
    ge: "≥", ne: "≠", and: "∧", or: "∨", not: "¬", iff: "↔", in: "∈",
    sub: "⊆", subseteq: "⊆", sqrt: "√", pi: "π", N: "ℕ", Z: "ℤ", Q: "ℚ",
    R: "ℝ", C: "ℂ", x: "×", circ: "∘", cdot: "·", alpha: "α", beta: "β",
    gamma: "γ", delta: "δ", epsilon: "ε", eps: "ε", theta: "θ", mu: "μ",
    sigma: "σ", omega: "ω", infty: "∞", empty: "∅",
  };
  editor.addEventListener("beforeinput", (e) => {
    if (e.inputType !== "insertText" || e.data !== " ") return;
    const pos = editor.selectionStart;
    const before = editor.value.slice(0, pos);
    const m = before.match(/\\([A-Za-z]+)$/);
    if (m && UNICODE_MAP[m[1]]) {
      e.preventDefault();
      const start = pos - m[0].length;
      editor.setRangeText(UNICODE_MAP[m[1]], start, pos, "end");
      editor.dispatchEvent(new Event("input"));
    }
  });

  function insertAtCursor(text) {
    const s = editor.selectionStart, e = editor.selectionEnd;
    editor.setRangeText(text, s, e, "end");
    editor.dispatchEvent(new Event("input"));
  }

  function updateCursor() {
    const pos = editor.selectionStart;
    const before = editor.value.slice(0, pos);
    const line = before.split("\n").length;
    const col = pos - before.lastIndexOf("\n");
    $("#cursorPos").textContent = `Ln ${line}, Col ${col}`;
  }

  function gotoSpan(span) {
    if (!span || !span[0]) return;
    const [l0, c0] = span;
    const lines = editor.value.split("\n");
    let pos = 0;
    for (let i = 0; i < l0 - 1 && i < lines.length; i++) pos += lines[i].length + 1;
    pos += c0 - 1;
    editor.focus();
    editor.setSelectionRange(pos, pos);
    updateCursor();
    // scroll into view
    const lineTop = (l0 - 1) * 20;
    codeScroll.scrollTop = Math.max(0, lineTop - codeScroll.clientHeight / 2);
  }

  /* ===================================================================
   * Files & tabs
   * =================================================================== */
  function currentTab() {
    return state.tabs.find((t) => t.path === state.active);
  }

  /** Extension -> editor language. Mirrors the server's `_language_of`. */
  const EXT_LANGUAGE = {
    epsl: "epsilon", py: "python", pyi: "python",
    cpp: "cpp", cc: "cpp", cxx: "cpp", c: "cpp", h: "cpp", hpp: "cpp",
    md: "markdown", json: "json", toml: "toml", ini: "toml", cfg: "toml",
    yaml: "yaml", yml: "yaml", tex: "latex", js: "javascript",
    ts: "javascript", html: "html", css: "css", sh: "shell",
  };

  function languageOf(path) {
    const entry = (state.entries || []).find((e) => e.path === path);
    if (entry && entry.language) return entry.language;
    const dot = path.lastIndexOf(".");
    return (dot < 0 ? "" : EXT_LANGUAGE[path.slice(dot + 1).toLowerCase()]) || "plain";
  }

  /** The language of the file in the editor right now. */
  function currentLanguage() {
    const tab = currentTab();
    return tab ? tab.language || languageOf(tab.path) : "epsilon";
  }

  /** Only Epsilon files go through the proof engine. */
  const isEpsilon = () => currentLanguage() === "epsilon";

  async function loadFiles() {
    const r = await api("GET", "/api/files");
    state.files = r.files || [];
    state.entries = r.entries || (state.files || []).map((f) =>
      ({ ...f, kind: "file", language: "epsilon", editable: true }));
    renderFileList();
    if (state.files.length === 0) {
      await api("POST", "/api/file", { path: "main.epsl", content: "" });
      return loadFiles();
    }
    if (!state.active) openFile(state.files[0].path);
  }

  /* ---- explorer tree ---- */

  const COLLAPSE_KEY = "epsilon.explorer.collapsed.v1";
  const collapsed = new Set(readJSON(COLLAPSE_KEY, []));
  function persistCollapsed() {
    writeJSON(COLLAPSE_KEY, Array.from(collapsed));
  }

  /** A small glyph per language — enough to tell files apart at a glance. */
  const FILE_GLYPH = {
    epsilon: "ε", python: "py", cpp: "c++", markdown: "md", json: "{}",
    toml: "cfg", yaml: "yml", latex: "TeX", javascript: "js", html: "<>",
    css: "css", shell: "$",
  };

  /** Build a nested tree from the flat entry list the API returns. */
  function fileTree(entries) {
    const root = { children: new Map() };
    const nodeAt = (path, kind, entry) => {
      const parts = path.split("/");
      let node = root;
      parts.forEach((part, i) => {
        const here = parts.slice(0, i + 1).join("/");
        if (!node.children.has(part)) {
          node.children.set(part, {
            name: part, path: here, children: new Map(),
            kind: i === parts.length - 1 ? kind : "folder",
            entry: i === parts.length - 1 ? entry : null,
          });
        }
        node = node.children.get(part);
      });
      return node;
    };
    entries.forEach((e) => nodeAt(e.path, e.kind, e));
    return root;
  }

  function matchesFilter(node, needle) {
    if (!needle) return true;
    if (node.path.toLowerCase().includes(needle)) return true;
    return Array.from(node.children.values())
      .some((c) => matchesFilter(c, needle));
  }

  function renderFileList() {
    const list = $("#fileList");
    list.innerHTML = "";
    const needle = (state.fileFilter || "").trim().toLowerCase();
    const root = fileTree(state.entries || []);

    const sorted = (node) => Array.from(node.children.values()).sort((a, b) =>
      (a.kind === b.kind ? 0 : a.kind === "folder" ? -1 : 1)
      || a.name.localeCompare(b.name));

    const walk = (node, depth) => {
      sorted(node).forEach((child) => {
        if (!matchesFilter(child, needle)) return;
        list.appendChild(rowFor(child, depth));
        // a filter expands what it matches, so a hit is never hidden
        const open = needle || !collapsed.has(child.path);
        if (child.kind === "folder" && open) walk(child, depth + 1);
      });
    };
    walk(root, 0);

    if (!list.children.length) {
      const empty = el("li", "file-empty",
        needle ? "No file matches that filter." : "No files yet.");
      list.appendChild(empty);
    }
  }

  function rowFor(node, depth) {
    const item = el("li", "file-item" + (node.kind === "folder" ? " folder" : ""));
    item.style.paddingLeft = 8 + depth * 13 + "px";
    item.dataset.path = node.path;
    item.dataset.kind = node.kind;
    item.title = node.path;

    if (node.kind === "folder") {
      const twisty = el("span", "twisty", collapsed.has(node.path) ? "▸" : "▾");
      item.appendChild(twisty);
      item.appendChild(el("span", "file-glyph folder-glyph", "▪"));
    } else {
      const lang = (node.entry && node.entry.language) || "plain";
      item.appendChild(el("span", "file-glyph lang-" + lang,
                          FILE_GLYPH[lang] || "·"));
    }

    item.appendChild(el("span", "file-name", node.name));

    const tab = state.tabs.find((t) => t.path === node.path);
    if (tab && tab.dirty) item.classList.add("dirty");
    if (node.path === state.active) item.classList.add("active");
    item.appendChild(el("span", "dirty"));

    item.onclick = () => {
      if (node.kind === "folder") {
        if (collapsed.has(node.path)) collapsed.delete(node.path);
        else collapsed.add(node.path);
        persistCollapsed();
        renderFileList();
      } else if (node.entry && node.entry.editable === false) {
        toast(node.name + " is not a text file", "warn");
      } else {
        openFile(node.path);
      }
    };
    item.oncontextmenu = (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, node);
    };

    wireFileDrag(item, node);
    return item;
  }

  /* ---- drag a file onto a folder to move it ---- */

  function wireFileDrag(item, node) {
    item.draggable = true;
    item.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/epsilon-path", node.path);
      e.dataTransfer.effectAllowed = "move";
    });
    if (node.kind !== "folder") return;
    item.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("text/epsilon-path")) return;
      e.preventDefault();
      item.classList.add("drop-target");
    });
    item.addEventListener("dragleave", () => item.classList.remove("drop-target"));
    item.addEventListener("drop", (e) => {
      e.preventDefault();
      item.classList.remove("drop-target");
      const from = e.dataTransfer.getData("text/epsilon-path");
      if (!from) return;
      moveEntry(from, node.path + "/" + from.split("/").pop());
    });
  }

  /* ---- explorer commands ---- */

  /** The folder a new entry should land in, given what is selected. */
  function currentFolder(node) {
    if (node) return node.kind === "folder" ? node.path
      : node.path.split("/").slice(0, -1).join("/");
    if (state.active) return state.active.split("/").slice(0, -1).join("/");
    return "";
  }

  const joinPath = (dir, name) => (dir ? dir + "/" + name : name);

  async function moveEntry(from, to) {
    if (!to || from === to) return;
    const r = await api("POST", "/api/rename", { path: from, to });
    if (r && r.ok === false) return;
    // follow the file: open tabs and the active file keep pointing at it
    state.tabs.forEach((t) => {
      if (t.path === from) t.path = to;
      else if (t.path.startsWith(from + "/")) t.path = to + t.path.slice(from.length);
    });
    if (state.active === from) state.active = to;
    else if (state.active && state.active.startsWith(from + "/"))
      state.active = to + state.active.slice(from.length);
    if (collapsed.delete(from)) { collapsed.add(to); persistCollapsed(); }
    await loadFiles();
    renderTabs();
    toast("Moved to " + to, "ok");
  }

  async function renameEntry(node) {
    const name = prompt("Rename " + node.name + " to:", node.name);
    if (!name || name === node.name) return;
    const dir = node.path.split("/").slice(0, -1).join("/");
    await moveEntry(node.path, joinPath(dir, name));
  }

  async function duplicateEntry(node) {
    const r = await api("POST", "/api/duplicate", { path: node.path });
    await loadFiles();
    if (r && r.path) toast("Duplicated to " + r.path, "ok");
  }

  async function deleteEntry(node) {
    const what = node.kind === "folder"
      ? `Delete the folder "${node.name}" and everything in it?`
      : `Delete "${node.name}"?`;
    if (!confirm(what)) return;
    if (node.kind === "folder") {
      await api("DELETE", "/api/folder?path=" + encodeURIComponent(node.path));
      state.tabs.filter((t) => t.path.startsWith(node.path + "/"))
        .forEach((t) => closeTab(t.path));
    } else {
      await api("DELETE", "/api/file?path=" + encodeURIComponent(node.path));
      closeTab(node.path);
    }
    await loadFiles();
    toast("Deleted " + node.name, "ok");
  }

  async function newFolder(node) {
    const name = prompt("New folder name:", "untitled");
    if (!name) return;
    await api("POST", "/api/folder", { path: joinPath(currentFolder(node), name) });
    await loadFiles();
  }

  /* ---- context menu ---- */

  function openContextMenu(x, y, node) {
    const menu = $("#ctxMenu");
    menu.innerHTML = "";
    const add = (label, run, danger) => {
      const b = el("button", "ctx-item" + (danger ? " danger" : ""), label);
      b.onclick = () => { closeContextMenu(); run(); };
      menu.appendChild(b);
    };
    add("New file…", () => newFile(node));
    add("New folder…", () => newFolder(node));
    // the workspace root is a place to put things, not a thing itself
    if (node.path) {
      menu.appendChild(el("div", "ctx-sep"));
      add("Rename…", () => renameEntry(node));
      add("Duplicate", () => duplicateEntry(node));
      add("Copy path", () => {
        if (navigator.clipboard) navigator.clipboard.writeText(node.path);
        toast("Copied " + node.path, "ok");
      });
      menu.appendChild(el("div", "ctx-sep"));
      add("Delete", () => deleteEntry(node), true);
    }

    menu.classList.remove("hidden");
    // keep the menu on screen when the click lands near an edge
    const r = menu.getBoundingClientRect();
    menu.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    menu.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
  }

  function closeContextMenu() {
    const menu = $("#ctxMenu");
    if (menu) menu.classList.add("hidden");
  }

  async function openFile(path) {
    let tab = state.tabs.find((t) => t.path === path);
    if (!tab) {
      const r = await api("GET", "/api/file?path=" + encodeURIComponent(path));
      tab = { path, content: r.content || "", saved: r.content || "",
              dirty: false, language: languageOf(path) };
      state.tabs.push(tab);
    }
    state.active = path;
    editor.value = tab.content;
    renderEditor();
    renderTabs();
    renderFileList();
    updateCursor();
    runCheck();
  }

  function renderTabs() {
    const strip = $("#tabstrip");
    strip.innerHTML = "";
    state.tabs.forEach((t) => {
      const tab = el("div", "tab" + (t.path === state.active ? " active" : ""));
      const name = t.path.split("/").pop();
      const lang = t.language || languageOf(t.path);
      tab.appendChild(el("span", "file-glyph lang-" + lang,
                         FILE_GLYPH[lang] || "·"));
      tab.appendChild(el("span", null, name));
      tab.title = t.path;
      if (t.dirty) tab.appendChild(el("span", "dirty"));
      const close = el("span", "close", "×");
      close.onclick = (e) => {
        e.stopPropagation();
        closeTab(t.path);
      };
      tab.appendChild(close);
      tab.onclick = () => openFile(t.path);
      strip.appendChild(tab);
    });
  }

  function closeTab(path) {
    const idx = state.tabs.findIndex((t) => t.path === path);
    if (idx === -1) return;
    state.tabs.splice(idx, 1);
    if (state.active === path) {
      state.active = null;
      if (state.tabs.length) openFile(state.tabs[Math.max(0, idx - 1)].path);
      else { editor.value = ""; renderEditor(); }
    }
    renderTabs();
    renderFileList();
  }

  async function saveCurrent() {
    const tab = currentTab();
    if (!tab) return;
    await api("PUT", "/api/file", { path: tab.path, content: tab.content });
    tab.saved = tab.content;
    tab.dirty = false;
    renderTabs();
    renderFileList();
    toast("Saved " + tab.path.split("/").pop(), "ok");
    runCheck();
  }

  async function newFile(node) {
    const name = prompt("New file name:", "untitled.epsl");
    if (!name) return;
    // no extension means Epsilon — the language this IDE is for
    const path = joinPath(currentFolder(node),
                          /\.[^./]+$/.test(name) ? name : name + ".epsl");
    const r = await api("POST", "/api/file", { path, content: "" });
    if (r && r.ok === false) return;
    const dir = path.split("/").slice(0, -1).join("/");
    if (dir && collapsed.delete(dir)) persistCollapsed();
    await loadFiles();
    openFile(path);
  }

  /* ===================================================================
   * Check flow
   * =================================================================== */
  let checkTimer = null;
  function scheduleCheck() {
    clearTimeout(checkTimer);
    checkTimer = setTimeout(runCheck, 650);
  }

  async function runCheck() {
    const tab = currentTab();
    if (!tab) return;
    // the proof engine only understands Epsilon. Reporting bogus Epsilon
    // errors against a Python file would be worse than reporting nothing.
    if (!isEpsilon()) {
      errorLines = new Set();
      renderEditor();
      renderProblems([]);
      setCheckState("na");
      // the theorem list, plots and graph still describe the last Epsilon
      // file checked, which is the useful thing to keep on screen
      return;
    }
    setCheckState("running");
    let r;
    try {
      r = await api("POST", "/api/check", { path: tab.path, content: tab.content });
    } catch (e) {
      setCheckState("error");
      return;
    }
    state.lastCheck = r;
    errorLines = new Set(
      (r.diagnostics || [])
        .filter((d) => d.severity === "error")
        .map((d) => d.span && d.span[0])
        .filter(Boolean)
    );
    renderEditor();
    renderProblems(r.diagnostics || []);
    renderTheorems(r.theorems || []);
    renderPlots(r.plots || []);
    renderInspector(r.results || []);
    renderDeps(r.deps || { nodes: [], edges: [] });
    setCheckState(r.ok ? "ok" : "error");
    updateStatusCounts(r.theorems || []);
    if (EpsilonPanes.isOpen("render")) refreshRender();
  }

  const LANGUAGE_LABEL = {
    epsilon: "Epsilon", python: "Python", cpp: "C++", markdown: "Markdown",
    json: "JSON", toml: "TOML", yaml: "YAML", latex: "LaTeX",
    javascript: "JavaScript", shell: "Shell", html: "HTML", css: "CSS",
    plain: "Plain text",
  };

  function setCheckState(s) {
    const chip = $("#checkState");
    chip.className = "chip " + (s === "ok" ? "ok" : s === "error" ? "err" :
      s === "running" ? "running" : "");
    chip.textContent = s === "running" ? "checking…" :
      s === "ok" ? "✓ checked" : s === "error" ? "✗ errors" :
      s === "na" ? "not an Epsilon file" : "ready";
    $("#checkBtn").classList.toggle("running", s === "running");
    // the check button is meaningless outside Epsilon; say so rather than
    // leaving a live-looking control that does nothing
    const epsl = isEpsilon();
    $("#checkBtn").disabled = !epsl;
    $("#checkBtn").title = epsl ? "Check (Ctrl/Cmd+Enter)"
      : "Checking applies to Epsilon files";
    const label = $("#editorLanguage");
    if (label) label.textContent = LANGUAGE_LABEL[currentLanguage()] || "Plain text";
  }

  function updateStatusCounts(theorems) {
    const c = { proven: 0, symbolic: 0, numeric: 0, heuristic: 0 };
    theorems.forEach((t) => (c[t.status] = (c[t.status] || 0) + 1));
    const map = { proven: ["✓", "var(--ok)"], symbolic: ["✓", "var(--sym)"],
      numeric: ["≈", "var(--num)"], heuristic: ["⚠", "var(--heur)"] };
    const parts = Object.keys(map)
      .filter((k) => c[k])
      .map((k) => `<span class="sc" style="color:${map[k][1]}">${map[k][0]} ${c[k]}</span>`);
    $("#statusCounts").innerHTML = parts.join("");
  }

  /* ---- problems ---- */
  function renderProblems(diags) {
    const panel = $("#problemsPanel");
    panel.innerHTML = "";
    const errs = diags.filter((d) => d.severity !== "info");
    const warned = errs.some((d) => d.severity === "warning") && errs.every((d) => d.severity === "warning");
    EpsilonPanes.setBadge("problems", errs.length, warned ? "warn" : "err");
    if (!errs.length) {
      panel.appendChild(el("div", "no-problems", "No problems detected."));
      return;
    }
    errs.forEach((d) => {
      const item = el("div", "problem-item");
      const sev = el("span", "pi-sev" + (d.severity === "warning" ? " warning" : ""),
        d.severity);
      const loc = el("span", "pi-loc", `${d.span[0]}:${d.span[1]}`);
      const wrap = el("div");
      wrap.appendChild(el("div", "pi-msg", d.message));
      item.appendChild(sev);
      item.appendChild(loc);
      item.appendChild(wrap);
      item.onclick = () => gotoSpan(d.span);
      panel.appendChild(item);
    });
  }

  /* ---- theorems sidebar ---- */
  function renderTheorems(theorems) {
    const list = $("#thmList");
    list.innerHTML = "";
    const counts = { proven: 0, symbolic: 0, numeric: 0, heuristic: 0 };
    theorems.forEach((t) => {
      counts[t.status] = (counts[t.status] || 0) + 1;
      const item = el("li", "thm-item");
      if (state.selectedTheorem === t.name) item.classList.add("active");
      const row = el("div", "thm-row");
      row.appendChild(el("span", "status-dot " + t.status));
      // lead with the mathematical name when the library gives one, and
      // keep the internal identifier visible underneath - it is what a
      // proof cites and what error messages name
      row.appendChild(el("span", "thm-name", t.title || t.name));
      item.appendChild(row);
      if (t.display_name) item.appendChild(el("div", "thm-ident", t.name));
      item.appendChild(el("div", "thm-stmt", t.statement));
      if (t.doc) item.appendChild(el("div", "thm-doc", t.doc));
      if (t.axioms && t.axioms.length) {
        const ax = el("div", "thm-axioms");
        t.axioms.forEach((a) => ax.appendChild(el("span", "axiom-chip", a)));
        item.appendChild(ax);
      }
      item.onclick = () => {
        state.selectedTheorem = t.name;
        gotoSpan(t.span);
        showProofTree(t.name);
        renderTheorems(theorems);
        switchUtil("proof");
      };
      list.appendChild(item);
    });
    const dot = (k, c) =>
      `<span style="color:${c}">${counts[k] || 0}</span>`;
    $("#thmCounts").innerHTML =
      dot("proven", "var(--ok)") + dot("symbolic", "var(--sym)") +
      dot("numeric", "var(--num)") + dot("heuristic", "var(--heur)");
  }

  /* ---- proof tree ---- */
  function showProofTree(name) {
    const panel = $("#proofPanel");
    const trace = state.lastCheck && state.lastCheck.traces &&
      state.lastCheck.traces[name];
    panel.innerHTML = "";
    if (!trace || !trace.length) {
      panel.appendChild(el("div", "empty-hint",
        "No recorded proof steps (term-style or imported)."));
      return;
    }
    const tree = buildProofTree(trace);
    const container = el("div", "proof-tree");
    if (tree) container.appendChild(renderProofNode(tree));
    panel.appendChild(container);
  }

  function buildProofTree(trace) {
    const byGoal = {};
    const nodes = [];
    trace.forEach((step) => {
      const node = {
        goal_id: step.goal_id, tactic: step.tactic, rule: step.rule,
        target: step.before_target, after: step.after_goals || [], children: [],
      };
      if (byGoal[step.goal_id]) byGoal[step.goal_id].children.push(node);
      byGoal[step.goal_id] = node;
      nodes.push(node);
    });
    trace.forEach((step, i) => {
      const node = nodes[i];
      (step.after_goals || []).forEach((g) => {
        const child = byGoal[g];
        if (child && child !== node && !node.children.includes(child))
          node.children.push(child);
      });
    });
    return nodes[0];
  }

  function ruleLabel(rule) {
    if (!rule) return "";
    if (rule.startsWith("oracle:")) return rule.split(":")[1];
    return rule;
  }

  function renderProofNode(node) {
    const wrap = el("div", "pnode");
    const head = el("div", "pnode-head");
    const toggle = el("span", "pnode-toggle", node.children.length ? "▾" : "·");
    head.appendChild(toggle);
    if (node.rule) head.appendChild(el("span", "pnode-rule", ruleLabel(node.rule)));
    head.appendChild(el("span", "pnode-tactic", node.tactic || "(open)"));
    wrap.appendChild(head);
    wrap.appendChild(el("div", "pnode-goal", "⊢ " + node.target));
    if (node.children.length) {
      const kids = el("div", "pnode-children");
      node.children.forEach((c) => kids.appendChild(renderProofNode(c)));
      wrap.appendChild(kids);
      head.onclick = () => {
        wrap.classList.toggle("collapsed");
        toggle.textContent = wrap.classList.contains("collapsed") ? "▸" : "▾";
      };
    }
    return wrap;
  }

  /* ---- plots ---- */
  function renderPlots(plots) {
    const panel = $("#plotPanel");
    panel.innerHTML = "";
    if (!plots.length) {
      panel.appendChild(el("div", "empty-hint", "No plots in this file."));
      return;
    }
    plots.forEach((spec, idx) => {
      if (spec.error) {
        panel.appendChild(el("div", "empty-hint", "Plot error: " + spec.error));
        return;
      }
      const item = el("div", "plot-item");
      const canvas = el("canvas");
      canvas.width = 560; canvas.height = 320;
      item.appendChild(canvas);
      const readout = el("div", "plot-readout", "");
      item.appendChild(readout);
      panel.appendChild(item);
      drawPlot(canvas, spec, readout);
    });
  }

  function drawPlot(canvas, spec, readout) {
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.clientWidth || 560, H = 320;
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.height = H + "px";
    const ctx = canvas.getContext("2d");
    ctx.scale(dpr, dpr);
    const css = getComputedStyle(document.documentElement);
    const fg = css.getPropertyValue("--fg-dim").trim();
    const line = css.getPropertyValue("--glass-border").trim();
    const colors = ["#7c78ff", "#38d6c8", "#ffc861", "#ff7a90", "#79c0ff"];

    // bounds
    let xmin = spec.lo != null ? spec.lo : -10, xmax = spec.hi != null ? spec.hi : 10;
    let ymin = Infinity, ymax = -Infinity;
    spec.series.forEach((s) =>
      s.y.forEach((v) => {
        if (v != null && isFinite(v)) { ymin = Math.min(ymin, v); ymax = Math.max(ymax, v); }
      })
    );
    if (!isFinite(ymin)) { ymin = -1; ymax = 1; }
    if (ymin === ymax) { ymin -= 1; ymax += 1; }
    const pad = (ymax - ymin) * 0.1; ymin -= pad; ymax += pad;
    const pl = 8, pr = 8, pt = 8, pb = 8;
    const X = (x) => pl + ((x - xmin) / (xmax - xmin)) * (W - pl - pr);
    const Y = (y) => pt + (1 - (y - ymin) / (ymax - ymin)) * (H - pt - pb);

    ctx.clearRect(0, 0, W, H);
    // grid
    ctx.strokeStyle = line; ctx.lineWidth = 1; ctx.font = "10px ui-monospace";
    ctx.fillStyle = fg;
    for (let g = 0; g <= 4; g++) {
      const gx = pl + (g / 4) * (W - pl - pr);
      ctx.globalAlpha = 0.4;
      ctx.beginPath(); ctx.moveTo(gx, pt); ctx.lineTo(gx, H - pb); ctx.stroke();
      const gy = pt + (g / 4) * (H - pt - pb);
      ctx.beginPath(); ctx.moveTo(pl, gy); ctx.lineTo(W - pr, gy); ctx.stroke();
      ctx.globalAlpha = 1;
    }
    // axes at 0
    ctx.strokeStyle = fg; ctx.globalAlpha = 0.6; ctx.lineWidth = 1.2;
    if (0 >= ymin && 0 <= ymax) { ctx.beginPath(); ctx.moveTo(pl, Y(0)); ctx.lineTo(W - pr, Y(0)); ctx.stroke(); }
    if (0 >= xmin && 0 <= xmax) { ctx.beginPath(); ctx.moveTo(X(0), pt); ctx.lineTo(X(0), H - pb); ctx.stroke(); }
    ctx.globalAlpha = 1;
    // series
    spec.series.forEach((s, si) => {
      ctx.strokeStyle = colors[si % colors.length];
      ctx.lineWidth = 2; ctx.beginPath();
      let started = false;
      s.x.forEach((x, i) => {
        const y = s.y[i];
        if (y == null || !isFinite(y)) { started = false; return; }
        const px = X(x), py = Y(y);
        if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
      });
      ctx.stroke();
    });
    // legend
    spec.series.forEach((s, si) => {
      ctx.fillStyle = colors[si % colors.length];
      ctx.fillRect(W - 90, 10 + si * 15, 10, 3);
      ctx.fillStyle = fg;
      ctx.fillText(s.label || "f", W - 76, 14 + si * 15);
    });
    // crosshair
    canvas.onmousemove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = e.clientX - rect.left;
      const x = xmin + ((mx - pl) / (W - pl - pr)) * (xmax - xmin);
      const s0 = spec.series[0];
      let closest = null, cd = Infinity;
      s0.x.forEach((xx, i) => {
        const d = Math.abs(xx - x);
        if (d < cd && s0.y[i] != null) { cd = d; closest = { x: xx, y: s0.y[i] }; }
      });
      if (closest)
        readout.textContent = `x=${closest.x.toFixed(3)}  ${s0.label || "f"}=${closest.y.toFixed(4)}`;
    };
  }

  /* ---- inspector ---- */
  function renderInspector(results) {
    const panel = $("#inspectorResults");
    panel.innerHTML = "";
    const rel = results.filter((r) => r.kind === "check" || r.kind === "eval");
    const meta = el("div", "inspector-item");
    meta.innerHTML = `<span class="ik">SESSION</span><br>${esc(state.meta.brand ||
      "Epsilon")} ${esc(state.meta.version || "")}`;
    panel.appendChild(meta);
    if (!rel.length) {
      panel.appendChild(el("div", "empty-hint",
        "#check / #eval outputs will appear here."));
      return;
    }
    rel.forEach((r) => {
      const item = el("div", "inspector-item");
      item.innerHTML = `<span class="ik">${r.kind.toUpperCase()}</span><br>${esc(r.message || "")}`;
      panel.appendChild(item);
    });
  }

  /* ===================================================================
   * Dependency graph
   *
   * A continuously relaxing force simulation, the way a note-graph view
   * behaves: repulsion pushes the whole set apart, springs hold linked
   * results together, and the layout keeps settling for as long as it is
   * moving instead of freezing after a fixed number of passes. Labels are
   * drawn only where they can be read - the focused node's neighbourhood,
   * or everything once you have zoomed in - so the picture never becomes
   * a wall of overlapping text.
   * =================================================================== */
  const graphCanvas = $("#graphCanvas");
  let graphData = { nodes: [], edges: [] };
  const graphView = { x: 0, y: 0, scale: 1 };
  const graphSim = {
    running: false, frame: null, alpha: 0,
    hover: null, selected: null, drag: null,
    panning: false, px: 0, py: 0, moved: false,
    adjacency: new Map(),
  };

  const GRAPH_KIND_COLOR = {
    axiom: "--heur", definition: "--accent-2", inductive: "--sym",
  };

  function graphColor(n, css) {
    const statusVar = { proven: "--ok", symbolic: "--sym",
                        numeric: "--num", heuristic: "--heur" }[n.status];
    const v = statusVar || GRAPH_KIND_COLOR[n.kind] || "--fg-dim";
    return css.getPropertyValue(v).trim() || "#888";
  }

  let graphRaw = { nodes: [], edges: [] };
  const graphFilters = { theorem: true, axiom: true, definition: false,
                         isolated: false };

  function renderDeps(deps) {
    graphRaw = { nodes: deps.nodes || [], edges: deps.edges || [] };
    applyGraphFilters();
  }

  /** Derive the drawn graph from the raw one. Type aliases such as ℝ are
   *  definitions that nearly every axiom mentions, so including them turns
   *  the picture into a star around one hub; they are off by default. */
  function applyGraphFilters() {
    const keepKind = (n) => {
      if (n.kind === "theorem") return graphFilters.theorem;
      if (n.kind === "axiom") return graphFilters.axiom;
      return graphFilters.definition;
    };
    const kept = new Set(graphRaw.nodes.filter(keepKind).map((n) => n.name));
    const edges = graphRaw.edges.filter(
      (e) => kept.has(e.from) && kept.has(e.to));
    const linked = new Set();
    edges.forEach((e) => { linked.add(e.from); linked.add(e.to); });
    const nodes = graphRaw.nodes.filter(
      (n) => kept.has(n.name) &&
             (graphFilters.isolated || linked.has(n.name)));
    const visible = new Set(nodes.map((n) => n.name));

    const prev = new Map(graphData.nodes.map((n) => [n.name, n]));
    graphData = { nodes: nodes.map((n) => ({ ...n })),
                  edges: edges.filter((e) => visible.has(e.from) &&
                                             visible.has(e.to)) };
    renderGraphLegend();
    const R = 260;
    graphData.nodes.forEach((n, i) => {
      const old = prev.get(n.name);
      if (old) { n.x = old.x; n.y = old.y; n.vx = 0; n.vy = 0; return; }
      // seed on a ring: a circle spreads better than a point cloud
      const a = (i / Math.max(1, graphData.nodes.length)) * Math.PI * 2;
      n.x = Math.cos(a) * R + (i % 7) * 3;
      n.y = Math.sin(a) * R + (i % 5) * 3;
      n.vx = 0; n.vy = 0;
    });
    buildAdjacency();
    graphSim.alpha = 1;
    if ($('.act[data-view="graph"]').classList.contains("active")) startGraph();
  }


  function renderGraphLegend() {
    const box = $("#graphLegend");
    if (!box) return;
    const css = getComputedStyle(document.documentElement);
    const rows = [
      ["--ok", "proven"], ["--sym", "symbolic"], ["--num", "numeric"],
      ["--heur", "axiom / heuristic"], ["--accent-2", "definition"],
    ];
    box.innerHTML = "";
    rows.forEach(([v, label]) => {
      const s = el("span");
      const dot = el("i");
      dot.style.background = css.getPropertyValue(v).trim();
      s.appendChild(dot);
      s.appendChild(document.createTextNode(label));
      box.appendChild(s);
    });
    const s = el("span", null, `${graphData.nodes.length} shown`);
    box.appendChild(s);
  }

  function focusGraphNode(query) {
    const q = query.trim().toLowerCase();
    if (!q) { graphSim.selected = null; drawGraph(); return; }
    const hit = graphData.nodes.find(
      (n) => n.name.toLowerCase().includes(q) ||
             (n.title || "").toLowerCase().includes(q));
    if (!hit) return;
    graphSim.selected = hit.name;
    // centre the view on it without changing the zoom
    graphView.x = -hit.x * graphView.scale;
    graphView.y = -hit.y * graphView.scale;
    drawGraph();
  }

  function wireGraphFilters() {
    const map = { gfTheorem: "theorem", gfAxiom: "axiom",
                  gfDefinition: "definition", gfIsolated: "isolated" };
    Object.entries(map).forEach(([id, key]) => {
      const box = $("#" + id);
      if (!box) return;
      box.checked = graphFilters[key];
      box.onchange = () => {
        graphFilters[key] = box.checked;
        applyGraphFilters();
        graphSim.alpha = 1;
        startGraph();
        setTimeout(fitGraphView, 700);
      };
    });
    const search = $("#graphSearch");
    if (search) {
      let t = null;
      search.addEventListener("input", () => {
        clearTimeout(t);
        t = setTimeout(() => focusGraphNode(search.value), 180);
      });
    }
  }

  function buildAdjacency() {
    const byName = new Map(graphData.nodes.map((n) => [n.name, n]));
    const adj = new Map(graphData.nodes.map((n) => [n.name, new Set()]));
    graphData.links = [];
    graphData.edges.forEach((e) => {
      const a = byName.get(e.from), b = byName.get(e.to);
      if (!a || !b || a === b) return;
      graphData.links.push({ a, b });
      adj.get(e.from).add(e.to);
      adj.get(e.to).add(e.from);
    });
    graphSim.adjacency = adj;
    graphData.nodes.forEach((n) => {
      n.degree = (adj.get(n.name) || new Set()).size;
      n.r = 4 + Math.min(7, Math.sqrt(n.degree) * 2.1);
    });
    graphData.byName = byName;
  }

  function startGraph() {
    if (graphSim.running) return;
    graphSim.running = true;
    const step = () => {
      if (!graphSim.running) return;
      if (graphSim.alpha > 0.005) { tickGraph(); graphSim.alpha *= 0.985; }
      drawGraph();
      graphSim.frame = requestAnimationFrame(step);
    };
    step();
  }

  function stopGraph() {
    graphSim.running = false;
    if (graphSim.frame) cancelAnimationFrame(graphSim.frame);
    graphSim.frame = null;
  }

  function tickGraph() {
    const nodes = graphData.nodes;
    const n = nodes.length;
    if (!n) return;
    const k = graphSim.alpha;

    // repulsion — the term that does the spreading
    for (let i = 0; i < n; i++) {
      const a = nodes[i];
      for (let j = i + 1; j < n; j++) {
        const b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy;
        if (d2 < 1e-4) { dx = (i % 3) - 1 || 0.7; dy = (j % 3) - 1 || 0.7; d2 = 1; }
        const dist = Math.sqrt(d2);
        // strong close-range push, decaying with distance
        const f = Math.min(4000 / d2, 90) * k;
        const ux = dx / dist, uy = dy / dist;
        a.vx -= ux * f; a.vy -= uy * f;
        b.vx += ux * f; b.vy += uy * f;
      }
    }

    // springs on dependency edges
    const REST = 78;
    graphData.links.forEach(({ a, b }) => {
      const dx = b.x - a.x, dy = b.y - a.y;
      const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const f = (dist - REST) * 0.035 * k;
      const ux = dx / dist, uy = dy / dist;
      a.vx += ux * f; a.vy += uy * f;
      b.vx -= ux * f; b.vy -= uy * f;
    });

    // gentle pull to the origin so disconnected parts do not drift away
    nodes.forEach((nd) => {
      nd.vx -= nd.x * 0.0016 * k;
      nd.vy -= nd.y * 0.0016 * k;
    });

    // integrate with damping; a dragged node is pinned to the pointer
    nodes.forEach((nd) => {
      if (graphSim.drag && graphSim.drag.node === nd) { nd.vx = nd.vy = 0; return; }
      nd.vx *= 0.82; nd.vy *= 0.82;
      const sp = Math.hypot(nd.vx, nd.vy);
      if (sp > 12) { nd.vx = (nd.vx / sp) * 12; nd.vy = (nd.vy / sp) * 12; }
      nd.x += nd.vx; nd.y += nd.vy;
    });
  }

  function graphFocus() {
    return graphSim.hover || graphSim.selected;
  }

  function isNear(name) {
    const f = graphFocus();
    if (!f) return true;
    if (name === f) return true;
    const nb = graphSim.adjacency.get(f);
    return nb ? nb.has(name) : false;
  }

  function drawGraph() {
    const dpr = window.devicePixelRatio || 1;
    const W = graphCanvas.clientWidth, H = graphCanvas.clientHeight;
    if (!W || !H) return;
    if (graphCanvas.width !== Math.round(W * dpr)) {
      graphCanvas.width = Math.round(W * dpr);
      graphCanvas.height = Math.round(H * dpr);
    }
    const ctx = graphCanvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, H);
    ctx.translate(W / 2 + graphView.x, H / 2 + graphView.y);
    ctx.scale(graphView.scale, graphView.scale);

    const css = getComputedStyle(document.documentElement);
    const line = css.getPropertyValue("--glass-border").trim();
    const fg = css.getPropertyValue("--fg").trim();
    const dim = css.getPropertyValue("--fg-faint").trim();
    const accent = css.getPropertyValue("--accent").trim();
    const focus = graphFocus();

    // edges
    ctx.lineWidth = 1 / graphView.scale;
    graphData.links.forEach(({ a, b }) => {
      const lit = focus && (a.name === focus || b.name === focus);
      ctx.strokeStyle = lit ? accent : line;
      ctx.globalAlpha = focus ? (lit ? 0.95 : 0.12) : 0.5;
      ctx.lineWidth = (lit ? 1.8 : 1) / graphView.scale;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    });
    ctx.globalAlpha = 1;

    // nodes
    const labelAll = graphView.scale > 1.35;
    ctx.font = `${11 / graphView.scale}px ui-monospace, monospace`;
    ctx.textBaseline = "middle";
    graphData.nodes.forEach((nd) => {
      const near = isNear(nd.name);
      ctx.globalAlpha = near ? 1 : 0.18;
      ctx.beginPath();
      ctx.arc(nd.x, nd.y, nd.r, 0, 7);
      ctx.fillStyle = graphColor(nd, css);
      ctx.fill();
      if (nd.name === graphSim.selected) {
        ctx.strokeStyle = fg;
        ctx.lineWidth = 2 / graphView.scale;
        ctx.stroke();
      }
      const showLabel = labelAll || (focus && near) || nd.degree >= 6;
      if (showLabel) {
        ctx.fillStyle = nd.name === focus ? fg : dim;
        ctx.fillText(nd.title || nd.name.split(".").pop(),
                     nd.x + nd.r + 4 / graphView.scale, nd.y);
      }
      ctx.globalAlpha = 1;
    });
  }

  /* -------- interaction -------- */
  function graphPointAt(ev) {
    const rect = graphCanvas.getBoundingClientRect();
    const x = (ev.clientX - rect.left - rect.width / 2 - graphView.x) / graphView.scale;
    const y = (ev.clientY - rect.top - rect.height / 2 - graphView.y) / graphView.scale;
    return { x, y };
  }

  function graphNodeAt(ev) {
    const { x, y } = graphPointAt(ev);
    let best = null, bestD = Infinity;
    graphData.nodes.forEach((n) => {
      const d = Math.hypot(n.x - x, n.y - y);
      if (d < Math.max(n.r + 6, 10) && d < bestD) { best = n; bestD = d; }
    });
    return best;
  }

  graphCanvas.addEventListener("mousedown", (ev) => {
    const node = graphNodeAt(ev);
    graphSim.moved = false;
    if (node) {
      graphSim.drag = { node, ...graphPointAt(ev) };
    } else {
      graphSim.panning = true;
      graphSim.px = ev.clientX; graphSim.py = ev.clientY;
    }
  });

  graphCanvas.addEventListener("mousemove", (ev) => {
    if (graphSim.drag) {
      const p = graphPointAt(ev);
      graphSim.drag.node.x = p.x;
      graphSim.drag.node.y = p.y;
      graphSim.alpha = Math.max(graphSim.alpha, 0.35);
      graphSim.moved = true;
      startGraph();
      return;
    }
    if (graphSim.panning) {
      graphView.x += ev.clientX - graphSim.px;
      graphView.y += ev.clientY - graphSim.py;
      graphSim.px = ev.clientX; graphSim.py = ev.clientY;
      graphSim.moved = true;
      drawGraph();
      return;
    }
    const node = graphNodeAt(ev);
    const name = node ? node.name : null;
    if (name !== graphSim.hover) {
      graphSim.hover = name;
      graphCanvas.style.cursor = name ? "pointer" : "grab";
      drawGraph();
    }
  });

  window.addEventListener("mouseup", (ev) => {
    if (graphSim.drag && !graphSim.moved) selectGraphNode(graphSim.drag.node);
    else if (graphSim.panning && !graphSim.moved) {
      graphSim.selected = null;
      drawGraph();
    }
    graphSim.drag = null;
    graphSim.panning = false;
  });

  graphCanvas.addEventListener("mouseleave", () => {
    if (graphSim.hover) { graphSim.hover = null; drawGraph(); }
  });

  graphCanvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const rect = graphCanvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left - rect.width / 2;
    const my = ev.clientY - rect.top - rect.height / 2;
    const before = graphView.scale;
    const next = Math.max(0.15, Math.min(6, before * (ev.deltaY < 0 ? 1.12 : 0.89)));
    // keep the point under the pointer fixed while zooming
    graphView.x = mx - ((mx - graphView.x) / before) * next;
    graphView.y = my - ((my - graphView.y) / before) * next;
    graphView.scale = next;
    drawGraph();
  }, { passive: false });

  graphCanvas.addEventListener("dblclick", () => resetGraphView());

  function selectGraphNode(node) {
    graphSim.selected = node.name;
    drawGraph();
    showSymbolInInspector(node.name);
  }

  function resetGraphView() {
    graphView.x = 0; graphView.y = 0; graphView.scale = 1;
    graphSim.alpha = 1;
    startGraph();
  }

  function fitGraphView() {
    if (!graphData.nodes.length) return;
    const xs = graphData.nodes.map((n) => n.x), ys = graphData.nodes.map((n) => n.y);
    const w = Math.max(...xs) - Math.min(...xs) || 1;
    const h = Math.max(...ys) - Math.min(...ys) || 1;
    const cx = (Math.max(...xs) + Math.min(...xs)) / 2;
    const cy = (Math.max(...ys) + Math.min(...ys)) / 2;
    const s = Math.min(graphCanvas.clientWidth / (w + 120),
                       graphCanvas.clientHeight / (h + 120), 2);
    graphView.scale = Math.max(0.15, s);
    graphView.x = -cx * graphView.scale;
    graphView.y = -cy * graphView.scale;
    drawGraph();
  }

  /* ===================================================================
   * Views, panels, palette
   * =================================================================== */
  function switchView(view) {
    $$(".act").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    $$(".side-panel").forEach((p) =>
      p.classList.toggle("hidden", p.dataset.panel !== view));
    document.getElementById("app").classList.remove("sidebar-collapsed");
    if (view === "graph") openPaneView("deps");
  }

  function switchUtil(util) {
    openPaneView(util);
  }

  function switchBottom(b) {
    openPaneView(b);
  }

  /* command palette */
  const COMMANDS = [
    { name: "Check file", kind: "cmd", run: runCheck },
    { name: "Save file", kind: "cmd", run: saveCurrent },
    { name: "Toggle theme", kind: "cmd", run: toggleTheme },
    { name: "Export: LaTeX", kind: "export", run: () => doExport("latex", "tex") },
    { name: "Export: Markdown", kind: "export", run: () => doExport("markdown", "md") },
    { name: "Export: JSON", kind: "export", run: () => doExport("json", "json") },
    { name: "Export: Python", kind: "export", run: () => doExport("python", "py") },
    { name: "Export: Lean", kind: "export", run: () => doExport("lean", "lean") },
    { name: "New file", kind: "cmd", run: newFile },
    { name: "Split pane right", kind: "pane",
      run: () => EpsilonPanes.splitPane("row") },
    { name: "Split pane down", kind: "pane",
      run: () => EpsilonPanes.splitPane("col") },
    { name: "Maximize pane", kind: "pane",
      run: () => EpsilonPanes.toggleMaximize() },
    { name: "Reset workspace layout", kind: "pane",
      run: () => { EpsilonPanes.reset(); toast("Workspace reset", "ok"); } },
  ];

  // opening any registered view, and switching workspace profile, are
  // commands too - so every tool is reachable without hunting for a button
  const PANE_COMMANDS = [
    ["editor", "Editor"], ["proof", "Proof"], ["plot", "Plot"],
    ["inspector", "Inspector"], ["problems", "Problems"],
    ["console", "Console"], ["output", "Output"],
    ["cas", "CAS"], ["render", "Rendered mathematics"],
    ["deps", "Dependency graph"],
  ].map(([id, label]) => ({
    name: "Open: " + label, kind: "view", run: () => openPaneView(id),
  }));

  const PROFILE_COMMANDS = [
    ["mathematics", "Mathematics"], ["algorithm", "Algorithm"],
    ["research", "Research"], ["minimal", "Minimal"],
  ].map(([id, label]) => ({
    name: "Workspace: " + label, kind: "layout",
    run: () => { EpsilonPanes.applyProfile(id); toast(label + " layout", "ok"); },
  }));
  let paletteMode = "cmd";
  let paletteItems = [];
  let paletteSel = 0;

  function openPalette(mode) {
    paletteMode = mode;
    $("#paletteOverlay").classList.remove("hidden");
    const input = $("#paletteInput");
    input.value = "";
    input.placeholder = mode === "file" ? "Go to file…" : "Type a command…";
    updatePalette("");
    input.focus();
  }
  function closePalette() { $("#paletteOverlay").classList.add("hidden"); }

  function updatePalette(q) {
    q = q.toLowerCase();
    if (paletteMode === "file") {
      paletteItems = (state.files || [])
        .filter((f) => f.path.toLowerCase().includes(q))
        .map((f) => ({ name: f.path, kind: "file", run: () => openFile(f.path) }));
    } else {
      paletteItems = COMMANDS.concat(PANE_COMMANDS, PROFILE_COMMANDS)
        .filter((c) => c.name.toLowerCase().includes(q));
    }
    paletteSel = 0;
    renderPalette();
  }

  function renderPalette() {
    const list = $("#paletteList");
    list.innerHTML = "";
    paletteItems.forEach((it, i) => {
      const li = el("li", "palette-item" + (i === paletteSel ? " sel" : ""));
      li.appendChild(el("span", null, it.name));
      li.appendChild(el("span", "pk", it.kind));
      li.onclick = () => { closePalette(); it.run(); };
      list.appendChild(li);
    });
  }

  $("#paletteInput").addEventListener("input", (e) => updatePalette(e.target.value));
  $("#paletteInput").addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { paletteSel = Math.min(paletteItems.length - 1, paletteSel + 1); renderPalette(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { paletteSel = Math.max(0, paletteSel - 1); renderPalette(); e.preventDefault(); }
    else if (e.key === "Enter") { const it = paletteItems[paletteSel]; closePalette(); if (it) it.run(); }
    else if (e.key === "Escape") closePalette();
  });
  $("#paletteOverlay").addEventListener("click", (e) => {
    if (e.target.id === "paletteOverlay") closePalette();
  });

  async function doExport(format, ext) {
    const tab = currentTab();
    if (!tab) return;
    await saveCurrent();
    const r = await api("POST", "/api/export", { path: tab.path, format });
    if (!r.ok) { toast("Export failed", "err"); return; }
    const blob = new Blob([r.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = tab.path.replace(/\.epsl$/, "") + "." + ext;
    a.click();
    URL.revokeObjectURL(url);
    toast("Exported " + format, "ok");
  }

  /* ===================================================================
   * Console (REPL)
   * =================================================================== */

  /* ===================================================================
   * search
   * =================================================================== */
  let searchTimer = null;
  $("#searchInput").addEventListener("input", (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value;
    searchTimer = setTimeout(async () => {
      const r = await api("GET", "/api/completions?prefix=" + encodeURIComponent(q));
      const list = $("#searchResults");
      list.innerHTML = "";
      (r.items || []).slice(0, 40).forEach((it) => {
        const item = el("li", "search-item");
        // the citable name: the mathematical one when the library defines
        // it, otherwise the internal identifier. Both resolve in a proof.
        const cite = it.display_name || it.name;
        item.innerHTML =
          `<span class="sn">${esc(it.title || it.name)}</span><br>` +
          (it.display_name ? `<span class="si">${esc(it.name)}</span><br>` : "") +
          `<span class="ss">${esc(it.type || it.kind)}</span>`;
        item.title = "Click to insert " + cite;
        item.onclick = () => {
          editor.focus();
          insertAtCursor(cite);
          toast("Inserted " + cite, "ok");
        };
        list.appendChild(item);
      });
    }, 200);
  });

  /* ===================================================================
   * theme
   * =================================================================== */
  function toggleTheme() {
    const root = document.documentElement;
    const next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("epsilon-theme", next); } catch (e) {}
    if (EpsilonPanes.isOpen("deps")) drawGraph();
  }

  /* ===================================================================
   * Text geometry
   *
   * The editor is a textarea sitting under a highlight layer, both in the
   * same monospace face, so a caret or popup can be placed from (line,
   * column) once the cell size is measured. The measurement is redone
   * whenever the font may have changed rather than hard-coded.
   * =================================================================== */
  const metrics = { cw: 7.8, lh: 20, padL: 16, padT: 14 };

  function measureText() {
    const probe = el("span", null, "0".repeat(40));
    const cs = getComputedStyle(editor);
    probe.style.cssText =
      `position:absolute;visibility:hidden;white-space:pre;font:${cs.font}`;
    document.body.appendChild(probe);
    const w = probe.getBoundingClientRect().width / 40;
    probe.remove();
    if (w > 0) metrics.cw = w;
    metrics.lh = parseFloat(cs.lineHeight) || 20;
    metrics.padL = parseFloat(cs.paddingLeft) || 16;
    metrics.padT = parseFloat(cs.paddingTop) || 14;
  }

  function posToLineCol(pos) {
    const before = editor.value.slice(0, pos);
    const line = before.split("\n").length - 1;
    const col = pos - (before.lastIndexOf("\n") + 1);
    return { line, col };
  }

  /** Pixel position of a document offset, relative to the editor's box. */
  function caretXY(pos) {
    const { line, col } = posToLineCol(pos);
    return {
      x: metrics.padL + col * metrics.cw,
      y: metrics.padT + line * metrics.lh,
      line, col,
    };
  }

  /* ===================================================================
   * Animated caret
   *
   * The native caret cannot be styled, so it is hidden and drawn here.
   * It eases in and out rather than hard-blinking, and holds solid while
   * you are actually typing - a blink under the fingers is just noise.
   * =================================================================== */
  const caretEl = $("#caret");

  function updateCaret() {
    if (document.activeElement !== editor) {
      caretEl.classList.add("hidden");
      return;
    }
    // a selection has its own highlight; a caret on top would be confusing
    if (editor.selectionStart !== editor.selectionEnd) {
      caretEl.classList.add("hidden");
      return;
    }
    const p = caretXY(editor.selectionStart);
    caretEl.classList.remove("hidden");
    caretEl.style.transform = `translate(${p.x}px, ${p.y}px)`;
    caretEl.style.height = metrics.lh + "px";
    // restart the animation so the caret is solid at the moment of typing
    caretEl.classList.remove("blinking");
    void caretEl.offsetWidth;
    caretEl.classList.add("blinking");
  }

  /* ===================================================================
   * Word under a position
   * =================================================================== */
  const IDENT_RE = /[A-Za-z0-9_'.ℕℤℚℝℂπ]/;

  function wordAt(pos) {
    const v = editor.value;
    if (!v) return null;
    let s = pos, e = pos;
    while (s > 0 && IDENT_RE.test(v[s - 1])) s--;
    while (e < v.length && IDENT_RE.test(v[e])) e++;
    if (s === e) return null;
    let word = v.slice(s, e).replace(/^\.+|\.+$/g, "");
    if (!word || /^[0-9.]+$/.test(word)) return null;
    return { word, start: s, end: e };
  }

  /** Document offset for a mouse event over the editor. */
  function offsetAtPoint(clientX, clientY) {
    const rect = editor.getBoundingClientRect();
    const x = clientX - rect.left + editor.scrollLeft - metrics.padL;
    const y = clientY - rect.top + editor.scrollTop - metrics.padT;
    const line = Math.floor(y / metrics.lh);
    const col = Math.round(x / metrics.cw);
    const lines = editor.value.split("\n");
    if (line < 0 || line >= lines.length) return null;
    let off = 0;
    for (let i = 0; i < line; i++) off += lines[i].length + 1;
    return off + Math.max(0, Math.min(lines[line].length, col));
  }

  /* ===================================================================
   * Autocomplete
   * =================================================================== */
  const acEl = $("#autocomplete");
  const ac = { open: false, items: [], sel: 0, from: 0, token: 0 };
  const acCache = new Map();

  function currentPrefix() {
    const pos = editor.selectionStart;
    const v = editor.value;
    let s = pos;
    while (s > 0 && IDENT_RE.test(v[s - 1])) s--;
    return { text: v.slice(s, pos), start: s };
  }

  async function fetchCompletions(prefix) {
    if (acCache.has(prefix)) return acCache.get(prefix);
    const r = await api("GET", "/api/completions?prefix=" +
                        encodeURIComponent(prefix));
    const items = (r.items || []).slice(0, 60);
    acCache.set(prefix, items);
    if (acCache.size > 80) acCache.delete(acCache.keys().next().value);
    return items;
  }

  async function openAutocomplete(force) {
    // completions come from the Epsilon environment; there is nothing
    // honest to offer for a Python or C++ buffer yet
    if (!isEpsilon()) return closeAutocomplete();
    const { text, start } = currentPrefix();
    if (!force && text.length < 2) return closeAutocomplete();
    const token = ++ac.token;
    let items;
    try {
      items = await fetchCompletions(text);
    } catch (e) {
      return closeAutocomplete();
    }
    if (token !== ac.token) return;          // a newer request superseded this
    if (!items.length) return closeAutocomplete();
    ac.items = items;
    ac.sel = 0;
    ac.from = start;
    ac.open = true;
    renderAutocomplete();
  }

  function renderAutocomplete() {
    acEl.innerHTML = "";
    ac.items.forEach((it, i) => {
      const row = el("div", "ac-item" + (i === ac.sel ? " sel" : ""));
      const kind = el("span", "ac-kind " + it.kind, shortKind(it.kind));
      const main = el("div", "ac-main");
      main.appendChild(el("div", "ac-name", it.name));
      if (it.display_name) main.appendChild(el("div", "ac-title", it.title));
      else if (it.type) main.appendChild(el("div", "ac-type", it.type));
      row.appendChild(kind);
      row.appendChild(main);
      row.onmousedown = (ev) => { ev.preventDefault(); acceptCompletion(i); };
      acEl.appendChild(row);
    });
    const p = caretXY(ac.from);
    const wrapRect = $(".editor-wrap").getBoundingClientRect();
    const gut = $("#gutter").getBoundingClientRect().width;
    let left = gut + p.x - editor.scrollLeft;
    let top = p.y + metrics.lh - codeScroll.scrollTop;
    acEl.classList.remove("hidden");
    // flip above the line when there is no room below
    const h = acEl.getBoundingClientRect().height;
    if (top + h > wrapRect.height && p.y - h > 0) top = p.y - h - codeScroll.scrollTop;
    acEl.style.left = Math.max(4, Math.min(left, wrapRect.width - 320)) + "px";
    acEl.style.top = Math.max(0, top) + "px";
    scrollSelIntoView();
  }

  function shortKind(k) {
    return ({ theorem: "thm", definition: "def", axiom: "ax",
              constructor: "ctor", recursor: "rec", inductive: "ind",
              opaque: "const", tactic: "tac", keyword: "kw" }[k] || k)
      .slice(0, 5);
  }

  function scrollSelIntoView() {
    const row = acEl.children[ac.sel];
    if (row) row.scrollIntoView({ block: "nearest" });
  }

  function moveAutocomplete(delta) {
    ac.sel = (ac.sel + delta + ac.items.length) % ac.items.length;
    renderAutocomplete();
  }

  function acceptCompletion(index) {
    const it = ac.items[index != null ? index : ac.sel];
    if (!it) return closeAutocomplete();
    const insert = it.display_name || it.name;
    const pos = editor.selectionStart;
    editor.setRangeText(insert, ac.from, pos, "end");
    closeAutocomplete();
    editor.dispatchEvent(new Event("input"));
    updateCaret();
  }

  function closeAutocomplete() {
    ac.open = false;
    ac.items = [];
    acEl.classList.add("hidden");
  }

  /* ===================================================================
   * Hover and go-to-definition
   * =================================================================== */
  const tip = $("#hoverTip");
  let hoverTimer = null;
  let hoverWord = null;

  function hideTip() {
    tip.classList.add("hidden");
    hoverWord = null;
  }

  async function showTipFor(word, clientX, clientY) {
    if (!isEpsilon()) return;
    let r;
    try {
      r = await api("GET", "/api/hover?name=" + encodeURIComponent(word));
    } catch (e) { return; }
    const info = r && r.info;
    if (!info || hoverWord !== word) return;
    tip.innerHTML = "";
    if (info.title && info.title !== info.name) {
      tip.appendChild(el("div", "tip-title", info.title));
    }
    tip.appendChild(el("div", "tip-name", info.name));
    if (info.type) tip.appendChild(el("div", "tip-type", info.type));
    if (info.status_label) {
      tip.appendChild(el("div", "tip-status " + info.status, info.status_label));
    }
    if (info.doc) tip.appendChild(el("div", "tip-doc", info.doc));
    if (info.axioms && info.axioms.length) {
      tip.appendChild(el("div", "tip-doc",
                         "axioms: " + info.axioms.join(", ")));
    }
    tip.appendChild(el("div", "tip-hint",
                       (isMac ? "⌘" : "Ctrl") + "+click to go to definition"));
    tip.classList.remove("hidden");
    const box = tip.getBoundingClientRect();
    const x = Math.min(clientX + 12, window.innerWidth - box.width - 10);
    const y = clientY + 22 + box.height > window.innerHeight
      ? clientY - box.height - 10 : clientY + 22;
    tip.style.left = Math.max(6, x) + "px";
    tip.style.top = Math.max(6, y) + "px";
  }

  function showSymbolInInspector(name) {
    switchUtil("inspector");
    api("GET", "/api/hover?name=" + encodeURIComponent(name)).then((r) => {
      const info = r && r.info;
      const panel = $("#inspectorSymbol");
      panel.innerHTML = "";
      if (!info) {
        panel.appendChild(el("div", "empty-hint", "Unknown symbol: " + name));
        return;
      }
      const item = el("div", "inspector-item");
      item.appendChild(el("div", "ik", (info.kind || "symbol").toUpperCase()));
      if (info.title && info.title !== info.name) {
        item.appendChild(el("div", "tip-title", info.title));
      }
      item.appendChild(el("div", "tip-name", info.name));
      if (info.type) item.appendChild(el("div", "tip-type", info.type));
      if (info.status_label) {
        item.appendChild(el("div", "tip-status " + info.status,
                            info.status_label));
      }
      if (info.doc) item.appendChild(el("div", "tip-doc", info.doc));
      if (info.module) {
        item.appendChild(el("div", "tip-doc", "module: " + info.module));
      }
      panel.appendChild(item);
    });
  }

  async function goToDefinition(word) {
    if (!isEpsilon()) return;
    let r;
    try {
      r = await api("GET", "/api/definition?name=" + encodeURIComponent(word));
    } catch (e) { return; }
    const loc = r && r.location;
    if (loc && loc.span) {
      const file = (state.files || []).find(
        (f) => f.path.replace(/\.epsl$/, "") === loc.module);
      const here = state.active &&
        state.active.replace(/\.epsl$/, "").split("/").pop() === loc.module;
      // only navigate when the definition is in a file we can actually show;
      // a library span would otherwise scroll to a meaningless line here
      if (here) {
        gotoSpan(loc.span);
        toast("Jumped to " + loc.name, "ok");
        return;
      }
      if (file) {
        await openFile(file.path);
        setTimeout(() => gotoSpan(loc.span), 140);
        toast("Jumped to " + loc.name, "ok");
        return;
      }
    }
    // library symbols have no file in the workspace: show them instead of
    // navigating nowhere
    showSymbolInInspector(word);
  }

  /* ===================================================================
   * Console
   * =================================================================== */
  const consoleInput = $("#consoleInput");
  const CONSOLE_HISTORY_KEY = "epsilon.console.history.v1";
  let consoleHistory = [];
  let histIdx = 0;

  function loadConsoleHistory() {
    try {
      consoleHistory = JSON.parse(localStorage.getItem(CONSOLE_HISTORY_KEY)) || [];
    } catch (e) { consoleHistory = []; }
    histIdx = consoleHistory.length;
  }

  function saveConsoleHistory() {
    try {
      localStorage.setItem(CONSOLE_HISTORY_KEY,
                           JSON.stringify(consoleHistory.slice(-200)));
    } catch (e) {}
  }

  function appendConsole(text, cls) {
    const log = $("#consoleLog");
    const line = el("div", "console-line " + (cls || ""));
    line.textContent = text;
    if (cls !== "in") {
      const copy = el("button", "console-copy", "copy");
      copy.title = "Copy this result";
      copy.onclick = () => {
        navigator.clipboard && navigator.clipboard.writeText(text);
        toast("Copied", "ok");
      };
      line.appendChild(copy);
    }
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
    return line;
  }

  function clearConsole() {
    $("#consoleLog").innerHTML = "";
  }

  async function runConsole(code) {
    consoleHistory.push(code);
    saveConsoleHistory();
    histIdx = consoleHistory.length;
    appendConsole(code, "in");
    const pending = appendConsole("…", "pending");
    let r;
    try {
      r = await api("POST", "/api/eval", { code });
    } catch (e) {
      pending.remove();
      appendConsole(String(e), "err");
      return;
    }
    pending.remove();
    if (r.output) appendConsole(r.output, r.ok ? "" : "err");
    (r.diagnostics || []).forEach((d) => appendConsole(d, "err"));
  }

  function autosizeConsoleInput() {
    consoleInput.style.height = "auto";
    consoleInput.style.height =
      Math.min(140, consoleInput.scrollHeight) + "px";
  }

  async function consoleComplete() {
    const pos = consoleInput.selectionStart;
    const v = consoleInput.value;
    let s = pos;
    while (s > 0 && IDENT_RE.test(v[s - 1])) s--;
    const prefix = v.slice(s, pos);
    if (prefix.length < 2) return;
    const items = await fetchCompletions(prefix);
    if (!items.length) return;
    if (items.length === 1) {
      consoleInput.setRangeText(items[0].name, s, pos, "end");
      return;
    }
    appendConsole(items.slice(0, 12).map((i) => i.name).join("   "), "hint");
  }

  /* ===================================================================
   * Editor intelligence wiring
   * =================================================================== */
  function wireIntelligence() {
    measureText();
    editor.classList.add("custom-caret");
    loadConsoleHistory();

    // --- caret ---
    ["input", "click", "keyup", "focus", "select"].forEach((ev) =>
      editor.addEventListener(ev, updateCaret));
    editor.addEventListener("blur", () => { updateCaret(); closeAutocomplete(); });
    codeScroll.addEventListener("scroll", () => {
      caretEl.style.marginTop = -codeScroll.scrollTop + "px";
      caretEl.style.marginLeft = -codeScroll.scrollLeft + "px";
      if (ac.open) renderAutocomplete();
    });

    // --- autocomplete keys, before the editor's own handler ---
    editor.addEventListener("keydown", (ev) => {
      const mod = isMac ? ev.metaKey : ev.ctrlKey;
      if (mod && ev.code === "Space") {
        ev.preventDefault();
        openAutocomplete(true);
        return;
      }
      if (!ac.open) return;
      if (ev.key === "ArrowDown") { ev.preventDefault(); moveAutocomplete(1); }
      else if (ev.key === "ArrowUp") { ev.preventDefault(); moveAutocomplete(-1); }
      else if (ev.key === "Enter" || ev.key === "Tab") {
        ev.preventDefault();
        ev.stopPropagation();
        acceptCompletion();
      } else if (ev.key === "Escape") {
        ev.preventDefault();
        closeAutocomplete();
      }
    }, true);

    editor.addEventListener("input", () => {
      const { text } = currentPrefix();
      if (text.length >= 2) openAutocomplete(false);
      else closeAutocomplete();
    });

    // --- hover ---
    editor.addEventListener("mousemove", (ev) => {
      if (!isEpsilon()) { editor.classList.remove("linking"); hideTip(); return; }
      if (ev.ctrlKey || ev.metaKey) editor.classList.add("linking");
      else editor.classList.remove("linking");
      clearTimeout(hoverTimer);
      const off = offsetAtPoint(ev.clientX, ev.clientY);
      const w = off == null ? null : wordAt(off);
      if (!w) { hideTip(); return; }
      if (w.word === hoverWord) return;
      hoverWord = w.word;
      const { clientX, clientY } = ev;
      hoverTimer = setTimeout(() => showTipFor(w.word, clientX, clientY), 320);
    });
    editor.addEventListener("mouseleave", () => {
      clearTimeout(hoverTimer);
      hideTip();
      editor.classList.remove("linking");
    });
    window.addEventListener("keyup", (ev) => {
      if (!ev.ctrlKey && !ev.metaKey) editor.classList.remove("linking");
    });

    // --- ctrl/cmd + click: go to definition ---
    editor.addEventListener("mousedown", (ev) => {
      const mod = isMac ? ev.metaKey : ev.ctrlKey;
      if (!mod) return;
      const off = offsetAtPoint(ev.clientX, ev.clientY);
      const w = off == null ? null : wordAt(off);
      if (!w) return;
      ev.preventDefault();
      hideTip();
      goToDefinition(w.word);
    });

    // --- console ---
    consoleInput.addEventListener("input", autosizeConsoleInput);
    consoleInput.addEventListener("keydown", async (ev) => {
      if (ev.key === "Enter" && !ev.shiftKey) {
        ev.preventDefault();
        const code = consoleInput.value.trim();
        if (!code) return;
        consoleInput.value = "";
        autosizeConsoleInput();
        await runConsole(code);
      } else if (ev.key === "Tab") {
        ev.preventDefault();
        consoleComplete();
      } else if (ev.key === "ArrowUp" && !consoleInput.value.includes("\n")) {
        if (histIdx > 0) {
          histIdx--;
          consoleInput.value = consoleHistory[histIdx] || "";
          autosizeConsoleInput();
        }
      } else if (ev.key === "ArrowDown" && !consoleInput.value.includes("\n")) {
        if (histIdx < consoleHistory.length) {
          histIdx++;
          consoleInput.value = consoleHistory[histIdx] || "";
          autosizeConsoleInput();
        }
      }
    });
    $("#consoleClear").onclick = clearConsole;

    // --- graph tools ---
    wireGraphFilters();
    $("#graphFit").onclick = fitGraphView;
    $("#graphReset").onclick = resetGraphView;

    window.addEventListener("resize", () => {
      measureText();
      updateCaret();
      if (EpsilonPanes.isOpen("deps")) drawGraph();
    });
  }


  /* ===================================================================
   * Rendered mathematics pane
   *
   * The same declarations the kernel checked, typeset. MathML, which the
   * browser draws itself — the IDE ships no typesetting library. The source
   * is never rewritten to make a rendering work; this is a layer over it,
   * and each block keeps the status the engine reported.
   * =================================================================== */
  const render = { blocks: [], latex: "", showSource: false, busy: false };

  async function refreshRender() {
    const tab = currentTab();
    const body = $("#renderBody");
    if (!body) return;
    if (!tab || !isEpsilon()) {
      body.innerHTML = "";
      body.appendChild(el("div", "empty-hint",
        "Open an Epsilon file to see it typeset."));
      return;
    }
    if (render.busy) return;
    render.busy = true;
    let r;
    try {
      r = await api("POST", "/api/render", { path: tab.path, content: tab.content });
    } finally {
      render.busy = false;
    }
    render.blocks = (r && r.blocks) || [];
    render.latex = (r && r.document_latex) || "";
    renderRendered(r && r.diagnostics);
  }

  function renderRendered(diagnostics) {
    const body = $("#renderBody");
    if (!body) return;
    body.innerHTML = "";

    if (!render.blocks.length) {
      const why = (diagnostics || []).find((d) => d.severity === "error");
      body.appendChild(el("div", "empty-hint", why
        ? "Nothing to render yet — the file has an error: " + why.message
        : "No definitions or theorems in this file yet."));
      return;
    }

    render.blocks.forEach((b) => {
      const card = el("div", "render-block");

      const head = el("div", "render-head");
      head.appendChild(el("span", "render-kind", b.kind));
      head.appendChild(el("span", "render-name", b.title || b.name));
      if (b.display_name && b.display_name !== b.name)
        head.appendChild(el("code", "render-ident", b.name));
      if (b.status_label)
        head.appendChild(el("span", "status-chip " + b.status, b.status_label));
      head.onclick = () => { if (b.span && b.span[0]) gotoSpan(b.span); };
      head.title = "Go to the source";
      card.appendChild(head);

      if (b.doc) card.appendChild(el("div", "render-doc", b.doc));

      card.appendChild(renderMath(b.type, b.statement));
      if (b.value) card.appendChild(renderMath(b.value, null, "definition"));

      if (b.axioms && b.axioms.length) {
        card.appendChild(el("div", "render-axioms",
          "depends on: " + b.axioms.join(", ")));
      }
      body.appendChild(card);
    });
  }

  function renderMath(forms, sourceText, cls) {
    const wrap = el("div", "render-math" + (cls ? " " + cls : ""));
    if (forms && forms.mathml) {
      const m = el("div", "math-render");
      m.innerHTML = forms.mathml;
      wrap.appendChild(m);
    }
    if (render.showSource) {
      const src = sourceText || (forms && forms.latex) || "";
      if (src) wrap.appendChild(el("code", "render-source", src));
    }
    return wrap;
  }

  /* ===================================================================
   * CAS pane
   *
   * Computer algebra, kept visibly separate from proof. Every result is
   * labelled with the status the engine reports, and the label for a CAS
   * answer is "Symbolically Verified" — never "Formally Proven". The two
   * are different claims and the IDE never blurs them.
   * =================================================================== */
  const cas = { ops: [], history: [], busy: false };

  async function loadCasOperations() {
    if (cas.ops.length) return cas.ops;
    const r = await api("GET", "/api/cas/operations");
    cas.ops = r.operations || [];
    const select = $("#casOp");
    if (select) {
      select.innerHTML = "";
      cas.ops.forEach((o) => {
        const opt = el("option", null, o.label);
        opt.value = o.op;
        opt.title = o.description;
        select.appendChild(opt);
      });
      select.onchange = syncCasFields;
    }
    syncCasFields();
    return cas.ops;
  }

  /** Only show the inputs the chosen operation actually reads. */
  function syncCasFields() {
    const op = $("#casOp") && $("#casOp").value;
    const spec = cas.ops.find((o) => o.op === op);
    const wantsPoint = op === "limit" || op === "taylor" || op === "evaluate";
    const wantsOrder = op === "taylor";
    const wantsVar = spec ? spec.needs_variable : false;
    const show = (sel, on) => {
      const e = $(sel);
      if (e) e.classList.toggle("hidden", !on);
    };
    show("#casVar", wantsVar);
    show("#casPoint", wantsPoint);
    show("#casOrder", wantsOrder);
    const hint = $("#casHint");
    if (hint) hint.textContent = spec ? spec.description : "";
    const point = $("#casPoint");
    if (point) {
      point.placeholder = op === "evaluate" ? "value of the variable" : "0";
    }
  }

  async function runCas() {
    if (cas.busy) return;
    const expr = ($("#casExpr").value || "").trim();
    if (!expr) return;
    const op = $("#casOp").value;
    cas.busy = true;
    $("#casRun").classList.add("running");
    let r;
    try {
      r = await api("POST", "/api/cas", {
        op,
        expr,
        variable: ($("#casVar").value || "").trim() || null,
        point: ($("#casPoint").value || "").trim() || "0",
        order: Number($("#casOrder").value) || 5,
      });
    } finally {
      cas.busy = false;
      $("#casRun").classList.remove("running");
    }
    cas.history.unshift({ expr, ...r });
    renderCas();
  }

  function renderCas() {
    const panel = $("#casResults");
    if (!panel) return;
    panel.innerHTML = "";
    if (!cas.history.length) {
      panel.appendChild(el("div", "empty-hint",
        "A CAS result is Symbolically Verified, never a formal proof."));
      return;
    }
    cas.history.forEach((h, idx) => panel.appendChild(casCard(h, idx)));
  }

  function casCard(h, idx) {
    const card = el("div", "cas-card" + (h.ok ? "" : " failed"));

    const head = el("div", "cas-card-head");
    head.appendChild(el("span", "cas-op-label", h.label || h.op));
    if (h.ok) {
      const chip = el("span", "status-chip " + h.status, h.status_label);
      chip.title = "Computer algebra, not a kernel proof";
      head.appendChild(chip);
    }
    const drop = el("button", "mini-btn", "×");
    drop.title = "Remove";
    drop.onclick = () => { cas.history.splice(idx, 1); renderCas(); };
    head.appendChild(drop);
    card.appendChild(head);

    card.appendChild(mathRow("input", h.expr, h.input));

    if (!h.ok) {
      card.appendChild(el("div", "cas-error", h.message || "failed"));
      return card;
    }

    if (h.result) card.appendChild(mathRow("result", null, h.result));
    (h.results || []).forEach((t, i) =>
      card.appendChild(mathRow(`solution ${i + 1}`, null, t)));
    if (h.note) card.appendChild(el("div", "cas-note", h.note));

    const actions = el("div", "cas-actions");
    const first = h.result || (h.results || [])[0];
    if (first) {
      const insert = el("button", "chip-btn", "Insert in editor");
      insert.onclick = () => insertAtCaret(first.source);
      actions.appendChild(insert);
      const copyLatex = el("button", "chip-btn", "Copy LaTeX");
      copyLatex.onclick = () => {
        if (navigator.clipboard) navigator.clipboard.writeText(first.latex || "");
        toast("LaTeX copied", "ok");
      };
      actions.appendChild(copyLatex);
    }
    card.appendChild(actions);
    return card;
  }

  /**
   * A term shown as rendered mathematics with its Epsilon source beneath.
   * Rendering is MathML, which browsers draw natively — the IDE ships no
   * external typesetting library, and the source is never rewritten to make
   * the rendering work.
   */
  function mathRow(label, fallbackSource, forms) {
    const row = el("div", "cas-row");
    row.appendChild(el("span", "cas-row-label", label));
    const body = el("div", "cas-row-body");
    if (forms && forms.mathml) {
      const rendered = el("div", "math-render");
      rendered.innerHTML = forms.mathml;
      body.appendChild(rendered);
    }
    const src = (forms && forms.source) || fallbackSource || "";
    if (src) body.appendChild(el("code", "cas-source", src));
    row.appendChild(body);
    return row;
  }

  /** Paste text at the editor caret, the way a result should come back. */
  function insertAtCaret(text) {
    if (!text) return;
    EpsilonPanes.openView("editor");
    const start = editor.selectionStart;
    const end = editor.selectionEnd;
    editor.value = editor.value.slice(0, start) + text + editor.value.slice(end);
    editor.selectionStart = editor.selectionEnd = start + text.length;
    editor.focus();
    const tab = currentTab();
    if (tab) {
      tab.content = editor.value;
      tab.dirty = tab.content !== tab.saved;
      renderTabs();
    }
    renderEditor();
    updateCaret();
    scheduleCheck();
  }

  /* ===================================================================
   * Pane workspace
   *
   * Every tool is a view in the shared pane system rather than a panel
   * nailed to a fixed grid slot. The view elements are the same DOM nodes
   * the rest of this file already talks to, so nothing else has to change.
   * =================================================================== */
  const PANE_VIEWS = [
    { id: "editor",    title: "Editor",     icon: "∑", element: "#viewEditor",
      closable: false, onShow: () => { measureText(); renderEditor(); updateCaret(); } },
    { id: "proof",     title: "Proof",      icon: "∴", element: "#proofPanel" },
    { id: "plot",      title: "Plot",       icon: "📈", element: "#plotPanel",
      onShow: () => { if (state.lastCheck) renderPlots(state.lastCheck.plots || []); } },
    { id: "inspector", title: "Inspector",  icon: "🔍", element: "#inspectorPanel" },
    { id: "problems",  title: "Problems",   icon: "⚠", element: "#problemsPanel" },
    { id: "console",   title: "Console",    icon: "›", element: "#consolePanel" },
    { id: "output",    title: "Output",     icon: "⎙", element: "#outputPanel" },
    { id: "render",    title: "Rendered",   icon: "𝛴", element: "#renderPanel",
      onShow: () => refreshRender() },
    { id: "cas",       title: "CAS",        icon: "∫", element: "#casPanel",
      onShow: () => { loadCasOperations(); } },
    { id: "deps",      title: "Dependencies", icon: "◇", element: "#viewDeps",
      onShow: () => {
        graphSim.alpha = Math.max(graphSim.alpha, 0.9);
        startGraph();
        setTimeout(fitGraphView, 800);
      } },
  ];

  function initPanes() {
    EpsilonPanes.init({
      host: "#paneHost",
      vault: "#viewVault",
      views: PANE_VIEWS,
      onChange: () => {
        // geometry changed: canvases and the caret need remeasuring
        requestAnimationFrame(() => {
          measureText();
          updateCaret();
          if (EpsilonPanes.isOpen("deps")) drawGraph(); else stopGraph();
          if (state.lastCheck) renderPlots(state.lastCheck.plots || []);
        });
      },
    });
  }

  function openPaneView(id) { EpsilonPanes.openView(id); }

  /* ===================================================================
   * wiring
   * =================================================================== */
  function wire() {
    $("#checkBtn").onclick = runCheck;
    $("#themeBtn").onclick = toggleTheme;
    $("#newFileBtn").onclick = () => newFile();
    $("#newFolderBtn").onclick = () => newFolder();
    $("#refreshFilesBtn").onclick = () => loadFiles();
    $("#collapseAllBtn").onclick = () => {
      (state.entries || []).forEach((e) => {
        if (e.kind === "folder") collapsed.add(e.path);
      });
      persistCollapsed();
      renderFileList();
    };
    $("#renderRefresh").onclick = refreshRender;
    $("#renderShowSource").onchange = (e) => {
      render.showSource = e.target.checked;
      renderRendered();
    };
    $("#renderCopyLatex").onclick = () => {
      if (navigator.clipboard) navigator.clipboard.writeText(render.latex || "");
      toast("LaTeX document copied", "ok");
    };
    $("#casRun").onclick = runCas;
    $("#casExpr").addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); runCas(); }
    });
    $("#fileFilter").oninput = (e) => {
      state.fileFilter = e.target.value;
      renderFileList();
    };
    // the context menu closes on any click elsewhere, or on Escape
    document.addEventListener("mousedown", (e) => {
      const menu = $("#ctxMenu");
      if (menu && !menu.classList.contains("hidden") && !menu.contains(e.target))
        closeContextMenu();
    });
    $("#fileList").oncontextmenu = (e) => {
      if (e.target.closest(".file-item")) return;   // handled per row
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY,
                      { name: "workspace", path: "", kind: "folder" });
    };
    $("#paletteBtn").onclick = () => openPalette("cmd");
    $$(".act[data-view]").forEach((a) =>
      (a.onclick = () => switchView(a.dataset.view)));

    document.addEventListener("keydown", (e) => {
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key === "Enter") { e.preventDefault(); runCheck(); }
      else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveCurrent(); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === "p") { e.preventDefault(); openPalette("cmd"); }
      else if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); openPalette("file"); }
      else if (e.key === "Escape") { closePalette(); closeContextMenu(); }
    });
    window.addEventListener("resize", () => {
      if (EpsilonPanes.isOpen("deps")) drawGraph();
    });
  }

  async function init() {
    try {
      const saved = localStorage.getItem("epsilon-theme");
      if (saved) document.documentElement.setAttribute("data-theme", saved);
    } catch (e) {}
    initPanes();
    wire();
    wireIntelligence();
    state.meta = await api("GET", "/api/meta");
    $("#metaVersion").textContent = "v" + (state.meta.version || "0.1");
    await loadFiles();
  }

  init();
})();
