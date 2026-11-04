// 設定檔、log 脫敏、整個程序的啟動與關閉。
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { DEFAULTS, DEFAULT_ENV_FILE, LIMITS, createLogger, loadConfig, parseEnvText } from '../../lib/config.mjs';
import { start } from '../../server.mjs';
import {
  TEST_PASSWORD,
  TEST_USER,
  backendFromFixture,
  captureSink,
  fakeServer,
  loadFixture,
  neo4jFromFixture,
  rawRequest,
  waitUntil,
} from './stack.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(HERE, '..', '..');

function withEnvFile(content, run) {
  const dir = mkdtempSync(join(tmpdir(), 'bible-env-'));
  const file = join(dir, '.env');
  try {
    if (content !== null) writeFileSync(file, content);
    return run(file);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe('parseEnvText', () => {
  test('只留 NEO4J 帳密，其他 key 一律不讀', () => {
    const text = 'OPENAI_API_KEY=sk-other\nNEO4J_USER=neo4j\nNEO4J_PASSWORD=abc\nPOSTGRES_PASSWORD=zzz\n';

    assert.deepEqual(parseEnvText(text), { NEO4J_USER: 'neo4j', NEO4J_PASSWORD: 'abc' });
  });

  test('處理引號、export、行內註解、註解行、CRLF', () => {
    assert.deepEqual(parseEnvText('export NEO4J_USER="ne o#4j"\r\nNEO4J_PASSWORD=\'a=b\' # note\r\n'), {
      NEO4J_USER: 'ne o#4j',
      NEO4J_PASSWORD: 'a=b',
    });
    assert.deepEqual(parseEnvText('# NEO4J_USER=commented\nNEO4J_PASSWORD=plain # note\n'), {
      NEO4J_PASSWORD: 'plain',
    });
    assert.deepEqual(parseEnvText('NEO4J_PASSWORD=pa#ss\n'), { NEO4J_PASSWORD: 'pa#ss' });
    assert.deepEqual(parseEnvText('garbage line\n\n'), {});
  });
});

describe('loadConfig', () => {
  test('預設值與契約一致，.env 路徑是 repo 根目錄', () => {
    withEnvFile('NEO4J_USER=u\nNEO4J_PASSWORD=p\n', (envFile) => {
      const config = loadConfig({ env: {}, envFile });

      assert.equal(config.host, '127.0.0.1');
      assert.equal(config.port, 5173);
      assert.equal(config.backendUrl, 'http://localhost:8002');
      assert.equal(config.neo4j.url, 'http://127.0.0.1:7474/db/neo4j/query/v2');
      assert.equal(config.neo4j.user, 'u');
      assert.equal(config.neo4j.password, 'p');
      assert.equal(config.neo4j.timeoutMs, LIMITS.neo4jTimeoutMs);
      assert.deepEqual(config.warnings, []);
      assert.ok(Object.isFrozen(config));
    });
    assert.equal(DEFAULT_ENV_FILE, resolve(FRONTEND, '..', '.env'));
    assert.equal(DEFAULTS.port, 5173);
  });

  test('環境變數可覆寫，且優先於 .env', () => {
    withEnvFile('NEO4J_USER=file\nNEO4J_PASSWORD=file\n', (envFile) => {
      const config = loadConfig({
        envFile,
        env: {
          DEMO_HOST: '0.0.0.0',
          DEMO_PORT: '0',
          DEMO_BACKEND_URL: 'http://backend.test:9000/',
          NEO4J_HTTP_URL: 'http://neo.test:7474',
          NEO4J_USER: 'envuser',
          NEO4J_PASSWORD: 'envpw',
        },
      });

      assert.equal(config.host, '0.0.0.0');
      assert.equal(config.port, 0);
      assert.equal(config.backendUrl, 'http://backend.test:9000');
      assert.equal(config.neo4j.url, 'http://neo.test:7474/db/neo4j/query/v2');
      assert.equal(config.neo4j.user, 'envuser');
      assert.equal(config.neo4j.password, 'envpw');
    });
  });

  test('NEO4J_HTTP_URL 寫完整路徑就照用', () => {
    withEnvFile('', (envFile) => {
      const config = loadConfig({ envFile, env: { NEO4J_HTTP_URL: 'http://neo.test:7474/db/other/query/v2' } });

      assert.equal(config.neo4j.url, 'http://neo.test:7474/db/other/query/v2');
    });
  });

  test('.env 不存在或沒帳密：不當掉，給一行警告，且 warnings 不含任何值', () => {
    for (const content of [null, 'OTHER=1\n', 'NEO4J_USER=only-user-value\n']) {
      withEnvFile(content, (envFile) => {
        const config = loadConfig({ env: {}, envFile });

        assert.equal(config.neo4j.password, '');
        assert.equal(config.warnings.length, 1);
        assert.match(config.warnings[0], /NEO4J/);
        assert.equal(config.warnings[0].includes('only-user-value'), false);
      });
    }
  });

  test('壞的設定值退回預設並警告，網址裡的帳密不留也不印', () => {
    withEnvFile('NEO4J_USER=u\nNEO4J_PASSWORD=p\n', (envFile) => {
      const config = loadConfig({
        envFile,
        env: {
          DEMO_PORT: '99999',
          DEMO_BACKEND_URL: 'ftp://x',
          NEO4J_HTTP_URL: 'http://leak-user:leak-pw@neo.test:7474/db/neo4j/query/v2',
        },
      });

      assert.equal(config.port, DEFAULTS.port);
      assert.equal(config.backendUrl, DEFAULTS.backendUrl);
      assert.equal(config.neo4j.url, 'http://neo.test:7474/db/neo4j/query/v2');
      const printed = config.warnings.join('\n');
      assert.equal(config.warnings.length, 3);
      assert.equal(printed.includes('leak-pw'), false);
      assert.equal(printed.includes('leak-user'), false);
    });
    withEnvFile('NEO4J_USER=u\nNEO4J_PASSWORD=p\n', (envFile) => {
      const config = loadConfig({ envFile, env: { DEMO_BACKEND_URL: 'not a url', DEMO_PORT: 'abc' } });

      assert.equal(config.backendUrl, DEFAULTS.backendUrl);
      assert.equal(config.port, DEFAULTS.port);
    });
  });

  test('secrets 有密碼與 Basic 字串，沒密碼就是空的', () => {
    withEnvFile('NEO4J_USER=u\nNEO4J_PASSWORD=p\n', (envFile) => {
      assert.deepEqual(loadConfig({ env: {}, envFile }).secrets, ['p', Buffer.from('u:p').toString('base64')]);
    });
    withEnvFile('', (envFile) => {
      assert.deepEqual(loadConfig({ env: {}, envFile }).secrets, []);
    });
  });
});

describe('createLogger', () => {
  test('訊息與 context 都脫敏，空字串不算秘密', () => {
    const sink = captureSink();
    const log = createLogger(['hunter2', ''], sink);

    log.error('登入失敗 hunter2', { detail: 'x hunter2 y' });
    log.warn('純文字');
    log.info('hi');

    assert.deepEqual(sink.lines, ['登入失敗 *** {"detail":"x *** y"}', '純文字', 'hi']);
  });

  test('context 無法序列化也不會丟例外', () => {
    const sink = captureSink();
    const circular = {};
    circular.self = circular;

    createLogger([], sink).error('壞掉', circular);

    assert.match(sink.lines[0], /壞掉/);
  });
});

describe('start：完整啟動', () => {
  test('.env 讀不到：照常啟動，一行警告，kg unavailable', async () => {
    const fixture = loadFixture('walk_plain');
    const backend = await fakeServer(backendFromFixture(fixture));
    const sink = captureSink();
    const dir = mkdtempSync(join(tmpdir(), 'bible-start-'));
    const server = await start({
      env: { DEMO_PORT: '0', DEMO_BACKEND_URL: backend.url },
      envFile: join(dir, 'missing.env'),
      sink,
    });
    try {
      const url = `http://127.0.0.1:${server.address().port}`;
      const response = await rawRequest(url, {
        method: 'POST',
        path: '/api/ask',
        body: JSON.stringify({ question: fixture.question }),
      });

      assert.equal(response.status, 200);
      assert.equal(response.json.kg.status, 'unavailable');
      assert.equal(sink.lines.filter((line) => /NEO4J/.test(line)).length, 1);
      assert.ok(sink.lines.some((line) => line.includes(url)));
    } finally {
      server.closeAllConnections();
      await new Promise((done) => server.close(done));
      await backend.close();
      rmSync(dir, { recursive: true, force: true });
    }
  });

  test('node server.mjs 真的啟動、回應、收 SIGTERM 正常退出，輸出不含密碼', async () => {
    const fixture = loadFixture('walk_plain');
    const backend = await fakeServer(backendFromFixture(fixture));
    const neo4j = await fakeServer(neo4jFromFixture(fixture));
    const child = spawn(process.execPath, ['server.mjs'], {
      cwd: FRONTEND,
      env: {
        PATH: process.env.PATH,
        DEMO_PORT: '0',
        DEMO_BACKEND_URL: backend.url,
        NEO4J_HTTP_URL: neo4j.url,
        NEO4J_USER: TEST_USER,
        NEO4J_PASSWORD: TEST_PASSWORD,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    let output = '';
    const onData = (chunk) => {
      output += chunk;
    };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
    const exited = new Promise((done) => child.once('exit', (code, signal) => done({ code, signal })));
    try {
      const announced = /http:\/\/127\.0\.0\.1:\d+/;
      await waitUntil(() => announced.test(output), 'server 印出啟動網址');
      const [url] = output.match(announced);

      const health = await rawRequest(url, { path: '/api/health' });

      assert.deepEqual(health.json, { ok: true, graph: true });
    } finally {
      child.kill('SIGTERM');
    }
    assert.deepEqual(await exited, { code: 0, signal: null });
    assert.equal(output.includes(TEST_PASSWORD), false);
    await Promise.all([backend.close(), neo4j.close()]);
  });
});
