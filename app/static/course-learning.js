import {api,state} from './api.js?v=20261114-ui-v17';
import {el,button,notify,run,confirmAction} from './ui.js?v=20261114-ui-v17';
import {modal,field,input,textArea,uploadFile} from './live-ui.js?v=1';

let goTo=()=>{},generation=0;
const courseProgressFlushers=new Set();
const root=()=>document.getElementById('liveContent');
const json=body=>JSON.stringify(body);
async function flushCourseProgress(){
  for(const flush of courseProgressFlushers){if(!await flush())return false;}
  courseProgressFlushers.clear();return true;
}
const route=async(path)=>{root()?.querySelectorAll('video').forEach(player=>player.pause());if(!await flushCourseProgress())return;return goTo(path);};
const refreshManagedCourse=(id,editor)=>renderCoursePage(editor?{kind:'editor',id,step:'content'}:{kind:'course',id});
const hostName=course=>course.host_name||'';
function pageTitle(title,description=''){
  const box=el('div','','course-heading-copy');box.append(el('h1',title));
  if(description)box.append(el('p',description));return box;
}
function sectionTitle(title,meta=''){
  const row=el('div','','course-section-title');row.append(el('h2',title));if(meta)row.append(el('span',meta,'course-muted'));return row;
}
function statusText(course){
  if(course.publication_status==='draft')return '草稿';
  if(course.publication_status==='archived')return '已归档';
  return course.access_mode==='public'?'公开课程':'名单课程';
}
function allLessons(course){return (course.sections||[]).flatMap(section=>section.lessons||[]);}
function unitType(lesson){
  const kinds=new Set((lesson.items||[]).map(item=>item.kind));
  if(kinds.has('live')&&kinds.size===1)return '直播课时';
  if(kinds.has('video')&&kinds.has('document'))return '综合课时';
  if(kinds.has('video'))return '录播课时';
  if(kinds.has('document'))return '资料课时';
  return '待完善';
}
function setBusy(node,value){node.setAttribute('aria-busy',String(value));}
export function configureCourseLearning(navigate){goTo=navigate;}
export function clearCourseLearning(){generation++;document.body.classList.remove('course-center-active');void flushCourseProgress();}

export async function renderCoursePage(view){
  const turn=++generation;document.body.classList.add('course-center-active');const target=root();target.querySelectorAll('video').forEach(player=>player.pause());setBusy(target,true);target.replaceChildren(el('p','正在准备课程…','live-loading'));
  try{
    if(view.kind==='list')await renderCatalog(turn,'mine');
    else if(view.kind==='public')await renderCatalog(turn,'public');
    else if(view.kind==='manage')await renderCatalog(turn,'managed');
    else if(view.kind==='course')await renderCourse(view.id,turn);
    else if(view.kind==='editor')await renderEditor(view.id,view.step,turn);
    else if(view.kind==='study')await renderStudy(view.id,turn);
    else if(view.kind==='preview')await renderPreview(view.id,turn);
  }catch(error){if(turn===generation){const panel=el('section','','course-error');panel.append(el('h2','暂时无法打开课程'),el('p',error.message),button('返回课程',()=>route('')));target.replaceChildren(panel);}}
  finally{if(turn===generation)setBusy(target,false);}
}

async function renderCatalog(turn,initialScope){
  const target=root();const admin=Boolean(state.user?.is_admin);let data=[];
  const shell=el('div','','course-catalog');
  const hero=el('header','','course-library-hero');const heading=pageTitle(initialScope==='public'?'发现课程':initialScope==='managed'?'课程管理':'我的课程',initialScope==='public'?'先看看课程内容，再决定是否加入。':initialScope==='managed'?'创建课程、整理课时并发布给学员。':'查看已加入的课程和学习进度。');hero.append(heading);
  if(initialScope==='managed')hero.append(button('＋ 新建课程',()=>route('/editor/new/info'),'button primary'));
  const tabs=el('nav','','course-tabs');tabs.setAttribute('aria-label','课程工作区');
  const itemList=admin?[['mine','我的课程',''],['public','课程广场','/plaza'],['managed','课程管理','/manage']]:[['mine','我的课程',''],['public','课程广场','/plaza']];
  for(const [scope,label,path]of itemList){const tab=button(label,()=>route(path),'course-tab');tab.classList.toggle('selected',scope===initialScope);tab.setAttribute('aria-current',scope===initialScope?'page':'false');tabs.append(tab);}
  const filters=el('nav','','course-filters');filters.setAttribute('aria-label','按课程内容筛选');let selectedKind='all',pageIndex=0;const pageSize=12;
  for(const [kind,label]of [['all','全部课程'],['live','含直播'],['video','含录播'],['document','含资料']]){const filter=button(label,()=>{selectedKind=kind;pageIndex=0;filters.querySelectorAll('button').forEach(item=>{const active=item.dataset.kind===kind;item.classList.toggle('selected',active);item.setAttribute('aria-pressed',String(active));});paint();},'course-filter');filter.dataset.kind=kind;filter.classList.toggle('selected',kind==='all');filter.setAttribute('aria-pressed',String(kind==='all'));filters.append(filter);}
  const toolbar=el('div','','course-catalog-toolbar');const count=el('span','','course-muted');const controls=el('div','','course-catalog-controls');const search=input('','search');search.placeholder=initialScope==='managed'?'搜索课程名称':'搜索课程';search.setAttribute('aria-label',search.placeholder);search.className='course-search';controls.append(search);let statusFilter;
  if(initialScope==='managed'){statusFilter=el('select','','course-status-filter');for(const [value,label]of [['all','全部状态'],['draft','草稿'],['published','已发布'],['archived','已归档']]){const option=el('option',label);option.value=value;statusFilter.append(option);}statusFilter.setAttribute('aria-label','按课程状态筛选');controls.append(statusFilter);}
  toolbar.append(count,controls);
  const grid=el('div','','course-card-grid');const pagination=el('nav','','course-pagination');pagination.setAttribute('aria-label','课程分页');
  const paint=()=>{
    if(turn!==generation)return;grid.replaceChildren();pagination.replaceChildren();const query=search.value.trim().toLocaleLowerCase();const filtered=data.filter(course=>[course.title,course.description,course.host_name].some(value=>(value||'').toLocaleLowerCase().includes(query))&&(selectedKind==='all'||(course.content_kinds||[]).includes(selectedKind))&&(initialScope!=='managed'||statusFilter.value==='all'||course.publication_status===statusFilter.value));const pageCount=Math.ceil(filtered.length/pageSize);pageIndex=Math.min(pageIndex,Math.max(0,pageCount-1));const start=pageIndex*pageSize;count.textContent=filtered.length?`${start+1}–${Math.min(start+pageSize,filtered.length)} / ${filtered.length} 门课程`:'0 门课程';
    if(!filtered.length){const empty=el('section','','course-empty');const noMatches=Boolean(data.length);empty.append(el('h2',noMatches?'没有符合条件的课程':initialScope==='public'?'暂时没有公开课程':initialScope==='managed'?'还没有课程':'还没有加入课程'),el('p',noMatches?'可以更换关键词，或清除筛选条件查看全部课程。':initialScope==='public'?'公开课程会显示在这里，加入后即可开始学习。':initialScope==='managed'?'先创建课程，再逐步添加课时。':'去课程广场挑选一门课程，加入后就能开始学习。'));
      if(noMatches)empty.append(button('清除筛选条件',()=>{search.value='';selectedKind='all';if(statusFilter)statusFilter.value='all';pageIndex=0;filters.querySelectorAll('button').forEach(item=>{const active=item.dataset.kind==='all';item.classList.toggle('selected',active);item.setAttribute('aria-pressed',String(active));});paint();},'button secondary'));
      else if(initialScope==='mine')empty.append(button('前往课程广场',()=>route('/plaza'),'button primary'));
      else if(initialScope==='managed')empty.append(button('创建课程',()=>route('/editor/new/info'),'button primary'));
      grid.append(empty);return;}
    for(const course of filtered.slice(start,start+pageSize)){
      const card=el('article','','course-card');const body=el('div','','course-card-body');const labels=el('div','','course-card-labels');
      const status=initialScope==='managed'?statusText(course):course.is_enrolled?'已加入':course.access_mode==='public'?'公开加入':'名单课程';labels.append(el('span',status,'course-chip'),el('span',`${course.lesson_count||0} 课时`,'course-muted'));body.append(labels,el('h3',course.title),el('p',course.description||'按章节学习课程内容。','course-card-description'));
      if(course.host_name)body.append(el('p',`主讲 · ${course.host_name}`,'course-card-host'));
      const kinds=el('div','','course-kind-list');for(const [kind,label]of [['live','直播'],['video','录播'],['document','资料']])if((course.content_kinds||[]).includes(kind))kinds.append(el('span',label,'course-kind'));if(kinds.childElementCount)body.append(kinds);
      if(initialScope==='mine'&&course.progress_summary?.total){const progress=el('div','','course-card-progress');const track=el('div','','course-progress-track');const bar=el('span');bar.style.width=`${course.progress_summary.percent}%`;track.append(bar);progress.append(track,el('span',`${course.progress_summary.percent}% · ${course.progress_summary.completed}/${course.progress_summary.total} 课时`,'course-muted'));body.append(progress);}
      if(initialScope==='managed'&&course.access_mode==='roster')body.append(el('p','仅指定学员可见','course-muted'));
      const actions=el('div','','course-card-actions');
      const path=initialScope==='public'?`/preview/${course.id}`:`/course/${course.id}`;const action=initialScope==='managed'?`/editor/${course.id}/content`:initialScope==='mine'&&course.resume_lesson_id?`/study/${course.resume_lesson_id}`:path;const actionLabel=initialScope==='managed'?'编辑课程':initialScope==='public'?'查看课程':course.progress_summary?.percent>0&&course.progress_summary.percent<100?'继续学习':course.progress_summary?.percent===100?'复习课程':'开始学习';actions.append(button(actionLabel,()=>route(action),initialScope==='managed'?'button secondary':'button primary'));
      body.append(actions);card.append(body);grid.append(card);
    }
    if(pageCount>1){const previous=button('← 上一页',()=>{pageIndex--;paint();},'button secondary');previous.disabled=pageIndex===0;const current=el('span',`第 ${pageIndex+1} / ${pageCount} 页`,'course-muted');const next=button('下一页 →',()=>{pageIndex++;paint();},'button secondary');next.disabled=pageIndex>=pageCount-1;pagination.append(previous,current,next);}
  };
  search.addEventListener('input',()=>{pageIndex=0;paint();});statusFilter?.addEventListener('change',()=>{pageIndex=0;paint();});const panel=el('div','','course-catalog-content');panel.append(filters,toolbar,grid,pagination);shell.append(hero,tabs,panel);target.replaceChildren(shell);setBusy(target,true);grid.replaceChildren(el('p','正在加载课程…','course-muted'));
  try{const result=await api(`/courses?scope=${initialScope}`);if(turn!==generation)return;data=result.items||[];paint();}finally{if(turn===generation)setBusy(target,false);}
}

async function renderPreview(id,turn){
  const course=await api(`/courses/public/${id}`);if(turn!==generation)return;const target=root();target.replaceChildren();
  const back=button('← 返回课程广场',()=>route('/plaza'),'text-button course-back');const header=el('header','','course-preview-header');header.append(pageTitle(course.title,course.description||'课程简介暂未填写。'));
  const facts=el('div','','course-preview-facts');if(hostName(course))facts.append(el('span',hostName(course)));facts.append(el('span',`${course.lesson_count} 个课时`),el('span',(course.content_kinds||[]).map(kind=>({live:'直播',video:'录播',document:'资料'}[kind])).join(' · ')||'课程内容准备中'));
  const actions=el('div','','course-preview-actions');if(course.is_enrolled){const lessonId=course.resume_lesson_id;actions.append(button(course.progress_summary?.percent===100?'复习课程':'继续学习',()=>route(lessonId?`/study/${lessonId}`:`/course/${course.id}`),'button primary'));if(course.progress_summary?.total)actions.append(el('span',`${course.progress_summary.percent}% · ${course.progress_summary.completed}/${course.progress_summary.total} 课时`,'course-muted'));}else if(course.can_manage)actions.append(button('管理课程',()=>route(`/editor/${course.id}/content`),'button primary'));else actions.append(button('加入并开始学习',async()=>{const enrolled=await api(`/courses/${course.id}/enroll`,{method:'POST'});notify('已加入课程，开始第一课');const first=allLessons(enrolled)[0];await route(first?`/study/${first.id}`:`/course/${course.id}`);},'button primary'));
  header.append(facts,actions);const outline=el('section','','course-preview-outline');outline.append(sectionTitle('课程目录',`${course.sections.length} 章 · ${course.lesson_count} 个课时`));
  for(const [sectionIndex,section]of course.sections.entries()){const group=el('section','','course-preview-section');group.append(el('h2',`${String(sectionIndex+1).padStart(2,'0')}  ${section.title}`));const list=el('ol','','course-preview-lessons');for(const lesson of section.lessons){const row=el('li','','course-preview-lesson');row.append(el('span',lesson.title),el('span',(lesson.content_kinds||[]).map(kind=>({live:'直播',video:'录播',document:'资料'}[kind])).join(' · ')||'内容准备中','course-muted'));list.append(row);}group.append(list);outline.append(group);}
  target.append(back,header,outline);
}

function deleteCourseAction(course){
  return button('永久删除课程',async()=>{if(!await confirmAction(`永久删除“${course.title}”将同时移除课程章节、课时、报名记录、学习进度、直播历史、录播和所有课程文件。此操作无法撤销。`,{title:'永久删除整门课程？',danger:true,confirmText:'删除课程'}))return;await api(`/courses/${course.id}`,{method:'DELETE'});notify('课程及其全部内容已删除');await route('/manage');},'text-button danger');
}

async function renderEditor(courseId,step,turn){
  if(!courseId){renderEditorInfo(null,null);return;}
  const course=await api(`/courses/${courseId}`);if(turn!==generation)return;
  if(step==='content'){await renderCourse(courseId,turn,true);return;}
  const target=root();if(step==='info'){renderEditorInfo(courseId,course,target);return;}target.replaceChildren();const shell=el('div','','course-editor-shell');const back=button('← 返回课程内容',()=>route(`/editor/${courseId}/content`),'text-button course-back');const header=el('header','','course-editor-header');header.append(pageTitle(course.title,'设置学员和发布状态。'));
  shell.append(back,header);await renderEditorPublish(course,turn,shell);if(turn===generation)target.append(shell);
}

function renderEditorInfo(courseId,course,target=root()){
  const shell=el('div','','course-editor-shell');const back=button(courseId?'← 返回课程内容':'← 返回课程管理',()=>route(courseId?`/editor/${courseId}/content`:'/manage'),'text-button course-back');const header=el('header','','course-editor-header');header.append(pageTitle(course?.title||'新建课程','添加基本信息，再安排课程内容。'));
  const panel=el('section','','course-editor-panel');panel.append(el('h2','课程信息'),el('p','名称和简介会显示在课程广场及学员课程页。','course-muted'));
  const title=input(course?.title||'');title.required=true;title.maxLength=100;const description=textArea(course?.description||'');description.maxLength=4000;const access=el('select');for(const [value,label]of [['public','公开加入'],['roster','名单学员']]){const option=el('option',label);option.value=value;access.append(option);}access.value=course?.access_mode||'public';
  panel.append(field('课程名称',title),field('课程简介',description),field('加入方式',access,'公开课程会出现在课程广场；名单课程只对分配的学员开放。'));
  const actions=el('div','','course-editor-actions');actions.append(button(courseId?'保存课程信息':'保存并继续：课程内容 →',async()=>{if(!title.value.trim()){title.focus();throw new Error('请填写课程名称');}const payload={title:title.value.trim(),description:description.value.trim(),publication_status:course?.publication_status||'draft',access_mode:access.value,host_id:course?.host_id||state.user.id,member_ids:course?.member_ids||[]};const saved=await api(courseId?`/courses/${courseId}`:'/courses',{method:courseId?'PATCH':'POST',body:json(payload)});notify(courseId?'课程信息已保存':'课程草稿已创建');await route(`/editor/${saved.id}/content`);},'button primary'));
  shell.append(back,header,panel,actions);target.replaceChildren(shell);
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
  const back=button(editor?'← 返回课程管理':'← 返回课程',()=>route(editor?'/manage':''),'text-button course-back');const header=el('header','','course-detail-header');header.append(pageTitle(course.title,course.description));
  const actions=el('div','','course-header-actions');if(course.can_manage){if(editor){const nav=el('nav','','course-editor-nav');nav.setAttribute('aria-label','课程管理');for(const [label,path,selected]of [['课程内容',`/editor/${course.id}/content`,true],['课程信息',`/editor/${course.id}/info`,false],['学员与发布',`/editor/${course.id}/publish`,false]]){const link=button(label,()=>route(path),'course-editor-nav-link');link.setAttribute('aria-current',selected?'page':'false');nav.append(link);}actions.append(nav);}else actions.append(button('编辑课程',()=>route(`/editor/${course.id}/info`),'button secondary'));}
  else if(course.is_self_enrolled)actions.append(button('退出课程',async()=>{if(await confirmAction('退出后仍会保留学习进度，但需要重新加入才能继续学习。',{title:'退出这门课程？',danger:true,confirmText:'退出课程'})){await api(`/courses/${id}/enroll`,{method:'DELETE'});await route('');}},'text-button'));
  header.append(actions);
  const summary=el('div','','course-overview');const track=el('div','','course-progress-track');const fill=el('span');fill.style.width=`${course.progress_summary.percent}%`;track.append(fill);summary.append(track,el('span',`${course.progress_summary.completed}/${course.progress_summary.total} 个课时完成`,'course-muted'));
  let readiness=null;if(course.can_manage&&course.publication_status==='draft'){const issues=course.publish_issues||[];readiness=el('aside','','course-publish-readiness');const readinessHeading=el('div','','course-readiness-heading');readinessHeading.append(el('span',issues.length?'发布准备':'发布条件','eyebrow'),el('strong',issues.length?`${issues.length} 项待完成`:'已满足发布条件'));readiness.append(readinessHeading);if(issues.length){const list=el('ul','','course-readiness-list');issues.forEach(issue=>list.append(el('li',issue)));readiness.append(list);}else readiness.append(el('p','课程内容已准备就绪，可以发布给学员。','course-muted'));}
  const sections=el('div','','course-section-list');
  course.sections.forEach((section,index)=>{
    const sectionNode=el('section','','course-chapter');const heading=el('header','','course-chapter-heading');const title=el('div','','course-chapter-title');title.append(el('span',String(index+1).padStart(2,'0'),'course-order-number'),el('h2',section.title),el('span',`${section.lessons.length} 课时`,'course-muted'));heading.append(title);
    if(course.can_manage){const controls=el('div','','course-inline-actions');if(section.lessons.length)controls.append(button('＋ 添加课时',()=>addLesson(course,section,editor),'button secondary'));const more=el('details','','course-manage-more');more.append(el('summary','章节设置'));const menu=el('div','','course-manage-more-menu');if(index>0)menu.append(button('上移章节',async()=>{const ids=course.sections.map(s=>s.id);[ids[index-1],ids[index]]=[ids[index],ids[index-1]];await api(`/courses/${id}/sections/order`,{method:'PUT',body:json({ids})});await refreshManagedCourse(id,editor);},'text-button'));if(index<course.sections.length-1)menu.append(button('下移章节',async()=>{const ids=course.sections.map(s=>s.id);[ids[index+1],ids[index]]=[ids[index],ids[index+1]];await api(`/courses/${id}/sections/order`,{method:'PUT',body:json({ids})});await refreshManagedCourse(id,editor);},'text-button'));menu.append(button('重命名章节',()=>editSection(course,section,editor),'text-button'));const removeSection=button('删除章节',async()=>{if(await confirmAction(`删除空章节“${section.title}”？章节中仍有课时，需先删除课时。`,{title:'删除章节？',danger:true,confirmText:'删除章节'})){await api(`/courses/sections/${section.id}`,{method:'DELETE'});await refreshManagedCourse(id,editor);}},'text-button danger');removeSection.disabled=section.lessons.length>0;removeSection.title=section.lessons.length?'请先删除章节内的课时':'';menu.append(removeSection);more.append(menu);controls.append(more);heading.append(controls);}
    const lessonList=el('div','','course-lesson-list');
    if(!section.lessons.length){const empty=el('div','','course-first-lesson');empty.append(el('span','本章还没有课时。','course-muted'));if(course.can_manage)empty.append(button('添加第一课时',()=>addLesson(course,section,editor),'button primary'));lessonList.append(empty);}
    section.lessons.forEach((lesson,lessonIndex)=>{
      const row=el('article','','course-lesson-row');const details=el('div','','course-lesson-copy');const name=el('div','','course-lesson-name');name.append(el('span',String(lessonIndex+1).padStart(2,'0'),'course-lesson-number'),el('h3',lesson.title),el('span',unitType(lesson),'course-unit-type'));if(lesson.progress.completed)name.append(el('span','已完成','course-complete-chip'));const liveItem=lesson.items.find(item=>item.kind==='live'&&item.live);const liveTime=liveItem?.live?.starts_at?` · ${new Date(liveItem.live.starts_at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false})}`:'';details.append(name,el('p',`${lesson.description||lesson.items.map(item=>item.kind==='live'?'直播课':item.kind==='video'?'录播视频':'文档资料').join(' · ')||'课程管理员正在准备内容'}${liveTime}`,'course-muted'));
      const buttons=el('div','','course-lesson-actions');
      if(course.can_manage){const open=lesson.items.length?button('预览课时 →',()=>route(`/study/${lesson.id}`),'button secondary'):button('添加内容',()=>addLessonContent(course,lesson,editor),'button primary');buttons.append(open);if(lesson.items.length)buttons.append(button('＋ 添加内容',()=>addLessonContent(course,lesson,editor),'button secondary'));const more=el('details','','course-lesson-more');const summary=el('summary','更多');const menu=el('div','','course-lesson-more-menu');if(lessonIndex>0)menu.append(button('上移课时',async()=>{const ids=section.lessons.map(x=>x.id);[ids[lessonIndex-1],ids[lessonIndex]]=[ids[lessonIndex],ids[lessonIndex-1]];await api(`/courses/sections/${section.id}/lessons/order`,{method:'PUT',body:json({ids})});await refreshManagedCourse(id,editor);},'text-button'));if(lessonIndex<section.lessons.length-1)menu.append(button('下移课时',async()=>{const ids=section.lessons.map(x=>x.id);[ids[lessonIndex+1],ids[lessonIndex]]=[ids[lessonIndex],ids[lessonIndex+1]];await api(`/courses/sections/${section.id}/lessons/order`,{method:'PUT',body:json({ids})});await refreshManagedCourse(id,editor);},'text-button'));menu.append(button('重命名课时',()=>editLesson(course,lesson,editor),'text-button'));const removeLesson=button('删除课时',async()=>{if(await confirmAction(`删除空课时“${lesson.title}”？请先移除视频和资料；直播课次请在直播课堂中删除。`,{title:'删除课时？',danger:true,confirmText:'删除课时'})){await api(`/courses/lessons/${lesson.id}`,{method:'DELETE'});await refreshManagedCourse(id,editor);}},'text-button danger');removeLesson.disabled=lesson.items.length>0;removeLesson.title=lesson.items.length?'请先移除课时中的内容':'';menu.append(removeLesson);more.append(summary,menu);buttons.append(more);}
      else{buttons.append(button('开始学习 →',()=>route(`/study/${lesson.id}`),'button primary'));}
      if(course.can_manage&&lesson.items.length){const contents=el('div','','course-managed-items');contents.append(el('span','课时内容','course-muted'));lesson.items.forEach((item,itemIndex)=>{const itemRow=el('div','','course-managed-item');const itemName=item.kind==='live'?item.live?.title||'直播课':item.asset?.original_name||'课程文件';itemRow.append(el('span',item.kind==='live'?'直播':item.kind==='video'?'录播':'资料','course-chip'),el('span',itemName,'course-managed-item-name'));const more=el('details','','course-item-more');more.append(el('summary','⋯'));const menu=el('div','','course-manage-more-menu');if(itemIndex>0)menu.append(button('上移内容',()=>moveItem(course,lesson,itemIndex,-1,editor),'text-button'));if(itemIndex<lesson.items.length-1)menu.append(button('下移内容',()=>moveItem(course,lesson,itemIndex,1,editor),'text-button'));if(item.asset)menu.append(button('移除内容',()=>removeAsset(course,item.asset,editor),'text-button danger'));more.append(menu);itemRow.append(more);contents.append(itemRow);});details.append(contents);}
      row.append(details,buttons);lessonList.append(row);
    });
    sectionNode.append(heading,lessonList);sections.append(sectionNode);
  });
  if(!course.sections.length)sections.append(el('p','课程还没有章节。','course-muted'));
  if(editor){const shell=el('div','','course-editor-shell');shell.append(back,header);const panel=el('section','','course-editor-content-panel');const titleRow=sectionTitle('课程目录',`${course.sections.length} 章 · ${course.progress_summary.total} 课时`);titleRow.append(button('＋ 添加章节',()=>addSection(course,editor),'button secondary'));panel.append(titleRow,sections);shell.append(panel);target.append(shell);return;}
  target.append(back,header);if(!course.can_manage)target.append(summary);if(readiness)target.append(readiness);target.append(sectionTitle('课程目录',`${course.sections.length} 章 · ${course.progress_summary.total} 课时`),sections);
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
  const first=!section.lessons.length;const {dialog,body,footer}=modal(first?'添加第一课时':'添加课时','设置名称并选择内容类型。创建后会直接进入上传或直播安排。');const title=input('');title.required=true;const description=textArea('');const kind=el('select');
  for(const [value,label]of [['document','课程资料'],['video','录播视频'],['live','直播']]){const option=el('option',label);option.value=value;kind.append(option);}
  body.append(field('课时名称',title),field('课时说明（可选）',description),field('内容类型',kind,'之后可在课时中继续添加其他内容。'));
  footer.append(button('创建课时并继续',async()=>{
    if(!title.value.trim())throw new Error('请填写课时名称');
    const data={title:title.value.trim(),description:description.value.trim(),position:section.lessons.length};
    const created=await api(`/courses/sections/${section.id}/lessons`,{method:'POST',body:json(data)});
    dialog.close();
    await refreshManagedCourse(course.id,editor);
    const lesson=allLessons(created).find(item=>item.id===created.id)||{id:created.id,title:data.title,items:[],course_id:course.id};
    if(kind.value==='live')scheduleLive(lesson,editor);else pickAsset(lesson.id,kind.value,course.id,editor);
  },'button primary'));
}

function addLessonContent(course,lesson,editor=false){
  const {dialog,body}=modal('添加课时内容',`为“${lesson.title}”选择一种内容。可以重复添加，让一节课包含视频和资料，也可以安排直播。`);
  const choices=el('div','','course-content-choices');
  const choose=(label,action)=>{const control=button(label,()=>{dialog.close();action();},'button secondary');choices.append(control);};
  choose('上传录播视频',()=>pickAsset(lesson.id,'video',course.id,editor));
  choose('上传课程资料',()=>pickAsset(lesson.id,'document',course.id,editor));
  choose('安排直播',()=>scheduleLive(lesson,editor));
  body.append(choices);
}

function editLesson(course,lesson,editor=false){
  const {dialog,body,footer}=modal('编辑课时');const title=input(lesson.title);title.required=true;const description=textArea(lesson.description||'');body.append(field('课时名称',title),field('课时说明',description));
  footer.append(button('保存课时',async()=>{if(!title.value.trim())throw new Error('请填写课时名称');await api(`/courses/lessons/${lesson.id}`,{method:'PATCH',body:json({title:title.value.trim(),description:description.value.trim(),position:lesson.position})});dialog.close();await refreshManagedCourse(course.id,editor);},'button primary'));
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
  const picker=el('input');picker.type='file';picker.accept=kind==='video'?'.mp4,.webm':'.pdf,.txt,.md,.docx,.pptx,.xlsx,.png,.jpg,.jpeg';picker.hidden=true;document.body.append(picker);
  picker.addEventListener('change',()=>{const file=picker.files?.[0];if(!file){picker.remove();return;}void run(async()=>{try{await uploadFile(`/courses/lessons/${lessonId}/assets?kind=${kind}`,file);notify(kind==='video'?'视频已加入课时':'资料已加入课时');await refreshManagedCourse(courseId,editor);}finally{picker.remove();}});});picker.click();
}

async function privateAsset(asset,asText=false){
  const response=await fetch(`/api/courses/assets/${asset.id}/file`,{headers:{Authorization:`Bearer ${state.token}`}});
  if(!response.ok)throw new Error('资料读取失败，请刷新课程后重试');
  return asText?response.text():URL.createObjectURL(await response.blob());
}
async function videoUrl(asset){const result=await api(`/courses/assets/${asset.id}/playback`,{method:'POST'});return result.url;}

async function renderStudy(lessonId,turn){
  const lesson=await api(`/courses/lessons/${lessonId}`);if(turn!==generation)return;const course=await api(`/courses/${lesson.course_id}`);if(turn!==generation)return;
  const lessons=allLessons(course);const index=lessons.findIndex(item=>item.id===lesson.id);const target=root();target.replaceChildren();
  const back=button('← 课程目录',()=>route(`/course/${course.id}`),'text-button course-back');const top=el('header','','course-study-heading');top.append(pageTitle(lesson.title,lesson.description));top.append(el('span',`${course.title} · ${lesson.progress.completed?'已完成':'学习中'}`,'course-muted'));
  const layout=el('div','','course-study-layout');const nav=el('aside','','course-study-nav');const navHeading=sectionTitle('本课程',`${course.progress_summary.completed}/${course.progress_summary.total} 已完成`);const navToggle=button('',()=>{const expanded=navToggle.getAttribute('aria-expanded')!=='true';navToggle.setAttribute('aria-expanded',String(expanded));nav.classList.toggle('is-expanded',expanded);navContent.hidden=!expanded;},'course-study-nav-toggle');navToggle.setAttribute('aria-expanded','false');navToggle.append(el('span',`课程目录 · ${course.progress_summary.completed}/${course.progress_summary.total} 已完成`),el('span','⌄','course-nav-chevron'));const navContent=el('div','','course-study-nav-content');navContent.hidden=matchMedia('(max-width: 760px)').matches;
  for(const section of course.sections){const group=el('section','','course-study-group');group.append(el('h3',section.title));for(const item of section.lessons){const link=button('',()=>route(`/study/${item.id}`),'course-study-link');link.classList.toggle('current',item.id===lesson.id);link.append(el('span',item.progress.completed?'✓':String(item.position+1).padStart(2,'0'),'course-study-link-number'),el('span',item.title));group.append(link);}navContent.append(group);}nav.append(navHeading,navToggle,navContent);
  const content=el('main','','course-study-content');const contentMeta=el('div','','course-lesson-content-meta');contentMeta.append(el('span',`第 ${index+1} / ${lessons.length} 课时`,'course-muted'),el('span',unitType(lesson),'course-chip'));content.append(contentMeta);
  if(!lesson.items.length){const empty=el('div','','course-empty');empty.append(el('h2','本课时内容正在准备'),el('p','课程管理员会在这里添加直播、录播或文档资料。'));content.append(empty);}
  for(const item of lesson.items){
    if(item.kind==='live'){
      if(!item.live){content.append(el('p','该直播已删除。','course-muted'));continue;}
      const panel=el('section','','course-content-block course-live-block');panel.append(el('span','直播课','course-chip'));
      if(item.live.title!==lesson.title)panel.append(el('h2',item.live.title));
      if(item.live.description&&item.live.description!==lesson.description)panel.append(el('p',item.live.description,'course-muted'));
      const starts=item.live.starts_at?new Date(item.live.starts_at*1000).toLocaleString('zh-CN',{month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit',hour12:false}):'时间待安排';
      const liveStatus={scheduled:'等待开课',live:'直播进行中',ended:'直播已结束'}[item.live.status]||'直播状态待确认';
      panel.append(el('p',`开课时间 ${starts} · ${liveStatus}`,'course-muted'));
      panel.append(button(item.live.status==='live'?'进入直播课堂 →':item.live.status==='ended'?'查看课堂与回放 →':'查看直播安排',()=>route(`/lesson/${item.live.id}`),'button primary'));
      if(item.live.status==='ended'){const complete=button(lesson.progress.completed?'本课时已完成':'标记本课时完成',()=>markLessonComplete(lesson),'button secondary');complete.disabled=Boolean(lesson.progress.completed);panel.append(complete);}
      content.append(panel);
    }else if(item.kind==='video'&&item.asset){
      const panel=el('section','','course-content-block course-video-block');panel.append(el('div',item.asset.original_name,'course-content-title'));
      try{const player=el('video');player.controls=true;player.playsInline=true;player.preload='metadata';player.src=await videoUrl(item.asset);if(lesson.progress.position_seconds>0)player.addEventListener('loadedmetadata',()=>{player.currentTime=Math.min(lesson.progress.position_seconds,Math.max(0,player.duration-1));},{once:true});let lastSaved=0,pending=null,saving=null;
        const save=(completed=false)=>{pending={position_seconds:Math.floor(player.currentTime||0),completed};if(saving)return saving;saving=(async()=>{while(pending){const snapshot=pending;pending=null;try{await api(`/courses/lessons/${lesson.id}/progress`,{method:'PUT',body:json(snapshot)});}catch(error){pending=snapshot;notify(`播放进度保存失败，切换页面前会重试：${error.message}`,'error');return false;}}return true;})().finally(()=>{saving=null;});return saving;};
        courseProgressFlushers.add(()=>save());
        player.addEventListener('timeupdate',()=>{if(player.currentTime-lastSaved>=15){lastSaved=player.currentTime;void save();}});player.addEventListener('pause',()=>void save());player.addEventListener('ended',()=>void save(true));panel.append(player);
      }catch(error){panel.append(el('p',error.message,'course-error-text'));}content.append(panel);
    }else if(item.kind==='document'&&item.asset){
      const panel=el('section','','course-content-block course-document-block');const title=el('div','','course-content-title');title.append(el('span',item.asset.original_name),el('span',`${(item.asset.size/1024/1024).toFixed(1)} MB`,'course-muted'));panel.append(title);
      const view=button('预览资料',async()=>{const url=await privateAsset(item.asset);const frame=el('iframe');frame.src=url;frame.title=item.asset.original_name;frame.loading='lazy';frame.className='course-document-preview';panel.replaceChildren(title,frame,actions);},'button secondary');
      const download=button('下载',async()=>{const url=await privateAsset(item.asset);const link=el('a');link.href=url;link.download=item.asset.original_name;link.click();setTimeout(()=>URL.revokeObjectURL(url),30000);},'button secondary');
      const complete=button(lesson.progress.completed?'已完成':'标记本课时完成',()=>markLessonComplete(lesson),'button primary');complete.disabled=Boolean(lesson.progress.completed);
      const actions=el('div','','course-document-actions');actions.append(view,download,complete);panel.append(actions);content.append(panel);
    }
  }
  const navigation=el('footer','','course-study-navigation');const previous=button('← 上一课',()=>route(`/study/${lessons[index-1].id}`),'button secondary');previous.disabled=index<=0;const next=button('下一课 →',()=>route(`/study/${lessons[index+1].id}`),'button primary');next.disabled=index<0||index>=lessons.length-1;navigation.append(previous,next);content.append(navigation);layout.append(nav,content);target.append(back,top,layout);
}

async function markLessonComplete(lesson){
  await api(`/courses/lessons/${lesson.id}/progress`,{method:'PUT',body:json({position_seconds:lesson.progress.position_seconds||0,completed:true})});
  notify('学习进度已保存');await renderCoursePage({kind:'study',id:lesson.id});
}
