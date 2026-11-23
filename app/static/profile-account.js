/** Authenticated account settings; changing a mailbox always verifies the new address. */
import { api, state } from "./api.js?v=20261122-session-guard-v1";
import { $, el, notify } from "./ui.js?v=20261114-ui-v17";

const cooldowns = new Map();
let passwordRequestVersion = 0;
export function clearProfilePassword() {
  passwordRequestVersion++;
  $("profilePasswordValue").textContent = "••••••••";
  $("profilePasswordToggleLabel").textContent = "查看";
  const control = $("profileRevealPassword");
  control.disabled = false;
  control.setAttribute("aria-label", "查看登录密码");
  control.setAttribute("aria-pressed", "false");
}
export function refreshAccountSettings() {
  const user = state.user;
  if (!user) return false;
  clearProfilePassword();
  $("profileAccountUsername").textContent = user.username;
  $("profileAccountEmail").textContent = user.email || "尚未绑定";
  $("profileEditEmail").textContent = user.email ? "变更绑定邮箱" : "绑定邮箱";
  const deleteRow = $("profileDeleteAccount").closest(".profile-delete-row");
  deleteRow.hidden = user.is_superadmin;
  $("profileDeleteAccount").hidden = user.is_superadmin;
  $("profileDeleteHint").textContent = "永久删除账号、面试录音、PPT 与练习记录，剩余次数不退回。";
  return true;
}
function field(body, id, label, { type = "text", value = "", autocomplete = "off" } = {}) {
  const caption = el("label", label); caption.htmlFor = id;
  const input = el("input"); input.id = id; input.type = type;
  input.value = value; input.autocomplete = autocomplete; input.required = true;
  body.append(caption, input); return input;
}
function openSettings(kind) {
  const titles = { username: "修改用户名", password: "修改登录密码", email: state.user.email ? "变更绑定邮箱" : "绑定邮箱", delete: "注销当前账号" };
  const dialog = el("dialog", "", "account-dialog profile-account-dialog");
  const form = el("form");
  const header = el("div", "", "dialog-header");
  const title = el("h2", titles[kind]); title.id = "profileAccountDialogTitle";
  dialog.setAttribute("aria-labelledby", title.id);
  const close = el("button", "×", "icon-button"); close.type = "button";
  close.setAttribute("aria-label", "关闭账号设置"); header.append(title, close);
  const body = el("div", "", "dialog-body");
  const description = el("p", "", "dialog-description"); description.id = "profileAccountDescription";
  dialog.setAttribute("aria-describedby", description.id); body.append(description);
  let username, email, password, passwordConfirm, currentPassword, confirmation, code, send;
  const mailboxSecurity = kind === "email" || (state.user.email && ["password", "delete"].includes(kind));
  if (kind === "username") {
    description.textContent = "修改后请使用新用户名进行密码登录。绑定邮箱、剩余次数和历史记录保持不变。";
    username = field(body, "profileNewUsername", "新用户名", { value: state.user.username, autocomplete: "username" });
  } else if (kind === "email") {
    description.textContent = state.user.email ? `当前邮箱：${state.user.email}。验证码将发送到新邮箱；验证成功后，旧邮箱不能再登录此账号，其他设备需要重新登录。` : "填写你的邮箱，接收并验证邮件中的验证码后完成绑定。";
    email = field(body, "profileNewEmail", "新邮箱", { type: "email", autocomplete: "email" });
    email.maxLength = 254;
  } else if (kind === "password") {
    description.textContent = state.user.email ? `验证码将发送到绑定邮箱 ${state.user.email}，验证后可设置新密码，无需知道随机初始密码。` : "请先验证当前密码，再设置新密码。你也可以先绑定邮箱，使用邮箱验证码验证身份。";
    password = field(body, "profileNewPassword", "新密码", { type: "password", autocomplete: "new-password" });
    passwordConfirm = field(body, "profileConfirmPassword", "再次输入新密码", { type: "password", autocomplete: "new-password" });
    passwordConfirm.addEventListener("input", () => passwordConfirm.setCustomValidity(""));
    password.addEventListener("input", () => passwordConfirm.setCustomValidity(""));
  } else {
    description.textContent = "注销后将永久删除账号、面试录音、PPT、回答和上机提交，剩余次数不退回，已兑换的卡密仍保持已使用。此操作不可撤销。";
    description.classList.add("account-deletion-warning");
    confirmation = field(body, "profileDeleteConfirmation", `请输入当前用户名“${state.user.username}”确认`);
    confirmation.addEventListener("input", () => confirmation.setCustomValidity(""));
  }
  const status = el("p", "", "field-help"); status.setAttribute("role", "status"); status.hidden = true;
  const error = el("p", "", "form-error"); error.setAttribute("role", "alert"); error.hidden = true;
  let sending = false;
  let saving = false;
  const key = kind;
  let timer;
  function updateSend() {
    if (!send) return;
    const seconds = Math.max(0, Math.ceil(((cooldowns.get(key) || 0) - Date.now()) / 1000));
    send.disabled = saving || sending || seconds > 0;
    send.textContent = sending ? "发送中…" : seconds ? `${seconds} 秒后重发` : "获取验证码";
  }
  if (mailboxSecurity) {
    const label = el("label", "邮件验证码"); label.htmlFor = "profileSecurityCode";
    const row = el("div", "", "email-code-row");
    code = el("input"); code.id = label.htmlFor; code.inputMode = "numeric";
    code.autocomplete = "one-time-code"; code.pattern = "[0-9]{6}"; code.maxLength = 6;
    code.placeholder = "6 位验证码"; code.required = true;
    send = el("button", "获取验证码", "button secondary"); send.type = "button";
    row.append(code, send); body.append(label, row, status);
    if (email) email.addEventListener("input", () => { code.value = ""; status.hidden = true; });
    send.addEventListener("click", async () => {
      if (sending || send.disabled || (email && !email.reportValidity())) return;
      error.hidden = true; sending = true; updateSend();
      if (email) email.readOnly = true;
      const target = email ? email.value.trim() : state.user.email;
      try {
        const data = await api(kind === "email" ? "/profile/email/code" : "/profile/security/code", {
          method: "POST", body: JSON.stringify(kind === "email" ? { email: target } : { purpose: kind }),
        });
        cooldowns.set(key, Date.now() + (data.retry_after || 60) * 1000);
        if (dialog.open) {
          status.textContent = `验证码已发送至 ${target}，请查收邮件。`;
          status.hidden = false; code.focus();
        }
      } catch (failure) {
        if (failure.retryAfterSeconds) cooldowns.set(key, Date.now() + failure.retryAfterSeconds * 1000);
        if (dialog.open) {
          error.textContent = failure.retryAfterSeconds
            ? `请求过于频繁，请在 ${failure.retryAfterSeconds} 秒后重试`
            : failure.message;
          error.hidden = false;
        }
      } finally { sending = false; if (email) email.readOnly = false; updateSend(); }
    });
    updateSend(); timer = setInterval(updateSend, 1000);
  } else if (["password", "delete"].includes(kind)) {
    currentPassword = field(body, "profileCurrentPassword", "当前密码", { type: "password", autocomplete: "current-password" });
  }
  body.append(error);
  const footer = el("div", "", "dialog-footer");
  const cancel = el("button", "取消", "button secondary"); cancel.type = "button";
  const save = el("button", kind === "delete" ? "确认注销账号" : "保存修改", `button ${kind === "delete" ? "danger-button" : "primary"}`); save.type = "submit";
  footer.append(cancel, save); form.append(header, body, footer); dialog.append(form);
  close.addEventListener("click", () => { if (!saving) dialog.close(); });
  cancel.addEventListener("click", () => { if (!saving) dialog.close(); });
  dialog.addEventListener("cancel", event => { if (saving) event.preventDefault(); });
  dialog.addEventListener("close", () => { clearInterval(timer); dialog.remove(); }, { once: true });
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (saving) return;
    if (password && password.value !== passwordConfirm.value) {
      passwordConfirm.setCustomValidity("两次输入的密码不一致"); passwordConfirm.reportValidity(); return;
    }
    if (confirmation && confirmation.value !== state.user.username) {
      confirmation.setCustomValidity("请输入完整的当前用户名"); confirmation.reportValidity(); return;
    }
    let path, payload;
    const identity = code ? { code: code.value } : currentPassword ? { current_password: currentPassword.value } : {};
    if (kind === "username") { path = "/profile/username"; payload = { username: username.value }; }
    else if (kind === "email") { path = "/profile/email"; payload = { email: email.value.trim(), code: code.value }; }
    else if (kind === "password") { path = "/profile/password"; payload = { password: password.value, ...identity }; }
    else { path = "/profile/account"; payload = identity; }
    saving = true; save.disabled = true; close.disabled = true; cancel.disabled = true; error.hidden = true;
    if (send) send.disabled = true;
    try {
      const result = await api(path, { method: kind === "delete" ? "DELETE" : "POST", body: JSON.stringify(payload) });
      dialog.close();
      if (["password", "delete"].includes(kind)) {
        window.dispatchEvent(new CustomEvent("account-session-ended", { detail: {
          message: kind === "delete" ? "账号已注销。" : "密码已更新，请重新登录。",
          deleted: kind === "delete",
        } }));
      } else {
        state.user = { ...state.user, ...result };
        window.dispatchEvent(new Event("account-access-updated"));
        notify(kind === "email" ? "邮箱已验证并完成绑定。" : "用户名已更新。");
      }
    } catch (failure) {
      error.textContent = failure.message; error.hidden = false;
    } finally {
      saving = false; save.disabled = false; close.disabled = false; cancel.disabled = false; updateSend();
    }
  });
  document.body.append(dialog); dialog.showModal();
}
export function setupAccountSettings() {
  const control = $("profileRevealPassword");
  control.addEventListener("click", async () => {
    if (control.getAttribute("aria-pressed") === "true") { clearProfilePassword(); return; }
    const version = ++passwordRequestVersion;
    const token = state.token;
    control.disabled = true;
    $("profilePasswordToggleLabel").textContent = "读取中…";
    try {
      const result = await api("/profile/reveal-password", { method: "POST" });
      if (version !== passwordRequestVersion || token !== state.token || $("profile").hidden) return;
      $("profilePasswordValue").textContent = result.password;
      $("profilePasswordToggleLabel").textContent = "隐藏";
      control.setAttribute("aria-label", "隐藏登录密码");
      control.setAttribute("aria-pressed", "true");
    } catch (failure) {
      if (version === passwordRequestVersion) {
        clearProfilePassword();
        notify(failure.message, "error");
      }
    } finally {
      if (version === passwordRequestVersion) control.disabled = false;
    }
  });
  document.addEventListener("visibilitychange", () => { if (document.hidden) clearProfilePassword(); });
  for (const [id, action] of [["profileEditUsername", "username"], ["profileEditEmail", "email"], ["profileEditPassword", "password"], ["profileDeleteAccount", "delete"]])
    $(id).addEventListener("click", () => openSettings(action));
}
