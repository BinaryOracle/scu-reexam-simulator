/** Live lesson detail, classroom entry, and recording playback. */
import {api,state,requireAuthenticatedUser} from './api.js?v=20261122-session-guard-v1';
import {emptyState} from './ui.js?v=20261114-ui-v17';
import {el,button,notify,confirmAction,modal,materialList} from './live-ui.js?v=1';
import {liveRoute,liveDate,recordingText,mayJoin,needsLessonUpdates} from './live-model.mjs?v=20261121-markdown-v1';
import {configureCourseLearning,renderCoursePage,clearCourseLearning} from './course-learning.js?v=20261126-course-popover-resize-v1';
import {mediaLease} from './live-devices.mjs?v=1';
import {Classroom} from './live-room.js?v=20261126-share-recovery-v1';
import {writeAppRoute} from './view-route.mjs?v=20261115-navigation-v3';
let revision=0,room=null,pageTimer=null;
const root=()=>document.getElementById('liveContent');
const liveRestoreKey='live-room-lesson';
function storedLiveLesson(){try{return sessionStorage.getItem(liveRestoreKey)||'';}catch{return '';}}
function rememberLiveLesson(id){try{sessionStorage.setItem(liveRestoreKey,String(id));}catch{}}
function forgetLiveLesson(id){try{if(!id||sessionStorage.getItem(liveRestoreKey)===String(id))sessionStorage.removeItem(liveRestoreKey);}catch{}}
const valid=(turn)=>turn===revision&&state.user&&!document.getElementById('live')?.hidden;
const labels={scheduled:'待开课',live:'直播中',ended:'已结束'};
const json=(body)=>JSON.stringify(body);
configureCourseLearning(path=>navigate(path));
/** Release devices and timers on logout or navigation away from the classroom. */
export function clearLive(){const lessonId=room?.lesson?.id;revision++;root().querySelectorAll('video').forEach(player=>player.pause());clearCourseLearning();clearTimeout(pageTimer);pageTimer=null;room?.dispose();room=null;forgetLiveLesson(lessonId);document.body.classList.remove('live-immersive');document.querySelectorAll('dialog[data-live-owned]').forEach(dialog=>dialog.close());}
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
  const target=root();const route=liveRoute(location.hash);target.setAttribute('aria-busy','true');
  if(route.kind!=='study'){clearCourseLearning();target.replaceChildren(el('p','正在准备课堂…','live-loading'));}
  try{
    if(['list','public','manage','course','study','preview','editor','markdown'].includes(route.kind)){if(valid(turn))await renderCoursePage(route);}
    else {const data=await api(`/live/lessons/${route.id}`);if(valid(turn)){renderLesson(data);if(needsLessonUpdates(data))scheduleLesson(data.id,turn);if(data.status==='live'&&storedLiveLesson()===String(data.id))await joinLesson(data,{restore:true,turn});}}
  }catch(error){if(valid(turn))target.replaceChildren(emptyState('暂时无法打开课堂',error.message),button('返回课程列表',()=>navigate('')));}
  finally{if(valid(turn))target.removeAttribute('aria-busy');}
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
async function prepare(lesson){
  const user=requireAuthenticatedUser();
  const {dialog,body,footer}=modal('准备进入课堂','入会默认关闭麦克风和摄像头。建议佩戴耳机，减少回声。');dialog.classList.add('live-prepare-dialog');
  const preview=el('div','','live-device-preview');const avatar=el('div',user.username.slice(0,1).toUpperCase(),'live-avatar');const video=el('video');video.autoplay=true;video.muted=true;video.playsInline=true;video.hidden=true;preview.append(avatar,video,el('span','摄像头默认关闭'));body.append(preview);
  const meter=el('div','','live-mic-meter');meter.setAttribute('role','meter');meter.setAttribute('aria-label','麦克风输入音量');meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');meter.append(el('i'));
  const status=el('p','检测完成后，可在课堂中自行开启设备。','live-helper');status.setAttribute('role','status');
  const lease=mediaLease(constraints=>navigator.mediaDevices.getUserMedia(constraints));
  let context,frame=0,closed=false;const release=()=>{lease.release();if(context)void context.close().catch(()=>{});context=null;cancelAnimationFrame(frame);video.srcObject=null;video.hidden=true;avatar.hidden=false;meter.style.setProperty('--level','0%');};
  dialog.addEventListener('live-dispose',()=>{closed=true;release();});
  const deviceActions=el('div','','live-device-actions');
  deviceActions.append(button('检测麦克风',async()=>{release();if(!navigator.mediaDevices?.getUserMedia)throw new Error('当前浏览器无法使用麦克风，请通过 HTTPS 或本机地址访问。');let acquired;try{acquired=await lease.acquire({audio:true});}catch(error){throw new Error('无法访问麦克风，请检查浏览器授权和系统输入设备。');}if(!acquired||closed)return;const AudioContext=window.AudioContext||window.webkitAudioContext;const audioContext=new AudioContext();context=audioContext;try{await audioContext.resume();}catch(error){if(!acquired.isCurrent())return;throw error;}if(!acquired.isCurrent()||closed){void audioContext.close().catch(()=>{});return;}const analyser=audioContext.createAnalyser();audioContext.createMediaStreamSource(acquired.stream).connect(analyser);const samples=new Uint8Array(analyser.fftSize);const tick=()=>{if(!context)return;analyser.getByteTimeDomainData(samples);const level=Math.min(100,Math.round(Math.sqrt(samples.reduce((sum,value)=>sum+((value-128)/128)**2,0)/samples.length)*300));meter.style.setProperty('--level',`${level}%`);meter.setAttribute('aria-valuenow',String(level));frame=requestAnimationFrame(tick);};tick();status.textContent='麦克风已连接，请说几句话，确认音量条有变化。';}),button('预览摄像头',async()=>{release();if(!navigator.mediaDevices?.getUserMedia)throw new Error('当前浏览器无法使用摄像头，请通过 HTTPS 或本机地址访问。');let acquired;try{acquired=await lease.acquire({video:true});}catch(error){throw new Error('无法访问摄像头，请检查浏览器授权。');}if(!acquired||closed)return;video.srcObject=acquired.stream;video.hidden=false;avatar.hidden=true;status.textContent='预览仅对自己可见，入会后摄像头仍保持关闭。';}));
  body.append(deviceActions,meter,status);
  footer.append(button('进入课堂 →',async()=>{release();const turn=revision;dialog.close();await joinLesson(lesson,{turn});},'button primary'));
}
async function joinLesson(lesson,{restore=false,turn=revision}={}){
  if(room||!valid(turn))return;
  let credentials;
  try{credentials=await api(`/live/lessons/${lesson.id}/join`,{method:'POST'});}
  catch(error){if(restore){forgetLiveLesson(lesson.id);notify(`课堂恢复失败：${error.message}`,'error');}throw error;}
  if(!valid(turn)){void api(`/live/lessons/${lesson.id}/leave`,{method:'POST'}).catch(()=>{});return;}
  rememberLiveLesson(lesson.id);clearTimeout(pageTimer);document.body.classList.add('live-immersive');
  room=new Classroom(root(),lesson,credentials,async()=>{forgetLiveLesson(lesson.id);room=null;document.body.classList.remove('live-immersive');await refreshLive();});
  try{await room.connect();}
  catch(error){room?.dispose({leave:true});room=null;forgetLiveLesson(lesson.id);document.body.classList.remove('live-immersive');if(restore)notify(`课堂恢复失败：${error.message}`,'error');await refreshLive();throw error;}
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
