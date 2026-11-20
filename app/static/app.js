import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, notify, run, confirmAction } from "./ui.js?v=20261114-ui-v17";
import {
  refreshInterviews,
  startInterview,
  configureInterviewMode,
  allowNavigation,
  hasUnsavedWork,
  pauseInterviewAudio,
  clearInterviewState,
} from "./interview.js?v=20261114-ui-v20";
import {
  refreshContests,
  refreshSubmissions,
  createContest,
  clearContestState,
  setupContestCreation,
} from "./contest.js?v=20261115-navigation-v3";
import { clearVisiblePasswords, refreshUsers, refreshQuestionBank, refreshLuoguSettings, setupAdmin } from "./admin.js?v=20261114-ui-v23";
import { refreshProfile, refreshVouchers, setupCredits } from "./credits.js?v=20261114-training-v9";
import { clearProfilePassword } from "./profile-account.js?v=20261114-ui-v17";

import { refreshTraining, clearTraining, selectTrainingSection } from "./training.js?v=20261114-training-v11";
import { refreshTrainingAdmin, clearTrainingAdmin } from "./training-admin.js?v=20261114-training-v11";

import { clearTransfers } from "./credit-transfers.js?v=20261114-training-v10";
import { refreshHome, refreshAnnouncementsAdmin, setupHome } from "./home.js?v=20261114-home-v3";
import { cancelCapture, clearCourses, getCapture, refreshCourses } from "./courses.js?v=3";
import { isAppRouteHash, readAppRoute, writeAppRoute, writeAppViewRoute } from "./view-route.mjs?v=20261115-navigation-v3";

const views = {
  home: { label: "备考首页", refresh: refreshHome },
  announcementsAdmin: { label: "公告管理", refresh: refreshAnnouncementsAdmin },
  training: { label: "每日训练", refresh: refreshTraining },
  trainingAdmin: { label: "训练题库", refresh: refreshTrainingAdmin },
  courses: { label: "课程", refresh: refreshCourses },
  coursesAdmin: { label: "课程管理", refresh: refreshCourses },
  users: { label: "用户管理", refresh: refreshUsers },
  questionBank: { label: "面试题库", refresh: refreshQuestionBank },
  vouchers: { label: "卡密与次数", refresh: refreshVouchers },
  systemSettings: { label: "系统设置", refresh: refreshLuoguSettings },
  profile: { label: "个人主页", refresh: refreshProfile },
  interview: {
    label: state.adminMode ? "面试记录" : "模拟面试",
    refresh: refreshInterviews,
  },
  contest: {
    label: state.adminMode ? "考务管理" : "上机考试",
    refresh: refreshContests,
  },
  submissions: {
    label: state.adminMode ? "提交总览" : "提交记录",
    refresh: refreshSubmissions,
  },
  adminDenied: { label: "后台管理", refresh: async () => {} },
};
let currentView = null;
function configureSidebar() {
  let collapsed = false;
  try { collapsed = localStorage.getItem("scu-sidebar-collapsed") === "1"; }
  catch (error) { /* Storage may be disabled; the current page still supports toggling. */ }
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  syncSidebarToggle();
  window.addEventListener("interview-layout-changed", syncSidebarToggle);
  $("sidebarToggle").addEventListener("click", () => {
    if (document.body.classList.contains("interview-immersive")) {
      return;
    }
    const isCollapsed = document.body.classList.toggle("sidebar-collapsed");
    try { localStorage.setItem("scu-sidebar-collapsed", isCollapsed ? "1" : "0"); }
    catch (error) { /* Keep the current layout when browser storage is unavailable. */ }
    syncSidebarToggle();
  });
  for (const item of document.querySelectorAll(".nav-item")) {
    item.title = item.querySelector(".nav-label")?.textContent || "";
    item.setAttribute("aria-label", item.title);
  }
}
function syncSidebarToggle() {
  const collapsed = document.body.classList.contains("interview-immersive")
    ? !document.body.classList.contains("interview-shell-open")
    : document.body.classList.contains("sidebar-collapsed");
  const control = $("sidebarToggle");
  control.hidden = document.body.classList.contains("interview-immersive");
  control.textContent = collapsed ? "›" : "‹";
  control.title = collapsed ? "展开侧边栏" : "收起侧边栏";
  control.setAttribute("aria-label", control.title);
  control.setAttribute("aria-expanded", String(!collapsed));
}

function allowedViews() {
  if (state.adminMode)
    return state.user.is_admin
      ? ["users", "questionBank", "trainingAdmin", "coursesAdmin", "announcementsAdmin", "vouchers", "systemSettings", "interview", "contest", "submissions", "profile"]
      : ["adminDenied"];
  return ["home", "training", "courses", "interview", "contest", "submissions", "profile"];
}
function configureAccess() {
  const allowed = allowedViews();
  for (const item of document.querySelectorAll("[data-view]"))
    item.hidden = !allowed.includes(item.dataset.view);
  $("managementTools").hidden = !(state.adminMode && state.user.is_admin);
  $("frontendEntry").hidden = !state.adminMode;
  $("identity").textContent = state.user.username;
  $("avatar").textContent = state.user.username.slice(0, 1).toUpperCase();
  $("roleLabel").textContent = state.adminMode
    ? state.user.is_admin
      ? state.user.is_superadmin ? "超级管理员" : "后台管理员"
      : "普通用户"
    : "用户工作台";
  return allowed;
}
async function show(view, force = false, { historyMode = "push" } = {}) {
  if (!force && !allowNavigation()) return;
  if (getCapture() && view !== currentView) {
    notify("请先结束直播或取消开播准备", "error");
    return;
  }
  clearVisiblePasswords();
  clearProfilePassword();
  clearTransfers();
  const user = await api("/me");
  state.user = user;
  const allowed = configureAccess();
  const selected = allowed.includes(view) ? view : allowed[0];
  if (getCapture() && selected !== "coursesAdmin") cancelCapture();
  if (historyMode !== "none") writeAppViewRoute(selected, Object.keys(views), { replace: historyMode === "replace" });
  document.body.classList.toggle("interview-immersive", selected === "interview" && !$("interviewDetail").hidden && $("interviewDetail").dataset.immersive === "true");
  document.body.classList.toggle("contest-immersive", selected === "contest" && document.body.dataset.contestWorkspace === "true" && !state.adminMode);
  document.body.classList.remove("interview-shell-open");
  syncSidebarToggle();
  if (selected !== currentView) {
    pauseInterviewAudio(); clearTraining(); clearTrainingAdmin(); clearCourses();
  }
  currentView = selected;
  for (const [key, value] of Object.entries(views)) {
    $(key).hidden = key !== selected;
    const item = document.querySelector(`[data-view="${key}"]`);
    item?.classList.toggle("active", key === selected);
    if (key === selected) item?.setAttribute("aria-current", "page");
    else item?.removeAttribute("aria-current");
    if (key === selected) {
      $("pageLabel").textContent = value.label;
      document.title = `${value.label} · 知序${state.adminMode ? "后台" : ""}`;
    }
  }
  window.scrollTo({ top: 0, behavior: "instant" });
  await views[selected].refresh();
}
async function enterWorkspace() {
  state.user = await api("/me");
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin();
  $("login").hidden = true;
  $("app").hidden = false;
  $("today").textContent = new Date().toLocaleDateString("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  });
  configureInterviewMode();
  configureAccess();
  const fallback = state.adminMode ? "users" : "home";
  await show(readAppRoute(location.hash, allowedViews(), fallback), false, { historyMode: "replace" });
}
function configureShell() {
  document.body.classList.toggle("admin-mode", state.adminMode);
  if (!state.adminMode) return;
  document.querySelector(".sidebar-caption").textContent = "管理与配置";
  document.querySelector(".sidebar .brand").href = "/admin";
  document.querySelector(".sidebar .brand-subtitle").textContent =
    "后台管理系统";
  document.querySelector(".breadcrumb").textContent = "管理工作台";
  $("workspaceLabel").textContent = "平台管理空间";
  document.querySelector(".login-card h2").textContent = "登录管理后台";
  document.querySelector(".login-description").textContent =
    "使用管理员账号，管理用户、题库与考务。";
  document.querySelector(".login-story .brand-subtitle").textContent =
    "后台管理系统";
  for (const item of document.querySelectorAll("[data-view]")) {
    // The icon and arrow keep their own elements; labels use a text node or span.
    const label = [...item.childNodes].find(
      (node) => node.nodeType === Node.TEXT_NODE && node.textContent.trim(),
    );
    if (label) label.textContent = views[item.dataset.view].label;
    const span = item.querySelector(".nav-label");
    if (span) span.textContent = views[item.dataset.view].label;
  }
  $("contestTitleHeading").replaceChildren(
    document.createTextNode("考务管理"),
    Object.assign(document.createElement("span"), {
      textContent: ".",
      className: "heading-dot",
    }),
  );
}
document.addEventListener("navigate-view", event => {
  const target = event.detail?.view;
  if (!target || !views[target]) return;
  if (event.detail.section && target === "training") selectTrainingSection(event.detail.section);
  void show(target).then(() => {
  }).catch(error => notify(error.message, "error"));
});
window.addEventListener("popstate", () => {
  if (!state.user) return;
  if (!isAppRouteHash(location.hash)) return;
  const fallback = state.adminMode ? "users" : "home";
  const route = readAppRoute(location.hash, allowedViews(), fallback);
  const capture = getCapture();
  if (capture || !allowNavigation()) {
    writeAppRoute(capture ? `coursesAdmin/${capture.cid}/${capture.lid}` : currentView || fallback, { replace: true });
    return;
  }
  void show(route, true, { historyMode: "none" }).catch(error => notify(error.message, "error"));
});
let loginMethod = state.adminMode ? "password" : "email";
let codeRequestPending = false;
let codeCooldownUntil = 0;
let emailCooldownTimer = null;
function selectLoginMethod(method) {
  loginMethod = method;
  const email = method === "email";
  $("loginForm").dataset.loginMethod = method;
  $("emailLoginFields").hidden = !email;
  $("emailLoginFields").disabled = !email;
  $("passwordLoginFields").hidden = email;
  $("passwordLoginFields").disabled = email;
  $("emailLoginMethod").setAttribute("aria-pressed", String(email));
  $("passwordLoginMethod").setAttribute("aria-pressed", String(!email));
  $("loginError").hidden = true;
}
function syncCodeButton() {
  const seconds = Math.max(0, Math.ceil((codeCooldownUntil - Date.now()) / 1000));
  $("sendEmailCode").disabled = codeRequestPending || seconds > 0;
  $("sendEmailCode").textContent = codeRequestPending ? "发送中…" : seconds ? `${seconds} 秒后重发` : "获取验证码";
  if (!seconds && emailCooldownTimer) {
    clearInterval(emailCooldownTimer);
    emailCooldownTimer = null;
  }
}
function startCodeCooldown(seconds) {
  codeCooldownUntil = Date.now() + seconds * 1000;
  clearInterval(emailCooldownTimer);
  emailCooldownTimer = setInterval(syncCodeButton, 1000);
}
for (const [id, method] of [["emailLoginMethod", "email"], ["passwordLoginMethod", "password"]])
  $(id).addEventListener("click", () => selectLoginMethod(method));
$("sendEmailCode").addEventListener("click", async () => {
  const email = $("loginEmail");
  if (!email.reportValidity() || codeRequestPending || codeCooldownUntil > Date.now()) return;
  const requestedEmail = email.value.trim();
  codeRequestPending = true;
  email.readOnly = true;
  syncCodeButton();
  $("loginError").hidden = true;
  $("emailCodeStatus").hidden = true;
  try {
    const result = await api("/auth/email/code", { method: "POST", body: JSON.stringify({ email: requestedEmail }) });
    startCodeCooldown(result.retry_after || 60);
    $("emailCodeStatus").textContent = `验证码已发送至 ${requestedEmail}，请查收邮件。`;
    $("emailCodeStatus").hidden = false;
    if (loginMethod === "email") $("loginCode").focus();
  } catch (error) {
    if (error.retryAfterSeconds) startCodeCooldown(error.retryAfterSeconds);
    $("loginError").textContent = error.retryAfterSeconds
      ? `请求过于频繁，请在 ${error.retryAfterSeconds} 秒后重试`
      : error.message;
    $("loginError").hidden = false;
  } finally {
    codeRequestPending = false;
    email.readOnly = false;
    syncCodeButton();
  }
});
selectLoginMethod(loginMethod);
if (state.adminMode) {
  $("loginMethods").hidden = true;
  $("loginAccountNote").textContent = "请使用管理员用户名与密码登录。普通用户请返回前台。";
}

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  const control = $("loginButton");
  if (control.disabled) return;
  control.disabled = true;
  control.classList.add("busy-label");
  $("loginError").hidden = true;
  $("loginMethods").querySelectorAll("button").forEach(button => { button.disabled = true; });
  try {
    const email = loginMethod === "email";
    const result = await api(email ? "/auth/email/login" : "/login", {
      method: "POST",
      body: JSON.stringify(email ? {
        email: $("loginEmail").value.trim(),
        code: $("loginCode").value,
      } : {
        username: $("username").value,
        password: $("password").value,
      }),
    });
    if (state.adminMode && !result.is_admin)
      throw new Error("当前账号没有后台管理权限，请返回前台登录。");
    state.token = result.token;
    sessionStorage.setItem("token", state.token);
    $("password").value = "";
    $("loginCode").value = "";
    $("notification").hidden = true;
    await enterWorkspace();
  } catch (error) {
    $("loginError").textContent = error.message;
    $("loginError").hidden = false;
  } finally {
    control.disabled = false;
    control.classList.remove("busy-label");
    $("loginMethods").querySelectorAll("button").forEach(button => { button.disabled = false; });
  }
});
$("togglePassword").addEventListener("click", () => {
  const visible = $("password").type === "password";
  $("password").type = visible ? "text" : "password";
  $("togglePassword").textContent = visible ? "隐藏" : "显示";
  $("togglePassword").setAttribute(
    "aria-label",
    visible ? "隐藏密码" : "显示密码",
  );
});
async function logout() {
  if (!allowNavigation()) return;
  if (getCapture()) throw new Error("请先结束直播或取消开播准备");
  if (hasUnsavedWork() && !await confirmAction("有尚未保存的面试文本，退出后将丢失这些修改。", { title: "退出登录？", confirmText: "退出登录" })) return;
  await api("/logout", { method: "POST" });
  clearProfilePassword();
  clearTransfers();
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin();
  sessionStorage.removeItem("token");
  state.token = null;
  location.reload();
}
for (const id of ["logout", "profileLogout"]) $(id).addEventListener("click", event => run(logout, event.currentTarget));
for (const item of document.querySelectorAll("[data-view]"))
  item.addEventListener("click", () =>
    run(() => show(item.dataset.view), item),
  );
$("newInterview").addEventListener("click", (event) =>
  run(startInterview, event.currentTarget),
);
for (const [id, action] of [
  ["refreshInterviews", refreshInterviews],
  ["refreshContests", refreshContests],
  ["refreshSubmissions", refreshSubmissions],
  ["refreshUsers", refreshUsers],
]) {
  $(id).addEventListener("click", (event) => run(action, event.currentTarget));
}
setupContestCreation();
document.querySelectorAll("#luoguTutorial .dialog-close").forEach(button => button.addEventListener("click", () => $("luoguTutorial").close()));
$("contestForm").addEventListener("submit", (event) => {
  event.preventDefault();
  run(createContest, $("contestForm").querySelector('[type="submit"]'));
});
window.addEventListener("beforeunload", (event) => {
  if (hasUnsavedWork() || getCapture()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("account-access-updated", () =>
  run(() => show(currentView, false, { historyMode: "none" })),
);
let updatingAccess = false;
window.addEventListener("session-expired", () => {
  cancelCapture();
  clearCourses();
  clearProfilePassword();
  clearTransfers();
  state.token = null;
  state.user = null;
  sessionStorage.removeItem("token");
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin();
  for (const dialog of document.querySelectorAll("dialog[open]"))
    dialog.close();
  $("app").hidden = true;
  $("login").hidden = false;
  document.title = "登录 · 知序";
  $("emailCodeStatus").hidden = true;
  $("loginError").textContent = "登录已过期或账号已停用，请重新登录。";
  $("loginError").hidden = false;
});
window.addEventListener("account-session-ended", event => {
  cancelCapture();
  clearCourses();
  clearProfilePassword();
  clearTransfers();
  $("loginEmail").value = event.detail.deleted ? "" : state.user?.email || "";
  $("username").value = event.detail.deleted ? "" : state.user?.username || "";
  if (event.detail.deleted && state.user) {
    const prefix = `scu:${state.user.id}:`;
    try {
      for (const storage of [localStorage, sessionStorage]) {
        const keys = [];
        for (let index = 0; index < storage.length; index++) {
          const key = storage.key(index);
          if (key?.startsWith(prefix)) keys.push(key);
        }
        for (const key of keys) storage.removeItem(key);
      }
    } catch (error) { /* Restricted browser storage does not prevent clearing the authenticated page. */ }
  }
  state.token = null;
  state.user = null;
  sessionStorage.removeItem("token");
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin();
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  currentView = null;
  $("app").hidden = true;
  $("login").hidden = false;
  $("loginError").hidden = true;
  $("password").value = "";
  $("loginCode").value = "";
  $("emailCodeStatus").hidden = true;
  document.title = "登录 · 知序";
  notify(event.detail.message);
});
window.addEventListener("access-denied", async () => {
  if (updatingAccess || !state.user) return;
  updatingAccess = true;
  try {
    await show(currentView, true, { historyMode: "none" });
  } catch (error) {
    notify(error.message, "error");
  } finally {
    updatingAccess = false;
  }
});
configureShell();
configureSidebar();
setupAdmin();
setupCredits();
$("avatar").addEventListener("click", () => run(() => show("profile")));
$("openRedeemProfile").addEventListener("click", () => run(() => show("profile")));
$("profileBack").addEventListener("click", event => run(() => show(null), event.currentTarget));
window.addEventListener("open-profile", () => run(() => show("profile")));
setupHome();
if (state.token)
  enterWorkspace().catch((error) => {
    notify(`无法恢复工作台：${error.message}。请重新登录。`, "error");
    state.token = null;
    sessionStorage.removeItem("token");
    $("app").hidden = true;
    $("login").hidden = false;
  });
