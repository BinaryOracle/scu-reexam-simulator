import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../app/static/coding.js', import.meta.url), 'utf8');
const contestSource = readFileSync(new URL('../app/static/contest.js', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../app/static/app.js', import.meta.url), 'utf8');
const indexSource = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/static/coding.css', import.meta.url), 'utf8');

test('refreshes cached code-draft modules in the coding and contest workspaces', () => {
  assert.match(source, /code-drafts\.mjs\?v=20261121-drafts-v7/);
  assert.match(contestSource, /code-drafts\.mjs\?v=20261121-drafts-v7/);
  assert.match(source, /draft-compat\.mjs\?v=20261121-cache-compat-v2/);
  assert.match(contestSource, /draft-compat\.mjs\?v=20261121-cache-compat-v2/);
});

test('refreshes cached entry modules when the code-draft API changes', () => {
  assert.match(appSource, /contest\.js\?v=20261121-workspace-controls-v7/);
  assert.match(appSource, /coding\.js\?v=20261121-workspace-controls-v7/);
  assert.match(indexSource, /app\.js\?v=20261121-workspace-controls-v7/);
});

test('supports previously cached code-draft modules without a has method', () => {
  assert.match(source, /hasCodeDraft\(drafts, draftKey/);
  assert.match(contestSource, /hasCodeDraft\(codeDrafts, key/);
});

test('keeps the return-to-list action outside the collapsible statement pane', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /navigation\.append\(button\("← 返回题单"/);
  assert.match(render, /workspace\.append\(navigation, mobile, restoreBar, columns\)/);
  assert.doesNotMatch(render, /statementHead\.append\(button\("← 返回题单"/);
});

test('shows submission details only from the submission-record dialog', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /const records = el\("div", "", "coding-submission-panel coding-record-list"\)/);
  assert.match(render, /const submissionTab = button\("提交记录", \(\) => selectStatementView\("submissions"\)/);
  assert.doesNotMatch(render, /footer\.append\([^;]*result/);
  assert.doesNotMatch(render, /renderResult\(result,/);
  assert.doesNotMatch(source, /resultTargets/);
  assert.match(source, /row\.setAttribute\("aria-label", `查看提交 #\$\{record\.id\} 的评测详情`\)/);
  assert.match(source, /coding-submission-dialog/);
});

test('keeps the coding workspace focused on the problem and editor within the viewport', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /navigation\.append\(button\("← 返回题单"/);
  assert.doesNotMatch(render, /content\.append\(el\("h3", question\.title\)/);
  assert.match(render, /coding-statement-meta/);
  assert.match(styles, /\.coding-immersive \.coding-workspace\s*\{[^}]*height:\s*calc\(100dvh/s);
  assert.match(styles, /\.coding-workspace \.candidate-workspace\s*\{[^}]*flex:\s*1 1 0/s);
  assert.match(styles, /--statement-size:\s*\.43/);
});

test('initializes the narrow workspace on the selected statement pane', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /const columns = el\("div", "", "problem-columns candidate-workspace"\); columns\.dataset\.activePane = "statement"/);
  assert.match(render, /mobile\.children\[0\]\.classList\.add\("selected"\)/);
  assert.match(render, /columns\.dataset\.activePane = name/);
});

test('hides judge deployment details from students and disables unavailable sample judging', () => {
  assert.match(source, /本地运行暂不可用，请稍后再试或联系管理员。/);
  assert.match(source, /if \(!home\.judge\.available\) run\.disabled = true/);
  assert.doesNotMatch(source, /home\.judge\.notice/);
});

test('separates local runs from remote submissions and lets users edit test cases', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /\/coding\/questions\/\$\{question\.id\}\/run/);
  assert.match(render, /const submit = button\(`提交 \$\{platformLabel\} 评测 →`/);
  assert.match(render, /submit\.disabled = question\.judge_mode !== "luogu"/);
  assert.match(render, /添加测试用例/);
  assert.match(render, /coding-test-case-remove/);
  assert.doesNotMatch(render, /删除当前测试用例/);
  assert.match(render, /localStorage/);
  assert.match(render, /测试用例/);
  assert.match(render, /运行结果/);
  assert.doesNotMatch(render, /运行公开样例 →/);
  assert.match(render, /coding-test-case-group/);
  assert.match(render, /inputGroup\.append/);
  assert.match(render, /outputGroup\.append/);
});

test('keeps the shared editor expanded while book reference code remains collapsed', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderDiscussion('));
  assert.match(render, /书中原代码/);
  assert.match(render, /coding-book-code/);
  assert.match(render, /const editor = el\("section", "", "panel editor-panel"\)/);
  assert.match(render, /editor\.append\(editorHead, area, footer\)/);
  assert.doesNotMatch(render, /coding-editor-foldout|coding-editor-summary|coding-editor-content/);
  assert.match(render, /提交 \$\{platformLabel\} 评测/);
  assert.doesNotMatch(render, /coding-book-code[^;]*\.open\s*=\s*true/s);
});

test('edits book reference code through the shared Markdown editor', () => {
  const form = readFileSync(new URL('../app/static/coding-form.mjs', import.meta.url), 'utf8');
  assert.match(form, /书中原代码（Markdown）/);
  assert.match(form, /referenceMarkdownEditor\s*=\s*questionMarkdownEditor/);
  assert.match(form, /referenceMarkdownEditor\.dispose/);
});

test('explains that question order is scoped to a stage and zero inserts first', () => {
  const form = readFileSync(new URL('../app/static/coding-form.mjs', import.meta.url), 'utf8');
  assert.match(form, /阶段内顺序（0 最前）/);
  assert.match(form, /设置为 0 会插入当前阶段最前/);
});

test('lets users resize run input and output boxes without overflowing the results pane', () => {
  assert.match(styles, /\.coding-run-output pre\s*\{[^}]*resize:\s*both/s);
  assert.match(styles, /\.coding-run-output pre\s*\{[^}]*max-width:\s*100%/s);
  assert.match(styles, /\.coding-run-output pre\s*\{[^}]*min-height:\s*72px/s);
});

test('provides a persistent question discussion area with sorting, replies, likes, and pinning', () => {
  assert.match(source, /coding\/questions\/\$\{question\.id\}\/comments/);
  assert.match(source, /\/coding\/comments\/\$\{comment\.id\}\/like/);
  assert.match(source, /\/coding\/comments\/\$\{comment\.id\}\/pin/);
  assert.match(source, /评论排序/);
  assert.match(source, /回复/);
  assert.match(source, /coding-comment-composer-footer/);
  assert.match(source, /coding-comment-replies/);
  assert.match(styles, /\.coding-discussion/);
  assert.match(styles, /\.coding-comment-sort-option\.selected/);
  assert.match(styles, /\.coding-comment-replies\s*\{[^}]*border-left/s);
  assert.match(styles, /\.coding-test-case-fields\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/s);
});

test('constrains statement images and places case removal beside its tab', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /coding-test-case-remove/);
  assert.match(render, /删除测试用例/);
  assert.doesNotMatch(render, /删除当前测试用例/);
  assert.match(styles, /\.coding-workspace \.workspace-statement-content img\s*\{[^}]*max-width:\s*min\(100%,\s*720px\)/s);
  assert.match(styles, /max-height:\s*360px/);
  assert.match(styles, /\.coding-test-case-remove/);
});

test('presents comments as a LeetCode-style discussion stream with compact sorting', () => {
  const discussion = source.slice(source.indexOf('function renderDiscussion('), source.indexOf('function renderResult('));
  assert.match(discussion, /coding-comment-avatar/);
  assert.match(discussion, /coding-comment-sort/);
  assert.match(discussion, /最新发布/);
  assert.match(styles, /\.coding-comment-avatar/);
  assert.match(styles, /\.coding-comment-sort/);
});

test('keeps question discussion beside the statement in the left workspace pane', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderDiscussion('));
  assert.match(render, /statementTabs\.append\(statementTab, discussionTab, submissionTab\)/);
  assert.match(render, /statement\.append\(statementHead, statementTabs, content, discussion, records\)/);
  assert.match(render, /const bottomPanes = \[\["测试用例", casePanel\], \["运行结果", results\]\]/);
  assert.doesNotMatch(render, /\["提交记录", records\]/);
  assert.match(render, /root\.replaceChildren\(workspace\)/);
  assert.doesNotMatch(render, /root\.replaceChildren\(workspace, discussion\)/);
  assert.match(styles, /\.coding-statement-tabs/);
  assert.match(styles, /\.coding-statement-discussion\s*\{[^}]*flex:\s*1/s);
  assert.match(styles, /\.coding-submission-panel\s*\{[^}]*flex:\s*1 1 0;[^}]*overflow-y:\s*auto/s);
});

test('defaults voucher export to unredeemed codes and resets to that safe filter', () => {
  const markup = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');
  const credits = readFileSync(new URL('../app/static/credits.js', import.meta.url), 'utf8');
  assert.match(markup, /<select id="voucherStatus"><option value="unused" selected>未兑换<\/option>/);
  assert.match(credits, /\$\("voucherStatus"\)\.value = "unused"/);
  assert.doesNotMatch(credits, /\$\("voucherStatus"\)\.value = "all"/);
});

test('offers progress and favorite views and a persistent favorite action', () => {
  assert.match(source, /\["solved", "已完成"\]/);
  assert.match(source, /\["failed", "尝试未通过"\]/);
  assert.match(source, /\["favorites", "收藏"\]/);
  assert.match(source, /\/coding\/questions\/\$\{question\.id\}\/favorite/);
  assert.match(styles, /\.coding-mode-tabs\s*\{[^}]*overflow-x:\s*auto/s);
  assert.match(styles, /\.coding-workspace-toolbar/);
});

test('numbers the combined question list consecutively across pages instead of using editable position', () => {
  assert.match(source, /questionRow\(item, start \+ index \+ 1\)/);
  assert.match(source, /String\(ordinal\)\.padStart/);
  assert.doesNotMatch(source, /question\.position \+ 1/);
});

test('renders an embedded empty question list without a second card frame', () => {
  assert.match(styles, /\.coding-question-list\s*>\s*\.empty-state\s*\{[^}]*border:\s*0/);
  assert.match(styles, /\.coding-question-list\s*>\s*\.empty-state\s*\{[^}]*box-shadow:\s*none/);
  assert.match(styles, /\.coding-question-list\s*>\s*\.empty-state\s*\{[^}]*background:\s*transparent/);
});

 test('keeps local testing available and places layout reset in the workspace toolbar', () => {
  assert.doesNotMatch(source, /const localRun = platform\?\.standardInput/);
  assert.match(source, /footer\.append\(run\)/);
  assert.match(source, /navigation\.append\(button\("← 返回题单".*reset\)/s);
  assert.doesNotMatch(source, /editorActions\.append\(editorControl, reset, closeEditor\)/);
  assert.match(source, /editorActions\.append\(editorControl, closeEditor\)/);
  assert.match(source, /headingTools\.append\(language, editorActions\)/);
  assert.match(source, /testCaseFormat\(/);
});

test('keeps contest layout controls and bridge tools inside the code workspace', () => {
  assert.doesNotMatch(contestSource, /headerActions\.prepend\(resetLayout\)/);
  assert.match(contestSource, /headerRight\.append\(resetLayout\)/);
  assert.match(contestSource, /const editor = renderEditor\(problem, resetLayout\)/);
  assert.match(contestSource, /function renderEditor\(problem, resetLayout\)/);
  assert.match(contestSource, /headingTools\.append\(language\)/);
  assert.doesNotMatch(contestSource, /headingTools\.append\(language, copyCodeButton/);
  assert.doesNotMatch(contestSource, /editorActions\.append\(editorControl, resetLayout, closeEditor\)/);
  assert.match(contestSource, /editorActions\.append\(editorControl, closeEditor\)/);
  assert.match(contestSource, /contest-bridge-tools/);
  assert.match(contestSource, /coding-tutorial-button/);
});
