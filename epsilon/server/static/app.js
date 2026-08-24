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
      row.appendChild(el("span", "thm-name", t.name));
      item.appendChild(row);
      item.appendChild(el("div", "thm-stmt", t.statement));
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
    const panel = $("#inspectorPanel");
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
   * Dependency graph (force-directed)
   * =================================================================== */
  const graphCanvas = $("#graphCanvas");
  let graphData = { nodes: [], edges: [] };
  let graphView = { x: 0, y: 0, scale: 1, dragging: false, node: null };

  function renderDeps(deps) {
    graphData = deps;
    if (!$('.act[data-view="graph"]').classList.contains("active")) return;
    layoutGraph();
    drawGraph();
  }

  function layoutGraph() {
    const nodes = graphData.nodes;
    if (!nodes.length) return;
    const idx = {};
    nodes.forEach((n, i) => {
      idx[n.name] = n;
      if (n._x === undefined) {
        n._x = Math.cos(i) * 120 + 300;
        n._y = Math.sin(i * 1.7) * 120 + 220;
      }
    });
    const edges = graphData.edges
      .map((e) => [idx[e.from], idx[e.to]])
      .filter(([a, b]) => a && b);
    for (let iter = 0; iter < 80; iter++) {
      for (let i = 0; i < nodes.length; i++) {
        let fx = 0, fy = 0;
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const dx = nodes[i]._x - nodes[j]._x, dy = nodes[i]._y - nodes[j]._y;
          const d2 = dx * dx + dy * dy + 0.1;
          const f = 2400 / d2;
          fx += (dx / Math.sqrt(d2)) * f;
          fy += (dy / Math.sqrt(d2)) * f;
        }
        nodes[i]._fx = fx; nodes[i]._fy = fy;
      }
      edges.forEach(([a, b]) => {
        const dx = b._x - a._x, dy = b._y - a._y;
        const d = Math.sqrt(dx * dx + dy * dy) + 0.1;
        const f = (d - 90) * 0.02;
        a._fx += (dx / d) * f; a._fy += (dy / d) * f;
        b._fx -= (dx / d) * f; b._fy -= (dy / d) * f;
      });
      nodes.forEach((n) => {
        n._x += Math.max(-10, Math.min(10, n._fx * 0.1));
        n._y += Math.max(-10, Math.min(10, n._fy * 0.1));
      });
    }
  }

  function drawGraph() {
    const dpr = window.devicePixelRatio || 1;
    const W = graphCanvas.clientWidth, H = graphCanvas.clientHeight;
    graphCanvas.width = W * dpr; graphCanvas.height = H * dpr;
    const ctx = graphCanvas.getContext("2d");
    ctx.setTransform(dpr * graphView.scale, 0, 0, dpr * graphView.scale,
      graphView.x * dpr, graphView.y * dpr);
    ctx.clearRect(-5000, -5000, 10000, 10000);
    const css = getComputedStyle(document.documentElement);
    const line = css.getPropertyValue("--glass-border").trim();
    const fg = css.getPropertyValue("--fg-dim").trim();
    const statusColor = {
      proven: css.getPropertyValue("--ok").trim(),
      symbolic: css.getPropertyValue("--sym").trim(),
      numeric: css.getPropertyValue("--num").trim(),
      heuristic: css.getPropertyValue("--heur").trim(),
    };
    const idx = {};
    graphData.nodes.forEach((n) => (idx[n.name] = n));
    ctx.strokeStyle = line; ctx.lineWidth = 1;
    graphData.edges.forEach((e) => {
      const a = idx[e.from], b = idx[e.to];
      if (!a || !b) return;
      ctx.beginPath(); ctx.moveTo(a._x, a._y); ctx.lineTo(b._x, b._y); ctx.stroke();
    });
    ctx.font = "10px ui-monospace";
    graphData.nodes.forEach((n) => {
      ctx.beginPath(); ctx.arc(n._x, n._y, 6, 0, 7);
      ctx.fillStyle = n.kind === "axiom" ? "#ff9ec4" :
        (statusColor[n.status] || fg);
      ctx.fill();
      ctx.fillStyle = fg;
      ctx.fillText(n.name.split(".").pop(), n._x + 9, n._y + 3);
    });
  }

  graphCanvas.addEventListener("mousedown", (e) => {
    graphView.dragging = true;
    graphView._px = e.clientX; graphView._py = e.clientY;
  });
  window.addEventListener("mousemove", (e) => {
    if (!graphView.dragging) return;
    graphView.x += e.clientX - graphView._px;
    graphView.y += e.clientY - graphView._py;
    graphView._px = e.clientX; graphView._py = e.clientY;
    drawGraph();
  });
  window.addEventListener("mouseup", () => (graphView.dragging = false));
  graphCanvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    graphView.scale *= e.deltaY < 0 ? 1.1 : 0.9;
    graphView.scale = Math.max(0.2, Math.min(4, graphView.scale));
    drawGraph();
  });

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
    if (showGraph) { layoutGraph(); drawGraph(); }
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
  const consoleHistory = [];
  let histIdx = -1;
  $("#consoleInput").addEventListener("keydown", async (e) => {
    if (e.key === "Enter") {
      const code = e.target.value.trim();
      if (!code) return;
      consoleHistory.push(code);
      histIdx = consoleHistory.length;
      e.target.value = "";
      appendConsole(code, "in");
      const r = await api("POST", "/api/eval", { code });
      if (r.output) appendConsole(r.output, r.ok ? "" : "err");
      (r.diagnostics || []).forEach((d) => appendConsole(d, "err"));
    } else if (e.key === "ArrowUp") {
      histIdx = Math.max(0, histIdx - 1);
      if (consoleHistory[histIdx]) e.target.value = consoleHistory[histIdx];
    } else if (e.key === "ArrowDown") {
      histIdx = Math.min(consoleHistory.length, histIdx + 1);
      e.target.value = consoleHistory[histIdx] || "";
    }
  });
  function appendConsole(text, cls) {
    const log = $("#consoleLog");
    log.appendChild(el("div", "console-line " + (cls || ""), text));
    log.scrollTop = log.scrollHeight;
  }

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
        item.innerHTML = `<span class="sn">${esc(it.name)}</span><br>
          <span class="ss">${esc(it.type || it.kind)}</span>`;
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
    state.meta = await api("GET", "/api/meta");
    $("#metaVersion").textContent = "v" + (state.meta.version || "0.1");
    await loadFiles();
  }

  init();
})();
