import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const read=path=>readFileSync(new URL(path,import.meta.url),'utf8');
const source=read('../app/static/course-learning.js').replace(/^import .*;\n/gm,'').replaceAll('export function','function').replaceAll('export async function','async function');

class Node extends EventTarget{
  constructor(tag,text='',classes=''){super();this.tag=tag;this.textContent=text;this.className=classes;this.children=[];this.hidden=false;this.value='';}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=nodes;}
  querySelectorAll(){return [];}
  setAttribute(){}
  focus(){}
}

function editor(course=null){
  const root=new Node('div'),requests=[];
  const el=(...args)=>new Node(...args);
  const input=(value='',type='text')=>Object.assign(el('input'),{value,type});
  const field=(label,control)=>{const node=el('label',label);node.append(control);return node;};
  const button=(label,action,classes)=>Object.assign(el('button',label,classes),{action});
  const context=vm.createContext({el,input,field,button,Event,closeCourseMenusOutsideClick:()=>{},document:{getElementById:()=>root,addEventListener:()=>{}},state:{user:{id:1}},
    api:async(path,options)=>{requests.push({path,...JSON.parse(options.body)});return {id:7};},notify:()=>{}});
  vm.runInContext(source,context);
  vm.runInContext(`
    pageTitle=()=>el('header');
    markdownEditor=(_label,value)=>({editor:input(value),container:el('div'),bindSave:()=>{}});
    editorCoverField=()=>({area:el('div'),preset:'current'});
    editorStepNavigation=()=>el('nav');
    goTo=()=>{};
  `,context);
  context.renderEditorInfo(course?.id,course,root);
  const nodes=node=>[node,...node.children.flatMap(nodes)];
  const all=nodes(root),access=all.find(node=>node.tag==='select'),numbers=all.filter(node=>node.type==='number'),price=numbers[0],duration=numbers[1];
  return {requests,access,price,priceField:all.find(node=>node.children.includes(price)),
    duration,durationField:all.find(node=>node.children.includes(duration)),
    title:all.find(node=>node.tag==='input'&&node.type==='text'),save:all.find(node=>node.textContent===(course?'保存课程信息':'保存草稿并继续'))};
}

test('switching a new course to points exposes an editable price and saves that mode',async()=>{
  const f=editor();
  assert.deepEqual(f.access.children.map(option=>option.value),['public','roster','points']);
  assert.equal(f.priceField.hidden,true);
  f.access.value='points';f.access.dispatchEvent(new Event('change'));
  assert.equal(f.priceField.hidden,false);
  assert.equal(f.price.hidden,false);
  f.title.value='付费课程';f.price.value='25';f.duration.value='365';await f.save.action();
  assert.equal(f.requests[0].access_mode,'points');assert.equal(f.requests[0].points_price,25);assert.equal(f.requests[0].points_access_days,365);
  f.access.value='roster';f.access.dispatchEvent(new Event('change'));
  assert.equal(f.priceField.hidden,true);
});

test('editing a paid course retains its price',async()=>{
  const f=editor({id:7,title:'付费课程',access_mode:'points',points_price:25});
  assert.equal(f.access.value,'points');assert.equal(f.price.hidden,false);assert.equal(f.priceField.hidden,false);
  assert.equal(f.price.value,'25');assert.equal(f.duration.value,'0');await f.save.action();
  assert.equal(f.requests[0].points_price,25);assert.equal(f.requests[0].points_access_days,0);
});

test('administrator publish view explains course participation and purchase duration',()=>{
  assert.match(source,/enrollment_summary/);
  assert.match(source,/points_access_days/);
  assert.match(source,/已购买/);
  assert.match(source,/已加入学习/);
});

test('the document and parent imports refresh cached course access forms',()=>{
  const version='20261122-course-purchase-duration-v1';
  assert.ok(read('../app/static/index.html').includes(`app.js?v=${version}`));
  assert.ok(read('../app/static/app.js').includes(`live.js?v=${version}`));
  assert.ok(read('../app/static/live.js').includes(`course-learning.js?v=${version}`));
  assert.ok(read('../app/static/index.html').includes(`course-learning.css?v=${version}`));
});

test('uses the public sanitized outline when the lesson is preview-only',()=>{
  assert.match(source,/lesson\.preview_only\?`\/courses\/public\/\$\{lesson\.course_id\}`:`\/courses\/\$\{lesson\.course_id\}`/);
});
