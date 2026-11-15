import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const sources = Object.fromEntries(await Promise.all(['training-ui', 'training-admin', 'home'].map(async name =>
  [name, (await readFile(new URL(`../app/static/${name}.js`, import.meta.url), 'utf8')).replace(/^import .*;\n/gm, '').replace(/\bexport /g, '')])));
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

function environment(api = async () => ({})) {
  class Element {
    constructor(tag, text = '', className = '') {
      Object.assign(this, { tag, textContent: text, className, children: [], listeners: {}, value: '', hidden: false, disabled: false, open: false, tabIndex: 0 });
      this.classList = { add: name => { this.className += ` ${name}`; }, remove() {} };
    }
    get isConnected() { return this === body || Boolean(this.parent?.isConnected); }
    append(...nodes) { for (const node of nodes) { node.parent = this; this.children.push(node); } }
    replaceChildren(...nodes) { for (const node of this.children) node.parent = null; this.children = []; this.append(...nodes); }
    remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); this.parent = null; }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
    async fire(name, fields = {}) {
      const event = { preventDefault() { this.defaultPrevented = true; }, defaultPrevented: false, ...fields };
      const pending = (this.listeners[name] || []).map(listener => listener(event));
      if (name === 'cancel' && !event.defaultPrevented) this.close();
      await Promise.all(pending); return event;
    }
    async click() { if (this.disabled) return; if (this.action) { this.disabled = true; try { await this.action(); } finally { this.disabled = false; } } else await this.fire('click'); }
    querySelectorAll(selector) {
      const choices = selector.replace(/:scope > /g, '').split(/,\s*/);
      const matches = node => choices.some(part => part.startsWith('.') ? node.className.split(' ').includes(part.slice(1)) : part.startsWith('#') ? node.id === part.slice(1) : part === node.tag || (part === 'dialog.learning-dialog' && node.tag === 'dialog' && node.className.includes('learning-dialog')));
      const result = [];
      const walk = node => { for (const child of node.children) { if (matches(child)) result.push(child); walk(child); } };
      walk(this); return result;
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    showModal() { this.open = true; }
    close() { this.open = false; void this.fire('close'); }
    focus() { document.activeElement = this; }
    scrollIntoView() {}
    getClientRects() { return [{}]; }
  }
  const body = new Element('body');
  const document = { body, activeElement: body, querySelectorAll: selector => body.querySelectorAll(selector), createDocumentFragment: () => new Element('fragment') };
  const notices = [], confirmations = [];
  let confirmation = false;
  const el = (...args) => new Element(...args);
  const button = (text, action, className) => { const node = el('button', text, className); node.action = action; return node; };
  const context = vm.createContext({ document, el, button, api, state: { token: 'token', user: { is_admin: true } },
    $: id => body.querySelector(`#${id}`), notify: (...args) => notices.push(args), badge: text => el('span', text),
    emptyState: (title, description, icon = '◉') => { const node = el('div', '', 'empty-state'); node.append(el('span', icon, 'empty-icon'), el('h3', title), el('p', description)); return node; },
    confirmAction: async (...args) => { confirmations.push(args); return confirmation; }, crypto: { randomUUID: () => 'id' },
    URLSearchParams, URL, FormData: class { append() {} }, setTimeout, clearTimeout });
  return { body, context, notices, confirmations, el, choose: value => { confirmation = value; },
    load(name) { vm.runInContext(sources[name], context); }, find: (root, text) => root.querySelectorAll('button').find(node => node.textContent === text) };
}
const collections = [{ id: 'ds', name: '数据结构', section_id: 'interview', category: 'professional', active: true }];
function editor(env, save = async () => {}) {
  env.context.questionEditor(collections, null, save);
  const dialog = env.body.querySelector('dialog');
  return { dialog, form: dialog.querySelector('form'), question: dialog.querySelector('textarea') };
}

for (const control of ['取消', '×', 'Escape']) test(`question ${control} preserves unsaved changes when discard is declined`, async () => {
  const env = environment(); env.load('training-ui');
  const { dialog, question } = editor(env); question.value = '尚未保存的题目';
  if (control === 'Escape') await dialog.fire('cancel'); else await env.find(dialog, control).click();
  assert.equal(dialog.open, true);
  assert.equal(env.confirmations.length, 1);
  assert.equal(question.value, '尚未保存的题目');
  env.choose(true); await env.find(dialog, '取消').click(); assert.equal(dialog.open, false);
});

test('question cannot be closed while its save is pending', async () => {
  const pending = deferred(), env = environment(); env.load('training-ui');
  const { dialog, form } = editor(env, () => pending.promise);
  const saving = form.fire('submit');
  await dialog.fire('cancel'); await env.find(dialog, '取消').click();
  assert.equal(dialog.open, true);
  pending.resolve(); await saving; assert.equal(dialog.open, false);
});

test('successful public create closes the editor even when the list refresh fails', async () => {
  let wrote = 0;
  const env = environment(async (path, options) => {
    if (path === '/admin/training/settings') return { collections };
    if (options?.method === 'POST') { wrote++; return {}; }
    if (wrote) throw new Error('列表暂时不可用');
    return { total: 0, page: 1, page_size: 20, items: [] };
  });
  for (const id of ['trainingAdmin', 'trainingAdminContent']) { const node = env.el('section'); node.id = id; env.body.append(node); }
  env.load('training-ui'); env.load('training-admin'); await env.context.refreshTrainingAdmin();
  await env.find(env.body, '公开题库').click(); await env.find(env.body, '新增公开题').click();
  const dialog = env.body.querySelector('dialog'); dialog.querySelector('textarea').value = '题目';
  await dialog.querySelector('form').fire('submit');
  assert.equal(wrote, 1); assert.equal(dialog.open, false);
  assert.ok(env.notices.some(([message]) => message.includes('已保存') && message.includes('刷新')));
});

test('import stays open during submission and reports the completed import once', async () => {
  const pending = deferred(); let refreshed = 0, writes = 0;
  const env = environment(async path => {
    if (path.endsWith('/preview')) return { count: 1, errors: [], items: [{ collection_id: 'ds', question: '题目' }] };
    writes++; return pending.promise;
  }); env.load('training-ui'); env.context.importDialog(async () => { refreshed++; });
  const dialog = env.body.querySelector('dialog'), file = dialog.querySelector('input'); file.files = [{}]; await file.fire('change');
  const importing = env.find(dialog, '确认导入').click();
  await dialog.fire('cancel'); await env.find(dialog, '取消').click(); await env.find(dialog, '×').click();
  assert.equal(dialog.open, true); assert.equal(file.disabled, true);
  pending.resolve({ created: 1 }); await importing;
  assert.equal(writes, 1); assert.equal(refreshed, 1); assert.equal(dialog.open, false);
  assert.ok(env.notices.some(([message]) => message === '已保存 1 道私人题目'));
});

test('announcement cancel preserves edited content until discard is confirmed', async () => {
  const env = environment(); env.load('home');
  const root = env.el('section'); root.id = 'announcementsAdmin'; env.body.append(root);
  for (const name of ['page-heading', 'announcement-admin-toolbar', 'announcement-admin-list']) root.append(env.el('div', '', name));
  env.context.editNotice(null); const form = root.querySelector('form'); form.querySelector('input').value = '未保存公告';
  await env.find(form, '取消').click(); await settle();
  assert.equal(form.isConnected, true); assert.equal(env.confirmations.length, 1);
  env.choose(true); await env.find(form, '取消').click();
  assert.equal(form.isConnected, false); assert.equal(root.querySelector('.page-heading').hidden, false);
});

test('announcement status change returns an invalid filtered last page to the preceding page', async () => {
  let changed = false; const requests = [];
  const item = { id: 1, title: '公告', summary: '', status: 'published' };
  const env = environment(async (path, options) => {
    if (options?.method === 'POST') { changed = true; return {}; }
    if (!path.includes('?')) return {};
    const params = new URLSearchParams(path.split('?')[1]); requests.push(params);
    const page = Number(params.get('page'));
    return { items: changed && page === 2 ? [] : [item], pages: changed ? 1 : 2, total: changed ? 10 : 11 };
  }); env.load('home'); const root = env.el('section'); root.id = 'announcementsAdmin'; env.body.append(root);
  await env.context.refreshAnnouncementsAdmin();
  const status = root.querySelector('select'); status.value = 'published'; await status.fire('change'); await settle();
  await env.find(root, '下一页').click(); await settle();
  await env.find(root, '下架').click(); await settle();
  assert.equal(requests.at(-1).get('page'), '1'); assert.equal(requests.at(-1).get('status'), 'published');
  assert.ok(root.querySelector('strong')); assert.equal(root.querySelector('.empty-state'), null);
});
