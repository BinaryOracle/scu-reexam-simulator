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
} from "./interview.js?v=20261115-ui-v24";
import {
  refreshContests,
  refreshSubmissions,
  createContest,
  clearContestState,
  suspendContestWorkspace,
  setupContestCreation,
  requestLuoguSubmit,
} from "./contest.js?v=20261115-access-layout-v2";
import { clearVisiblePasswords, refreshUsers, refreshQuestionBank, refreshLuoguSettings, setupAdmin } from "./admin.js?v=20261115-access-layout-v2";
import { refreshProfile, refreshVouchers, setupCredits } from "./credits.js?v=20261115-profile-independent-sections-v1";
import { clearProfilePassword } from "./profile-account.js?v=20261114-ui-v17";

import { refreshTraining, clearTraining, selectTrainingSection } from "./training.js?v=20261115-access-layout-v1";
import { refreshTrainingAdmin, clearTrainingAdmin } from "./training-admin.js?v=20261115-dialog-v1";

import { clearTransfers } from "./credit-transfers.js?v=20261115-dialog-v1";
import { refreshHome, refreshAnnouncementsAdmin, setupHome } from "./home.js?v=20261115-access-layout-v2";
import { refreshHomeLayoutAdmin } from "./home-layout.js?v=20261115-layout-v1";
import { isAppRouteHash, readAppRoute, writeAppRoute, writeAppViewRoute } from "./view-route.mjs?v=20261115-navigation-v3";

import { refreshCoding, clearCoding, configureCodingBridge } from "./coding.js?v=20261115-access-layout-v1";
import { refreshCodingAdmin, clearCodingAdmin } from "./coding-admin.js?v=20261115-coding-v1";

configureCodingBridge(requestLuoguSubmit);

const views = {
  home: { label: "备考首页", refresh: refreshHome },
  announcementsAdmin: { label: "公告管理", refresh: refreshAnnouncementsAdmin },
  homeLayoutAdmin: { label: "首页编排", refresh: refreshHomeLayoutAdmin },
  coding: { label: "算法带刷", refresh: refreshCoding },
  codingAdmin: { label: "带刷题库", refresh: refreshCodingAdmin },
  training: { label: "每日训练", refresh: refreshTraining },
  trainingAdmin: { label: "训练题库", refresh: refreshTrainingAdmin },
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
    label: "上机考试",
    refresh: refreshContests,
  },
  submissions: {
    label: "提交记录",
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
  window.addEventListener("resize", syncSidebarToggle);
  $("sidebarToggle").addEventListener("click", () => {
    if (document.body.classList.contains("interview-immersive")) {
      if (window.matchMedia("(max-width: 620px)").matches) {
        document.body.classList.toggle("interview-shell-open");
        syncSidebarToggle();
      }
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
function configureContestNavigation() {
  const submenu = $("contestSubnav");
  const toggle = $("contestNavToggle");
  const admin = state.adminMode && Boolean(state.user?.is_admin);
  const isExpanded = !admin;
  submenu.hidden = admin;
  toggle.hidden = true;
  toggle.setAttribute("aria-expanded", String(isExpanded));
  toggle.setAttribute("aria-label", `${isExpanded ? "收起" : "展开"}上机考试菜单`);
  toggle.title = `${isExpanded ? "收起" : "展开"}上机考试菜单`;
  toggle.querySelector("span").textContent = isExpanded ? "⌃" : "⌄";
}
function syncSidebarToggle() {
  const immersive = document.body.classList.contains("interview-immersive");
  const menuOpen = document.body.classList.contains("interview-shell-open");
  const collapsed = immersive
    ? !menuOpen
    : document.body.classList.contains("sidebar-collapsed");
  const control = $("sidebarToggle");
  control.hidden = immersive && !window.matchMedia("(max-width: 620px)").matches;
  control.textContent = immersive
    ? menuOpen ? "×" : "☰"
    : collapsed ? "›" : "‹";
  control.title = immersive
    ? menuOpen ? "关闭菜单" : "打开菜单"
    : collapsed ? "展开侧边栏" : "收起侧边栏";
  control.setAttribute("aria-label", control.title);
  control.setAttribute("aria-expanded", String(!collapsed));
}

function allowedViews() {
  if (state.adminMode)
    return state.user.is_admin
      ? ["users", "questionBank", "trainingAdmin", "codingAdmin", "announcementsAdmin", "homeLayoutAdmin", "vouchers", "systemSettings", "interview", "contest", "profile"]
      : ["adminDenied"];
  return ["home", "training", "coding", "interview", "contest", "submissions", "profile"];
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
  configureContestNavigation();
  return allowed;
}
async function show(view, force = false, { historyMode = "push" } = {}) {
  if (state.adminMode && view === "submissions") view = "contest";
  if (!force && !allowNavigation()) return;
  if (view !== "contest") suspendContestWorkspace();
  clearVisiblePasswords();
  clearProfilePassword();
  clearTransfers();
  const user = await api("/me");
  state.user = user;
  const allowed = configureAccess();
  const selected = allowed.includes(view) ? view : allowed[0];
  if (historyMode !== "none") writeAppViewRoute(selected, Object.keys(views), { replace: historyMode === "replace" });
  document.body.classList.toggle("interview-immersive", selected === "interview" && !$("interviewDetail").hidden && $("interviewDetail").dataset.immersive === "true");
  document.body.classList.toggle("contest-immersive", selected === "contest" && document.body.dataset.contestWorkspace === "true" && !state.adminMode);
  document.body.classList.toggle("coding-immersive", selected === "coding" && /^#view=coding\/question\/\d+$/.test(location.hash));
  document.body.classList.remove("interview-shell-open");
  syncSidebarToggle();
  if (selected !== currentView) { pauseInterviewAudio(); clearTraining(); clearTrainingAdmin(); clearCoding(); clearCodingAdmin(); }
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
  clearTrainingAdmin(); clearCoding(); clearCodingAdmin();
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
  const route = readAppRoute(location.hash, Object.keys(views), fallback);
  await show(route, false, { historyMode: "replace" });
  document.documentElement.classList.remove("session-restoring");
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
    "使用管理员账号，管理用户、题库与上机考试。";
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
    document.createTextNode("上机考试"),
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
  const route = readAppRoute(location.hash, Object.keys(views), fallback);
  if (!allowNavigation()) {
    writeAppRoute(currentView || fallback, { replace: true });
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
  if (hasUnsavedWork() && !await confirmAction("有尚未保存的面试内容或已选择的 PPT，退出后需要重新准备。", { title: "退出登录？", confirmText: "退出登录" })) return;
  await api("/logout", { method: "POST" });
  clearProfilePassword();
  clearTransfers();
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin(); clearCoding(); clearCodingAdmin();
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
  if (hasUnsavedWork()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("account-access-updated", () =>
  run(() => show(currentView, false, { historyMode: "none" })),
);
let updatingAccess = false;
window.addEventListener("session-expired", () => {
  document.documentElement.classList.remove("session-restoring");
  clearProfilePassword();
  clearTransfers();
  state.token = null;
  state.user = null;
  sessionStorage.removeItem("token");
  clearInterviewState();
  clearContestState();
  clearTraining();
  clearTrainingAdmin(); clearCoding(); clearCodingAdmin();
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
  clearTrainingAdmin(); clearCoding(); clearCodingAdmin();
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
    document.documentElement.classList.remove("session-restoring");
  });
