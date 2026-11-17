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

test("package deletion warns that every issued code and redemption record will be permanently removed", async () => {
  const source = await readFile(new URL("../app/static/credits.js", import.meta.url), "utf8");
  const app = await readFile(new URL("../app/static/app.js", import.meta.url), "utf8");
  const admin = await readFile(new URL("../app/static/admin.js", import.meta.url), "utf8");
  const markup = await readFile(new URL("../app/static/index.html", import.meta.url), "utf8");
  assert.match(source, /永久删除该套餐下的全部卡密记录/);
  assert.match(source, /未兑换卡密将立即失效，兑换历史也会删除/);
  assert.match(source, /已经到账的积分不会退回/);
  assert.match(source, /确认永久删除/);
  assert.match(app, /credits\.js\?v=20261117-package-delete-v2/);
  assert.match(admin, /credits\.js\?v=20261117-package-delete-v2/);
  assert.match(markup, /app\.js\?v=20261117-package-delete-v2/);
});
