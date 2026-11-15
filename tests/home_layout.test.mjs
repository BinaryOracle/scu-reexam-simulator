import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../app/static/home-layout.js', import.meta.url), 'utf8')
  .replace(/^import .*;\n/gm, '').replace(/^export /gm, '');

function renderer() {
  const el = (tag, text = '', className = '') => ({ tag, text, className, children: [], append(...nodes) { this.children.push(...nodes); } });
  const opened = [], navigated = [];
  const context = vm.createContext({ el, button: (text, action, className) => ({ ...el('button', text, className), action }),
    window: { addEventListener() {}, open(...args) { opened.push(args); } } });
  vm.runInContext(source, context);
  const root = el('main'); context.root = root;
  return { root, opened, navigated, render(blocks) {
    context.blocks = blocks; context.navigate = (...args) => navigated.push(args);
    vm.runInContext('renderHomeBlocks(root, blocks, navigate)', context);
  } };
}

test('published sections retain administrator order while disabled content stays hidden', () => {
  const f = renderer();
  f.render([
    { enabled: true, type: 'roadmap', title: '准备路线', items: [{ enabled: false, title: '隐藏' }, { enabled: true, title: '先学基础', summary: '介绍' }] },
    { enabled: false, type: 'resources', title: '不可见', items: [] },
    { enabled: true, type: 'resources', title: '资料', items: [] },
  ]);
  assert.equal(f.root.children.length, 2);
  const [roadmap, resources] = f.root.children;
  assert.equal(roadmap.children[0].children[0].text, '准备路线');
  assert.equal(resources.children[0].children[0].text, '资料');
  assert.equal(roadmap.children[1].children.length, 1);
  assert.equal(roadmap.children[1].children[0].children[0].text, '01');
});

test('resource links retain training sections and open external destinations without an opener', () => {
  const f = renderer();
  f.render([{ enabled: true, type: 'resources', title: '资源', items: [
    { enabled: true, kind: 'view', view: 'training', section: 'written_ai', title: 'AI', stars: 0 },
    { enabled: true, kind: 'external', url: 'https://example.org/guide', title: '<img onerror=alert(1)>', stars: 4 },
  ] }]);
  const [internal, external] = f.root.children[0].children[1].children;
  internal.action(); external.action();
  assert.deepEqual(f.navigated, [['training', 'written_ai']]);
  assert.deepEqual(f.opened, [['https://example.org/guide', '_blank', 'noopener,noreferrer']]);
  assert.equal(external.children[1].text, '<img onerror=alert(1)>');
  assert.equal(internal.children[0].tag, 'strong');
});
