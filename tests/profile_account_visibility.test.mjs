import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../app/static/profile-account.js', import.meta.url), 'utf8');

test('hides the entire deletion row for root and restores it for an ordinary user', () => {
  const row = { hidden: false };
  const elements = new Map();
  const context = vm.createContext({
    state: { user: { username: 'root', is_superadmin: true } },
    clearProfilePassword() {},
    $: id => {
      if (!elements.has(id)) elements.set(id, { closest: () => row });
      return elements.get(id);
    },
  });
  const start = source.indexOf('export function refreshAccountSettings()');
  const end = source.indexOf('\nfunction field(', start);
  vm.runInContext(source.slice(start, end).replace('export ', ''), context);
  context.refreshAccountSettings();
  assert.equal(row.hidden, true);
  context.state.user = { username: 'candidate', is_superadmin: false };
  context.refreshAccountSettings();
  assert.equal(row.hidden, false);
  assert.equal(elements.get('profileDeleteAccount').hidden, false);
});
