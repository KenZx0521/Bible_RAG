// 提問流程：首屏、等待、網址、輸入驗證、錯誤與重試、純鍵盤操作。
import { after, before, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { askViaForm, assertClean, loadFixture, mockAsk, openAnswer, openPage, startHarness } from './support.mjs';

const WALK = loadFixture('walk_event');
const KIN = loadFixture('kin');
const DIRECT = loadFixture('direct');

describe('提問流程', () => {
  let harness;
  before(async () => {
    harness = await startHarness();
  });
  after(() => harness.close());

  test('首屏列出四個範例，點範例就問那一題並同步網址', async () => {
    const { page, context, problems } = await openPage(harness);
    const asked = await mockAsk(page, () => WALK);
    await page.goto(harness.base);
    assert.equal(await page.locator('.example').count(), 4);
    const example = page.locator('.example').first();
    const question = await example.locator('.example-question').textContent();
    await example.click();
    await page.waitForSelector('#answer > *');
    assert.deepEqual(asked, [question]);
    assert.equal(new URL(page.url()).searchParams.get('q'), question);
    assert.equal(await page.locator('#question').textContent(), question);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('等待時問題立刻大字顯示、有說明與已等秒數，沒有假進度條', async () => {
    const { page, context, problems } = await openPage(harness);
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await mockAsk(page, async () => {
      await held;
      return WALK;
    });
    await askViaForm(page, harness.base, WALK.question);
    await page.waitForSelector('#waiting:not([hidden])');
    assert.equal(await page.locator('#question').textContent(), WALK.question);
    assert.match(await page.locator('#waiting-line').textContent(), /通常需要 15–30 秒/);
    await page.waitForFunction(() => /已等 [1-9]\d* 秒/.test(document.getElementById('waiting-elapsed').textContent));
    assert.equal(await page.locator('progress, [role="progressbar"]').count(), 0);
    release();
    await page.waitForSelector('#answer > *');
    assert.equal(await page.locator('#waiting').isVisible(), false);
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('等待的細線只動 transform；reduced-motion 時不動', async () => {
    const moving = await openPage(harness);
    await mockAsk(moving.page, () => new Promise(() => {}));
    await askViaForm(moving.page, harness.base, '測試');
    const name = await moving.page.locator('.waiting-rule span').evaluate((node) => getComputedStyle(node).animationName);
    assert.equal(name, 'leaf-through');
    const frames = await moving.page.evaluate(() => [...document.styleSheets]
      .filter((sheet) => sheet.href?.startsWith(location.origin))
      .flatMap((sheet) => [...sheet.cssRules])
      .filter((rule) => rule.name === 'leaf-through')
      .flatMap((rule) => [...rule.cssRules].map((frame) => [...frame.style])));
    assert.ok(frames.flat().every((property) => property === 'transform'), `只准動 transform：${frames}`);
    await moving.context.close();

    const still = await openPage(harness, { reducedMotion: 'reduce' });
    await mockAsk(still.page, () => new Promise(() => {}));
    await askViaForm(still.page, harness.base, '測試');
    const stillName = await still.page.locator('.waiting-rule span').evaluate((node) => getComputedStyle(node).animationName);
    assert.equal(stillName, 'none');
    assert.equal(await still.page.locator('.waiting-rule span').isVisible(), false, '不動的黑線看起來就是卡住的進度條，要藏起來');
    assert.match(await still.page.locator('#waiting-line').textContent(), /通常需要 15–30 秒/);
    await still.context.close();
  });

  test('切走分頁再回來略過第 30 秒：「比平常久」的訊息照樣換上', async () => {
    const { page, context } = await openPage(harness, { width: 1024, height: 768 });
    await page.clock.install();
    await page.route('**/api/ask', () => {});
    await page.goto(`${harness.base}/?q=${encodeURIComponent(WALK.question)}`);
    await page.waitForSelector('#waiting:not([hidden])');
    await page.clock.fastForward(29_500);
    assert.match(await page.locator('#waiting-line').textContent(), /通常需要 15–30 秒/);
    await page.clock.fastForward(5_000);
    assert.match(await page.locator('#waiting-line').textContent(), /比平常久/);
    await context.close();
  });

  test('320px 長問題：等待訊息與答案都還在第一屏', async () => {
    const long = '請問'.repeat(88);
    const { page, context } = await openPage(harness, { width: 320, height: 640 });
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await mockAsk(page, async () => {
      await held;
      return WALK;
    });
    await page.goto(`${harness.base}/?q=${encodeURIComponent(long)}`);
    await page.waitForSelector('#waiting:not([hidden])');
    for (const selector of ['#waiting-line', '#waiting-elapsed', '#waiting-cancel']) {
      const box = await page.locator(selector).boundingBox();
      assert.ok(box.y + box.height <= 640, `${selector} 在視窗外：${JSON.stringify(box)}`);
    }
    assert.equal(await page.locator('#question').textContent(), long, '問題全文還在，可以捲動看');
    release();
    await page.waitForSelector('#answer > *');
    assert.ok((await page.locator('#answer').boundingBox()).y < 640, '答案起點要在第一屏');
    await context.close();
  });

  test('一般長度的問題維持大字', async () => {
    const { page, context } = await openPage(harness, { width: 320, height: 640 });
    await mockAsk(page, () => WALK);
    await openAnswer(page, harness.base, WALK.question);
    assert.equal(await page.locator('#question').evaluate((node) => node.classList.contains('is-long')), false);
    await context.close();
  });

  test('首屏文案：打開的是和合本修訂版，不能說是「原文」', async () => {
    const { page, context } = await openPage(harness);
    await page.goto(harness.base);
    const text = await page.locator('.ask-lede').textContent();
    assert.match(text, /對照經文/);
    assert.doesNotMatch(text, /原文/);
    await context.close();
  });

  test('空字串與超過 500 字不送出，改了就清掉訊息；剛好 500 字可以送', async () => {
    const { page, context } = await openPage(harness);
    const asked = await mockAsk(page, () => WALK);
    await page.goto(harness.base);
    await page.press('#ask-input', 'Enter');
    assert.match(await page.locator('#ask-message').textContent(), /請先輸入問題/);
    await page.fill('#ask-input', '   ');
    await page.press('#ask-input', 'Enter');
    assert.match(await page.locator('#ask-message').textContent(), /請先輸入問題/);
    await page.fill('#ask-input', '問'.repeat(501));
    await page.press('#ask-input', 'Enter');
    assert.match(await page.locator('#ask-message').textContent(), /500 字以內.*501 字/);
    assert.equal(await page.getAttribute('#ask-input', 'aria-invalid'), 'true');
    assert.deepEqual(asked, []);
    await page.fill('#ask-input', '問'.repeat(500));
    assert.equal(await page.locator('#ask-message').textContent(), '');
    await page.press('#ask-input', 'Enter');
    await page.waitForSelector('#answer > *');
    assert.equal(asked.length, 1);
    await context.close();
  });

  test('網址帶 ?q= 直接問；超長的 ?q= 不送出，回首頁並說明', async () => {
    const { page, context } = await openPage(harness);
    const asked = await mockAsk(page, () => KIN);
    await openAnswer(page, harness.base, KIN.question);
    assert.deepEqual(asked, [KIN.question]);
    assert.equal(await page.title(), `${KIN.question} · 聖經問答`);
    await page.goto(`${harness.base}/?q=${'問'.repeat(501)}`);
    assert.equal(await page.locator('#home').isVisible(), true);
    assert.match(await page.locator('#ask-message').textContent(), /500 字以內/);
    assert.equal(asked.length, 1);
    await context.close();
  });

  test('上一頁回前一題不必重新查詢，再上一頁回首頁；再問一題可以回首屏', async () => {
    const { page, context } = await openPage(harness);
    const replies = { [WALK.question]: WALK, [KIN.question]: KIN };
    const asked = await mockAsk(page, (question) => replies[question]);
    await askViaForm(page, harness.base, WALK.question);
    await page.waitForSelector('.graph-stage .node');
    await page.click('#ask-again');
    assert.equal(await page.locator('#home').isVisible(), true);
    assert.equal(await page.evaluate(() => document.activeElement.id), 'ask-input');
    await page.fill('#ask-input', KIN.question);
    await page.press('#ask-input', 'Enter');
    await page.waitForSelector('.node--person');

    await page.goBack();
    assert.equal(await page.locator('#home').isVisible(), true);
    await page.goBack();
    await page.waitForSelector('.node--name');
    assert.equal(await page.locator('#question').textContent(), WALK.question);
    assert.equal(new URL(page.url()).searchParams.get('q'), WALK.question);
    assert.equal(asked.length, 2, '回前一題用記憶體裡的答案');
    await page.goBack();
    assert.equal(await page.locator('#home').isVisible(), true);
    await context.close();
  });

  test('等待中換題：舊請求的結果不會蓋掉畫面', async () => {
    const { page, context, problems } = await openPage(harness);
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    await mockAsk(page, async (question) => {
      if (question === WALK.question) await held;
      return question === WALK.question ? WALK : KIN;
    });
    await askViaForm(page, harness.base, WALK.question);
    await page.waitForSelector('#waiting:not([hidden])');
    await page.click('#waiting-cancel');
    assert.equal(await page.locator('#home').isVisible(), true);
    await page.fill('#ask-input', KIN.question);
    await page.press('#ask-input', 'Enter');
    await page.waitForSelector('.node--person');
    release();
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#question').textContent(), KIN.question);
    assert.equal(await page.locator('.node--person').first().isVisible(), true);
    assert.deepEqual(problems.page, []);
    await context.close();
  });

  for (const [status, message] of [
    [429, '現在問的人比較多，請稍後再試'],
    [502, '查詢服務暫時沒有回應'],
    [504, '查詢服務暫時沒有回應'],
  ]) {
    test(`${status} 顯示友善訊息與重試，重試成功就看到答案`, async () => {
      const { page, context, problems } = await openPage(harness);
      const asked = await mockAsk(page, (_q, nth) => (nth === 1 ? { status, body: { error: '內部細節不該出現' } } : WALK));
      await askViaForm(page, harness.base, WALK.question);
      await page.waitForSelector('#failure:not([hidden])');
      const text = await page.locator('#failure').textContent();
      assert.ok(text.includes(message), text);
      assert.ok(!text.includes('內部細節'), '不顯示 server 細節');
      assert.equal(await page.locator('#question').textContent(), WALK.question);
      assert.equal(await page.evaluate(() => document.activeElement.id), 'retry');
      await page.click('#retry');
      await page.waitForSelector('#answer > *');
      assert.equal(asked.length, 2);
      assert.equal(await page.locator('#failure').isVisible(), false);
      await assertClean(assert, page, problems, { allowHttpErrors: true });
      await context.close();
    });
  }

  test('連線失敗也是同一個友善畫面；失敗的答案不進記憶體', async () => {
    const { page, context } = await openPage(harness);
    const asked = await mockAsk(page, (_q, nth) => (nth === 1 ? null : WALK));
    await askViaForm(page, harness.base, WALK.question);
    await page.waitForSelector('#failure:not([hidden])');
    assert.match(await page.locator('#failure-message').textContent(), /查詢服務暫時沒有回應/);
    await page.click('#failure-home');
    await page.goBack();
    await page.waitForSelector('#answer > *');
    assert.equal(asked.length, 2);
    await context.close();
  });

  test('只用鍵盤（Tab／Enter）可以提問、開引用與來源，ESC 關閉', async () => {
    const { page, context, problems } = await openPage(harness);
    await mockAsk(page, () => WALK);
    await page.goto(harness.base);
    const focusIs = () => page.evaluate(() => document.activeElement.id || document.activeElement.className);
    for (let tab = 0; tab < 5 && (await focusIs()) !== 'ask-input'; tab += 1) await page.keyboard.press('Tab');
    assert.equal(await focusIs(), 'ask-input');
    await page.keyboard.type(WALK.question);
    await page.keyboard.press('Enter');
    await page.waitForSelector('#answer > *');
    assert.equal(await focusIs(), 'question', '答案出來後焦點移到問題');

    await page.keyboard.press('Tab');
    assert.equal(await focusIs(), 'cite');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#reader[open]');
    assert.equal(await page.locator('.verse.is-cited').count() > 0, true);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#reader').isVisible(), false);
    assert.equal(await focusIs(), 'cite', '焦點回到引用');

    // 繼續 Tab 走到第一個來源列
    for (let tab = 0; tab < 40 && (await focusIs()) !== 'source'; tab += 1) await page.keyboard.press('Tab');
    assert.equal(await focusIs(), 'source');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#reader[open]');
    await page.keyboard.press('Escape');
    assert.equal(await focusIs(), 'source');
    await assertClean(assert, page, problems);
    await context.close();
  });

  // ---- 讀完再問 ----

  for (const [width, height] of [[320, 640], [768, 1024], [1440, 900]]) {
    test(`${width}px 捲到底也有「再問一題」，按了回首屏並把焦點放在輸入框`, async () => {
      const { page, context, problems } = await openPage(harness, { width, height });
      await mockAsk(page, () => WALK);
      await openAnswer(page, harness.base, WALK.question);
      await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
      await page.waitForFunction(() => window.scrollY > 0 || document.documentElement.scrollHeight <= window.innerHeight);
      const foot = page.locator('#ask-again-foot');
      assert.equal(await foot.textContent(), '再問一題');
      const inView = await foot.evaluate((node) => {
        const box = node.getBoundingClientRect();
        return box.top >= 0 && box.bottom <= window.innerHeight;
      });
      assert.equal(inView, true, '捲到底時要看得到');
      await foot.click();
      assert.equal(await page.locator('#home').isVisible(), true);
      assert.equal(await page.evaluate(() => document.activeElement.id), 'ask-input');
      assert.equal(new URL(page.url()).search, '');
      await assertClean(assert, page, problems);
      await context.close();
    });
  }

  test('底部的「再問一題」只在答案畫面出現', async () => {
    const { page, context } = await openPage(harness);
    await mockAsk(page, () => new Promise(() => {}));
    await page.goto(harness.base);
    assert.equal(await page.locator('#ask-again-foot').isVisible(), false, '首屏');
    await page.fill('#ask-input', '測試');
    await page.press('#ask-input', 'Enter');
    await page.waitForSelector('#waiting:not([hidden])');
    assert.equal(await page.locator('#ask-again-foot').isVisible(), false, '等待');
    await context.close();
  });

  // ---- 鍵盤不必穿過整張圖 ----

  test('鍵盤讀完答案可以跳過關聯圖，一步到經文來源；連結平常看不到', async () => {
    const { page, context, problems } = await openPage(harness, { width: 1440, height: 900 });
    await mockAsk(page, () => WALK);
    await openAnswer(page, harness.base, WALK.question);
    const skip = page.locator('.skip-link');
    assert.equal(await skip.textContent(), '跳到經文來源');
    const clipped = () => skip.evaluate((node) => node.getBoundingClientRect().width <= 1);
    assert.equal(await clipped(), true, '沒有焦點時不佔版面');
    const citeCount = await page.locator('.cite').count();
    await page.locator('#question').focus();
    for (let tab = 0; tab < citeCount; tab += 1) await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'cite');
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.className.includes('skip-link')), true, '引用之後的第一站就是它');
    assert.equal(await clipped(), false, '拿到焦點時看得到');
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.className), 'source');
    assert.equal(await page.evaluate(() => document.activeElement.querySelector('.source-no').textContent), '1');
    await assertClean(assert, page, problems);
    await context.close();
  });

  test('不跳過也行：Tab 還是能走到每個節點', async () => {
    const { page, context } = await openPage(harness, { width: 1440, height: 900 });
    await mockAsk(page, () => WALK);
    await openAnswer(page, harness.base, WALK.question);
    await page.locator('.skip-link').focus();
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.className.includes('hint-toggle')), true);
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('node')), true);
    await context.close();
  });

  test('沒有來源時，跳過連結改到底部的再問一題；沒有圖就沒有跳過連結', async () => {
    const { page, context } = await openPage(harness, { width: 1440, height: 900 });
    await mockAsk(page, (question) => (question === KIN.question ? { ...KIN, sources: [] } : DIRECT));
    await openAnswer(page, harness.base, KIN.question);
    await page.locator('.skip-link').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(() => document.activeElement.id), 'ask-again-foot');
    await openAnswer(page, harness.base, DIRECT.question);
    assert.equal(await page.locator('.skip-link').count(), 0);
    await context.close();
  });
});
