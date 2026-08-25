/* ===================================================================
 * Epsilon — the symbol dependency graph.
 *
 * A picture of what refers to what inside a file: functions, classes,
 * variables and imports as nodes, "mentions" as edges. The layout is a
 * small force simulation — repulsion between every pair, springs along
 * edges, a weak pull to the centre — run for a fixed number of steps and
 * then left alone. It settles rather than animating forever, because a
 * graph that never stops moving is a graph you cannot read.
 *
 * Rendering is plain SVG built once per layout. Interaction (hover,
 * drag, select) only touches classes and transforms, so following an
 * edge with the pointer never re-runs the simulation.
 *
 * The module knows nothing about the workbench: it takes a container, a
 * {nodes, edges} payload and a couple of callbacks, and gives back a
 * handle. That is what lets the same renderer serve a panel, a tab, or
 * a future cross-file view.
 * =================================================================== */
(function (root) {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";

  const KIND_ORDER = ["module", "class", "function", "variable", "import"];
  const KIND_LABEL = {
    module: "module body", class: "class", function: "function",
    variable: "variable", import: "import",
  };

  function svgEl(name, attrs) {
    const node = document.createElementNS(NS, name);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  /**
   * Lay the graph out.
   *
   * Deterministic on purpose: the same file gives the same picture every
   * time it is opened, which matters more here than the prettiest
   * possible arrangement. Seeded by index rather than Math.random.
   */
  function layout(nodes, edges, width, height, steps) {
    const n = nodes.length;
    if (!n) return;
    const cx = width / 2, cy = height / 2;
    const radius = Math.min(width, height) * 0.36;
    nodes.forEach((node, i) => {
      const angle = (i / n) * Math.PI * 2;
      // a slight spiral keeps equal-degree nodes from starting on top
      const r = radius * (0.55 + 0.45 * ((i * 7) % n) / Math.max(1, n));
      node.x = cx + Math.cos(angle) * r;
      node.y = cy + Math.sin(angle) * r;
      node.vx = 0;
      node.vy = 0;
    });

    const index = new Map(nodes.map((node) => [node.id, node]));
    const links = edges
      .map((e) => ({ a: index.get(e.from), b: index.get(e.to) }))
      .filter((l) => l.a && l.b);

    const REPEL = 5200;
    const SPRING = 0.012;
    const REST = 108;
    const CENTRE = 0.006;
    const DAMP = 0.86;

    for (let step = 0; step < (steps || 260); step++) {
      for (let i = 0; i < n; i++) {
        const a = nodes[i];
        for (let j = i + 1; j < n; j++) {
          const b = nodes[j];
          let dx = a.x - b.x, dy = a.y - b.y;
          let d2 = dx * dx + dy * dy;
          if (d2 < 1) { dx = (i - j) || 1; dy = 1; d2 = 2; }
          const f = REPEL / d2;
          const d = Math.sqrt(d2);
          a.vx += (dx / d) * f; a.vy += (dy / d) * f;
          b.vx -= (dx / d) * f; b.vy -= (dy / d) * f;
        }
      }
      for (const l of links) {
        const dx = l.b.x - l.a.x, dy = l.b.y - l.a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const f = (d - REST) * SPRING;
        l.a.vx += (dx / d) * f; l.a.vy += (dy / d) * f;
        l.b.vx -= (dx / d) * f; l.b.vy -= (dy / d) * f;
      }
      for (const node of nodes) {
        if (node.pinned) { node.vx = node.vy = 0; continue; }
        node.vx += (cx - node.x) * CENTRE;
        node.vy += (cy - node.y) * CENTRE;
        node.vx *= DAMP; node.vy *= DAMP;
        node.x += node.vx; node.y += node.vy;
        node.x = Math.max(46, Math.min(width - 46, node.x));
        node.y = Math.max(30, Math.min(height - 30, node.y));
      }
    }
  }

  function radiusOf(node) {
    return 8 + Math.min(9, (node.refs || 0) * 1.7);
  }

  /**
   * Draw `data` into `host`.
   *
   * opts.onSelect(node)  a node was chosen (click) — used to jump to it
   * opts.filter          Set of kinds to show, or null for everything
   */
  function render(host, data, opts) {
    const options = opts || {};
    host.innerHTML = "";
    const nodes = (data.nodes || []).filter(
      (node) => !options.filter || options.filter.has(node.kind));
    const keep = new Set(nodes.map((node) => node.id));
    const edges = (data.edges || []).filter(
      (e) => keep.has(e.from) && keep.has(e.to));

    if (!nodes.length) {
      const empty = document.createElement("div");
      empty.className = "wb-empty";
      empty.textContent = data.message
        || "Nothing to graph — this file defines no symbols yet.";
      host.appendChild(empty);
      return { destroy() { host.innerHTML = ""; } };
    }

    const rect = host.getBoundingClientRect();
    const width = Math.max(360, rect.width || 900);
    const height = Math.max(280, rect.height || 560);
    layout(nodes, edges, width, height, options.steps);

    const svg = svgEl("svg", {
      class: "gr-svg", viewBox: `0 0 ${width} ${height}`,
      preserveAspectRatio: "xMidYMid meet",
    });
    const scene = svgEl("g", { class: "gr-scene" });
    svg.appendChild(scene);

    const defs = svgEl("defs");
    const marker = svgEl("marker", {
      id: "gr-arrow", viewBox: "0 0 10 10", refX: "9", refY: "5",
      markerWidth: "5", markerHeight: "5", orient: "auto-start-reverse",
    });
    marker.appendChild(svgEl("path", { d: "M0 0 L10 5 L0 10 z",
                                       class: "gr-arrowhead" }));
    defs.appendChild(marker);
    svg.appendChild(defs);

    const index = new Map(nodes.map((node) => [node.id, node]));
    const edgeEls = [];
    const edgeLayer = svgEl("g", { class: "gr-edges" });
    edges.forEach((e) => {
      const a = index.get(e.from), b = index.get(e.to);
      const line = svgEl("line", {
        class: "gr-edge kind-" + (e.kind || "uses"),
        "marker-end": "url(#gr-arrow)",
      });
      edgeLayer.appendChild(line);
      edgeEls.push({ el: line, a, b, from: e.from, to: e.to });
    });
    scene.appendChild(edgeLayer);

    const nodeEls = new Map();
    const nodeLayer = svgEl("g", { class: "gr-nodes" });
    nodes.forEach((node) => {
      const g = svgEl("g", { class: "gr-node kind-" + node.kind,
                             tabindex: "0", role: "button" });
      const circle = svgEl("circle", { r: radiusOf(node), class: "gr-dot" });
      const label = svgEl("text", { class: "gr-label", y: radiusOf(node) + 15 });
      label.textContent = node.name;
      const title = svgEl("title");
      title.textContent = `${node.name}${node.detail || ""}\n` +
        `${KIND_LABEL[node.kind] || node.kind} · line ${node.line} · ` +
        `${node.refs || 0} reference${node.refs === 1 ? "" : "s"}`;
      g.appendChild(circle);
      g.appendChild(label);
      g.appendChild(title);
      nodeLayer.appendChild(g);
      nodeEls.set(node.id, { g, node });
    });
    scene.appendChild(nodeLayer);
    host.appendChild(svg);

    function place() {
      edgeEls.forEach((e) => {
        // stop the line short of the target so the arrowhead is visible
        const dx = e.b.x - e.a.x, dy = e.b.y - e.a.y;
        const d = Math.sqrt(dx * dx + dy * dy) || 1;
        const r = radiusOf(e.b) + 5;
        e.el.setAttribute("x1", e.a.x.toFixed(1));
        e.el.setAttribute("y1", e.a.y.toFixed(1));
        e.el.setAttribute("x2", (e.b.x - (dx / d) * r).toFixed(1));
        e.el.setAttribute("y2", (e.b.y - (dy / d) * r).toFixed(1));
      });
      nodeEls.forEach(({ g, node }) => {
        g.setAttribute("transform",
          `translate(${node.x.toFixed(1)},${node.y.toFixed(1)})`);
      });
    }
    place();

    /* ---- neighbourhood highlighting ---- */
    function focus(id) {
      const near = new Set(id ? [id] : []);
      if (id) {
        edges.forEach((e) => {
          if (e.from === id) near.add(e.to);
          if (e.to === id) near.add(e.from);
        });
      }
      svg.classList.toggle("gr-focused", !!id);
      nodeEls.forEach(({ g }, nid) => g.classList.toggle("near", near.has(nid)));
      edgeEls.forEach((e) => e.el.classList.toggle("near",
        !!id && (e.from === id || e.to === id)));
    }

    nodeEls.forEach(({ g, node }) => {
      g.addEventListener("mouseenter", () => focus(node.id));
      g.addEventListener("mouseleave", () => focus(null));
      g.addEventListener("focus", () => focus(node.id));
      g.addEventListener("blur", () => focus(null));
      const choose = () => options.onSelect && options.onSelect(node);
      g.addEventListener("click", choose);
      g.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); choose(); }
      });
      // dragging a node lets a reader untangle a knot by hand
      g.addEventListener("pointerdown", (ev) => {
        if (ev.button) return;
        ev.preventDefault();
        g.setPointerCapture(ev.pointerId);
        const box = svg.getBoundingClientRect();
        const sx = width / box.width, sy = height / box.height;
        let moved = false;
        const move = (e) => {
          moved = true;
          node.x = (e.clientX - box.left) * sx;
          node.y = (e.clientY - box.top) * sy;
          node.pinned = true;
          place();
        };
        const up = () => {
          g.removeEventListener("pointermove", move);
          g.removeEventListener("pointerup", up);
          if (moved) g.classList.add("pinned");
        };
        g.addEventListener("pointermove", move);
        g.addEventListener("pointerup", up);
      });
    });

    return {
      focus,
      counts: nodes.reduce((acc, node) => {
        acc[node.kind] = (acc[node.kind] || 0) + 1;
        return acc;
      }, {}),
      destroy() { host.innerHTML = ""; },
    };
  }

  root.EpsilonGraph = { render, layout, KIND_ORDER, KIND_LABEL };
})(typeof window !== "undefined" ? window : globalThis);
