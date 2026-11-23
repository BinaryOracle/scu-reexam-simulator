import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../app/static/admin.js", import.meta.url), "utf8");

test("administrator user list edits ordinary-user points and masks admin balances as unlimited", () => {
  assert.match(source, /accountCell\("积分", "account-points-cell"\)/);
  assert.match(source, /if \(user\.is_admin\) pointsCell\.append\(el\("span", "无限积分"/);
  assert.match(source, /body: JSON\.stringify\(\{ points: Number\(input\.value\) \}\)/);
  assert.match(source, /user\.points = Number\(input\.value\)/);
  assert.doesNotMatch(source, /accountCell\("面试次数"/);
});
