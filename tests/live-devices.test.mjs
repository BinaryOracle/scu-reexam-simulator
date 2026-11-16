import test from 'node:test';import assert from 'node:assert/strict';
import {mediaLease} from '../app/static/live-devices.mjs';
function stream(){const track={stopped:false,stop(){this.stopped=true;}};return{track,getTracks:()=>[track]};}
test('discards a late microphone grant after a newer preview request',async()=>{
 const pending=[];const lease=mediaLease(()=>new Promise(resolve=>pending.push(resolve)));const a=lease.acquire({audio:true});const b=lease.acquire({video:true});
 const first=stream(),second=stream();pending[1](second);assert.equal((await b).stream,second);pending[0](first);assert.equal(await a,null);assert.equal(first.track.stopped,true);assert.equal(second.track.stopped,false);lease.release();assert.equal(second.track.stopped,true);
});
test('closing preparation releases a stream granted after dialog closure',async()=>{
 let resolve;const lease=mediaLease(()=>new Promise(r=>resolve=r));const pending=lease.acquire({audio:true});lease.release();const late=stream();resolve(late);assert.equal(await pending,null);assert.equal(late.track.stopped,true);
});
test('marks a captured stream stale while an audio context is resuming',async()=>{
 const source=stream();const lease=mediaLease(async()=>source);const capture=await lease.acquire({audio:true});assert.equal(capture.isCurrent(),true);lease.release();assert.equal(capture.isCurrent(),false);assert.equal(source.track.stopped,true);
});
