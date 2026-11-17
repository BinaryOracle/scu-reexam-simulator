/** Shared practice leaderboards for ordinary student accounts. */
import { api } from "./api.js?v=20261114-ui-v17";
import { el, button, emptyState } from "./ui.js?v=20261114-ui-v17";

const METRICS = [
  ["checkins", "打卡天数", "累计完成训练打卡"],
  ["training_questions", "抽题训练", "累计完成抽题数量"],
  ["coding_solved", "上机通过", "通过的不同题目"],
];

/**
 * Create the entry button used by practice modules.
 * @param {() => void} open - Opens the leaderboard view in the caller.
 * @param {string} className - Additional button classes.
 * @returns {HTMLButtonElement}
 */
export function leaderboardButton(open, className = "button secondary") {
  const control = button("排行榜", open, className);
  control.setAttribute("aria-label", "查看练习排行榜");
  return control;
}

function metricTabs(active, select) {
  const tabs = el("div", "", "leaderboard-metric-tabs");
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "排行榜指标");
  for (const [key, label, description] of METRICS) {
    const tab = button(label, () => select(key), `leaderboard-metric-tab${active === key ? " selected" : ""}`);
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(active === key));
    tab.title = description;
    tabs.append(tab);
  }
  return tabs;
}

function renderRows(board, currentRank, root) {
  const list = el("div", "", "leaderboard-rows");
  list.setAttribute("role", "list");
  if (!board.length) {
    list.append(emptyState("还没有上榜记录", "完成一次打卡、抽题训练或上机题目后，就会出现在这里。", "◇"));
    return list;
  }
  for (const item of board) {
    const current = item.rank === currentRank;
    const row = el("div", "", `leaderboard-row${current ? " current" : ""}`);
    row.setAttribute("role", "listitem");
    row.dataset.username = item.username;
    if (current) row.setAttribute("aria-current", "true");
    const rank = el("span", item.rank <= 3 ? ["", "🥇", "🥈", "🥉"][item.rank] : String(item.rank).padStart(2, "0"), `leaderboard-rank rank-${item.rank}`);
    const person = el("div", "", "leaderboard-person");
    person.append(el("strong", item.username), current ? el("span", "你", "leaderboard-you") : null);
    const value = el("strong", item.value.toLocaleString("zh-CN"), "leaderboard-value");
    row.append(rank, person, value);
    list.append(row);
  }
  return list;
}

function renderData(root, payload, options) {
  let active = options.metric || "checkins";
  const panel = el("section", "", "leaderboard-panel");
  const heading = el("div", "", "leaderboard-heading");
  const headingText = el("div", "", "leaderboard-heading-text");
  headingText.append(el("span", "PRACTICE RANKING", "eyebrow"), el("h2", "练习排行榜"), el("p", "按累计数据统计，只展示普通用户。", "muted"));
  heading.append(headingText, options.onBack ? button("返回练习", options.onBack, "button quiet leaderboard-back") : null);
  const content = el("div", "", "leaderboard-content");
  const update = metric => {
    active = metric;
    const board = payload.boards[metric] || [];
    const currentRank = payload.me?.[metric] ?? null;
    const label = payload.metric_labels?.[metric] || METRICS.find(item => item[0] === metric)?.[1] || "排行榜";
    content.replaceChildren(
      metricTabs(active, update),
      el("div", `${label} · 共 ${board.length} 位用户`, "leaderboard-caption"),
      renderRows(board, currentRank, content),
    );
  };
  panel.append(heading, content);
  root.replaceChildren(panel);
  update(active);
}

/**
 * Load and mount the shared leaderboard panel.
 * @param {HTMLElement} root - Container to replace with the panel.
 * @param {{onBack?: () => void, metric?: string}} options - View options.
 * @returns {Promise<void>}
 */
export async function mountLeaderboard(root, options = {}) {
  root.replaceChildren(el("div", "正在加载排行榜…", "leaderboard-loading"));
  try {
    const payload = await api("/leaderboard");
    if (root.isConnected) renderData(root, payload, options);
  } catch (error) {
    if (!root.isConnected) return;
    const retry = button("重新加载", () => mountLeaderboard(root, options), "button secondary");
    root.replaceChildren(emptyState("排行榜暂时无法加载", error.message || "请检查网络连接后重试。", "◇"), retry);
  }
}
