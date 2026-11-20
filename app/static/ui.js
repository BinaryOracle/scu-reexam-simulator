/** Shared DOM components. User and model content is rendered as text. */
export const $ = (id) => document.getElementById(id);
export function el(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
}
let noticeTimer;
export function notify(message, kind = "success") {
  clearTimeout(noticeTimer);
  const node = $("notification");
  const close = el("button", "×", "notification-close");
  close.type = "button";
  close.setAttribute("aria-label", "关闭提示");
  close.addEventListener("click", () => { node.hidden = true; });
  node.replaceChildren(el("span", message), close);
  node.className = `notification ${kind}`;
  node.hidden = false;
  if (kind !== "error")
    noticeTimer = setTimeout(() => {
      node.hidden = true;
    }, 6000);
}
export async function run(action, control) {
  if (control?.disabled) return;
  if (control) {
    control.disabled = true;
    control.classList.add("busy-label");
  }
  try {
    await action();
  } catch (error) {
    notify(error.message || "操作失败，请稍后重试", "error");
  } finally {
    if (control) {
      control.disabled = false;
      control.classList.remove("busy-label");
    }
  }
}
export function button(text, action, className = "button secondary") {
  const node = el("button", text, className);
  node.type = "button";
  node.addEventListener("click", () => run(action, node));
  return node;
}

let dialogQueue = Promise.resolve();
function siteDialog({ title, message, confirmText = "确定", danger = false, input = null }) {
  const task = () => new Promise(resolve => {
    const previousFocus = document.activeElement;
    const dialog = el("dialog", "", "account-dialog action-dialog");
    const form = el("form");
    const header = el("div", "", "dialog-header");
    const heading = el("h2", title); heading.id = "siteDialogTitle";
    dialog.setAttribute("aria-labelledby", heading.id);
    const cancel = el("button", "取消", "button secondary"); cancel.type = "button";
    const close = el("button", "×", "icon-button"); close.type = "button";
    close.setAttribute("aria-label", "关闭对话框");
    header.append(heading, close);
    const body = el("div", "", "dialog-body");
    const description = el("p", message, "dialog-description"); description.id = "siteDialogDescription";
    dialog.setAttribute("aria-describedby", description.id); body.append(description);
    let field;
    if (input) {
      const label = el("label", input.label || "名称"); label.htmlFor = "siteDialogInput";
      field = el("input"); field.id = label.htmlFor; field.value = input.value || "";
      field.required = true; field.maxLength = input.maxLength || 100;
      field.addEventListener("input", () => field.setCustomValidity(""));
      body.append(label, field);
    }
    const footer = el("div", "", "dialog-footer");
    const submit = el("button", confirmText, `button ${danger ? "danger-button" : "primary"}`);
    submit.type = "submit"; footer.append(cancel, submit); form.append(header, body, footer); dialog.append(form);
    close.addEventListener("click", () => dialog.close());
    cancel.addEventListener("click", () => dialog.close());
    let result = null;
    form.addEventListener("submit", event => {
      event.preventDefault();
      if (field && !field.value.trim()) {
        field.setCustomValidity("名称不能为空"); field.reportValidity(); return;
      }
      result = field ? field.value.trim() : true; dialog.close();
    });
    dialog.addEventListener("close", () => {
      dialog.remove(); resolve(result);
      requestAnimationFrame(() => { if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus({ preventScroll: true }); });
    }, { once: true });
    (document.fullscreenElement || document.body).append(dialog);
    dialog.showModal();
    (field || cancel).focus(); field?.select();
  });
  const result = dialogQueue.then(task);
  dialogQueue = result.catch(() => {});
  return result;
}
export function confirmAction(message, options = {}) {
  return siteDialog({ title: "确认操作", message, ...options });
}
export function requestText(title, value, options = {}) {
  return siteDialog({ title, message: "为这场面试设置一个方便查找的名称。", confirmText: "保存名称", input: { value }, ...options });
}
export function badge(text, kind = "gray") {
  return el("span", text, `badge ${kind}`);
}
export function emptyState(title, description, icon = "◉") {
  const node = el("div", "", "empty-state");
  node.append(
    el("span", icon, "empty-icon"),
    el("h3", title),
    el("p", description),
  );
  return node;
}
export function dateTime(value) {
  return new Date(value * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}
export function sectionHeading(title, caption = "") {
  const heading = el("div", "", "section-heading");
  const text = el("h2", title);
  if (caption) text.append(el("span", caption, "section-caption"));
  heading.append(text);
  return heading;
}
export function renderPagination(container, page, total, pageSize, change) {
  const pageCount = Math.ceil(total / pageSize);
  container.replaceChildren();
  container.hidden = pageCount <= 1;
  if (container.hidden) return;
  const previous = button("上一页", () => change(page - 1), "button secondary");
  previous.disabled = page <= 1;
  const next = button("下一页", () => change(page + 1), "button secondary");
  next.disabled = page >= pageCount;
  container.append(previous, el("span", `第 ${page} / ${pageCount} 页`), next);
}
export function statusBadge(status) {
  const labels = {
    Accepted: ["通过", "green"],
    "Wrong Answer": ["答案错误", "red"],
    "Runtime Error": ["运行错误", "red"],
    "Judge Error": ["评测服务异常", "red"],
    "Waiting for browser extension": ["等待插件", "orange"],
    Submitted: ["已提交洛谷", "blue"],
    Judging: ["洛谷评测中", "blue"],
    "Compile Error": ["编译错误", "red"],
    "Time Limit Exceeded": ["超时", "orange"],
    "Memory Limit Exceeded": ["超内存", "orange"],
    "Runtime Error": ["运行错误", "red"],
    "Wrong Answer": ["答案错误", "red"],
    "System Error": ["评测异常", "red"],
    "Output Limit Exceeded": ["输出超限", "orange"],
    "Submission Failed": ["提交失败", "red"],
    "Time Limit Exceeded": ["运行超时", "orange"],
    Judging: ["评测中", "blue"],
    "Unsupported language": ["语言不支持", "gray"],
  };
  const [label, kind] = labels[status] || [status, "gray"];
  const node = badge(label, kind);
  node.title = status;
  return node;
}
