// 經文面板與圖的對應：卡片標的範圍＝點開看得到的範圍；手機按上一頁只關面板。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { assertClean, loadFixture, mockAsk, openAnswer, openPage, startHarness } from './support.mjs';

const WALK = loadFixture('walk_event');
const KIN = loadFixture('kin');

const citedVerses = (page) => page.locator('.verse.is-cited').evaluateAll((nodes) => nodes.map((node) => node.dataset.verse));

async function showAnswer(harness, fixture, options) {
  const opened = await openPage(harness, options);
  await mockAsk(opened.page, () => fixture);
  await openAnswer(opened.page, harness.base, fixture.question);
  return opened;
}

describe('面板與圖、與歷史紀錄', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  // ---- 節點標的範圍要和點開的內容一致 ----

  /** 打開這個範例的每一張用到的卡片（含完整圖），比對卡片標的範圍、面板的範圍、實際的節。 */
  async function assertCardsMatchReader(page, tabName) {
    if (tabName) await page.locator('.segment', { hasText: tabName }).click();
    const toggle = page.locator('.hint-toggle');
    if ((await toggle.count()) > 0 && await toggle.isVisible()) await toggle.click();
    const cards = page.locator('.node--passage:not(.is-unused)');
    const total = await cards.count();
    assert.ok(total > 0);
    for (let i = 0; i < total; i += 1) {
      const card = cards.nth(i);
      const ref = /（(.+)）$/.exec(await card.getAttribute('title'))[1];
      await card.click();
      await page.waitForSelector('#reader[open]');
      assert.equal(await page.locator('#reader-ref').textContent(), ref, await card.getAttribute('title'));
      const verses = await page.locator('#reader-body .verse').evaluateAll((nodes) => nodes.map((node) => node.dataset.verse));
      const span = /:(\d+)(?:-(\d+))?$/.exec(ref);
      const [first, last] = [Number(span[1]), Number(span[2] ?? span[1])];
      const numbers = verses.flatMap((verse) => verse.split('-').map(Number));
      assert.equal(Math.min(...numbers), first, `${ref} 第一節`);
      assert.equal(Math.max(...numbers), last, `${ref} 最後一節`);
      await page.keyboard.press('Escape');
    }
  }

  for (const [label, fixture, tab] of [
    ['保羅', WALK, null],
    ['受洗', loadFixture('walk_plain'), null],
    ['親屬', KIN, '答案怎麼找到的'],
    ['年表', loadFixture('regnal'), '答案怎麼找到的'],
  ]) {
    test(`${label}範例：每張用到的卡片，標的範圍＝面板範圍＝實際顯示的節`, async () => {
      const { page, context, problems } = await showAnswer(harness, fixture, { width: 1280, height: 900 });
      await assertCardsMatchReader(page, tab);
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('受洗範例：「耶穌和撒馬利亞婦人」只有 chunk 來源，卡片就標 4:1-20，不再寫 4:1-42', async () => {
    const { page, context } = await showAnswer(harness, loadFixture('walk_plain'));
    const node = page.locator('.node--passage', { hasText: '耶穌和撒馬利亞婦人' });
    assert.match(await node.getAttribute('title'), /約翰福音 4:1-20/);
    await node.click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-ref').textContent(), '約翰福音 4:1-20');
    await context.close();
  });

  test('章節區塊裡的段落：卡片標段落範圍，面板開整章並高亮那幾節', async () => {
    const plain = loadFixture('walk_plain');
    const passage = plain.kg.passages.find((item) => item.id === 'ps:mrk.1.9');
    const block = {
      id: 'mrk.1', kind: 'chapter', book: '馬可福音', chapter: 1, title: '', verse_range: '1-12',
      start_key: 'mrk.1.1', end_key: 'mrk.1.12', passage_id: null, member_ids: ['ps:mrk.1.9'], split_passage_ids: [], build_id: plain.build_id,
      context: '[1] 馬可福音 第1章 (1-12節)\n**8** 八。\n\n**9** 九。\n\n**10** 十。\n\n**11** 十一。\n\n**12** 十二。',
    };
    const fixture = { ...plain, sources: [block], kg: { ...plain.kg, passages: [passage], mentions: [], names: [] } };
    const { page, context } = await showAnswer(harness, fixture);
    const node = page.locator('.node--passage');
    assert.match(await node.getAttribute('title'), /馬可福音 1:9-11/);
    await node.click();
    await page.waitForSelector('#reader[open]');
    assert.deepEqual(await citedVerses(page), ['9', '10', '11']);
    await context.close();
  });

  // ---- 手機按上一頁只關面板 ----

  const readerEntryGone = (page) => page.waitForFunction(() => !history.state?.reader);

  for (const [label, open] of [
    ['來源列', (page) => page.locator('.source').first().click()],
    ['引用', (page) => page.locator('.cite').first().click()],
    ['段落卡片', (page) => page.locator('.node--passage').first().click()],
  ]) {
    test(`320×640 從${label}開面板後按上一頁：只關面板，答案還在；再按一次才回首頁`, async () => {
      const { page, context, problems } = await openPage(harness, { width: 320, height: 640 });
      const asked = await mockAsk(page, () => WALK);
      await page.goto(harness.base);
      await page.locator('.example').first().click();
      await page.waitForSelector('#answer > *');
      const url = page.url();
      await open(page);
      await page.waitForSelector('#reader[open]');
      await page.goBack();
      await page.waitForSelector('#reader:not([open])', { state: 'attached' });
      assert.equal(page.url(), url, '還在這一題');
      assert.equal(await page.locator('#answer').isVisible(), true);
      assert.equal(await page.locator('#home').isVisible(), false);
      assert.equal(asked.length, 1, '不重查');
      await page.goBack();
      await page.waitForFunction(() => !document.getElementById('home').hidden);
      assert.equal(new URL(page.url()).pathname + new URL(page.url()).search, '/');
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('上一頁關面板：焦點回到打開它的元素，捲動位置不變', async () => {
    const { page, context } = await showAnswer(harness, WALK, { width: 320, height: 640 });
    const row = page.locator('.source').first();
    await row.scrollIntoViewIfNeeded();
    const scrolled = await page.evaluate(() => window.scrollY);
    await row.click();
    await page.waitForSelector('#reader[open]');
    await page.goBack();
    await page.waitForSelector('#reader:not([open])', { state: 'attached' });
    await page.waitForFunction(() => document.activeElement?.classList.contains('source'));
    assert.equal(await page.evaluate(() => window.scrollY), scrolled);
    await context.close();
  });

  for (const [label, dismiss] of [
    ['Esc', (page) => page.keyboard.press('Escape')],
    ['關閉鈕', (page) => page.click('#reader-close')],
  ]) {
    test(`用${label}關面板不留歷史：開關三次後按一次上一頁就回前一個畫面`, async () => {
      const { page, context, problems } = await openPage(harness, { width: 320, height: 640 });
      await mockAsk(page, () => WALK);
      await page.goto(harness.base);
      await page.locator('.example').first().click();
      await page.waitForSelector('#answer > *');
      for (let round = 0; round < 3; round += 1) {
        await page.locator('.source').first().click();
        await page.waitForSelector('#reader[open]');
        await dismiss(page);
        await readerEntryGone(page);
        assert.equal(await page.locator('#answer').isVisible(), true, '關面板不能離開答案');
      }
      await page.goBack();
      await page.waitForFunction(() => !document.getElementById('home').hidden);
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('關面板後按下一頁：還是這一題，不會跳走、不重查、捲動不變', async () => {
    const { page, context } = await openPage(harness, { width: 320, height: 640 });
    const asked = await mockAsk(page, () => WALK);
    await page.goto(`${harness.base}/?q=${encodeURIComponent(WALK.question)}`);
    await page.waitForSelector('#answer > *');
    const row = page.locator('.source').first();
    await row.scrollIntoViewIfNeeded();
    const scrolled = await page.evaluate(() => window.scrollY);
    await row.click();
    await page.waitForSelector('#reader[open]');
    await page.keyboard.press('Escape');
    await readerEntryGone(page);
    await page.goForward();
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#answer').isVisible(), true);
    assert.equal(asked.length, 1);
    assert.equal(await page.evaluate(() => window.scrollY), scrolled);
    await context.close();
  });

  test('面板開著時一次跳兩筆歷史：面板關掉，畫面跟著網址走', async () => {
    const { page, context } = await openPage(harness, { width: 320, height: 640 });
    await mockAsk(page, () => WALK);
    await page.goto(harness.base);
    await page.locator('.example').first().click();
    await page.waitForSelector('#answer > *');
    await page.locator('.source').first().click();
    await page.waitForSelector('#reader[open]');
    await page.evaluate(() => history.go(-2));
    await page.waitForFunction(() => !document.getElementById('home').hidden);
    assert.equal(await page.locator('#reader').isVisible(), false);
    await context.close();
  });

  test('面板開著時換內容（查另一節）不會多推一筆歷史', async () => {
    const { page, context } = await showAnswer(harness, WALK);
    const before = await page.evaluate(() => history.length);
    await page.locator('.source').first().click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.evaluate(() => history.length), before + 1);
    await context.close();
  });
});
