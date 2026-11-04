import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parsePassageText, verseIsCited, verseSpan } from '../public/js/passage-text.js';
import { FIXTURE_NAMES, loadFixture } from './support/fixtures.mjs';

test('段落格式：去掉標頭，以空行分節', () => {
  const context = '[1] 使徒行傳 第15章 - 保羅和巴拿巴分手 (36-41節)\n**36** 過了些日子。\n\n**37** 巴拿巴有意。';
  assert.deepEqual(parsePassageText(context), [
    { verse: '36', text: '過了些日子。' },
    { verse: '37', text: '巴拿巴有意。' },
  ]);
});

test('單節格式：16. 開頭', () => {
  const context = '[1] 約翰福音 第3章 - 耶穌與尼哥德慕 (16節)\n16. 「上帝愛世人，反得永生。';
  assert.deepEqual(parsePassageText(context), [{ verse: '16', text: '「上帝愛世人，反得永生。' }]);
});

test('章節區塊：【標題】當小標，節照常解析', () => {
  const context = '[2] 羅馬書 第8章 (1-30節)\n【在聖靈裏的生活】\n**1** 如今。\n\n**2** 因為。\n\n【將來的榮耀】\n**18** 我想。';
  assert.deepEqual(parsePassageText(context), [
    { heading: '在聖靈裏的生活' },
    { verse: '1', text: '如今。' },
    { verse: '2', text: '因為。' },
    { heading: '將來的榮耀' },
    { verse: '18', text: '我想。' },
  ]);
});

test('詩體換行留在同一節裡，不丟字', () => {
  const context = '[4] 馬可福音 第1章 - 施洗約翰傳道 (1-8節)\n**3** 在曠野有人聲喊着說：\n預備主的道，\n修直他的路。\n\n**4** 照這話。';
  assert.deepEqual(parsePassageText(context), [
    { verse: '3', text: '在曠野有人聲喊着說：\n預備主的道，\n修直他的路。' },
    { verse: '4', text: '照這話。' },
  ]);
});

test('半節標記保留尾碼', () => {
  const context = '[1] 哥林多前書 第12章 (31節)\n**31b** 我現在把最妙的道指示你們。';
  assert.deepEqual(parsePassageText(context), [{ verse: '31b', text: '我現在把最妙的道指示你們。' }]);
});

test('節號之前的文字不丟，節號留空', () => {
  const context = '[1] 詩篇 第3章 (1-2節)\n大衛逃避他兒子押沙龍的時候作的詩。\n**1** 耶和華啊。';
  assert.deepEqual(parsePassageText(context), [
    { verse: '', text: '大衛逃避他兒子押沙龍的時候作的詩。' },
    { verse: '1', text: '耶和華啊。' },
  ]);
});

test('沒有標頭時第一行照常解析', () => {
  assert.deepEqual(parsePassageText('**1** 起初。'), [{ verse: '1', text: '起初。' }]);
});

test('空值與只有標頭回空陣列', () => {
  assert.deepEqual(parsePassageText(null), []);
  assert.deepEqual(parsePassageText(undefined), []);
  assert.deepEqual(parsePassageText(''), []);
  assert.deepEqual(parsePassageText('[1] 約翰福音 第3章 (16節)'), []);
});

for (const name of FIXTURE_NAMES) {
  test(`真實 context ${name}：節號連續、落在範圍內、內容不缺`, (t) => {
    for (const source of loadFixture(name).sources) {
      const items = parsePassageText(source.context);
      const verses = items.filter((item) => 'verse' in item);
      const [first, last = first] = source.verse_range.split('-').map(Number);
      t.diagnostic(`${source.id}: ${verses.length} 節（${source.verse_range}）`);
      assert.equal(items.length, verses.length, '這些 fixture 沒有章節區塊，不該有小標');
      assert.deepEqual(
        verses.map((item) => Number(item.verse)),
        Array.from({ length: last - first + 1 }, (_, i) => first + i),
      );
      const body = source.context.slice(source.context.indexOf('\n') + 1);
      for (const { text } of verses) {
        assert.ok(text.length > 0);
        assert.ok(body.includes(text), '文字要逐字來自原文');
        assert.ok(!text.startsWith('**'), '節號標記不可殘留');
      }
    }
  });
}

// 真實語料（struct 層 ps:gen.24.1 等 53 段）有 N-N 形狀的合併節，五份 fixture 剛好沒有
test('合併節（段落格式）：**29-30** 自成一節，不黏到前一節，也不留星號', () => {
  const context = '[1] 創世記 第24章 (1-67節)\n**28** 女子跑回去。\n\n**29-30** 利百加有一個哥哥。\n\n**31** 拉班說。';
  assert.deepEqual(parsePassageText(context), [
    { verse: '28', text: '女子跑回去。' },
    { verse: '29-30', text: '利百加有一個哥哥。' },
    { verse: '31', text: '拉班說。' },
  ]);
});

test('合併節（單節格式）：2-3. 開頭，後端的 `{label}. {text}` 也用同一種標籤', () => {
  assert.deepEqual(parsePassageText('[1] x\n2-3. 合併節內容'), [{ verse: '2-3', text: '合併節內容' }]);
});

test('verseSpan：單節、半節、合併節；沒有節號回 null', () => {
  assert.deepEqual(verseSpan('36'), { first: 36, last: 36 });
  assert.deepEqual(verseSpan('31b'), { first: 31, last: 31 });
  assert.deepEqual(verseSpan('29-30'), { first: 29, last: 30 });
  assert.equal(verseSpan(''), null);
  assert.equal(verseSpan(undefined), null);
});

test('verseIsCited：引用的節落在合併節裡就算，範圍與列舉都看', () => {
  assert.equal(verseIsCited('29-30', [[29, 29]]), true);
  assert.equal(verseIsCited('29-30', [[30, 30]]), true);
  assert.equal(verseIsCited('29-30', [[31, 31]]), false);
  assert.equal(verseIsCited('28', [[29, 29]]), false);
  assert.equal(verseIsCited('6', [[4, 4], [6, 6]]), true);
  assert.equal(verseIsCited('5', [[4, 4], [6, 6]]), false);
  assert.equal(verseIsCited('', [[1, 9]]), false);
});
