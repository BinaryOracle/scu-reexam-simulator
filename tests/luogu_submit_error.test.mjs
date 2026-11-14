import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { formatLuoguSubmitError, isLuoguExtensionOutdated } from "../app/static/luogu-errors.mjs";
const contestSource = await readFile(new URL("../app/static/contest.js", import.meta.url), "utf8");

test("normalizes raw Luogu captcha failures before displaying them", () => {
  assert.match(contestSource, /formatLuoguSubmitError\(error\)/);
});

test("explains how to recover from a raw Luogu captcha error", () => {
  assert.equal(
    formatLuoguSubmitError(new Error("验证码错误")),
    "洛谷暂时未接受这次提交，需要完成安全验证。请切换到洛谷页面，按页面提示处理后回到知序重试。",
  );
});

test("hides bridge internals when the current extension opened the problem page", () => {
  const message = "洛谷返回验证码错误，自动提交未成功。已为你打开洛谷题目页（P1000）。请按页面提示手动完成验证，回到知序重新提交。";
  assert.equal(
    formatLuoguSubmitError(new Error(message)),
    "洛谷暂时未接受这次提交，需要完成安全验证。已打开本题的洛谷页面，请按页面提示处理后回到知序重试。",
  );
});

test("leaves non-captcha failures unchanged", () => {
  assert.equal(formatLuoguSubmitError(new Error("洛谷未返回提交编号。")), "洛谷未返回提交编号。");
});

test("requires an extension version that can guide captcha recovery", () => {
  assert.equal(isLuoguExtensionOutdated(undefined), true);
  assert.equal(isLuoguExtensionOutdated("1.0.0"), true);
  assert.equal(isLuoguExtensionOutdated("1.0.1"), true);
  assert.equal(isLuoguExtensionOutdated("1.0.2"), false);
  assert.equal(isLuoguExtensionOutdated("1.1.0"), false);
  assert.equal(isLuoguExtensionOutdated("unknown"), true);
  assert.match(contestSource, /isLuoguExtensionOutdated\(.*extension_version/);
});
