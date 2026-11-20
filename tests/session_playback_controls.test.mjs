import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const interview = await readFile(new URL("../app/static/interview.js", import.meta.url), "utf8");
const styles = await readFile(new URL("../app/static/style.css", import.meta.url), "utf8");

test("full-session playback uses an explicit seek slider instead of native browser controls", () => {
  assert.ok(interview.includes('"session-playback-seek"'));
  assert.ok(interview.includes('setAttribute("aria-label", "播放进度")'));
  assert.ok(interview.includes('setAttribute("aria-label", "音量")'));
  assert.ok(interview.includes("audio.controls = false"));
  assert.ok(interview.includes("audio.duration !== Infinity"));
  assert.ok(interview.includes("Number.MAX_VALUE"));
  assert.ok(interview.includes("audio.addEventListener(\"seeked\", updateDuration"));
  assert.ok(styles.includes(".session-playback-seek"));
  assert.ok(!styles.includes(".session-playback-seek:disabled { cursor: wait"));
});

test("expanded answer review gets a larger reading area than the live answer editor", () => {
  assert.ok(interview.includes('editor.classList.add("is-review")'));
  assert.ok(styles.includes(".transcript-editor.is-review .answer-transcript"));
  assert.ok(styles.includes("height: clamp(320px, 52vh, 620px)"));
});

test("professional question history appears only when both old and new questions were saved", () => {
  assert.ok(interview.includes("questionHistory.length > 1"));
  assert.ok(!interview.includes("question_choices > 1) {\n    const history"));
});
