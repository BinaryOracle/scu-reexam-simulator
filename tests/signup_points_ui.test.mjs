import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = async name => (await readFile(new URL(`../app/static/${name}.js`, import.meta.url), 'utf8'))
  .replace(/^import\b[\s\S]*?;\n/gm, '').replace(/^export \{[^}]*\};\n/gm, '').replace(/\bexport /g, '');
const [admin, credits] = await Promise.all(['admin', 'credits'].map(source));

function environment(code) {
  const nodes = new Map(), calls = [], notices = [], pending = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, {
      value: '', checked: false, hidden: false, disabled: false, textContent: '', listeners: {},
      elements: { namedItem: name => node(`${id}.${name}`) },
      classList: { add() {}, remove() {} },
      setAttribute() {}, removeAttribute() {}, append() {}, replaceChildren() {}, reset() {},
      closest() { return node(`${id}.parent`); }, querySelector() { return node(`${id}.child`); },
      addEventListener(type, handler) { this.listeners[type] = handler; },
      showModal() { this.open = true; }, close() { this.open = false; },
    });
    return nodes.get(id);
  };
  const settings = { default_points: 7, packages: [], interview_points_cost: 1,
    reward_rules: { leaderboard_rewards: [3, 2, 1], contest_rewards: [3, 2, 1] } };
  const context = vm.createContext({
    $: node, el: () => node(Symbol()), button: () => node(Symbol()), emptyState: () => node(Symbol()),
    api: async (url, options) => {
      calls.push({ url, options });
      if (url === '/admin/credit-settings') return settings;
      if (url.startsWith('/admin/vouchers')) throw new Error('卡密列表加载失败');
      return {};
    },
    state: { user: { is_superadmin: true } }, readCreditSettings: async () => settings,
    notify: text => notices.push(text), setupAccountSettings() {}, clearTimeout, URLSearchParams,
    run: action => { const promise = action(); pending.push(promise); return promise; },
  });
  vm.runInContext(code, context);
  return { node, calls, notices, pending, context, settings };
}

test('account creation loads the configured points grant and sends an explicit zero override', async () => {
  const env = environment(admin);
  vm.runInContext('refreshUsers = async () => {}', env.context);
  await env.context.openAccount();
  assert.equal(env.node('accountPoints').value, 7);
  assert.equal(env.node('initialPointsField').hidden, false);
  env.node('accountUsername').value = 'student';
  env.node('accountPassword').value = 'password';
  env.node('accountPoints').value = '0';
  await env.context.submitAccount({ preventDefault() {} });
  const payload = JSON.parse(env.calls[0].options.body);
  assert.equal(payload.points, 0);
  assert.equal('interview_credits' in payload, false);
  assert.equal(env.node('userDialog').open, false);
  env.node('accountTypeAdmin').checked = true;
  env.context.syncAccountType();
  assert.equal(env.node('initialPointsField').hidden, true);
  assert.equal(env.node('accountPoints').disabled, true);
});

test('initial points settings remain usable when the voucher list fails and retain unsaved edits', async () => {
  const env = environment(credits);
  env.context.setupCredits();
  await assert.rejects(env.context.refreshVouchers(), /卡密列表加载失败/);
  assert.equal(env.node('defaultPoints').value, 7);
  env.node('defaultPoints').value = '11';
  env.node('defaultPoints').listeners.input();
  await assert.rejects(env.context.refreshVouchers(), /卡密列表加载失败/);
  assert.equal(env.node('defaultPoints').value, '11');
  env.node('defaultPointsForm').listeners.submit({ preventDefault() {} });
  await Promise.all(env.pending);
  const saved = env.calls.find(call => call.options?.method === 'PATCH');
  assert.deepEqual(JSON.parse(saved.options.body), { default_points: 11 });
  assert.match(env.notices.at(-1), /初始积分已更新/);
});
