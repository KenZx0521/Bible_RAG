// 關聯圖讀不讀得到：淡出後的對比、焦點與選取、怎麼退出高亮、回饋在不在視窗內、報讀器、手機與大字、說明與實際一致。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  assertClean, assertNoHorizontalScroll, bigFamily, clippedNodes, effectiveContrast, loadFixture, mockAsk, openAnswer, openPage, startHarness,
} from './support.mjs';

const WALK = loadFixture('walk_event');
const PLAIN = loadFixture('walk_plain');
const KIN = loadFixture('kin');

const AA_TEXT = 4.5;
const AA_NON_TEXT = 3;

async function showFixture(harness, fixture, options) {
  const opened = await openPage(harness, options);
  await mockAsk(opened.page, () => fixture);
  await openAnswer(opened.page, harness.base, fixture.question);
  return opened;
}

describe('關聯圖讀得到', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  // ---- 淡出的節點仍可點，字要讀得到 ----

  test('淡出的節點文字對比 ≥ 4.5:1，滑鼠移上去恢復', async () => {
    const { page, context } = await showFixture(harness, WALK);
    await page.locator('.node--name', { hasText: '保羅' }).click();
    const faded = page.locator('.has-focus .node:not(.is-linked, .is-selected)');
    assert.ok((await faded.count()) > 0);
    for (let i = 0; i < await faded.count(); i += 1) {
      const node = faded.nth(i);
      for (const part of ['.node-title', '.node-ref', '.node-flag']) {
        const inner = node.locator(part);
        if ((await inner.count()) > 0) {
          const ratio = await effectiveContrast(inner);
          assert.ok(ratio >= AA_TEXT, `${await node.textContent()} ${part}: ${ratio.toFixed(2)}`);
        }
      }
      assert.equal(await node.evaluate((element) => getComputedStyle(element).opacity), '1');
    }
    const target = page.locator('.has-focus .node--name:not(.is-linked, .is-selected)').first();
    await target.hover();
    assert.equal(await target.evaluate((element) => getComputedStyle(element).color), 'rgb(29, 24, 19)');
    await context.close();
  });

  test('親屬圖：淡出的人物與關係字一樣讀得到', async () => {
    const { page, context } = await showFixture(harness, KIN);
    await page.locator('.node--person', { hasText: '波阿斯' }).click();
    for (const selector of ['.has-focus .node:not(.is-linked, .is-selected) .node-title', '.has-focus .edge-label:not(.is-linked)']) {
      const faded = page.locator(selector);
      assert.ok((await faded.count()) > 0, selector);
      for (let i = 0; i < await faded.count(); i += 1) {
        const ratio = await effectiveContrast(faded.nth(i));
        assert.ok(ratio >= AA_TEXT, `${await faded.nth(i).textContent()}: ${ratio.toFixed(2)}`);
      }
    }
    await context.close();
  });

  test('鍵盤：選取的樣式和焦點環不一樣，焦點環也不會被淡出', async () => {
    const { page, context } = await showFixture(harness, WALK, { width: 1440, height: 900 });
    await page.locator('.node--name', { hasText: '保羅' }).focus();
    await page.keyboard.press('Enter');
    await page.keyboard.press('Tab');
    const state = await page.evaluate(() => {
      const describe = (element) => {
        const style = getComputedStyle(element);
        return { outline: style.outlineStyle, width: parseFloat(style.outlineWidth), opacity: style.opacity, selected: element.classList.contains('is-selected') };
      };
      return { active: describe(document.activeElement), selected: describe(document.querySelector('.node.is-selected')) };
    });
    assert.equal(state.active.selected, false, '焦點已離開選取的節點');
    assert.equal(state.active.outline, 'solid');
    assert.ok(state.active.width >= 2);
    assert.equal(state.active.opacity, '1');
    assert.equal(state.selected.outline, 'none', '選取不再用外框環，畫面上的環只代表焦點');
    const ring = await effectiveContrast(page.locator(':focus'), 'outlineColor');
    assert.ok(ring >= AA_NON_TEXT, `焦點環對比 ${ring.toFixed(2)}`);
    await context.close();
  });

  test('圖的線與名字外框對比 ≥ 3:1', async () => {
    const { page, context } = await showFixture(harness, WALK);
    const edge = await effectiveContrast(page.locator('.graph-edges path:not(.edge--brought):not(.edge--anchor)').first(), 'stroke');
    assert.ok(edge >= AA_NON_TEXT, `線 ${edge.toFixed(2)}`);
    const border = await effectiveContrast(page.locator('.node--name:not(.is-asked)').first(), 'borderTopColor');
    assert.ok(border >= AA_NON_TEXT, `外框 ${border.toFixed(2)}`);
    await context.close();
  });

  // ---- 怎麼退出高亮 ----

  for (const [label, point] of [
    ['右欄下半的空白', { x: 1300, y: 860 }],
    ['答案欄的文字', { x: 120, y: 330 }],
  ]) {
    test(`點${label}也會還原高亮`, async () => {
      const { page, context } = await showFixture(harness, WALK, { width: 1440, height: 900 });
      await page.locator('.node--name', { hasText: '保羅' }).click();
      assert.equal(await page.locator('.graph-stage.has-focus').count(), 1);
      const hit = await page.evaluate(({ x, y }) => document.elementFromPoint(x, y)?.tagName, point);
      assert.notEqual(hit, 'BUTTON', '測試點不能剛好是按鈕');
      await page.mouse.click(point.x, point.y);
      assert.equal(await page.locator('.graph-stage.has-focus').count(), 0);
      await context.close();
    });
  }

  test('Esc 還原高亮；面板開著時 Esc 只關面板', async () => {
    const { page, context } = await showFixture(harness, WALK);
    await page.locator('.node--name', { hasText: '保羅' }).click();
    await page.locator('.cite').first().click();
    await page.waitForSelector('#reader[open]');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#reader').isVisible(), false);
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 1, '只關面板，高亮還在');
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 0);
    await context.close();
  });

  test('高亮時有看得到的「還原」鈕，按了焦點回到選取的節點；沒高亮時不出現', async () => {
    const { page, context, problems } = await showFixture(harness, WALK);
    const clear = page.locator('.graph-clear');
    assert.equal(await clear.isVisible(), false);
    const name = page.locator('.node--name', { hasText: '保羅' });
    await name.click();
    assert.equal(await clear.isVisible(), true);
    await clear.focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('.graph-stage.has-focus').count(), 0);
    assert.equal(await clear.isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.kind), 'name');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('換檢視後不留下 document 上的監聽：Esc 不會影響新的檢視', async () => {
    const { page, context, problems } = await showFixture(harness, KIN);
    await page.locator('.node--person', { hasText: '大衛' }).click();
    await page.locator('.segment').nth(1).click();
    await page.locator('.node--name').first().click();
    await page.locator('.segment').nth(0).click();
    await page.keyboard.press('Escape');
    await page.mouse.click(5, 5);
    await assertClean(assert, page, problems);
    await context.close();
  });

  // ---- 回饋要看得到 ----

  for (const [width, height] of [[1024, 768], [1366, 768], [1440, 900]]) {
    test(`${width}×${height} 完整圖譜點名字：說明列在視窗內`, async () => {
      const { page, context } = await showFixture(harness, WALK, { width, height });
      await page.click('.hint-toggle');
      await page.locator('.node--name').first().click();
      const box = await page.locator('.graph-status').boundingBox();
      assert.ok(box.y >= 0 && box.y + box.height <= height, JSON.stringify(box));
      assert.match(await page.locator('.graph-status').textContent(), /出現在/);
      await context.close();
    });
  }

  test('桌機：點名字時圖不會跳動（說明列預留高度）', async () => {
    const { page, context } = await showFixture(harness, WALK, { width: 1440, height: 900 });
    const before = await page.locator('.graph-stage').boundingBox();
    await page.locator('.node--name', { hasText: '巴拿巴' }).click();
    const after = await page.locator('.graph-stage').boundingBox();
    assert.equal(after.y, before.y);
    await context.close();
  });

  for (const [title, fixture, selector] of [
    ['親屬圖', KIN, '.node--person'],
    ['走圖精簡圖', WALK, '.node--name'],
  ]) {
    test(`320×640 ${title}：節點捲到中央時點它，說明列沒有被切掉`, async () => {
      const { page, context } = await showFixture(harness, fixture, { width: 320, height: 640 });
      const node = page.locator(selector).first();
      await node.evaluate((element) => element.scrollIntoView({ block: 'center' }));
      await node.click();
      const box = await page.locator('.graph-status').boundingBox();
      assert.ok(box.y >= 0 && box.y + box.height <= 640, JSON.stringify(box));
      await context.close();
    });
  }

  // ---- 非視覺使用者也拿得到關係 ----

  test('按名字會念出是哪幾段；段落的標籤列出提到的名字', async () => {
    const { page, context } = await showFixture(harness, WALK);
    await page.locator('.node--name', { hasText: '保羅' }).click();
    const titles = await page.locator('.node--passage.is-linked .node-title').allTextContents();
    assert.ok(titles.length > 0);
    const status = await page.locator('.graph-status').textContent();
    for (const title of titles) assert.ok(status.includes(title), `${status} 缺 ${title}`);
    const label = await page.locator('.node--passage', { hasText: '在塞浦路斯傳道' }).getAttribute('aria-label');
    assert.match(label, /提到.*保羅/);
    assert.match(await page.locator('.node--name', { hasText: '保羅' }).getAttribute('aria-label'), /出現在 \d+ 段經文/);
    await context.close();
  });

  // ---- 手機與大字 ----

  test('320px：段落節點看得到書名', async () => {
    const { page, context } = await showFixture(harness, PLAIN, { width: 320, height: 640 });
    const books = page.locator('.node--passage .node-ref-book');
    assert.ok((await books.count()) > 0);
    for (let i = 0; i < await books.count(); i += 1) assert.equal(await books.nth(i).isVisible(), true);
    assert.match((await books.allTextContents()).join(), /馬可福音/);
    assert.match((await books.allTextContents()).join(), /約翰福音/);
    await context.close();
  });

  for (const scale of ['100%', '150%', '200%']) {
    for (const width of [320, 768, 1024, 1440]) {
      test(`根字級 ${scale}、${width}px：節點文字放得下，沒有切半；不水平捲動`, async () => {
        const { page, context } = await openPage(harness, { width, height: 900 });
        const replies = { [WALK.question]: WALK, [KIN.question]: KIN };
        await mockAsk(page, (question) => replies[question]);
        await page.goto(harness.base);
        await page.evaluate((size) => { document.documentElement.style.fontSize = size; }, scale);
        for (const fixture of [WALK, KIN]) {
          await page.fill('#ask-input', fixture.question);
          await page.press('#ask-input', 'Enter');
          await page.waitForSelector('.graph-stage .node');
          assert.deepEqual(await clippedNodes(page), [], `${fixture.question} 精簡圖`);
          if (fixture === WALK) {
            await page.click('.hint-toggle');
            assert.deepEqual(await clippedNodes(page), [], '完整圖譜');
          }
          await assertNoHorizontalScroll(assert, page, fixture.question);
          await page.click('#ask-again');
        }
        await context.close();
      });
    }
  }

  // ---- 說明與實際一致 ----

  test('kg 讀不到但親屬圖有畫：不會同時說關聯圖讀不到', async () => {
    const broken = { ...KIN, kg: { status: 'unavailable', reason: 'neo4j_query_failed', names: [], passages: [], mentions: [], events: [] } };
    const { page, context } = await showFixture(harness, broken);
    assert.equal(await page.locator('.node--person').count(), 5);
    assert.doesNotMatch(await page.locator('.graph-note').textContent(), /關聯圖/);
    await context.close();
  });

  test('走到且用到、但資料裡沒有任何名字：卡片照畫，段數對得上說明，不當掉', async () => {
    const walk = PLAIN.graph_trace.find((op) => op.op === 'graph_walk');
    const ids = Array.from({ length: 16 }, (_, i) => `ps:act.${i + 1}.1`);
    const sources = ids.map((id, i) => ({
      id, kind: 'passage', book: '使徒行傳', chapter: i + 1, title: `段${i}`, start_key: `act.${i + 1}.1`, end_key: `act.${i + 1}.2`,
      passage_id: id, member_ids: [], build_id: PLAIN.build_id, context: `[${i + 1}] x\n**1** a`,
    }));
    const kg = {
      status: 'ok', reason: null, names: [], mentions: [], events: [],
      passages: ids.map((id, i) => ({ id, title: `段${i}`, book_id: 'act', chapter: i + 1, start_key: `act.${i + 1}.1`, end_key: `act.${i + 1}.2`, walked: true })),
    };
    const fixture = { ...PLAIN, question: '全藏', answer: '答', sources, graph_trace: [{ ...walk, walked: ids, confirmed: ids, passages: [], nodes: ids, names: [], seeds: ids }], kg };
    const { page, context, problems } = await showFixture(harness, fixture);
    assert.equal(await page.locator('.graph-stage .node--passage').count(), 16);
    assert.match(await page.locator('.graph-caption').textContent(), /答案參考的 16 段經文/);
    assert.equal(await page.locator('.graph-status').textContent(), '點段落讀經文。', '圖上沒有名字，就不能叫人點名字');
    assert.equal(await page.locator('.graph-offgraph').count(), 0);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('親屬圖的完整圖譜提示說人物，不說段落', async () => {
    const { page, context } = await showFixture(harness, bigFamily());
    await page.click('.hint-toggle');
    const hint = await page.locator('.prune-hint').textContent();
    assert.match(hint, /完整圖譜：18 位人物、20 條關係/);
    assert.doesNotMatch(hint, /段落/);
    await context.close();
  });

  test('親屬圖的圖例色塊和實際節點同形狀', async () => {
    const { page, context } = await showFixture(harness, KIN);
    const radius = (selector) => page.locator(selector).first().evaluate((node) => parseFloat(getComputedStyle(node).borderTopLeftRadius));
    assert.ok((await radius('.graph-legend .swatch')) <= (await radius('.node--person')));
    await context.close();
  });

  // ---- 關係字不能互相蓋住 ----

  const labelRects = (page) => page.$$eval('.edge-label', (labels) => labels.map((label) => {
    const { left, right, top, bottom } = label.getBoundingClientRect();
    return { text: label.textContent, left, right, top, bottom };
  }));
  const overlapping = (rects) => rects.flatMap((a, i) => rects.slice(i + 1)
    .filter((b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom)
    .map((b) => `${a.text}@${Math.round(a.left)},${Math.round(a.top)} × ${b.text}@${Math.round(b.left)},${Math.round(b.top)}`));

  for (const scale of ['100%', '150%', '200%']) {
    for (const width of [320, 768, 1024, 1280, 1440]) {
      test(`根字級 ${scale}、${width}px 大家族：精簡與完整親屬圖的關係字互不重疊，也不蓋人名`, async () => {
        const family = bigFamily();
        const { page, context } = await openPage(harness, { width, height: 900 });
        await mockAsk(page, () => family);
        await page.goto(harness.base);
        await page.evaluate((size) => { document.documentElement.style.fontSize = size; }, scale);
        await page.fill('#ask-input', family.question);
        await page.press('#ask-input', 'Enter');
        await page.waitForSelector('.edge-label');
        assert.deepEqual(overlapping(await labelRects(page)), [], '精簡圖');
        await page.click('.hint-toggle');
        const rects = await labelRects(page);
        assert.equal(rects.length, 20);
        assert.deepEqual(overlapping(rects), [], '完整圖');
        const covered = await page.$$eval('.node--person', (people, tags) => tags.filter((a) => people.some((person) => {
          const b = person.getBoundingClientRect();
          return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
        })).map((tag) => tag.text), rects);
        assert.deepEqual(covered, [], '不蓋人名');
        const stage = await page.locator('.graph-stage').boundingBox();
        for (const rect of rects) assert.ok(rect.left >= stage.x - 1 && rect.right <= stage.x + stage.width + 1, `關係字超出舞台：${JSON.stringify(rect)}`);
        await assertNoHorizontalScroll(assert, page, `${scale} ${width}`);
        await context.close();
      });
    }
  }

  // ---- 重畫時焦點不能掉 ----

  test('改視窗寬度時焦點在親屬關係字上：焦點留在同一條關係', async () => {
    const { page, context, problems } = await showFixture(harness, KIN, { width: 1280, height: 900 });
    const label = page.locator('.edge-label').nth(1);
    const title = await label.getAttribute('title');
    await label.focus();
    await page.setViewportSize({ width: 800, height: 900 });
    await page.waitForFunction(() => document.querySelector('.graph-stage')?.clientWidth < 800);
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(() => document.activeElement.tagName), 'BUTTON', '不能掉到 body');
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('title')), title);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('同一對人有兩條關係（又配偶又手足）：重畫後焦點回到按的那一條', async () => {
    const trace = KIN.graph_trace.map((op) => (op.op === 'kin_card'
      ? { ...op, edges: [[op.nodes[0], 'SPOUSE_OF', op.nodes[1], 'rut.4.17'], [op.nodes[0], 'SIBLING_OF', op.nodes[1], 'rut.4.21'], ...op.edges.slice(2)] }
      : op));
    const { page, context } = await showFixture(harness, { ...KIN, graph_trace: trace }, { width: 1280, height: 900 });
    const label = page.locator('.edge-label', { hasText: '手足' }).first();
    await label.focus();
    await page.setViewportSize({ width: 800, height: 900 });
    await page.waitForFunction(() => document.querySelector('.graph-stage')?.clientWidth < 800);
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(() => document.activeElement.textContent), '手足');
    await context.close();
  });

  test('改視窗寬度時焦點在節點上：焦點也留著', async () => {
    const { page, context } = await showFixture(harness, WALK, { width: 1280, height: 900 });
    await page.locator('.node--name', { hasText: '巴拿巴' }).focus();
    await page.setViewportSize({ width: 800, height: 900 });
    await page.waitForFunction(() => document.querySelector('.graph-stage')?.clientWidth < 800);
    await page.waitForTimeout(150);
    assert.equal(await page.evaluate(() => document.activeElement.textContent), '巴拿巴');
    await context.close();
  });

  test('親屬圖的 Tab 順序由上而下，人物與關係字照視覺排', async () => {
    const { page, context } = await showFixture(harness, KIN, { width: 1440, height: 900 });
    await page.locator('.segment').first().focus();
    const focusable = await page.locator('.graph-stage button').count();
    const rows = [];
    for (let i = 0; i < focusable; i += 1) {
      await page.keyboard.press('Tab');
      rows.push(await page.evaluate(() => {
        const box = document.activeElement.getBoundingClientRect();
        return box.top + box.height / 2;
      }));
    }
    const sorted = [...rows].sort((a, b) => a - b);
    assert.deepEqual(rows, sorted, `實際順序 ${rows.map((y) => y.toFixed(0))}`);
    await context.close();
  });
});
