import { testCaseFormat } from "./test-case-formats.mjs?v=20261121-local-cases-v1";
import { el, button } from "./ui.js?v=20261114-ui-v17";
import { api } from "./api.js?v=20261114-ui-v17";
import { judgePlatform } from "./judge-platforms.mjs?v=20261121-china-judge-v2";

import {questionMarkdownEditor} from "./question-markdown-editor.js?v=20261121-v1";

/** A labelled native form control shared by both practice editors. */
export function codingField(label, name, value = "", { type = "text", options, required = false, min, max, rows } = {}) {
  const wrap = el("label", "", "coding-field");
  wrap.append(el("span", label));
  const input = el(options ? "select" : type === "textarea" ? "textarea" : "input");
  if (!options && type !== "textarea") input.type = type;
  input.name = name;
  if (options) for (const [id, title] of options) input.append(Object.assign(el("option", title), { value: id }));
  input.value = value ?? "";
  input.required = required;
  if (min !== undefined) input.min = min;
  if (max !== undefined) input.max = max;
  if (rows) input.rows = rows;
  wrap.append(input);
  return { wrap, input };
}

/** Open an accessible modal while keeping the question list and its filters intact. */
export function codingDialog(title, owner = "coding") {
  const previousFocus = document.activeElement;
  const dialog = el("dialog", "", "account-dialog coding-dialog");
  dialog.dataset.codingOwner = owner;
  dialog.setAttribute("aria-label", title);
  const form = el("form");
  const header = el("div", "", "dialog-header");
  header.append(el("h2", title), button("关闭", () => dialog.close(), "button secondary"));
  const body = el("div", "", "dialog-body coding-form-body");
  const footer = el("div", "", "dialog-footer");
  form.append(header, body, footer); dialog.append(form); document.body.append(dialog);
  dialog.addEventListener("close", () => { dialog.remove(); if (previousFocus?.isConnected) previousFocus.focus(); }, { once: true });
  dialog.showModal();
  return { dialog, form, body, footer };
}

/** Create or update one question with server version checks and editable public samples. */
export function editCodingQuestion({ question = {}, stages, admin = false, save, importProblem }) {
  const { dialog, form, body, footer } = codingDialog(question.id ? "编辑题目" : admin ? "新增公开题目" : "添加我的题目", admin ? "codingAdmin" : "coding");
  body.append(el("p", admin ? "保存后题目进入公开题库。阶段内顺序越小越靠前，设置为 0 会插入当前阶段最前。星级表示复习重要性。" : "新题目只对自己可见，也会进入自己的每日抽题池。阶段内顺序设置为 0 会排在当前阶段最前，需要公开时可单独送审。", "muted"));
  const grid = el("div", "", "coding-form-grid");
  const fields = {};
  const add = (label, name, value, options = {}) => {
    const field = codingField(label, name, value, options); fields[name] = field.input; grid.append(field.wrap); return field;
  };
  const title = codingField("题目名称", "title", question.title, { required: true });
  fields.title = title.input;
  const titleSearch = el("div", "", "coding-field coding-span-all coding-title-search");
  const titleAnchor = el("div", "", "coding-title-anchor");
  titleAnchor.append(title.wrap); titleSearch.append(titleAnchor); grid.append(titleSearch);
  add("所属阶段", "stage_id", question.stage_id ?? stages[0]?.id ?? "", { options: stages.map(stage => [stage.id, stage.title]), required: true });
  add("知识点", "topic", question.topic || "基础算法", { required: true });
  add("难度", "difficulty", question.difficulty ?? 1, { options: [[1,"1 · 入门"],[2,"2 · 基础"],[3,"3 · 进阶"],[4,"4 · 提高"],[5,"5 · 挑战"]] });
  add("重要性", "stars", question.stars ?? 3, { options: [1,2,3,4,5].map(n => [n, "★".repeat(n)]) });
  add("阶段内顺序（0 最前）", "position", question.position ?? 0, { type: "number", min: 0, required: true });
  const initialMode = question.judge_mode === "luogu" ? question.remote_platform || "luogu" : "samples";
  add("评测方式", "judge_mode", initialMode, { options: [["samples","仅运行公开样例"],["luogu","洛谷评测"],["leetcode","LeetCode 评测（中国区）"]] });
  let remoteProblemId = question.remote_problem_id || "";
  let importing = false;
  let markdownBusy = false;
  const markdownEditorsBusy = new Set();
  const setMarkdownBusy = (name, value) => {
    if (value) markdownEditorsBusy.add(name); else markdownEditorsBusy.delete(name);
    markdownBusy = markdownEditorsBusy.size > 0;
    submit.disabled = markdownBusy || importing;
  };
  add("来源链接", "source_url", question.source_url || "", { type: "url" });
  const statement=codingField("题目描述（Markdown）","statement",question.statement||"",{type:"textarea",rows:9});
  fields.statement=statement.input;fields.statement.maxLength=200000;fields.statement.id=`coding-statement-${crypto.randomUUID()}`;
  const statementWrap=el('div','','coding-field coding-span-all');const statementLabel=el('label','题目描述（Markdown）');statementLabel.htmlFor=fields.statement.id;
  const markdownEditor=questionMarkdownEditor(fields.statement,{onBusy:value=>setMarkdownBusy("statement", value)});
  statementWrap.append(statementLabel,markdownEditor.node);grid.append(statementWrap);
  dialog.addEventListener('close',()=>markdownEditor.dispose(),{once:true});
  add("参考代码语言", "reference_language", question.reference_language || "cpp11", { options: [["cpp11","C++11"],["c","C"],["python3","Python 3"]] });
  add("题目状态", "active", question.active === false ? "false" : "true", { options: [["true","启用"],["false","停用"]] });
  const reference = codingField("书中原代码（Markdown）", "reference_code", question.reference_code || "", { type: "textarea", rows: 9 });
  fields.reference_code = reference.input;
  fields.reference_code.maxLength = 200000;
  fields.reference_code.id = `coding-reference-code-${crypto.randomUUID()}`;
  const referenceWrap = el("div", "", "coding-field coding-span-all");
  const referenceLabel = el("label", "书中原代码（Markdown）");
  referenceLabel.htmlFor = fields.reference_code.id;
  const referenceMarkdownEditor = questionMarkdownEditor(fields.reference_code, {
    onBusy: value => setMarkdownBusy("reference", value),
  });
  referenceWrap.append(referenceLabel, referenceMarkdownEditor.node);
  grid.append(referenceWrap);
  dialog.addEventListener('close',()=>referenceMarkdownEditor.dispose(),{once:true});
  if (!admin && question.visibility === "public") body.append(el("p", "修改已公开题目会将其改回私人草稿，需要重新送审。", "coding-review-reason"));
  body.append(grid);
  let sourceInfo = question.source_info || {};
  let starterCodes = question.starter_codes || {};
  if (importProblem) {
    const results = el("div", "", "luogu-suggestions");
    results.id = `coding-platform-results-${crypto.randomUUID()}`;
    results.hidden = true;
    const status = el("small", "", "muted coding-title-status");
    status.setAttribute("role", "status");
    titleAnchor.append(results); titleSearch.append(status);
    title.input.autocomplete = "off";
    title.input.setAttribute("aria-controls", results.id);
    title.input.setAttribute("aria-expanded", "false");
    let searchRevision = 0;
    let timer;
    const clearResults = () => {
      searchRevision++;
      clearTimeout(timer);
      results.hidden = true;
      results.replaceChildren();
      title.input.setAttribute("aria-expanded", "false");
    };
    const invalidateSelection = () => {
      remoteProblemId = "";
      starterCodes = {};
      sourceInfo = {};
      importing = false;
      submit.disabled = markdownBusy;
    };
    const importSelected = async id => {
      clearResults();
      const selected = fields.judge_mode.value;
      const revision = searchRevision;
      importing = true; submit.disabled = true;
      status.textContent = "正在载入题面和样例…";
      try {
        const result = await importProblem(selected, id);
        if (!dialog.open || revision !== searchRevision) return;
        for (const key of ["title", "statement", "source_url"]) if (result[key] != null) fields[key].value = result[key];
        remoteProblemId = result.remote_problem_id;
        markdownEditor.refresh();
        starterCodes = result.starter_codes || {};
        sourceInfo = result.source_info || {};
        if (result.difficulty != null) fields.difficulty.value = result.difficulty;
        samples.replaceChildren(); (result.samples || []).forEach(addSample); syncSampleFormat();
        status.textContent = `已关联 ${judgePlatform(selected).label} · ${remoteProblemId}`;
        error.textContent = "";
      } catch (failure) {
        if (dialog.open && revision === searchRevision) status.textContent = `题面载入失败：${failure.message}。请重新输入并选择题目。`;
      } finally {
        if (revision === searchRevision) { importing = false; submit.disabled = markdownBusy; }
      }
    };
    const search = async () => {
      const query = title.input.value.trim();
      const selected = fields.judge_mode.value;
      if (!query || selected === "samples") return;
      const revision = searchRevision;
      status.textContent = "正在搜索…";
      try {
        const suggestions = await api(`/coding/import/${selected}/suggestions?q=${encodeURIComponent(query)}`);
        if (!dialog.open || revision !== searchRevision) return;
        results.replaceChildren();
        for (const item of suggestions) results.append(button(`${item.number || item.problem_id} · ${item.title}`,
          () => importSelected(item.problem_id), "luogu-suggestion-option"));
        if (!suggestions.length) results.append(el("p", "没有匹配的题目，试试名称、编号或原题链接。", "luogu-suggestion-empty"));
        results.hidden = false;
        title.input.setAttribute("aria-expanded", "true");
        status.textContent = suggestions.length ? "请选择匹配题目，自动填充题面和样例。" : "";
      } catch (failure) {
        if (dialog.open && revision === searchRevision) status.textContent = `搜索失败：${failure.message}。请修改关键词重试。`;
      }
    };
    const syncMode = () => {
      const selected = fields.judge_mode.value;
      title.input.placeholder = selected === "samples" ? "请输入题目名称" : judgePlatform(selected).hint;
      status.textContent = selected === "samples" ? "" : remoteProblemId
        ? `已关联 ${judgePlatform(selected).label} · ${remoteProblemId}`
        : `输入${judgePlatform(selected).label}题目名称、编号或链接，选择联想结果。`;
    };
    fields.judge_mode.addEventListener("change", () => {
      clearResults(); invalidateSelection(); fields.source_url.value = ""; syncMode(); syncSampleFormat();
    });
    title.input.addEventListener("input", () => {
      clearResults(); invalidateSelection(); syncMode(); syncSampleFormat();
      if (fields.judge_mode.value !== "samples" && title.input.value.trim()) timer = setTimeout(search, 300);
    });
    titleSearch.addEventListener("keydown", event => {
      const options = [...results.children].filter(node => node.tagName === "BUTTON");
      const index = options.indexOf(document.activeElement);
      if ((event.key === "ArrowDown" || event.key === "ArrowUp") && options.length && !results.hidden) {
        event.preventDefault(); options[(index + (event.key === "ArrowDown" ? 1 : options.length - 1)) % options.length].focus();
      } else if (event.key === "Escape" && !results.hidden) {
        event.preventDefault(); event.stopPropagation(); clearResults(); title.input.focus();
      }
    });
    dialog.addEventListener("pointerdown", event => { if (!importing && !titleSearch.contains(event.target)) clearResults(); });
    dialog.addEventListener("close", clearResults, { once: true });
    syncMode();
  }
  const sampleHint = el("p", "", "muted coding-case-format");
  body.append(el("h3", "公开样例"), sampleHint);
  function syncSampleFormat() {
    const format = testCaseFormat(fields.judge_mode.value, sourceInfo.leetcode_metadata);
    sampleHint.textContent = format.hint;
    for (const row of samples.children) {
      row.querySelector('[name="sample_input"]').placeholder = format.input;
      row.querySelector('[name="sample_output"]').placeholder = format.output;
    }
  }
  const samples = el("div", "", "coding-edit-samples");
  function addSample(sample = {}) {
    const row = el("div", "", "coding-sample-edit");
    const input = codingField("输入", "sample_input", sample.input || "", { type: "textarea", rows: 3 });
    const output = codingField("期望输出", "sample_output", sample.output || "", { type: "textarea", rows: 3 });
    row.append(input.wrap, output.wrap, button("移除样例", () => row.remove(), "text-button")); samples.append(row); syncSampleFormat();
  }
  (question.samples || []).forEach(addSample); syncSampleFormat();
  body.append(samples, button("＋ 添加样例", () => addSample()));
  const error = el("p", "", "coding-form-error"); error.setAttribute("role", "alert");
  const submit = el("button", "保存题目", "button primary"); submit.type = "submit";
  footer.append(error, button("取消", () => dialog.close()), submit);
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (submit.disabled) return;
    if(markdownEditor.busy || importing)return;
    if (fields.judge_mode.value !== "samples" && !remoteProblemId) {
      error.textContent = "请从题目名称的联想列表中选择一道平台题目。"; fields.title.focus(); return;
    }
    if(!fields.statement.value.trim()){error.textContent="请填写题目描述";fields.statement.focus();return;}
    const data = Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.value]));
    for (const key of ["difficulty", "stars", "position"]) data[key] = Number(data[key]);
    data.remote_platform = data.judge_mode === "samples" ? "luogu" : data.judge_mode;
    data.remote_problem_id = data.judge_mode === "samples" ? "" : remoteProblemId;
    data.judge_mode = data.judge_mode === "samples" ? "samples" : "luogu";
    data.active = data.active === "true";
    data.source_info = sourceInfo;
    data.starter_codes = starterCodes;
    data.samples = [...samples.children].map(row => ({ input: row.querySelector('[name="sample_input"]').value, output: row.querySelector('[name="sample_output"]').value }));
    if (question.id) data.version = question.version;
    submit.disabled = true; error.textContent = "";
    try { await save(data); if (dialog.isConnected) dialog.close(); }
    catch (failure) { if (dialog.isConnected) error.textContent = failure.message; }
    finally { submit.disabled = false; }
  });
  return dialog;
}
