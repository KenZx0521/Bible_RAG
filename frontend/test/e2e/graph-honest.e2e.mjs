// 圖要誠實：只畫圖譜走到的段落、說明的段數等於卡片數、走了沒用到時不畫空框、畫面沒有術語。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { assertClean, assertNoHorizontalScroll, loadFixture, mockAsk, openAnswer, openPage, startHarness } from './support.mjs';

const WALK = loadFixture('walk_event');
const PLAIN = loadFixture('walk_plain');
const KIN = loadFixture('kin');
const DIRECT = loadFixture('direct');
const REGNAL = loadFixture('regnal');
const ALL = [WALK, PLAIN, KIN, DIRECT, REGNAL];

const WIDTHS = [[320, 640], [1280, 900]];

/** walk：看走圖檢視要不要先切分頁。 */
const SHOWN = [
  { name: 'walk_event', fixture: WALK, cards: 5, walkedUsed: 4, tab: false, off: '另有 1 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。' },
  { name: 'walk_plain', fixture: PLAIN, cards: 3, walkedUsed: 3, tab: false, off: '另有 2 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。' },
  { name: 'kin', fixture: KIN, cards: 1, walkedUsed: 1, tab: true, off: '另有 1 段是直接比對問題找到的，沒有經過圖譜；2 段是親屬關係的出處。都列在經文來源。' },
  { name: 'regnal', fixture: REGNAL, cards: 2, walkedUsed: 2, tab: true, off: '另有 3 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。' },
];

/** 走了，但答案用的段落全部沒走到：把來源換成 walked=false 的那幾段。 */
function walkedButUnused() {
  const notWalked = new Set(PLAIN.kg.passages.filter((passage) => !passage.walked).map((passage) => passage.id));
  const sources = PLAIN.sources.filter((source) => notWalked.has(source.passage_id));
  const trace = PLAIN.graph_trace.map((op) => (op.op === 'graph_walk' ? { ...op, confirmed: [], passages: [] } : op));
  return { ...PLAIN, sources, graph_trace: trace, answer: '答案只用到直接比對找到的經文。' };
}

async function show(harness, fixture, options) {
  const opened = await openPage(harness, options);
  await mockAsk(opened.page, () => fixture);
  await openAnswer(opened.page, harness.base, fixture.question);
  return opened;
}

const allText = (page) => page.evaluate(() => {
  const attrs = ['aria-label', 'title', 'placeholder'];
  const fromAttrs = [...document.querySelectorAll('*')].flatMap((node) => attrs.map((name) => node.getAttribute(name) ?? ''));
  return [document.body.innerText, ...fromAttrs].join('\n');
});

describe('圖要誠實', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  for (const [width, height] of WIDTHS) {
    for (const { name, fixture, cards, walkedUsed, tab, off } of SHOWN) {
      test(`${width}px ${name}：說明的段數＝走到且用到的卡片，圖下方說明不在圖上的段落`, async () => {
        const { page, context, problems } = await show(harness, fixture, { width, height });
        if (tab) await page.locator('.segment', { hasText: '答案怎麼找到的' }).click();
        assert.equal(await page.locator('.graph-stage .node--passage').count(), cards);
        assert.equal(await page.locator('.graph-stage .node--passage:not(.is-anchored)').count(), walkedUsed);
        const caption = await page.locator('.graph-caption').textContent();
        const counted = /答案參考的 (\d+) 段經文/.exec(caption);
        if (counted) assert.equal(Number(counted[1]), walkedUsed, caption);
        assert.equal(await page.locator('.graph-offgraph').textContent(), off);
        const stage = await page.locator('.graph-canvas').boundingBox();
        const note = await page.locator('.graph-offgraph').boundingBox();
        assert.ok(note.y >= stage.y + stage.height - 1, '句子在圖下方');
        await assertNoHorizontalScroll(assert, page, name);
        await assertClean(assert, page, problems);
        await context.close();
      });
    }
  }

  test('保羅範例：沒走到的「掃羅在耶路撒冷」不在圖上（完整圖也沒有），但仍在經文來源', async () => {
    const { page, context } = await show(harness, WALK);
    const titles = () => page.locator('.graph-stage .node-title').allTextContents();
    assert.equal((await titles()).includes('掃羅在耶路撒冷'), false);
    await page.click('.hint-toggle');
    assert.equal((await titles()).includes('掃羅在耶路撒冷'), false);
    assert.equal(await page.locator('.source', { hasText: '掃羅在耶路撒冷' }).count(), 1);
    await context.close();
  });

  test('事件對應的段落只連事件那條線，樣式與報讀都分得出來，圖例也寫', async () => {
    const { page, context } = await show(harness, WALK);
    const card = page.locator('.node--passage', { hasText: '巴拿巴和掃羅奉差遣' });
    assert.ok(await card.evaluate((node) => node.classList.contains('is-anchored')));
    assert.match(await card.getAttribute('aria-label'), /事件對應/);
    const edges = await page.locator('.graph-edges path').evaluateAll((paths) => paths
      .filter((path) => path.dataset.to === 'ps:act.13.1' || path.dataset.from === 'ps:act.13.1')
      .map((path) => [path.dataset.from, path.dataset.to]));
    assert.deepEqual(edges, [['ev0009', 'ps:act.13.1']]);
    assert.match(await page.locator('.graph-legend').textContent(), /事件對應的段落/);
    const plain = page.locator('.node--passage', { hasText: '在塞浦路斯傳道' });
    const style = (locator) => locator.evaluate((node) => {
      const css = getComputedStyle(node);
      return `${css.borderLeftWidth} ${css.borderLeftColor}`;
    });
    assert.notEqual(await style(card), await style(plain), '看得出和一般卡片不同');
    await context.close();
  });

  for (const [width, height] of WIDTHS) {
    test(`${width}px 走了但沒用到：只有說明與「顯示完整圖譜」，沒有空框，切完整圖再切回不當掉`, async () => {
      const { page, context, problems } = await show(harness, walkedButUnused(), { width, height });
      assert.equal(await page.locator('.graph-caption').textContent(), '知識圖譜有走，但連到的段落沒有用在答案裡。');
      assert.equal(await page.locator('.graph-stage .node').count(), 0);
      assert.equal(await page.locator('.graph-canvas').isVisible(), false, '不畫空框');
      assert.equal(await page.locator('.graph-status').isVisible(), false, '沒有東西可點，不留操作提示');
      assert.equal(await page.locator('.graph-legend').isVisible(), false, '沒有圖就沒有圖例');
      assert.equal((await page.locator('.prune-hint').innerText()).trim(), '顯示完整圖譜', '不留「隱藏了 N 個」，也不留分隔點');
      assert.equal(await page.locator('.graph-offgraph').textContent(), '另有 2 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。');
      assert.equal(await page.locator('.source').count(), 2, '來源照常');

      await page.click('.hint-toggle');
      assert.ok((await page.locator('.graph-stage .node').count()) > 0);
      assert.ok((await page.locator('.graph-stage .node--passage.is-unused').count()) > 0);
      assert.equal(await page.locator('.graph-status').isVisible(), true);
      assert.match(await page.locator('.graph-legend').textContent(), /連到但沒用在答案/);
      assert.match(await page.locator('.prune-hint').textContent(), /完整圖譜.*回到精簡圖/);
      assert.equal(await page.evaluate(() => document.activeElement.className.includes('hint-toggle')), true, '焦點留在切換鈕');

      await page.click('.hint-toggle');
      assert.equal(await page.locator('.graph-stage .node').count(), 0);
      assert.equal(await page.locator('.graph-canvas').isVisible(), false);
      assert.equal(await page.locator('.hint-toggle').textContent(), '顯示完整圖譜');
      await assertNoHorizontalScroll(assert, page, '沒有卡片');
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('走了但一段都沒有回來（kg 沒有段落）：只有說明，沒有連結，不當掉', async () => {
    const fixture = { ...walkedButUnused(), kg: { ...PLAIN.kg, passages: [], mentions: [], names: [], events: [] } };
    const { page, context, problems } = await show(harness, fixture);
    assert.equal(await page.locator('.graph-canvas').isVisible(), false);
    assert.equal(await page.locator('.prune-hint').isVisible(), false);
    assert.match(await page.locator('.graph-caption').textContent(), /知識圖譜有走/);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('只有 1 張卡（親屬範例第二分頁）：整組置中，有線連著，不難看', async () => {
    const { page, context } = await show(harness, KIN, { width: 1280, height: 900 });
    await page.locator('.segment', { hasText: '答案怎麼找到的' }).click();
    const stage = await page.locator('.graph-stage').boundingBox();
    const card = await page.locator('.node--passage').boundingBox();
    const name = await page.locator('.node--name').boundingBox();
    const [left, right] = [card.x - stage.x, stage.x + stage.width - (name.x + name.width)];
    assert.ok(Math.abs(left - right) <= 2, `左 ${left}、右 ${right}`);
    assert.equal(await page.locator('.graph-edges path').count(), 1);
    await context.close();
  });

  for (const [label, fixture, tab] of [['1 張卡', KIN, true], ['2 張卡', REGNAL, true], ['3 張卡', PLAIN, false]]) {
    test(`桌機 ${label}：圖和下方的句子之間沒有一大塊空白；句子不留孤字`, async () => {
      const { page, context } = await show(harness, fixture, { width: 1440, height: 900 });
      if (tab) await page.locator('.segment', { hasText: '答案怎麼找到的' }).click();
      const stage = await page.locator('.graph-stage').boundingBox();
      const note = await page.locator('.graph-offgraph').boundingBox();
      const gap = note.y - (stage.y + stage.height);
      assert.ok(gap <= 32, `空了 ${gap}px`);
      const lines = await page.locator('.graph-offgraph').evaluate((node) => Math.round(node.getBoundingClientRect().height / parseFloat(getComputedStyle(node).lineHeight)));
      assert.equal(lines, 1, '桌機這欄放得下一行');
      await context.close();
    });
  }

  test('桌機完整圖譜仍在側欄內捲動，不把頁面撐長', async () => {
    const { page, context } = await show(harness, WALK, { width: 1440, height: 800 });
    await page.click('.hint-toggle');
    const room = await page.locator('.graph-scroll').evaluate((node) => ({ scroll: node.scrollHeight - node.clientHeight, height: node.clientHeight }));
    assert.ok(room.scroll > 0, '要能捲');
    assert.ok(room.height >= 200, `捲動區不能被擠扁：${room.height}`);
    await context.close();
  });

  // ---- 文案 ----

  test('五個範例（含切分頁、完整圖譜、未用到段落的面板）：畫面任何地方都沒有「語意搜尋」與舊說法', async () => {
    const { page, context } = await openPage(harness);
    await mockAsk(page, (question) => ALL.find((fixture) => fixture.question === question));
    await page.route('**/api/verse/**', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ verse: 1, verse_range: '1', unit_key: 'x', text: '經文' }) }));
    const forbidden = /語意搜尋|走到但沒用到|走到但沒有用|知識圖譜走到了/;
    for (const fixture of ALL) {
      await openAnswer(page, harness.base, fixture.question);
      assert.doesNotMatch(await allText(page), forbidden, fixture.question);
      for (let i = 1; i < await page.locator('.segment').count(); i += 1) {
        await page.locator('.segment').nth(i).click();
        assert.doesNotMatch(await allText(page), forbidden, fixture.question);
      }
      if ((await page.locator('.hint-toggle').count()) > 0 && await page.locator('.hint-toggle').isVisible()) {
        await page.click('.hint-toggle');
        assert.doesNotMatch(await allText(page), forbidden, `${fixture.question} 完整圖譜`);
        const unused = page.locator('.node.is-unused').first();
        if ((await unused.count()) > 0) {
          await unused.click();
          await page.waitForSelector('.reader-note');
          assert.match(await page.locator('.reader-note').textContent(), /知識圖譜連到了這段/);
          assert.doesNotMatch(await allText(page), forbidden, `${fixture.question} 面板`);
          await page.keyboard.press('Escape');
        }
      }
    }
    await context.close();
  });

  for (const [label, kg, trace] of [
    ['walk_skipped', { status: 'walk_skipped', reason: 'timeout', names: [], passages: [], mentions: [], events: [] }, WALK.graph_trace.map((op) => (op.op === 'graph_walk' ? { ...op, skip_reason: 'timeout' } : op))],
    ['unavailable 且沒走成', { status: 'unavailable', reason: 'x', names: [], passages: [], mentions: [], events: [] }, []],
  ]) {
    test(`${label}：沒有圖，說明寫直接比對`, async () => {
      const { page, context } = await show(harness, { ...WALK, kg, graph_trace: trace });
      assert.equal(await page.locator('.graph-note').textContent(), '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。');
      assert.equal(await page.locator('.graph-stage').count(), 0);
      await context.close();
    });
  }
});
