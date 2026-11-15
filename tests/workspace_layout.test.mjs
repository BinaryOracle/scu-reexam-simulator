import assert from "node:assert/strict";
import test from "node:test";
import { createLayoutStore, mountWorkspaceLayout } from "../app/static/workspace-layout.mjs";

function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test("remembers independent pane sizes for each user across workspace visits", () => {
  const saved = storage();
  const first = createLayoutStore(saved, "user:1");
  first.resize("statement", 0.62);
  first.resize("editor", 0.55);
  assert.deepEqual(createLayoutStore(saved, "user:1").read(), { statement: 0.62, editor: 0.55, focused: "", collapsed: { statement: false, editor: false, panels: false } });
  assert.deepEqual(createLayoutStore(saved, "user:2").read(), { statement: 0.46, editor: 0.72, focused: "", collapsed: { statement: false, editor: false, panels: false } });
});

test("maximizing and restoring any pane preserves both divider positions", () => {
  const layout = createLayoutStore(storage(), "user:1");
  layout.resize("statement", 0.6);
  layout.resize("editor", 0.5);
  for (const pane of ["statement", "editor", "panels"]) {
    layout.focus(pane);
    assert.equal(layout.read().focused, pane);
    layout.focus(pane);
    assert.deepEqual(layout.read(), { statement: 0.6, editor: 0.5, focused: "", collapsed: { statement: false, editor: false, panels: false } });
  }
  layout.focus("editor");
  layout.restore();
  assert.equal(layout.read().focused, "");
  layout.focus("panels");
  layout.reset();
  assert.deepEqual(layout.read(), { statement: 0.46, editor: 0.72, focused: "", collapsed: { statement: false, editor: false, panels: false } });
});

test("closes individual panes and restores them with individual or expand-all controls", () => {
  const saved = storage();
  const layout = createLayoutStore(saved, "user:1");
  layout.collapse("statement");
  layout.collapse("panels");
  assert.deepEqual(layout.read().collapsed, { statement: true, editor: false, panels: true });
  assert.deepEqual(createLayoutStore(saved, "user:1").read().collapsed,
    { statement: true, editor: false, panels: true });
  layout.expand("statement");
  assert.deepEqual(layout.read().collapsed, { statement: false, editor: false, panels: true });
  layout.expandAll();
  assert.deepEqual(layout.read().collapsed, { statement: false, editor: false, panels: false });
});

test("bounds pane sizes and recovers from malformed or obsolete stored values", () => {
  const saved = storage();
  saved.setItem("user:1", '{"statement":"0.7","editor":null,"focused":"editor"}');
  const layout = createLayoutStore(saved, "user:1");
  assert.deepEqual(layout.read(), {
    statement: 0.46, editor: 0.72, focused: "",
    collapsed: { statement: false, editor: false, panels: false },
  });
  layout.resize("statement", -10);
  layout.resize("editor", 10);
  assert.deepEqual(layout.read(), {
    statement: 0.2, editor: 0.85, focused: "",
    collapsed: { statement: false, editor: false, panels: false },
  });
  layout.resize("statement", NaN);
  assert.equal(layout.read().statement, 0.2);
  saved.setItem("user:2", "{");
  assert.equal(createLayoutStore(saved, "user:2").read().editor, 0.72);
});

test("retains working layout when browser storage is unavailable, without persisting focus", () => {
  const unavailable = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("full"); } };
  const layout = createLayoutStore(unavailable, "user:1");
  layout.resize("editor", 0.6);
  layout.focus("editor");
  assert.equal(layout.read().editor, 0.6);
  const saved = storage();
  const persistent = createLayoutStore(saved, "user:1");
  persistent.resize("editor", 0.6);
  persistent.focus("editor");
  assert.equal(createLayoutStore(saved, "user:1").read().focused, "");
});

class Pane extends EventTarget {
  constructor() {
    super();
    this.hidden = false;
    this.dataset = {};
    this.attributes = new Map();
    this.classes = new Set();
    this.classList = { add: value => this.classes.add(value), remove: value => this.classes.delete(value) };
    this.style = { setProperty() {} };
    this.clientWidth = 1400;
    this.clientHeight = 800;
  }
  setAttribute(name, value) { this.attributes.set(name, value); }
  removeAttribute(name) { delete this.dataset[name.replace(/^data-/, "").replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())]; }
  getBoundingClientRect() { return { width: this.clientWidth, height: this.clientHeight }; }
  getClientRects() { return [{}]; }
  setPointerCapture(id) { this.pointer = id; }
  hasPointerCapture(id) { return this.pointer === id; }
  releasePointerCapture() { this.pointer = null; }
  focus() { this.focused = true; }
  querySelector() { return null; }
}
function interactionFixture() {
  const columns = new Pane();
  const doc = new EventTarget();
  const media = new EventTarget();
  let disconnected = false;
  doc.querySelector = () => null;
  doc.defaultView = {
    AbortController, matchMedia: () => media,
    ResizeObserver: class { observe() {} disconnect() { disconnected = true; } },
  };
  columns.ownerDocument = doc;
  const regions = { statement: new Pane(), editor: new Pane(), panels: new Pane() };
  const restoreControls = { statement: new Pane(), editor: new Pane(), panels: new Pane() };
  const closeControls = { statement: new Pane(), editor: new Pane(), panels: new Pane() };
  const nodes = { columns, stack: new Pane(), horizontal: new Pane(), vertical: new Pane(), regions, restoreControls, closeControls, expandAll: new Pane(),
    controls: { statement: new Pane(), editor: new Pane(), panels: new Pane() },
    reset: new Pane(), store: createLayoutStore(storage(), "candidate") };
  const dispose = mountWorkspaceLayout(nodes);
  const emit = (target, type, values = {}) => {
    const event = new Event(type, { cancelable: true });
    Object.assign(event, { button: 0, pointerId: 1, clientX: 0, clientY: 0, ...values });
    target.dispatchEvent(event);
    return event;
  };
  return { ...nodes, emit, doc, media, dispose, disconnected: () => disconnected };
}

test("pointer capture keeps dragging smooth and cancellation or teardown ends the gesture", () => {
  const f = interactionFixture();
  f.emit(f.horizontal, "pointerdown", { clientX: 600 });
  f.emit(f.horizontal, "pointermove", { clientX: 740 });
  const dragged = f.store.read().statement;
  assert.ok(dragged > 0.55 && dragged < 0.57);
  assert.ok(f.columns.classes.has("is-resizing"));
  f.emit(f.horizontal, "pointermove", { clientX: 1000, pointerId: 2 });
  assert.equal(f.store.read().statement, dragged);
  f.emit(f.horizontal, "pointercancel");
  f.emit(f.horizontal, "pointermove", { clientX: 1000 });
  assert.equal(f.store.read().statement, dragged);
  assert.equal(f.columns.classes.has("is-resizing"), false);
  f.emit(f.vertical, "pointerdown");
  f.dispose();
  f.emit(f.vertical, "pointermove", { clientY: -200 });
  assert.equal(f.store.read().editor, 0.72);
  assert.equal(f.vertical.pointer, null);
  assert.equal(f.disconnected(), true);
  f.emit(f.controls.editor, "click");
  assert.equal(f.store.read().focused, "");
});

test("keyboard sizing, focus restoration, viewport changes and reset stay coordinated", () => {
  const f = interactionFixture();
  assert.equal(f.emit(f.horizontal, "keydown", { key: "ArrowRight" }).defaultPrevented, true);
  assert.ok(Math.abs(f.store.read().statement - 0.48) < 1e-10);
  f.emit(f.vertical, "keydown", { key: "Home" });
  assert.ok(f.store.read().editor > 0.25);
  f.emit(f.controls.panels, "click");
  assert.equal(f.columns.dataset.focused, "panels");
  f.emit(f.doc, "keydown", { key: "Escape" });
  assert.equal(f.columns.dataset.focused, "");
  assert.equal(f.controls.panels.focused, true);
  f.emit(f.controls.editor, "click");
  f.emit(f.media, "change");
  assert.equal(f.store.read().focused, "");
  f.emit(f.controls.panels, "click");
  f.emit(f.columns, "workspacepanechange");
  assert.equal(f.store.read().focused, "");
  f.emit(f.controls.statement, "click");
  f.emit(f.reset, "click");
  assert.deepEqual(f.store.read(), { statement: 0.46, editor: 0.72, focused: "", collapsed: { statement: false, editor: false, panels: false } });
  f.dispose();
});

test("hides closed workspace panes and exposes one-click restore controls", () => {
  const f = interactionFixture();
  f.emit(f.closeControls.statement, "click");
  assert.equal(f.regions.statement.hidden, true);
  assert.equal(f.restoreControls.statement.hidden, false);
  assert.equal(f.horizontal.hidden, true);
  f.emit(f.restoreControls.statement, "click");
  assert.equal(f.regions.statement.hidden, false);
  assert.equal(f.horizontal.hidden, false);
  f.emit(f.closeControls.editor, "click");
  f.emit(f.closeControls.panels, "click");
  assert.equal(f.regions.editor.hidden, true);
  assert.equal(f.regions.panels.hidden, true);
  f.emit(f.expandAll, "click");
  assert.deepEqual(f.store.read().collapsed, { statement: false, editor: false, panels: false });
  f.dispose();
});
