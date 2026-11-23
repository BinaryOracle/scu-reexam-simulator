import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const credits = readFileSync(new URL("../app/static/credits.js", import.meta.url), "utf8");
const account = readFileSync(new URL("../app/static/profile-account.js", import.meta.url), "utf8");
const transfers = readFileSync(new URL("../app/static/credit-transfers.js", import.meta.url), "utf8");
const live = readFileSync(new URL("../app/static/live.js", import.meta.url), "utf8");
const html = readFileSync(new URL("../app/static/index.html", import.meta.url), "utf8");

test("card redemption history renders before optional account-security refresh", () => {
  const profile = credits.slice(credits.indexOf("export async function refreshProfile()"), credits.indexOf("export async function refreshInterviewShop()"));
  assert.ok(profile.indexOf('$("redemptionHistory").replaceChildren') < profile.indexOf("refreshAccountSettings()"));
  assert.match(profile, /try\s*\{\s*refreshAccountSettings\(\)/);
});

test("optional profile panels start hidden and become visible only after content is ready", () => {
  assert.match(html, /id="profileContribution"[^>]*hidden/);
  assert.match(html, /id="profileTransfers"[^>]*hidden/);
  assert.match(credits, /contributionRoot\.hidden\s*=\s*false/);
  assert.match(transfers, /root\.hidden\s*=\s*false/);
});

test("account settings refresh safely handles a missing authenticated user", () => {
  assert.match(account, /const user = state\.user;\s*if \(!user\) return false;/);
  assert.match(account, /profileAccountUsername"\)\.textContent = user\.username/);
  assert.match(live, /async function prepare\(lesson\)\{\s*const user=requireAuthenticatedUser\(\)/);
  assert.match(live, /user\.username\.slice/);
  assert.doesNotMatch(live, /state\.user\.username/);
});
