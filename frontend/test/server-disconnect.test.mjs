// 讀者中途離開（按「換一個問題」、關分頁、RST）。實測 staging r12：連線中斷後 backend 仍把生成跑完
// （vLLM finished_reason 是 stop，不是 abort），所以額度要等 backend 真的回來才還；
// 但讀者不該因此撞 429，新題目排隊等斷線的題目跑完。
import { afterEach, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { backendFromFixture, loadFixture, sendJson, startStack, waitUntil } from './helpers/stack.mjs';

const FIXTURE = loadFixture('walk_plain');
const SETTLE_MS = 30;

const stacks = [];
afterEach(async () => {
  await Promise.all(stacks.splice(0).map((s) => s.close()));
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** backend 不自動回：release() 依序放行，記下同時進行的最大題數。 */
async function heldStack(options = {}) {
  const reply = backendFromFixture(FIXTURE);
  const held = [];
  const peak = { now: 0, max: 0 };
  const s = await startStack({
    fixture: FIXTURE,
    ...options,
    backend: (entry, res) => {
      if (entry.url !== '/api/v1/query') return reply(entry, res);
      peak.now += 1;
      peak.max = Math.max(peak.max, peak.now);
      held.push(() => {
        peak.now -= 1;
        reply(entry, res);
      });
      return undefined;
    },
  });
  stacks.push(s);
  const queries = () => s.backend.requests.filter((request) => request.url === '/api/v1/query').length;
  return { s, held, peak, queries, release: () => held.shift()() };
}

/** 兩題都進到 backend 後斷線，額度還佔著（backend 還在跑）。 */
async function twoAbandoned({ s, queries }) {
  const sockets = [await s.openAsk('一'), await s.openAsk('二')];
  await waitUntil(() => queries() === 2, '兩題都進到 backend');
  sockets.forEach((socket) => socket.destroy());
  await sleep(SETTLE_MS);
}

describe('POST /api/ask：讀者中途離開', () => {
  test('按兩次「換一個問題」再問第三題：不回 429，排隊等 backend 跑完；GPU 上同時仍不超過 2 題', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);

    let settled = false;
    const third = stack.s.ask('三').finally(() => { settled = true; });
    await sleep(SETTLE_MS);
    assert.equal(settled, false, '不該立刻被拒絕');
    assert.equal(stack.queries(), 2, 'backend 還在跑兩題，不再多送');

    stack.release();
    await waitUntil(() => stack.queries() === 3, '空出來就輪到第三題');
    assert.equal(stack.peak.max, 2);
    stack.release();
    stack.release();
    assert.equal((await third).status, 200);
  });

  test('另一個 IP 也不會被斷線的題目擋成 429', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);

    const other = stack.s.ask('另一個人', {}, '127.0.0.3');
    await sleep(SETTLE_MS);
    stack.release();
    await waitUntil(() => stack.queries() === 3, '輪到另一個 IP');
    stack.release();
    stack.release();
    assert.equal((await other).status, 200);
  });

  test('斷線的題目 backend 回來後就還額度，不查 Neo4j', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);

    stack.release();
    stack.release();
    await sleep(SETTLE_MS);

    assert.equal(stack.s.neo4j.requests.length, 0, '沒有人要看這個答案了');
    const next = stack.s.ask('下一題');
    await waitUntil(() => stack.queries() === 3, '額度已還');
    stack.release();
    assert.equal((await next).status, 200);
  });

  test('排隊中也離開：不打 backend，也不佔名額', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);

    const waiting = await stack.s.openAsk('排隊中離開');
    await sleep(SETTLE_MS);
    waiting.destroy();
    await sleep(SETTLE_MS);
    stack.release();
    stack.release();
    await sleep(SETTLE_MS);

    assert.equal(stack.queries(), 2);
    const next = stack.s.ask('下一題');
    await waitUntil(() => stack.queries() === 3, '名額是空的');
    stack.release();
    assert.equal((await next).status, 200);
  });

  test('一題還有人在等、一題斷線：新題目也排隊', async () => {
    const stack = await heldStack();
    const present = stack.s.ask('還在等');
    await waitUntil(() => stack.queries() === 1, '第一題進 backend');
    const socket = await stack.s.openAsk('會離開');
    await waitUntil(() => stack.queries() === 2, '第二題進 backend');
    socket.destroy();
    await sleep(SETTLE_MS);

    const third = stack.s.ask('三');
    await sleep(SETTLE_MS);
    stack.release();
    assert.equal((await present).status, 200);
    await waitUntil(() => stack.queries() === 3, '輪到第三題');
    stack.release();
    stack.release();
    assert.equal((await third).status, 200);
  });

  test('排隊有上限，一個 IP 只佔一席：不讓單一來源把隊伍排滿', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);

    const first = stack.s.ask('A 排隊', {}, '127.0.0.4');
    await sleep(SETTLE_MS);
    const sameIp = await stack.s.ask('A 又排一次', {}, '127.0.0.4');
    assert.equal(sameIp.status, 429);
    assert.equal(sameIp.headers['retry-after'], '15');

    const second = stack.s.ask('B 排隊', {}, '127.0.0.5');
    await sleep(SETTLE_MS);
    assert.equal((await stack.s.ask('C 沒位子了', {}, '127.0.0.6')).status, 429);

    stack.release();
    stack.release();
    await waitUntil(() => stack.queries() === 4, 'A、B 依序進 backend');
    stack.release();
    stack.release();
    assert.equal((await first).status, 200);
    assert.equal((await second).status, 200);
  });

  test('排隊先來先服務', async () => {
    const stack = await heldStack();
    await twoAbandoned(stack);
    const first = stack.s.ask('先來', {}, '127.0.0.7');
    await sleep(SETTLE_MS);
    const second = stack.s.ask('後到', {}, '127.0.0.8');
    await sleep(SETTLE_MS);

    stack.release();
    await waitUntil(() => stack.queries() === 3, '輪到第一個');

    assert.equal(JSON.parse(stack.s.backend.requests.at(-1).text).question, '先來');
    stack.release();
    stack.release();
    await waitUntil(() => stack.queries() === 4, '輪到第二個');
    stack.release();
    await Promise.all([first, second]);
  });

  test('backend 卡住：排隊等太久回 429，不會無限等；還沒進 backend', async () => {
    const stack = await heldStack({ limits: { askQueueWaitMs: 60 } });
    await twoAbandoned(stack);

    const waited = await stack.s.ask('等不到');

    assert.equal(waited.status, 429);
    assert.equal(stack.queries(), 2);
    stack.release();
    stack.release();
  });

  test('backend 失敗的斷線題目也會還額度', async () => {
    let nth = 0;
    const s = await startStack({
      fixture: FIXTURE,
      backend: (entry, res) => {
        if (entry.url !== '/api/v1/query') return backendFromFixture(FIXTURE)(entry, res);
        nth += 1;
        if (nth === 1) return setTimeout(() => sendJson(res, 500, { detail: 'boom' }), SETTLE_MS);
        return backendFromFixture(FIXTURE)(entry, res);
      },
      limits: { maxConcurrentAsks: 1 },
    });
    stacks.push(s);
    const socket = await s.openAsk('會失敗');
    await waitUntil(() => s.backend.requests.length === 1, '進 backend');
    socket.destroy();

    assert.equal((await s.ask('下一題')).status, 200);
  });
});

describe('POST /api/ask：限流看得到連線斷掉的請求', () => {
  test('送完 body 立刻 RST：仍算在該 IP，不會跑到共用的 unknown 桶多拿額度', async () => {
    const LIMIT = 3;
    const s = await startStack({ fixture: FIXTURE, limits: { asksPerMinute: LIMIT } });
    stacks.push(s);
    const IP = '127.0.0.41';

    for (let i = 0; i < LIMIT; i += 1) {
      (await s.openAsk(`RST ${i}`, { localAddress: IP })).resetAndDestroy();
      await sleep(SETTLE_MS);
    }
    const statuses = [];
    for (let i = 0; i <= LIMIT; i += 1) statuses.push((await s.ask(`正常 ${i}`, {}, IP)).status);

    const reached = s.backend.requests.filter((request) => request.url === '/api/v1/query').length;
    assert.ok(reached <= LIMIT, `同一分鐘內這個 IP 最多 ${LIMIT} 題進 backend，實際 ${reached}`);
    assert.equal(statuses.at(-1), 429);
  });
});
