import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../app/static/contest.js', import.meta.url), 'utf8');
const renderer = source.slice(source.indexOf('async function loadContestRanking('), source.indexOf('async function enterContest('));

class Node {
  constructor(tag = 'div', text = '', className = '') {
    Object.assign(this, { tag, textContent: text, className, children: [], dataset: {}, isConnected: true });
    this.classList = { toggle() {} };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  setAttribute(name, value) { this[name] = value; }
  querySelector(selector) {
    const className = selector.slice(1);
    return this.children.find(node => node.className.split(' ').includes(className))
      ?? this.children.map(node => node.querySelector?.(selector)).find(Boolean) ?? null;
  }
  findAll(selector) {
    const className = selector.slice(1);
    return [...this.children.filter(node => node.className.split(' ').includes(className)), ...this.children.flatMap(node => node.findAll?.(selector) || [])];
  }
}

function fixture({ admin = false } = {}) {
  const records = [];
  const problems = [{ id: 10, title: '两数之和', points: 100 }];
  const rows = [
    { user_id: 7, username: 'alice', rank: 1, score: 0, accepted_count: 0, problems: [{ problem_id: 10, attempts: 0, solved: false, score: 0 }] },
    { user_id: 8, username: 'bob', rank: 2, score: 0, accepted_count: 0, problems: [{ problem_id: 10, attempts: 2, solved: false, score: 0 }] },
  ];
  const context = vm.createContext({
    state: { user: { id: 7, username: 'alice', is_admin: admin } },
    contestOverview: { id: 3, ends: Date.now() / 1000 + 1000 },
    managementMode: () => admin,
    api: async () => ({ visible: true, ranking_rule: 'score', problems, rows }),
    el: (...args) => new Node(...args),
    button: (text, action, className) => Object.assign(new Node('button', text, className), { action }),
    badge: () => new Node(), deadline: () => '',
    judgePlatform: () => null,
    showContestRecords: filters => records.push(filters),
    document: {
      createElement: tag => new Node(tag),
      createElementNS: (_namespace, tag) => new Node(tag),
    },
    Date, String,
  });
  vm.runInContext(renderer, context);
  const panel = new Node();
  return { context, panel, records, async render() { await context.loadContestRanking(panel, 3); } };
}

test('ranking opens own records including an unattempted problem but leaves others non-interactive', async () => {
  const f = fixture();
  await f.render();
  const users = f.panel.findAll('.contest-records-user');
  const problems = f.panel.findAll('.contest-records-verdict');
  assert.equal(users.length, 1);
  assert.equal(problems.length, 1);
  assert.deepEqual(users[0].children.map(node => node.className), ['', 'contest-rank-self']);
  users[0].action();
  problems[0].action();
  assert.deepEqual(JSON.parse(JSON.stringify(f.records)), [
    { userId: 7, userName: 'alice' },
    { userId: 7, userName: 'alice', problemId: 10, problemTitle: 'A · 两数之和' },
  ]);
});

test('administrator ranking retains links to every user and problem record', async () => {
  const f = fixture({ admin: true });
  await f.render();
  const users = f.panel.findAll('.contest-records-user');
  const problems = f.panel.findAll('.contest-records-verdict');
  assert.equal(users.length, 2);
  assert.equal(problems.length, 2);
});
