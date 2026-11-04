import { test } from 'node:test';
import assert from 'node:assert/strict';
import { citedSpans, findCitations, formatCitedRef, formatVerseList, resolveCitation } from '../public/js/citations.js';
import { FIXTURE_NAMES, loadFixture } from './support/fixtures.mjs';

function only(text) {
  const found = findCitations(text);
  assert.equal(found.length, 1, `應該剛好抓到一筆：${text} → ${JSON.stringify(found)}`);
  assert.equal(text.slice(found[0].start, found[0].end), found[0].raw, 'start/end 要對回原文');
  return found[0];
}

// 契約列的每一種真實寫法
const CONTRACT_FORMS = [
  ['使徒行傳 13:4', { bookId: 'act', bookName: '使徒行傳', chapter: 13, verse: 4 }],
  ['使徒行傳 13:1-3', { bookId: 'act', chapter: 13, verse: 1, verseEnd: 3 }],
  ['路得記 4:17', { bookId: 'rut', bookName: '路得記', chapter: 4, verse: 17 }],
  ['列王紀上 第22章 41節', { bookId: '1ki', bookName: '列王紀上', chapter: 22, verse: 41 }],
  ['列王紀上 第15章 27-28節', { bookId: '1ki', chapter: 15, verse: 27, verseEnd: 28 }],
  ['創世記 第5章 第5節', { bookId: 'gen', chapter: 5, verse: 5 }],
  ['歷代志上 第1章 第1-4節', { bookId: '1ch', chapter: 1, verse: 1, verseEnd: 4 }],
  ['約翰福音 第3章 16節', { bookId: 'jhn', chapter: 3, verse: 16 }],
  ['詩篇 第23篇 1節', { bookId: 'psa', bookName: '詩篇', chapter: 23, verse: 1 }],
];

for (const [text, expected] of CONTRACT_FORMS) {
  test(`契約寫法：${text}`, () => {
    const got = only(text);
    assert.equal(got.raw, text);
    for (const [key, value] of Object.entries(expected)) assert.equal(got[key], value, key);
    if (!('verseEnd' in expected)) assert.equal(got.verseEnd, undefined);
    assert.equal(got.block, undefined);
  });
}

test('契約寫法：全形括號包住的引用，括號不算在 raw 裡', () => {
  const text = '差遣他們（使徒行傳 15:3-4）。';
  const got = only(text);
  assert.equal(got.raw, '使徒行傳 15:3-4');
  assert.equal(got.start, text.indexOf('使徒行傳'));
  assert.deepEqual([got.chapter, got.verse, got.verseEnd], [15, 3, 4]);
});

test('契約寫法：創世記 第28章 [3]，[3] 是第 3 個 source', () => {
  const got = only('見創世記 第28章 [3]。');
  assert.equal(got.raw, '創世記 第28章 [3]');
  assert.deepEqual([got.bookId, got.chapter, got.block], ['gen', 28, 3]);
  assert.equal(got.verse, undefined);
});

test('契約寫法：經文[1]，沒有書名，只有 source 編號', () => {
  const got = only('如經文[1]所示');
  assert.equal(got.raw, '經文[1]');
  assert.equal(got.block, 1);
  assert.equal(got.bookId, null);
  assert.equal(got.bookName, null);
  assert.equal(got.chapter, null);
});

// 500 題真實回答掃出來、契約沒列但確實出現的變體
const SCANNED_FORMS = [
  ['約翰一書第1章9節', { bookId: '1jn', chapter: 1, verse: 9 }],
  ['約翰福音第14章第6節', { bookId: 'jhn', chapter: 14, verse: 6 }],
  ['以弗所書第2章8-9節', { bookId: 'eph', chapter: 2, verse: 8, verseEnd: 9 }],
  ['列王紀上 1章 5節', { bookId: '1ki', chapter: 1, verse: 5 }],
  ['耶利米書 第1章 13節-14節', { bookId: 'jer', chapter: 1, verse: 13, verseEnd: 14 }],
  ['加拉太書第5章第22至23節', { bookId: 'gal', chapter: 5, verse: 22, verseEnd: 23 }],
  ['約翰一書 第4章 7, 8節', { bookId: '1jn', chapter: 4, verse: 7 }],
  ['以西結書 第37章 13節、14節', { bookId: 'ezk', chapter: 37, verse: 13 }],
  ['歷代志下第32章（24-26節）', { bookId: '2ch', chapter: 32, verse: 24, verseEnd: 26 }],
  ['約翰福音 第19章 (39節)', { bookId: 'jhn', chapter: 19, verse: 39 }],
  ['詩篇第23章 1節', { bookId: 'psa', chapter: 23, verse: 1 }],
  ['約翰福音 3：16', { bookId: 'jhn', chapter: 3, verse: 16 }],
  ['約翰福音　3:16', { bookId: 'jhn', chapter: 3, verse: 16 }],
  ['馬太福音 6:1–2', { bookId: 'mat', chapter: 6, verse: 1, verseEnd: 2 }],
  ['《路加福音》第11章第28節', { bookId: 'luk', bookName: '路加福音', chapter: 11, verse: 28 }],
  ['《以弗所書》第4章26節', { bookId: 'eph', chapter: 4, verse: 26 }],
];

for (const [text, expected] of SCANNED_FORMS) {
  test(`真實變體：${text}`, () => {
    const got = only(text);
    assert.equal(got.raw, text);
    for (const [key, value] of Object.entries(expected)) assert.equal(got[key], value, key);
    if (!('verseEnd' in expected)) assert.equal(got.verseEnd, undefined);
  });
}

test('真實變體：逗號接下一節時只引第一段，後面留成文字', () => {
  assert.equal(only('希伯來書 11:23, 25').raw, '希伯來書 11:23');
  assert.equal(only('列王紀上 21:19, 21:21').raw, '列王紀上 21:19');
});

test('真實變體：方括號包住的引用，括號不算在 raw 裡', () => {
  assert.equal(only('[約翰福音 15:1]').raw, '約翰福音 15:1');
  assert.equal(only('[希伯來書 第8章 5節]。').raw, '希伯來書 第8章 5節');
});

test('同一段文字多筆引用，依出現順序且不重疊', () => {
  const text = '民數記 23:1-12；民數記 24:3 與馬太福音 第5章 3節，還有經文[2]。';
  const found = findCitations(text);
  assert.deepEqual(found.map((c) => c.raw), ['民數記 23:1-12', '民數記 24:3', '馬太福音 第5章 3節', '經文[2]']);
  for (const c of found) assert.equal(text.slice(c.start, c.end), c.raw);
  for (let i = 1; i < found.length; i += 1) assert.ok(found[i].start >= found[i - 1].end);
});

// 反例：一律不算引用，不准變成按鈕
const NOT_CITATIONS = [
  '第一次', '保羅第一次宣教旅程', '使徒行傳第一次', '3個人', '共有 3個人', '1856年', '西元 1856年',
  '路得記 4個人', '詩篇 1856年', '創世記 第5章 3個人',
  '[3]', '如[3]所說', '使徒之一 [3]', '[0]', '經文[0]', '經文', '經文[]', '經文[a]',
  '13:4', '第5章 3節', '第3章', '創世記 3', '約翰福音 3', '創世記', '使徒行傳',
  '創世記 第28章', '馬可福音 第2章。', '創世記 第28章 [0]', '《箴言》第27章', '《箴言》',
  '列王紀 3:4', '列王紀 第5章 3節', '歷代志 第1章 3節', '撒母耳記 16:7', '約翰 3:16',
  '使徒行傳 0:1', '使徒行傳 13:0', '使徒行傳 13:4567', '創世記\n3:4', '第0章 第0節',
  '', '尚無引用的一般句子。',
];

for (const text of NOT_CITATIONS) {
  test(`反例不算引用：${JSON.stringify(text)}`, () => {
    assert.deepEqual(findCitations(text), []);
  });
}

test('倒過來或相等的範圍不當範圍；跨章範圍只取起點', () => {
  const reversed = only('使徒行傳 13:5-3');
  assert.deepEqual([reversed.verse, reversed.verseEnd], [5, undefined]);
  assert.equal(only('使徒行傳 13:5-5').verseEnd, undefined);
  assert.equal(only('列王紀上 第15章 28-27節').verseEnd, undefined);
  const cross = only('使徒行傳 13:1-14:2');
  assert.equal(cross.raw, '使徒行傳 13:1');
  assert.deepEqual([cross.chapter, cross.verse, cross.verseEnd], [13, 1, undefined]);
});

test('不是字串回空陣列', () => {
  assert.deepEqual(findCitations(null), []);
  assert.deepEqual(findCitations(undefined), []);
  assert.deepEqual(findCitations(42), []);
});

test('連續呼叫結果相同（全域 regex 不殘留狀態）', () => {
  const text = '使徒行傳 13:4、路得記 4:17';
  assert.deepEqual(findCitations(text), findCitations(text));
  assert.equal(findCitations(text).length, 2);
});

// fixtures 的答案全部掃過，把抓到的引用印出來人工確認
const EXPECTED_IN_FIXTURES = {
  walk_event: ['使徒行傳 13:1-3', '使徒行傳 13:7', '使徒行傳 15:38-39', '使徒行傳 15:39-40',
    '使徒行傳 13:4', '使徒行傳 13:5', '使徒行傳 13:6', '使徒行傳 15:41'],
  walk_plain: ['馬可福音 第1章 9節', '馬太福音 第3章 13節'],
  kin: ['路得記 4:17', '路得記 4:21', '路得記 4:21'],
  direct: ['約翰福音 第3章 16節', '約翰福音 第3章 16節'],
  regnal: [],
};

for (const name of FIXTURE_NAMES) {
  test(`真實答案 ${name} 的引用`, (t) => {
    const resp = loadFixture(name);
    const found = findCitations(resp.answer);
    t.diagnostic(`${name}: ${found.map((c) => c.raw).join(' ｜ ') || '（沒有引用）'}`);
    assert.deepEqual(found.map((c) => c.raw), EXPECTED_IN_FIXTURES[name]);
  });

  test(`真實答案 ${name} 的引用都對回 sources 裡涵蓋該節的段落`, (t) => {
    const resp = loadFixture(name);
    for (const citation of findCitations(resp.answer)) {
      const hit = resolveCitation(citation, resp.sources);
      assert.equal(hit.type, 'source', citation.raw);
      const source = resp.sources[hit.sourceIndex];
      t.diagnostic(`${citation.raw} → [${hit.sourceIndex + 1}] ${source.book} ${source.verse_range}`);
      assert.equal(source.book, citation.bookName);
      assert.equal(source.chapter, citation.chapter);
      const [first, last = first] = source.verse_range.split('-').map(Number);
      assert.ok(first <= citation.verse && citation.verse <= last, citation.raw);
      assert.equal(hit.verse, citation.verse);
      assert.equal(hit.verseEnd, citation.verseEnd);
    }
  });
}

const GEN_28 = { book: '創世記', chapter: 28, start_key: 'gen.28.1', end_key: 'gen.28.9' };
const JHN_3 = { book: '約翰福音', chapter: 3, start_key: 'jhn.3.1', end_key: 'jhn.3.21' };
const ROM_8_BLOCK = { book: '羅馬書', chapter: 8, kind: 'chapter', start_key: 'rom.8.1', end_key: 'rom.8.39' };
const COR_HALF = { book: '哥林多前書', chapter: 12, start_key: '1co.12.1', end_key: '1co.12.31a' };

function resolve(text, sources) {
  return resolveCitation(findCitations(text)[0], sources);
}

test('resolveCitation：[N] 只要書卷章相符就開第 N 個 source', () => {
  assert.deepEqual(resolve('創世記 第28章 [2]', [JHN_3, GEN_28]), { type: 'source', sourceIndex: 1 });
  assert.deepEqual(resolve('經文[1]', [JHN_3]), { type: 'source', sourceIndex: 0 });
});

test('resolveCitation：[N] 與書名不符時改依書卷章找', () => {
  assert.deepEqual(resolve('創世記 第28章 [1]', [JHN_3, GEN_28]), { type: 'source', sourceIndex: 1 });
});

test('resolveCitation：無法解析的編號回 null，不准變按鈕', () => {
  assert.equal(resolve('經文[9]', [JHN_3]), null);
  assert.equal(resolve('創世記 第28章 [3]', [JHN_3]), null);
  assert.equal(resolve('經文[1]', []), null);
});

test('resolveCitation：對不到 sources 就回查經文 API 需要的欄位', () => {
  assert.deepEqual(resolve('羅馬書 8:28', [JHN_3]), { type: 'verse', bookId: 'rom', chapter: 8, verse: 28 });
  assert.deepEqual(resolve('約翰福音 3:30-31', [JHN_3]), {
    type: 'verse', bookId: 'jhn', chapter: 3, verse: 30, verseEnd: 31,
  });
});

test('resolveCitation：章區塊與半節結尾的 source 也算涵蓋', () => {
  assert.deepEqual(resolve('羅馬書 第8章 28-30節', [ROM_8_BLOCK]), {
    type: 'source', sourceIndex: 0, verse: 28, verseEnd: 30,
  });
  assert.deepEqual(resolve('哥林多前書 12:31', [COR_HALF]), { type: 'source', sourceIndex: 0, verse: 31 });
});

test('resolveCitation：缺 key 的 source 不會被誤認', () => {
  assert.deepEqual(resolve('約翰福音 3:16', [{ book: '約翰福音', chapter: 3 }]), {
    type: 'verse', bookId: 'jhn', chapter: 3, verse: 16,
  });
});

// ---- 列舉：按鈕涵蓋整串，每一段都要算數 ----

test('列舉式引用：ranges 列出每一段，verse／verseEnd 仍是第一段', () => {
  const list = only('使徒行傳 第13章 4節、6節');
  assert.deepEqual([list.verse, list.verseEnd, list.ranges], [4, undefined, [[4, 4], [6, 6]]]);
  const mixed = only('使徒行傳 第15章 38-39節、41節');
  assert.deepEqual([mixed.verse, mixed.verseEnd, mixed.ranges], [38, 39, [[38, 39], [41, 41]]]);
  const paren = only('歷代志下第32章（24-26節、第30節）');
  assert.deepEqual(paren.ranges, [[24, 26], [30, 30]]);
  assert.deepEqual(only('約翰一書 第4章 7, 8節').ranges, [[7, 7], [8, 8]]);
});

test('單段引用沒有 ranges 欄位；倒過來的段當單節', () => {
  assert.equal('ranges' in only('使徒行傳 第13章 4節'), false);
  assert.equal('ranges' in only('使徒行傳 13:1-3'), false);
  assert.deepEqual(only('使徒行傳 第13章 9-7節、4節').ranges, [[9, 9], [4, 4]]);
});

// ---- 範圍：要找涵蓋整段的來源 ----

const VERSE_16 = { id: 'vs:jhn.3.16', start_key: 'jhn.3.16', end_key: 'jhn.3.16' };
const JHN_3_1_21 = { id: 'ps:jhn.3.1', start_key: 'jhn.3.1', end_key: 'jhn.3.21' };
const KGS_15 = { id: 'ps:1ki.15.25', start_key: '1ki.15.25', end_key: '1ki.15.32' };

test('範圍引用：第一個來源只有起點那節時，開涵蓋整段的來源', () => {
  assert.deepEqual(resolve('約翰福音 3:16-17', [VERSE_16, JHN_3_1_21]), {
    type: 'source', sourceIndex: 1, verse: 16, verseEnd: 17,
  });
  assert.deepEqual(resolve('約翰福音 第3章 16-18節', [VERSE_16, JHN_3_1_21]), {
    type: 'source', sourceIndex: 1, verse: 16, verseEnd: 18,
  });
});

test('單節引用維持開第一個涵蓋的來源', () => {
  assert.deepEqual(resolve('約翰福音 3:16', [VERSE_16, JHN_3_1_21]), { type: 'source', sourceIndex: 0, verse: 16 });
});

test('範圍超出來源尾端：照開，但要帶 missing 讓面板照實說', () => {
  assert.deepEqual(resolve('列王紀上 15:30-40', [KGS_15]), {
    type: 'source', sourceIndex: 0, verse: 30, verseEnd: 40, missing: [[33, 40]],
  });
});

test('都不完整時開缺得最少的來源', () => {
  const short = { id: 'a', start_key: 'jhn.3.16', end_key: 'jhn.3.16' };
  const longer = { id: 'b', start_key: 'jhn.3.16', end_key: 'jhn.3.18' };
  assert.deepEqual(resolve('約翰福音 3:16-20', [short, longer]), {
    type: 'source', sourceIndex: 1, verse: 16, verseEnd: 20, missing: [[19, 20]],
  });
});

test('列舉有一段落在來源起點之前：照實列出缺的那段', () => {
  assert.deepEqual(resolve('列王紀上 第15章 27節、3節', [KGS_15]), {
    type: 'source', sourceIndex: 0, verse: 27, ranges: [[27, 27], [3, 3]], missing: [[3, 3]],
  });
});

test('跨章的來源：只看引用那一章涵蓋到哪', () => {
  const spanning = { id: 'x', start_key: 'act.12.25', end_key: 'act.13.3' };
  assert.deepEqual(resolve('使徒行傳 13:1-3', [spanning]), { type: 'source', sourceIndex: 0, verse: 1, verseEnd: 3 });
  assert.deepEqual(resolve('使徒行傳 12:25-30', [spanning]), { type: 'source', sourceIndex: 0, verse: 25, verseEnd: 30 });
  assert.deepEqual(resolve('使徒行傳 13:2-5', [spanning]), {
    type: 'source', sourceIndex: 0, verse: 2, verseEnd: 5, missing: [[4, 5]],
  });
});

test('列舉：要找涵蓋每一段的來源，找不到就標 missing', () => {
  const short = { id: 'a', start_key: 'act.15.36', end_key: 'act.15.40' };
  const long = { id: 'b', start_key: 'act.15.36', end_key: 'act.15.41' };
  assert.deepEqual(resolve('使徒行傳 第15章 38-39節、41節', [short, long]), {
    type: 'source', sourceIndex: 1, verse: 38, verseEnd: 39, ranges: [[38, 39], [41, 41]],
  });
  assert.deepEqual(resolve('使徒行傳 第15章 38-39節、41節', [short]), {
    type: 'source', sourceIndex: 0, verse: 38, verseEnd: 39, ranges: [[38, 39], [41, 41]], missing: [[41, 41]],
  });
});

test('對不到來源的列舉帶著 ranges 去查經文', () => {
  assert.deepEqual(resolve('羅馬書 第8章 28節、31節', [JHN_3_1_21]), {
    type: 'verse', bookId: 'rom', chapter: 8, verse: 28, ranges: [[28, 28], [31, 31]],
  });
});

test('citedSpans：target → 要高亮的每一段；沒有節回空陣列', () => {
  assert.deepEqual(citedSpans({ verse: 4 }), [[4, 4]]);
  assert.deepEqual(citedSpans({ verse: 1, verseEnd: 3 }), [[1, 3]]);
  assert.deepEqual(citedSpans({ verse: 4, ranges: [[4, 4], [6, 6]] }), [[4, 4], [6, 6]]);
  assert.deepEqual(citedSpans({}), []);
});

test('formatVerseList：missing 欄位的文字', () => {
  assert.equal(formatVerseList([[33, 40]]), '33-40');
  assert.equal(formatVerseList([[3, 3], [33, 40]]), '3、33-40');
});

test('formatCitedRef：單節、範圍、列舉', () => {
  assert.equal(formatCitedRef({ bookId: 'act', chapter: 28, verse: 1 }), '使徒行傳 28:1');
  assert.equal(formatCitedRef({ bookId: 'act', chapter: 28, verse: 1, verseEnd: 20 }), '使徒行傳 28:1-20');
  assert.equal(formatCitedRef({ bookId: 'act', chapter: 13, verse: 4, ranges: [[4, 4], [6, 8]] }), '使徒行傳 13:4、6-8');
});

// ---- 答案是 LLM 輸出，沒有長度上限，也不能讓 regex 回溯到凍結分頁 ----

const SLOW_MS = 200;
const ADVERSARIAL = {
  逗號列舉不收尾: `創世記 第1章 ${Array.from({ length: 5000 }, (_, i) => (i % 900) + 1).join(', ')}。`,
  空白逗號列舉: `創世記 第1章 ${Array.from({ length: 5000 }, () => '1').join(' , ')}。`,
  空白連字號列舉: `創世記 第1章 ${Array.from({ length: 5000 }, () => '1').join(' - ')}。`,
  節字列舉: `創世記 第1章 ${Array.from({ length: 5000 }, () => '1').join(' 節 , ')} x`,
  第字列舉: `創世記 第1章 ${Array.from({ length: 5000 }, () => '1').join(' , 第 ')} x`,
  書名後一長串空白: `創世記${' '.repeat(100_000)}x`,
  第字後一長串空白: `創世記 第${' '.repeat(100_000)}x`,
  章後一長串空白: `創世記 第1章${' '.repeat(100_000)}x`,
  章後第字一長串空白: `創世記 第1章 第${' '.repeat(100_000)}x`,
  節前一長串空白: `創世記 第1章 1${' '.repeat(100_000)}x`,
  括號後一長串空白: `創世記 第1章（${' '.repeat(100_000)}x`,
  範圍前一長串空白: `創世記 3:1${' '.repeat(100_000)}x`,
  重複書名: '創世記 第1章 1, '.repeat(5000),
};

for (const [name, text] of Object.entries(ADVERSARIAL)) {
  test(`惡意輸入不回溯：${name}（${text.length} 字）`, () => {
    const started = performance.now();
    findCitations(text);
    const elapsed = performance.now() - started;
    assert.ok(elapsed < SLOW_MS, `花了 ${elapsed.toFixed(1)}ms`);
  });
}

test('修掉回溯後，列舉收尾有「節」仍抓得到整串', () => {
  const got = only('創世記 第1章 1, 2 , 3 節 - 第 4、5 節。');
  assert.equal(got.raw, '創世記 第1章 1, 2 , 3 節 - 第 4、5 節');
  assert.deepEqual(got.ranges, [[1, 1], [2, 2], [3, 4], [5, 5]]);
});
