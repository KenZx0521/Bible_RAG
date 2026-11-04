// 靜態檔、路徑穿越、verse 代理、health、安全標頭。
import { afterEach, describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { symlinkSync } from 'node:fs';
import { join } from 'node:path';

import { sendJson, startStack } from './stack.mjs';

const stacks = [];
async function stack(options) {
  const started = await startStack(options);
  stacks.push(started);
  return started;
}

afterEach(async () => {
  await Promise.all(stacks.splice(0).map((s) => s.close()));
});

describe('靜態檔', () => {
  test('/ 與 /?q= 回 index.html', async () => {
    const s = await stack();

    for (const path of ['/', '/?q=%E8%80%B6%E7%A9%8C', '/index.html']) {
      const response = await s.request({ path });
      assert.equal(response.status, 200);
      assert.match(response.headers['content-type'], /^text\/html/);
      assert.match(response.text, /<title>demo/);
    }
  });

  test('內容類型正確', async () => {
    const s = await stack();

    assert.match((await s.request({ path: '/js/app.js' })).headers['content-type'], /^text\/javascript/);
    assert.match((await s.request({ path: '/styles.css' })).headers['content-type'], /^text\/css/);
    assert.match((await s.request({ path: '/blob.bin' })).headers['content-type'], /^application\/octet-stream/);
  });

  test('HEAD 沒有 body、POST 回 405、不存在與資料夾回 404', async () => {
    const s = await stack();

    const head = await s.request({ method: 'HEAD', path: '/' });
    assert.equal(head.status, 200);
    assert.equal(head.text, '');
    assert.equal((await s.request({ method: 'POST', path: '/' })).status, 405);
    assert.equal((await s.request({ path: '/nope.js' })).status, 404);
    assert.equal((await s.request({ path: '/js' })).status, 404);
    assert.equal((await s.request({ path: '/js/' })).status, 404);
    assert.equal((await s.request({ path: '/index.html/x' })).status, 404);
  });

  const traversals = [
    '/../secret.txt',
    '/js/../../secret.txt',
    '/%2e%2e/secret.txt',
    '/%2E%2E/secret.txt',
    '/..%2fsecret.txt',
    '/%2e%2e%2fsecret.txt',
    '/js/%2e%2e/%2e%2e/secret.txt',
    '/..\\secret.txt',
    '/js\\..\\..\\secret.txt',
    '/..%5csecret.txt',
    '/%2e%2e%5csecret.txt',
    '/%252e%252e/secret.txt',
    '/.env',
    '/%2eenv',
    '/../.env',
    '/.hidden',
    '/link.txt',
    '/secret.txt%00.html',
    '/%E0%A4%A',
    '//etc/passwd',
    '/%2fetc%2fpasswd',
    '/etc/passwd',
    'http://127.0.0.1/../secret.txt',
    '*',
  ];
  for (const path of traversals) {
    test(`路徑穿越被擋：${path}`, async () => {
      const s = await stack();

      const response = await s.request({ path });

      assert.notEqual(response.status, 200);
      assert.equal(response.text.includes('TOP-SECRET'), false);
      assert.equal(response.text.includes('root:'), false);
      assert.equal(response.text.includes(s.publicDir), false);
    });
  }

  const layered = {
    '/%2e%2e/secret.txt': 403,
    '/..%2fsecret.txt': 403,
    '/..\\secret.txt': 403,
    '/..%5csecret.txt': 403,
    '/.env': 403,
    '/secret.txt%00.html': 403,
    '/link.txt': 404,
    '/%E0%A4%A': 400,
    'http://127.0.0.1/../secret.txt': 400,
  };
  for (const [path, status] of Object.entries(layered)) {
    test(`每層防線各自有作用：${path} → ${status}`, async () => {
      const s = await stack();

      assert.equal((await s.request({ path })).status, status);
    });
  }

  test('確實存在的檔案，用編碼過的絕對路徑也讀不到', async () => {
    const s = await stack();
    const secretFile = encodeURIComponent(join(s.root, 'secret.txt'));

    for (const path of [`/${secretFile}`, `//${s.root}/secret.txt`, `/${encodeURIComponent(`${s.publicDir}/../secret.txt`)}`]) {
      const response = await s.request({ path });

      assert.notEqual(response.status, 200, path);
      assert.equal(response.text.includes('TOP-SECRET'), false);
    }
  });
});

describe('GET /api/verse', () => {
  const VERSE = { book_id: 'jhn', chapter: 3, verse: 16, text: '「上帝愛世人' };

  test('合法請求代理到 backend，回傳內容不動', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 200, VERSE) });

    const response = await s.request({ path: '/api/verse/jhn/3/16' });

    assert.equal(response.status, 200);
    assert.deepEqual(response.json, VERSE);
    assert.equal(s.backend.requests[0].url, '/api/v1/verse/jhn/3/16');
  });

  test('66 卷書表的頭尾與數字開頭的書卷都可以', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 200, VERSE) });

    for (const path of ['/api/verse/gen/1/1', '/api/verse/rev/22/21', '/api/verse/1ki/22/41']) {
      assert.equal((await s.request({ path })).status, 200);
    }
  });

  const invalid = [
    '/api/verse/zzz/1/1',
    '/api/verse/JHN/3/16',
    '/api/verse/john/3/16',
    '/api/verse/jh/3/16',
    '/api/verse/0ki/1/1',
    '/api/verse/jhn/0/1',
    '/api/verse/jhn/1/0',
    '/api/verse/jhn/-1/1',
    '/api/verse/jhn/1.5/1',
    '/api/verse/jhn/1e2/1',
    '/api/verse/jhn/01/1',
    '/api/verse/jhn/3',
    '/api/verse/jhn/3/16/17',
    '/api/verse/jhn/3/9999',
    '/api/verse/jhn/99999999999999999999/1',
    '/api/verse/%2e%2e/3/16',
    '/api/verse/..%2f/3/16',
    '/api/verse/jhn/3/16%2f..',
    '/api/verse/',
  ];
  for (const path of invalid) {
    test(`400：${path}`, async () => {
      const s = await stack();

      const response = await s.request({ path });

      assert.equal(response.status, 400);
      assert.equal(s.backend.requests.length, 0);
    });
  }

  test('backend 404 → 404「找不到這節經文」', async () => {
    const s = await stack({ backend: (_e, res) => sendJson(res, 404, { detail: 'no PDF slot or alias for jhn.99.16' }) });

    const response = await s.request({ path: '/api/verse/jhn/99/16' });

    assert.equal(response.status, 404);
    assert.deepEqual(response.json, { error: '找不到這節經文' });
  });

  test('backend 500 → 502 不洩漏；逾時 → 504；非 JSON → 502', { timeout: 5000 }, async () => {
    const down = await stack({ backend: (_e, res) => sendJson(res, 500, { detail: 'Traceback' }) });
    const slow = await stack({ backend: () => {}, limits: { verseTimeoutMs: 40 } });
    const junk = await stack({ backend: (_e, res) => res.end('<html>') });

    const failed = await down.request({ path: '/api/verse/jhn/3/16' });
    assert.equal(failed.status, 502);
    assert.equal(failed.text.includes('Traceback'), false);
    assert.equal((await slow.request({ path: '/api/verse/jhn/3/16' })).status, 504);
    assert.equal((await junk.request({ path: '/api/verse/jhn/3/16' })).status, 502);
  });

  test('POST 回 405；有限流', async () => {
    const s = await stack({ limits: { apiPerMinute: 1 }, backend: (_e, res) => sendJson(res, 200, VERSE) });

    assert.equal((await s.request({ method: 'POST', path: '/api/verse/jhn/3/16' })).status, 405);
    assert.equal((await s.request({ path: '/api/verse/jhn/3/16' })).status, 200);
    assert.equal((await s.request({ path: '/api/verse/jhn/3/16' })).status, 429);
  });
});

describe('GET /api/health', () => {
  const healthy = (extra = {}) => (_e, res) =>
    sendJson(res, 200, {
      status: 'ok',
      build_id: 'b_secret_build',
      services: { postgres: true },
      graph: { state: 'ready', kg_sha256: 'abc', neo4j_version: '5' },
      ...extra,
    });

  test('正常：只回 ok 與 graph，不洩漏內部細節', async () => {
    const s = await stack({ backend: healthy() });

    const response = await s.request({ path: '/api/health' });

    assert.equal(response.status, 200);
    assert.deepEqual(response.json, { ok: true, graph: true });
  });

  test('prod 沒有圖譜：graph=false', async () => {
    const s = await stack({ backend: healthy({ graph: { state: 'missing' } }) });

    assert.deepEqual((await s.request({ path: '/api/health' })).json, { ok: true, graph: false });
  });

  test('Neo4j 帳密錯：graph=false，答案端照常', async () => {
    const s = await stack({ backend: healthy(), neo4j: (_e, res) => sendJson(res, 401, { errors: [] }) });

    assert.deepEqual((await s.request({ path: '/api/health' })).json, { ok: true, graph: false });
    assert.ok(s.sink.lines.some((line) => line.includes('unauthorized')));
  });

  test('build 不符（503 mismatch）：ok=false', async () => {
    const s = await stack({
      backend: (_e, res) => sendJson(res, 503, { status: 'mismatch', graph: { state: 'ready' } }),
    });

    assert.deepEqual((await s.request({ path: '/api/health' })).json, { ok: false, graph: true });
  });

  test('backend 連不上或壞掉：ok=false、graph=false', async () => {
    const down = await stack({ backendUrl: 'http://127.0.0.1:9' });
    const junk = await stack({ backend: (_e, res) => res.end('<html>') });

    assert.deepEqual((await down.request({ path: '/api/health' })).json, { ok: false, graph: false });
    assert.deepEqual((await junk.request({ path: '/api/health' })).json, { ok: false, graph: false });
  });

  test('POST 回 405', async () => {
    const s = await stack();

    assert.equal((await s.request({ method: 'POST', path: '/api/health' })).status, 405);
  });
});

describe('其他路由與安全標頭', () => {
  test('未知的 /api 路徑回 JSON 404', async () => {
    const s = await stack();

    const response = await s.request({ path: '/api/nope' });

    assert.equal(response.status, 404);
    assert.equal(typeof response.json.error, 'string');
  });

  test('所有回應都帶安全標頭（靜態、API、錯誤）', async () => {
    const s = await stack();
    const probes = [
      { path: '/' },
      { path: '/api/health' },
      { path: '/nope' },
      { path: '/../secret.txt' },
      { method: 'POST', path: '/api/ask', body: '{' },
      { path: '/api/verse/zzz/1/1' },
    ];

    for (const probe of probes) {
      const { headers } = await s.request(probe);
      const csp = headers['content-security-policy'];
      assert.match(csp, /default-src 'self'/);
      assert.match(csp, /script-src 'self'(;|$)/);
      assert.match(csp, /style-src 'self' https:\/\/fonts\.googleapis\.com/);
      assert.match(csp, /font-src 'self' https:\/\/fonts\.gstatic\.com/);
      assert.equal(csp.includes('unsafe-inline'), false);
      assert.equal(csp.includes('unsafe-eval'), false);
      assert.equal(headers['x-content-type-options'], 'nosniff');
      assert.equal(headers['referrer-policy'], 'strict-origin-when-cross-origin');
      assert.equal(headers['x-frame-options'], 'DENY');
    }
  });
});

describe('靜態檔：怪路徑只是找不到，不是伺服器錯誤', () => {
  test('超長檔名與符號連結循環回 404，不寫錯誤 log（未驗證的請求不能無限灌 log）', async () => {
    const s = await stack();
    symlinkSync('loop', join(s.publicDir, 'loop'));
    const before = s.sink.lines.length;

    for (const path of [`/${'a'.repeat(301)}`, '/loop', '/loop/x']) {
      assert.equal((await s.request({ path })).status, 404, path);
    }

    assert.deepEqual(s.sink.lines.slice(before), []);
  });
});
