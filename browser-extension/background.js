import { APP_ORIGIN } from "./extension-config.js";

const LUOGU_PATTERNS = ["https://www.luogu.com.cn/*"];
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

async function handleRequest(type, payload = {}, appTabId) {
  const found = await findLoggedInTab();
  if (type === "PING") {
    await flushPendingStatuses(appTabId);
    return found
      ? { connected: true, account: found.account, extension_version: chrome.runtime.getManifest().version }
      : { connected: false, reason: "请在浏览器中打开洛谷并登录，再返回此处检测。", extension_version: chrome.runtime.getManifest().version };
  }
  if (type !== "SUBMIT") throw new Error("不支持的桥接操作");
  if (!found) throw new Error("洛谷登录状态已失效，请重新登录后提交。");
  if (!/^[A-Z]{1,4}[0-9]{1,8}$/.test(payload.problem_id || "")) throw new Error("洛谷题号格式无效。");
  if (payload.language !== "python3" || typeof payload.source !== "string" || payload.source.length < 1 || payload.source.length > 30000)
    throw new Error("目前只支持 Python 3，代码长度不超过 30000 字符。");
  const [submitted] = await chrome.scripting.executeScript({
    target: { tabId: found.tab.id }, world: "MAIN",
    args: [payload.problem_id, payload.source],
    func: async (problemId, source) => {
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
      if (!csrf) return { error: "洛谷页面缺少 CSRF 校验信息，请刷新洛谷页面后重试。" };
      const response = await fetch(`/fe/api/problem/submit/${encodeURIComponent(problemId)}`, {
        method: "POST", credentials: "include",
        headers: { "Content-Type": "application/json", "X-CSRF-TOKEN": csrf },
        body: JSON.stringify({ code: source, language: 7, enableO2: false }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok || body?.errorCode) {
        const error = String(body?.errorMessage || `洛谷拒绝提交（HTTP ${response.status}）。`);
        const requiresManualVerification = /captcha|验证码|人机验证|安全验证/i.test(error);
        return { error, requires_manual_verification: requiresManualVerification };
      }
      const id = body?.data?.record?.id ?? body?.data?.id ?? body?.data?.rid;
      return id ? { id: String(id) } : { error: "洛谷没有返回提交编号，无法跟踪评测结果。" };
    },
  });
  if (submitted.result?.requires_manual_verification || /captcha|验证码|人机验证|安全验证/i.test(submitted.result?.error || "")) {
    const problemUrl = `https://www.luogu.com.cn/problem/${encodeURIComponent(payload.problem_id)}`;
    let opened = false;
    try {
      await chrome.tabs.create({ url: problemUrl, active: true });
      opened = true;
    } catch (openError) {
      console.warn("Unable to open the Luogu problem page for manual verification.", openError);
    }
    const page = opened ? `已为你打开洛谷题目页（${payload.problem_id}）` : `请打开洛谷题目页：${problemUrl}`;
    throw new Error(`洛谷返回“${submitted.result?.error || "安全验证"}”，自动提交未成功。${page}。请确认账号已登录，并按洛谷页面提示手动完成验证；若题目页未显示验证，请在该题的洛谷提交区域查看页面提示。处理后回到知序重新提交。`);
  }
  const remoteId = submitted.result?.id;
  if (!remoteId) throw new Error(submitted.result?.error || "洛谷提交失败。");
  void trackResult(found.tab.id, appTabId, { ...payload, remote_submission_id: remoteId });
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
