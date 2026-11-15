import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

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
  assert.ok(styles.includes("min-height: min(320px, 45vh)"));
});

test("professional question history appears only when both old and new questions were saved", () => {
  assert.ok(interview.includes("questionHistory.length > 1"));
  assert.ok(!interview.includes("question_choices > 1) {\n    const history"));
});


test("dragging playback keeps its preview and cancellation restores the actual position", () => {
  class Element {
    constructor(tag, text = "", className = "") {
      Object.assign(this, { tag, textContent: text, className, listeners: {}, children: [],
        style: { setProperty() {} }, currentTime: 0, duration: 100, volume: 1,
        paused: true, seekable: { length: 0 }, isConnected: true });
    }
    setAttribute() {}
    append(...nodes) { this.children.push(...nodes); }
    addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
    removeEventListener() {}
    fire(name) { for (const listener of this.listeners[name] || []) listener(); }
    querySelectorAll() { return []; }
  }
  const context = vm.createContext({
    el: (...args) => new Element(...args),
    button: (text, action, className) => new Element("button", text, className),
    notify() {},
  });
  const start = interview.indexOf("function formatPlaybackTime(");
  const end = interview.indexOf("async function saveAnswer(", start);
  vm.runInContext(`${interview.slice(start, end)}\nthis.make = sessionPlaybackControl;`, context);
  const control = context.make({ id: 1 }, { id: 1 }, 1, new Element("section"));
  const [audio, , current, seek] = control.children;
  audio.currentTime = 10;
  audio.fire("loadedmetadata");
  seek.value = "700";
  seek.fire("input");
  audio.fire("durationchange");
  assert.equal(seek.value, "700");
  assert.equal(current.textContent, "1:10");
  seek.fire("pointercancel");
  assert.equal(audio.currentTime, 10);
  assert.equal(seek.value, "100");
  seek.value = "600";
  seek.fire("input");
  seek.fire("change");
  assert.equal(audio.currentTime, 60);
});
