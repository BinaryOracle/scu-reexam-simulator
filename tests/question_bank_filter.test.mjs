import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const markup = readFileSync(new URL('../app/static/index.html', import.meta.url), 'utf8');
const admin = readFileSync(new URL('../app/static/admin.js', import.meta.url), 'utf8');
const styles = readFileSync(new URL('../app/static/style.css', import.meta.url), 'utf8');
const selectStyles = readFileSync(new URL('../app/static/select-controls.css', import.meta.url), 'utf8');

test('question bank filter exposes all professional subjects and filters by subject', () => {
  const filterMarkup = markup.slice(markup.indexOf('<select id="questionBankFilter">'), markup.indexOf('</select>', markup.indexOf('<select id="questionBankFilter">')));
  assert.match(filterMarkup, /value="professional:data_structures"[^>]*>专业课 · 数据结构/);
  assert.match(filterMarkup, /value="professional:computer_networks"[^>]*>专业课 · 计算机网络/);
  assert.match(filterMarkup, /value="professional:operating_systems"[^>]*>专业课 · 操作系统/);
  assert.match(admin, /filter\.includes\(":"\).*filter\.split\(":", 2\)/s);
  assert.match(admin, /row\.category === category && \(!subject \|\| row\.subject === subject\)/);
});

test('question bank filter changes reset pagination and retain category filtering', () => {
  assert.match(admin, /const filterKey = JSON\.stringify\(\[filter, query\]\)/);
  assert.match(admin, /bankPage = 1; bankFilterKey = filterKey/);
  assert.match(admin, /row\.category === category/);
});

test('select controls share a custom arrow and compact code-language sizing', () => {
  assert.match(selectStyles, /select:not\(\[multiple\]\)\s*\{[^}]*appearance:\s*none/s);
  assert.match(selectStyles, /select:not\(\[multiple\]\)\s*\{[^}]*background-image:/s);
  assert.match(selectStyles, /\.candidate-workspace select\.language-select\s*\{[^}]*min-height:\s*30px/s);
  assert.match(markup, /select-controls\.css\?v=20261116-v2/);
});

test('question bank filters fit their toolbar without squeezing field labels', () => {
  assert.match(styles, /\.question-bank-toolbar\s*\{[^}]*display:\s*grid/s);
  assert.match(styles, /\.question-bank-toolbar-field\s*\{[^}]*display:\s*grid/s);
  assert.match(styles, /\.question-bank-toolbar-field select\s*\{[^}]*min-width:\s*0/s);
  assert.match(styles, /#questionBankSearch\s*\{\s*width:\s*100%/);
});
