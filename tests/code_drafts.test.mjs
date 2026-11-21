import assert from "node:assert/strict";
import test from "node:test";
import { createCodeDrafts, saveDraftOnShortcut } from "../app/static/code-drafts.mjs";
import { hasCodeDraft } from "../app/static/draft-compat.mjs";

test("Ctrl+S saves the focused code draft and prevents the browser save page action", () => {
  let saved = 0;
  let prevented = false;
  const handled = saveDraftOnShortcut({
    key: "s",
    ctrlKey: true,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    preventDefault() { prevented = true; },
  }, () => { saved++; });
  assert.equal(handled, true);
  assert.equal(saved, 1);
  assert.equal(prevented, true);
});

test("unrelated shortcuts are left to the browser and do not save code", () => {
  let saved = 0;
  let prevented = false;
  const handled = saveDraftOnShortcut({
    key: "s",
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    shiftKey: false,
    preventDefault() { prevented = true; },
  }, () => { saved++; });
  assert.equal(handled, false);
  assert.equal(saved, 0);
  assert.equal(prevented, false);
});

test("keeps independent language and problem drafts when storage is blocked", () => {
  const drafts = createCodeDrafts(() => { throw new Error("blocked"); });
  assert.equal(drafts.available(), false);
  assert.equal(drafts.write("problem1:cpp", "int main() {}"), false);
  assert.equal(drafts.write("problem1:python", "print(1)"), false);
  assert.equal(drafts.read("problem1:cpp"), "int main() {}");
  assert.equal(drafts.read("problem1:python"), "print(1)");
  assert.equal(drafts.read("problem2:cpp"), "");
});

test("retains the latest draft when a previously available storage write fails", () => {
  const storage = new Map([["p:cpp", "old"]]);
  const drafts = createCodeDrafts(() => ({
    getItem: key => storage.get(key),
    setItem: () => { throw new Error("quota"); },
  }));
  assert.equal(drafts.read("p:cpp"), "old");
  assert.equal(drafts.write("p:cpp", "new"), false);
  assert.equal(drafts.read("p:cpp"), "new");
});

test("reads newer shared storage after a successful save", () => {
  const values = new Map();
  const drafts = createCodeDrafts(() => ({
    getItem: key => values.get(key),
    setItem: (key, value) => values.set(key, value),
  }));
  assert.equal(drafts.write("p:cpp", "first"), true);
  values.set("p:cpp", "updated in another tab");
  assert.equal(drafts.read("p:cpp"), "updated in another tab");
});

test("reads draft presence from a cached module that predates has", () => {
  const storage = new Map([["p:cpp", ""]]);
  const legacyDrafts = { read: key => storage.get(key) ?? "" };
  assert.equal(hasCodeDraft(legacyDrafts, "p:cpp", () => ({ getItem: key => storage.get(key) ?? null })), true);
  assert.equal(hasCodeDraft(legacyDrafts, "missing", () => ({ getItem: key => storage.get(key) ?? null })), false);
});

test("falls back to the legacy draft reader when browser storage is blocked", () => {
  const legacyDrafts = { read: key => key === "p:cpp" ? "int main() {}" : "" };
  assert.equal(hasCodeDraft(legacyDrafts, "p:cpp", () => { throw new Error("blocked"); }), true);
  assert.equal(hasCodeDraft(legacyDrafts, "missing", () => { throw new Error("blocked"); }), false);
});
