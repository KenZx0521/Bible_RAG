// e2e 共用：開真的 demo server（要驗真的 CSP 標頭），/api/ask 用 page.route 接到 fixtures，不打真後端。
import { readFileSync } from 'node:fs';
import { chromium } from 'playwright';

import { LIMITS } from '../../lib/config.mjs';
import { createDemoServer } from '../../server.mjs';

const SILENT_LOG = Object.freeze({ info() {}, warn() {}, error() {} });
const EMPTY_CSS = { status: 200, contentType: 'text/css', body: '' };
const FONT_HOSTS = /^https:\/\/fonts\.(googleapis|gstatic)\.com\//;

export function loadFixture(name) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), 'utf8'));
}

/** 合成資料：kin fixture 換成 18 人的大家族，含配偶、手足，用來測親屬圖剪枝與標籤位置。 */
export function bigFamily() {
  const people = ['亞伯拉罕', '撒拉', '夏甲', '以撒', '以實瑪利', '利百加', '雅各', '以掃', '拉結', '利亞',
    '約瑟', '便雅憫', '流便', '西緬', '利未', '猶大', '以法蓮', '瑪拿西'];
  const id = (name) => `p${people.indexOf(name)}`;
  const parent = (a, b) => [id(a), 'PARENT_OF', id(b), 'gen.21.3'];
  const edges = [
    parent('亞伯拉罕', '以撒'), parent('撒拉', '以撒'), parent('亞伯拉罕', '以實瑪利'), parent('夏甲', '以實瑪利'),
    [id('亞伯拉罕'), 'SPOUSE_OF', id('撒拉'), 'gen.11.29'],
    [id('以撒'), 'SPOUSE_OF', id('利百加'), 'gen.24.67'],
    parent('以撒', '雅各'), parent('以撒', '以掃'), parent('利百加', '雅各'), [id('雅各'), 'SIBLING_OF', id('以掃'), 'gen.25.26'],
    [id('雅各'), 'SPOUSE_OF', id('拉結'), 'gen.29.28'], [id('雅各'), 'SPOUSE_OF', id('利亞'), 'gen.29.23'],
    parent('拉結', '約瑟'), parent('拉結', '便雅憫'), parent('利亞', '流便'), parent('利亞', '西緬'), parent('利亞', '利未'), parent('利亞', '猶大'),
    parent('約瑟', '以法蓮'), parent('約瑟', '瑪拿西'),
  ];
  const kin = loadFixture('kin');
  const op = { op: 'kin_card', injected: 'prompt', nodes: people.map(id), names: people, edges };
  return {
    ...kin,
    question: '雅各的親屬有誰？',
    aux_card: { ...kin.aux_card, kings: [id('雅各')] },
    graph_trace: [op],
    kg: { status: 'not_walked', reason: null, names: [], passages: [], mentions: [], events: [] },
  };
}

function testConfig() {
  return {
    host: '127.0.0.1',
    port: 0,
    backendUrl: 'http://127.0.0.1:9',
    neo4j: { url: 'http://127.0.0.1:9/db/neo4j/query/v2', user: '', password: '', timeoutMs: 50 },
    limits: LIMITS,
  };
}

/** 開 demo server 與瀏覽器；close() 一次收乾淨。 */
export async function startHarness() {
  const server = createDemoServer({ config: testConfig(), log: SILENT_LOG });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch();
  const close = async () => {
    await browser.close();
    await new Promise((resolve) => {
      server.close(resolve);
      server.closeAllConnections();
    });
  };
  return { base: `http://127.0.0.1:${server.address().port}`, browser, close };
}

function fulfillJson(route, status, body) {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

/** 把 /api/ask 接到 handler；handler 回 {status, body} 或 fixture 物件。回傳收到的問題清單。 */
export async function mockAsk(page, respond) {
  const asked = [];
  await page.route('**/api/ask', async (route) => {
    const { question } = route.request().postDataJSON();
    asked.push(question);
    const reply = await respond(question, asked.length);
    if (reply === null) return route.abort('failed');
    if (reply.status) return fulfillJson(route, reply.status, reply.body ?? {});
    return fulfillJson(route, 200, reply);
  });
  return asked;
}

/** 開新頁（獨立 context）。字型回空 CSS：測試不依賴外部網路，也不會有載入失敗的 console 錯誤。 */
export async function openPage(harness, { width = 1280, height = 900, reducedMotion } = {}) {
  const context = await harness.browser.newContext({
    viewport: { width, height },
    locale: 'zh-TW',
    reducedMotion,
  });
  const page = await context.newPage();
  await page.route(FONT_HOSTS, (route) => route.fulfill(EMPTY_CSS));
  await page.addInitScript(() => {
    window.__csp = [];
    document.addEventListener('securitypolicyviolation', (event) => {
      window.__csp.push(`${event.violatedDirective} ${event.blockedURI}`);
    });
  });
  const problems = { console: [], page: [] };
  page.on('console', (message) => {
    if (message.type() === 'error') problems.console.push(message.text());
  });
  page.on('pageerror', (error) => problems.page.push(String(error)));
  return { page, context, problems };
}

/** 頁面乾不乾淨：瀏覽器自己印的 HTTP 狀態錯誤（故意測 429／502 時）由 allowHttpErrors 放行。 */
export async function assertClean(assert, page, problems, { allowHttpErrors = false } = {}) {
  const consoleErrors = problems.console.filter(
    (text) => !(allowHttpErrors && text.startsWith('Failed to load resource')),
  );
  assert.deepEqual(consoleErrors, [], 'console 不應有錯誤');
  assert.deepEqual(problems.page, [], '不應有未捕捉的例外');
  assert.deepEqual(await page.evaluate(() => window.__csp), [], '不應有 CSP 違規');
}

export async function assertNoHorizontalScroll(assert, page, label = '') {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 0, `${label} 不應水平捲動（多出 ${overflow}px）`);
}

// 紙紋疊上去之後實際取樣到的紙色，比 --paper 略深；透明底的元素以它算對比
const SAMPLED_PAPER = [244, 237, 225];

function luminance(rgb) {
  const [r, g, b] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function contrastRatio(a, b) {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

/** 元素的文字（property 可換成 outlineColor、stroke…）對它實際底色的對比，把祖先的 opacity 都算進去。 */
export async function effectiveContrast(locator, property = 'color') {
  await locator.page().evaluate(() => Promise.all(document.getAnimations().map((animation) => animation.finished.catch(() => {}))));
  const { fg, alpha, bg, bgAlpha } = await locator.evaluate((element, prop) => {
    const rgba = (text) => {
      const [r, g, b, a = 1] = text.match(/[\d.]+/g).map(Number);
      return { rgb: [r, g, b], a };
    };
    let opacity = 1;
    let background = null;
    for (let node = element; node; node = node.parentElement) {
      const style = getComputedStyle(node);
      opacity *= Number(style.opacity);
      const fill = rgba(style.backgroundColor);
      if (!background && fill.a > 0) background = { rgb: fill.rgb, opacity };
    }
    const own = rgba(getComputedStyle(element)[prop]);
    return { fg: own.rgb, alpha: own.a * opacity, bg: background?.rgb ?? null, bgAlpha: background?.opacity ?? 0 };
  }, property);
  const mix = (top, under, ratio) => top.map((channel, i) => channel * ratio + under[i] * (1 - ratio));
  const base = bg ? mix(bg, SAMPLED_PAPER, bgAlpha) : SAMPLED_PAPER;
  return contrastRatio(mix(fg, base, alpha), base);
}

/** 節點裡要顯示的文字放不放得下：line-clamp 的標題以 clamp 後的行數算，超過就是被切半。回傳放不下的節點。 */
export function clippedNodes(page) {
  return page.$$eval('.graph-stage .node', (nodes) => nodes.flatMap((node) => {
    const style = getComputedStyle(node);
    const room = node.clientHeight - parseFloat(style.paddingTop) - parseFloat(style.paddingBottom);
    const need = [...node.children].reduce((sum, child) => {
      const childStyle = getComputedStyle(child);
      const clamp = Number.parseInt(childStyle.webkitLineClamp, 10);
      const clamped = clamp > 0 ? clamp * parseFloat(childStyle.lineHeight) : Infinity;
      return sum + Math.min(child.scrollHeight, clamped);
    }, 0);
    return need > room + 1 ? [`${node.textContent}：要 ${need}，只有 ${room}`] : [];
  }));
}

/** 從首屏輸入問題並送出。 */
export async function askViaForm(page, base, question) {
  await page.goto(base);
  await page.fill('#ask-input', question);
  await page.press('#ask-input', 'Enter');
}

/** 直接帶 ?q= 打開，等到答案出現。 */
export async function openAnswer(page, base, question) {
  await page.goto(`${base}/?q=${encodeURIComponent(question)}`);
  await page.waitForSelector('#answer > *');
}

export { fulfillJson };
