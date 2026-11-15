import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Exercise the actual renderer without the API/network side effects of importing the app.
const source = readFileSync(new URL('../app/static/contest.js', import.meta.url), 'utf8');
const render = source.slice(source.indexOf('function renderWorkspace()'), source.indexOf('function renderEditorPanels('));
class Node {
  constructor(tag = 'div', text = '', classes = '') {
    this.tag = tag; this.textContent = text; this.className = classes;
    this.childNodes = []; this.dataset = {}; this.style = {}; this.hidden = false;
    this.classList = { add: name => { this.className += ` ${name}`; } };
  }
  append(...nodes) { this.childNodes.push(...nodes); }
  prepend(...nodes) { this.childNodes.unshift(...nodes); }
  replaceChildren(...nodes) { this.childNodes = nodes; }
  insertBefore(node, reference) { this.childNodes.splice(this.childNodes.indexOf(reference), 0, node); }
  setAttribute(name, value) { this[name] = value; }
  querySelector(selector) {
    return this.childNodes.find(node => selector.startsWith('.') && node.className?.split(' ').includes(selector.slice(1)))
      ?? this.childNodes.map(node => node.querySelector?.(selector)).find(Boolean) ?? null;
  }
  getBoundingClientRect() { return { left: 0, right: 500 }; }
}
function fixture() {
  const roots = new Map(); let mounts = 0;
  const context = {
    el: (tag, text, classes) => new Node(tag, text, classes),
    $: id => { if (!roots.has(id)) roots.set(id, new Node()); return roots.get(id); },
    document: { body: { classList: { contains: () => true } } },
    currentProblems: [{id:1,title:'区间查询',statement:'完整题面',statement_html:'<p>完整题面</p>',samples:[{input:'1',output:'2'}]}],
    selectedProblem:1,selectedContest:{id:1,title:'模拟赛',judge_mode:'luogu'}, mobilePane:'statement',
    luoguStatusChecked:true,
    managementMode:()=>false, suspendContestWorkspace(){}, prepareLuoguConnection(){},
    renderContestTimeline:()=>new Node(), button:(label,action,classes)=>{const n=new Node('button',label,classes);n.action=action;return n;},
    contestStatus:()=>['进行中','green'],badge:()=>new Node(), deadline:()=>'', canRevealLuoguSource:()=>false,
    appendProblemStatement:(node,html)=>node.append(new Node('div',html,'problem-statement-content')),
    renderEditorPanels:()=>{const panel=new Node();panel.append(new Node('div','','auxiliary-panel-heading'));return panel;},
    renderEditor:()=>{const editor=new Node('section','','editor-panel');editor.append(new Node('div','','editor-heading'));return editor;},
    expandPaneButton:()=>new Node('button','','pane-expand'),renderMobilePaneSwitcher:()=>new Node(),
    layoutPreferences:()=>({}),mountWorkspaceLayout:()=>{mounts++;}, loadContestSubmissions(){}, tick(){},
  };
  vm.createContext(context); vm.runInContext(render, context);
  return {context,roots,mounts:()=>mounts};
}

test('opens a candidate workspace with usable editor controls and independent content panes', () => {
  const f=fixture();
  assert.doesNotThrow(()=>f.context.renderWorkspace());
  assert.equal(f.mounts(),1);
  const workspace=f.roots.get('problemList').childNodes[0];
  assert.ok(workspace.querySelector('.candidate-workspace'));
  assert.ok(workspace.querySelector('.editor-heading').childNodes.some(node=>node['aria-label']==='收起代码区'));
  assert.ok(workspace.querySelector('.problem-statement-content'));
  assert.equal(f.roots.get('problemList').hidden,false);
});
