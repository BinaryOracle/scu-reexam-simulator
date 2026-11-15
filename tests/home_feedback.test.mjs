import assert from "node:assert/strict";
import test from "node:test";
import { homeLayoutErrorMessage } from "../app/static/home-feedback.mjs";

test("home layout failures give a recovery hint without exposing server details", () => {
  assert.equal(homeLayoutErrorMessage(new Error("Not Found")), "备考内容暂时无法加载，请稍后重试。");
  assert.equal(homeLayoutErrorMessage(new TypeError("Failed to fetch")), "网络连接失败，请检查网络后重试。");
  assert.equal(homeLayoutErrorMessage(Object.assign(new Error("token expired"), { status: 401 })), "登录状态已失效，请重新登录后再试。");
  assert.equal(homeLayoutErrorMessage(Object.assign(new Error("forbidden"), { status: 403 })), "当前账号暂不可访问备考内容，请联系管理员确认权限。");
});
