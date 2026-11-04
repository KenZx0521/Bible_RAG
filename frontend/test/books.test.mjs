import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { BOOKS, bookById, bookByName, isBookId, parseKey, formatRef } from '../public/js/books.js';

const SOURCE = new URL('../../packages/ragcommon/data/books.json', import.meta.url);

test('靜態表與 ragcommon books.json 逐欄一致', () => {
  const source = JSON.parse(readFileSync(SOURCE, 'utf8')).books;
  const expected = source.map(({ book_id, name, ord, testament }) => ({ book_id, name, ord, testament }));
  assert.equal(BOOKS.length, 66);
  assert.deepEqual(BOOKS.map((b) => ({ ...b })), expected);
});

test('BOOKS 不可被改動', () => {
  assert.ok(Object.isFrozen(BOOKS));
  assert.ok(Object.isFrozen(BOOKS[0]));
});

test('中文名與 book_id 互查', () => {
  assert.equal(bookById('act').name, '使徒行傳');
  assert.equal(bookById('1ki').name, '列王紀上');
  assert.equal(bookByName('約翰福音').book_id, 'jhn');
  assert.equal(bookByName('啟示錄').ord, 66);
  assert.equal(bookById('xxx'), undefined);
  assert.equal(bookByName('列王紀'), undefined);
});

test('isBookId 只接受表內代號', () => {
  assert.equal(isBookId('gen'), true);
  assert.equal(isBookId('2sa'), true);
  for (const bad of ['GEN', 'xyz', '', '../', 'gen ', null, undefined, 3]) {
    assert.equal(isBookId(bad), false, String(bad));
  }
  assert.equal(isBookId('__proto__'), false);
  assert.equal(isBookId('constructor'), false);
});

test('parseKey 解析經節 key（含半節）', () => {
  assert.deepEqual(parseKey('act.13.4'), { bookId: 'act', chapter: 13, verse: 4, part: '' });
  assert.deepEqual(parseKey('1co.12.31b'), { bookId: '1co', chapter: 12, verse: 31, part: 'b' });
  assert.equal(parseKey('rom.8'), null);
  assert.equal(parseKey('ps:act.13.1'), null);
  assert.equal(parseKey('zzz.1.1'), null);
  assert.equal(parseKey(null), null);
});

test('formatRef 產生讀者看得懂的出處', () => {
  assert.equal(formatRef('act.13.1', 'act.13.3'), '使徒行傳 13:1-3');
  assert.equal(formatRef('rut.4.17'), '路得記 4:17');
  assert.equal(formatRef('rut.4.17', 'rut.4.17'), '路得記 4:17');
  assert.equal(formatRef('act.13.40', 'act.14.2'), '使徒行傳 13:40-14:2');
  assert.equal(formatRef('1co.12.1', '1co.12.31a'), '哥林多前書 12:1-31a');
  assert.equal(formatRef('bad'), '');
  assert.equal(formatRef('act.13.1', 'bad'), '使徒行傳 13:1');
});
