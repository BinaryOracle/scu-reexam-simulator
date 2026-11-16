import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const source = readFileSync(new URL('../app/static/coding.js', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/static/coding.css', import.meta.url), 'utf8');

test('keeps the return-to-list action outside the collapsible statement pane', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /navigation\.append\(button\("← 返回题单"/);
  assert.match(render, /workspace\.append\(navigation, mobile, restoreBar, columns\)/);
  assert.doesNotMatch(render, /statementHead\.append\(button\("← 返回题单"/);
});

test('places submit feedback in the submission tab and consumes errors inline', () => {
  const render = source.slice(source.indexOf('function renderWorkspace('), source.indexOf('function renderResult('));
  assert.match(render, /const records = el\("div", "", "editor-bottom-content coding-submission-panel"\); records\.hidden = true; records\.append\(result\)/);
  assert.match(render, /activateRecords\(\);/);
  assert.doesNotMatch(render, /footer\.append\([^;]*result/);
  assert.doesNotMatch(render, /await loadRecords\(question\.id, request, userId\);\s*throw error;/);
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
  assert.match(render, /const submit = button\("提交洛谷评测 →"/);
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
  assert.match(render, /statementTabs\.append\(statementTab, discussionTab\)/);
  assert.match(render, /statement\.append\(statementHead, statementTabs, content, discussion\)/);
  assert.match(render, /root\.replaceChildren\(workspace\)/);
  assert.doesNotMatch(render, /root\.replaceChildren\(workspace, discussion\)/);
  assert.match(styles, /\.coding-statement-tabs/);
  assert.match(styles, /\.coding-statement-discussion\s*\{[^}]*flex:\s*1/s);
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
