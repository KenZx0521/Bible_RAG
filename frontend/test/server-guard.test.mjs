// server 的防線：連線數上限、實際逾時、Host 白名單（DNS rebinding）、log 脫敏遇到需跳脫的密碼。
import { afterEach, describe, test } from 'node:test';
import assert from 'node:assert/strict';
import net from 'node:net';

import { LIMITS, LOG_LINE_CHARS, createLogger, loadConfig } from '../lib/config.mjs';
import { isAllowedHost } from '../lib/limits.mjs';
import { captureSink, loadFixture, sendJson, startStack, toBackendBody, waitUntil } from './helpers/stack.mjs';

const stacks = [];
const sockets = [];

async function stack(options) {
  const started = await startStack(options);
  stacks.push(started);
  return started;
}

afterEach(async () => {
  sockets.splice(0).forEach((socket) => socket.destroy());
  await Promise.all(stacks.splice(0).map((s) => s.close()));
});

/** 真的 TCP 連線；記下收到什麼、何時被關。 */
function connect(url, { localAddress, send } = {}) {
  const { hostname, port } = new URL(url);
  return new Promise((resolve, reject) => {
    const socket = net.connect({ host: hostname, port: Number(port), localAddress }, () => {
      if (send) socket.write(send);
      resolve(socket);
    });
    socket.received = '';
    socket.isClosed = false;
    socket.on('data', (chunk) => { socket.received += chunk; });
    socket.on('close', () => { socket.isClosed = true; });
    socket.on('error', () => {});
    socket.once('error', reject);
    sockets.push(socket);
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const halfHeader = (url) => `GET / HTTP/1.1\r\nHost: ${new URL(url).host}\r\nX-Slow: `;

describe('連線數上限', () => {
  test('同一個 IP 超過上限：多的連線直接關掉，已有的連線與其他 IP 不受影響', async () => {
    const s = await stack({ limits: { maxConnectionsPerIp: 3 } });
    const held = await Promise.all([1, 2, 3].map(() => connect(s.url, { localAddress: '127.0.0.2', send: halfHeader(s.url) })));
    await sleep(30);
    const extra = await connect(s.url, { localAddress: '127.0.0.2' });
    await waitUntil(() => extra.isClosed, '第 4 條要被關掉');
    assert.equal(held.some((socket) => socket.isClosed), false, '前 3 條還在');
    assert.equal((await s.request({ path: '/', localAddress: '127.0.0.3' })).status, 200, '別的 IP 照常');
  });

  test('連線關掉之後名額就還回來', async () => {
    const s = await stack({ limits: { maxConnectionsPerIp: 2 } });
    const held = await Promise.all([1, 2].map(() => connect(s.url, { localAddress: '127.0.0.2', send: halfHeader(s.url) })));
    await sleep(30);
    held[0].destroy();
    await waitUntil(() => held[0].isClosed, '關掉');
    await sleep(30);
    assert.equal((await s.request({ path: '/', localAddress: '127.0.0.2' })).status, 200);
  });

  test('整個 server 的總數上限', async () => {
    const s = await stack({ limits: { maxConnections: 2, maxConnectionsPerIp: 100 } });
    await connect(s.url, { localAddress: '127.0.0.2', send: halfHeader(s.url) });
    await connect(s.url, { localAddress: '127.0.0.3', send: halfHeader(s.url) });
    await sleep(30);
    const extra = await connect(s.url, { localAddress: '127.0.0.4' });
    await waitUntil(() => extra.isClosed, '超過總數要被關掉');
  });

  test('拒絕連線只記一行 log：被打的時候不能連 log 都灌爆，也不寫對方送的東西', async () => {
    const s = await stack({ limits: { maxConnectionsPerIp: 1 } });
    await connect(s.url, { localAddress: '127.0.0.2', send: halfHeader(s.url) });
    await sleep(30);
    for (let i = 0; i < 5; i += 1) {
      const extra = await connect(s.url, { localAddress: '127.0.0.2' });
      await waitUntil(() => extra.isClosed, '被關掉');
    }
    const warned = s.sink.lines.filter((line) => line.includes('連線數已達上限'));
    assert.equal(warned.length, 1, warned.join('\n'));
  });

  test('過了一分鐘還在發生才再記一行', async () => {
    let clock = 0;
    const s = await stack({ limits: { maxConnectionsPerIp: 1 }, now: () => clock });
    await connect(s.url, { localAddress: '127.0.0.2', send: halfHeader(s.url) });
    await sleep(30);
    const refuse = async () => {
      const extra = await connect(s.url, { localAddress: '127.0.0.2' });
      await waitUntil(() => extra.isClosed, '被關掉');
    };
    await refuse();
    clock = 59_000;
    await refuse();
    assert.equal(s.sink.lines.filter((line) => line.includes('連線數已達上限')).length, 1);
    clock = 61_000;
    await refuse();
    assert.equal(s.sink.lines.filter((line) => line.includes('連線數已達上限')).length, 2);
  });

  test('預設值：真的有上限，而且一般瀏覽器不會撞到', () => {
    assert.ok(LIMITS.maxConnectionsPerIp >= 16 && LIMITS.maxConnectionsPerIp <= 128);
    assert.ok(LIMITS.maxConnections >= LIMITS.maxConnectionsPerIp && LIMITS.maxConnections <= 4096);
  });
});

describe('慢連線的實際逾時', () => {
  const FAST = { headersTimeoutMs: 100, requestTimeoutMs: 200, connectionCheckMs: 20 };
  const REPLY_WITHIN_MS = 1500;

  test('標頭沒送完：照常數逾時，不再多等一個檢查週期', async () => {
    const s = await stack({ limits: FAST });
    const startedAt = Date.now();
    const socket = await connect(s.url, { send: halfHeader(s.url) });
    await waitUntil(() => socket.received.includes('408') || socket.isClosed, '收到 408', REPLY_WITHIN_MS);
    assert.match(socket.received, /^HTTP\/1\.1 408/);
    assert.ok(Date.now() - startedAt >= FAST.headersTimeoutMs - 10);
  });

  test('body 沒送完：照常數逾時', async () => {
    const s = await stack({ limits: FAST });
    const head = `POST /api/ask HTTP/1.1\r\nHost: ${new URL(s.url).host}\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n{"q`;
    const socket = await connect(s.url, { send: head });
    await waitUntil(() => socket.received.includes('408') || socket.isClosed, '收到 408', REPLY_WITHIN_MS);
    assert.match(socket.received, /^HTTP\/1\.1 408/);
  });

  test('連線後一個位元組都不送：閒置逾時就關掉（它不算請求，上面兩個逾時管不到）', async () => {
    const s = await stack({ limits: { idleSocketMs: 100 } });
    const socket = await connect(s.url);
    await waitUntil(() => socket.isClosed, '閒置連線被關掉', REPLY_WITHIN_MS);
  });

  test('等 backend 不算慢連線：請求送完後 backend 慢也不會被 408', async () => {
    const fixture = loadFixture('walk_plain');
    const s = await stack({
      fixture,
      limits: FAST,
      backend: (entry, res) => {
        if (entry.url === '/api/v1/query') setTimeout(() => sendJson(res, 200, toBackendBody(fixture)), 400);
        else sendJson(res, 200, { status: 'ok', build_id: fixture.build_id });
      },
    });
    assert.equal((await s.ask(fixture.question)).status, 200);
  });

  test('預設值：閒置逾時比「排隊＋等 backend」還長，等答案時連線不會被砍；標頭逾時不超過請求逾時', () => {
    assert.ok(LIMITS.idleSocketMs > LIMITS.askTimeoutMs + LIMITS.askQueueWaitMs);
    assert.ok(LIMITS.headersTimeoutMs <= LIMITS.requestTimeoutMs);
    assert.ok(LIMITS.connectionCheckMs <= 5_000, '常數才代表實際逾時');
  });
});

describe('Host 白名單', () => {
  test('isAllowedHost：本機名、IP 字面值、白名單放行；其他網域不行', () => {
    const allowed = ['demo.example'];
    for (const host of ['localhost', 'localhost:5173', 'LOCALHOST:5173', '127.0.0.1:5173', '192.168.1.20', '[::1]:5173', '[::1]', 'demo.example:8080', 'DEMO.example']) {
      assert.equal(isAllowedHost(host, allowed), true, host);
    }
    for (const host of ['evil.test', 'evil.test:5173', 'localhost.evil.test', '127.0.0.1.evil.test', 'demo.example.evil.test', '', undefined, 'bad host', 'a b:1']) {
      assert.equal(isAllowedHost(host, allowed), false, String(host));
    }
    assert.equal(isAllowedHost('demo.example'), false, '沒給白名單也能呼叫');
  });

  test('DNS rebinding：Origin 與 Host 都是攻擊者網域也要擋，不打 backend', async () => {
    const s = await stack();
    const response = await s.ask('問題', { host: 'evil.test:5173', origin: 'http://evil.test:5173' });
    assert.equal(response.status, 403);
    assert.deepEqual(Object.keys(response.json), ['error']);
    assert.equal(s.backend.requests.length, 0);
  });

  test('靜態頁、health、verse 也一樣；403 仍帶安全標頭', async () => {
    const s = await stack();
    for (const path of ['/', '/api/health', '/api/verse/jhn/3/16']) {
      const response = await s.request({ path, headers: { host: 'evil.test' } });
      assert.equal(response.status, 403, path);
      assert.match(response.headers['content-security-policy'], /default-src 'self'/);
    }
    assert.equal(s.backend.requests.length, 0);
  });

  test('正常用法不受影響：127.0.0.1、localhost、白名單', async () => {
    const s = await stack();
    const { port } = new URL(s.url);
    assert.equal((await s.request({ path: '/' })).status, 200);
    assert.equal((await s.request({ path: '/', headers: { host: `localhost:${port}` } })).status, 200);
    assert.equal((await s.request({ path: '/', headers: { host: `192.168.1.20:${port}` } })).status, 200, '區網用 IP 不必設定');
    const allowed = await stack({ allowedHosts: ['demo.example'] });
    assert.equal((await allowed.request({ path: '/', headers: { host: 'demo.example' } })).status, 200);
  });

  test('同網站檢查還在：Host 正常但 Origin 是別的網站', async () => {
    const s = await stack();
    const response = await s.ask('問題', { origin: 'http://evil.test' });
    assert.equal(response.status, 403);
  });

  test('loadConfig：DEMO_ALLOWED_HOSTS 逗號分隔，DEMO_HOST 自動算進去；綁全部介面時不把 0.0.0.0 當網域', () => {
    const env = { NEO4J_USER: 'u', NEO4J_PASSWORD: 'p' };
    const named = loadConfig({ env: { ...env, DEMO_HOST: 'demo.local', DEMO_ALLOWED_HOSTS: ' A.example , b.example,, ' }, envFile: '/nonexistent' });
    assert.deepEqual(named.allowedHosts, ['demo.local', 'a.example', 'b.example']);
    assert.ok(Object.isFrozen(named.allowedHosts));
    assert.deepEqual(loadConfig({ env, envFile: '/nonexistent' }).allowedHosts, ['127.0.0.1']);
    assert.deepEqual(loadConfig({ env: { ...env, DEMO_HOST: '0.0.0.0' }, envFile: '/nonexistent' }).allowedHosts, ['0.0.0.0']);
  });
});

describe('log 脫敏：密碼含需跳脫的字元', () => {
  for (const [label, secret] of [
    ['引號與反斜線', 'pa"ss\\w0rd'],
    ['換行', 'line1\nline2'],
    ['tab', 'tab\there'],
    ['中文', '中文密碼'],
    ['控制字元', 'ctl\u0001x'],
  ]) {
    test(`${label}：context 與訊息都遮掉`, () => {
      const sink = captureSink();
      createLogger([secret], sink).error(`訊息 ${secret} 尾`, { body: `detail ${secret} end` });
      assert.equal(sink.lines.length, 1);
      assert.equal(sink.lines[0], '訊息 *** 尾 {"body":"detail *** end"}');
    });
  }

  test('backend 回應裡的密碼跨在第 500 字上：不留前半段', async () => {
    const secret = 'StraddlePw12345';
    const s = await stack({
      secrets: [secret],
      backend: (_e, res) => {
        res.writeHead(500, { 'content-type': 'text/plain' });
        res.end(`${'x'.repeat(495)}${secret} tail`);
      },
    });

    await s.ask('問題');

    const line = s.sink.lines.find((entry) => entry.includes('backend 回應異常'));
    assert.ok(line, '要有這筆 log');
    assert.equal(line.includes(secret.slice(0, 5)), false, line);
  });

  test('一行再長也有上限，而且先遮再切：密碼跨在任何切點上都不留前半段', () => {
    const secret = 'StraddlePw12345';
    const overhead = 'm {"body":"'.length;
    for (let shift = 0; shift <= secret.length; shift += 1) {
      const sink = captureSink();
      const padding = 'x'.repeat(LOG_LINE_CHARS - overhead - shift);
      createLogger([secret], sink).error('m', { body: `${padding}${secret} tail` });
      assert.ok(sink.lines[0].length <= LOG_LINE_CHARS, `長度 ${sink.lines[0].length}`);
      assert.equal(/Str|ddlePw|12345/.test(sink.lines[0]), false, `shift ${shift}`);
    }
  });

  test('已經跳脫過一次的形式（backend 回 JSON 字串帶出密碼）也遮掉', () => {
    const secret = 'Fake"Pw\\zz';
    const sink = captureSink();
    const body = JSON.stringify({ detail: `bolt://u:${secret}@neo4j:7687` });
    createLogger([secret], sink).error('backend 回應異常', { body });
    assert.equal(sink.lines[0].includes('Fake'), false, sink.lines[0]);
  });

  test('網址編碼過的形式也遮掉', () => {
    const secret = 'pa ss/w0rd"';
    const sink = captureSink();
    createLogger([secret], sink).error(`連線 bolt://u:${encodeURIComponent(secret)}@neo4j`);
    assert.equal(sink.lines[0], '連線 bolt://u:***@neo4j');
  });

  test('一般密碼不受影響；一個秘密是另一個的子字串時先換長的', () => {
    const sink = captureSink();
    createLogger(['plainpw123', 'plainpw'], sink).error('a plainpw123 b plainpw c', { x: 'plainpw123' });
    assert.equal(sink.lines[0], 'a *** b *** c {"x":"***"}');
  });

  test('空字串不算秘密；context 是字串本身也遮', () => {
    const sink = captureSink();
    createLogger(['', 'q"x'], sink).warn('t', 'a q"x b');
    assert.equal(sink.lines[0].includes('q'), false, sink.lines[0]);
  });

  test('完整鏈：真 server 收到帶密碼的 backend 錯誤，log 看不到，瀏覽器也看不到', async () => {
    const secret = 'Fake"Pw\\zz';
    const s = await stack({
      secrets: [secret],
      backend: (entry, res) => {
        res.writeHead(500, { 'content-type': 'text/plain' });
        res.end(`Traceback bolt://u:${secret}@neo4j:7687 plain-marker`);
      },
    });
    const response = await s.ask('問題');
    assert.equal(response.status, 502);
    assert.equal(response.text.includes('Fake'), false);
    const logged = s.sink.lines.join('\n');
    assert.match(logged, /plain-marker/, '確實有記到這一筆');
    assert.equal(logged.includes('Fake'), false, logged);
    assert.equal(logged.includes('zz'), false, logged);
  });
});
