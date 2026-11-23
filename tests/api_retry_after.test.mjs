import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SourceTextModule, createContext } from "node:vm";
import test from "node:test";

async function failedRequest(status, retryAfter, detail = "请求过于频繁，请稍后重试") {
  const headers = retryAfter === undefined ? {} : { "Retry-After": retryAfter };
  const context = createContext({
    sessionStorage: { getItem: () => null },
    location: { pathname: "/" },
    window: { dispatchEvent() {} },
    FormData, Event,
    fetch: async () => new Response(JSON.stringify({ detail }), { status, headers }),
  });
  const source = await readFile(new URL("../app/static/api.js", import.meta.url), "utf8");
  const module = new SourceTextModule(source, { context });
  await module.link(() => { throw new Error("Unexpected import"); });
  await module.evaluate();
  try {
    await module.namespace.api("/auth/email/code");
    assert.fail("Expected request failure");
  } catch (error) {
    return error;
  }
}

async function loadApi() {
  const context = createContext({ sessionStorage: { getItem: () => null }, location: { pathname: "/" }, window: { dispatchEvent() {} }, FormData, Event, fetch });
  const source = await readFile(new URL("../app/static/api.js", import.meta.url), "utf8");
  const module = new SourceTextModule(source, { context });
  await module.link(() => { throw new Error("Unexpected import"); });
  await module.evaluate();
  return module.namespace;
}

test("rate-limit failures expose server wait seconds for the resend countdown", async () => {
  const error = await failedRequest(429, "43");
  assert.equal(error.status, 429);
  assert.equal(error.retryAfterSeconds, 43);
});

test("rate-limit failures without a usable wait default to one minute", async () => {
  for (const value of [undefined, "invalid", "0", "-1"]) {
    assert.equal((await failedRequest(429, value)).retryAfterSeconds, 60);
  }
});

test("other failures do not disable verification code requests for a minute", async () => {
  assert.equal((await failedRequest(503, "60")).retryAfterSeconds, undefined);
});

test("validation failures name invalid fields without exposing submitted values", async () => {
  const error = await failedRequest(422, undefined, [{
    type: "missing",
    loc: ["body", "quantity"],
    msg: "Field required",
    input: { secret: "must not be shown" },
  }]);
  assert.match(error.message, /购买次数/);
  assert.match(error.message, /必填/);
  assert.doesNotMatch(error.message, /must not be shown/);
});

test("workspace identity access rejects missing user state with an actionable message", async () => {
  const api = await loadApi();
  assert.throws(() => api.requireAuthenticatedUser(null), /登录状态已失效/);
});
