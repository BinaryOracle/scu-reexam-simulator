import assert from "node:assert/strict";
import test from "node:test";
import { codingQuestionId, filterCodingQuestions, codingDraftKey, acceptsCodingStatus } from "../app/static/coding-model.mjs";

test("practice question routes restore a positive safe identifier only", () => {
  assert.equal(codingQuestionId("#view=coding/question/42"), 42);
  for (const hash of ["#view=coding", "#view=contest/question/42", "#view=coding/question/0", "#view=coding/question/-1", "#view=coding/question/42/extra", "#view=coding/question/99999999999999999"]) assert.equal(codingQuestionId(hash), null);
});

test("default ordering preserves the server's stage sequence even when later stages have smaller positions", () => {
  const items = [{ id: 1, position: 10, difficulty: 1, stars: 3, topic: "基础" }, { id: 2, position: 0, difficulty: 4, stars: 5, topic: "动态规划" }, { id: 3, position: 1, difficulty: 2, stars: 5, topic: "动态规划" }];
  assert.deepEqual(filterCodingQuestions(items).map(item => item.id), [1,2,3]);
  assert.deepEqual(filterCodingQuestions(items, { topic: "动态规划", stars: 4, order: "difficulty" }).map(item => item.id), [3,2]);
  assert.deepEqual(filterCodingQuestions(items, { order: "stars" }).map(item => item.id), [2,3,1]);
  assert.deepEqual(items.map(item => item.id), [1,2,3]);
});

test("practice drafts are isolated by account, question, language and feature", () => {
  const first = codingDraftKey(1, 2, "cpp11");
  assert.notEqual(first, codingDraftKey(2, 2, "cpp11"));
  assert.notEqual(first, codingDraftKey(1, 3, "cpp11"));
  assert.notEqual(first, codingDraftKey(1, 2, "python3"));
  assert.notEqual(first, "scu:1:code:2:cpp11");
});

test("only valid coding callbacks proceed to server ownership verification, including after reload", () => {
  const status = { context: "coding", submission_id: 10, remote_submission_id: "321", status: "Accepted" };
  assert.equal(acceptsCodingStatus(status), true);
  for (const change of [{ context: "contest" }, { context: undefined }, { submission_id: "10" }, { submission_id: -1 }, { remote_submission_id: "" }, { remote_submission_id: "foreign" }, { status: "" }]) assert.equal(acceptsCodingStatus({ ...status, ...change }), false);
});
