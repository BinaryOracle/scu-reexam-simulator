import { el, statusBadge } from "./ui.js?v=20261114-ui-v17";

/** Present stored verdicts and code without interpreting provider or user text as HTML. */
export function renderSubmissionDetails(target, result) {
  const summary = el("section", "", "submission-overview");
  const verdict = el("div", "", "submission-verdict");
  verdict.append(el("span", "评测结果", "submission-label"), statusBadge(result.status));
  summary.append(verdict);
  const metadata = el("dl", "", "submission-metadata");
  const language = ({ cpp11: "C++11", c: "C", python3: "Python 3" })[result.language] || result.language || "—";
  for (const [label, value] of [["题目", result.question_title], ["语言", language],
    ["提交时间", result.created ? new Date(result.created * 1000).toLocaleString("zh-CN", { hour12: false }) : null],
    ["洛谷提交编号", result.remote_submission_id]]) {
    if (!value) continue;
    const item = el("div"); item.append(el("dt", label), el("dd", String(value))); metadata.append(item);
  }
  summary.append(metadata);
  target.replaceChildren(summary);

  const cases = []; const remaining = []; let counts = null;
  for (const line of (result.detail || "").split("\n")) {
    const count = /^通过(?:测试用例|公开样例)数[：:]\s*(\d+)\s*\/\s*(\d+)\s*$/.exec(line.trim());
    const point = /^测试点\s*#(\d+)[：:]\s*(AC|WA|TLE|MLE|RE|OLE|CE|UE|Judging)\s*$/.exec(line.trim());
    if (count && !counts) counts = [count[1], count[2]];
    else if (point) cases.push({ number: point[1], verdict: point[2] });
    else remaining.push(line);
  }
  if (!counts && Number.isInteger(result.total_cases) && result.total_cases > 0 && Number.isInteger(result.passed_cases)) {
    counts = [result.passed_cases, result.total_cases];
  }
  if (cases.length || counts) {
    const section = el("section", "", "submission-testcases");
    const heading = el("div", "", "submission-section-heading"); heading.append(el("h3", "测试点"));
    if (counts) {
      const count = el("div", "", "submission-pass-summary");
      count.append(el("span", "通过", "submission-label"), el("strong", `${counts[0]} / ${counts[1]}`, "submission-pass-count"));
      heading.append(count);
    }
    section.append(heading);
    const grid = el("div", "", "submission-case-grid");
    for (const item of cases) {
      const card = el("div", "", `submission-case ${item.verdict === "AC" ? "accepted" : item.verdict === "Judging" ? "pending" : "failed"}`);
      card.append(el("span", `#${item.number}`), el("strong", item.verdict)); grid.append(card);
    }
    if (cases.length) section.append(grid);
    target.append(section);
  }
  if (result.judge_mode === "samples") target.append(el("p", "仅验证公开样例，未验证隐藏测试。", "muted"));
  const detail = remaining.join("\n").trim();
  if (detail) {
    const diagnostics = el("section", "", "submission-diagnostics");
    diagnostics.append(el("h3", "评测信息"), el("pre", detail)); target.append(diagnostics);
  }
  const codeSection = el("section", "", "submission-code-section");
  const codeHeading = el("div", "", "submission-section-heading");
  codeHeading.append(el("h3", "提交代码"), el("span", language, "submission-label"));
  const pre = el("pre", "", "submission-code"); pre.append(el("code", result.source || "（未保存代码）"));
  codeSection.append(codeHeading, pre); target.append(codeSection);
}
