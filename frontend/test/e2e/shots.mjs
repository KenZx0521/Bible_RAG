// 視覺檢查用：截 320／768／1024／1440 四個寬度的主要畫面。不是測試，手動跑：
//   SHOTS_DIR=/some/dir node test/e2e/shots.mjs [畫面名…]
// 字型真的向 Google Fonts 拿，並快取到 SHOTS_DIR/.fontcache，第二次起不必再下載。
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { bigFamily, loadFixture, startHarness } from './support.mjs';

const OUT = process.env.SHOTS_DIR ?? fileURLToPath(new URL('./screenshots/', import.meta.url));
const FONT_CACHE = join(OUT, '.fontcache');
const WIDTHS = [
  [320, 640],
  [768, 1024],
  [1024, 768],
  [1440, 900],
];
const WALK_Q = '保羅第一次宣教旅程中經過哪些城市，巴拿巴和他的關係是什麼？';
const FONT_WAIT_MS = 60_000;

async function cachedFont(route) {
  const url = route.request().url();
  const file = join(FONT_CACHE, createHash('sha256').update(url).digest('hex'));
  if (existsSync(file)) {
    const { contentType, body } = JSON.parse(readFileSync(file, 'utf8'));
    return route.fulfill({ status: 200, contentType, body: Buffer.from(body, 'base64'), headers: { 'access-control-allow-origin': '*' } });
  }
  const response = await route.fetch();
  const body = await response.body();
  const contentType = response.headers()['content-type'] ?? 'application/octet-stream';
  writeFileSync(file, JSON.stringify({ contentType, body: body.toString('base64') }));
  return route.fulfill({ response, body });
}

async function settle(page) {
  await Promise.race([page.evaluate(() => document.fonts.ready.then(() => true)), new Promise((r) => setTimeout(r, FONT_WAIT_MS))]);
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.waitForTimeout(300);
}

async function waitForAnswer(page, base, question) {
  await page.goto(`${base}/?q=${encodeURIComponent(question)}`);
  await page.waitForSelector('#answer > *');
}

/** 走了，但答案用的段落全部沒走到：測「沒有卡片可畫」的畫面。 */
function walkedButUnused() {
  const plain = loadFixture('walk_plain');
  const notWalked = new Set(plain.kg.passages.filter((passage) => !passage.walked).map((passage) => passage.id));
  const trace = plain.graph_trace.map((op) => (op.op === 'graph_walk' ? { ...op, confirmed: [], passages: [] } : op));
  return { ...plain, sources: plain.sources.filter((source) => notWalked.has(source.passage_id)), graph_trace: trace };
}

const SCENES = {
  home: {
    run: async (page, base) => page.goto(base),
  },
  waiting: {
    run: async (page, base) => {
      await page.unroute('**/api/ask');
      await page.route('**/api/ask', () => {});
      await page.goto(`${base}/?q=${encodeURIComponent(WALK_Q)}`);
      await page.waitForSelector('#waiting:not([hidden])');
      await page.waitForTimeout(2200);
    },
  },
  walk: {
    fullPage: true,
    run: async (page, base) => waitForAnswer(page, base, WALK_Q),
  },
  kin: {
    fullPage: true,
    fixture: 'kin',
    run: async (page, base) => waitForAnswer(page, base, '大衛的曾祖父是誰？'),
  },
  full: {
    fullPage: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.click('.hint-toggle');
    },
  },
  reader: {
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.click('.cite >> nth=3');
      await page.waitForSelector('#reader[open]');
      await page.waitForTimeout(300);
    },
  },
  regnal: {
    extra: true,
    fullPage: true,
    fixture: 'regnal',
    run: async (page, base) => waitForAnswer(page, base, '耶羅波安之後的第二位以色列王是誰？'),
  },
  direct: {
    extra: true,
    fullPage: true,
    fixture: 'direct',
    run: async (page, base) => waitForAnswer(page, base, '約翰福音 3:16 說了什麼？'),
  },
  plain: {
    extra: true,
    fullPage: true,
    fixture: 'walk_plain',
    run: async (page, base) => waitForAnswer(page, base, '耶穌在哪裡受洗？'),
  },
  regnalwalk: {
    extra: true,
    fullPage: true,
    fixture: 'regnal',
    run: async (page, base) => {
      await waitForAnswer(page, base, '耶羅波安之後的第二位以色列王是誰？');
      await page.click('.segment >> nth=1');
    },
  },
  kinwalk: {
    extra: true,
    fullPage: true,
    fixture: 'kin',
    run: async (page, base) => {
      await waitForAnswer(page, base, '大衛的曾祖父是誰？');
      await page.click('.segment >> nth=1');
    },
  },
  empty: {
    extra: true,
    fullPage: true,
    respond: walkedButUnused(),
    run: async (page, base) => waitForAnswer(page, base, '耶穌在哪裡受洗？'),
  },
  emptyfull: {
    extra: true,
    fullPage: true,
    respond: walkedButUnused(),
    run: async (page, base) => {
      await waitForAnswer(page, base, '耶穌在哪裡受洗？');
      await page.click('.hint-toggle');
    },
  },
  familyfull: {
    extra: true,
    fullPage: true,
    respond: bigFamily(),
    run: async (page, base) => {
      await waitForAnswer(page, base, '雅各的親屬有誰？');
      await page.click('.hint-toggle');
    },
  },
  skiplink: {
    extra: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.locator('.skip-link').focus();
    },
  },
  bottom: {
    extra: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    },
  },
  family: {
    extra: true,
    fullPage: true,
    respond: bigFamily(),
    run: async (page, base) => waitForAnswer(page, base, '雅各的親屬有誰？'),
  },
  fullscroll: {
    extra: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.click('.hint-toggle');
      await page.locator('.node--name', { hasText: '巴拿巴' }).scrollIntoViewIfNeeded();
      await page.locator('.node--name', { hasText: '巴拿巴' }).click();
      await page.waitForTimeout(300);
    },
  },
  states: {
    extra: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.keyboard.press('Tab');
      await page.locator('.node--passage', { hasText: '在塞浦路斯傳道' }).hover();
    },
  },
  homestates: {
    extra: true,
    run: async (page, base) => {
      await page.goto(base);
      await page.focus('#ask-input');
      await page.press('#ask-input', 'Enter');
      await page.locator('.example').nth(1).hover();
    },
  },
  failure: {
    extra: true,
    respond: { status: 429, body: { error: 'x' } },
    run: async (page, base) => {
      await page.goto(`${base}/?q=${encodeURIComponent(WALK_Q)}`);
      await page.waitForSelector('#failure:not([hidden])');
    },
  },
  focused: {
    extra: true,
    run: async (page, base) => {
      await waitForAnswer(page, base, WALK_Q);
      await page.click('.node--name.is-asked >> nth=0');
    },
  },
};

async function shootScene(harness, name, scene, [width, height]) {
  const context = await harness.browser.newContext({ viewport: { width, height }, locale: 'zh-TW', deviceScaleFactor: 1 });
  const page = await context.newPage();
  await page.route(/^https:\/\/fonts\.(googleapis|gstatic)\.com\//, cachedFont);
  const reply = scene.respond ?? loadFixture(scene.fixture ?? 'walk_event');
  await page.route('**/api/ask', (route) => route.fulfill({
    status: reply.status ?? 200,
    contentType: 'application/json',
    body: JSON.stringify(reply.body ?? reply),
  }));
  await scene.run(page, harness.base);
  await settle(page);
  await page.screenshot({ path: join(OUT, `${name}-${width}.png`), fullPage: Boolean(scene.fullPage) });
  await context.close();
}

async function main() {
  mkdirSync(FONT_CACHE, { recursive: true });
  const wanted = process.argv.slice(2);
  const harness = await startHarness();
  const names = Object.keys(SCENES).filter((name) => (wanted.length > 0 ? wanted.includes(name) : !SCENES[name].extra));
  for (const name of names) {
    for (const size of WIDTHS) {
      await shootScene(harness, name, SCENES[name], size);
      console.info(`${name}-${size[0]}`);
    }
  }
  await harness.close();
}

await main();
