import { APP_ORIGIN } from "./extension-config.js";

const LUOGU_PATTERNS = ["https://www.luogu.com.cn/*"];
// Luogu /_lfe/config CodeLanguage (74d532c6c7861bfe, 2026-11-14).
const LUOGU_LANGUAGE_IDS = { cpp11: 4, c: 2, python3: 7, java: 8, go: 14 };
const PENDING_STATUS_PREFIX = "pendingLuoguStatus:";

function summarizeLuoguTestcases(detail) {
  if (!detail) return "";
  if (typeof detail === "string") {
    try { detail = JSON.parse(detail); }
    catch { return ""; }
  }
  const cases = [];
  const verdicts = new Map([[2, "CE"], [3, "OLE"], [4, "MLE"], [5, "TLE"], [6, "WA"], [7, "RE"], [11, "SE"], [12, "AC"], [14, "WA"]]);
  const visit = value => {
    if (Array.isArray(value)) {
      for (const item of value) visit(item);
      return;
    }
    if (!value || typeof value !== "object") return;
    const before = cases.length;
    for (const item of Object.values(value)) {
      if (item && typeof item === "object") visit(item);
    }
    const status = value.status ?? value.result ?? value.state;
    const statusCode = Number(status);
    const statusText = String(status).toLocaleLowerCase();
    const verdict = verdicts.get(statusCode) || ({ accepted: "AC", "wrong answer": "WA", "runtime error": "RE", "time limit exceeded": "TLE", "memory limit exceeded": "MLE", "output limit exceeded": "OLE", "compile error": "CE" })[statusText];
    if (cases.length === before && verdict) {
      cases.push(verdict);
    }
  };
  visit(detail);
  if (!cases.length) return "";
  const passed = cases.filter(verdict => verdict === "AC").length;
  const summary = `通过测试用例数：${passed} / ${cases.length}`;
  const lines = [];
  let length = summary.length;
  for (const [index, verdict] of cases.entries()) {
    const line = `测试点 #${index + 1}：${verdict}`;
    if (length + line.length + 1 > 9800) break;
    lines.push(line);
    length += line.length + 1;
  }
  if (lines.length < cases.length) lines.push(`另有 ${cases.length - lines.length} 个测试点未展开`);
  return [summary, ...lines].join("\n");
}

function evaluationDetail(status, detail) {
  const summary = summarizeLuoguTestcases(detail);
  if (summary) return summary;
  if (status === "Accepted") return "全部测试用例通过。";
  if (status !== "Compile Error") return `${status}。洛谷暂未提供测试点明细，无法统计通过数。`;
  let parsed = detail;
  if (typeof detail === "string") {
    try { parsed = JSON.parse(detail); } catch { /* Plain compiler output is already readable. */ }
  }
  const messages = [];
  const visit = value => {
    if (typeof value === "string") { messages.push(value); return; }
    if (!value || typeof value !== "object") return;
    for (const [key, child] of Object.entries(value)) {
      if (/message|error|output|log|detail|compile|stderr/i.test(key)) visit(child);
    }
  };
  visit(parsed);
  return `编译错误，未运行测试用例。\n${messages.join("\n").slice(0, 9700) || "洛谷暂未提供编译器错误详情。"}`;
}

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

async function handleRequest(type, payload = {}, appTabId) {
  if (type === "PING") {
    await flushPendingStatuses(appTabId);
    const found = await findLoggedInTab();
    return found
      ? { connected: true, account: found.account, extension_version: chrome.runtime.getManifest().version }
      : { connected: false, reason: "请在浏览器中打开洛谷并登录，再返回此处检测。", extension_version: chrome.runtime.getManifest().version };
  }
  if (type !== "SUBMIT") throw new Error("不支持的桥接操作");
  if (!/^[A-Z][A-Z0-9_-]{0,31}$/.test(payload.problem_id || "")) throw new Error("洛谷题号格式无效。");
  if (!Object.hasOwn(LUOGU_LANGUAGE_IDS, payload.language) || typeof payload.source !== "string" || payload.source.length < 1 || payload.source.length > 30000)
    throw new Error("编程语言不受支持，或代码长度超过 30000 字符。");
  if (payload.captcha != null && (typeof payload.captcha !== "string" || payload.captcha.length > 16))
    throw new Error("验证码格式无效，请重新输入。");
  const signedIn = await findLoggedInTab();
  if (!signedIn) throw new Error("洛谷登录状态已失效，请重新登录后提交。");
  const [submitted] = await chrome.scripting.executeScript({
    target: { tabId: signedIn.tab.id }, world: "MAIN",
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
    const diagnosticText = [
      diagnostic.http_status ? `HTTP ${diagnostic.http_status}` : "",
      diagnostic.error_code !== "unknown" ? `错误码 ${diagnostic.error_code}` : "",
    ].filter(Boolean).join("，");
    const diagnosticSuffix = diagnosticText ? `（${diagnosticText}）` : "";
    throw new Error(`洛谷返回“${submitted.result?.error || "安全验证"}”${diagnosticSuffix}，自动提交未成功。请在已登录的洛谷页面处理安全验证，再回到知序重新提交。`);
  }
  const remoteId = submitted.result?.id;
  if (!remoteId) throw new Error(submitted.result?.error || "洛谷提交失败。");
  void trackResult(signedIn.tab.id, appTabId, { ...payload, remote_submission_id: remoteId });
  return { remote_submission_id: remoteId, status: "Submitted", detail: "评测中" };
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
            ? { status, detail: record.detail || record.subtasks || record.testcases || record.testCases || record.compileResult || "" }
            : { status: "System Error", detail: `洛谷返回暂不支持的状态码 ${record.status}` };
        },
      });
      const result = response.result;
      if (!result) continue;
      consecutiveErrors = 0;
      failureReported = false;
      if (result.status === prior) continue;
      prior = result.status;
      const isTerminal = !["Judging", "Submitted"].includes(result.status);
      const detail = isTerminal
        ? evaluationDetail(result.status, result.detail)
        : "评测中";
      await publishStatus(appTabId, { context: submission.context, submission_id: submission.submission_id, remote_submission_id: submission.remote_submission_id, ...result, detail });
      if (!["Judging", "Submitted"].includes(prior)) return;
    } catch (error) {
      consecutiveErrors += 1;
      if (consecutiveErrors >= 3 && !failureReported) {
        failureReported = true;
        await publishStatus(appTabId, {
          context: submission.context,
          submission_id: submission.submission_id,
          remote_submission_id: submission.remote_submission_id,
          status: prior,
          detail: "暂时无法读取洛谷评测状态，插件仍在重试。",
        });
      }
    }
  }
  await publishStatus(appTabId, {
    context: submission.context,
    submission_id: submission.submission_id,
    remote_submission_id: submission.remote_submission_id,
    status: prior,
    detail: "洛谷尚未返回最终结果。重新检测洛谷连接后可同步后续状态。",
  });
}
