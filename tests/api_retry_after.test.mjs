import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { SourceTextModule, createContext } from "node:vm";
import test from "node:test";

async function failedRequest(status, retryAfter) {
  const headers = retryAfter === undefined ? {} : { "Retry-After": retryAfter };
  const context = createContext({
    sessionStorage: { getItem: () => null },
    location: { pathname: "/" },
    window: { dispatchEvent() {} },
    FormData, Event,
    fetch: async () => new Response(JSON.stringify({ detail: "请求过于频繁，请稍后重试" }), { status, headers }),
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
