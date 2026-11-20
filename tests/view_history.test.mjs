import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../app/static/app.js", import.meta.url), "utf8");
const contestSource = await readFile(new URL("../app/static/contest.js", import.meta.url), "utf8");

test("restores the active app view from browser history and URL", () => {
  assert.match(appSource, /window\.addEventListener\(["']popstate["']/);
  assert.match(appSource, /readAppRoute/);
  assert.match(appSource, /writeAppViewRoute/);
});

test("restores the selected contest workspace after reload", () => {
  assert.match(contestSource, /restoreContestRoute/);
  assert.match(contestSource, /writeAppRoute/);
});

test("persists the Luogu account and rechecks the extension after reload", () => {
  assert.match(contestSource, /readLuoguConnection/);
  assert.match(contestSource, /writeLuoguConnection/);
  assert.match(contestSource, /refreshLuoguBridgeConnection/);
});
