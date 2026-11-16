import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomUUID } from 'node:crypto';
import test from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../app/static/interview.js', import.meta.url), 'utf8');

test('saved audio counts as an answer even when transcription is unavailable', () => {
  const start = source.indexOf('function answerIsComplete(');
  const end = source.indexOf('const reviewMode =', start);
  const context = vm.createContext({});
  vm.runInContext(source.slice(start, end), context);
  const item = { workflow_version: 5, intro_completed: false };
  assert.equal(context.answerIsComplete(item, { stage: 1, has_audio: true }), false);
  item.intro_completed = true;
  assert.equal(context.answerIsComplete(item, { stage: 1 }), true);
  assert.equal(context.answerIsComplete(item, { stage: 2, transcript: '', has_audio: true }), true);
  assert.equal(context.answerIsComplete(item, { stage: 3, transcript: 'answer' }), true);
  assert.equal(context.answerIsComplete(item, { stage: 4, transcript: '  ' }), false);
});

test('history keeps timed-out interviews available for review without listing active sessions', () => {
  assert.match(source, /interviewItems = allItems\.filter\(item => item\.status === "finished" \|\| item\.status === "expired"\)/);
  assert.match(source, /const closed = item\.status === "finished" \|\| item\.status === "expired"/);
  assert.match(source, /closed \? "查看回顾 →" : reviewMode\(\) \? "查看回答 →" : "继续面试 →"/);
});

test('keeps the interview search toolbar exclusive to the records list', async () => {
  assert.match(source, /\$\("interviewListToolbar"\)\.hidden = true;/);
  assert.match(source, /\$\("interviewListToolbar"\)\.hidden = reviewMode\(\) \|\| !interviewItems\.length;/);
  const returnStart = source.indexOf('const back = button');
  const preparationStart = source.indexOf('if (preparing)', returnStart);
  assert.match(source.slice(returnStart, preparationStart), /\$\("interviewListToolbar"\)\.hidden = reviewMode\(\) \|\| !interviewItems\.length;/);
  const html = await readFile(new URL('../app/static/index.html', import.meta.url), 'utf8');
  assert.match(html, /id="interviewListToolbar"[\s\S]*?搜索面试/);
});

test('describes the end action as returning to the first interview stage', () => {
  assert.match(source, /返回第一个面试环节/);
  assert.doesNotMatch(source, /返回 001 环节/);
});

test('keeps the preparation return action visible while scrolling the setup form', async () => {
  const styles = await readFile(new URL('../app/static/style.css', import.meta.url), 'utf8');
  assert.match(source, /preparationToolbar\.append\(el\("span", "INTERVIEW SETUP", "eyebrow"\), back\)/);
  assert.match(source, /准备好 PPT 后，可先检测麦克风并试听/);
  assert.match(styles, /\.interview-preparation-toolbar\s*\{[^}]*position:\s*sticky/);
  assert.match(styles, /\.interview-preparation-toolbar \.return-interviews-button\s*\{[^}]*width:\s*auto/);
});

test('starting again after a lost response keeps the original request key', async () => {
  const headers = [];
  const item = { id: null, workflow_version: 5 };
  const storage = new Map();
  const sessionStorage = {
    getItem: key => storage.get(key) || null,
    setItem: (key, value) => storage.set(key, value),
    removeItem: key => storage.delete(key),
  };
  const context = vm.createContext({
    FormData, crypto: { randomUUID }, state: { user: { id: 7 } }, sessionStorage, activeInterview: item,
    preparationFile: new Blob(['test deck']), uploading: false, selectedStage: 1,
    allowInteraction: () => true, allowNavigation: () => true,
    sessionAudio: { prepare: async () => {}, begin: async () => {}, cancelPrepared() {} },
    api: async (path, options) => {
      headers.push(options.headers);
      if (headers.length === 1) throw new Error('response lost after server commit');
      return { id: 1, workflow_version: 5 };
    },
    renderInterview() {}, refreshInterviews: async () => {}, notify() {}, announceStage() {},
  });
  const helpersStart = source.indexOf('const resumeKey =');
  const helpersEnd = source.indexOf('\nfunction rememberInterview(', helpersStart);
  const begin = source.indexOf('function presentationControls() {');
  const end = source.indexOf('\nfunction recordingBar(', begin);
  vm.runInContext(source.slice(helpersStart, helpersEnd) + source.slice(begin, end) +
    '\nthis.controls = presentationControls();', context);
  await assert.rejects(context.controls.start(item), /response lost/);
  await context.controls.start(item);
  assert.ok(headers[0]?.['Idempotency-Key']);
  assert.equal(headers[0]['Idempotency-Key'], headers[1]['Idempotency-Key']);
});

test('a reselected deck after reload reuses its pending key and a different deck gets a new key', () => {
  const values = new Map();
  const store = {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key),
  };
  const makeContext = () => {
    const context = vm.createContext({ state: { user: { id: 7 } }, sessionStorage: store,
      crypto: { randomUUID }, transcriptionNotices: new Map() });
    const begin = source.indexOf('const resumeKey =');
    const end = source.indexOf('\nfunction rememberInterview(', begin);
    vm.runInContext(source.slice(begin, end) + '\nthis.keyFor = startRequestKey;', context);
    return context;
  };
  const file = { name: 'deck.pdf', size: 500, lastModified: 123 };
  const first = makeContext().keyFor(file);
  assert.equal(makeContext().keyFor(file), first);
  assert.notEqual(makeContext().keyFor({ ...file, name: 'new-deck.pdf' }), first);
});

test('an empty speech recognition result leaves an actionable persistent note', () => {
  const notices = new Map();
  const context = vm.createContext({ transcriptionNotices: notices });
  const begin = source.indexOf('function rememberTranscriptionResult(');
  const end = source.indexOf('\nfunction rememberInterview(', begin);
  vm.runInContext(source.slice(begin, end) + '\nthis.remember = rememberTranscriptionResult;', context);
  context.remember('3:2', '');
  assert.match(notices.get('3:2'), /没有识别到语音内容/);
  context.remember('3:2', '识别结果');
  assert.equal(notices.has('3:2'), false);
});

test('recording health exposes backup and transcription failures without captions', () => {
  const notice = { hidden: true, textContent: '' };
  const context = vm.createContext({
    document: { querySelectorAll: () => [] },
    $: id => id === 'interviewRecordingNotice' ? notice : null,
    sessionAudio: { active: true, pending: false, backupError: '录音备份失败', liveError: '实时转写不可用' },
  });
  const begin = source.indexOf('function updateRecordingStatus() {');
  const end = source.indexOf('\nfunction receiveLiveText(', begin);
  vm.runInContext(source.slice(begin, end) + '\nthis.update = updateRecordingStatus;', context);
  context.update();
  assert.equal(notice.hidden, false);
  assert.match(notice.textContent, /录音备份失败/);
  assert.match(notice.textContent, /实时转写不可用/);
  context.sessionAudio.backupError = '';
  context.sessionAudio.liveError = '';
  context.update();
  assert.equal(notice.hidden, true);
});
