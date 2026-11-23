/** Browse current AI trend reports and edit the selected report as an administrator. */
import { api, state } from "./api.js?v=20261122-session-guard-v1";
import { $, el, button, notify } from "./ui.js?v=20261114-ui-v17";

const periods = [
  { id: "week", label: "当周趋势" },
  { id: "month", label: "当月趋势" },
  { id: "year", label: "当年趋势" },
];
let selectedPeriod = "week";
let selectedTrend = null;
let requestRevision = 0;
let generationPeriodSelect = null;

function dateText(timestamp) {
  return timestamp ? new Date(timestamp * 1000).toLocaleString("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
  }) : "";
}

function periodControls() {
  const controls = el("div", "", "trend-periods");
  controls.setAttribute("role", "tablist");
  controls.setAttribute("aria-label", "趋势时间范围");
  for (const item of periods) {
    const tab = button(item.label, async () => {
      selectedPeriod = item.id;
      if (generationPeriodSelect) generationPeriodSelect.value = item.id;
      await loadPeriod();
    }, "trend-period");
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(selectedPeriod === item.id));
    tab.classList.toggle("active", selectedPeriod === item.id);
    controls.append(tab);
  }
  return controls;
}

function sourceList(sources) {
  const list = el("div", "", "trend-source-list");
  for (const source of sources || []) {
    const link = el("a", "", "trend-source");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    const meta = el("span", "", "trend-source-meta");
    meta.append(el("span", source.source, "trend-source-kind"));
    if (source.published_at) meta.append(el("time", source.published_at.slice(0, 10)));
    link.append(meta, el("strong", source.title), el("span", source.summary, "trend-source-summary"));
    list.append(link);
  }
  if (!sources?.length) list.append(el("p", "本期检索来源尚未生成。", "trend-muted"));
  return list;
}

function renderReport(item) {
  const root = $("trendsContent");
  const report = root.querySelector("#trendReport");
  report.replaceChildren();
  if (!item) {
    const empty = el("div", "", "trend-empty");
    empty.append(el("span", "AI FRONTIER", "eyebrow"), el("h2", "本期暂无趋势报告"),
      el("p", "当前周期还没有已生成的内容，生成完成后会显示在这里。"));
    report.append(empty);
    root.querySelector("#trendTitle").textContent = "等待本期内容";
    root.querySelector("#trendUpdated").textContent = "";
    root.querySelector("#trendSources").replaceChildren();
    root.querySelector("#trendSourceCount").textContent = "0";
    return;
  }
  root.querySelector("#trendTitle").textContent = item.title;
  root.querySelector("#trendUpdated").textContent = `检索区间 ${item.period_start} 至 ${item.period_end} · 更新于 ${dateText(item.updated_at)}`;
  root.querySelector("#trendSourceCount").textContent = String(item.sources.length);
  const markdown = el("div", "", "trend-markdown");
  markdown.innerHTML = item.body_html || "";
  markdown.querySelectorAll("a").forEach(link => {
    link.target = "_blank";
    link.rel = "noopener noreferrer";
  });
  report.append(markdown);
  root.querySelector("#trendSources").replaceChildren(sourceList(item.sources));
}

function renderEditor() {
  const editor = $("trendEditor");
  editor.replaceChildren();
  if (!selectedTrend) {
    editor.append(el("p", "当前周期报告生成后可在这里修订展示正文。", "trend-muted"));
    return;
  }
  const field = el("textarea");
  field.value = selectedTrend.body_markdown;
  field.rows = 12;
  field.maxLength = 100000;
  field.setAttribute("aria-label", "编辑热点趋势 Markdown 正文");
  const save = button("保存正文", async () => {
    try {
      selectedTrend = await api(`/admin/trends/${selectedTrend.id}`, {
        method: "PATCH", body: JSON.stringify({ body_markdown: field.value }),
      });
      renderReport(selectedTrend);
      renderEditor();
      notify("趋势正文已保存。");
    } catch (error) {
      notify(error.message, "error");
    }
  }, "button primary");
  editor.append(field, save);
}

function syncPeriodControls(root) {
  for (const tab of root.querySelectorAll(".trend-period")) {
    const active = tab.textContent === periods.find(item => item.id === selectedPeriod).label;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  }
  if (generationPeriodSelect) generationPeriodSelect.value = selectedPeriod;
}

async function loadPeriod() {
  const revision = ++requestRevision;
  const root = $("trendsContent");
  root.querySelector("#trendLoading").hidden = false;
  syncPeriodControls(root);
  try {
    const result = await api(`/trends/current?period=${selectedPeriod}`);
    if (revision !== requestRevision) return;
    selectedTrend = result.item;
    renderReport(selectedTrend);
    if (state.adminMode) renderEditor();
  } catch (error) {
    if (revision === requestRevision) notify(error.message, "error");
  } finally {
    if (revision === requestRevision) root.querySelector("#trendLoading").hidden = true;
  }
}

function buildPage() {
  const root = $("trendsContent");
  root.replaceChildren();
  const heading = el("header", "", "trend-page-heading");
  const copy = el("div", "", "trend-heading-copy");
  copy.append(el("span", "AI FRONTIER BRIEFING", "eyebrow"), el("h1", "热点趋势"),
    el("p", "按周、月、年整理最具影响力的 AI 前沿科技进展。"));
  heading.append(copy);

  const admin = el("section", "", "panel trend-admin-panel"); admin.id = "trendAdminPanel"; admin.hidden = !state.adminMode;
  const adminHeading = el("div", "", "trend-admin-heading");
  const adminCopy = el("div", "", "trend-admin-copy");
  adminCopy.append(el("span", "EDITORIAL DESK", "eyebrow"), el("h2", "趋势内容管理"),
    el("p", "系统每天早上及每次启动时自动刷新周、月、年三个周期；也可立即重整所选周期。", "trend-muted"));
  const form = el("form", "", "trend-generate-form");
  const periodLabel = el("label", "刷新范围"); periodLabel.htmlFor = "trendGeneratePeriod";
  const period = el("select"); period.id = periodLabel.htmlFor;
  generationPeriodSelect = period;
  for (const item of periods) period.append(new Option(item.label, item.id));
  period.value = selectedPeriod;
  period.addEventListener("change", async () => {
    selectedPeriod = period.value;
    await loadPeriod();
  });
  const generate = el("button", "立即刷新"); generate.type = "submit"; generate.className = "button primary";
  form.append(periodLabel, period, generate);
  form.addEventListener("submit", async event => {
    event.preventDefault();
    generate.disabled = true; generate.textContent = "检索与整理中…";
    try {
      const result = await api("/admin/trends/generate", { method: "POST", body: JSON.stringify({ period: period.value }) });
      selectedPeriod = period.value;
      selectedTrend = result;
      syncPeriodControls(root);
      renderReport(result);
      renderEditor();
      notify("本周期趋势已刷新并覆盖旧内容。");
    } catch (error) {
      notify(error.message, "error");
    } finally {
      generate.disabled = false; generate.textContent = "立即刷新";
    }
  });
  adminHeading.append(adminCopy, form);
  const editor = el("div", "", "trend-editor"); editor.id = "trendEditor";
  admin.append(adminHeading, editor);

  const selector = el("div", "", "trend-filter-row"); selector.append(periodControls());
  const grid = el("div", "", "trend-content-grid");
  const main = el("article", "", "panel trend-report-panel");
  const meta = el("div", "", "trend-report-meta");
  meta.append(el("span", "本期精选", "trend-report-kicker"));
  const title = el("h2", "等待本期内容"); title.id = "trendTitle";
  const updated = el("p", "", "trend-updated"); updated.id = "trendUpdated";
  meta.append(title, updated);
  const report = el("div", "", "trend-report-body"); report.id = "trendReport";
  main.append(meta, report);
  const aside = el("aside", "", "panel trend-evidence-panel");
  const asideHeader = el("div", "", "trend-evidence-heading");
  const asideTitle = el("div", "", "trend-evidence-title");
  asideTitle.append(el("span", "SOURCE INDEX", "eyebrow"), el("h2", "检索来源"));
  const sourceCount = el("strong", "0"); sourceCount.id = "trendSourceCount";
  asideHeader.append(asideTitle, sourceCount);
  const sources = el("div", "", "trend-sources"); sources.id = "trendSources";
  aside.append(asideHeader, sources);
  grid.append(main, aside);
  const loading = el("p", "正在读取趋势…", "trend-loading"); loading.id = "trendLoading"; loading.hidden = true;
  root.append(heading, admin, selector, loading, grid);
}

export async function refreshTrends() {
  buildPage();
  await loadPeriod();
}
