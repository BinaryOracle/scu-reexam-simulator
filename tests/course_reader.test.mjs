import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const source=readFileSync(new URL('../app/static/course-reader.mjs',import.meta.url),'utf8')
  .replace(/^import .*;\n/,'').replaceAll('export function','function');

class Node extends EventTarget{
  constructor(tag='div',text='',classes=''){
    super();this.tag=tag;this.textContent=text;this.className=classes;this.children=[];this.hidden=false;this.attributes={};
    this.classList={
      toggle:(name,on)=>{const values=new Set(this.className.split(' ').filter(Boolean));if(on)values.add(name);else values.delete(name);this.className=[...values].join(' ');},
      remove:name=>this.classList.toggle(name,false),
      contains:name=>this.className.split(' ').includes(name),
    };
  }
  append(...nodes){this.children.push(...nodes);}
  prepend(...nodes){this.children.unshift(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  setAttribute(key,value){this.attributes[key]=value;}
  querySelector(selector){return this.children.find(node=>node.classList.contains(selector.slice(1)))??this.children.map(node=>node.querySelector(selector)).find(Boolean)??null;}
  querySelectorAll(){return this.children.flatMap(node=>[...(node.tag==='button'?[node]:[]),...node.querySelectorAll()]);}
  contains(node){return node===this||this.children.some(child=>child.contains(node));}
  getBoundingClientRect(){return {top:-240};}
  getClientRects(){return [{}];}
  focus(){this.owner.activeElement=this;}
}

function fixture({mobile=false,native=true,rejected=false,pending=false}={}){
  const doc=new EventTarget();doc.body=new Node();doc.activeElement=null;doc.fullscreenElement=null;
  let exitCalls=0,resolveFullscreen;
  doc.exitFullscreen=async()=>{exitCalls++;doc.fullscreenElement=null;doc.dispatchEvent(new Event('fullscreenchange'));};
  const media=new EventTarget();media.matches=mobile;
  const win={matchMedia:()=>media,scrollY:500,scrollTo:(_x,y)=>{win.scrollY=y;}};
  const el=(...args)=>{const node=new Node(...args);node.owner=doc;return node;};
  const button=(label,action,classes)=>{const node=el('button',label,classes);node.action=action;return node;};
  const context=vm.createContext({document:doc,window:win,el,button});vm.runInContext(source,context);
  const host=el();
  function mount(){
    const layout=el(),nav=el(),content=el();nav.append(el('div','','course-section-title'),el('div','','course-study-nav-content'));const reading=el('section','','course-study-reading');reading.append(el('h2','课程正文'));content.append(reading);layout.append(nav,content);
    if(native)content.requestFullscreen=async()=>{
      if(rejected)throw new Error('Fullscreen is not permitted');
      if(pending)await new Promise(resolve=>{resolveFullscreen=resolve;});
      doc.fullscreenElement=content;doc.dispatchEvent(new Event('fullscreenchange'));
    };
    host.replaceChildren(layout);
    host.requestFullscreen=content.requestFullscreen&&async function(){if(rejected)throw new Error('Fullscreen is not permitted');if(pending)await new Promise(resolve=>{resolveFullscreen=resolve;});doc.fullscreenElement=host;doc.dispatchEvent(new Event('fullscreenchange'));};
    const dispose=context.mountCourseReader({host,layout,nav,content,title:'动态规划：状态转移方程'});
    const toggle=content.querySelector('.course-reader-restore');
    const fullscreen=content.querySelector('.course-reader-fullscreen');
    return {host,layout,nav,content,toggle,fullscreen,dispose};
  }
  return {doc,win,media,mount,host,exitCalls:()=>exitCalls,finishRequest:()=>resolveFullscreen()};
}

test('collapses the desktop catalog, frees its column and retains the choice across lessons',()=>{
  const f=fixture(),a=f.mount();
  assert.equal(a.nav.hidden,false);assert.equal(a.toggle.attributes['aria-expanded'],'true');
  a.nav.querySelector('.course-reader-catalog-heading').focus();
  a.nav.querySelector('.course-reader-catalog-heading').action();
  assert.equal(a.nav.hidden,true);assert.equal(a.layout.classList.contains('is-catalog-collapsed'),true);
  assert.equal(f.doc.activeElement,a.toggle);assert.equal(a.toggle.attributes['aria-expanded'],'false');
  a.dispose();const b=f.mount();assert.equal(b.nav.hidden,true);
  b.toggle.action();assert.equal(b.nav.hidden,false);b.dispose();
});

test('starts mobile with the catalog closed and adapts to resizing until the user chooses',()=>{
  const f=fixture({mobile:true}),a=f.mount();assert.equal(a.nav.hidden,true);
  f.media.matches=false;f.media.dispatchEvent(new Event('change'));assert.equal(a.nav.hidden,false);
  a.nav.querySelector('.course-reader-catalog-heading').action();f.media.matches=true;f.media.dispatchEvent(new Event('change'));
  f.media.matches=false;f.media.dispatchEvent(new Event('change'));assert.equal(a.nav.hidden,true);a.dispose();
});

test('enters native fullscreen for the lesson and synchronizes a browser Escape exit',async()=>{
  const f=fixture(),a=f.mount();await a.fullscreen.action();
  assert.equal(f.doc.fullscreenElement,a.host);assert.equal(a.content.classList.contains('is-reader-fullscreen'),true);
  assert.equal(a.content.scrollTop,240);assert.equal(a.content.querySelector('.course-reader-rail').hidden,true);
  assert.equal(a.fullscreen.attributes['aria-pressed'],'true');
  f.win.scrollY=0;await f.doc.exitFullscreen();
  assert.equal(a.content.classList.contains('is-reader-fullscreen'),false);assert.equal(a.content.querySelector('.course-reader-rail').hidden,true);
  assert.equal(a.fullscreen.attributes['aria-pressed'],'false');assert.equal(f.win.scrollY,500);a.dispose();
});

for(const native of [false,true])test(`keeps an escapable reading mode when native fullscreen is ${native?'denied':'unavailable'}`,async()=>{
  const f=fixture({native,rejected:true}),a=f.mount();await a.fullscreen.action();
  assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),true);
  assert.equal(a.content.classList.contains('is-reader-fullscreen'),true);
  const escape=new Event('keydown',{cancelable:true});escape.key='Escape';f.doc.dispatchEvent(escape);
  assert.equal(escape.defaultPrevented,true);assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),false);
  assert.equal(a.content.classList.contains('is-reader-fullscreen'),false);a.dispose();
});

test('exit control works and route cleanup releases fullscreen without retaining listeners',async()=>{
  const f=fixture(),a=f.mount();await a.fullscreen.action();await a.fullscreen.action();assert.equal(f.exitCalls(),1);
  await a.fullscreen.action();a.dispose();assert.equal(f.exitCalls(),2);
  a.toggle.textContent='disposed';f.media.matches=true;f.media.dispatchEvent(new Event('change'));
  assert.equal(a.toggle.textContent,'disposed');assert.equal(a.content.classList.contains('is-reader-fullscreen'),false);
});

test('does not reopen fullscreen if the user navigates while its request is pending',async()=>{
  const f=fixture({pending:true}),a=f.mount();const request=a.fullscreen.action();a.dispose();f.finishRequest();await request;
  assert.equal(f.doc.fullscreenElement,null);assert.equal(f.exitCalls(),1);
  assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),false);
});

test('fallback cleanup unlocks page scrolling and stops responding to Escape',async()=>{
  const f=fixture({native:false}),a=f.mount();await a.fullscreen.action();a.dispose();
  assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),false);
  const escape=new Event('keydown',{cancelable:true});escape.key='Escape';f.doc.dispatchEvent(escape);assert.equal(escape.defaultPrevented,false);
});


test('uses the complete catalog heading to collapse and restores keyboard focus when expanding',()=>{
  const f=fixture(),a=f.mount();const heading=a.nav.querySelector('.course-reader-catalog-heading');
  assert.equal(heading.tag,'button');assert.equal(heading.attributes['aria-expanded'],'true');
  assert.equal(a.content.querySelector('.course-reader-rail').hidden,true);
  assert.equal(a.content.querySelector('.course-reader-toolbar'),null);
  heading.focus();heading.action();assert.equal(a.content.querySelector('.course-reader-rail').hidden,false);
  a.toggle.action();assert.equal(f.doc.activeElement,heading);
  assert.equal(a.content.querySelector('.course-reading-heading').querySelector('.course-reader-fullscreen'),a.fullscreen);
  assert.equal(a.fullscreen.attributes['aria-label'],'全屏阅读');a.dispose();
});


for(const native of [true,false])test(`retains ${native?'native fullscreen':'page reading mode'} across lesson replacement`,async()=>{
  const f=fixture({native}),a=f.mount();await a.fullscreen.action();
  a.dispose({preserveFullscreen:true});
  if(native)assert.equal(f.doc.fullscreenElement,f.host);
  else assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),true);
  const b=f.mount();assert.equal(b.fullscreen.attributes['aria-pressed'],'true');
  assert.equal(b.content.classList.contains('is-reader-fullscreen'),true);
  assert.equal(f.exitCalls(),0);b.dispose();
});

for(const native of [true,false])test(`Escape during lesson loading releases ${native?'native fullscreen':'page reading mode'}`,async()=>{
  const f=fixture({native}),a=f.mount();await a.fullscreen.action();a.dispose({preserveFullscreen:true});
  if(native)await f.doc.exitFullscreen();
  else{const escape=new Event('keydown',{cancelable:true});escape.key='Escape';f.doc.dispatchEvent(escape);}
  assert.equal(f.host.classList.contains('course-reader-host-fullscreen'),false);
  assert.equal(f.doc.body.classList.contains('course-reader-focus-active'),false);
  const b=f.mount();assert.equal(b.fullscreen.attributes['aria-pressed'],'false');b.dispose();
});
