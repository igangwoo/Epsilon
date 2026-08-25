/* ===================================================================
 * Epsilon — the editor.
 *
 * A textarea with a painted layer behind it. The textarea is kept
 * because it brings the platform's text input for free — IME, native
 * selection, native undo, accessibility — and everything a code editor
 * adds is layered on top rather than replacing it.
 *
 * Three rules keep it quick, and each is load-bearing:
 *
 *   1. A keystroke repaints; a caret move does not. Highlighting is
 *      cached against the exact source it was built from, and only the
 *      lines on screen are ever in the document.
 *   2. Nothing on the typing path leaves the page. Completion comes
 *      from the buffer's own words and a fixed word list — Python runs
 *      on this thread, so asking it per keystroke would freeze the tab.
 *   3. The caret is interpolated in a frame loop, not by a CSS
 *      transition. A transition restarts from zero velocity on every
 *      keystroke, which is exactly what makes a caret feel steppy.
 * =================================================================== */
(function (root) {
  "use strict";

  const set = (s) => new Set(s.split(/\s+/).filter(Boolean));

  /* =================================================================
   * Languages
   *
   * Each entry is everything the editor needs to know about a language
   * and nothing more: how a comment starts, what opens a block, which
   * words are reserved. Three small tables beat three code paths.
   * ================================================================= */

  const LANGS = {
    python: {
      id: "python", label: "python", file: "main.py",
      line: "#", comment: "# ", block: null, triple: true, preproc: false,
      unit: "    ", colon: true, braces: false,
      dedentAfter: /^\s*(return|pass|break|continue|raise)\b/,
      keywords: set(`False None True and as assert async await break class
        continue def del elif else except finally for from global if import
        in is lambda nonlocal not or pass raise return try while with yield
        match case`),
      known: set(`abs all any bool bytes callable chr dict dir divmod
        enumerate filter float format frozenset getattr hasattr hash hex id
        input int isinstance issubclass iter len list map max min next object
        oct open ord pow print range repr reversed round set setattr sorted
        str sum tuple type vars zip self cls super __init__ __name__ math
        Exception ValueError TypeError KeyError IndexError`),
    },

    cpp: {
      id: "cpp", label: "c++", file: "main.cpp",
      line: "//", comment: "// ", block: true, triple: false, preproc: true,
      unit: "    ", colon: false, braces: true, dedentAfter: null,
      keywords: set(`alignas alignof and asm auto bool break case catch char
        class const constexpr const_cast continue decltype default delete do
        double dynamic_cast else enum explicit export extern false float for
        friend goto if inline int long mutable namespace new noexcept nullptr
        operator or private protected public register reinterpret_cast return
        short signed sizeof static static_assert static_cast struct switch
        template this throw true try typedef typeid typename union unsigned
        using virtual void volatile wchar_t while`),
      known: set(`std string vector map set unordered_map unordered_set pair
        tuple array deque queue stack priority_queue cout cin cerr endl getline
        printf scanf size_t int64_t uint64_t shared_ptr unique_ptr make_shared
        make_unique sort reverse accumulate find begin end push_back
        emplace_back size empty length substr to_string stoi stod ostream
        istream iostream vector iterator const_iterator`),
    },

    java: {
      id: "java", label: "java", file: "Main.java",
      line: "//", comment: "// ", block: true, triple: false, preproc: false,
      unit: "    ", colon: false, braces: true, dedentAfter: null,
      keywords: set(`abstract assert boolean break byte case catch char class
        const continue default do double else enum extends final finally float
        for goto if implements import instanceof int interface long native new
        package private protected public return short static strictfp super
        switch synchronized this throw throws transient try void volatile
        while var record sealed permits yield true false null`),
      known: set(`String System out err println print printf Integer Double
        Boolean Long Character Math List ArrayList Map HashMap Set HashSet
        Arrays Collections Scanner StringBuilder Object Exception
        RuntimeException Override length size add get put contains toString
        valueOf parseInt parseDouble equals nextInt nextLine hasNext main
        args`),
    },
  };

  /* =================================================================
   * Ligatures
   *
   * A rendering layer, never an edit: the file still says `>=`, and
   * every keystroke, selection and column number is computed from that
   * text. What changes is only what the eye is shown.
   *
   * The hard rule is width. The textarea underneath owns hit testing
   * and selection and lays every character out on a uniform monospace
   * grid — so a ligature occupies exactly as many cells as the source
   * it stands for. Each is drawn in a fixed `Nch` box.
   *
   * The set is deliberately five. Every one of them means the same
   * thing in all three languages, and none of them is ambiguous: `<-`
   * would be a comparison against a negative number, `//` is a comment
   * in two of the three, and `<<` is how C++ prints. Those stay text.
   * ================================================================= */

  const LIG_OPS = [
    ["->", "→"], [">=", "≥"], ["<=", "≤"],
    ["!=", "≠"], ["==", "≡"],
  ];

  //: an operator character on either side means this is part of a
  //: longer operator — `>>=`, `<=>`, `!==` — and not what it looks like
  const GLUED = /[=<>!+\-*/%&|^~]/;

  /** One ligature, in a box exactly as wide as the text it replaces. */
  const cell = (width, glyph) =>
    '<span class="lg" style="width:' + width + 'ch">' + glyph + "</span>";

  function ligAt(src, i) {
    for (const [text, glyph] of LIG_OPS) {
      if (!src.startsWith(text, i)) continue;
      if (GLUED.test(src[i - 1] || "") ||
          GLUED.test(src[i + text.length] || "")) return null;
      return { len: text.length, html: cell(text.length, glyph) };
    }
    return null;
  }

  const esc = (s) => s.replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  /**
   * One line as HTML.
   *
   * Deliberately a lexer over one line and not a parser: it never needs
   * to be right about the program, only about what the eye should
   * group. `state` carries an open triple-quoted string or an open
   * `/* *\/` comment across lines.
   */
  function paintLine(src, state, spec, lig) {
    let out = "";
    let i = 0;

    if (state.triple) {
      const end = src.indexOf(state.triple);
      if (end === -1) return '<span class="s">' + esc(src) + "</span>";
      out += '<span class="s">' + esc(src.slice(0, end + 3)) + "</span>";
      i = end + 3;
      state.triple = null;
    } else if (state.block) {
      const end = src.indexOf("*/");
      if (end === -1) return '<span class="c">' + esc(src) + "</span>";
      out += '<span class="c">' + esc(src.slice(0, end + 2)) + "</span>";
      i = end + 2;
      state.block = false;
    } else if (spec.preproc) {
      // `#include <vector>` — the directive is the keyword, and what
      // follows is left to the ordinary lexer so a quoted header still
      // reads as a string
      const m = /^(\s*)(#\s*[A-Za-z]+)/.exec(src);
      if (m) {
        out += esc(m[1]) + '<span class="k">' + esc(m[2]) + "</span>";
        i = m[0].length;
      }
    }

    while (i < src.length) {
      const c = src[i];

      if (spec.line && src.startsWith(spec.line, i)) {
        out += '<span class="c">' + esc(src.slice(i)) + "</span>";
        break;
      }
      if (spec.block && src.startsWith("/*", i)) {
        const end = src.indexOf("*/", i + 2);
        if (end === -1) {
          state.block = true;
          out += '<span class="c">' + esc(src.slice(i)) + "</span>";
          break;
        }
        out += '<span class="c">' + esc(src.slice(i, end + 2)) + "</span>";
        i = end + 2;
        continue;
      }
      if (c === '"' || c === "'") {
        if (spec.triple && src.slice(i, i + 3) === c + c + c) {
          const triple = c + c + c;
          const end = src.indexOf(triple, i + 3);
          if (end === -1) {
            state.triple = triple;
            out += '<span class="s">' + esc(src.slice(i)) + "</span>";
            break;
          }
          out += '<span class="s">' + esc(src.slice(i, end + 3)) + "</span>";
          i = end + 3;
          continue;
        }
        let j = i + 1;
        while (j < src.length && src[j] !== c) j += src[j] === "\\" ? 2 : 1;
        out += '<span class="s">' + esc(src.slice(i, j + 1)) + "</span>";
        i = j + 1;
        continue;
      }
      if (c >= "0" && c <= "9") {
        let j = i;
        while (j < src.length && /[0-9._boxXa-fA-FlLuUfF']/.test(src[j])) j++;
        out += '<span class="n">' + esc(src.slice(i, j)) + "</span>";
        i = j;
        continue;
      }
      if (/[A-Za-z_$]/.test(c)) {
        let j = i;
        while (j < src.length && /[A-Za-z0-9_$]/.test(src[j])) j++;
        const word = src.slice(i, j);
        const cls = spec.keywords.has(word) ? "k"
                  : spec.known.has(word) ? "d" : null;
        out += cls ? '<span class="' + cls + '">' + esc(word) + "</span>"
                   : esc(word);
        i = j;
        continue;
      }
      if (lig) {
        const hit = ligAt(src, i);
        if (hit) { out += hit.html; i += hit.len; continue; }
      }
      out += esc(c);
      i += 1;
    }
    return out;
  }

  function paint(src, spec, ligatures) {
    const state = { triple: null, block: false };
    const lang = typeof spec === "string" ? LANGS[spec] : (spec || LANGS.python);
    return src.split("\n").map((line) => paintLine(line, state, lang, !!ligatures));
  }

  /* ---- pure text operations, so they can be reasoned about alone ---- */

  const Ops = {
    lineStart: (t, at) => t.lastIndexOf("\n", at - 1) + 1,
    lineEnd: (t, at) => {
      const i = t.indexOf("\n", at);
      return i === -1 ? t.length : i;
    },
    indentOf: (line) => (line.match(/^[ \t]*/) || [""])[0],

    /**
     * What Enter should insert here, and how far back from the end of
     * it the caret belongs. Splitting a pair — Enter between `{` and
     * `}` — is the only case where those two differ.
     */
    newline(text, at, spec) {
      const start = Ops.lineStart(text, at);
      const line = text.slice(start, Ops.lineEnd(text, at));
      const before = text.slice(start, at).trimEnd();
      const after = text.slice(at, Ops.lineEnd(text, at));
      const unit = spec.unit;
      let indent = Ops.indentOf(line);

      if (/[([{]$/.test(before) || (spec.colon && /:$/.test(before))) {
        const inner = indent + unit;
        if (/^\s*[)\]}]/.test(after)) {
          return { ins: "\n" + inner + "\n" + indent, back: indent.length + 1 };
        }
        return { ins: "\n" + inner, back: 0 };
      }
      if (spec.dedentAfter && spec.dedentAfter.test(before)) {
        indent = indent.slice(0, Math.max(0, indent.length - unit.length));
      }
      return { ins: "\n" + indent, back: 0 };
    },

    /** The [start, end) of the whole lines a selection touches. */
    block(text, a, b) {
      const start = Ops.lineStart(text, a);
      const end = Ops.lineEnd(text, b > a && text[b - 1] === "\n" ? b - 1 : b);
      return [start, end];
    },

    indent(text, a, b, unit) {
      const [s, e] = Ops.block(text, a, b);
      const body = text.slice(s, e).split("\n")
        .map((l) => (l.length ? unit + l : l)).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a: a + unit.length, b: b + (body.length - (e - s)) };
    },

    dedent(text, a, b, unit) {
      const [s, e] = Ops.block(text, a, b);
      let firstCut = 0;
      const body = text.slice(s, e).split("\n").map((l, i) => {
        const cut = Math.min(unit.length, (l.match(/^ */) || [""])[0].length);
        if (i === 0) firstCut = cut;
        return l.slice(cut);
      }).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a: Math.max(s, a - firstCut),
               b: Math.max(s, b - ((e - s) - body.length)) };
    },

    comment(text, a, b, token) {
      const [s, e] = Ops.block(text, a, b);
      const lines = text.slice(s, e).split("\n");
      const live = lines.filter((l) => l.trim());
      const mark = token.trim();
      const off = live.length > 0 &&
        live.every((l) => l.trimStart().startsWith(mark));
      const body = lines.map((l) => {
        if (!l.trim()) return l;
        const ind = Ops.indentOf(l);
        const rest = l.slice(ind.length);
        return off
          ? ind + (rest.startsWith(token) ? rest.slice(token.length)
                                          : rest.slice(mark.length))
          : ind + token + rest;
      }).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a, b: b + (body.length - (e - s)) };
    },

    /** The word around `at`, as [start, end), or null. */
    wordAt(text, at) {
      let s = at, e = at;
      while (s > 0 && /[A-Za-z0-9_$]/.test(text[s - 1])) s--;
      while (e < text.length && /[A-Za-z0-9_$]/.test(text[e])) e++;
      return e > s ? [s, e] : null;
    },
  };

  const PAIRS = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" };
  const CLOSERS = new Set([")", "]", "}", '"', "'"]);

  /* ================================================================= */

  function Editor(opts) {
    const ta = opts.textarea;
    const paintEl = opts.paint;
    const gutter = opts.gutter;
    const caret = opts.caret;
    const hints = opts.hints;
    const doc = ta.ownerDocument;
    const win = doc.defaultView;

    let spec = LANGS[opts.language] || LANGS.python;
    let lines = [""];
    let starts = [0];
    let painted = null;         // the source `lines` was built from
    let need = 0;               // 1 text, 2 caret
    let frame = 0;
    let metrics = null;
    let composing = false;
    let idleTimer = 0;

    // caret motion: current, target, and whether to land instead of glide
    let cx = 0, cy = 0, tx = 0, ty = 0, jump = true, craf = 0, prev = 0;

    const reduceMotion = () => win.matchMedia
      && win.matchMedia("(prefers-reduced-motion: reduce)").matches;

    /**
     * Font metrics, measured from what is actually on screen.
     *
     * `getComputedStyle().lineHeight` reports "normal" or a bare ratio
     * depending on the engine and whether the element is visible, so a
     * rendered gutter row is the more reliable witness. Cached: reading
     * it per frame forces a style recalculation, which is its own
     * stutter.
     */
    function measure() {
      if (metrics) return metrics;
      const cs = getComputedStyle(ta);
      const size = parseFloat(cs.fontSize) || 14;
      const declared = parseFloat(cs.lineHeight);
      const row = gutter.firstElementChild;
      const measured = row ? row.getBoundingClientRect().height : 0;
      const probe = doc.createElement("span");
      probe.style.cssText = "position:absolute;visibility:hidden;white-space:pre";
      probe.style.font = cs.font;
      probe.textContent = "0".repeat(20);
      doc.body.appendChild(probe);
      const charW = probe.getBoundingClientRect().width / 20;
      probe.remove();
      metrics = {
        lh: measured > size * 0.6 ? measured
          : (declared > size * 0.6 ? declared : size * 1.72),
        charW,
        padTop: parseFloat(cs.paddingTop) || 0,
      };
      return metrics;
    }

    function schedule(what) {
      need |= what;
      if (frame) return;
      frame = win.requestAnimationFrame(() => { frame = 0; render(); });
    }

    function render() {
      const flags = need;
      need = 0;
      if (composing) return;      // never disturb the layer mid-composition
      const src = ta.value;
      if (flags & 1) { reflow(src); drawWindow(true); }
      else drawWindow(false);
      if (flags & 2) {
        markLine();
        if (opts.onCursor) opts.onCursor(position());
      }
      sync();
    }

    function reflow(src) {
      if (src === painted) return;
      lines = paint(src, spec, opts.ligatures ? opts.ligatures() : true);
      const next = new Array(lines.length);
      let at = 0;
      for (let i = 0; i < lines.length; i++) {
        next[i] = at;
        at = src.indexOf("\n", at) + 1 || src.length;
      }
      starts = next;
      painted = src;
      shown = [-1, -1];
    }

    /**
     * Only the visible lines go into the document.
     *
     * The textarea holds and scrolls the whole file; it is the painted
     * layers that are windowed, and they are offset to sit under the
     * real text. A thousand-line file otherwise means a thousand nodes
     * re-parsed on every edit.
     */
    let shown = [-1, -1];
    const OVERSCAN = 20;

    function drawWindow(force) {
      const m = measure();
      const top = ta.scrollTop;
      const height = ta.clientHeight || 600;
      const from = Math.max(0, Math.floor(top / m.lh) - OVERSCAN);
      const to = Math.min(lines.length,
                          Math.ceil((top + height) / m.lh) + OVERSCAN);
      if (!force && from === shown[0] && to === shown[1]) return;
      shown = [from, to];
      paintEl.firstElementChild.innerHTML =
        lines.slice(from, to).join("\n") + "\n";
      let rows = "";
      for (let i = from + 1; i <= to; i++) {
        rows += '<div class="ln' + (opts.badLine === i ? " bad" : "") +
          '" data-line="' + i + '">' + i + "</div>";
      }
      gutter.innerHTML = rows;
      here = null;
      markLine();
    }

    let here = null;
    function markLine() {
      const line = position().line;
      if (here && +here.dataset.line === line) return;
      if (here) here.classList.remove("here");
      const row = gutter.children[line - 1 - shown[0]];
      if (row && +row.dataset.line === line) row.classList.add("here");
      here = row || null;
    }

    function sync() {
      const m = measure();
      const y = shown[0] * m.lh - ta.scrollTop;
      paintEl.style.transform =
        "translate3d(" + (-ta.scrollLeft) + "px," + y + "px,0)";
      gutter.style.transform = "translate3d(0," + y + "px,0)";
      aimCaret();
      if (hints && !hints.hidden) placeHints();
    }

    /* ---- caret ---------------------------------------------------- */

    function position() {
      const at = ta.selectionStart;
      const before = ta.value.slice(0, at);
      const line = (before.match(/\n/g) || []).length + 1;
      return { line, col: at - before.lastIndexOf("\n"), at };
    }

    function aimCaret() {
      if (doc.activeElement !== ta || ta.selectionStart !== ta.selectionEnd) {
        caret.style.opacity = "0";
        return;
      }
      caret.style.opacity = "";
      const m = measure();
      const p = position();
      const line = ta.value.slice(starts[p.line - 1] || 0, p.at);
      let cols = 0;
      for (const ch of line) cols += ch === "\t" ? 4 - (cols % 4) : 1;
      const x = cols * m.charW - ta.scrollLeft;
      const y = (p.line - 1) * m.lh - ta.scrollTop + m.padTop;
      caret.style.height = m.lh + "px";
      if (Math.abs(x - tx) + Math.abs(y - ty) > m.lh * 3.5) jump = true;
      tx = x; ty = y;
      glide();
    }

    /**
     * Interpolate towards the target, then stop.
     *
     * The easing is raised to (dt / 16.667) so the motion feels the same
     * at 60, 120 or 144 Hz rather than being tuned for one of them, and
     * the loop cancels itself on arrival — a caret holding a frame
     * callback open while nothing moves is a battery bug.
     */
    function glide() {
      if (craf) return;
      const ex = reduceMotion() ? 1 : 0.3;
      const ey = reduceMotion() ? 1 : 0.36;
      const step = (now) => {
        const dt = prev ? Math.min(64, now - prev) : 16.667;
        prev = now;
        if (jump) { cx = tx; cy = ty; jump = false; }
        else {
          cx += (tx - cx) * (1 - Math.pow(1 - ex, dt / 16.667));
          cy += (ty - cy) * (1 - Math.pow(1 - ey, dt / 16.667));
        }
        caret.style.transform =
          "translate3d(" + cx.toFixed(2) + "px," + cy.toFixed(2) + "px,0)";
        if (Math.abs(tx - cx) < 0.05 && Math.abs(ty - cy) < 0.05) {
          cx = tx; cy = ty;
          caret.style.transform =
            "translate3d(" + cx.toFixed(2) + "px," + cy.toFixed(2) + "px,0)";
          craf = 0; prev = 0;
          return;
        }
        craf = win.requestAnimationFrame(step);
      };
      prev = 0;
      craf = win.requestAnimationFrame(step);
    }

    function typingNow() {
      doc.body.classList.add("typing");
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => doc.body.classList.remove("typing"), 620);
    }

    /* ---- edits that keep native undo ------------------------------ */

    function insert(text) {
      ta.focus();
      if (!doc.execCommand || !doc.execCommand("insertText", false, text)) {
        const s = ta.selectionStart, e = ta.selectionEnd;
        ta.setRangeText(text, s, e, "end");
      }
      changed();
    }

    function replaceAll(next, a, b) {
      ta.select();
      if (!doc.execCommand || !doc.execCommand("insertText", false, next)) {
        ta.value = next;
      }
      ta.setSelectionRange(a, b);
      changed();
    }

    function changed() {
      typingNow();
      schedule(3);
      if (opts.onChange) opts.onChange();
    }

    /* ---- completion: the buffer's own words, and nothing remote --- */

    let index = null;
    let list = [];
    let pick = 0;
    let from = 0;

    function words(text) {
      const now = performance.now();
      if (index && index.spec === spec && now - index.at < 900
          && Math.abs(text.length - index.len) < 240) return index.seen;
      const seen = new Map();
      const re = /[A-Za-z_$][A-Za-z0-9_$]{1,}/g;
      let m;
      while ((m = re.exec(text))) seen.set(m[0], (seen.get(m[0]) || 0) + 1);
      index = { at: now, len: text.length, spec, seen };
      return seen;
    }

    function suggest() {
      if (!hints) return;
      const text = ta.value;
      const p = position();
      const w = Ops.wordAt(text, p.at);
      from = w && w[0] < p.at ? w[0] : p.at;
      const prefix = text.slice(from, p.at);
      if (prefix.length < 2) return closeHints();
      const low = prefix.toLowerCase();
      const out = [];
      spec.keywords.forEach((k) => {
        if (k.length > prefix.length && k.toLowerCase().startsWith(low)) {
          out.push({ name: k, kind: "keyword" });
        }
      });
      spec.known.forEach((b) => {
        if (b.length > prefix.length && b.toLowerCase().startsWith(low)) {
          out.push({ name: b, kind: spec.label });
        }
      });
      words(text).forEach((count, word) => {
        if (word !== prefix && word.toLowerCase().startsWith(low)
            && !spec.keywords.has(word) && !spec.known.has(word)) {
          out.push({ name: word, kind: "here", n: count });
        }
      });
      if (!out.length) return closeHints();
      out.sort((a, b) =>
        (b.n || 0) - (a.n || 0) || a.name.length - b.name.length);
      list = out.slice(0, 12);
      pick = 0;
      drawHints(prefix);
    }

    function drawHints(prefix) {
      hints.innerHTML = "";
      list.forEach((item, i) => {
        const row = doc.createElement("div");
        row.className = "hint" + (i === pick ? " on" : "");
        row.innerHTML = "<em>" + esc(item.name.slice(0, prefix.length)) +
          "</em>" + esc(item.name.slice(prefix.length)) +
          "<span>" + esc(item.kind) + "</span>";
        row.addEventListener("mousedown", (ev) => {
          ev.preventDefault();
          pick = i;
          accept();
        });
        hints.appendChild(row);
      });
      hints.hidden = false;
      placeHints();
    }

    function placeHints() {
      const m = measure();
      const p = position();
      const left = Math.max(0, (p.col - 1) * m.charW - ta.scrollLeft);
      const top = p.line * m.lh - ta.scrollTop + m.padTop + 4;
      hints.style.left = left + "px";
      hints.style.top = top + "px";
    }

    function closeHints() { if (hints) hints.hidden = true; list = []; }

    function accept() {
      const item = list[pick];
      if (!item) return;
      const at = ta.selectionStart;
      ta.setSelectionRange(from, at);
      insert(item.name);
      closeHints();
    }

    /* ---- keys ------------------------------------------------------ */

    ta.addEventListener("keydown", (ev) => {
      if (ev.isComposing || ev.keyCode === 229) return;   // let the IME work
      const text = ta.value;
      const a = ta.selectionStart, b = ta.selectionEnd;

      if (hints && !hints.hidden) {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          pick = (pick + (ev.key === "ArrowDown" ? 1 : list.length - 1))
                 % list.length;
          Array.from(hints.children).forEach((el, i) =>
            el.classList.toggle("on", i === pick));
          return;
        }
        if (ev.key === "Enter" || ev.key === "Tab") {
          ev.preventDefault();
          return accept();
        }
        if (ev.key === "Escape") { ev.preventDefault(); return closeHints(); }
      }

      if (ev.key === "Enter" && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
        ev.preventDefault();
        const r = Ops.newline(text, a, spec);
        insert(r.ins);
        if (r.back) {
          const at = ta.selectionStart - r.back;
          ta.setSelectionRange(at, at);
          schedule(2);
        }
        return;
      }
      if (ev.key === "Tab") {
        ev.preventDefault();
        if (a !== b || ev.shiftKey) {
          const r = ev.shiftKey ? Ops.dedent(text, a, b, spec.unit)
                                : Ops.indent(text, a, b, spec.unit);
          return replaceAll(r.text, r.a, r.b);
        }
        return insert(spec.unit);
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "/") {
        ev.preventDefault();
        const r = Ops.comment(text, a, b, spec.comment);
        return replaceAll(r.text, r.a, r.b);
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === " ") {
        ev.preventDefault();
        return suggest();
      }

      // a `}` alone on its line closes the block it belongs to, so it
      // takes back one level as you type it
      if (spec.braces && ev.key === "}" && a === b) {
        const head = text.slice(Ops.lineStart(text, a), a);
        if (/^[ \t]+$/.test(head) && head.length >= spec.unit.length) {
          ev.preventDefault();
          ta.setSelectionRange(a - spec.unit.length, a);
          return insert("}");
        }
      }

      if (PAIRS[ev.key] && !ev.ctrlKey && !ev.metaKey) {
        const close = PAIRS[ev.key];
        if (a !== b) {                       // wrap the selection
          ev.preventDefault();
          const sel = text.slice(a, b);
          insert(ev.key + sel + close);
          ta.setSelectionRange(a + 1, a + 1 + sel.length);
          return;
        }
        if (!/[A-Za-z0-9_$]/.test(text[a] || "")) {
          ev.preventDefault();
          insert(ev.key + close);
          ta.setSelectionRange(a + 1, a + 1);
          return;
        }
      }
      if (CLOSERS.has(ev.key) && text[a] === ev.key && a === b) {
        ev.preventDefault();                 // type through the closer
        ta.setSelectionRange(a + 1, a + 1);
        schedule(2);
        return;
      }
      if (ev.key === "Backspace" && a === b && a > 0) {
        const before = text[a - 1];
        if (PAIRS[before] && text[a] === PAIRS[before]) {
          ev.preventDefault();
          ta.setSelectionRange(a - 1, a + 1);
          insert("");
          return;
        }
      }
    });

    ta.addEventListener("input", () => {
      changed();
      if (!composing) suggest();
    });
    ta.addEventListener("compositionstart", () => {
      composing = true;
      doc.body.classList.add("ime");
      closeHints();
    });
    ta.addEventListener("compositionend", () => {
      composing = false;
      doc.body.classList.remove("ime");
      changed();
    });
    ["click", "keyup", "select"].forEach((e) =>
      ta.addEventListener(e, () => schedule(2)));
    ta.addEventListener("scroll", () => { jump = true; schedule(2); });
    ta.addEventListener("blur", () => { closeHints(); schedule(2); });
    ta.addEventListener("focus", () => schedule(2));
    win.addEventListener("resize", () => {
      metrics = null; jump = true; shown = [-1, -1]; schedule(3);
    });

    gutter.addEventListener("click", (ev) => {
      const row = ev.target.closest(".ln");
      if (row && opts.onGutter) opts.onGutter(+row.dataset.line);
    });

    return {
      get value() { return ta.value; },
      set value(v) {
        ta.value = v;
        painted = null;
        jump = true;
        shown = [-1, -1];
        closeHints();
        schedule(3);
      },
      get language() { return spec.id; },
      setLanguage(name) {
        spec = LANGS[name] || LANGS.python;
        index = null;
        painted = null;
        shown = [-1, -1];
        closeHints();
        schedule(3);
      },
      position,
      focus: () => ta.focus(),
      refresh: () => { metrics = null; shown = [-1, -1]; schedule(3); },
      repaint: () => { painted = null; shown = [-1, -1]; schedule(3); },
      goToLine(line) {
        const at = starts[Math.max(0, Math.min(line, starts.length) - 1)] || 0;
        ta.focus();
        ta.setSelectionRange(at, at);
        ta.scrollTop = Math.max(0, (line - 5) * measure().lh);
        jump = true;
        schedule(3);
      },
      markBad(line) { opts.badLine = line; shown = [-1, -1]; schedule(1); },
    };
  }

  root.EpsilonEditor = { Editor, Ops, paint, LANGS };
})(typeof window !== "undefined" ? window : globalThis);
