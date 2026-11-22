import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const [css, style, html] = await Promise.all([
  readFile(new URL("../app/static/credits.css", import.meta.url), "utf8"),
  readFile(new URL("../app/static/style.css", import.meta.url), "utf8"),
  readFile(new URL("../app/static/index.html", import.meta.url), "utf8"),
]);

test("voucher package form has roomier spacing and responsive fields", () => {
  assert.match(css, /#voucherPackageForm\.package-create-panel\s*\{[^}]*gap:\s*20px[^}]*padding:\s*28px/);
  assert.match(css, /#voucherPackageForm \.package-create-fields\s*\{[^}]*gap:\s*18px/);
  assert.match(css, /#voucherPackageForm \.package-create-fields input\s*\{[^}]*min-height:\s*48px/);
  assert.match(css, /@media \(max-width: 620px\)[\s\S]*?#voucherPackageForm \.package-create-fields\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(html, /credits\.css\?v=20261122-voucher-spacing-v1/);
});

test("points reward rules are grouped and the save action is not full width", () => {
  for (const [group, label] of [["rewardInviteTitle", "邀请与签到"], ["rewardTrainingTitle", "题库投稿"], ["rewardCodingTitle", "算法投稿"], ["rewardLeaderboardTitle", "周榜奖励"]]) {
    assert.match(html, new RegExp(`id="${group}">${label}<`));
    assert.match(html, new RegExp(`aria-labelledby="${group}"`));
  }
  assert.match(html, /class="reward-rule-groups"/);
  assert.match(style, /\.reward-rule-groups\s*\{[^}]*grid-template-columns:\s*repeat\(2/);
  assert.match(style, /\.reward-rules-panel \.form-footer\s*\{[^}]*justify-content:\s*flex-end/);
  assert.match(style, /\.reward-rules-panel \.form-footer \.button\s*\{[^}]*width:\s*auto/);
  assert.match(html, /style\.css\?v=20261122-reward-groups-v1/);
});
