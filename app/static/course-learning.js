import {api,state} from './api.js?v=20261114-ui-v17';
import {el,button,notify,run,confirmAction} from './ui.js?v=20261114-ui-v17';
import {modal,field,input,textArea,uploadFile} from './live-ui.js?v=1';
import {renderProblemMath} from './problem-content.js?v=20261121-question-images-v1';
import {mountCourseReader,exitCourseReaderFullscreen} from './course-reader.mjs?v=20261121-reader-v3';
import {courseCatalogScope} from './live-model.mjs?v=20261121-markdown-v1';
import {mountMarkdownWorkspace} from './course-markdown-workspace.js?v=20261121-v1';

let goTo=()=>{},generation=0,courseCompletionCleanup=()=>{},courseReaderCleanup=()=>{},markdownCleanup=()=>{};
const courseProgressFlushers=new Set();
const orderSaves=new WeakMap();
const root=()=>document.getElementById('liveContent');
const json=body=>JSON.stringify(body);
async function flushCourseProgress(){
  for(const flush of courseProgressFlushers){if(!await flush())return false;}
  courseProgressFlushers.clear();return true;
}
const route=async(path)=>{courseCompletionCleanup();courseCompletionCleanup=()=>{};root()?.querySelectorAll('video').forEach(player=>player.pause());if(!await flushCourseProgress())return;return goTo(path);};
const refreshManagedCourse=(id,editor)=>renderCoursePage(editor?{kind:'editor',id,step:'content'}:{kind:'course',id});
const hostName=course=>course.host_name||'';
function pageTitle(title,description=''){
  const box=el('div','','course-heading-copy');box.append(el('h1',title));
  if(description)box.append(el('p',description));return box;
}
function renderMarkdownInto(node,html){
  const template=el('template');template.innerHTML=html||'';
  const images=[...template.content.querySelectorAll('img')].map(image=>{
    const path=image.getAttribute('src');image.removeAttribute('src');
    return {image,path};
  });
  node.replaceChildren(template.content);
  for(const {image,path} of images){
    const unavailable=()=>image.replaceWith(el('span',image.alt?'图片无法加载：'+image.alt: '图片无法加载','course-image-unavailable'));
    if(!/^\/api\/courses\/markdown-images\/[a-f0-9]{32}$/.test(path||'')){unavailable();continue;}
    image.decoding='async';
    fetch(path,{headers:{Authorization:`Bearer ${state.token}`}}).then(response=>{
      if(!response.ok)throw new Error('图片暂时不可用');return response.blob();
    }).then(blob=>{
      if(!node.contains(image))return;
      const url=URL.createObjectURL(blob);image.src=url;
      return image.decode().catch(unavailable).finally(()=>URL.revokeObjectURL(url));
    }).catch(unavailable);
  }
  void renderProblemMath(node);
}
function wireDragReorder(container,selector,endpoint,courseId,editor=true){
  let dragged=null,original=[];
  refreshOrderControls(container,selector);
  const visibleRows=()=>orderedRows(container,selector).filter(row=>!row.hidden);
  container.addEventListener('dragstart',event=>{
    const handle=event.target.closest('.course-drag-handle');
    if(!handle)return;
    dragged=handle.closest(selector);
    if(!dragged)return;
    original=[...container.querySelectorAll(`:scope > ${selector}`)].map(row=>row.dataset.orderId);
    dragged.classList.add('is-dragging');
    event.dataTransfer.effectAllowed='move';
    event.dataTransfer.setData('text/plain',dragged.dataset.orderId);
  });
  container.addEventListener('dragover',event=>{
    if(!dragged)return;
    const target=event.target.closest(selector);
    if(!target||target===dragged||target.parentElement!==container)return;
    if(target.hidden)return;
    event.preventDefault();
    const bounds=target.getBoundingClientRect();const after=event.clientY>bounds.top+bounds.height/2;
    if((after&&target.nextElementSibling===dragged)||(!after&&target.previousElementSibling===dragged))return;
    const rows=visibleRows();rows.forEach(row=>row.getAnimations?.().forEach(animation=>animation.cancel()));const before=new Map(rows.filter(row=>row!==dragged).map(row=>[row,row.getBoundingClientRect().top]));
    container.insertBefore(dragged,after?target.nextSibling:target);
    if(window.matchMedia('(prefers-reduced-motion: reduce)').matches)return;
    rows.forEach(row=>{if(row===dragged)return;const offset=before.get(row)-row.getBoundingClientRect().top;if(Math.abs(offset)>=1&&row.animate)row.animate([{transform:`translateY(${offset}px)`},{transform:'translateY(0)'}],{duration:150,easing:'cubic-bezier(.2,.75,.25,1)'});});
  });
  container.addEventListener('dragend',()=>{
    if(!dragged)return;
    dragged.classList.remove('is-dragging');dragged=null;
    const ids=[...container.querySelectorAll(`:scope > ${selector}`)].map(row=>Number(row.dataset.orderId));
    if(ids.join(',')===original.join(','))return;
    refreshOrderControls(container,selector);
    void run(()=>saveCourseOrder(container,selector,endpoint,courseId,editor));
  });
}
function orderedRows(container,selector){return [...container.querySelectorAll(`:scope > ${selector}`)];}
function refreshOrderControls(container,selector){
  orderedRows(container,selector).forEach((row,index)=>{
    const marker=selector==='.course-chapter'?row.querySelector('.course-chapter-toggle .course-order-number'):row.querySelector('.course-lesson-number');
    if(marker)marker.textContent=String(index+1).padStart(2,'0');
  });
}
function chapterPagination(container,pageSize=8){
  const total=orderedRows(container,'.course-chapter').length;if(total<=pageSize)return null;
  const nav=el('nav','','course-chapter-pagination');nav.setAttribute('aria-label','章节目录分页');let page=0;
  const previous=el('button','上一页','button secondary');previous.type='button';
  const status=el('span','','course-muted');
  const next=el('button','下一页','button secondary');next.type='button';
  const update=()=>{orderedRows(container,'.course-chapter').forEach((chapter,index)=>{chapter.hidden=Math.floor(index/pageSize)!==page;});previous.disabled=page===0;next.disabled=page>=Math.ceil(total/pageSize)-1;status.textContent=`第 ${page+1} / ${Math.ceil(total/pageSize)} 页 · ${total} 个章节`;};
  previous.addEventListener('click',()=>{if(page>0){page--;update();}});
  next.addEventListener('click',()=>{if(page<Math.ceil(total/pageSize)-1){page++;update();}});
  nav.append(previous,status,next);update();return nav;
}
async function saveCourseOrder(container,selector,endpoint,courseId,editor){
  const previous=orderSaves.get(container)||Promise.resolve();
  const saving=previous.catch(()=>{}).then(()=>api(endpoint,{method:'PUT',body:json({ids:orderedRows(container,selector).map(row=>Number(row.dataset.orderId))})}));
  orderSaves.set(container,saving);
  try{await saving;}
  catch(error){if(orderSaves.get(container)===saving){await refreshManagedCourse(courseId,editor);throw error;}return;}
  finally{if(orderSaves.get(container)===saving)orderSaves.delete(container);}
}
function markdownContent(html,className='course-markdown-content'){
  const node=el('div','',className);renderMarkdownInto(node,html);return node;
}
function courseModal(title,description='',wide=false){
  const context=modal(title,description);context.dialog.classList.add('course-admin-dialog');
  if(wide)context.dialog.classList.add('course-admin-dialog-wide');
  return context;
}
function markdownEditor(label,value,{imagePath,rows=10,maxLength,hint='',empty='没有可预览的内容。'}={}){
  const container=el('section','','course-editor-markdown');const editor=textArea(value);
  editor.id=`course-markdown-${crypto.randomUUID()}`;editor.rows=rows;editor.spellcheck=false;
  editor.className='course-markdown-editor';editor.placeholder='在这里编写 Markdown…';
  if(maxLength)editor.maxLength=maxLength;
  const heading=el('div','','course-markdown-heading');const title=el('label',label);title.htmlFor=editor.id;
  const help=el('small',hint||'支持 Markdown 和公式。复制截图或图片后，可直接粘贴到正文。','course-markdown-help');
  help.id=editor.id+'-help';editor.setAttribute('aria-describedby',help.id);
  const status=el('p','','course-markdown-status');status.setAttribute('role','status');status.hidden=true;
  const message=(text,error=false)=>{status.hidden=!text;status.textContent=text;status.classList.toggle('is-error',error);};
  const toolbar=el('div','','course-markdown-controls');toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','Markdown 显示方式');
  const preview=el('div','','course-editor-markdown-preview');preview.hidden=true;
  let saveControl=null,uploading=false;
  const setMode=show=>{
    editor.hidden=show;preview.hidden=!show;
    edit.setAttribute('aria-pressed',String(!show));showPreview.setAttribute('aria-pressed',String(show));
  };
  const edit=button('编辑',()=>{setMode(false);editor.focus();},'course-markdown-mode');
  const showPreview=button('预览',async()=>{
    if(!editor.value.trim()){preview.replaceChildren(el('p',empty));setMode(true);return;}
    editor.readOnly=true;message('正在生成预览…');
    try{
      const response=await fetch('/api/courses/markdown/preview',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${state.token}`},body:json({markdown:editor.value})});
      if(!response.ok)throw new Error('预览暂时不可用，请重试');
      preview.replaceChildren(markdownContent(await response.text(),'course-reading-body'));setMode(true);message('');
    }catch(error){message(error.message,true);}finally{editor.readOnly=uploading;}
  },'course-markdown-mode');
  setMode(false);toolbar.append(edit,showPreview);heading.append(title,toolbar);container.append(heading,help,editor,preview,status);
  editor.addEventListener('paste',async event=>{
    const images=[...(event.clipboardData?.files||[])].filter(file=>file.type.startsWith('image/'));
    if(!images.length)return;
    event.preventDefault();if(uploading||editor.readOnly||saveControl?.disabled)return;
    if(!imagePath){message('请先保存草稿，再打开此处粘贴图片。',true);return;}
    const start=editor.selectionStart,end=editor.selectionEnd;
    const imageLinks=images.map(()=> '![粘贴图片](/api/courses/markdown-images/'+'0'.repeat(32)+')');
    const prefix=start&&!editor.value.slice(0,start).endsWith('\n\n')?'\n\n':'';
    const suffix=end<editor.value.length&&!editor.value.slice(end).startsWith('\n\n')?'\n\n':'\n';
    const insertion=()=>prefix+imageLinks.filter(Boolean).join('\n\n')+suffix;
    if(maxLength&&editor.value.length-(end-start)+insertion().length>maxLength){message('剩余字数不足，缩短正文后再粘贴图片。',true);return;}
    uploading=true;editor.readOnly=true;showPreview.disabled=true;if(saveControl)saveControl.disabled=true;
    let failed=0,firstError='';
    try{
      for(const [index,image] of images.entries()){
        message(`正在上传图片 ${index+1}/${images.length}…`);
        try{const uploaded=await uploadFile(imagePath,image);imageLinks[index]=`![粘贴图片](${uploaded.url})`;}
        catch(error){imageLinks[index]='';failed++;firstError||=error.message;}
        if(!container.isConnected)return;
      }
      if(failed!==images.length)editor.setRangeText(insertion(),start,end,'end');
      message(failed?`${failed} 张图片上传失败：${firstError}`:'图片已插入，可切换到预览。',!!failed);
    }finally{
      uploading=false;editor.readOnly=false;showPreview.disabled=false;if(saveControl)saveControl.disabled=false;
    }
  });
  return {container,editor,bindSave(control){saveControl=control;}};
}
function presetClass(course){return `course-cover-preset-${course.cover_value||'forest'}`;}
function courseCover(course,className='course-cover'){
  const cover=el('div','',''+className);
  cover.dataset.courseMark=String(course.id||'01').padStart(2,'0');
  if(course.cover_kind==='upload'&&course.cover_url){cover.classList.add('course-cover-upload');const image=el('img');image.alt='课程封面';image.loading='lazy';fetch(course.cover_url,{headers:{Authorization:`Bearer ${state.token}`}}).then(response=>{if(!response.ok)throw new Error('封面不可用');return response.blob();}).then(blob=>{if(image.isConnected)image.src=URL.createObjectURL(blob);}).catch(()=>cover.classList.add('course-cover-unavailable'));cover.append(image);}
  else{cover.classList.add(presetClass(course));const artwork=el('div','','course-cover-art');artwork.append(el('span','SCU · COURSE','course-cover-eyebrow'),el('strong',course.title||'课程学习'));cover.append(artwork);}
  return cover;
}
function sectionTitle(title,meta=''){
  const row=el('div','','course-section-title');row.append(el('h2',title));if(meta)row.append(el('span',meta,'course-muted'));return row;
}
function editorStepNavigation(courseId,current){
  const nav=el('nav','','course-editor-nav');nav.setAttribute('aria-label','课程管理步骤');
  for(const [label,step]of [['课程内容','content'],['课程信息','info'],['学员与发布','publish']]){
    const path=`/editor/${courseId}/${step}`;const link=button(label,()=>route(path),'course-editor-nav-link');
    link.setAttribute('aria-current',step===current?'page':'false');nav.append(link);
  }
  return nav;
}
function statusText(course){
  if(course.publication_status==='draft')return '草稿';
  if(course.publication_status==='archived')return '已归档';
  return course.access_mode==='public'?'公开课程':'名单课程';
}
function allLessons(course){return (course.sections||[]).flatMap(section=>section.lessons||[]);}
function setBusy(node,value){node.setAttribute('aria-busy',String(value));}
export function configureCourseLearning(navigate){goTo=navigate;}
export function clearCourseLearning(){generation++;markdownCleanup();markdownCleanup=()=>{};exitCourseReaderFullscreen();courseReaderCleanup();courseReaderCleanup=()=>{};courseCompletionCleanup();courseCompletionCleanup=()=>{};document.body.classList.remove('course-center-active');void flushCourseProgress();}

export async function renderCoursePage(view){
  markdownCleanup();markdownCleanup=()=>{};
  const turn=++generation;courseReaderCleanup({preserveFullscreen:view.kind==='study'});courseReaderCleanup=()=>{};if(view.kind!=='study')exitCourseReaderFullscreen();courseCompletionCleanup();courseCompletionCleanup=()=>{};if(view.kind==='study')window.scrollTo(0,0);document.body.classList.add('course-center-active');const target=root();target.querySelectorAll('video').forEach(player=>player.pause());setBusy(target,true);target.replaceChildren(el('p','正在准备课程…','live-loading'));
  try{
    if(view.kind==='list'||view.kind==='public')await renderCatalog(turn,courseCatalogScope(view.kind,state.adminMode));
    else if(view.kind==='manage')await renderCatalog(turn,'managed');
    else if(view.kind==='course')await renderCourse(view.id,turn);
    else if(view.kind==='editor')await renderEditor(view.id,view.step,turn);
    else if(view.kind==='markdown')await renderMarkdownWorkspace(view.id,view.assetId,turn);
    else if(view.kind==='study')await renderStudy(view.id,turn);
    else if(view.kind==='preview')await renderPreview(view.id,turn);
  }catch(error){if(turn===generation){exitCourseReaderFullscreen();const panel=el('section','','course-error');panel.append(el('h2','暂时无法打开课程'),el('p',error.message),button('返回课程',()=>route('')));target.replaceChildren(panel);}}
  finally{if(turn===generation)setBusy(target,false);}
}

function libraryAction(course,onChanged,className='text-button course-library-action'){
  const removed=Boolean(course.is_removed_from_library);
  const label=removed?'恢复课程':'移除';
  const action=button(label,async()=>{
    if(!removed&&!await confirmAction(`将“${course.title}”从我的课程移除？报名资格和学习进度会保留，之后可在“已移除课程”中恢复。`,{title:'从我的课程移除',confirmText:'确认移除'}))return;
    await api(`/courses/${course.id}/library`,{method:removed?'POST':'DELETE'});
    notify(removed?'课程已恢复到我的课程':'课程已移除，可在已移除课程中恢复');
    await onChanged();
  },className);
  action.setAttribute('aria-label',`${removed?'恢复':'移除'}课程：${course.title}`);
  return action;
}

async function renderCatalog(turn,initialScope){
  const target=root();const admin=Boolean(state.user?.is_admin);let data=[];
  const shell=el('div','','course-catalog');
  if(initialScope==='managed')shell.classList.add('course-management-workbench');
  const hero=el('header','','course-library-hero');const heading=pageTitle(initialScope==='public'?'发现课程':initialScope==='managed'?'课程管理':'我的课程',initialScope==='public'?'先看看课程内容，再决定是否加入。':initialScope==='managed'?'创建课程、整理课时并发布给学员。':'查看已加入的课程和学习进度。');hero.append(heading);
  if(initialScope==='managed')hero.append(button('＋ 新建课程',()=>route('/editor/new/info'),'button primary'));
  let tabs;
  if(initialScope!=='managed'){
    tabs=el('nav','','course-tabs');tabs.setAttribute('aria-label','课程工作区');
    const itemList=admin?[['mine','我的课程',''],['public','课程广场','/plaza'],['managed','课程管理','/manage']]:[['mine','我的课程',''],['public','课程广场','/plaza']];
    for(const [scope,label,path]of itemList){const tab=button(label,()=>route(path),'course-tab');tab.classList.toggle('selected',scope===initialScope);tab.setAttribute('aria-current',scope===initialScope?'page':'false');tabs.append(tab);}
  }
  let pageIndex=0;const pageSize=12;
  const toolbar=el('div','','course-catalog-toolbar');const count=el('span','','course-muted');const controls=el('div','','course-catalog-controls');const search=input('','search');search.placeholder=initialScope==='managed'?'搜索课程名称':'搜索课程';search.setAttribute('aria-label',search.placeholder);search.className='course-search';controls.append(search);let statusFilter;
  if(initialScope==='managed'){statusFilter=el('select','','course-status-filter');for(const [value,label]of [['all','全部状态'],['draft','草稿'],['published','已发布'],['archived','已归档']]){const option=el('option',label);option.value=value;statusFilter.append(option);}statusFilter.setAttribute('aria-label','按课程状态筛选');controls.append(statusFilter);}
  let libraryFilter;
  if(initialScope==='mine'){
    libraryFilter=el('select','','course-status-filter');libraryFilter.setAttribute('aria-label','课程显示范围');
    for(const [value,label]of [['active','我的课程'],['removed','已移除课程']]){const option=el('option',label);option.value=value;libraryFilter.append(option);}
    controls.prepend(libraryFilter);
  }
  toolbar.append(count,controls);
  const grid=el('div','','course-card-grid');const pagination=el('nav','','course-pagination');pagination.setAttribute('aria-label','课程分页');
  const paint=()=>{
    if(turn!==generation)return;grid.replaceChildren();pagination.replaceChildren();const query=search.value.trim().toLocaleLowerCase();const filtered=data.filter(course=>[course.title,course.description,course.host_name].some(value=>(value||'').toLocaleLowerCase().includes(query))&&(initialScope!=='managed'||statusFilter.value==='all'||course.publication_status===statusFilter.value));const pageCount=Math.ceil(filtered.length/pageSize);pageIndex=Math.min(pageIndex,Math.max(0,pageCount-1));const start=pageIndex*pageSize;count.textContent=filtered.length?`${start+1}–${Math.min(start+pageSize,filtered.length)} / ${filtered.length} 门课程`:'0 门课程';
    if(!filtered.length){const empty=el('section','','course-empty');const noMatches=Boolean(data.length);const removed=libraryFilter?.value==='removed';empty.append(el('h2',noMatches?'没有符合条件的课程':initialScope==='public'?'暂时没有公开课程':initialScope==='managed'?'还没有课程':removed?'没有已移除的课程':'还没有加入课程'),el('p',noMatches?'可以更换关键词，或清除筛选条件查看全部课程。':initialScope==='public'?'公开课程会显示在这里，加入后即可开始学习。':initialScope==='managed'?'先创建课程，再逐步添加课时。':removed?'从我的课程移除后，会显示在这里，学习进度始终保留。':'去课程广场挑选一门课程，加入后就能开始学习。'));
      if(noMatches)empty.append(button('清除搜索',()=>{search.value='';if(statusFilter)statusFilter.value='all';pageIndex=0;paint();},'button secondary'));
      else if(initialScope==='mine'&&!removed)empty.append(button('前往课程广场',()=>route('/plaza'),'button primary'));
      else if(initialScope==='managed')empty.append(button('创建课程',()=>route('/editor/new/info'),'button primary'));
      grid.append(empty);return;}
    for(const course of filtered.slice(start,start+pageSize)){
      const card=el('article','','course-card');card.append(courseCover(course));const body=el('div','','course-card-body');const labels=el('div','','course-card-labels');
      const status=initialScope==='managed'?statusText(course):course.is_removed_from_library?'已移除':course.is_enrolled?'已加入':course.access_mode==='public'?'公开加入':'名单课程';labels.append(el('span',status,'course-chip'),el('span',`${course.section_count||0} 章 · ${course.lesson_count||0} 课时`,'course-muted'));body.append(labels,el('h3',course.title),el('p',course.description_summary||'按章节学习课程内容。','course-card-description'));
      if(course.host_name)body.append(el('p',`主讲 · ${course.host_name}`,'course-card-host'));
      if(initialScope==='mine'&&course.progress_summary?.total){const progress=el('div','','course-card-progress');const track=el('div','','course-progress-track');const bar=el('span');bar.style.width=`${course.progress_summary.percent}%`;track.append(bar);progress.append(track,el('span',`${course.progress_summary.percent}% · ${course.progress_summary.completed}/${course.progress_summary.total} 课时`,'course-muted'));body.append(progress);}
      if(initialScope==='managed'&&course.access_mode==='roster')body.append(el('p','仅指定学员可见','course-muted'));
      const actions=el('div','','course-card-actions');
      const path=initialScope==='public'?`/preview/${course.id}`:`/course/${course.id}`;const action=initialScope==='managed'?`/editor/${course.id}/content`:path;const actionLabel=initialScope==='managed'?'编辑课程':initialScope==='public'?'查看课程':'课程目录';actions.append(button(actionLabel,()=>route(action),'button primary'));
      if(initialScope==='mine')actions.append(libraryAction(course,load));
      if(initialScope==='managed'){
        actions.append(button('预览',()=>route(`/course/${course.id}`),'button secondary'));
        if(course.publication_status==='published')actions.append(button('归档',async()=>{await api(`/courses/${course.id}`,{method:'PATCH',body:json({title:course.title,description:course.description,publication_status:'archived',access_mode:course.access_mode,host_id:course.host_id,member_ids:course.member_ids||[]})});notify('课程已归档');await renderCoursePage({kind:'manage'});},'text-button'));
        actions.append(button('删除',async()=>{if(await confirmAction(`永久删除“${course.title}”及其全部课程资料和学习记录？`,{title:'删除课程？',danger:true,confirmText:'删除课程'})){await api(`/courses/${course.id}`,{method:'DELETE'});notify('课程已删除');await renderCoursePage({kind:'manage'});}},'text-button danger'));
      }
      body.append(actions);card.append(body);grid.append(card);
    }
    if(pageCount>1){const previous=button('← 上一页',()=>{pageIndex--;paint();},'button secondary');previous.disabled=pageIndex===0;const current=el('span',`第 ${pageIndex+1} / ${pageCount} 页`,'course-muted');const next=button('下一页 →',()=>{pageIndex++;paint();},'button secondary');next.disabled=pageIndex>=pageCount-1;pagination.append(previous,current,next);}
  };
  search.addEventListener('input',()=>{pageIndex=0;paint();});statusFilter?.addEventListener('change',()=>{pageIndex=0;paint();});const panel=el('div','','course-catalog-content');panel.append(toolbar,grid,pagination);shell.append(hero);if(tabs)shell.append(tabs);shell.append(panel);target.replaceChildren(shell);setBusy(target,true);grid.replaceChildren(el('p','正在加载课程…','course-muted'));
  let loadSequence=0;
  async function load(){
    const sequence=++loadSequence;setBusy(grid,true);grid.replaceChildren(el('p','正在加载课程…','course-muted'));pagination.replaceChildren();
    try{
      const result=await api(`/courses?scope=${initialScope}${libraryFilter?.value==='removed'?'&removed=true':''}`);
      if(turn!==generation||sequence!==loadSequence)return;
      data=result.items||[];pageIndex=0;paint();
    }catch(error){
      if(turn!==generation||sequence!==loadSequence)return;
      data=[];count.textContent='';grid.replaceChildren(el('p',`课程加载失败：${error.message}`,'course-error-text'),button('重新加载',load,'button secondary'));
    }finally{if(turn===generation&&sequence===loadSequence)setBusy(grid,false);}
  }
  libraryFilter?.addEventListener('change',()=>{void load();});
  await load();
}

function courseProgressPanel(summary){
  const panel=el('section','','course-learning-progress');panel.setAttribute('aria-label','学习进度');
  const heading=el('div','','course-learning-progress-heading');heading.append(el('span','学习进度'),el('strong',`${summary.percent}%`));
  const track=el('div','','course-progress-track');track.setAttribute('role','progressbar');track.setAttribute('aria-label','课程完成进度');track.setAttribute('aria-valuemin','0');track.setAttribute('aria-valuemax','100');track.setAttribute('aria-valuenow',String(summary.percent));
  const fill=el('span');fill.style.width=`${summary.percent}%`;track.append(fill);
  const count=el('p','','course-learning-progress-count');count.append(el('strong',String(summary.completed)),el('span',` / ${summary.total} 课时已完成`));
  panel.append(heading,track,count);return panel;
}

function learnerCourseOutline(course,startLesson){
  const outline=el('section','','course-learner-outline');
  const lessonCount=allLessons(course).length;
  outline.append(sectionTitle('课程目录',`${course.sections.length} 章 · ${lessonCount} 课时`));
  const sections=el('div','','course-section-list');
  for(const [sectionIndex,section]of course.sections.entries()){
    const chapter=el('section','','course-chapter');
    const heading=el('header','','course-chapter-heading');const title=el('div','','course-chapter-title');
    const list=el('div','','course-lesson-list');list.id=`course-outline-${course.id}-${section.id}`;
    const toggle=button('',()=>{
      const expanded=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!expanded));list.hidden=expanded;chapter.classList.toggle('is-collapsed',expanded);
    },'course-chapter-toggle');
    toggle.setAttribute('aria-expanded','true');toggle.setAttribute('aria-controls',list.id);
    toggle.append(el('span',String(sectionIndex+1).padStart(2,'0'),'course-order-number'),el('h2',section.title),el('span',`${section.lessons.length} 课时`,'course-muted'));
    title.append(toggle);heading.append(title);
    for(const [lessonIndex,lesson]of section.lessons.entries()){
      const row=el('article','','course-lesson-row');const details=el('div','','course-lesson-copy');const name=el('div','','course-lesson-name');
      name.append(el('span',String(lessonIndex+1).padStart(2,'0'),'course-lesson-number'),el('h3',lesson.title));
      if(lesson.progress?.completed)name.append(el('span','已完成','course-complete-chip'));
      details.append(name,el('p',lesson.description_summary||'打开课时，学习本节内容。','course-muted'));
      const actions=el('div','','course-lesson-actions');const study=button('开始学习 →',()=>startLesson(lesson),'button primary');study.setAttribute('aria-label',`开始学习：${lesson.title}`);actions.append(study);
      row.append(details,actions);list.append(row);
    }
    if(!section.lessons.length)list.append(el('p','本章还没有课时。','course-muted'));
    chapter.append(heading,list);sections.append(chapter);
  }
  if(!course.sections.length)sections.append(el('p','课程还没有章节。','course-muted'));
  outline.append(sections);const pager=chapterPagination(sections);if(pager)outline.append(pager);return outline;
}

async function renderPreview(id,turn){
  const course=await api(`/courses/public/${id}`);if(turn!==generation)return;const target=root();target.replaceChildren();const shell=el('div','','course-page-shell course-preview-shell');
  const back=button('← 返回课程广场',()=>route('/plaza'),'text-button course-back');const header=el('header','','course-preview-header');const media=el('aside','','course-preview-sidebar');media.append(courseCover(course,'course-cover course-preview-cover'));if(course.is_enrolled&&course.progress_summary?.total)media.append(courseProgressPanel(course.progress_summary));header.append(media);const copy=pageTitle(course.title);copy.append(markdownContent(course.description_html,'course-markdown-content course-description-rendered'));header.append(copy);
  const facts=el('div','','course-preview-facts');if(hostName(course))facts.append(el('span',`主讲 · ${hostName(course)}`));facts.append(el('span',`${course.sections.length} 章 · ${course.lesson_count} 课时`));
  const actions=el('div','','course-preview-actions');if(!course.is_enrolled&&course.can_manage)actions.append(button('管理课程',()=>route(`/editor/${course.id}/content`),'button secondary'));else if(!course.is_enrolled)actions.append(button('加入课程',async()=>{await api(`/courses/${course.id}/enroll`,{method:'POST'});notify('已加入课程，现在可从下方目录选择课时');await renderCoursePage({kind:'preview',id:course.id});},'button primary'));
  if(course.is_enrolled&&course.is_removed_from_library)actions.append(libraryAction(course,()=>renderCoursePage({kind:'preview',id:course.id}),'button secondary'));
  header.append(facts);if(actions.childElementCount)media.append(actions);
  const outline=learnerCourseOutline(course,async lesson=>{
    if(!course.is_enrolled&&!course.can_manage){
      await api(`/courses/${course.id}/enroll`,{method:'POST'});
      if(turn!==generation)return;course.is_enrolled=true;notify('已加入课程');
    }
    await route(`/study/${lesson.id}`);
  });
  shell.append(back,header,outline);target.append(shell);
}

function deleteCourseAction(course){
  return button('永久删除课程',async()=>{if(!await confirmAction(`永久删除“${course.title}”将同时移除课程章节、课时、报名记录、学习进度、直播历史、录播和所有课程文件。此操作无法撤销。`,{title:'永久删除整门课程？',danger:true,confirmText:'删除课程'}))return;await api(`/courses/${course.id}`,{method:'DELETE'});notify('课程及其全部内容已删除');await route('/manage');},'text-button danger');
}

async function renderEditor(courseId,step,turn){
  if(!courseId){renderEditorInfo(null,null);return;}
  const course=await api(`/courses/${courseId}`);if(turn!==generation)return;
  if(step==='content'){await renderCourse(courseId,turn,true);return;}
  const target=root();if(step==='info'){renderEditorInfo(courseId,course,target);return;}target.replaceChildren();const shell=el('div','','course-editor-shell');const back=button('← 返回课程管理',()=>route('/manage'),'text-button course-back');const header=el('header','','course-editor-header');header.append(pageTitle(course.title,'设置学员和发布状态。'),editorStepNavigation(courseId,'publish'));
  shell.append(back,header);await renderEditorPublish(course,turn,shell);if(turn===generation)target.append(shell);
}

function editorCoverField(course,title){
  const area=el('section','','course-cover-field');const label=el('label','课程封面');label.htmlFor='courseCoverPreset';
  const picker=el('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp';picker.hidden=true;
  const preset=el('select','','course-cover-select');preset.id=label.htmlFor;
  const hasUpload=course?.cover_kind==='upload';
  const options=[['forest','森林绿'],['ocean','海岸蓝'],['coral','暖珊瑚'],['graphite','石墨灰'],['violet','鸢尾紫'],['mint','薄荷青']];
  if(hasUpload)options.unshift(['current','保留当前封面']);
  for (const [value,label] of options){const option=el('option',label);option.value=value;preset.append(option);}
  preset.value=hasUpload?'current':course?.cover_value||'forest';
  const preview=el('div','','course-cover-slot');const filename=el('small','','course-cover-filename');filename.setAttribute('role','status');filename.hidden=true;
  let file=null;
  const repaint=()=>{
    if(!file){preview.replaceChildren(courseCover({id:course?.id,title:title.value||'课程封面',cover_kind:preset.value==='current'?'upload':'preset',cover_value:preset.value,cover_url:course?.cover_url}));return;}
    const image=el('img');image.alt='待上传封面预览';const url=URL.createObjectURL(file);image.src=url;
    void image.decode().catch(()=>image.replaceWith(el('span','无法预览此图片'))).finally(()=>URL.revokeObjectURL(url));
    preview.replaceChildren(image);
  };
  const reset=button('移除待上传图片',()=>{file=null;picker.value='';filename.hidden=true;reset.hidden=true;repaint();},'text-button');reset.hidden=true;
  const upload=button('上传封面',()=>picker.click(),'button secondary');
  picker.addEventListener('change',()=>{
    if(!picker.files?.[0])return;file=picker.files[0];filename.textContent=file.name;filename.hidden=false;reset.hidden=false;repaint();
  });
  preset.addEventListener('change',()=>{file=null;picker.value='';filename.hidden=true;reset.hidden=true;repaint();});
  title.addEventListener('input',()=>{if(!file&&preset.value!=='current')repaint();});
  const controls=el('div','','course-cover-actions');controls.append(preset,upload,reset,picker);
  const settings=el('div','','course-cover-settings');settings.append(label,el('small','选择预设，或上传 PNG、JPG、WebP 图片。建议比例 16:9。'),controls,filename);
  area.append(preview,settings);repaint();
  return {area,get file(){return file;},get preset(){return preset.value;}};
}

function renderEditorInfo(courseId,course,target=root()){
  const shell=el('div','','course-editor-shell course-management-workbench');
  const back=button('← 返回课程管理',()=>route('/manage'),'text-button course-back');
  const header=el('header','','course-editor-header');header.append(pageTitle(course?.title||'新建课程','设置学员在课程页看到的名称、封面和简介。'));
  if(courseId)header.append(editorStepNavigation(courseId,'info'));
  const panel=el('section','','course-editor-panel course-info-panel');
  const title=input(course?.title||'');title.required=true;title.maxLength=100;title.placeholder='例如：数据结构与算法';
  const description=markdownEditor('课程简介',course?.description||'',{imagePath:courseId?`/courses/${courseId}/markdown-images`:null,
    rows:12,maxLength:4000,hint:courseId?'支持 Markdown、公式和直接粘贴图片。':'支持 Markdown 和公式；保存草稿后可回来粘贴图片。'});
  const cover=editorCoverField(course,title);
  const access=el('select');for(const [value,label]of [['public','公开加入'],['roster','名单学员']]){const option=el('option',label);option.value=value;access.append(option);}access.value=course?.access_mode||'public';
  const basics=el('div','','course-info-basics');basics.append(field('课程名称',title),field('加入方式',access,'公开课程显示在课程广场；名单课程仅对分配的学员开放。'));
  const actions=el('div','','course-editor-actions course-info-actions');
  const cancel=button('取消',()=>route(courseId?`/editor/${courseId}/content`:'/manage'),'button secondary');
  const save=button(courseId?'保存课程信息':'保存草稿并继续',async()=>{
    if(!title.value.trim()){title.focus();throw new Error('请填写课程名称');}
    const file=cover.file;
    const payload={title:title.value.trim(),description:description.editor.value.trim(),publication_status:course?.publication_status||'draft',access_mode:access.value,host_id:course?.host_id||state.user.id,member_ids:course?.member_ids||[]};
    if(!file&&cover.preset!=='current'){payload.cover_kind='preset';payload.cover_value=cover.preset;}
    const saved=await api(courseId?`/courses/${courseId}`:'/courses',{method:courseId?'PATCH':'POST',body:json(payload)});
    const editing=!!courseId;courseId=saved.id;
    if(file)await uploadFile(`/courses/${saved.id}/cover`,file);
    notify(editing?'课程信息已保存':'课程草稿已创建');await route(`/editor/${saved.id}/content`);
  },'button primary');
  description.bindSave(save);actions.append(cancel,save);
  panel.append(basics,cover.area,description.container,actions);shell.append(back,header,panel);target.replaceChildren(shell);
}

async function renderEditorPublish(course,turn,target){
  const issues=course.publish_issues||[];const hasLive=allLessons(course).some(lesson=>lesson.items.some(item=>item.kind==='live'));const panel=el('section','','course-editor-panel');panel.append(el('h2','发布设置'),el('p',course.access_mode==='public'?'公开课程加入后即可学习；如果包含直播课时，需要指定主持人。':'分配可访问课程的学员；如果包含直播课时，需要指定主持人。','course-muted'));
  const access=el('div','','course-editor-setting');access.append(el('span','加入方式','course-editor-setting-label'),el('strong',course.access_mode==='public'?'公开加入':'名单学员'));panel.append(access);
  let people=[];if(hasLive||course.access_mode==='roster'){try{const result=await api('/live/people');people=Array.isArray(result)?result:result.items||[];}catch(error){if(turn!==generation)return;const actions=el('div','','course-editor-actions');actions.append(button('重试加载',()=>renderCoursePage({kind:'editor',id:course.id,step:'publish'}),'button secondary'),deleteCourseAction(course));target.append(panel,el('p',`暂时无法读取学员和主持人列表：${error.message}`,'course-error-text'),actions);return;}}
  if(turn!==generation)return;
  if(hasLive){const host=el('select');for(const person of people){const option=el('option',person.username);option.value=person.id;host.append(option);}if(!people.some(person=>person.id===course.host_id)){const current=el('option',course.host_name||'当前主持人');current.value=course.host_id;host.append(current);}host.value=String(course.host_id);panel.append(field('课程主持人',host,'主持人可在直播课时中管理课堂。'));}
  const chosen=new Set(course.member_ids||[]);if(course.access_mode==='roster'){const roster=el('div','','course-roster');roster.append(el('strong','分配学员'));const list=el('div','','course-roster-list');people.filter(person=>person.id!==state.user.id).forEach(person=>{const label=el('label','','course-roster-person');const check=el('input');check.type='checkbox';check.checked=chosen.has(person.id);check.addEventListener('change',()=>check.checked?chosen.add(person.id):chosen.delete(person.id));label.append(check,el('span',person.username));list.append(label);});roster.append(list);panel.append(roster);}
  const readiness=el('aside','','course-publish-readiness');const heading=el('div','','course-readiness-heading');heading.append(el('span',issues.length?'发布准备':'发布条件','eyebrow'),el('strong',issues.length?`${issues.length} 项待完成`:'已满足发布条件'));readiness.append(heading);if(issues.length){const items=el('ul','','course-readiness-list');issues.forEach(issue=>items.append(el('li',issue)));readiness.append(items);}else readiness.append(el('p','每个课时都已有可访问内容，可以发布课程。','course-muted'));panel.append(readiness);
  const host=panel.querySelector('select');
  const payload=status=>({title:course.title,description:course.description,publication_status:status,access_mode:course.access_mode,host_id:hasLive?Number(host?.value||course.host_id):course.host_id,member_ids:course.access_mode==='roster'?[...chosen]:[]});const actions=el('div','','course-editor-actions');if(hasLive||course.access_mode==='roster')actions.append(button('保存发布设置',async()=>{await api(`/courses/${course.id}`,{method:'PATCH',body:json(payload(course.publication_status))});notify('课程设置已保存');await renderCoursePage({kind:'editor',id:course.id,step:'publish'});},'button secondary'));
  if(course.publication_status==='published')actions.append(button('归档课程',async()=>{await api(`/courses/${course.id}`,{method:'PATCH',body:json(payload('archived'))});notify('课程已归档');await renderCoursePage({kind:'editor',id:course.id,step:'publish'});},'button secondary'));
  else{const publish=button(course.publication_status==='archived'?'重新发布':'发布课程',async()=>{await api(`/courses/${course.id}`,{method:'PATCH',body:json(payload('published'))});notify('课程已发布');await renderCoursePage({kind:'editor',id:course.id,step:'publish'});},'button primary');publish.disabled=issues.length>0;actions.append(publish);}
  actions.append(deleteCourseAction(course));
  target.append(panel,actions);
}

async function renderCourse(id,turn,editor=false){
  const course=await api(`/courses/${id}`);if(turn!==generation)return;const target=root();target.replaceChildren();
  const back=button(editor?'← 返回课程管理':'← 返回课程',()=>route(editor?'/manage':''),'text-button course-back');const header=el('header','','course-detail-header');if(editor)header.classList.add('course-management-header');const cover=courseCover(course,'course-cover course-detail-cover');if(editor)header.append(cover);else{const media=el('aside','','course-detail-sidebar');media.append(cover);if(!course.can_manage&&course.progress_summary?.total)media.append(courseProgressPanel(course.progress_summary));header.append(media);}const courseCopy=pageTitle(course.title);if(editor)courseCopy.append(el('p','整理课程章节、课时和教学内容。'));else courseCopy.append(markdownContent(course.description_html,'course-markdown-content course-description-rendered'));header.append(courseCopy);
  const actions=el('div','','course-header-actions');if(course.can_manage){if(editor)actions.append(editorStepNavigation(course.id,'content'));else actions.append(button('编辑课程',()=>route(`/editor/${course.id}/info`),'button secondary'));}
  if(!editor&&course.is_enrolled)actions.append(libraryAction(course,()=>course.is_removed_from_library?renderCoursePage({kind:'course',id}):route('')));
  header.append(actions);
  if(!editor){
    const shell=el('div','','course-page-shell course-detail-shell');shell.append(back,header,learnerCourseOutline(course,lesson=>route(`/study/${lesson.id}`)));target.append(shell);return;
  }
  const sections=el('div','','course-section-list');
  course.sections.forEach((section,index)=>{
    const sectionNode=el('section','','course-chapter');sectionNode.dataset.orderId=section.id;const heading=el('header','','course-chapter-heading');const title=el('div','','course-chapter-title');const lessonList=el('div','','course-lesson-list');lessonList.id=`course-lessons-${section.id}`;
    if(course.can_manage){const drag=button('⠿',()=>{},'course-drag-handle');drag.draggable=true;drag.title='拖动调整章节顺序';drag.setAttribute('aria-label','拖动调整章节顺序');title.append(drag);}
    const toggle=button('',()=>{const expanded=toggle.getAttribute('aria-expanded')==='true';toggle.setAttribute('aria-expanded',String(!expanded));lessonList.hidden=expanded;sectionNode.classList.toggle('is-collapsed',expanded);},'course-chapter-toggle');toggle.setAttribute('aria-expanded','true');toggle.setAttribute('aria-controls',lessonList.id);toggle.append(el('span',String(index+1).padStart(2,'0'),'course-order-number'),el('h2',section.title),el('span',`${section.lessons.length} 课时`,'course-muted'));title.append(toggle);heading.append(title);
    if(course.can_manage){
      const controls=el('div','','course-inline-actions');
      if(section.lessons.length)controls.append(button('＋ 添加课时',()=>addLesson(course,section,editor),'button secondary'));
      const more=el('details','','course-manage-more');more.append(el('summary','章节设置'));
      const menu=el('div','','course-manage-more-menu');
      menu.append(button('重命名章节',()=>editSection(course,section,editor),'text-button'));
      const removeSection=button('删除章节',async()=>{if(await confirmAction(`删除空章节“${section.title}”？章节中仍有课时，需先删除课时。`,{title:'删除章节？',danger:true,confirmText:'删除章节'})){await api(`/courses/sections/${section.id}`,{method:'DELETE'});await refreshManagedCourse(id,editor);}},'text-button danger');
      removeSection.disabled=section.lessons.length>0;removeSection.title=section.lessons.length?'请先删除章节内的课时':'';menu.append(removeSection);more.append(menu);controls.append(more);heading.append(controls);
    }
    if(!section.lessons.length){const empty=el('div','','course-first-lesson');empty.append(el('span','本章还没有课时。','course-muted'));if(course.can_manage)empty.append(button('添加第一课时',()=>addLesson(course,section,editor),'button primary'));lessonList.append(empty);}
    section.lessons.forEach((lesson,lessonIndex)=>{
      const row=el('article','','course-lesson-row');row.dataset.orderId=lesson.id;const details=el('div','','course-lesson-copy');const name=el('div','','course-lesson-name');name.append(el('span',String(lessonIndex+1).padStart(2,'0'),'course-lesson-number'),el('h3',lesson.title));if(lesson.progress.completed)name.append(el('span','已完成','course-complete-chip'));details.append(name,el('p',lesson.description_summary||'打开课时，学习本节内容。','course-muted'));
      const buttons=el('div','','course-lesson-actions');
      if(course.can_manage){
        const drag=button('⠿',()=>{},'course-drag-handle');drag.draggable=true;drag.title='拖动调整课时顺序';drag.setAttribute('aria-label','拖动调整课时顺序');buttons.append(drag);
        const open=lesson.items.length?button('预览课时 →',()=>route(`/study/${lesson.id}`),'button secondary'):button('添加内容',()=>addLessonContent(course,lesson,editor),'button primary');buttons.append(open);
        if(lesson.items.length)buttons.append(button('＋ 添加内容',()=>addLessonContent(course,lesson,editor),'button secondary'));
        const more=el('details','','course-lesson-more');const summary=el('summary','更多');const menu=el('div','','course-lesson-more-menu');
        menu.append(button('重命名课时',()=>editLesson(course,lesson,editor),'text-button'));
        const removeLesson=button('删除课时',async()=>{if(await confirmAction(`删除空课时“${lesson.title}”？请先移除视频和资料；直播课次请在直播课堂中删除。`,{title:'删除课时？',danger:true,confirmText:'删除课时'})){await api(`/courses/lessons/${lesson.id}`,{method:'DELETE'});await refreshManagedCourse(id,editor);}},'text-button danger');
        removeLesson.disabled=lesson.items.length>0;removeLesson.title=lesson.items.length?'请先移除课时中的内容':'';menu.append(removeLesson);more.append(summary,menu);buttons.append(more);
      }
      else{buttons.append(button('开始学习 →',()=>route(`/study/${lesson.id}`),'button primary'));}
      if(course.can_manage&&lesson.items.length){const contents=el('div','','course-managed-items');lesson.items.forEach((item,itemIndex)=>{const itemRow=el('div','','course-managed-item');const itemName=item.kind==='live'?item.live?.title||'直播课':item.asset?.original_name||'课程文件';itemRow.append(el('span',item.kind==='live'?'直播':item.kind==='video'?'录播':'资料','course-chip'),el('span',itemName,'course-managed-item-name'));const more=el('details','','course-item-more');more.append(el('summary','⋯'));const menu=el('div','','course-manage-more-menu');if(itemIndex>0)menu.append(button('上移内容',()=>moveItem(course,lesson,itemIndex,-1,editor),'text-button'));if(itemIndex<lesson.items.length-1)menu.append(button('下移内容',()=>moveItem(course,lesson,itemIndex,1,editor),'text-button'));if(item.asset&&isMarkdown(item.asset))menu.append(button('编辑正文',()=>editMarkdown(course,lesson,item.asset,editor),'text-button'));if(item.asset)menu.append(button('移除内容',()=>removeAsset(course,item.asset,editor),'text-button danger'));more.append(menu);itemRow.append(more);contents.append(itemRow);});details.append(contents);}
      row.append(details,buttons);lessonList.append(row);
    });
    sectionNode.append(heading,lessonList);sections.append(sectionNode);
    if(course.can_manage&&section.lessons.length)wireDragReorder(lessonList,'.course-lesson-row',`/courses/sections/${section.id}/lessons/order`,id,editor);
  });
  if(!course.sections.length)sections.append(el('p','课程还没有章节。','course-muted'));
  const chapterPager=chapterPagination(sections);
  if(course.can_manage&&course.sections.length)wireDragReorder(sections,'.course-chapter',`/courses/${id}/sections/order`,id,editor);
  if(editor){const shell=el('div','','course-editor-shell course-management-workbench');shell.append(back,header);const panel=el('section','','course-editor-content-panel');const titleRow=sectionTitle('课程目录',`${course.sections.length} 章 · ${course.progress_summary.total} 课时`);titleRow.append(button('＋ 添加章节',()=>addSection(course,editor),'button secondary'));panel.append(titleRow,sections);if(chapterPager)panel.append(chapterPager);shell.append(panel);target.append(shell);return;}
}

function scheduleLive(lesson,editor=false){
  const {dialog,body,footer}=modal('安排直播','这场直播会加入当前课时。');const starts=input('','datetime-local');body.append(field('开课时间',starts));
  footer.append(button('安排直播',async()=>{if(!starts.value)throw new Error('请选择开课时间');await api(`/courses/lessons/${lesson.id}/live`,{method:'POST',body:json({starts_at:new Date(starts.value).getTime()/1000})});dialog.close();notify('直播已加入课时');await refreshManagedCourse(lesson.course_id,editor);},'button primary'));
}

function addSection(course,editor=false){
  const {dialog,body,footer}=modal('新增章节');const title=input('');title.required=true;body.append(field('章节名称',title));
  footer.append(button('创建章节',async()=>{if(!title.value.trim())throw new Error('请填写章节名称');await api(`/courses/${course.id}/sections`,{method:'POST',body:json({title:title.value.trim(),position:course.sections.length})});dialog.close();await refreshManagedCourse(course.id,editor);},'button primary'));
}

function editSection(course,section,editor=false){
  const {dialog,body,footer}=modal('编辑章节');const title=input(section.title);title.required=true;body.append(field('章节名称',title));
  footer.append(button('保存章节',async()=>{if(!title.value.trim())throw new Error('请填写章节名称');await api(`/courses/sections/${section.id}`,{method:'PATCH',body:json({title:title.value.trim(),position:section.position})});dialog.close();await refreshManagedCourse(course.id,editor);},'button primary'));
}

function addLesson(course,section,editor=false){
  const first=!section.lessons.length;const {dialog,body,footer}=modal(first?'添加第一课时':'添加课时','先建立课时目录，创建后可按需添加视频、Markdown、资料或直播。');const title=input('');title.required=true;const description=textArea('');description.rows=5;
  body.append(field('课时名称',title),field('课时说明（可选）',description));
  footer.append(button('创建课时',async()=>{
    if(!title.value.trim())throw new Error('请填写课时名称');
    const data={title:title.value.trim(),description:description.value.trim(),position:section.lessons.length};
    await api(`/courses/sections/${section.id}/lessons`,{method:'POST',body:json(data)});
    dialog.close();notify('课时已创建');await refreshManagedCourse(course.id,editor);
  },'button primary'));
}

function addLessonContent(course,lesson,editor=false){
  const {dialog,body}=courseModal('添加课时内容',`为“${lesson.title}”选择一种内容。可以重复添加，让一节课包含视频和资料，也可以安排直播。`);
  dialog.classList.add('course-content-dialog');
  const choices=el('div','','course-content-choices');
  const choose=(label,action)=>{const control=button(label,()=>{dialog.close();return action();},'button secondary');choices.append(control);};
  choose('上传录播视频',()=>pickAsset(lesson.id,'video',course.id,editor));
  choose('上传课程资料',()=>pickAsset(lesson.id,'document',course.id,editor));
  choose('编写 Markdown 正文',()=>editMarkdown(course,lesson,null,editor));
  choose('上传 MD 正文',()=>pickAsset(lesson.id,'markdown',course.id,editor));
  choose('安排直播',()=>scheduleLive(lesson,editor));
  body.append(choices);
}

function editMarkdown(course,lesson,asset){
  return route(`/markdown/${lesson.id}/${asset?.id||'new'}`);
}

async function renderMarkdownWorkspace(lessonId,assetId,turn){
  const lesson=await api(`/courses/lessons/${lessonId}`);if(turn!==generation)return;
  const course=await api(`/courses/${lesson.course_id}`);if(turn!==generation)return;
  if(!course.can_manage)throw new Error('你没有编辑本课程的权限');
  const asset=assetId?(lesson.items||[]).map(item=>item.asset).find(item=>item?.id===assetId):null;
  if(assetId&&(!asset||!isMarkdown(asset)))throw new Error('本课时中没有这份 Markdown 文档');
  let source='';
  if(asset){
    const response=await fetch(`/api/courses/assets/${asset.id}/file`,{headers:{Authorization:`Bearer ${state.token}`}});
    if(!response.ok)throw new Error('无法读取 Markdown 正文，请刷新后重试');
    source=await response.text();if(turn!==generation)return;
  }
  markdownCleanup=mountMarkdownWorkspace({target:root(),course,lesson,asset,source,userId:state.user.id,
    render:renderMarkdownInto,
    compile:async(markdown,signal)=>{
      const response=await fetch('/api/courses/markdown/preview',{method:'POST',signal,headers:{'Content-Type':'application/json',Authorization:`Bearer ${state.token}`},body:json({markdown})});
      if(!response.ok)throw new Error('预览暂时不可用，请稍后继续编辑重试');
      return response.text();
    },
    uploadImage:file=>uploadFile(`/courses/lessons/${lesson.id}/markdown-images`,file),
    save:async payload=>{
      if(asset)await api(`/courses/assets/${asset.id}/markdown`,{method:'PUT',body:json(payload)});
      else await api(`/courses/lessons/${lesson.id}/markdown`,{method:'POST',body:json(payload)});
      notify('Markdown 正文已保存到课时');
    },
    onBack:()=>route(`/editor/${course.id}/content`),
  });
}

function editLesson(course,lesson,editor=false){
  const {dialog,body,footer}=modal('编辑课时');const title=input(lesson.title);title.required=true;const description=markdownEditor('课时说明 · Markdown',lesson.description||'',{imagePath:`/courses/lessons/${lesson.id}/markdown-images`,rows:10,hint:'可写简短说明，也支持直接粘贴图片。'});body.append(field('课时名称',title),description.container);
  const save=button('保存课时',async()=>{if(!title.value.trim())throw new Error('请填写课时名称');await api(`/courses/lessons/${lesson.id}`,{method:'PATCH',body:json({title:title.value.trim(),description:description.editor.value.trim(),position:lesson.position})});dialog.close();await refreshManagedCourse(course.id,editor);},'button primary');description.bindSave(save);footer.append(save);
}

async function moveItem(course,lesson,index,direction,editor=false){
  const items=[...lesson.items];[items[index],items[index+direction]]=[items[index+direction],items[index]];
  await api(`/courses/lessons/${lesson.id}/items`,{method:'PUT',body:json({items:items.map(item=>({id:item.id,kind:item.kind,live_lesson_id:item.live_lesson_id}))})});
  await refreshManagedCourse(course.id,editor);
}

async function removeAsset(course,asset,editor=false){
  if(!await confirmAction(`移除“${asset.original_name}”会同时删除私有文件，学员将无法继续查看。`,{title:'移除课程文件？',danger:true,confirmText:'移除文件'}))return;
  await api(`/courses/assets/${asset.id}`,{method:'DELETE'});notify('课程文件已移除');await refreshManagedCourse(course.id,editor);
}

function pickAsset(lessonId,kind,courseId,editor=false){
  const picker=el('input');picker.type='file';picker.accept=kind==='video'?'.mp4,.webm':kind==='markdown'?'.md':'.pdf,.txt,.md,.docx,.pptx,.xlsx,.png,.jpg,.jpeg';picker.hidden=true;document.body.append(picker);
  picker.addEventListener('change',()=>{const file=picker.files?.[0];if(!file){picker.remove();return;}void run(async()=>{try{await uploadFile(`/courses/lessons/${lessonId}/assets?kind=${kind==='markdown'?'document':kind}`,file);notify(kind==='video'?'视频已加入课时':'资料已加入课时');await refreshManagedCourse(courseId,editor);}finally{picker.remove();}});});picker.click();
}

async function privateAsset(asset){
  const response=await fetch(`/api/courses/assets/${asset.id}/file`,{headers:{Authorization:`Bearer ${state.token}`}});
  if(!response.ok)throw new Error('资料读取失败，请刷新课程后重试');
  return URL.createObjectURL(await response.blob());
}
async function videoUrl(asset){const result=await api(`/courses/assets/${asset.id}/playback`,{method:'POST'});return result.url;}
function markdownAsset(asset){return fetch(`/api/courses/assets/${asset.id}/markdown`,{headers:{Authorization:`Bearer ${state.token}`}});}
function isMarkdown(asset){return asset.original_name?.toLocaleLowerCase().endsWith('.md')||asset.mime_type==='text/markdown';}
function resumeLessonVideo(player,lesson){
  if(lesson.progress.position_seconds>0)player.addEventListener('loadedmetadata',()=>{
    player.currentTime=Math.min(lesson.progress.position_seconds,Math.max(0,player.duration-1));
  },{once:true});
}
function trackLessonVideo(player,lesson,onEnded=()=>{}){
  let lastSaved=0,pending=null,saving=null;
  const save=()=>{lesson.progress.position_seconds=Math.floor(player.currentTime||0);pending={position_seconds:lesson.progress.position_seconds,completed:false};if(saving)return saving;saving=(async()=>{while(pending){const snapshot=pending;pending=null;try{await api(`/courses/lessons/${lesson.id}/progress`,{method:'PUT',body:json(snapshot)});}catch(error){pending=snapshot;notify(`播放进度保存失败，切换页面前会重试：${error.message}`,'error');return false;}}return true;})().finally(()=>{saving=null;});return saving;};
  courseProgressFlushers.add(()=>save());
  player.addEventListener('timeupdate',()=>{if(player.currentTime-lastSaved>=15){lastSaved=player.currentTime;void save();}});
  player.addEventListener('pause',()=>void save());player.addEventListener('ended',()=>void save().then(saved=>{if(saved)onEnded();}));
  return save;
}
async function replayPlayer(recording,lesson,onPlayer=()=>{}){
  const replay=el('div','','course-replay');replay.append(el('h3','直播回放'));
  try{const ticket=await api(`/live/recordings/${recording.id}/playback`,{method:'POST'});const player=el('video');player.controls=true;player.playsInline=true;player.preload='metadata';player.src=ticket.url;resumeLessonVideo(player,lesson);trackLessonVideo(player,lesson,()=>{});onPlayer(player);replay.append(player);}
  catch(error){replay.append(el('p',error.message,'course-error-text'));}
  return replay;
}
function watchRecordings(entries,lesson,turn,onPlayer=()=>{}){
  if(!entries.length)return;
  const poll=async()=>{
    if(turn!==generation)return;
    const active=entries.filter(entry=>entry.statusNode.isConnected);
    if(!active.length)return;
    try{
      const fresh=await api(`/courses/lessons/${lesson.id}`);if(turn!==generation)return;
      const recordings=new Map(fresh.items.flatMap(item=>item.recordings||[]).map(recording=>[recording.id,recording]));
      for(const entry of active){
        const recording=recordings.get(entry.id);if(!recording)continue;
        if(recording.status==='ready'){const replay=await replayPlayer(recording,lesson,onPlayer);if(turn!==generation)return;entry.statusNode.replaceWith(replay);}
        else if(recording.status==='failed')entry.statusNode.textContent='本次直播录制未能生成回放。';
        else entry.statusNode.textContent='直播回放正在生成，完成后会显示在本小节。';
      }
      if(active.some(entry=>entry.statusNode.isConnected&&recordings.get(entry.id)?.status!=='failed'))setTimeout(poll,8000);
    }catch(error){
      if(turn===generation)active.forEach(entry=>{if(entry.statusNode.isConnected)entry.statusNode.textContent='回放状态暂时无法更新，请稍后刷新课程。';});
    }
  };
  setTimeout(poll,8000);
}

async function renderStudy(lessonId,turn){
  courseCompletionCleanup();courseCompletionCleanup=()=>{};
  const lesson=await api(`/courses/lessons/${lessonId}`);if(turn!==generation)return;const course=await api(`/courses/${lesson.course_id}`);if(turn!==generation)return;
  const lessons=allLessons(course);const index=lessons.findIndex(item=>item.id===lesson.id);const target=root();target.replaceChildren();
  const back=button('← 课程目录',()=>route(`/course/${course.id}`),'text-button course-back');const top=el('header','','course-study-heading');const lessonHeading=pageTitle(lesson.title);lessonHeading.prepend(el('span',course.title,'course-study-kicker'));if(lesson.description_html)lessonHeading.append(markdownContent(lesson.description_html,'course-markdown-content course-description-rendered'));top.append(lessonHeading);const status=el('div','','course-study-status');const progressStatus=el('span',`${course.progress_summary.completed} / ${course.progress_summary.total} 已完成`,'course-study-status-item');progressStatus.dataset.courseProgress='true';status.append(el('span',`第 ${index+1} / ${lessons.length} 课时`,'course-study-status-item'),progressStatus);top.append(status);
  const shell=el('div','','course-page-shell course-study-shell');const layout=el('div','','course-study-layout');const nav=el('aside','','course-study-nav');const navHeading=sectionTitle('本课程',`${course.progress_summary.completed}/${course.progress_summary.total} 已完成`);const navContent=el('div','','course-study-nav-content');
  for(const section of course.sections){const group=el('section','','course-study-group');group.append(el('h3',section.title));for(const item of section.lessons){const link=button('',()=>route(`/study/${item.id}`),'course-study-link');link.classList.toggle('current',item.id===lesson.id);link.append(el('span',item.progress.completed?'✓':String(item.position+1).padStart(2,'0'),'course-study-link-number'),el('span',item.title));group.append(link);}navContent.append(group);}nav.append(navHeading,navContent);
  const content=el('main','','course-study-content');const completion={readingEndReached:false,videoCount:0,videosEnded:0,saving:false,saved:!!lesson.progress.completed};
  const completionNote=el('p','本小节已完成','course-completed-note');completionNote.hidden=!completion.saved;
  const maybeComplete=async()=>{
    if(completion.saved||completion.saving||!lesson.items.length||!completion.readingEndReached||completion.videosEnded<completion.videoCount)return;
    completion.saving=true;
    try{
      const result=await api(`/courses/lessons/${lesson.id}/progress`,{method:'PUT',body:json({position_seconds:lesson.progress.position_seconds||0,completed:true})});
      completion.saved=true;lesson.progress.completed=true;completionNote.hidden=false;
      courseCompletionCleanup();courseCompletionCleanup=()=>{};
      const count=result.course;
      const progressLabel=`${count.completed} / ${count.total} 已完成`;
      status.querySelector('[data-course-progress]')?.replaceChildren(document.createTextNode(progressLabel));
      navHeading.querySelector('.course-muted')?.replaceChildren(document.createTextNode(`${count.completed}/${count.total} 已完成`));
      navContent.querySelector('.course-study-link.current .course-study-link-number')?.replaceChildren(document.createTextNode('✓'));
    }catch(error){notify(`自动保存学习进度失败：${error.message}`,'error');}
    finally{completion.saving=false;}
  };
  const registerVideo=player=>{
    completion.videoCount++;
    player.addEventListener('ended',()=>{completion.videosEnded++;void maybeComplete();},{once:true});
  };
  const media=el('div','','course-study-media');const markdown=el('div','','course-reading-list');const attachments=el('section','','course-materials');const pendingRecordings=[];let mediaCount=0,markdownCount=0,attachmentCount=0;
  if(!lesson.items.length)content.append(el('p','本小节内容正在准备中。','course-empty'));
  for(const item of lesson.items){
    if(item.kind==='video'&&item.asset){
      mediaCount++;const entry=el('section','','course-media-entry');entry.append(el('h2',item.asset.original_name,'course-media-title'));
      try{const url=await videoUrl(item.asset);if(turn!==generation)return;const player=el('video');player.controls=true;player.playsInline=true;player.preload='metadata';player.src=url;resumeLessonVideo(player,lesson);trackLessonVideo(player,lesson);registerVideo(player);entry.append(player);}catch(error){if(turn!==generation)return;entry.append(el('p',error.message,'course-error-text'));}media.append(entry);
    }else if(item.kind==='live'){
      mediaCount++;const entry=el('section','','course-media-entry course-live-entry');
      if(!item.live){entry.append(el('p','该直播课次已删除。','course-muted'));media.append(entry);continue;}
      const session=el('div','','course-live-summary');session.append(el('span','直播','course-live-label'),el('h2',item.live.title===lesson.title?lesson.title:item.live.title));
      const starts=item.live.starts_at?new Date(item.live.starts_at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'时间待安排';
      const liveStatus={scheduled:'等待开课',live:'直播进行中',ended:'直播已结束'}[item.live.status]||'直播状态待确认';
      session.append(el('p',`${starts} · ${liveStatus}`,'course-muted'),button(item.live.status==='live'?'进入直播课堂 →':'查看直播课次 →',()=>route(`/lesson/${item.live.id}`),'button secondary'));entry.append(session);
      for(const recording of item.recordings||[]){
        if(recording.status==='ready'){const replay=await replayPlayer(recording,lesson,registerVideo);if(turn!==generation)return;entry.append(replay);}
        else if(['starting','recording','stopping','unknown'].includes(recording.status)){const statusNode=el('p','直播回放正在生成，完成后会显示在本小节。','course-muted');entry.append(statusNode);pendingRecordings.push({id:recording.id,statusNode});}
        else if(recording.status==='failed')entry.append(el('p','本次直播录制未能生成回放。','course-error-text'));
      }
      media.append(entry);
    }else if(item.kind==='document'&&item.asset){
      if(isMarkdown(item.asset)){
        markdownCount++;const body=el('article','','course-reading-body');
        try{const response=await markdownAsset(item.asset);if(turn!==generation)return;if(!response.ok)throw new Error('课程正文暂时无法加载，请刷新后重试');const html=await response.text();if(turn!==generation)return;renderMarkdownInto(body,html);}catch(error){if(turn!==generation)return;body.replaceChildren(el('p',error.message,'course-error-text'));}markdown.append(body);
      }else{
        attachmentCount++;const row=el('div','','course-material-row');row.append(el('span',item.asset.original_name,'course-material-name'),el('span',`${(item.asset.size/1024/1024).toFixed(1)} MB`,'course-muted'));
        row.append(button('下载',async()=>{const url=await privateAsset(item.asset);const link=el('a');link.href=url;link.download=item.asset.original_name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);},'button secondary'));attachments.append(row);
      }
    }
  }
  if(mediaCount)content.append(media);
  if(markdownCount){const reading=el('section','','course-study-reading');reading.append(el('h2','课程正文'));reading.append(markdown);content.append(reading);}
  if(attachmentCount){attachments.prepend(el('h2','课程资料'));content.append(attachments);}
  content.append(completionNote);
  const navigation=el('footer','','course-study-navigation');navigation.setAttribute('aria-label','课时导航');
  const lessonLink=(item,direction)=>{
    const previous=direction==='previous';
    const label=previous?'上一课':'下一课';
    const link=button('',()=>item&&route(`/study/${item.id}`),`button secondary course-study-${direction}`);
    link.disabled=!item;link.title=item?`${label}：${item.title}`:previous?'已经是第一课':'已到最后一课';
    link.setAttribute('aria-label',link.title);
    const arrow=el('span',previous?'←':'→','course-study-nav-arrow');arrow.setAttribute('aria-hidden','true');
    const copy=el('span','','course-study-nav-copy');
    copy.append(el('span',label,'course-study-nav-label'));
    link.append(...(previous?[arrow,copy]:[copy,arrow]));return link;
  };
  navigation.append(lessonLink(lessons[index-1],'previous'),lessonLink(lessons[index+1],'next'));content.append(navigation);
  const endMarker=el('div','','course-study-end-marker');endMarker.setAttribute('aria-hidden','true');content.append(endMarker);
  layout.append(nav,content);shell.append(back,top,layout);target.append(shell);
  courseReaderCleanup=mountCourseReader({host:target,layout,nav,content,title:lesson.title});
  let observer=null;const onEndVisible=entries=>{if(entries.some(entry=>entry.isIntersecting)){completion.readingEndReached=true;void maybeComplete();}};
  if('IntersectionObserver'in window){observer=new IntersectionObserver(onEndVisible,{threshold:0.8});observer.observe(endMarker);}
  else{const check=()=>{if(endMarker.getBoundingClientRect().top<=window.innerHeight){completion.readingEndReached=true;void maybeComplete();}};window.addEventListener('scroll',check,{passive:true});check();courseCompletionCleanup=()=>window.removeEventListener('scroll',check,{passive:true});}
  if(observer)courseCompletionCleanup=()=>observer.disconnect();
  watchRecordings(pendingRecordings,lesson,turn,registerVideo);
}
