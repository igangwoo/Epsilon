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
    if (!res.ok && res.status >= 500) {
      toast("Server error " + res.status, "err");
    }
    const ct = res.headers.get("content-type") || "";
    return ct.includes("json") ? res.json() : res.text();
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
   * Syntax highlighting (regex tokenizer)
   * =================================================================== */
  const KEYWORDS = new Set(("def define theorem lemma proposition corollary " +
    "example axiom constant inductive structure where import namespace end " +
    "open by fun forall exists in with notation infixl infixr prefix postfix " +
    "plot calc if then else sorry match").split(" "));
  const TACTICS = new Set(("intro intros exact apply assumption rfl symm " +
    "constructor split left right exists cases induction rw rewrite simp " +
    "unfold decide norm_num have show calc trivial contradiction exfalso " +
    "cas numeric ring linarith sorry clear auto").split(" "));

  function highlight(src) {
    // process line by line so we can track comment state and tactic context
    const out = [];
    const lines = src.split("\n");
    let inBlock = 0;
    for (let line of lines) {
      out.push(highlightLine(line, () => inBlock, (v) => (inBlock = v)));
    }
    return out.join("\n");
  }

  function highlightLine(line, getBlock, setBlock) {
    let res = "";
    let i = 0;
    const n = line.length;
    while (i < n) {
      if (getBlock() > 0) {
        const endBlk = line.indexOf("-/", i);
        if (endBlk === -1) {
          res += `<span class="tok-comment">${esc(line.slice(i))}</span>`;
          return res;
        }
        res += `<span class="tok-comment">${esc(line.slice(i, endBlk + 2))}</span>`;
        setBlock(getBlock() - 1);
        i = endBlk + 2;
        continue;
      }
      const ch = line[i];
      const two = line.slice(i, i + 2);
      if (two === "--") {
        res += `<span class="tok-comment">${esc(line.slice(i))}</span>`;
        return res;
      }
      if (two === "/-") {
        setBlock(getBlock() + 1);
        continue;
      }
      if (ch === '"') {
        let j = i + 1;
        while (j < n && line[j] !== '"') { if (line[j] === "\\") j++; j++; }
        res += `<span class="tok-string">${esc(line.slice(i, j + 1))}</span>`;
        i = j + 1;
        continue;
      }
      if (ch === "#") {
        let j = i + 1;
        while (j < n && /[a-zA-Z]/.test(line[j])) j++;
        res += `<span class="tok-directive">${esc(line.slice(i, j))}</span>`;
        i = j;
        continue;
      }
      if (/[0-9]/.test(ch)) {
        let j = i;
        while (j < n && /[0-9.]/.test(line[j])) j++;
        res += `<span class="tok-num">${esc(line.slice(i, j))}</span>`;
        i = j;
        continue;
      }
      if (/[A-Za-z_ℕℤℚℝℂπ]/.test(ch)) {
        let j = i;
        while (j < n && /[A-Za-z0-9_'.ℕℤℚℝℂπ]/.test(line[j])) j++;
        const word = line.slice(i, j);
        const bare = word.split(".").pop();
        let cls = "";
        if (KEYWORDS.has(word)) cls = "tok-keyword";
        else if (TACTICS.has(word)) cls = "tok-tactic";
        else if (/^[A-Zℕℤℚℝℂ]/.test(word) || /^[ℕℤℚℝℂ]/.test(bare)) cls = "tok-type";
        res += cls ? `<span class="${cls}">${esc(word)}</span>` : esc(word);
        i = j;
        continue;
      }
      if ("∀∃λ→↔∧∨¬≤≥≠∈∉⊆×√·∘".includes(ch) ||
          "+-*/^=<>|".includes(ch)) {
        res += `<span class="tok-op">${esc(ch)}</span>`;
        i++;
        continue;
      }
      res += esc(ch);
      i++;
    }
    return res;
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
    highlightCode.innerHTML = highlight(src);
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

  async function loadFiles() {
    const r = await api("GET", "/api/files");
    state.files = r.files || [];
    renderFileList();
    if (state.files.length === 0) {
      await api("POST", "/api/file", { path: "main.epsl", content: "" });
      return loadFiles();
    }
    if (!state.active) openFile(state.files[0].path);
  }

  function renderFileList() {
    const list = $("#fileList");
    list.innerHTML = "";
    (state.files || []).forEach((f) => {
      const item = el("li", "file-item");
      const tab = state.tabs.find((t) => t.path === f.path);
      if (tab && tab.dirty) item.classList.add("dirty");
      if (f.path === state.active) item.classList.add("active");
      item.innerHTML = `<svg viewBox="0 0 16 16" width="13" height="13">
        <path d="M4 1h5l3 3v11H4z" fill="none" stroke="currentColor"
        stroke-width="1.2"/></svg><span>${esc(f.name)}</span>
        <span class="dirty"></span>`;
      item.onclick = () => openFile(f.path);
      list.appendChild(item);
    });
  }

  async function openFile(path) {
    let tab = state.tabs.find((t) => t.path === path);
    if (!tab) {
      const r = await api("GET", "/api/file?path=" + encodeURIComponent(path));
      tab = { path, content: r.content || "", saved: r.content || "", dirty: false };
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
      tab.appendChild(el("span", null, name));
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

  async function newFile() {
    const name = prompt("New file name:", "untitled.epsl");
    if (!name) return;
    const path = name.endsWith(".epsl") ? name : name + ".epsl";
    await api("POST", "/api/file", { path, content: "" });
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
  }

  function setCheckState(s) {
    const chip = $("#checkState");
    chip.className = "chip " + (s === "ok" ? "ok" : s === "error" ? "err" :
      s === "running" ? "running" : "");
    chip.textContent = s === "running" ? "checking…" :
      s === "ok" ? "✓ checked" : s === "error" ? "✗ errors" : "ready";
    $("#checkBtn").classList.toggle("running", s === "running");
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
    $("#problemCount").textContent = errs.length;
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
    const showGraph = view === "graph";
    graphCanvas.classList.toggle("hidden", !showGraph);
    $(".editor-wrap .code-scroll").classList.toggle("hidden", showGraph);
    $("#gutter").classList.toggle("hidden", showGraph);
    document.getElementById("app").classList.remove("sidebar-collapsed");
    $("#graphTools").classList.toggle("hidden", !showGraph);
    if (showGraph) {
      graphSim.alpha = Math.max(graphSim.alpha, 0.9);
      startGraph();
      // let the simulation open up before framing it
      setTimeout(fitGraphView, 900);
    } else {
      stopGraph();
    }
  }

  function switchUtil(util) {
    $$(".util-tab").forEach((t) => t.classList.toggle("active", t.dataset.util === util));
    $$(".util-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.util !== util));
  }

  function switchBottom(b) {
    $$(".bottom-tab").forEach((t) => t.classList.toggle("active", t.dataset.bottom === b));
    $$(".bottom-panel").forEach((p) => p.classList.toggle("hidden", p.dataset.bottom !== b));
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
  ];
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
      paletteItems = COMMANDS.filter((c) => c.name.toLowerCase().includes(q));
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
    if (!graphCanvas.classList.contains("hidden")) drawGraph();
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
   * Resizable layout
   * =================================================================== */
  const LAYOUT_KEY = "epsilon.layout.v1";
  const layout = { side: 280, util: 320, bottom: 190 };

  function loadLayout() {
    try {
      Object.assign(layout, JSON.parse(localStorage.getItem(LAYOUT_KEY)) || {});
    } catch (e) {}
    applyLayout();
  }

  function applyLayout() {
    const app = document.getElementById("app");
    app.style.gridTemplateColumns =
      `52px ${layout.side}px 1fr ${layout.util}px`;
    app.style.gridTemplateRows = `44px 1fr ${layout.bottom}px 26px`;
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
    } catch (e) {}
  }

  function resetLayout() {
    layout.side = 280; layout.util = 320; layout.bottom = 190;
    applyLayout();
    toast("Layout reset", "ok");
  }

  function initResizers() {
    const app = document.getElementById("app");
    const bounds = { side: [150, 640], util: [180, 720], bottom: [60, 620] };

    $$(".resizer").forEach((handle) => {
      const which = handle.dataset.resize;
      let startPos = 0, startVal = 0, dragging = false;

      const onMove = (ev) => {
        if (!dragging) return;
        const p = ev.touches ? ev.touches[0] : ev;
        const delta = (which === "bottom")
          ? startPos - p.clientY
          : (which === "util" ? startPos - p.clientX : p.clientX - startPos);
        const [lo, hi] = bounds[which];
        layout[which] = Math.max(lo, Math.min(hi, startVal + delta));
        applyLayout();
      };
      const onUp = () => {
        dragging = false;
        document.body.classList.remove("resizing");
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        if (!graphCanvas.classList.contains("hidden")) drawGraph();
      };
      handle.addEventListener("mousedown", (ev) => {
        ev.preventDefault();
        dragging = true;
        startPos = which === "bottom" ? ev.clientY : ev.clientX;
        startVal = layout[which];
        document.body.classList.add("resizing");
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      });
      handle.addEventListener("dblclick", resetLayout);
      // keyboard accessible
      handle.addEventListener("keydown", (ev) => {
        const step = ev.shiftKey ? 40 : 12;
        if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") {
          layout[which] += which === "side" ? -step : step;
        } else if (ev.key === "ArrowRight" || ev.key === "ArrowDown") {
          layout[which] += which === "side" ? step : -step;
        } else return;
        ev.preventDefault();
        const [lo, hi] = bounds[which];
        layout[which] = Math.max(lo, Math.min(hi, layout[which]));
        applyLayout();
      });
    });
  }

  /* ===================================================================
   * Editor intelligence wiring
   * =================================================================== */
  function wireIntelligence() {
    measureText();
    editor.classList.add("custom-caret");
    loadLayout();
    initResizers();
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
      if (!graphCanvas.classList.contains("hidden")) drawGraph();
    });
  }

  /* ===================================================================
   * wiring
   * =================================================================== */
  function wire() {
    $("#checkBtn").onclick = runCheck;
    $("#themeBtn").onclick = toggleTheme;
    $("#newFileBtn").onclick = newFile;
    $("#paletteBtn").onclick = () => openPalette("cmd");
    $("#bottomCollapse").onclick = () =>
      document.getElementById("app").classList.toggle("bottom-collapsed");
    $$(".act[data-view]").forEach((a) =>
      (a.onclick = () => switchView(a.dataset.view)));
    $$(".util-tab").forEach((t) => (t.onclick = () => switchUtil(t.dataset.util)));
    $$(".bottom-tab").forEach((t) => (t.onclick = () => switchBottom(t.dataset.bottom)));

    document.addEventListener("keydown", (e) => {
      const mod = isMac ? e.metaKey : e.ctrlKey;
      if (mod && e.key === "Enter") { e.preventDefault(); runCheck(); }
      else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); saveCurrent(); }
      else if (mod && e.shiftKey && e.key.toLowerCase() === "p") { e.preventDefault(); openPalette("cmd"); }
      else if (mod && e.key.toLowerCase() === "p") { e.preventDefault(); openPalette("file"); }
      else if (e.key === "Escape") closePalette();
    });
    window.addEventListener("resize", () => {
      if (!graphCanvas.classList.contains("hidden")) drawGraph();
    });
  }

  async function init() {
    try {
      const saved = localStorage.getItem("epsilon-theme");
      if (saved) document.documentElement.setAttribute("data-theme", saved);
    } catch (e) {}
    wire();
    wireIntelligence();
    state.meta = await api("GET", "/api/meta");
    $("#metaVersion").textContent = "v" + (state.meta.version || "0.1");
    await loadFiles();
  }

  init();
})();
