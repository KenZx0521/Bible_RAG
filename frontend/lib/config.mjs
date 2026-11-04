// 設定：環境變數＋repo 根目錄 .env 的 NEO4J_USER／NEO4J_PASSWORD。
// 帳密只留在 server：警告訊息絕不帶值，createLogger 再多一層脫敏。
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const NEO4J_QUERY_PATH = '/db/neo4j/query/v2';
const CREDENTIAL_KEYS = new Set(['NEO4J_USER', 'NEO4J_PASSWORD']);
const MAX_PORT = 65535;

export const DEFAULT_ENV_FILE = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '.env');

export const DEFAULTS = Object.freeze({
  host: '127.0.0.1',
  port: 5173,
  backendUrl: 'http://localhost:8002',
  neo4jUrl: `http://127.0.0.1:7474${NEO4J_QUERY_PATH}`,
});

export const LIMITS = Object.freeze({
  questionMaxChars: 500,
  bodyMaxBytes: 8 * 1024,
  askTimeoutMs: 120_000,
  verseTimeoutMs: 10_000,
  healthTimeoutMs: 5_000,
  neo4jTimeoutMs: 2_000,
  maxConcurrentAsks: 2,
  askQueueMax: 2,
  askQueueWaitMs: 60_000,
  asksPerMinute: 20,
  apiPerMinute: 120,
  // 慢連線：標頭（含連上後什麼都不送）與整個請求都有時限。實際關閉時間最多再多一個檢查週期，實測 12／32 秒
  headersTimeoutMs: 10_000,
  requestTimeoutMs: 30_000,
  connectionCheckMs: 2_000,
  // 請求送完、等回應時的閒置上限；要比「排隊＋等 backend」長，等答案時才不會被砍
  idleSocketMs: 200_000,
  // 每條半開連線約 12KB。一個 IP 佔滿也只有 64 條；SSH 轉埠時所有人都是同一個 IP，這個數字約夠十個瀏覽器
  maxConnections: 1024,
  maxConnectionsPerIp: 64,
});

const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com",
  "img-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ');

export const SECURITY_HEADERS = Object.freeze({
  'Content-Security-Policy': CSP,
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'X-Frame-Options': 'DENY',
});

function unquote(value) {
  const quote = value[0];
  if (quote === '"' || quote === "'") {
    const end = value.indexOf(quote, 1);
    if (end > 0) return value.slice(1, end);
  }
  return value.replace(/\s+#.*$/, '');
}

function parseLine(line) {
  const match = line.match(/^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
  return match ? [match[1], unquote(match[2].trim())] : null;
}

/** 只取 Neo4j 帳密；.env 其他 key（其他服務的密碼）一律不進記憶體。 */
export function parseEnvText(text) {
  const entries = String(text)
    .split(/\r?\n/)
    .map(parseLine)
    .filter((entry) => entry && CREDENTIAL_KEYS.has(entry[0]));
  return Object.fromEntries(entries);
}

function readEnvFile(path) {
  try {
    return parseEnvText(readFileSync(path, 'utf8'));
  } catch {
    return {}; // 讀不到就當沒有帳密，由 loadConfig 警告一行；不記錄例外以免帶出路徑外的內容
  }
}

function parsePort(raw, warnings) {
  if (raw === undefined || raw === '') return DEFAULTS.port;
  const port = Number(raw);
  if (Number.isInteger(port) && port >= 0 && port <= MAX_PORT) return port;
  warnings.push(`DEMO_PORT 不是有效的埠號，改用預設 ${DEFAULTS.port}。`);
  return DEFAULTS.port;
}

/** 解析服務網址：壞掉退回預設；網址裡的帳密一律丟掉（fetch 會拒絕，錯誤訊息還可能帶出來）。 */
function parseServiceUrl(name, raw, fallback, warnings) {
  if (!raw) return new URL(fallback);
  let url;
  try {
    url = new URL(raw);
  } catch {
    url = null;
  }
  if (!url || !['http:', 'https:'].includes(url.protocol)) {
    warnings.push(`${name} 不是有效的 http(s) 網址，改用預設值。`);
    return new URL(fallback);
  }
  if (url.username || url.password) {
    warnings.push(`${name} 的網址帶了帳密，已忽略；帳密請放 .env。`);
    url.username = '';
    url.password = '';
  }
  return url;
}

function backendUrlFrom(env, warnings) {
  const url = parseServiceUrl('DEMO_BACKEND_URL', env.DEMO_BACKEND_URL, DEFAULTS.backendUrl, warnings);
  return url.href.replace(/\/+$/, '');
}

function neo4jUrlFrom(env, warnings) {
  const url = parseServiceUrl('NEO4J_HTTP_URL', env.NEO4J_HTTP_URL, DEFAULTS.neo4jUrl, warnings);
  if (url.pathname === '/') url.pathname = NEO4J_QUERY_PATH;
  return url.href;
}

/** Host 白名單的網域：綁定的主機名加上 DEMO_ALLOWED_HOSTS。IP 字面值與 localhost 不必列（見 isAllowedHost）。 */
function allowedHostsFrom(env) {
  const extra = (env.DEMO_ALLOWED_HOSTS ?? '').split(',').map((host) => host.trim().toLowerCase()).filter(Boolean);
  return Object.freeze([(env.DEMO_HOST || DEFAULTS.host).toLowerCase(), ...extra]);
}

function credentialsFrom(env, envFile, warnings) {
  const fromFile = readEnvFile(envFile);
  const user = env.NEO4J_USER || fromFile.NEO4J_USER || '';
  const password = env.NEO4J_PASSWORD || fromFile.NEO4J_PASSWORD || '';
  if (user && password) return { user, password };
  warnings.push('讀不到 NEO4J_USER／NEO4J_PASSWORD：答案照常，但關聯圖無法顯示。');
  return { user: '', password: '' };
}

export function loadConfig({ env = process.env, envFile = DEFAULT_ENV_FILE } = {}) {
  const warnings = [];
  const { user, password } = credentialsFrom(env, envFile, warnings);
  const secrets = password ? [password, Buffer.from(`${user}:${password}`).toString('base64')] : [];
  return Object.freeze({
    host: env.DEMO_HOST || DEFAULTS.host,
    allowedHosts: allowedHostsFrom(env),
    port: parsePort(env.DEMO_PORT, warnings),
    backendUrl: backendUrlFrom(env, warnings),
    neo4j: Object.freeze({
      url: neo4jUrlFrom(env, warnings),
      user,
      password,
      timeoutMs: LIMITS.neo4jTimeoutMs,
    }),
    limits: LIMITS,
    secrets: Object.freeze(secrets),
    warnings: Object.freeze(warnings),
  });
}

function safeStringify(value) {
  try {
    return JSON.stringify(value);
  } catch {
    return '[無法序列化]';
  }
}

/** 同一個秘密在 log 裡可能長的樣子：context 會被 JSON.stringify（跳脫一次），backend 回的 JSON 字串再跳脫一次，
 *  網址裡則是百分比編碼。只比對原字串的話，含引號、反斜線、換行的密碼就遮不到。 */
function secretForms(secret) {
  const escaped = JSON.stringify(secret).slice(1, -1);
  return [secret, escaped, JSON.stringify(escaped).slice(1, -1), encodeURIComponent(secret)];
}

export const LOG_LINE_CHARS = 1000;

/** 所有 log 都經過這裡：訊息與 context 先組成一行，再把秘密字串換掉。長的先換，短的才不會只遮掉一半。 */
export function createLogger(secrets = [], sink = console) {
  const active = [...new Set(secrets.filter(Boolean).flatMap(secretForms))].sort((a, b) => b.length - a.length);
  const scrub = (line) => active.reduce((out, secret) => out.split(secret).join('***'), line);
  const emit = (level) => (message, context) => {
    const line = context === undefined ? String(message) : `${message} ${safeStringify(context)}`;
    // 先遮再切：反過來的話，密碼跨在切點上時前半段會留在 log 裡
    sink[level](scrub(line).slice(0, LOG_LINE_CHARS));
  };
  return Object.freeze({ info: emit('info'), warn: emit('warn'), error: emit('error') });
}
