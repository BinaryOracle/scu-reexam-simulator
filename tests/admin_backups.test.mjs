import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = (await readFile(new URL('../app/static/admin-backups.js', import.meta.url), 'utf8'))
  .replace(/^import .*;\n/gm, '').replace(/\bexport /g, '');
const modules = ['accounts', 'credits', 'courses', 'live', 'announcements', 'media'].map(id =>
  ({ id, name: id, description: '说明', rows: 2, media: id === 'media', estimated_bytes: 10 }));
function environment({ superadmin = true, confirm = true } = {}) {
  class Element {
    constructor(tag, text = '', className = '') {
      Object.assign(this, { tag, textContent: text, className, children: [], listeners: {}, hidden: false, disabled: false, checked: false, files: [] });
      this.classList = { toggle: (name, enabled) => { this[name] = enabled; } };
    }
    append(...children) { for (const child of children) { child.parent = this; this.children.push(child); } }
    replaceChildren(...children) { this.children = []; this.append(...children); }
    setAttribute(name, value) { this[name] = value; }
    addEventListener(name, callback) { this.listeners[name] = callback; }
    closest() { return this.parent; }
  }
  const ids = Object.fromEntries(['backupPanel', 'backupModuleList', 'backupStatus', 'exportBackup', 'restoreBackup',
    'backupFile', 'backupPreview', 'backupRestoreStatus', 'refreshBackupModules', 'backupSelectAll', 'backupSelectNone',
    'backupRestoreForm'].map(id => [id, new Element('div')]));
  const requests = [], notices = [], events = [], handlers = {};
  const window = { addEventListener(name, callback) { handlers[name] = callback; }, dispatchEvent(event) { events.push(event.type); handlers[event.type]?.(event); } };
  const document = { querySelectorAll(selector) {
    if (selector === '#backupModuleList input') return ids.backupModuleList.children.map(label => label.children[0]);
    if (selector === '#backupPanel button, #backupPanel input') return Object.values(ids);
    return [];
  } };
  class FormData {
    constructor() { this.data = new Map(); }
    append(key, value) { this.data.set(key, value); }
  }
  const state = { token: 'root-token', user: { is_superadmin: superadmin } };
  const result = { sha256: 'abc123', exported_at: '2026-11-22T12:00:00Z', files: 2, includes_passwords: true,
    modules: [{ id: 'accounts', name: '账号', rows: 4 }], warnings: [] };
  const context = vm.createContext({ $, window, document, state, FormData, Event, Date, Set, Number,
    el: (...args) => new Element(...args), notify: (...args) => notices.push(args), confirmAction: async () => confirm,
    api: async (path, options) => {
      requests.push({ path, options });
      if (path.endsWith('/modules')) return modules;
      if (path.endsWith('/preview')) return result;
      if (path.endsWith('/restore')) return { safety_backup: 'before-restore-test' };
      throw new Error('unexpected request');
    } });
  function $(id) { return ids[id]; }
  vm.runInContext(source, context);
  return { context, ids, state, requests, notices, events,
    run: code => vm.runInContext(code, context), file: () => { ids.backupFile.files = [{ name: 'test.zip' }]; } };
}

test('ordinary administrator never loads credential backup metadata', async () => {
  const env = environment({ superadmin: false });
  await env.run('refreshBackupModules()');
  assert.equal(env.ids.backupPanel.hidden, true);
  assert.equal(env.requests.length, 0);
});

test('related modules toggle together and refresh preserves selection', async () => {
  const env = environment();
  await env.run('refreshBackupModules()');
  const account = env.ids.backupModuleList.children[0].children[0];
  account.checked = false; account.listeners.change();
  assert.equal(env.ids.backupModuleList.children[1].children[0].checked, false);
  await env.run('refreshBackupModules()');
  assert.equal(env.ids.backupModuleList.children[0].children[0].checked, false);
  assert.equal(env.ids.backupModuleList.children[4].children[0].checked, true);
});

test('a new file invalidates the prior preview and disables restore', async () => {
  const env = environment(); await env.run('refreshBackupModules()'); env.file();
  await env.run('previewBackup({ preventDefault() {} })');
  assert.equal(env.ids.restoreBackup.disabled, false);
  env.run('clearPreview()');
  assert.equal(env.ids.restoreBackup.disabled, true);
  assert.equal(env.ids.backupPreview.hidden, true);
});

test('declining destructive confirmation sends no restore request', async () => {
  const env = environment({ confirm: false }); await env.run('refreshBackupModules()'); env.file();
  await env.run('previewBackup({ preventDefault() {} })');
  await env.run('restoreBackup()');
  assert.equal(env.requests.some(request => request.path.endsWith('/restore')), false);
  assert.equal(env.ids.restoreBackup.disabled, false);
});

test('successful restore submits the exact previewed file and clears the session UI', async () => {
  const env = environment(); env.run('setupBackups()');
  await env.run('refreshBackupModules()'); env.file();
  await env.run('previewBackup({ preventDefault() {} })');
  await env.run('restoreBackup()');
  const request = env.requests.find(request => request.path.endsWith('/restore'));
  assert.equal(request.options.body.data.get('file'), env.ids.backupFile.files[0]);
  assert.equal(request.options.body.data.get('sha256'), 'abc123');
  assert.equal(request.options.body.data.get('confirmation'), 'RESTORE');
  assert.deepEqual(env.events, ['session-expired']);
  assert.equal(env.ids.restoreBackup.disabled, true);
  assert.equal(env.ids.exportBackup.disabled, true);
});
