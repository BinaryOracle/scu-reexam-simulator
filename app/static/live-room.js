/** LiveKit classroom lifecycle: stable media panes, moderated controls and recoverable interaction. */
import {api,state} from './api.js?v=20261122-session-guard-v1';
import {el,button,notify,confirmAction,modal,materialList,field} from './live-ui.js?v=1';
import {elapsed,orderedMembers,recordingText} from './live-model.mjs?v=1';
import {mountVideo} from './live-video.mjs?v=20261116-frames-v1';
const paths={mic:'M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3ZM5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8',camera:'M16 8l6-4v16l-6-4M2 5h14v14H2z',screen:'M3 3h18v14H3zM8 22h8m-4-5v5M8 9l4-4 4 4m-4-4v9',hand:'M8 12V5a2 2 0 0 1 4 0v7-8a2 2 0 0 1 4 0v8-5a2 2 0 0 1 4 0v9c0 5-3 7-7 7-3 0-5-2-7-5L3 12a2 2 0 0 1 3-2l2 2z',chat:'M3 3h18v14H9l-6 4V3zM7 7h10M7 11h7',people:'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m20 0v-2a4 4 0 0 0-3-4M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8m8 0a4 4 0 0 1 0 8',files:'M4 3h6l2 3h8v15H4zM8 11h8M8 15h6',like:'M7 10l5-8c2 0 3 2 2 5l-1 3h7l-2 12H7V10ZM2 10h5v12H2z',record:'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20ZM8 8h8v8H8z',exit:'M9 5H3v14h6m6-14 7 7-7 7m-8-7h15',expand:'M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5',settings:'M3 6h18M3 12h18M3 18h18M8 3v6m8 0v6m-8 0v6'};
function icon(name){const box=el('span','','live-control-icon');box.setAttribute('aria-hidden','true');box.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="${paths[name]}"/></svg>`;return box;}
function control(name,label,action,extra=''){const node=button('',action,`live-control ${extra}`);node.append(icon(name),el('span',label));node.setAttribute('aria-label',label);node.title=label;return node;}
let sdkPromise;
function loadSDK(){if(window.LivekitClient)return Promise.resolve(window.LivekitClient);if(!sdkPromise)sdkPromise=new Promise((resolve,reject)=>{const script=el('script');script.src='/static/vendor/livekit-client-2.24.1.umd.js';script.onload=()=>resolve(window.LivekitClient);script.onerror=()=>{sdkPromise=null;script.remove();reject(new Error('课堂组件加载失败，请刷新重试。'));};document.head.append(script);});return sdkPromise;}
export class Classroom {
  constructor(root,lesson,credentials,onExit){
    this.root=root;this.lesson=lesson;this.credentials=credentials;this.onExit=onExit;this.closed=false;this.isHost=credentials.is_host;this.permissions={can_speak:credentials.can_speak,can_share:credentials.can_share};this.messages=new Set();this.after=0;this.members=[];this.lastState=null;this.mediaNodes=new Map();this.mountedTracks=new Map();this.audioNodes=new Map();this.created=Date.now();this.lastHeartbeat=0;this.tab='chat';this.panelOpen=true;this.hand=false;this.requestShare=false;this.build();
  }
  build(){
    this.shell=el('section','','live-classroom');this.root.replaceChildren(this.shell);
    const header=el('header','','live-room-header');const title=el('div','','live-room-title');title.append(el('span','知序 · 直播课堂','live-room-brand'),el('h1',this.lesson.title));
    const meta=el('div','','live-room-meta');this.connection=el('span','正在连接…','live-network');this.connection.setAttribute('role','status');this.clock=el('time','00:00');this.recordIndicator=el('span','未录制','live-record-indicator');
    this.fullscreen=button('⛶',async()=>{if(document.fullscreenElement)await document.exitFullscreen();else await this.shell.requestFullscreen();},'live-header-button');this.fullscreen.setAttribute('aria-label','切换全屏');
    meta.append(this.connection,this.recordIndicator,this.clock,this.fullscreen);header.append(title,meta);
    this.body=el('div','','live-room-body');this.media=el('div','','live-room-media');this.stage=el('div','','live-main-stage');this.stageMedia=el('div','','live-stage-media');
    this.stageFallback=el('div','','live-stage-fallback');const mark=el('div',this.lesson.course_title?.slice(0,1)||'知','live-stage-avatar');this.stageTitle=el('h2',this.lesson.title);this.stageCaption=el('p','等待主持人共享屏幕，或开启摄像头。');this.stageRecovery=button('重新连接画面',()=>this.recoverStage(),'button live-stage-recovery');this.stageRecovery.hidden=true;this.stageFallback.setAttribute('role','status');this.stageFallback.append(mark,this.stageTitle,this.stageCaption,this.stageRecovery);
    this.stageName=el('span','','live-stage-name');this.stage.append(this.stageFallback,this.stageMedia,this.stageName);
    this.strip=el('div','','live-participant-strip');this.strip.setAttribute('aria-label','参与者画面');this.media.append(this.stage,this.strip);
    this.audioSink=el('div','','live-audio-sink');this.audioSink.hidden=true;this.media.append(this.audioSink);
    this.sidebar=el('aside','','live-room-sidebar');this.sidebar.setAttribute('aria-label','课堂互动');
    const tabs=el('div','','live-panel-tabs');tabs.setAttribute('role','tablist');this.tabs={};
    for(const [key,label]of [['chat','评论'],['members','成员'],['files','资料']]){const tab=button(label,()=>this.openPanel(key),'live-panel-tab');tab.setAttribute('role','tab');tab.id=`live-tab-${key}`;tab.setAttribute('aria-controls',`live-pane-${key}`);tabs.append(tab);this.tabs[key]=tab;}
    const close=button('×',()=>this.togglePanel(false),'live-panel-close');close.setAttribute('aria-label','收起互动面板');tabs.append(close);
    this.panes={};for(const key of ['chat','members','files']){const pane=el('section','',`live-room-pane live-pane-${key}`);pane.id=`live-pane-${key}`;pane.setAttribute('role','tabpanel');pane.setAttribute('aria-labelledby',`live-tab-${key}`);this.panes[key]=pane;}
    this.chatList=el('div','','live-chat-list');this.chatList.setAttribute('role','log');this.chatList.setAttribute('aria-label','课堂评论');this.chatList.append(el('p','欢迎来到课堂。把问题写下来，一起交流。','live-chat-welcome'));
    const chatForm=el('form','','live-chat-form');this.chatInput=el('textarea');this.chatInput.rows=2;this.chatInput.placeholder='说点什么，或留下你的问题…';this.chatInput.maxLength=2000;this.chatInput.setAttribute('aria-label','评论内容');this.send=el('button','发送','button primary');this.send.type='submit';const hint=el('small','Enter 发送 · Shift + Enter 换行');chatForm.append(this.chatInput,hint,this.send);
    const sendMessage=async()=>{const content=this.chatInput.value.trim();if(!content)return;this.send.disabled=true;try{await api(`/live/lessons/${this.lesson.id}/messages`,{method:'POST',body:JSON.stringify({content})});if(this.closed)return;this.chatInput.value='';await this.pollOnce();}catch(error){if(!this.closed)notify(error.message,'error');}finally{this.send.disabled=false;}};
    chatForm.addEventListener('submit',event=>{event.preventDefault();void sendMessage();});this.chatInput.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!this.send.disabled)void sendMessage();}});
    this.panes.chat.append(this.chatList,chatForm);this.memberList=el('div','','live-member-list');this.panes.members.append(el('p','举手后由主持人邀请发言，共享屏幕需单独授权。','live-helper'),this.memberList);
    this.fileList=el('div');this.panes.files.append(el('p','资料保存在本次课中，离开后也可以下载。','live-helper'),this.fileList);
    this.sidebar.append(tabs,...Object.values(this.panes));this.body.append(this.media,this.sidebar);
    this.banner=el('div','','live-room-banner');this.banner.hidden=true;this.banner.setAttribute('role','status');
    const footer=el('footer','','live-room-footer');const devices=el('div','','live-control-group');this.mic=control('mic','开启麦克风',()=>this.toggleMic());this.cam=control('camera','开启摄像头',()=>this.toggleCamera());const settings=control('settings','设备',()=>this.deviceSettings());devices.append(this.mic,this.cam,settings);
    const interaction=el('div','','live-control-group');this.share=control('screen','共享屏幕',()=>this.toggleShare());this.raise=control('hand','举手',()=>this.raiseHand());interaction.append(this.share);if(!this.isHost)interaction.append(this.raise);
    const panels=el('div','','live-control-group');this.comment=control('chat','评论',()=>this.panelOpen&&this.tab==='chat'?this.togglePanel(false):this.openPanel('chat'));this.memberControl=control('people','成员',()=>this.openPanel('members'));this.fileControl=control('files','资料',async()=>{this.openPanel('files');await this.refreshMaterials();});this.like=control('like','点赞',async()=>{const result=await api(`/live/lessons/${this.lesson.id}/like`,{method:'POST'});this.like.lastChild.textContent=`点赞 ${result.likes}`;this.like.classList.remove('live-liked');requestAnimationFrame(()=>this.like.classList.add('live-liked'));});panels.append(this.comment,this.memberControl,this.fileControl,this.like);
    const ending=el('div','','live-control-group live-end-controls');if(this.isHost){this.record=control('record','开始录制',()=>this.recording());ending.append(this.record);}ending.append(control('exit','离开',()=>this.leave(),'live-leave'));if(this.isHost)ending.append(button('结束课堂',()=>this.end(),'button live-end-button'));
    footer.append(devices,interaction,panels,ending);this.shell.append(header,this.banner,this.body,footer);this.openPanel('chat');if(window.matchMedia('(max-width:800px)').matches)this.togglePanel(false);
    tabs.addEventListener('keydown',event=>{const keys=Object.keys(this.tabs);const current=keys.findIndex(key=>this.tabs[key]===event.target);if(current<0)return;let next;if(event.key==='ArrowRight')next=(current+1)%keys.length;else if(event.key==='ArrowLeft')next=(current+keys.length-1)%keys.length;else if(event.key==='Home')next=0;else if(event.key==='End')next=keys.length-1;else return;event.preventDefault();this.openPanel(keys[next]);this.tabs[keys[next]].focus();});
    this.clockTimer=setInterval(()=>{this.clock.textContent=elapsed((Date.now()-this.created)/1000);},1000);
    this.beforeUnload=event=>{if(!this.closed){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',this.beforeUnload);this.pageHide=()=>this.dispose();window.addEventListener('pagehide',this.pageHide);
  }
  async connect(){
    const SDK=await loadSDK();if(this.closed)return;this.SDK=SDK;
    this.room=new SDK.Room({adaptiveStream:true,dynacast:true,videoCaptureDefaults:{resolution:SDK.VideoPresets.h720.resolution}});
    const event=SDK.RoomEvent;
    for(const name of [event.TrackSubscribed,event.TrackUnsubscribed,event.TrackPublished,event.TrackUnpublished,event.LocalTrackPublished,event.LocalTrackUnpublished,event.ParticipantConnected,event.ParticipantDisconnected,event.TrackMuted,event.TrackUnmuted,event.ActiveSpeakersChanged])this.room.on(name,()=>this.scheduleMediaRender());
    this.room.on(event.VideoPlaybackStatusChanged,playing=>{if(!playing){this.playbackState='blocked';this.updateStageStatus();}});
    this.room.on(event.Reconnecting,()=>{this.connection.textContent='正在重新连接…';this.connection.dataset.state='reconnecting';this.syncControls();this.showBanner('连接暂时中断，正在尝试恢复，请稍候。');});
    this.room.on(event.Reconnected,()=>{this.connection.textContent='连接正常';this.connection.dataset.state='connected';this.syncControls();this.hideBanner();void this.pollOnce().catch(error=>this.showBanner(error.message));});
    this.room.on(event.Disconnected,()=>{if(!this.closed){this.reconnectNeeded=true;this.connection.textContent='已断开';this.connection.dataset.state='disconnected';this.syncControls();this.showBanner('音视频连接已断开，正在尝试重新入会。');}});
    this.room.on(event.MediaDevicesError,()=>this.showBanner('无法使用设备，请检查浏览器授权和系统设备设置。'));
    this.room.on(event.AudioPlaybackStatusChanged,()=>{if(!this.room.canPlaybackAudio){this.showBanner('浏览器暂停了课堂声音。');const resume=button('点击开启声音',async()=>{await this.room.startAudio();this.hideBanner();},'button secondary live-small');this.banner.append(resume);}});
    await this.room.connect(this.credentials.url,this.credentials.token);if(this.closed){await this.room.disconnect();return;}
    this.connection.textContent='连接正常';this.connection.dataset.state='connected';this.renderMedia();this.syncControls();await this.pollOnce();this.schedulePoll();
    await this.refreshMaterials();
  }
  showBanner(message){this.banner.replaceChildren(el('span',message));this.banner.hidden=false;}
  hideBanner(){this.banner.hidden=true;this.banner.replaceChildren();}
  openPanel(key){this.tab=key;this.togglePanel(true);for(const name of Object.keys(this.panes)){this.panes[name].hidden=name!==key;this.tabs[name].setAttribute('aria-selected',String(name===key));this.tabs[name].tabIndex=name===key?0:-1;}if(key==='chat'){this.chatList.scrollTop=this.chatList.scrollHeight;this.tabs.chat.textContent='评论';}}
  togglePanel(open){this.panelOpen=open;this.sidebar.hidden=!open;this.body.classList.toggle('panel-hidden',!open);this.comment?.setAttribute('aria-pressed',String(open&&this.tab==='chat'));}
  async refreshMaterials(){const detail=await api(`/live/lessons/${this.lesson.id}`);if(this.closed)return;materialList(this.fileList,detail,{canManage:this.isHost,refresh:()=>this.refreshMaterials()});}
  syncControls(){if(!this.room)return;const local=this.room.localParticipant;const mic=Boolean(local.isMicrophoneEnabled),cam=Boolean(local.isCameraEnabled),sharing=Boolean(local.isScreenShareEnabled);
    this.mic.disabled=!this.permissions.can_speak;this.cam.disabled=!this.permissions.can_speak;this.share.disabled=Boolean(this.shareBusy)||this.connection.dataset.state!=='connected';this.mic.lastChild.textContent=mic?'关闭麦克风':'开启麦克风';this.cam.lastChild.textContent=cam?'关闭摄像头':'开启摄像头';this.share.lastChild.textContent=this.shareBusy?'正在处理共享…':sharing?'停止共享':(this.isHost||this.permissions.can_share)?'共享屏幕':this.requestShare?'取消共享申请':'申请共享';
    for(const [node,value]of [[this.mic,mic],[this.cam,cam],[this.share,sharing]]){node.setAttribute('aria-pressed',String(value));node.setAttribute('aria-label',node.lastChild.textContent);node.classList.toggle('is-on',value);}
    this.mic.title=this.permissions.can_speak?'开启或关闭麦克风':'请先举手，主持人授权后可以开启麦克风';this.cam.title=this.permissions.can_speak?'开启或关闭摄像头':'主持人授权发言后可以开启摄像头';
    if(this.raise){this.raise.classList.toggle('is-on',this.hand);this.raise.lastChild.textContent=this.hand?'取消举手':'举手';this.raise.setAttribute('aria-pressed',String(this.hand));}
  }
  async toggleMic(){try{await this.room.localParticipant.setMicrophoneEnabled(!this.room.localParticipant.isMicrophoneEnabled);this.syncControls();}catch(error){throw new Error('麦克风未能开启，请检查设备和浏览器授权。');}}
  async toggleCamera(){try{await this.room.localParticipant.setCameraEnabled(!this.room.localParticipant.isCameraEnabled);this.syncControls();}catch(error){throw new Error('摄像头未能开启，请检查设备和浏览器授权。');}}
  async toggleShare(){
    if(this.closed||this.shareBusy)return;
    if(this.connection.dataset.state!=='connected'){
      this.reconnectNeeded=true;
      await this.pollOnce();
      if(!this.closed)notify('课堂连接已恢复，请再次点击“共享屏幕”选择窗口。');
      return;
    }
    this.shareBusy=true;this.syncControls();
    try{
    const local=this.room.localParticipant;
    if(local.isScreenShareEnabled){await local.setScreenShareEnabled(false);return;}
    if(!navigator.mediaDevices?.getDisplayMedia)throw new Error('当前浏览器不支持屏幕共享，请使用最新版 Chrome 或 Edge，通过本机地址或 HTTPS 打开课堂。');
    if(this.isHost&&!this.permissions.can_share){
      try{await api(`/live/lessons/${this.lesson.id}/members/${state.user.id}`,{method:'PATCH',body:JSON.stringify({can_share:true})});}
      catch(error){if(error.status!==409||!error.message.includes('课堂音视频连接已中断'))throw error;this.reconnectNeeded=true;await this.pollOnce();if(!this.closed)notify('课堂连接已恢复，请再次点击“共享屏幕”选择窗口。');return;}
      await this.pollOnce();
      if(navigator.userActivation&&!navigator.userActivation.isActive){notify('共享已就绪，请再次点击“共享屏幕”选择窗口。');return;}
    }
    if(!this.permissions.can_share){this.requestShare=!this.requestShare;try{await this.presence();}catch(error){this.requestShare=!this.requestShare;throw error;}this.syncControls();notify(this.requestShare?'已向主持人申请共享屏幕':'已取消共享申请');return;}
    if(this.closed)return;
    const profile=this.credentials.screen_share||{width:1280,height:720,frame_rate:15,max_bitrate:1500000};
    try{
      await local.setScreenShareEnabled(true,{audio:false,systemAudio:'exclude',selfBrowserSurface:'exclude',surfaceSwitching:'exclude',contentHint:'detail',resolution:{width:profile.width,height:profile.height,frameRate:profile.frame_rate}},
        {simulcast:false,backupCodec:false,screenShareEncoding:{maxBitrate:profile.max_bitrate,maxFramerate:profile.frame_rate}});
      if(this.closed){await local.setScreenShareEnabled(false);return;}
      this.shareHealth=null;this.renderMedia();
    }catch(error){
      if(error.name==='AbortError'){notify('已取消共享屏幕');return;}
      if(error.name==='NotAllowedError'||error.name==='NotReadableError')throw new Error('未开始共享：可能已取消选择，或 Chrome 没有屏幕录制权限。请在 macOS「系统设置 → 隐私与安全性 → 屏幕与系统音频录制」允许 Chrome，按系统提示重开浏览器，再选择课件窗口重试。');
      throw new Error('共享未能开始，请检查课堂连接并重新选择窗口；建议共享课件窗口，避免共享整个桌面。');
    }
    }finally{this.shareBusy=false;this.syncControls();}
  }
  async raiseHand(){this.hand=!this.hand;try{await this.presence();}catch(error){this.hand=!this.hand;throw error;}this.syncControls();}
  async presence(){await api(`/live/lessons/${this.lesson.id}/presence`,{method:'POST',body:JSON.stringify({hand:this.hand,request_share:this.requestShare})});this.lastHeartbeat=Date.now();}
  schedulePoll(){if(this.closed)return;this.pollTimer=setTimeout(async()=>{try{await this.pollOnce();}catch(error){if(!this.closed){if([401,403,404].includes(error.status)){notify('课堂访问已失效，已停止音视频连接。','error');await this.finishExit();}else this.showBanner(`互动暂未同步：${error.message}。正在重试。`);}}finally{this.schedulePoll();}},2500);}
  pollOnce(){if(!this.polling)this.polling=this.pollState().finally(()=>{this.polling=null;});return this.polling;}
  async pollState(){
    const result=await api(`/live/lessons/${this.lesson.id}/state?after=${this.after}`);if(this.closed)return;
    if(result.status==='ended'){notify('本次课堂已结束，资料与回放将保存在课次中。');await this.finishExit();return;}
    if(!this.reconnectNeeded&&Date.now()-this.lastHeartbeat>10000){try{await this.presence();}catch(error){if(error.status!==409)throw error;this.reconnectNeeded=true;}}
    if(this.closed)return;
    if(this.reconnectNeeded){
      this.showBanner('正在恢复课堂连接…');const credentials=await api(`/live/lessons/${this.lesson.id}/join`,{method:'POST'});if(this.closed){await api(`/live/lessons/${this.lesson.id}/leave`,{method:'POST'});return;}
      await this.room.disconnect();if(this.closed)return;await this.room.connect(credentials.url,credentials.token);if(this.closed){await this.room.disconnect();return;}
      this.permissions=credentials;await this.presence();this.reconnectNeeded=false;this.connection.textContent='连接正常';this.connection.dataset.state='connected';this.hideBanner();this.syncControls();this.renderMedia();return;
    }if(this.closed)return;
    const self=result.members.find(member=>member.user_id===state.user.id);if(self){const oldSpeak=this.permissions.can_speak,oldShare=this.permissions.can_share;this.permissions=self;this.hand=Boolean(self.hand);this.requestShare=Boolean(self.request_share);
      if(!self.can_speak&&oldSpeak){await this.room.localParticipant.setMicrophoneEnabled(false);await this.room.localParticipant.setCameraEnabled(false);}
      if(!self.can_share&&oldShare)await this.room.localParticipant.setScreenShareEnabled(false);
      this.chatInput.disabled=Boolean(self.muted);this.chatInput.placeholder=self.muted?'当前已被禁言':'说点什么，或留下你的问题…';this.send.disabled=Boolean(self.muted);
    }
    this.members=result.members;this.renderMembers();this.appendMessages(result.messages||[]);this.like.lastChild.textContent=`点赞 ${result.likes||0}`;this.memberControl.lastChild.textContent=`成员 ${result.members.length}`;
    this.recordingStatus=result.recording_status;const recording=['starting','recording','stopping','processing'].includes(result.recording_status);this.recordIndicator.textContent=recordingText(result.recording_status);this.recordIndicator.classList.toggle('active',recording);
    if(this.record){this.record.lastChild.textContent=result.recording_status==='unknown'?'核对录制状态':result.recording_status==='recording'?'停止录制':'开始录制';this.record.setAttribute('aria-label',this.record.lastChild.textContent);this.record.title=this.record.lastChild.textContent;this.record.disabled=['starting','stopping','processing'].includes(result.recording_status);this.record.classList.toggle('is-recording',result.recording_status==='recording');}
    this.lastState=result;this.syncControls();void this.checkShareHealth();
  }
  appendMessages(items){
    const follow=this.chatList.scrollHeight-this.chatList.scrollTop-this.chatList.clientHeight<90;let added=0;
    for(const item of items){this.after=Math.max(this.after,item.id);if(this.messages.has(item.id))continue;this.messages.add(item.id);added++;
      const row=el('article','',`live-message ${item.user_id===state.user.id?'own':''}`);const meta=el('div','','live-message-meta');meta.append(el('strong',item.username),el('time',new Date(item.created*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})));row.append(meta,el('p',item.content));this.chatList.append(row);
    }
    if(follow)this.chatList.scrollTop=this.chatList.scrollHeight;if(added&&(!this.panelOpen||this.tab!=='chat'))this.tabs.chat.textContent='评论 · 新';
  }
  renderMembers(){
    // Only rebuild member controls when permissions or presence change, preserving focus between polls.
    const signature=JSON.stringify(this.members);if(signature===this.memberSignature)return;this.memberSignature=signature;this.memberList.replaceChildren();
    for(const member of orderedMembers(this.members)){const row=el('div','','live-member-row');const avatar=el('span',member.username.slice(0,1).toUpperCase(),'live-member-avatar');const info=el('div','','live-member-info');info.append(el('strong',`${member.username}${member.user_id===state.user.id?'（我）':''}`),el('small',member.is_host?'主持人':member.hand?'已举手':member.request_share?'申请共享':member.can_speak?'可发言':'正在听课'));row.append(avatar,info);
      if(this.isHost&&!member.is_host){const actions=el('div','','live-member-actions');
        const grant=(values)=>async()=>{await api(`/live/lessons/${this.lesson.id}/members/${member.user_id}`,{method:'PATCH',body:JSON.stringify(values)});await this.pollOnce();};
        actions.append(button(member.can_speak?'结束发言':'允许发言',grant({can_speak:!member.can_speak}),'button secondary live-small'),button(member.can_share?'收回共享':'允许共享',grant({can_share:!member.can_share}),'button secondary live-small'),button(member.muted?'解除禁言':'禁言',grant({muted:!member.muted}),'text-button live-small'));row.append(actions);
      }this.memberList.append(row);
    }
  }
  scheduleMediaRender(){
    if(this.closed||this.mediaFrame)return;
    // SDK track events may fire before their publications are removed.
    this.mediaFrame=requestAnimationFrame(()=>{this.mediaFrame=null;if(!this.closed)this.renderMedia();});
  }
  renderMedia(){
    if(!this.room||this.closed)return;const participants=[this.room.localParticipant,...this.room.remoteParticipants.values()];const videos=[],audios=[];
    for(const person of participants){for(const pub of person.trackPublications.values()){const track=pub.track;if(!track||pub.isMuted||track.mediaStreamTrack?.readyState==='ended')continue;const item={track,person,pub};if(track.kind==='video')videos.push(item);else if(person!==this.room.localParticipant)audios.push(item);}}
    const audioIds=new Set(audios.map(x=>x.track.sid));for(const [id,node]of this.audioNodes){if(!audioIds.has(id)){this.mountedTracks.get(id)?.detach(node);node.remove();this.audioNodes.delete(id);this.mountedTracks.delete(id);}}
    for(const item of audios){if(!this.audioNodes.has(item.track.sid)){const node=item.track.attach();this.audioSink.append(node);this.audioNodes.set(item.track.sid,node);this.mountedTracks.set(item.track.sid,item.track);}}
    const source=this.SDK.Track.Source;const localScreen=videos.some(item=>item.pub.source===source.ScreenShare&&item.person===this.room.localParticipant);
    // The sender does not decode its own desktop, avoiding a recursive classroom preview.
    const screen=videos.find(item=>item.pub.source===source.ScreenShare&&item.person!==this.room.localParticipant);
    const active=this.room.activeSpeakers[0];const main=screen||videos.find(item=>item.pub.source===source.Camera&&item.person===active)||videos.find(item=>item.person!==this.room.localParticipant&&item.pub.source===source.Camera)||videos.find(item=>item.pub.source===source.Camera);
    const stageKey=main?.track.sid||'';
    this.stageMain=main;this.localScreen=localScreen;this.stageScreen=screen;
    if(stageKey!==this.stageKey||main?.track!==this.stageTrack){this.stagePlayback?.dispose();this.stagePlayback=null;this.stageMedia.replaceChildren();this.stageKey=stageKey;this.stageTrack=main?.track;this.playbackState='connecting';if(main){this.stagePlayback=mountVideo(main.track,this.stageMedia,{onState:value=>{this.playbackState=value;this.updateStageStatus();}});this.stageNode=this.stagePlayback.node;this.stageNode.classList.toggle('camera',!screen);}}
    this.stageName.hidden=!main;this.stageName.textContent=main?`${main.person.name||main.person.identity}${screen?' · 正在共享屏幕':''}`:'';
    this.updateStageStatus();
    const identities=new Set(participants.map(person=>person.identity));for(const child of [...this.strip.children])if(!identities.has(child.dataset.identity)){child._track?.detach(child.querySelector('video'));child.remove();}
    for(const person of participants){let tile=[...this.strip.children].find(child=>child.dataset.identity===person.identity);if(!tile){tile=el('div','','live-video-tile');tile.dataset.identity=person.identity;tile.append(el('span',(person.name||person.identity).slice(0,1).toUpperCase(),'live-tile-avatar'),el('span','','live-tile-name'));this.strip.append(tile);}
      tile.lastElementChild.textContent=`${person.name||person.identity}${person===this.room.localParticipant?'（我）':''}${person.isMicrophoneEnabled?'':' · 静音'}`;
      const camera=videos.find(item=>item.person===person&&item.pub.source===source.Camera)?.track;
      if(tile._track!==camera){tile._track?.detach(tile.querySelector('video'));tile.querySelector('video')?.remove();tile._track=camera;if(camera){const video=camera.attach();video.muted=true;video.playsInline=true;tile.insertBefore(video,tile.firstChild);}}
      tile.classList.toggle('speaking',this.room.activeSpeakers.includes(person));
    }
    this.syncControls();
  }
  updateStageStatus(){
    const main=this.stageMain,status=this.playbackState;
    this.stageFallback.hidden=Boolean(main&&status==='playing');
    this.stageFallback.classList.toggle('live-stage-recovering',Boolean(main&&status!=='playing'));
    this.stageRecovery.hidden=!main||!['blocked','unavailable'].includes(status);
    if(main){
      this.stageTitle.textContent=status==='blocked'?'点击播放课堂画面':status==='unavailable'?'暂未收到课堂画面':'正在连接课堂画面';
      this.stageCaption.textContent=status==='blocked'?'浏览器暂停了视频播放，点击下方按钮继续观看。':status==='unavailable'?'共享已发起，但画面尚未到达。可重新连接；若仍无画面，请共享者停止并重新选择课件标签页。':'正在等待视频画面，请稍候。';
      this.stageRecovery.textContent=status==='blocked'?'播放画面':'重新连接画面';
    }else{
      const failed=this.localScreen&&this.shareHealth?.failed;
      this.stageTitle.textContent=failed?'共享画面未能发出':this.localScreen?'正在共享屏幕':this.lesson.title;
      this.stageCaption.textContent=failed?'已尝试恢复发送。请停止共享并重新选择课件标签页；若仍失败，请检查 Chrome 的屏幕录制权限。':this.localScreen?'已开启屏幕采集，请切换到课件窗口继续讲解。结束时点击下方“停止共享”。':'等待主持人共享屏幕，或开启摄像头。';
    }
  }
  async recoverStage(){
    if(this.closed||this.stageRecovering)return;this.stageRecovering=true;this.stageRecovery.disabled=true;
    try{
      if(this.playbackState==='blocked')await this.stagePlayback?.play();
      else{this.reconnectNeeded=true;await this.pollOnce();}
    }finally{this.stageRecovering=false;this.stageRecovery.disabled=false;}
  }
  async checkShareHealth(){
    if(this.closed||this.shareHealthBusy||this.shareBusy||!this.room?.localParticipant)return;
    const local=this.room.localParticipant,source=this.SDK.Track.Source.ScreenShare;
    const track=[...local.trackPublications.values()].find(pub=>pub.source===source)?.track;
    if(!track){this.shareHealth=null;return;}
    if(this.shareHealth?.track!==track)this.shareHealth={track,since:Date.now(),retried:false,failed:false};
    const health=this.shareHealth;if(health.failed||health.sent||Date.now()-health.since<30000||!track.getSenderStats)return;
    this.shareHealthBusy=true;
    try{
      const stats=await track.getSenderStats();if(this.closed||this.shareHealth!==health||this.shareBusy||!local.isScreenShareEnabled)return;
      if(stats.some(item=>item.framesSent>0)){health.sent=true;return;}
      // A published track can exist before the SFU receives any video packets.
      if(!health.retried){
        health.retried=true;health.since=Date.now();
        console.warn('[classroom-share] no outbound frames; renegotiating screen track');
        const profile=this.credentials.screen_share||{frame_rate:15,max_bitrate:1500000};
        await local.unpublishTrack(track,false);
      if(this.closed||!this.permissions.can_share||track.mediaStreamTrack?.readyState==='ended'){track.stop();return;}
        await local.publishTrack(track,{source,simulcast:false,backupCodec:false,screenShareEncoding:{maxBitrate:profile.max_bitrate,maxFramerate:profile.frame_rate}});
        if(this.closed){await local.unpublishTrack(track,true);return;}
      }else{health.failed=true;console.warn('[classroom-share] screen still has no outbound frames after recovery');}
      this.renderMedia();
    }catch(error){
      if(!this.closed&&this.shareHealth===health){health.failed=true;this.showBanner('共享画面发送未恢复，请停止共享并重新选择课件标签页。');}
    }finally{this.shareHealthBusy=false;}
  }
  async recording(){const action=this.recordingStatus==='unknown'?'reconcile':this.recordingStatus==='recording'?'stop':'start';if(action==='stop'&&!await confirmAction('停止后，本段录播会进入处理状态。',{title:'停止课堂录制？',confirmText:'停止录制'}))return;await api(`/live/lessons/${this.lesson.id}/recording`,{method:'POST',body:JSON.stringify({action})});await this.pollOnce();}
  async deviceSettings(){
    const {dialog,body,footer}=modal('音视频设备','请先授权设备，再选择要使用的麦克风、摄像头或扬声器。');const devices=await navigator.mediaDevices.enumerateDevices();if(!dialog.isConnected)return;
    const controls=[];for(const [kind,label]of [['audioinput','麦克风'],['videoinput','摄像头'],['audiooutput','扬声器']]){const select=el('select');for(const [index,device]of devices.filter(item=>item.kind===kind).entries())select.append(Object.assign(el('option',device.label||`${label} ${index+1}`),{value:device.deviceId}));if(!select.options.length)select.append(Object.assign(el('option','尚未授权或没有可用设备'),{value:''}));select.value=this.room.getActiveDevice(kind)||select.value;body.append(field(label,select));controls.push([kind,select]);}
    footer.append(button('应用设置',async()=>{for(const [kind,select]of controls)if(select.value)await this.room.switchActiveDevice(kind,select.value);dialog.close();},'button primary'));
  }
  async leave(){if(!await confirmAction('离开会停止你的麦克风、摄像头和共享，课堂仍会继续。',{title:'离开当前课堂？',confirmText:'离开课堂'}))return;await this.finishExit();}
  async end(){if(!await confirmAction('所有学员将离开课堂；录制完成处理后可在课次中查看。',{title:'结束本次课堂？',danger:true,confirmText:'结束课堂'}))return;await api(`/live/lessons/${this.lesson.id}/end`,{method:'POST'});await this.finishExit();}
  async finishExit(){if(this.closed)return;this.dispose();await this.onExit();}
  dispose(){
    if(this.closed)return;this.closed=true;clearTimeout(this.pollTimer);clearInterval(this.clockTimer);cancelAnimationFrame(this.mediaFrame);window.removeEventListener('beforeunload',this.beforeUnload);window.removeEventListener('pagehide',this.pageHide);
    this.room?.disconnect(true);for(const track of this.mountedTracks.values())track.detach();this.audioNodes.clear();this.stagePlayback?.dispose();for(const tile of this.strip.children)tile._track?.detach();
    if(document.fullscreenElement===this.shell)void document.exitFullscreen().catch(()=>{});
    // Keep a short authenticated leave request alive during document navigation.
    if(state.token)void fetch(`/api/live/lessons/${this.lesson.id}/leave`,{method:'POST',headers:{Authorization:`Bearer ${state.token}`},keepalive:true}).catch(()=>{});
    document.querySelectorAll('dialog[data-live-owned]').forEach(dialog=>dialog.close());
  }
}
