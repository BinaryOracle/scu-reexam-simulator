import test from 'node:test';
import assert from 'node:assert/strict';
import {createMarkdownPreview,readMarkdownFile} from '../app/static/course-markdown-model.mjs';
const tick=()=>new Promise(resolve=>setTimeout(resolve,5));
test('only displays the newest compilation even when a server ignores cancellation',async()=>{
  const requests=[],shown=[],errors=[];
  const preview=createMarkdownPreview({delay:0,compile:(text,signal)=>new Promise((resolve,reject)=>requests.push({text,signal,resolve,reject})),show:html=>shown.push(html),pending:()=>{},failed:error=>errors.push(error)});
  preview.update('first');await tick();preview.update('second');await tick();
  assert.equal(requests[0].signal.aborted,true);
  requests[1].resolve('<p>second</p>');await tick();requests[0].resolve('<p>first</p>');await tick();
  assert.deepEqual(shown,['<p>second</p>']);assert.deepEqual(errors,[]);preview.dispose();
});
test('clearing and disposing prevent stale content and errors from reappearing',async()=>{
  const requests=[],shown=[],errors=[];
  const preview=createMarkdownPreview({delay:0,compile:()=>new Promise((resolve,reject)=>requests.push({resolve,reject})),show:html=>shown.push(html),pending:()=>{},failed:error=>errors.push(error)});
  preview.update('first');await tick();preview.update('');requests[0].resolve('stale');await tick();
  assert.deepEqual(shown,['']);preview.update('second');await tick();preview.dispose();requests[1].reject(new Error('late'));await tick();assert.deepEqual(errors,[]);
});
test('reports compilation failure and permits a later edit to recover',async()=>{
  const errors=[],shown=[];let fail=true;
  const preview=createMarkdownPreview({delay:0,compile:async()=>{if(fail)throw new Error('unavailable');return 'recovered';},show:html=>shown.push(html),pending:()=>{},failed:error=>errors.push(error.message)});
  preview.update('one');await tick();assert.deepEqual(errors,['unavailable']);fail=false;preview.update('two');await tick();assert.deepEqual(shown,['recovered']);preview.dispose();
});
test('imports Chinese Markdown with a UTF-8 BOM and retains the filename',async()=>{
  const file=new File(['\uFEFF# 中文正文\n\n**重点**'],'第一课.MD');
  assert.deepEqual(await readMarkdownFile(file),{name:'第一课',text:'# 中文正文\n\n**重点**'});
});
test('rejects non-Markdown, binary and invalid UTF-8 uploads',async()=>{
  await assert.rejects(readMarkdownFile(new File(['text'],'bad.txt')),/\.md/);
  await assert.rejects(readMarkdownFile(new File([new Uint8Array([0xff,0xfe])],'bad.md')),/UTF-8/);
  await assert.rejects(readMarkdownFile(new File(['a\0b'],'bad.md')),/有效/);
});
