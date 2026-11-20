import assert from "node:assert/strict";
import test from "node:test";
import { normalizeSubmissionPage, refreshContestProblemStats } from "../app/static/contest-model.mjs";

test("refreshes cached contest problem counts after submissions", () => {
  const overview = {
    id: 7,
    title: "模拟赛",
    problems: [{ id: 12, title: "A题", attempt_count: 0, accepted_count: 0 }],
  };
  const refreshed = refreshContestProblemStats(overview, {
    id: 7,
    problem_count: 1,
    problems: [{ id: 12, title: "A题", attempt_count: 3, accepted_count: 1 }],
  });

  assert.deepEqual(refreshed.problems[0], {
    id: 12,
    title: "A题",
    attempt_count: 3,
    accepted_count: 1,
  });
  assert.equal(refreshed.title, "模拟赛");
});

test("does not refresh a different contest from stale async responses", () => {
  const overview = { id: 8, problems: [{ id: 22, attempt_count: 0 }] };
  assert.equal(refreshContestProblemStats(overview, { id: 7, problems: [] }), overview);
});

test("normalizes legacy submission arrays for the current table and pagination controls", () => {
  const result = normalizeSubmissionPage([
    { id: 4, status: "Accepted" },
    { id: 3, status: "Judging" },
  ]);

  assert.deepEqual(result, {
    items: [{ id: 4, status: "Accepted" }, { id: 3, status: "Judging" }],
    total: 2,
    page: 1,
    page_size: 2,
    pages: 1,
    stats: { accepted: 1, judging: 1 },
  });
});

test("preserves valid pagination metadata and rejects an unknown submission response", () => {
  const result = normalizeSubmissionPage({
    items: [{ id: 5, status: "Wrong Answer" }],
    total: 11,
    page: 2,
    page_size: 10,
    pages: 2,
    stats: { accepted: 1, judging: 0 },
  });
  assert.equal(result.page, 2);
  assert.equal(result.pages, 2);
  assert.deepEqual(result.stats, { accepted: 1, judging: 0 });
  assert.throws(() => normalizeSubmissionPage({ data: [] }), /提交记录服务返回了无法识别的数据/);
});
