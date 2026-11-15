import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, badge, emptyState, notify, confirmAction, statusBadge, renderPagination } from "./ui.js?v=20261114-ui-v17";
import { appendProblemStatement } from "./problem-content.js?v=20261115-resource-limits-v1";
import { writeAppRoute } from "./view-route.mjs?v=20261115-navigation-v3";
import { createCodeDrafts, saveDraftOnShortcut } from "./code-drafts.mjs?v=20261115-drafts-v3";
import { createLayoutStore, mountWorkspaceLayout } from "./workspace-layout.mjs?v=20261115-workspace-v5";
import { editCodingQuestion, codingDialog } from "./coding-form.mjs?v=20261115-coding-v1";
import { codingQuestionId, filterCodingQuestions, codingDraftKey, acceptsCodingStatus } from "./coding-model.mjs?v=20261115-coding-v1";

let revision = 0;
let requestLuoguSubmit;

/** Share one bridge instance even when contest assets receive a new cache version. */
export function configureCodingBridge(submit) {
  requestLuoguSubmit = submit;
}
let listRevision = 0;
let recordsRevision = 0;
let home;
let selectedQuestion = null;
let mode = "roadmap";
let stageId = "";
let query = "";
let topic = "";
let stars = "0";
let order = "stage";
let page = 1;
let disposeLayout;
let searchTimer;
let recordTarget;
const drafts = createCodeDrafts(() => window.localStorage);
const pending = new Map();
const resultTargets = new Map();
const terminal = new Set(["Accepted", "Wrong Answer", "Runtime Error", "Compile Error", "Time Limit Exceeded", "Memory Limit Exceeded", "Output Limit Exceeded", "Judge Error", "System Error", "Submission Failed"]);
const languages = [["cpp11", "C++11"], ["c", "C"], ["python3", "Python 3"]];
const reviewLabels = { draft: "私人草稿", pending: "审核中", approved: "已公开", rejected: "需修改" };
const active = (request, userId) => revision === request && state.user?.id === userId && !$("coding")?.hidden;

/** Stop workspace listeners and invalidate requests when leaving the practice view. */
export function clearCoding() {
  document.body.classList.remove("coding-immersive");
  revision++; listRevision++; recordsRevision++;
  clearTimeout(searchTimer); disposeLayout?.(); disposeLayout = null;
  selectedQuestion = null; recordTarget = null; resultTargets.clear();
  document.querySelectorAll('[data-coding-owner="coding"]').forEach(dialog => dialog.close());
  if (!state.user) { home = null; pending.clear(); stageId = ""; query = ""; topic = ""; mode = "roadmap"; }
}

/** Restore the selected question from browser history or refresh the practice dashboard. */
export async function refreshCoding() {
  const request = ++revision;
  const userId = state.user?.id;
  if (!userId || !$("codingContent")) return;
  disposeLayout?.(); disposeLayout = null; clearTimeout(searchTimer);
  selectedQuestion = null; recordTarget = null;
  const root = $("codingContent"); root.setAttribute("aria-busy", "true");
  root.replaceChildren(el("p", "正在载入算法带刷…", "coding-loading"));
  const id = codingQuestionId(location.hash);
  document.body.classList.toggle("coding-immersive", Boolean(id));
  try {
    const [data, question] = await Promise.all([api("/coding/home"), id ? api(`/coding/questions/${id}`) : Promise.resolve(null)]);
    if (!active(request, userId)) return;
    home = data;
    if (question) { selectedQuestion = question; renderWorkspace(question, request, userId); }
    else { renderHome(); await loadQuestions(request, userId); }
  } catch (error) {
    if (!active(request, userId)) return;
    root.replaceChildren(emptyState("暂时无法打开练习", error.message), button("重试", refreshCoding));
    if (id) root.append(button("返回题单", goHome));
  } finally { if (active(request, userId)) root.removeAttribute("aria-busy"); }
}
function goHome() { writeAppRoute("coding"); return refreshCoding(); }
function openQuestion(id) { writeAppRoute(`coding/question/${id}`); return refreshCoding(); }
function select(label, options, value, onChange) {
  const control = el("select"); control.setAttribute("aria-label", label);
  for (const [key, title] of options) control.append(Object.assign(el("option", title), { value: key }));
  control.value = value; control.addEventListener("change", () => onChange(control.value)); return control;
}
function refreshList() { page = 1; return loadQuestions(revision, state.user.id); }
function renderHome() {
  const root = $("codingContent");
  const hero = el("section", "", "coding-hero");
  const intro = el("div"); intro.append(el("span", "ALGORITHM PRACTICE", "eyebrow"), el("h2", "一步一步，练出解题能力"), el("p", "从基础到进阶，按阶段积累。没有倒计时，每一次思考都算数。"));
  const progress = el("div", "", "coding-progress-summary");
  progress.append(el("strong", `${home.progress.solved}`), el("span", `/ ${home.progress.total} 题已通过`));
  hero.append(intro, progress);
  const daily = el("section", "", "coding-daily panel");
  const dailyText = el("div"); dailyText.append(el("span", "DAILY CHALLENGE", "eyebrow"), el("h3", home.daily.question_title || "今天，从一道题开始"), el("p", `${home.daily.date} · 连续打卡 ${home.daily.streak} 天 · 每连续 7 天递增奖励：第 7 天 1 次、第 14 天 2 次面试`));
  const dailyActions = el("div", "", "coding-actions");
  const dailyUnavailable = home.daily.question_id && home.daily.available === false;
  const dailyStart = button(dailyUnavailable ? "今日题目暂不可用" : home.daily.question_id ? "继续每日一题 →" : "随机抽取今日题 →", async () => {
    const current = revision; const owner = state.user.id;
    const result = await api("/coding/daily", { method: "POST" });
    if (active(current, owner) && result.available !== false) await openQuestion(result.question_id);
    else if (active(current, owner)) await refreshCoding();
  }, "button primary");
  dailyStart.disabled = Boolean(dailyUnavailable);
  if (dailyUnavailable) dailyStart.title = "今日抽中的题目已停用或撤回，请联系管理员；明天可抽取新题。";
  dailyActions.append(dailyStart);
  if (home.daily.checked_in) dailyActions.append(badge("今日已打卡", "green"));
  else {
    const checkin = button("完成打卡", async () => {
      const current = revision; const owner = state.user.id;
      const result = await api("/coding/checkin", { method: "POST" });
      if (!active(current, owner)) return;
      notify(result.already_checked ? "今天已经打卡。" : `打卡成功，连续 ${result.streak} 天${result.credits ? `，获得 ${result.credits} 次面试` : ""}。`);
      await refreshCoding();
    });
    checkin.disabled = !home.daily.solved;
    checkin.title = "通过当天抽中的题目后即可打卡"; dailyActions.append(checkin);
  }
  daily.append(dailyText);
  if (home.can_coding) daily.append(dailyActions);
  else daily.append(el("p", "算法题带刷权限尚未开通，题目浏览与个人投稿仍可使用。", "practice-access-notice"));
  const tabs = el("div", "", "coding-mode-tabs");
  for (const [key, label] of [["roadmap", "阶段题单"], ["mine", "我的投稿"], ["solved", "已完成"], ["failed", "尝试未通过"], ["favorites", "收藏"]]) {
    const tab = button(label, () => { mode = key; stageId = ""; topic = ""; page = 1; renderHome(); return refreshList(); }, `button ${mode === key ? "primary" : "secondary"}`);
    tab.setAttribute("aria-pressed", String(mode === key)); tabs.append(tab);
  }
  root.replaceChildren(hero);
  if (mode === "roadmap") root.append(daily);
  root.append(tabs);
  if (mode === "roadmap") {
    const roadmap = el("nav", "", "coding-roadmap"); roadmap.setAttribute("aria-label", "由易到难的学习阶段");
    for (const [index, stage] of home.stages.entries()) {
      const card = button("", () => { stageId = String(stage.id); topic = ""; renderHome(); return refreshList(); }, `coding-stage ${String(stage.id) === stageId ? "selected" : ""}`);
      card.setAttribute("aria-pressed", String(String(stage.id) === stageId));
      card.disabled = !home.can_coding;
      const top = el("div", "", "coding-stage-top"); top.append(el("span", String(index + 1).padStart(2, "0"), "coding-stage-number"), badge(stage.total && stage.solved >= stage.total ? "已完成" : `${stage.solved}/${stage.total}`, stage.total && stage.solved >= stage.total ? "green" : "gray"));
      card.append(top, el("h3", stage.title), el("p", stage.description));
      const meter = el("progress"); meter.max = Math.max(stage.total, 1); meter.value = stage.solved; meter.setAttribute("aria-label", `${stage.title}已通过 ${stage.solved} / ${stage.total} 题`); card.append(meter); roadmap.append(card);
    }
    root.append(roadmap);
  } else if (mode === "mine") {
    const contribution = el("div", "", "coding-contribution panel");
    contribution.append(el("div", `已公开 ${home.contribution.approved_count} 道 · 已获得 ${home.contribution.credits_earned} 次面试奖励`), el("p", `每 ${home.contribution.questions_per_reward} 道首次审核通过，获得 ${home.contribution.credits_per_reward} 次面试。私人题只对自己可见，也参与自己的每日抽题。`, "muted"), button("＋ 添加我的题目", () => editQuestion(), "button primary")); root.append(contribution);
  }
  if (!home.can_coding && mode !== "mine") return;
  const toolbar = el("div", "", "coding-toolbar");
  const search = el("input"); search.type = "search"; search.placeholder = "搜索题目或知识点"; search.setAttribute("aria-label", "搜索题目或知识点"); search.value = query;
  search.addEventListener("input", () => { query = search.value; clearTimeout(searchTimer); searchTimer = setTimeout(() => { void refreshList(); }, 250); });
  toolbar.append(search, select("所属阶段", [["", "全部阶段"], ...home.stages.map(stage => [stage.id, stage.title])], stageId, value => { stageId = value; topic = ""; renderHome(); void refreshList(); }));
  const topicSelect = select("知识点筛选", [["", "全部知识点"]], topic, value => { topic = value; void refreshList(); }); topicSelect.id = "codingTopic";
  toolbar.append(topicSelect, select("重要性筛选", [[0,"全部星级"],[3,"三星及以上"],[4,"四星及以上"],[5,"五星重点"]], stars, value => { stars = value; void refreshList(); }), select("题目排序", [["stage","阶段顺序"],["difficulty","由易到难"],["stars","重要性优先"]], order, value => { order = value; void refreshList(); }));
  const list = el("div", "", "coding-question-list panel"); list.id = "codingQuestions";
  const pagination = el("div", "", "pagination"); pagination.id = "codingPagination";
  root.append(toolbar, list, pagination);
}
async function loadQuestions(request, userId) {
  const turn = ++listRevision;
  const target = $("codingQuestions"); if (!target) return;
  target.setAttribute("aria-busy", "true");
  try {
    const params = new URLSearchParams({ mine: String(mode === "mine"), page_size: "100", q: query });
    if (stageId) params.set("stage_id", stageId);
    const items = []; let next = 1; let pages = 1;
    do {
      params.set("view", mode); params.set("mine", String(mode === "mine"));
      params.set("page", String(next)); const result = await api(`/coding/questions?${params}`);
      if (!active(request, userId) || turn !== listRevision || !target.isConnected) return;
      items.push(...result.items); pages = result.pages; next++;
    } while (next <= pages);
    const topics = [...new Set(items.map(item => item.topic).filter(Boolean))].sort();
    const picker = $("codingTopic"); picker.replaceChildren(...[["", "全部知识点"], ...topics.map(value => [value,value])].map(([key, title]) => Object.assign(el("option", title), { value: key })));
    if (!topics.includes(topic)) topic = ""; picker.value = topic;
    const filtered = filterCodingQuestions(items, { topic, stars, order });
    const render = () => {
      const start = (page - 1) * 15; target.replaceChildren();
      const titles = { mine: "我的题库", solved: "已完成题目", failed: "尝试未通过", favorites: "收藏题目" };
      const heading = el("div", "", "coding-list-heading"); heading.append(el("strong", mode === "roadmap" ? home.stages.find(stage => String(stage.id) === stageId)?.title || "全部练习" : titles[mode]), el("span", `${filtered.length} 道题`, "muted")); target.append(heading);
      const emptyCopy = mode === "favorites" ? ["还没有收藏题目", "在题单或写题页点击收藏，方便之后继续练习。"]
        : mode === "solved" ? ["还没有已完成题目", "通过评测的题目会集中显示在这里。"]
        : mode === "failed" ? ["没有待复盘的题目", "完成评测但尚未通过的题目会显示在这里。"]
        : ["这里还没有题目", "试试其他阶段或筛选条件，也可以添加自己的题目。"];
      if (!filtered.length) target.append(emptyState(...emptyCopy));
      for (const item of filtered.slice(start, start + 15)) target.append(questionRow(item));
      renderPagination($("codingPagination"), page, filtered.length, 15, value => { page = value; render(); });
    };
    page = Math.min(page, Math.max(1, Math.ceil(filtered.length / 15))); render();
  } catch (error) {
    if (active(request, userId) && turn === listRevision && target.isConnected) target.replaceChildren(emptyState("题单加载失败", error.message), button("重试", refreshList));
  } finally { if (turn === listRevision) target.removeAttribute("aria-busy"); }
}
function questionRow(question) {
  const row = el("div", "", "coding-question-row");
  const mark = el("span", question.solved ? "✓" : String(question.position + 1).padStart(2, "0"), `coding-solve-mark ${question.solved ? "solved" : ""}`);
  const main = el("div", "", "coding-question-main");
  main.append(home.can_coding ? button(question.title, () => openQuestion(question.id), "coding-question-title") : el("strong", question.title));
  const tags = el("div", "", "coding-question-tags"); tags.append(el("span", question.topic), el("span", `难度 ${question.difficulty}/5`), el("span", question.judge_mode === "luogu" ? "洛谷评测" : "公开样例练习"));
  if (mode === "mine") tags.append(badge(reviewLabels[question.review_status] || question.review_status, question.review_status === "approved" ? "green" : "gray"));
  main.append(tags);
  if (question.review_reason && mode === "mine") main.append(el("p", `审核意见：${question.review_reason}`, "coding-review-reason"));
  const importance = el("span", "★".repeat(question.stars), "coding-stars"); importance.setAttribute("aria-label", `重要性 ${question.stars} 星`);
  const actions = el("div", "", "coding-actions");
  if (home.can_coding) {
    const favorite = button(question.favorited ? "★" : "☆", async () => {
      await api(`/coding/questions/${question.id}/favorite`, { method: question.favorited ? "DELETE" : "PUT" });
      if (active(revision, state.user.id)) await refreshList();
    }, `coding-favorite${question.favorited ? " is-favorite" : ""}`);
    favorite.title = question.favorited ? "取消收藏" : "收藏题目";
    favorite.setAttribute("aria-label", favorite.title);
    favorite.setAttribute("aria-pressed", String(Boolean(question.favorited)));
    actions.append(favorite);
  }
  if (mode === "mine") {
    actions.append(button("编辑", () => editQuestion(question), "text-button"));
    if (question.review_status !== "pending" && question.review_status !== "approved") actions.append(button("送审", async () => {
      const owner = state.user.id; const current = revision;
      await api(`/coding/questions/${question.id}/submit`, { method: "POST", body: JSON.stringify({ version: question.version }) });
      if (active(current, owner)) { notify("题目已送审。"); await refreshList(); }
    }, "text-button"));
    actions.append(button("删除", async () => {
      if (!await confirmAction(`删除「${question.title}」？删除后将不再参与抽题，已有提交记录会保留。`, { danger: true })) return;
      const owner = state.user.id; const current = revision;
      await api(`/coding/questions/${question.id}`, { method: "DELETE" }); if (active(current, owner)) await refreshList();
    }, "text-button"));
  } else actions.append(button("开始练习 →", () => openQuestion(question.id), "text-button"));
  row.append(mark, main, importance, actions); return row;
}
async function editQuestion(question) {
  const owner = state.user.id; const current = revision;
  const complete = question ? await api(`/coding/questions/${question.id}`) : {};
  if (!active(current, owner)) return;
  editCodingQuestion({ question: complete, stages: home.stages, save: async data => {
    await api(question ? `/coding/questions/${question.id}` : "/coding/questions", { method: question ? "PATCH" : "POST", body: JSON.stringify(data) });
    if (active(current, owner)) { notify("题目已保存。"); await refreshList(); }
  } });
}
function paneControl() { const control = el("button", "⛶", "workspace-icon-button pane-expand"); control.type = "button"; return control; }
function closePaneControl(label) { const control = el("button", "×", "workspace-icon-button workspace-pane-close"); control.type = "button"; control.setAttribute("aria-label", `收起${label}`); control.title = `收起${label}`; return control; }
function splitter(className, label, orientation) {
  const node = el("div", "", className); node.setAttribute("role", "separator"); node.setAttribute("aria-label", label); node.setAttribute("aria-orientation", orientation); node.tabIndex = 0; return node;
}
function renderWorkspace(question, request, userId) {
  const root = $("codingContent"); const workspace = el("div", "", "coding-workspace problem-workspace");
  const navigation = el("div", "", "coding-workspace-toolbar");
  navigation.append(button("← 返回题单", goHome, "button secondary workspace-back"), el("strong", question.title, "coding-workspace-title"));
  const favorite = button(question.favorited ? "★ 已收藏" : "☆ 收藏", async () => {
    const favorited = !question.favorited;
    await api(`/coding/questions/${question.id}/favorite`, { method: favorited ? "PUT" : "DELETE" });
    if (!active(request, userId)) return;
    question.favorited = favorited;
    favorite.textContent = favorited ? "★ 已收藏" : "☆ 收藏";
    favorite.setAttribute("aria-pressed", String(favorited));
    favorite.setAttribute("aria-label", favorited ? "取消收藏题目" : "收藏题目");
  }, `button secondary coding-workspace-favorite${question.favorited ? " is-favorite" : ""}`);
  favorite.setAttribute("aria-pressed", String(Boolean(question.favorited)));
  favorite.setAttribute("aria-label", question.favorited ? "取消收藏题目" : "收藏题目");
  navigation.append(favorite);
  const columns = el("div", "", "problem-columns candidate-workspace"); columns.dataset.activePane = "statement";
  const restoreBar = el("div", "", "workspace-pane-restores"); const restoreControls = {}; const closeControls = {};
  for (const [pane, label] of [["statement", "题面"], ["editor", "代码区"], ["panels", "样例与提交记录"]]) {
    const restore = button(`展开${label}`, () => {}, "workspace-pane-restore"); restore.hidden = true; restoreControls[pane] = restore; restoreBar.append(restore);
  }
  const expandAll = button("展开全部", () => {}, "workspace-expand-all"); expandAll.hidden = true; restoreBar.append(expandAll);
  const statement = el("article", "", "panel problem-statement"); const statementHead = el("div", "", "workspace-panel-heading statement-panel-heading"); const statementControl = paneControl();
  const closeStatement = closePaneControl("题面"); closeControls.statement = closeStatement;
  const statementActions = el("div", "", "workspace-pane-actions"); statementActions.append(statementControl, closeStatement);
  statementHead.append(el("span", "题目描述", "workspace-panel-label"), statementActions);
  const content = el("div", "", "workspace-statement-content");
  content.append(el("p", [question.topic, `难度 ${question.difficulty}/5`, "★".repeat(question.stars)].filter(Boolean).join(" · "), "coding-statement-meta"));
  if (question.statement_html) appendProblemStatement(content, question.statement_html); else content.append(el("pre", question.statement, "coding-statement-text"));
  if (/^https?:\/\//i.test(question.source_url || "")) { const link = el("a", "查看原题与来源 ↗", "text-button"); link.href = question.source_url; link.target = "_blank"; link.rel = "noopener noreferrer"; content.append(link); }
  const sourceInfo = question.source_info;
  if (typeof sourceInfo === "string") content.append(el("p", sourceInfo, "coding-source-info"));
  else if (sourceInfo) {
    for (const source of sourceInfo.occurrences || []) content.append(el("p", `${source.file} · 第 ${source.page} 页${source.section ? ` · ${source.section}` : ""}`, "coding-source-info"));
    if (sourceInfo.pdf_reference_code) {
      const pdf = el("details", "", "coding-reference"); pdf.append(el("summary", "查看 PDF 原始代码摘录"));
      pdf.addEventListener("toggle", () => {
        if (!pdf.open || pdf.querySelector("pre")) return;
        pdf.append(el("p", "PDF 原文摘录，可能缺少上下文或完整输入输出，未经执行验证。", "muted"), el("pre", sourceInfo.pdf_reference_code));
      }); content.append(pdf);
    }
  }
  if (question.content_notice) content.append(el("p", question.content_notice, "sample-unavailable"));
  if (question.reference_code) {
    const reference = el("details", "", "coding-reference"); reference.append(el("summary", "查看参考代码（建议独立完成后再看）"));
    reference.addEventListener("toggle", () => {
      if (!reference.open || reference.querySelector("pre")) return;
      reference.append(el("p", sourceInfo?.reference_note || "来源参考代码可能是算法片段；提交评测前请补齐输入输出和完整程序。", "muted"), el("pre", question.reference_code));
    }); content.append(reference);
  }
  statement.append(statementHead, content);
  const stack = el("div", "", "editor-stack");
  const editor = el("section", "", "panel editor-panel"); const editorHead = el("div", "", "editor-heading");
  const language = select("编程语言", languages, "cpp11", () => {}); language.className = "language-select"; const editorControl = paneControl();
  const closeEditor = closePaneControl("代码区"); closeControls.editor = closeEditor;
  const reset = button("恢复布局", () => {}, "workspace-layout-reset"); reset.title = "恢复默认分栏比例";
  const judgeBadge = badge(question.judge_mode === "luogu" ? "洛谷评测" : "公开样例", "blue");
  judgeBadge.title = question.judge_mode === "luogu" ? "不限时练习 · 通过浏览器插件提交至洛谷" : "不限时练习 · 只校验公开样例，通过不代表通过完整隐藏测试";
  editorHead.append(el("h4", "代码工作区"));
  if (question.judge_mode === "samples" && !home.judge.available) {
    const judgeWarning = el("span", "本站公开样例评测暂不可用，请稍后再试或联系管理员。", "coding-form-error");
    judgeWarning.title = judgeWarning.textContent;
    editorHead.append(judgeWarning);
  }
  const editorActions = el("div", "", "workspace-pane-actions"); editorActions.append(editorControl, closeEditor);
  const headingTools = el("div", "", "editor-heading-tools"); headingTools.append(language, reset, editorActions);
  editorHead.append(headingTools);
  const area = el("div", "", "code-area"); const numbers = el("pre", "", "line-numbers"); numbers.setAttribute("aria-hidden", "true");
  const input = el("textarea", "", "code-editor mono"); input.spellcheck = false; input.autocapitalize = "off"; input.wrap = "off"; input.maxLength = 30000; input.setAttribute("aria-label", "练习代码"); input.placeholder = "// 从标准输入读取，向标准输出输出\n// 按自己的节奏完成这道题";
  const saved = el("span", "草稿自动保存在此浏览器", "muted"); let previous = language.value;
  input.value = drafts.read(codingDraftKey(userId, question.id, previous));
  function update() { numbers.textContent = input.value.split("\n").map((_, index) => index + 1).join("\n"); }
  function save(lang) { saved.textContent = drafts.write(codingDraftKey(userId, question.id, lang), input.value) ? "草稿已保存至此浏览器" : "草稿暂存在当前页面，请自行保存代码"; }
  input.addEventListener("input", () => { save(language.value); update(); });
  input.addEventListener("scroll", () => { numbers.scrollTop = input.scrollTop; });
  input.addEventListener("keydown", event => {
    if (saveDraftOnShortcut(event, () => save(language.value))) return;
    if (event.key === "Tab" && !event.shiftKey) { event.preventDefault(); input.setRangeText("    ", input.selectionStart, input.selectionEnd, "end"); input.dispatchEvent(new Event("input")); }
  });
  language.addEventListener("change", () => { save(previous); previous = language.value; input.value = drafts.read(codingDraftKey(userId, question.id, previous)); update(); }); update(); area.append(numbers, input);
  const footer = el("div", "", "editor-footer"); const result = el("div", "", "submission-result"); result.setAttribute("role", "status"); result.setAttribute("aria-live", "polite");
  let activateRecords = () => {};
  const submit = button(question.judge_mode === "luogu" ? "提交洛谷评测 →" : "运行公开样例 →", async () => {
    activateRecords();
    if (!input.value.trim()) { result.replaceChildren(el("span", "请先输入代码，再提交评测。", "coding-form-error")); return; }
    const source = input.value; const lang = language.value; result.replaceChildren(el("span", "正在评测…", "muted"));
    let remotePayload = null; let submissionId = null;
    try {
      let response = await api(`/coding/questions/${question.id}/submissions`, { method: "POST", body: JSON.stringify({ language: lang, source }) });
      if (state.user?.id !== userId) return;
      submissionId = response.id;
      if (response.judge_mode === "luogu") {
        pending.set(response.id, { userId, questionId: question.id, remoteProblemId: response.remote_problem_id });
        resultTargets.set(response.id, { userId, result });
        try {
          remotePayload = await requestLuoguSubmit({ context: "coding", submission_id: response.id, problem_id: response.remote_problem_id, source, language: lang });
        } catch (error) {
          if (state.user?.id !== userId) return;
          const current = await api(`/coding/submissions/${response.id}`);
          if (!current.remote_submission_id) {
            try { await saveRemote(response.id, { remote_submission_id: "", status: "Submission Failed", detail: error.message }); }
            catch { /* A concurrent extension result may have bound the record; preserve that server result. */ }
          }
          throw error;
        }
        if (state.user?.id !== userId) return;
        if (!remotePayload?.remote_submission_id || !remotePayload.status) throw new Error("洛谷未返回提交编号，请先检查洛谷提交记录。");
        remotePayload.remote_problem_id = response.remote_problem_id;
        response = await saveRemote(response.id, remotePayload);
      }
      if (!active(request, userId)) return;
      renderResult(result, response); await loadRecords(question.id, request, userId);
    } catch (error) {
      if (active(request, userId)) {
        result.replaceChildren(el("span", error.message, "coding-form-error"));
        if (remotePayload?.remote_submission_id && submissionId) result.append(button("重新同步评测结果", async () => {
          try {
            const synced = await saveRemote(submissionId, remotePayload);
            if (!active(request, userId)) return;
            renderResult(result, synced); await loadRecords(question.id, request, userId);
          } catch (syncError) { result.replaceChildren(el("span", syncError.message, "coding-form-error")); }
        }, "text-button"));
        await loadRecords(question.id, request, userId);
      }
    }
  }, "button primary");
  if (question.judge_mode === "samples" && !home.judge.available) submit.disabled = true;
  const submitTools = el("div", "", "coding-submit-tools"); submitTools.append(judgeBadge);
  if (question.judge_mode === "luogu") submitTools.append(button("插件教程", () => $("luoguTutorial")?.showModal(), "text-button coding-tutorial-button"));
  footer.append(submitTools, saved, submit); editor.append(editorHead, area, footer);
  const panels = el("section", "", "editor-bottom-panel"); const tabs = el("div", "", "workspace-panel-heading auxiliary-panel-heading"); const tabsInner = el("div", "", "editor-bottom-tabs"); const panelControl = paneControl();
  const samples = el("div", "", "editor-bottom-content");
  for (const [index, sample] of (question.samples || []).entries()) {
    const block = el("div", "", "sample-block"); block.append(el("h4", `公开样例 ${index + 1}`, "sample-heading")); const pair = el("div", "", "sample-pair");
    for (const [name, value] of [["输入", sample.input], ["期望输出", sample.output]]) { const part = el("div", "", "sample-value"); part.append(el("div", name, "sample-value-heading"), el("pre", value)); pair.append(part); } block.append(pair); samples.append(block);
  }
  if (!question.samples?.length) samples.append(el("p", "此题未提供公开样例。", "muted"));
  const records = el("div", "", "editor-bottom-content coding-submission-panel"); records.hidden = true; records.append(result);
  const recordList = el("div", "", "coding-record-list"); records.append(recordList); recordTarget = recordList;
  const tabButtons = [];
  for (const [label, pane] of [["公开样例", samples], ["提交记录", records]]) {
    const control = button(label, () => { samples.hidden = pane !== samples; records.hidden = pane !== records; tabButtons.forEach(([button, target]) => { button.classList.toggle("selected", pane === target); button.setAttribute("aria-pressed", String(pane === target)); }); }, `editor-bottom-tab${pane === samples ? " selected" : ""}`);
    control.setAttribute("aria-pressed", String(pane === samples)); tabButtons.push([control,pane]); tabsInner.append(control);
  }
  const layoutStore = createLayoutStore((() => { try { return window.localStorage; } catch { return undefined; } })(), `scu:${userId}:coding-layout:v1`);
  activateRecords = () => {
    samples.hidden = true; records.hidden = false;
    tabButtons.forEach(([tab, target]) => { tab.classList.toggle("selected", target === records); tab.setAttribute("aria-pressed", String(target === records)); });
    if (layoutStore.read().collapsed.panels) restoreControls.panels.click();
  };
  const closePanels = closePaneControl("样例与提交记录"); closeControls.panels = closePanels;
  const panelActions = el("div", "", "workspace-pane-actions"); panelActions.append(panelControl, closePanels);
  tabs.append(tabsInner, panelActions); panels.append(tabs, samples, records);
  const horizontal = splitter("problem-splitter", "调整题面和代码区宽度", "vertical"); const vertical = splitter("editor-splitter", "调整代码与样例区高度", "horizontal");
  stack.append(editor, vertical, panels); columns.append(statement, horizontal, stack);
  const mobile = el("div", "", "workspace-pane-switcher");
  for (const [name, label] of [["statement","题目描述"],["editor","代码与评测"]]) {
    const tab = button(label, () => { columns.dataset.activePane = name; columns.dispatchEvent(new Event("workspacepanechange")); for (const node of mobile.children) { const selected = node.dataset.pane === name; node.setAttribute("aria-pressed", String(selected)); node.classList.toggle("selected", selected); } }, "workspace-pane-tab");
    tab.dataset.pane = name; mobile.append(tab);
  }
  mobile.children[0].setAttribute("aria-pressed", "true"); mobile.children[0].classList.add("selected"); mobile.children[1].setAttribute("aria-pressed", "false");
  workspace.append(navigation, mobile, restoreBar, columns); root.replaceChildren(workspace);
  disposeLayout = mountWorkspaceLayout({ columns, stack, horizontal, vertical, controls: { statement: statementControl, editor: editorControl, panels: panelControl }, closeControls, regions: { statement, editor, panels }, restoreControls, expandAll, reset, paneSwitcher: mobile, store: layoutStore });
  void loadRecords(question.id, request, userId);
}
function renderResult(target, result) {
  target.replaceChildren(el("span", `提交 #${result.id}`), statusBadge(result.status));
  if (result.judge_mode === "samples") target.append(el("span", `公开样例 ${result.passed_cases ?? 0}/${result.total_cases ?? 0}，未验证隐藏测试`));
  if (result.detail) target.append(el("pre", result.detail, "submission-result-detail"));
}
async function loadRecords(id, request, userId) {
  const turn = ++recordsRevision; const target = recordTarget;
  if (!target) return;
  try {
    const result = await api(`/coding/questions/${id}/submissions`);
    if (!active(request, userId) || selectedQuestion?.id !== id || turn !== recordsRevision || !target.isConnected) return;
    target.replaceChildren(button("刷新提交记录", () => loadRecords(id, request, userId), "text-button"));
    if (!result.items.length) target.append(el("p", "完成代码后提交，评测记录会出现在这里。", "muted"));
    for (const record of result.items) {
      if (record.judge_mode === "luogu" && !terminal.has(record.status)) pending.set(record.id, { userId, questionId: id, remoteProblemId: record.remote_problem_id });
      const row = el("div", "", "coding-record"); row.append(el("span", `#${record.id} · ${record.language}`), statusBadge(record.status), button("详情", async () => {
        const data = await api(`/coding/submissions/${record.id}`); if (!active(request, userId)) return;
        const { body } = codingDialog(`提交 #${record.id}`); renderResult(body, data); body.append(el("pre", data.source || "", "coding-source-code"));
      }, "text-button")); target.append(row);
    }
  } catch (error) { if (active(request, userId) && turn === recordsRevision && target.isConnected) target.replaceChildren(el("p", error.message, "coding-form-error"), button("重试", () => loadRecords(id, request, userId))); }
}
async function saveRemote(id, payload) {
  const body = {
    remote_submission_id: String(payload.remote_submission_id || ""),
    remote_problem_id: payload.remote_problem_id || payload.problem_id || pending.get(id)?.remoteProblemId || "",
    status: payload.status, detail: payload.detail || "",
  };
  try { return await api(`/coding/submissions/${id}/remote-result`, { method: "POST", body: JSON.stringify(body) }); }
  catch (error) {
    if (error.status !== 409) throw error;
    const current = await api(`/coding/submissions/${id}`);
    // Extension progress and the initial submission response can arrive out of order.
    if (String(current.remote_submission_id) === body.remote_submission_id
      && (terminal.has(current.status) || (current.status === "Judging" && body.status === "Submitted"))) return current;
    throw error;
  }
}
window.addEventListener("scu-luogu-status", event => {
  const data = event.detail; const userId = state.user?.id; const token = state.token;
  if (!userId || !acceptsCodingStatus(data)) return;
  const sameSession = () => state.user?.id === userId && state.token === token;
  void (async () => {
    const owned = await api(`/coding/submissions/${data.submission_id}`);
    if (!sameSession() || owned.user_id !== userId || owned.judge_mode !== "luogu") return;
    pending.set(data.submission_id, { userId, questionId: owned.question_id, remoteProblemId: owned.remote_problem_id });
    const saved = await saveRemote(data.submission_id, data);
    if (!sameSession()) return;
    if (terminal.has(saved.status)) pending.delete(data.submission_id);
    const visible = resultTargets.get(data.submission_id);
    if (visible?.userId === userId && visible.result.isConnected) renderResult(visible.result, saved);
    if (selectedQuestion?.id === owned.question_id) await loadRecords(owned.question_id, revision, userId);
    else if (!$("coding")?.hidden && !selectedQuestion) await refreshCoding();
  })().catch(error => { if (sameSession() && error.status !== 404) notify(`带刷评测状态同步失败：${error.message}`, "error"); });
});
