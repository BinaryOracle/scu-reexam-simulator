import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/static/contest-roster.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");

test("participant picker uses a structured compact selection panel", () => {
  assert.match(source, /contest-roster-count/);
  assert.match(source, /contest-roster-search/);
  assert.match(source, /contest-roster-actions/);
  assert.match(source, /contest-roster-user-identity/);
  assert.match(source, /contest-roster-user-copy/);
  assert.match(source, /contest-roster-user-avatar/);
  assert.match(styles, /\.contest-roster-tools\s*\{[^}]*display:\s*grid/s);
  assert.match(styles, /\.contest-roster-list\s*\{[^}]*max-height:/s);
  assert.match(styles, /\.contest-roster-user\[data-selected="true"\]/);
  assert.match(styles, /@media\s*\(max-width:\s*620px\)[\s\S]*?\.contest-roster-actions/);
});
