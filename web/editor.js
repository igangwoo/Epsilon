/* ===================================================================
 * Epsilon — the code editor.
 *
 * An instantiable editor component over a textarea. The textarea is kept
 * deliberately: it brings the platform's text input — IME, native
 * selection, native undo, accessibility — for free, and everything a code
 * editor adds (indentation, bracket pairs, block edits, decorations, a
 * find widget, completion) is layered on top without replacing it.
 *
 * Two layers in this file:
 *   EditorOps  — pure text operations: (text, selection, options) in,
 *                (text, selection) out. No DOM; tested under node.
 *   CodeEditor — the component: renders, highlights, decorates, wires
 *                keys through the ops, hosts the find widget and the
 *                completion list.
 *
 * What a textarea cannot do is not imitated: multiple cursors, column
 * selection and code folding need a custom text surface, and the commands
 * for them are registered disabled with exactly that reason.
 * =================================================================== */
(function (root) {
  "use strict";

  /* =================================================================
   * Language tables
   * ================================================================= */
  const LANGS = {
    python: {
      comment: "#",
      indentAfter: /[:({[]\s*$/,
      electricDedent: null,
      pairs: { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" },
    },
    cpp: {
      comment: "//",
      indentAfter: /[{([]\s*$/,
      electricDedent: "}",
      pairs: { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" },
    },
    javascript: {
      comment: "//",
      indentAfter: /[{([]\s*$/,
      electricDedent: "}",
      pairs: { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'", "`": "`" },
    },
    epsilon: {
      comment: "--",
      indentAfter: /(:=|=>|\bby|\bwith|[({[])\s*$/,
      electricDedent: null,
      pairs: { "(": ")", "[": "]", "{": "}", '"': '"' },
    },
    plain: { comment: null, indentAfter: null, electricDedent: null,
             pairs: { "(": ")", "[": "]", "{": "}", '"': '"' } },
  };
  LANGS.markdown = { ...LANGS.plain };
  LANGS.json = { ...LANGS.plain, indentAfter: /[{[]\s*$/, electricDedent: "}" };
  LANGS.shell = { ...LANGS.plain, comment: "#" };
  LANGS.yaml = { ...LANGS.plain, comment: "#", indentAfter: /:\s*$/ };
  LANGS.toml = { ...LANGS.plain, comment: "#" };
  LANGS.latex = { ...LANGS.plain, comment: "%" };
  LANGS.html = { ...LANGS.plain };
  LANGS.css = { ...LANGS.plain, comment: null };

  function langOf(id) { return LANGS[id] || LANGS.plain; }

  /* =================================================================
   * EditorOps — pure text operations
   *
   * Every op takes (text, selStart, selEnd, opts) and returns
   * {text, selStart, selEnd} (text omitted when unchanged). opts carries
   * {language, tabSize, insertSpaces}.
   * ================================================================= */
  const EditorOps = {};

  function unit(opts) {
    return opts.insertSpaces === false ? "\t" : " ".repeat(opts.tabSize || 4);
  }

  function lineStart(text, at) {
    return text.lastIndexOf("\n", at - 1) + 1;
  }
  function lineEnd(text, at) {
    const idx = text.indexOf("\n", at);
    return idx === -1 ? text.length : idx;
  }
  function indentOf(line) {
    return (line.match(/^[ \t]*/) || [""])[0];
  }

  /** The [start, end) byte range of the full lines the selection touches. */
  function blockRange(text, selStart, selEnd) {
    const start = lineStart(text, selStart);
    let end = lineEnd(text, Math.max(selStart, selEnd > selStart &&
      text[selEnd - 1] === "\n" ? selEnd - 1 : selEnd));
    return [start, end];
  }

  /** What Enter should insert at this position. */
  EditorOps.newlineIndent = function (text, at, opts) {
    const lang = langOf(opts.language);
    const start = lineStart(text, at);
    const line = text.slice(start, lineEnd(text, at));
    const before = text.slice(start, at);
    let indent = indentOf(line);
    let extra = "";
    let after = "";
    if (lang.indentAfter && lang.indentAfter.test(before.trimEnd())) {
      extra = unit(opts);
      // between a freshly opened bracket and its closer: push the closer
      // to its own line at the old indent ("smart newline")
      const closer = { "(": ")", "[": "]", "{": "}" }[before.trimEnd().slice(-1)];
      if (closer && text[at] === closer) {
        after = "\n" + indent;
      }
    }
    return { insert: "\n" + indent + extra, after };
  };

  /** Indent every line the selection touches by one unit. */
  EditorOps.indentBlock = function (text, selStart, selEnd, opts) {
    const [start, end] = blockRange(text, selStart, selEnd);
    const u = unit(opts);
    const lines = text.slice(start, end).split("\n");
    const replaced = lines.map((l) => (l.length ? u + l : l)).join("\n");
    const grewFirst = lines[0].length ? u.length : 0;
    return {
      text: text.slice(0, start) + replaced + text.slice(end),
      selStart: selStart + grewFirst,
      selEnd: selEnd + (replaced.length - (end - start)),
      range: [start, end], replacement: replaced,
    };
  };

  /** Dedent every line the selection touches by up to one unit. */
  EditorOps.dedentBlock = function (text, selStart, selEnd, opts) {
    const [start, end] = blockRange(text, selStart, selEnd);
    const width = opts.insertSpaces === false ? 1 : (opts.tabSize || 4);
    let firstCut = 0;
    const lines = text.slice(start, end).split("\n").map((l, i) => {
      let cut = 0;
      while (cut < width && (l[cut] === " " || (l[cut] === "\t" && cut === 0))) {
        if (l[cut] === "\t") { cut += 1; break; }
        cut += 1;
      }
      if (i === 0) firstCut = cut;
      return l.slice(cut);
    });
    const replaced = lines.join("\n");
    return {
      text: text.slice(0, start) + replaced + text.slice(end),
      selStart: Math.max(start, selStart - firstCut),
      selEnd: Math.max(start, selEnd - ((end - start) - replaced.length)),
      range: [start, end], replacement: replaced,
    };
  };

  /** Toggle the line comment on every line the selection touches. */
  EditorOps.toggleComment = function (text, selStart, selEnd, opts) {
    const token = langOf(opts.language).comment;
    if (!token) return null;
    const [start, end] = blockRange(text, selStart, selEnd);
    const lines = text.slice(start, end).split("\n");
    const content = lines.filter((l) => l.trim().length);
    const allCommented = content.length > 0 && content.every(
      (l) => l.trimStart().startsWith(token));
    const replaced = lines.map((l) => {
      if (!l.trim().length) return l;
      const ind = indentOf(l);
      const rest = l.slice(ind.length);
      if (allCommented) {
        const stripped = rest.startsWith(token + " ")
          ? rest.slice(token.length + 1) : rest.slice(token.length);
        return ind + stripped;
      }
      return ind + token + " " + rest;
    }).join("\n");
    const delta = replaced.length - (end - start);
    return {
      text: text.slice(0, start) + replaced + text.slice(end),
      selStart, selEnd: selEnd + delta,
      range: [start, end], replacement: replaced,
    };
  };

  /** Move the selected block one line up or down. */
  EditorOps.moveLines = function (text, selStart, selEnd, dir) {
    const [start, end] = blockRange(text, selStart, selEnd);
    if (dir < 0) {
      if (start === 0) return null;
      const prevStart = lineStart(text, start - 1);
      const prev = text.slice(prevStart, start - 1);
      const block = text.slice(start, end);
      const replaced = block + "\n" + prev;
      const shift = -(prev.length + 1);
      return {
        text: text.slice(0, prevStart) + replaced + text.slice(end),
        selStart: selStart + shift, selEnd: selEnd + shift,
        range: [prevStart, end], replacement: replaced,
      };
    }
    if (end >= text.length) return null;
    const nextEnd = lineEnd(text, end + 1);
    const next = text.slice(end + 1, nextEnd);
    const block = text.slice(start, end);
    const replaced = next + "\n" + block;
    const shift = next.length + 1;
    return {
      text: text.slice(0, start) + replaced + text.slice(nextEnd),
      selStart: selStart + shift, selEnd: selEnd + shift,
      range: [start, nextEnd], replacement: replaced,
    };
  };

  /** Duplicate the selected block below itself. */
  EditorOps.duplicateLines = function (text, selStart, selEnd) {
    const [start, end] = blockRange(text, selStart, selEnd);
    const block = text.slice(start, end);
    const shift = block.length + 1;
    return {
      text: text.slice(0, start) + block + "\n" + block + text.slice(end),
      selStart: selStart + shift, selEnd: selEnd + shift,
      range: [start, end], replacement: block + "\n" + block,
    };
  };

  /** Delete the lines the selection touches. */
  EditorOps.deleteLines = function (text, selStart, selEnd) {
    let [start, end] = blockRange(text, selStart, selEnd);
    let cutEnd = end;
    if (end < text.length) cutEnd = end + 1;         // take the newline too
    else if (start > 0) start -= 1;                  // last line: take the
    const newText = text.slice(0, start) + text.slice(cutEnd);   // one before
    const caret = Math.min(start, newText.length);
    return { text: newText, selStart: caret, selEnd: caret,
             range: [start, cutEnd], replacement: "" };
  };

  /** The matching bracket position for the one at/before `at`, or null. */
  EditorOps.matchBracket = function (text, at) {
    const OPEN = "([{", CLOSE = ")]}";
    const PAIR = { "(": ")", "[": "]", "{": "}",
                   ")": "(", "]": "[", "}": "{" };
    let pos = -1, ch = "";
    for (const p of [at, at - 1]) {
      const c = text[p];
      if (c && (OPEN + CLOSE).includes(c)) { pos = p; ch = c; break; }
    }
    if (pos === -1) return null;
    const forward = OPEN.includes(ch);
    const other = PAIR[ch];
    let depth = 0;
    if (forward) {
      for (let i = pos; i < text.length; i++) {
        if (text[i] === ch) depth += 1;
        else if (text[i] === other && --depth === 0) return [pos, i];
      }
    } else {
      for (let i = pos; i >= 0; i--) {
        if (text[i] === ch) depth += 1;
        else if (text[i] === other && --depth === 0) return [i, pos];
      }
    }
    return null;
  };

  /** Smart Home: first non-whitespace column, or 0 if already there. */
  EditorOps.smartHome = function (text, at) {
    const start = lineStart(text, at);
    const line = text.slice(start, lineEnd(text, at));
    const firstNonWs = start + indentOf(line).length;
    return at === firstNonWs ? start : firstNonWs;
  };

  /** The word range around `at` (identifier characters). */
  EditorOps.wordAt = function (text, at) {
    const isWord = (c) => /[A-Za-z0-9_]/.test(c || "");
    if (!isWord(text[at]) && !isWord(text[at - 1])) return null;
    let s = at, e = at;
    while (s > 0 && isWord(text[s - 1])) s -= 1;
    while (e < text.length && isWord(text[e])) e += 1;
    return [s, e];
  };

  /** The next occurrence of the selection (wrapping), for Ctrl+D. */
  EditorOps.nextOccurrence = function (text, selStart, selEnd) {
    if (selStart === selEnd) return EditorOps.wordAt(text, selStart);
    const needle = text.slice(selStart, selEnd);
    if (!needle) return null;
    let idx = text.indexOf(needle, selEnd);
    if (idx === -1) idx = text.indexOf(needle);
    if (idx === -1 || idx === selStart) return null;
    return [idx, idx + needle.length];
  };

  /* =================================================================
   * Syntax highlighting (tokenizer moved here from the workbench —
   * the editor owns how its text is drawn)
   * ================================================================= */
  const KEYWORDS_EPSL = new Set(("def define theorem lemma proposition " +
    "corollary example axiom constant inductive structure where import " +
    "namespace end open by fun forall exists in with notation infixl " +
    "infixr prefix postfix plot calc if then else sorry match").split(" "));
  const TACTICS_EPSL = new Set(("intro intros exact apply assumption rfl " +
    "symm constructor split left right exists cases induction rw rewrite " +
    "simp unfold decide norm_num have show calc trivial contradiction " +
    "exfalso cas numeric ring linarith sorry clear auto").split(" "));
  const words = (s) => new Set(s.split(" "));

  const SYNTAX = {
    epsilon: {
      line: ["--"], block: [["/-", "-/"]], nested: true,
      strings: ['"'], directive: "#",
      keywords: KEYWORDS_EPSL, secondary: TACTICS_EPSL,
      identStart: /[A-Za-z_ℕℤℚℝℂπ]/,
      identBody: /[A-Za-z0-9_'.ℕℤℚℝℂπ]/,
      isType: (w) => /^[A-Zℕℤℚℝℂ]/.test(w) ||
        /^[ℕℤℚℝℂ]/.test(w.split(".").pop()),
      ops: "∀∃λ→↔∧∨¬≤≥≠∈∉⊆×√·∘+-*/^=<>|",
    },
    python: {
      line: ["#"], block: [['"""', '"""'], ["'''", "'''"]],
      strings: ['"', "'"],
      keywords: words("def class return if elif else for while break " +
        "continue import from as pass raise try except finally with lambda " +
        "yield global nonlocal assert del in is not and or None True False " +
        "await async match case"),
      secondary: words("print len range int float str list dict set tuple " +
        "bool sum min max abs round sorted enumerate zip map filter open " +
        "isinstance type super self cls __init__ __name__"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~@",
    },
    cpp: {
      line: ["//"], block: [["/*", "*/"]],
      strings: ['"', "'"], directive: "#",
      keywords: words("auto break case catch class const constexpr " +
        "const_cast continue decltype default delete do double else enum " +
        "explicit export extern false final float for friend goto if inline " +
        "int long mutable namespace new noexcept nullptr operator override " +
        "private protected public register reinterpret_cast return short " +
        "signed sizeof static static_assert static_cast struct switch " +
        "template this throw true try typedef typeid typename union " +
        "unsigned using virtual void volatile while bool char"),
      secondary: words("std cout cin endl vector string map set pair size_t " +
        "unique_ptr shared_ptr printf scanf malloc free"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~?:",
    },
    javascript: {
      line: ["//"], block: [["/*", "*/"]],
      strings: ['"', "'", "`"],
      keywords: words("async await break case catch class const continue " +
        "debugger default delete do else export extends finally for " +
        "function if import in instanceof let new of return static super " +
        "switch this throw try typeof var void while with yield true false " +
        "null undefined"),
      secondary: words("console document window Math JSON Object Array " +
        "Promise Number String Boolean Set Map require module exports"),
      isType: (w) => /^[A-Z]/.test(w),
      ops: "+-*/%^=<>!&|~?:",
    },
    shell: {
      line: ["#"], block: [], strings: ['"', "'"],
      keywords: words("if then else elif fi for while do done case esac " +
        "function return export local source exit set unset"),
      secondary: words("echo cd ls cat grep sed awk cp mv rm mkdir python " +
        "pip git make"),
      ops: "|&<>$=",
    },
    json: { line: [], block: [], strings: ['"'],
            keywords: words("true false null"), ops: ":," },
    yaml: { line: ["#"], block: [], strings: ['"', "'"],
            keywords: words("true false null yes no on off"), ops: ":-|>" },
    toml: { line: ["#"], block: [], strings: ['"', "'"],
            keywords: words("true false"), ops: "=[]" },
    latex: { line: ["%"], block: [], strings: [], command: "\\",
             keywords: new Set(), ops: "^_&$" },
    plain: { line: [], block: [], strings: [], keywords: new Set(), ops: "" },
  };
  SYNTAX.html = SYNTAX.plain;
  SYNTAX.css = SYNTAX.plain;

  const escapeHTML = (s) => String(s).replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  function highlight(src, language) {
    return highlightLines(src, language).join("\n");
  }

  /**
   * The same pass, but kept as one entry per source line.
   *
   * The editor only ever puts the visible lines in the document, so it
   * needs them addressable; joining them back up is what `highlight`
   * does for everyone else. Each entry is self-contained HTML — the
   * tokeniser closes its spans at every line end — so any slice of this
   * array is valid markup on its own.
   */
  function highlightLines(src, language) {
    if (language === "markdown") return highlightMarkdown(src).split("\n");
    const spec = SYNTAX[language || "plain"] || SYNTAX.plain;
    const out = [];
    const st = { depth: 0, closer: null };
    src.split("\n").forEach((line) => out.push(highlightLine(line, spec, st)));
    return out;
  }

  function highlightLine(line, spec, st) {
    let res = "";
    let i = 0;
    const n = line.length;
    const span = (cls, text) => `<span class="${cls}">${escapeHTML(text)}</span>`;
    while (i < n) {
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
        res += cls ? span(cls, word) : escapeHTML(word);
        i = j;
        continue;
      }
      if ((spec.ops || "").includes(ch)) {
        res += span("tok-op", ch);
        i++;
        continue;
      }
      res += escapeHTML(ch);
      i++;
    }
    return res;
  }

  function highlightMarkdown(src) {
    let fenced = false;
    return src.split("\n").map((line) => {
      if (/^\s*```/.test(line)) {
        fenced = !fenced;
        return `<span class="tok-directive">${escapeHTML(line)}</span>`;
      }
      if (fenced) return `<span class="tok-string">${escapeHTML(line)}</span>`;
      if (/^\s{0,3}#{1,6}\s/.test(line))
        return `<span class="tok-keyword">${escapeHTML(line)}</span>`;
      if (/^\s*>/.test(line))
        return `<span class="tok-comment">${escapeHTML(line)}</span>`;
      return escapeHTML(line);
    }).join("\n");
  }

  /* =================================================================
   * Decorations: wrap absolute-offset ranges inside highlighted HTML
   * ================================================================= */
  function decorate(html, ranges, doc) {
    if (!ranges.length) return html;
    const template = doc.createElement("template");
    template.innerHTML = html;
    const walker = doc.createTreeWalker(template.content, 4 /* TEXT */);
    const sorted = ranges.slice().sort((a, b) => a.start - b.start);
    let offset = 0, ri = 0;
    const jobs = [];
    let node;
    while ((node = walker.nextNode()) && ri < sorted.length) {
      const len = node.nodeValue.length;
      while (ri < sorted.length && sorted[ri].start < offset + len) {
        const r = sorted[ri];
        const from = Math.max(0, r.start - offset);
        const to = Math.min(len, r.end - offset);
        if (to > from) jobs.push({ node, from, to, cls: r.cls });
        if (r.end <= offset + len) ri += 1; else break;
      }
      offset += len;
    }
    // apply inside-out so earlier offsets stay valid
    for (let i = jobs.length - 1; i >= 0; i--) {
      const { node: n, from, to, cls } = jobs[i];
      const range = doc.createRange();
      range.setStart(n, from);
      range.setEnd(n, to);
      const mark = doc.createElement("span");
      mark.className = cls;
      try { range.surroundContents(mark); } catch (e) { /* split node: skip */ }
    }
    const div = doc.createElement("div");
    div.appendChild(template.content);
    return div.innerHTML;
  }

  /* =================================================================
   * CodeEditor component
   * ================================================================= */
  /* ---- render passes, requested as a bitmask ---- */
  const TEXT = 1, GUTTER = 2, CURSOR = 4, WINDOW = 8;

  //: lines rendered beyond the viewport, so a small scroll does not
  //: have to touch the document at all
  const OVERSCAN = 24;

  //: past this size a full re-tokenise costs more than highlighting is
  //: worth on every keystroke; the buffer stays editable, plainly drawn
  const HUGE = 260000;
  const MAX_OCCURRENCES = 300;

  //: how long the keyboard must be still before the language service is
  //: asked. In the browser build that call runs Python on the main
  //: thread, so firing it per keystroke freezes the page while typing.
  const SEMANTIC_DELAY = 140;
  const WORD_CHAR = /[A-Za-z0-9_]/;

  function escapeHtml(s) {
    return String(s).replace(/[&<>]/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
  }

  const TEMPLATE = `
    <div class="ed-scroll">
      <div class="ed-gutter" aria-hidden="true"></div>
      <div class="ed-body">
        <div class="ed-decor" aria-hidden="true"></div>
        <pre class="ed-highlight" aria-hidden="true"><code></code></pre>
        <textarea class="ed-input" spellcheck="false" autocomplete="off"
          autocapitalize="off" wrap="off" aria-label="Code editor"></textarea>
      </div>
    </div>
    <div class="ed-find hidden" role="search"></div>
    <div class="ed-complete hidden" role="listbox"></div>`;

  class CodeEditor {
    /**
     * host: element to mount into. opts:
     *   language, value, path, settings (a getter: id -> value),
     *   onChange(), onSave(), onCursor(pos), onGutterClick(line),
     *   completions: async (state) => items, onRequestHover?, doc?
     */
    constructor(host, opts) {
      this.host = host;
      this.opts = opts || {};
      this.doc = this.opts.doc || document;
      this.language = this.opts.language || "plain";
      this.path = this.opts.path || "";
      this.readOnly = !!this.opts.readOnly;
      this.diagnostics = [];
      this.breakpoints = new Set();
      this.currentLine = 0;
      this.overwrite = false;
      this._findState = { open: false, query: "", regex: false, case: false,
                          matches: [], index: -1, replaceVisible: false };
      this._ac = { open: false, items: [], sel: 0, token: 0, from: 0,
                   cache: new Map() };
      // render bookkeeping: what is pending, and what is already painted
      this._need = 0;
      this._frame = 0;
      this._srcCache = null;
      this._wsCache = null;
      this._baseHtml = null;
      this._decKey = null;
      this._occCache = null;
      this._gutterLines = 0;
      this._activeRow = null;
      this._metrics = null;
      this._lines = [""];
      this._lineStarts = [0];
      this._winFrom = 0;
      this._winTo = 0;
      // caret motion: current position, target, and whether to snap
      this._cx = 0; this._cy = 0;
      this._ctx = 0; this._cty = 0;
      this._caretJump = true;
      this._caretRaf = 0;
      this._caretPrev = 0;

      const el = this.doc.createElement("div");
      el.className = "ed-root";
      el.innerHTML = TEMPLATE;
      host.appendChild(el);
      this.el = el;
      this.scroller = el.querySelector(".ed-scroll");
      this.gutter = el.querySelector(".ed-gutter");
      this.body = el.querySelector(".ed-body");
      this.highlightEl = el.querySelector(".ed-highlight code");
      this.pre = el.querySelector(".ed-highlight");
      this.decorEl = el.querySelector(".ed-decor");
      this.input = el.querySelector(".ed-input");
      this.findEl = el.querySelector(".ed-find");
      this.acEl = el.querySelector(".ed-complete");

      // Two elements on purpose. The wrapper carries the position, written
      // every frame by the glide loop; the bar owns the blink. Sharing one
      // element would mean the blink animation and the motion both writing
      // `transform`, and one would simply erase the other.
      this.caretEl = this.doc.createElement("div");
      this.caretEl.className = "ed-caret hidden";
      this.caretEl.setAttribute("aria-hidden", "true");
      this.caretBar = this.doc.createElement("i");
      this.caretBar.className = "ed-caret-bar";
      this.caretEl.appendChild(this.caretBar);
      this.body.appendChild(this.caretEl);

      this.input.value = this.opts.value || "";
      this._wire();
      this.applySettings();
      this.render();
    }

    /* ---------- settings ---------- */
    setting(id) {
      const get = this.opts.settings;
      return get ? get(id) : undefined;
    }

    applySettings() {
      const s = (id, fallback) => {
        const v = this.setting(id);
        return v === undefined ? fallback : v;
      };
      const font = s("editor.fontFamily", "");
      const size = s("editor.fontSize", 13);
      const lineHeight = s("editor.lineHeight", 1.55);
      const tabSize = s("editor.tabSize", 4);
      this.el.style.setProperty("--ed-font-size", size + "px");
      this.el.style.setProperty("--ed-line-height", String(lineHeight));
      if (font) this.el.style.setProperty("--ed-font-family", font);
      this.el.style.setProperty("--ed-tab-size", String(tabSize));
      const wrap = s("editor.wordWrap", false);
      this.input.setAttribute("wrap", wrap ? "soft" : "off");
      this.el.classList.toggle("ed-wrap", !!wrap);
      this.el.dataset.cursorStyle = s("editor.cursorStyle", "line");
      this.el.dataset.cursorBlink = s("editor.cursorBlinking", "smooth");
      this.el.classList.toggle("ed-no-numbers",
        s("editor.lineNumbers", true) === false);
      this._metrics = null;                 // the font may have changed
      this._wsCache = null;                 // and so may whitespace rendering
      this._caretJump = true;
      this.render();
    }

    _opOpts() {
      return {
        language: this.language,
        tabSize: this.setting("editor.tabSize") || 4,
        insertSpaces: this.setting("editor.insertSpaces") !== false,
      };
    }

    /* ---------- value / selection ---------- */
    getValue() { return this.input.value; }
    setValue(v) {
      this._caretJump = true;      // new document: land, do not sail
      this.input.value = v;
      this.render();
    }
    getSelection() {
      return [this.input.selectionStart, this.input.selectionEnd];
    }
    setSelection(start, end) {
      this.input.setSelectionRange(start, end == null ? start : end);
      this.render();
    }
    focus() { this.input.focus(); }

    cursor() {
      const at = this.input.selectionStart;
      const before = this.input.value.slice(0, at);
      const line = (before.match(/\n/g) || []).length + 1;
      const col = at - before.lastIndexOf("\n");
      return { line, col, at };
    }

    /** Cursor for status displays: 1-based line/col + selection size. */
    cursorPosition() {
      const pos = this.cursor();
      const selected = this.input.selectionEnd - this.input.selectionStart;
      return { line: pos.line, col: pos.col, selected };
    }

    revealLine(line, col) {
      const lines = this.input.value.split("\n");
      const target = Math.max(1, Math.min(line, lines.length));
      let at = 0;
      for (let i = 0; i < target - 1; i++) at += lines[i].length + 1;
      at += Math.max(0, Math.min((col || 1) - 1, lines[target - 1].length));
      this.input.focus();
      this.input.setSelectionRange(at, at);
      const lh = this.lineHeightPx();
      this.input.scrollTop = Math.max(0, (target - 4) * lh);
      this._caretJump = true;
      this.render(WINDOW | CURSOR);
    }

    /**
     * Font metrics, measured once and reused. Reading them back from the
     * DOM every frame forces a style recalculation, which is exactly the
     * kind of cost that turns into a stutter while typing. Invalidated
     * whenever the settings that could change them are applied.
     */
    metrics() {
      if (this._metrics) return this._metrics;
      const view = this.doc.defaultView || window;
      const style = view.getComputedStyle(this.input);
      const declared = parseFloat(style.lineHeight);
      const size = parseFloat(style.fontSize) || 13;
      const row = this.gutter && this.gutter.firstElementChild;
      const measured = row ? row.getBoundingClientRect().height : 0;
      this._metrics = {
        // `line-height` reads back as "normal" on some engines, and as the
        // bare ratio when the element is hidden; a rendered row is the truth
        lh: measured > size * 0.6 ? measured
          : (declared > size * 0.6 ? declared : size * 1.6),
        charW: this._measureChar(style),
        padLeft: parseFloat(style.paddingLeft) || 0,
        padTop: parseFloat(style.paddingTop) || 0,
      };
      return this._metrics;
    }

    lineHeightPx() { return this.metrics().lh; }

    /* ---------- edits that keep native undo ---------- */
    insertText(text) {
      this.input.focus();
      if (!this.doc.execCommand || !this.doc.execCommand("insertText", false, text)) {
        const [s, e] = this.getSelection();
        this.input.setRangeText(text, s, e, "end");
        this._afterEdit();
      }
    }

    replaceRange(start, end, text, selStart, selEnd) {
      this.input.focus();
      this.input.setSelectionRange(start, end);
      if (!this.doc.execCommand ||
          !this.doc.execCommand("insertText", false, text)) {
        this.input.setRangeText(text, start, end, "end");
      }
      if (selStart != null) {
        this.input.setSelectionRange(selStart, selEnd == null ? selStart : selEnd);
      }
      this._afterEdit();
    }

    applyOp(result) {
      if (!result) return;
      if (result.range) {
        this.replaceRange(result.range[0], result.range[1],
                          result.replacement, result.selStart, result.selEnd);
      } else if (result.text != null) {
        this.setValue(result.text);
        this.setSelection(result.selStart, result.selEnd);
        this._afterEdit();
      }
    }

    _afterEdit() {
      this._markTyping();
      this.render(TEXT | GUTTER | CURSOR);
      if (this.opts.onChange) this.opts.onChange();
    }

    /* ---------- editor commands (invoked by the command registry) ---------- */
    exec(action) {
      const text = this.input.value;
      const [s, e] = this.getSelection();
      const opts = this._opOpts();
      switch (action) {
        case "indent": return this.applyOp(EditorOps.indentBlock(text, s, e, opts));
        case "dedent": return this.applyOp(EditorOps.dedentBlock(text, s, e, opts));
        case "toggleComment":
          return this.applyOp(EditorOps.toggleComment(text, s, e, opts));
        case "moveLinesUp": return this.applyOp(EditorOps.moveLines(text, s, e, -1));
        case "moveLinesDown": return this.applyOp(EditorOps.moveLines(text, s, e, 1));
        case "duplicateLines":
          return this.applyOp(EditorOps.duplicateLines(text, s, e));
        case "deleteLines": return this.applyOp(EditorOps.deleteLines(text, s, e));
        case "selectLine": {
          const start = text.lastIndexOf("\n", s - 1) + 1;
          const end = text.indexOf("\n", e);
          return this.setSelection(start, end === -1 ? text.length : end + 1);
        }
        case "selectWord": {
          const range = EditorOps.wordAt(text, s);
          if (range) this.setSelection(range[0], range[1]);
          return;
        }
        case "selectNextOccurrence": {
          const range = EditorOps.nextOccurrence(text, s, e);
          if (range) {
            this.setSelection(range[0], range[1]);
            const lh = this.lineHeightPx();
            const line = (text.slice(0, range[0]).match(/\n/g) || []).length;
            const top = line * lh;
            if (top < this.input.scrollTop ||
                top > this.input.scrollTop + this.input.clientHeight - lh) {
              this.input.scrollTop = Math.max(0, top - this.input.clientHeight / 2);
            }
          }
          return;
        }
        case "selectAll": return this.setSelection(0, text.length);
        case "find": return this.openFind(false);
        case "replace": return this.openFind(true);
        case "findNext": return this._findMove(1);
        case "findPrevious": return this._findMove(-1);
        default: return;
      }
    }

    /* ================================================================
     * Rendering
     *
     * Typing must not re-do the whole document. The work splits into
     * three passes that are requested independently and coalesced into
     * one animation frame:
     *
     *   TEXT    the syntax pass — only when the characters changed
     *   GUTTER  line numbers — only when the line count changed
     *   CURSOR  caret, active line, bracket match — every movement
     *
     * Moving the caret used to re-tokenise and re-parse the entire
     * buffer; on a long file that is what the lag was.
     * ============================================================== */
    render(flags) {
      this._need |= flags == null ? (TEXT | GUTTER | CURSOR) : flags;
      if (this._frame) return;
      this._frame = (this.doc.defaultView || window).requestAnimationFrame(
        () => { this._frame = 0; this._paint(); });
    }

    _paint() {
      const need = this._need;
      this._need = 0;
      if (!need) return;
      const src = this.input.value;

      if (need & TEXT) this._reflow(src);
      if (need & (TEXT | GUTTER | WINDOW)) this._paintWindow(need & TEXT);
      if (need & (TEXT | CURSOR)) this._paintDecorLayer(src, !!(need & TEXT));
      if (need & CURSOR) {
        this._paintActiveLine();
        const c = this.cursor();
        this.currentLine = c.line;
        if (this.opts.onCursor) this.opts.onCursor(c);
      }
      this._syncScroll();
    }

    /** Re-tokenise. Cached on the exact source it was built from, so a
        pass that only moved the caret reuses it. */
    _reflow(src) {
      const ws = this.setting("editor.renderWhitespace") || "none";
      if (src === this._srcCache && ws === this._wsCache) return;
      let lines = src.length > HUGE
        ? src.split("\n").map(escapeHtml)
        : highlightLines(src, this.language);
      if (ws === "all" || ws === "boundary") {
        lines = lines.map((l) => this._whitespace(l, ws));
      }
      this._lines = lines;
      // where each line begins, for turning an offset into a position
      const starts = new Array(lines.length);
      let at = 0;
      for (let i = 0; i < lines.length; i++) {
        starts[i] = at;
        at = src.indexOf("\n", at) + 1 || src.length;
      }
      this._lineStarts = starts;
      this._srcCache = src;
      this._wsCache = ws;
      this._winTo = -1;                       // force the window to redraw
    }

    /**
     * Only the visible lines go into the document.
     *
     * A thousand-line file put a thousand highlighted lines and a
     * thousand gutter rows in the tree, and every edit re-parsed all of
     * them; that is where the typing lag came from. The textarea still
     * holds and scrolls the whole text — it is the *painted* layers that
     * are windowed, and they are offset to sit under the real one.
     *
     * Soft wrap breaks the arithmetic (a line is no longer one row
     * high), so that mode renders everything and takes the cost.
     */
    _paintWindow(textChanged) {
      const wrap = this.el.classList.contains("ed-wrap");
      const m = this.metrics();
      let from = 0, to = this._lines.length;
      if (!wrap) {
        const top = this.input.scrollTop;
        const h = this.input.clientHeight || 640;
        from = Math.max(0, Math.floor(top / m.lh) - OVERSCAN);
        to = Math.min(this._lines.length,
                      Math.ceil((top + h) / m.lh) + OVERSCAN);
      }
      if (!textChanged && from === this._winFrom && to === this._winTo) return;
      this._winFrom = from;
      this._winTo = to;
      this.highlightEl.innerHTML = this._lines.slice(from, to).join("\n") + "\n";
      this._paintGutterRows(from, to);
    }

    _paintGutterRows(from, to) {
      const errors = new Set();
      const warnings = new Set();
      this.diagnostics.forEach((d) => {
        const line = d.span && d.span[0];
        if (line) (d.severity === "error" ? errors : warnings).add(line);
      });
      let out = "";
      for (let i = from + 1; i <= to; i++) {
        let cls = "ed-ln";
        if (errors.has(i)) cls += " err";
        else if (warnings.has(i)) cls += " warn";
        if (this.breakpoints.has(i)) cls += " bp";
        out += `<div class="${cls}" data-line="${i}">` +
          `<span class="ed-bp-dot"></span>${i}</div>`;
      }
      this.gutter.innerHTML = out;
      this._activeRow = null;
      this._paintActiveLine();
    }

    _paintActiveLine() {
      const line = this.cursor().line;
      if (this._activeRow && Number(this._activeRow.dataset.line) === line) return;
      if (this._activeRow) this._activeRow.classList.remove("active");
      const row = this.gutter.children[line - 1 - this._winFrom] || null;
      if (row && Number(row.dataset.line) === line) row.classList.add("active");
      this._activeRow = row;
    }

    /**
     * Decorations are drawn, not injected.
     *
     * Wrapping ranges in spans meant re-parsing the whole highlighted
     * document every time the caret moved to a different word. The text
     * is monospaced and unwrapped, so each range's position is simple
     * arithmetic: one absolutely-positioned box per range, costing the
     * number of decorations rather than the size of the file.
     */
    _paintDecorLayer(src, forced) {
      const decs = this._decorations(src);
      const key = decs.length
        ? decs.map((d) => d.start + ":" + d.end + ":" + d.cls).join("|") : "";
      if (!forced && key === this._decKey) return;
      this._decKey = key;
      if (this.el.classList.contains("ed-wrap")) {
        this.decorEl.innerHTML = "";        // geometry does not hold when wrapped
        return;
      }
      const m = this.metrics();
      const out = [];
      for (const d of decs) {
        const a = this.positionOf(d.start);
        const b = this.positionOf(d.end);
        for (let ln = a.line; ln <= b.line && ln <= this._lines.length; ln++) {
          const text = this.lineText(ln);
          const from = ln === a.line ? a.col : 0;
          const to = ln === b.line ? b.col : text.length;
          const x0 = this.visualCol(text, from);
          const x1 = this.visualCol(text, to);
          if (x1 <= x0) continue;
          out.push('<i class="' + d.cls + '" style="transform:translate(' +
            (x0 * m.charW).toFixed(2) + 'px,' +
            ((ln - 1 - this._winFrom) * m.lh).toFixed(2) +
            'px);width:' + ((x1 - x0) * m.charW).toFixed(2) + 'px"></i>');
        }
      }
      this.decorEl.innerHTML = out.join("");
    }

    _decorations(src) {
      const out = [];
      const [s, e] = this.getSelection();
      if (s === e) {
        const match = EditorOps.matchBracket(src, s);
        if (match) {
          out.push({ start: match[0], end: match[0] + 1, cls: "ed-bracket" });
          out.push({ start: match[1], end: match[1] + 1, cls: "ed-bracket" });
        }
        out.push(...this._occurrences(src, s));
      }
      if (this._findState.open) {
        this._findState.matches.forEach((mm, i) => {
          out.push({ start: mm[0], end: mm[1],
                     cls: i === this._findState.index
                       ? "ed-find-current" : "ed-find-match" });
        });
      }
      return out;
    }

    /**
     * Other occurrences of the word under the caret.
     *
     * A whole-document scan, so it is cached against the word itself:
     * walking along a line with the arrow keys re-uses the answer until
     * the caret lands on a different identifier. `indexOf` beats a global
     * regex here — no per-call compile, no match objects.
     */
    _occurrences(src, at) {
      const word = EditorOps.wordAt(src, at);
      if (!word || word[1] - word[0] < 3 || src.length > HUGE) return [];
      const needle = src.slice(word[0], word[1]);
      const cache = this._occCache;
      if (cache && cache.needle === needle && cache.src === src) {
        return cache.hits.filter((h) => h.start !== word[0]);
      }
      const hits = [];
      const n = needle.length;
      for (let i = src.indexOf(needle); i >= 0 && hits.length < MAX_OCCURRENCES;
           i = src.indexOf(needle, i + n)) {
        const before = i === 0 ? "" : src[i - 1];
        const after = i + n >= src.length ? "" : src[i + n];
        if (!WORD_CHAR.test(before) && !WORD_CHAR.test(after)) {
          hits.push({ start: i, end: i + n, cls: "ed-occurrence" });
        }
      }
      this._occCache = { needle, src, hits };
      return hits.filter((h) => h.start !== word[0]);
    }

    /** 1-based line and 0-based column for an absolute offset. */
    positionOf(off) {
      const starts = this._lineStarts;
      let lo = 0, hi = starts.length - 1;
      while (lo < hi) {
        const mid = (lo + hi + 1) >> 1;
        if (starts[mid] <= off) lo = mid; else hi = mid - 1;
      }
      return { line: lo + 1, col: off - starts[lo] };
    }

    lineText(line) {
      const src = this.input.value;
      const start = this._lineStarts[line - 1];
      if (start == null) return "";
      const end = this._lineStarts[line] != null
        ? this._lineStarts[line] - 1 : src.length;
      return src.slice(start, end);
    }

    /** Column in character cells, counting a tab to the next tab stop. */
    visualCol(text, index) {
      const tab = Number(this.setting("editor.tabSize")) || 4;
      let cols = 0;
      for (let i = 0; i < index && i < text.length; i++) {
        cols += text[i] === "\t" ? tab - (cols % tab) : 1;
      }
      return cols;
    }

    _whitespace(html, mode) {
      // substitute in the *overlay* only; the real text is untouched
      const dot = '<span class="ed-ws">·</span>';
      const arrow = '<span class="ed-ws">→</span>';
      if (mode === "all") {
        return html.replace(/ /g, dot).replace(/\t/g, arrow);
      }
      return html.split("\n").map((line) => {
        const stripped = line.replace(/<[^>]*>/g, "");
        const lead = (stripped.match(/^[ \t]*/) || [""])[0];
        let i = 0;
        return line.replace(/^([ \t]*)/, (m) =>
          m.replace(/ /g, dot).replace(/\t/g, arrow));
      }).join("\n");
    }

    /**
     * The gutter is rebuilt only when its shape changes — the line count,
     * a breakpoint, a diagnostic. The active-line highlight moves far more
     * often than any of those, so it is a class swap on two rows rather
     * than a reason to re-parse a thousand of them.
     */

    /** The textarea is the one real scroller; the highlight layer and the
        gutter follow it by transform, so all three can never disagree. */
    _syncScroll() {
      const x = -this.input.scrollLeft;
      const wrap = this.el.classList.contains("ed-wrap");
      // the window starts at line `_winFrom`, so shift it down by that
      // many lines before taking the scroll offset back off again
      const y = wrap ? -this.input.scrollTop
        : this._winFrom * this.metrics().lh - this.input.scrollTop;
      this.pre.style.transform = `translate(${x}px, ${y}px)`;
      this.decorEl.style.transform = `translate(${x}px, ${y}px)`;
      this.gutter.style.transform = `translate(0, ${y}px)`;
      this._positionCaret();
    }

    /**
     * The drawn caret.
     *
     * A textarea's own caret has exactly one look, so the cursor style and
     * blink settings are honoured by hiding it (`caret-color: transparent`)
     * and drawing this one at the measured spot. Soft wrap falls back to the
     * native caret, where logical line arithmetic no longer matches the
     * screen.
     *
     * This only sets the *target*. A CSS transition would be the obvious
     * way to smooth the movement and the wrong one: a transition restarts
     * from zero velocity on every keystroke, so fast typing reads as a
     * series of little jerks. The glide loop below keeps its velocity
     * across retargets, which is what makes it feel continuous.
     */
    _positionCaret() {
      const caret = this.caretEl;
      if (!caret) return;
      if (this.el.classList.contains("ed-wrap")) {
        caret.classList.add("hidden");
        return;
      }
      const [s, e] = this.getSelection();
      if (this.doc.activeElement !== this.input || s !== e) {
        caret.classList.add("hidden");
        return;
      }
      const m = this.metrics();
      const lh = m.lh;
      const c = this.cursor();
      const cols = this.visualCol(this.lineText(c.line), c.col - 1);
      const shape = this.el.dataset.cursorStyle || "line";

      const x = cols * m.charW - this.input.scrollLeft + m.padLeft;
      let y = (c.line - 1) * lh - this.input.scrollTop + m.padTop;
      let h = lh;
      const w = shape === "line" ? 2 : Math.ceil(m.charW);
      if (shape === "underline") { y += lh - 2; h = 2; }
      if (y < -lh || y > (this.input.clientHeight || 0) + lh) {
        caret.classList.add("hidden");   // scrolled out of sight
        return;
      }
      caret.classList.remove("hidden");
      caret.style.width = w + "px";
      caret.style.height = h + "px";

      // a long jump — a click across the file, a reveal, a page scroll —
      // should land, not sail across the viewport
      if (Math.abs(x - this._ctx) + Math.abs(y - this._cty) > lh * 3.5) {
        this._caretJump = true;
      }
      this._ctx = x;
      this._cty = y;
      this._glide();
    }

    /**
     * Interpolate towards the caret target, then stop.
     *
     * The easing constant is raised to (dt / 16.667) so the motion feels
     * identical at 60, 120 or 144 Hz instead of being tuned for one of
     * them. The loop cancels itself once it has arrived — a caret that
     * keeps a frame callback alive while nothing moves is a battery bug.
     */
    _glide() {
      if (this._caretRaf) return;
      const view = this.doc.defaultView || window;
      const EASE_X = this._reduceMotion() ? 1 : 0.28;
      const EASE_Y = this._reduceMotion() ? 1 : 0.34;
      const step = (now) => {
        const dt = this._caretPrev ? Math.min(64, now - this._caretPrev) : 16.667;
        this._caretPrev = now;
        if (this._caretJump) {
          this._cx = this._ctx; this._cy = this._cty;
          this._caretJump = false;
        } else {
          const kx = 1 - Math.pow(1 - EASE_X, dt / 16.667);
          const ky = 1 - Math.pow(1 - EASE_Y, dt / 16.667);
          this._cx += (this._ctx - this._cx) * kx;
          this._cy += (this._cty - this._cy) * ky;
        }
        this.caretEl.style.transform =
          `translate3d(${this._cx.toFixed(2)}px,${this._cy.toFixed(2)}px,0)`;
        if (Math.abs(this._ctx - this._cx) < 0.05 &&
            Math.abs(this._cty - this._cy) < 0.05) {
          this._cx = this._ctx; this._cy = this._cty;
          this.caretEl.style.transform =
            `translate3d(${this._cx.toFixed(2)}px,${this._cy.toFixed(2)}px,0)`;
          this._caretRaf = 0;
          this._caretPrev = 0;
          return;
        }
        this._caretRaf = view.requestAnimationFrame(step);
      };
      this._caretPrev = 0;
      this._caretRaf = view.requestAnimationFrame(step);
    }

    _reduceMotion() {
      const view = this.doc.defaultView || window;
      return (this.doc.body && this.doc.body.classList.contains("wb-reduced-motion"))
        || !!(view.matchMedia
              && view.matchMedia("(prefers-reduced-motion: reduce)").matches);
    }

    /** Solid while typing, blinking once the hands stop — a caret that
        blinks under the fingers is just noise. */
    _markTyping() {
      this.el.classList.add("typing");
      clearTimeout(this._typingTimer);
      this._typingTimer = setTimeout(
        () => this.el.classList.remove("typing"), 620);
    }

    setDiagnostics(diags) {
      this.diagnostics = diags || [];
      this._winTo = -1;                 // gutter marks changed; redraw them
      this.render(GUTTER | CURSOR);
    }

    toggleBreakpoint(line) {
      if (this.breakpoints.has(line)) this.breakpoints.delete(line);
      else this.breakpoints.add(line);
      this._winTo = -1;                 // the gutter dot changed
      this.render(GUTTER | CURSOR);
      if (this.opts.onBreakpoints) {
        this.opts.onBreakpoints(Array.from(this.breakpoints).sort((a, b) => a - b));
      }
    }

    /* ---------- find widget ---------- */
    openFind(withReplace) {
      const st = this._findState;
      st.open = true;
      st.replaceVisible = !!withReplace;
      const [s, e] = this.getSelection();
      if (e > s && e - s < 200 && !this.input.value.slice(s, e).includes("\n")) {
        st.query = this.input.value.slice(s, e);
      }
      this._renderFind();
      this._recompute();
      const box = this.findEl.querySelector(".ed-find-input");
      if (box) { box.focus(); box.select(); }
    }

    closeFind() {
      this._findState.open = false;
      this.findEl.classList.add("hidden");
      this.render();
      this.focus();
    }

    _renderFind() {
      const st = this._findState;
      this.findEl.classList.remove("hidden");
      this.findEl.innerHTML = `
        <div class="ed-find-row">
          <input class="ed-find-input" value="${escapeHTML(st.query)}"
            placeholder="Find" aria-label="Find" />
          <button class="ed-find-opt${st.case ? " on" : ""}" data-opt="case"
            title="Match case">Aa</button>
          <button class="ed-find-opt${st.word ? " on" : ""}" data-opt="word"
            title="Whole word">ab</button>
          <button class="ed-find-opt${st.regex ? " on" : ""}" data-opt="regex"
            title="Regular expression">.*</button>
          <span class="ed-find-count"></span>
          <button class="ed-find-nav" data-nav="-1" title="Previous (Shift+F3)">↑</button>
          <button class="ed-find-nav" data-nav="1" title="Next (F3)">↓</button>
          <button class="ed-find-close" title="Close (Escape)">×</button>
        </div>
        <div class="ed-find-row${st.replaceVisible ? "" : " hidden"}">
          <input class="ed-find-replace" value="${escapeHTML(st.replaceText || "")}"
            placeholder="Replace" aria-label="Replace" />
          <button class="ed-find-do" data-do="one">Replace</button>
          <button class="ed-find-do" data-do="all">All</button>
        </div>`;
      const input = this.findEl.querySelector(".ed-find-input");
      input.addEventListener("input", () => {
        st.query = input.value;
        this._recompute();
      });
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") { ev.preventDefault(); this._findMove(ev.shiftKey ? -1 : 1); }
        if (ev.key === "Escape") { ev.preventDefault(); this.closeFind(); }
      });
      const rep = this.findEl.querySelector(".ed-find-replace");
      if (rep) {
        rep.addEventListener("input", () => { st.replaceText = rep.value; });
        rep.addEventListener("keydown", (ev) => {
          if (ev.key === "Enter") { ev.preventDefault(); this._replaceOne(); }
          if (ev.key === "Escape") { ev.preventDefault(); this.closeFind(); }
        });
      }
      this.findEl.querySelectorAll(".ed-find-opt").forEach((b) => {
        b.addEventListener("click", () => {
          st[b.dataset.opt] = !st[b.dataset.opt];
          this._renderFind();
          this._recompute();
        });
      });
      this.findEl.querySelectorAll(".ed-find-nav").forEach((b) =>
        b.addEventListener("click", () => this._findMove(Number(b.dataset.nav))));
      this.findEl.querySelector(".ed-find-close")
        .addEventListener("click", () => this.closeFind());
      this.findEl.querySelectorAll(".ed-find-do").forEach((b) =>
        b.addEventListener("click", () =>
          b.dataset.do === "one" ? this._replaceOne() : this._replaceAll()));
    }

    _pattern() {
      const st = this._findState;
      if (!st.query) return null;
      let source = st.regex ? st.query
        : st.query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      if (st.word) source = "\\b(?:" + source + ")\\b";
      try {
        return new RegExp(source, st.case ? "g" : "gi");
      } catch (e) { return null; }
    }

    _recompute() {
      const st = this._findState;
      st.matches = [];
      st.index = -1;
      const pattern = this._pattern();
      if (pattern) {
        const text = this.input.value;
        let m;
        while ((m = pattern.exec(text)) && st.matches.length < 5000) {
          st.matches.push([m.index, m.index + Math.max(1, m[0].length)]);
          if (m[0].length === 0) pattern.lastIndex += 1;
        }
        const caret = this.input.selectionStart;
        st.index = st.matches.findIndex(([a]) => a >= caret);
        if (st.index === -1 && st.matches.length) st.index = 0;
      }
      const count = this.findEl.querySelector(".ed-find-count");
      if (count) {
        count.textContent = st.matches.length
          ? `${st.index + 1} of ${st.matches.length}` : "No results";
      }
      this.render();
    }

    _findMove(dir) {
      const st = this._findState;
      if (!st.open) { this.openFind(false); return; }
      if (!st.matches.length) return;
      st.index = (st.index + dir + st.matches.length) % st.matches.length;
      const [a, b] = st.matches[st.index];
      this.input.setSelectionRange(a, b);
      const line = (this.input.value.slice(0, a).match(/\n/g) || []).length;
      this.input.scrollTop = Math.max(0, (line - 4) * this.lineHeightPx());
      this._recompute();
    }

    _replaceOne() {
      const st = this._findState;
      if (st.index < 0 || !st.matches.length) return;
      const [a, b] = st.matches[st.index];
      this.replaceRange(a, b, st.replaceText || "");
      this._recompute();
    }

    _replaceAll() {
      const st = this._findState;
      const pattern = this._pattern();
      if (!pattern) return;
      const text = this.input.value;
      const replaced = text.replace(pattern, st.replaceText || "");
      if (replaced !== text) {
        this.replaceRange(0, text.length, replaced);
        this._recompute();
      }
    }


    /* ================================================================
     * Completion
     *
     * The list appears on the first keystroke, not when the network
     * answers. Two sources feed it:
     *
     *   local     identifiers already in the buffer plus the language's
     *             keywords — computed here, synchronously, so there is
     *             something accurate to look at immediately;
     *   semantic  the language service (jedi), which knows real module
     *             members and signatures but costs a round trip. It
     *             replaces the local list in place when it lands.
     *
     * Waiting for that round trip before drawing anything is what made
     * completion feel slow; the answer was rarely slow, the wait was.
     * ============================================================== */
    openCompletion(explicit) {
      if (!this.opts.completions) return;
      const c = this.cursor();
      const text = this.input.value;
      const word = EditorOps.wordAt(text, c.at);
      const prefixStart = word && word[0] < c.at ? word[0] : c.at;
      const prefix = text.slice(prefixStart, c.at);
      const dotted = text[c.at - 1] === "." ||
        (this.language === "cpp" && text.slice(c.at - 2, c.at) === "::");
      clearTimeout(this._acTimer);
      if (!explicit && prefix.length < 1 && !dotted) {
        return this.closeCompletion();
      }
      const token = ++this._ac.token;
      this._ac.from = prefixStart;

      // 1. what can be answered without leaving the page — immediately
      const from = lineStart(text, c.at);
      const key = this.language + "\u0000" + text.slice(from, c.at);
      const cached = this._ac.cache.get(key);
      const local = cached || (dotted ? [] : this._localCompletions(text, prefix));
      if (local.length) this._showCompletion(local);
      else if (!dotted && !explicit) this.closeCompletion();
      if (cached) return;                     // already the semantic answer

      // 2. the language service, once the typing pauses
      const ask = () => this._semanticCompletion(
        { text, line: c.line, col: c.col - 1, prefix, key }, token, !local.length);
      if (explicit) ask();
      else this._acTimer = setTimeout(ask, SEMANTIC_DELAY);
    }

    async _semanticCompletion(ctx, token, wasEmpty) {
      if (token !== this._ac.token) return;
      let items;
      try {
        items = await this.opts.completions({
          language: this.language, code: ctx.text,
          line: ctx.line, col: ctx.col, path: this.path, prefix: ctx.prefix,
        });
      } catch (e) { return; }
      if (token !== this._ac.token) return;   // the caret moved on
      const prefix = ctx.prefix.toLowerCase();
      items = (items || []).filter((i) =>
        !prefix || i.name.toLowerCase().startsWith(prefix));
      if (items.length) {
        if (this._ac.cache.size > 60) this._ac.cache.clear();
        this._ac.cache.set(ctx.key, items);
        this._showCompletion(items);
      } else if (wasEmpty) {
        this.closeCompletion();
      }
    }

    /** Swap the list without losing the reader's place in it. */
    _showCompletion(items) {
      const keep = this._ac.open && this._ac.items[this._ac.sel];
      this._ac.items = items.slice(0, 60);
      const again = keep
        ? this._ac.items.findIndex((i) => i.name === keep.name) : -1;
      this._ac.sel = again > 0 ? again : 0;
      this._ac.open = true;
      this._renderCompletion();
    }

    /**
     * Identifiers already written in this buffer, plus the language's own
     * words. Indexed lazily and reused until the text actually changes —
     * a full scan per keystroke would cost more than it returns.
     */
    _localCompletions(text, prefix) {
      if (!prefix) return [];
      // Scanning the buffer on every keystroke costs more than it returns:
      // the words in a file barely change between two characters. Rebuild
      // when the text has moved on meaningfully, not on every edit.
      const now = performance.now();
      const stale = !this._identIndex
        || now - this._identIndex.at > 900
        || Math.abs(text.length - this._identIndex.len) > 240;
      if (stale) {
        const seen = new Map();
        const re = /[A-Za-z_][A-Za-z0-9_]{1,}/g;
        const scan = text.length > HUGE ? text.slice(0, HUGE) : text;
        let m;
        while ((m = re.exec(scan))) seen.set(m[0], (seen.get(m[0]) || 0) + 1);
        const syn = SYNTAX[this.language] || {};
        const words = new Set([...(syn.keywords || []),
                               ...(syn.secondary || [])]);
        this._identIndex = { at: now, len: text.length, seen, words };
      }
      const { seen, words } = this._identIndex;
      const lower = prefix.toLowerCase();
      const out = [];
      words.forEach((w) => {
        if (w.length > prefix.length && w.toLowerCase().startsWith(lower)) {
          out.push({ name: w, kind: "keyword", detail: "keyword", insert: w });
        }
      });
      seen.forEach((count, w) => {
        if (w !== prefix && w.toLowerCase().startsWith(lower) && !words.has(w)) {
          out.push({ name: w, kind: "text", detail: "in this file",
                     insert: w, _n: count });
        }
      });
      out.sort((a, b) => (b._n || 0) - (a._n || 0) ||
                         a.name.length - b.name.length);
      return out.slice(0, 40);
    }

    closeCompletion() {
      clearTimeout(this._acTimer);
      this._ac.token++;             // strand any request already in flight
      this._ac.open = false;
      this.acEl.classList.add("hidden");
    }

    _renderCompletion() {
      const ac = this._ac;
      this.acEl.innerHTML = "";
      ac.items.forEach((item, i) => {
        const row = this.doc.createElement("div");
        row.className = "ed-ac-item" + (i === ac.sel ? " sel" : "");
        row.setAttribute("role", "option");
        row.innerHTML =
          `<span class="ed-ac-kind k-${escapeHTML(item.kind || "text")}">` +
          `${escapeHTML((item.kind || "t")[0])}</span>` +
          `<span class="ed-ac-name">${escapeHTML(item.name)}</span>` +
          `<span class="ed-ac-detail">${escapeHTML(item.detail || "")}</span>`;
        row.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          ac.sel = i;
          this.acceptCompletion();
        });
        this.acEl.appendChild(row);
      });
      this.acEl.classList.remove("hidden");
      this._positionCompletion();
    }

    _positionCompletion() {
      // mirror measurement: caret x/y inside the scroller
      const c = this.cursor();
      const m = this.metrics();
      const lh = m.lh;
      const charW = m.charW;
      const x = (c.col - 1) * charW - this.input.scrollLeft +
        this.gutter.offsetWidth;
      const y = c.line * lh - this.input.scrollTop;
      const maxX = this.el.clientWidth - this.acEl.offsetWidth - 8;
      this.acEl.style.left = Math.max(0, Math.min(x, maxX)) + "px";
      const below = y + 4;
      if (below + this.acEl.offsetHeight > this.el.clientHeight) {
        this.acEl.style.top = Math.max(0, y - lh - this.acEl.offsetHeight - 2) + "px";
      } else {
        this.acEl.style.top = below + "px";
      }
    }

    _measureChar(style) {
      const probe = this.doc.createElement("span");
      probe.style.font = style.font;
      probe.style.position = "absolute";
      probe.style.visibility = "hidden";
      probe.textContent = "0000000000";
      this.doc.body.appendChild(probe);
      const width = probe.getBoundingClientRect().width / 10;
      probe.remove();
      return width || 8;
    }

    moveCompletion(delta) {
      const ac = this._ac;
      ac.sel = (ac.sel + delta + ac.items.length) % ac.items.length;
      this._renderCompletion();
      const row = this.acEl.children[ac.sel];
      if (row && row.scrollIntoView) row.scrollIntoView({ block: "nearest" });
    }

    acceptCompletion() {
      const ac = this._ac;
      const item = ac.items[ac.sel];
      if (!item) return;
      this.replaceRange(ac.from, this.input.selectionStart,
                        item.insert || item.name);
      this.closeCompletion();
    }

    /* ---------- key handling ---------- */
    _wire() {
      const input = this.input;

      input.addEventListener("input", () => {
        this._afterEdit();
        this.openCompletion(false);
      });
      input.addEventListener("scroll", () => {
        this._caretJump = true;    // the caret rides the viewport, not the text
        this.render(WINDOW | CURSOR);
        if (this._ac.open) this._positionCompletion();
      });
      //: moving the caret is not a text change — repaint the cheap passes
      ["click", "keyup", "select"].forEach((ev) =>
        input.addEventListener(ev, () => this.render(CURSOR)));
      input.addEventListener("blur", () => {
        this.closeCompletion();
        this._positionCaret();
      });
      input.addEventListener("focus", () => this._positionCaret());

      this.gutter.addEventListener("mousedown", (ev) => {
        const row = ev.target.closest(".ed-ln");
        if (!row) return;
        const line = Number(row.dataset.line);
        if (ev.target.classList.contains("ed-bp-dot") || ev.offsetX < 18) {
          this.toggleBreakpoint(line);
        } else {
          this.revealLine(line, 1);
        }
        if (this.opts.onGutterClick) this.opts.onGutterClick(line, ev);
      });

      input.addEventListener("keydown", (ev) => this._keydown(ev));
    }

    _keydown(ev) {
      const input = this.input;
      const text = input.value;
      const [s, e] = this.getSelection();
      const opts = this._opOpts();
      const lang = langOf(this.language);

      // completion list owns its keys while open
      if (this._ac.open) {
        if (ev.key === "ArrowDown") { ev.preventDefault(); return this.moveCompletion(1); }
        if (ev.key === "ArrowUp") { ev.preventDefault(); return this.moveCompletion(-1); }
        if (ev.key === "Enter" || ev.key === "Tab") {
          ev.preventDefault();
          ev.stopPropagation();
          return this.acceptCompletion();
        }
        if (ev.key === "Escape") { ev.preventDefault(); return this.closeCompletion(); }
      }
      if (ev.key === "Escape" && this._findState.open) {
        ev.preventDefault();
        return this.closeFind();
      }

      if (this.readOnly) return;

      // ---- Enter: automatic indentation ----
      if (ev.key === "Enter" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        ev.preventDefault();
        const nl = EditorOps.newlineIndent(text, s, opts);
        this.insertText(nl.insert + nl.after);
        if (nl.after) {
          const at = input.selectionStart - nl.after.length;
          input.setSelectionRange(at, at);
        }
        this.render();
        return;
      }

      // ---- Tab / Shift+Tab ----
      if (ev.key === "Tab" && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        ev.preventDefault();
        const multiline = text.slice(s, e).includes("\n");
        if (ev.shiftKey) return this.exec("dedent");
        if (multiline) return this.exec("indent");
        return this.insertText(opts.insertSpaces === false
          ? "\t" : " ".repeat(opts.tabSize - ((this.cursor().col - 1) % opts.tabSize)));
      }

      // ---- bracket & quote pairs ----
      const pairs = lang.pairs || {};
      if (!ev.ctrlKey && !ev.metaKey && !ev.altKey &&
          this.setting("editor.autoClosingBrackets") !== false) {
        const closerOf = pairs[ev.key];
        if (closerOf) {
          const isQuote = ev.key === closerOf;
          if (s !== e) {                       // wrap the selection
            ev.preventDefault();
            const inner = text.slice(s, e);
            this.insertText(ev.key + inner + closerOf);
            input.setSelectionRange(s + 1, s + 1 + inner.length);
            this.render();
            return;
          }
          const next = text[s] || "";
          if (isQuote && (next === ev.key ||
              /[A-Za-z0-9_]/.test(text[s - 1] || ""))) {
            if (next === ev.key) {             // type through the closer
              ev.preventDefault();
              input.setSelectionRange(s + 1, s + 1);
              this.render();
            }
            return;                            // inside a word: just type
          }
          if (!isQuote || next === "" || /[\s)\]},;:]/.test(next)) {
            ev.preventDefault();
            this.insertText(ev.key + closerOf);
            input.setSelectionRange(s + 1, s + 1);
            this.render();
            return;
          }
          return;
        }
        if (Object.values(pairs).includes(ev.key) && text[s] === ev.key &&
            s === e) {                          // type through )] }
          ev.preventDefault();
          input.setSelectionRange(s + 1, s + 1);
          this.render();
          return;
        }
        if (ev.key === "Backspace" && s === e && s > 0 &&
            pairs[text[s - 1]] === text[s]) {   // delete the empty pair
          ev.preventDefault();
          this.replaceRange(s - 1, s + 1, "");
          return;
        }
      }

      // ---- electric } dedent (cpp/js/json) ----
      if (ev.key === lang.electricDedent && s === e) {
        const start = text.lastIndexOf("\n", s - 1) + 1;
        const before = text.slice(start, s);
        if (/^[ \t]+$/.test(before) && before.length >= (opts.tabSize || 4)) {
          ev.preventDefault();
          const u = opts.insertSpaces === false ? 1 : opts.tabSize;
          this.replaceRange(s - u, s, ev.key);
          return;
        }
      }

      // ---- Home: smart home ----
      if (ev.key === "Home" && !ev.ctrlKey && !ev.metaKey) {
        ev.preventDefault();
        const target = EditorOps.smartHome(text, s);
        if (ev.shiftKey) input.setSelectionRange(Math.min(target, e), Math.max(target, e),
          target < e ? "backward" : "forward");
        else input.setSelectionRange(target, target);
        this.render();
        return;
      }

      // ---- Insert: overwrite mode ----
      if (ev.key === "Insert") {
        this.overwrite = !this.overwrite;
        this.el.classList.toggle("ed-overwrite", this.overwrite);
        if (this.opts.onCursor) this.opts.onCursor(this.cursor());
        return;
      }
      if (this.overwrite && ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey &&
          s === e && text[s] && text[s] !== "\n") {
        ev.preventDefault();
        this.replaceRange(s, s + 1, ev.key);
        return;
      }
    }

    destroy() {
      // a frame still queued would paint into a detached tree
      if (this._frame) {
        (this.doc.defaultView || window).cancelAnimationFrame(this._frame);
        this._frame = 0;
      }
      if (this._caretRaf) {
        (this.doc.defaultView || window).cancelAnimationFrame(this._caretRaf);
        this._caretRaf = 0;
      }
      clearTimeout(this._acTimer);
      clearTimeout(this._typingTimer);
      this._ac.token++;                  // orphan any in-flight completion
      this.el.remove();
    }
  }

  const api = { CodeEditor, EditorOps, highlight, highlightLines,
                decorate, langOf, LANGS };
  root.EpsilonEditor = api;
  if (typeof module === "object" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
