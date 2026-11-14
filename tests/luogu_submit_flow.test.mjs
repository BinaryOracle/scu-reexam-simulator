import assert from "node:assert/strict";
import test from "node:test";
import { submitWithLuoguVerification } from "../app/static/luogu-submit.mjs";

const payload = { problem_id: "P1001", language: "cpp11", source: "int main(){}" };
const accepted = { remote_submission_id: "12345", status: "Submitted" };
const challenge = { captcha_required: true, captcha_image: [137, 80], captcha_mime_type: "image/png" };

test("submits once when no verification is requested", async () => {
  const sent = [];
  const result = await submitWithLuoguVerification(payload, {
    send: async value => { sent.push(value); return accepted; },
    requestCaptcha: () => { throw new Error("no captcha should be shown"); },
  });
  assert.equal(result, accepted);
  assert.deepEqual(sent, [payload]);
});

test("retries with the human-entered answer and the same code", async () => {
  const sent = [];
  const result = await submitWithLuoguVerification(payload, {
    send: async value => { sent.push(value); return sent.length === 1 ? challenge : accepted; },
    requestCaptcha: async value => { assert.equal(value, challenge); return "ABCD"; },
  });
  assert.equal(result, accepted);
  assert.deepEqual(sent, [payload, { ...payload, captcha: "ABCD" }]);
});

test("does not retry when the user cancels verification", async () => {
  let sends = 0;
  await assert.rejects(submitWithLuoguVerification(payload, {
    send: async () => { sends++; return challenge; },
    requestCaptcha: async () => null,
  }), /已取消验证码，本次提交未被洛谷受理/);
  assert.equal(sends, 1);
});

test("offers a new human challenge after an incorrect answer", async () => {
  const sent = [];
  const hints = [];
  const result = await submitWithLuoguVerification(payload, {
    send: async value => { sent.push(value); return sent.length < 3 ? challenge : accepted; },
    requestCaptcha: async (_challenge, hint) => { hints.push(hint); return hints.length === 1 ? "WRONG" : "ABCD"; },
  });
  assert.equal(result, accepted);
  assert.equal(hints[0], "");
  assert.match(hints[1], /验证码未通过/);
  assert.deepEqual(sent[2], { ...payload, captcha: "ABCD" });
});

test("does not blindly retry a network error with unknown submission outcome", async () => {
  let sends = 0;
  await assert.rejects(submitWithLuoguVerification(payload, {
    send: async () => { sends++; throw new Error("网络异常，提交结果未知"); },
    requestCaptcha: async () => "ABCD",
  }), /提交结果未知/);
  assert.equal(sends, 1);
});
