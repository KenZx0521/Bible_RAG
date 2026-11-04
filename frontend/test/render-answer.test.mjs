// 答案解析的純函式部分；DOM 的部分由 e2e 覆蓋。
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { nestItems, parseAnswer, splitBold } from '../public/js/render-answer.js';
import { loadFixture } from './support/fixtures.mjs';

test('空字串與缺值不會出錯', () => {
  assert.deepEqual(parseAnswer(''), []);
  assert.deepEqual(parseAnswer(null), []);
  assert.deepEqual(parseAnswer(undefined), []);
});

test('空行分段，同段換行留在同一段', () => {
  assert.deepEqual(parseAnswer('第一行\n第二行\n\n第二段'), [
    { type: 'paragraph', lines: ['第一行', '第二行'] },
    { type: 'paragraph', lines: ['第二段'] },
  ]);
});

test('「*   」是列表，縮排記成層級；粗體開頭不是列表', () => {
  assert.deepEqual(parseAnswer('**標題**\n\n*   甲\n    *   乙\n*   丙'), [
    { type: 'paragraph', lines: ['**標題**'] },
    { type: 'list', items: [{ level: 0, text: '甲' }, { level: 4, text: '乙' }, { level: 0, text: '丙' }] },
  ]);
});

test('列表項之間的空行不會斷開列表，空行後的一般文字才另起一段', () => {
  assert.deepEqual(parseAnswer('*   甲\n\n*   乙\n\n結論'), [
    { type: 'list', items: [{ level: 0, text: '甲' }, { level: 0, text: '乙' }] },
    { type: 'paragraph', lines: ['結論'] },
  ]);
});

test('緊接在列表項後的縮排文字併入該項；沒縮排的另起一段', () => {
  assert.deepEqual(parseAnswer('*   甲\n    續\n乙'), [
    { type: 'list', items: [{ level: 0, text: '甲 續' }] },
    { type: 'paragraph', lines: ['乙'] },
  ]);
});

test('Tab 縮排也算一層', () => {
  assert.deepEqual(parseAnswer('*   甲\n\t*   乙')[0].items[1].level, 4);
});

test('CRLF 換行與真實回答都解析得出來', () => {
  assert.equal(parseAnswer('甲\r\n\r\n乙').length, 2);
  const blocks = parseAnswer(loadFixture('walk_event').answer);
  assert.deepEqual(blocks.map((block) => block.type), ['paragraph', 'paragraph', 'list', 'paragraph', 'list']);
  assert.equal(blocks[2].items.length, 3);
});

test('不改輸入、同輸入同輸出', () => {
  const text = '*   甲\n*   乙';
  assert.deepEqual(parseAnswer(text), parseAnswer(text));
  const items = Object.freeze([Object.freeze({ level: 0, text: '甲' }), Object.freeze({ level: 2, text: '乙' })]);
  assert.deepEqual(nestItems(items), [{ text: '甲', children: [{ text: '乙', children: [] }] }]);
});

test('splitBold 拆出粗體；落單的星號留成文字', () => {
  assert.deepEqual(splitBold('a **b** c'), [
    { text: 'a ', bold: false },
    { text: 'b', bold: true },
    { text: ' c', bold: false },
  ]);
  assert.deepEqual(splitBold('**全粗**'), [{ text: '全粗', bold: true }]);
  assert.deepEqual(splitBold('2 * 3 **'), [{ text: '2 * 3 **', bold: false }]);
  assert.deepEqual(splitBold(''), []);
});

test('nestItems 依縮排疊成樹，多層也行；第一項就縮排時以它為本層', () => {
  assert.deepEqual(nestItems([]), []);
  assert.deepEqual(
    nestItems([{ level: 0, text: '甲' }, { level: 2, text: '乙' }, { level: 4, text: '丙' }, { level: 0, text: '丁' }]),
    [
      { text: '甲', children: [{ text: '乙', children: [{ text: '丙', children: [] }] }] },
      { text: '丁', children: [] },
    ],
  );
  assert.deepEqual(nestItems([{ level: 4, text: '甲' }, { level: 0, text: '乙' }]), [
    { text: '甲', children: [] },
    { text: '乙', children: [] },
  ]);
});

test('模型寫成 LaTeX 的箭頭顯示成真的符號（真實回答出現過 $\\leftarrow$）', () => {
  assert.deepEqual(parseAnswer('大衛 $\\leftarrow$ 耶西 $\\rightarrow$ 俄備得'), [
    { type: 'paragraph', lines: ['大衛 ← 耶西 → 俄備得'] },
  ]);
});

test('認不得的 LaTeX 與一般錢字號原樣留著，不亂改', () => {
  assert.deepEqual(parseAnswer('$\\alpha$ 花了 $100 和 $200'), [
    { type: 'paragraph', lines: ['$\\alpha$ 花了 $100 和 $200'] },
  ]);
});
