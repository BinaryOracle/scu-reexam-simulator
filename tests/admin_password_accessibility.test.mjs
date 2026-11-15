import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/static/admin.js", import.meta.url), "utf8");

test("account password display does not use browser login-password semantics", () => {
  const control = source.slice(source.indexOf("function passwordControl(user)"), source.indexOf("const categoryNames"));
  assert.match(control, /field\.type = "text"/);
  assert.doesNotMatch(control, /field\.type = "password"/);
  assert.match(control, /field\.value = "••••••"/);
});
