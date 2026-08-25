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

  //: panes.js stays standalone (it is node-tested without a DOM), so it
  //: carries the handful of glyphs it draws rather than importing a set
  const GLYPH = {
    close: '<path d="M6.8 6.8l10.4 10.4M17.2 6.8L6.8 17.2"/>',
    dot: '<circle cx="12" cy="12" r="4" fill="currentColor" stroke="none"/>',
    pin: '<path d="M9 3.8h6l-.8 5.1 3 3.1H6.8l3-3.1L9 3.8Z"/><path d="M12 12v8.2"/>',
    splitRight: '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.4"/><path d="M12 4.6v14.8"/>',
    splitDown: '<rect x="3.6" y="4.6" width="16.8" height="14.8" rx="2.4"/><path d="M3.6 12h16.8"/>',
    maximize: '<path d="M9.4 4.6H6A1.4 1.4 0 0 0 4.6 6v3.4M14.6 4.6H18A1.4 1.4 0 0 1 19.4 6v3.4M9.4 19.4H6A1.4 1.4 0 0 1 4.6 18v-3.4M14.6 19.4H18a1.4 1.4 0 0 0 1.4-1.4v-3.4"/>',
    restore: '<rect x="4.6" y="4.6" width="14.8" height="14.8" rx="2.2"/><path d="M8.6 8.6h6.8v6.8"/>',
  };

  function glyph(name, size) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("width", String(size || 14));
    svg.setAttribute("height", String(size || 14));
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.7");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = GLYPH[name] || "";
    return svg;
  }

  /** Registered views: id -> {title, icon, element, onShow} */
  const views = new Map();

  /** Pinned tabs survive Close Others / Close to the Right. */
  const pinned = new Set();

  const state = {
    root: null,          // layout tree
    maximized: null,     // leaf id, or null
    focus: null,         // leaf id
    onChange: null,
    onTabContext: null,  // (viewId, x, y) -> show a context menu
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
      onClose: spec.onClose || null,
      closable: spec.closable !== false,
      badge: "",
      badgeTone: "",
      dirty: false,
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
    pinned.delete(viewId);
    render();
    const v = views.get(viewId);
    if (v && v.onClose) v.onClose();
  }

  /** Close every unpinned tab in `viewId`'s group except `viewId` itself. */
  function closeOthers(viewId) {
    const l = leafOfView(viewId);
    if (!l) return;
    l.tabs.slice()
      .filter((t) => t !== viewId && !pinned.has(t))
      .forEach(closeView);
  }

  /** Close the unpinned tabs after `viewId` in its group. */
  function closeToTheRight(viewId) {
    const l = leafOfView(viewId);
    if (!l) return;
    const i = l.tabs.indexOf(viewId);
    l.tabs.slice(i + 1).filter((t) => !pinned.has(t)).forEach(closeView);
  }

  /** Collapse every split into a single tab group, keeping tab order. */
  function joinAll() {
    const all = [];
    leaves().forEach((l) => l.tabs.forEach((t) => all.push(t)));
    if (!all.length) return;
    const active = activeView() || all[0];
    state.root = leaf(all, active);
    state.maximized = null;
    state.focus = state.root.id;
    render();
  }

  /** The view showing in the focused leaf (falls back to any leaf). */
  function activeView() {
    const l = findLeaf(state.focus) || leaves()[0];
    return l ? l.active : null;
  }

  function isPinned(viewId) { return pinned.has(viewId); }

  function togglePin(viewId) {
    if (pinned.has(viewId)) pinned.delete(viewId);
    else {
      pinned.add(viewId);
      // pinned tabs gather at the front of their group
      const l = leafOfView(viewId);
      if (l) {
        l.tabs = l.tabs.filter((t) => t !== viewId);
        const firstUnpinned = l.tabs.findIndex((t) => !pinned.has(t));
        l.tabs.splice(firstUnpinned < 0 ? l.tabs.length : firstUnpinned,
                      0, viewId);
      }
    }
    render();
  }

  /** Rename a view in place: registry key, layout tabs, and tab title. */
  function renameView(oldId, newId, newTitle) {
    const v = views.get(oldId);
    if (!v || views.has(newId)) return;
    views.delete(oldId);
    v.id = newId;
    if (newTitle) v.title = newTitle;
    views.set(newId, v);
    walk(state.root, (n) => {
      if (n.type !== "leaf") return;
      n.tabs = n.tabs.map((t) => (t === oldId ? newId : t));
      if (n.active === oldId) n.active = newId;
    });
    if (pinned.has(oldId)) { pinned.delete(oldId); pinned.add(newId); }
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

  /**
   * Mark a view's tab as having unsaved changes. The close box becomes the
   * familiar dot (and turns back into × under the pointer, via CSS), so the
   * signal costs no extra space. Updates in place — a keystroke that flips
   * dirtiness must not rebuild the workspace.
   */
  function setDirty(id, dirty) {
    const v = views.get(id);
    if (!v || v.dirty === !!dirty) return;
    v.dirty = !!dirty;
    if (!host) return;
    const tab = Array.from(host.querySelectorAll(".pane-tab"))
      .find((t) => t.dataset.view === id);
    if (!tab) return;
    tab.classList.toggle("dirty", v.dirty);
    const x = tab.querySelector(".pane-tab-close");
    if (x) {
      x.innerHTML = "";
      x.appendChild(glyph(v.dirty ? "dot" : "close", 13));
    }
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
      tab.className = "pane-tab" + (node.active === viewId ? " active" : "")
        + (v.dirty ? " dirty" : "") + (pinned.has(viewId) ? " pinned" : "");
      tab.draggable = true;
      tab.dataset.view = viewId;
      if (pinned.has(viewId)) {
        const pin = document.createElement("span");
        pin.className = "pane-tab-pin";
        pin.appendChild(glyph("pin", 12));
        pin.title = "Pinned — right-click to unpin";
        tab.appendChild(pin);
      } else if (v.icon) {
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
        x.appendChild(glyph(v.dirty ? "dot" : "close", 13));
        x.title = "Close";
        x.onclick = (e) => { e.stopPropagation(); closeView(viewId); };
        tab.appendChild(x);
      }
      tab.onclick = () => {
        node.active = viewId;
        state.focus = node.id;
        render();
      };
      // middle click closes, like every tabbed application since forever
      tab.addEventListener("auxclick", (e) => {
        if (e.button === 1 && v.closable) {
          e.preventDefault();
          closeView(viewId);
        }
      });
      tab.addEventListener("contextmenu", (e) => {
        if (!state.onTabContext) return;
        e.preventDefault();
        state.onTabContext(viewId, e.clientX, e.clientY);
      });
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

    bar.appendChild(paneButton("splitRight", "Split right",
                               () => splitPane("row", node.active)));
    bar.appendChild(paneButton("splitDown", "Split down",
                               () => splitPane("col", node.active)));
    bar.appendChild(paneButton(
      state.maximized === node.id ? "restore" : "maximize",
      "Maximize / restore", () => toggleMaximize(node.id)));

    const body = document.createElement("div");
    body.className = "pane-body";
    const v = views.get(node.active);
    if (v) body.appendChild(v.element);
    else {
      const empty = document.createElement("div");
      empty.className = "pane-empty";
      empty.textContent = "Open a file from the Explorer, or press Ctrl+P to jump to one.";
      body.appendChild(empty);
    }
    wireDrop(body, node);

    pane.appendChild(bar);
    pane.appendChild(body);
    return pane;
  }

  function paneButton(name, title, fn) {
    const b = document.createElement("button");
    b.className = "pane-btn";
    b.appendChild(glyph(name, 14));
    b.title = title;
    b.setAttribute("aria-label", title);
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
      // a group the user deliberately left empty is part of their layout;
      // one whose every view has gone missing is not
      const wasEmpty = !node.tabs.length;
      node.tabs = node.tabs.filter((t) => views.has(t));
      if (!node.tabs.length) return wasEmpty ? node : null;
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
        pinned: Array.from(pinned),
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
      pinned.clear();
      (raw.pinned || []).filter((id) => views.has(id)).forEach((id) =>
        pinned.add(id));
      return true;
    } catch (e) { return false; }
  }

  /**
   * Re-apply the saved layout after views have been registered. The boot
   * sequence needs this: `restore()` at init time drops tabs for views
   * that do not exist yet, so the app registers its views first (opening
   * files), then asks for the saved arrangement back.
   */
  function restoreLayout() {
    if (!restore()) return false;
    render();
    return true;
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
    //: the IDE workbench starts with one empty group; files fill it in
    empty: () => leaf([]),
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
    state.onTabContext = opts.onTabContext || null;
    (opts.views || []).forEach((v) => registerView(v.id, v));
    if (!restore()) applyProfile(opts.profile || "mathematics");
    else render();
    return api;
  }

  const api = {
    init, registerView, setBadge, setDirty, openView, closeView, closeOthers,
    closeToTheRight, joinAll, activeView, isPinned, togglePin, renameView,
    splitPane, toggleMaximize, restoreLayout,
    moveView, applyProfile, profileNames, viewIds, render,
    isOpen: (id) => !!leafOfView(id),
    focusView: (id) => openView(id),
    reset: () => applyProfile("mathematics"),
    layout: () => serialize(state.root),
  };

  global.EpsilonPanes = api;
})(window);
