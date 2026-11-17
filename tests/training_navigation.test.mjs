import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = (await readFile(new URL('../app/static/training.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
const styles = await readFile(new URL('../app/static/training.css', import.meta.url), 'utf8');
const markup = await readFile(new URL('../app/static/index.html', import.meta.url), 'utf8');

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}
function home(active = null) {
  return { sections: [{ id: 'interview', name: '面试篇', count: 2 }, { id: 'written_ai', name: 'AI 篇', count: 2 }],
    collections: [{ id: 'data_structures', section_id: 'interview', name: '数据结构', count: 2, favorites: 0 },
      { id: 'ai_ml', section_id: 'written_ai', name: '机器学习', count: 2, favorites: 0 }],
    active_session: active, can_training: true, can_practice: true, completed: 0, goal: 5, recent_days: [], rewards: [], mastery: { again: 0, known: 0 },
    max_round_questions: 100, default_round_size: 2 };
}
function round(completed = 0) {
  return { id: 1, section_id: 'interview', collection_id: 'data_structures', mode: 'random',
    status: completed ? 'completed' : 'active', total: 1, completed,
    cards: [{ id: 4, question_id: 8, question: '当前题目', collection_name: '数据结构', category: 'professional',
      available: true, completed: Boolean(completed), mastery: { status: 'unseen' } }] };
}
function fixture(api) {
  class Element {
    constructor(tag, text = '', className = '') {
      Object.assign(this, { tag, textContent: String(text), className, children: [], style: {}, dataset: {}, hidden: false, value: '', disabled: false });
      this.classList = { add() {}, toggle() {}, contains(name) { return this.owner.className.split(' ').includes(name); }, owner: this };
    }
    get isConnected() { return this === training || Boolean(this.parent?.isConnected); }
    get firstChild() { return this.children[0]; }
    append(...nodes) { for (const node of nodes) if (node) { node.parent = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const child of this.children) child.parent = null; this.children = []; this.append(...nodes); }
    insertBefore(node, before) { node.parent = this; this.children.splice(this.children.indexOf(before), 0, node); }
    remove() { this.parent.children.splice(this.parent.children.indexOf(this), 1); this.parent = null; }
    setAttribute(name, value) { (this.attributes ||= {})[name] = String(value); }
    addEventListener() {}
    reportValidity() { return true; }
    scrollIntoView() {}
    focus() {}
    querySelector(selector) { return find(this, node => selector.startsWith('.') ? node.className.split(' ').includes(selector.slice(1)) : node.tag === selector); }
  }
  const el = (...args) => new Element(...args);
  const training = el('section');
  const content = el('div'); training.append(content);
  const find = (node, predicate) => node.children.flatMap(child => [child, ...descendants(child)]).find(predicate);
  const descendants = node => node.children.flatMap(child => [child, ...descendants(child)]);
  const context = vm.createContext({ api, state: { token: 'same' }, URLSearchParams,
    $: id => id === 'training' ? training : id === 'trainingContent' ? content : null,
    el, button: (text, action, classes) => Object.assign(el('button', text, classes), { action }),
    badge: text => el('span', text), clearLearningMedia() {}, notify() {},
    passageContext: () => el('div'), referenceAnswer: () => el('p', '参考答案'),
    selectField: (label, options, selected) => ({ wrap: el('label', label), input: Object.assign(el('select'), { value: selected }) }),
  });
  vm.runInContext(source, context);
  return {
    show(value, data = home()) { context.value = value; context.data = data; vm.runInContext('homeData=data; session=value; render();', context); },
    read(expression) { return vm.runInContext(expression, context); },
    has(text) { return Boolean(find(content, node => node.textContent === text)); },
    isDisabled(label) { const control = find(content, node => node.tag === 'button' && node.textContent === label); assert.ok(control, `Missing button ${label}`); return control.disabled; },
    buttonsIn(className) { return find(content, node => node.className.split(' ').includes(className))?.children.filter(node => node.tag === 'button').map(node => node.textContent) || []; },
    node(className) { return find(content, node => node.className.split(' ').includes(className)); },
    async click(label) { const control = find(content, node => node.tag === 'button' && (node.textContent === label || node.children.some(child => child.textContent === label))); assert.ok(control, `Missing button ${label}`); return control.action(); },
  };
}

test('failed return leaves the current card available for rating', async () => {
  const f = fixture(async path => { if (path.startsWith('/training/home')) throw new Error('offline'); return round(1); });
  f.show(round()); await f.click('查看参考答案');
  await assert.rejects(f.click('← 返回今日练习'), /offline/);
  await f.click('已掌握，下一题 →');
  assert.equal(f.read('session.completed'), 1);
  assert.equal(f.has('回顾本轮题目'), true);
});

test('describes an active training round as current progress', () => {
  const f = fixture(async () => home());
  f.show(null, home({ section_id: 'interview', completed: 0, total: 1 }));
  assert.equal(f.has('面试篇 · 本轮进度 0/1 题'), true);
});

test('a rating response cannot reopen a round after returning to today', async () => {
  const response = deferred();
  const f = fixture(path => path.includes('/complete') ? response.promise : Promise.resolve(home()));
  f.show(round()); await f.click('查看参考答案');
  const pending = f.click('已掌握，下一题 →');
  await f.click('← 返回今日练习');
  response.resolve(round(1)); await pending;
  assert.equal(f.read('session'), null);
  assert.equal(f.has('开始训练 →'), true);
});

test('starting a round cannot replace a chapter selected while the request was pending', async () => {
  const response = deferred();
  const f = fixture(path => path === '/training/sessions' ? response.promise : Promise.resolve(home()));
  f.show(null);
  const pending = f.click('开始训练 →');
  await f.click('AI 篇'); response.resolve(round()); await pending;
  assert.equal(f.read('session'), null);
  assert.equal(f.read('section'), 'written_ai');
});

test('a failed chapter request preserves the displayed chapter and collection', async () => {
  const f = fixture(async () => { throw new Error('offline'); });
  f.show(null); f.read("collection='data_structures'; render()");
  await assert.rejects(f.click('AI 篇'), /offline/);
  assert.equal(f.read('section'), 'interview');
  assert.equal(f.read('collection'), 'data_structures');
});

test('resuming a round cannot override a later chapter selection', async () => {
  const response = deferred();
  const f = fixture(path => path === '/training/sessions/1' ? response.promise : Promise.resolve(home()));
  f.show(null, home({ id: 1, section_id: 'interview', completed: 0, total: 1 }));
  const pending = f.click('继续练习');
  await f.click('AI 篇'); response.resolve(round()); await pending;
  assert.equal(f.read('session'), null);
  assert.equal(f.read('section'), 'written_ai');
});


test('failed return from a completed round preserves it and permits retry', async () => {
  let offline = true;
  const f = fixture(async () => { if (offline) throw new Error('offline'); return home(); });
  f.show(round(1));
  await assert.rejects(f.click('结束本轮训练'), /offline/);
  assert.equal(f.read('session.status'), 'completed');
  assert.equal(f.has('结束本轮训练'), true);
  offline = false; await f.click('结束本轮训练');
  assert.equal(f.read('session'), null);
  assert.equal(f.has('开始训练 →'), true);
});

test('a slower chapter response cannot change a newer chapter selection', async () => {
  const response = deferred();
  const f = fixture(path => path.endsWith('written_ai') ? response.promise : Promise.resolve(home()));
  f.show(null);
  const pending = f.click('AI 篇');
  await f.click('面试篇'); response.resolve(home()); await pending;
  assert.equal(f.read('section'), 'interview');
  assert.equal(f.read('session'), null);
});

test('an uninterrupted start still opens the question card', async () => {
  const f = fixture(async () => round());
  f.show(null); await f.click('开始训练 →');
  assert.equal(f.read('session.id'), 1);
  assert.equal(f.has('当前题目'), true);
  assert.equal(f.has('查看参考答案'), true);
});

test('an active round provides a question dock to revisit completed questions', async () => {
  const cards = [
    { id: 4, question_id: 8, question: '已完成的问题', collection_name: '数据结构', category: 'professional', available: true, completed: true, rating: 'again', mastery: { status: 'again' } },
    { id: 5, question_id: 9, question: '当前问题', collection_name: '数据结构', category: 'professional', available: true, completed: false, mastery: { status: 'unseen' } },
    { id: 6, question_id: 10, question: '尚未作答的问题', collection_name: '数据结构', category: 'professional', available: true, completed: false, mastery: { status: 'unseen' } },
  ];
  const f = fixture(async () => ({ id: 1, section_id: 'interview', collection_id: 'data_structures', mode: 'random', status: 'active', total: 3, completed: 1, cards }));
  f.show({ id: 1, section_id: 'interview', collection_id: 'data_structures', mode: 'random', status: 'active', total: 3, completed: 1, cards });
  assert.equal(f.has('题目列表'), true);
  await f.click('第 1 题 · 已完成');
  assert.equal(f.has('已完成的问题'), true);
  assert.equal(f.has('自评：还需练习'), true);
  await f.click('返回当前题目');
  assert.equal(f.has('当前问题'), true);
  assert.equal(f.isDisabled('第 3 题 · 未作答'), true);
});

test('a learner can continue without self-rating and leave the question unseen', async () => {
  const calls = [];
  const f = fixture(async (path, options) => { calls.push([path, options]); return round(1); });
  f.show(round()); await f.click('查看参考答案');
  await f.click('暂不自评，下一题 →');
  assert.equal(JSON.parse(calls[0][1].body).rating, 'done');
});

test('oral practice also offers the three self-rating choices', () => {
  const card = { ...round().cards[0], category: 'oral' };
  const f = fixture(async () => round());
  f.show({ ...round(), cards: [card] });
  assert.equal(f.has('还需练习，下一题 →'), true);
  assert.equal(f.has('已掌握，下一题 →'), true);
  assert.equal(f.has('暂不自评，下一题 →'), true);
});

test('self-rating controls are ordered with skip centered and explain each choice', async () => {
  const f = fixture(async () => round());
  f.show(round()); await f.click('查看参考答案');
  assert.deepEqual(f.buttonsIn('learning-rating-footer'), ['还需练习，下一题 →', '暂不自评，下一题 →', '已掌握，下一题 →']);
  assert.equal(f.has('还需练习：下轮随机训练更容易抽中 · 暂不自评：不更改掌握记录 · 已掌握：下轮随机训练降低抽中概率'), true);
  assert.match(styles, /\.learning-rating-footer\{display:grid;grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(styles, /\.learning-rating-skip\{[^}]*background:#f7f5f1/);
});

test('question dock sits beside expanded or collapsed sidebar and clears mobile navigation', () => {
  assert.match(styles, /\.learning-question-dock\{[^}]*left:238px/);
  assert.match(styles, /\.sidebar-collapsed \.learning-question-dock\{left:90px/);
  assert.match(styles, /@media\(max-width:850px\)\{\.learning-question-dock\{left:12px;top:auto;bottom:12px/);
});

test('entry document invalidates the app module cache for the training navigation update', () => {
  assert.match(markup, /app\.js\?v=20261118-review-layout-v1/);
});

test('a completed round can be reviewed from its full question list or ended', async () => {
  const cards = [
    { id: 4, question_id: 8, question: '第一题', answer: '答案一', collection_name: '数据结构', category: 'professional', available: true, completed: true, mastery: { status: 'known' } },
    { id: 5, question_id: 9, question: '第二题', answer: '答案二', collection_name: '数据结构', category: 'professional', available: true, completed: true, mastery: { status: 'unseen' } },
  ];
  const completed = { id: 1, section_id: 'interview', collection_id: 'data_structures', mode: 'random', status: 'completed', total: 2, completed: 2, cards };
  const f = fixture(async () => home());
  f.show(completed);
  assert.equal(f.has('回顾本轮题目'), true);
  assert.equal(f.has('结束本轮训练'), true);
  await f.click('回顾本轮题目');
  assert.equal(f.has('第一题'), true);
  assert.equal(f.has('第二题'), false);
  assert.equal(f.isDisabled('← 上一题'), true);
  assert.equal(f.isDisabled('下一题 →'), false);
  await f.click('下一题 →');
  assert.equal(f.has('第二题'), true);
  assert.equal(f.isDisabled('下一题 →'), true);
  await f.click('← 上一题');
  assert.equal(f.has('第一题'), true);
  await f.click('第 2 题 · 已完成');
  assert.equal(f.has('第二题'), true);
  assert.equal(f.has('结束回顾'), true);
  await f.click('结束回顾');
  assert.equal(f.has('结束本轮训练'), true);
  await f.click('结束本轮训练');
  assert.equal(f.read('session'), null);
});

test('review navigation keeps the same slots without an answer and after revealing an answer', async () => {
  const f = fixture(async () => home());
  const layout = category => {
    const completed = round(1);
    completed.cards[0].category = category;
    f.show(completed);
  };
  layout('professional');
  await f.click('回顾本轮题目');
  const slots = f.node('learning-review-footer').children.map(node => node.className);
  const navigation = f.node('learning-review-navigation');
  const answerSlot = f.node('learning-review-answer-slot');
  await f.click('查看参考答案');
  assert.equal(f.node('learning-review-navigation'), navigation);
  assert.equal(f.node('learning-review-answer-slot'), answerSlot);
  layout('oral');
  assert.deepEqual(f.node('learning-review-footer').children.map(node => node.className), slots);
  assert.equal(f.node('learning-review-answer-slot').children.length, 0);
  assert.match(styles, /\.learning-study-footer\.learning-review-footer\{display:grid;grid-template-columns:minmax\(0,1fr\) minmax\(0,1\.6fr\) minmax\(0,1fr\)/);
});

test('an account without daily training permission can browse but cannot start a round', async () => {
  let calls = 0;
  const f = fixture(async () => { calls++; return round(); });
  f.show(null, { ...home(), can_training: false, can_practice: true });
  assert.equal(f.has('每日训练'), true);
  assert.equal(f.isDisabled('开始训练 →'), true);
  await f.click('开始训练 →');
  assert.equal(calls, 0);
  assert.equal(f.read('session'), null);
});

test('explains that an existing round can continue without permission for new rounds', () => {
  const f = fixture(async () => home());
  f.show(null, { ...home({ id: 1, section_id: 'interview', completed: 0, total: 1 }), can_training: false });
  assert.equal(f.has('每日训练权限尚未开通。你仍可浏览篇目、管理个人题目，并继续已开始的练习轮次；开始新一轮前请联系管理员开通。'), true);
  assert.equal(f.has('继续练习'), true);
});
