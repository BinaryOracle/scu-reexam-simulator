import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, badge, emptyState, notify, confirmAction, renderPagination } from "./ui.js?v=20261114-ui-v17";
import { codingField, codingDialog, editCodingQuestion } from "./coding-form.mjs?v=20261115-coding-v1";

let revision = 0;
let listRevision = 0;
let stages = [];
let tab = "questions";
let stageId = "";
let query = "";
let status = "";
let page = 1;
let searchTimer;
const valid = (turn, user) => turn === revision && user === state.user?.id && !$("codingAdmin")?.hidden;

/** Invalidate management requests and close editors on navigation or sign-out. */
export function clearCodingAdmin() {
  revision++; listRevision++; clearTimeout(searchTimer);
  document.querySelectorAll('[data-coding-owner="codingAdmin"]').forEach(dialog => dialog.close());
}

/** Load the management dashboard without losing the current filter selection. */
export async function refreshCodingAdmin() {
  const turn = ++revision; const user = state.user?.id; const root = $("codingAdminContent");
  if (!user || !root) return;
  root.replaceChildren(el("p", "正在载入带刷管理…", "coding-loading"));
  try {
    const [stageResult, settings] = await Promise.all([api("/admin/coding/stages"), api("/admin/coding/settings")]);
    if (!valid(turn, user)) return;
    stages = stageResult.items;
    const header = el("div", "", "coding-admin-heading"); header.append(el("div", "算法带刷管理", "section-title"));
    if (tab === "questions") header.append(button("＋ 新增题目", () => editQuestion(), "button primary"));
    const tabs = el("div", "", "coding-mode-tabs");
    for (const [key, label] of [["questions","题库管理"],["reviews","投稿审核"],["stages","学习阶段"],["settings","奖励规则"]]) {
      const control = button(label, () => { tab = key; page = 1; return refreshCodingAdmin(); }, `button ${tab === key ? "primary" : "secondary"}`); control.setAttribute("aria-pressed", String(tab === key)); tabs.append(control);
    }
    const content = el("div"); content.id = "codingAdminPanel"; root.replaceChildren(header, tabs, content);
    if (tab === "stages") renderStages(content, turn, user);
    else if (tab === "settings") renderSettings(content, settings, turn, user);
    else { renderQuestionControls(content); await loadQuestions(turn, user); }
  } catch (error) { if (valid(turn, user)) root.replaceChildren(emptyState("管理页面加载失败", error.message), button("重试", refreshCodingAdmin)); }
}
function filterSelect(label, options, selected, change) {
  const control = el("select"); control.setAttribute("aria-label", label);
  for (const [value, title] of options) control.append(Object.assign(el("option", title), { value })); control.value = selected;
  control.addEventListener("change", () => change(control.value)); return control;
}
function renderQuestionControls(content) {
  const toolbar = el("div", "", "coding-toolbar");
  const search = el("input"); search.type = "search"; search.placeholder = "搜索题目或知识点"; search.setAttribute("aria-label", search.placeholder); search.value = query;
  const refresh = () => { page = 1; return loadQuestions(revision, state.user.id); };
  search.addEventListener("input", () => { query = search.value; clearTimeout(searchTimer); searchTimer = setTimeout(() => { void refresh(); }, 250); });
  toolbar.append(search, filterSelect("所属阶段", [["","全部阶段"], ...stages.map(stage => [stage.id,stage.title])], stageId, value => { stageId = value; void refresh(); }));
  if (tab === "questions") toolbar.append(filterSelect("审核状态", [["","全部状态"],["pending","等待审核"],["approved","已公开"]], status, value => { status = value; void refresh(); }));
  const list = el("div", "", "coding-admin-list"); list.id = "codingAdminQuestions"; const pagination = el("div", "", "pagination"); pagination.id = "codingAdminPagination";
  content.append(toolbar, list, pagination);
}
async function loadQuestions(turn, user) {
  const current = ++listRevision; const root = $("codingAdminQuestions"); if (!root) return;
  root.setAttribute("aria-busy", "true");
  try {
    const params = new URLSearchParams({ q: query, page, page_size: 20 });
    if (stageId) params.set("stage_id", stageId);
    const selectedStatus = tab === "reviews" ? "pending" : status; if (selectedStatus) params.set("status", selectedStatus);
    const result = await api(`/admin/coding/questions?${params}`);
    if (!valid(turn, user) || current !== listRevision || !root.isConnected) return;
    root.replaceChildren();
    if (!result.items.length) root.append(emptyState(tab === "reviews" ? "没有等待审核的投稿" : "没有符合条件的题目", "调整筛选条件，或新增题目。"));
    for (const question of result.items) {
      const row = el("article", "", "panel coding-admin-question"); const main = el("div");
      main.append(el("h3", question.title), el("p", `${stages.find(stage => stage.id === question.stage_id)?.title || question.stage_id} · ${question.topic} · 难度 ${question.difficulty}/5 · 顺序 ${question.position}`, "muted"));
      const tags = el("div", "", "coding-question-tags"); tags.append(el("span", "★".repeat(question.stars), "coding-stars"), badge(({ draft:"私人草稿",pending:"等待审核",approved:"已公开",rejected:"已拒绝" })[question.review_status] || question.review_status), badge(question.active ? "启用" : "停用", question.active ? "green" : "gray")); main.append(tags);
      if (question.owner_user_id) main.append(el("p", `投稿用户 #${question.owner_user_id}`, "muted"));
      if (question.review_reason) main.append(el("p", `审核意见：${question.review_reason}`, "coding-review-reason"));
      const actions = el("div", "", "coding-actions"); actions.append(button(tab === "reviews" ? "查看并审核" : "编辑题目", () => tab === "reviews" ? reviewQuestion(question, turn, user) : editQuestion(question)));
      if (tab !== "reviews") actions.append(button(question.active ? "停用" : "启用", async () => {
        await api(`/admin/coding/questions/${question.id}`, { method: "PATCH", body: JSON.stringify({ version: question.version, active: !question.active }) });
        if (valid(turn, user)) await loadQuestions(turn, user);
      }, "text-button"), button("删除", async () => {
        if (!await confirmAction(`删除「${question.title}」？删除后将不再参与抽题，已有提交记录会保留。`, { danger: true })) return;
        await api(`/admin/coding/questions/${question.id}`, { method: "DELETE" }); if (valid(turn, user)) await loadQuestions(turn, user);
      }, "text-button"));
      row.append(main, actions); root.append(row);
    }
    renderPagination($("codingAdminPagination"), page, result.total, 20, value => { page = value; return loadQuestions(turn, user); });
  } catch (error) { if (valid(turn, user) && current === listRevision && root.isConnected) root.replaceChildren(emptyState("题库加载失败", error.message), button("重试", () => loadQuestions(turn, user))); }
  finally { if (current === listRevision) root.removeAttribute("aria-busy"); }
}
async function editQuestion(question) {
  const turn = revision; const user = state.user.id;
  // Management list entries contain the full editable question, including private submissions.
  const complete = question || {};
  if (!valid(turn, user)) return;
  editCodingQuestion({ question: complete, stages, admin: true, importLuogu: id => api("/admin/coding/import-luogu", { method: "POST", body: JSON.stringify({ problem_id: id }) }), save: async data => {
    await api(question ? `/admin/coding/questions/${question.id}` : "/admin/coding/questions", { method: question ? "PATCH" : "POST", body: JSON.stringify(data) });
    if (valid(turn, user)) { notify("题目已保存。"); await refreshCodingAdmin(); }
  } });
}
async function reviewQuestion(question, turn, user) {
  const { dialog, body, footer } = codingDialog(`审核：${question.title}`, "codingAdmin");
  body.append(el("p", `${question.topic} · ${question.judge_mode === "luogu" ? `洛谷 ${question.remote_problem_id}` : "公开样例练习"}`), el("pre", question.statement, "coding-review-statement"));
  for (const [index, sample] of (question.samples || []).entries()) body.append(el("h4", `样例 ${index + 1}`), el("pre", `输入：\n${sample.input}\n期望输出：\n${sample.output}`));
  if (question.reference_code) { const reference = el("details"); reference.append(el("summary", "参考代码"), el("pre", question.reference_code)); body.append(reference); }
  const reason = codingField("审核意见（拒绝时必填）", "reason", "", { type: "textarea", rows: 3 }); body.append(reason.wrap);
  const error = el("p", "", "coding-form-error"); error.setAttribute("role", "alert"); body.append(error);
  async function review(approve) {
    if (!approve && !reason.input.value.trim()) { reason.input.focus(); throw new Error("请填写拒绝原因，帮助投稿者修改。"); }
    const controls = [...footer.querySelectorAll("button")]; controls.forEach(control => { control.disabled = true; });
    try {
      await api(`/admin/coding/questions/${question.id}/review`, { method: "POST", body: JSON.stringify({ version: question.version, approve, reason: reason.input.value }) });
      if (dialog.isConnected) dialog.close(); if (valid(turn, user)) { notify(approve ? "投稿已通过并公开。" : "审核意见已保存。"); await loadQuestions(turn, user); }
    } catch (failure) { if (dialog.isConnected) error.textContent = failure.message; }
    finally { controls.forEach(control => { control.disabled = false; }); }
  }
  footer.append(button("拒绝并反馈", () => review(false)), button("通过并公开", () => review(true), "button primary"));
}
function renderStages(content, turn, user) {
  content.append(el("p", "阶段按顺序从小到大展示。停用阶段不进入用户题单和每日抽题；非空阶段不能删除。", "muted"), button("＋ 新增阶段", () => editStage(null, turn, user), "button primary"));
  const list = el("div", "", "coding-admin-list");
  for (const stage of stages) {
    const row = el("article", "", "panel coding-admin-question"); const main = el("div"); main.append(el("h3", stage.title), el("p", stage.description), el("p", `顺序 ${stage.position} · ${stage.active ? "启用" : "停用"}`, "muted"));
    const actions = el("div", "", "coding-actions"); actions.append(button("编辑阶段", () => editStage(stage, turn, user)), button("删除", async () => {
      if (!await confirmAction(`删除阶段「${stage.title}」？请先移走此阶段的全部题目。`, { danger: true })) return;
      await api(`/admin/coding/stages/${encodeURIComponent(stage.id)}`, { method: "DELETE" }); if (valid(turn, user)) await refreshCodingAdmin();
    }, "text-button")); row.append(main, actions); list.append(row);
  } content.append(list);
}
function editStage(stage, turn, user) {
  const { dialog, form, body, footer } = codingDialog(stage ? "编辑学习阶段" : "新增学习阶段", "codingAdmin");
  const title = codingField("阶段名称", "title", stage?.title || "", { required: true });
  const description = codingField("学习目标", "description", stage?.description || "", { type: "textarea", rows: 3 });
  const position = codingField("阶段顺序", "position", stage?.position ?? stages.length, { type: "number", min: 0, required: true });
  const active = codingField("状态", "active", stage?.active === false ? "false" : "true", { options: [["true","启用"],["false","停用"]] });
  body.append(title.wrap, description.wrap, position.wrap, active.wrap);
  const error = el("p", "", "coding-form-error"); error.setAttribute("role", "alert"); const save = el("button", "保存阶段", "button primary"); save.type = "submit"; footer.append(error, save);
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (save.disabled) return; save.disabled = true;
    try {
      await api(stage ? `/admin/coding/stages/${encodeURIComponent(stage.id)}` : "/admin/coding/stages", { method: stage ? "PATCH" : "POST", body: JSON.stringify({ title: title.input.value, description: description.input.value, position: Number(position.input.value), active: active.input.value === "true" }) });
      if (dialog.isConnected) dialog.close(); if (valid(turn, user)) await refreshCodingAdmin();
    } catch (failure) { if (dialog.isConnected) error.textContent = failure.message; }
    finally { save.disabled = false; }
  });
}
function renderSettings(content, settings, turn, user) {
  const panel = el("form", "", "panel coding-settings"); panel.append(el("h3", "投稿奖励规则"), el("p", "仅统计首次审核通过的投稿。新规则只影响后续通过的题目，不重复发奖；管理员不获得奖励。", "muted"));
  const count = codingField("每通过多少道题发奖", "questions_per_reward", settings.questions_per_reward, { type: "number", min: 1, required: true });
  const credits = codingField("每次奖励的面试次数", "credits_per_reward", settings.credits_per_reward, { type: "number", min: 1, required: true });
  const save = el("button", "保存奖励规则", "button primary"); save.type = "submit"; const message = el("p", "", "coding-form-error"); message.setAttribute("role", "status"); panel.append(count.wrap, credits.wrap, save, message);
  panel.addEventListener("submit", async event => {
    event.preventDefault(); if (save.disabled) return; save.disabled = true;
    try { await api("/admin/coding/settings", { method: "PUT", body: JSON.stringify({ questions_per_reward: Number(count.input.value), credits_per_reward: Number(credits.input.value) }) }); if (valid(turn, user)) notify("奖励规则已保存。"); }
    catch (failure) { if (valid(turn, user)) message.textContent = failure.message; } finally { save.disabled = false; }
  });
  content.append(panel, el("p", "每日打卡奖励：连续第 7、14、21…天，分别奖励 1、2、3…次面试。同一天重复打卡不会重复发奖。", "coding-settings-note"));
}
