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
  assert.match(source, /本站公开样例评测暂不可用，请稍后再试或联系管理员。/);
  assert.match(source, /if \(question\.judge_mode === "samples" && !home\.judge\.available\) submit\.disabled = true/);
  assert.doesNotMatch(source, /home\.judge\.notice/);
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
