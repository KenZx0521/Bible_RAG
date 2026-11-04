// 關聯圖：剪枝與完整圖譜切換、點名字高亮、親屬圖、推算文字、沒走圖與讀不到圖的說明。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { buildViews } from '../../public/js/graph-model.js';
import { assertClean, assertNoHorizontalScroll, bigFamily, loadFixture, mockAsk, openAnswer, openPage, startHarness } from './support.mjs';

const WALK = loadFixture('walk_event');
const PLAIN = loadFixture('walk_plain');
const KIN = loadFixture('kin');
const DIRECT = loadFixture('direct');
const REGNAL = loadFixture('regnal');

const FULL_NODE_COUNT = buildViews(WALK).views.find((view) => view.key === 'walk').graph.nodes.length;
const FAINT_TEXT = 'rgb(110, 100, 85)';

async function showFixture(harness, fixture, options) {
  const opened = await openPage(harness, options);
  await mockAsk(opened.page, () => fixture);
  await openAnswer(opened.page, harness.base, fixture.question);
  return opened;
}

describe('關聯圖', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  test('走圖＋事件：看到答案、剪過的圖不超過 14 節點，且老實說隱藏了多少', async () => {
    const { page, context, problems } = await showFixture(harness, WALK);
    assert.match(await page.locator('#answer').textContent(), /塞浦路斯/);
    const nodes = page.locator('.graph-stage .node');
    assert.ok((await nodes.count()) <= 14);
    assert.ok((await page.locator('.graph-edges path').count()) <= 24);
    const labels = await page.locator('.graph-stage .node-title').allTextContents();
    for (const label of ['巴拿巴', '保羅', '安提阿的教會', '第一次宣教旅程']) assert.ok(labels.includes(label), label);
    assert.match(await page.locator('.prune-hint').textContent(), /為了好讀，隱藏了 29 個人名地名、6 段經文.*顯示完整圖譜/);
    assert.match(await page.locator('.graph-caption').textContent(), /從問題裡的「巴拿巴」「保羅」出發.*「安提阿的教會」/);

    const brought = page.locator('.node--passage.is-brought');
    assert.equal(await brought.count(), 1);
    assert.match(await brought.textContent(), /圖譜帶進來.*安提阿的教會/);
    assert.equal(await page.locator('.node--name.is-asked').count(), 2);
    assert.match(await page.locator('.source', { hasText: '安提阿的教會' }).textContent(), /圖譜帶進來/);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('切完整圖譜可以捲動閱讀，切回精簡圖一切還原', async () => {
    const { page, context, problems } = await showFixture(harness, WALK, { width: 1440, height: 800 });
    const prunedCount = await page.locator('.graph-stage .node').count();
    await page.click('.hint-toggle');
    assert.equal(await page.locator('.graph-stage .node').count(), FULL_NODE_COUNT);
    assert.match(await page.locator('.prune-hint').textContent(), /完整圖譜.*回到精簡圖/);
    assert.equal(await page.evaluate(() => document.activeElement.className.includes('hint-toggle')), true, '焦點留在切換鈕');
    assert.equal(await page.locator('.node.is-unused').count() > 0, true, '沒用到的段落要淡');

    const scrolled = await page.locator('.graph-scroll').evaluate((node) => {
      const room = node.scrollHeight - node.clientHeight;
      node.scrollTop = 300;
      return { room, top: node.scrollTop };
    });
    assert.ok(scrolled.room > 300, `要能捲動：${scrolled.room}`);
    assert.equal(scrolled.top, 300);
    // 字沒有被縮小到看不見
    const fontSize = await page.locator('.node--name .node-title').first().evaluate((node) => parseFloat(getComputedStyle(node).fontSize));
    assert.ok(fontSize >= 11, `${fontSize}`);

    await page.click('.hint-toggle');
    assert.equal(await page.locator('.graph-stage .node').count(), prunedCount);
    assert.match(await page.locator('.prune-hint').textContent(), /隱藏了/);
    assert.equal(await page.locator('.graph-scroll').evaluate((node) => node.scrollTop), 0);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('單欄時完整圖譜隨頁面長高、由頁面捲動', async () => {
    const { page, context } = await showFixture(harness, WALK, { width: 375, height: 700 });
    const before320 = await page.evaluate(() => document.documentElement.scrollHeight);
    await page.click('.hint-toggle');
    const after320 = await page.evaluate(() => document.documentElement.scrollHeight);
    assert.ok(after320 > before320 + 500, `${before320} → ${after320}`);
    const scroller = await page.locator('.graph-scroll').evaluate((node) => node.scrollHeight - node.clientHeight);
    assert.ok(scroller <= 0, '單欄不做內層捲動');
    // 切換鈕貼在視窗底時也不能被黏住的狀態列蓋住
    const covering = await page.locator('.hint-toggle').evaluate((node) => {
      node.scrollIntoView({ block: 'end' });
      const rect = node.getBoundingClientRect();
      return document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2)?.className;
    });
    assert.match(covering, /hint-toggle/);
    await context.close();
  });

  test('點名字高亮它連到的段落、其餘淡出；再點或點空白處還原', async () => {
    const { page, context, problems } = await showFixture(harness, WALK);
    const idle = await page.locator('.graph-status').textContent();
    const name = page.locator('.node--name', { hasText: '巴拿巴' });
    await name.click();
    const linked = await page.locator('.node--passage.is-linked').count();
    assert.ok(linked >= 1);
    assert.match(await page.locator('.graph-status').textContent(), new RegExp(`^巴拿巴 出現在 ${linked} 段經文：`));
    assert.equal(await name.getAttribute('aria-pressed'), 'true');
    const dimmed = page.locator('.has-focus .node--name:not(.is-selected):not(.is-linked)').first();
    assert.equal(await dimmed.evaluate((element) => getComputedStyle(element).color), FAINT_TEXT);
    assert.ok((await page.locator('.graph-edges path.is-linked').count()) === linked, '高亮的邊與段落數一致');

    await name.click();
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 0);
    assert.equal(await page.locator('.graph-status').textContent(), idle);

    await name.click();
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 1);
    const box = await page.locator('.graph-stage').boundingBox();
    await page.mouse.click(box.x + box.width / 2 + 60, box.y + 2);
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 0, '點空白處還原');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('節點是 button，不重疊，全部落在舞台裡', async () => {
    const { page, context } = await showFixture(harness, WALK, { width: 320, height: 640 });
    const check = await page.evaluate(() => {
      const stage = document.querySelector('.graph-stage').getBoundingClientRect();
      const boxes = [...document.querySelectorAll('.graph-stage .node')].map((node) => ({
        tag: node.tagName, rect: node.getBoundingClientRect(),
      }));
      const overlaps = boxes.filter((a, i) => boxes.slice(i + 1).some((b) => a.rect.left < b.rect.right
        && b.rect.left < a.rect.right && a.rect.top < b.rect.bottom && b.rect.top < a.rect.bottom));
      return {
        tags: [...new Set(boxes.map((box) => box.tag))],
        overlaps: overlaps.length,
        outside: boxes.filter(({ rect }) => rect.left < stage.left - 1 || rect.right > stage.right + 1).length,
      };
    });
    assert.deepEqual(check, { tags: ['BUTTON'], overlaps: 0, outside: 0 });
    await context.close();
  });

  test('親屬圖：看到人物、關係標籤與問題問的人；點關係字開出處經文', async () => {
    const { page, context, problems } = await showFixture(harness, KIN);
    const people = await page.locator('.node--person .node-title').allTextContents();
    assert.deepEqual([...people].sort(), ['俄備得', '大衛', '波阿斯', '耶西', '路得'].sort());
    assert.equal(await page.locator('.node--person.is-asked .node-title').textContent(), '大衛');
    assert.equal(await page.locator('.edge-label').count(), 4);
    assert.equal(await page.locator('.edge-label').first().textContent(), '父母');
    assert.equal(await page.locator('.prune-hint').isVisible(), false, '小圖不剪');
    assert.match(await page.locator('.graph-caption').textContent(), /親屬關係，每條都有經文出處/);

    const ruthLabel = page.locator('.edge-label[title*="路得記 4:17"]').first();
    await ruthLabel.click();
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('#reader-title').textContent(), '波阿斯和他的後代');
    assert.equal(await page.locator('.verse.is-cited').getAttribute('data-verse'), '17');
    await page.keyboard.press('Escape');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'edge-label');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('親屬圖的分段切換：切到走圖看到剪過的圖，切回親屬圖還在', async () => {
    const { page, context } = await showFixture(harness, KIN);
    const segments = page.locator('.segment');
    assert.deepEqual(await segments.allTextContents(), ['親屬關係', '答案怎麼找到的']);
    assert.equal(await segments.nth(0).getAttribute('aria-pressed'), 'true');
    await segments.nth(1).click();
    assert.equal(await segments.nth(1).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.node--person').count(), 0);
    assert.ok((await page.locator('.node--name').count()) > 0);
    assert.ok((await page.locator('.graph-stage .node').count()) <= 14);
    await segments.nth(0).click();
    assert.equal(await page.locator('.node--person').count(), 5);
    await context.close();
  });

  test('直接查經文：說明沒走圖，而且沒有圖', async () => {
    const { page, context, problems } = await showFixture(harness, DIRECT);
    assert.equal(await page.locator('.graph-stage').count(), 0);
    assert.equal(await page.locator('.graph-note').textContent(), '這題寫明了經文出處，直接查就找到了，不需要走知識圖譜。');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('沒帶新段落的走圖：說明照實寫', async () => {
    const { page, context } = await showFixture(harness, PLAIN);
    assert.match(await page.locator('.graph-caption').textContent(), /這題沒有多找到新段落/);
    assert.equal(await page.locator('.node.is-brought').count(), 0);
    await context.close();
  });

  test('年表：有分段切換與推算文字，不畫代號節點', async () => {
    const { page, context, problems } = await showFixture(harness, REGNAL);
    const segments = page.locator('.segment');
    assert.deepEqual(await segments.allTextContents(), ['王位順序推算', '答案怎麼找到的']);
    assert.match(await page.locator('.graph-caption').textContent(), /依列王紀整理的王位順序推算/);
    assert.match(await page.locator('.chrono').textContent(), /拿答之後第1位以色列王.*巴沙/);
    assert.equal(await page.locator('.graph-stage').count(), 0, '年表不畫圖');
    await segments.nth(1).click();
    assert.ok((await page.locator('.graph-stage .node').count()) > 0);
    assert.equal(await page.locator('.chrono').count(), 0);
    await segments.nth(0).click();
    assert.equal(await page.locator('.chrono').count(), 1);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('圖譜讀不到：答案照常，說明這題有走但圖讀不到', async () => {
    const broken = { ...WALK, kg: { status: 'unavailable', reason: 'neo4j_query_failed', names: [], passages: [], mentions: [], events: [] } };
    const { page, context, problems } = await showFixture(harness, broken);
    assert.match(await page.locator('#answer').textContent(), /塞浦路斯/);
    assert.equal(await page.locator('.graph-stage').count(), 0);
    assert.equal(await page.locator('.graph-note').textContent(), '這題有走知識圖譜，但關聯圖暫時讀不到。');
    assert.equal(await page.locator('.source').count(), WALK.sources.length);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('知識圖譜沒回應：說答案是直接比對找到的', async () => {
    const skipped = { ...WALK, kg: { status: 'walk_skipped', reason: 'timeout', names: [], passages: [], mentions: [], events: [] } };
    const trace = WALK.graph_trace.map((op) => (op.op === 'graph_walk' ? { ...op, skip_reason: 'timeout' } : op));
    const { page, context } = await showFixture(harness, { ...skipped, graph_trace: trace });
    assert.equal(await page.locator('.graph-note').textContent(), '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。');
    await context.close();
  });

  for (const width of [320, 1280]) {
    test(`大家族（${width}px）：剪到 14 人內且說清楚，關係字不蓋住名字，配偶手足都標得出來`, async () => {
      const family = bigFamily();
      const { page, context, problems } = await showFixture(harness, family, { width, height: 800 });
      assert.ok((await page.locator('.node--person').count()) <= 14);
      assert.match(await page.locator('.prune-hint').textContent(), /隱藏了 \d+ 位人物.*顯示完整圖譜/);
      assert.equal(await page.locator('.node--person.is-asked .node-title').textContent(), '雅各', '問題問的人一定留著');
      const labels = await page.locator('.edge-label').allTextContents();
      assert.ok(labels.includes('配偶') && labels.includes('手足') && labels.includes('父母'), labels.join());
      const covered = await page.evaluate(() => {
        const people = [...document.querySelectorAll('.node--person .node-title')];
        const tags = [...document.querySelectorAll('.edge-label')];
        return tags.filter((tag) => {
          const a = tag.getBoundingClientRect();
          return people.some((person) => {
            const range = document.createRange();
            range.selectNodeContents(person);
            const b = range.getBoundingClientRect();
            return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
          });
        }).length;
      });
      assert.equal(covered, 0, '關係字不准蓋住人名');
      await page.click('.hint-toggle');
      assert.equal(await page.locator('.node--person').count(), 18);
      await assertNoHorizontalScroll(assert, page, '完整親屬圖');
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('圖譜資料壞掉時答案照常顯示', async () => {
    const broken = { ...WALK, kg: { status: 'ok', names: null, passages: null, mentions: null, events: null } };
    const { page, context } = await showFixture(harness, broken);
    assert.match(await page.locator('#answer').textContent(), /塞浦路斯/);
    assert.match(await page.locator('.graph-note').textContent(), /關聯圖這次畫不出來/);
    assert.equal(await page.locator('.source').count(), WALK.sources.length);
    await context.close();
  });

  test('視窗變窄時圖會重排，不超出欄寬', async () => {
    const { page, context, problems } = await showFixture(harness, WALK, { width: 1280, height: 800 });
    const wide = await page.locator('.graph-stage .node').first().boundingBox();
    await page.setViewportSize({ width: 360, height: 700 });
    await page.waitForFunction(() => document.querySelector('.node.is-compact') !== null);
    const narrow = await page.locator('.graph-stage .node').first().boundingBox();
    assert.ok(narrow.width < wide.width);
    await assertClean(assert, page, problems);
    await context.close();
  });
});
