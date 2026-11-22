import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../app/static/app.js", import.meta.url), "utf8");
const contestSource = await readFile(new URL("../app/static/contest.js", import.meta.url), "utf8");
const htmlSource = await readFile(new URL("../app/static/index.html", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");
const trainingSource = await readFile(new URL("../app/static/training.js", import.meta.url), "utf8");
const homeSource = await readFile(new URL("../app/static/home.js", import.meta.url), "utf8");
const interviewSource = await readFile(new URL("../app/static/interview.js", import.meta.url), "utf8");
const uiSource = await readFile(new URL("../app/static/ui.js", import.meta.url), "utf8");

test("restores the active app view from browser history and URL", () => {
  assert.match(appSource, /window\.addEventListener\(["']popstate["']/);
  assert.match(appSource, /readAppRoute/);
  assert.match(appSource, /writeAppViewRoute/);
});

test("restores the selected contest workspace after reload", () => {
  assert.match(contestSource, /restoreContestRoute/);
  assert.match(contestSource, /writeAppRoute/);
});

test("persists the Luogu account and rechecks the extension after reload", () => {
  assert.match(contestSource, /readLuoguConnection/);
  assert.match(contestSource, /writeLuoguConnection/);
  assert.match(contestSource, /refreshLuoguBridgeConnection/);
});

test("removes the standalone submission-history page from the user workspace", () => {
  assert.doesNotMatch(htmlSource, /class="nav-item submission-nav-item" data-view="submissions"/);
  assert.doesNotMatch(htmlSource, /<section id="submissions"/);
  assert.doesNotMatch(appSource, /submissions: \{\s*label: "提交记录"/);
  assert.doesNotMatch(appSource, /refreshSubmissions/);
});

test("does not flash the login screen while restoring an authenticated session", () => {
  const head = htmlSource.slice(0, htmlSource.indexOf("</head>"));
  assert.match(head, /sessionStorage\.getItem\(["']token["']\)/);
  assert.match(head, /session-restoring/);
  assert.match(styleSource, /session-restoring[^\n]*#login/);
  assert.match(appSource, /session-restoring/);
});

test("releases the restore screen after authentication and bounds session validation", () => {
  const restore = appSource.slice(appSource.indexOf("async function enterWorkspace()"), appSource.indexOf("function configureShell()"));
  assert.match(restore, /setTimeout\(\(\) => controller\.abort\(\), 15000\)/);
  assert.match(restore, /api\("\/me", \{ signal: controller\.signal \}\)/);
  assert.match(restore, /classList\.remove\("session-restoring"\)[\s\S]*?await show\(route[\s\S]*?catch \(error\) \{[\s\S]*?首屏内容加载失败/);
  assert.match(restore, /authenticatedUser: state\.user/);
});

test("contest list actions are hidden in contest details and the workspace", () => {
  const overviewRenderer = contestSource.slice(contestSource.indexOf("function renderContestOverview()"), contestSource.indexOf("function showContestRanking()"));
  const listRenderer = contestSource.slice(contestSource.indexOf("function renderContestList()"), contestSource.indexOf("$(\"contestSearch\").addEventListener"));
  assert.match(listRenderer, /\$\("problemList"\)\.hidden = true/);
  assert.match(listRenderer, /contestNavigationRevision\+\+/);
  assert.match(contestSource, /function renderContestList\(\)[\s\S]*?\$\("managementTools"\)\.hidden = !managementMode\(\)/);
  assert.match(contestSource, /async function openContest\([\s\S]*?\$\("managementTools"\)\.hidden = true/);
  assert.match(contestSource, /if \(navigationRevision !== contestNavigationRevision\) return/);
  assert.match(overviewRenderer, /\$\("contestList"\)\.hidden = true/);
  assert.match(overviewRenderer, /\$\("contestListToolbar"\)\.hidden = true/);
  assert.match(overviewRenderer, /\$\("contestPagination"\)\.hidden = true/);
  assert.match(contestSource, /function renderWorkspace\([\s\S]*?\$\("managementTools"\)\.hidden = true/);
  assert.match(contestSource, /async function openContest\([\s\S]*?\$\("refreshContests"\)\.hidden = true/);
});

test("training sessions remove list-level creation and navigation controls", () => {
  assert.match(trainingSource, /head\.hidden = Boolean\(session\)/);
  assert.match(trainingSource, /tabs\.hidden = Boolean\(session\)/);
});

test("interview detail hides the record list heading and refresh control", () => {
  assert.match(interviewSource, /function renderInterview\(\)[\s\S]*?\$\("refreshInterviews"\)\.parentElement\.hidden = true/);
  assert.match(interviewSource, /function renderInterview\(\)[\s\S]*?\$\("interviewListTitle"\)\.hidden = true/);
});

test("announcement editor hides list-level create and filters", () => {
  assert.match(homeSource, /function editNotice\([\s\S]*?if\(heading\)heading\.hidden=true;[\s\S]*?if\(toolbar\)toolbar\.hidden=true;[\s\S]*?if\(list\)list\.hidden=true;/);
});

test("submission detail hides Luogu record links from regular users", () => {
  assert.match(contestSource, /if \(managementMode\(\)\) \{\s*const remote = el\("td"\)/);
  assert.match(contestSource, /if \(managementMode\(\) && item\.remote_submission_id\)/);
  assert.match(contestSource, /item\.detail \|\| \(item\.status === "Accepted" \? "全部测试用例通过。" : item\.status\)/);
});

test("submission states show pending Luogu work as evaluating", () => {
  assert.match(uiSource, /"Waiting for browser extension": \["评测中", "blue"\]/);
  assert.match(uiSource, /Submitted: \["评测中", "blue"\]/);
});
