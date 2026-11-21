import assert from 'node:assert/strict';
import test from 'node:test';

import { judgePlatform, judgeProblemUrl, judgeRecordUrl, judgeSubmitPayload } from '../app/static/judge-platforms.mjs';

test('builds LeetCode links only on the China site and preserves slug case', () => {
  assert.equal(judgePlatform('leetcode').home, 'https://leetcode.cn/');
  assert.equal(judgeProblemUrl('leetcode', '1fGaJU'), 'https://leetcode.cn/problems/1fGaJU');
  assert.equal(judgeRecordUrl('leetcode', '98765'), 'https://leetcode.cn/submissions/detail/98765/');
});

test('routes each LeetCode submission with its original exercise context', () => {
  assert.deepEqual(judgeSubmitPayload({
    id: 18,
    remote_platform: 'leetcode',
    remote_problem_id: '1fGaJU',
    source_info: { question_id: '1001' },
  }, 'contest', 'cpp11', 'class Solution {};'), {
    context: 'contest', platform: 'leetcode', submission_id: 18,
    problem_id: '1fGaJU', question_id: '1001', language: 'cpp11', source: 'class Solution {};',
  });
});
