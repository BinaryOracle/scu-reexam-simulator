/** Local workspace preferences; focus is temporary and never saved across reloads. */
const defaults = { statement: 0.46, editor: 0.72 };
const limits = { statement: [0.2, 0.8], editor: [0.25, 0.85] };
const paneNames = ["statement", "editor", "panels"];
const paneLabels = { statement: "题面", editor: "代码区", panels: "样例与提交记录" };
const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

/** Remember independent split positions, keeping the workspace usable if storage fails. */
export function createLayoutStore(storage, key) {
  const sizes = { ...defaults };
  const collapsed = { statement: false, editor: false, panels: false };
  let focused = "";
  try {
    const saved = JSON.parse(storage?.getItem(key) ?? "null");
    for (const axis of Object.keys(defaults)) {
      if (Number.isFinite(saved?.[axis])) sizes[axis] = clamp(saved[axis], ...limits[axis]);
    }
    for (const pane of paneNames) {
      if (typeof saved?.collapsed?.[pane] === "boolean") collapsed[pane] = saved.collapsed[pane];
    }
  } catch { /* Missing, blocked or malformed preferences use the default layout. */ }
  const persist = () => {
    try { storage?.setItem(key, JSON.stringify({ ...sizes, collapsed })); }
    catch { /* Size changes remain usable in memory when storage is blocked or full. */ }
  };
  return {
    read: () => ({ ...sizes, focused, collapsed: { ...collapsed } }),
    resize(axis, value, save = true) {
      if (!Object.hasOwn(defaults, axis) || !Number.isFinite(value)) return;
      sizes[axis] = clamp(value, ...limits[axis]);
      if (save) persist();
    },
    save: persist,
    focus(pane) {
      if (!paneNames.includes(pane) || collapsed[pane]) return;
      focused = focused === pane ? "" : pane;
    },
    restore() { focused = ""; },
    collapse(pane) {
      if (!paneNames.includes(pane)) return;
      collapsed[pane] = true;
      if (focused === pane) focused = "";
      persist();
    },
    expand(pane) {
      if (!paneNames.includes(pane)) return;
      collapsed[pane] = false;
      persist();
    },
    expandAll() { for (const pane of paneNames) collapsed[pane] = false; focused = ""; persist(); },
    reset() { Object.assign(sizes, defaults); for (const pane of paneNames) collapsed[pane] = false; focused = ""; persist(); },
  };
}

/** Attach resizing and pane focus without replacing editor or result DOM nodes. */
export function mountWorkspaceLayout({ columns, stack, horizontal, vertical, controls, closeControls, regions, restoreControls, expandAll, reset, store }) {
  const doc = columns.ownerDocument;
  const view = doc.defaultView;
  const lifecycle = new view.AbortController();
  const { signal } = lifecycle;
  const narrow = view.matchMedia("(max-width: 1050px)");
  let drag = null;
  let restoreTarget = null;

  const bounds = axis => {
    const size = axis === "statement" ? columns.clientWidth - 8 : stack.clientHeight - 8;
    // Leave enough room for code controls and an accessible auxiliary panel header.
    const minimum = axis === "statement" ? 240 : 210;
    const remaining = axis === "statement" ? 300 : 100;
    const [lower, upper] = limits[axis];
    if (size <= 0) return [lower, upper];
    return [Math.max(lower, Math.min(minimum, size * 0.65) / size),
      Math.min(upper, 1 - Math.min(remaining, size * 0.3) / size)];
  };
  const displayedRatio = axis => clamp(store.read()[axis], ...bounds(axis));
  const paint = () => {
    const current = store.read();
    columns.dataset.focused = current.focused;
    columns.dataset.statementHidden = String(current.collapsed.statement);
    columns.dataset.editorHidden = String(current.collapsed.editor);
    columns.dataset.panelsHidden = String(current.collapsed.panels);
    for (const [pane, region] of Object.entries(regions)) region.hidden = current.collapsed[pane];
    horizontal.hidden = current.collapsed.statement || current.collapsed.editor;
    vertical.hidden = current.collapsed.editor || current.collapsed.panels;
    for (const [pane, control] of Object.entries(restoreControls)) {
      control.hidden = !current.collapsed[pane];
      control.textContent = `展开${paneLabels[pane]}`;
    }
    expandAll.hidden = !Object.values(current.collapsed).some(Boolean);
    if (narrow.matches && columns.dataset.activePane) {
      const activePane = columns.dataset.activePane === "statement" ? "statement" : "editor";
      const alternatePane = activePane === "statement" ? "editor" : "statement";
      if (current.collapsed[activePane] && !current.collapsed[alternatePane]) columns.dataset.activePane = alternatePane;
    }
    for (const [axis, handle] of [["statement", horizontal], ["editor", vertical]]) {
      const ratio = displayedRatio(axis);
      const [min, max] = bounds(axis);
      columns.style.setProperty(`--${axis}-size`, ratio);
      handle.setAttribute("aria-valuemin", String(Math.round(min * 100)));
      handle.setAttribute("aria-valuemax", String(Math.round(max * 100)));
      handle.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
      handle.setAttribute("aria-valuetext", `${Math.round(ratio * 100)}%`);
    }
    for (const [pane, control] of Object.entries(controls)) {
      const expanded = current.focused === pane;
      const label = `${expanded ? "还原" : "放大"}${paneLabels[pane]}`;
      control.setAttribute("aria-label", label);
      control.setAttribute("aria-pressed", String(expanded));
      control.title = `${label}${expanded ? "（Esc）" : ""}`;
      control.dataset.expanded = String(expanded);
    }
  };
  const finishDrag = () => {
    if (!drag) return;
    const { handle, pointerId } = drag;
    drag = null;
    if (handle.hasPointerCapture(pointerId)) handle.releasePointerCapture(pointerId);
    columns.classList.remove("is-resizing");
    columns.removeAttribute("data-resize-axis");
    store.save();
  };
  for (const [axis, handle, backward, forward] of [
    ["statement", horizontal, "ArrowLeft", "ArrowRight"],
    ["editor", vertical, "ArrowUp", "ArrowDown"],
  ]) {
    handle.title = "拖动调整大小 · 方向键微调 · 双击恢复默认比例";
    handle.addEventListener("pointerdown", event => {
      if (event.button !== 0 || event.isPrimary === false || store.read().focused) return;
      event.preventDefault();
      finishDrag();
      const rect = (axis === "statement" ? columns : stack).getBoundingClientRect();
      drag = {
        handle, axis, pointerId: event.pointerId, ratio: displayedRatio(axis),
        start: axis === "statement" ? event.clientX : event.clientY,
        size: Math.max(1, (axis === "statement" ? rect.width : rect.height) - 8),
      };
      handle.focus({ preventScroll: true });
      handle.setPointerCapture(event.pointerId);
      columns.classList.add("is-resizing");
      columns.dataset.resizeAxis = axis;
    }, { signal });
    handle.addEventListener("pointermove", event => {
      if (drag?.handle !== handle || drag.pointerId !== event.pointerId) return;
      const coordinate = axis === "statement" ? event.clientX : event.clientY;
      store.resize(axis, clamp(drag.ratio + (coordinate - drag.start) / drag.size, ...bounds(axis)), false);
      paint();
    }, { signal });
    for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
      handle.addEventListener(type, event => {
        if (drag?.pointerId === event.pointerId) finishDrag();
      }, { signal });
    }
    handle.addEventListener("keydown", event => {
      if (![backward, forward, "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      const [min, max] = bounds(axis);
      const value = event.key === "Home" ? min : event.key === "End" ? max
        : displayedRatio(axis) + (event.key === backward ? -1 : 1) * (event.shiftKey ? 0.1 : 0.02);
      store.resize(axis, clamp(value, min, max));
      paint();
    }, { signal });
    handle.addEventListener("dblclick", () => { store.resize(axis, defaults[axis]); paint(); }, { signal });
  }
  for (const [pane, control] of Object.entries(controls)) {
    control.addEventListener("click", () => {
      finishDrag();
      store.focus(pane);
      restoreTarget = control;
      paint();
    }, { signal });
  }
  for (const [pane, control] of Object.entries(closeControls)) {
    control.addEventListener("click", () => {
      finishDrag();
      store.collapse(pane);
      paint();
      restoreControls[pane].focus({ preventScroll: true });
    }, { signal });
  }
  for (const [pane, control] of Object.entries(restoreControls)) {
    control.addEventListener("click", () => {
      store.expand(pane);
      paint();
      regions[pane].querySelector?.(".pane-expand")?.focus({ preventScroll: true });
    }, { signal });
  }
  expandAll.addEventListener("click", () => { store.expandAll(); paint(); }, { signal });
  reset.addEventListener("click", () => { finishDrag(); store.reset(); paint(); }, { signal });
  doc.addEventListener("keydown", event => {
    if (event.key !== "Escape" || !columns.getClientRects().length || !store.read().focused
      || doc.querySelector("dialog[open]")) return;
    event.preventDefault();
    store.restore();
    paint();
    restoreTarget?.focus({ preventScroll: true });
  }, { signal });
  narrow.addEventListener("change", () => { finishDrag(); store.restore(); paint(); }, { signal });
  columns.addEventListener("workspacepanechange", () => { finishDrag(); store.restore(); paint(); }, { signal });
  const observer = new view.ResizeObserver(paint);
  observer.observe(columns);
  observer.observe(stack);
  paint();
  return () => { finishDrag(); lifecycle.abort(); observer.disconnect(); };
}
