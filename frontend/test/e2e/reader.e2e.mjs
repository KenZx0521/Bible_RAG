// 經文閱讀面板：引用、來源、段落三個入口；高亮、焦點回原處；模型自己引的節改查 /api/verse。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { assertClean, fulfillJson, loadFixture, mockAsk, openAnswer, openPage, startHarness } from './support.mjs';

const DIRECT = loadFixture('direct');
const NOT_WALKED = { status: 'not_walked', reason: null, names: [], passages: [], mentions: [], events: [] };
const KIN = loadFixture('kin');

/** 真實語料 ps:gen.24.1 的形狀：段落中有合併節；五份 fixture 剛好都沒有。 */
const MERGED_SOURCE = {
  id: 'ps:gen.24.1', kind: 'passage', book: '創世記', chapter: 24, title: '以撒和利百加', verse_range: '1-67',
  start_key: 'gen.24.1', end_key: 'gen.24.67', passage_id: 'ps:gen.24.1', member_ids: [], split_passage_ids: [],
  build_id: 'b_test',
  context: '[1] 創世記 第24章 - 以撒和利百加 (1-67節)\n**28** 女子跑回去。\n\n**29-30** 利百加有一個哥哥。\n\n**31** 拉班說。',
};

function answerWith(answer, sources) {
  return { ...DIRECT, question: answer.slice(0, 12), answer, sources, graph_trace: [], kg: NOT_WALKED, route: 'R3' };
}

const citedVerses = (page) => page.locator('.verse.is-cited').evaluateAll((nodes) => nodes.map((node) => node.dataset.verse));

const WALK = loadFixture('walk_event');

const VERSE_REPLY = {
  book_id: 'rut', book_name: '路得記', chapter: 4, verse: 17, text: '鄰舍的婦人說：「拿俄米得孩子了！」',
  pericope_title: '波阿斯和他的後代', verse_range: '17', unit_key: 'rut.4.17', status: 'present', footnote: null,
};

async function showAnswer(harness, fixture, options) {
  const opened = await openPage(harness, options);
  await mockAsk(opened.page, () => fixture);
  await openAnswer(opened.page, harness.base, fixture.question);
  return opened;
}

const activeText = (page) => page.evaluate(() => document.activeElement.textContent);

describe('經文面板', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  test('點引用開面板並高亮該節，節號上標；ESC 關閉且焦點回原處', async () => {
    const { page, context, problems } = await showAnswer(harness, WALK);
    const cite = page.locator('.cite', { hasText: '使徒行傳 13:4' }).first();
    await cite.click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-title').textContent(), '在塞浦路斯傳道');
    assert.equal(await page.locator('#reader-book').textContent(), '使徒行傳');
    assert.equal(await page.locator('#reader-numeral').textContent(), '13');
    const cited = page.locator('.verse.is-cited');
    assert.equal(await cited.count(), 1);
    assert.equal(await cited.getAttribute('data-verse'), '4');
    assert.match(await cited.textContent(), /他們既被聖靈差遣/);
    const color = await page.locator('.verse-no').first().evaluate((node) => ({ tag: node.tagName, color: getComputedStyle(node).color }));
    assert.equal(color.tag, 'SUP');
    assert.equal(color.color, 'rgb(163, 37, 23)');

    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#reader').isVisible(), false);
    assert.equal(await activeText(page), '使徒行傳 13:4');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('範圍引用高亮每一節，並捲到看得到的地方', async () => {
    const { page, context } = await showAnswer(harness, WALK, { width: 320, height: 640 });
    await page.locator('.cite', { hasText: '使徒行傳 15:39-40' }).click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(
      await page.locator('.verse.is-cited').evaluateAll((nodes) => nodes.map((node) => node.dataset.verse)),
      ['39', '40'],
    );
    const inView = await page.locator('.verse.is-cited').first().evaluate((node) => {
      const body = document.getElementById('reader-body').getBoundingClientRect();
      const rect = node.getBoundingClientRect();
      return rect.top >= body.top - 40 && rect.top <= body.bottom;
    });
    assert.equal(inView, true);
    await context.close();
  });

  test('點來源列與點段落節點開同一個面板；關閉鈕也把焦點帶回去', async () => {
    const { page, context, problems } = await showAnswer(harness, WALK);
    await page.locator('.source', { hasText: '耶路撒冷會議' }).click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-title').textContent(), '耶路撒冷會議');
    assert.equal(await page.locator('.verse.is-cited').count(), 0);
    await page.click('#reader-close');
    assert.match(await activeText(page), /耶路撒冷會議/);

    await page.locator('.node--passage', { hasText: '安提阿的教會' }).click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-title').textContent(), '安提阿的教會');
    assert.equal(await page.locator('#reader-ref').textContent(), '使徒行傳 11:19-30');
    await page.keyboard.press('Escape');
    assert.match(await activeText(page), /安提阿的教會/);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('點面板外面會關閉；面板位置：桌機右側、手機底部', async () => {
    const wide = await showAnswer(harness, WALK, { width: 1280, height: 800 });
    await wide.page.locator('.cite').first().click();
    await wide.page.waitForSelector('#reader[open]');
    await wide.page.waitForTimeout(280);
    const side = await wide.page.locator('#reader').boundingBox();
    assert.ok(side.x + side.width >= 1270 && side.height >= 790, JSON.stringify(side));
    await wide.page.mouse.click(40, 400);
    assert.equal(await wide.page.locator('#reader').isVisible(), false);
    await wide.context.close();

    const narrow = await showAnswer(harness, WALK, { width: 320, height: 640 });
    await narrow.page.locator('.cite').first().click();
    await narrow.page.waitForSelector('#reader[open]');
    await narrow.page.waitForTimeout(280);
    const sheet = await narrow.page.locator('#reader').boundingBox();
    assert.ok(sheet.y + sheet.height >= 638 && sheet.width >= 318, JSON.stringify(sheet));
    assert.ok(sheet.y > 0, '手機面板從底部升起，不蓋滿');
    await narrow.context.close();
  });

  test('模型自己引的節（不在來源裡）改查 /api/verse，顯示實際經文', async () => {
    const answer = { ...DIRECT, answer: '可參考路得記 4:17 的記載。' };
    const { page, context, problems } = await showAnswer(harness, answer);
    const requested = [];
    await page.route('**/api/verse/**', (route) => {
      requested.push(new URL(route.request().url()).pathname);
      return fulfillJson(route, 200, VERSE_REPLY);
    });
    await page.locator('.cite', { hasText: '路得記 4:17' }).click();
    await page.waitForSelector('.verse.is-cited');
    assert.deepEqual(requested, ['/api/verse/rut/4/17']);
    assert.equal(await page.locator('#reader-title').textContent(), '波阿斯和他的後代');
    assert.match(await page.locator('.verse.is-cited').textContent(), /拿俄米得孩子了/);
    assert.match(await page.locator('.reader-note').textContent(), /不在這題找到的經文來源裡/);
    await page.keyboard.press('Escape');
    assert.equal(await activeText(page), '路得記 4:17');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('查無此節顯示「找不到這節經文」；服務失敗顯示稍後再試', async () => {
    const answer = { ...DIRECT, answer: '可參考路得記 4:99，以及路得記 3:1。' };
    const { page, context, problems } = await showAnswer(harness, answer);
    await page.route('**/api/verse/rut/4/99', (route) => fulfillJson(route, 404, { error: '找不到這節經文' }));
    await page.route('**/api/verse/rut/3/1', (route) => fulfillJson(route, 502, { error: 'x' }));
    await page.locator('.cite', { hasText: '路得記 4:99' }).click();
    await page.waitForSelector('.reader-message:not(.is-loading)');
    assert.equal(await page.locator('.reader-message').textContent(), '找不到這節經文');
    await page.keyboard.press('Escape');
    await page.locator('.cite', { hasText: '路得記 3:1' }).click();
    await page.waitForFunction(() => /稍後再試/.test(document.getElementById('reader-body').textContent));
    await assertClean(assert, page, problems, { allowHttpErrors: true });
    await context.close();
  });

  test('連續開兩節：慢的舊回應不會蓋掉新的內容', async () => {
    const answer = { ...DIRECT, answer: '路得記 4:17 與路得記 3:1。' };
    const { page, context } = await showAnswer(harness, answer);
    let releaseSlow;
    const slow = new Promise((resolve) => { releaseSlow = resolve; });
    await page.route('**/api/verse/rut/4/17', async (route) => {
      await slow;
      await fulfillJson(route, 200, { ...VERSE_REPLY, text: '舊的回應' }).catch(() => {});
    });
    await page.route('**/api/verse/rut/3/1', (route) => fulfillJson(route, 200, { ...VERSE_REPLY, verse: 1, verse_range: '1', unit_key: 'rut.3.1', text: '新的回應' }));
    await page.locator('.cite', { hasText: '路得記 4:17' }).click();
    await page.keyboard.press('Escape');
    await page.locator('.cite', { hasText: '路得記 3:1' }).click();
    await page.waitForSelector('.verse.is-cited');
    releaseSlow();
    await page.waitForTimeout(100);
    assert.match(await page.locator('#reader-body').textContent(), /新的回應/);
    assert.doesNotMatch(await page.locator('#reader-body').textContent(), /舊的回應/);
    await context.close();
  });

  test('無法解析的文字不會變成按鈕；經文[N] 開第 N 個來源', async () => {
    const answer = {
      ...WALK,
      answer: '只寫到章的馬可福音 第2章不算引用，「列王紀」也不算；經文[2] 才算，經文[99] 不算。',
    };
    const { page, context } = await showAnswer(harness, answer);
    assert.deepEqual(await page.locator('.cite').allTextContents(), ['經文[2]']);
    assert.match(await page.locator('#answer').textContent(), /馬可福音 第2章/);
    assert.match(await page.locator('#answer').textContent(), /經文\[99\]/);
    await page.locator('.cite').click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-title').textContent(), WALK.sources[1].title);
    await context.close();
  });

  test('完整圖譜裡沒進答案的段落：查 /api/verse 並說明它沒用在答案裡', async () => {
    const { page, context, problems } = await showAnswer(harness, WALK);
    const verses = [];
    await page.route('**/api/verse/**', (route) => {
      const [, , , book, chapter, verse] = new URL(route.request().url()).pathname.split('/');
      verses.push(Number(verse));
      return fulfillJson(route, 200, { ...VERSE_REPLY, book_id: book, chapter: Number(chapter), verse: Number(verse), verse_range: verse, unit_key: `${book}.${chapter}.${verse}`, text: `第${verse}節` });
    });
    await page.click('.hint-toggle');
    const unused = page.locator('.node.is-unused').first();
    const title = await unused.locator('.node-title').textContent();
    await unused.click();
    await page.waitForSelector('.reader-note');
    assert.equal(await page.locator('#reader-title').textContent(), title);
    assert.match(await page.locator('.reader-note').textContent(), /沒有用在答案裡/);
    assert.ok(verses.length >= 1 && verses.length <= 12, `最多查 12 節：${verses.length}`);
    assert.equal(await page.locator('.verse.is-cited').count(), 0);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('合併節：引第 29、30 節都高亮「29-30」，面板沒有星號；下一節照常', async () => {
    const fixture = answerWith('拉班出來（創世記 24:29）。金環見創世記 24:30，下一節是創世記 24:31。', [MERGED_SOURCE]);
    const { page, context, problems } = await showAnswer(harness, fixture);
    const cites = page.locator('.cite');
    for (const [index, expected] of [[0, ['29-30']], [1, ['29-30']], [2, ['31']]]) {
      await cites.nth(index).click();
      await page.waitForSelector('#reader[open]');
      assert.deepEqual(await citedVerses(page), expected);
      assert.doesNotMatch(await page.locator('#reader-body').textContent(), /\*\*/);
      await page.keyboard.press('Escape');
    }
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('模型自己引的長範圍：只列前 12 節時面板要照實說', async () => {
    const fixture = answerWith('見使徒行傳 28:1-20。', []);
    const { page, context, problems } = await showAnswer(harness, fixture);
    const requested = [];
    await page.route('**/api/verse/**', (route) => {
      const verse = Number(new URL(route.request().url()).pathname.split('/').at(-1));
      requested.push(verse);
      return fulfillJson(route, 200, { ...VERSE_REPLY, book_id: 'act', chapter: 28, verse, verse_range: String(verse), unit_key: `act.28.${verse}`, text: `第${verse}節` });
    });
    await page.locator('.cite').click();
    await page.waitForSelector('.verse.is-cited');
    assert.equal(requested.length, 12);
    assert.equal(await page.locator('#reader-ref').textContent(), '使徒行傳 28:1-20');
    assert.match(await page.locator('.reader-note').textContent(), /只列前 12 節/);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('範圍引用：開涵蓋整段的來源，兩節都高亮', async () => {
    const fixture = answerWith('約翰福音 3:16-17 說得很清楚。', DIRECT.sources);
    const { page, context } = await showAnswer(harness, fixture);
    await page.locator('.cite').click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(await citedVerses(page), ['16', '17']);
    assert.equal(await page.locator('#reader-ref').textContent(), '約翰福音 3:1-21');
    assert.equal(await page.locator('.reader-note').count(), 0, '完整就不必多說');
    await context.close();
  });

  test('範圍超出來源尾端：照開，並說明缺哪幾節', async () => {
    const source = {
      ...MERGED_SOURCE, id: 'ps:1ki.15.25', book: '列王紀上', chapter: 15, start_key: '1ki.15.25', end_key: '1ki.15.32', passage_id: 'ps:1ki.15.25',
      context: '[1] 列王紀上 第15章 (25-32節)\n**30** 三十。\n\n**31** 三一。\n\n**32** 三二。',
    };
    const { page, context } = await showAnswer(harness, answerWith('見列王紀上 15:30-40。', [source]));
    await page.locator('.cite').click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(await citedVerses(page), ['30', '31', '32']);
    assert.equal(await page.locator('.reader-note').textContent(), '答案引的第 33-40 節不在這段來源裡。');
    await context.close();
  });

  test('列舉式引用：整串是一顆按鈕，每一段都高亮', async () => {
    const fixture = answerWith('見使徒行傳 第13章 4節、6節，以及使徒行傳 第15章 38-39節、41節。', WALK.sources);
    const { page, context } = await showAnswer(harness, fixture);
    await page.locator('.cite').nth(0).click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(await citedVerses(page), ['4', '6']);
    await page.keyboard.press('Escape');
    await page.locator('.cite').nth(1).click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(await citedVerses(page), ['38', '39', '41']);
    await context.close();
  });

  test('模型自己引的列舉：每一段都查，標頭照實寫', async () => {
    const { page, context } = await showAnswer(harness, answerWith('見羅馬書 第8章 28節、31節。', []));
    const requested = [];
    await page.route('**/api/verse/**', (route) => {
      const verse = Number(new URL(route.request().url()).pathname.split('/').at(-1));
      requested.push(verse);
      return fulfillJson(route, 200, { ...VERSE_REPLY, book_id: 'rom', chapter: 8, verse, verse_range: String(verse), unit_key: `rom.8.${verse}`, text: `第${verse}節` });
    });
    await page.locator('.cite').click();
    await page.waitForSelector('.verse.is-cited');
    assert.deepEqual(requested, [28, 31]);
    assert.equal(await page.locator('#reader-ref').textContent(), '羅馬書 8:28、31');
    await context.close();
  });

  test('面板開著時背景不跟著捲', async () => {
    const { page, context } = await showAnswer(harness, WALK, { width: 1024, height: 500 });
    await page.locator('.source').first().click();
    await page.waitForSelector('#reader[open]');
    const opened = await page.evaluate(() => window.scrollY);
    await page.mouse.move(100, 300);
    await page.mouse.wheel(0, -200);
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(() => window.scrollY), opened, '滾輪在背景上不捲頁面，位置也不跳');
    await page.keyboard.press('Escape');
    await page.mouse.wheel(0, -200);
    await page.waitForFunction((from) => window.scrollY < from, opened);
    await context.close();
  });

  test('面板開著時視窗改寬度（旋轉手機）：關閉後焦點回到重畫後的同一個節點', async () => {
    const { page, context } = await showAnswer(harness, WALK, { width: 1024, height: 768 });
    const title = '安提阿的教會';
    await page.locator('.node--passage', { hasText: title }).click();
    await page.waitForSelector('#reader[open]');
    await page.setViewportSize({ width: 800, height: 768 });
    await page.waitForFunction(() => document.querySelector('.node--passage')?.offsetWidth > 0);
    await page.waitForTimeout(100);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement?.classList.contains('node'));
    assert.match(await activeText(page), new RegExp(title));
    await context.close();
  });

  test('親屬標籤開的面板：重畫後焦點也回到同一個標籤', async () => {
    const { page, context } = await showAnswer(harness, KIN, { width: 1024, height: 768 });
    const label = page.locator('.edge-label').first();
    const title = await label.getAttribute('title');
    await label.click();
    await page.waitForSelector('#reader[open]');
    await page.setViewportSize({ width: 800, height: 768 });
    await page.waitForTimeout(150);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.activeElement?.classList.contains('edge-label'));
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('title')), title);
    await context.close();
  });

  test('reduced-motion：面板背景也不淡入', async () => {
    const { page, context } = await showAnswer(harness, WALK, { reducedMotion: 'reduce' });
    await page.locator('.source').first().click();
    await page.waitForSelector('#reader[open]');
    const backdrop = await page.locator('#reader').evaluate((node) => getComputedStyle(node, '::backdrop').animationName);
    assert.equal(backdrop, 'none');
    await context.close();
  });
});
