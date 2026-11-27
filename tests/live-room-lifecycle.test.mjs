import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {SourceTextModule,SyntheticModule,createContext} from 'node:vm';

async function harness(request){
  const frameJobs=[];
  const notifications=[];
  const context=createContext({Date,JSON,Boolean,requestAnimationFrame:job=>(frameJobs.push(job),frameJobs.length),
    navigator:{mediaDevices:{getDisplayMedia(){}},userActivation:{isActive:true}}});
  const exports=(values)=>new SyntheticModule(Object.keys(values),function(){for(const [key,value]of Object.entries(values))this.setExport(key,value);},{context});
  const api=exports({api:request,state:{user:{id:1}}});
  const ui=exports(Object.fromEntries(['el','button','notify','confirmAction','modal','materialList','field'].map(key=>[key,key==='notify'?(message)=>notifications.push(message):()=>{}])));
  const model=exports({elapsed:()=>'',orderedMembers:x=>x,recordingText:x=>x});
  const video=exports({mountVideo:()=>({node:{classList:{toggle(){}}},dispose(){}})});
  const module=new SourceTextModule(await readFile(new URL('../app/static/live-room.js',import.meta.url),'utf8'),{context});
  await module.link(path=>path.includes('api.js')?api:path.includes('live-ui.js')?ui:path.includes('live-video.mjs')?video:model);await module.evaluate();
  const room=Object.create(module.namespace.Classroom.prototype);
  Object.assign(room,{lesson:{id:7},after:0,lastHeartbeat:0,closed:false,
    connection:{dataset:{state:'connected'}},notifications,permissions:{},like:{lastChild:{}},memberControl:{lastChild:{}},recordIndicator:{classList:{toggle(){}}},updateStageStatus(){},
    showBanner(){},hideBanner(){},checkShareHealth(){},renderMedia(){},renderMembers(){},appendMessages(){},syncControls(){},
    flushMedia(){frameJobs.splice(0).forEach(job=>job());}});
  return room;
}
const state=()=>({status:'live',members:[],messages:[],likes:0,recording_status:'idle'});

test('screen sharing bounds capture and encoding without capturing system audio by default',async()=>{
  let args;
  const room=await harness(async()=>state());room.permissions={can_share:true};
  room.credentials={screen_share:{width:1280,height:720,frame_rate:15,max_bitrate:1500000}};
  room.room={localParticipant:{isScreenShareEnabled:false,setScreenShareEnabled:async(...values)=>{args=values;}}};
  await room.toggleShare();
  assert.equal(args[0],true);assert.equal(args[1].audio,false);
  assert.equal(args[1].resolution.width,1280);assert.equal(args[1].resolution.frameRate,15);
  assert.equal(args[2].screenShareEncoding.maxBitrate,1500000);assert.equal(args[2].simulcast,false);
});

test('a stale SFU participant is reconnected before the user retries screen sharing',async()=>{
  const requests=[];let pickerCalls=0,reconnects=0;
  const room=await harness(async(path)=>{
    requests.push(path);
    if(path.endsWith('/members/1'))throw Object.assign(new Error('课堂音视频连接已中断，正在恢复；请等待“连接正常”后重新点击共享屏幕。'),{status:409});
    return state();
  });
  room.isHost=true;room.permissions={can_share:false};room.credentials={};
  room.pollOnce=async()=>{reconnects++;room.connection.dataset.state='connected';room.reconnectNeeded=false;};
  room.room={localParticipant:{isScreenShareEnabled:false,setScreenShareEnabled:async()=>{pickerCalls++;}}};

  await room.toggleShare();

  assert.equal(reconnects,1);assert.equal(pickerCalls,0);assert.equal(room.shareBusy,false);
  assert.match(room.notifications.at(-1),/再次点击.*共享屏幕/);
});

test('polling and repeated clicks cannot open concurrent screen pickers',async()=>{
  let calls=0;const pending=[];
  const room=await harness(async()=>state());room.permissions={can_share:true};room.credentials={};
  room.room={localParticipant:{isScreenShareEnabled:false,setScreenShareEnabled:()=>{calls++;return new Promise(done=>pending.push(done));}}};
  const first=room.toggleShare(),second=room.toggleShare();const opened=calls;
  pending.forEach(resolve=>resolve());await Promise.all([first,second]);
  assert.equal(opened,1);assert.equal(room.shareBusy,false);
});

test('screen permission denial gives recovery instructions instead of silently succeeding',async()=>{
  const room=await harness(async()=>state());room.permissions={can_share:true};room.credentials={};
  room.room={localParticipant:{isScreenShareEnabled:false,setScreenShareEnabled:async()=>{throw Object.assign(new Error('denied'),{name:'NotAllowedError'});}}};
  await assert.rejects(room.toggleShare(),/屏幕.*录制|屏幕.*音频/);assert.equal(room.shareBusy,false);
});

test('local screen capture is not recursively previewed in the classroom stage',async()=>{
  const room=await harness(async()=>state());let attached=0;
  const track={kind:'video',sid:'local-screen',attach(){attached++;return {classList:{toggle(){}}};}};
  const local={identity:'1',trackPublications:new Map([['screen',{track,source:'screen_share'}]])};
  room.room={localParticipant:local,remoteParticipants:new Map(),activeSpeakers:[]};
  room.SDK={Track:{Source:{ScreenShare:'screen_share',Camera:'camera'}}};
  room.audioNodes=new Map();room.mountedTracks=new Map();room.stageMedia={replaceChildren(){},append(){}};
  room.stageFallback={};room.stageTitle={};room.stageCaption={};room.stageName={};room.stageRecovery={};
  room.strip={children:[{dataset:{identity:'1'},lastElementChild:{},classList:{toggle(){}}}]};
  delete room.renderMedia;
  await assert.doesNotReject(async()=>room.renderMedia());
  assert.equal(attached,0);assert.equal(room.localScreen,true);assert.equal(room.stageMain,undefined);
});

test('media events render once after the SDK finishes removing a track',async()=>{
  const room=await harness(async()=>state());let trackPresent=true,renders=0;
  room.renderMedia=()=>{renders++;assert.equal(trackPresent,false);};
  room.scheduleMediaRender();room.scheduleMediaRender();
  assert.equal(renders,0);trackPresent=false;room.flushMedia();assert.equal(renders,1);
});

test('a queued media update does not render after leaving',async()=>{
  const room=await harness(async()=>state());let renders=0;
  room.renderMedia=()=>{renders++;};room.scheduleMediaRender();room.closed=true;
  room.flushMedia();assert.equal(renders,0);
});

test('a failed SFU recovery is retried even after admission has been refreshed',async()=>{
  let joins=0,connects=0,heartbeats=0;
  const room=await harness(async path=>path.endsWith('/join')?(joins++,{url:'wss://test',token:'temporary',can_speak:false,can_share:false}):state());
  room.presence=async()=>{if(heartbeats++===0)throw Object.assign(new Error('Expired presence'),{status:409});room.lastHeartbeat=Date.now();};
  room.room={disconnect:async()=>{},connect:async()=>{if(connects++===0)throw new Error('SFU unavailable');}};
  await assert.rejects(room.pollOnce(),/SFU unavailable/);assert.equal(room.reconnectNeeded,true);
  await room.pollOnce();assert.equal(joins,2);assert.equal(connects,2);assert.equal(room.reconnectNeeded,false);
  await room.pollOnce();assert.equal(joins,2);
});

test('overlapping state updates share one admission and connection recovery',async()=>{
  let resolve,joins=0,connects=0;
  const room=await harness(async path=>path.endsWith('/join')?(joins++,{url:'wss://test',token:'temporary'}):new Promise(done=>resolve=done));
  room.reconnectNeeded=true;room.presence=async()=>{};
  room.room={disconnect:async()=>{},connect:async()=>{connects++;}};
  const first=room.pollOnce(),second=room.pollOnce();assert.equal(first,second);resolve(state());await Promise.all([first,second]);assert.equal(joins,1);assert.equal(connects,1);
});

test('a late state response after leaving never reconnects the classroom',async()=>{
  let resolve,joins=0;
  const room=await harness(async path=>{if(path.endsWith('/join'))joins++;return new Promise(done=>resolve=done);});
  room.reconnectNeeded=true;const pending=room.pollOnce();room.closed=true;resolve(state());await pending;assert.equal(joins,0);
});

test('an expired heartbeat arriving after departure does not readmit the user',async()=>{
  let rejectHeartbeat,joins=0;
  const room=await harness(async path=>{if(path.endsWith('/join'))joins++;return state();});
  room.presence=()=>new Promise((resolve,reject)=>rejectHeartbeat=reject);
  const pending=room.pollOnce();await new Promise(resolve=>setImmediate(resolve));room.closed=true;
  rejectHeartbeat(Object.assign(new Error('Expired presence'),{status:409}));await pending;assert.equal(joins,0);
});

test('leaving during media disconnect prevents a new connection',async()=>{
  let release,connects=0;
  const room=await harness(async path=>path.endsWith('/join')?{url:'wss://test',token:'temporary'}:state());
  room.reconnectNeeded=true;room.room={disconnect:()=>new Promise(resolve=>release=resolve),connect:async()=>{connects++;}};
  const pending=room.pollOnce();await new Promise(resolve=>setImmediate(resolve));room.closed=true;release();await pending;assert.equal(connects,0);
});

test('admission completing after departure releases its late reservation',async()=>{
  let admit,leaves=0;
  const room=await harness(async path=>{if(path.endsWith('/join'))return new Promise(resolve=>admit=resolve);if(path.endsWith('/leave'))leaves++;return state();});
  room.reconnectNeeded=true;const pending=room.pollOnce();await new Promise(resolve=>setImmediate(resolve));room.closed=true;admit({url:'wss://test',token:'temporary'});await pending;assert.equal(leaves,1);
});

async function screenHealthRoom(){
  const room=await harness(async()=>state());delete room.checkShareHealth;room.credentials={};room.permissions={can_share:true};
  const calls=[];const track={mediaStreamTrack:{readyState:'live'},getSenderStats:async()=>[{framesSent:0}],stop(){calls.push('stop');}};
  room.SDK={Track:{Source:{ScreenShare:'screen_share'}}};
  const local={isScreenShareEnabled:true,trackPublications:new Map([['screen',{source:'screen_share',track}]]),
    async unpublishTrack(){calls.push('unpublish');},async publishTrack(value,options){calls.push('publish');assert.equal(value,track);assert.equal(options.source,'screen_share');}};
  room.room={localParticipant:local};room.shareHealth={track,since:Date.now()-31000,retried:false,failed:false};
  return {room,track,calls,local};
}

test('a screen publication with no outbound frames renegotiates once using the existing capture',async()=>{
  const {room,calls}=await screenHealthRoom();await room.checkShareHealth();
  assert.deepEqual(calls,['unpublish','publish']);assert.equal(room.shareHealth.retried,true);
  room.shareHealth.since=Date.now()-31000;await room.checkShareHealth();
  assert.deepEqual(calls,['unpublish','publish']);assert.equal(room.shareHealth.failed,true);
});

test('a screen that already sent frames is never republished merely because the slide is static',async()=>{
  const {room,track,calls}=await screenHealthRoom();track.getSenderStats=async()=>[{framesSent:1}];
  await room.checkShareHealth();assert.deepEqual(calls,[]);assert.equal(room.shareHealth.sent,true);
});

test('native stop during screen recovery never republishes an ended capture',async()=>{
  const {room,track,calls,local}=await screenHealthRoom();local.unpublishTrack=async()=>{calls.push('unpublish');track.mediaStreamTrack.readyState='ended';};
  await room.checkShareHealth();assert.equal(calls.includes('publish'),false);
});

test('leaving during a screen stats request prevents renegotiation',async()=>{
  const {room,track,calls}=await screenHealthRoom();let release;track.getSenderStats=()=>new Promise(resolve=>release=resolve);
  const pending=room.checkShareHealth();room.closed=true;release([{framesSent:0}]);await pending;assert.deepEqual(calls,[]);
});
