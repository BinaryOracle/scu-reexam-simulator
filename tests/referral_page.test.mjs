import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const html = await readFile(new URL("../app/static/index.html", import.meta.url), "utf8");
const app = await readFile(new URL("../app/static/app.js", import.meta.url), "utf8");
const credits = await readFile(new URL("../app/static/credits.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");

test("referrals have a standalone route without a duplicate profile shortcut", () => {
  assert.match(html, /data-view="referrals"/);
  assert.ok(html.indexOf('data-view="contest"') < html.indexOf('data-view="referrals"'));
  assert.doesNotMatch(html, /<section class="panel profile-referral-shortcut"|profileReferralsLink/);
  assert.match(html, /<section id="referrals"[^>]+hidden>/);
  assert.doesNotMatch(html, /id="profileReferrals"/);
  assert.match(app, /referrals: \{ label: "邀请返利", refresh: refreshReferrals \}/);
  assert.match(app, /\["home", "referrals", "training"/);
  assert.doesNotMatch(credits, /profileReferralsLink/);
});

test("email login explains that invitation codes are for first-time registration", () => {
  assert.match(html, /<summary>首次注册可填写邀请码<\/summary>/);
  assert.match(html, /仅首次注册创建账号时有效，已有账号登录无需填写。/);
  assert.match(html, /id="loginInvitationCode"/);
});

test("referrals are available to regular users and omitted from admin navigation", () => {
  const adminViews = app.match(/if \(state\.adminMode\)[\s\S]*?\? \[(.*?)\]\s*:\s*\["adminDenied"\]/)?.[1];
  assert.ok(adminViews);
  assert.doesNotMatch(adminViews, /"referrals"/);
  assert.match(app, /const views = \["home", "referrals", "training"/);
});

test("referral page presents dynamic rewards, service states, and responsive layout", () => {
  assert.match(credits, /data\.signup_reward_points/);
  assert.match(credits, /按购买时该套餐的返利比例/);
  assert.match(credits, /purchaseSummaryButton\(item/);
  assert.match(credits, /openPurchaseDetails\(item/);
  assert.doesNotMatch(credits, /套餐服务[^\n]{0,80}10%/);
  assert.match(credits, /待兑换返利/);
  assert.match(credits, /已兑换返利/);
  assert.match(styles, /\.referral-overview-grid \{[^}]*repeat\(4, minmax\(0, 1fr\)\)/);
  assert.match(styles, /\.referral-share-grid \{[^}]*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.match(styles, /\.referral-stat > strong \{[^}]*font-size: 23px/);
});
