import { api, state } from "./api.js?v=20261114-ui-v17";
import { el, button, emptyState } from "./ui.js?v=20261114-ui-v18";

let activeDialog = null;

/** Dismiss contest records when changing pages, contests or signed-in accounts. */
export function closeContestRecords() {
  activeDialog?.close();
}

/** Open a paginated administrative record list scoped to one contest and optional drill-down filters. */
export function openContestRecords(filters, renderTable) {
  closeContestRecords();
  if (!state.adminMode || !state.user?.is_admin) return;
  const userId = state.user.id;
  const prior = document.activeElement;
  const dialog = el("dialog", "", "account-dialog contest-records-dialog");
  activeDialog = dialog;
  const title = filters.userName ? `${filters.userName} 的提交记录` : filters.problemTitle ? "题目提交记录" : "本场全部提交";
  dialog.setAttribute("aria-label", title);
  const heading = el("div", "", "dialog-header");
  const identity = el("div");
  identity.append(el("span", "比赛提交记录", "eyebrow"), el("h2", title));
  const close = button("×", () => dialog.close(), "icon-button");
  close.setAttribute("aria-label", "关闭提交记录");
  heading.append(identity, close);
  const subtitle = el("p", [filters.contestTitle, filters.problemTitle, filters.acceptedOnly ? "仅已通过" : "全部结果"].filter(Boolean).join(" · "), "contest-records-subtitle");
  const toolbar = el("div", "", "contest-records-toolbar");
  const summary = el("p", "正在加载…", "contest-records-summary"); summary.setAttribute("role", "status");
  let currentPage = 1;
  const refresh = button("刷新记录", () => load(currentPage), "button secondary");
  toolbar.append(summary, refresh);
  const body = el("div", "", "contest-records-body");
  const footer = el("nav", "", "dialog-footer submission-pagination");
  footer.setAttribute("aria-label", "比赛提交记录分页");
  dialog.append(heading, subtitle, toolbar, body, footer);
  let revision = 0;
  const valid = turn => dialog.open && dialog.isConnected && revision === turn && state.user?.id === userId && state.user?.is_admin && state.adminMode;
  dialog.addEventListener("close", () => {
    revision++;
    dialog.remove();
    if (activeDialog === dialog) activeDialog = null;
    if (prior?.isConnected) prior.focus();
  }, { once: true });
  document.body.append(dialog);
  dialog.showModal();
  void load(1);

  async function load(page) {
    const turn = ++revision;
    currentPage = page;
    const params = new URLSearchParams({ contest_id: filters.contestId, page, page_size: 10 });
    if (filters.userId != null) params.set("user_id", filters.userId);
    if (filters.problemId != null) params.set("problem_id", filters.problemId);
    if (filters.acceptedOnly) params.set("status", "Accepted");
    if (filters.participantsOnly) params.set("participants_only", "true");
    body.setAttribute("aria-busy", "true");
    body.replaceChildren(el("p", "正在读取提交记录…", "muted"));
    summary.textContent = "正在加载…";
    footer.replaceChildren();
    try {
      const result = await api(`/admin/submissions?${params}`);
      if (!valid(turn)) return;
      if (page > Math.max(1, result.pages)) { await load(Math.max(1, result.pages)); return; }
      summary.textContent = `共 ${result.total} 条 · 通过 ${result.stats.accepted} 条 · 评测中 ${result.stats.judging} 条`;
      body.replaceChildren(result.items.length
        ? renderTable(result.items, { groupedUser: filters.userId != null })
        : emptyState(filters.acceptedOnly ? "暂无通过记录" : "暂无提交记录", "当前筛选范围内还没有对应记录。", "▤"));
      const previous = button("← 上一页", () => load(page - 1), "button secondary");
      const next = button("下一页 →", () => load(page + 1), "button secondary");
      previous.disabled = page <= 1;
      next.disabled = page >= result.pages;
      footer.append(previous, el("span", `第 ${page} / ${Math.max(1, result.pages)} 页`), next);
      body.scrollTo({ top: 0 });
    } catch (error) {
      if (!valid(turn)) return;
      summary.textContent = "记录暂时无法加载";
      body.replaceChildren(el("p", error.message, "form-error"), button("重新加载", () => load(page), "button secondary"));
    } finally {
      if (valid(turn)) body.removeAttribute("aria-busy");
    }
  }
}
