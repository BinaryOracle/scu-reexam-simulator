import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

// Exercise the actual renderer without the API/network side effects of importing the app.
const source = readFileSync(new URL('../app/static/contest.js', import.meta.url), 'utf8');
const layoutStyles = readFileSync(new URL('../app/static/workspace.css', import.meta.url), 'utf8');
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
    renderEditorPanels:()=>{const panel=new Node();const heading=new Node('div','','auxiliary-panel-heading');heading.append(new Node('button','','pane-expand'));panel.append(heading);return panel;},
    renderEditor:()=>{const editor=new Node('section','','editor-panel');const heading=new Node('div','','editor-heading');const tools=new Node('div','','editor-heading-tools');tools.append(new Node('select','','language-select'),new Node('button','复制代码','code-copy-button'));heading.append(new Node('h4','代码工作区'),tools);editor.append(heading);return editor;},
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
  const workbench = workspace.querySelector('.problem-workbench');
  assert.ok(workspace.childNodes.includes(workspace.querySelector('.workspace-pane-restores')));
  assert.ok(workbench.childNodes.includes(workspace.querySelector('.candidate-workspace')));
  assert.equal(workbench.childNodes.includes(workspace.querySelector('.workspace-pane-restores')), false);
  const headingTools = workspace.querySelector('.editor-heading-tools');
  assert.deepEqual(headingTools.childNodes.map(node=>node.className), ['language-select','code-copy-button','workspace-pane-actions']);
  assert.ok(headingTools.querySelector('.workspace-pane-actions').childNodes.some(node=>node['aria-label']==='收起代码区'));
  assert.ok(workspace.querySelector('.problem-statement-content'));
  assert.equal(f.roots.get('problemList').hidden,false);
});

test('keeps the editor and sample splitter adjustable after closing the statement pane', () => {
  assert.match(layoutStyles, /\.candidate-workspace\s*>\s*\.editor-stack\s*\{\s*grid-template-rows:\s*minmax\(0,\s*calc\(var\(--editor-size,\s*\.72\)\s*\*\s*\(100%\s*-\s*8px\)\)\)\s*8px\s*minmax\(0,\s*1fr\)/);
  assert.doesNotMatch(layoutStyles, /data-statement-hidden="true"\]:not\(\[data-editor-hidden="true"\]\):not\(\[data-panels-hidden="true"\]\)\s*>\s*\.editor-stack\s*\{\s*grid-template-rows:\s*minmax\(0,\s*1fr\)\s*8px\s*minmax\(0,\s*1fr\)/);
});

test('keeps the submission panel in the remaining outer grid columns when the code editor closes', () => {
  assert.match(layoutStyles, /\.candidate-workspace\[data-editor-hidden="true"\]:not\(\[data-panels-hidden="true"\]\)\s*>\s*\.editor-stack\s*\{\s*grid-column:\s*2\s*\/\s*-1/);
});

test('lets the submission panel fill the workspace when it is the only visible pane', () => {
  assert.match(layoutStyles, /\.candidate-workspace\[data-statement-hidden="true"\]\[data-editor-hidden="true"\]:not\(\[data-panels-hidden="true"\]\)\s*>\s*\.editor-stack\s*\{\s*grid-column:\s*1\s*\/\s*-1/);
});

test('does not expose the local database id as a user-facing problem number', () => {
  const f = fixture();
  f.context.renderWorkspace();
  const statement = f.roots.get('problemList').childNodes[0].querySelector('.workspace-statement-content').childNodes[0];
  assert.equal(statement.textContent, '区间查询');
});

test('labels a visible external problem number with its platform', () => {
  const f = fixture();
  f.context.currentProblems[0].remote_problem_id = 'P1000';
  f.context.canRevealLuoguSource = () => true;
  f.context.renderWorkspace();
  const content = f.roots.get('problemList').childNodes[0].querySelector('.workspace-statement-content');
  assert.deepEqual(content.childNodes.slice(0, 2).map(node => node.textContent), ['洛谷题号 · P1000', '区间查询']);
});

test('groups Luogu source and refresh actions with clear spacing when they wrap', () => {
  const f = fixture();
  f.context.currentProblems[0] = { ...f.context.currentProblems[0], remote_problem_id: 'P1000' };
  f.context.managementMode = () => true;
  f.context.canRevealLuoguSource = () => true;
  f.context.renderWorkspace();
  const workspace = f.roots.get('problemList').childNodes[0];
  const actions = workspace.querySelector('.problem-source-actions');
  assert.ok(actions);
  assert.deepEqual(actions.childNodes.map(row => row.className), [
    'problem-source-action-row',
    'problem-source-action-row',
  ]);
  assert.deepEqual(actions.childNodes.map(row => row.childNodes[0].textContent), [
    '在洛谷打开题目 ↗',
    '从洛谷更新题面与样例',
  ]);
  assert.match(readFileSync(new URL('../app/static/style.css', import.meta.url), 'utf8'), /\.problem-source-actions\s*\{\s*display:\s*grid;\s*grid-template-columns:\s*minmax\(0, max-content\);\s*justify-content:\s*start;\s*row-gap:\s*24px;/);
  assert.match(readFileSync(new URL('../app/static/style.css', import.meta.url), 'utf8'), /\.problem-source-action-row\s*\{\s*display:\s*flex;\s*align-items:\s*center;\s*width:\s*100%;\s*min-width:\s*0;\s*min-height:\s*40px;/);
  assert.match(readFileSync(new URL('../app/static/style.css', import.meta.url), 'utf8'), /\.contest-immersive \.problem-source-actions\s*\{[^}]*row-gap:\s*20px/);
});

test('removes the empty restore bar so narrow workspaces do not reserve blank space', () => {
  assert.match(layoutStyles, /\.workspace-pane-restores:not\(:has\(> button:not\(\[hidden\]\)\)\)\s*\{\s*display:\s*none;\s*\}/);
});
