/** Microphone check, continuous session audio and independent live transcription. */
import { api } from "./api.js?v=20261114-ui-v17";
import { el, button, notify, run } from "./ui.js?v=20261114-ui-v17";

async function microphone() {
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
    throw new Error("当前浏览器不支持录音，请使用新版 Chrome / Edge，通过 HTTPS 或 localhost 访问。");
  try {
    return await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    throw new Error(error.name === "NotAllowedError"
      ? "麦克风权限未开启，请在浏览器地址栏允许使用麦克风后重试。"
      : "无法使用麦克风，请检查设备连接和系统录音权限。");
  }
}
const stopTracks = (stream) => stream?.getTracks().forEach(track => track.stop());
const options = (bitrate = 64000) => {
  const mimeType = ["audio/webm;codecs=opus", "audio/mp4", "audio/ogg;codecs=opus"]
    .find(type => MediaRecorder.isTypeSupported(type));
  return { audioBitsPerSecond: bitrate, ...(mimeType ? { mimeType } : {}) };
};
let testCleanup = null;
let tested = false;
export function stopMicrophoneTest() {
  testCleanup?.();
  testCleanup = null;
}
export function microphoneCheck() {
  const card = el("section", "", "microphone-check");
  card.append(el("h3", "开始前，检查一下麦克风"),
    el("p", "录一小段话并试听，确认声音清晰。测试音频仅保留在当前页面，不会上传。"));
  const status = el("p", tested ? "✓ 已完成麦克风检测，可再次检查" : "尚未检测麦克风", "microphone-status");
  status.setAttribute("role", "status");
  const level = el("meter");
  level.min = 0; level.max = 1; level.value = 0;
  level.setAttribute("aria-label", "麦克风输入音量");
  const player = el("audio");
  player.controls = true; player.hidden = true;
  player.setAttribute("aria-label", "麦克风测试试听");
  const finish = button("停止检测并试听", () => { testRecorder?.stop(); }, "button secondary");
  finish.hidden = true;
  let testRecorder;
  const start = button("检测麦克风", async () => {
    stopMicrophoneTest();
    const stream = await microphone();
    let recorder;
    try { recorder = new MediaRecorder(stream, options()); }
    catch (error) { stopTracks(stream); throw error; }
    testRecorder = recorder;
    const chunks = [];
    let url, context, frame, limit;
    const cleanup = () => {
      clearTimeout(limit);
      cancelAnimationFrame(frame);
      if (recorder.state !== "inactive") { recorder.onstop = null; recorder.stop(); }
      stopTracks(stream);
      if (context && context.state !== "closed") void context.close();
      if (url) URL.revokeObjectURL(url);
      start.hidden = false; finish.hidden = true; level.value = 0;
    };
    testCleanup = cleanup;
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      if (AudioContext) {
        context = new AudioContext();
        await context.resume();
        const analyser = context.createAnalyser();
        context.createMediaStreamSource(stream).connect(analyser);
        const samples = new Uint8Array(analyser.fftSize);
        const tick = () => {
          analyser.getByteTimeDomainData(samples);
          level.value = Math.min(1, Math.sqrt(samples.reduce((sum, v) => sum + ((v - 128) / 128) ** 2, 0) / samples.length) * 4);
          frame = requestAnimationFrame(tick);
        };
        tick();
      }
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onstop = () => {
        clearTimeout(limit); cancelAnimationFrame(frame); stopTracks(stream);
        if (context && context.state !== "closed") void context.close();
        url = URL.createObjectURL(new Blob(chunks, { type: recorder.mimeType }));
        player.src = url; player.hidden = false;
        tested = true;
        status.textContent = "✓ 已采集测试声音，请点击播放确认音量和清晰度。";
        start.hidden = false; finish.hidden = true; level.value = 0;
      };
      recorder.onerror = () => { cleanup(); status.textContent = "检测录音异常，请检查设备后重试。"; };
      recorder.start();
      status.textContent = "正在检测，请说一句话，观察音量条并试听。";
      start.hidden = true; finish.hidden = false; player.hidden = true;
      limit = setTimeout(() => { if (recorder.state !== "inactive") recorder.stop(); }, 5000);
    } catch (error) { cleanup(); throw error; }
  }, "button secondary");
  card.append(status, level, start, finish, player);
  return card;
}

/** One MediaRecorder survives all stage renders; checkpoints retain the WebM header. */
export class SessionAudio {
  constructor({ changed, text, interrupted }) {
    this.changed = changed; this.text = text; this.interrupted = interrupted;
    this.current = null; this.prepared = null; this.queue = Promise.resolve();
    this.liveQueue = Promise.resolve(); this.live = null; this.liveError = ""; this.backupError = "";
  }
  get active() { return !!this.current && !this.current.stopped; }
  get pending() { return !!this.current && !this.active && !this.current.saved; }
  async prepare() {
    if (this.pending) throw new Error("请先保存或下载并处理上一段录音，再恢复录音。");
    stopMicrophoneTest(); this.prepared = await microphone();
  }
  cancelPrepared() { stopTracks(this.prepared); this.prepared = null; }
  async begin(item) {
    if (this.active) return;
    if (this.pending) {
      this.cancelPrepared();
      throw new Error("上一段录音尚未保存，请先重试上传，避免覆盖本地声音。");
    }
    if (!this.prepared) await this.prepare();
    const stream = this.prepared;
    this.prepared = null;
    try {
      const media = new MediaRecorder(stream, options(item.recording_options.bitrate));
      const part = await api(`/interviews/${item.id}/recordings`, { method: "POST" });
      const current = { iid: item.id, rid: part.id, media, stream, chunks: [], stopped: false, saved: false };
      this.current = current;
      current.completed = new Promise(resolve => { current.resolve = resolve; });
      media.ondataavailable = event => { if (event.data.size) current.chunks.push(event.data); };
      media.onstop = () => {
        current.stopped = true; clearInterval(current.checkpointTimer); stopTracks(stream);
        current.resolve(); this.changed();
      };
      media.onerror = () => this.interrupted("录音设备发生异常，本轮面试将结束并保存已采集的声音。");
      stream.getAudioTracks().forEach(track => { track.onended = () => {
        if (!current.stopped) this.interrupted("麦克风已断开，本轮面试将结束并保存已采集的声音。");
      }; });
      media.start(1000);
      current.checkpointTimer = setInterval(() => {
        void this.checkpoint().catch(error => { this.backupError = `录音备份失败：${error.message}。本地录音仍保留，结束时会重试保存。`; this.changed(); });
      }, item.recording_options.checkpoint_seconds * 1000);
      this.changed();
    } catch (error) { stopTracks(stream); throw error; }
  }
  async snapshot() {
    const c = this.current;
    if (!c) return null;
    if (!c.stopped && c.media.state === "recording") {
      await new Promise(resolve => {
        c.media.addEventListener("dataavailable", resolve, { once: true });
        c.media.requestData();
      });
    } else await c.completed;
    return new Blob(c.chunks, { type: c.media.mimeType });
  }
  async upload(final) {
    const c = this.current;
    if (!c) return;
    const blob = await this.snapshot();
    if (!blob?.size) throw new Error("尚未采集到录音，请确认麦克风后重试。");
    const form = new FormData();
    form.append("file", blob, "session.webm"); form.append("final", String(final));
    const item = await api(`/interviews/${c.iid}/recordings/${c.rid}`, { method: "PUT", body: form });
    if (final) c.saved = true;
    this.backupError = "";
    this.changed();
    return item;
  }
  checkpoint() {
    this.queue = this.queue.catch(() => {}).then(() => this.upload(false));
    return this.queue;
  }
  stopCapture() {
    const c = this.current;
    if (!c || c.stopped) return;
    clearInterval(c.checkpointTimer);
    this.stopLive();
    c.stopped = true;
    if (c.media.state !== "inactive") c.media.stop();
    stopTracks(c.stream);
  }
  async finalize() {
    if (!this.current) return;
    this.stopCapture();
    await this.queue.catch(() => {});
    if (this.current.saved) return;
    return this.upload(true);
  }
  download() {
    const c = this.current;
    if (!c?.chunks.length) return;
    const url = URL.createObjectURL(new Blob(c.chunks, { type: c.media.mimeType }));
    const link = el("a"); link.href = url; link.download = `interview-${c.iid}-${c.rid}.webm`;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  stopLive() {
    const live = this.live;
    this.live = null;
    if (!live) return;
    clearTimeout(live.timer);
    live.recognition?.stop();
    if (live.media?.state === "recording") live.media.stop();
  }
  async drainLive() {
    const live = this.live;
    this.stopLive();
    if (live?.completed) {
      if (live.recognition) await Promise.race([live.completed, new Promise(resolve => setTimeout(resolve, 1500))]);
      else await live.completed;
    }
    await this.liveQueue;
  }
  startLive(item, stage) {
    if (!this.active || this.live?.stage === stage) return;
    this.stopLive();
    const current = this.current;
    this.liveError = "";
    const live = { stage };
    this.live = live;
    if (item.server_asr_available) {
      const recordChunk = () => {
        if (this.live !== live || !this.active) return;
        const media = new MediaRecorder(this.current.stream, options(item.recording_options.bitrate));
        live.media = media;
        const chunks = [];
        live.completed = new Promise(resolve => { live.resolve = resolve; });
        media.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
        media.onstop = () => {
          if (this.current !== current) { live.resolve(); return; }
          const blob = new Blob(chunks, { type: media.mimeType });
          this.liveQueue = this.liveQueue.then(async () => {
            if (!blob.size || this.current !== current) return;
            const form = new FormData(); form.append("file", blob, "speech.webm");
            const result = await api(`/interviews/${item.id}/answers/${stage}/live-transcribe`, { method: "POST", body: form });
            if (this.current === current) this.text(stage, result.transcript, "");
          }).catch(error => {
            if (this.current !== current) return;
            this.liveError = `实时转写暂不可用：${error.message}，全程录音继续保存。`; this.changed();
          });
          live.resolve(); recordChunk();
        };
        media.onerror = () => {
          if (this.current !== current) return;
          this.liveError = "实时转写音频采集失败，全程录音继续保存。"; this.changed();
        };
        media.start();
        live.timer = setTimeout(() => { if (media.state === "recording") media.stop(); }, item.recording_options.live_chunk_seconds * 1000);
      };
      recordChunk();
    } else {
      const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!Speech) {
        this.liveError = "当前浏览器不支持实时转写，且未配置语音识别服务。可继续作答，全程录音仍会保存。";
        this.changed(); return;
      }
      const speech = new Speech(); live.recognition = speech;
      speech.continuous = true; speech.interimResults = true;
      speech.lang = (item.workflow_version >= 5 ? stage === 4 : stage === 2) ? "en-US" : "zh-CN";
      speech.onresult = event => {
        if (this.current !== current) return;
        let final = "", interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
          if (event.results[i].isFinal) final += event.results[i][0].transcript;
          else interim += event.results[i][0].transcript;
        }
        this.text(stage, final, interim);
      };
      speech.onerror = event => {
        if (this.current !== current) return;
        if (event.error === "no-speech" || event.error === "aborted") return;
        live.failed = true;
        this.liveError = "浏览器实时识别不可用，请检查网络及语音权限，或配置语音识别服务；全程录音继续保存。";
        this.changed();
      };
      live.completed = new Promise(resolve => { live.resolve = resolve; });
      speech.onend = () => {
        live.resolve();
        if (this.live === live && this.active && !live.failed) {
          try { speech.start(); } catch (error) { this.liveError = "实时识别已停止，全程录音继续保存。"; this.changed(); }
        }
      };
      try { speech.start(); } catch (error) { this.liveError = "无法启动实时识别，全程录音继续保存。"; this.changed(); }
    }
    this.changed();
  }
  clear() {
    this.stopCapture(); this.cancelPrepared();
    this.current = null;
    this.liveQueue = Promise.resolve();
    this.liveError = ""; this.backupError = "";
  }
}
