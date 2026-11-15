import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const styleSource = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");

test("mobile page-heading actions meet a 44px touch target", () => {
  assert.match(styleSource, /\.page-heading > \.button \{[^}]*min-height: 44px;/s);
});
