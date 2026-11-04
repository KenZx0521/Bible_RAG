// server 整合測試：/api/ask、Neo4j 失敗不拖垮答案、併發與限流、backend 失敗。
// 靜態檔、verse、health、設定檔在另外兩個 suite，這裡一併載入。
import { afterEach, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import './helpers/server-static.suite.mjs';
import './helpers/server-config.suite.mjs';
import {
  TEST_BASIC,
  TEST_PASSWORD,
  backendFromFixture,
  loadFixture,
  rawRequest,
  sendJson,
  startStack,
  toBackendBody,
  waitUntil,
} from './helpers/stack.mjs';

const stacks = [];
async function stack(options) {
  const started = await startStack(options);
  stacks.push(started);
  return started;
}

afterEach(async () => {
  await Promise.all(stacks.splice(0).map((s) => s.close()));
});

function assertNoSecret(started, response) {
  const everything = [response.text, ...started.sink.lines].join('\n');
  assert.equal(everything.includes(TEST_PASSWORD), false, '回應或 log 出現密碼');
  assert.equal(everything.includes(TEST_BASIC), false, '回應或 log 出現 Basic 認證');
}

describe('POST /api/ask：正常流程', () => {
  test('形狀與真實 fixture 完全一致', async () => {
    const fixture = loadFixture('walk_plain');
    const s = await stack({ fixture });

    const response = await s.ask(fixture.question);

    assert.equal(response.status, 200);
    assert.deepEqual(response.json, fixture);
    assert.match(response.headers['content-type'], /^application\/json/);
  });

  test('帶事件的走圖：Neo4j 收到 build_id 過濾與 READ', async () => {
    const fixture = loadFixture('walk_event');
    const s = await stack({ fixture });

    const response = await s.ask(fixture.question);

    assert.deepEqual(response.json.kg, fixture.kg);
    assert.equal(s.neo4j.requests.length, 4);
    for (const request of s.neo4j.requests) {
      const body = JSON.parse(request.text);
      assert.equal(body.accessMode, 'READ');
      assert.equal(body.parameters.b, fixture.build_id);
    }
  });

  test('轉 backend 只帶 question（已去空白）與 include_context', async () => {
    const s = await stack();

    await s.ask('  耶穌在哪裡受洗？\n');

    const [request] = s.backend.requests;
    assert.equal(request.url, '/api/v1/query');
    assert.deepEqual(JSON.parse(request.text), { question: '耶穌在哪裡受洗？', include_context: true });
  });

  test('沒走圖的題目不查 Neo4j', async () => {
    const fixture = loadFixture('direct');
    const s = await stack({ fixture });

    const response = await s.ask(fixture.question);

    assert.deepEqual(response.json, fixture);
    assert.equal(s.neo4j.requests.length, 0);
  });

  test('沒有 source：build_id 從 backend health 拿', async () => {
    const fixture = loadFixture('walk_plain');
    const s = await stack({
      fixture,
      backend: (entry, res) => {
        if (entry.url === '/api/v1/health') {
          return sendJson(res, 200, { status: 'ok', build_id: 'b_health', graph: { state: 'ready' } });
        }
        return sendJson(res, 200, { ...toBackendBody(fixture), sources: [] });
      },
    });

    const response = await s.ask(fixture.question);

    assert.equal(response.json.build_id, 'b_health');
    assert.ok(s.neo4j.requests.every((r) => JSON.parse(r.text).parameters.b === 'b_health'));
  });
});

describe('POST /api/ask：Neo4j 失敗不拖垮答案', () => {
  const fixture = loadFixture('walk_plain');
  const failures = {
    '401': (_e, res) => sendJson(res, 401, { errors: [{ code: 'Neo.ClientError.Security.Unauthorized', message: 'no' }] }),
    '401 且回應夾帶帳密': (entry, res) => sendJson(res, 401, { errors: [{ code: `x ${TEST_PASSWORD}`, message: entry.headers.authorization }] }),
    逾時: () => {},
    '500': (_e, res) => sendJson(res, 500, { errors: [] }),
    非_JSON: (_e, res) => res.end('oops'),
  };
  for (const [name, neo4j] of Object.entries(failures)) {
    test(name, { timeout: 5000 }, async () => {
      const s = await stack({ fixture, neo4j, neo4jTimeoutMs: 80 });

      const response = await s.ask(fixture.question);

      assert.equal(response.status, 200);
      assert.equal(response.json.answer, fixture.answer);
      assert.deepEqual(response.json.sources, fixture.sources);
      assert.equal(response.json.kg.status, 'unavailable');
      assert.deepEqual(response.json.kg.names, []);
      assert.ok(s.sink.lines.some((line) => /Neo4j/.test(line)));
      assertNoSecret(s, response);
    });
  }

  test('沒有帳密：kg unavailable，不打 Neo4j', async () => {
    const s = await stack({ fixture, password: null });

    const response = await s.ask(fixture.question);

    assert.equal(response.status, 200);
    assert.equal(response.json.kg.status, 'unavailable');
    assert.equal(s.neo4j.requests.length, 0);
  });
});

describe('POST /api/ask：輸入驗證', () => {
  const invalid = {
    不是_JSON: '{not json',
    陣列: '[]',
    null: 'null',
    缺_question: '{}',
    question_是數字: '{"question":123}',
    空字串: '{"question":""}',
    只有空白: '{"question":" \\n\\t "}',
    超過_500_字: JSON.stringify({ question: '字'.repeat(501) }),
  };
  for (const [name, body] of Object.entries(invalid)) {
    test(`400：${name}`, async () => {
      const s = await stack();

      const response = await s.request({ method: 'POST', path: '/api/ask', body });

      assert.equal(response.status, 400);
      assert.equal(typeof response.json.error, 'string');
      assert.equal(s.backend.requests.length, 0);
    });
  }

  test('500 字剛好可以，以字元數算（與 backend 的 pydantic 一致）', async () => {
    const s = await stack();

    assert.equal((await s.ask('字'.repeat(500))).status, 200);
    assert.equal((await s.ask('😀'.repeat(500))).status, 200);
    assert.equal((await s.ask('😀'.repeat(501))).status, 400);
  });

  test('超過 8 KB 回 413（有 content-length）', async () => {
    const s = await stack();

    const response = await s.request({
      method: 'POST',
      path: '/api/ask',
      headers: { 'content-length': String(8 * 1024 + 1) },
      body: 'x'.repeat(8 * 1024 + 1),
    });

    assert.equal(response.status, 413);
    assert.equal(s.backend.requests.length, 0);
  });

  test('超過 8 KB 回 413（chunked，沒有 content-length）', async () => {
    const s = await stack();

    const response = await s.request({
      method: 'POST',
      path: '/api/ask',
      chunks: ['x'.repeat(5 * 1024), 'x'.repeat(5 * 1024)],
    });

    assert.equal(response.status, 413);
    assert.equal(response.headers.connection, 'close');
    assert.equal(s.backend.requests.length, 0);
  });

  test('宣告超過 8 KB 就立刻回 413，不等 body 傳完', { timeout: 5000 }, async () => {
    const s = await stack();

    const response = await s.request({
      method: 'POST',
      path: '/api/ask',
      headers: { 'content-length': '1000000' },
      body: 'x',
    });

    assert.equal(response.status, 413);
  });

  test('8 KB 剛好不擋大小', async () => {
    const s = await stack();
    const padded = `{"question":"耶穌","pad":"${'x'.repeat(8 * 1024 - 32)}"}`;

    const response = await s.request({ method: 'POST', path: '/api/ask', body: padded });

    assert.ok(Buffer.byteLength(padded) <= 8 * 1024);
    assert.equal(response.status, 200);
  });

  test('GET 回 405 並帶 Allow', async () => {
    const s = await stack();

    const response = await s.request({ path: '/api/ask' });

    assert.equal(response.status, 405);
    assert.equal(response.headers.allow, 'POST');
  });

  test('其他網站發的請求回 403，不佔 GPU；同站可以', async () => {
    const s = await stack();
    const sameOrigin = new URL(s.url).origin;

    assert.equal((await s.ask('問題', { origin: 'https://evil.example' })).status, 403);
    assert.equal((await s.ask('問題', { origin: 'null' })).status, 403);
    assert.equal(s.backend.requests.length, 0);
    assert.equal((await s.ask('問題', { origin: sameOrigin })).status, 200);
  });
});

describe('POST /api/ask：併發與限流', () => {
  test('同時進行上限 2，第三個回 429；結束後空出名額', async () => {
    const fixture = loadFixture('direct');
    const release = [];
    const reply = backendFromFixture(fixture);
    const s = await stack({
      fixture,
      backend: (entry, res) => release.push(() => reply(entry, res)),
    });
    const first = s.ask('一');
    const second = s.ask('二');
    await waitUntil(() => release.length === 2, '兩題都進到 backend');

    const third = await s.ask('三');

    assert.equal(third.status, 429);
    assert.equal(third.headers['retry-after'], '15');
    assert.equal(typeof third.json.error, 'string');
    assert.equal(s.backend.requests.length, 2);

    release.splice(0).forEach((go) => go());
    assert.equal((await first).status, 200);
    assert.equal((await second).status, 200);

    const fourth = s.ask('四');
    await waitUntil(() => release.length === 1, '第四題進到 backend');
    release.splice(0).forEach((go) => go());
    assert.equal((await fourth).status, 200);
  });

  test('backend 失敗也會還名額', async () => {
    const s = await stack({
      backend: (_e, res) => sendJson(res, 500, { detail: 'boom' }),
      limits: { maxConcurrentAsks: 1 },
    });

    assert.equal((await s.ask('一')).status, 502);
    assert.equal((await s.ask('二')).status, 502);
  });

  test('每 IP 每分鐘上限；視窗過了就恢復', async () => {
    let clock = 1_000_000;
    const s = await stack({ limits: { asksPerMinute: 3 }, now: () => clock });

    for (const question of ['一', '二', '三']) {
      assert.equal((await s.ask(question)).status, 200);
    }
    const blocked = await s.ask('四');

    assert.equal(blocked.status, 429);
    assert.equal(blocked.headers['retry-after'], '60');
    assert.equal(s.backend.requests.filter((r) => r.url === '/api/v1/query').length, 3);

    clock += 60_001;
    assert.equal((await s.ask('五')).status, 200);
  });

  test('預設就是 2 併發、每分鐘 20 次、8 KB、120 秒、Neo4j 2 秒', async () => {
    const { LIMITS } = await import('../lib/config.mjs');

    assert.equal(LIMITS.maxConcurrentAsks, 2);
    assert.equal(LIMITS.asksPerMinute, 20);
    assert.equal(LIMITS.bodyMaxBytes, 8192);
    assert.equal(LIMITS.askTimeoutMs, 120_000);
    assert.equal(LIMITS.neo4jTimeoutMs, 2000);
  });
});

describe('POST /api/ask：backend 失敗', () => {
  const LEAK = 'Traceback secret_internal_path /app/backend/routers/query.py';

  function assertFriendly(response, status) {
    assert.equal(response.status, status);
    assert.deepEqual(Object.keys(response.json), ['error']);
    assert.equal(response.text.includes('Traceback'), false);
    assert.equal(response.text.includes('127.0.0.1'), false);
    assert.equal(response.text.includes('backend'), false);
  }

  test('500 → 502，細節只進 log', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 500, { detail: LEAK }) });

    const response = await s.ask('問題');

    assertFriendly(response, 502);
    assert.ok(s.sink.lines.some((line) => line.includes('Traceback')));
  });

  test('422 也算非 2xx → 502', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 422, { detail: LEAK }) });

    assertFriendly(await s.ask('問題'), 502);
  });

  test('逾時 → 504', { timeout: 5000 }, async () => {
    const s = await stack({ backend: () => {}, limits: { askTimeoutMs: 50 } });

    assertFriendly(await s.ask('問題'), 504);
    assert.ok(s.sink.lines.some((line) => line.includes('TimeoutError')));
  });

  test('連不上 → 502', async () => {
    const s = await stack({ backendUrl: 'http://127.0.0.1:9' });

    assertFriendly(await s.ask('問題'), 502);
  });

  test('2xx 但不是 JSON → 502', async () => {
    const s = await stack({ backend: (_e, res) => res.end('<html>') });

    assertFriendly(await s.ask('問題'), 502);
  });

  test('2xx 但沒有 answer → 502', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 200, { sources: [] }) });

    assertFriendly(await s.ask('問題'), 502);
  });

  test('log 也不含密碼', async () => {
    const s = await stack({
      backend: (_e, res) => sendJson(res, 500, { detail: `neo4j auth ${TEST_PASSWORD} ${TEST_BASIC}` }),
    });

    const response = await s.ask('問題');

    assertFriendly(response, 502);
    assertNoSecret(s, response);
    assert.ok(s.sink.lines.some((line) => line.includes('***')));
  });
});

test('假 Neo4j 本身拒絕閉集外的語句（它若來者不拒，上面的斷言就沒有意義）', async () => {
  const s = await stack();

  const response = await rawRequest(s.neo4j.url, {
    method: 'POST',
    path: '/',
    body: JSON.stringify({ statement: 'MATCH (n) RETURN n', parameters: {}, accessMode: 'READ' }),
  });

  assert.equal(response.status, 400);
});
