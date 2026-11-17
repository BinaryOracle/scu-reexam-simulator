import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../app/static/coding.css", import.meta.url), "utf8");

test("coding filters keep all four selectors on one desktop row", () => {
  assert.match(css, /\.coding-toolbar\s*\{[^}]*grid-template-columns:\s*minmax\(180px, 1\.5fr\) repeat\(4, minmax\(0, 1fr\)\)/s);
  assert.match(css, /@media\s*\(min-width:\s*621px\) and \(max-width:\s*1150px\)[\s\S]*?\.coding-toolbar input\s*\{\s*grid-column:\s*1 \/ -1/);
  const mobile = css.slice(css.lastIndexOf("@media (max-width: 700px)"));
  assert.match(mobile, /\.coding-toolbar\s*\{\s*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
});
