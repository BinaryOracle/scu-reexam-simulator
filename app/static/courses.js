/** Course catalog, lesson media, and administrator authoring. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, button, confirmAction, el, emptyState, notify, run } from "./ui.js?v=20261114-ui-v17";
import { writeAppRoute } from "./view-route.mjs?v=20261115-navigation-v3";
import { cancelCapture, getCapture, prepareCapture, stopCapture } from "./course-capture.js?v=2";

export { cancelCapture, getCapture };
const timeLabel = new Intl.DateTimeFormat("zh-CN", {
  timeZone: "Asia/Shanghai", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
});
const labels = { material: "资料", video: "录播", live: "直播" };
const statusText = {
  unscheduled: "暂无直播安排", scheduled: "直播尚未开始", waiting: "等待老师开播",
  connecting: "老师正在接入直播…", live: "直播进行中", processing: "直播已结束，正在保存回放…", ended: "直播已结束",
};
const section = () => state.adminMode ? "coursesAdmin" : "courses";
const root = () => $(section());
const base = () => state.adminMode ? "/admin/courses" : "/courses";
const media = (cid, path) => `/api/course-media/${cid}/${path}`;
const playlist = id => `live/${id}/index.m3u8`;
const format = timestamp => timeLabel.format(timestamp * 1000);
const fileSize = bytes => bytes < 1048576 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
const previewTime = seconds => seconds === null ? "" : new Date((seconds + 28800) * 1000).toISOString().slice(0, 16);
let course, lessonId, tab, poll, generation = 0, player, receivedAt, playingKey;

function closePlayer() {
  if (!player) return;
  player.hls?.destroy();
  player.video.pause();
  player.video.removeAttribute("src");
  player.video.load();
  player = null;
  playingKey = null;
}

export function clearCourses() {
  generation++;
  clearTimeout(poll);
  closePlayer();
  course = null;
  lessonId = null;
}

function ensureIdle() {
  if (getCapture()) throw new Error("请先结束直播或取消开播准备");
}

function route(cid, lid) {
  return [section(), cid, lid].filter(Boolean).join("/");
}

async function navigate(cid, lid) {
  ensureIdle();
  writeAppRoute(route(cid, lid));
  await refreshCourses();
}

function header(title, description, ...controls) {
  const heading = el("div", "", "page-heading course-heading");
  const info = el("div");
  const h1 = el("h1", title);
  h1.append(el("span", ".", "heading-dot"));
  info.append(el("div", state.adminMode ? "LEARNING MANAGEMENT" : "COURSE LIBRARY", "eyebrow"), h1,
    el("p", description, "muted"));
  heading.append(info, ...controls);
  return heading;
}

function field(form, label, name, options = {}) {
  const wrapper = el("label", "", "course-field");
  const input = el(options.multiline ? "textarea" : "input");
  if (!options.multiline) input.type = options.type || "text";
  Object.assign(input, { name, ...options.attributes });
  if (options.value !== undefined) input.value = options.value;
  wrapper.append(el("span", label), input);
  form.append(wrapper);
  return input;
}

function formBox(title, expanded) {
  const box = el("details", "", "panel course-editor");
  box.open = expanded;
  const form = el("form", "", "course-form");
  box.append(el("summary", title), form);
  return [box, form];
}

function submitForm(form, label, submit) {
  const control = el("button", label, "button primary");
  control.type = "submit";
  form.append(control);
  form.addEventListener("submit", event => {
    event.preventDefault();
    void run(() => { ensureIdle(); return submit(); }, control);
  });
}

function courseForm(item) {
  const [box, form] = formBox(item ? "编辑课程信息与发布状态" : "新建课程", false);
  const title = field(form, "课程名称", "title", { value: item?.title, attributes: { required: true, maxLength: 120 } });
  const description = field(form, "课程简介", "description", { multiline: true, value: item?.description, attributes: { rows: 3, maxLength: 4000 } });
  const published = field(form, "发布课程", "published", { type: "checkbox", attributes: { checked: Boolean(item?.published) } });
  published.parentNode.classList.add("course-checkbox");
  if (!item) form.append(el("p", "新课程默认仅指定学员可看。创建后，在「观看权限」中添加学员。", "muted"));
  submitForm(form, item ? "保存课程" : "创建课程", async () => {
    const result = await api(item ? `${base()}/${item.id}` : base(), {
      method: item ? "PUT" : "POST", body: JSON.stringify({ title: title.value.trim(), description: description.value, published: published.checked }),
    });
    notify(item ? "课程已保存" : "课程已创建");
    await navigate(result.id, item && lessonId);
  });
  return box;
}

function accessForm(item) {
  const [box, form] = formBox("观看权限", false);
  const endpoint = `${base()}/${item.id}/access`;
  const status = el("p", "", "muted");
  status.setAttribute("role", "status");
  form.append(status);
  let loaded = false;
  function render(data) {
    status.textContent = "";
    const modes = el("fieldset", "", "course-access-modes");
    modes.append(el("legend", "谁可以观看"));
    for (const [value, label] of [["restricted", "仅指定学员"], ["all", "所有已注册学员"]]) {
      const input = field(modes, label, "access_mode", { type: "radio", value, attributes: { checked: data.mode === value } });
      input.parentNode.classList.add("course-choice");
    }
    const picker = el("div", "", "course-access-picker");
    const search = field(picker, "搜索学员（用户名或邮箱）", "learner_search", { type: "search" });
    const count = el("p", "", "muted");
    count.setAttribute("aria-live", "polite");
    const list = el("div", "", "course-access-list");
    const selected = new Set(data.learners.filter(row => row.selected).map(row => row.id));
    const updateCount = () => { count.textContent = `已选择 ${selected.size} 名学员`; };
    function paintList() {
      const query = search.value.trim().toLocaleLowerCase();
      const matches = data.learners.filter(row => `${row.username} ${row.email || ""}`.toLocaleLowerCase().includes(query));
      list.replaceChildren();
      if (!matches.length) list.append(el("p", data.learners.length ? "没有找到匹配的学员。" : "暂无学员，请先前往「用户管理」创建账号。", "muted"));
      for (const learner of matches) {
        const input = field(list, learner.username, "learner", { type: "checkbox", attributes: { checked: selected.has(learner.id) } });
        const choice = input.parentNode;
        choice.classList.add("course-choice");
        if (learner.email || !learner.is_active) choice.querySelector("span").append(
          el("small", [learner.email, learner.is_active ? "" : "已停用"].filter(Boolean).join(" · "), "muted"));
        input.addEventListener("change", () => {
          if (input.checked) selected.add(learner.id);
          else selected.delete(learner.id);
          updateCount();
        });
      }
    }
    function syncMode() {
      picker.hidden = form.elements.access_mode.value !== "restricted";
    }
    search.addEventListener("input", paintList);
    modes.addEventListener("change", syncMode);
    picker.append(count, list);
    form.append(modes, picker,
      el("p", "权限适用于本课程的所有课节、资料、录播与直播。名单为空时，学员无法访问。", "muted"));
    updateCount();
    paintList();
    syncMode();
    submitForm(form, "保存观看权限", async () => {
      const mode = form.elements.access_mode.value;
      await api(endpoint, { method: "PUT", body: JSON.stringify({ mode, learner_ids: [...selected] }) });
      if (!box.isConnected) return;
      item.access_mode = mode;
      $("courseAccessBadge").textContent = accessLabel(item);
      status.textContent = "观看权限已保存";
    });
  }
  async function load() {
    loaded = true;
    form.replaceChildren(status);
    status.textContent = "正在读取学员名单…";
    try {
      const data = await api(endpoint);
      if (box.isConnected) render(data);
    } catch (error) {
      if (!box.isConnected) return;
      status.textContent = error.message;
      form.append(button("重新加载学员", load));
    }
  }
  box.addEventListener("toggle", () => {
    if (box.open && !loaded) void load();
  });
  return box;
}

const accessLabel = item => item.access_mode === "all" ? "所有已注册学员" : "仅指定学员";

function lessonForm(item, cid, position, expanded = false) {
  const [box, form] = formBox(item ? "编辑课节与直播排期" : "添加课节", expanded);
  const title = field(form, "课节名称", "title", { value: item?.title, attributes: { required: true, maxLength: 120 } });
  const description = field(form, "课节简介", "description", { multiline: true, value: item?.description, attributes: { rows: 2, maxLength: 4000 } });
  const order = field(form, "排序（从小到大）", "position", { type: "number", value: item?.position ?? position, attributes: { min: 1, max: 10000, required: true } });
  const starts = field(form, "直播开始（北京时间）", "live_start", { type: "datetime-local", value: item ? previewTime(item.live_start) : "" });
  const ends = field(form, "直播结束（北京时间）", "live_end", { type: "datetime-local", value: item ? previewTime(item.live_end) : "" });
  form.append(el("p", "暂不直播时可将两项时间留空。设置排期后，到「直播」页授权设备并保持页面打开，即可定时开播。", "muted"));
  submitForm(form, "保存课节", async () => {
    const parse = input => input.value ? Date.parse(`${input.value}+08:00`) / 1000 : null;
    const live_start = parse(starts), live_end = parse(ends);
    if ((live_start !== null || live_end !== null) && !(live_start && live_end && live_start < live_end)) {
      throw new Error("请填写直播开始和结束时间，结束时间应晚于开始时间");
    }
    const url = `${base()}/${cid}/lessons`;
    const result = await api(item ? `${url}/${item.id}` : url, {
      method: item ? "PUT" : "POST",
      body: JSON.stringify({ title: title.value.trim(), description: description.value, position: Number(order.value), live_start, live_end }),
    });
    notify("课节已保存");
    await navigate(cid, result.id);
  });
  return box;
}

function deleteButton(label, message, url, after) {
  return button(label, async () => {
    ensureIdle();
    if (!await confirmAction(message, { title: label, confirmText: "确认删除", danger: true })) return;
    await api(url, { method: "DELETE" });
    notify("已删除");
    await after();
  }, "button danger-button");
}

async function upload(file, endpoint) {
  const response = await fetch(`/api${endpoint}?name=${encodeURIComponent(file.name)}`, {
    method: "PUT", body: file, headers: { Authorization: `Bearer ${state.token}` },
  });
  if (response.status === 401) window.dispatchEvent(new Event("session-expired"));
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new Error(typeof data?.detail === "string" ? data.detail
      : response.status === 413 ? "文件超过网站上传上限" : "上传失败，请检查文件并重试");
  }
}

async function play(cid, path, type, host, key) {
  closePlayer();
  const video = el("video", "", "course-player");
  video.controls = true;
  video.playsInline = true;
  const hint = el("p", "正在加载视频…", "muted");
  host.replaceChildren(video, hint);
  const current = player = { video };
  playingKey = key;
  video.addEventListener("loadedmetadata", () => { hint.hidden = true; });
  video.addEventListener("error", () => { hint.hidden = false; hint.textContent = "无法播放，请检查登录状态后重试"; });
  try {
    await api("/courses/media-access", { method: "POST" });
    if (player !== current || !host.isConnected) return;
    const url = media(cid, path);
    if (type === "file" || video.canPlayType("application/vnd.apple.mpegurl")) {
      video.src = url;
    } else {
      const { default: Hls } = await import("./vendor/hls/hls.light.min.mjs?v=1.7.4");
      if (player !== current || !host.isConnected) return;
      if (!Hls.isSupported()) throw new Error("此浏览器不支持直播播放，请使用新版 Chrome、Edge 或 Safari");
      const hls = current.hls = new Hls({ lowLatencyMode: false, backBufferLength: 30 });
      hls.on(Hls.Events.ERROR, (_event, error) => {
        if (!error.fatal) return;
        hint.hidden = false;
        hint.textContent = "视频连接中断，请重新点击播放";
        hls.destroy();
        current.hls = null;
      });
      hls.loadSource(url);
      hls.attachMedia(video);
    }
    hint.textContent = "视频加载后可点击播放器中的播放键。";
    void video.play().catch(() => {});
  } catch (error) {
    hint.hidden = false;
    hint.textContent = error.message;
  }
}

function livePanel(host, item, lesson, refresh) {
  host.append(el("h3", statusText[lesson.live_state]));
  if (lesson.live_start !== null) host.append(el("p", `${format(lesson.live_start)} — ${format(lesson.live_end)}（北京时间）`, "muted"));
  if (lesson.last_live_failed) host.append(el("p", "上一次直播没有生成可播放的回放。", "muted"));
  if (lesson.live_state === "live" && lesson.live_id) {
    const videoHost = el("div");
    host.append(button("观看直播", () => play(item.id, playlist(lesson.live_id), "hls", videoHost, lesson.live_id), "button primary"), videoHost);
  } else if (lesson.replays.length && !state.adminMode) {
    host.append(button("查看直播回放", () => { tab = "video"; paintMedia(item, lesson); }));
  }
  if (!state.adminMode) return;
  if (!item.published || lesson.live_start === null || lesson.live_end <= item.server_time) {
    host.append(el("p", !item.published ? "请先发布课程，再准备直播。" : "请在课节编辑中设置一个尚未结束的直播时段。", "muted"));
    return;
  }
  const controls = el("div", "", "course-actions");
  const preview = el("video", "", "course-player course-preview");
  preview.muted = true;
  preview.playsInline = true;
  preview.autoplay = true;
  const status = el("p", "", "muted");
  status.setAttribute("role", "status");
  const sourceButtons = ["camera", "screen"].map((source, index) => button(index ? "屏幕共享 + 麦克风" : "摄像头 + 麦克风", () =>
    prepareCapture({ cid: item.id, lesson, source, serverTime: item.server_time, receivedAt, onChange: updateCapture }),
    index ? "button secondary" : "button primary"));
  const stop = el("button", "取消开播准备", "button danger-button");
  stop.type = "button";
  stop.addEventListener("click", stopCapture);
  function paintCapture(capture) {
    controls.hidden = Boolean(capture);
    stop.hidden = !capture;
    stop.disabled = capture?.stage === "finishing";
    stop.textContent = capture?.stage === "live" ? "结束直播并保存" : capture?.stage === "finishing" ? "正在保存…" : "取消开播准备";
    preview.hidden = !capture?.stream;
    if (preview.srcObject !== (capture?.stream || null)) preview.srcObject = capture?.stream || null;
    status.textContent = capture?.message || "可提前授权设备，到排期时间会自动开播。请保持浏览器页面打开。";
  }
  function updateCapture(capture, result) {
    paintCapture(capture);
    if (result?.message) notify(result.message, result.error ? "error" : "success");
    if (result?.refresh && host.isConnected) void run(refresh);
  }
  controls.append(...sourceButtons);
  host.append(status, controls, preview, stop);
  if (["live", "connecting", "processing"].includes(lesson.live_state) && !getCapture()) {
    controls.hidden = true;
    stop.hidden = true;
    preview.hidden = true;
    status.textContent = "已有直播正在运行或保存，可刷新查看状态。";
    host.append(button("刷新状态", refresh));
    return;
  }
  paintCapture(getCapture());
}

function recordsPanel(host, item, lesson) {
  const url = `${base()}/${item.id}/lessons/${lesson.id}`;
  const refresh = () => navigate(item.id, lesson.id);
  const files = lesson.files.filter(file => file.kind === tab);
  const replays = tab === "video" ? lesson.replays : [];
  const videoHost = el("div");
  if (!files.length && !replays.length) host.append(el("p", `本节课暂无${labels[tab]}。`, "muted"));
  for (const file of files) {
    const row = el("div", "", "course-file");
    row.append(el("strong", file.name), el("span", fileSize(file.size), "muted"));
    row.append(tab === "video" ? button("播放录播", () => play(item.id, `files/${file.id}`, "file", videoHost, file.id))
      : button("下载资料", async () => {
        await api("/courses/media-access", { method: "POST" });
        const link = el("a");
        link.href = media(item.id, `files/${file.id}`);
        link.download = file.name;
        document.body.append(link);
        link.click();
        link.remove();
      }));
    if (state.adminMode) row.append(deleteButton("删除文件", `删除「${file.name}」？`, `${url}/files/${file.id}`, refresh));
    host.append(row);
  }
  for (const replay of replays) {
    const row = el("div", "", "course-file");
    row.append(el("strong", `${format(replay.started)} 直播回放`), el("span", "自动保存", "muted"),
      button("播放回放", () => play(item.id, playlist(replay.id), "hls", videoHost, replay.id)));
    if (state.adminMode) row.append(deleteButton("删除回放", "确认删除这场直播回放？", `${url}/replays/${replay.id}`, refresh));
    host.append(row);
  }
  host.append(videoHost);
  if (!state.adminMode) return;
  const kind = tab;
  const form = el("form", "", "course-form course-upload");
  const file = field(form, kind === "material" ? "选择课程资料" : "选择 MP4 / WebM 视频", "file", {
    type: "file", attributes: { required: true, ...(kind === "video" ? { accept: ".mp4,.webm,video/mp4,video/webm" } : {}) },
  });
  submitForm(form, `上传${labels[kind]}`, async () => {
    await upload(file.files[0], `${url}/files/${kind}`);
    notify(`${labels[kind]}已上传`);
    await refresh();
  });
  host.append(form);
}

function paintMedia(item, lesson) {
  const surface = $("courseMedia");
  if (!surface) return;
  closePlayer();
  surface.replaceChildren();
  const tabs = el("div", "", "course-tabs");
  for (const id of Object.keys(labels)) {
    const control = button(labels[id], () => { ensureIdle(); tab = id; paintMedia(course, course.lessons.find(row => row.id === lessonId)); });
    control.setAttribute("aria-pressed", String(id === tab));
    tabs.append(control);
  }
  const host = el("div", "", "course-media-body");
  surface.append(tabs, host);
  if (tab === "live") livePanel(host, item, lesson, () => navigate(item.id, lesson.id));
  else recordsPanel(host, item, lesson);
}

function paintDetail(item) {
  const back = button("← 返回课程列表", () => navigate());
  root().replaceChildren(header(item.title, item.description || `${item.lessons.length} 节课`, back));
  if (state.adminMode) {
    const tools = el("div", "", "course-admin-tools");
    const badges = el("div", "", "course-actions");
    const access = el("span", accessLabel(item), "course-pill");
    access.id = "courseAccessBadge";
    badges.append(el("span", item.published ? "已发布" : "草稿 · 学员不可见", "course-pill"), access);
    tools.append(badges, courseForm(item), accessForm(item),
      lessonForm(null, item.id, Math.min(10000, 1 + Math.max(0, ...item.lessons.map(row => row.position))), !item.lessons.length),
      deleteButton("删除课程", "此操作会删除此课程的所有课节、资料、录播及直播回放。", `${base()}/${item.id}`, () => navigate()));
    root().append(tools);
  }
  const lesson = item.lessons.find(row => row.id === lessonId);
  if (!lesson) {
    root().append(emptyState("暂无课节", state.adminMode ? "添加课节后即可上传资料、录播或安排直播。" : "课程内容准备中。"));
    return;
  }
  const grid = el("div", "", "course-detail");
  const rail = el("nav", "", "panel course-rail");
  rail.setAttribute("aria-label", "课节目录");
  rail.append(el("h2", "课节目录"));
  item.lessons.forEach((row, index) => {
    const entry = button(`${String(index + 1).padStart(2, "0")}  ${row.title}`, () => navigate(item.id, row.id), "course-lesson-link");
    if (row.id === lesson.id) entry.setAttribute("aria-current", "true");
    rail.append(entry);
  });
  const content = el("article", "", "panel course-lesson");
  content.append(el("div", "本节内容", "eyebrow"), el("h2", lesson.title));
  if (lesson.description) content.append(el("p", lesson.description, "course-description"));
  if (state.adminMode) content.append(lessonForm(lesson, item.id), deleteButton("删除课节", "删除此课节及其所有文件、直播回放？",
    `${base()}/${item.id}/lessons/${lesson.id}`, () => navigate(item.id)));
  const surface = el("div");
  surface.id = "courseMedia";
  content.append(surface);
  grid.append(rail, content);
  root().append(grid);
  paintMedia(item, lesson);
}

function pollLesson(cid, epoch) {
  poll = setTimeout(async () => {
    if (epoch !== generation) return;
    try {
      const next = await api(`/courses/${cid}`);
      if (epoch !== generation) return;
      const old = course.lessons.find(row => row.id === lessonId);
      const current = next.lessons.find(row => row.id === lessonId);
      if (!current) { await navigate(cid); return; }
      course = next;
      const changed = old.live_state !== current.live_state || old.live_id !== current.live_id
        || old.live_start !== current.live_start || old.live_end !== current.live_end || old.replays.length !== current.replays.length;
      if (tab === "live" && changed) { paintMedia(next, current); }
      if (tab === "video" && !playingKey && current.replays.length !== old.replays.length) paintMedia(next, current);
    } catch (error) {
      if (epoch !== generation) return;
      if (error.status === 404) { await navigate(); notify("你当前无法访问这门课程。", "error"); return; }
    }
    if (epoch === generation) pollLesson(cid, epoch);
  }, 3500);
}

export async function refreshCourses() {
  if (getCapture()) return;
  const [, cid, requested] = location.hash.split("/");
  const selected = /^\d+$/.test(cid || "") ? Number(cid) : null;
  const previousId = lessonId;
  clearCourses();
  const epoch = generation;
  if (selected) {
    try {
      const result = await api(`${base()}/${selected}`);
      if (epoch !== generation) return;
      course = result;
      receivedAt = Date.now();
      lessonId = course.lessons.find(row => row.id === Number(requested))?.id || course.lessons[0]?.id;
      if (!tab || previousId !== lessonId) tab = "material";
      paintDetail(course);
      if (!state.adminMode && lessonId) pollLesson(selected, epoch);
      return;
    } catch (error) {
      if (epoch !== generation) return;
      if (error.status !== 404) throw error;
      writeAppRoute(route(), { replace: true });
      if (!state.adminMode) notify("你当前无法访问这门课程。", "error");
    }
  }
  const items = await api(base());
  if (epoch !== generation) return;
  root().replaceChildren(header(state.adminMode ? "课程管理" : "课程", state.adminMode
    ? "创建课程、编排课节，发布资料、录播与直播。" : "查看课程资料、跟随直播，或按自己的进度观看录播。"));
  if (state.adminMode) root().append(courseForm());
  if (!items.length) {
    root().append(emptyState("暂无课程", state.adminMode ? "创建第一门课程，开始编排课节。" : "你有权限观看且已发布的课程会显示在这里。"));
    return;
  }
  const grid = el("div", "", "course-grid");
  for (const item of items) {
    const card = el("article", "", "panel course-card");
    const status = state.adminMode ? ` · ${item.published ? "已发布" : "草稿"} · ${accessLabel(item)}` : "";
    card.append(el("span", `${item.lesson_count} 节课${status}`, "course-pill"),
      el("h2", item.title), el("p", item.description || "暂无课程简介。", "course-description muted"),
      button(state.adminMode ? "管理课程 →" : "进入课程 →", () => navigate(item.id)));
    grid.append(card);
  }
  root().append(grid);
}
