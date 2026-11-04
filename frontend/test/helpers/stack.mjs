// 測試共用：假 backend、假 Neo4j（node:http 開在 port 0）與 demo server 組裝。
import http from 'node:http';
import net from 'node:net';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { LIMITS, createLogger } from '../../lib/config.mjs';
import { TEMPLATES } from '../../lib/neo4j.mjs';
import { createDemoServer } from '../../server.mjs';

export const TEST_USER = 'neo4j-test-user';
export const TEST_PASSWORD = 'S3cret-Neo4j-Pw!';
export const TEST_BASIC = Buffer.from(`${TEST_USER}:${TEST_PASSWORD}`).toString('base64');

export function loadFixture(name) {
  return JSON.parse(readFileSync(new URL(`../fixtures/${name}.json`, import.meta.url), 'utf8'));
}

/** 把 fixture（AskResponse）還原成 backend /api/v1/query 的回應形狀。 */
export function toBackendBody(fixture) {
  const { answer, intent, sources, aux_card, graph_trace, route } = fixture;
  return {
    answer,
    intent,
    sources,
    aux_card,
    graph_trace,
    retrieval_stats: { route_used: route, fusion_alpha: 0.2, strategies_used: ['hybrid_hybrid'] },
  };
}

/** 注入給 enrich 的查詢函式：資料來自 fixture，並記下每次呼叫。 */
export function kgFromFixture(fixture) {
  const calls = [];
  const recorded = (name, rows) => async (...args) => {
    calls.push([name, ...args]);
    return rows(...args);
  };
  const pick = (row, keys) => Object.fromEntries(keys.map((key) => [key, row[key]]));
  const PASSAGE_KEYS = ['id', 'title', 'book_id', 'chapter', 'start_key', 'end_key'];
  return {
    calls,
    names: recorded('names', (_b, ids) =>
      fixture.kg.names.filter((n) => ids.includes(n.id)).map((n) => pick(n, ['id', 'label', 'df', 'idf']))),
    passages: recorded('passages', (_b, ids) =>
      fixture.kg.passages.filter((p) => ids.includes(p.id)).map((p) => pick(p, PASSAGE_KEYS))),
    mentions: recorded('mentions', (_b, ps, ns) =>
      fixture.kg.mentions.filter(([p, n]) => ps.includes(p) && ns.includes(n))),
    events: recorded('events', (_b, ids) =>
      fixture.kg.events.filter((e) => ids.includes(e.id)).map((e) => pick(e, ['id', 'name']))),
  };
}

export function silentLog() {
  const lines = [];
  const push = (message, context) => lines.push(`${message} ${JSON.stringify(context ?? '')}`);
  return { lines, info: push, warn: push, error: push };
}

export function captureSink() {
  const lines = [];
  const push = (line) => lines.push(line);
  return { lines, info: push, warn: push, error: push };
}

/** 等條件成立；逾時直接失敗，不讓測試永遠卡住。 */
export async function waitUntil(condition, label, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() > deadline) throw new Error(`等不到：${label}`);
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

export function sendJson(res, status, body) {
  res.writeHead(status, { 'content-type': 'application/json' });
  res.end(JSON.stringify(body));
}

function closeServer(server) {
  return new Promise((resolve) => {
    server.close(() => resolve());
    server.closeAllConnections();
  });
}

function listen(server) {
  return new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
}

/** 記下所有請求的假 HTTP 服務；handler(entry, res, nth)。 */
export async function fakeServer(handler) {
  const requests = [];
  const server = http.createServer((req, res) => {
    const chunks = [];
    req.on('data', (chunk) => chunks.push(chunk));
    req.on('end', () => {
      const entry = {
        method: req.method,
        url: req.url,
        headers: req.headers,
        text: Buffer.concat(chunks).toString('utf8'),
      };
      requests.push(entry);
      handler(entry, res, requests.length);
    });
  });
  await listen(server);
  return {
    url: `http://127.0.0.1:${server.address().port}`,
    requests,
    close: () => closeServer(server),
  };
}

/** 假 Neo4j：只認閉集模板，資料來自 fixture。 */
export function neo4jFromFixture(fixture) {
  const rows = {
    [TEMPLATES.names]: ({ ids }) =>
      fixture.kg.names.filter((n) => ids.includes(n.id)).map((n) => [n.id, n.label, n.df, n.idf]),
    [TEMPLATES.passages]: ({ ids }) =>
      fixture.kg.passages
        .filter((p) => ids.includes(p.id))
        .map((p) => [p.id, p.title, p.book_id, p.chapter, p.start_key, p.end_key]),
    [TEMPLATES.mentions]: ({ ps, ns }) =>
      fixture.kg.mentions.filter(([p, n]) => ps.includes(p) && ns.includes(n)),
    [TEMPLATES.events]: ({ ids }) =>
      fixture.kg.events.filter((e) => ids.includes(e.id)).map((e) => [e.id, e.name]),
    [TEMPLATES.ping]: () => [[1]],
  };
  return (entry, res) => {
    const { statement, parameters } = JSON.parse(entry.text);
    const query = rows[statement];
    if (!query) return sendJson(res, 400, { errors: [{ code: 'Test.UnknownStatement', message: statement }] });
    return sendJson(res, 202, { data: { fields: [], values: query(parameters) }, bookmarks: [] });
  };
}

/** 預設 backend：/api/v1/query 回 fixture，/api/v1/health 回 ready。 */
export function backendFromFixture(fixture) {
  return (entry, res) => {
    if (entry.url === '/api/v1/query') return sendJson(res, 200, toBackendBody(fixture));
    if (entry.url === '/api/v1/health') {
      return sendJson(res, 200, { status: 'ok', build_id: fixture.build_id, graph: { state: 'ready' } });
    }
    return sendJson(res, 404, { detail: 'not found' });
  };
}

function makePublicDir() {
  const root = mkdtempSync(join(tmpdir(), 'bible-demo-'));
  const publicDir = join(root, 'public');
  mkdirSync(join(publicDir, 'js'), { recursive: true });
  writeFileSync(join(publicDir, 'index.html'), '<!doctype html><title>demo</title>');
  writeFileSync(join(publicDir, 'js', 'app.js'), 'export const app = 1;\n');
  writeFileSync(join(publicDir, 'styles.css'), 'body{}\n');
  writeFileSync(join(publicDir, 'blob.bin'), 'bin');
  writeFileSync(join(publicDir, '.hidden'), 'TOP-SECRET-HIDDEN');
  writeFileSync(join(root, 'secret.txt'), 'TOP-SECRET-OUTSIDE');
  writeFileSync(join(root, '.env'), `NEO4J_PASSWORD=${TEST_PASSWORD}\n`);
  symlinkSync(join(root, 'secret.txt'), join(publicDir, 'link.txt'));
  return { root, publicDir };
}

/** 組一整套：假 backend、假 Neo4j、demo server；回傳 close() 一次收乾淨。 */
export async function startStack(options = {}) {
  const fixture = options.fixture ?? loadFixture('walk_plain');
  const backend = await fakeServer(options.backend ?? backendFromFixture(fixture));
  const neo4j = await fakeServer(options.neo4j ?? neo4jFromFixture(fixture));
  const { root, publicDir } = makePublicDir();
  const sink = captureSink();
  const hasPassword = options.password !== null;
  const config = {
    host: '127.0.0.1',
    port: 0,
    backendUrl: options.backendUrl ?? backend.url,
    neo4j: {
      url: neo4j.url,
      user: hasPassword ? TEST_USER : '',
      password: hasPassword ? TEST_PASSWORD : '',
      timeoutMs: options.neo4jTimeoutMs ?? LIMITS.neo4jTimeoutMs,
    },
    limits: { ...LIMITS, ...options.limits },
    allowedHosts: options.allowedHosts ?? [],
  };
  const log = createLogger([TEST_PASSWORD, TEST_BASIC, ...(options.secrets ?? [])], sink);
  const server = createDemoServer({
    config,
    log,
    publicDir,
    now: options.now,
  });
  await listen(server);
  const url = `http://127.0.0.1:${server.address().port}`;
  return {
    url,
    backend,
    neo4j,
    sink,
    root,
    publicDir,
    request: (spec) => rawRequest(url, spec),
    ask: (question, headers = {}, localAddress) => askJson(url, question, headers, localAddress),
    openAsk: (question, options) => openAskSocket(url, question, options),
    close: async () => {
      await Promise.all([closeServer(server), backend.close(), neo4j.close()]);
      rmSync(root, { recursive: true, force: true });
    },
  };
}

/** 用 http.request 送原始路徑：fetch 會先把 .. 正規化掉，測不到路徑穿越。 */
export function rawRequest(base, { method = 'GET', path = '/', headers = {}, body, chunks = [], localAddress } = {}) {
  const { hostname, port } = new URL(base);
  return new Promise((resolve, reject) => {
    const req = http.request({ hostname, port, method, path, headers, localAddress, agent: false }, (res) => {
      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => {
        const text = Buffer.concat(chunks).toString('utf8');
        resolve({ status: res.statusCode, headers: res.headers, text, json: parseOrNull(text) });
      });
    });
    req.on('error', reject);
    chunks.forEach((chunk) => req.write(chunk)); // 先 write 才是真的 chunked，沒有 content-length
    req.end(body);
  });
}

function parseOrNull(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function askJson(base, question, headers, localAddress) {
  return rawRequest(base, {
    method: 'POST',
    path: '/api/ask',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify({ question }),
    localAddress,
  });
}

/** 真的 TCP 連線送完整個 /api/ask 就停著；呼叫端決定之後要 destroy（關閉）還是 resetAndDestroy（RST）。 */
export function openAskSocket(base, question, { localAddress } = {}) {
  const { hostname, port } = new URL(base);
  const body = JSON.stringify({ question });
  const head = `POST /api/ask HTTP/1.1\r\nHost: ${hostname}:${port}\r\nContent-Type: application/json\r\n`
    + `Content-Length: ${Buffer.byteLength(body)}\r\n\r\n`;
  return new Promise((resolve) => {
    const socket = net.connect({ host: hostname, port: Number(port), localAddress }, () => {
      socket.write(`${head}${body}`, () => resolve(socket));
    });
    socket.on('error', () => {});
  });
}
