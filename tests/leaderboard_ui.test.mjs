import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = name => readFile(new URL(`../app/static/${name}`, import.meta.url), "utf8");
const [leaderboard, training, coding, markup, leaderboardStyles] = await Promise.all([
  read("leaderboard.js"), read("training.js"), read("coding.js"), read("index.html"), read("leaderboard.css"),
]);

test("leaderboard presents the three ordinary-user metrics and current user", () => {
  assert.match(leaderboard, /api\("\/leaderboard"\)/);
  assert.match(leaderboard, /\["checkins", "打卡天数"/);
  assert.match(leaderboard, /\["training_questions", "抽题训练"/);
  assert.match(leaderboard, /\["coding_solved", "上机通过"/);
  assert.match(leaderboard, /row\.dataset\.username = item\.username/);
  assert.match(leaderboard, /row\.setAttribute\("aria-current", "true"\)/);
  assert.match(leaderboard, /重新加载/);
});

test("daily training and algorithm practice both expose the shared leaderboard", () => {
  assert.match(training, /from '\.\/leaderboard\.js\?v=20261117-leaderboard-v1'/);
  assert.match(training, /\['leaderboard','排行榜'\]/);
  assert.match(training, /mountLeaderboard\(root, \{ onBack:/);
  assert.match(coding, /from "\.\/leaderboard\.js\?v=20261117-leaderboard-v1"/);
  assert.match(coding, /\["leaderboard", "排行榜"\]/);
  assert.match(coding, /if \(mode === "leaderboard"\)/);
});

test("leaderboard styling is loaded globally and stays usable on narrow screens", () => {
  assert.match(markup, /leaderboard\.css\?v=20261117-leaderboard-v1/);
  assert.match(leaderboardStyles, /\.leaderboard-row\.current/);
  assert.match(leaderboardStyles, /@media \(max-width:700px\)/);
  assert.match(leaderboardStyles, /\.leaderboard-metric-tabs\{grid-template-columns:1fr/);
});
