/* ===================================================================
 * Epsilon — workbench core.
 *
 * The registries every surface of the IDE speaks through. A command is
 * registered once, here, and from that single registration the palette,
 * the menu bar, the keyboard, the buttons and the context menus all get
 * their behaviour, their label, their keybinding and their enablement —
 * one command never needs per-surface implementations, and a disabled
 * command can always say why it is disabled.
 *
 * DOM-free on purpose (rendering lives in the workbench): the logic here
 * runs under node for tests exactly as it runs in the page.
 * =================================================================== */
(function (root) {
  "use strict";

  const storage = (() => {
    try {
      if (typeof localStorage !== "undefined") return localStorage;
    } catch (e) { /* node, or storage blocked */ }
    const mem = {};
    return { getItem: (k) => (k in mem ? mem[k] : null),
             setItem: (k, v) => { mem[k] = String(v); },
             removeItem: (k) => { delete mem[k]; } };
  })();

  function readJSON(key, fallback) {
    try {
      const raw = storage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (e) { return fallback; }
  }
  function writeJSON(key, value) {
    try { storage.setItem(key, JSON.stringify(value)); } catch (e) {}
  }

  const isMac = typeof navigator !== "undefined" &&
    /Mac/.test(navigator.platform || "");

  /* =================================================================
   * Settings
   * ================================================================= */
  const Settings = (() => {
    const KEY = "epsilon.settings.v1";
    const schema = new Map();          // id -> descriptor
    let overrides = readJSON(KEY, {});
    const listeners = new Map();       // id|"*" -> Set<fn>

    function register(desc) {
      schema.set(desc.id, desc);
      return desc.id;
    }

    function get(id) {
      if (id in overrides) return overrides[id];
      const desc = schema.get(id);
      return desc ? desc.default : undefined;
    }

    function set(id, value) {
      const desc = schema.get(id);
      if (desc) {
        if (desc.type === "number") value = Number(value);
        if (desc.type === "boolean") value = !!value;
        if (desc.type === "enum" && desc.options &&
            !desc.options.includes(value)) return;
        if (desc.type === "number") {
          if (desc.min != null) value = Math.max(desc.min, value);
          if (desc.max != null) value = Math.min(desc.max, value);
          if (Number.isNaN(value)) return;
        }
      }
      if (get(id) === value) return;
      overrides[id] = value;
      writeJSON(KEY, overrides);
      fire(id, value);
    }

    function reset(id) {
      if (!(id in overrides)) return;
      delete overrides[id];
      writeJSON(KEY, overrides);
      fire(id, get(id));
    }

    function fire(id, value) {
      (listeners.get(id) || []).forEach((fn) => fn(value, id));
      (listeners.get("*") || []).forEach((fn) => fn(value, id));
    }

    function onChange(id, fn) {
      if (!listeners.has(id)) listeners.set(id, new Set());
      listeners.get(id).add(fn);
      return () => listeners.get(id).delete(fn);
    }

    function all() { return Array.from(schema.values()); }
    function isModified(id) { return id in overrides; }
    function categories() {
      const seen = [];
      schema.forEach((d) => {
        if (!seen.includes(d.category)) seen.push(d.category);
      });
      return seen;
    }

    return { register, get, set, reset, onChange, all, categories, isModified };
  })();

  /* =================================================================
   * Commands
   * ================================================================= */
  const Commands = (() => {
    const RECENT_KEY = "epsilon.commands.recent.v1";
    const commands = new Map();
    let recents = readJSON(RECENT_KEY, []);

    function register(desc) {
      if (!desc.id || typeof desc.run !== "function") {
        throw new Error("a command needs an id and a run()");
      }
      commands.set(desc.id, {
        id: desc.id,
        title: desc.title || desc.id,
        category: desc.category || "General",
        run: desc.run,
        // enabled unless whyDisabled() returns a reason — a disabled
        // command can always explain itself
        whyDisabled: desc.whyDisabled || (() => null),
        aliases: desc.aliases || [],
        description: desc.description || "",
        inPalette: desc.inPalette !== false,
      });
      return desc.id;
    }

    function get(id) { return commands.get(id); }
    function all() { return Array.from(commands.values()); }

    function enabled(id) {
      const c = commands.get(id);
      return c ? c.whyDisabled() == null : false;
    }
    function disabledReason(id) {
      const c = commands.get(id);
      return c ? c.whyDisabled() : "unknown command";
    }

    function execute(id, ...args) {
      const c = commands.get(id);
      if (!c) return { ok: false, reason: `unknown command: ${id}` };
      const reason = c.whyDisabled();
      if (reason) return { ok: false, reason };
      recents = [id, ...recents.filter((r) => r !== id)].slice(0, 30);
      writeJSON(RECENT_KEY, recents);
      const value = c.run(...args);
      return { ok: true, value };
    }

    function recentIds() { return recents.filter((id) => commands.has(id)); }

    return { register, get, all, execute, enabled, disabledReason, recentIds };
  })();

  /* =================================================================
   * Keybindings
   * ================================================================= */
  const Keys = (() => {
    const KEY = "epsilon.keybindings.v1";
    const defaults = new Map();        // commandId -> chord
    let user = readJSON(KEY, {});      // commandId -> chord | null (unbound)

    /** One canonical spelling per chord: "Ctrl+Shift+P", "F5", "Alt+ArrowUp".
        "Mod" in a registration means Ctrl everywhere and Cmd on a Mac. */
    function normalize(chord) {
      if (!chord) return null;
      const parts = String(chord).split("+").map((p) => p.trim());
      const key = parts.pop();
      const mods = new Set(parts.map((p) => {
        const low = p.toLowerCase();
        if (low === "mod") return isMac ? "Meta" : "Ctrl";
        if (low === "cmd" || low === "meta") return "Meta";
        if (low === "ctrl" || low === "control") return "Ctrl";
        if (low === "alt" || low === "option") return "Alt";
        if (low === "shift") return "Shift";
        return p;
      }));
      const order = ["Ctrl", "Meta", "Alt", "Shift"];
      const canonicalKey = key.length === 1 ? key.toUpperCase() : key;
      return order.filter((m) => mods.has(m)).concat(canonicalKey).join("+");
    }

    function fromEvent(e) {
      const key = e.key;
      if (["Control", "Shift", "Alt", "Meta"].includes(key)) return null;
      const mods = [];
      if (e.ctrlKey) mods.push("Ctrl");
      if (e.metaKey) mods.push("Meta");
      if (e.altKey) mods.push("Alt");
      if (e.shiftKey) mods.push("Shift");
      const canonicalKey = key.length === 1 ? key.toUpperCase() : key;
      return mods.concat(canonicalKey).join("+");
    }

    function registerDefault(commandId, chord) {
      defaults.set(commandId, normalize(chord));
    }

    function chordOf(commandId) {
      if (commandId in user) return user[commandId];
      return defaults.get(commandId) || null;
    }

    function setUser(commandId, chord) {
      user[commandId] = chord == null ? null : normalize(chord);
      writeJSON(KEY, user);
    }

    function resetUser(commandId) {
      delete user[commandId];
      writeJSON(KEY, user);
    }

    function isUser(commandId) { return commandId in user; }

    /** commandId for a chord; user bindings shadow defaults entirely. */
    function resolve(chord) {
      if (!chord) return null;
      for (const [id, c] of Object.entries(user)) {
        if (c === chord) return id;
      }
      for (const [id, c] of defaults) {
        if (c === chord && !(id in user)) return id;
      }
      return null;
    }

    /** Display form: ⌘⇧P style on a Mac, Ctrl+Shift+P elsewhere. */
    function label(commandId) {
      const chord = chordOf(commandId);
      if (!chord) return "";
      if (!isMac) return chord.replace(/Meta/g, "Win");
      return chord.replace(/Ctrl\+/g, "⌃").replace(/Meta\+/g, "⌘")
        .replace(/Alt\+/g, "⌥").replace(/Shift\+/g, "⇧");
    }

    function all() {
      const ids = new Set([...defaults.keys(), ...Object.keys(user)]);
      return Array.from(ids).map((id) => ({
        command: id, chord: chordOf(id),
        isDefault: !(id in user), default: defaults.get(id) || null,
      }));
    }

    return { registerDefault, chordOf, setUser, resetUser, isUser,
             resolve, label, normalize, fromEvent, all };
  })();

  /* =================================================================
   * Menus
   * ================================================================= */
  const Menus = (() => {
    const menus = [];                  // [{id, title, order, groups}]

    function addMenu(id, title, order) {
      menus.push({ id, title, order: order || 0, items: [] });
      menus.sort((a, b) => a.order - b.order);
    }

    /** item: {command} | {separator: true} | {submenu title + items} */
    function addItem(menuId, item) {
      const menu = menus.find((m) => m.id === menuId);
      if (menu) menu.items.push(item);
    }

    function bar() { return menus; }
    return { addMenu, addItem, bar };
  })();

  /* =================================================================
   * Context menus
   * ================================================================= */
  const ContextMenus = (() => {
    const registry = new Map();        // contextId -> (ctx) => items

    function register(contextId, provider) {
      registry.set(contextId, provider);
    }
    function itemsFor(contextId, ctx) {
      const provider = registry.get(contextId);
      return provider ? provider(ctx || {}) : [];
    }
    return { register, itemsFor };
  })();

  /* =================================================================
   * Diagnostics — one store, many producers, many consumers
   * ================================================================= */
  const Diagnostics = (() => {
    const byOwner = new Map();         // owner -> Map(path -> diags[])
    const listeners = new Set();

    function set(owner, path, diags) {
      if (!byOwner.has(owner)) byOwner.set(owner, new Map());
      if (diags && diags.length) byOwner.get(owner).set(path, diags);
      else byOwner.get(owner).delete(path);
      fire();
    }

    function clear(owner, path) {
      const m = byOwner.get(owner);
      if (!m) return;
      if (path != null) m.delete(path); else m.clear();
      fire();
    }

    function forPath(path) {
      const out = [];
      byOwner.forEach((m, owner) => {
        (m.get(path) || []).forEach((d) => out.push({ ...d, owner }));
      });
      return out;
    }

    function all() {
      const out = new Map();           // path -> diags
      byOwner.forEach((m, owner) => {
        m.forEach((diags, path) => {
          if (!out.has(path)) out.set(path, []);
          diags.forEach((d) => out.get(path).push({ ...d, owner }));
        });
      });
      return out;
    }

    function count() {
      let errors = 0, warnings = 0;
      all().forEach((diags) => diags.forEach((d) => {
        if (d.severity === "error") errors += 1;
        else if (d.severity === "warning") warnings += 1;
      }));
      return { errors, warnings };
    }

    function onChange(fn) { listeners.add(fn); return () => listeners.delete(fn); }
    function fire() { listeners.forEach((fn) => fn()); }

    return { set, clear, forPath, all, count, onChange };
  })();

  /* =================================================================
   * Fuzzy matching — the palette's and quick-open's scorer
   * ================================================================= */
  /**
   * Subsequence match of `query` in `text`; null when it does not match.
   * Scores favour word starts, consecutive runs and early matches — the
   * ordering a person expects from an IDE palette.
   */
  function fuzzy(query, text) {
    if (!query) return { score: 0, positions: [] };
    const q = query.toLowerCase();
    const t = text.toLowerCase();
    const positions = [];
    let score = 0, ti = 0, run = 0;
    for (let qi = 0; qi < q.length; qi++) {
      const idx = t.indexOf(q[qi], ti);
      if (idx === -1) return null;
      const boundary = idx === 0 || " /._-:>".includes(t[idx - 1]) ||
        (text[idx] >= "A" && text[idx] <= "Z" &&
         text[idx - 1] >= "a" && text[idx - 1] <= "z");
      run = idx === ti ? run + 1 : 1;
      score += 1 + (boundary ? 8 : 0) + run * 2 - Math.min(idx, 40) * 0.05;
      positions.push(idx);
      ti = idx + 1;
    }
    score -= (text.length - q.length) * 0.01;   // prefer tighter targets
    return { score, positions };
  }

  const core = { Settings, Commands, Keys, Menus, ContextMenus,
                 Diagnostics, fuzzy, isMac };
  root.EpsilonCore = core;
  if (typeof module === "object" && module.exports) module.exports = core;
})(typeof globalThis !== "undefined" ? globalThis : this);
