/* ===================================================================
 * Epsilon — pane system.
 *
 * One infrastructure hosts every tool. The workspace is a binary split
 * tree whose leaves are tab groups; a tab shows a *view*, and a view is
 * an existing DOM element that gets re-parented into the tab body rather
 * than rebuilt. That is what lets the proof panel, the plot canvas, the
 * console and the rest keep the wiring they already have: code elsewhere
 * still finds `#thmList` or `#consoleLog` exactly where it expects to.
 *
 * Layout tree:
 *   leaf  = { id, type: "leaf",  tabs: [viewId], active: viewId }
 *   split = { id, type: "split", dir: "row"|"col", ratio, a, b }
 *
 * The manager owns geometry, tabs, focus and persistence. It knows
 * nothing about what any particular view does.
 * =================================================================== */
(function (global) {
  "use strict";

  const LAYOUT_KEY = "epsilon.workspace.v1";
  const MIN_PANE = 90;
  //: sash thickness, shared with the stylesheet so the two halves of a
  //: split always add up to the whole
  const SASH = 6;

  let uid = 0;
  const nextId = (p) => `${p}${++uid}`;

  /** Registered views: id -> {title, icon, element, onShow} */
  const views = new Map();

  const state = {
    root: null,          // layout tree
    maximized: null,     // leaf id, or null
    focus: null,         // leaf id
    onChange: null,
  };

  /* ---------------- registry ---------------- */

  function registerView(id, spec) {
    const element = typeof spec.element === "string"
      ? document.querySelector(spec.element) : spec.element;
    if (!element) return false;
    views.set(id, {
      id,
      title: spec.title || id,
      icon: spec.icon || "",
      element,
      onShow: spec.onShow || null,
      closable: spec.closable !== false,
      badge: "",
      badgeTone: "",
    });
    element.classList.add("pane-view");
    return true;
  }

  function viewIds() {
    return Array.from(views.keys());
  }

  /* ---------------- tree helpers ---------------- */

  function leaf(tabs, active) {
    return { id: nextId("leaf"), type: "leaf", tabs: tabs.slice(),
             active: active || tabs[0] || null };
  }

  function split(dir, a, b, ratio) {
    return { id: nextId("split"), type: "split", dir, a, b,
             ratio: ratio == null ? 0.5 : ratio };
  }

  function walk(node, fn, parent) {
    if (!node) return;
    fn(node, parent);
    if (node.type === "split") { walk(node.a, fn, node); walk(node.b, fn, node); }
  }

  function findLeaf(id) {
    let hit = null;
    walk(state.root, (n) => { if (n.id === id) hit = n; });
    return hit;
  }

  function leaves() {
    const out = [];
    walk(state.root, (n) => { if (n.type === "leaf") out.push(n); });
    return out;
  }

  function leafOfView(viewId) {
    return leaves().find((l) => l.tabs.includes(viewId)) || null;
  }

  function parentOf(id) {
    let hit = null;
    walk(state.root, (n, p) => { if (n.id === id) hit = p; });
    return hit;
  }

  /* ---------------- mutations ---------------- */

  function openView(viewId, opts) {
    if (!views.has(viewId)) return;
    const existing = leafOfView(viewId);
    if (existing) {
      existing.active = viewId;
      state.focus = existing.id;
      if (state.maximized && state.maximized !== existing.id) {
        state.maximized = null;
      }
      render();
      return;
    }
    const target = (opts && opts.leafId && findLeaf(opts.leafId))
      || findLeaf(state.focus) || leaves()[0];
    if (!target) {
      state.root = leaf([viewId]);
    } else {
      target.tabs.push(viewId);
      target.active = viewId;
      state.focus = target.id;
    }
    render();
  }

  function closeView(viewId) {
    const l = leafOfView(viewId);
    if (!l) return;
    const i = l.tabs.indexOf(viewId);
    l.tabs.splice(i, 1);
    if (l.active === viewId) l.active = l.tabs[Math.max(0, i - 1)] || null;
    if (!l.tabs.length) removeLeaf(l.id);
    render();
  }

  function removeLeaf(id) {
    if (state.maximized === id) state.maximized = null;
    const parent = parentOf(id);
    if (!parent) {                       // the last leaf: keep an empty one
      state.root = leaf([]);
      state.focus = state.root.id;
      return;
    }
    const keep = parent.a.id === id ? parent.b : parent.a;
    const grand = parentOf(parent.id);
    if (!grand) state.root = keep;
    else if (grand.a.id === parent.id) grand.a = keep;
    else grand.b = keep;
    if (state.focus === id) state.focus = leaves()[0] ? leaves()[0].id : null;
  }

  /** Split the leaf holding `viewId` (or the focused leaf) in two. */
  function splitPane(dir, viewId) {
    const l = viewId ? leafOfView(viewId) : findLeaf(state.focus);
    if (!l) return;
    const moving = viewId || l.active;
    let newLeaf;
    if (l.tabs.length > 1 && moving) {
      l.tabs = l.tabs.filter((t) => t !== moving);
      if (l.active === moving) l.active = l.tabs[0];
      newLeaf = leaf([moving]);
    } else {
      newLeaf = leaf([]);
    }
    const replacement = split(dir, l, newLeaf, 0.5);
    const parent = parentOf(l.id);
    if (!parent) state.root = replacement;
    else if (parent.a.id === l.id) parent.a = replacement;
    else parent.b = replacement;
    state.focus = newLeaf.id;
    render();
  }

  function moveView(viewId, targetLeafId, dir) {
    const from = leafOfView(viewId);
    const target = findLeaf(targetLeafId);
    if (!from || !target) return;
    if (from.id === target.id && !dir) return;
    from.tabs = from.tabs.filter((t) => t !== viewId);
    if (from.active === viewId) from.active = from.tabs[0] || null;

    if (dir) {
      const fresh = leaf([viewId]);
      const replacement = dir === "left" || dir === "up"
        ? split(dir === "left" ? "row" : "col", fresh, target, 0.5)
        : split(dir === "right" ? "row" : "col", target, fresh, 0.5);
      const parent = parentOf(target.id);
      if (!parent) state.root = replacement;
      else if (parent.a.id === target.id) parent.a = replacement;
      else parent.b = replacement;
      state.focus = fresh.id;
    } else {
      target.tabs.push(viewId);
      target.active = viewId;
      state.focus = target.id;
    }
    if (!from.tabs.length && from.id !== target.id) removeLeaf(from.id);
    render();
  }

  function toggleMaximize(leafId) {
    const id = leafId || state.focus;
    state.maximized = state.maximized === id ? null : id;
    render();
  }

  /* ---------------- rendering ---------------- */

  let host = null;
  let vault = null;

  function render() {
    if (!host) return;
    // Detach view elements before rebuilding so they survive re-parenting,
    // then park every element that did not land in a pane back in the vault.
    // The invariant the rest of the app relies on is that a view element is
    // always *somewhere* in the document: code elsewhere looks views up with
    // querySelector, and a hidden tab must still be findable.
    views.forEach((v) => {
      if (v.element.parentNode) v.element.parentNode.removeChild(v.element);
    });
    host.innerHTML = "";
    const tree = state.maximized ? findLeaf(state.maximized) : state.root;
    host.appendChild(renderNode(tree || leaf([])));
    if (vault) {
      views.forEach((v) => {
        if (!v.element.parentNode) vault.appendChild(v.element);
      });
    }
    persist();
    notify();
    // let views react to becoming visible
    leaves().forEach((l) => {
      const v = views.get(l.active);
      if (v && v.onShow && isVisible(l)) v.onShow();
    });
  }

  /** Tell the host the geometry changed, so canvases can resize themselves. */
  function notify() {
    if (state.onChange) state.onChange();
  }

  function isVisible(l) {
    return !state.maximized || state.maximized === l.id;
  }

  function renderNode(node) {
    if (node.type === "leaf") return renderLeaf(node);
    const box = document.createElement("div");
    box.className = "pane-split " + node.dir;
    const a = renderNode(node.a);
    const b = renderNode(node.b);
    const pct = Math.max(0.08, Math.min(0.92, node.ratio)) * 100;
    a.style.flex = `0 0 calc(${pct}% - ${SASH / 2}px)`;
    b.style.flex = "1 1 0";
    const handle = document.createElement("div");
    handle.className = "pane-sash " + node.dir;
    handle.tabIndex = 0;
    handle.title = "Drag to resize · double-click to even out";
    wireSash(handle, node, box, a);
    box.appendChild(a);
    box.appendChild(handle);
    box.appendChild(b);
    return box;
  }

  function badgeEl(v) {
    const b = document.createElement("span");
    b.className = "pane-tab-badge";
    b.dataset.tone = v.badgeTone || "";
    b.textContent = v.badge;
    return b;
  }

  /**
   * Show a small count/label on a view's tab. Falsy or "0" clears it, so
   * callers can pass a raw count. Updates in place when the tab is already
   * rendered, so a badge change never disturbs focus or scroll position.
   */
  function setBadge(id, text, tone) {
    const v = views.get(id);
    if (!v) return;
    const val = text == null || text === "" || text === 0 || text === "0"
      ? "" : String(text);
    if (v.badge === val && v.badgeTone === (tone || "")) return;
    v.badge = val;
    v.badgeTone = tone || "";
    if (!host) return;
    const tab = Array.from(host.querySelectorAll(".pane-tab"))
      .find((t) => t.dataset.view === id);
    if (!tab) return;
    const existing = tab.querySelector(".pane-tab-badge");
    if (!val) { if (existing) existing.remove(); return; }
    if (existing) {
      existing.textContent = val;
      existing.dataset.tone = v.badgeTone;
      return;
    }
    tab.insertBefore(badgeEl(v), tab.querySelector(".pane-tab-close"));
  }

  function renderLeaf(node) {
    const pane = document.createElement("div");
    pane.className = "pane" + (state.focus === node.id ? " focused" : "");
    pane.dataset.leaf = node.id;
    pane.addEventListener("mousedown", () => {
      if (state.focus !== node.id) { state.focus = node.id; render(); }
    });

    const bar = document.createElement("div");
    bar.className = "pane-tabs";

    // the tabs scroll; the pane's own controls stay put, so a narrow pane
    // never hides the split and maximise buttons behind its tab list
    const strip = document.createElement("div");
    strip.className = "pane-tabs-strip";

    node.tabs.forEach((viewId) => {
      const v = views.get(viewId);
      if (!v) return;
      const tab = document.createElement("div");
      tab.className = "pane-tab" + (node.active === viewId ? " active" : "");
      tab.draggable = true;
      tab.dataset.view = viewId;
      if (v.icon) {
        const ic = document.createElement("span");
        ic.className = "pane-tab-icon";
        ic.textContent = v.icon;
        tab.appendChild(ic);
      }
      tab.appendChild(document.createTextNode(v.title));
      if (v.badge) tab.appendChild(badgeEl(v));
      if (v.closable) {
        const x = document.createElement("span");
        x.className = "pane-tab-close";
        x.textContent = "×";
        x.title = "Close";
        x.onclick = (e) => { e.stopPropagation(); closeView(viewId); };
        tab.appendChild(x);
      }
      tab.onclick = () => {
        node.active = viewId;
        state.focus = node.id;
        render();
      };
      tab.addEventListener("dragstart", (e) => {
        e.dataTransfer.setData("text/epsilon-view", viewId);
        e.dataTransfer.effectAllowed = "move";
      });
      strip.appendChild(tab);
    });

    const spacer = document.createElement("div");
    spacer.className = "pane-tabs-spacer";
    strip.appendChild(spacer);
    bar.appendChild(strip);

    bar.appendChild(paneButton("◫", "Split right", () => splitPane("row", node.active)));
    bar.appendChild(paneButton("⊟", "Split down", () => splitPane("col", node.active)));
    bar.appendChild(paneButton(state.maximized === node.id ? "❐" : "⛶",
                               "Maximize / restore", () => toggleMaximize(node.id)));

    const body = document.createElement("div");
    body.className = "pane-body";
    const v = views.get(node.active);
    if (v) body.appendChild(v.element);
    else {
      const empty = document.createElement("div");
      empty.className = "pane-empty";
      empty.textContent = "Empty pane — open a view from the sidebar or the command palette.";
      body.appendChild(empty);
    }
    wireDrop(body, node);

    pane.appendChild(bar);
    pane.appendChild(body);
    return pane;
  }

  function paneButton(glyph, title, fn) {
    const b = document.createElement("button");
    b.className = "pane-btn";
    b.textContent = glyph;
    b.title = title;
    b.onclick = (e) => { e.stopPropagation(); fn(); };
    return b;
  }

  /* ---------------- interaction ---------------- */

  /**
   * Dragging a sash resizes the two panes it sits between.
   *
   * The one thing a drag must not do is re-render: `render()` rebuilds the
   * whole tree, which detaches the very `box` this closure measures against.
   * A detached element reports a zero-sized rect, so the ratio divides by
   * zero and the split jumps to its limit and stops following the mouse.
   * The drag therefore writes the two panes' flex directly and leaves the
   * tree alone; one notify on release lets canvases resize themselves.
   *
   * Moves are coalesced into an animation frame, so a mouse reporting at
   * 1000 Hz still costs one layout per painted frame.
   */
  function wireSash(handle, node, box, a) {
    let rect = null;
    let pending = null;
    let frame = 0;

    const ratioAt = (e) => {
      const along = node.dir === "row"
        ? (e.clientX - rect.left) / rect.width
        : (e.clientY - rect.top) / rect.height;
      const span = node.dir === "row" ? rect.width : rect.height;
      const minR = span > 0 ? Math.min(0.45, MIN_PANE / span) : 0.08;
      return Math.max(minR, Math.min(1 - minR, along));
    };

    const paint = () => {
      frame = 0;
      if (pending == null) return;
      node.ratio = pending;
      pending = null;
      a.style.flex = `0 0 calc(${node.ratio * 100}% - ${SASH / 2}px)`;
    };

    const onMove = (e) => {
      if (!rect) return;
      pending = ratioAt(e);
      if (!frame) frame = requestAnimationFrame(paint);
    };

    const onUp = (e) => {
      if (!rect) return;
      rect = null;
      if (frame) { cancelAnimationFrame(frame); frame = 0; }
      paint();
      document.body.classList.remove("resizing");
      handle.classList.remove("dragging");
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
      if (e && handle.releasePointerCapture && e.pointerId != null) {
        try { handle.releasePointerCapture(e.pointerId); } catch (err) { /* gone */ }
      }
      persist();
      notify();
    };

    handle.addEventListener("pointerdown", (e) => {
      if (e.button != null && e.button !== 0) return;
      e.preventDefault();
      // measured once: the container does not move while its children resize
      rect = box.getBoundingClientRect();
      if (!rect.width || !rect.height) { rect = null; return; }
      document.body.classList.add("resizing");
      handle.classList.add("dragging");
      if (handle.setPointerCapture && e.pointerId != null) {
        try { handle.setPointerCapture(e.pointerId); } catch (err) { /* fine */ }
      }
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
    });

    handle.addEventListener("dblclick", () => {
      node.ratio = 0.5;
      render();
    });

    handle.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 0.1 : 0.03;
      if (e.key === "ArrowLeft" || e.key === "ArrowUp") node.ratio -= step;
      else if (e.key === "ArrowRight" || e.key === "ArrowDown") node.ratio += step;
      else return;
      e.preventDefault();
      node.ratio = Math.max(0.08, Math.min(0.92, node.ratio));
      render();
    });
  }


  function wireDrop(body, node) {
    let zone = null;
    const marker = document.createElement("div");
    marker.className = "pane-drop hidden";
    body.appendChild(marker);

    body.addEventListener("dragover", (e) => {
      if (!e.dataTransfer.types.includes("text/epsilon-view")) return;
      e.preventDefault();
      const r = body.getBoundingClientRect();
      const fx = (e.clientX - r.left) / r.width;
      const fy = (e.clientY - r.top) / r.height;
      zone = fx < 0.22 ? "left" : fx > 0.78 ? "right"
           : fy < 0.22 ? "up" : fy > 0.78 ? "down" : null;
      marker.className = "pane-drop " + (zone || "center");
    });
    body.addEventListener("dragleave", () => {
      marker.className = "pane-drop hidden";
      zone = null;
    });
    body.addEventListener("drop", (e) => {
      const viewId = e.dataTransfer.getData("text/epsilon-view");
      marker.className = "pane-drop hidden";
      if (!viewId) return;
      e.preventDefault();
      moveView(viewId, node.id, zone);
      zone = null;
    });
  }

  /* ---------------- persistence ---------------- */

  function serialize(node) {
    if (!node) return null;
    if (node.type === "leaf") {
      return { type: "leaf", tabs: node.tabs.slice(), active: node.active };
    }
    return { type: "split", dir: node.dir, ratio: node.ratio,
             a: serialize(node.a), b: serialize(node.b) };
  }

  function deserialize(raw) {
    if (!raw) return null;
    if (raw.type === "leaf") {
      const tabs = (raw.tabs || []).filter((t) => views.has(t));
      return leaf(tabs, views.has(raw.active) ? raw.active : tabs[0]);
    }
    const a = deserialize(raw.a), b = deserialize(raw.b);
    if (!a) return b;
    if (!b) return a;
    return split(raw.dir === "col" ? "col" : "row", a, b, raw.ratio);
  }

  /**
   * Drop tabs naming views that are not registered and collapse the leaves
   * that end up empty. Keeps a stale saved layout, or a profile that names a
   * not-yet-built view, from materialising a blank pane.
   */
  function normalize(node) {
    if (!node) return null;
    if (node.type === "leaf") {
      node.tabs = node.tabs.filter((t) => views.has(t));
      if (!node.tabs.length) return null;
      if (!views.has(node.active)) node.active = node.tabs[0];
      return node;
    }
    const a = normalize(node.a), b = normalize(node.b);
    if (!a) return b;
    if (!b) return a;
    node.a = a;
    node.b = b;
    return node;
  }

  function persist() {
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify({
        root: serialize(state.root), maximized: state.maximized,
      }));
    } catch (e) { /* private mode: layout simply is not remembered */ }
  }

  function restore() {
    try {
      const raw = JSON.parse(localStorage.getItem(LAYOUT_KEY));
      if (!raw || !raw.root) return false;
      const tree = normalize(deserialize(raw.root));
      if (!tree) return false;
      state.root = tree;
      state.maximized = findLeaf(raw.maximized) ? raw.maximized : null;
      state.focus = leaves()[0] ? leaves()[0].id : null;
      return true;
    } catch (e) { return false; }
  }

  /* ---------------- profiles ---------------- */

  const PROFILES = {
    mathematics: () => split("row",
      leaf(["editor"]),
      split("col", leaf(["proof", "plot", "inspector"]),
                   leaf(["problems", "console"]), 0.55),
      0.58),
    algorithm: () => split("col",
      split("row", leaf(["editor"]), leaf(["notes"]), 0.6),
      leaf(["console", "problems"]), 0.66),
    research: () => split("row",
      leaf(["editor"]),
      split("col", leaf(["deps"]), leaf(["inspector", "proof"]), 0.6), 0.5),
    minimal: () => split("col", leaf(["editor"]), leaf(["console", "problems"]), 0.74),
  };

  function applyProfile(name) {
    const make = PROFILES[name] || PROFILES.mathematics;
    state.root = normalize(make()) || leaf(viewIds().slice(0, 1));
    state.maximized = null;
    state.focus = leaves()[0] ? leaves()[0].id : null;
    render();
  }

  function profileNames() {
    return Object.keys(PROFILES);
  }

  /* ---------------- public API ---------------- */

  function init(opts) {
    host = typeof opts.host === "string"
      ? document.querySelector(opts.host) : opts.host;
    vault = typeof opts.vault === "string"
      ? document.querySelector(opts.vault) : (opts.vault || null);
    state.onChange = opts.onChange || null;
    (opts.views || []).forEach((v) => registerView(v.id, v));
    if (!restore()) applyProfile(opts.profile || "mathematics");
    else render();
    return api;
  }

  const api = {
    init, registerView, setBadge, openView, closeView, splitPane, toggleMaximize,
    moveView, applyProfile, profileNames, viewIds, render,
    isOpen: (id) => !!leafOfView(id),
    focusView: (id) => openView(id),
    reset: () => applyProfile("mathematics"),
    layout: () => serialize(state.root),
  };

  global.EpsilonPanes = api;
})(window);
