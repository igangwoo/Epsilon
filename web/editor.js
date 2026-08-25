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
 *      cached against the exact source it was built from.
 *   2. Nothing on the typing path leaves the page. Completion comes
 *      from the buffer's own words — Python runs on this thread, so
 *      asking it per keystroke would freeze the page.
 *   3. The caret is interpolated in a frame loop, not by a CSS
 *      transition. A transition restarts from zero velocity on every
 *      keystroke, which is exactly what makes a caret feel steppy.
 * =================================================================== */
(function (root) {
  "use strict";

  const KEYWORDS = new Set(("False None True and as assert async await break " +
    "class continue def del elif else except finally for from global if " +
    "import in is lambda nonlocal not or pass raise return try while with " +
    "yield match case").split(" "));
  const BUILTINS = new Set(("abs all any bool bytes callable chr dict dir " +
    "divmod enumerate filter float format frozenset getattr hasattr hash " +
    "hex id input int isinstance issubclass iter len list map max min next " +
    "object oct open ord pow print range repr reversed round set setattr " +
    "sorted str sum tuple type vars zip self cls super __init__ __name__ " +
    "Exception ValueError TypeError KeyError IndexError").split(" "));

  /* =================================================================
   * Ligatures
   *
   * A rendering layer, never an edit: the file on disk still says `>=`,
   * and every keystroke, selection and column number is computed from
   * that text. What changes is only what the eye is shown.
   *
   * The one hard rule is width. The textarea underneath owns hit
   * testing and selection, and it lays every character out on a uniform
   * monospace grid — so a ligature may occupy exactly as many cells as
   * the source it stands for, no more and no less. Each one is drawn in
   * a fixed `Nch` box, which is also why long words are absent here: a
   * `lambda` rendered as one λ would leave five empty cells behind it,
   * and a hole in the middle of a line is worse than the word.
   *
   * Strings and comments are left alone. Their contents are data, and
   * showing `>=` inside a string as `≥` would misreport what the
   * program holds.
   * ================================================================= */

  //: two- and three-character operators. Longest first: `<->` must be
  //: tried before `<-`, and `//` before `/`.
  const LIG_OPS = [
    ["<->", "↔"], ["...", "…"],
    ["->", "→"], ["<-", "←"], ["=>", "⇒"],
    ["==", "≡"], ["!=", "≠"], [">=", "≥"], ["<=", "≤"],
    [":=", "≔"], ["<<", "≪"], [">>", "≫"], ["//", "⫽"],
  ];

  //: single characters, and the only ones that cost nothing at all —
  //: one cell in, one cell out. Only when spaced, so `*args` and a bare
  //: `/` in a path keep their meaning.
  const LIG_SPACED = { "*": "×", "/": "÷", "-": "−" };

  //: short enough that the leftover cells still read as one token
  const LIG_WORDS = {
    pi: "π", tau: "τ", inf: "∞",
    not: "¬", and: "∧", or: "∨", in: "∈",
  };

  const SUP = { 0: "⁰", 1: "¹", 2: "²", 3: "³",
                4: "⁴", 5: "⁵", 6: "⁶", 7: "⁷",
                8: "⁸", 9: "⁹", "-": "⁻" };
  const SUB = { 0: "₀", 1: "₁", 2: "₂", 3: "₃",
                4: "₄", 5: "₅", 6: "₆", 7: "₇",
                8: "₈", 9: "₉" };

  //: where a single glyph exists it beats digits-over-digits
  const VULGAR = {
    "1/2": "½", "1/3": "⅓", "2/3": "⅔", "1/4": "¼",
    "3/4": "¾", "1/5": "⅕", "2/5": "⅖", "3/5": "⅗",
    "4/5": "⅘", "1/6": "⅙", "5/6": "⅚", "1/7": "⅐",
    "1/8": "⅛", "3/8": "⅜", "5/8": "⅝", "7/8": "⅞",
    "1/9": "⅑", "1/10": "⅒",
  };

  const map = (text, table) =>
    Array.from(text).map((ch) => table[ch] || ch).join("");

  /** One ligature, in a box exactly as wide as the text it replaces. */
  function cell(width, glyph, cls) {
    return '<span class="lg' + (cls ? " " + cls : "") + '" style="width:' +
      width + 'ch">' + glyph + "</span>";
  }

  /**
   * The ligature starting at `i`, or null.
   *
   * Order matters: an exponent claims its digits before `*` can become
   * a times sign, and the two-character operators are tried before the
   * spaced single characters that share their first letter.
   */
  function ligAt(src, i, cls) {
    const rest = src.slice(i);

    // x**2 — the exponent hugs its base, so this box is left-aligned
    const power = /^\*\*\s*(-?\d+)(?![\w.])/.exec(rest);
    if (power) {
      return { len: power[0].length,
               html: cell(power[0].length, map(power[1], SUP), "lg-left") };
    }

    for (const [text, glyph] of LIG_OPS) {
      if (rest.startsWith(text)) {
        return { len: text.length, html: cell(text.length, glyph, cls) };
      }
    }

    const ch = src[i];
    if (LIG_SPACED[ch] && src[i - 1] === " " && src[i + 1] === " ") {
      return { len: 1, html: cell(1, LIG_SPACED[ch], cls) };
    }
    return null;
  }

  /** `3/4` as a fraction — a single glyph where one exists, else the
      numerator raised over a fraction slash. */
  function fractionAt(src, i) {
    const m = /^(\d+)\/(\d+)(?![\w.])/.exec(src.slice(i));
    if (!m) return null;
    const glyph = VULGAR[m[1] + "/" + m[2]]
      || (map(m[1], SUP) + "⁄" + map(m[2], SUB));
    return { len: m[0].length, html: cell(m[0].length, glyph, "n") };
  }

  const esc = (s) => s.replace(/[&<>]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  /**
   * One line of Python as HTML.
   *
   * Deliberately a lexer over one line and not a parser: it never needs
   * to be right about the program, only about what the eye should group.
   * `state` carries an open triple-quoted string across lines.
   */
  function paintLine(src, state, lig) {
    let out = "";
    let i = 0;
    if (state.triple) {
      const end = src.indexOf(state.triple);
      if (end === -1) return '<span class="s">' + esc(src) + "</span>";
      out += '<span class="s">' + esc(src.slice(0, end + 3)) + "</span>";
      i = end + 3;
      state.triple = null;
    }
    while (i < src.length) {
      const c = src[i];
      if (c === "#") {
        out += '<span class="c">' + esc(src.slice(i)) + "</span>";
        break;
      }
      if (c === '"' || c === "'") {
        const triple = src.slice(i, i + 3);
        if (triple === c + c + c) {
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
        if (lig) {
          const frac = fractionAt(src, i);
          if (frac) { out += frac.html; i += frac.len; continue; }
        }
        let j = i;
        while (j < src.length && /[0-9._boxXa-fA-F]/.test(src[j])) j++;
        out += '<span class="n">' + esc(src.slice(i, j)) + "</span>";
        i = j;
        continue;
      }
      if (/[A-Za-z_]/.test(c)) {
        let j = i;
        while (j < src.length && /[A-Za-z0-9_]/.test(src[j])) j++;
        const word = src.slice(i, j);
        const cls = KEYWORDS.has(word) ? "k" : BUILTINS.has(word) ? "d" : null;
        if (lig && LIG_WORDS[word]) {
          out += cell(word.length, LIG_WORDS[word], cls);
        } else {
          out += cls ? '<span class="' + cls + '">' + esc(word) + "</span>"
                     : esc(word);
        }
        i = j;
        continue;
      }
      if (lig) {
        const hit = ligAt(src, i, "o");
        if (hit) { out += hit.html; i += hit.len; continue; }
      }
      out += esc(c);
      i += 1;
    }
    return out;
  }

  function paint(src, ligatures) {
    const state = { triple: null };
    return src.split("\n").map((line) => paintLine(line, state, !!ligatures));
  }

  /* ---- pure text operations, so they can be reasoned about alone ---- */

  const Ops = {
    lineStart: (t, at) => t.lastIndexOf("\n", at - 1) + 1,
    lineEnd: (t, at) => {
      const i = t.indexOf("\n", at);
      return i === -1 ? t.length : i;
    },
    indentOf: (line) => (line.match(/^[ \t]*/) || [""])[0],

    /** What Enter should insert here. */
    newline(text, at) {
      const start = Ops.lineStart(text, at);
      const line = text.slice(start, Ops.lineEnd(text, at));
      const before = text.slice(start, at).trimEnd();
      let indent = Ops.indentOf(line);
      if (/[:([{]$/.test(before)) indent += "    ";
      else if (/^\s*(return|pass|break|continue|raise)\b/.test(before)) {
        indent = indent.slice(0, Math.max(0, indent.length - 4));
      }
      return "\n" + indent;
    },

    /** The [start, end) of the whole lines a selection touches. */
    block(text, a, b) {
      const start = Ops.lineStart(text, a);
      const end = Ops.lineEnd(text, b > a && text[b - 1] === "\n" ? b - 1 : b);
      return [start, end];
    },

    indent(text, a, b) {
      const [s, e] = Ops.block(text, a, b);
      const body = text.slice(s, e).split("\n")
        .map((l) => (l.length ? "    " + l : l)).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a: a + 4, b: b + (body.length - (e - s)) };
    },

    dedent(text, a, b) {
      const [s, e] = Ops.block(text, a, b);
      let firstCut = 0;
      const body = text.slice(s, e).split("\n").map((l, i) => {
        const cut = Math.min(4, (l.match(/^ */) || [""])[0].length);
        if (i === 0) firstCut = cut;
        return l.slice(cut);
      }).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a: Math.max(s, a - firstCut),
               b: Math.max(s, b - ((e - s) - body.length)) };
    },

    comment(text, a, b) {
      const [s, e] = Ops.block(text, a, b);
      const lines = text.slice(s, e).split("\n");
      const live = lines.filter((l) => l.trim());
      const off = live.length > 0 && live.every((l) => l.trimStart().startsWith("#"));
      const body = lines.map((l) => {
        if (!l.trim()) return l;
        const ind = Ops.indentOf(l);
        const rest = l.slice(ind.length);
        return off
          ? ind + (rest.startsWith("# ") ? rest.slice(2) : rest.slice(1))
          : ind + "# " + rest;
      }).join("\n");
      return { text: text.slice(0, s) + body + text.slice(e),
               a, b: b + (body.length - (e - s)) };
    },

    /** The word around `at`, as [start, end), or null. */
    wordAt(text, at) {
      let s = at, e = at;
      while (s > 0 && /[A-Za-z0-9_]/.test(text[s - 1])) s--;
      while (e < text.length && /[A-Za-z0-9_]/.test(text[e])) e++;
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
          : (declared > size * 0.6 ? declared : size * 1.85),
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
      if (flags & 1) reflow(src);
      if (flags & 1) drawWindow(true);
      else drawWindow(false);
      if (flags & 2) {
        markLine();
        if (opts.onCursor) opts.onCursor(position());
      }
      sync();
    }

    function reflow(src) {
      if (src === painted) return;
      lines = paint(src, opts.ligatures && opts.ligatures());
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
      const to = Math.min(lines.length, Math.ceil((top + height) / m.lh) + OVERSCAN);
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
      paintEl.style.transform = "translate3d(" + (-ta.scrollLeft) + "px," + y + "px,0)";
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
      if (index && now - index.at < 900
          && Math.abs(text.length - index.len) < 240) return index.seen;
      const seen = new Map();
      const re = /[A-Za-z_][A-Za-z0-9_]{1,}/g;
      let m;
      while ((m = re.exec(text))) seen.set(m[0], (seen.get(m[0]) || 0) + 1);
      index = { at: now, len: text.length, seen };
      return seen;
    }

    function suggest() {
      const text = ta.value;
      const p = position();
      const w = Ops.wordAt(text, p.at);
      from = w && w[0] < p.at ? w[0] : p.at;
      const prefix = text.slice(from, p.at);
      if (prefix.length < 2) return closeHints();
      const low = prefix.toLowerCase();
      const out = [];
      KEYWORDS.forEach((k) => {
        if (k.length > prefix.length && k.toLowerCase().startsWith(low)) {
          out.push({ name: k, kind: "keyword" });
        }
      });
      BUILTINS.forEach((b) => {
        if (b.length > prefix.length && b.toLowerCase().startsWith(low)) {
          out.push({ name: b, kind: "builtin" });
        }
      });
      words(text).forEach((count, word) => {
        if (word !== prefix && word.toLowerCase().startsWith(low)
            && !KEYWORDS.has(word) && !BUILTINS.has(word)) {
          out.push({ name: word, kind: "here", n: count });
        }
      });
      if (!out.length) return closeHints();
      out.sort((a, b) => (b.n || 0) - (a.n || 0) || a.name.length - b.name.length);
      list = out.slice(0, 12);
      pick = 0;
      drawHints(prefix);
    }

    function drawHints(prefix) {
      hints.innerHTML = "";
      list.forEach((item, i) => {
        const row = doc.createElement("div");
        row.className = "hint" + (i === pick ? " on" : "");
        row.innerHTML = "<em>" + esc(item.name.slice(0, prefix.length)) + "</em>" +
          esc(item.name.slice(prefix.length)) + "<span>" + item.kind + "</span>";
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

    function closeHints() { hints.hidden = true; list = []; }

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

      if (!hints.hidden) {
        if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
          ev.preventDefault();
          pick = (pick + (ev.key === "ArrowDown" ? 1 : list.length - 1)) % list.length;
          Array.from(hints.children).forEach((el, i) =>
            el.classList.toggle("on", i === pick));
          return;
        }
        if (ev.key === "Enter" || ev.key === "Tab") { ev.preventDefault(); return accept(); }
        if (ev.key === "Escape") { ev.preventDefault(); return closeHints(); }
      }

      if (ev.key === "Enter" && !ev.shiftKey && !ev.metaKey && !ev.ctrlKey) {
        ev.preventDefault();
        return insert(Ops.newline(text, a));
      }
      if (ev.key === "Tab") {
        ev.preventDefault();
        if (a !== b || ev.shiftKey) {
          const r = ev.shiftKey ? Ops.dedent(text, a, b) : Ops.indent(text, a, b);
          return replaceAll(r.text, r.a, r.b);
        }
        return insert("    ");
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === "/") {
        ev.preventDefault();
        const r = Ops.comment(text, a, b);
        return replaceAll(r.text, r.a, r.b);
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key === " ") {
        ev.preventDefault();
        return suggest();
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
        if (!/[A-Za-z0-9_]/.test(text[a] || "")) {
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

  root.EpsilonEditor = { Editor, Ops, paint, KEYWORDS, BUILTINS };
})(typeof window !== "undefined" ? window : globalThis);
