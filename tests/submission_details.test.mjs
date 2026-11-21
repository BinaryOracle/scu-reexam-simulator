import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/submission-details.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
class Node {
  constructor(tag, text = '', className = '') { Object.assign(this, { tag, textContent: text, className, children: [], dataset: {} }); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  find(predicate) { return predicate(this) ? this : this.children.map(n => n.find(predicate)).find(Boolean); }
}
function fixture() {
  const context = vm.createContext({ el: (...args) => new Node(...args),
    statusBadge: status => new Node('span', status),
  });
  vm.runInContext(source, context);
  return context;
}

test('test point cards preserve unparsed diagnostics and the exact submitted source as text', () => {
  const f = fixture(); const body = new Node('div');
  const code = '#include <iostream>\nint main() { return 0; }';
  f.renderSubmissionDetails(body, { id: 8, language: 'cpp11', status: 'Wrong Answer', source: code,
    detail: '通过测试用例数：1 / 2\n测试点 #1：AC\n测试点 #2：WA\n另有信息 <script>alert(1)</script>' });
  assert.equal(body.find(n => n.tag === 'code').textContent, code);
  assert.equal(body.find(n => n.className === 'submission-case-grid').children.length, 2);
  assert.equal(body.find(n => n.className === 'submission-pass-count').textContent, '1 / 2');
  assert.ok(body.find(n => n.textContent === '另有信息 <script>alert(1)</script>'));
});

test('compile errors without testcase details stay fully readable without an invented count', () => {
  const f = fixture(); const body = new Node('div');
  f.renderSubmissionDetails(body, { id: 9, status: 'Compile Error', detail: 'main.cpp:2: error: expected ;' });
  assert.ok(body.find(n => n.textContent === 'main.cpp:2: error: expected ;'));
  assert.equal(body.find(n => n.className === 'submission-pass-count'), undefined);
});

test('remote submission details use a platform-neutral submission label', () => {
  const f = fixture(); const body = new Node('div');
  f.renderSubmissionDetails(body, { id: 10, remote_platform: 'leetcode', remote_submission_id: '98765', status: 'Accepted' });
  assert.ok(body.find(n => n.textContent === '评测平台提交编号'));
  assert.ok(body.find(n => n.textContent === '98765'));
});
