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

async function runResultTracker(polls, delivered, contextName) {
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
  await context.trackResultForTest(3, 4, { context: contextName, submission_id: 1, remote_submission_id: "8123" });
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

test("reports Luogu testcase pass counts for failed submissions", async () => {
  const delivered = [];
  await runResultTracker([{
    status: "Wrong Answer",
    detail: { subtasks: [{ records: [{ status: 12 }, { status: 12 }, { status: 6 }] }] },
  }], delivered);
  assert.equal(delivered.length, 1);
  assert.equal(delivered[0].detail, "通过测试用例数：2 / 3\n测试点 #1：AC\n测试点 #2：AC\n测试点 #3：WA");
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
  const activatedTabs = [];
  let executeCount = 0;
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: {
      async query() { return [{ id: 8, windowId: 2 }]; },
      async create(options) { openedTabs.push(options); },
      async update(tabId, options) { activatedTabs.push({ tabId, ...options }); },
    },
    scripting: { async executeScript({ func }) {
      executeCount += 1;
      if (func.toString().includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (func.toString().includes("meta[name=\"csrf-token\"]")) return [{ result: { error: "验证码错误", requires_manual_verification: true } }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = { chrome };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  await assert.rejects(
    context.handleRequestForTest("SUBMIT", { problem_id: "P1000", language: "python3", source: "print(1)" }, 4),
    /请在已登录的洛谷页面处理安全验证，再回到知序重新提交/,
  );
  assert.deepEqual(JSON.parse(JSON.stringify(activatedTabs)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(openedTabs)), []);
});

test("records sanitized Luogu rejection diagnostics for captcha failures", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const logs = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: {
      async query({ url }) { return Array.isArray(url) ? [{ id: 8 }] : [{ id: 12, status: "complete" }]; },
      async update() {},
    },
    scripting: { async executeScript({ func }) {
      if (func.toString().includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (func.toString().includes("csrf-token")) return [{ result: {
        error: "验证码错误", http_status: 403, error_code: "captcha_invalid",
        error_type: "security_verification", requires_manual_verification: true,
      } }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = { chrome, console: { info(...values) { logs.push(values); }, warn() {} } };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  await assert.rejects(
    context.handleRequestForTest("SUBMIT", {
      problem_id: "P1000", language: "cpp11", source: "SECRET_CODE_SHOULD_NOT_LOG",
    }, 4),
    /HTTP 403.*captcha_invalid/,
  );
  assert.match(JSON.stringify(logs), /captcha_invalid/);
  assert.doesNotMatch(JSON.stringify(logs), /SECRET_CODE_SHOULD_NOT_LOG|csrf-token-value/);
});

test("submits with the CSRF token from the existing signed-in Luogu tab", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const targets = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: { async query({ url }) {
      if (Array.isArray(url)) return [{ id: 8, status: "complete" }];
      assert.equal(url, "https://www.luogu.com.cn/problem/P1000*");
      return [{ id: 12, status: "complete" }];
    } },
    scripting: { async executeScript({ target, func }) {
      targets.push(target.tabId);
      if (func.toString().includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (func.toString().includes("meta[name=\"csrf-token\"]")) return [{ result: { id: "8123456" } }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = { chrome, setTimeout() { return 0; } };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(executable + "\nglobalThis.handleRequestForTest = handleRequest;", context);

  const result = await context.handleRequestForTest("SUBMIT", {
    problem_id: "P1000", language: "python3", source: "print(1)", submission_id: 3,
  }, 4);

  assert.equal(result.remote_submission_id, "8123456");
  assert.deepEqual(targets, [8, 8]);
});

test("uses Luogu's expected field names and captcha field in submit requests", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const requests = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: { async query() { return [{ id: 8, status: "complete" }]; } },
    scripting: { async executeScript({ args = [], func }) {
      const text = func.toString();
      if (text.includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (text.includes("/fe/api/problem/submit/")) return [{ result: await func(...args) }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = {
    chrome,
    document: { querySelector() { return { content: "csrf-token-value" }; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, status: 200, async json() { return { data: { record: { id: "8123456" } } }; } };
    },
    setTimeout() { return 0; },
  };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  await context.handleRequestForTest("SUBMIT", {
    problem_id: "P1000", language: "python3", source: "print(1)",
  }, 4);

  assert.equal(requests.length, 1);
  assert.deepEqual(JSON.parse(requests[0].options.body), {
    code: "print(1)", lang: 7, enableO2: 0,
  });
  assert.equal(requests[0].options.headers["X-CSRF-TOKEN"], "csrf-token-value");
  assert.equal(requests[0].options.headers["X-Requested-With"], "XMLHttpRequest");
});

test("returns a sanitized captcha image challenge when Luogu rejects the empty captcha", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const requests = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: { async query() { return [{ id: 8, status: "complete" }]; } },
    scripting: { async executeScript({ args = [], func }) {
      const text = func.toString();
      if (text.includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (text.includes("/fe/api/problem/submit/")) return [{ result: await func(...args) }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = {
    chrome,
    document: { querySelector() { return { content: "csrf-token-value" }; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      if (url.startsWith("/fe/api/problem/submit/"))
        return { ok: false, status: 403, async json() { return { errorCode: 403, errorMessage: "验证码错误" }; } };
      return {
        ok: true,
        status: 200,
        headers: { get(name) { return name === "content-type" ? "image/png" : null; } },
        async arrayBuffer() { return Uint8Array.from([137, 80, 78, 71]).buffer; },
      };
    },
    setTimeout() { return 0; },
  };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  const result = await context.handleRequestForTest("SUBMIT", {
    problem_id: "P1000", language: "python3", source: "print(1)",
  }, 4);

  assert.equal(result.captcha_required, true);
  assert.deepEqual(JSON.parse(JSON.stringify(result.captcha_image)), [137, 80, 78, 71]);
  assert.equal(result.captcha_mime_type, "image/png");
  assert.equal(requests[0].url, "/fe/api/problem/submit/P1000");
  assert.match(requests[1].url, /^\/api\/verify\/captcha\?_t=\d+$/);
  assert.equal(requests[1].options.cache, "no-store");
  assert.equal(requests[1].options.credentials, "include");
  assert.equal(requests[1].options.headers["X-CSRF-TOKEN"], "csrf-token-value");
});

test("forwards a user-entered captcha to Luogu without logging it", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  let submittedBody;
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: { async query() { return [{ id: 8, status: "complete" }]; } },
    scripting: { async executeScript({ args = [], func }) {
      const text = func.toString();
      if (text.includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (text.includes("/fe/api/problem/submit/")) return [{ result: await func(...args) }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = {
    chrome,
    document: { querySelector() { return { content: "csrf-token-value" }; } },
    fetch: async (_url, options) => {
      submittedBody = JSON.parse(options.body);
      return { ok: true, status: 200, async json() { return { data: { record: { id: "8123456" } } }; } };
    },
    setTimeout() { return 0; },
  };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);

  await context.handleRequestForTest("SUBMIT", {
    problem_id: "P1000", language: "python3", source: "print(1)", captcha: "A7K2",
  }, 4);

  assert.deepEqual(JSON.parse(JSON.stringify(submittedBody)), {
    code: "print(1)", lang: 7, enableO2: 0, captcha: "A7K2",
  });
});

test("maps each workspace language to its Luogu language id", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  // Luogu /_lfe/config, version 74d532c6c7861bfe, checked 2026-11-14.
  for (const [language, expectedId] of [["cpp11", 4], ["c", 2], ["python3", 7], ["java", 8], ["go", 14]]) {
    let submittedLanguageId;
    const chrome = {
      runtime: {
        onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} },
        getManifest() { return { version: "1.1.0" }; },
      },
      storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
      tabs: { async query() { return [{ id: 12, status: "complete" }]; }, async sendMessage() {} },
      scripting: { async executeScript({ args = [], func }) {
        const text = func.toString();
        if (text.includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
        if (text.includes("csrf-token")) {
          submittedLanguageId = args[2];
          return [{ result: { id: "8123456" } }];
        }
        return [{ result: { loggedIn: true, username: "candidate" } }];
      } },
    };
    const context = { chrome, setTimeout() { return 0; }, clearTimeout() {} };
    const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
      'const APP_ORIGIN = "http://127.0.0.1:8000";');
    runInNewContext(`${executable}\nglobalThis.handleRequestForTest = handleRequest;`, context);
    await context.handleRequestForTest("SUBMIT", { problem_id: "P1000", language, source: "code" }, 4);
    assert.equal(submittedLanguageId, expectedId, `${language} should use Luogu language ${expectedId}`);
  }
});

test("submits through an existing Luogu tab without opening or activating a problem page", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const openedTabs = [];
  const queriedUrls = [];
  const scriptTargets = [];
  const activatedTabs = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: {
      async query({ url }) {
        queriedUrls.push(url);
        if (Array.isArray(url)) return [{ id: 8, status: "complete" }];
        return [];
      },
      async create(options) { openedTabs.push(options); return { id: 19, status: "complete" }; },
      async get(tabId) { return { id: tabId, status: "complete" }; },
      async update(tabId, options) { activatedTabs.push({ tabId, ...options }); },
    },
    scripting: { async executeScript({ target, func }) {
      scriptTargets.push(target.tabId);
      if (func.toString().includes("meta[name=\"csrf-token\"]")) return [{ result: { id: "8123456" } }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = { chrome, setTimeout() { return 0; } };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(executable + "\nglobalThis.handleRequestForTest = handleRequest;", context);

  const result = await context.handleRequestForTest("SUBMIT", {
    problem_id: "P1000", language: "python3", source: "print(1)", submission_id: 3,
  }, 4);

  assert.equal(result.remote_submission_id, "8123456");
  assert.deepEqual(JSON.parse(JSON.stringify(openedTabs)), []);
  assert.deepEqual(JSON.parse(JSON.stringify(activatedTabs)), []);
  assert.deepEqual(scriptTargets, [8, 8]);
});

test("reports the installed extension version during connection checks", async () => {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const manifest = JSON.parse(await readFile(new URL("../browser-extension/manifest.json", import.meta.url), "utf8"));
  assert.equal(manifest.version, "1.1.5");
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
    extension_version: "1.1.5",
  });
});

async function runInjectedSubmit(fetchResponse) {
  const source = await readFile(new URL("../browser-extension/background.js", import.meta.url), "utf8");
  const requests = [];
  const activated = [];
  const chrome = {
    runtime: { onInstalled: { addListener() {} }, onStartup: { addListener() {} }, onMessage: { addListener() {} } },
    storage: { local: { async get() { return {}; }, async set() {}, async remove() {} } },
    tabs: {
      async query() { return [{ id: 8, status: "complete" }]; },
      async update(tabId) { activated.push(tabId); },
    },
    scripting: { async executeScript({ args = [], func }) {
      if (func.toString().includes("expectedPath")) return [{ result: { ready: true, loggedIn: true, username: "candidate" } }];
      if (func.toString().includes("/fe/api/problem/submit/")) return [{ result: await func(...args) }];
      return [{ result: { loggedIn: true, username: "candidate" } }];
    } },
  };
  const context = {
    chrome,
    document: { querySelector() { return { content: "csrf-token-value" }; } },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return fetchResponse(url, options);
    },
    console: { info() {}, warn() {} },
    setTimeout() { return 0; },
  };
  const executable = source.replace('import { APP_ORIGIN } from "./extension-config.js";',
    'const APP_ORIGIN = "http://127.0.0.1:8000";');
  runInNewContext(`${executable}\nglobalThis.submit = handleRequest;`, context);
  return { requests, activated, submit: () => context.submit("SUBMIT", {
    problem_id: "P1001", language: "cpp11", source: "int main(){}",
  }, 4) };
}

test("accepts the top-level rid returned by the current Luogu client", async () => {
  const bridge = await runInjectedSubmit(async () => ({
    ok: true, status: 200, async json() { return { rid: 12345678 }; },
  }));
  assert.equal((await bridge.submit()).remote_submission_id, "12345678");
  assert.equal(bridge.requests.length, 1);
});

test("leaves interactive verification to Luogu instead of fetching an unrelated image", async () => {
  const bridge = await runInjectedSubmit(async () => ({
    ok: false, status: 403, async json() { return {
      errorCode: 403, errorMessage: "验证码错误",
      errorType: "Luogu\\CaptchaNotMatchException",
      errorData: { interactive: { type: "YIDUN", state: "private-state" } },
    }; },
  }));
  await assert.rejects(bridge.submit(), /处理安全验证/);
  assert.equal(bridge.requests.length, 1, "interactive verification must not fetch an IMAGE captcha");
  assert.deepEqual(bridge.activated, []);
});

test("does not forward oversized captcha images across the bridge", async () => {
  const bridge = await runInjectedSubmit(async url => url.includes("/submit/") ? {
    ok: false, status: 403, async json() { return { errorMessage: "验证码错误" }; },
  } : {
    ok: true, headers: { get() { return "image/png"; } },
    async arrayBuffer() { return new Uint8Array(100001).buffer; },
  });
  await assert.rejects(bridge.submit(), /处理安全验证/);
});

test("shows actionable guidance for a non-JSON security response", async () => {
  const bridge = await runInjectedSubmit(async () => ({
    ok: false, status: 403, async json() { throw new SyntaxError("HTML response"); },
  }));
  await assert.rejects(bridge.submit(), /HTTP 403.*处理安全验证/);
  assert.deepEqual(bridge.activated, []);
});

test("preserves compiler diagnostics when no testcases were run", async () => {
  const delivered = [];
  await runResultTracker([{status: "Compile Error", detail: {compileResult: {message: "main.cpp:1: error: expected ';'"}}}], delivered);
  assert.match(delivered[0].detail, /main.cpp:1: error/);
  assert.match(delivered[0].detail, /未运行测试用例/);
});

test("counts testcases with nested metrics without counting a subtask verdict", async () => {
  const delivered = [];
  await runResultTracker([{status: "Wrong Answer", detail: {subtasks: [{status: 6, testCases: [
    {status: 12, metrics: {time: 1}}, {status: 6, metrics: {time: 2}}
  ]}]}}], delivered);
  assert.match(delivered[0].detail, /通过测试用例数：1 \/ 2/);
});


test("keeps coding callbacks isolated from contest submissions", async () => {
  const delivered = [];
  await runResultTracker([{status: "Accepted"}], delivered, "coding");
  assert.equal(delivered[0].context, "coding");
});
