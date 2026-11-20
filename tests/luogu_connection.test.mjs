import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { readLuoguConnection, writeLuoguConnection } from "../app/static/luogu-connection.mjs";

const contestSource = await readFile(new URL("../app/static/contest.js", import.meta.url), "utf8");

test("remembers the last verified account separately for each user", () => {
  const values = new Map();
  const storage = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  writeLuoguConnection(storage, 4, "candidate");
  writeLuoguConnection(storage, 9, "manager");
  assert.equal(readLuoguConnection(storage, 4), "candidate");
  assert.equal(readLuoguConnection(storage, 9), "manager");
  writeLuoguConnection(storage, 4, "");
  assert.equal(readLuoguConnection(storage, 4), "");
  assert.equal(readLuoguConnection(storage, 9), "manager");
});

test("continues when browser storage is unavailable", () => {
  const storage = {
    getItem() { throw new Error("blocked"); },
    setItem() { throw new Error("blocked"); },
    removeItem() { throw new Error("blocked"); },
  };
  assert.equal(readLuoguConnection(storage, 4), "");
  assert.doesNotThrow(() => writeLuoguConnection(storage, 4, "candidate"));
});

test("keeps startup bridge failures compact and reveals recovery only after user action", () => {
  const connection = contestSource.slice(contestSource.indexOf("function setLuoguConnection("), contestSource.indexOf("async function refreshLuoguBridgeConnection("));
  const refresh = contestSource.slice(contestSource.indexOf("async function refreshLuoguBridgeConnection("), contestSource.indexOf("function sendLuoguBridge("));
  const help = contestSource.slice(contestSource.indexOf("function showLuoguBridgeHelp("), contestSource.indexOf("function prepareLuoguConnection("));
  assert.match(refresh, /showLuoguBridgeHelp\(error\.message \|\| "插件未响应，请检查插件配置后重试。", \{ reveal: force \}\)/);
  assert.match(help, /if \(reveal\) panel\.open = true/);
  assert.match(connection, /if \(panel\?\.classList\.contains\("has-error"\)\)\s*\{[\s\S]*?panel\.classList\.remove\("has-error"\)/);
  assert.match(connection, /if \(panel\?\.classList\.contains\("has-error"\)\)\s*\{[\s\S]*?querySelector\("\.luogu-bridge-error"\)\?\.remove\(\)/);
  assert.match(connection, /if \(panel\?\.classList\.contains\("has-error"\)\)\s*\{[\s\S]*?panel\.open = false/);
});
