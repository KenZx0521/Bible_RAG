// 入口：HTTP、靜態檔、路由。零依賴（node:http、內建 fetch）。
// 這層存在的原因：graph_walk 沒有回邊、段落沒標題，而 Neo4j 密碼不能進瀏覽器。
import http from 'node:http';
import { realpathSync } from 'node:fs';
import { readFile, realpath, stat } from 'node:fs/promises';
import { dirname, extname, join, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

import { SECURITY_HEADERS, createLogger, loadConfig } from './lib/config.mjs';
import { enrich } from './lib/enrich.mjs';
import { createAskGate, createRateLimiter, guardConnections, isAllowedHost, watchClient } from './lib/limits.mjs';
import { createNeo4jClient } from './lib/neo4j.mjs';
import { isBookId } from './public/js/books.js';

const PUBLIC_DIR = join(dirname(fileURLToPath(import.meta.url)), 'public');
const BUSY_RETRY_SECONDS = '15';
const BOOK_ID_RE = /^[1-9a-z]{3}$/;
const VERSE_NUMBER_RE = /^[1-9]\d{0,2}$/; // 詩篇最多 150 篇、176 節；三位數已足夠
const NOT_FOUND_CODES = new Set(['ENOENT', 'ENOTDIR', 'ENAMETOOLONG', 'ELOOP']);

const CONTENT_TYPES = Object.freeze({
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
});

const MESSAGES = Object.freeze({
  method: '不支援這個請求方法。',
  crossOrigin: '不接受來自其他網站的請求。',
  unknownHost: '不接受這個網址的請求。',
  badRequest: '請求格式不正確。',
  emptyQuestion: '請輸入問題。',
  longQuestion: '問題太長了，請縮短到 500 字以內。',
  tooLarge: '請求內容太大。',
  busy: '目前正在回答其他問題，請稍候再試。',
  rate: '提問太頻繁了，請稍候一分鐘再試。',
  backend: '暫時無法取得答案，請稍後再試。',
  timeout: '等候逾時，請稍後再試。',
  badVerse: '經文出處格式不正確。',
  noVerse: '找不到這節經文',
  notFound: '找不到這個頁面。',
  forbidden: '不允許讀取這個路徑。',
  internal: '伺服器發生問題，請稍後再試。',
});

class HttpFailure extends Error {
  constructor(status, message, headers = {}) {
    super(message);
    this.status = status;
    this.headers = headers;
  }
}

function sendJson(res, status, body, headers = {}) {
  res.writeHead(status, { 'Content-Type': CONTENT_TYPES['.json'], 'Cache-Control': 'no-store', ...headers });
  res.end(JSON.stringify(body));
}

const requireMethod = (req, allowed) => {
  if (!allowed.includes(req.method)) {
    throw new HttpFailure(405, MESSAGES.method, { Allow: allowed.join(', ') });
  }
};

function enforceRate(limiter, ip, message) {
  const waitSeconds = limiter(ip);
  if (waitSeconds > 0) throw new HttpFailure(429, message, { 'Retry-After': String(waitSeconds) });
}

function readBody(req, limit) {
  const tooLarge = () => new HttpFailure(413, MESSAGES.tooLarge, { Connection: 'close' });
  return new Promise((resolve, reject) => {
    if (Number(req.headers['content-length']) > limit) {
      req.resume();
      reject(tooLarge());
      return;
    }
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > limit) reject(tooLarge());
      else chunks.push(chunk);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', () => reject(new HttpFailure(400, MESSAGES.badRequest)));
  });
}

function parseQuestion(text, maxChars) {
  const body = parseJsonObject(text);
  if (typeof body?.question !== 'string') throw new HttpFailure(400, MESSAGES.badRequest);
  const question = body.question.trim();
  if (question === '') throw new HttpFailure(400, MESSAGES.emptyQuestion);
  // 以字元（code point）計，與 backend pydantic 的 max_length 一致；.length 會把 emoji 算兩個
  if ([...question].length > maxChars) throw new HttpFailure(400, MESSAGES.longQuestion);
  return question;
}

/** 擋掉別的網站從瀏覽器打本機 demo 佔 GPU；同站請求的 Origin 與 Host 相同。 */
function requireSameOrigin(req) {
  const { origin, host } = req.headers;
  if (origin !== undefined && hostOf(origin) !== host) throw new HttpFailure(403, MESSAGES.crossOrigin);
}

function hostOf(origin) {
  try {
    return new URL(origin).host;
  } catch {
    return null;
  }
}

/** 打 backend；連線失敗與逾時在這裡轉成友善錯誤，細節只進 log。 */
async function callBackend(ctx, path, init, timeoutMs) {
  try {
    const signal = AbortSignal.timeout(timeoutMs);
    const response = await fetch(`${ctx.config.backendUrl}${path}`, { ...init, signal });
    return { status: response.status, text: await response.text() };
  } catch (err) {
    const timedOut = err?.name === 'TimeoutError' || err?.name === 'AbortError';
    ctx.log.error('backend 連線失敗', { path, name: err?.name, cause: err?.cause?.code });
    throw new HttpFailure(timedOut ? 504 : 502, timedOut ? MESSAGES.timeout : MESSAGES.backend);
  }
}

function parseJsonObject(text) {
  try {
    const value = JSON.parse(text);
    return value && typeof value === 'object' ? value : null;
  } catch {
    return null;
  }
}

const isSuccess = (status) => status >= 200 && status < 300;

/** 細節只進 log，瀏覽器只看到友善訊息。 */
function unexpectedBackend(ctx, path, status, text) {
  ctx.log.error('backend 回應異常', { path, status, body: text });
  return new HttpFailure(502, MESSAGES.backend);
}

async function askBackend(ctx, question) {
  const path = '/api/v1/query';
  const { status, text } = await callBackend(
    ctx,
    path,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json', accept: 'application/json' },
      body: JSON.stringify({ question, include_context: true }),
    },
    ctx.config.limits.askTimeoutMs,
  );
  const body = isSuccess(status) ? parseJsonObject(text) : null;
  if (typeof body?.answer !== 'string') throw unexpectedBackend(ctx, path, status, text);
  return body;
}

/** health 在 build 不符時回 503，但 body 仍是有用的 JSON，所以不看狀態碼。 */
async function readBackendHealth(ctx, timeoutMs) {
  const { text } = await callBackend(ctx, '/api/v1/health', {}, timeoutMs);
  return parseJsonObject(text);
}

const busyFailure = () => new HttpFailure(429, MESSAGES.busy, { 'Retry-After': BUSY_RETRY_SECONDS });

/** 拿到 backend 額度才做事；排隊時讀者走了回 null，不打 backend。 */
async function withAskSlot(ctx, ip, client, work) {
  if (!ctx.askGate.canEnter(ip)) throw busyFailure();
  enforceRate(ctx.askLimiter, ip, MESSAGES.rate);
  const release = await ctx.askGate.enter(ip, client);
  if (!release) {
    if (client.gone) return null;
    throw busyFailure();
  }
  try {
    return await work();
  } finally {
    release();
  }
}

async function handleAsk(ctx, req, res, ip) {
  requireMethod(req, ['POST']);
  requireSameOrigin(req);
  const client = watchClient(req, res);
  const { bodyMaxBytes, questionMaxChars } = ctx.config.limits;
  const question = parseQuestion(await readBody(req, bodyMaxBytes), questionMaxChars);
  if (client.gone) return;
  const answer = await withAskSlot(ctx, ip, client, async () => {
    // 不跟著讀者一起中止 backend：實測中止後它仍把生成跑完，中止只會讓我們不知道 GPU 何時空出來
    const backend = await askBackend(ctx, question);
    if (client.gone) return null;
    return enrich(question, backend, {
      kg: ctx.neo4j.session(),
      healthBuildId: async () => (await readBackendHealth(ctx, ctx.config.neo4j.timeoutMs))?.build_id,
      log: ctx.log,
    });
  });
  if (answer) sendJson(res, 200, answer);
}

function parseVersePath(pathname) {
  const parts = pathname.split('/').slice(3);
  if (parts.length !== 3) throw new HttpFailure(400, MESSAGES.badVerse);
  const [book, chapter, verse] = parts;
  const valid =
    BOOK_ID_RE.test(book) && isBookId(book) && VERSE_NUMBER_RE.test(chapter) && VERSE_NUMBER_RE.test(verse);
  if (!valid) throw new HttpFailure(400, MESSAGES.badVerse);
  return { book, chapter, verse };
}

async function handleVerse(ctx, req, res, pathname, ip) {
  requireMethod(req, ['GET']);
  const { book, chapter, verse } = parseVersePath(pathname);
  enforceRate(ctx.apiLimiter, ip, MESSAGES.rate);
  const path = `/api/v1/verse/${book}/${chapter}/${verse}`;
  const { status, text } = await callBackend(ctx, path, {}, ctx.config.limits.verseTimeoutMs);
  if (status === 404) throw new HttpFailure(404, MESSAGES.noVerse);
  const body = isSuccess(status) ? parseJsonObject(text) : null;
  if (!body) throw unexpectedBackend(ctx, path, status, text);
  sendJson(res, 200, body);
}

function neo4jReachable(ctx) {
  return ctx.neo4j.ping().then(
    () => true,
    (err) => {
      ctx.log.warn('Neo4j ping 失敗', { kind: err?.kind ?? err?.name });
      return false;
    },
  );
}

/** 只回兩個布林：build、版本、服務清單都不給瀏覽器。 */
async function handleHealth(ctx, req, res, ip) {
  requireMethod(req, ['GET']);
  enforceRate(ctx.apiLimiter, ip, MESSAGES.rate);
  // callBackend 已記下失敗細節，這裡只把它轉成 ok=false
  const health = await readBackendHealth(ctx, ctx.config.limits.healthTimeoutMs).catch(() => null);
  const graphReady = health?.graph?.state === 'ready';
  sendJson(res, 200, {
    ok: health?.status === 'ok',
    graph: graphReady && (await neo4jReachable(ctx)),
  });
}

/** 解碼後逐段檢查；.. 與點開頭（含 .env）、反斜線、NUL 一律拒絕。 */
function staticSegments(target) {
  if (!target.startsWith('/')) throw new HttpFailure(400, MESSAGES.badRequest);
  let decoded;
  try {
    decoded = decodeURIComponent(target);
  } catch {
    throw new HttpFailure(400, MESSAGES.badRequest);
  }
  if (decoded.includes('\\') || decoded.includes('\0')) throw new HttpFailure(403, MESSAGES.forbidden);
  const segments = decoded.split('/').filter(Boolean);
  if (segments.some((segment) => segment.startsWith('.'))) throw new HttpFailure(403, MESSAGES.forbidden);
  return segments;
}

/** realpath 後再比一次，symlink 也出不了 public。回傳 null 表示不存在。 */
async function locateStatic(publicDir, segments) {
  const wanted = join(publicDir, ...(segments.length > 0 ? segments : ['index.html']));
  try {
    const [real, root] = await Promise.all([realpath(wanted), realpath(publicDir)]);
    if (!real.startsWith(root + sep)) return null;
    return (await stat(real)).isFile() ? real : null;
  } catch (err) {
    if (NOT_FOUND_CODES.has(err.code)) return null;
    throw err;
  }
}

async function handleStatic(ctx, req, res, pathname) {
  requireMethod(req, ['GET', 'HEAD']);
  const file = await locateStatic(ctx.publicDir, staticSegments(pathname));
  if (!file) throw new HttpFailure(404, MESSAGES.notFound);
  const content = await readFile(file);
  res.writeHead(200, {
    'Content-Type': CONTENT_TYPES[extname(file)] ?? 'application/octet-stream',
    'Content-Length': content.length,
    'Cache-Control': 'no-cache',
  });
  res.end(req.method === 'HEAD' ? undefined : content);
}

function dispatch(ctx, req, res, ip) {
  if (!isAllowedHost(req.headers.host, ctx.config.allowedHosts)) throw new HttpFailure(403, MESSAGES.unknownHost);
  const [pathname] = (req.url ?? '').split('?');
  if (pathname === '/api/ask') return handleAsk(ctx, req, res, ip);
  if (pathname === '/api/health') return handleHealth(ctx, req, res, ip);
  if (pathname.startsWith('/api/verse/')) return handleVerse(ctx, req, res, pathname, ip);
  if (pathname.startsWith('/api/')) throw new HttpFailure(404, MESSAGES.notFound);
  return handleStatic(ctx, req, res, pathname);
}

function respondToFailure(ctx, res, err) {
  if (res.headersSent) {
    ctx.log.error('回應途中出錯', { name: err?.name });
    res.destroy();
    return;
  }
  if (err instanceof HttpFailure) {
    sendJson(res, err.status, { error: err.message }, err.headers);
    return;
  }
  ctx.log.error('未預期的錯誤', { name: err?.name, message: err?.message });
  sendJson(res, 500, { error: MESSAGES.internal });
}

/** 建立 server（不 listen），方便測試注入設定與時鐘。 */
export function createDemoServer({ config, log, publicDir = PUBLIC_DIR, now = Date.now }) {
  const ctx = {
    config,
    log,
    publicDir,
    neo4j: createNeo4jClient(config.neo4j),
    askGate: createAskGate({
      limit: config.limits.maxConcurrentAsks,
      maxWaiters: config.limits.askQueueMax,
      maxWaitMs: config.limits.askQueueWaitMs,
    }),
    askLimiter: createRateLimiter({ limit: config.limits.asksPerMinute, now }),
    apiLimiter: createRateLimiter({ limit: config.limits.apiPerMinute, now }),
  };
  const { limits } = config;
  const server = http.createServer({
    headersTimeout: limits.headersTimeoutMs,
    requestTimeout: limits.requestTimeoutMs,
    connectionsCheckingInterval: limits.connectionCheckMs,
  }, (req, res) => {
    // 連線一斷 remoteAddress 就變 undefined，所以進來時就記下。這時就讀不到表示已經被 RST：
    // 沒有人要收這個回應，也不能讓它用「不知道是誰」逃過限流、又把題目送進 backend。
    const ip = req.socket.remoteAddress;
    if (!ip) {
      res.destroy();
      return;
    }
    Object.entries(SECURITY_HEADERS).forEach(([name, value]) => res.setHeader(name, value));
    Promise.resolve()
      .then(() => dispatch(ctx, req, res, ip))
      .catch((err) => respondToFailure(ctx, res, err));
  });
  server.timeout = limits.idleSocketMs;
  guardConnections(server, {
    maxConnections: limits.maxConnections,
    maxPerIp: limits.maxConnectionsPerIp,
    now,
    onRefuse: () => log.warn('連線數已達上限，拒絕新連線'),
  });
  return server;
}

export async function start({ env = process.env, envFile, sink = console, publicDir = PUBLIC_DIR } = {}) {
  const config = loadConfig({ env, envFile });
  const log = createLogger(config.secrets, sink);
  config.warnings.forEach((warning) => log.warn(warning));
  const server = createDemoServer({ config, log, publicDir });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(config.port, config.host, resolve);
  });
  log.info(`Bible RAG demo 已啟動：http://${config.host}:${server.address().port}`);
  return server;
}

function stopOnSignal(server) {
  const stop = () => {
    server.close(() => process.exit(0));
    server.closeAllConnections();
  };
  process.once('SIGINT', stop);
  process.once('SIGTERM', stop);
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(realpathSync(process.argv[1])).href;
if (isMain) {
  start().then(stopOnSignal, (err) => {
    console.error(`demo 啟動失敗：${err.code ?? err.name}`);
    process.exit(1);
  });
}
