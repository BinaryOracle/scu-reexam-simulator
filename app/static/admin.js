/** Account management UI. Backend APIs remain the source of authorization. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { readCreditSettings } from "./credits.js?v=20261115-dialog-v1";
import {
  $,
  el,
  button,
  badge,
  emptyState,
  notify,
  confirmAction,
} from "./ui.js?v=20261114-ui-v17";

let accounts = [];
let usernameTarget = null;
let savingUsername = false;
let passwordTarget = null;
let savingAccount = false;
let savingPassword = false;
let bankQuestions = [];
let bankPage = 1;
let bankFilterKey = "";
let questionEditorBaseline = null;
const visiblePasswords = new Set();
export function clearVisiblePasswords() {
  for (const hide of visiblePasswords) hide();
}
function passwordControl(user) {
  let timeout;
  let shown = false;
  const group = el("div", "", "password-control");
  if (!user.password_available) {
    group.append(button("设置密码", () => openPassword(user), "text-button password-unavailable"));
    group.title = "邮箱注册账号尚未设置可查看密码；旧账号可重置密码或使用密码登录一次后查看";
    return group;
  }
  const field = el("input"); field.type = "password"; field.readOnly = true;
  field.value = "••••••"; field.setAttribute("aria-label", `${user.username} 的密码`);
  field.autocomplete = "off"; field.spellcheck = false;
  const control = button("查看", async () => {
    if (shown) { hide(); return; }
    const result = await api(`/admin/users/${user.id}/reveal-password`, { method: "POST" });
    if (!control.isConnected || document.hidden || $("users").hidden) return;
    field.type = "text"; field.value = result.password;
    control.textContent = "隐藏";
    shown = true;
    control.classList.add("revealed-password");
    control.title = "点击隐藏，15 秒后自动隐藏";
    control.setAttribute("aria-label", `隐藏 ${user.username} 的密码`);
    visiblePasswords.add(hide);
    timeout = setTimeout(hide, 15000);
  }, "password-reveal-button");
  function hide() {
    clearTimeout(timeout);
    shown = false;
    field.type = "password"; field.value = "••••••";
    control.textContent = "查看";
    control.classList.remove("revealed-password");
    control.title = "点击查看密码原文";
    control.setAttribute("aria-label", `查看 ${user.username} 的密码原文`);
    visiblePasswords.delete(hide);
  }
  hide();
  group.append(field, control);
  return group;
}
const categoryNames = { professional: "专业课", translation: "英文段落翻译", oral: "英文口语" };
const subjectNames = { data_structures: "数据结构", operating_systems: "操作系统", computer_networks: "计算机网络" };

export async function refreshUsers() {
  accounts = await api("/admin/users");
  $("userTotal").textContent = accounts.length;
  $("userActive").textContent = accounts.filter(
    (user) => user.is_active,
  ).length;
  $("userInterview").textContent = accounts.filter(
    (user) => !user.is_admin,
  ).length;
  $("userExam").textContent = accounts.filter((user) => user.is_admin).length;
  renderUsers();
}
export async function refreshQuestionBank() {
  bankQuestions = await api("/admin/question-bank");
  renderQuestionBank();
}
let luoguSettingsRevision = 0;
export async function refreshLuoguSettings() {
  const revision = ++luoguSettingsRevision;
  const settings = await api('/admin/luogu-settings');
  if (revision !== luoguSettingsRevision || $('luoguAppOrigin').readOnly) return;
  $('luoguAppOrigin').value = `${settings.app_origin}/`;
  $('luoguSettingsStatus').hidden = true;
}
function questionEditorState() {
  return JSON.stringify([$("questionCategory").value, $("questionSubject").value, $("questionContent").value, $("questionActive").checked]);
}
function questionEditorDirty() {
  return questionEditorBaseline !== null && questionEditorState() !== questionEditorBaseline;
}
async function discardQuestionChanges() {
  return !questionEditorDirty() || await confirmAction("未保存的题目修改将丢失。", { title: "放弃未保存的修改？", confirmText: "放弃修改", danger: true });
}
function resetQuestionEditor() {
  $("questionBankForm").reset();
  $("questionBankId").value = "";
  $("questionActive").checked = true;
  $("cancelQuestionEdit").hidden = true;
  syncQuestionCategory();
  $("questionEditorTitle").textContent = "新增题目";
  $("questionBankForm").querySelector('[type="submit"]').textContent = "添加题目";
  questionEditorBaseline = questionEditorState();
}
function syncQuestionCategory() {
  $("questionSubjectField").hidden = $("questionCategory").value !== "professional";
}
function renderQuestionBank() {
  const filter = $("questionBankFilter").value;
  const query = $("questionBankSearch").value.trim().toLowerCase();
  const filterKey = JSON.stringify([filter, query]);
  if (filterKey !== bankFilterKey) { bankPage = 1; bankFilterKey = filterKey; }
  const rows = bankQuestions.filter((row) => (!filter || row.category === filter) && row.content.toLowerCase().includes(query));
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  bankPage = Math.min(bankPage, pages);
  $("questionBankCount").textContent = `${rows.length} 道题目`;
  if (!rows.length) {
    $("questionBankList").replaceChildren(emptyState("暂无题目", "调整筛选条件，或添加一道题目。", "▤"));
    return;
  }
  const list = el("div", "", "question-bank-list");
  for (const row of rows.slice((bankPage - 1) * 10, bankPage * 10)) {
    const item = el("article", "", "question-bank-item");
    const meta = el("div", "", "question-bank-meta");
    meta.append(badge(categoryNames[row.category], "gray"));
    if (row.subject) meta.append(badge(subjectNames[row.subject] || row.subject, "orange"));
    meta.append(badge(row.active ? "已启用" : "已停用", row.active ? "green" : "gray"));
    const content = el("p", row.content);
    content.lang = row.category === "professional" ? "zh" : "en";
    const actions = el("div", "", "table-actions");
    actions.append(button("编辑", async () => {
      if (!await discardQuestionChanges()) return;
      $("questionBankId").value = row.id;
      $("questionCategory").value = row.category;
      $("questionSubject").value = row.subject || "data_structures";
      $("questionContent").value = row.content;
      $("questionActive").checked = !!row.active;
      $("cancelQuestionEdit").hidden = false;
      syncQuestionCategory();
      $("questionEditorTitle").textContent = "编辑题目";
      $("questionBankForm").querySelector('[type="submit"]').textContent = "保存修改";
      questionEditorBaseline = questionEditorState();
      $("questionBankForm").scrollIntoView({ behavior: "smooth", block: "start" });
      $("questionContent").focus();
    }, "text-button"), button("删除", async () => {
      if (!await confirmAction("已抽取到面试记录中的题目不会受影响。此操作无法撤销。", { title: "删除这道题目？", confirmText: "删除题目", danger: true })) return;
      await api(`/admin/question-bank/${row.id}`, { method: "DELETE" });
      if ($("questionBankId").value === String(row.id)) resetQuestionEditor();
      await refreshQuestionBank();
      notify("题目已删除。");
    }, "text-button"));
    item.append(meta, content, actions);
    list.append(item);
  }
  const pagination = el("nav", "", "question-bank-pagination");
  pagination.setAttribute("aria-label", "题库分页");
  const turn = number => {
    bankPage = number;
    renderQuestionBank();
    $("questionBankList").scrollIntoView({ block: "start", behavior: "instant" });
    $("questionBankList").focus({ preventScroll: true });
  };
  const previous = button("上一页", () => turn(bankPage - 1), "button secondary");
  const next = button("下一页", () => turn(bankPage + 1), "button secondary");
  previous.disabled = bankPage === 1; next.disabled = bankPage === pages;
  pagination.append(previous, el("span", `${bankPage} / ${pages} · 共 ${rows.length} 题`), next);
  $("questionBankList").tabIndex = -1;
  $("questionBankList").replaceChildren(list, pagination);
}
async function submitQuestion(event) {
  event.preventDefault();
  const control = $("questionBankForm").querySelector('[type="submit"]');
  if (control.disabled) return;
  control.disabled = true;
  try {
  const id = $("questionBankId").value;
  const payload = {
    category: $("questionCategory").value,
    subject: $("questionCategory").value === "professional" ? $("questionSubject").value : "",
    content: $("questionContent").value.trim(),
    active: $("questionActive").checked,
  };
  await api(id ? `/admin/question-bank/${id}` : "/admin/question-bank", {
    method: id ? "PATCH" : "POST",
    body: JSON.stringify(payload),
  });
  resetQuestionEditor();
  await refreshQuestionBank();
  notify(id ? "题目已更新。" : "题目已添加。");
  } finally { control.disabled = false; }
}
async function exportQuestionBank() {
  const rows = await api("/admin/question-bank");
  const payload = rows.map(row => ({ category: row.category, subject: row.subject, content: row.content, active: !!row.active }));
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2) + "\n"], { type: "application/json;charset=utf-8" }));
  const link = el("a"); link.href = url; link.download = "interview-question-bank.json";
  link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderUsers() {
  clearVisiblePasswords();
  const query = $("userSearch").value.trim().toLocaleLowerCase();
  const status = $("userStatus").value;
  const visible = accounts.filter(
    (user) =>
      (user.username.toLocaleLowerCase().includes(query) || (user.email || "").toLocaleLowerCase().includes(query)) &&
      (status === "all" ||
        (status === "active" ? user.is_active : !user.is_active)),
  );
  $("userCount").textContent = `${visible.length} / ${accounts.length} 位用户`;
  if (!visible.length) {
    $("userList").replaceChildren(
      emptyState(
        "没有匹配的用户",
        "调整搜索条件，或点击「新建用户」添加账号。",
        "◎",
      ),
    );
    return;
  }
  const wrap = el("div", "", "table-scroll");
  const table = document.createElement("table");
  table.className = "account-table";
  table.append(el("caption", "账号、邮箱、面试次数与状态", "sr-only"));
  const head = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const text of [
    "用户",
    "密码",
    "邮箱",
    "面试次数",
    "管理权限",
    "账号状态",
    "操作",
  ]) {
    const th = el("th", text);
    th.scope = "col";
    tr.append(th);
  }
  head.append(tr);
  const body = document.createElement("tbody");
  for (const user of visible) {
    const row = document.createElement("tr");
    if (!user.is_active) row.className = "account-disabled";
    const name = el("td");
    const cell = el("div", "", "account-name");
    const text = el("div");
    text.append(
      el("strong", user.username),
      el(
        "small",
        `ID ${String(user.id).padStart(3, "0")}${user.id === state.user.id ? " · 当前账号" : ""}`,
      ),
    );
    cell.append(
      el(
        "span",
        user.username.slice(0, 1).toUpperCase(),
        `avatar${user.is_admin ? " admin-avatar" : ""}`,
      ),
      text,
    );
    name.append(cell);
    const password = el("td", "", "account-password-cell");
    password.append(passwordControl(user));
    const email = el("td", "", "account-email-cell");
    email.append(el("span", user.email || "未绑定", "account-email-address"));
    const credits = el("td", "", "account-credits-cell");
    if (user.is_admin) credits.append(el("span", "已开通", "muted"));
    else {
      const form = el("form", "", "inline-credit-form");
      const input = el("input"); input.type = "number"; input.min = "0"; input.max = "1000000"; input.step = "1";
      input.required = true; input.value = String(user.interview_credits);
      input.setAttribute("aria-label", `${user.username} 的剩余面试次数`);
      const save = el("button", "保存", "text-button"); save.type = "submit"; save.disabled = true;
      input.addEventListener("input", () => { save.disabled = input.value === String(user.interview_credits); });
      form.addEventListener("submit", event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        void (async () => {
          save.disabled = true; input.disabled = true;
          try {
            await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ interview_credits: Number(input.value) }) });
            user.interview_credits = Number(input.value); notify("剩余模拟面试次数已保存。");
          } catch (error) { save.disabled = false; notify(error.message, "error"); }
          finally { input.disabled = false; }
        })();
      });
      form.append(input, el("span", "次"), save); credits.append(form);
    }
    const admin = el("td");
    admin.append(
      badge(
        user.is_superadmin ? "超级管理员" : user.is_admin ? "管理员" : "普通用户",
        user.is_admin ? "orange" : "gray",
      ),
    );
    const active = el("td");
    const statusControl = button(
      user.is_active ? "已启用" : "已停用",
      async () => {
        const next = !user.is_active;
        await api(`/admin/users/${user.id}`, {
          method: "PATCH",
          body: JSON.stringify({ is_active: next }),
        });
        await refreshUsers();
        notify(`${user.username} 已${next ? "启用" : "停用"}。`);
      },
      `account-status-button ${user.is_active ? "active" : "inactive"}`,
    );
    statusControl.disabled = user.id === state.user.id;
    statusControl.setAttribute("aria-pressed", String(user.is_active));
    statusControl.setAttribute(
      "aria-label",
      `${user.is_active ? "停用" : "启用"} ${user.username}`,
    );
    statusControl.title = statusControl.disabled
      ? "不能停用当前登录账号"
      : `点击${user.is_active ? "停用" : "启用"}账号`;
    active.append(statusControl);
    const actions = el("td");
    const group = el("div", "", "table-actions");
    group.append(
      button("重置用户名", () => openUsername(user), "text-button"),
      button("重置密码", () => openPassword(user), "text-button"),
    );
    if (!user.is_superadmin && user.id !== state.user.id) group.append(button("删除用户", async () => {
      if (!await confirmAction(`将删除「${user.username}」的账号、面试记录、录音、PPT 和提交记录，已兑换卡密不会恢复。此操作无法撤销。`, { title: "删除这个用户？", confirmText: "删除用户", danger: true })) return;
      await api(`/admin/users/${user.id}`, { method: "DELETE" });
      await refreshUsers(); notify("用户及其记录已删除。");
    }, "text-button danger"));
    actions.append(group);
    row.append(name, password, email, credits, admin, active, actions);
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  wrap.tabIndex = 0;
  wrap.setAttribute("aria-label", "账号列表，可左右滑动查看全部信息和操作");
  $("userList").replaceChildren(el("p", "左右滑动表格，查看全部信息与账号操作 →", "mobile-table-hint"), wrap);
}
function syncAccountType() {
  const admin = $("accountTypeAdmin").checked;
  $("initialCreditsField").hidden = admin;
  $("accountCredits").disabled = admin;
}
async function openAccount() {
  const settings = await readCreditSettings();
  $("userForm").reset();
  $("accountTypeAdmin").disabled = !state.user.is_superadmin;
  $("accountTypeAdmin").closest("label").hidden = !state.user.is_superadmin;
  $("userFormError").hidden = true;
  $("accountCredits").value = settings.default_credits;
  syncAccountType();
  $("userDialog").showModal();
}
function openUsername(user) {
  usernameTarget = user;
  $("usernameForm").reset();
  $("usernameFormError").hidden = true;
  $("usernameTarget").textContent = `当前用户名：${user.username}`;
  $("resetUsername").value = user.username;
  $("usernameDialog").showModal();
}
async function submitUsername(event) {
  event.preventDefault();
  if (savingUsername) return;
  savingUsername = true;
  const control = $("usernameForm").querySelector('[type="submit"]');
  control.disabled = true;
  $("usernameFormError").hidden = true;
  let saved = false;
  try {
    const username = $("resetUsername").value;
    const result = await api(`/admin/users/${usernameTarget.id}/username`, {
      method: "POST",
      body: JSON.stringify({ username }),
    });
    saved = true;
    $("usernameDialog").close();
    if ($("userSearch").value.trim() === usernameTarget.username)
      $("userSearch").value = username;
    if (usernameTarget.id === state.user.id) {
      state.user = result;
      window.dispatchEvent(new Event("account-access-updated"));
    }
    await refreshUsers();
    notify("用户名已更新，后续请使用新用户名登录。密码和历史记录保持不变。");
  } catch (error) {
    if (saved) {
      notify("用户名已更新，但用户列表未能刷新。请点击刷新列表；不要重复提交。", "error");
      return;
    }
    $("usernameFormError").textContent = error.message;
    $("usernameFormError").hidden = false;
  } finally {
    savingUsername = false;
    control.disabled = false;
  }
}
function openPassword(user) {
  passwordTarget = user;
  $("passwordForm").reset();
  $("passwordFormError").hidden = true;
  $("passwordTarget").textContent = `为 ${user.username} 设置新密码。`;
  $("passwordDialog").showModal();
}
async function submitAccount(event) {
  event.preventDefault();
  if (savingAccount) return;
  savingAccount = true;
  $("saveUser").disabled = true;
  $("userFormError").hidden = true;
  let saved = false;
  try {
    const payload = {
      username: $("accountUsername").value,
      password: $("accountPassword").value,
      is_admin: $("accountTypeAdmin").checked,
      email: $("accountEmail").value.trim() || null,
      interview_credits: Number($("accountCredits").value),
    };
    await api("/admin/users", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    saved = true;
    $("userDialog").close();
    $("accountPassword").value = "";
    await refreshUsers();
    notify(
      `${payload.is_admin ? "管理员" : "普通用户"}已创建，请将账号信息告知使用者。`,
    );
  } catch (error) {
    if (saved) {
      notify("用户已创建，但列表未能刷新。请点击刷新列表；不要重复创建。", "error");
      return;
    }
    $("userFormError").textContent = error.message;
    $("userFormError").hidden = false;
  } finally {
    savingAccount = false;
    $("saveUser").disabled = false;
  }
}
async function submitPassword(event) {
  event.preventDefault();
  if (savingPassword) return;
  const password = $("resetPassword").value;
  $("passwordFormError").hidden = true;
  if (password !== $("confirmPassword").value) {
    $("passwordFormError").textContent = "两次输入的密码不一致，请重新检查。";
    $("passwordFormError").hidden = false;
    return;
  }
  savingPassword = true;
  const control = $("passwordForm").querySelector('[type="submit"]');
  control.disabled = true;
  let saved = false;
  try {
    await api(`/admin/users/${passwordTarget.id}/password`, {
      method: "POST",
      body: JSON.stringify({ password }),
    });
    saved = true;
    $("passwordDialog").close();
    $("passwordForm").reset();
    if (passwordTarget.id === state.user.id) {
      sessionStorage.removeItem("token");
      location.reload();
      return;
    }
    await refreshUsers();
    notify("密码已重置，该用户需要重新登录。");
  } catch (error) {
    if (saved) {
      notify("密码已重置，但用户列表未能刷新。请点击刷新列表；用户需要使用新密码登录。", "error");
      return;
    }
    $("passwordFormError").textContent = error.message;
    $("passwordFormError").hidden = false;
  } finally {
    savingPassword = false;
    control.disabled = false;
  }
}
export function setupAdmin() {
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearVisiblePasswords(); });
  $("newUser").addEventListener("click", () => void openAccount().catch(error => notify(error.message, "error")));
  $("luoguAppOrigin").addEventListener("input", () => { luoguSettingsRevision++; $("luoguSettingsStatus").hidden = true; });
  $("luoguSettingsForm").addEventListener("submit", (event) => {
    event.preventDefault();
    luoguSettingsRevision++;
    const form = event.currentTarget;
    const save = form.querySelector('[type="submit"]');
    const status = $("luoguSettingsStatus");
    save.disabled = true;
    const origin = $("luoguAppOrigin");
    origin.readOnly = true;
    status.hidden = true;
    void api('/admin/luogu-settings', {
      method: 'PATCH',
      body: JSON.stringify({ app_origin: $('luoguAppOrigin').value }),
    }).then(settings => {
      $('luoguAppOrigin').value = `${settings.app_origin}/`;
      status.textContent = '设置已保存。请重新下载插件 ZIP，并在浏览器扩展管理页重新加载插件。';
      status.hidden = false;
      status.classList.remove('form-error');
      notify('洛谷插件网站来源已更新。');
    }).catch(error => {
      status.textContent = error.status === 422
        ? '请输入仅包含协议、域名和端口的地址，不要填写路径或参数。正式网站须使用 HTTPS。'
        : error.message;
      status.hidden = false;
      status.classList.add('form-error');
    }).finally(() => { save.disabled = false; origin.readOnly = false; });
  });
  $("questionBankForm").addEventListener("submit", (event) => void submitQuestion(event).catch((error) => notify(error.message, "error")));
  $("questionCategory").addEventListener("change", syncQuestionCategory);
  $("questionBankFilter").addEventListener("change", renderQuestionBank);
  $("questionBankSearch").addEventListener("input", renderQuestionBank);
  $("exportQuestionBank").addEventListener("click", () => void exportQuestionBank().catch(error => notify(error.message, "error")));
  $("cancelQuestionEdit").addEventListener("click", async () => {
    if (await discardQuestionChanges()) resetQuestionEditor();
  });
  questionEditorBaseline = questionEditorState();
  $("userSearch").addEventListener("input", renderUsers);
  $("userStatus").addEventListener("change", renderUsers);
  $("userForm").addEventListener("submit", submitAccount);
  $("passwordForm").addEventListener("submit", submitPassword);
  $("usernameForm").addEventListener("submit", submitUsername);
  for (const node of document.querySelectorAll('[name="accountType"]'))
    node.addEventListener("change", syncAccountType);
  for (const node of document.querySelectorAll(".username-close"))
    node.addEventListener("click", () => {
      if (!savingUsername) $("usernameDialog").close();
    });
  $("usernameDialog").addEventListener("cancel", (event) => {
    if (savingUsername) event.preventDefault();
  });
  for (const node of document.querySelectorAll(".dialog-close"))
    node.addEventListener("click", () => {
      if (!savingAccount) $("userDialog").close();
    });
  for (const node of document.querySelectorAll(".password-close"))
    node.addEventListener("click", () => {
      if (!savingPassword) $("passwordDialog").close();
    });
  $("userDialog").addEventListener("cancel", (event) => {
    if (savingAccount) event.preventDefault();
  });
  $("passwordDialog").addEventListener("cancel", (event) => {
    if (savingPassword) event.preventDefault();
  });
  $("userDialog").addEventListener("close", () => {
    $("accountPassword").value = "";
  });
  $("passwordDialog").addEventListener("close", () => {
    $("passwordForm").reset();
  });
}
