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
} from "./ui.js?v=20261114-ui-v17";
import { appendProblemStatement, renderProblemMath } from "./problem-content.js?v=20261114-ui-v20";
import { formatLuoguSubmitError, isLuoguExtensionOutdated } from "./luogu-errors.mjs?v=20261114-captcha-v2";

let contests = [];
let selectedContest = null;
let currentProblems = [];
let selectedProblem = null;
let clock;
let submitting = false;
let luoguConnected = false;
let selectedLuoguProblems = [];
let editingContestId = null;
let contestOverview = null;
let problemSearchTimer;
let problemSearchRevision = 0;
let mobilePane = "statement";
const bridgeWaiters = new Map();
const timerNodes = new Map();
const submissionResultNodes = new Map();
const managementMode = () => state.adminMode;
const contestPath = (path) => `${managementMode() ? "/admin" : ""}${path}`;
const draftKey = (id) => `scu:${state.user.id}:code:${id}`;

export function clearContestState() {
  contests = [];
  selectedContest = null;
  currentProblems = [];
  selectedProblem = null;
  contestOverview = null;
  editingContestId = null;
  timerNodes.clear();
  submissionResultNodes.clear();
  bridgeWaiters.clear();
  clearInterval(clock);
  $("problemList").replaceChildren();
  $("problemList").hidden = true;
  $("contestList").hidden = false;
  $("contestListHeading").hidden = false;
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
  const now = Date.now() / 1000;
  return managementMode() || (now >= contest.starts && now <= contest.ends);
}
function contestAvailability(contest) {
  const now = Date.now() / 1000;
  if (now < contest.starts) return "比赛开始后开放题目";
  if (now > contest.ends) return "比赛已结束";
  return "";
}
function tick() {
  for (const [id, nodes] of timerNodes) {
    const contest = contests.find((c) => c.id === id);
    if (!contest) continue;
    nodes.time.textContent = deadline(contest);
    const [label, color] = contestStatus(contest);
    nodes.status.textContent = label;
    nodes.status.className = `badge ${color}`;
    if (nodes.enter) nodes.enter.disabled = !contestCanEnter(contest);
    if (nodes.availability) {
      nodes.availability.textContent = contestAvailability(contest);
      nodes.availability.hidden = contestCanEnter(contest);
    }
  }
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
  const list = $("contestList");
  list.hidden = Boolean(selectedContest);
  $("contestListHeading").hidden = Boolean(selectedContest);
  list.replaceChildren();
  timerNodes.clear();
  $("contestCount").textContent = `${contests.length} 场比赛`;
  if (!contests.length)
    list.append(
      emptyState(
        "暂时没有比赛",
        managementMode()
          ? "创建比赛时搜索洛谷题目并自动导入题面。"
          : "管理员发布比赛后，将在这里展示，请留意考试安排。",
        "</>",
      ),
    );
  for (const contest of contests) {
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
  clearInterval(clock);
  clock = setInterval(tick, 1000);
  if (selectedContest)
    selectedContest = contests.find((c) => c.id === selectedContest.id) || null;
}
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
async function openContest(contest) {
  try {
    contestOverview = await api(`/contests/${contest.id}`);
  } catch (error) {
    if (error.status !== 404) throw error;
    let problems = [];
    try {
      problems = await api(`/contests/${contest.id}/problems`);
    } catch (problemError) {
      if (problemError.status !== 403) throw problemError;
    }
    contestOverview = {
      ...contest,
      problem_count: problems.length || null,
      problems: problems.map(({ id, title, remote_problem_id }) => ({ id, title, remote_problem_id })),
    };
  }
  selectedContest = contest;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  currentProblems = [];
  selectedProblem = null;
  renderContestOverview();
  $("problemList").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderContestOverview() {
  const container = $("problemList");
  container.hidden = false;
  const panel = el("section", "", "panel contest-overview");
  const head = el("div", "", "contest-overview-head");
  head.append(el("span", `CONTEST / ${String(contestOverview.id).padStart(3, "0")}`, "eyebrow"));
  const [label, color] = contestStatus(contestOverview);
  head.append(badge(label, color));
  panel.append(head, el("h2", contestOverview.title, "contest-overview-title"));
  const schedule = el("div", "", "contest-overview-schedule");
  for (const [name, value] of [["开始时间", contestOverview.starts], ["结束时间", contestOverview.ends]]) {
    const row = el("div", "", "contest-overview-time");
    row.append(el("span", name), el("strong", dateTime(value)));
    schedule.append(row);
  }
  const meta = el("div", "", "contest-overview-meta");
  meta.append(
    el("span", contestOverview.problem_count == null ? "题目将在开赛后开放" : `${contestOverview.problem_count} 道题目`),
    el("span", deadline(contestOverview), "countdown"),
  );
  panel.append(schedule, meta);
  const list = el("div", "", "contest-overview-problems");
  list.append(el("h3", "比赛题目"));
  contestOverview.problems.forEach((problem, index) => {
    const item = el("div", "", "contest-overview-problem");
    item.append(el("span", String.fromCharCode(65 + index), "problem-rail-letter"));
    const title = el("div", "", "contest-overview-problem-title");
    title.append(el("strong", problem.title));
    if (problem.remote_problem_id) title.append(el("span", problem.remote_problem_id, "muted"));
    item.append(title);
    list.append(item);
  });
  panel.append(list);
  const actions = el("div", "", "contest-overview-actions");
  actions.append(button("← 返回比赛列表", () => {
    selectedContest = null;
    contestOverview = null;
    container.replaceChildren();
    container.hidden = true;
    $("contestList").hidden = false;
    $("contestListHeading").hidden = false;
    void refreshContests();
  }, "button secondary"));
  if (managementMode()) actions.append(button("编辑比赛信息", () => beginEditContest(selectedContest), "text-button"));
  const canEnter = contestCanEnter(contestOverview);
  const enter = button(managementMode() ? "查看题目工作区 →" : "开始答题 →", enterContest, "button primary");
  enter.disabled = !canEnter;
  actions.append(enter);
  const availability = el("span", contestAvailability(contestOverview), "muted contest-availability");
  availability.hidden = canEnter;
  actions.append(availability);
  const countdown = meta.querySelector(".countdown");
  timerNodes.set(contestOverview.id, {
    time: countdown,
    status: head.querySelector(".badge"),
    enter,
    availability,
  });
  panel.append(actions);
  container.replaceChildren(panel);
  tick();
}
async function enterContest() {
  currentProblems = await api(contestPath(`/contests/${selectedContest.id}/problems`));
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  selectedProblem = currentProblems[0]?.id ?? null;
  renderWorkspace();
  $("problemList").scrollIntoView({ behavior: "smooth", block: "start" });
}
function renderWorkspace() {
  const container = $("problemList");
  container.hidden = false;
  $("contestList").hidden = true;
  $("contestListHeading").hidden = true;
  const workspace = el("div", "", "problem-workspace");
  const header = el("div", "", "workspace-header");
  const heading = el("div", "", "workspace-header-title");
  heading.append(el("span", "答题工作区", "eyebrow"), el("h2", selectedContest.title));
  header.append(heading, button("返回比赛信息", renderContestOverview, "button secondary workspace-back"));
  const [statusLabel, statusColor] = contestStatus(selectedContest);
  const livebar = el("div", "", "contest-livebar");
  livebar.append(
    Object.assign(badge(statusLabel, statusColor), { className: `badge ${statusColor} workspace-status` }),
    el("span", selectedContest.judge_mode === "luogu" ? "洛谷评测" : "本站评测", "workspace-judge-mode"),
    el("span", deadline(selectedContest), "workspace-countdown"),
  );
  workspace.append(header, livebar);
  if (!managementMode() && selectedContest.judge_mode === "luogu") workspace.append(renderLuoguSetup());
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
        renderWorkspace();
      },
      `problem-tab${problem.id === selectedProblem ? " selected" : ""}`,
    );
    tab.append(el("b", String.fromCharCode(65 + index)), el("span", problem.title));
    if (problem.remote_problem_id) tab.title = `${problem.remote_problem_id} · ${problem.title}`;
    if (problem.id === selectedProblem)
      tab.setAttribute("aria-current", "page");
    tabs.append(tab);
  });
  rail.append(tabs);
  const problem = currentProblems.find((p) => p.id === selectedProblem);
  if (problem.remote_problem_id) {
    const remote = el("a", "在洛谷打开题目 ↗", "text-button problem-rail-remote");
    remote.href = `https://www.luogu.com.cn/problem/${encodeURIComponent(problem.remote_problem_id)}`;
    remote.target = "_blank";
    remote.rel = "noopener noreferrer";
    rail.append(remote);
  }
  workbench.append(rail);
  const columns = el("div", "", "problem-columns");
  columns.dataset.activePane = mobilePane;
  const statement = el("article", "", "panel problem-statement");
  statement.append(
    el("span", problem.remote_problem_id ? `洛谷题号 · ${problem.remote_problem_id}` : `题目编号 · #${problem.id}`, "eyebrow"),
    el("h3", problem.title),
  );
  if (managementMode() && problem.remote_problem_id) {
    statement.append(button("从洛谷更新题面与样例", async () => {
      const refreshed = await api(`/admin/problems/${problem.id}/refresh`, { method: "POST" });
      currentProblems = currentProblems.map(item => item.id === refreshed.id ? { ...item, ...refreshed, judge_mode: selectedContest.judge_mode } : item);
      renderWorkspace();
      notify("题面与全部公开样例已从洛谷更新，提交记录保持不变。");
    }, "text-button problem-refresh"));
  }
  appendProblemStatement(statement, problem.statement_html || `<pre>${problem.statement.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</pre>`);
  const samples = problem.samples?.length
    ? problem.samples
    : Boolean(problem.sample_input || problem.sample_output)
      ? [{ input: problem.sample_input ?? "", output: problem.sample_output ?? "" }]
      : [];
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
    statement.append(sample);
  }
  if (!samples.length && problem.remote_problem_id) {
    statement.append(el("p", "洛谷未提供公开样例。请按题面自行构造测试数据验证程序。", "sample-unavailable"));
  }
  columns.append(statement);
  let paneSwitcher;
  if (!managementMode()) {
    columns.classList.add("candidate-workspace");
    const splitter = el("div", "", "problem-splitter");
    splitter.setAttribute("role", "separator");
    splitter.setAttribute("aria-label", "调整题面和代码区宽度");
    splitter.setAttribute("aria-orientation", "vertical");
    splitter.setAttribute("aria-valuemin", "32");
    splitter.setAttribute("aria-valuemax", "68");
    splitter.tabIndex = 0;
    attachProblemSplitter(splitter, columns);
    columns.append(splitter, renderEditor(problem));
    paneSwitcher = renderMobilePaneSwitcher(columns);
  } else {
    columns.style.gridTemplateColumns = "minmax(0, 1fr)";
  }
  workbench.append(columns);
  if (paneSwitcher) workbench.insertBefore(paneSwitcher, columns);
  workspace.append(workbench);
  const records = el("div", "", "inline-submissions");
  records.id = "contestSubmissions";
  workspace.append(records);
  container.replaceChildren(workspace);
  loadContestSubmissions();
  tick();
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
      tabs.forEach(([name, node]) => {
        node.setAttribute("aria-selected", String(name === pane));
        node.classList.toggle("selected", name === pane);
      });
    }, `workspace-pane-tab${mobilePane === pane ? " selected" : ""}`);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(mobilePane === pane));
    tabs.push([pane, tab]);
    switcher.append(tab);
  }
  return switcher;
}
function attachProblemSplitter(splitter, columns) {
  let ratio = 0.48;
  const apply = value => {
    ratio = Math.min(0.68, Math.max(0.32, value));
    columns.style.gridTemplateColumns = `minmax(0, ${ratio}fr) 10px minmax(0, ${1 - ratio}fr)`;
    splitter.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
  };
  splitter.addEventListener("pointerdown", event => {
    event.preventDefault();
    const bounds = columns.getBoundingClientRect();
    const move = moveEvent => apply((moveEvent.clientX - bounds.left) / bounds.width);
    const finish = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", finish);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish, { once: true });
    window.addEventListener("pointercancel", finish, { once: true });
  });
  splitter.addEventListener("keydown", event => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    apply(ratio + (event.key === "ArrowLeft" ? -0.04 : 0.04));
  });
  apply(ratio);
}
function renderEditor(problem) {
  const panel = el("section", "", "panel editor-panel");
  const heading = el("div", "", "editor-heading");
  heading.append(
    el("h4", "代码工作区"),
    el("span", "Python 3", "language-label"),
  );
  const area = el("div", "", "code-area");
  const numbers = el("pre", "", "line-numbers");
  numbers.setAttribute("aria-hidden", "true");
  const input = el("textarea", "", "code-editor mono");
  input.setAttribute("aria-label", "Python 3 代码");
  input.spellcheck = false;
  input.autocapitalize = "off";
  input.wrap = "off";
  input.maxLength = 30000;
  input.placeholder = "# 在这里编写你的解答\n# 从标准输入读取，向标准输出输出";
  let storageAvailable = true;
  try {
    input.value = localStorage.getItem(draftKey(problem.id)) || "";
  } catch {
    storageAvailable = false;
  }
  const saved = el(
    "span",
    storageAvailable
      ? "草稿自动保存至此浏览器"
      : "浏览器存储不可用，请自行保存代码",
  );
  const update = () => {
    numbers.textContent = Array.from(
      { length: input.value.split("\n").length },
      (_, index) => index + 1,
    ).join("\n");
  };
  input.addEventListener("input", () => {
    update();
    try {
      localStorage.setItem(draftKey(problem.id), input.value);
      saved.textContent = "草稿已保存至此浏览器";
    } catch {
      saved.textContent = "草稿保存失败，请自行保存代码";
    }
  });
  input.addEventListener("keydown", (event) => {
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
      submitting = true;
      const result = el("div", "", "submission-result");
      footer.querySelector(".submission-result")?.remove();
      result.append(el("span", "正在评测，请稍候…", "busy-label"));
      footer.append(result);
      try {
        const response = await api(`/problems/${problem.id}/submissions`, {
          method: "POST",
          body: JSON.stringify({ source: input.value, language: "python3" }),
        });
        if (response.judge_mode === "luogu") {
          try {
            const remote = await requestLuoguSubmit({
              submission_id: response.id,
              problem_id: response.remote_problem_id,
              source: input.value,
              language: "python3",
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
        submissionResultNodes.set(response.id, result);
        if (submissionResultNodes.size > 30)
          submissionResultNodes.delete(submissionResultNodes.keys().next().value);
        result.replaceChildren(
          el("span", `提交 #${response.id}`),
          statusBadge(response.status),
        );
        await loadContestSubmissions();
        if (response.status === "Judge Error")
          notify("评测服务暂不可用，提交记录已保存，请联系管理员。", "error");
      } catch (error) {
        result.replaceChildren(
          el("span", "未获得评测结果，请刷新提交记录后确认。"),
        );
        throw error;
      } finally {
        submitting = false;
      }
    },
    "button primary",
  );
  submit.id = "submitCode";
  row.append(saved, submit);
  footer.append(row);
  panel.append(heading, area, footer);
  return panel;
}
function renderLuoguSetup() {
  const panel = el("section", "", "panel luogu-setup");
  const heading = el("div", "", "luogu-setup-heading");
  heading.append(el("h3", "洛谷提交桥接"), badge(luoguConnected ? `插件已连接 · ${luoguConnected}` : "需先配置", luoguConnected ? "green" : "orange"));
  panel.append(heading,
    el("p", "通过浏览器中的洛谷登录页提交；请保持插件已安装且洛谷处于登录状态。本站不保存洛谷凭证。"),
    button("查看插件配置教程", () => $("luoguTutorial")?.showModal(), "text-button"),
    button("检测洛谷登录状态", async () => {
      const response = await sendLuoguBridge("PING", {});
      ensureLuoguExtensionCurrent(response);
      luoguConnected = response.connected ? response.account || "已连接" : false;
      if (!luoguConnected) throw new Error(response.reason || "未找到已登录的洛谷页面，请先登录洛谷后重试。");
      notify("已连接洛谷登录页面。");
      renderWorkspace();
    }, "button secondary"),
  );
  return panel;
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
  const { submission_id, remote_submission_id, status, detail = "" } = event.detail || {};
  if (!Number.isInteger(submission_id) || !remote_submission_id || !status) return;
  void updateRemoteResult(submission_id, { remote_submission_id, status, detail })
    .then(saved => {
      const result = submissionResultNodes.get(submission_id);
      if (result?.isConnected) {
        result.replaceChildren(el("span", `提交 #${submission_id}`), statusBadge(saved.status));
        if (detail) result.title = `洛谷状态由浏览器插件同步：${detail}`;
      }
      if (selectedProblem) void loadContestSubmissions();
    })
    .catch(error => notify(`洛谷评测状态同步失败：${error.message}`, "error"));
});
async function requestLuoguSubmit(payload) {
  const ping = await sendLuoguBridge("PING", {});
  ensureLuoguExtensionCurrent(ping);
  if (!ping.connected) throw new Error(ping.reason || "请先登录洛谷并检测插件连接。");
  luoguConnected = true;
  return sendLuoguBridge("SUBMIT", payload, 30000);
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
async function loadContestSubmissions() {
  const cid = selectedContest?.id;
  try {
    const submissions = await api(contestPath("/submissions"));
    if (selectedContest?.id !== cid) return;
    const target = $("contestSubmissions");
    if (!target) return;
    const ids = new Set(currentProblems.map((p) => p.id));
    const rows = submissions.filter((s) => ids.has(s.problem_id));
    target.replaceChildren(
      sectionHeading(
        managementMode() ? "本场提交" : "我的提交",
        `${rows.length} 次尝试`,
      ),
      submissionTable(rows),
    );
  } catch (error) {
    notify(error.message, "error");
  }
}
function submissionTable(rows) {
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
  for (const label of [
    "提交编号",
    "用户",
    "题目",
    "语言",
    "评测结果",
    "洛谷记录",
    "提交时间",
  ]) {
    const th = el("th", label);
    th.scope = "col";
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    for (const value of [
      `#${row.id}`,
      row.username,
      `#${row.problem_id}`,
      row.language === "python3" ? "Python 3" : row.language,
    ])
      tr.append(el("td", value));
    const status = el("td");
    status.append(statusBadge(row.status));
    if (row.remote_submission_id) status.append(el("span", "洛谷浏览器同步", "remote-result-source"));
    const remote = el("td");
    if (row.remote_submission_id) {
      const link = el("a", `#${row.remote_submission_id}`, "text-button");
      link.href = `https://www.luogu.com.cn/record/${encodeURIComponent(row.remote_submission_id)}`;
      link.target = "_blank"; link.rel = "noopener noreferrer"; remote.append(link);
    } else remote.textContent = "—";
    const statusHint = [
      row.remote_submission_id ? "洛谷状态由用户浏览器插件读取并同步，请打开洛谷记录复核。" : "",
      row.detail,
    ].filter(Boolean).join("\n");
    if (statusHint) {
      status.title = statusHint;
      status.setAttribute("aria-label", `${row.status}：${statusHint}`);
    }
    tr.append(status, remote, el("td", dateTime(row.created)));
    body.append(tr);
  }
  table.append(caption, head, body);
  wrap.append(table);
  panel.append(wrap);
  return panel;
}
export async function refreshSubmissions() {
  const rows = await api(contestPath("/submissions"));
  const target = $("submissionContent");
  const summary = el("div", "", "submission-summary");
  for (const [name, value] of [
    ["累计提交", rows.length],
    ["通过", rows.filter((r) => r.status === "Accepted").length],
    ["评测中", rows.filter((r) => ["Waiting for browser extension", "Submitted", "Judging"].includes(r.status)).length],
  ]) {
    const chip = el("div", "", "summary-chip");
    chip.append(el("span", name), el("strong", value));
    summary.append(chip);
  }
  target.replaceChildren(summary, submissionTable(rows));
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
  const body = { title: $("contestTitle").value.trim(), starts, ends };
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
  editingContestId = contest.id;
  editingContestJudgeMode = contest.judge_mode;
  $("contestTitle").value = contest.title;
  $("starts").value = dateTimeInput(contest.starts);
  $("ends").value = dateTimeInput(contest.ends);
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
      selectedLuoguProblems.push({ ...problem, remote_problem_id: problem.problem_id, tests: [] });
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
    statement.innerHTML = problem.statement_html || problem.statement;
    detail.append(el("summary", "查看自动导入的题面与样例"), statement, samples);
    detail.addEventListener("toggle", () => { if (detail.open) void renderProblemMath(statement); });
    item.append(heading, detail); list.append(item);
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
