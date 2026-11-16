import test from 'node:test';
import assert from 'node:assert/strict';
import {mountVideo} from '../app/static/live-video.mjs';

function fixture(){
  const jobs=new Map(),listeners=new Map();let next=0;const states=[];
  const node={paused:true,readyState:0,videoWidth:0,isConnected:false,frames:new Map(),frameId:0,
    addEventListener(name,fn){listeners.set(name,fn);},removeEventListener(name){listeners.delete(name);},
    requestVideoFrameCallback(fn){this.frames.set(++this.frameId,fn);return this.frameId;},
    cancelVideoFrameCallback(id){this.frames.delete(id);},
    async play(){this.paused=false;},remove(){this.isConnected=false;}};
  const target={append(child){child.isConnected=true;}};
  const track={mediaStreamTrack:{readyState:'live',muted:false},attach(video){assert.equal(video.isConnected,true);assert.equal(video.muted,true);return video;},detach(){}};
  return {node,target,track,states,jobs,fire(name){listeners.get(name)?.();},
    options:{createVideo:()=>node,onState:s=>states.push(s),setTimer:fn=>{jobs.set(++next,fn);return next;},clearTimer:id=>jobs.delete(id)},
    paint(){const [id,fn]=this.node.frames.entries().next().value||[];if(fn){this.node.frames.delete(id);fn();}}};
}

test('a subscribed track keeps a waiting state until the video actually plays',async()=>{
  const f=fixture();const view=mountVideo(f.track,f.target,f.options);
  assert.equal(f.states.at(-1),'connecting');
  f.node.videoWidth=1280;f.node.readyState=4;f.fire('playing');
  assert.equal(f.states.at(-1),'connecting');f.paint();
  assert.equal(f.states.at(-1),'playing');view.dispose();
});

test('a zero-frame stream times out visibly instead of leaving an empty stage',()=>{
  const f=fixture();const view=mountVideo(f.track,f.target,f.options);
  f.node.paused=false;f.node.videoWidth=1280;f.node.readyState=4;
  for(const fn of [...f.jobs.values()])fn();assert.equal(f.states.at(-1),'unavailable');
  f.fire('playing');f.paint();
  assert.equal(f.states.at(-1),'playing');view.dispose();
});

test('blocked autoplay is recoverable by a user gesture',async()=>{
  const f=fixture();let blocked=true;f.node.play=async()=>{if(blocked)throw Object.assign(new Error('blocked'),{name:'NotAllowedError'});f.node.paused=false;};
  const view=mountVideo(f.track,f.target,f.options);await new Promise(done=>setImmediate(done));
  assert.equal(f.states.at(-1),'blocked');blocked=false;await view.play();
  f.node.videoWidth=1280;f.node.readyState=4;f.fire('playing');f.paint();assert.equal(f.states.at(-1),'playing');view.dispose();
});

test('leaving detaches the exact node and prevents late events or timers from updating the stage',()=>{
  const f=fixture();let detached;f.track.detach=node=>detached=node;
  const view=mountVideo(f.track,f.target,f.options);const late=[...f.jobs.values()];view.dispose();const count=f.states.length;
  for(const fn of late)fn();f.paint();f.fire('playing');assert.equal(f.states.length,count);assert.equal(detached,f.node);assert.equal(f.jobs.size,0);
});
