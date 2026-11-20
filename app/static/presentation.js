/** Private slide preview; recordings stay in the owning interview component. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { el, button, notify, run, confirmAction } from "./ui.js?v=20261114-ui-v17";

const positions = new Map();
const previews = new Set();
let generation = 0;
let keyboardController = null;
export function releasePresentation() {
  generation++;
  keyboardController?.abort();
  keyboardController = null;
  previews.forEach((url) => URL.revokeObjectURL(url));
  previews.clear();
}
export function clearPresentation() {
  releasePresentation();
  positions.clear();
}
export function presentationView(item, readOnly, controls, options = {}) {
  const root = el("section", "", "presentation-view");
  const meta = el("div", "", "presentation-meta");
  meta.append(el("span", "YOUR PRESENTATION", "eyebrow"));
  root.append(meta);
  const template = item.default_presentation;
  const showTemplate =
    !item.presentation && !readOnly && options.showDefaultPreview !== false;
  const waitingToStart = item.presentation && !item.started_at && !readOnly;
  const presentation = item.presentation || (showTemplate ? template : null);
  if (!state.adminMode && !options.hideTemplateReference) {
    const reference = el("aside", "", "template-reference");
    reference.append(el("strong", template.notice));
    const links = el("div", "", "template-links");
    const download = el(
      "a",
      `↓ 下载 ${template.year} 年复试 PPT 模板`,
      "text-button",
    );
    download.href = template.download_url;
    download.setAttribute("download", template.name);
    const official = el("a", "前往复试官网 ↗", "text-button");
    official.href = template.source_url;
    official.target = "_blank";
    official.rel = "noopener noreferrer";
    links.append(download, official);
    reference.append(links);
    root.append(reference);
  }
  if (!item.presentation) {
    root.append(el("h3", readOnly ? "未上传演示文件" : "先上传你的复试 PPT"));
    root.append(
      el(
        "p",
        "用自己的幻灯片介绍经历、项目与研究兴趣。上传并点击开始面试后，边放映边录音，完成自我介绍。",
      ),
    );
  }
  if (presentation && !waitingToStart) {
    const info = el("div", "", "presentation-file");
    info.append(
      el(
        "strong",
        showTemplate
          ? `${template.year} 年复试 PPT 模板预览`
          : presentation.name,
      ),
      el(
        "span",
        `${presentation.pages} 页 · ${showTemplate ? "参考模板" : "已保存"}`,
        showTemplate ? "badge orange" : "badge green",
      ),
    );
    root.append(info);
    const viewer = el("div", "", "slide-viewer");
    viewer.tabIndex = 0;
    viewer.setAttribute("aria-label", "PPT 放映区，可使用上下方向键翻页");
    const image = el("img", "", "slide-image");
    image.hidden = true;
    const status = el("p", "正在加载演示页…", "slide-status");
    status.setAttribute("role", "status");
    viewer.append(image, status);
    root.append(viewer);
    const key = `${item.id}:${showTemplate ? "template" : "uploaded"}:${presentation.name}`;
    let page = Math.min(positions.get(key) || 1, presentation.pages);
    let request = 0;
    const token = generation;
    const counter = el("span", "", "slide-counter");
    const previous = el("button", "← 上一页", "button secondary");
    const next = el("button", "下一页 →", "button secondary");
    previous.type = next.type = "button";
    previous.addEventListener("click", () => {
      void show(page - 1);
    });
    next.addEventListener("click", () => {
      void show(page + 1);
    });
    let currentUrl;
    async function show(number) {
      page = Math.max(1, Math.min(number, presentation.pages));
      positions.set(key, page);
      const turn = ++request;
      previous.disabled = page === 1;
      next.disabled = page === presentation.pages;
      counter.textContent = `${page} / ${presentation.pages}`;
      image.hidden = true;
      status.hidden = false;
      status.textContent = "正在加载演示页…";
      try {
        const response = await fetch(
          showTemplate
            ? `${template.pages_url}/${page}`
            : `/api${state.adminMode ? "/admin" : ""}/interviews/${item.id}/presentation/pages/${page}`,
          {
            headers: { Authorization: `Bearer ${state.token}` },
          },
        );
        if (!response.ok) throw new Error("演示页读取失败，请重试或刷新页面。");
        const blob = await response.blob();
        if (turn !== request || token !== generation) return;
        if (currentUrl) {
          URL.revokeObjectURL(currentUrl);
          previews.delete(currentUrl);
        }
        currentUrl = URL.createObjectURL(blob);
        previews.add(currentUrl);
        image.src = currentUrl;
        image.alt = `${presentation.name}，第 ${page} 页`;
        image.hidden = false;
        status.hidden = true;
      } catch (error) {
        if (turn === request && token === generation)
          status.textContent = error.message;
      }
    }
    const toolbar = el("div", "", "slide-toolbar");
    toolbar.append(previous, counter, next);
    const focus = button(
      "⛶ 全屏放映",
      async () => {
        const session = root.closest(".presentation-session") || root;
        if (document.fullscreenElement) await document.exitFullscreen();
        else if (session.requestFullscreen) await session.requestFullscreen();
        else throw new Error("当前浏览器不支持全屏，请使用浏览器的全屏模式。");
      },
      "text-button",
    );
    toolbar.append(focus);
    root.append(toolbar);
    keyboardController?.abort();
    keyboardController = new AbortController();
    document.addEventListener("keydown", (event) => {
      if (!["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"].includes(event.key) ||
          event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey ||
          !viewer.isConnected || viewer.closest("[hidden]") || document.querySelector("dialog[open]") ||
          event.target.closest("input, textarea, select, [contenteditable='true'], .stage-drawer, .expert-question-scroll")) return;
      event.preventDefault();
      void show(page + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1));
    }, { signal: keyboardController.signal });
    root.append(
      button("重新加载本页", () => show(page), "text-button slide-retry"),
    );
    void show(page);
  } else if (waitingToStart) {
    const gate = el("div", "", "presentation-start-gate");
    gate.append(
      el("span", "READY WHEN YOU ARE", "eyebrow"),
      el("h3", "PPT 已就绪，准备好后再开始"),
      el("p", "请点击页面底部的「开始模拟面试」。进入面试后展示 PPT、自动开启全程录音，并启动严格 10 分钟倒计时，最后 1 分钟显示红色提醒。"),
      el("p", item.presentation.name + (item.presentation.pages ? ` · ${item.presentation.pages} 页` : " · 已选择，等待开始"), "presentation-ready-file"),
    );
    root.append(gate);
  }
  if (!readOnly && !item.intro_completed && !item.started_at) {
    const label = el(
      "label",
      item.presentation ? "替换演示文件" : "选择演示文件",
      "presentation-upload-label",
    );
    const input = el("input");
    input.type = "file";
    input.accept = ".ppt,.pptx,.pdf";
    input.setAttribute("aria-label", label.textContent);
    const hint = el(
      "p",
      `支持 PPT / PPTX / PDF，最大 ${item.presentation_limits.max_mb} MB、${item.presentation_limits.max_pages} 页。转换为静态幻灯片，动画与嵌入音视频不播放。`,
      "field-hint",
    );
    const status = el("span", "", "presentation-upload-status");
    status.setAttribute("role", "status");
    input.addEventListener("change", () =>
      run(async () => {
        if (!input.files.length || !controls.allowNavigation()) {
          input.value = "";
          return;
        }
        const file = input.files[0];
        if (file.size > item.presentation_limits.max_mb * 1024 * 1024) {
          input.value = "";
          throw new Error(`文件不能超过 ${item.presentation_limits.max_mb} MB`);
        }
        if (
          item.id && item.presentation &&
          !await confirmAction("替换 PPT 将清空本环节已保存的录音与回答，是否继续？")
        ) {
          input.value = "";
          return;
        }
        if (!item.id) {
          controls.selected(file);
          return;
        }
        controls.setBusy(true);
        input.disabled = true;
        status.textContent = "正在上传并转换，请稍候…";
        try {
          const form = new FormData();
          form.append("file", file);
          const updated = await api(`/interviews/${item.id}/presentation`, {
            method: "POST",
            body: form,
          });
          positions.delete(`${item.id}:uploaded:${updated.presentation.name}`);
          controls.uploaded(updated);
          notify(updated.workflow_version >= 3 && !updated.started_at
            ? "PPT 已保存，点击「开始本轮面试」进入自我介绍。"
            : "PPT 已保存，现在可以边放映边录音完成自我介绍。");
        } finally {
          controls.setBusy(false);
          input.disabled = false;
          input.value = "";
          status.textContent = "";
        }
      }),
    );
    label.append(input);
    if (item.presentation) {
      const replace = el("details", "", "presentation-replace");
      replace.append(
        el("summary", item.id ? "替换 PPT（将清空本环节录音与回答）" : "重新选择 PPT"),
        label,
        hint,
        status,
      );
      root.append(replace);
    } else root.append(label, hint, status);
  }
  return root;
}
