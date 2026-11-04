// 防線：答案注入不執行、console 與 CSP 乾淨、窄螢幕不水平捲動、畫面不露開發者概念。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  assertClean,
  assertNoHorizontalScroll,
  loadFixture,
  mockAsk,
  openAnswer,
  openPage,
  startHarness,
} from './support.mjs';

const FIXTURES = ['walk_event', 'walk_plain', 'kin', 'direct', 'regnal'].map(loadFixture);
const WALK = FIXTURES[0];
const IMG_ATTACK = '<img src=x onerror="window.__pwned=1">';
const SCRIPT_ATTACK = '<script>window.__pwned=2</script>';
const ATTACK = `${IMG_ATTACK} ${SCRIPT_ATTACK}`;
const DEV_TERMS = /top_k|fusion|alpha|use_graph|cypher|\bR[1-6]\b|rerank|\bps:|\bnm:|\bck:|\bvs:|\bev\d{4}|e000\d+|strategy|hybrid/;

function poisoned(fixture) {
  return {
    ...fixture,
    answer: `開頭 ${ATTACK} 結尾\n\n*   列表 ${ATTACK}\n\n**粗體 ${IMG_ATTACK}** 使徒行傳 13:4`,
    sources: fixture.sources.map((source) => ({
      ...source,
      title: `${source.title}${IMG_ATTACK}`,
      context: `${source.context}\n\n**99** ${ATTACK}`,
    })),
    kg: {
      ...fixture.kg,
      names: fixture.kg.names.map((name) => ({ ...name, label: `${name.label}${IMG_ATTACK}` })),
      passages: fixture.kg.passages.map((passage) => ({ ...passage, title: `${passage.title}${IMG_ATTACK}` })),
      events: fixture.kg.events.map((event) => ({ ...event, name: `${event.name}${IMG_ATTACK}` })),
    },
  };
}

describe('防線', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  test('答案、來源、圖譜標籤、問題裡的 <img onerror> 與 <script> 都不執行，原樣顯示為文字', async () => {
    const { page, context, problems } = await openPage(harness);
    await mockAsk(page, () => poisoned(WALK));
    await openAnswer(page, harness.base, ATTACK);

    const answerText = await page.locator('#answer').textContent();
    assert.ok(answerText.includes(IMG_ATTACK), answerText);
    assert.ok(answerText.includes(SCRIPT_ATTACK), answerText);
    assert.equal(await page.locator('#question').textContent(), ATTACK);
    assert.ok((await page.locator('.graph-stage .node-title').allTextContents()).some((text) => text.includes(IMG_ATTACK)));
    assert.equal(await page.locator('main img, main script, #reader img, #reader script').count(), 0);

    await page.locator('.source').first().click();
    await page.waitForSelector('#reader[open]');
    assert.ok((await page.locator('#reader-body').textContent()).includes(SCRIPT_ATTACK));
    assert.equal(await page.locator('#reader img, #reader script').count(), 0);
    await page.waitForTimeout(100);
    assert.equal(await page.evaluate(() => window.__pwned), undefined);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('答案的粗體與列表用元素畫出來，星號不外露', async () => {
    const { page, context } = await openPage(harness);
    await mockAsk(page, () => WALK);
    await openAnswer(page, harness.base, WALK.question);
    assert.equal(await page.locator('#answer strong').first().textContent(), '關於巴拿巴和保羅的關係：');
    assert.ok((await page.locator('#answer .answer-list > li').count()) >= 5);
    assert.ok(!(await page.locator('#answer').textContent()).includes('*'));
    await context.close();
  });

  test('巢狀列表依縮排分層', async () => {
    const { page, context } = await openPage(harness);
    await mockAsk(page, () => ({ ...WALK, answer: '*   第一層\n    *   第二層\n*   第一層之二' }));
    await openAnswer(page, harness.base, WALK.question);
    assert.equal(await page.locator('#answer .answer-list .answer-list > li').textContent(), '第二層');
    assert.equal(await page.locator('#answer > .answer-list > li').count(), 2);
    await context.close();
  });

  test('所有 fixture：console 無錯誤、CSP 無違規、沒有開發者概念', async () => {
    const { page, context, problems } = await openPage(harness);
    await mockAsk(page, (question) => FIXTURES.find((fixture) => fixture.question === question));
    for (const fixture of FIXTURES) {
      await openAnswer(page, harness.base, fixture.question);
      const visible = await page.locator('body').innerText();
      const leaked = visible.replace(/資料版本 \S+/, '').match(DEV_TERMS);
      assert.equal(leaked, null, `${fixture.question} 露出 ${leaked}`);
      await assertClean(assert, page, problems);
    }
    await context.close();
  });

  test('文件帶著 CSP 標頭，圖的定位在這個 CSP 下仍然生效', async () => {
    const { page, context, problems } = await openPage(harness);
    await mockAsk(page, () => WALK);
    const response = await page.goto(`${harness.base}/?q=${encodeURIComponent(WALK.question)}`);
    const csp = response.headers()['content-security-policy'];
    assert.match(csp, /default-src 'self'/);
    assert.doesNotMatch(csp, /unsafe-inline/);
    await page.waitForSelector('.graph-stage .node');
    const transform = await page.locator('.graph-stage .node').first().evaluate((node) => getComputedStyle(node).transform);
    assert.notEqual(transform, 'none');
    await assertClean(assert, page, problems);
    await context.close();
  });

  for (const width of [320, 768, 1024, 1440]) {
    test(`${width}px：每種畫面都沒有水平捲動`, async () => {
      const { page, context } = await openPage(harness, { width, height: 700 });
      await page.goto(harness.base);
      await assertNoHorizontalScroll(assert, page, '首屏');

      await page.route('**/api/ask', () => {});
      await page.goto(`${harness.base}/?q=${encodeURIComponent(WALK.question)}`);
      await page.waitForSelector('#waiting:not([hidden])');
      await assertNoHorizontalScroll(assert, page, '等待');
      await page.unroute('**/api/ask');

      await mockAsk(page, (question) => FIXTURES.find((fixture) => fixture.question === question));
      for (const fixture of FIXTURES) {
        await openAnswer(page, harness.base, fixture.question);
        await assertNoHorizontalScroll(assert, page, fixture.question);
      }

      await openAnswer(page, harness.base, WALK.question);
      await page.click('.hint-toggle');
      await assertNoHorizontalScroll(assert, page, '完整圖譜');
      await page.locator('.cite').first().click();
      await page.waitForSelector('#reader[open]');
      await assertNoHorizontalScroll(assert, page, '經文面板');
      const sheetOverflow = await page.locator('#reader-body').evaluate((node) => node.scrollWidth - node.clientWidth);
      assert.ok(sheetOverflow <= 0, `面板不水平捲動（${sheetOverflow}）`);
      await context.close();
    });
  }

  test('320px：很長沒有斷點的問題與答案不會撐破版面', async () => {
    const long = 'A'.repeat(400);
    const { page, context } = await openPage(harness, { width: 320, height: 640 });
    await mockAsk(page, () => ({ ...WALK, answer: `${long}\n\n*   ${long}` }));
    await openAnswer(page, harness.base, long);
    await assertNoHorizontalScroll(assert, page, '長字串');
    await context.close();
  });

  test('答案是惡意列舉也不會凍結分頁', async () => {
    const answers = [
      `馬太福音 第5章 ${Array.from({ length: 40 }, (_, i) => i + 1).join(', ')}。`,
      `創世記 第1章 ${Array.from({ length: 24 }, (_, i) => i + 1).join(' - ')}。`,
    ];
    for (const answer of answers) {
      const { page, context, problems } = await openPage(harness);
      await mockAsk(page, () => ({ ...WALK, answer }));
      await openAnswer(page, harness.base, '惡意列舉');
      assert.equal(await page.evaluate(() => document.getElementById('answer').textContent.length > 0), true);
      await assertClean(assert, page, problems);
      await context.close();
    }
  });

  for (const size of ['150%', '200%']) {
    test(`根字級 ${size}、320px：括號包住的長引用不會撐破版面`, async () => {
      const { page, context } = await openPage(harness, { width: 320, height: 640 });
      const answer = '*   巴拿巴帶著馬可坐船往塞浦路斯（使徒行傳 15:38-39）。保羅則揀選了西拉（撒母耳記上 第17章 12-40節）。';
      await mockAsk(page, () => ({ ...WALK, answer }));
      await page.goto(harness.base);
      await page.evaluate((value) => { document.documentElement.style.fontSize = value; }, size);
      await page.fill('#ask-input', '長引用');
      await page.press('#ask-input', 'Enter');
      await page.waitForSelector('#answer > *');
      await assertNoHorizontalScroll(assert, page, size);
      await context.close();
    });
  }
});
