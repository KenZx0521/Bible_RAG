// Neo4j client：唯讀、閉集模板、一定帶 build_id、失敗分類不洩漏帳密。全程只打本機假 Neo4j。
import { after, afterEach, describe, test } from 'node:test';
import assert from 'node:assert/strict';

import { Neo4jError, TEMPLATES, createNeo4jClient } from '../lib/neo4j.mjs';
import { TEST_BASIC, TEST_PASSWORD, TEST_USER, fakeServer, sendJson } from './helpers/stack.mjs';

const BUILD = 'b20261103_615c1ceb';
const open = [];

async function clientWith(handler, overrides = {}) {
  const fake = await fakeServer(handler);
  open.push(fake);
  const client = createNeo4jClient({
    url: fake.url,
    user: TEST_USER,
    password: TEST_PASSWORD,
    timeoutMs: 2000,
    ...overrides,
  });
  return { fake, client };
}

const answer = (values) => (_entry, res) => sendJson(res, 202, { data: { fields: [], values } });
const rejectsKind = (promise, kind) =>
  assert.rejects(promise, (err) => {
    assert.ok(err instanceof Neo4jError);
    assert.equal(err.kind, kind);
    return true;
  });

afterEach(async () => {
  await Promise.all(open.splice(0).map((fake) => fake.close()));
});

describe('neo4j：請求', () => {
  test('body 只有 statement／parameters／accessMode READ，帶 Basic 認證', async () => {
    const { fake, client } = await clientWith(answer([['nm:a', '巴拿巴', 16, 5.15]]));

    const rows = await client.session().names(BUILD, ['nm:a']);

    assert.deepEqual(rows, [{ id: 'nm:a', label: '巴拿巴', df: 16, idf: 5.15 }]);
    const [request] = fake.requests;
    assert.deepEqual(JSON.parse(request.text), {
      statement: TEMPLATES.names,
      parameters: { b: BUILD, ids: ['nm:a'] },
      accessMode: 'READ',
    });
    assert.equal(request.headers.authorization, `Basic ${TEST_BASIC}`);
  });

  test('四個查詢都帶 build_id、都用閉集模板、都是 READ', async () => {
    const { fake, client } = await clientWith(answer([]));
    const session = client.session();

    await session.names(BUILD, ['nm:a']);
    await session.passages(BUILD, ['ps:a']);
    await session.mentions(BUILD, ['ps:a'], ['nm:a']);
    await session.events(BUILD, ['ev1']);

    const bodies = fake.requests.map((request) => JSON.parse(request.text));
    assert.equal(bodies.length, 4);
    for (const body of bodies) {
      assert.equal(body.parameters.b, BUILD);
      assert.equal(body.accessMode, 'READ');
      assert.ok(Object.values(TEMPLATES).includes(body.statement));
      assert.match(body.statement, /build_id:\$b/);
    }
    assert.deepEqual(bodies[2].parameters, { b: BUILD, ps: ['ps:a'], ns: ['nm:a'] });
  });

  test('模板與契約逐字相同：Passage、Name、Event 每一側都過濾 build_id', () => {
    assert.equal(
      TEMPLATES.names,
      'UNWIND $ids AS i MATCH (n:Name {build_id:$b,id:i}) RETURN n.id,n.label,n.df,n.idf ORDER BY n.id',
    );
    assert.equal(
      TEMPLATES.passages,
      'UNWIND $ids AS i MATCH (p:Passage {build_id:$b,id:i}) RETURN p.id,p.title,p.book_id,p.chapter,p.start_key,p.end_key ORDER BY p.id',
    );
    assert.equal(
      TEMPLATES.mentions,
      'UNWIND $ps AS i MATCH (p:Passage {build_id:$b,id:i})-[:MENTIONS]->(n:Name {build_id:$b}) WHERE n.id IN $ns RETURN p.id,n.id ORDER BY p.id,n.id',
    );
    assert.equal(TEMPLATES.events, 'UNWIND $ids AS i MATCH (e:Event {build_id:$b,id:i}) RETURN e.id,e.name');
  });

  test('模板表凍結，沒有任何寫入語句', () => {
    assert.ok(Object.isFrozen(TEMPLATES));
    for (const statement of Object.values(TEMPLATES)) {
      assert.doesNotMatch(statement, /\b(CREATE|MERGE|SET|DELETE|REMOVE|DROP|CALL|LOAD)\b/i);
    }
  });

  test('列對應成物件', async () => {
    const passageRow = ['ps:a', '標題', 'act', 13, 'act.13.1', 'act.13.3'];
    const { client } = await clientWith((entry, res) => {
      const { statement } = JSON.parse(entry.text);
      const values = {
        [TEMPLATES.passages]: [passageRow],
        [TEMPLATES.mentions]: [['ps:a', 'nm:a']],
        [TEMPLATES.events]: [['ev1', '第一次宣教旅程']],
      }[statement];
      sendJson(res, 202, { data: { values } });
    });
    const session = client.session();

    assert.deepEqual(await session.passages(BUILD, ['ps:a']), [
      { id: 'ps:a', title: '標題', book_id: 'act', chapter: 13, start_key: 'act.13.1', end_key: 'act.13.3' },
    ]);
    assert.deepEqual(await session.mentions(BUILD, ['ps:a'], ['nm:a']), [['ps:a', 'nm:a']]);
    assert.deepEqual(await session.events(BUILD, ['ev1']), [{ id: 'ev1', name: '第一次宣教旅程' }]);
  });

  test('空清單不打網路', async () => {
    const { fake, client } = await clientWith(answer([]));
    const session = client.session();

    assert.deepEqual(await session.names(BUILD, []), []);
    assert.deepEqual(await session.mentions(BUILD, ['ps:a'], []), []);
    assert.equal(fake.requests.length, 0);
  });

  test('沒有 build_id 拒絕查詢，絕不跨 build', async () => {
    const { fake, client } = await clientWith(answer([]));

    await rejectsKind(client.session().names(null, ['nm:a']), 'no_build_id');
    assert.equal(fake.requests.length, 0);
  });

  test('沒有帳密：configured=false，不打網路', async () => {
    const { fake, client } = await clientWith(answer([]), { password: '' });

    assert.equal(client.configured, false);
    await rejectsKind(client.session().names(BUILD, ['nm:a']), 'not_configured');
    await rejectsKind(client.ping(), 'not_configured');
    assert.equal(fake.requests.length, 0);
  });
});

describe('neo4j：失敗分類', () => {
  test('401 → unauthorized，錯誤不含回應內容與帳密', async () => {
    const { client } = await clientWith((entry, res) =>
      sendJson(res, 401, {
        errors: [{ code: 'Neo.ClientError.Security.Unauthorized', message: `bad ${TEST_PASSWORD} ${entry.headers.authorization}` }],
      }),
    );

    const failure = await client.session().names(BUILD, ['nm:a']).catch((err) => err);

    assert.equal(failure.kind, 'unauthorized');
    assert.equal(failure.status, 401);
    const printed = `${failure} ${failure.stack} ${JSON.stringify(failure)}`;
    assert.equal(printed.includes(TEST_PASSWORD), false);
    assert.equal(printed.includes(TEST_BASIC), false);
  });

  test('逾時 → timeout；同一個 session 共用同一個時限', { timeout: 5000 }, async () => {
    const { client } = await clientWith(() => {}, { timeoutMs: 60 });
    const session = client.session();
    const startedAt = Date.now();

    const results = await Promise.allSettled([
      session.names(BUILD, ['nm:a']),
      session.passages(BUILD, ['ps:a']),
    ]);

    assert.ok(results.every((r) => r.status === 'rejected' && r.reason.kind === 'timeout'));
    assert.ok(Date.now() - startedAt < 1000);
  });

  test('連不上 → network', async () => {
    const client = createNeo4jClient({
      url: 'http://127.0.0.1:9/db/neo4j/query/v2',
      user: TEST_USER,
      password: TEST_PASSWORD,
      timeoutMs: 1000,
    });

    await rejectsKind(client.session().names(BUILD, ['nm:a']), 'network');
  });

  test('語法錯誤 400 → query，只留 code', async () => {
    const { client } = await clientWith((_e, res) =>
      sendJson(res, 400, { errors: [{ code: 'Neo.ClientError.Statement.SyntaxError', message: 'detail' }] }),
    );

    const failure = await client.session().names(BUILD, ['nm:a']).catch((err) => err);

    assert.equal(failure.kind, 'query');
    assert.equal(failure.code, 'Neo.ClientError.Statement.SyntaxError');
    assert.equal(failure.message.includes('detail'), false);
  });

  test('2xx 但帶 errors → query', async () => {
    const { client } = await clientWith((_e, res) =>
      sendJson(res, 202, { errors: [{ code: 'Neo.X', message: 'no' }], data: { values: [] } }),
    );

    await rejectsKind(client.session().names(BUILD, ['nm:a']), 'query');
  });

  test('回應不是預期形狀 → malformed', async () => {
    const { client } = await clientWith((_e, res) => {
      res.writeHead(200);
      res.end('<html>not json</html>');
    });

    await rejectsKind(client.session().names(BUILD, ['nm:a']), 'malformed');
  });
});

describe('neo4j：ping', () => {
  test('成功 resolve，且也是 READ', async () => {
    const { fake, client } = await clientWith(answer([[1]]));

    await client.ping();

    const body = JSON.parse(fake.requests[0].text);
    assert.equal(body.statement, TEMPLATES.ping);
    assert.equal(body.accessMode, 'READ');
  });

  test('401 拒絕', async () => {
    const { client } = await clientWith((_e, res) => sendJson(res, 401, { errors: [] }));

    await rejectsKind(client.ping(), 'unauthorized');
  });
});

after(() => assert.equal(open.length, 0));
