import { refreshBackupModules, setupBackups } from './admin-backups.js?v=20261122-restore-v2';
export { refreshBackupModules };
/** Account management UI. Backend APIs remain the source of authorization. */
import { api, state } from "./api.js?v=20261122-session-guard-v1";
import { readCreditSettings } from "./credits.js?v=20261122-packages-v1";
import {
  $,
  el,
  button,
  badge,
  emptyState,
  notify,
  confirmAction,
} from "./ui.js?v=20261114-ui-v17";

import { purchaseSummaryButton, openPurchaseDetails, rebateText } from './service-packages.js?v=20261124-feishu-mobile-v1';
import { refreshFeishuOAuth, setupFeishuOAuth } from './feishu-oauth.js?v=20261124-oauth-v1';

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
let usersRevision = 0;
export function clearVisiblePasswords() {
  for (const hide of visiblePasswords) hide();
}
function accountCell(label, className = "") {
  const cell = el("td", "", className);
  cell.dataset.label = label;
  cell.append(el("span", label, "account-cell-label"));
  return cell;
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
  const field = el("input"); field.type = "text"; field.readOnly = true;
  field.value = "••••••"; field.setAttribute("aria-label", `${user.username} 的密码`);
  field.autocomplete = "off"; field.spellcheck = false;
  const control = button("查看", async () => {
    if (shown) { hide(); return; }
    const result = await api(`/admin/users/${user.id}/reveal-password`, { method: "POST" });
    if (!control.isConnected || document.hidden || $("users").hidden) return;
    field.value = result.password;
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
    field.value = "••••••";
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
  const revision = ++usersRevision;
  const refreshed = await api("/admin/users");
  if (revision !== usersRevision) return;
  accounts = refreshed;
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
async function saveUserFields(user, fields, successMessage) {
  await api(`/admin/users/${user.id}`, {
    method: "PATCH",
    body: JSON.stringify(fields),
  });
  Object.assign(accounts.find((account) => account.id === user.id) || user, fields);
  renderUsers();
  try {
    await refreshUsers();
  } catch {
    notify(`${successMessage} 用户列表暂时未能刷新，当前状态已更新。请点击“刷新用户列表”重新读取。`, "info");
    return;
  }
  notify(successMessage);
}
export async function refreshQuestionBank() {
  bankQuestions = await api("/admin/question-bank");
  renderQuestionBank();
}
let luoguSettingsRevision = 0;
let feishuSettingsRevision = 0;
const modelServiceMeta = {
  interview: { title: '面试多模态模型', description: '用于专家提问与整场面试点评，可结合 PPT、回答文本和录音。', tag: '面试' },
  asr: { title: '语音识别（ASR）', description: '将面试录音转写为文字，供面试记录与点评使用。', tag: '语音输入' },
  tts: { title: '语音合成（TTS）', description: '播报专家问答环节生成的问题。', tag: '语音输出' },
  trends: { title: '热点趋势分析', description: '根据公开来源生成 AI 技术趋势内容，可单独配置模型。', tag: '内容生成' },
};
let modelSettingsSnapshot = null;
let activeModelService = null;
export async function refreshLuoguSettings() {
  const revision = ++luoguSettingsRevision;
  const settings = await api('/admin/luogu-settings');
  if (revision !== luoguSettingsRevision || $('luoguAppOrigin').readOnly) return;
  $('luoguAppOrigin').value = `${settings.app_origin}/`;
  $('luoguSettingsStatus').hidden = true;
}
export async function refreshFeishuSettings() {
  const revision = ++feishuSettingsRevision;
  const settings = await api('/admin/feishu-settings');
  if (revision !== feishuSettingsRevision || $('feishuAppId').readOnly) return;
  $('feishuAppId').value = settings.app_id || '';
  $('feishuRedirectUri').value = settings.redirect_uri || '';
  $('feishuAppSecret').value = '';
  $('feishuAppSecret').placeholder = settings.app_secret_configured
    ? '••••••••••••••••（留空保持不变）' : '请输入飞书 App Secret';
  const status = $('feishuSettingsStatus');
  status.textContent = settings.app_secret_configured
    ? `凭证已配置 · 当前来源：${settings.credential_source}`
    : `尚未配置 App Secret · 当前来源：${settings.credential_source}`;
  status.hidden = false;
  status.classList.remove('form-error');
  await refreshFeishuOAuth();
}
let modelSettingsRevision = 0;
function renderModelSettings(settings) {
  modelSettingsSnapshot = settings;
  const list = $('modelServiceList');
  const rows = Object.entries(modelServiceMeta).map(([id, meta]) => {
    const service = settings.services[id];
    const row = el('button', '', 'model-service-row');
    row.type = 'button';
    row.setAttribute('aria-haspopup', 'dialog');
    row.setAttribute('aria-label', '编辑' + meta.title);
    const main = el('span', '', 'model-service-main');
    const heading = el('span', '', 'model-service-heading');
    heading.append(el('strong', meta.title), el('span', meta.tag, 'model-service-tag'));
    main.append(heading, el('span', meta.description, 'model-service-description'));
    const details = el('span', '', 'model-service-details');
    details.append(el('strong', service.model || '未设置模型'), el('span', service.base_url || '未设置接口地址'));
    const aside = el('span', '', 'model-service-aside');
    aside.append(el('span', service.api_key_configured ? '密钥已配置 · ' + service.api_key_source : '尚未配置密钥', service.api_key_configured ? 'model-service-status configured' : 'model-service-status missing'), el('span', '›', 'model-service-arrow'));
    row.append(main, details, aside);
    row.addEventListener('click', () => openModelService(id));
    return row;
  });
  list.replaceChildren(...rows);
}
function openModelService(serviceName) {
  const service = modelSettingsSnapshot?.services[serviceName];
  if (!service) return;
  activeModelService = serviceName;
  const meta = modelServiceMeta[serviceName];
  const form = $('modelSettingsForm');
  form.reset();
  $('modelServiceDialogTitle').textContent = meta.title;
  $('modelServiceDialogDescription').textContent = meta.description;
  for (const field of ['base_url', 'model', 'provider', 'protocol', 'voice']) {
    const input = form.querySelector('[name="' + field + '"]');
    if (input) input.value = service[field] || '';
  }
  $('modelTtsFields').hidden = serviceName !== 'tts';
  form.querySelector('[name="voice"]').required = serviceName === 'tts';
  const keyInput = form.querySelector('[name="api_key"]');
  keyInput.value = '';
  keyInput.placeholder = service.api_key_configured ? '••••••••••••••••' : '请输入 API Key';
  $('modelServiceKeyStatus').textContent = service.api_key_configured
    ? '当前使用：' + service.api_key_source + ' · 输入新密钥可替换'
    : '尚未配置 API Key';
  const status = $('modelSettingsStatus');
  status.hidden = true;
  status.classList.remove('form-error');
  $('modelServiceDialog').showModal();
}
export async function refreshModelSettings() {
  const revision = ++modelSettingsRevision;
  const settings = await api('/admin/model-settings');
  if (revision !== modelSettingsRevision || $('modelSettingsForm').dataset.saving === 'true') return;
  renderModelSettings(settings);
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
  const [category, subject] = filter.includes(":") ? filter.split(":", 2) : [filter, ""];
  const query = $("questionBankSearch").value.trim().toLowerCase();
  const filterKey = JSON.stringify([filter, query]);
  if (filterKey !== bankFilterKey) { bankPage = 1; bankFilterKey = filterKey; }
  const rows = bankQuestions.filter((row) => (!category || (row.category === category && (!subject || row.subject === subject))) && row.content.toLowerCase().includes(query));
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
      notify("题目已删除。");
      try { await refreshQuestionBank(); }
      catch { notify("题目已删除，但列表刷新失败。请点击刷新列表；不要重复删除。", "error"); }
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
  notify(id ? "题目已更新。" : "题目已添加。");
  try { await refreshQuestionBank(); }
  catch { notify("题目已保存，但列表刷新失败。请点击刷新列表；不要重复提交。", "error"); }
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
  const emailQuery = $("userEmailSearch").value.trim().toLocaleLowerCase();
  const referrerQuery = $("userReferrerSearch").value.trim().toLocaleLowerCase();
  const status = $("userStatus").value;
  const roleFilter = $("userRoleFilter").value;
  const rebateFilter = $("userRebateFilter").value;
  const visible = accounts.filter(
    (user) =>
      user.username.toLocaleLowerCase().includes(query) &&
      (user.email || "").toLocaleLowerCase().includes(emailQuery) &&
      (!referrerQuery || `${user.referrer_name || ""} ${user.referrer_email || ""}`.toLocaleLowerCase().includes(referrerQuery)) &&
      (roleFilter === "all" || (roleFilter === "admin" ? user.is_admin : !user.is_admin)) &&
      (rebateFilter === "all" || user.rebate_status === (rebateFilter === "none" ? "unset" : rebateFilter)) &&
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
  const wrap = el("div", "", "account-table-wrap");
  const table = document.createElement("table");
  table.className = "account-table";
  table.append(el("caption", "账号、邀请者、套餐服务、返利、积分与状态", "sr-only"));
  const head = document.createElement("thead");
  const tr = document.createElement("tr");
  for (const text of [
    "用户信息",
    "密码",
    "功能权限",
    "账号状态",
    "邀请者",
    "套餐服务",
    "返利",
    "积分",
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
    const name = accountCell("用户", "account-identity-cell");
    const cell = el("div", "", "account-name");
    const text = el("div", "", "account-identity-copy");
    text.append(
      el("strong", user.username, "account-username"),
      el(
        "small",
        `ID ${String(user.id).padStart(3, "0")}${user.id === state.user.id ? " · 当前账号" : ""}`,
      ),
    );
    text.firstChild.title = user.username;
    const role = el("span", user.is_superadmin ? "超级管理员" : user.is_admin ? "管理员" : "普通用户", `account-role${user.is_admin ? " account-role-admin" : ""}`);
    text.append(role);
    cell.append(
      el(
        "span",
        user.username.slice(0, 1).toUpperCase(),
        `avatar${user.is_admin ? " admin-avatar" : ""}`,
      ),
      text,
    );
    name.append(cell);
    const referrer = accountCell("邀请者", "account-referrer-cell");
    referrer.append(el("span", user.referrer_name || "—", user.referrer_name ? "account-referrer-name" : "muted"));
    if (user.referrer_email) referrer.append(el("small", user.referrer_email, "account-email-address"));
    const service = accountCell("套餐服务", "account-purchase-service-cell");
    const rebate = accountCell("返利", "account-rebate-cell");
    if (user.is_admin) {
      service.append(el("span", "—", "muted"));
      rebate.append(el("span", "—", "muted"));
    } else {
      service.append(purchaseSummaryButton(user, () => openPurchaseDetails(user, { manage: true, onChange: refreshUsers })));
      const statusButton = button(rebateText(user.rebate_status), async () => {
        const next = user.rebate_status !== "redeemed";
        if (!await confirmAction(`将「${user.username}」当前有效购买记录的返利标记为${next ? "已兑换" : "待兑换"}。当前待兑换 ${(user.pending_rebate_fen / 100).toFixed(2)} 元，已兑换 ${(user.redeemed_rebate_fen / 100).toFixed(2)} 元；总返利 ${(user.rebate_total_fen / 100).toFixed(2)} 元。`, { title: "确认更新返利状态？", confirmText: next ? "标记已兑换" : "恢复待兑换" })) return;
        const result = await api(`/admin/users/${user.id}/rebate`, { method: "PATCH", body: JSON.stringify({ redeemed: next }) });
        Object.assign(user, result); renderUsers(); notify("返利状态已更新。");
      }, `account-rebate-state ${user.rebate_status}`);
      statusButton.disabled = user.rebate_status === "unset";
      statusButton.setAttribute("aria-label", `${user.username} 的返利：${rebateText(user.rebate_status)}`);
      statusButton.title = statusButton.disabled ? "没有有效购买记录或邀请者" : "点击修改返利状态";
      rebate.append(statusButton);
    }
    const password = accountCell("密码", "account-password-cell");
    password.append(passwordControl(user));
    const email = el("span", user.email || "未绑定邮箱", "account-email-address");
    email.title = user.email || "未绑定邮箱";
    text.append(email);
    const pointsCell = accountCell("积分", "account-points-cell");
    if (user.is_admin) pointsCell.append(el("span", "无限积分", "account-unlimited-points"));
    else {
      const form = el("form", "", "inline-credit-form");
      const input = el("input"); input.type = "number"; input.min = "0"; input.max = "1000000000"; input.step = "1";
      input.required = true; input.value = String(user.points ?? 0);
      input.setAttribute("aria-label", `${user.username} 的积分余额`);
      const save = el("button", "保存", "text-button"); save.type = "submit"; save.disabled = true;
      input.addEventListener("input", () => { save.disabled = input.value === String(user.points ?? 0); });
      form.addEventListener("submit", event => {
        event.preventDefault();
        if (!form.reportValidity()) return;
        void (async () => {
          save.disabled = true; input.disabled = true;
          try {
            await api(`/admin/users/${user.id}`, { method: "PATCH", body: JSON.stringify({ points: Number(input.value) }) });
            user.points = Number(input.value); notify("用户积分已保存。");
          } catch (error) { save.disabled = false; notify(error.message, "error"); }
          finally { input.disabled = false; }
        })();
      });
      form.append(input, el("span", "分"), save); pointsCell.append(form);
    }
    const active = accountCell("账号状态");
    const statusControl = button(
      user.is_active ? "已启用" : "已停用",
      async () => {
        const next = !user.is_active;
        await saveUserFields(user, { is_active: next }, `${user.username} 已${next ? "启用" : "停用"}。`);
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
    const actions = accountCell("操作", "account-actions-cell");
    const group = el("div", "", "table-actions");
    group.append(
      button("重置用户名", () => openUsername(user), "text-button"),
      button("重置密码", () => openPassword(user), "text-button"),
    );
    if (!user.is_superadmin && user.id !== state.user.id) group.append(button("删除用户", async () => {
      if (!await confirmAction(`将删除「${user.username}」的账号、面试记录、录音、PPT 和提交记录，已兑换卡密不会恢复。此操作无法撤销。`, { title: "删除这个用户？", confirmText: "删除用户", danger: true })) return;
      await api(`/admin/users/${user.id}`, { method: "DELETE" });
      notify("用户及其记录已删除。");
      try { await refreshUsers(); }
      catch { notify("用户已删除，但列表刷新失败。请点击刷新用户列表；不要重复删除。", "error"); }
    }, "text-button danger"));
    actions.append(group);
    const permissionCell = (key, label, shortLabel) => {
      const cell = el("div", "", "account-permission-item");
      const enabled = Boolean(user[key]);
      if (user.is_admin) cell.append(el("span", shortLabel, "account-permission-default"));
      else {
        const control = button(shortLabel, async () => {
          const next = !Boolean(user[key]);
          await saveUserFields(user, { [key]: next }, `${user.username} 的${label}已${next ? "开启" : "关闭"}。`);
        }, `account-status-button ${enabled ? "active" : "inactive"}`);
        control.setAttribute("aria-label", `${enabled ? "关闭" : "开通"} ${user.username} 的${label}`);
        control.title = `${label}：${enabled ? "已开通，点击关闭" : "未开通，点击开通"}`;
        control.setAttribute("aria-pressed", String(enabled)); cell.append(control);
      }
      return cell;
    };
    const permissions = accountCell("功能权限", "account-permissions-cell");
    const permissionGroup = el("div", "", "account-permission-grid");
    permissionGroup.append(
      permissionCell("can_training", "每日训练权限", "每日训练"),
      permissionCell("can_coding", "算法题带刷权限", "算法带刷"),
      permissionCell("can_interview", "模拟面试权限", "模拟面试"),
      permissionCell("can_exam", "上机考试权限", "上机考试"),
    );
    permissions.append(permissionGroup);
    if (user.is_admin) permissions.append(el("small", "全部功能已开通", "account-permission-note"));
    row.append(name, password, permissions, active, referrer, service, rebate, pointsCell, actions);
    body.append(row);
  }
  table.append(head, body);
  wrap.append(table);
  wrap.setAttribute("aria-label", "用户账号列表");
  $("userList").replaceChildren(wrap);
}
function syncAccountType() {
  const admin = $("accountTypeAdmin").checked;
  $("accountPermissions").hidden = admin;
  $("accountAdminNote").hidden = !admin;
  $("initialCreditsField").hidden = admin;
  $("accountCredits").disabled = admin;
  $("trainingPermissionField").hidden = admin;
  $("codingPermissionField").hidden = admin;
  $("interviewPermissionField").hidden = admin;
  $("examPermissionField").hidden = admin;
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
      can_training: $("accountTraining").checked,
      can_coding: $("accountCoding").checked,
      can_interview: $("accountInterview").checked,
      can_exam: $("accountExam").checked,
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
  setupBackups();
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
      notify('评测插件网站来源已更新。');
    }).catch(error => {
      status.textContent = error.status === 422
        ? '请输入仅包含协议、域名和端口的地址，不要填写路径或参数。正式网站须使用 HTTPS。'
        : error.message;
      status.hidden = false;
      status.classList.add('form-error');
    }).finally(() => { save.disabled = false; origin.readOnly = false; });
  });
  $("feishuAppId").addEventListener("input", () => { feishuSettingsRevision++; $("feishuSettingsStatus").hidden = true; });
  setupFeishuOAuth();
  $("feishuAppSecret").addEventListener("input", () => { feishuSettingsRevision++; $("feishuSettingsStatus").hidden = true; });
  $("feishuSettingsForm").addEventListener("submit", event => {
    event.preventDefault();
    feishuSettingsRevision++;
    const form = event.currentTarget;
    const save = form.querySelector('[type="submit"]');
    const appId = $("feishuAppId");
    const secret = $("feishuAppSecret");
    const status = $("feishuSettingsStatus");
    save.disabled = true; appId.readOnly = true; secret.readOnly = true; status.hidden = true;
    void api('/admin/feishu-settings', {
      method: 'PATCH',
      body: JSON.stringify({ app_id: appId.value.trim(), redirect_uri: $('feishuRedirectUri').value.trim(), ...(secret.value ? { app_secret: secret.value } : {}) }),
    }).then(settings => {
      appId.value = settings.app_id || '';
      secret.value = '';
      secret.placeholder = settings.app_secret_configured ? '••••••••••••••••（留空保持不变）' : '请输入飞书 App Secret';
      status.textContent = settings.app_secret_configured
        ? `飞书凭证已保存 · 当前来源：${settings.credential_source}` : 'App ID 已保存；App Secret 尚未配置。';
      status.hidden = false; status.classList.remove('form-error');
      notify('飞书授权凭证已保存。');
      void refreshFeishuOAuth();
    }).catch(error => {
      status.textContent = error.message; status.hidden = false; status.classList.add('form-error');
    }).finally(() => { save.disabled = false; appId.readOnly = false; secret.readOnly = false; });
  });
  $("clearFeishuAppSecret").addEventListener("click", async () => {
    if (!await confirmAction('清除后台保存的飞书 App Secret 后，服务端将回退到环境变量中的 FEISHU_APP_SECRET。若环境变量也未配置，飞书文档授权将无法使用。', {
      title: '清除飞书 App Secret？', confirmText: '清除 Secret', danger: true,
    })) return;
    const control = $("clearFeishuAppSecret");
    const status = $("feishuSettingsStatus");
    control.disabled = true; status.hidden = true;
    try {
      const settings = await api('/admin/feishu-settings', { method: 'PATCH', body: JSON.stringify({ clear_app_secret: true }) });
      $("feishuAppSecret").value = '';
      $("feishuAppSecret").placeholder = settings.app_secret_configured ? '使用环境变量中的 Secret' : '请输入飞书 App Secret';
      status.textContent = `后台保存的 Secret 已清除 · 当前来源：${settings.credential_source}`;
      status.hidden = false; status.classList.remove('form-error');
      notify('后台保存的飞书 App Secret 已清除。');
      await refreshFeishuOAuth();
    } catch (error) {
      status.textContent = error.message; status.hidden = false; status.classList.add('form-error');
    } finally { control.disabled = false; }
  });
  $('closeModelServiceDialog').addEventListener('click', () => {
    if ($('modelSettingsForm').dataset.saving !== 'true') $('modelServiceDialog').close();
  });
  $('cancelModelServiceEdit').addEventListener('click', () => {
    if ($('modelSettingsForm').dataset.saving !== 'true') $('modelServiceDialog').close();
  });
  $('modelServiceDialog').addEventListener('cancel', event => {
    if ($('modelSettingsForm').dataset.saving === 'true') event.preventDefault();
  });
  $("modelSettingsForm").addEventListener("submit", event => {
    event.preventDefault();
    const form = event.currentTarget;
    const save = form.querySelector('[type="submit"]');
    const status = $("modelSettingsStatus");
    if (!activeModelService) return;
    const service = {};
    const fields = ['base_url', 'model'];
    if (activeModelService === 'tts') fields.push('provider', 'protocol', 'voice');
    for (const field of fields) {
      service[field] = form.querySelector('[name="' + field + '"]').value;
    }
    const key = form.querySelector('[name="api_key"]').value;
    if (key) service.api_key = key;
    const changes = { [activeModelService]: service };
    form.dataset.saving = 'true'; save.disabled = true; $('cancelModelServiceEdit').disabled = true;
    $('closeModelServiceDialog').disabled = true; status.hidden = true;
    void api('/admin/model-settings', { method: 'PATCH', body: JSON.stringify(changes) })
      .then(settings => {
        renderModelSettings(settings);
        const updated = settings.services[activeModelService];
        const keyInput = form.querySelector('[name="api_key"]');
        keyInput.value = '';
        keyInput.placeholder = updated.api_key_configured ? '••••••••••••••••' : '请输入 API Key';
        $('modelServiceKeyStatus').textContent = updated.api_key_configured
          ? '当前使用：' + updated.api_key_source + ' · 输入新密钥可替换'
          : '尚未配置 API Key';
        status.textContent = '设置已保存，后续请求将使用新配置。';
        status.hidden = false; status.classList.remove('form-error');
        notify('AI 服务设置已保存。');
      }).catch(error => {
        status.textContent = error.message;
        status.hidden = false; status.classList.add('form-error');
      }).finally(() => {
        form.dataset.saving = 'false'; save.disabled = false;
        $('cancelModelServiceEdit').disabled = false; $('closeModelServiceDialog').disabled = false;
      });
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
  $("userEmailSearch").addEventListener("input", renderUsers);
  $("userReferrerSearch").addEventListener("input", renderUsers);
  $("userRoleFilter").addEventListener("change", renderUsers);
  $("userRebateFilter").addEventListener("change", renderUsers);
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
