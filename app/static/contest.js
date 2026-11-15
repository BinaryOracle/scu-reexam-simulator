import { api, state } from "./api.js?v=20261114-ui-v17";
import {
  $,
  el,
  button,
  badge,
  emptyState,
  dateTime,
  notify,
  confirmAction,
  sectionHeading,
  statusBadge,
  renderPagination,
} from "./ui.js?v=20261114-ui-v18";
import { appendProblemStatement, normalizeProblemStatementHtml, renderProblemMath } from "./problem-content.js?v=20261115-resource-limits-v1";
import { formatLuoguSubmitError, isLuoguExtensionOutdated } from "./luogu-errors.mjs?v=20261115-coding-v1";
import { submitWithLuoguVerification } from "./luogu-submit.mjs?v=20261114-captcha-v2";
import { requestLuoguCaptcha } from "./luogu-captcha.js?v=20261114-captcha-v2";
import { canRevealLuoguSource, normalizeSubmissionPage, refreshContestProblemStats, submissionPanelMessage } from "./contest-model.mjs?v=20261115-contest-submission-states-v1";
import { writeAppRoute } from "./view-route.mjs?v=20261115-navigation-v3";
import { readLuoguConnection, writeLuoguConnection } from "./luogu-connection.mjs?v=20261115-navigation-v3";
import { contestTiming, canOpenContestProblems } from "./contest-timing.mjs?v=20261115-contest-focus-v1";
import { createCodeDrafts, saveDraftOnShortcut } from "./code-drafts.mjs?v=20261115-drafts-v3";
import { createLayoutStore, mountWorkspaceLayout } from "./workspace-layout.mjs?v=20261115-workspace-v3";
import { openContestRecords, closeContestRecords } from "./contest-records.js?v=20261115-contest-records-v1";
import { loadContestRoster, resetContestRoster, contestParticipantIds, setupContestRoster } from "./contest-roster.js?v=20261115-access-v1";

let contests = [];
let selectedContest = null;
let currentProblems = [];
let selectedProblem = null;
let clock;
let workspaceEntryRevision = 0;
let submitting = false;
let luoguConnected = false;
let luoguConnectionUserId = null;
let luoguStatusChecked = false;
let luoguConnectionRequest = null;
let selectedLuoguProblems = [];
let editingContestId = null;
let contestOverview = null;
let contestNavigationRevision = 0;
let problemSearchTimer;
let problemSearchRevision = 0;
let mobilePane = "statement";
let disposeWorkspaceLayout = null;
let workspaceLayoutStore = null;
let workspaceLayoutUser = null;

/** Release active resize gestures and workspace listeners before navigation. */
export function suspendContestWorkspace() {
  closeContestRecords();
  if ($("submissionDetailDialog")?.open) $("submissionDetailDialog").close();
  disposeWorkspaceLayout?.();
  disposeWorkspaceLayout = null;
}
function layoutPreferences() {
  if (workspaceLayoutUser !== state.user.id || !workspaceLayoutStore) {
    let storage;
    try { storage = window.localStorage; }
    catch { /* The layout remains adjustable without browser storage. */ }
    workspaceLayoutStore = createLayoutStore(storage, `scu:${state.user.id}:workspace-layout:v1`);
    workspaceLayoutUser = state.user.id;
  }
  return workspaceLayoutStore;
}
function expandPaneButton() {
  const control = el("button", "", "workspace-icon-button pane-expand");
  control.type = "button";
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const [name, d] of [
    ["expand", "M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"],
    ["restore", "M9 3v6H3m12-6v6h6M3 15h6v6m6 0v-6h6"],
  ]) {
    const path = document.createElementNS(svg.namespaceURI, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", `pane-${name}-icon`);
    svg.append(path);
  }
  control.append(svg);
  return control;
}
let contestQuery = "";
let contestPage = 1;
const contestPageSize = 8;
const bridgeWaiters = new Map();
const timerNodes = new Map();
let submissionHistoryPage = 1;
let submissionUsersPage = 1;
let contestSubmissionPage = 1;
const submissionPageSize = 10;
const userSubmissionRequestIds = new WeakMap();
const managementMode = () => state.adminMode;
const contestPath = (path) => `${managementMode() ? "/admin" : ""}${path}`;
const LANGUAGES = [["cpp11", "C++11"], ["c", "C"], ["python3", "Python 3"], ["java", "Java"], ["go", "Go"]];
const languageName = language => LANGUAGES.find(([value]) => value === language)?.[1] || language;
const codeDrafts = createCodeDrafts(() => window.localStorage);
const draftKey = (id, language) => `scu:${state.user.id}:code:${id}:${language}`;

function copyCodeButton(readCode) {
  return button("复制代码", async () => {
    const code = readCode();
    if (!code) throw new Error("暂无可复制的代码。");
    try {
      await navigator.clipboard.writeText(code);
    } catch (error) {
      throw new Error("复制失败，请允许浏览器访问剪贴板，或手动选中代码复制。");
    }
    notify("代码已复制。");
  }, "text-button code-copy-button");
}

export function clearContestState() {
  contestNavigationRevision++;
  workspaceEntryRevision++;
  suspendContestWorkspace();
  workspaceLayoutStore = null;
  workspaceLayoutUser = null;
  contests = [];
  selectedContest = null;
  currentProblems = [];
  selectedProblem = null;
  contestOverview = null;
  editingContestId = null;
  contestQuery = "";
  contestPage = 1;
  $("contestSearch").value = "";
  timerNodes.clear();
  bridgeWaiters.clear();
  clearInterval(clock);
  document.body.dataset.contestWorkspace = "false";
  document.body.classList.remove("contest-immersive");
  if ($("submissionDetailDialog").open) $("submissionDetailDialog").close();
  $("problemList").replaceChildren();
  $("problemList").hidden = true;
  $("contestList").hidden = false;
  $("contestListHeading").hidden = false;
  $("contestListToolbar").hidden = !contests.length;
  $("contestPagination").hidden = false;
  $("contestList").replaceChildren();
}

function contestStatus(contest) {
  const now = Date.now() / 1000;
  return now < contest.starts
    ? ["未开始", "blue"]
    : now > contest.ends
      ? ["已结束", "gray"]
      : ["进行中", "green"];
}
function deadline(contest) {
  const now = Date.now() / 1000;
  if (now < contest.starts) return `开始于 ${dateTime(contest.starts)}`;
  if (now > contest.ends) return "比赛已结束";
  const seconds = Math.max(0, Math.floor(contest.ends - now));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `剩余 ${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}
function contestCanEnter(contest) {
  return (state.user.is_admin || contest.can_access !== false) && canOpenContestProblems(contest, Date.now() / 1000, managementMode());
}
function contestAvailability(contest) {
  if (!state.user.is_admin && contest.can_access === false) return "未获本场比赛参赛权限，请联系管理员";
  return Date.now() / 1000 < contest.starts ? "比赛开始后开放题目" : "";
}
function contestEntryLabel(contest) {
  return managementMode() ? "查看题目工作区 →" : Date.now() / 1000 > contest.ends ? "查看题目 →" : "开始答题 →";
}
function renderContestTimeline(contest, compact = false) {
  const timeline = el("div", "", `contest-timeline${compact ? " contest-timeline--compact" : ""}`);
  timeline.dataset.contestId = String(contest.id);
  const heading = el("div", "", "contest-timeline-heading");
  const label = el("span", "", "contest-time-label");
  const value = el("strong", "", "contest-time-value");
  const progress = el("div", "", "contest-progress-track");
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-label", "比赛时间进度");
  progress.setAttribute("aria-valuemin", "0");
  progress.setAttribute("aria-valuemax", "100");
  progress.append(el("span", "", "contest-progress-fill"));
  heading.append(label, value);
  timeline.append(heading, progress);
  if (!compact) {
    const endpoints = el("div", "", "contest-timeline-endpoints");
    for (const [name, timestamp] of [["开始", contest.starts], ["结束", contest.ends]]) {
      const endpoint = el("div");
      const time = el("time", dateTime(timestamp));
      time.dateTime = new Date(timestamp * 1000).toISOString();
      endpoint.append(el("span", name), time);
      endpoints.append(endpoint);
    }
    timeline.append(endpoints);
  }
  updateContestTimeline(timeline, contest);
  return timeline;
}
function updateContestTimeline(timeline, contest) {
  const timing = contestTiming(contest);
  timeline.dataset.phase = timing.phase;
  timeline.dataset.urgent = String(timing.urgent);
  const label = timing.phase === "upcoming" ? "距离开赛" : timing.phase === "ended" ? "比赛已结束" : "比赛剩余时间";
  timeline.querySelector(".contest-time-label").textContent = label;
  timeline.querySelector(".contest-time-value").textContent = timing.phase === "ended" ? "已结束" : timing.clock;
  timeline.style.setProperty("--contest-progress", `${timing.percent}%`);
  const progress = timeline.querySelector(".contest-progress-track");
  progress.setAttribute("aria-valuenow", String(Math.floor(timing.percent)));
  progress.setAttribute("aria-valuetext", `${label}${timing.phase === "ended" ? "" : ` ${timing.clock}`}，已用 ${Math.floor(timing.percent)}%`);
}
function tick() {
  for (const [id, nodes] of timerNodes) {
    const contest = contests.find((c) => c.id === id);
    if (!contest) continue;
    if (nodes.time) nodes.time.textContent = deadline(contest);
    const [label, color] = contestStatus(contest);
    nodes.status.textContent = label;
    nodes.status.className = `badge ${color}`;
    if (nodes.enter) {
      nodes.enter.disabled = !contestCanEnter(contest);
      nodes.enter.textContent = contestEntryLabel(contest);
    }
    nodes.problemLinks?.forEach(control => { control.disabled = !contestCanEnter(contest); });
    if (nodes.availability) {
      nodes.availability.textContent = contestAvailability(contest);
      nodes.availability.hidden = contestCanEnter(contest);
    }
  }
  document.querySelectorAll(".contest-timeline").forEach(timeline => {
    const contest = contests.find(item => String(item.id) === timeline.dataset.contestId);
    if (contest) updateContestTimeline(timeline, contest);
  });
  const submit = document.getElementById("submitCode");
  if (submit && selectedContest) {
    const now = Date.now() / 1000;
    submit.disabled =
      submitting || now < selectedContest.starts || now > selectedContest.ends;
  }
  document.querySelectorAll(".workspace-countdown").forEach(node => {
    if (selectedContest) node.textContent = deadline(selectedContest);
  });
  document.querySelectorAll(".workspace-status").forEach(node => {
    if (!selectedContest) return;
    const [label, color] = contestStatus(selectedContest);
    node.textContent = label;
    node.className = `badge ${color} workspace-status`;
  });
}
export async function refreshContests() {
  contests = await api(contestPath("/contests"));
  clearInterval(clock);
  clock = setInterval(tick, 1000);
  await restoreContestRoute();
}
function contestRoute() {
  const [, id, stage, problem] = location.hash.replace(/^#/, "").split("/");
  const contestId = Number(id);
  const problemId = Number(problem);
  return {
    contestId: Number.isInteger(contestId) && contestId > 0 ? contestId : null,
    workspace: stage === "workspace",
    problemId: Number.isInteger(problemId) && problemId > 0 ? problemId : null,
  };
}
async function restoreContestRoute() {
  const route = contestRoute();
  selectedContest = null;
  currentProblems = [];
  selectedProblem = null;
  contestOverview = null;
  if (!route.contestId) {
    renderContestList();
    return;
  }
  const contest = contests.find(item => item.id === route.contestId);
  if (!contest) {
    writeAppRoute("contest", { replace: true });
    renderContestList();
    return;
  }
  await openContest(contest, { recordHistory: false });
  if (route.workspace && selectedContest) await enterContest({ recordHistory: false, problemId: route.problemId });
}
function renderContestList() {
  contestNavigationRevision++;
  workspaceEntryRevision++;
  suspendContestWorkspace();
  document.body.dataset.contestWorkspace = "false";
  document.body.classList.remove("contest-immersive");
  $("problemList").replaceChildren();
  $("problemList").hidden = true;
  const list = $("contestList");
  $("managementTools").hidden = !managementMode();
  $("refreshContests").hidden = false;
  list.hidden = Boolean(selectedContest);
  $("contestListHeading").hidden = Boolean(selectedContest);
  list.replaceChildren();
  timerNodes.clear();
  $("contestCount").textContent = `${contests.length} 场比赛`;
  const query = contestQuery.trim().toLocaleLowerCase();
  const matching = contests.filter((contest) =>
    `${contest.title} ${contest.id} ${String(contest.id).padStart(3, "0")}`.toLocaleLowerCase().includes(query),
  );
  $("contestListToolbar").hidden = Boolean(selectedContest) || !contests.length;
  $("contestResultCount").textContent = query ? `匹配 ${matching.length} 场` : `共 ${matching.length} 场`;
  contestPage = Math.min(contestPage, Math.max(1, Math.ceil(matching.length / contestPageSize)));
  if (!matching.length) {
    list.append(
      emptyState(
        contests.length ? "没有匹配的比赛" : "暂时没有比赛",
        contests.length ? "请尝试其他比赛名称或编号。" : managementMode()
          ? "创建比赛时搜索洛谷题目并自动导入题面。"
          : "管理员发布比赛后，将在这里展示，请留意考试安排。",
        "</>",
      ),
    );
  }
  const start = (contestPage - 1) * contestPageSize;
  for (const contest of matching.slice(start, start + contestPageSize)) {
    const card = el(
      "article",
      "",
      `contest-card${selectedContest?.id === contest.id ? " selected" : ""}`,
    );
    card.dataset.contestId = contest.id;
    const top = el("div", "", "record-top");
    const [label, color] = contestStatus(contest);
    const status = badge(label, color);
    top.append(
      el(
        "span",
        `CONTEST / ${String(contest.id).padStart(3, "0")}`,
        "record-code",
      ),
      status,
    );
    const times = el("div", "", "contest-times");
    for (const [name, value] of [
      ["开始", contest.starts],
      ["结束", contest.ends],
    ]) {
      const row = el("div");
      row.append(el("span", name), document.createTextNode(dateTime(value)));
      times.append(row);
    }
    const bottom = el("div", "", "record-bottom");
    const time = el("span", deadline(contest), "countdown");
    timerNodes.set(contest.id, { time, status });
    bottom.append(
      time,
      button(
        "查看比赛信息 →",
        () => openContest(contest),
        "text-button",
      ),
    );
    if (managementMode()) {
      bottom.append(button("编辑比赛", () => beginEditContest(contest), "text-button"));
      bottom.append(button("删除比赛", () => deleteContest(contest), "danger-text-button"));
    }
    card.append(top, el("h3", contest.title), times, bottom);
    list.append(card);
  }
  renderPagination($("contestPagination"), contestPage, matching.length, contestPageSize, (page) => {
    contestPage = page;
    renderContestList();
    tick();
  });
  $("contestPagination").hidden = Boolean(selectedContest) || $("contestPagination").hidden;
}
$("contestSearch").addEventListener("input", () => {
  contestQuery = $("contestSearch").value;
  contestPage = 1;
  renderContestList();
});
async function deleteContest(contest) {
  const confirmed = await confirmAction(
    `删除“${contest.title}”及其题目和全部提交记录？此操作无法撤销。`,
    { confirmText: "删除比赛", danger: true },
  );
  if (!confirmed) return;
  await api(`/admin/contests/${contest.id}`, { method: "DELETE" });
  if (selectedContest?.id === contest.id) {
    selectedContest = null;
    currentProblems = [];
    selectedProblem = null;
    $("problemList").replaceChildren();
    $("problemList").hidden = true;
    $("contestList").hidden = false;
    $("contestListHeading").hidden = false;
  }
  await refreshContests();
  notify("比赛及其题目、提交记录已删除。");
}
async function openContest(contest, { recordHistory = true } = {}) {
  if (!state.user.is_admin && contest.can_access === false) {
    renderContestList();
    if (!recordHistory) writeAppRoute("contest", { replace: true });
    notify("你不在本场比赛的参赛名单中，请联系管理员", "error"); return;
  }
  const navigationRevision = ++contestNavigationRevision;
  try {
    contestOverview = await api(`/contests/${contest.id}`);
  } catch (error) {
    if (error.status !== 404) {
      if (navigationRevision !== contestNavigationRevision) return;
      throw error;
    }
    let problems = [];
    try {
      problems = await api(`/contests/${contest.id}/problems`);
    } catch (problemError) {
      if (problemError.status !== 403) {
        if (navigationRevision !== contestNavigationRevision) return;
        throw problemError;
      }
    }
    contestOverview = {
      ...contest,
      problem_count: problems.length || null,
      problems: problems.map(({ id, title, remote_problem_id }) => ({ id, title, remote_problem_id })),
    };
  }
  if (navigationRevision !== contestNavigationRevision) return;
  if (recordHistory) writeAppRoute(`contest/${contest.id}`);
  selectedContest = contest;
  $("managementTools").hidden = true;
  $("refreshContests").hidden = true;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  $("contestListToolbar").hidden = true;
  $("contestPagination").hidden = true;
  currentProblems = [];
  selectedProblem = null;
  renderContestOverview();
  $("problemList").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderContestOverview() {
  workspaceEntryRevision++;
  suspendContestWorkspace();
  document.body.dataset.contestWorkspace = "false";
  document.body.classList.remove("contest-immersive");
  $("managementTools").hidden = true;
  $("refreshContests").hidden = true;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  $("contestListToolbar").hidden = true;
  $("contestPagination").hidden = true;
  const container = $("problemList");
  container.hidden = false;
  const panel = el("section", "", "panel contest-overview");
  const head = el("div", "", "contest-overview-head");
  head.append(el("span", `CONTEST / ${String(contestOverview.id).padStart(3, "0")}`, "eyebrow"));
  const [label, color] = contestStatus(contestOverview);
  head.append(badge(label, color));
  panel.append(head, el("h2", contestOverview.title, "contest-overview-title"));
  panel.append(renderContestTimeline(contestOverview));
  const meta = el("div", "", "contest-overview-meta");
  meta.append(el("strong", contestOverview.problem_count == null ? "题目将在开赛后开放" : `${contestOverview.problem_count} 道题目`));
  meta.append(el("span", contestOverview.ranking_rule === "acm" ? "通过题数排名" : "题目分值排名", "contest-rule-label"));
  panel.append(meta);
  const list = el("div", "", "contest-overview-problems");
  list.append(el("h3", "比赛题目"));
  const problemLinks = [];
  contestOverview.problems.forEach((problem, index) => {
    const item = el("div", "", "contest-overview-problem");
    const open = button("", () => enterContest({ problemId: problem.id }), "contest-overview-problem-open");
    open.disabled = !contestCanEnter(contestOverview);
    const problemTitle = `${String.fromCharCode(65 + index)} · ${problem.title}`;
    open.setAttribute("aria-label", `${problemTitle}，打开题目`);
    problemLinks.push(open);
    open.append(el("span", String.fromCharCode(65 + index), "problem-rail-letter"));
    const title = el("div", "", "contest-overview-problem-title");
    title.append(el("strong", problem.title));
    if (problem.remote_problem_id && canRevealLuoguSource(contestOverview, Date.now() / 1000, managementMode()))
      title.append(el("span", problem.remote_problem_id, "muted"));
    open.append(title);
    const stats = el("span", "", "contest-problem-stats");
    const attempts = problem.attempt_count ?? 0;
    const accepted = problem.accepted_count ?? 0;
    const progress = el("span", "", "contest-problem-submission-count");
    progress.setAttribute("aria-label", `尝试 ${attempts} 次，通过 ${accepted} 次`);
    for (const [label, value, activeClass] of [
      ["尝试", attempts, "has-attempts"],
      ["通过", accepted, "has-accepted"],
    ]) {
      const metricClass = `contest-problem-stat${value > 0 ? ` ${activeClass}` : ""}`;
      const metric = managementMode()
        ? button("", () => showContestRecords({ problemId: problem.id, problemTitle, acceptedOnly: label === "通过", participantsOnly: true }), metricClass)
        : el("span", "", metricClass);
      if (managementMode()) {
        metric.setAttribute("aria-label", `查看${problemTitle}的${label}记录，${value} 条`);
        metric.title = `查看${label}记录`;
      }
      metric.append(el("span", label, "contest-problem-stat-label"), el("strong", String(value)));
      progress.append(metric);
    }
    stats.append(el("strong", `${problem.points ?? 100} 分`), progress);
    const arrow = button("→", () => enterContest({ problemId: problem.id }), "contest-problem-arrow");
    arrow.setAttribute("aria-label", `${problemTitle}，打开题目工作区`);
    arrow.disabled = open.disabled;
    problemLinks.push(arrow);
    item.append(open, stats, arrow);
    list.append(item);
  });
  panel.append(list);
  void loadContestRanking(panel, contestOverview.id);
  const actions = el("div", "", "contest-overview-actions");
  actions.append(button("← 返回比赛列表", () => {
    writeAppRoute("contest");
    selectedContest = null;
    contestOverview = null;
    container.replaceChildren();
    container.hidden = true;
    $("contestList").hidden = false;
    $("contestListHeading").hidden = false;
    $("contestListToolbar").hidden = !contests.length;
    $("contestPagination").hidden = false;
    void refreshContests();
  }, "button secondary"));
  if (managementMode()) actions.append(button("编辑比赛信息", () => beginEditContest(selectedContest), "text-button"));
  const canEnter = contestCanEnter(contestOverview);
  const enter = button(contestEntryLabel(contestOverview), enterContest, "button primary");
  enter.disabled = !canEnter;
  actions.append(enter);
  const availability = el("span", contestAvailability(contestOverview), "muted contest-availability");
  availability.hidden = canEnter;
  actions.append(availability);
  timerNodes.set(contestOverview.id, {
    status: head.querySelector(".badge"),
    enter,
    availability,
    problemLinks,
  });
  panel.append(actions);
  container.replaceChildren(panel);
  tick();
}
function showContestRanking() {
  writeAppRoute(`contest/${selectedContest.id}`);
  renderContestOverview();
  requestAnimationFrame(() => document.getElementById(`contest-ranking-${selectedContest?.id}`)
    ?.scrollIntoView({ behavior: "smooth", block: "start" }));
}
function showContestRecords(filters = {}) {
  if (!contestOverview) return;
  openContestRecords({ contestId: contestOverview.id, contestTitle: contestOverview.title, ...filters }, submissionTable);
}
async function loadContestRanking(panel, contestId, existingSection = null) {
  const section = existingSection || el("section", "", "contest-ranking");
  section.id = `contest-ranking-${contestId}`;
  const heading = el("div", "", "contest-ranking-heading");
  const identity = el("div", "", "contest-ranking-identity");
  const emblem = el("span", "", "contest-ranking-emblem");
  emblem.setAttribute("aria-hidden", "true");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", "M7 3h10v5a5 5 0 0 1-10 0V3Zm0 2H3v3a4 4 0 0 0 5 4m9-7h4v3a4 4 0 0 1-5 4M12 13v5m-4 3v-3h8v3M6 21h12");
  svg.append(path); emblem.append(svg);
  const title = el("div");
  title.append(el("span", "CONTEST STANDINGS", "contest-ranking-kicker"), el("h3", "比赛排名"));
  identity.append(emblem, title);
  const refresh = button("刷新排名", () => loadContestRanking(panel, contestId, section), "contest-ranking-refresh");
  const actions = el("div", "", "contest-ranking-actions");
  if (managementMode()) actions.append(button("本场全部提交", () => showContestRecords(), "contest-ranking-refresh"));
  actions.append(refresh);
  heading.append(identity, actions);
  const content = el("div", "", "contest-ranking-content");
  content.append(el("p", "正在读取排名…", "contest-ranking-message"));
  section.replaceChildren(heading, content);
  if (!existingSection) panel.append(section);
  try {
    const result = await api(`/contests/${contestId}/ranking`);
    if (!panel.isConnected || contestOverview?.id !== contestId || !content.isConnected) return;
    content.replaceChildren();
    if (!result.visible) {
      content.append(el("p", "管理员已关闭本场排名展示。", "contest-ranking-message"));
      return;
    }
    const summary = el("div", "", "contest-ranking-summary");
    summary.append(el("span", result.ranking_rule === "acm" ? "按通过题数、提交次数排序" : "按题目分值、通过题数和提交次数排序"));
    summary.append(el("strong", `${result.rows.length} 人上榜`));
    content.append(summary);
    if (!result.rows.length) {
      content.append(el("p", "暂无成绩。完成首次提交，争取榜上领先。", "contest-ranking-message"));
      return;
    }
    const wrap = el("div", "", "table-scroll contest-ranking-table");
    const table = document.createElement("table");
    const caption = el("caption", "本场比赛排名与每题作答情况", "visually-hidden");
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    for (const label of ["排名", "用户", "得分", "通过", ...result.problems.map((problem, index) => String.fromCharCode(65 + index))]) {
      const cell = el("th", label); cell.scope = "col"; headRow.append(cell);
    }
    head.append(headRow); const body = document.createElement("tbody");
    for (const row of result.rows) {
      const tr = document.createElement("tr");
      tr.dataset.rank = String(row.rank);
      tr.classList.toggle("is-current-user", row.user_id === state.user.id);
      const rank = el("td");
      rank.append(el("span", String(row.rank).padStart(2, "0"), "contest-rank-number"));
      const username = el("th", "", "contest-rank-user");
      username.scope = "row";
      const userIdentity = managementMode()
        ? button("", () => showContestRecords({ userId: row.user_id, userName: row.username }), "contest-records-trigger contest-records-user")
        : el("span");
      if (managementMode()) {
        userIdentity.setAttribute("aria-label", `查看 ${row.username} 在本场比赛的全部提交`);
        userIdentity.title = "查看本场全部提交";
      }
      userIdentity.append(el("strong", row.username));
      username.append(userIdentity);
      if (row.user_id === state.user.id) username.append(el("span", "我", "contest-rank-self"));
      tr.append(rank, username, el("td", row.score, "contest-rank-score"), el("td", `${row.accepted_count} / ${result.problems.length}`, "contest-rank-solved"));
      for (const item of row.problems) {
        const cell = el("td");
        const partial = !item.solved && item.score > 0;
        const caseProgress = item.total_cases > 0 ? ` · ${item.passed_cases}/${item.total_cases} 点` : "";
        const verdict = item.solved ? "✓ 通过" : partial ? `部分通过 · ${item.score} / ${result.problems.find(problem => problem.id === item.problem_id)?.points ?? item.score} 分${caseProgress}` : item.attempts ? "未通过" : "—";
        const problemIndex = result.problems.findIndex(problem => problem.id === item.problem_id);
        const problemTitle = `${String.fromCharCode(65 + problemIndex)} · ${result.problems[problemIndex]?.title || "题目"}`;
        const record = managementMode()
          ? button("", () => showContestRecords({ userId: row.user_id, userName: row.username, problemId: item.problem_id, problemTitle }), "contest-records-trigger contest-records-verdict")
          : el("span");
        if (managementMode()) {
          record.setAttribute("aria-label", `查看 ${row.username} 的${problemTitle}提交记录，${item.attempts} 条`);
          record.title = "查看该用户的本题提交";
        }
        record.append(el("span", verdict, `contest-rank-verdict${item.solved ? " is-solved" : partial ? " is-partial" : item.attempts ? " is-attempted" : ""}`));
        if (item.attempts) record.append(el("small", `${item.attempts} 次提交`, "contest-rank-attempts"));
        else cell.setAttribute("aria-label", "尚未尝试");
        cell.append(record);
        tr.append(cell);
      }
      body.append(tr);
    }
    table.append(caption, head, body); wrap.append(table); content.append(wrap);
  } catch (error) {
    if (panel.isConnected && contestOverview?.id === contestId && content.isConnected)
      content.replaceChildren(el("p", `${error.message} 可点击「刷新排名」重试。`, "contest-ranking-message"));
  }
}
async function enterContest({ recordHistory = true, problemId = null } = {}) {
  if (!selectedContest || !contestCanEnter(selectedContest)) throw new Error("比赛开始后才能打开题目。");
  const revision = ++workspaceEntryRevision;
  const contestId = selectedContest.id;
  contestSubmissionPage = 1;
  const problems = await api(contestPath(`/contests/${contestId}/problems`));
  if (revision !== workspaceEntryRevision || selectedContest?.id !== contestId) return;
  currentProblems = problems;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  $("contestListToolbar").hidden = true;
  $("contestPagination").hidden = true;
  selectedProblem = currentProblems.some(problem => problem.id === problemId)
    ? problemId
    : currentProblems[0]?.id ?? null;
  if (recordHistory) writeAppRoute(`contest/${selectedContest.id}/workspace${selectedProblem ? `/${selectedProblem}` : ""}`);
  document.body.dataset.contestWorkspace = "true";
  document.body.classList.toggle("contest-immersive", !managementMode());
  renderWorkspace();
  if (document.body.classList.contains("contest-immersive"))
    window.scrollTo({ top: 0, behavior: "instant" });
  else
    $("problemList").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderWorkspace() {
  suspendContestWorkspace();
  prepareLuoguConnection();
  $("managementTools").hidden = true;
  $("refreshContests").hidden = true;
  const container = $("problemList");
  container.hidden = false;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  const workspace = el("div", "", "problem-workspace");
  const header = el("div", "", "workspace-header");
  const heading = el("div", "", "workspace-header-title");
  if (managementMode()) heading.append(el("h2", selectedContest.title));
  const headerActions = el("div", "", "workspace-header-actions");
  const countdown = renderContestTimeline(selectedContest, true);
  headerActions.append(
    ...(!managementMode() ? [countdown] : []),
    button("返回比赛信息", () => {
      writeAppRoute(`contest/${selectedContest.id}`);
      renderContestOverview();
    }, "button secondary workspace-back"),
  );
  if (managementMode()) header.append(heading);
  const resetLayout = el("button", "恢复布局", "workspace-layout-reset");
  resetLayout.type = "button";
  resetLayout.title = "恢复默认分栏比例，并退出区域放大";
  if (!managementMode()) headerActions.prepend(resetLayout);
  header.append(headerActions);
  const [statusLabel, statusColor] = contestStatus(selectedContest);
  const livebar = el("div", "", "contest-livebar");
  livebar.append(
    Object.assign(badge(statusLabel, statusColor), { className: `badge ${statusColor} workspace-status` }),
    el("span", selectedContest.judge_mode === "luogu" ? "洛谷评测" : "本站评测", "workspace-judge-mode"),
    el("span", deadline(selectedContest), "workspace-countdown"),
  );
  workspace.append(header);
  if (managementMode()) workspace.append(livebar);
  if (!currentProblems.length) {
    workspace.append(
      emptyState(
        "比赛尚未录入题目",
        managementMode()
          ? "在「录入题目」中选择此比赛，添加题面和测试数据。"
          : "请等待管理员补充题目。",
        "</>",
      ),
    );
    container.replaceChildren(workspace);
    if (!managementMode() && selectedContest.judge_mode === "luogu" && !luoguStatusChecked)
      void refreshLuoguBridgeConnection();
    return;
  }
  const workbench = el("div", "", "problem-workbench");
  const rail = el("aside", "", "problem-rail");
  rail.append(el("div", "题目列表", "problem-rail-label"));
  const tabs = el("nav", "", "problem-tabs");
  tabs.setAttribute("aria-label", "比赛题目");
  currentProblems.forEach((problem, index) => {
    const tab = button(
      "",
      () => {
        selectedProblem = problem.id;
        writeAppRoute(`contest/${selectedContest.id}/workspace/${problem.id}`);
        renderWorkspace();
      },
      `problem-tab${problem.id === selectedProblem ? " selected" : ""}`,
    );
    tab.append(el("b", String.fromCharCode(65 + index)), el("span", problem.title));
    const showSource = problem.remote_problem_id
      && canRevealLuoguSource(selectedContest, Date.now() / 1000, managementMode());
    if (showSource) tab.title = `${problem.remote_problem_id} · ${problem.title}`;
    if (problem.id === selectedProblem)
      tab.setAttribute("aria-current", "page");
    tabs.append(tab);
  });
  rail.append(tabs);
  const problem = currentProblems.find((p) => p.id === selectedProblem);
  const showSource = problem.remote_problem_id
    && canRevealLuoguSource(selectedContest, Date.now() / 1000, managementMode());
  workbench.append(rail);
  const columns = el("div", "", "problem-columns");
  columns.dataset.activePane = mobilePane;
  const restoreBar = el("div", "", "workspace-pane-restores");
  const restoreControls = {};
  const closeControls = {};
  const restorePane = (pane, label) => {
    const control = button(`展开${label}`, () => {}, "workspace-pane-restore");
    control.hidden = true;
    restoreControls[pane] = control;
    restoreBar.append(control);
  };
  restorePane("statement", "题面");
  restorePane("editor", "代码区");
  restorePane("panels", "样例与提交记录");
  const expandAll = button("展开全部", () => {}, "workspace-expand-all");
  expandAll.hidden = true;
  restoreBar.append(expandAll);
  const statement = el("article", "", "panel problem-statement");
  statement.append(
    el("span", showSource ? `洛谷题号 · ${problem.remote_problem_id}` : `题目编号 · #${problem.id}`, "eyebrow"),
    el("h3", problem.title),
  );
  const problemStats = el("p", `尝试 ${problem.attempt_count || 0} 次 · 通过 ${problem.accepted_count || 0} 次`, "problem-attempt-stats");
  problemStats.id = `problemStats-${problem.id}`;
  statement.append(problemStats);
  const sourceActions = el("div", "", "problem-source-actions");
  if (showSource) {
    const remote = el("a", "在洛谷打开题目 ↗", "text-button problem-source-link");
    remote.href = `https://www.luogu.com.cn/problem/${encodeURIComponent(problem.remote_problem_id)}`;
    remote.target = "_blank";
    remote.rel = "noopener noreferrer";
    sourceActions.append(remote);
  }
  if (managementMode() && problem.remote_problem_id) {
    sourceActions.append(button("从洛谷更新题面与样例", async () => {
      const refreshed = await api(`/admin/problems/${problem.id}/refresh`, { method: "POST" });
      currentProblems = currentProblems.map(item => item.id === refreshed.id ? { ...item, ...refreshed, judge_mode: selectedContest.judge_mode } : item);
      renderWorkspace();
      notify("题面与全部公开样例已从洛谷更新，提交记录保持不变。");
    }, "text-button problem-refresh"));
  }
  if (sourceActions.childNodes.length) statement.append(sourceActions);
  appendProblemStatement(statement, problem.statement_html || `<pre>${problem.statement.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</pre>`);
  const samples = problem.samples?.length
    ? problem.samples
    : Boolean(problem.sample_input || problem.sample_output)
      ? [{ input: problem.sample_input ?? "", output: problem.sample_output ?? "" }]
      : [];
  const samplePanel = el("div", "", "workspace-samples");
  for (const [index, values] of samples.entries()) {
    const sample = el("section", "", "sample-block");
    sample.append(el("h4", `样例 ${index + 1}`, "sample-heading"));
    const pair = el("div", "", "sample-pair");
    for (const [name, value] of [["输入", values.input], ["输出", values.output]]) {
      const sampleValue = el("div", "", "sample-value");
      const heading = el("div", "", "sample-value-heading");
      const copy = button("复制", async () => {
        await navigator.clipboard.writeText(value);
        notify(`样例${name}已复制。`);
      }, "text-button");
      copy.setAttribute("aria-label", `复制样例 ${index + 1} ${name}`);
      heading.append(el("span", name), copy);
      sampleValue.append(heading, el("pre", value));
      pair.append(sampleValue);
    }
    sample.append(pair);
    samplePanel.append(sample);
  }
  if (!samples.length && problem.remote_problem_id) {
    samplePanel.append(el("p", "洛谷未提供公开样例。请按题面自行构造测试数据验证程序。", "sample-unavailable"));
  } else if (!samples.length) {
    samplePanel.append(el("p", "此题暂未提供样例。", "muted"));
  }
  columns.append(statement);
  let paneSwitcher;
  let layoutNodes;
  if (!managementMode()) {
    columns.classList.add("candidate-workspace");
    const statementHeading = el("div", "", "workspace-panel-heading statement-panel-heading");
    const statementControl = expandPaneButton();
    const closeStatement = button("×", () => {}, "workspace-icon-button workspace-pane-close");
    closeStatement.setAttribute("aria-label", "收起题面"); closeStatement.title = "收起题面";
    closeControls.statement = closeStatement;
    statementHeading.append(el("span", "题目描述", "workspace-panel-label"), statementControl, closeStatement);
    const statementBody = el("div", "", "workspace-statement-content");
    statementBody.append(...statement.childNodes);
    statement.replaceChildren(statementHeading, statementBody);
    const splitter = el("div", "", "problem-splitter");
    splitter.setAttribute("role", "separator");
    splitter.setAttribute("aria-label", "调整题面和代码区宽度");
    splitter.setAttribute("aria-orientation", "vertical");
    splitter.tabIndex = 0;
    const editorStack = el("div", "", "editor-stack");
    const verticalSplitter = el("div", "", "editor-splitter");
    verticalSplitter.setAttribute("role", "separator");
    verticalSplitter.setAttribute("aria-label", "调整代码区和下方面板高度");
    verticalSplitter.setAttribute("aria-orientation", "horizontal");
    verticalSplitter.tabIndex = 0;
    const panels = renderEditorPanels(samplePanel);
    const editor = renderEditor(problem);
    const closeEditor = button("×", () => {}, "workspace-icon-button workspace-pane-close");
    closeEditor.setAttribute("aria-label", "收起代码区"); closeEditor.title = "收起代码区";
    closeControls.editor = closeEditor;
    editor.querySelector(".editor-heading").append(closeEditor);
    const closePanels = button("×", () => {}, "workspace-icon-button workspace-pane-close");
    closePanels.setAttribute("aria-label", "收起样例与提交记录"); closePanels.title = "收起样例与提交记录";
    closeControls.panels = closePanels;
    panels.querySelector(".auxiliary-panel-heading").append(closePanels);
    const editorControl = expandPaneButton();
    editor.querySelector(".editor-heading").append(editorControl);
    editorStack.append(editor, verticalSplitter, panels);
    columns.append(splitter, editorStack);
    layoutNodes = {
      columns, stack: editorStack, horizontal: splitter, vertical: verticalSplitter,
      controls: { statement: statementControl, editor: editorControl, panels: panels.querySelector(".pane-expand") },
      closeControls, regions: { statement, editor, panels }, restoreControls, expandAll,
      reset: resetLayout, store: layoutPreferences(),
    };
    paneSwitcher = renderMobilePaneSwitcher(columns);
  } else {
    columns.style.gridTemplateColumns = "minmax(0, 1fr)";
    statement.append(samplePanel);
  }
  workbench.append(columns);
  if (paneSwitcher) workbench.insertBefore(restoreBar, columns);
  if (paneSwitcher) workbench.insertBefore(paneSwitcher, columns);
  workspace.append(workbench);
  container.replaceChildren(workspace);
  const selectedTab = tabs.querySelector('.problem-tab.selected');
  if (selectedTab) {
    const tabBounds = selectedTab.getBoundingClientRect();
    const railBounds = tabs.getBoundingClientRect();
    if (tabBounds.right > railBounds.right) tabs.scrollLeft += tabBounds.right - railBounds.right;
    else if (tabBounds.left < railBounds.left) tabs.scrollLeft -= railBounds.left - tabBounds.left;
  }
  if (layoutNodes) disposeWorkspaceLayout = mountWorkspaceLayout(layoutNodes);
  if (!managementMode() && selectedContest.judge_mode === "luogu" && !luoguStatusChecked)
    void refreshLuoguBridgeConnection();
  loadContestSubmissions();
  tick();
}
function renderEditorPanels(samplePanel) {
  const panel = el("section", "", "editor-bottom-panel");
  const tabs = el("div", "", "editor-bottom-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "代码工作区辅助面板");
  const sampleTab = button("样例", () => activate("samples"), "editor-bottom-tab selected");
  const submissionsTab = button("提交记录", () => activate("submissions"), "editor-bottom-tab");
  sampleTab.setAttribute("role", "tab");
  submissionsTab.setAttribute("role", "tab");
  sampleTab.setAttribute("aria-selected", "true");
  submissionsTab.setAttribute("aria-selected", "false");
  const sampleContent = el("div", "", "editor-bottom-content");
  sampleContent.setAttribute("role", "tabpanel");
  sampleContent.append(samplePanel);
  const submissionContent = el("div", "", "editor-bottom-content submissions-tab-content");
  submissionContent.setAttribute("role", "tabpanel");
  submissionContent.hidden = true;
  const records = el("div", "", "inline-submissions");
  records.id = "contestSubmissions";
  submissionContent.append(records);
  tabs.append(sampleTab, submissionsTab);
  enableTabKeyboard(tabs);
  const heading = el("div", "", "workspace-panel-heading auxiliary-panel-heading");
  heading.append(tabs, expandPaneButton());
  panel.append(heading, sampleContent, submissionContent);
  function activate(name) {
    const showSamples = name === "samples";
    sampleContent.hidden = !showSamples;
    submissionContent.hidden = showSamples;
    sampleTab.setAttribute("aria-selected", String(showSamples));
    submissionsTab.setAttribute("aria-selected", String(!showSamples));
    sampleTab.tabIndex = showSamples ? 0 : -1;
    submissionsTab.tabIndex = showSamples ? -1 : 0;
    sampleTab.classList.toggle("selected", showSamples);
    submissionsTab.classList.toggle("selected", !showSamples);
  }
  activate("samples");
  return panel;
}
function enableTabKeyboard(tablist) {
  tablist.addEventListener("keydown", (event) => {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(document.activeElement);
    if (index < 0) return;
    let next;
    if (event.key === "ArrowRight") next = (index + 1) % tabs.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = tabs.length - 1;
    else return;
    event.preventDefault();
    tabs[next].click();
    queueMicrotask(() => {
      if (tabs[next].isConnected && tabs[next].getAttribute("aria-selected") === "true") tabs[next].focus();
    });
  });
}
function renderMobilePaneSwitcher(columns) {
  const switcher = el("div", "", "workspace-pane-switcher");
  switcher.setAttribute("role", "tablist");
  switcher.setAttribute("aria-label", "答题工作区");
  const tabs = [];
  for (const [pane, label] of [["statement", "题面"], ["editor", "代码"]]) {
    const tab = button(label, () => {
      mobilePane = pane;
      columns.dataset.activePane = pane;
      columns.dispatchEvent(new Event("workspacepanechange"));
      tabs.forEach(([name, node]) => {
        node.setAttribute("aria-selected", String(name === pane));
        node.tabIndex = name === pane ? 0 : -1;
        node.classList.toggle("selected", name === pane);
      });
    }, `workspace-pane-tab${mobilePane === pane ? " selected" : ""}`);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(mobilePane === pane));
    tab.tabIndex = mobilePane === pane ? 0 : -1;
    tabs.push([pane, tab]);
    switcher.append(tab);
  }
  enableTabKeyboard(switcher);
  return switcher;
}
function renderEditor(problem) {
  const panel = el("section", "", "panel editor-panel");
  const heading = el("div", "", "editor-heading");
  heading.append(el("h4", "代码工作区"));
  const language = el("select", "", "language-select");
  language.setAttribute("aria-label", "选择编程语言");
  const availableLanguages = selectedContest?.judge_mode === "docker"
    ? LANGUAGES.filter(([value]) => value === "python3")
    : LANGUAGES;
  for (const [value, label] of availableLanguages) { const option = el("option", label); option.value = value; language.append(option); }
  language.value = availableLanguages[0][0];
  heading.append(language);
  const area = el("div", "", "code-area");
  const numbers = el("pre", "", "line-numbers");
  numbers.setAttribute("aria-hidden", "true");
  const input = el("textarea", "", "code-editor mono");
  heading.append(copyCodeButton(() => input.value));
  input.setAttribute("aria-label", `${languageName(language.value)} 代码`);
  input.spellcheck = false;
  input.autocapitalize = "off";
  input.wrap = "off";
  input.maxLength = 30000;
  input.placeholder = language.value === "python3" ? "# 在这里编写你的解答\n# 从标准输入读取，向标准输出输出" : "// 在这里编写你的解答\n// 从标准输入读取，向标准输出输出";
  let previousLanguage = language.value;
  input.value = codeDrafts.read(draftKey(problem.id, previousLanguage));
  const saved = el("span", codeDrafts.available()
    ? "草稿自动保存至此浏览器"
    : "浏览器存储不可用，草稿仅在当前页面保留，请自行保存代码");
  const update = () => {
    numbers.textContent = Array.from(
      { length: input.value.split("\n").length },
      (_, index) => index + 1,
    ).join("\n");
  };
  const saveDraft = (draftLanguage) => {
    const persisted = codeDrafts.write(draftKey(problem.id, draftLanguage), input.value);
    saved.textContent = persisted
      ? "草稿已保存至此浏览器"
      : "草稿仅在当前页面保留，请自行保存代码";
  };
  input.addEventListener("input", () => {
    update();
    saveDraft(language.value);
  });
  language.addEventListener("change", () => {
    saveDraft(previousLanguage);
    previousLanguage = language.value;
    input.value = codeDrafts.read(draftKey(problem.id, language.value));
    input.setAttribute("aria-label", `${languageName(language.value)} 代码`);
    input.placeholder = language.value === "python3" ? "# 在这里编写你的解答\n# 从标准输入读取，向标准输出输出" : "// 在这里编写你的解答\n// 从标准输入读取，向标准输出输出";
    update();
  });
  input.addEventListener("keydown", (event) => {
    if (saveDraftOnShortcut(event, () => saveDraft(language.value))) return;
    if (event.key !== "Tab" || event.shiftKey) return;
    event.preventDefault();
    input.setRangeText("    ", input.selectionStart, input.selectionEnd, "end");
    input.dispatchEvent(new Event("input"));
  });
  input.addEventListener("scroll", () => {
    numbers.scrollTop = input.scrollTop;
  });
  update();
  area.append(numbers, input);
  const footer = el("div", "", "editor-footer");
  const row = el("div", "", "editor-footer-top");
  const submit = button(
    "提交评测 →",
    async () => {
      if (!input.value.trim()) throw new Error("请先输入代码，再提交评测。");
      const source = input.value;
      const submittedLanguage = language.value;
      submitting = true;
      submit.textContent = "评测中…";
      try {
        const response = await api(`/problems/${problem.id}/submissions`, {
          method: "POST",
          body: JSON.stringify({ source, language: submittedLanguage }),
        });
        if (response.judge_mode === "luogu") {
          try {
            const remote = await requestLuoguSubmit({
              submission_id: response.id,
              problem_id: response.remote_problem_id,
              source,
              language: submittedLanguage,
            });
            if (!remote?.remote_submission_id || !remote.status)
              throw new Error("洛谷未返回有效的提交编号和评测状态，请在洛谷页面检查提交记录。");
            const saved = await updateRemoteResult(response.id, remote);
            response.status = saved.status;
          } catch (error) {
            const message = formatLuoguSubmitError(error);
            await updateRemoteResult(response.id, { remote_submission_id: "", status: "Submission Failed", detail: message });
            throw new Error(message);
          }
        }
        await loadContestSubmissions();
        if (response.status === "Judge Error")
          notify("评测服务暂不可用，提交记录已保存，请联系管理员。", "error");
      } finally {
        submitting = false;
        submit.textContent = "提交评测 →";
      }
    },
    "button primary",
  );
  submit.id = "submitCode";
  if (selectedContest.judge_mode === "luogu") row.append(renderLuoguSetup());
  row.append(saved, submit);
  footer.append(row);
  panel.append(heading, area, footer);
  return panel;
}
function renderLuoguSetup() {
  const panel = el("details", "", "panel luogu-setup");
  const heading = el("summary", "", "luogu-setup-heading");
  const status = badge(luoguConnected ? `插件已连接 · ${luoguConnected}` : "需先配置", luoguConnected ? "green" : "orange");
  status.classList.add("luogu-connection-status");
  heading.append(el("span", "洛谷桥接", "luogu-setup-title"), status);
  panel.append(heading,
    el("p", "通过浏览器中的洛谷登录页提交；请保持插件已安装且洛谷处于登录状态。本站不保存洛谷凭证。"),
    button("查看插件配置教程", () => $("luoguTutorial")?.showModal(), "text-button"),
    button("检测洛谷登录状态", async () => {
      const response = await refreshLuoguBridgeConnection({ force: true });
      if (!luoguConnected) throw new Error(response.reason || "未找到已登录的洛谷页面，请先登录洛谷后重试。");
      notify("已连接洛谷登录页面。");
      renderWorkspace();
    }, "button secondary"),
  );
  return panel;
}
function prepareLuoguConnection() {
  const userId = state.user?.id || null;
  if (userId === luoguConnectionUserId) return;
  luoguConnectionUserId = userId;
  luoguConnected = readLuoguConnection(localStorage, userId) || false;
  luoguStatusChecked = false;
  luoguConnectionRequest = null;
}
function setLuoguConnection(account) {
  prepareLuoguConnection();
  luoguConnected = account || false;
  writeLuoguConnection(localStorage, luoguConnectionUserId, luoguConnected);
  const status = document.querySelector(".luogu-connection-status");
  if (status) {
    status.textContent = luoguConnected ? `插件已连接 · ${luoguConnected}` : "需先配置";
    status.className = `badge ${luoguConnected ? "green" : "orange"} luogu-connection-status`;
  }
}
async function refreshLuoguBridgeConnection({ force = false } = {}) {
  prepareLuoguConnection();
  if (luoguConnectionRequest) return luoguConnectionRequest;
  if (luoguStatusChecked && !force)
    return { connected: Boolean(luoguConnected), account: luoguConnected };
  luoguStatusChecked = true;
  const status = document.querySelector(".luogu-connection-status");
  if (status) {
    status.textContent = luoguConnected ? `正在恢复连接 · ${luoguConnected}` : "正在检测洛谷连接";
    status.className = "badge blue luogu-connection-status";
  }
  const request = (async () => {
    try {
      const response = await sendLuoguBridge("PING", {});
      ensureLuoguExtensionCurrent(response);
      setLuoguConnection(response.connected ? response.account || "已连接" : "");
      return response;
    } catch (error) {
      const currentStatus = document.querySelector(".luogu-connection-status");
      if (currentStatus) {
        currentStatus.textContent = luoguConnected ? `上次连接 · ${luoguConnected}（等待确认）` : "插件未响应";
        currentStatus.className = "badge orange luogu-connection-status";
      }
      if (force) throw error;
      return { connected: false, reason: error.message };
    }
  })().finally(() => { luoguConnectionRequest = null; });
  luoguConnectionRequest = request;
  return request;
}
function sendLuoguBridge(type, payload, timeoutMs = 15000) {
  const requestId = crypto.randomUUID();
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => { bridgeWaiters.delete(requestId); reject(new Error("浏览器插件未响应，请检查插件安装和本站地址配置。")); }, timeoutMs);
    bridgeWaiters.set(requestId, { resolve, reject, timeout });
    window.postMessage({ source: "scu-luogu-bridge", type, requestId, payload }, location.origin);
  });
}
window.addEventListener("message", event => {
  if (event.source !== window || event.origin !== location.origin || event.data?.source !== "scu-luogu-bridge-result") return;
  const waiter = bridgeWaiters.get(event.data.requestId);
  if (!waiter) return;
  clearTimeout(waiter.timeout); bridgeWaiters.delete(event.data.requestId);
  if (event.data.error || event.data.payload?.error) waiter.reject(new Error(event.data.error || event.data.payload.error));
  else waiter.resolve(event.data.payload);
});
window.addEventListener("scu-luogu-status", event => {
  if (event.detail?.context === "coding") return;
  const { submission_id, remote_submission_id, status, detail = "" } = event.detail || {};
  if (!Number.isInteger(submission_id) || !remote_submission_id || !status) return;
  void updateRemoteResult(submission_id, { remote_submission_id, status, detail })
    .then(() => {
      if (selectedProblem) void loadContestSubmissions();
    })
    .catch(error => notify(`洛谷评测状态同步失败：${error.message}`, "error"));
});
export async function requestLuoguSubmit(payload) {
  const ping = await refreshLuoguBridgeConnection({ force: true });
  if (!ping.connected) throw new Error(ping.reason || "请先登录洛谷并检测插件连接。");
  return submitWithLuoguVerification(payload, {
    send: value => sendLuoguBridge("SUBMIT", value, 30000),
    requestCaptcha: requestLuoguCaptcha,
  });
}
function ensureLuoguExtensionCurrent(response) {
  if (!isLuoguExtensionOutdated(response.extension_version)) return;
  const tutorial = $("luoguTutorial");
  if (tutorial && !tutorial.open) tutorial.showModal();
  throw new Error("洛谷提交插件需要更新，已打开安装教程。下载新版并刷新浏览器扩展后即可继续。");
}
async function updateRemoteResult(id, payload) {
  return api(`/submissions/${id}/remote-result`, { method: "POST", body: JSON.stringify(payload) });
}
let contestSubmissionsRequest = 0;
let submissionHistoryRequest = 0;
let submissionDetailRequest = 0;
async function loadContestSubmissions() {
  const request = ++contestSubmissionsRequest;
  const cid = selectedContest?.id;
  const target = $("contestSubmissions");
  if (target) {
    const state = submissionPanelMessage("loading");
    target.setAttribute("aria-busy", "true");
    target.replaceChildren(emptyState(state.title, state.description, "◌"));
  }
  try {
    const result = normalizeSubmissionPage(await api(contestPath(`/submissions?page=${contestSubmissionPage}&page_size=10&contest_id=${cid}`)));
    if (selectedContest?.id !== cid || request !== contestSubmissionsRequest) return;
    if (!target) return;
    target.removeAttribute("aria-busy");
    const recordContent = result.items.length ? submissionTable(result.items) : (() => {
      const state = submissionPanelMessage("empty");
      return emptyState(state.title, state.description, "▤");
    })();
    target.replaceChildren(
      sectionHeading(
        managementMode() ? "本场提交" : "我的提交",
        `${result.total} 次尝试`,
      ),
      recordContent,
      paginationControls(result, page => { contestSubmissionPage = page; void loadContestSubmissions(); }),
    );
    try {
      const stats = await api(`/contests/${cid}`);
      if (selectedContest?.id !== cid || request !== contestSubmissionsRequest) return;
      contestOverview = refreshContestProblemStats(contestOverview, stats);
      currentProblems = currentProblems.map(problem => {
        const updated = stats.problems.find(item => item.id === problem.id);
        const node = document.getElementById(`problemStats-${problem.id}`);
        if (updated && node) node.textContent = `尝试 ${updated.attempt_count} 次 · 通过 ${updated.accepted_count} 次`;
        return updated ? { ...problem, ...updated } : problem;
      });
    } catch (error) {
      if (request === contestSubmissionsRequest && selectedContest?.id === cid)
        notify(`提交记录已加载，但题目统计暂未更新：${error.message}`, "info");
    }
  } catch (error) {
    if (request === contestSubmissionsRequest && selectedContest?.id === cid && target) {
      target.removeAttribute("aria-busy");
      const state = submissionPanelMessage("error");
      const message = emptyState(state.title, state.description, "◇");
      message.append(button("重新加载", () => { void loadContestSubmissions(); }, "text-button"));
      target.replaceChildren(message);
    }
  }
}
function submissionTable(rows, { groupedUser = false } = {}) {
  if (!rows.length)
    return emptyState(
      "还没有提交记录",
      managementMode()
        ? "用户提交后，评测结果将显示在这里。"
        : "完成代码后提交评测，结果将在这里展示。",
      "▤",
    );
  const panel = el("div", "", "panel table-panel");
  const wrap = el("div", "", "table-scroll");
  const table = document.createElement("table");
  const caption = el("caption", "代码提交与评测结果", "sr-only");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const labels = [
    "提交编号",
    ...(!groupedUser ? ["用户"] : []),
    "题目",
    "语言",
    "评测结果",
    ...(managementMode() ? ["洛谷记录"] : []),
    "提交时间",
  ];
  for (const label of labels) {
    const th = el("th", label);
    th.scope = "col";
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.className = "submission-row";
    tr.setAttribute("aria-label", `提交 #${row.id}，${row.problem_title || `题目 ${row.problem_id}`}，${languageName(row.language)}，${row.status}，点击查看详情`);
    const idCell = el("td");
    idCell.append(button(`#${row.id}`, () => { void openSubmissionDetail(row.id); }, "submission-open-button"));
    tr.append(idCell);
    if (!groupedUser) tr.append(el("td", row.username || "我"));
    tr.append(el("td", row.problem_title ? `${row.problem_title} · #${row.problem_id}` : `#${row.problem_id}`), el("td", languageName(row.language)));
    const status = el("td");
    status.append(statusBadge(row.status));
    if (managementMode() && row.remote_submission_id) status.append(el("span", "洛谷浏览器同步", "remote-result-source"));
    const cells = [status];
    if (managementMode()) {
      const remote = el("td");
      if (row.remote_submission_id) {
        const link = el("a", `#${row.remote_submission_id}`, "text-button");
        link.href = `https://www.luogu.com.cn/record/${encodeURIComponent(row.remote_submission_id)}`;
        link.target = "_blank"; link.rel = "noopener noreferrer"; remote.append(link);
      } else remote.textContent = "—";
      cells.push(remote);
    }
    const statusHint = [
      managementMode() && row.remote_submission_id ? "洛谷状态由用户浏览器插件读取并同步，请打开洛谷记录复核。" : "",
      row.detail,
    ].filter(Boolean).join("\n");
    if (statusHint) {
      status.title = statusHint;
      status.setAttribute("aria-label", `${row.status}：${statusHint}`);
    }
    tr.append(...cells, el("td", dateTime(row.created)));
    [...tr.children].forEach((cell, index) => { cell.dataset.label = labels[index]; });
    tr.addEventListener("click", event => {
      if (event.target.closest("a,button")) return;
      void openSubmissionDetail(row.id);
    });
    tr.addEventListener("keydown", event => {
      if (event.target !== tr || !["Enter", " "].includes(event.key)) return;
      event.preventDefault(); void openSubmissionDetail(row.id);
    });
    body.append(tr);
  }
  table.append(caption, head, body);
  wrap.append(table);
  panel.append(wrap);
  return panel;
}
function paginationControls(result, change, label = "提交记录分页") {
  if (result.pages <= 1) return el("div");
  const nav = el("nav", "", "submission-pagination");
  nav.setAttribute("aria-label", label);
  const previous = button("← 上一页", () => change(result.page - 1), "button secondary");
  previous.disabled = result.page <= 1;
  const next = button("下一页 →", () => change(result.page + 1), "button secondary");
  next.disabled = result.page >= result.pages;
  nav.append(previous, el("span", `第 ${result.page} / ${result.pages} 页 · 共 ${result.total} 条`), next);
  return nav;
}
async function openSubmissionDetail(id) {
  const dialog = $("submissionDetailDialog");
  const body = $("submissionDetailBody");
  const request = ++submissionDetailRequest;
  const prior = document.activeElement;
  if (!dialog.open) {
    dialog.addEventListener("close", () => {
      submissionDetailRequest++;
      if (prior?.isConnected) prior.focus();
    }, { once: true });
  }
  body.replaceChildren(el("p", "正在读取提交详情…", "muted"));
  $("submissionDetailTitle").textContent = `提交 #${id}`;
  if (!dialog.open) dialog.showModal();
  try {
    const item = await api(contestPath(`/submissions/${id}`));
    if (!dialog.open || request !== submissionDetailRequest) return;
    body.replaceChildren();
    const meta = el("dl", "", "submission-detail-meta");
    for (const [label, value] of [["比赛", item.contest_title], ["题目", `${item.problem_title} · #${item.problem_id}`], ["编程语言", languageName(item.language)], ["评测结果", item.status], ["提交时间", dateTime(item.created)]]) {
      const entry = el("div", "", "submission-detail-field"); entry.append(el("dt", label), el("dd", value || "—")); meta.append(entry);
    }
    body.append(meta);
    const detail = el("section", "", "submission-detail-message");
    const judgeDetail = item.detail || (item.status === "Accepted" ? "全部测试用例通过。" : item.status);
    detail.append(el("h3", "评测信息"), el("pre", judgeDetail));
    body.append(detail);
    if (managementMode() && item.remote_submission_id) {
      const remote = el("a", `打开洛谷记录 #${item.remote_submission_id} ↗`, "text-button");
      remote.href = `https://www.luogu.com.cn/record/${encodeURIComponent(item.remote_submission_id)}`;
      remote.target = "_blank"; remote.rel = "noopener noreferrer"; body.append(remote);
    }
    const source = el("section", "", "submission-detail-source");
    const sourceHeading = el("div", "", "submission-code-heading");
    sourceHeading.append(el("h3", "提交代码"), copyCodeButton(() => item.source));
    source.append(sourceHeading);
    const code = el("pre", item.source, "mono"); code.tabIndex = 0; source.append(code); body.append(source);
  } catch (error) {
    if (dialog.open && request === submissionDetailRequest) body.replaceChildren(el("p", error.message, "form-error"));
  }
}
export async function refreshSubmissions() {
  const request = ++submissionHistoryRequest;
  const target = $("submissionContent");
  target.setAttribute("aria-busy", "true");
  target.querySelector(".submission-loading")?.remove();
  const loading = el("p", "正在加载提交记录…", "muted submission-loading");
  loading.setAttribute("role", "status");
  target.prepend(loading);
  let result;
  try {
    const path = managementMode()
      ? `/submissions/users?page=${submissionUsersPage}&page_size=${submissionPageSize}`
      : `/submissions?page=${submissionHistoryPage}&page_size=${submissionPageSize}`;
    result = await api(contestPath(path));
    if (!managementMode()) result = normalizeSubmissionPage(result);
  } catch (error) {
    if (request === submissionHistoryRequest) {
      target.removeAttribute("aria-busy");
      const retry = button("重试", () => { void refreshSubmissions(); }, "button secondary");
      const message = error instanceof TypeError ? "网络连接失败，请检查网络后重试。" : error.message;
      target.replaceChildren(el("p", `提交记录加载失败：${message}`, "form-error"), retry);
    }
    return;
  }
  if (request !== submissionHistoryRequest) return;
  target.removeAttribute("aria-busy");
  const summary = el("div", "", "submission-summary");
  const summaryValues = managementMode()
    ? [["提交用户", result.total], ["累计提交", result.stats.total], ["通过", result.stats.accepted], ["评测中", result.stats.judging]]
    : [["累计提交", result.total], ["通过", result.stats.accepted], ["评测中", result.stats.judging]];
  for (const [name, value] of summaryValues) {
    const chip = el("div", "", "summary-chip");
    chip.append(el("span", name), el("strong", value));
    summary.append(chip);
  }
  if (managementMode()) {
    target.replaceChildren(summary, groupedSubmissionTables(result.items), paginationControls(
      result,
      page => { submissionUsersPage = page; void refreshSubmissions(); },
      "提交用户列表分页",
    ));
  } else {
    const records = submissionTable(result.items);
    if (!result.total) {
      records.append(button("查看比赛", () => {
        document.dispatchEvent(new CustomEvent("navigate-view", { detail: { view: "contest" } }));
      }, "button secondary"));
    }
    target.replaceChildren(summary, records, paginationControls(
      result,
      page => { submissionHistoryPage = page; void refreshSubmissions(); },
    ));
  }
}
function groupedSubmissionTables(users) {
  if (!users.length) return emptyState("暂无用户提交", "用户提交代码后，会按用户分组显示在这里。", "▤");
  const root = el("div", "", "submission-user-groups");
  for (const user of users) {
    const group = document.createElement("details");
    group.className = "submission-user-group";
    const heading = document.createElement("summary");
    heading.className = "submission-user-heading";
    heading.append(el("span", user.username, "submission-user-name"), el("span", `${user.submission_count} 条提交`, "submission-user-count"));
    const records = el("div", "", "submission-user-records");
    records.dataset.loaded = "false";
    group.append(heading, records);
    group.addEventListener("toggle", () => {
      if (group.open && records.dataset.loaded === "false") void loadUserSubmissionPage(group, user, 1);
    });
    root.append(group);
  }
  return root;
}
async function loadUserSubmissionPage(group, user, page) {
  const target = group.querySelector(".submission-user-records");
  const request = (userSubmissionRequestIds.get(group) || 0) + 1;
  userSubmissionRequestIds.set(group, request);
  target.dataset.loaded = "loading";
  target.setAttribute("aria-busy", "true");
  target.replaceChildren(el("p", "正在加载提交记录…", "muted submission-loading"));
  try {
    const result = await api(contestPath(`/submissions/users/${user.user_id}?page=${page}&page_size=${submissionPageSize}`));
    if (!group.isConnected || userSubmissionRequestIds.get(group) !== request) return;
    target.dataset.loaded = "true";
    target.removeAttribute("aria-busy");
    target.replaceChildren(submissionTable(result.items, { groupedUser: true }), paginationControls(
      result,
      nextPage => { void loadUserSubmissionPage(group, user, nextPage); },
      `${user.username}提交记录分页`,
    ));
  } catch (error) {
    if (!group.isConnected || userSubmissionRequestIds.get(group) !== request) return;
    target.dataset.loaded = "false";
    target.removeAttribute("aria-busy");
    target.replaceChildren(
      el("p", `提交记录加载失败：${error.message}`, "form-error"),
      button("重试", () => { void loadUserSubmissionPage(group, user, page); }, "button secondary"),
    );
  }
}
export async function createContest() {
  if (!editingContestId && !selectedLuoguProblems.length)
    throw new Error("至少添加一道洛谷题目后才能创建比赛。");
  const starts = new Date($("starts").value).getTime() / 1000;
  const ends = new Date($("ends").value).getTime() / 1000;
  if (!Number.isFinite(starts) || !Number.isFinite(ends))
    throw new Error("请选择有效的开始和结束时间。");
  if (ends <= starts) throw new Error("结束时间需要晚于开始时间。");
  const editing = editingContestId !== null;
  const body = { title: $("contestTitle").value.trim(), starts, ends,
    show_ranking: $("showRanking").checked, ranking_rule: $("rankingRule").value,
    participant_ids: contestParticipantIds() };
  if (editing) {
    body.judge_mode = editingContestJudgeMode;
    if (editingContestJudgeMode === "luogu") body.problems = selectedLuoguProblems;
  } else {
    body.judge_mode = "luogu";
    body.problems = selectedLuoguProblems;
  }
  const response = await api(editing ? `/admin/contests/${editingContestId}` : "/admin/contests", {
    method: editing ? "PUT" : "POST",
    body: JSON.stringify(body),
  });
  const finishedId = editingContestId || response.id;
  cancelContestEditing();
  $("contestForm").reset();
  selectedLuoguProblems = [];
  renderSelectedLuoguProblems();
  $("luoguProblemSearch").value = "";
  $("luoguProblemSuggestions").replaceChildren();
  await refreshContests();
  if (selectedContest?.id === finishedId) {
    selectedContest = contests.find(item => item.id === finishedId) || null;
    if (selectedContest) {
      contestOverview = await api(`/contests/${finishedId}`);
      renderContestOverview();
    }
  }
  notify(editing ? `比赛 #${finishedId} 信息已更新。` : `比赛 #${response.id} 已创建，包含 ${response.problem_ids.length} 道题目。`);
}
let editingContestJudgeMode = "luogu";
function dateTimeInput(timestamp) {
  const date = new Date(timestamp * 1000 - new Date().getTimezoneOffset() * 60000);
  return date.toISOString().slice(0, 16);
}
async function beginEditContest(contest) {
  await loadContestRoster(contest.id);
  if (selectedContest?.id === contest.id) {
    writeAppRoute("contest");
    selectedContest = null;
    contestOverview = null;
    $("problemList").replaceChildren();
    $("problemList").hidden = true;
    renderContestList();
  }
  editingContestId = contest.id;
  editingContestJudgeMode = contest.judge_mode;
  $("contestTitle").value = contest.title;
  $("starts").value = dateTimeInput(contest.starts);
  $("ends").value = dateTimeInput(contest.ends);
  $("showRanking").checked = Boolean(contest.show_ranking);
  $("rankingRule").value = contest.ranking_rule || "score";
  const questionFields = document.querySelectorAll(".contest-question-fields");
  for (const field of questionFields) field.hidden = contest.judge_mode !== "luogu";
  if (contest.judge_mode === "luogu") {
    selectedLuoguProblems = await api(`/admin/contests/${contest.id}/problems`);
    selectedLuoguProblems = selectedLuoguProblems.map(problem => ({
      ...problem,
      id: problem.id,
      remote_problem_id: problem.remote_problem_id,
      samples: problem.samples || [],
      tests: [],
      points: problem.points ?? 100,
    }));
    renderSelectedLuoguProblems();
  } else {
    selectedLuoguProblems = [];
    $("contestForm").querySelector('[type="submit"]').disabled = false;
  }
  $("contestDisclosureTitle").textContent = `编辑比赛 · ${contest.title}`;
  $("luoguProblemHelp").textContent = "可调整题单；已有提交记录的题目不能移除。题面和样例均可从洛谷刷新。";
  $("contestFormHelp").textContent = "保存后更新比赛信息和题单；已有提交的题目不能移除。";
  $("contestForm").querySelector('[type="submit"]').textContent = "保存修改";
  $("contestFormCancel").hidden = false;
  $("contestForm").closest("details").open = true;
  $("contestForm").scrollIntoView({ behavior: "smooth", block: "center" });
}
function cancelContestEditing() {
  resetContestRoster();
  editingContestId = null;
  editingContestJudgeMode = "luogu";
  selectedLuoguProblems = [];
  $("contestDisclosureTitle").textContent = "创建比赛";
  $("luoguProblemHelp").textContent = "选择候选题目后自动获取题面与全部公开样例，可添加多道题。";
  $("contestFormHelp").textContent = "题目和比赛信息将一并保存；至少选择一道题。";
  $("contestForm").querySelector('[type="submit"]').textContent = "创建比赛";
  $("contestFormCancel").hidden = true;
  for (const field of document.querySelectorAll(".contest-question-fields")) field.hidden = false;
  $("contestForm").reset();
  $("contestForm").closest("details").open = false;
  renderSelectedLuoguProblems();
}
export function setupContestCreation() {
  setupContestRoster();
  $("closeSubmissionDetail").addEventListener("click", () => $("submissionDetailDialog").close());
  $("closeSubmissionDetailFooter").addEventListener("click", () => $("submissionDetailDialog").close());
  const input = $("luoguProblemSearch");
  const results = $("luoguProblemSuggestions");
  const submit = $("contestForm").querySelector('[type="submit"]');
  input.addEventListener("input", () => {
    clearTimeout(problemSearchTimer);
    const query = input.value.trim();
    const revision = ++problemSearchRevision;
    if (!query) {
      results.replaceChildren();
      results.hidden = true;
      input.setAttribute("aria-expanded", "false");
      return;
    }
    problemSearchTimer = setTimeout(async () => {
      try {
        const suggestions = await api(`/admin/luogu/problem-suggestions?q=${encodeURIComponent(query)}`);
        if (revision === problemSearchRevision && query === input.value.trim()) renderLuoguSuggestions(suggestions, results);
      } catch (error) {
        if (revision === problemSearchRevision) { results.replaceChildren(el("p", error.message, "luogu-suggestion-error")); results.hidden = false; input.setAttribute("aria-expanded", "true"); }
      }
    }, 300);
  });
  input.addEventListener("keydown", event => {
    if (event.key === "Escape") { results.hidden = true; input.setAttribute("aria-expanded", "false"); }
    if (event.key === "ArrowDown" && !results.hidden) {
      event.preventDefault();
      results.querySelector('[role="option"]')?.focus();
    }
  });
  results.addEventListener("keydown", event => {
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    event.preventDefault();
    const options = [...results.querySelectorAll('[role="option"]')];
    const current = options.indexOf(document.activeElement);
    const next = event.key === "ArrowDown" ? Math.min(current + 1, options.length - 1) : Math.max(current - 1, 0);
    options[next]?.focus();
  });
  document.addEventListener("click", event => {
    if (!event.target.closest(".luogu-question-search")) {
      results.hidden = true;
      input.setAttribute("aria-expanded", "false");
    }
  });
  submit.disabled = true;
  renderSelectedLuoguProblems();
  $("contestFormCancel").addEventListener("click", cancelContestEditing);
}

function renderLuoguSuggestions(suggestions, container) {
  container.replaceChildren();
  if (!suggestions.length) { container.append(el("p", "没有匹配的题目。", "luogu-suggestion-empty")); container.hidden = false; $("luoguProblemSearch").setAttribute("aria-expanded", "true"); return; }
  for (const item of suggestions) {
    const option = button(`${item.problem_id} · ${item.title}`, async () => {
      if (selectedLuoguProblems.some(problem => problem.remote_problem_id === item.problem_id)) { notify("这道题已加入比赛。"); return; }
      const problem = await api(`/admin/luogu/problems/${encodeURIComponent(item.problem_id)}`);
      selectedLuoguProblems.push({ ...problem, remote_problem_id: problem.problem_id, tests: [], points: 100 });
      $("luoguProblemSearch").value = "";
      container.replaceChildren(); container.hidden = true;
      $("luoguProblemSearch").setAttribute("aria-expanded", "false");
      renderSelectedLuoguProblems();
    }, "luogu-suggestion-option");
    option.setAttribute("role", "option"); container.append(option);
  }
  container.hidden = false;
  $("luoguProblemSearch").setAttribute("aria-expanded", "true");
}

function renderSelectedLuoguProblems() {
  const container = $("selectedLuoguProblems");
  const submit = $("contestForm").querySelector('[type="submit"]');
  container.replaceChildren(); submit.disabled = selectedLuoguProblems.length === 0;
  if (!selectedLuoguProblems.length) { container.append(el("p", editingContestId ? "至少保留一道洛谷题目。" : "至少选择一道洛谷题目后才能创建比赛。", "muted")); return; }
  const list = el("div", "", "selected-question-list");
  selectedLuoguProblems.forEach((problem, index) => {
    const item = el("article", "", "selected-question");
    const heading = el("div", "", "selected-question-heading");
    const title = el("div", "", "selected-question-title");
    title.append(el("span", problem.remote_problem_id, "eyebrow"), el("strong", problem.title));
    const remove = button("移除", () => { selectedLuoguProblems.splice(index, 1); renderSelectedLuoguProblems(); }, "text-button");
    remove.setAttribute("aria-label", `移除 ${problem.remote_problem_id} ${problem.title}`);
    heading.append(title, remove);
    const detail = document.createElement("details");
    const samples = el("div", "", "imported-question-samples");
    const examples = problem.samples?.length
      ? problem.samples
      : Boolean(problem.sample_input || problem.sample_output)
        ? [{ input: problem.sample_input ?? "", output: problem.sample_output ?? "" }]
        : [];
    for (const [sampleIndex, example] of examples.entries()) {
      samples.append(el("pre", `样例 ${sampleIndex + 1} · 输入\n${example.input ?? ""}`), el("pre", `样例 ${sampleIndex + 1} · 输出\n${example.output ?? ""}`));
    }
    if (!examples.length) samples.append(el("p", "洛谷未提供公开样例。", "muted"));
    const statement = el("div", "", "imported-question-statement markdown-content");
    statement.innerHTML = normalizeProblemStatementHtml(problem.statement_html || problem.statement);
    detail.append(el("summary", "查看自动导入的题面与样例"), statement, samples);
    detail.addEventListener("toggle", () => { if (detail.open) void renderProblemMath(statement); });
    const pointsLabel = el("label", "题目分值"); pointsLabel.className = "selected-question-points";
    const points = el("input"); points.type = "number"; points.min = "0"; points.max = "100000"; points.step = "1";
    points.value = String(problem.points ?? 100); points.setAttribute("aria-label", `${problem.remote_problem_id} 题目分值`);
    points.addEventListener("input", () => { problem.points = Number(points.value); });
    pointsLabel.append(points);
    item.append(heading, pointsLabel, detail); list.append(item);
  });
  container.append(list);
}

export function updateJudgeModeFields() {
  const luogu = $("judgeMode").value === "luogu";
  $("remoteProblemField").hidden = !luogu;
  $("remoteProblemId").required = luogu;
  $("localTestsField").hidden = luogu;
  $("tests").required = !luogu;
}
