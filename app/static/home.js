/** Renders the authenticated preparation home and published announcement reader. */
import { api, state } from "./api.js?v=20261114-ui-v17";
import { $, el, button, notify } from "./ui.js?v=20261114-ui-v17";

let timer = null;
let notices = [];
let activeNotice = 0;

function openAnnouncement(item) {
  $("announcementDialogTitle").textContent = item.title;
  const body = $("announcementDialogContent");
  body.replaceChildren();
  if (item.cover_url) {
    const image = el("img", "", "announcement-detail-cover");
    image.src = state.adminMode
      ? item.cover_url.replace("/api/announcements/assets/", "/api/admin/announcements/assets/")
      : item.cover_url;
    image.alt = "";
    body.append(image);
  }
  if (item.summary) body.append(el("p", item.summary, "announcement-summary"));
  for (const block of item.blocks) {
    if (block.type === "heading") body.append(el("h3", block.text));
    else if (block.type === "paragraph") body.append(el("p", block.text));
    else if (block.type === "image") {
      const image = el("img", "", "announcement-content-image");
      image.src = announcementAssetUrl(block.asset_id);
      image.alt = block.alt || "";
      body.append(image);
    } else if (block.type === "link") {
      const link = el("a", block.text + " ↗", "announcement-content-link");
      link.href = block.url; link.target = "_blank"; link.rel = "noopener noreferrer";
      body.append(link);
    }
  }
  $("announcementDialog").showModal();
}

function announcementAssetUrl(assetId) {
  return (state.adminMode ? "/api/admin/announcements/assets/" : "/api/announcements/assets/") + encodeURIComponent(assetId);
}

function renderNotices(root) {
  const band = el("section", "", "home-announcement-band");
  band.setAttribute("aria-label", "平台公告");
  const current = notices[activeNotice];
  const open = button(current ? current.title : "暂无公告", () => current && openAnnouncement(current), "home-announcement-title");
  open.disabled = !current;
  band.append(el("span", "公告", "home-announcement-label"), open);
  if (notices.length > 1) {
    const controls = el("div", "", "home-announcement-controls");
    controls.append(button("‹", () => { activeNotice = (activeNotice + notices.length - 1) % notices.length; renderHome(); }, "icon-button"));
    controls.append(button("›", () => { activeNotice = (activeNotice + 1) % notices.length; renderHome(); }, "icon-button"));
    band.append(controls);
  }
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
  ]) {
    const control = button("", () => navigate(item[0]), "home-action");
    control.append(el("span", item[3], "home-action-icon"), el("span", item[1], "home-action-title"),
      el("span", item[2], "home-action-description"), el("span", "→", "home-action-arrow"));
    actions.append(control);
  }
  hero.append(actions); root.append(hero);
  const roadmap = el("section", "", "home-roadmap");
  const heading = el("div", "", "home-section-heading");
  heading.append(el("div", "复试准备路线", "eyebrow"), el("h2", "先夯实基础，再练习表达"));
  roadmap.append(heading);
  const stages = el("div", "", "home-roadmap-steps");
  for (const item of [
    ["01", "基础与 AI", "数学基础 · 机器学习 · 深度学习 · LLM"],
    ["02", "笔试与机试", "软件工程 · AI 笔试 · 文献翻译 · 算法题"],
    ["03", "面试准备", "专业课 · 英文 · PPT 自我介绍 · 专家问答"],
  ]) {
    const stage = el("article", "", "home-roadmap-stage");
    stage.append(el("span", item[0], "home-stage-number"), el("h3", item[1]), el("p", item[2]));
    stages.append(stage);
  }
  roadmap.append(stages); root.append(roadmap);
  fetch("/api/home/resources", { headers: { Authorization: "Bearer " + state.token } }).then(response => {
    if (!response.ok) throw new Error("备考资源暂时无法读取");
    return response.json();
  }).then(resources => {
    if ($("home").hidden) return;
    const groups = [...new Set(resources.map(item => item.group))];
    for (const group of groups) {
      const section = el("section", "", "home-resource-section");
      section.append(el("div", group, "eyebrow"));
      const grid = el("div", "", "home-resource-grid");
      for (const item of resources.filter(resource => resource.group === group)) {
        const control = button("", () => {
          if (item.kind === "external") window.open(item.url, "_blank", "noopener,noreferrer");
          else navigate(item.view, item.section);
        }, "home-resource-card");
        control.append(el("span", "★".repeat(item.stars) + "☆".repeat(5-item.stars), "home-resource-stars"),
          el("strong", item.title), el("span", item.summary, "home-resource-summary"));
        if (item.notice) control.append(el("small", item.notice, "home-resource-notice"));
        if (item.kind === "external") control.append(el("span", "外部资料 ↗", "home-resource-type"));
        grid.append(control);
      }
      section.append(grid); root.append(section);
    }
  }).catch(error => notify(error.message, "error"));
}

export async function refreshHome() {
  clearInterval(timer); timer = null;
  try { notices = await api("/announcements"); }
  catch (error) { notices = []; notify(error.message, "error"); }
  activeNotice = Math.min(activeNotice, Math.max(0, notices.length - 1));
  renderHome();
  if (notices.length > 1) timer = setInterval(() => {
    activeNotice = (activeNotice + 1) % notices.length;
    const root=$("home");root.querySelector(".home-announcement-band")?.remove();renderNotices(root);
  }, 8000);
}

export function setupHome() {
  $("closeAnnouncementDialog").addEventListener("click", () => $("announcementDialog").close());
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
  const status = el("select");
  for (const [value,label] of [["","全部状态"],["draft","草稿"],["published","已上架"],["withdrawn","已下架"]]) {
    const option = el("option",label); option.value=value; status.append(option);
  }
  const list = el("div", "", "announcement-admin-list"); list.id="announcementAdminList";
  const load = async () => {
    const query = new URLSearchParams({status:status.value,q:search.value.trim()});
    const data = await api("/admin/announcements?" + query);
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
  };
  toolbar.append(search,status);
  search.addEventListener("input",()=>void load().catch(error=>notify(error.message,"error")));
  status.addEventListener("change",()=>void load().catch(error=>notify(error.message,"error")));
  root.append(toolbar,list);
  await load();
}

function statusLabel(status) {
  return status==="published"?"已上架":status==="withdrawn"?"已下架":"草稿";
}

function editNotice(item) {
  const root=$("announcementsAdmin");
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
  const blocks=structuredClone(item?.blocks||[]);
  const editor=el("div","","announcement-block-editor");
  const addControl=el("div","","announcement-block-actions");
  function renderBlocks(){
    editor.replaceChildren();
    blocks.forEach((block,index)=>{
      const row=el("article","","announcement-block-row");
      const kind=el("strong",block.type==="heading"?"小标题":block.type==="paragraph"?"正文":block.type==="image"?"图片":"外部链接");
      row.append(kind);
      if(block.type==="image"){
      const image=el("img","","announcement-block-preview");
        image.src=block.asset_id?announcementAssetUrl(block.asset_id):block.url;
        image.alt=block.alt||"";row.append(image);
      }else{
        const input=el("textarea");input.rows=block.type==="paragraph"?4:2;
        input.value=block.type==="link"?block.text:block.text||"";
        input.addEventListener("input",()=>{block.text=input.value;});
        row.append(input);
        if(block.type==="link"){
          const url=el("input");url.type="url";url.required=true;url.placeholder="https://";url.value=block.url||"";
          url.addEventListener("input",()=>{block.url=url.value;});row.append(url);
        }
      }
      row.append(button("移除",()=>{blocks.splice(index,1);renderBlocks();},"text-button danger"));
      editor.append(row);
    });
  }
  for(const [kind,label] of [["heading","添加小标题"],["paragraph","添加正文"],["link","添加外部链接"]]){
    addControl.append(button(label,()=>{blocks.push(kind==="link"?{type:kind,text:"链接标题",url:"https://"}:{type:kind,text:""});renderBlocks();},"button quiet"));
  }
  const imageInput=el("input");imageInput.type="file";imageInput.accept="image/png,image/jpeg,image/webp";imageInput.hidden=true;
  const addImage=button("上传图片",()=>imageInput.click(),"button quiet");
  imageInput.addEventListener("change",async()=>{
    const file=imageInput.files?.[0];if(!file)return;
    if(file.size>5*1024*1024){notify("图片不能超过 5 MB","error");return;}
    const data=new FormData();data.append("file",file);
    try{
      const uploaded=await api("/admin/announcements/assets",{method:"POST",body:data});
      blocks.push({type:"image",asset_id:uploaded.asset_id,alt:file.name});renderBlocks();
    }catch(error){notify(error.message,"error");}
    finally{imageInput.value="";}
  });
  const blockHeading=el("div","","announcement-editor-heading");
  blockHeading.append(el("h2","公告正文"),el("p","内容以文字、图片和外链组成，页面不会执行自定义 HTML。","muted"));
  renderBlocks();
  const actions=el("div","","action-group");
  actions.append(button("取消",()=>form.remove(),"button quiet"));
  actions.append(button("预览",()=>{
    const preview={id:item?.id||0,title:title.value,summary:summary.value,cover_url:cover.value,blocks,status:"draft"};
    openAnnouncement(preview);
  },"button secondary"));
  actions.append(button("保存草稿",async()=>{
    const payload={title:title.value,summary:summary.value,cover_url:cover.value,blocks};
    const saved=await api(item?"/admin/announcements/"+item.id:"/admin/announcements",{
      method:item?"PUT":"POST",body:JSON.stringify(payload)});
    notify("公告草稿已保存");
    if(!item)editNotice(saved);else await refreshAnnouncementsAdmin();
  },"button primary"));
  form.append(titleLabel,summaryLabel,coverLabel,coverUpload,coverFile,blockHeading,addControl,addImage,imageInput,editor,actions);
  root.append(form);form.scrollIntoView({behavior:"smooth",block:"start"});
}
