/** Shared homepage renderer and structured administration of ordered sections. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, notify, confirmAction } from "./ui.js?v=20261114-ui-v17";

export function renderHomeBlocks(root, blocks, navigate) {
  for (const block of blocks.filter(item => item.enabled)) {
    const section = el("section", "", block.type === "roadmap" ? "home-roadmap" : "home-resource-section");
    const heading = el("div", "", "home-section-heading");
    if (block.eyebrow) heading.append(el("div", block.eyebrow, "eyebrow"));
    heading.append(el("h2", block.title));
    if (block.summary) heading.append(el("p", block.summary, "muted"));
    section.append(heading);
    const grid = el("div", "", block.type === "roadmap" ? "home-roadmap-steps" : "home-resource-grid");
    block.items.filter(item => item.enabled).forEach((item, index) => {
      if (block.type === "roadmap") {
        const step = el("article", "", "home-roadmap-stage");
        step.append(el("span", String(index + 1).padStart(2, "0"), "home-stage-number"), el("h3", item.title), el("p", item.summary));
        grid.append(step);
      } else {
        const control = button("", () => {
          if (item.kind === "external") window.open(item.url, "_blank", "noopener,noreferrer");
          else navigate(item.view, item.section);
        }, "home-resource-card");
        if (item.stars) control.append(el("span", "★".repeat(item.stars) + "☆".repeat(5 - item.stars), "home-resource-stars"));
        control.append(el("strong", item.title), el("span", item.summary, "home-resource-summary"));
        if (item.notice) control.append(el("small", item.notice, "home-resource-notice"));
        if (item.kind === "external") control.append(el("span", "外部资料 ↗", "home-resource-type"));
        grid.append(control);
      }
    });
    section.append(grid); root.append(section);
  }
}

let draft = null;
let owner = null;
let baseline = "";
let loading = 0;
let saving = false;
function dirty() { return draft && JSON.stringify(draft) !== baseline; }
const id = () => crypto.randomUUID();
function icon(label, symbol, action) {
  const control = button(symbol, action, "icon-button"); control.title = label; control.setAttribute("aria-label", label); return control;
}
function move(items, index, direction) {
  [items[index], items[index + direction]] = [items[index + direction], items[index]]; renderEditor();
}
function orderControls(items, index, name) {
  const actions = el("div", "", "layout-order");
  const up = icon(`上移${name}`, "↑", () => move(items, index, -1)); up.disabled = index === 0;
  const down = icon(`下移${name}`, "↓", () => move(items, index, 1)); down.disabled = index === items.length - 1;
  actions.append(up, down); return actions;
}
function toggle(item) {
  const label = el("label", "", "permission-switch");
  const input = el("input"); input.type = "checkbox"; input.checked = item.enabled;
  input.setAttribute("aria-label", `展示${item.title}`);
  input.addEventListener("change", () => { item.enabled = input.checked; renderEditor(); });
  label.append(input, el("span", "", "switch-track"), el("span", item.enabled ? "展示" : "隐藏")); return label;
}
function field(form, title, value, { multiline = false, max = 100, required = false } = {}) {
  const wrap = el("div", "", "layout-field");
  const input = el(multiline ? "textarea" : "input"); input.id = `layout-${id()}`; input.value = value || ""; input.maxLength = max; input.required = required;
  const label = el("label", title); label.htmlFor = input.id;
  wrap.append(label, input); form.append(wrap); return input;
}
function select(form, label, value, options) {
  const wrap = el("div", "", "layout-field"); const input = el("select"); input.id = `layout-${id()}`;
  for (const [key, title] of options) { const option = el("option", title); option.value = key; input.append(option); } input.value = value;
  const caption = el("label", label); caption.htmlFor = input.id; wrap.append(caption, input); form.append(wrap); return { input, wrap };
}
function editorDialog(title) {
  const dialog = el("dialog", "", "account-dialog layout-dialog");
  const heading = el("div", "", "dialog-header"); const h = el("h2", title); h.id = `layout-title-${id()}`; dialog.setAttribute("aria-labelledby", h.id);
  heading.append(h, icon("关闭", "×", () => dialog.close()));
  const form = el("form"); const body = el("div", "", "dialog-body layout-fields");
  const footer = el("div", "", "dialog-footer"); const save = el("button", "保存到草稿", "button primary"); save.type = "submit";
  footer.append(button("取消", () => dialog.close(), "button secondary"), save); form.append(body, footer); dialog.append(heading, form);
  document.body.append(dialog); dialog.addEventListener("close", () => dialog.remove(), { once: true });
  return { dialog, form, body };
}
function editBlock(block = null, type = "resources") {
  const { dialog, form, body } = editorDialog(block ? "编辑区块" : type === "roadmap" ? "新增备考路线" : "新增资源分组");
  const title = field(body, "区块标题", block?.title, { required: true });
  const eyebrow = field(body, "上方小标题", block?.eyebrow);
  const summary = field(body, "说明", block?.summary, { multiline: true, max: 1000 });
  form.addEventListener("submit", event => {
    event.preventDefault(); if (!title.value.trim()) { title.setCustomValidity("请输入标题"); title.reportValidity(); return; }
    const changes = { title: title.value.trim(), eyebrow: eyebrow.value, summary: summary.value };
    if (block) Object.assign(block, changes); else draft.blocks.push({ id: id(), type, enabled: true, items: [], ...changes });
    dialog.close(); renderEditor();
  });
  title.addEventListener("input", () => title.setCustomValidity("")); dialog.showModal();
}
function editItem(block, item = null) {
  const { dialog, form, body } = editorDialog(block.type === "roadmap" ? "编辑路线步骤" : "编辑资源卡片");
  const title = field(body, "标题", item?.title, { required: true });
  const summary = field(body, "介绍", item?.summary, { multiline: true, max: 1000 });
  let stars, notice, kind, view, section, url;
  if (block.type === "resources") {
    stars = select(body, "重要性", String(item?.stars ?? 3), Array.from({ length: 6 }, (_, n) => [String(n), n ? "★".repeat(n) : "不显示重点星级"]));
    notice = field(body, "补充备注", item?.notice, { max: 1000 });
    kind = select(body, "跳转类型", item?.kind || "view", [["view", "站内页面"], ["external", "外部链接"]]);
    view = select(body, "目标页面", item?.view || "training", [["training", "每日训练"], ["coding", "算法带刷"], ["interview", "模拟面试"], ["contest", "上机考试"], ["profile", "个人主页"], ["home", "备考首页"]]);
    section = select(body, "训练篇目", item?.section || "", [["", "默认篇目"], ["interview", "面试篇"], ["written_c", "笔试 · 软件工程篇"], ["written_ai", "笔试 · 人工智能篇"]]);
    url = field(body, "外部链接", item?.url, { max: 2000 }); url.type = "url";
    const sync = () => {
      const external = kind.input.value === "external";
      view.wrap.hidden = external; section.wrap.hidden = external || view.input.value !== "training";
      url.closest(".layout-field").hidden = !external; url.required = external; url.disabled = !external;
    };
    kind.input.addEventListener("change", sync); view.input.addEventListener("change", sync); sync();
  }
  form.addEventListener("submit", event => {
    event.preventDefault(); if (!title.value.trim()) { title.setCustomValidity("请输入标题"); title.reportValidity(); return; }
    const changes = { title: title.value.trim(), summary: summary.value };
    if (block.type === "resources") Object.assign(changes, { stars: Number(stars.input.value), notice: notice.value, kind: kind.input.value,
      view: view.input.value, section: view.input.value === "training" ? section.input.value : "", url: url.value.trim() });
    if (item) Object.assign(item, changes); else block.items.push({ id: id(), enabled: true, ...changes });
    dialog.close(); renderEditor();
  });
  title.addEventListener("input", () => title.setCustomValidity("")); dialog.showModal();
}
function preview() {
  const { dialog, body, form } = editorDialog("首页预览"); dialog.classList.add("layout-preview-dialog");
  form.querySelector(".dialog-footer").replaceChildren(button("关闭预览", () => dialog.close(), "button secondary"));
  renderHomeBlocks(body, draft.blocks, () => notify("预览中不跳转站内页面")); dialog.showModal();
}
function renderEditor() {
  const root = $("homeLayoutAdmin"); root.replaceChildren();
  const head = el("div", "", "page-heading"); const text = el("div");
  text.append(el("span", "PREPARATION HOME", "eyebrow"), el("h1", "首页编排"), el("p", "管理备考路线及下方资源，按展示顺序发布到首页。", "muted"));
  const actions = el("div", "", "action-group");
  actions.append(button("重新加载", async () => {
    if (dirty() && !await confirmAction("当前草稿将被丢弃。", { title: "重新加载已发布配置？", confirmText: "重新加载" })) return;
    draft = null; await refreshHomeLayoutAdmin();
  }, "button secondary"), button("预览", preview, "button secondary"));
  const publish = button(saving ? "正在发布…" : "发布修改", async () => {
    saving = true; renderEditor(); const token = state.token;
    try {
      const result = await api("/admin/home-layout", { method: "PUT", body: JSON.stringify(draft) });
      if (state.token !== token) return; draft = result; baseline = JSON.stringify(result); notify("首页配置已发布。");
    } finally { saving = false; if (state.token === token) renderEditor(); }
  }, "button primary"); publish.disabled = saving || !dirty(); actions.append(publish); head.append(text, actions); root.append(head);
  root.append(el("p", `${dirty() ? "有未发布的修改" : "已与线上同步"} · 版本 ${draft.revision}`, "layout-save-state"));
  const content = el("div", "", "layout-blocks");
  for (const [index, block] of draft.blocks.entries()) {
    const row = el("section", "", `layout-block${block.enabled ? "" : " layout-hidden"}`);
    const bar = el("div", "", "layout-block-header");
    const label = el("div", "", "layout-block-label"); label.append(el("span", block.type === "roadmap" ? "备考路线" : "资源分组", "eyebrow"), el("h2", block.title));
    const controls = el("div", "", "layout-controls");
    controls.append(toggle(block), orderControls(draft.blocks, index, "区块"), button("编辑", () => editBlock(block), "text-button"), icon("删除区块", "×", async () => {
      if (await confirmAction(`删除「${block.title}」及其中 ${block.items.length} 项内容？发布后生效。`, { title: "删除区块？", danger: true })) { draft.blocks.splice(index, 1); renderEditor(); }
    })); bar.append(label, controls); row.append(bar);
    if (block.summary) row.append(el("p", block.summary, "muted"));
    for (const [n, item] of block.items.entries()) {
      const line = el("div", "", `layout-item${item.enabled ? "" : " layout-hidden"}`);
      const copy = el("div", "", "layout-item-copy"); copy.append(el("strong", item.title));
      if (item.summary) copy.append(el("span", item.summary));
      if (block.type === "resources") copy.append(el("small", `${"★".repeat(item.stars)} · ${item.kind === "external" ? item.url : "站内页面"}`, "muted"));
      const actions = el("div", "", "layout-controls"); actions.append(toggle(item), orderControls(block.items, n, "内容"), button("编辑", () => editItem(block, item), "text-button"), icon("删除内容", "×", async () => {
        if (await confirmAction(`删除「${item.title}」？发布后生效。`, { title: "删除内容？", danger: true })) { block.items.splice(n, 1); renderEditor(); }
      })); line.append(copy, actions); row.append(line);
    }
    row.append(button(block.type === "roadmap" ? "＋ 添加路线步骤" : "＋ 添加资源卡片", () => editItem(block), "button secondary")); content.append(row);
  }
  root.append(content);
  const add = el("div", "", "layout-add-block"); add.append(button("＋ 新增备考路线", () => editBlock(null, "roadmap"), "button secondary"), button("＋ 新增资源分组", () => editBlock(), "button secondary")); root.append(add);
  if (saving) for (const control of root.querySelectorAll("button, input")) control.disabled = true;
}

export async function refreshHomeLayoutAdmin() {
  const token = state.token; const turn = ++loading;
  if (owner !== token) { draft = null; baseline = ""; owner = token; }
  if (!draft || !dirty()) {
    const result = await api("/admin/home-layout");
    if (token !== state.token || turn !== loading) return;
    draft = result; baseline = JSON.stringify(result);
  }
  renderEditor();
}
window.addEventListener("beforeunload", event => { if (owner === state.token && dirty()) { event.preventDefault(); event.returnValue = ""; } });
