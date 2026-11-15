import assert from "node:assert/strict";
import test from "node:test";
import { normalizeProblemStatementHtml } from "../app/static/problem-content.js";

test("collapses duplicated resource limits in previously saved problem HTML", () => {
  const html = '<h2>资源限制：</h2><ul><li>时间限制：1000-1000-1000-1000 ms</li><li>内存限制：128-128-128 MiB</li></ul>';
  assert.equal(normalizeProblemStatementHtml(html), '<h2>资源限制：</h2><ul><li>时间限制：1000 ms</li><li>内存限制：128 MiB</li></ul>');
});

test("retains distinct resource limits and leaves unrelated problem markup unchanged", () => {
  const html = '<p>复杂度为 O(n)</p><li>时间限制：1000-2000 ms</li><li>内存限制：128-256 MiB</li>';
  assert.equal(normalizeProblemStatementHtml(html), html);
});
