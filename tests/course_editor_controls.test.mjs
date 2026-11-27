import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {closeCourseMenusOutsideClick} from '../app/static/course-menu.mjs';

const source=readFileSync(new URL('../app/static/course-learning.js',import.meta.url),'utf8');
const styles=readFileSync(new URL('../app/static/course-learning.css',import.meta.url),'utf8');

test('closes open course menus on outside clicks and on menu action clicks',()=>{
  const first={open:true},second={open:true},other={open:true};
  const summary={parentElement:first};
  closeCourseMenusOutsideClick({target:{closest:()=>summary}},[first,second,other]);
  assert.equal(first.open,true);assert.equal(second.open,false);assert.equal(other.open,false);
  closeCourseMenusOutsideClick({target:{closest:()=>null}},[first]);
  assert.equal(first.open,false);
});

test('labels section and lesson editor actions as preview settings',()=>{
  assert.match(source,/编辑章节与预览/);
  assert.match(source,/编辑课时与预览/);
  assert.match(source,/允许本章预览/);
  assert.match(source,/允许预览本小节/);
  assert.match(source,/details\.course-menu-popover\[open\]/);
  assert.match(source,/course-menu-popover/);
});

test('lays out cover preview and upload controls without overlap',()=>{
  assert.match(styles,/\.course-cover-field\s*\{[^}]*display:\s*grid/s);
  assert.match(styles,/\.course-cover-actions\s*\{[^}]*display:\s*flex[^}]*flex-wrap:\s*wrap/s);
  assert.match(styles,/@media\s*\(max-width:\s*760px\)[\s\S]*?\.course-cover-field\s*\{[^}]*grid-template-columns:\s*minmax\(0,1fr\)/);
});

test('keeps preview checkboxes aligned with their labels in compact settings dialogs',()=>{
  assert.match(source,/dialog\.classList\.add\('course-settings-dialog'\)/);
  assert.match(source,/previewField\.classList\.add\('course-preview-toggle'\)/);
  assert.match(styles,/\.course-settings-dialog \.course-preview-toggle input\[type=checkbox\]\s*\{[^}]*width:\s*18px[^}]*height:\s*18px/s);
  assert.match(styles,/\.course-settings-dialog \.live-field:not\(\.course-preview-toggle\)\s*\{[^}]*margin:\s*0/s);
});

test('styles the lesson Markdown editor as a compact, clear edit-preview workspace',()=>{
  assert.match(styles,/\.course-settings-dialog \.course-markdown-heading\s*\{[^}]*display:\s*flex/s);
  assert.match(styles,/\.course-settings-dialog \.course-markdown-controls\s*\{[^}]*display:\s*inline-flex/s);
  assert.match(styles,/\.course-settings-dialog \.course-markdown-mode\.selected/);
  assert.match(styles,/\.course-settings-dialog \.course-markdown-editor\s*\{[^}]*min-height:\s*200px/s);
  assert.match(styles,/\.course-settings-dialog \.course-markdown-help\s*\{[^}]*margin:\s*0/s);
  assert.match(source,/edit\.classList\.toggle\('selected',!show\)/);
  assert.match(source,/showPreview\.classList\.toggle\('selected',show\)/);
});

test('lets managers resize long chapter lists and keeps lesson menus inside the visible area',()=>{
  assert.match(styles,/\.course-management-workbench \.course-lesson-list\s*\{[^}]*resize:\s*vertical/s);
  assert.match(styles,/\.course-menu-popover\.opens-up/);
  assert.match(source,/fitCourseMenu\(more,menu,lessonList\)/);
  assert.match(source,/拖动右下角调整当前章节高度/);
});
