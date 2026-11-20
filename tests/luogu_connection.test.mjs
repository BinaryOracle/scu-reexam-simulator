import assert from "node:assert/strict";
import test from "node:test";
import { readLuoguConnection, writeLuoguConnection } from "../app/static/luogu-connection.mjs";

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
