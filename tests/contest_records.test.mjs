import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = (await readFile(new URL('../app/static/contest-records.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
const settle = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function fixture(api, { user = { id: 1, is_admin: true }, adminMode = true } = {}) {
  class Node {
    constructor(tag, text = '', classes = '') { Object.assign(this, { tag, textContent: text, className: classes, children: [], listeners: {}, open: false, dataset: {} }); }
    get isConnected() { return this === body || Boolean(this.parent?.isConnected); }
    append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const node of this.children) node.parent = null; this.children = []; this.append(...nodes); }
    setAttribute(name, value) { this[name] = value; }
    removeAttribute(name) { delete this[name]; }
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); }
    showModal() { this.open = true; }
    close() { this.open = false; for (const fn of this.listeners.close || []) fn(); }
    remove() { this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; }
    focus() { document.activeElement = this; }
    scrollTo() {}
    find(text) { return this.children.find(node => node.textContent === text) || this.children.map(node => node.find(text)).find(Boolean); }
  }
  const body = new Node('body'); const document = { body, activeElement: body };
  const state = { user, adminMode };
  const rendered = [], requests = [];
  const el = (...args) => new Node(...args);
  const context = vm.createContext({ document, state, el, URLSearchParams,
    button: (text, action, classes) => Object.assign(el('button', text, classes), { action }),
    api: async path => { requests.push(path); return api(path); },
    emptyState: (title, description) => el('p', title + description),
  });
  vm.runInContext(source, context);
  const render = (items, options) => { rendered.push({ items, options }); return el('table'); };
  return { context, state, body, rendered, requests, open: filters => context.openContestRecords(filters, render) };
}
const page = number => ({ items: [{ id: number }], total: 21, page: number, page_size: 10, pages: 3, stats: { accepted: 2, judging: 0 } });
const filters = { contestId: 3, contestTitle: '模拟赛', userId: 7, userName: '小明', problemId: 9, problemTitle: 'A · 加法', acceptedOnly: true, participantsOnly: true };

test('record pagination keeps the selected contest, user, problem and verdict', async () => {
  const f = fixture(async path => page(Number(new URLSearchParams(path.split('?')[1]).get('page'))));
  f.open(filters); await settle();
  assert.equal(f.rendered.length, 1);
  assert.equal(f.rendered[0].options.groupedUser, true);
  await f.body.find('下一页 →').action(); await settle();
  const query = new URLSearchParams(f.requests.at(-1).split('?')[1]);
  for (const [key, value] of Object.entries({ contest_id: '3', user_id: '7', problem_id: '9', status: 'Accepted', participants_only: 'true', page: '2' })) assert.equal(query.get(key), value);
  assert.equal(f.rendered.at(-1).items[0].id, 2);
});

test('closing or replacing a record dialog ignores its pending response', async () => {
  let resolve; const pending = new Promise(yes => { resolve = yes; });
  const f = fixture(() => pending);
  f.open(filters); f.context.closeContestRecords(); resolve(page(1)); await settle();
  assert.equal(f.rendered.length, 0);
  assert.equal(f.body.children.length, 0);
});

test('a failed page offers retry without losing its selected filters', async () => {
  let failed = true; const f = fixture(async () => { if (failed) throw Error('暂时离线'); return page(1); });
  f.open(filters); await settle();
  assert.ok(f.body.find('重新加载'));
  failed = false; await f.body.find('重新加载').action(); await settle();
  assert.equal(f.rendered.length, 1);
  assert.equal(f.requests[0], f.requests[1]);
});

test('a changed login cannot populate a previous administrator dialog', async () => {
  let resolve; const f = fixture(() => new Promise(yes => { resolve = yes; }));
  f.open(filters); f.state.user = { id: 2, is_admin: false }; resolve(page(1)); await settle();
  assert.equal(f.rendered.length, 0);
});

test('regular users load only their own contest problem submissions from the self-scoped endpoint', async () => {
  const f = fixture(async () => page(1), { user: { id: 7, username: 'alice', is_admin: false }, adminMode: false });
  f.open({ contestId: 3, contestTitle: '模拟赛', userId: 7, userName: 'alice', problemId: 9, problemTitle: 'A · 加法' });
  await settle();
  const query = new URLSearchParams(f.requests[0].split('?')[1]);
  assert.equal(f.requests[0].split('?')[0], '/submissions');
  assert.equal(query.get('contest_id'), '3');
  assert.equal(query.get('problem_id'), '9');
  assert.equal(query.get('user_id'), null);
  assert.equal(f.rendered[0].options.groupedUser, true);
});

test('regular users cannot open another user submission filter', async () => {
  const f = fixture(async () => page(1), { user: { id: 7, username: 'alice', is_admin: false }, adminMode: false });
  f.open({ contestId: 3, userId: 8, userName: 'bob' });
  await settle();
  assert.deepEqual(f.requests, []);
  assert.equal(f.rendered.length, 0);
});
