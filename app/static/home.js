/** Renders the authenticated preparation home and published announcement reader. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, notify, confirmAction } from "./ui.js?v=20261114-ui-v17";
import { renderHomeBlocks } from "./home-layout.js?v=20261115-layout-v1";

let notices = [];
let announcementIndex = 0;
let announcementsUnavailable = false;
let releaseAnnouncementImages = null;
let homeRevision = 0;

/** Load private images with the current session; closing the reader cancels and releases them. */
function prepareAnnouncementImage(image, source, session) {
  image.classList.add("announcement-content-image");
  image.removeAttribute("src");
  const match = /^\/api\/(?:admin\/)?announcements\/assets\/([a-f0-9]{32})$/.exec(source);
  if (!match) { image.src = source; return; }
  const status = el("span", "图片加载中…", "announcement-image-status");
  image.hidden = true;
  const load = async () => {
    status.textContent = "图片加载中…";
    try {
      const response = await fetch(announcementAssetUrl(match[1]), {
        headers: { Authorization: `Bearer ${session.token}` }, signal: session.controller.signal,
      });
      if (!response.ok) throw new Error(response.status === 401 ? "登录已过期，请重新登录后查看图片" : "图片加载失败");
      const blob = await response.blob();
      if (session.controller.signal.aborted || state.token !== session.token || !image.isConnected) return;
      const url = URL.createObjectURL(blob); session.urls.add(url);
      image.src = url;
      try { await image.decode(); }
      catch (error) { URL.revokeObjectURL(url); session.urls.delete(url); throw new Error("图片无法显示，请重新上传"); }
      if (session.controller.signal.aborted) return;
      image.hidden = false; status.remove();
    } catch (error) {
      if (session.controller.signal.aborted || !image.isConnected) return;
      status.replaceChildren(el("span", error.message), button("重试", load, "button quiet"));
    }
  };
  return { status, load };
}

function openAnnouncement(item, { returnToList = false } = {}) {
  releaseAnnouncementImages?.();
  const session = { controller: new AbortController(), urls: new Set(), token: state.token };
  releaseAnnouncementImages = () => {
    session.controller.abort();
    session.urls.forEach(url => URL.revokeObjectURL(url));
    session.urls.clear();
  };
  $("announcementDialogTitle").textContent = item.title;
  const body = $("announcementDialogContent");
  body.replaceChildren();
  if (returnToList) body.append(button("← 返回公告列表", openAnnouncementList, "button quiet announcement-list-back"));
  const content = document.createElement("template");
  if (item.cover_url) {
    const image = el("img", "", "announcement-detail-cover");
    image.dataset.assetSource = item.cover_url;
    image.alt = "";
    content.content.append(image);
  }
  if (item.summary) content.content.append(el("p", item.summary, "announcement-summary"));
  const markdown = document.createElement("template");
  markdown.innerHTML = item.body_html || "";
  content.content.append(markdown.content);
  const loads = [];
  for (const image of content.content.querySelectorAll("img")) {
    const task = prepareAnnouncementImage(image, image.dataset.assetSource || image.getAttribute("src") || "", session);
    if (task) { image.before(task.status); loads.push(task.load); }
  }
  body.append(content.content);
  if (!$("announcementDialog").open) $("announcementDialog").showModal();
  body.scrollTop = 0;
  body.querySelector(".announcement-list-back")?.focus({ preventScroll: true });
  loads.forEach(load => { void load(); });
}

function openAnnouncementList() {
  releaseAnnouncementImages?.(); releaseAnnouncementImages = null;
  $("announcementDialogTitle").textContent = "全部公告";
  const body = $("announcementDialogContent");
  body.replaceChildren(el("p", `共 ${notices.length} 条公告`, "announcement-list-count"));
  const list = el("ul", "", "announcement-public-list");
  for (const item of notices) {
    const row = el("li");
    const control = button("", () => openAnnouncement(item, { returnToList: true }), "announcement-public-item");
    const copy = el("span", "", "announcement-public-copy");
    copy.append(el("strong", item.title));
    if (item.summary) copy.append(el("span", item.summary, "announcement-public-summary"));
    if (item.published_at) {
      const date = el("time", new Date(item.published_at * 1000).toLocaleDateString("zh-CN"));
      date.dateTime = new Date(item.published_at * 1000).toISOString();
      copy.append(date);
    }
    const arrow = el("span", "→", "announcement-public-arrow"); arrow.setAttribute("aria-hidden", "true");
    control.append(copy, arrow); row.append(control); list.append(row);
  }
  if (notices.length) body.append(list);
  else body.append(el("p", "暂无已发布的公告。", "empty-state"));
  if (!$("announcementDialog").open) $("announcementDialog").showModal();
  body.scrollTop = 0;
  $("closeAnnouncementDialog").focus({ preventScroll: true });
}

function announcementAssetUrl(assetId) {
  return (state.adminMode ? "/api/admin/announcements/assets/" : "/api/announcements/assets/") + encodeURIComponent(assetId);
}

function renderNotices(root) {
  const band = el("section", "", "home-announcement-band");
  band.setAttribute("aria-label", "平台公告");
  const viewport = el("div", "", "home-announcement-viewport");
  const controls = el("div", "", "home-announcement-controls");
  viewport.setAttribute("aria-live", "polite");
  if (announcementsUnavailable) {
    viewport.append(el("span", "公告暂时无法加载", "home-announcement-error"),
      button("重试", () => { void refreshHome(); }, "text-button home-announcement-retry"));
  } else if (!notices.length) viewport.append(el("span", "暂无公告"));
  else {
    announcementIndex %= notices.length;
    const title = button("", () => openAnnouncement(notices[announcementIndex]), "home-announcement-title");
    const position = el("span", "", "home-announcement-position");
    const showNotice = () => {
      title.textContent = notices[announcementIndex].title;
      position.textContent = notices.length > 1 ? `${announcementIndex + 1} / ${notices.length}` : "";
    };
    showNotice();
    viewport.append(title);
    if (notices.length > 1) {
      const previous = button("‹", () => {
        announcementIndex = (announcementIndex - 1 + notices.length) % notices.length;
        showNotice();
      }, "icon-button");
      previous.setAttribute("aria-label", "上一条公告");
      const next = button("›", () => {
        announcementIndex = (announcementIndex + 1) % notices.length;
        showNotice();
      }, "icon-button");
      next.setAttribute("aria-label", "下一条公告");
      controls.append(position, previous, next);
    }
  }
  const label = button("公告", openAnnouncementList, "home-announcement-label");
  label.title = "查看全部公告";
  band.append(label, viewport);
  if (controls.childNodes.length) band.append(controls);
  root.append(band);
}

function navigate(view, section) {
  document.dispatchEvent(new CustomEvent("navigate-view", { detail: { view, section } }));
}

function renderHome() {
  const root = $("home");
  root.replaceChildren();
  renderNotices(root);
  const hero = el("section", "", "home-welcome");
  hero.append(el("span", "SCU COMPUTER SCIENCE · 2027", "eyebrow"),
    el("h1", "把复试准备，拆成每天能完成的一步。"),
    el("p", "从基础复习、笔试机试到面试表达，按阶段推进。白皮书的重点和优先级已整理成下方导航。", "muted"));
  const actions = el("div", "", "home-actions");
  for (const item of [
    ["training", "每日训练", "题库练习 · 连续签到", "◈"],
    ["interview", "模拟面试", "PPT、语音回答与点评", "◉"],
    ["contest", "上机考试", "限时编程与在线评测", "</>"],
    ["coding", "算法带刷", "分阶段题单 · 每日一题", "⌘"],
  ]) {
    const control = button("", () => navigate(item[0]), "home-action");
    control.append(el("span", item[3], "home-action-icon"), el("span", item[1], "home-action-title"),
      el("span", item[2], "home-action-description"), el("span", "→", "home-action-arrow"));
    actions.append(control);
  }
  hero.append(actions); root.append(hero);
  const content = el("div"); root.append(content);
  const token = state.token, revision = ++homeRevision;
  content.append(el("p", "正在加载备考内容…", "muted"));
  api("/home/layout").then(layout => {
    if (revision !== homeRevision || token !== state.token || !content.isConnected) return;
    content.replaceChildren(); renderHomeBlocks(content, layout.blocks, navigate);
  }).catch(error => {
    if (revision === homeRevision && token === state.token && content.isConnected)
      content.replaceChildren(el("p", error.message, "form-error"), button("重新加载", refreshHome, "button secondary"));
  });
}

export async function refreshHome() {
  try { notices = await api("/announcements"); announcementIndex = 0; announcementsUnavailable = false; }
  catch { notices = []; announcementsUnavailable = true; }
  renderHome();
}

export function setupHome() {
  $("closeAnnouncementDialog").addEventListener("click", () => $("announcementDialog").close());
  $("announcementDialog").addEventListener("close", () => {
    releaseAnnouncementImages?.(); releaseAnnouncementImages = null;
    $("announcementDialogContent").replaceChildren();
  });
}

export async function refreshAnnouncementsAdmin() {
  const root = $("announcementsAdmin");
  const result = await api("/admin/announcements");
  root.replaceChildren();
  const heading = el("header", "", "page-heading");
  const title = el("div");
  title.append(el("span", "CONTENT MANAGEMENT", "eyebrow"), el("h1", "公告管理"),
    el("p", "维护首页公告、图文内容与发布状态。", "muted"));
  heading.append(title, button("新建公告", () => editNotice(null), "button primary"));
  root.append(heading);
  const toolbar = el("div", "", "announcement-admin-toolbar");
  const search = el("input"); search.type = "search"; search.placeholder = "搜索公告标题";
  search.setAttribute("aria-label", "搜索公告标题");
  const status = el("select");
  status.setAttribute("aria-label", "按公告状态筛选");
  for (const [value,label] of [["","全部状态"],["draft","草稿"],["published","已上架"],["withdrawn","已下架"]]) {
    const option = el("option",label); option.value=value; status.append(option);
  }
  const list = el("div", "", "announcement-admin-list"); list.id="announcementAdminList";
  let request = 0;
  let page = 1;
  let searchTimer = null;
  const load = async () => {
    const currentRequest = ++request;
    const query = new URLSearchParams({status:status.value,q:search.value.trim(),page:String(page),page_size:"10"});
    const data = await api("/admin/announcements?" + query);
    if (currentRequest !== request || root.hidden) return;
    if (page > Math.max(1, data.pages)) { page = Math.max(1, data.pages); return load(); }
    list.replaceChildren();
    for (const item of data.items) {
      const row=el("article","","announcement-admin-row");
      const copy=el("div");
      copy.append(el("strong",item.title),el("small",statusLabel(item.status)+" · "+item.summary));
      const controls=el("div","","action-group");
      controls.append(button("编辑",()=>editNotice(item),"button secondary"));
      controls.append(button("预览",()=>openAnnouncement(item),"button quiet"));
      controls.append(button(item.status==="published"?"下架":"上架",async()=>{
        await api("/admin/announcements/"+item.id+"/status",{method:"POST",body:JSON.stringify({status:item.status==="published"?"withdrawn":"published"})});
        await load();
      },item.status==="published"?"button quiet":"button secondary"));
      row.append(copy,controls);list.append(row);
    }
    if(!data.items.length)list.append(el("p","当前没有匹配的公告。","empty-state"));
    toolbar.querySelector(".announcement-admin-pagination")?.remove();
    if(data.pages>1){
      const pagination=el("nav","","announcement-admin-pagination");pagination.setAttribute("aria-label","公告列表分页");
      const previous=button("上一页",()=>{page--;void load().catch(error=>notify(error.message,"error"));},"button secondary");previous.disabled=page<=1;
      const next=button("下一页",()=>{page++;void load().catch(error=>notify(error.message,"error"));},"button secondary");next.disabled=page>=data.pages;
      pagination.append(previous,el("span",`第 ${page} / ${data.pages} 页 · 共 ${data.total} 条`),next);toolbar.append(pagination);
    }
  };
  toolbar.append(search,status);
  search.addEventListener("input",()=>{
    clearTimeout(searchTimer);
    searchTimer = setTimeout(()=>{page=1;void load().catch(error=>notify(error.message,"error"));},180);
  });
  status.addEventListener("change",()=>{page=1;void load().catch(error=>notify(error.message,"error"));});
  root.append(toolbar,list);
  await load();
}

function statusLabel(status) {
  return status==="published"?"已上架":status==="withdrawn"?"已下架":"草稿";
}

function editNotice(item) {
  const root=$("announcementsAdmin");
  const heading=root.querySelector(":scope > .page-heading");
  const toolbar=root.querySelector(":scope > .announcement-admin-toolbar");
  const list=root.querySelector(":scope > .announcement-admin-list");
  if(heading)heading.hidden=true;
  if(toolbar)toolbar.hidden=true;
  if(list)list.hidden=true;
  root.querySelector(".announcement-editor")?.remove();
  const form=el("form","","panel announcement-editor");
  const title=el("input");title.required=true;title.maxLength=120;title.value=item?.title||"";
  const summary=el("input");summary.maxLength=500;summary.value=item?.summary||"";
  const cover=el("input");cover.value=item?.cover_url||"";
  const coverFile=el("input");coverFile.type="file";coverFile.accept="image/png,image/jpeg,image/webp";coverFile.hidden=true;
  const coverUpload=button("上传封面",()=>coverFile.click(),"button quiet");
  coverFile.addEventListener("change",async()=>{
    const file=coverFile.files?.[0];if(!file)return;
    if(file.size>5*1024*1024){notify("图片不能超过 5 MB","error");return;}
    const data=new FormData();data.append("file",file);
    try{const uploaded=await api("/admin/announcements/assets",{method:"POST",body:data});cover.value=uploaded.url;}
    catch(error){notify(error.message,"error");}
    finally{coverFile.value="";}
  });
  const titleLabel=el("label","标题");titleLabel.append(title);
  const summaryLabel=el("label","摘要");summaryLabel.append(summary);
  const coverLabel=el("label","封面图片地址");coverLabel.append(cover);
  const markdown=el("textarea");markdown.rows=16;markdown.maxLength=100000;
  markdown.className="announcement-markdown-editor";markdown.value=item?.body_markdown||"";
  markdown.setAttribute("aria-label","公告 Markdown 正文");
  async function uploadInlineImage(file){
    if(file.size>5*1024*1024)throw new Error("图片不能超过 5 MB");
    if(!["image/png","image/jpeg","image/webp"].includes(file.type))throw new Error("粘贴图片仅支持 PNG、JPEG 或 WebP");
    const data=new FormData();data.append("file",file,file.name||"pasted-image.png");
    return api("/admin/announcements/assets",{method:"POST",body:data});
  }
  markdown.addEventListener("paste",async event=>{
    const images=[...(event.clipboardData?.items||[])].filter(part=>part.type.startsWith("image/"));
    if(!images.length)return;
    event.preventDefault();
    for(const part of images){
      const file=part.getAsFile();if(!file)continue;
      try{
        const uploaded=await uploadInlineImage(file);
        const alt=(file.name||"公告图片").replace(/[\[\]\\]/g,"");
        const value=`![${alt}](${uploaded.url})`;
        const start=markdown.selectionStart,end=markdown.selectionEnd;
        markdown.setRangeText(value,start,end,"end");markdown.dispatchEvent(new Event("input",{bubbles:true}));
        markdown.focus();
      }catch(error){notify(error.message,"error");}
    }
  });
  const blockHeading=el("div","","announcement-editor-heading");
  blockHeading.append(el("h2","公告正文 · Markdown"),el("p","支持标题、列表、引用、表格和链接。将图片粘贴到正文框，会自动上传并插入图片引用。","muted"));
  const imageInput=el("input");imageInput.type="file";imageInput.accept="image/png,image/jpeg,image/webp";imageInput.hidden=true;
  const addImage=button("插入图片",()=>imageInput.click(),"button quiet");
  imageInput.addEventListener("change",async()=>{
    const file=imageInput.files?.[0];if(!file)return;
    try{
      const uploaded=await uploadInlineImage(file);
      const alt=file.name.replace(/[\[\]\\]/g,"")||"公告图片";
      markdown.setRangeText(`![${alt}](${uploaded.url})`,markdown.selectionStart,markdown.selectionEnd,"end");
      markdown.focus();
    }catch(error){notify(error.message,"error");}
    finally{imageInput.value="";}
  });
  const actions=el("div","","action-group");
  const values=()=>({title:title.value,summary:summary.value,cover_url:cover.value,body_markdown:markdown.value});
  let original=JSON.stringify(values());
  actions.append(button("取消",async()=>{
    if(JSON.stringify(values())!==original&&!await confirmAction("公告有尚未保存的修改，确定放弃吗？"))return;
    form.remove();
    for(const node of [heading,toolbar,list])if(node)node.hidden=false;
  },"button quiet"));
  actions.append(button("预览",async()=>{
    try{
      const preview=await api("/admin/announcements/preview",{method:"POST",body:JSON.stringify({
        title:title.value,summary:summary.value,cover_url:cover.value,body_markdown:markdown.value})});
      openAnnouncement(preview);
    }catch(error){notify(error.message,"error");}
  },"button secondary"));
  actions.append(button("保存草稿",async()=>{
    const payload={title:title.value,summary:summary.value,cover_url:cover.value,body_markdown:markdown.value};
    const saved=await api(item?"/admin/announcements/"+item.id:"/admin/announcements",{
      method:item?"PUT":"POST",body:JSON.stringify(payload)});
    original=JSON.stringify(payload);
    notify("公告草稿已保存");
    if(!item)editNotice(saved);else await refreshAnnouncementsAdmin();
  },"button primary"));
  form.append(titleLabel,summaryLabel,coverLabel,coverUpload,coverFile,blockHeading,markdown,addImage,imageInput,actions);
  root.append(form);form.scrollIntoView({behavior:"smooth",block:"start"});
}
