import { APP_ORIGIN } from "./extension-config.js";

const LUOGU_PATTERNS = ["https://www.luogu.com.cn/*"];
// Luogu /_lfe/config CodeLanguage (74d532c6c7861bfe, 2026-11-14).
const LUOGU_LANGUAGE_IDS = { cpp11: 4, c: 2, python3: 7, java: 8, go: 14 };
const PENDING_STATUS_PREFIX = "pendingLuoguStatus:";

async function publishStatus(appTabId, payload) {
  const key = `${PENDING_STATUS_PREFIX}${payload.remote_submission_id}`;
  try {
    await chrome.tabs.sendMessage(appTabId, { type: "SCU_LUOGU_STATUS", payload });
    await chrome.storage.local.remove(key);
  } catch (error) {
    await chrome.storage.local.set({ [key]: payload });
  }
}

async function flushPendingStatuses(appTabId) {
  const values = await chrome.storage.local.get(null);
  for (const [key, payload] of Object.entries(values)) {
    if (!key.startsWith(PENDING_STATUS_PREFIX)) continue;
    try {
      await chrome.tabs.sendMessage(appTabId, { type: "SCU_LUOGU_STATUS", payload });
      await chrome.storage.local.remove(key);
    } catch (error) {
      break;
    }
  }
}

async function injectAppBridge(origin) {
  const registered = await chrome.scripting.getRegisteredContentScripts({ ids: ["scu-app-bridge"] });
  if (registered.length) await chrome.scripting.unregisterContentScripts({ ids: ["scu-app-bridge"] });
  await chrome.scripting.registerContentScripts([{
    id: "scu-app-bridge",
    matches: [`${origin}/*`],
    js: ["app-content.js"],
    runAt: "document_idle",
    persistAcrossSessions: true,
  }]);
  const tabs = await chrome.tabs.query({ url: `${origin}/*` });
  for (const tab of tabs) if (tab.id) await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["app-content.js"] });
}

chrome.runtime.onInstalled.addListener(() => void injectAppBridge(APP_ORIGIN));
chrome.runtime.onStartup.addListener(() => void injectAppBridge(APP_ORIGIN));

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "SCU_BRIDGE_REQUEST" && sender.tab?.id) {
    void handleRequest(message.action, message.payload, sender.tab.id).then(sendResponse)
      .catch(error => sendResponse({ error: error.message }));
    return true;
  }
  return false;
});

async function findLoggedInTab() {
  const tabs = await chrome.tabs.query({ url: LUOGU_PATTERNS });
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      const [result] = await chrome.scripting.executeScript({
        target: { tabId: tab.id }, world: "MAIN",
        func: () => {
          const context = document.querySelector("#lentille-context");
          if (!context) return null;
          try {
            const data = JSON.parse(context.textContent);
            return data.user ? { loggedIn: true, username: data.user.name || data.user.username || data.user.uid || "洛谷用户" } : { loggedIn: false };
          } catch { return null; }
        },
      });
      if (result?.result?.loggedIn) return { tab, account: result.result.username };
    } catch { /* Tab may close or navigate while login state is checked. */ }
  }
  return null;
}

async function readProblemPage(tabId, problemId) {
  const [page] = await chrome.scripting.executeScript({
    target: { tabId }, world: "MAIN", args: [problemId],
    func: expectedProblemId => {
      const expectedPath = `/problem/${expectedProblemId}`;
      if (window.location.pathname !== expectedPath) return null;
      const context = document.querySelector("#lentille-context");
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
      if (!context || !csrf) return { ready: false };
      try {
        const data = JSON.parse(context.textContent);
        return data.user
          ? { ready: true, loggedIn: true, username: data.user.name || data.user.username || data.user.uid || "洛谷用户" }
          : { ready: true, loggedIn: false };
      } catch { return { ready: false }; }
    },
  });
  return page.result;
}

async function waitForTabLoad(tabId) {
  for (let attempt = 0; attempt < 40; attempt++) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error("洛谷题目页加载超时，请稍后重试。");
}

async function findProblemTab(problemId) {
  const url = `https://www.luogu.com.cn/problem/${encodeURIComponent(problemId)}`;
  const tabs = await chrome.tabs.query({ url: `${url}*` });
  for (const tab of tabs) {
    if (!tab.id) continue;
    try {
      const page = await readProblemPage(tab.id, problemId);
      if (page?.ready && page.loggedIn) return { tab, account: page.username };
    } catch { /* The page may navigate or close during inspection. */ }
  }
  return null;
}

async function handleRequest(type, payload = {}, appTabId) {
  if (type === "PING") {
    await flushPendingStatuses(appTabId);
    const found = await findLoggedInTab();
    return found
      ? { connected: true, account: found.account, extension_version: chrome.runtime.getManifest().version }
      : { connected: false, reason: "请在浏览器中打开洛谷并登录，再返回此处检测。", extension_version: chrome.runtime.getManifest().version };
  }
  if (type !== "SUBMIT") throw new Error("不支持的桥接操作");
  if (!/^[A-Z]{1,4}[0-9]{1,8}$/.test(payload.problem_id || "")) throw new Error("洛谷题号格式无效。");
  if (!Object.hasOwn(LUOGU_LANGUAGE_IDS, payload.language) || typeof payload.source !== "string" || payload.source.length < 1 || payload.source.length > 30000)
    throw new Error("编程语言不受支持，或代码长度超过 30000 字符。");
  if (payload.captcha != null && (typeof payload.captcha !== "string" || payload.captcha.length > 16))
    throw new Error("验证码格式无效，请重新输入。");
  const signedIn = await findLoggedInTab();
  if (!signedIn) throw new Error("洛谷登录状态已失效，请重新登录后提交。");
  let problemPage = await findProblemTab(payload.problem_id);
  if (!problemPage) {
    const tab = await chrome.tabs.create({
      url: `https://www.luogu.com.cn/problem/${encodeURIComponent(payload.problem_id)}`,
      active: false,
    });
    await waitForTabLoad(tab.id);
    const page = await readProblemPage(tab.id, payload.problem_id);
    if (!page?.ready || !page.loggedIn) {
      await chrome.tabs.update(tab.id, { active: true });
      throw new Error("已打开本题的洛谷页面，但页面尚未准备好。请确认账号仍已登录且题目页加载完成，再回到知序重试。");
    }
    problemPage = { tab, account: page.username };
  }
  const [submitted] = await chrome.scripting.executeScript({
    target: { tabId: problemPage.tab.id }, world: "MAIN",
    args: [payload.problem_id, payload.source, LUOGU_LANGUAGE_IDS[payload.language], payload.captcha?.trim() || ""],
    func: async (problemId, source, languageId, captcha) => {
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
      if (!csrf) return { error: "洛谷页面缺少 CSRF 校验信息，请刷新洛谷页面后重试。" };
      const payload = { code: source, lang: languageId, enableO2: 0 };
      if (captcha) payload.captcha = captcha;
      const response = await fetch(`/fe/api/problem/submit/${encodeURIComponent(problemId)}`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-TOKEN": csrf, "X-Requested-With": "XMLHttpRequest" },
        body: JSON.stringify(payload),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || body?.errorCode) {
        const error = String(body?.errorMessage || `洛谷拒绝提交（HTTP ${response.status}）。`);
        const captchaError = /captcha|验证码|人机验证|安全验证/i.test(error)
          || /\\(?:CaptchaNotMatchException|InvalidCaptchaException)$/.test(body?.errorType || "");
        const interactive = body?.errorData?.interactive;
        const requiresManualVerification = captchaError || (!body && response.status === 403);
        if (captchaError && !interactive) {
          try {
            const challenge = await fetch(`/api/verify/captcha?_t=${Date.now()}`, {
              credentials: "include", cache: "no-store",
              headers: { "X-CSRF-TOKEN": csrf },
            });
            const mimeType = (challenge.headers.get("content-type") || "").split(";")[0].trim().toLowerCase();
            if (challenge.ok && ["image/png", "image/jpeg", "image/gif", "image/webp"].includes(mimeType)) {
              const bytes = new Uint8Array(await challenge.arrayBuffer());
              if (bytes.length > 0 && bytes.length <= 100000) return {
                captcha_required: true,
                captcha_image: Array.from(bytes),
                captcha_mime_type: mimeType,
              };
            }
          } catch (error) {
            console.info("[SCU Luogu bridge] captcha image unavailable", { category: "captcha_image_unavailable" });
          }
        }
        return {
          error,
          http_status: response.status,
          error_code: body?.errorCode == null ? "" : String(body.errorCode).slice(0, 64),
          error_type: body?.errorType == null ? "" : String(body.errorType).slice(0, 64),
          requires_manual_verification: requiresManualVerification,
        };
      }
      const id = body?.rid ?? body?.data?.rid ?? body?.data?.record?.id ?? body?.data?.id;
      return /^[1-9]\d*$/.test(String(id)) ? { id: String(id) }
        : { error: "洛谷没有返回提交编号，提交结果尚未确认。请先在洛谷查看提交记录，避免重复提交。" };
    },
  });
  if (submitted.result?.captcha_required) return submitted.result;
  if (submitted.result?.requires_manual_verification || /captcha|验证码|人机验证|安全验证/i.test(submitted.result?.error || "")) {
    const diagnostic = {
      problem_id: payload.problem_id,
      http_status: submitted.result?.http_status || 0,
      error_code: submitted.result?.error_code || "unknown",
      error_type: submitted.result?.error_type || "unknown",
      category: "manual_verification_required",
    };
    console.info("[SCU Luogu bridge] submission rejected", diagnostic);
    let opened = false;
    try {
      await chrome.tabs.update(problemPage.tab.id, { active: true });
      opened = true;
    } catch (openError) {
      console.warn("Unable to open the Luogu problem page for manual verification.", openError);
      try {
        await chrome.tabs.create({ url: `https://www.luogu.com.cn/problem/${encodeURIComponent(payload.problem_id)}`, active: true });
        opened = true;
      } catch (fallbackError) {
        console.warn("Unable to open a Luogu page for manual verification.", fallbackError);
      }
    }
    const page = opened ? `已切换到洛谷题目页（${payload.problem_id}）` : `请切换到洛谷题目页（${payload.problem_id}）`;
    const diagnosticText = [
      diagnostic.http_status ? `HTTP ${diagnostic.http_status}` : "",
      diagnostic.error_code !== "unknown" ? `错误码 ${diagnostic.error_code}` : "",
    ].filter(Boolean).join("，");
    const diagnosticSuffix = diagnosticText ? `（${diagnosticText}）` : "";
    throw new Error(`洛谷返回“${submitted.result?.error || "安全验证"}”${diagnosticSuffix}，自动提交未成功。${page}。请确认账号已登录，并按洛谷页面提示手动完成验证；若题目页未显示验证，请在该题的洛谷提交区域查看页面提示。处理后回到知序重新提交。`);
  }
  const remoteId = submitted.result?.id;
  if (!remoteId) throw new Error(submitted.result?.error || "洛谷提交失败。");
  void trackResult(problemPage.tab.id, appTabId, { ...payload, remote_submission_id: remoteId });
  return { remote_submission_id: remoteId, status: "Submitted", detail: `洛谷提交 #${remoteId}` };
}

async function trackResult(luoguTabId, appTabId, submission) {
  let prior = "Submitted";
  let consecutiveErrors = 0;
  let failureReported = false;
  for (let attempt = 0; attempt < 120; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 5000));
    try {
      const [response] = await chrome.scripting.executeScript({
        target: { tabId: luoguTabId }, world: "MAIN", args: [submission.remote_submission_id],
        func: async id => {
          const response = await fetch(`/record/${encodeURIComponent(id)}`, { credentials: "include" });
          if (!response.ok) return null;
          const html = await response.text();
          const match = html.match(/<script id="lentille-context" type="application\/json">([\s\S]*?)<\/script>/);
          if (!match) return null;
          const context = JSON.parse(match[1]);
          const record = context.data?.record;
          if (!record) return null;
          const statuses = { 0: "Judging", 1: "Judging", 2: "Compile Error", 3: "Output Limit Exceeded", 4: "Memory Limit Exceeded", 5: "Time Limit Exceeded", 6: "Wrong Answer", 7: "Runtime Error", 11: "System Error", 12: "Accepted", 14: "Wrong Answer" };
          const status = statuses[record.status];
          return status
            ? { status, detail: status === "Accepted" ? "Accepted" : "" }
            : { status: "System Error", detail: `洛谷返回暂不支持的状态码 ${record.status}` };
        },
      });
      const result = response.result;
      if (!result) continue;
      consecutiveErrors = 0;
      failureReported = false;
      if (result.status === prior) continue;
      prior = result.status;
      await publishStatus(appTabId, { submission_id: submission.submission_id, remote_submission_id: submission.remote_submission_id, ...result });
      if (!["Judging", "Submitted"].includes(prior)) return;
    } catch (error) {
      consecutiveErrors += 1;
      if (consecutiveErrors >= 3 && !failureReported) {
        failureReported = true;
        await publishStatus(appTabId, {
          submission_id: submission.submission_id,
          remote_submission_id: submission.remote_submission_id,
          status: prior,
          detail: "暂时无法读取洛谷评测状态，插件仍在重试。",
        });
      }
    }
  }
  await publishStatus(appTabId, {
    submission_id: submission.submission_id,
    remote_submission_id: submission.remote_submission_id,
    status: prior,
    detail: "洛谷尚未返回最终结果。重新检测洛谷连接后可同步后续状态。",
  });
}
