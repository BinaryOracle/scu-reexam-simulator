import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { runInNewContext } from "node:vm";
import test from "node:test";

test("forwards extension evaluation updates into the app page", async () => {
  const listeners = new Map();
  const runtimeListeners = [];
  const dispatched = [];
  const source = await readFile(new URL("../browser-extension/app-content.js", import.meta.url), "utf8");
  const window = {
    __scuLuoguBridgeInstalled: false,
    addEventListener: (type, listener) => listeners.set(type, listener),
    dispatchEvent: event => dispatched.push(event),
  };
  const chrome = { runtime: { onMessage: { addListener: listener => runtimeListeners.push(listener) } } };
  runInNewContext(source, { window, chrome, location: { origin: "https://exam.example" }, CustomEvent });

  assert.equal(runtimeListeners.length, 1, "the app content script must subscribe to extension updates");
  runtimeListeners[0]({
    type: "SCU_LUOGU_STATUS",
    payload: { submission_id: 4, remote_submission_id: "8123456", status: "Accepted", detail: "通过" },
  });

  assert.equal(dispatched.length, 1);
  assert.equal(dispatched[0].type, "scu-luogu-status");
  assert.deepEqual(JSON.parse(JSON.stringify(dispatched[0].detail)), {
    submission_id: 4,
    remote_submission_id: "8123456",
    status: "Accepted",
    detail: "通过",
  });
});

test("forwards extension request failures as bridge errors", async () => {
  const listeners = new Map();
  const posted = [];
  const source = await readFile(new URL("../browser-extension/app-content.js", import.meta.url), "utf8");
  const window = {
    __scuLuoguBridgeInstalled: false,
    addEventListener: (type, listener) => listeners.set(type, listener),
    postMessage: message => posted.push(message),
  };
  const chrome = {
    runtime: {
      onMessage: { addListener() {} },
      sendMessage: async () => ({ error: "请先登录洛谷。" }),
    },
  };
  runInNewContext(source, { window, chrome, location: { origin: "https://exam.example" }, CustomEvent });
  await listeners.get("message")({
    source: window,
    origin: "https://exam.example",
    data: { source: "scu-luogu-bridge", type: "SUBMIT", requestId: "request-1", payload: { submission_id: 9 } },
  });

  assert.equal(posted.length, 1);
  assert.equal(posted[0].error, "请先登录洛谷。");
  assert.equal(posted[0].payload, undefined);
});

async function runResultTracker(polls, delivered) {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    scripting: { async executeScript() {
      const next = polls.shift();
      if (next instanceof Error) throw next;
      return [{ result: next }];
    } },
    tabs: { async sendMessage(_tabId, message) { delivered.push(message.payload); } },
  };
  const context = {
    chrome,
    setTimeout(callback) { callback(); return 0; },
    clearTimeout() {},
  };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.trackResultForTest = trackResult;`, context);
  await context.trackResultForTest(3, 4, { submission_id: 1, remote_submission_id: "8123" });
}

test("does not publish repeated Luogu judging states", async () => {
  const delivered = [];
  const polls = [
    { status: "Judging" },
    { status: "Judging" },
    { status: "Judging" },
    { status: "Judging" },
    { status: "Accepted" },
  ];
  await runResultTracker(polls, delivered);
  assert.deepEqual(delivered.map(item => item.status), ["Judging", "Accepted"]);
});

test("retries a transient Luogu record read failure", async () => {
  const delivered = [];
  const polls = [new Error("temporary read failure"), { status: "Accepted" }];
  await runResultTracker(polls, delivered);
  assert.deepEqual(delivered.map(item => item.status), ["Accepted"]);
});

test("guides the user through Luogu captcha verification instead of hiding the cause", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const openedTabs = [];
  let executeCount = 0;
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: {
      async query() { return [{ id: 8, windowId: 2 }]; },
      async create(options) { openedTabs.push(options); },
    },
    scripting: { async executeScript() {
      executeCount += 1;
      return [{ result: executeCount === 1
        ? { loggedIn: true, username: "candidate" }
        : { error: "验证码错误", requires_manual_verification: true } }];
    } },
  };
  const context = { chrome };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  await assert.rejects(
    context.handleRequestForTest("SUBMIT", { problem_id: "P1000", language: "python3", source: "print(1)" }, 4),
    /已为你打开洛谷题目页.*手动完成验证.*回到知序重新提交/,
  );
  assert.deepEqual(JSON.parse(JSON.stringify(openedTabs)), [{ url: "https://www.luogu.com.cn/problem/P1000", active: true }]);
});

test("reports the installed extension version during connection checks", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const manifest = JSON.parse(await readFile(new URL("../browser-extension/manifest.json", import.meta.url), "utf8"));
  assert.equal(manifest.version, "1.0.2");
  const chrome = {
    runtime: {
      getManifest() { return manifest; },
      onInstalled: { addListener() {} },
      onStartup: { addListener() {} },
      onMessage: { addListener() {} },
    },
    storage: { local: { async get() { return {}; }, async remove() {} } },
    tabs: { async query() { return [{ id: 8 }]; } },
    scripting: { async executeScript() { return [{ result: { loggedIn: true, username: "candidate" } }]; } },
  };
  const context = { chrome };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(executable + "\nglobalThis.handleRequestForTest = handleRequest;", context);

  const response = await context.handleRequestForTest("PING", {}, 4);
  assert.deepEqual(JSON.parse(JSON.stringify(response)), {
    connected: true,
    account: "candidate",
    extension_version: "1.0.2",
  });
});
