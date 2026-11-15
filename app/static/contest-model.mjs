/** Merge fresh public problem counters into the matching cached contest view. */
export function refreshContestProblemStats(overview, stats) {
  if (overview?.id !== stats?.id) return overview;
  return {
    ...overview,
    problem_count: stats.problem_count,
    problems: stats.problems,
  };
}

/** Reveal source problem IDs to participants only after their contest ends. */
export function canRevealLuoguSource(contest, now = Date.now() / 1000, isAdmin = false) {
  return isAdmin || now > contest.ends;
}

/** Normalize paginated and legacy submission responses before rendering. */
export function normalizeSubmissionPage(response) {
  const countStatuses = (items) => ({
    accepted: items.filter(item => item.status === "Accepted").length,
    judging: items.filter(item => ["Waiting for browser extension", "Submitted", "Judging"].includes(item.status)).length,
  });
  if (Array.isArray(response)) {
    return {
      items: response,
      total: response.length,
      page: 1,
      page_size: Math.max(1, response.length),
      pages: 1,
      stats: countStatuses(response),
    };
  }
  if (!response || !Array.isArray(response.items)) {
    throw new Error("提交记录服务返回了无法识别的数据。请刷新页面；问题持续时联系管理员检查服务版本。");
  }
  const total = Number.isInteger(response.total) && response.total >= 0 ? response.total : response.items.length;
  const page = Number.isInteger(response.page) && response.page > 0 ? response.page : 1;
  const pageSize = Number.isInteger(response.page_size) && response.page_size > 0
    ? response.page_size
    : Math.max(1, response.items.length);
  const pages = Number.isInteger(response.pages) && response.pages >= 0
    ? response.pages
    : Math.ceil(total / pageSize);
  const stats = response.stats && typeof response.stats === "object"
    ? {
      accepted: Number.isInteger(response.stats.accepted) ? response.stats.accepted : 0,
      judging: Number.isInteger(response.stats.judging) ? response.stats.judging : 0,
    }
    : countStatuses(response.items);
  return { ...response, items: response.items, total, page, page_size: pageSize, pages, stats };
}

/** Return user-facing copy for contest submission panel states. */
export function submissionPanelMessage(state) {
  if (state === "loading") return { title: "正在加载提交记录", description: "提交记录正在同步，请稍候。" };
  if (state === "empty") return { title: "还没有提交记录", description: "完成代码后提交评测，结果将在这里展示。" };
  if (state === "error") return { title: "提交记录暂时无法加载", description: "请检查网络连接后重试。" };
  throw new Error(`未知的提交记录面板状态：${state}`);
}
