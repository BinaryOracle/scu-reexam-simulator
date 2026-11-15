import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [component, styles] = await Promise.all([
  readFile(new URL("../app/static/credits.js", import.meta.url), "utf8"),
  readFile(new URL("../app/static/credits.css", import.meta.url), "utf8"),
]);

test("mobile voucher cards keep code, package, status, redeemer and time visible without horizontal scrolling", () => {
  assert.match(component, /cardCode\.append\(el\("span", "卡密"\)/);
  for (const label of ["批次", "套餐", "兑换用户", "兑换时间"])
    assert.match(component, new RegExp(`addField\\("${label}"`));
  assert.match(component, /badge\(redeemed \? "已兑换" : "未兑换"/);
  assert.match(styles, /\.voucher-mobile-list\s*\{\s*display:\s*none;\s*\}/);
  assert.match(styles, /@media \(max-width:\s*620px\)\s*\{[\s\S]*?\.voucher-results > \.table-scroll\s*\{\s*display:\s*none;\s*\}[\s\S]*?\.voucher-mobile-list\s*\{\s*display:\s*grid/);
});
