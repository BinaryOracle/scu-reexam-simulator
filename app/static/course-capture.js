/** Pre-authorized browser capture starts sending only when the scheduled window opens. */
import { api } from "./api.js?v=20261114-ui-v17";

let active;
const MIME = ["video/webm;codecs=vp8,opus", "video/webm;codecs=vp9,opus"];
const now = capture => (Date.now() + capture.clockOffset) / 1000;

export function getCapture() { return active; }

function update(capture, stage, message) {
  capture.stage = stage;
  capture.message = message;
  capture.onChange(capture);
}

function dispose(capture, message, error = false, refresh = false) {
  if (active !== capture) return;
  active = null;
  clearInterval(capture.timer);
  clearTimeout(capture.timeout);
  clearTimeout(capture.closeTimeout);
  if (capture.recorder?.state === "recording") capture.recorder.stop();
  capture.tracks.forEach(track => track.stop());
  capture.socket?.close();
  capture.onChange(null, { message, error, refresh });
}

export function cancelCapture() {
  if (active) dispose(active);
}

export function stopCapture() {
  const capture = active;
  if (!capture || capture.stage === "finishing") return;
  if (capture.stage !== "live") {
    dispose(capture, "已取消开播准备");
    return;
  }
  clearInterval(capture.timer);
  update(capture, "finishing", "正在保存直播回放，请稍候…");
  if (capture.recorder.state === "recording") capture.recorder.stop();
  capture.closeTimeout = setTimeout(() => dispose(capture, "回放仍在处理，请刷新课程查看", false, true), 18000);
}

async function openBroadcast(capture) {
  if (active !== capture || capture.stage !== "armed") return;
  clearInterval(capture.timer);
  update(capture, "connecting", "正在连接直播服务器…");
  try {
    await api("/courses/media-access", { method: "POST" });
    if (active !== capture) return;
    const url = new URL(`/api/course-media/${capture.cid}/lessons/${capture.lid}/publish`, location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const socket = capture.socket = new WebSocket(url);
    capture.timeout = setTimeout(() => dispose(capture, "连接直播服务器超时", true, true), 15000);
    socket.addEventListener("close", () => {
      if (active === capture) dispose(capture, capture.serverError || "直播连接已断开，已接收的画面会尝试保存为回放", true, true);
    });
    socket.addEventListener("message", ({ data }) => {
      if (active !== capture) return;
      const info = JSON.parse(data);
      if (info.error) {
        capture.serverError = info.error;
        return;
      }
      if (info.finished) {
        dispose(capture, info.replay_saved ? "直播已结束，回放已保存" : capture.serverError || "直播未产生可播放的画面", !info.replay_saved, true);
        return;
      }
      if (info.stop) {
        stopCapture();
        return;
      }
      if (info.ready && capture.stage === "connecting") {
        clearTimeout(capture.timeout);
        try {
          const recorder = capture.recorder = new MediaRecorder(capture.stream, {
            mimeType: capture.mime, videoBitsPerSecond: 1500000, audioBitsPerSecond: 96000,
          });
          recorder.addEventListener("dataavailable", ({ data: chunk }) => {
            if (active !== capture || !chunk.size || socket.readyState !== WebSocket.OPEN) return;
            if (socket.bufferedAmount > 8 * 1024 * 1024 || chunk.size > 4 * 1024 * 1024) {
              dispose(capture, "直播网络传输积压，已接收的画面会尝试保存为回放", true, true);
              return;
            }
            socket.send(chunk);
          });
          recorder.addEventListener("error", () => dispose(capture, "浏览器录制失败，已接收的画面会尝试保存", true, true));
          recorder.addEventListener("stop", () => {
            if (active === capture && socket.readyState === WebSocket.OPEN) socket.send("finish");
          });
          recorder.start(1000);
          update(capture, "live", "正在直播 · 学员端画面会有数秒延迟");
          capture.timer = setInterval(() => {
            if (now(capture) >= info.ends_at) stopCapture();
          }, 250);
        } catch (error) {
          dispose(capture, error.message || "无法开始录制", true, true);
        }
      }
    });
  } catch (error) {
    dispose(capture, error.message, true, true);
  }
}

export async function prepareCapture({ cid, lesson, source, serverTime, receivedAt, onChange }) {
  if (active) throw new Error("当前已有直播正在准备或进行中");
  const devices = navigator.mediaDevices;
  if (!devices?.getUserMedia || !globalThis.MediaRecorder)
    throw new Error("请在 HTTPS 网站或 localhost 上使用支持录制的 Chrome / Edge");
  const mime = MIME.find(value => MediaRecorder.isTypeSupported(value));
  if (!mime) throw new Error("当前浏览器不支持 WebM 直播录制，请使用新版 Chrome / Edge");
  if (source === "screen" && !devices.getDisplayMedia) throw new Error("当前浏览器不支持屏幕共享");
  const clockOffset = serverTime * 1000 - receivedAt;
  if ((Date.now() + clockOffset) / 1000 >= lesson.live_end) throw new Error("直播时段已结束，请重新设置排期");
  const capture = active = { cid, lid: lesson.id, mime, clockOffset, onChange, tracks: [] };
  update(capture, "preparing", "正在获取设备授权…");
  function take(stream) {
    const tracks = stream.getTracks();
    if (active !== capture) {
      tracks.forEach(track => track.stop());
      throw new Error("已取消直播准备");
    }
    capture.tracks.push(...tracks);
    return stream;
  }
  try {
    if (source === "screen") {
      const screen = take(await devices.getDisplayMedia({ video: { frameRate: { ideal: 24, max: 30 } }, audio: false }));
      const mic = take(await devices.getUserMedia({ audio: true, video: false }));
      capture.stream = new MediaStream([...screen.getVideoTracks(), ...mic.getAudioTracks()]);
    } else {
      capture.stream = take(await devices.getUserMedia({
        audio: true, video: { width: { ideal: 1280 }, height: { ideal: 720 }, frameRate: { ideal: 24, max: 30 } },
      }));
    }
    const tick = () => {
      if (now(capture) >= lesson.live_end) dispose(capture, "直播时段已结束，请重新设置排期", true);
      else if (now(capture) >= lesson.live_start + 0.25) void openBroadcast(capture);
    };
    for (const track of capture.tracks) {
      track.addEventListener("ended", () => {
        if (active !== capture) return;
        if (capture.stage === "live") stopCapture();
        else if (capture.stage !== "finishing") dispose(capture, "摄像头、麦克风或屏幕共享已停止", true);
      }, { once: true });
      if (track.readyState === "ended") throw new Error("摄像头、麦克风或屏幕共享已停止");
    }
    update(capture, "armed", "已就绪，到达排期后自动开播。请保持此页面打开。");
    capture.timer = setInterval(tick, 250);
    tick();
  } catch (error) {
    dispose(capture, error.name === "NotAllowedError" ? "未授予摄像头、麦克风或屏幕共享权限" : error.message, true);
  }
}
