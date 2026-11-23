import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const adminSource = await readFile(new URL("../app/static/admin.js", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");
const creditsStyleSource = await readFile(new URL("../app/static/credits.css", import.meta.url), "utf8");

test("mobile account cards label each field and keep actions in the same card", () => {
  for (const label of ["用户", "邀请者", "套餐服务", "返利", "密码", "积分", "功能权限", "账号状态", "操作"])
    assert.ok(adminSource.includes(`"${label}"`), `missing mobile label ${label}`);
  assert.match(adminSource, /text\.append\(email\)/);
  assert.match(adminSource, /text\.append\(role\)/);
  assert.match(styleSource, /\.account-table tbody tr \{[^}]*display: grid/s);
  assert.match(styleSource, /\.account-table thead \{ display: none; \}/);
  assert.match(styleSource, /\.account-cell-label \{ display: block/);
  assert.match(styleSource, /\.account-table td:nth-child\(1\).*\.account-table td:nth-child\(4\).*\.account-table td:nth-child\(6\).*\.account-table td:nth-child\(8\).*\{ grid-column: 1 \/ -1; \}/s);
  assert.match(adminSource, /wrap\.setAttribute\("aria-label", "用户账号列表"\)/);
});

test("desktop account table keeps core columns fixed while secondary columns scroll", () => {
  assert.match(adminSource, /"用户信息",\s*"密码",\s*"功能权限",\s*"账号状态",\s*"邀请者",\s*"套餐服务",\s*"返利",\s*"积分",\s*"操作"/);
  assert.match(adminSource, /row\.append\(name, password, permissions, active, referrer, service, rebate, pointsCell, actions\)/);
  assert.match(styleSource, /\.account-table th:nth-child\(-n\+4\), \.account-table td:nth-child\(-n\+4\) \{ position: sticky/);
  assert.match(styleSource, /\.account-table th:nth-child\(4\), \.account-table td:nth-child\(4\) \{ left: 555px/);
  assert.match(styleSource, /\.account-table \{ width: 1487px; min-width: 1487px; table-layout: fixed/);
  assert.match(styleSource, /\.account-table-wrap::-webkit-scrollbar-thumb/);
  assert.doesNotMatch(creditsStyleSource, /\.account-table \{ width: 100%; table-layout: fixed/);
  assert.doesNotMatch(creditsStyleSource, /\.account-table th:last-child[\s\S]*?right: 0/);
});

test("account permissions are independent and report the changed permission state", () => {
  assert.match(adminSource, /permissionCell\("can_training", "每日训练权限", "每日训练"\)/);
  assert.match(adminSource, /permissionCell\("can_coding", "算法题带刷权限", "算法带刷"\)/);
  assert.match(adminSource, /saveUserFields\(user, \{ \[key\]: next \}, `\$\{user\.username\} 的\$\{label\}已\$\{next \? "开启" : "关闭"\}。`\)/);
  assert.match(adminSource, /account-status-button \$\{enabled \? "active" : "inactive"\}/);
});

test("purchase totals open a shared detail reader and settlement stays in its own column", () => {
  assert.match(adminSource, /purchaseSummaryButton\(user/);
  assert.match(adminSource, /openPurchaseDetails\(user, \{ manage: true/);
  assert.match(adminSource, /accountCell\("返利", "account-rebate-cell"\)/);
  assert.match(adminSource, /account-rebate-state \$\{user\.rebate_status\}/);
  assert.doesNotMatch(adminSource, /serviceInput|purchase-service`/);
  assert.match(styleSource, /\.account-rebate-state\.pending \{[^}]*background: #edf8f1/);
  assert.match(styleSource, /\.account-rebate-state\.redeemed \{[^}]*background: #efeeeb/);
});

test("account management toolbar and table adapt to narrow viewports", () => {
  assert.match(styleSource, /\.account-filters \{ display: grid; grid-template-columns: repeat\(6, minmax\(0, 1fr\)\) auto/);
  assert.match(styleSource, /\.account-table \{ width: 1487px; min-width: 1487px; table-layout: fixed/);
  assert.match(styleSource, /@media \(max-width: 620px\) \{\s*\.account-toolbar \{ padding: 17px/);
});

test("a saved account permission stays visible when refreshing the user list fails", async () => {
  const user = { id: 7, username: "candidate", can_training: true };
  const notices = [], calls = [];
  const start = adminSource.indexOf("async function saveUserFields(user, fields, successMessage)");
  const end = adminSource.indexOf("\nexport async function refreshQuestionBank()", start);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({
    accounts: [user],
    api: async (...args) => { calls.push(args); return {}; },
    renderUsers: () => { calls.push(["render"]); },
    refreshUsers: async () => { throw new Error("temporary read failure"); },
    notify: (...args) => notices.push(args),
  });
  vm.runInContext(`${adminSource.slice(start, end)}\nglobalThis.save = saveUserFields;`, context);

  await context.save(user, { can_training: false }, "candidate 的每日训练权限已关闭。");

  assert.equal(user.can_training, false);
  assert.equal(calls[0][0], "/admin/users/7");
  assert.equal(calls[0][1].method, "PATCH");
  assert.deepEqual(JSON.parse(calls[0][1].body), { can_training: false });
  assert.ok(calls.some(([kind]) => kind === "render"));
  assert.equal(notices.length, 1);
  assert.equal(notices[0][1], "info");
  assert.match(notices[0][0], /已关闭。.*当前状态已更新.*刷新用户列表/s);
});

test("account status filter keeps its label and controls readable on narrow screens", () => {
  assert.ok(styleSource.includes("flex: 0 0 132px;\n  width: 132px;\n  min-width: 0;"));
  assert.ok(styleSource.includes("flex: 0 1 132px;\n    width: auto;\n    max-width: 100%;"));
  assert.ok(styleSource.includes("@media (max-width: 420px)"));
  assert.ok(styleSource.includes("grid-template-columns: minmax(0, 1fr);\n    align-items: stretch;"));
  assert.ok(styleSource.includes(".account-filters select {\n    width: 100%;\n    flex: initial;"));
});

test("mobile administrator navigation keeps readable labels in a horizontal rail", () => {
  const navigation = styleSource.slice(styleSource.indexOf(".admin-mode .sidebar nav {", styleSource.indexOf("@media (max-width: 620px)")), styleSource.indexOf(".admin-mode .sidebar-nav-group"));
  assert.match(navigation, /display: flex/);
  assert.match(navigation, /overflow-x: auto/);
  assert.match(navigation, /flex: 0 0 72px/);
  assert.match(navigation, /font-size: 11px/);
  assert.match(navigation, /scroll-snap-align: start/);
});
