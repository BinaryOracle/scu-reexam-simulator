import assert from 'node:assert/strict';
import test from 'node:test';
import { testCaseFormat } from '../app/static/test-case-formats.mjs';

test('distinguishes stdin and function argument examples', () => {
  const luogu = testCaseFormat('luogu');
  assert.match(luogu.hint, /标准输入/);
  assert.equal(luogu.input, '2 7\n9');
  const leetcode = testCaseFormat('leetcode', JSON.stringify({ params: [{ name: 'nums', type: 'integer[]' }, { name: 'target', type: 'integer' }] }));
  assert.match(leetcode.hint, /JSON/);
  assert.match(leetcode.hint, /nums: integer\[\]/);
  assert.equal(leetcode.input, 'nums = [1]\ntarget = 1');
  assert.notEqual(leetcode.output, luogu.output);
});
