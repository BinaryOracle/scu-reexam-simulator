import { SessionAudio, microphoneCheck, stopMicrophoneTest } from "./interview-audio.js?v=20261115-interview-recovery-v1";
import {
  presentationView,
  releasePresentation,
  clearPresentation,
} from "./presentation.js?v=20261115-mouse-navigation-v1";
import { api, audioBlob, state } from "./api.js?v=20261114-ui-v17";
import {
  $,
  el,
  button,
  badge,
  emptyState,
  dateTime,
  notify,
  confirmAction,
  requestText,
  run,
  renderPagination,
} from "./ui.js?v=20261114-ui-v18";

let activeInterview = null;
let selectedStage = 1;
let recording = null;
let uploading = false;
let ending = false;
const feedbackRequests = new Map();
const feedbackViewDirty = new Set();
const openUserArchives = new Set();
let archiveQuery = "";
let archivePage = 1;
let interviewQuery = "";
let interviewPage = 1;
let interviewItems = [];
const interviewPageSize = 8;
let timerHandle = null;
let timerInterviewId = null;
let timerDock = null;
let timerFullscreenListener = null;
let interviewClock = null;
let preparationFile = null;
const drafts = new Map();
const interimTexts = new Map();
const transcriptionNotices = new Map();
const collapsedFeedback = new Set();
let liveSaveTimer = null;

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape" || document.querySelector("dialog[open]")) return;
  const drawer = document.querySelector(".stage-drawer.is-open");
  const toggle = drawer?.querySelector(".stage-drawer-toggle");
  if (!toggle) return;
  event.preventDefault();
  toggle.focus();
  toggle.click();
});
let expertSpeechPlaying = false;
let stageSpeech = null;
const sessionAudio = new SessionAudio({
  changed: updateRecordingStatus,
  text: receiveLiveText,
  interrupted: (message) => { notify(message, "error"); void run(() => endCurrentInterview({ automatic: true })); },
});
function updateRecordingStatus() {
  document.querySelectorAll(".session-recording-status").forEach(node => {
    node.textContent = sessionAudio.active ? "● 全程录音中 · 切换环节不中断" : sessionAudio.pending ? "录音待保存，请重试上传" : "全程录音已停止";
    node.classList.toggle("is-recording", sessionAudio.active);
  });
  const notice = $("interviewRecordingNotice");
  if (notice) {
    notice.textContent = [sessionAudio.backupError, sessionAudio.liveError].filter(Boolean).join(" ");
    notice.hidden = !notice.textContent;
  }
}
function receiveLiveText(stage, final, interim) {
  const item = activeInterview;
  if (!item || !sessionAudio.current || sessionAudio.current.iid !== item.id) return;
  const answer = item.answers.find(entry => entry.stage === stage);
  if (!answer) return;
  const key = answerKey(item.id, stage);
  if (final.trim()) {
    const value = drafts.get(key) ?? answer.transcript;
    drafts.set(key, (value + (value && !value.endsWith("\n") ? "\n" : "") + final.trim()).slice(0, 20000));
  }
  interimTexts.set(key, interim);
  if (selectedStage === stage) {
    const input = $("answerTranscript");
    if (input) input.value = drafts.get(key) ?? answer.transcript;
    const preview = $("liveInterim");
    if (preview) preview.textContent = interim;
    const status = document.querySelector(".save-state");
    if (status) { status.textContent = "实时转写已更新"; status.classList.add("dirty"); }
  }
  clearTimeout(liveSaveTimer);
  if (final.trim() && !ending && !item.timed_out && item.status !== "finished")
    liveSaveTimer = setTimeout(() => {
      if (!uploading && !ending) void saveDrafts().catch(error => notify(`转写文字尚未保存：${error.message}`, "error"));
    }, 800);
}
function allowInteraction() {
  if (recording || uploading || ending) {
    notify("正在录音保存或处理，请稍候。", "info");
    return false;
  }
  return true;
}
function resumeLiveTranscription() {
  const item = activeInterview;
  if (expertSpeechPlaying || !item || item.workflow_version < 4 || !sessionAudio.active || ending ||
      reviewMode() || item.status === "finished" || item.timed_out) return;
  const target = selectedStage === 1 && item.intro_completed ? null : selectedStage;
  const ready = item.workflow_version < 5 || ![2, 3, 4].includes(target) ||
    item.answers.find(answer => answer.stage === target)?.question_choices;
  if (target && ready) sessionAudio.startLive(item, target);
  else sessionAudio.stopLive();
}
async function switchStage(stage) {
  if (!allowInteraction()) return;
  const item = activeInterview;
  if (stage === selectedStage) return;
  cancelStageSpeech();
  if (stage === item.expert_stage && !item.answers.some(answer => answer.stage === stage)) {
    if (!reviewMode() && item.status !== "finished" && !item.timed_out) await enterExpert();
    return;
  }
  uploading = true;
  try {
    if (sessionAudio.active) await sessionAudio.drainLive();
    if (activeInterview.status !== "finished" && !activeInterview.timed_out) await saveDrafts();
    if (!reviewMode() && activeInterview.workflow_version >= 5 &&
        activeInterview.status !== "finished" && !activeInterview.timed_out && (stage === 3 || stage === 4))
      activeInterview = await api(`/interviews/${activeInterview.id}/draw-question/${stage}`, { method: "POST" });
    selectedStage = stage;
    renderInterview();
    window.scrollTo({ top: 0, behavior: "instant" });
  } finally { uploading = false; resumeLiveTranscription(); }
  void announceStage(activeInterview, stage);
}
const audioUrls = new Set();
const sessionPlaybackUrls = new Set();
let playbackPanel = null;
let playbackSignature = null;
const answerKey = (id, stage) => `${id}:${stage}`;
const stageName = (answer, item) => answer.stage === item.expert_stage ? "专家问答"
  : answer.stage === 1 && item.workflow_version >= 2 ? "PPT 自我介绍"
  : (item.workflow_version >= 5 ? { 2: "专业课问答", 3: "英文翻译", 4: "英文问答" }[answer.stage] : null) || `第 ${answer.stage} 个环节`;
function answerIsComplete(item, answer) {
  if (answer.stage === 1 && item.workflow_version >= 2) return Boolean(item.intro_completed);
  return Boolean(answer.transcript?.trim() || answer.has_audio);
}
const reviewMode = () => state.adminMode;
const interviewPath = (path) => `${reviewMode() ? "/admin" : ""}${path}`;
const resumeKey = () => `scu:${state.user.id}:interview-in-session`;
function startRequestKey(file) {
  const storageKey = `${resumeKey()}:start`;
  const identity = JSON.stringify([file.name, file.size, file.lastModified]);
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || "null");
    if (saved?.identity === identity && /^[0-9a-f-]{36}$/i.test(saved.key)) return saved.key;
  } catch (error) { /* The current preparation keeps its request key in memory. */ }
  const key = crypto.randomUUID();
  try { sessionStorage.setItem(storageKey, JSON.stringify({ identity, key })); }
  catch (error) { /* Retry remains stable until the preparation page is left. */ }
  return key;
}
function clearStartRequestKey(key) {
  try {
    const storageKey = `${resumeKey()}:start`;
    if (JSON.parse(sessionStorage.getItem(storageKey) || "null")?.key === key)
      sessionStorage.removeItem(storageKey);
  } catch (error) { /* A completed start does not depend on browser storage. */ }
}
function rememberTranscriptionResult(key, transcript) {
  if (transcript.trim()) transcriptionNotices.delete(key);
  else transcriptionNotices.set(key, "没有识别到语音内容，请检查录音或直接填写回答。");
}
function rememberInterview(item) {
  if (reviewMode() || !item.id) return;
  try {
    if (item.status === "finished") {
      if (sessionStorage.getItem(resumeKey()) === String(item.id)) sessionStorage.removeItem(resumeKey());
    } else if (item.started_at) sessionStorage.setItem(resumeKey(), item.id);
  } catch (error) { /* Recording remains usable when browser storage is disabled. */ }
}

/** Keep navigation from abandoning an active recording or upload. */
export function allowNavigation() {
  if (sessionAudio.active || sessionAudio.pending) {
    notify("请先结束本轮面试并保存全程录音，再离开面试页面。", "info");
    return false;
  }
  if (recording || uploading || ending) {
    notify(
      recording
        ? "请先停止录音并保存，再离开当前页面。"
        : "文件正在处理或保存，请稍候。",
      "info",
    );
    return false;
  }
  return true;
}
export function hasUnsavedWork() {
  return sessionAudio.active || sessionAudio.pending || recording || uploading || ending || drafts.size > 0 || Boolean(preparationFile);
}
export function pauseInterviewAudio() {
  cancelStageSpeech();
  document
    .querySelectorAll("#interviewDetail audio")
    .forEach((audio) => audio.pause());
}
function releaseStageMedia() {
  cancelStageSpeech();
  document.querySelectorAll("#interviewDetail .answer-content audio").forEach(audio => audio.pause());
  releasePresentation();
  audioUrls.forEach((url) => URL.revokeObjectURL(url));
  audioUrls.clear();
}
/** Cancel both an in-flight speech request and playback when leaving its stage. */
function cancelStageSpeech() {
  const task = stageSpeech;
  stageSpeech = null;
  task?.controller.abort();
  task?.audio?.pause();
  task?.resolve?.();
  if (task?.audio?.hidden) task.audio.remove();
  expertSpeechPlaying = false;
}
function speechIsCurrent(task) {
  return stageSpeech === task && !task.controller.signal.aborted && state.token === task.token &&
    activeInterview?.id === task.iid && selectedStage === task.stage &&
    activeInterview.status !== "finished" && !activeInterview.timed_out &&
    !$("interview").hidden && !$("interviewDetail").hidden;
}
async function speechBlob(path, task) {
  const response = await fetch(`/api${path}`, {
    method: "POST", signal: task.controller.signal,
    headers: { Authorization: `Bearer ${task.token}` },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "语音播报暂不可用");
  }
  return response.blob();
}
async function playStageSpeech(blob, task, expert = false) {
  if (!speechIsCurrent(task)) return;
  await sessionAudio.drainLive();
  if (!speechIsCurrent(task)) return;
  const player = el("audio");
  player.hidden = true;
  player.setAttribute("aria-label", expert ? "专家问题语音播报" : "当前环节语音提示");
  const url = URL.createObjectURL(blob);
  audioUrls.add(url);
  player.src = url;
  task.audio = player;
  $("interviewDetail").append(player);
  let resolvePlayback;
  const completed = new Promise(resolve => { resolvePlayback = resolve; });
  task.resolve = resolvePlayback;
  const done = () => {
    expertSpeechPlaying = false;
    resumeLiveTranscription();
    resolvePlayback();
  };
  player.addEventListener("play", () => { expertSpeechPlaying = true; sessionAudio.stopLive(); });
  player.addEventListener("ended", done);
  player.addEventListener("pause", done);
  player.addEventListener("error", () => resolvePlayback(new Error("语音播放失败，可点击环节播报重试。")));
  const aborted = () => { player.pause(); resolvePlayback(); };
  task.controller.signal.addEventListener("abort", aborted, { once: true });
  try {
    await player.play();
    const failure = await completed;
    if (failure) throw failure;
  } finally {
    task.controller.signal.removeEventListener("abort", aborted);
    task.resolve = null;
    player.remove(); URL.revokeObjectURL(url); audioUrls.delete(url);
  }
}
/** Announce only actual live-stage entries; reviewing never starts speech automatically. */
async function announceStage(item, stage) {
  if (!item?.started_at || reviewMode() || item.status === "finished" || item.timed_out || activeInterview?.id !== item.id) return;
  cancelStageSpeech();
  const task = { iid: item.id, stage, token: state.token, controller: new AbortController() };
  stageSpeech = task;
  try {
    const introduction = await speechBlob(`/interviews/${item.id}/stage-speech/${stage}`, task);
    await playStageSpeech(introduction, task);
    if (stage === item.expert_stage && speechIsCurrent(task)) {
      const blob = await speechBlob(`/interviews/${item.id}/expert-speech`, task);
      await playStageSpeech(blob, task, true);
    }
  } catch (error) {
    if (!task.controller.signal.aborted && speechIsCurrent(task))
      notify(error.name === "NotAllowedError" ? "浏览器未允许自动播报，可点击「环节播报」播放。" : `播报未完成：${error.message}，可点击「环节播报」重试。`, "info");
  } finally {
    if (stageSpeech === task) {
      stageSpeech = null;
      expertSpeechPlaying = false;
      resumeLiveTranscription();
    }
  }
}
function releaseSessionPlayback() {
  playbackPanel?.querySelectorAll("audio").forEach(audio => audio.pause());
  playbackPanel?.remove();
  playbackPanel = null;
  playbackSignature = null;
  sessionPlaybackUrls.forEach(url => URL.revokeObjectURL(url));
  sessionPlaybackUrls.clear();
}
function releaseAudio() {
  releaseStageMedia();
  releaseSessionPlayback();
}
function stopInterviewTimer() {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = null;
  timerInterviewId = null;
  timerDock?.remove();
  timerDock = null;
  document.body.classList.remove("has-interview-timer");
  if (timerFullscreenListener)
    document.removeEventListener("fullscreenchange", timerFullscreenListener);
  timerFullscreenListener = null;
}
function renderInterviewTimer(item) {
  stopInterviewTimer();
  if (item.workflow_version < 3 || !item.started_at || item.status === "finished") return;
  const timer = el("aside", "", "interview-timer");
  timer.setAttribute("aria-label", "面试倒计时");
  const alarm = el("span", "", "interview-alarm");
  alarm.setAttribute("aria-hidden", "true");
  alarm.append(el("span", "", "alarm-face"), el("span", "", "alarm-feet"));
  const copy = el("div", "", "interview-timer-copy");
  const label = el("span", "剩余时间", "interview-timer-label");
  const hint = el("span", "整场严格限时，请合理安排作答", "interview-timer-hint");
  copy.append(label, hint);
  const value = el("strong", "", "interview-timer-value");
  value.setAttribute("role", "timer");
  value.setAttribute("aria-live", "off");
  const minutes = el("span", "", "timer-digits");
  const seconds = el("span", "", "timer-digits");
  value.append(minutes, el("span", ":", "timer-colon"), seconds);
  const warning = el("span", "", "interview-timer-warning");
  warning.setAttribute("role", "status");
  const progress = el("div", "", "interview-timer-progress");
  progress.setAttribute("aria-hidden", "true");
  const fill = el("span");
  progress.append(fill);
  const content = el("div", "", "interview-timer-content");
  content.append(alarm, copy, value, warning);
  timer.append(content, progress);
  if (!reviewMode() && item.workflow_version >= 4) {
    timer.append(el("span", "", "session-recording-status"));
    updateRecordingStatus();
  }
  timerDock = timer;
  document.body.classList.add("has-interview-timer");
  // Fullscreen hides elements outside its subtree; move this same clock with it.
  timerFullscreenListener = () => {
    const fullscreen = document.fullscreenElement;
    const host = fullscreen?.matches(".presentation-session") ? fullscreen : document.body;
    host.prepend(timer);
  };
  document.addEventListener("fullscreenchange", timerFullscreenListener);
  timerFullscreenListener();
  timerInterviewId = item.id;
  if (!interviewClock || interviewClock.id !== item.id || interviewClock.deadline !== item.deadline_at) {
    interviewClock = {
      id: item.id,
      deadline: item.deadline_at,
      remaining: item.remaining_seconds ?? item.duration_seconds,
      anchor: performance.now(),
    };
  }
  let expiredReloaded = false;
  const update = () => {
    if (timerInterviewId !== item.id) return;
    const remaining = item.timed_out ? 0 : Math.max(0, Math.ceil(interviewClock.remaining - (performance.now() - interviewClock.anchor) / 1000));
    minutes.textContent = String(Math.floor(remaining / 60)).padStart(2, "0");
    seconds.textContent = String(remaining % 60).padStart(2, "0");
    value.setAttribute("aria-label", `剩余 ${Math.floor(remaining / 60)} 分 ${remaining % 60} 秒`);
    const isWarning = remaining <= (item.warning_seconds || 60);
    timer.classList.toggle("warning", isWarning);
    timer.classList.toggle("expired", remaining <= 0);
    fill.style.transform = `scaleX(${Math.min(1, remaining / item.duration_seconds)})`;
    const message = remaining <= 0 ? "时间已到，已停止作答" : isWarning ? "即将结束，请完成当前回答" : "";
    if (warning.textContent !== message) warning.textContent = message;
    hint.textContent = message || "整场严格限时，请合理安排作答";
    if (remaining <= 0 && !expiredReloaded && !item.timed_out) {
      expiredReloaded = true;
      clearInterval(timerHandle);
      timerHandle = null;
      notify("面试时间已到，已停止继续作答。", "info");
      if (item.workflow_version >= 4 && sessionAudio.current?.iid === item.id) {
        sessionAudio.stopCapture();
        void run(() => endCurrentInterview({ automatic: true }));
      } else if (recording) {
        recording.deadlineReached = true;
        recording.recorder.stop();
      } else void openInterview(item.id, selectedStage);
    }
  };
  update();
  if (!expiredReloaded && !item.timed_out) timerHandle = setInterval(update, 1000);
}
export async function refreshInterviews() {
  if (activeInterview && feedbackViewDirty.has(activeInterview.id) &&
      !$("interview").hidden && !$("interviewDetail").hidden) renderInterview();
  if (!reviewMode()) {
    state.user = await api("/me");
    $("interviewQuotaText").textContent = state.user.is_admin ? "模拟面试已开通" : `剩余 ${state.user.interview_credits} 次模拟面试 · 正式开始时消耗 1 次`;
  }
  $("interviewQuota").hidden = reviewMode();
  const allItems = await api(interviewPath("/interviews"));
  if (!reviewMode() && $("interviewDetail").hidden) {
    let resumeId;
    try { resumeId = Number(sessionStorage.getItem(resumeKey())); }
    catch (error) { /* A restricted browser can still start and finish a session. */ }
    if (allItems.some(item => item.id === resumeId && item.status !== "finished")) await openInterview(resumeId);
  }
  interviewItems = allItems.filter(item => item.status === "finished" || item.status === "expired");
  $("interviewFinished").textContent = interviewItems.length;
  renderInterviewList();
}
function renderInterviewList() {
  const list = $("interviewList");
  list.replaceChildren();
  list.classList.toggle("is-user-archive", reviewMode());
  $("interviewListToolbar").hidden = reviewMode() || !interviewItems.length;
  $("interviewPagination").hidden = reviewMode();
  if (!interviewItems.length) {
    list.append(
      emptyState(
        reviewMode() ? "还没有用户面试记录" : "你的第一次模拟，从这里开始",
        reviewMode()
          ? "用户完成练习后，可在这里查看回答、回听录音与复核点评。"
          : "点击「开始新面试」，逐环节完成练习；可在最后的专家问答中主动生成点评。",
      ),
    );
    return;
  }
  if (reviewMode()) {
    renderUserArchives(list, interviewItems, interviewItems.map(renderInterviewCard));
    return;
  }
  const query = interviewQuery.trim().toLocaleLowerCase();
  const matching = interviewItems.filter(item =>
    `${item.title || `计算机复试模拟 #${item.id}`} ${item.id} ${String(item.id).padStart(3, "0")} ${dateTime(item.created)}`
      .toLocaleLowerCase().includes(query),
  );
  $("interviewResultCount").textContent = query ? `匹配 ${matching.length} 场` : `共 ${matching.length} 场`;
  interviewPage = Math.min(interviewPage, Math.max(1, Math.ceil(matching.length / interviewPageSize)));
  if (!matching.length) list.append(emptyState("没有匹配的面试记录", "请尝试其他面试名称或编号。"));
  const start = (interviewPage - 1) * interviewPageSize;
  list.append(...matching.slice(start, start + interviewPageSize).map(renderInterviewCard));
  renderPagination($("interviewPagination"), interviewPage, matching.length, interviewPageSize, (page) => {
    interviewPage = page;
    renderInterviewList();
  });
}
$("interviewSearch").addEventListener("input", () => {
  interviewQuery = $("interviewSearch").value;
  interviewPage = 1;
  renderInterviewList();
});
function renderInterviewCard(item) {
    const closed = item.status === "finished" || item.status === "expired";
    const statusLabel = item.status === "expired" ? "已超时" : item.status === "finished" ? "已完成" : item.status === "preparing" ? "待开始" : "进行中";
    const card = el("article", "", "record-card");
    const top = el("div", "", "record-top");
    top.append(
      el(
        "span",
        `INTERVIEW / ${String(item.id).padStart(3, "0")}`,
        "record-code",
      ),
      badge(
        statusLabel,
        item.status === "finished" ? "green" : item.status === "expired" ? "red" : "orange",
      ),
    );
    const meta = el("div", "", "record-meta");
    meta.append(el("span", dateTime(item.created)));
    const bottom = el("div", "", "record-bottom");
    const actions = el("div", "", "record-actions");
    actions.append(button(
      closed ? "查看回顾 →" : reviewMode() ? "查看回答 →" : "继续面试 →",
      () => openInterview(item.id),
      "text-button",
    ));
    if (!reviewMode()) {
      actions.append(button("重命名", async () => {
        const current = item.title || `计算机复试模拟 #${item.id}`;
        const title = await requestText("重命名面试记录", current);
        if (title === null) return;
        await api(`/interviews/${item.id}`, { method: "PATCH", body: JSON.stringify({ title }) });
        await refreshInterviews();
        notify("面试记录名称已更新");
      }, "text-button record-action"));
      actions.append(button("删除", async () => {
        const title = item.title || `计算机复试模拟 #${item.id}`;
        if (!await confirmAction(`确定删除「${title}」及其录音和 PPT 吗？${item.status === "active" ? "这场面试正在进行，删除后将无法继续。" : ""}此操作无法撤销。`)) return;
        await api(`/interviews/${item.id}`, { method: "DELETE" });
        await refreshInterviews();
        notify("面试记录已删除");
      }, "text-button record-action danger"));
    }
    bottom.append(
      el(
        "span",
        item.status === "expired"
          ? "时间已到，回答已保存，可查看回顾"
          : item.status === "finished"
          ? feedbackRequests.has(item.id) ? "AI 点评正在生成，可先查看回答" : item.has_feedback ? "回答与点评已归档" : "面试已结束，回答已归档"
          : item.status === "preparing"
            ? "上传 PPT 后开始面试"
            : "按环节继续作答",
      ),
      actions,
    );
    card.append(top, el("h3", item.title || `计算机复试模拟 #${item.id}`), meta, bottom);
    return card;
}
/** Group authorized records by stable user ID, keeping each user's archive collapsed initially. */
function renderUserArchives(list, items, cards) {
  const groups = new Map();
  items.forEach((item, index) => {
    if (!groups.has(item.user_id)) groups.set(item.user_id, { id: item.user_id, name: item.username, latest: item.created, cards: [] });
    const group = groups.get(item.user_id);
    group.latest = Math.max(group.latest, item.created);
    group.cards.push(cards[index]);
  });
  const toolbar = el("div", "", "archive-toolbar");
  const searchLabel = el("label", "查找用户", "archive-search-label");
  const input = el("input");
  input.type = "search"; input.id = "interviewArchiveSearch";
  input.placeholder = "输入用户名查找面试归档"; input.value = archiveQuery;
  searchLabel.htmlFor = input.id;
  const count = el("span", `${groups.size} 位用户 · ${items.length} 场已完成面试`, "archive-count");
  toolbar.append(searchLabel, input, count);
  const results = el("div", "", "archive-groups");
  const pagination = el("nav", "", "list-pagination");
  const render = () => {
    results.replaceChildren();
    const matching = [...groups.values()].filter(group => group.name.toLocaleLowerCase().includes(archiveQuery.trim().toLocaleLowerCase()))
      .sort((a, b) => b.latest - a.latest);
    archivePage = Math.min(archivePage, Math.max(1, Math.ceil(matching.length / interviewPageSize)));
    if (!matching.length) results.append(emptyState("没有匹配的用户", "请尝试其他用户名。"));
    const start = (archivePage - 1) * interviewPageSize;
    for (const group of matching.slice(start, start + interviewPageSize)) {
      const archive = el("details", "", "archive-user");
      archive.open = openUserArchives.has(group.id);
      const summary = el("summary", "", "archive-user-summary");
      const icon = el("span", "▤", "archive-user-icon"); icon.setAttribute("aria-hidden", "true");
      const identity = el("div", "", "archive-user-identity");
      identity.append(el("h3", group.name), el("span", `最近面试 ${dateTime(group.latest)}`));
      summary.append(icon, identity, el("span", `${group.cards.length} 场面试`, "archive-user-total"));
      const records = el("div", "", "record-grid archive-user-records");
      records.append(...group.cards);
      archive.append(summary, records);
      archive.addEventListener("toggle", () => {
        if (archive.open) openUserArchives.add(group.id);
        else openUserArchives.delete(group.id);
      });
      results.append(archive);
    }
    renderPagination(pagination, archivePage, matching.length, interviewPageSize, (page) => {
      archivePage = page;
      render();
    });
  };
  input.addEventListener("input", () => { archiveQuery = input.value; archivePage = 1; render(); });
  list.append(toolbar, results, pagination);
  render();
}
export async function startInterview() {
  if (!allowNavigation()) return;
  state.user = await api("/me");
  if (!state.user.is_admin && state.user.interview_credits < 1) {
    notify("模拟面试次数已用完，请在个人主页兑换卡密后再开始。", "info");
    window.dispatchEvent(new Event("open-profile"));
    return;
  }
  const setup = await api("/interview-setup");
  preparationFile = null;
  activeInterview = { ...setup, id: null, status: "preparing", workflow_version: 5,
    started_at: null, presentation: null, intro_completed: false, answers: [] };
  renderInterview();
  $("interviewDetail").scrollIntoView({ block: "start", behavior: "smooth" });
}
export async function openInterview(id, stage) {
  if (!allowNavigation()) return;
  let item = await api(interviewPath(`/interviews/${id}`));
  if (!reviewMode() && item.timed_out && item.status !== "finished")
    item = await api(`/interviews/${id}/stop`, { method: "POST" });
  selectedStage =
    stage ||
    (item.status === "finished" ? 1 : null) ||
    (item.workflow_version >= 2 && !item.intro_completed ? 1 : null) ||
    item.answers.find((a) => !a.transcript.trim())?.stage ||
    item.answers[0]?.stage ||
    1;
  activeInterview = item;
  renderInterview();
  $("interviewDetail").scrollIntoView({ block: "start", behavior: "smooth" });
  void announceStage(item, selectedStage);
}
function renderInterview() {
  if (activeInterview) feedbackViewDirty.delete(activeInterview.id);
  if (!activeInterview) return;
  releaseStageMedia();
  const item = activeInterview;
  rememberInterview(item);
  const finished = item.status === "finished";
  const timedOut = item.timed_out || item.status === "expired";
  const readOnly = reviewMode() || finished || timedOut;
  const preparing =
    item.workflow_version >= 3 &&
    !item.started_at &&
    !readOnly;
  const root = $("interviewDetail");
  let container = root.querySelector(":scope > .interview-content");
  if (!container) {
    container = el("div", "", "interview-content");
    root.replaceChildren(container);
  }
  document.body.classList.toggle("interview-immersive", !preparing);
  root.dataset.immersive = String(!preparing);
  document.body.classList.remove("interview-shell-open");
  window.dispatchEvent(new Event("interview-layout-changed"));
  root.hidden = false;
  $("interviewOverview").hidden = true;
  $("newInterview").hidden = true;
  $("refreshInterviews").parentElement.hidden = true;
  $("interviewList").classList.add("compact");
  $("interviewListTitle").hidden = true;
  const topline = el("div", "", "detail-topline");
  const title = el("div", "", "detail-title");
  title.append(
    el("h2", item.id ? item.title || `面试 #${item.id}` : "面试准备"),
    badge(
      finished ? "已完成" : preparing ? "待开始" : timedOut ? "已超时" : "进行中",
      finished ? "green" : timedOut ? "red" : "orange",
    ),
  );
  if (!readOnly && item.started_at) title.append(button("环节播报", () => announceStage(activeInterview, selectedStage), "text-button stage-announcement-button"));
  topline.append(title);
  $("returnInterviews")?.remove();
  const back = button("← 返回面试记录", async () => {
    if (!reviewMode() && item.started_at && item.status !== "finished") {
      if (!await confirmAction("返回记录会结束当前面试并保存全程录音，不会生成 AI 点评。是否继续？")) return;
      await endCurrentInterview({ automatic: true });
    }
    if (!allowNavigation()) return;
    if (preparationFile && !await confirmAction("返回后需要重新选择 PPT，是否继续？", { title: "离开面试准备？", confirmText: "返回面试记录" })) return;
    preparationFile = null;
    activeInterview = null;
    document.body.classList.remove("interview-immersive", "interview-shell-open");
    window.dispatchEvent(new Event("interview-layout-changed"));
    stopMicrophoneTest();
    releaseAudio(); stopInterviewTimer();
    root.hidden = true;
    root.dataset.immersive = "false";
    $("interviewOverview").hidden = false;
    $("interviewList").classList.remove("compact");
    $("interviewListTitle").hidden = false;
    $("interviewListTitle").replaceChildren(
      document.createTextNode(reviewMode() ? "用户面试" : "我的面试"),
      el("span", reviewMode() ? "按用户归档" : "练习记录", "section-caption"),
    );
    $("refreshInterviews").parentElement.hidden = false;
    $("newInterview").hidden = reviewMode();
    $("returnInterviews")?.remove();
    window.scrollTo({ top: 0, behavior: "instant" });
    await refreshInterviews();
  }, "button secondary return-interviews-button");
  back.id = "returnInterviews";
  $("newInterview").parentElement.append(back);
  if (preparing) {
    stopInterviewTimer();
    const preparation = el("section", "", "panel interview-preparation");
    const preparationToolbar = el("div", "", "interview-preparation-toolbar");
    preparationToolbar.append(el("span", "INTERVIEW SETUP", "eyebrow"), back);
    preparation.append(
      preparationToolbar,
      el("h2", "正式开始前，请先上传你的复试 PPT"),
      el("p", "准备好 PPT 后，可先检测麦克风并试听。点击页面底部的「开始模拟面试」后，才会正式请求麦克风权限、创建面试记录并开始计时。"),
    );
    const session = el("div", "", "presentation-session");
    session.append(
      presentationView(item, false, presentationControls(), {
        showDefaultPreview: false,
      }),
    );
    preparation.append(microphoneCheck(), session);
    const startArea = el("div", "", "interview-start-actions");
    const start = button("开始模拟面试", () => presentationControls().start(item), "button primary start-interview-button");
    start.disabled = !item.presentation;
    startArea.append(start, el("p", item.presentation
      ? "点击后上传并处理 PPT，正式进入面试时开始计时和全程录音。"
      : "请先选择自己的复试 PPT，准备好后再开始。", "field-hint"));
    preparation.append(startArea);
    container.replaceChildren(topline, preparation);
    releaseSessionPlayback();
    return;
  }
  const workspace = el("div", "", "interview-workspace");
  const stages = el("aside", "", "panel stage-panel");
  const complete = item.answers.filter((answer) => answerIsComplete(item, answer)).length;
  const progress = el("div", "", "stage-progress");
  const fill = el("span");
  fill.style.width = `${(100 * complete) / Math.max(item.answers.length, 1)}%`;
  progress.append(fill);
  stages.append(
    el("h3", "面试环节"),
    progress,
    el(
      "p",
      `已保存 ${complete} / ${item.answers.length} 个回答`,
      "stage-caption",
    ),
  );
  const stageList = el("nav", "", "stage-list");
  stageList.setAttribute("aria-label", "面试环节");
  item.answers.forEach((answer) => {
    const saved = answerIsComplete(item, answer);
    const stageButton = button(
      "",
      async () => {
        if (!allowInteraction()) return;
        if (
          item.workflow_version >= 2 &&
          !item.intro_completed &&
          answer.stage > 1 &&
          !readOnly
        ) {
          notify("请先完成 PPT 自我介绍。", "info");
          return;
        }
        await switchStage(answer.stage);
      },
      `stage-item${selectedStage === answer.stage ? " selected" : ""}${saved ? " complete" : ""}`,
    );
    stageButton.setAttribute(
      "aria-label",
      `第 ${answer.stage} 题，${saved ? "已保存" : "待回答"}`,
    );
    if (selectedStage === answer.stage)
      stageButton.setAttribute("aria-current", "step");
    stageButton.append(
      el(
        "span",
        saved ? "✓" : String(answer.stage).padStart(2, "0"),
        "stage-number",
      ),
      el(
        "span",
        stageName(answer, item),
        "stage-item-text",
      ),
      el("span", saved ? "已保存" : "待回答", "stage-item-meta"),
    );
    stageButton.disabled =
      !readOnly &&
      item.workflow_version >= 2 &&
      !item.intro_completed &&
      answer.stage > 1;
    stageList.append(stageButton);
  });
  stages.append(stageList);
  const answer = item.answers.find((a) => a.stage === selectedStage);
  const drawer = el("div", "", "stage-drawer");
  let pointerInsideDrawer = false;
  const setDrawerOpen = (open) => {
    drawer.classList.toggle("is-open", open);
    stageToggle.setAttribute("aria-expanded", String(open));
    stageToggle.setAttribute("aria-label", open ? "收起面试环节列表" : "展开面试环节列表");
  };
  const stageToggle = button("环节", () => {
    setDrawerOpen(!drawer.classList.contains("is-open"));
  }, "stage-drawer-toggle");
  stageToggle.setAttribute("aria-label", "展开面试环节列表");
  stageToggle.setAttribute("aria-expanded", "false");
  stageToggle.setAttribute("aria-controls", "interviewStages");
  stages.id = "interviewStages";
  drawer.append(stageToggle, stages);
  drawer.addEventListener("pointerenter", event => {
    if (event.pointerType !== "mouse") return;
    pointerInsideDrawer = true;
    setDrawerOpen(true);
  });
  drawer.addEventListener("pointerleave", () => {
    pointerInsideDrawer = false;
    if (!drawer.contains(document.activeElement)) setDrawerOpen(false);
  });
  drawer.addEventListener("focusin", event => {
    if (event.target !== stageToggle) setDrawerOpen(true);
  });
  drawer.addEventListener("focusout", event => {
    if (!pointerInsideDrawer && !drawer.contains(event.relatedTarget)) setDrawerOpen(false);
  });
  workspace.append(drawer);
  const answerReview = el("section", "", "panel answer-review-panel");
  answerReview.id = "answerReview";
  if (answer) workspace.append(renderAnswer(item, answer, readOnly, answerReview));
  const recordingNotice = el("p", "", "field-hint live-transcription-status");
  recordingNotice.id = "interviewRecordingNotice";
  recordingNotice.setAttribute("role", "status");
  recordingNotice.hidden = true;
  container.replaceChildren(topline, recordingNotice, workspace);
  if (feedbackRequests.has(item.id)) {
    const progress = el("section", "", "panel feedback-progress");
    progress.setAttribute("role", "status");
    progress.append(el("strong", "正在生成整场面试点评…"),
      el("p", "可以继续切换环节复盘，也可以返回面试记录；生成结果会自动保存。"));
    container.append(progress);
  }
  renderInterviewTimer(item);
  resumeLiveTranscription();
  updateRecordingStatus();
  if (item.feedback) {
    const feedback = el("details", "", "panel feedback-panel");
    feedback.open = !collapsedFeedback.has(item.id);
    const summary = el("summary", "", "feedback-toggle");
    const title = el("div", "", "feedback-title");
    title.append(
      el("span", "INTERVIEW REVIEW", "eyebrow"),
      el("h3", "整场面试点评"),
    );
    const hint = el("span", "", "feedback-toggle-hint");
    const updateToggle = () => {
      hint.textContent = feedback.open ? "收起点评" : "展开点评";
      if (feedback.open) collapsedFeedback.delete(item.id);
      else collapsedFeedback.add(item.id);
    };
    updateToggle();
    feedback.addEventListener("toggle", updateToggle);
    summary.append(title, hint);
    const body = el("div", "", "feedback-markdown");
    // The server renders Markdown with raw HTML and image embedding disabled.
    body.innerHTML = item.feedback_html;
    feedback.append(summary, body);
    container.append(feedback);
  }
  if (answerReview.childElementCount) container.append(answerReview);
  const reviewTranscript = answerReview.querySelector(".transcript-editor.is-review .answer-transcript");
  if (reviewTranscript && !CSS.supports("field-sizing", "content")) {
    requestAnimationFrame(() => {
      if (!reviewTranscript.isConnected) return;
      reviewTranscript.style.height = "auto";
      reviewTranscript.style.height = `${Math.min(reviewTranscript.scrollHeight, window.innerHeight * 0.6)}px`;
    });
  }
  if (item.workflow_version >= 4) {
    const signature = JSON.stringify([item.id, readOnly, sessionAudio.active,
      sessionAudio.pending, item.recordings]);
    if (signature !== playbackSignature) {
      releaseSessionPlayback();
      playbackPanel = sessionAudioPanel(item, readOnly);
      playbackSignature = signature;
      if (playbackPanel) root.append(playbackPanel);
    }
  } else releaseSessionPlayback();
}
/** Only advancing from the English answer requests an expert question, never feedback. */
async function enterExpert() {
  if (!allowInteraction()) return;
  cancelStageSpeech();
  const item = activeInterview;
  const next = document.querySelector(".stage-next-button");
  const originalLabel = next?.textContent;
  uploading = true;
  if (next) { next.disabled = true; next.textContent = "正在准备专家问题…"; }
  $("interviewDetail").inert = true;
  try {
    if (sessionAudio.active) { await sessionAudio.drainLive(); await sessionAudio.checkpoint(); }
    await saveDrafts();
    await api(`/interviews/${item.id}/teacher-question`, { method: "POST" });
    activeInterview = await api(`/interviews/${item.id}`);
    selectedStage = item.expert_stage;
    renderInterview();
    window.scrollTo({ top: 0, behavior: "instant" });
  } finally {
    uploading = false;
    $("interviewDetail").inert = false;
    if (next?.isConnected) { next.disabled = false; next.textContent = originalLabel; }
    resumeLiveTranscription();
  }
  void announceStage(activeInterview, selectedStage);
}

/** Feedback is requested exclusively by the expert stage's explicit review button. */
async function generateFeedback() {
  if (!allowInteraction()) return;
  const item = activeInterview;
  if (reviewMode() || selectedStage !== item.expert_stage) return;
  if (feedbackRequests.has(item.id)) return;
  if (!await confirmAction("生成点评会结束本轮面试并保存录音，再由 AI 点评整场回答。是否继续？", {
    title: "生成整场面试点评", confirmText: "结束并生成点评",
  })) return;
  if (!allowInteraction() || activeInterview !== item) return;
  const task = { token: state.token, controller: new AbortController() };
  feedbackRequests.set(item.id, task);
  try {
    if (item.status !== "finished")
      await endCurrentInterview({ automatic: true, showNotice: false });
    if (sessionAudio.pending) throw new Error("请先重试保存全程录音，再生成点评。");
    renderInterview();
    const result = await api(`/interviews/${item.id}/finish`, {
      method: "POST", signal: task.controller.signal,
    });
    if (state.token !== task.token || task.controller.signal.aborted) return;
    if (activeInterview?.id === item.id) activeInterview = result;
    notify("整场面试点评已生成并保存，可在面试记录中查看。");
  } catch (error) {
    if (!task.controller.signal.aborted && state.token === task.token)
      notify(`点评未生成：${error.message}。可进入专家问答环节重试。`, "error");
  } finally {
    if (feedbackRequests.get(item.id) === task) feedbackRequests.delete(item.id);
    if (state.token === task.token && !task.controller.signal.aborted) {
      if (activeInterview?.id === item.id) feedbackViewDirty.add(item.id);
      if (activeInterview?.id === item.id && !$("interview").hidden && !$("interviewDetail").hidden)
        renderInterview();
      await refreshInterviews();
    }
  }
}

async function endCurrentInterview({ automatic = false, returnStage = 1, showNotice = true } = {}) {
  if (ending || (uploading && !automatic)) {
    notify("正在保存或处理，请稍候再结束面试。", "info");
    return;
  }
  const item = activeInterview;
  if (!item || item.status === "finished") return;
  if (!automatic && !await confirmAction("确认结束本轮面试？系统会保存录音与回答并返回 001 环节，不会生成 AI 点评。")) return;
  if (ending || activeInterview !== item || activeInterview?.status === "finished") return;
  ending = true;
  cancelStageSpeech();
  clearTimeout(liveSaveTimer);
  $("interviewDetail").inert = true;
  const expired = item.timed_out || (interviewClock?.id === item.id &&
    interviewClock.remaining - (performance.now() - interviewClock.anchor) / 1000 <= 0);
  try {
    if (item.workflow_version >= 4) {
      if (!expired) await sessionAudio.drainLive();
      sessionAudio.stopCapture();
    } else if (recording) {
      const current = recording;
      if (current.recorder.state !== "inactive") current.recorder.stop();
      if (!await current.completed) throw new Error("录音未成功保存，请检查提示后重试。");
    }
    if (item.started_at && !expired) {
      try { await saveDrafts(); }
      catch (error) { if (error.status !== 409) throw error; }
    }
    activeInterview = await api(`/interviews/${item.id}/stop`, { method: "POST" });
    selectedStage = returnStage;
    if (item.workflow_version >= 4 && sessionAudio.current?.iid === item.id) {
      try { activeInterview = await sessionAudio.finalize() || activeInterview; }
      catch (error) { notify(`面试已结束，录音待上传：${error.message}。请重试保存或下载录音。`, "error"); }
    }
    if (showNotice && !sessionAudio.pending) notify("本轮面试已结束，录音与回答已保存，未生成 AI 点评。");
  } finally {
    ending = false;
    $("interviewDetail").inert = false;
    renderInterview();
    window.scrollTo({ top: 0, behavior: "instant" });
    await refreshInterviews();
  }
}
function sessionAudioPanel(item, readOnly) {
  if (!readOnly && sessionAudio.active) return null;
  const panel = el("section", "", "panel session-audio-panel");
  panel.append(el("h3", readOnly ? "全程录音回放" : "恢复面试录音"));
  if (!reviewMode() && item.started_at && !readOnly) {
    if (!sessionAudio.active && !sessionAudio.pending) panel.append(button("恢复全程录音", async () => {
      if (!allowInteraction()) return;
      await sessionAudio.prepare();
      await sessionAudio.begin(item);
      renderInterview();
    }, "button primary"), el("p", "页面刷新后需点击恢复录音，已上传的音频片段仍保留，面试倒计时不会重置。"));
  }
  if (sessionAudio.pending && sessionAudio.current?.iid === item.id) {
    panel.append(el("p", "录音尚未上传，请重试保存；也可下载到本机保留。"),
      button("重试保存全程录音", async () => {
        activeInterview = await sessionAudio.finalize() || activeInterview;
        renderInterview(); notify("全程录音已保存。");
      }), button("下载本地录音", () => sessionAudio.download()),
      button("放弃本地录音", async () => {
        if (!await confirmAction("请先下载并确认本地录音已保存。放弃后，尚未上传的声音将从当前页面清除，无法恢复；服务器已上传的备份仍会保留。", { title: "放弃待上传的录音？", confirmText: "确认已下载，放弃上传", danger: true })) return;
        sessionAudio.clear();
        renderInterview();
        notify("已清除待上传的本地录音，服务器上的录音备份仍保留。", "info");
      }, "button secondary"));
  }
  if (readOnly) item.recordings?.filter(part => part.has_audio).forEach((part, index) => {
    panel.append(sessionPlaybackControl(item, part, index + 1, panel));
    if (part.transcript) panel.append(el("details", "", "recording-transcript"));
    const transcript = panel.lastElementChild;
    if (part.transcript) transcript.append(el("summary", "查看全程转写"), el("pre", part.transcript));
  });
  if (!panel.querySelector("button") && !sessionAudio.active && !item.recordings?.some(part => part.has_audio))
    panel.append(el("p", "本场尚无已保存的全程录音。"));
  return panel;
}
function formatPlaybackTime(seconds) {
  const total = Number.isFinite(seconds) && seconds > 0 ? Math.floor(seconds) : 0;
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}
function sessionPlaybackControl(item, part, index, panel) {
  const control = el("div", "", "session-playback");
  const audio = el("audio");
  audio.controls = false;
  audio.preload = "metadata";
  audio.hidden = true;
  audio.setAttribute("aria-hidden", "true");
  const toggle = button("▷", async () => {
    if (!audio.paused) {
      audio.pause();
      return;
    }
    panel.querySelectorAll(".session-playback audio").forEach(other => {
      if (other !== audio) other.pause();
    });
    if (!audio.src) {
      toggle.disabled = true;
      try {
        const blob = await audioBlob(interviewPath(`/interviews/${item.id}/recordings/${part.id}`));
        if (!control.isConnected) return;
        const url = URL.createObjectURL(blob);
        sessionPlaybackUrls.add(url);
        audio.src = url;
      } finally {
        toggle.disabled = false;
      }
    }
    try { await audio.play(); }
    catch (error) { notify(`录音播放失败：${error.message}`, "error"); }
  }, "session-playback-toggle");
  toggle.setAttribute("aria-label", `播放全程录音片段 ${index}`);
  const current = el("span", "0:00", "session-playback-current");
  const seek = el("input", "", "session-playback-seek");
  seek.type = "range";
  seek.min = "0";
  seek.max = "1000";
  seek.value = "0";
  seek.disabled = true;
  seek.setAttribute("aria-label", "播放进度");
  const duration = el("span", "--:--", "session-playback-duration");
  const mute = button("静音", () => { audio.muted = !audio.muted; }, "session-playback-mute");
  const volume = el("input", "", "session-playback-volume");
  volume.type = "range";
  volume.min = "0";
  volume.max = "1";
  volume.step = "0.05";
  volume.value = String(audio.volume);
  volume.setAttribute("aria-label", "音量");
  const updateMute = () => {
    mute.textContent = audio.muted ? "取消静音" : "静音";
    mute.setAttribute("aria-label", audio.muted ? "取消静音" : "静音");
  };
  updateMute();
  volume.addEventListener("input", () => {
    audio.volume = Number(volume.value);
    if (audio.volume > 0) audio.muted = false;
  });
  audio.addEventListener("volumechange", () => {
    volume.value = String(audio.volume);
    updateMute();
  });
  let seeking = false;
  const playbackLength = () => {
    if (Number.isFinite(audio.duration) && audio.duration > 0) return audio.duration;
    const ranges = audio.seekable;
    return ranges.length ? ranges.end(ranges.length - 1) : 0;
  };
  const updateProgress = (seconds = audio.currentTime) => {
    const length = playbackLength();
    const fraction = length > 0 ? Math.min(Math.max(seconds / length, 0), 1) : 0;
    const percent = Math.round(fraction * 1000);
    seek.value = String(percent);
    seek.style.setProperty("--seek-progress", `${fraction * 100}%`);
    current.textContent = formatPlaybackTime(seconds);
    seek.setAttribute("aria-valuetext", `${current.textContent} / ${duration.textContent}`);
  };
  const updateDuration = () => {
    const length = playbackLength();
    if (length <= 0) return;
    duration.textContent = formatPlaybackTime(length);
    seek.disabled = false;
    if (!seeking) updateProgress();
  };
  const probeDuration = () => {
    if (audio.duration !== Infinity) return;
    const originalTime = audio.currentTime;
    const onSeeked = () => {
      audio.removeEventListener("seeked", onSeeked);
      updateDuration();
      if (Number.isFinite(audio.duration) && audio.duration > 0) audio.currentTime = originalTime;
    };
    audio.addEventListener("seeked", onSeeked);
    try {
      audio.currentTime = Number.MAX_VALUE;
    } catch (error) {
      audio.removeEventListener("seeked", onSeeked);
      throw error;
    }
  };
  seek.addEventListener("input", () => {
    seeking = true;
    const preview = playbackLength() * Number(seek.value) / Number(seek.max);
    updateProgress(preview);
  });
  const commitSeek = () => {
    const length = playbackLength();
    if (length <= 0) return;
    audio.currentTime = length * Number(seek.value) / Number(seek.max);
    seeking = false;
    updateProgress();
  };
  seek.addEventListener("change", commitSeek);
  seek.addEventListener("pointercancel", () => {
    seeking = false;
    updateProgress();
  });
  audio.addEventListener("loadedmetadata", () => { updateDuration(); probeDuration(); });
  audio.addEventListener("durationchange", updateDuration);
  audio.addEventListener("seeked", updateDuration);
  audio.addEventListener("timeupdate", () => { if (!seeking) updateProgress(); });
  audio.addEventListener("play", () => {
    toggle.textContent = "Ⅱ";
    toggle.setAttribute("aria-label", `暂停全程录音片段 ${index}`);
  });
  audio.addEventListener("pause", () => {
    toggle.textContent = "▷";
    toggle.setAttribute("aria-label", `播放全程录音片段 ${index}`);
  });
  audio.addEventListener("ended", () => { updateDuration(); updateProgress(playbackLength()); });
  control.append(audio, toggle, current, seek, duration, mute, volume);
  return control;
}
async function saveAnswer(item, answer, value) {
  await api(`/interviews/${item.id}/answers/${answer.stage}`, {
    method: "PUT",
    body: JSON.stringify({ transcript: value }),
  });
  answer.transcript = value;
  const key = answerKey(item.id, answer.stage);
  if (drafts.get(key) === value) drafts.delete(key);
}
async function saveDrafts() {
  const item = activeInterview;
  for (const answer of item.answers) {
    const key = answerKey(item.id, answer.stage);
    if (drafts.has(key)) await saveAnswer(item, answer, drafts.get(key));
  }
}
function renderAnswer(item, answer, readOnly, reviewContainer) {
  const panel = el("article", "", "panel answer-panel");
  const isIntro = item.workflow_version >= 2 && answer.stage === 1;
  const isExpert = answer.stage === item.expert_stage;
  const reviewing = reviewMode() || item.status === "finished" || item.timed_out || item.status === "expired";
  panel.classList.toggle("is-review", reviewing);
  panel.classList.toggle("has-presentation", !!item.presentation && (isIntro || isExpert));
  panel.classList.toggle("is-expert-stage", isExpert);
  panel.classList.toggle("is-question-stage", !isIntro && !(isExpert && item.presentation));
  if (isIntro && item.intro_completed) readOnly = true;
  const heading = el("div", "", "question-heading");
  const subjectNames = { data_structures: "数据结构", operating_systems: "操作系统", computer_networks: "计算机网络" };
  heading.append(
    el("span", `QUESTION ${String(answer.stage).padStart(2, "0")}`, "eyebrow"),
    el("h3", item.workflow_version >= 5 && [2, 3, 4].includes(answer.stage) && !answer.question_choices ? stageName(answer, item) : answer.question),
    el(
      "p",
      readOnly
        ? "回顾回答，回听录音，关注可以改进的细节。"
        : item.workflow_version >= 4 ? "全程录音已自动开启，请自然作答。" : "先整理思路，再自然表达；录音后可转写并校对回答。",
    ),
  );
  if (isExpert) {
    heading.classList.add("expert-question-card");
    const header = el("div", "", "expert-question-header");
    header.append(el("h3", "专家问答"),
      el("span", `QUESTION ${String(answer.stage).padStart(2, "0")}`, "eyebrow"));
    const question = el("div", "", "expert-question-scroll");
    question.tabIndex = 0;
    question.setAttribute("role", "region");
    question.setAttribute("aria-label", "专家提问内容，可滚动阅读");
    question.append(el("p", answer.question, "expert-question-text"));
    heading.replaceChildren(header, question);
  }
  if (isIntro) {
    const session = el("div", "", "presentation-session");
    session.append(presentationView(item, readOnly, presentationControls(), { hideTemplateReference: true }));
    if (item.presentation && !readOnly && item.started_at && item.workflow_version < 4)
      session.append(recordingBar(item, answer));
    panel.append(heading, session);
    if (!item.presentation && !readOnly) {
      panel.append(
        el(
          "p",
          "下载模板填写后，请上传自己的复试 PPT，再开始放映与录音。其他面试环节会在自我介绍完成后解锁。",
          "intro-gate-hint",
        ),
      );
      return panel;
    }
    if (item.presentation && !item.started_at && !readOnly) return panel;
  }
  if (isExpert && item.presentation) {
    panel.append(heading);
    const session = el("div", "", "presentation-session expert-presentation");
    session.append(presentationView(item, true, presentationControls(), { hideTemplateReference: true }));
    if (!readOnly && item.workflow_version < 4) session.append(recordingBar(item, answer));
    panel.append(session);
  }
  if (!readOnly && item.workflow_version >= 5 && answer.stage === 2 && !answer.question_choices) {
    const picker = el("section", "", "subject-question-picker");
    picker.append(el("h3", "选择一门专业课", "compact-heading"), el("p", "先选择一张学科卡片查看题目；答不出来时，可再从另外两门中换题一次。"));
    const cards = el("div", "", "subject-card-grid");
    for (const [subject, name] of Object.entries(subjectNames)) cards.append(button(name, async () => {
      if (!allowInteraction()) return;
      uploading = true;
      try {
        await sessionAudio.drainLive();
        activeInterview = await api(`/interviews/${item.id}/professional-question`, { method: "POST", body: JSON.stringify({ subject }) });
        renderInterview();
      } finally { uploading = false; resumeLiveTranscription(); }
    }, "subject-question-card"));
    picker.append(cards);
    const endArea = el("div", "", "interview-end-actions");
    endArea.append(button("结束本轮面试", endCurrentInterview, "button secondary end-interview-button"));
    panel.append(heading, picker, endArea);
    return panel;
  }
  if (!readOnly && item.workflow_version >= 5 && (answer.stage === 3 || answer.stage === 4) && !answer.question_choices) {
    const draw = button(answer.stage === 3 ? "抽取英文段落" : "随机抽取英文问题", async () => {
      if (!allowInteraction()) return;
      uploading = true;
      try {
        activeInterview = await api(`/interviews/${item.id}/draw-question/${answer.stage}`, { method: "POST" });
        renderInterview();
      } finally { uploading = false; resumeLiveTranscription(); }
    }, "button primary question-draw-button");
    const drawPanel = el("section", "", "question-draw-panel");
    drawPanel.append(draw);
    const endArea = el("div", "", "interview-end-actions");
    endArea.append(button("结束本轮面试", endCurrentInterview, "button secondary end-interview-button"));
    panel.append(heading, drawPanel, endArea);
    return panel;
  }
  let changePanel = null;
  if (item.workflow_version >= 5 && [2, 3, 4].includes(answer.stage) && answer.question_choices) {
    heading.classList.add("drawn-question-card");
    const label = el("span", answer.stage === 2 ? subjectNames[answer.subject] : stageName(answer, item), "drawn-question-label");
    heading.prepend(label);
    heading.querySelector("h3").lang = answer.stage === 2 ? "zh-CN" : "en";
  }
  if (!readOnly && item.workflow_version >= 5 && answer.stage === 2 && answer.question_choices === 1) {
    const change = el("div", "", "question-change");
    change.append(el("span", `已选择：${subjectNames[answer.subject] || answer.subject} · 可换题 1 次`));
    const buttons = el("div", "", "subject-change-actions");
    for (const [subject, name] of Object.entries(subjectNames)) if (subject !== answer.subject) buttons.append(button(name, async () => {
      if (!allowInteraction()) return;
      if (!await confirmAction("确认使用唯一一次换题机会？请选择另一门学科，原题文字回答将清空，全程录音保留。")) return;
      uploading = true;
      try {
        await sessionAudio.drainLive();
        clearTimeout(liveSaveTimer);
        activeInterview = await api(`/interviews/${item.id}/professional-question`, { method: "POST", body: JSON.stringify({ subject }) });
        drafts.delete(answerKey(item.id, 2));
        interimTexts.delete(answerKey(item.id, 2));
        renderInterview();
      } finally { uploading = false; resumeLiveTranscription(); }
    }, "button secondary"));
    change.append(buttons);
    changePanel = change;
  }
  const content = el("div", "", "answer-content");
  const compactTranscript = item.workflow_version >= 4;
  const editor = compactTranscript ? el("details", "", "transcript-editor") : content;
  if (compactTranscript) {
    if (reviewing) editor.classList.add("is-review");
    if (reviewing) editor.append(el("summary", "查看完整回答", "transcript-editor-toggle"));
  }
  const input = el("textarea", "", "answer-transcript");
  const key = answerKey(item.id, answer.stage);
  input.id = "answerTranscript";
  input.value = drafts.get(key) ?? answer.transcript;
  input.readOnly = readOnly;
  input.placeholder = "录音并转写后，回答会显示在这里；也可以直接输入回答。";
  input.maxLength = 20000;
  const status = el(
    "span",
    drafts.has(key)
      ? "有修改尚未保存"
      : answer.transcript
        ? "回答已保存"
        : "等待作答",
    `save-state${drafts.has(key) ? " dirty" : ""}`,
  );
  const label = el("div", "", "transcript-label");
  const inputLabel = el("label", item.workflow_version >= 4 || readOnly ? "回答内容" : "回答转写");
  inputLabel.htmlFor = input.id;
  label.append(inputLabel, status);
  const count = el("span", `${input.value.length} / 20000`);
  input.addEventListener("input", () => {
    transcriptionNotices.delete(key);
    if (input.value === answer.transcript) drafts.delete(key);
    else drafts.set(key, input.value);
    status.textContent = drafts.has(key) ? "有修改尚未保存" : "回答已保存";
    status.classList.toggle("dirty", drafts.has(key));
    count.textContent = `${input.value.length} / 20000`;
  });
  if (!readOnly && item.workflow_version < 4 && !isIntro && !(isExpert && item.presentation)) content.append(recordingBar(item, answer));
  editor.append(label, input);
  const help = el("div", "", "transcript-help");
  help.append(
    el(
      "span",
      readOnly
        ? "已提交的回答仅可查看。"
        : isIntro
          ? "请检查专业名词和关键表述，完成自我介绍时会自动保存回答。"
          : "请检查专业名词和关键表述，确认后保存。",
    ),
    count,
  );
  if (transcriptionNotices.has(key))
    help.prepend(el("span", transcriptionNotices.get(key), "transcription-warning"));
  editor.append(help);
  const actions = el("div", "", "answer-actions");
  const left = el("div", "", "action-group");
  if (answer.has_audio && (reviewing || !compactTranscript))
    left.append(
      button(
        "▷ 回听录音",
        async () => {
          const blob = await audioBlob(
            interviewPath(
              `/interviews/${item.id}/answers/${answer.stage}/audio`,
            ),
          );
          const url = URL.createObjectURL(blob);
          audioUrls.add(url);
          content.querySelector("audio")?.remove();
          const audio = document.createElement("audio");
          audio.controls = true;
          audio.className = "audio-player";
          audio.src = url;
          audio.setAttribute("aria-label", `第 ${answer.stage} 题录音`);
          content.append(audio);
          await audio.play();
        },
        "button secondary",
      ),
    );
  if (!readOnly && answer.has_audio)
    left.append(
      button(
        "语音转写",
        async () => {
          if (!allowNavigation()) return;
          if (drafts.has(key))
            throw new Error("请先保存当前文本，再进行转写。");
          const result = await api(
            `/interviews/${item.id}/answers/${answer.stage}/transcribe`,
            { method: "POST" },
          );
          answer.transcript = result.transcript;
          drafts.delete(key);
          rememberTranscriptionResult(key, result.transcript);
          renderInterview();
          notify(result.transcript.trim() ? "转写已保存，请检查专业名词并修正。" : "没有识别到语音内容，请检查录音或直接填写回答。",
            result.transcript.trim() ? "success" : "info");
        },
        "button soft",
      ),
    );
  actions.append(left);
  if (!readOnly && !isIntro)
    actions.append(
      button(
        "保存回答",
        async () => {
          if (!allowInteraction()) return;
          await saveAnswer(item, answer, input.value);
          renderInterview();
          notify("回答已保存。");
        },
        "button primary",
      ),
    );
  editor.append(actions);
  if (compactTranscript) {
    if (reviewing) content.append(editor);
  }
  const footer = el("div", "", "stage-footer");
  const previous = button(
    "← 上一环节",
    () => switchStage(selectedStage - 1),
    "button secondary",
  );
  const next = button(
    isExpert && !readOnly ? "结束本轮面试" : "下一环节 →",
    async () => {
      if (!allowInteraction()) return;
      if (isExpert && !readOnly) { await endCurrentInterview(); return; }
      if (isIntro && !item.intro_completed && !readOnly) {
        uploading = true;
        input.readOnly = true;
        try {
          if (item.workflow_version >= 4) {
            await sessionAudio.drainLive();
            if (sessionAudio.active) await sessionAudio.checkpoint();
          }
          await saveAnswer(item, answer, drafts.get(key) ?? input.value);
          status.textContent = "回答已保存";
          status.classList.remove("dirty");
          activeInterview = await api(
            `/interviews/${item.id}/complete-introduction`,
            { method: "POST" },
          );
        } finally {
          uploading = false;
          input.readOnly = false;
          resumeLiveTranscription();
        }
      }
      await switchStage(selectedStage + 1);
    },
    "button secondary stage-next-button",
  );
  previous.disabled = selectedStage <= 1;
  next.disabled = readOnly ? selectedStage >= item.answers.length : selectedStage > item.expert_stage;
  if (!readOnly && selectedStage === item.expert_stage - 1) next.title = "进入专家问答";
  footer.append(
    previous,
    el("span", `${selectedStage} / ${readOnly ? item.answers.length : item.expert_stage}`),
    next,
  );
  if (!isIntro && !(isExpert && item.presentation)) panel.append(heading);
  if (changePanel) panel.append(changePanel);
  const questionHistory = answer.question_history || [];
  if (reviewing && answer.stage === 2 && questionHistory.length > 1) {
    const history = el("section", "", "question-history-panel");
    history.append(el("h3", "专业课换题记录"));
    const list = el("ol", "", "question-history-list");
    questionHistory.forEach((entry, index) => {
      const row = el("li", "", "question-history-item");
      const label = index === 0 ? "换题前" : "换题后";
      row.append(el("span", `${label} · ${subjectNames[entry.subject] || entry.subject}`, "question-history-label"),
        el("p", entry.question));
      list.append(row);
    });
    history.append(list);
    panel.append(history);
  }
  if (compactTranscript && reviewing) {
    reviewContainer.append(el("h3", `回答回顾 · ${stageName(answer, item)}`),
      el("p", answer.transcript ? "结合录音回顾本环节的完整回答。" : "本环节暂无转写内容，可结合下方全程录音复盘。", "muted"), content);
  } else if (!compactTranscript) panel.append(content);
  panel.append(footer);
  if (!reviewMode() && (isExpert ? !item.feedback : item.status !== "finished")) {
    const endActions = el("div", "", "interview-end-actions");
    const action = isExpert
      ? button("生成整场面试点评", generateFeedback, "button primary generate-feedback-button")
      : button("结束本轮面试", endCurrentInterview, "button secondary end-interview-button");
    if (isExpert && feedbackRequests.has(item.id)) {
      action.disabled = true;
      action.textContent = "正在生成整场点评…";
    }
    endActions.append(action);
    if (isExpert) endActions.append(el("p", "仅点击此按钮才生成 AI 点评；结束或返回记录只保存面试。", "field-hint"));
    panel.append(endActions);
  }
  return panel;
}
function presentationControls() {
  return {
    allowNavigation,
    setBusy: (value) => {
      uploading = value;
    },
    selected: (file) => {
      preparationFile = file;
      activeInterview.presentation = { name: file.name, pages: null };
      renderInterview();
    },
    uploaded: (updated) => {
      drafts.delete(answerKey(updated.id, 1));
      activeInterview = updated;
      renderInterview();
    },
    start: async (item) => {
      if (!allowInteraction()) return;
      uploading = true;
      try {
        if (item.workflow_version >= 4) await sessionAudio.prepare();
        let updated;
        if (!item.id) {
          if (!preparationFile) throw new Error("请先选择自己的复试 PPT。");
          const form = new FormData();
          form.append("file", preparationFile);
          item.startRequestKey ||= startRequestKey(preparationFile);
          updated = await api("/interviews/start", { method: "POST", body: form,
            headers: { "Idempotency-Key": item.startRequestKey } });
          clearStartRequestKey(item.startRequestKey);
          preparationFile = null;
        } else {
          updated = await api(`/interviews/${item.id}/start`, { method: "POST" });
        }
        activeInterview = updated;
        if (item.workflow_version >= 4) await sessionAudio.begin(updated);
        selectedStage = 1;
        renderInterview();
        await refreshInterviews();
        notify("面试已开始，正在全程录音。", "info");
      } finally {
        sessionAudio.cancelPrepared();
        uploading = false;
        renderInterview();
      }
      void announceStage(activeInterview, selectedStage);
    },
  };
}
function recordingBar(item, answer) {
  const bar = el("div", "", "recording-bar");
  const info = el("div", "", "recording-info");
  const title = el(
    "strong",
    answer.has_audio ? "本题录音已保存" : "用声音，完成你的回答",
  );
  const hint = el(
    "span",
    answer.has_audio ? "再次录音将替换当前录音" : "开始前请确认麦克风可用",
  );
  info.append(title, hint);
  const timer = el("span", "", "recording-timer");
  const stop = button(
    "■ 停止并保存",
    () => {
      if (recording) recording.recorder.stop();
    },
    "button secondary",
  );
  stop.hidden = true;
  const start = button(
    answer.has_audio ? "重新录音" : "● 开始录音",
    async () => {
      if (!allowNavigation()) return;
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
        throw new Error(
          "此浏览器不支持录音，请使用新版 Chrome / Edge，并通过 HTTPS 或 localhost 访问。",
        );
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      let media;
      try {
        media = new MediaRecorder(stream);
      } catch (error) {
        stream.getTracks().forEach((track) => track.stop());
        throw error;
      }
      const chunks = [];
      const started = Date.now();
      let recordingError = false;
      const tick = setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        timer.textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
      }, 1000);
      let completeRecording;
      const completed = new Promise((resolve) => { completeRecording = resolve; });
      recording = { recorder: media, stream, timer: tick, deadlineReached: false, completed };
      media.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      media.onerror = () => {
        recordingError = true;
        notify("录音发生异常，请停止后重试。", "error");
      };
      media.onstop = async () => {
        clearInterval(tick);
        stream.getTracks().forEach((track) => track.stop());
        recording = null;
        uploading = true;
        stop.disabled = true;
        if (recordingState.deadlineReached) {
          const url = URL.createObjectURL(new Blob(chunks, { type: media.mimeType || "audio/webm" }));
          const link = document.createElement("a");
          link.href = url;
          link.download = `interview-${item.id}-stage-${answer.stage}-late.webm`;
          link.click();
          URL.revokeObjectURL(url);
          uploading = false;
          completeRecording(false);
          notify("截止时尚未保存的录音已下载到本机，不会计入本场点评。", "info");
          await openInterview(item.id, selectedStage);
          return;
        }
        title.textContent = "正在保存录音…";
        let saved = false;
        await run(async () => {
          if (recordingError || !chunks.length)
            throw new Error("未获得有效录音，请重新录制。");
          const form = new FormData();
          form.append(
            "file",
            new Blob(chunks, { type: media.mimeType || "audio/webm" }),
            "answer.webm",
          );
          await api(
            interviewPath(
              `/interviews/${item.id}/answers/${answer.stage}/audio`,
            ),
            {
              method: "POST",
              body: form,
            },
          );
          answer.has_audio = 1;
          saved = true;
          notify("录音已保存，可以回听或进行语音转写。");
        });
        uploading = false;
        completeRecording(saved);
        renderInterview();
      };
      const recordingState = recording;
      try {
        media.start();
      } catch (error) {
        clearInterval(tick);
        stream.getTracks().forEach((track) => track.stop());
        recording = null;
        throw error;
      }
      bar.classList.add("is-recording");
      start.hidden = true;
      stop.hidden = false;
      timer.textContent = "00:00";
      title.textContent = "正在录音";
      hint.textContent = "结束后点击「停止并保存」";
    },
    "button soft",
  );
  bar.append(el("span", "◉", "recording-symbol"), info, timer, start, stop);
  return bar;
}
export function clearInterviewState() {
  feedbackRequests.forEach(task => task.controller.abort());
  feedbackRequests.clear();
  feedbackViewDirty.clear();
  openUserArchives.clear();
  archiveQuery = "";
  archivePage = 1;
  interviewQuery = "";
  interviewPage = 1;
  interviewItems = [];
  $("interviewSearch").value = "";
  collapsedFeedback.clear();
  expertSpeechPlaying = false;
  preparationFile = null;
  clearTimeout(liveSaveTimer);
  stopMicrophoneTest();
  sessionAudio.clear();
  interimTexts.clear();
  drafts.clear();
  transcriptionNotices.clear();
  clearPresentation();
  activeInterview = null;
  document.body.classList.remove("interview-immersive", "interview-shell-open");
  window.dispatchEvent(new Event("interview-layout-changed"));
  releaseAudio();
  stopInterviewTimer();
  $("interviewDetail").replaceChildren();
  $("interviewDetail").hidden = true;
  $("interviewOverview").hidden = false;
  $("interviewListTitle").hidden = false;
  $("refreshInterviews").parentElement.hidden = false;
  $("returnInterviews")?.remove();
  $("newInterview").hidden = reviewMode();
  $("interviewList").replaceChildren();
  $("interviewList").classList.remove("compact");
  if (recording) {
    recording.recorder.onstop = null;
    clearInterval(recording.timer);
    recording.stream.getTracks().forEach((track) => track.stop());
    if (recording.recorder.state !== "inactive") recording.recorder.stop();
    recording = null;
  }
}
export function configureInterviewMode() {
  $("newInterview").hidden = reviewMode();
  $("interviewListToolbar").hidden = reviewMode();
  $("interviewPagination").hidden = reviewMode();
  if (reviewMode()) {
    $("interviewTitle").replaceChildren(
      document.createTextNode("面试记录"),
      Object.assign(document.createElement("span"), {
        textContent: ".",
        className: "heading-dot",
      }),
    );
    $("interviewIntro").textContent =
      "查看用户回答与面试点评，关注每一次练习的成长。";
    $("interviewListTitle").replaceChildren(
      document.createTextNode("用户面试"),
      el("span", "按用户归档", "section-caption"),
    );
    $("interviewOverview").querySelector(".interview-banner").hidden = true;
  }
}
