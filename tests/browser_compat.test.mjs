import assert from 'node:assert/strict';
import { webcrypto } from 'node:crypto';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';

const scriptUrl = new URL('../app/static/browser-compat.js', import.meta.url);
const source = readFileSync(scriptUrl, 'utf8');
const uuidPattern = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
function httpContext() {
  const crypto = { getRandomValues: bytes => webcrypto.getRandomValues(bytes) };
  const context = vm.createContext({ crypto });
  vm.runInContext(source, context);
  return context;
}

test('generates distinct UUID v4 identifiers without the secure-context-only API', () => {
  const { crypto } = httpContext();
  assert.equal(typeof crypto.randomUUID, 'function');
  const ids = Array.from({ length: 1000 }, () => crypto.randomUUID());
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.match(id, uuidPattern);
});

test('sets UUID version and variant bits for either extreme of random bytes', () => {
  for (const [byte, expected] of [[0, '00000000-0000-4000-8000-000000000000'], [255, 'ffffffff-ffff-4fff-bfff-ffffffffffff']]) {
    const crypto = { getRandomValues(bytes) { assert.equal(bytes.length, 16); bytes.fill(byte); return bytes; } };
    vm.runInNewContext(source, { crypto });
    assert.equal(crypto.randomUUID(), expected);
  }
});

test('retains native UUID support and remains safe to load twice', () => {
  const native = () => 'native-result';
  const crypto = { randomUUID: native, getRandomValues() { assert.fail('native API should be used'); } };
  vm.runInNewContext(source, { crypto });
  assert.equal(crypto.randomUUID, native);
  const context = httpContext();
  const fallback = context.crypto.randomUUID;
  vm.runInContext(source, context);
  assert.equal(context.crypto.randomUUID, fallback);
});

test('propagates secure random source failures instead of generating weak identifiers', () => {
  const error = new Error('random source unavailable');
  const crypto = { getRandomValues() { throw error; } };
  vm.runInNewContext(source, { crypto });
  assert.throws(() => crypto.randomUUID(), thrown => thrown === error);
});

test('loads compatibility synchronously before any application module', () => {
  const html = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');
  const scripts = Array.from(html.matchAll(/<script\b([^>]*)>/g));
  const compat = scripts.find(match => /src="\/static\/browser-compat\.js\?v=[^"]+"/.test(match[1]));
  assert.ok(compat, 'the HTML entry point must load browser compatibility');
  assert.doesNotMatch(compat[1], /\b(async|defer)\b|type="module"/);
  for (const module of scripts.filter(match => /type="module"/.test(match[1]))) assert.ok(compat.index < module.index);
});

test('opens the actual classroom dialog on HTTP with a valid accessible heading', () => {
  const context = httpContext();
  class Element {
    constructor(tag, text) { Object.assign(this, { tag, text, children: [], dataset: {} }); }
    append(...nodes) { this.children.push(...nodes); }
    setAttribute(name, value) { this[name] = value; }
    addEventListener() {}
    showModal() { this.open = true; }
  }
  context.document = { body: new Element('body'), activeElement: null };
  context.el = (...args) => new Element(...args);
  context.button = (...args) => new Element('button', args[0]);
  const modalSource = readFileSync(new URL('../app/static/live-ui.js', import.meta.url), 'utf8')
    .replace(/^import .*;\n/gm, '').replace(/^export \{.*\};\n/gm, '').replace(/\bexport /g, '');
  vm.runInContext(modalSource, context);
  const { dialog } = context.modal('创建课程');
  assert.equal(dialog.open, true);
  const heading = dialog.children[0].children[0];
  assert.equal(dialog['aria-labelledby'], heading.id);
  assert.match(heading.id.slice('liveDialog-'.length), uuidPattern);
});
