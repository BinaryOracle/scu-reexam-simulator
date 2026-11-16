/** Course library, lesson preparation, administration and recording playback. */
import {api,state} from './api.js?v=20261114-ui-v17';
import {emptyState,run} from './ui.js?v=20261114-ui-v17';
import {el,button,notify,confirmAction,field,input,textArea,modal,materialList} from './live-ui.js?v=1';
import {liveRoute,liveDate,recordingText,mayJoin,needsLessonUpdates} from './live-model.mjs?v=1';
import {mediaLease} from './live-devices.mjs?v=1';
import {Classroom} from './live-room.js?v=20261116-frames-v1';
import {writeAppRoute} from './view-route.mjs?v=20261115-navigation-v3';
let revision=0,room=null,pageTimer=null;
const root=()=>document.getElementById('liveContent');
const valid=(turn)=>turn===revision&&state.user&&!document.getElementById('live')?.hidden;
const labels={scheduled:'待开课',live:'直播中',ended:'已结束'};
const json=(body)=>JSON.stringify(body);
/** Release devices and timers on logout or navigation away from the classroom. */
export function clearLive(){revision++;clearTimeout(pageTimer);pageTimer=null;room?.dispose();room=null;document.body.classList.remove('live-immersive');document.querySelectorAll('dialog[data-live-owned]').forEach(dialog=>dialog.close());}
export function liveActive(){return Boolean(room);}
export async function allowLiveNavigation(){return !room||await confirmAction('离开后将停止你的麦克风、摄像头和共享。课堂会继续进行。',{title:'离开当前课堂？',confirmText:'离开课堂'});}
function navigate(route){writeAppRoute(`live${route}`);return refreshLive();}
function pageHeading(eyebrow,title,description){const box=el('div','','live-heading-copy');box.append(el('span',eyebrow,'eyebrow'),el('h1',title));if(description)box.append(el('p',description));return box;}
function pill(status){return el('span',labels[status]||status,`live-status ${status}`);}
/** Restore a course or lesson route without retaining a previous audio session. */
export async function refreshLive(){
  if(room){
    if(location.hash===`#view=live/lesson/${room.lesson.id}`)return;
    if(!await allowLiveNavigation()){writeAppRoute(`live/lesson/${room.lesson.id}`,{replace:true});return;}
    room.dispose();room=null;
  }
  const turn=++revision;clearTimeout(pageTimer);document.body.classList.remove('live-immersive');
  const target=root();target.setAttribute('aria-busy','true');target.replaceChildren(el('p','正在准备课堂…','live-loading'));
  const route=liveRoute(location.hash);
  try{
    if(route.kind==='list'){const data=await api('/live/courses');if(valid(turn))renderLibrary(data);}
    else if(route.kind==='course'){const data=await api(`/live/courses/${route.id}`);if(valid(turn))renderCourse(data);}
    else {const data=await api(`/live/lessons/${route.id}`);if(valid(turn)){renderLesson(data);if(needsLessonUpdates(data))scheduleLesson(data.id,turn);}}
  }catch(error){if(valid(turn))target.replaceChildren(emptyState('暂时无法打开课堂',error.message),button('返回课程列表',()=>navigate('')));}
  finally{if(valid(turn))target.removeAttribute('aria-busy');}
}
function renderLibrary(data){
  const target=root();target.replaceChildren();
  const hero=el('header','','live-library-hero');
  hero.append(pageHeading('LIVE CLASSROOM','一起上课，把问题当场讲明白。','课程资料、课堂互动与课后回放，在一个地方继续学习。'));
  const motif=el('div','','live-hero-motif');motif.setAttribute('aria-hidden','true');motif.append(el('span','LIVE'),el('div','一起学习'),el('i'));hero.append(motif);
  const toolbar=el('div','','live-section-toolbar');const title=el('div');title.append(el('h2','我的课程'),el('span',`${data.items.length} 门课程`,'live-helper'));toolbar.append(title);
  if(state.user.is_admin)toolbar.append(button('＋ 创建课程',()=>editCourse(),'button primary'));
  target.append(hero,toolbar);
  const filters=el('div','','live-library-filters');const search=input('','search');search.placeholder='搜索课程名称';search.setAttribute('aria-label','搜索课程名称');filters.append(search);
  const grid=el('div','','live-course-grid');const paint=()=>{
    grid.replaceChildren();const items=data.items.filter(item=>item.title.toLowerCase().includes(search.value.trim().toLowerCase()));
    if(!items.length){const empty=emptyState(data.items.length?'没有找到相关课程':'学习，从一堂课开始',data.items.length?'换一个关键词试试看。':state.user.is_admin?'创建课程，安排第一节直播课，并邀请学员加入。':'加入的课程会显示在这里，请联系课程管理员。','▤');grid.append(empty);return;}
    items.forEach((course,index)=>{
      const card=el('article','',`live-course-card tone-${index%3}`);const cover=el('div','','live-course-cover');
      cover.append(el('span','知序课堂','live-cover-brand'),el('span',String(index+1).padStart(2,'0'),'live-cover-number'));
      if(course.live_count)cover.append(pill('live'));
      const body=el('div','','live-course-body');body.append(el('h3',course.title),el('p',course.description||'和同学一起，在交流中理解，在练习中进步。','live-course-description'));
      const meta=el('div','','live-course-meta');meta.append(el('span',`${course.host_name||'课程主持人'}`),el('span',`${course.lesson_count||0} 节课`));
      const footer=el('div','','live-course-footer');footer.append(el('span',course.can_manage?'可管理课程':'已加入课程','live-helper'),button('查看课程 →',()=>navigate(`/course/${course.id}`),'button secondary'));
      body.append(meta,footer);card.append(cover,body);grid.append(card);
    });
  };search.addEventListener('input',paint);paint();target.append(filters,grid);
}
function renderCourse(course){
  const target=root();target.replaceChildren();target.append(button('← 全部课程',()=>navigate(''),'text-button live-back'));
  const header=el('header','','live-course-heading');header.append(pageHeading('COURSE',course.title,course.description));
  if(course.can_manage){const actions=el('div','','live-actions');actions.append(button('编辑课程',()=>editCourse(course)),button('＋ 安排直播课',()=>editLesson(course),'button primary'));header.append(actions);}
  target.append(header);
  const toolbar=el('div','','live-section-toolbar');toolbar.append(el('h2','课程安排'),el('span',`${course.lessons.length} 节课 · 资料与回放按课次保存`,'live-helper'));target.append(toolbar);
  const list=el('div','','live-lesson-list');
  if(!course.lessons.length)list.append(emptyState('第一堂课，正在准备','课次发布后，学员可以在这里查看时间、资料和回放。','◷'));
  course.lessons.forEach((lesson,index)=>{
    const row=el('article','','live-lesson-row');const order=el('div',String(index+1).padStart(2,'0'),'live-lesson-order');const info=el('div','','live-lesson-info');
    const line=el('div','','live-title-line');line.append(pill(lesson.status),el('h3',lesson.title));info.append(line,el('p',liveDate(lesson.starts_at),'live-helper'));
    const actions=el('div','','live-actions');if(course.can_manage&&lesson.status!=='live')actions.append(button('编辑',()=>editLesson(course,lesson),'text-button'));
    actions.append(button(lesson.status==='live'?'进入课堂 →':lesson.status==='ended'?'资料与回放 →':'课前准备 →',()=>navigate(`/lesson/${lesson.id}`),lesson.status==='live'?'button primary':'button secondary'));
    row.append(order,info,actions);list.append(row);
  });target.append(list);
  if(course.can_manage)target.append(button('删除课程',async()=>{if(await confirmAction('删除课程将同时移除课次与课堂记录，此操作无法撤销。',{title:'删除课程？',danger:true,confirmText:'删除课程'})){await api(`/live/courses/${course.id}`,{method:'DELETE'});await navigate('');}},'text-button live-delete'));
}
function renderLesson(lesson){
  const target=root();target.replaceChildren();target.append(button('← 返回课程',()=>navigate(`/course/${lesson.course_id}`),'text-button live-back'));
  const hero=el('header','','live-lesson-hero');const copy=pageHeading('CLASS SESSION',lesson.title,lesson.description);
  const metadata=el('div','','live-lesson-metadata');metadata.append(pill(lesson.status),el('span',liveDate(lesson.starts_at)),el('span',lesson.course_title));copy.append(metadata);hero.append(copy);
  const entrance=el('div','','live-entrance');
  if(lesson.status==='scheduled'){
    entrance.append(el('span',lesson.is_host?'一切准备好，就开始吧':'好课堂，值得期待','live-entrance-caption'));
    if(lesson.is_host){const start=button('开始直播课 →',async()=>{await api(`/live/lessons/${lesson.id}/start`,{method:'POST'});await refreshLive();},'button primary');start.disabled=!lesson.configured;entrance.append(start);}
    else entrance.append(el('p','主持人开课后，这里将开放入会。','live-helper'));
  }else if(lesson.status==='live'){entrance.append(el('span','课堂已开始，加入一起学习','live-entrance-caption'));const join=button('进入课堂 →',()=>prepare(lesson),'button primary');join.disabled=!mayJoin(lesson);entrance.append(join);}
  else entrance.append(el('span','课堂已结束，学习还可以继续。','live-entrance-caption'));
  hero.append(entrance);target.append(hero);
  if(!lesson.configured&&lesson.status!=='ended'){const notice=el('div','','live-service-notice');notice.append(el('strong','直播服务尚未就绪'),el('span',state.user.is_admin?'完成直播服务配置后即可开课；现在可以先安排课程和上传资料。':'课程资料可以正常查看，直播开放时间请联系主持人。'));target.append(notice);}
  const columns=el('div','','live-detail-columns');const materials=el('section','','live-detail-panel');materials.append(el('h2','课程资料'),el('p','课前准备，课后也随时可查。','live-helper'));const files=el('div');materials.append(files);
  const lessonTurn=revision;
  materialList(files,lesson,{canManage:lesson.is_host||lesson.can_manage,refresh:()=>valid(lessonTurn)?refreshLive():undefined});
  const recordings=el('section','','live-detail-panel');recordings.append(el('h2','课堂回放'),el('p','把没来得及消化的内容，再听一遍。','live-helper'));
  if(!lesson.recordings?.length)recordings.append(el('div',lesson.status==='ended'?'本次课堂暂无录播文件。':'课堂录制完成后，回放会保存在这里。','live-empty-note'));
  for(const record of lesson.recordings||[]){const row=el('div','','live-recording-row');const text=el('div');text.append(el('strong',record.name||'课堂录播'),el('small',recordingText(record.status)));if(record.error)text.append(el('p',record.error,'live-helper'));row.append(text);
    if(['ready','completed'].includes(record.status))row.append(button('观看回放',()=>playback(record,lesson),'button secondary'));
    else if(lesson.is_host&&['unknown','starting','stopping',...(lesson.status==='ended'?['recording','processing']:[])].includes(record.status))row.append(button('核对录制状态',async()=>{await api(`/live/lessons/${lesson.id}/recording`,{method:'POST',body:json({action:'reconcile'})});await refreshLive();},'button secondary'));
    recordings.append(row);}
  columns.append(materials,recordings);target.append(columns);
  if(lesson.can_manage&&lesson.status!=='live')target.append(button('删除本次课',async()=>{if(await confirmAction('本次课的资料与回放也将移除。',{title:'删除课次？',danger:true,confirmText:'删除课次'})){await api(`/live/lessons/${lesson.id}`,{method:'DELETE'});await navigate(`/course/${lesson.course_id}`);}},'text-button live-delete'));
}
function scheduleLesson(id,turn){pageTimer=setTimeout(async()=>{try{const data=await api(`/live/lessons/${id}`);if(valid(turn)&&!room){if(!document.querySelector('dialog[data-live-owned][open]')&&!root().querySelector('[data-uploading]'))renderLesson(data);if(needsLessonUpdates(data))scheduleLesson(id,turn);}}catch(error){if(valid(turn)){notify(error.message,'error');scheduleLesson(id,turn);}}},10000);}
async function editCourse(course=null){
  const {dialog,body,footer}=modal(course?'编辑课程':'创建课程','设置课程信息和学员名单。主持人只在该课程内拥有课堂管理权限。');
  const title=input(course?.title||'');title.maxLength=100;title.required=true;
  const description=textArea(course?.description||'');description.maxLength=2000;
  const host=el('select');host.setAttribute('aria-label','课程主持人');
  const hostSearch=input('','search');hostSearch.placeholder='输入用户名查找主持人';
  body.append(field('课程名称',title),field('课程介绍',description),field('查找主持人',hostSearch),field('课程主持人',host));
  let selectedHost={id:course?.host_id||state.user.id,username:course?.host_name||state.user.username},hostTurn=0,hostDebounce;
  const paintHosts=items=>{host.replaceChildren();const candidates=[selectedHost,...items.filter(person=>person.id!==selectedHost.id)];for(const person of candidates)host.append(Object.assign(el('option',person.username),{value:person.id}));host.value=String(selectedHost.id);};
  host.addEventListener('change',()=>{selectedHost={id:Number(host.value),username:host.selectedOptions[0].textContent};});
  hostSearch.addEventListener('input',()=>{clearTimeout(hostDebounce);const turn=++hostTurn;hostDebounce=setTimeout(()=>void run(async()=>{const items=await api(`/live/people?q=${encodeURIComponent(hostSearch.value)}`);if(turn===hostTurn&&dialog.isConnected)paintHosts(items);}),250);});
  const search=input('','search');search.placeholder='搜索用户名';const roster=el('div','','live-roster-picker');const count=el('p','','live-helper');
  body.append(field('选择学员',search),count,roster);const chosen=new Set(course?.member_ids||[]);let people=[],searchTurn=0;
  const paint=()=>{roster.replaceChildren();for(const person of people){const check=input('','checkbox');check.checked=chosen.has(person.id);check.addEventListener('change',()=>{check.checked?chosen.add(person.id):chosen.delete(person.id);count.textContent=`已选择 ${chosen.size} 位学员`;});const label=el('label','','live-roster-choice');label.append(check,el('span',person.username));roster.append(label);}count.textContent=`已选择 ${chosen.size} 位学员`;if(!people.length)roster.append(el('p','未找到用户','live-helper'));};
  let debounce;search.addEventListener('input',()=>{clearTimeout(debounce);debounce=setTimeout(()=>void run(async()=>{const turn=++searchTurn;const result=await api(`/live/people?q=${encodeURIComponent(search.value)}`);if(turn!==searchTurn||!dialog.isConnected)return;people=Array.isArray(result)?result:result.items;paint();}),250);});
  const save=button('保存课程',async()=>{if(!title.value.trim()){title.focus();throw new Error('请填写课程名称');}await api(course?`/live/courses/${course.id}`:'/live/courses',{method:course?'PATCH':'POST',body:json({title:title.value.trim(),description:description.value.trim(),host_id:Number(host.value),member_ids:[...chosen]})});dialog.close();await refreshLive();},'button primary');save.disabled=true;footer.append(save);
  dialog.addEventListener('live-dispose',()=>{clearTimeout(debounce);clearTimeout(hostDebounce);});
  try{const result=await api('/live/people');if(!dialog.isConnected)return;people=Array.isArray(result)?result:result.items;paintHosts(people);paint();save.disabled=false;}catch(error){body.append(el('p',error.message,'live-error'));}
}
function editLesson(course,lesson=null){
  const {dialog,body,footer}=modal(lesson?'编辑课次':'安排直播课','资料可在课次创建后上传。直播开始前可以继续修改安排。');
  const title=input(lesson?.title||'');title.maxLength=100;
  const starts=input('','datetime-local');const date=new Date((lesson?.starts_at||Date.now()/1000+3600)*1000);date.setMinutes(date.getMinutes()-date.getTimezoneOffset());starts.value=date.toISOString().slice(0,16);
  const description=textArea(lesson?.description||'');body.append(field('本次课标题',title),field('开课时间',starts),field('课堂说明',description));
  footer.append(button('保存安排',async()=>{if(!title.value.trim())throw new Error('请填写本次课标题');if(!starts.value||!Number.isFinite(new Date(starts.value).getTime()))throw new Error('请选择开课时间');await api(lesson?`/live/lessons/${lesson.id}`:`/live/courses/${course.id}/lessons`,{method:lesson?'PATCH':'POST',body:json({title:title.value.trim(),description:description.value.trim(),starts_at:new Date(starts.value).getTime()/1000})});dialog.close();await refreshLive();},'button primary'));
}
async function prepare(lesson){
  const {dialog,body,footer}=modal('准备进入课堂','入会默认关闭麦克风和摄像头。建议佩戴耳机，减少回声。');dialog.classList.add('live-prepare-dialog');
  const preview=el('div','','live-device-preview');const avatar=el('div',state.user.username.slice(0,1).toUpperCase(),'live-avatar');const video=el('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.hidden=true;preview.append(avatar,video,el('span','摄像头默认关闭'));body.append(preview);
  const meter=el('div','','live-mic-meter');meter.setAttribute('role','meter');meter.setAttribute('aria-label','麦克风输入音量');meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');meter.append(el('i'));
  const status=el('p','检测完成后，可在课堂中自行开启设备。','live-helper');status.setAttribute('role','status');
  const lease=mediaLease(constraints=>navigator.mediaDevices.getUserMedia(constraints));
  let context,frame=0,closed=false;const release=()=>{lease.release();if(context)void context.close().catch(()=>{});context=null;cancelAnimationFrame(frame);video.srcObject=null;video.hidden=true;avatar.hidden=false;meter.style.setProperty('--level','0%');};
  dialog.addEventListener('live-dispose',()=>{closed=true;release();});
  const deviceActions=el('div','','live-device-actions');
  deviceActions.append(button('检测麦克风',async()=>{release();if(!navigator.mediaDevices?.getUserMedia)throw new Error('当前浏览器无法使用麦克风，请通过 HTTPS 或本机地址访问。');let acquired;try{acquired=await lease.acquire({audio:true});}catch(error){throw new Error('无法访问麦克风，请检查浏览器授权和系统输入设备。');}if(!acquired||closed)return;const AudioContext=window.AudioContext||window.webkitAudioContext;const audioContext=new AudioContext();context=audioContext;try{await audioContext.resume();}catch(error){if(!acquired.isCurrent())return;throw error;}if(!acquired.isCurrent()||closed){void audioContext.close().catch(()=>{});return;}const analyser=audioContext.createAnalyser();audioContext.createMediaStreamSource(acquired.stream).connect(analyser);const samples=new Uint8Array(analyser.fftSize);const tick=()=>{if(!context)return;analyser.getByteTimeDomainData(samples);const level=Math.min(100,Math.round(Math.sqrt(samples.reduce((sum,value)=>sum+((value-128)/128)**2,0)/samples.length)*300));meter.style.setProperty('--level',`${level}%`);meter.setAttribute('aria-valuenow',String(level));frame=requestAnimationFrame(tick);};tick();status.textContent='麦克风已连接，请说几句话，确认音量条有变化。';}),button('预览摄像头',async()=>{release();if(!navigator.mediaDevices?.getUserMedia)throw new Error('当前浏览器无法使用摄像头，请通过 HTTPS 或本机地址访问。');let acquired;try{acquired=await lease.acquire({video:true});}catch(error){throw new Error('无法访问摄像头，请检查浏览器授权。');}if(!acquired||closed)return;video.srcObject=acquired.stream;video.hidden=false;avatar.hidden=true;status.textContent='预览仅对自己可见，入会后摄像头仍保持关闭。';}));
  body.append(deviceActions,meter,status);
  footer.append(button('进入课堂 →',async()=>{release();const turn=revision;const credentials=await api(`/live/lessons/${lesson.id}/join`,{method:'POST'});if(!dialog.isConnected||!valid(turn)){void api(`/live/lessons/${lesson.id}/leave`,{method:'POST'}).catch(()=>{});return;}dialog.close();clearTimeout(pageTimer);document.body.classList.add('live-immersive');room=new Classroom(root(),lesson,credentials,async()=>{room=null;document.body.classList.remove('live-immersive');await refreshLive();});try{await room.connect();}catch(error){room?.dispose();room=null;document.body.classList.remove('live-immersive');await refreshLive();throw error;}},'button primary'));
}
async function playback(record,lesson){
  const {dialog,body,footer}=modal(lesson.title,'课堂回放');dialog.classList.add('live-playback-dialog');footer.firstChild.textContent='关闭回放';
  const video=el('video');video.controls=true;video.playsInline=true;video.preload='metadata';
  const status=el('p','正在加载回放…','live-helper');status.setAttribute('role','status');body.append(video,status);
  let expiresAt=0,refreshing=false,attempts=0,disposed=false,renewTimer;
  const renew=async()=>{
    if(refreshing||disposed)return;refreshing=true;retry.hidden=true;
    const position=Number.isFinite(video.currentTime)?video.currentTime:0;const resume=!video.paused;
    try{const result=await api(`/live/recordings/${record.id}/playback`,{method:'POST'});if(disposed)return;
      expiresAt=result.expires_at||Date.now()/1000+(result.expires_in||14400);
      clearTimeout(renewTimer);renewTimer=setTimeout(()=>void renew(),Math.max(1000,(expiresAt-Date.now()/1000-30)*1000));
      video.src=result.url;video.addEventListener('loadedmetadata',()=>{if(disposed)return;attempts=0;if(position>0)video.currentTime=position;if(resume)void video.play().catch(()=>{status.textContent='点击播放按钮继续观看。';});},{once:true});
      status.textContent='';
    }catch(error){if(!disposed){status.textContent=error.message;retry.hidden=false;}}
    finally{refreshing=false;}
  };
  const retry=button('重新加载回放',renew,'button secondary');retry.hidden=true;footer.append(retry);
  video.addEventListener('seeking',()=>{if(Date.now()/1000>expiresAt)void renew();});
  video.addEventListener('error',()=>{if(disposed)return;if(!refreshing&&attempts<1){attempts++;void renew();}else{status.textContent='回放暂时无法加载，请重试；若持续失败，请联系管理员。';retry.hidden=false;}});
  dialog.addEventListener('live-dispose',()=>{disposed=true;clearTimeout(renewTimer);video.pause();video.removeAttribute('src');video.load();});
  await renew();
}
