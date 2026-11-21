import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const sharedStyles = readFileSync(new URL('../app/static/style.css', import.meta.url), 'utf8');
const codingStyles = readFileSync(new URL('../app/static/coding.css', import.meta.url), 'utf8');
const trainingStyles = readFileSync(new URL('../app/static/training.css', import.meta.url), 'utf8');
const index = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');

test('embedded empty states do not draw a nested card frame', () => {
  assert.match(sharedStyles, /\.panel\s*>\s*\.empty-state[\s\S]*?border:\s*0/);
  assert.match(sharedStyles, /\.leaderboard-rows\s*>\s*\.empty-state[\s\S]*?box-shadow:\s*none/);
  assert.match(sharedStyles, /#voucherList\s*>\s*\.empty-state[\s\S]*?background:\s*transparent/);
  assert.match(sharedStyles, /#pointsHistory\s*>\s*\.empty-state/);
  assert.match(sharedStyles, /#redemptionHistory\s*>\s*\.empty-state/);
  assert.match(sharedStyles, /\.learning-list\s*>\s*\.empty-state[\s\S]*?border:\s*0/);
  assert.match(trainingStyles, /\.learning-list\s*>\.empty-state\s*\{[^}]*min-height:\s*170px/);
});

test('the coding question list keeps a single outer frame on empty pages', () => {
  const rule = codingStyles.match(/\.coding-question-list\s*>\s*\.empty-state\s*\{[^}]+\}/)?.[0] || '';
  assert.match(rule, /border:\s*0/);
  assert.match(rule, /box-shadow:\s*none/);
  assert.match(rule, /background:\s*transparent/);
  assert.match(rule, /min-height:\s*250px/);
});

test('bumps static stylesheet versions so browsers receive the layout fix', () => {
  assert.match(index, /style\.css\?v=20261121-empty-state-v1/);
  assert.match(index, /coding\.css\?v=20261121-local-cases-v2/);
  assert.match(index, /training\.css\?v=20261121-empty-state-v2/);
});
