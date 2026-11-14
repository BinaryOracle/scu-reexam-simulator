/** Run the production recording class with controlled media and delayed ASR. */
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';

const pending = [];
const recognizers = [];
const flush = () => new Promise(resolve => setImmediate(resolve));
class Recorder {
  static isTypeSupported() { return true; }
  constructor() { this.state = 'inactive'; this.mimeType = 'audio/webm'; }
  start() { this.state = 'recording'; }
  stop() {
    this.state = 'inactive';
    queueMicrotask(() => {
      this.ondataavailable?.({ data: new Blob(['recorded voice']) });
      this.onstop?.();
    });
  }
}
class Recognition {
  constructor() { recognizers.push(this); }
  start() {}
  stop() { queueMicrotask(() => { if (this.finalOnStop) this.onresult?.(this.finalOnStop); this.onend?.(); }); }
}
const stream = () => ({ getTracks: () => [], getAudioTracks: () => [] });
const context = vm.createContext({
  Blob, FormData, MediaRecorder: Recorder, window: { SpeechRecognition: Recognition },
  setTimeout, clearTimeout, setInterval, clearInterval, queueMicrotask,
});
const apiModule = new vm.SyntheticModule(['api'], function () {
  this.setExport('api', (path) => {
    if (path.endsWith('/live-transcribe')) return new Promise((resolve, reject) => pending.push({ resolve, reject, path }));
    return Promise.resolve({ id: 'recording' });
  });
}, { context });
const uiModule = new vm.SyntheticModule(['el', 'button', 'notify', 'run'], function () {
  for (const name of ['el', 'button', 'notify', 'run']) this.setExport(name, () => {});
}, { context });
const source = await fs.readFile('app/static/interview-audio.js', 'utf8');
const module = new vm.SourceTextModule(source, { context });
await module.link(specifier => specifier.startsWith('./api.js') ? apiModule : uiModule);
await module.evaluate();
const { SessionAudio } = module.namespace;
const item = (id, server = true) => ({ id, server_asr_available: server, workflow_version: 5,
  recording_options: { bitrate: 64000, checkpoint_seconds: 3600, live_chunk_seconds: 3600 } });
const makeAudio = () => {
  const texts = [];
  const audio = new SessionAudio({ changed() {}, interrupted() {}, text: (...parts) => texts.push(parts) });
  return { audio, texts };
};
async function begin(audio, id) { audio.prepared = stream(); await audio.begin(item(id)); }

// Draining a stage must retain the final chunk after stopLive clears the live object.
{
  const { audio, texts } = makeAudio();
  await begin(audio, 1);
  audio.startLive(item(1), 1);
  const drained = audio.drainLive();
  await flush();
  pending.shift().resolve({ transcript: 'final words' });
  await drained;
  assert.equal(texts[0][1], 'final words');
  audio.clear();
}
// A prior ASR response must not write into a new interview's stage.
{
  const { audio, texts } = makeAudio();
  await begin(audio, 2);
  audio.startLive(item(2), 1);
  audio.stopLive();
  await flush();
  const old = pending.shift();
  const oldQueue = audio.liveQueue;
  audio.clear();
  await begin(audio, 3);
  audio.startLive(item(3), 1);
  const drained = audio.drainLive();
  await flush();
  assert.equal(pending.length, 1, 'A detached request blocked transcription for the replacement interview');
  pending.shift().resolve({ transcript: 'new interview words' });
  await drained;
  old.resolve({ transcript: 'belongs to prior interview' });
  await oldQueue;
  assert.equal(texts.length, 1, 'A detached ASR result reached the replacement interview');
  assert.equal(texts[0][1], 'new interview words');
  audio.clear();
}
// Browser recognition must preserve final results during drain and discard detached callbacks.
{
  const { audio, texts } = makeAudio();
  await begin(audio, 4);
  audio.startLive(item(4, false), 1);
  const recognition = recognizers.at(-1);
  const result = text => ({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal: true })] });
  recognition.finalOnStop = result('last browser words');
  await audio.drainLive();
  assert.equal(texts[0][1], 'last browser words');
  audio.clear();
  await begin(audio, 5);
  recognition.onresult(result('detached browser result'));
  assert.equal(texts.length, 1, 'Detached browser recognition reached the replacement interview');
  audio.clear();
}
