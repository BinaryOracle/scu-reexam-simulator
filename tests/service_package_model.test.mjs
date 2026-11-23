import assert from 'node:assert/strict';
import test from 'node:test';
import { packageMoney, rebateText, filterPackages, insertPastedImages } from '../app/static/service-package-model.mjs';

test('purchase summaries format integer fen and all three settlement states', () => {
  assert.equal(packageMoney(9999), '¥99.99');
  assert.equal(packageMoney(0), '¥0.00');
  assert.deepEqual(['unset', 'pending', 'redeemed'].map(rebateText), ['未填写', '待兑换', '已兑换']);
});

test('catalog search and state filters compose without hiding disabled packages by default', () => {
  const items = [{ name: '复试辅导', enabled: true }, { name: '项目辅导', enabled: false }];
  assert.equal(filterPackages(items, '', 'all').length, 2);
  assert.deepEqual(filterPackages(items, '辅导', 'disabled'), [items[1]]);
  assert.deepEqual(filterPackages(items, '复试', 'enabled'), [items[0]]);
});

test('pasting images uploads them and inserts Markdown at the current selection', async () => {
  const editor = {
    value: '前文后文', selectionStart: 1, selectionEnd: 2,
    setRangeText(value, start, end) {
      this.value = this.value.slice(0, start) + value + this.value.slice(end);
      this.selectionStart = this.selectionEnd = start + value.length;
    },
    dispatchEvent(event) { this.lastEvent = event.type; },
  };
  const files = [{ type: 'image/png', name: '课件[1].png' }];
  const uploaded = [];

  await insertPastedImages(editor, files, async file => {
    uploaded.push(file);
    return { url: '/api/admin/announcements/assets/0123456789abcdef0123456789abcdef' };
  });

  assert.deepEqual(uploaded, files);
  assert.equal(editor.value, '前![课件1.png](/api/admin/announcements/assets/0123456789abcdef0123456789abcdef)后文');
  assert.equal(editor.lastEvent, 'input');
});
