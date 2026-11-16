import test from 'node:test';
import assert from 'node:assert/strict';
import { liveRoute, elapsed, recordingText, orderedMembers, mayJoin, needsLessonUpdates } from '../app/static/live-model.mjs';
test('accepts only positive safe course and lesson route identifiers',()=>{
  assert.deepEqual(liveRoute('#view=live/course/12'),{kind:'course',id:12});
  assert.deepEqual(liveRoute('#view=live/lesson/2'),{kind:'lesson',id:2});
  for(const hash of ['#view=live/course/0','#view=live/lesson/-1','#view=live/lesson/9007199254740992','#view=live/lesson/2evil']) assert.deepEqual(liveRoute(hash),{kind:'list'});
});
test('formats elapsed classroom time without negative or invalid clocks',()=>{
  assert.equal(elapsed(0),'00:00');assert.equal(elapsed(3661),'01:01:01');assert.equal(elapsed(-1),'00:00');
});
test('keeps host and pending hands prominent without mutating server data',()=>{
  const source=[{user_id:3,username:'B'},{user_id:2,username:'A',hand:true},{user_id:1,username:'Host',is_host:true}];
  assert.deepEqual(orderedMembers(source).map(x=>x.user_id),[1,2,3]);assert.equal(source[0].user_id,3);
});
test('never labels an unfinished or failed recording playable',()=>{
 assert.equal(recordingText('failed'),'录制失败');assert.equal(recordingText('processing'),'回放处理中');assert.equal(recordingText('ready'),'可观看');assert.equal(recordingText('recording'),'正在录制');
});
test('only a live configured classroom accepts entry',()=>{
 assert.equal(mayJoin({status:'scheduled',configured:true}),false);assert.equal(mayJoin({status:'live',configured:false}),false);assert.equal(mayJoin({status:'ended',configured:true}),false);assert.equal(mayJoin({status:'live',configured:true}),true);
});
test('keeps ended lessons fresh until recordings finish',()=>{
  for(const status of ['starting','recording','stopping','processing','unknown']) assert.equal(needsLessonUpdates({status:'ended',recordings:[{status}]}),true);
  assert.equal(needsLessonUpdates({status:'ended',recordings:[{status:'ready'},{status:'failed'}]}),false);
  assert.equal(needsLessonUpdates({status:'ended',recordings:[]}),false);
  assert.equal(needsLessonUpdates({status:'live',recordings:[]}),true);
});
