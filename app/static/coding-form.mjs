import { el, button, notify } from "./ui.js?v=20261114-ui-v17";

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
export function editCodingQuestion({ question = {}, stages, admin = false, save, importLuogu }) {
  const { dialog, form, body, footer } = codingDialog(question.id ? "编辑题目" : admin ? "新增公开题目" : "添加我的题目", admin ? "codingAdmin" : "coding");
  body.append(el("p", admin ? "保存后题目进入公开题库。顺序越小越靠前，星级表示复习重要性。" : "新题目只对自己可见，也会进入自己的每日抽题池。需要公开时可单独送审。", "muted"));
  const grid = el("div", "", "coding-form-grid");
  const fields = {};
  const add = (label, name, value, options = {}) => {
    const field = codingField(label, name, value, options); fields[name] = field.input; grid.append(field.wrap); return field;
  };
  add("题目名称", "title", question.title, { required: true }).wrap.classList.add("coding-span-all");
  add("所属阶段", "stage_id", question.stage_id ?? stages[0]?.id ?? "", { options: stages.map(stage => [stage.id, stage.title]), required: true });
  add("知识点", "topic", question.topic || "基础算法", { required: true });
  add("难度", "difficulty", question.difficulty ?? 1, { options: [[1,"1 · 入门"],[2,"2 · 基础"],[3,"3 · 进阶"],[4,"4 · 提高"],[5,"5 · 挑战"]] });
  add("重要性", "stars", question.stars ?? 3, { options: [1,2,3,4,5].map(n => [n, "★".repeat(n)]) });
  add("列表顺序", "position", question.position ?? 0, { type: "number", min: 0, required: true });
  add("评测方式", "judge_mode", question.judge_mode || "samples", { options: [["samples","仅运行公开样例"],["luogu","洛谷评测"]] });
  add("洛谷题号", "remote_problem_id", question.remote_problem_id || "");
  add("来源链接", "source_url", question.source_url || "", { type: "url" });
  add("题目描述（Markdown）", "statement", question.statement || "", { type: "textarea", rows: 9, required: true }).wrap.classList.add("coding-span-all");
  add("参考代码语言", "reference_language", question.reference_language || "cpp11", { options: [["cpp11","C++11"],["c","C"],["python3","Python 3"]] });
  add("题目状态", "active", question.active === false ? "false" : "true", { options: [["true","启用"],["false","停用"]] });
  add("参考代码（可选）", "reference_code", question.reference_code || "", { type: "textarea", rows: 7 }).wrap.classList.add("coding-span-all");
  if (!admin && question.visibility === "public") body.append(el("p", "修改已公开题目会将其改回私人草稿，需要重新送审。", "coding-review-reason"));
  body.append(grid);
  if (importLuogu) {
    const importButton = button("从洛谷填充题面和样例", async () => {
      const id = fields.remote_problem_id.value.trim();
      if (!id) throw new Error("请先填写洛谷题号，例如 P1001。");
      const result = await importLuogu(id);
      if (!dialog.isConnected) return;
      for (const key of ["title", "statement", "source_url", "remote_problem_id", "judge_mode"]) if (result[key] != null) fields[key].value = result[key];
      samples.replaceChildren(); (result.samples || []).forEach(addSample);
      notify("已填充洛谷题面，请检查后保存。");
    });
    body.insertBefore(importButton, grid);
  }
  body.append(el("h3", "公开样例"), el("p", "本站样例评测只检查以下输入输出，不代表通过隐藏测试。", "muted"));
  const samples = el("div", "", "coding-edit-samples");
  function addSample(sample = {}) {
    const row = el("div", "", "coding-sample-edit");
    const input = codingField("输入", "sample_input", sample.input || "", { type: "textarea", rows: 3 });
    const output = codingField("期望输出", "sample_output", sample.output || "", { type: "textarea", rows: 3 });
    row.append(input.wrap, output.wrap, button("移除样例", () => row.remove(), "text-button")); samples.append(row);
  }
  (question.samples || []).forEach(addSample);
  body.append(samples, button("＋ 添加样例", () => addSample()));
  const error = el("p", "", "coding-form-error"); error.setAttribute("role", "alert");
  const submit = el("button", "保存题目", "button primary"); submit.type = "submit";
  footer.append(error, button("取消", () => dialog.close()), submit);
  form.addEventListener("submit", async event => {
    event.preventDefault(); if (submit.disabled) return;
    const data = Object.fromEntries(Object.entries(fields).map(([name, field]) => [name, field.value]));
    for (const key of ["difficulty", "stars", "position"]) data[key] = Number(data[key]);
    data.active = data.active === "true";
    data.samples = [...samples.children].map(row => ({ input: row.querySelector('[name="sample_input"]').value, output: row.querySelector('[name="sample_output"]').value }));
    if (question.id) data.version = question.version;
    submit.disabled = true; error.textContent = "";
    try { await save(data); if (dialog.isConnected) dialog.close(); }
    catch (failure) { if (dialog.isConnected) error.textContent = failure.message; }
    finally { submit.disabled = false; }
  });
  return dialog;
}
