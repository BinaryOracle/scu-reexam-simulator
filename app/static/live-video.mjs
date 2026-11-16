/** Mount a muted video in the document before attaching a LiveKit track.
 * Track subscription is separate from playback: retain a visible waiting or
 * recovery state until decoded frames are playing. The owner disposes on swap.
 */
export function mountVideo(track,target,{onState,createVideo=()=>document.createElement('video'),setTimer=setTimeout,clearTimer=clearTimeout,timeout=12000}={}) {
  const node=createVideo();node.muted=true;node.autoplay=true;node.playsInline=true;
  let closed=false,timer,current,frameHandle,receivedFrame=false;
  const report=state=>{if(closed||current===state)return;current=state;onState?.(state);};
  const frameApi=typeof node.requestVideoFrameCallback==='function';
  const watchFrame=()=>{frameHandle=node.requestVideoFrameCallback(()=>{if(closed)return;receivedFrame=true;update();watchFrame();});};
  const ready=()=>node.readyState>=2&&node.videoWidth>0&&!node.paused&&(!frameApi||receivedFrame);
  const wait=()=>{if(timer||current==='blocked')return;timer=setTimer(()=>{timer=null;if(!closed&&!ready())report('unavailable');},timeout);};
  const update=()=>{if(closed)return;if(ready()){clearTimer(timer);timer=null;report('playing');}else{if(current!=='blocked'&&current!=='unavailable')report('connecting');wait();}};
  const fail=()=>report('unavailable');
  const play=async()=>{if(closed)return;try{await node.play();if(!closed){if(current==='blocked')report('connecting');update();}}catch(error){if(!closed){if(error.name==='NotAllowedError'){clearTimer(timer);timer=null;report('blocked');}else if(error.name!=='AbortError')report('unavailable');}}};
  const events=['playing','loadeddata','resize','waiting','pause','emptied'];
  for(const event of events)node.addEventListener(event,update);
  node.addEventListener('error',fail);report('connecting');target.append(node);if(frameApi)watchFrame();
  try{track.attach(node);}catch(error){clearTimer(timer);if(frameHandle!==undefined)node.cancelVideoFrameCallback?.(frameHandle);for(const event of events)node.removeEventListener(event,update);node.removeEventListener('error',fail);track.detach(node);node.remove();throw error;}
  update();void play();
  return {node,play,update,dispose(){if(closed)return;closed=true;clearTimer(timer);if(frameHandle!==undefined)node.cancelVideoFrameCallback?.(frameHandle);for(const event of events)node.removeEventListener(event,update);node.removeEventListener('error',fail);track.detach(node);node.remove();}};
}
