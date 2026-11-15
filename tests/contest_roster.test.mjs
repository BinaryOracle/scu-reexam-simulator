import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/contest-roster.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');
function deferred() { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; }
function fixture(api) {
  const context = vm.createContext({ api, state: { token: 'same-session' } });
  vm.runInContext(source + '\nrender = () => {};', context);
  return { load(cid) { context.cid = cid; return vm.runInContext('loadContestRoster(cid)', context); },
    ids() { return Array.from(vm.runInContext('contestParticipantIds()', context)); },
    reset() { vm.runInContext('resetContestRoster()', context); },
    logout() { vm.runInContext('state.token=null', context); } };
}

test('an older roster response cannot reopen editing or replace the newer selected users', async () => {
  const earlier = deferred(), later = deferred();
  const f = fixture(path => path === '/admin/contest-participants' ? Promise.resolve([]) : path.includes('/1/') ? earlier.promise : later.promise);
  const first = f.load(1), second = f.load(2);
  later.resolve({ participant_ids: [20] }); assert.equal(await second, true);
  earlier.resolve({ participant_ids: [10] }); assert.equal(await first, false);
  assert.deepEqual(f.ids(), [20]);
});

test('cancelling or changing login invalidates pending roster loads', async () => {
  for (const action of ['reset', 'logout']) {
    const pending = deferred();
    const f = fixture(path => path === '/admin/contest-participants' ? Promise.resolve([]) : pending.promise);
    const loading = f.load(1); f[action](); pending.resolve({ participant_ids: [10] });
    assert.equal(await loading, false);
    assert.throws(() => f.ids(), /参赛名单尚未加载完成/);
  }
});
