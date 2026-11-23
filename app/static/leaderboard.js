/** Weekly practice leaderboards for ordinary student accounts. */
import { api, state } from "./api.js?v=20261122-session-guard-v1";
import { el, button, emptyState } from "./ui.js?v=20261114-ui-v17";

const BOARD_DEFS = {
  training_checkins: { short: "打卡天数", label: "每日训练打卡", description: "完成每日训练并成功打卡的天数" },
  training_questions: { short: "抽题数量", label: "每日训练抽题", description: "每日训练中完成的抽题数量" },
  coding_checkins: { short: "打卡天数", label: "算法带刷打卡", description: "算法带刷每日题完成并打卡的天数" },
  coding_solved: { short: "通过题数", label: "算法带刷通过", description: "算法带刷中通过的不同题目数量" },
};
const SCOPES = {
  training: ["training_checkins", "training_questions"],
  coding: ["coding_checkins", "coding_solved"],
  all: Object.keys(BOARD_DEFS),
};
const mountRequests = new WeakMap();

/** Create the entry button used by practice modules. */
export function leaderboardButton(open, className = "button secondary") {
  const control = button("排行榜", open, className);
  control.setAttribute("aria-label", "查看练习排行榜");
  return control;
}

function boardData(payload, key) {
  const normalized = payload.boards[key];
  const username = payload?.username || payload?.user?.username || state.user?.username;
  const rank = username ? normalized.find(item => item.username === username)?.rank : null;
  return { definition: BOARD_DEFS[key], rows: normalized, currentRank: rank || payload?.me?.[key] || null };
}

function renderRows(board, currentRank) {
  const list = el("div", "", "leaderboard-rows");
  list.setAttribute("role", "list");
  list.setAttribute("aria-label", "排行榜排名，可滚动查看更多");
  list.tabIndex = 0;
  if (!board.length) {
    list.append(emptyState("还没有上榜记录", "完成一次练习后，这里会显示你的排名。", "◇"));
    return list;
  }
  for (const item of board) {
    const current = item.rank === currentRank;
    const row = el("div", "", `leaderboard-row${current ? " current" : ""}${item.rank <= 3 ? " podium-row" : ""}`);
    row.setAttribute("role", "listitem");
    row.dataset.username = item.username;
    if (current) row.setAttribute("aria-current", "true");
    const rank = el("span", String(item.rank).padStart(2, "0"), `leaderboard-rank rank-${item.rank}`);
    const person = el("div", "", "leaderboard-person");
    person.append(el("strong", item.username));
    if (current) person.append(el("span", "你", "leaderboard-you"));
    row.append(rank, person, el("strong", item.value.toLocaleString("zh-CN"), "leaderboard-value"));
    list.append(row);
  }
  return list;
}

function renderBoardCard(payload, key) {
  const { definition, rows, currentRank } = boardData(payload, key);
  const card = el("article", "", `leaderboard-card leaderboard-card-${key}`);
  const head = el("header", "", "leaderboard-card-heading");
  const title = el("div", "", "leaderboard-card-title");
  title.append(el("span", definition.short, "eyebrow"), el("h3", definition.label), el("p", definition.description, "muted"));
  head.append(title, el("span", `${rows.length} 人`, "leaderboard-count"));
  card.append(head, renderRows(rows, currentRank));
  return card;
}

function renderData(root, payload, options) {
  const scope = options.scope || "all";
  const keys = SCOPES[scope] || SCOPES.all;
  const panel = el("section", "", "leaderboard-panel");
  const heading = el("div", "", "leaderboard-heading");
  const headingText = el("div", "", "leaderboard-heading-text");
  const title = scope === "training" ? "每日训练排行榜" : scope === "coding" ? "算法带刷排行榜" : "练习排行榜";
  headingText.append(el("span", "PRACTICE RANKING", "eyebrow"), el("h2", title), el("p", `每周六 00:00（北京时间）结算，本周前三名分别获得 ${payload.rewards[0]}、${payload.rewards[1]}、${payload.rewards[2]} 积分。`, "muted"));
  heading.append(headingText);
  if (options.onBack) heading.append(button("返回练习", options.onBack, "button quiet leaderboard-back"));
  const period = el("div", "", "leaderboard-period");
  period.append(el("span", "本周榜单", "leaderboard-period-label"), el("span", payload?.period?.label || "每周六 00:00 开始新一周", "muted"));
  const rewards = el("div", "", "leaderboard-rewards");
  for (const [index, credits] of payload.rewards.entries()) {
    const rank = index + 1;
    const reward = el("span", "", `leaderboard-reward reward-${rank}`);
    reward.append(el("b", `第 ${rank} 名`), el("span", `+${credits} 积分`));
    rewards.append(reward);
  }
  const grid = el("div", "", "leaderboard-grid");
  for (const key of keys) grid.append(renderBoardCard(payload, key));
  panel.append(heading, period, rewards, grid);
  root.replaceChildren(panel);
}

/** Load and mount independent leaderboard cards. */
export async function mountLeaderboard(root, options = {}) {
  const requestId = (mountRequests.get(root) || 0) + 1;
  mountRequests.set(root, requestId);
  const scope = SCOPES[options.scope] ? options.scope : "training";
  root.replaceChildren(el("div", "正在加载排行榜…", "leaderboard-loading"));
  try {
    const payload = await api(`/leaderboard?scope=${scope}`);
    if (mountRequests.get(root) !== requestId) return;
    const keys = SCOPES[scope];
    const valid = payload && typeof payload.boards === "object" && keys.every(key =>
      Array.isArray(payload.boards[key]) && payload.boards[key].every(item =>
        typeof item.username === "string" && Number.isInteger(item.rank) && item.rank > 0 &&
        Number.isFinite(item.value) && item.value >= 0));
    if (!valid) throw new Error("排行榜数据暂未更新，请刷新后重试。若问题持续，请联系管理员更新服务。");
    if (root.isConnected) renderData(root, payload, options);
  } catch (error) {
    if (!root.isConnected || mountRequests.get(root) !== requestId) return;
    const description = error.status === 401 ? "登录状态已过期，请重新登录后查看排行榜。"
      : error.status === 404 ? "当前服务尚未加载排行榜接口，请联系管理员重启或更新服务。"
        : error.message || "请检查网络连接后重试。";
    const message = emptyState("排行榜暂时无法加载", description, "◇");
    const hint = el("p", "你的训练记录不会受到影响，可以返回练习后稍后重试。", "leaderboard-error-hint");
    const retry = button("重新加载", () => mountLeaderboard(root, options), "button secondary");
    retry.setAttribute("aria-label", "重新加载排行榜");
    if (options.onBack) {
      const back = button("返回练习", options.onBack, "button quiet leaderboard-back");
      root.replaceChildren(message, hint, retry, back);
    } else {
      root.replaceChildren(message, hint, retry);
    }
  }
}
