import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source = readFileSync(new URL('../app/static/coding-form.mjs', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
function fixture(api = async () => [], { question = {}, importProblem } = {}) {
  class Element {
    constructor(tag, text = '', classes = '') {
      Object.assign(this, { tag, tagName: tag.toUpperCase(), textContent: text, className: classes, children: [], dataset: {}, listeners: {}, value: '', open: false, isConnected: true });
      this.classList = { add: name => { this.className += ` ${name}`; } };
    }
    append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
    after(node) { this.parent.append(node); }
    replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
    setAttribute(key, value) { this[key] = value; }
    addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
    async fire(type, extra = {}) { for (const listener of this.listeners[type] || []) await listener({ preventDefault() {}, target: this, ...extra }); }
    focus() { document.activeElement = this; }
    contains(node) { return this === node || this.children.some(child => child.contains(node)); }
    showModal() { this.open = true; }
    close() { this.open = false; this.fire('close'); }
    remove() { this.isConnected = false; }
    querySelector(selector) { return flatten(this).find(node => selector.startsWith('[name=') ? node.name === selector.match(/"([^"]+)"/)[1] : selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : node.tag === selector); }
  }
  const flatten = root => root.children.flatMap(child => [child, ...flatten(child)]);
  const document = { body: new Element('body'), activeElement: null };
  let pendingTimer; const calls = [], saved = [], notices = [];
  const context = vm.createContext({ document, crypto: { randomUUID: () => 'fixture' },
    setTimeout: callback => { pendingTimer = callback; return 1; }, clearTimeout: () => { pendingTimer = null; },
    el: (...args) => new Element(...args),
    button: (label, action, classes) => { const node = new Element('button', label, classes); node.action = action; return node; },
    notify: message => notices.push(message),
    api: async url => { calls.push(url); return api(url); },
    testCaseFormat: () => ({ hint: '用例格式', input: '[]', output: '[]' }),
    judgePlatform: id => ({ label: id === 'leetcode' ? 'LeetCode 中国区' : '洛谷', hint: '搜索题目' }),
    questionMarkdownEditor: input => ({ node: input, refresh() {}, dispose() {}, busy: false }),
  });
  vm.runInContext(source, context);
  const imported = { title: '两数之和', statement: '题面正文', remote_problem_id: 'two-sum', source_url: 'https://leetcode.cn/problems/two-sum/', remote_platform: 'leetcode', judge_mode: 'luogu', starter_codes: { cpp11: 'class Solution {};' }, source_info: { platform: 'leetcode', question_id: '1' }, samples: [{ input: '[2,7]', output: '[0,1]' }] };
  const imports = [];
  const dialog = context.editCodingQuestion({ question, stages: [{ id: 'base', title: '基础' }], save: data => saved.push(data), importProblem: async (platform, id) => { imports.push([platform, id]); return importProblem ? importProblem(platform, id) : imported; } });
  const field = name => flatten(dialog).find(node => node.name === name);
  return { dialog, field, calls, imports, imported, saved, notices, nodes: () => flatten(dialog), flush: async () => { const run = pendingTimer; pendingTimer = null; if (run) await run(); } };
}

test('offers sample, Luogu and LeetCode judging in one selector without separate import controls', () => {
  const f = fixture();
  const mode = f.field('judge_mode');
  assert.deepEqual(mode.children.map(node => node.value), ['samples', 'luogu', 'leetcode']);
  assert.equal(f.field('remote_platform'), undefined);
  assert.equal(f.field('remote_problem_id'), undefined);
  assert.ok(!f.nodes().some(node => ['搜索平台题目', '直接导入'].includes(node.textContent)));
});

test('searches from the title and imports the selected China problem before saving', async () => {
  const f = fixture(async () => [{ problem_id: 'two-sum', number: '1', title: '两数之和' }]);
  f.field('judge_mode').value = 'leetcode'; await f.field('judge_mode').fire('change');
  f.field('title').value = '两数'; await f.field('title').fire('input'); await f.flush();
  assert.equal(f.calls[0], '/coding/import/leetcode/suggestions?q=%E4%B8%A4%E6%95%B0');
  await f.nodes().find(node => node.className.includes('luogu-suggestion-option')).action();
  assert.deepEqual(f.imports, [['leetcode', 'two-sum']]);
  assert.equal(f.field('title').value, '两数之和');
  assert.equal(f.field('statement').value, '题面正文');
  await f.nodes().find(node => node.tag === 'form').fire('submit');
  assert.equal(f.saved[0].judge_mode, 'luogu');
  assert.equal(f.saved[0].remote_platform, 'leetcode');
  assert.equal(f.saved[0].remote_problem_id, 'two-sum');
  assert.equal(f.saved[0].starter_codes.cpp11, 'class Solution {};');
});

test('ignores late suggestions after switching platform and skips search for sample-only questions', async () => {
  let finish;
  const f = fixture(() => new Promise(resolve => { finish = resolve; }));
  f.field('title').value = 'local'; await f.field('title').fire('input'); await f.flush();
  assert.equal(f.calls.length, 0);
  f.field('judge_mode').value = 'luogu'; await f.field('judge_mode').fire('change');
  f.field('title').value = 'P1000'; await f.field('title').fire('input'); const pending = f.flush();
  f.field('judge_mode').value = 'leetcode'; await f.field('judge_mode').fire('change');
  finish([{ problem_id: 'P1000', title: '旧平台题目' }]); await pending;
  assert.equal(f.nodes().filter(node => node.className.includes('luogu-suggestion-option')).length, 0);
});


test('keeps an existing China platform binding when editing unrelated fields', async () => {
  const f = fixture(undefined, { question: { id: 21, title: '两数之和', statement: '原题面', judge_mode: 'luogu', remote_platform: 'leetcode', remote_problem_id: 'two-sum', version: 2 } });
  assert.equal(f.field('judge_mode').value, 'leetcode');
  await f.nodes().find(node => node.tag === 'form').fire('submit');
  assert.equal(f.saved[0].remote_problem_id, 'two-sum');
  assert.equal(f.saved[0].remote_platform, 'leetcode');
  assert.equal(f.saved[0].version, 2);
});

test('requires reselecting a remote problem after changing its title', async () => {
  const f = fixture(undefined, { question: { title: '旧题', statement: '原题面', judge_mode: 'luogu', remote_platform: 'luogu', remote_problem_id: 'P1000' } });
  f.field('title').value = '另一题'; await f.field('title').fire('input');
  await f.nodes().find(node => node.tag === 'form').fire('submit');
  assert.equal(f.saved.length, 0);
  assert.match(f.nodes().find(node => node.className === 'coding-form-error').textContent, /联想列表/);
});

test('shows recoverable search errors and retains the entered title', async () => {
  const f = fixture(async () => { throw new Error('网络中断'); });
  f.field('judge_mode').value = 'leetcode'; await f.field('judge_mode').fire('change');
  f.field('title').value = '两数'; await f.field('title').fire('input'); await f.flush();
  assert.equal(f.field('title').value, '两数');
  assert.match(f.nodes().find(node => node.className.includes('coding-title-status')).textContent, /搜索失败.*网络中断/);
});

test('does not overwrite a new platform choice with a delayed imported problem', async () => {
  let finish;
  const f = fixture(async () => [{ problem_id: 'P1000', title: '旧题' }], { importProblem: () => new Promise(resolve => { finish = resolve; }) });
  f.field('judge_mode').value = 'luogu'; await f.field('judge_mode').fire('change');
  f.field('title').value = 'P1000'; await f.field('title').fire('input'); await f.flush();
  const pending = f.nodes().find(node => node.className.includes('luogu-suggestion-option')).action();
  f.field('judge_mode').value = 'leetcode'; await f.field('judge_mode').fire('change');
  finish(f.imported); await pending;
  assert.equal(f.field('judge_mode').value, 'leetcode');
  assert.equal(f.field('statement').value, '');
  assert.equal(f.nodes().find(node => node.type === 'submit').disabled, false);
});

test('allows saving after a failed import is retried successfully', async () => {
  let fail = true;
  const f = fixture(async () => [{ problem_id: 'two-sum', title: '两数之和' }], { importProblem: () => { if (fail) throw new Error('暂时不可用'); return f.imported; } });
  f.field('judge_mode').value = 'leetcode'; await f.field('judge_mode').fire('change');
  f.field('title').value = '两数'; await f.field('title').fire('input'); await f.flush();
  await f.nodes().find(node => node.className.includes('luogu-suggestion-option')).action();
  assert.match(f.nodes().find(node => node.className.includes('coding-title-status')).textContent, /载入失败/);
  assert.equal(f.nodes().find(node => node.type === 'submit').disabled, false);
  fail = false;
  await f.field('title').fire('input'); await f.flush();
  await f.nodes().find(node => node.className.includes('luogu-suggestion-option')).action();
  await f.nodes().find(node => node.tag === 'form').fire('submit');
  assert.equal(f.saved[0].remote_problem_id, 'two-sum');
});
