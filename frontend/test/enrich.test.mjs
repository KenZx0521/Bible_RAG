// enrich 是純邏輯＋注入的查詢函式：這裡完全不開網路，用真實 fixture 當 Neo4j 的資料來源。
import { describe, test } from 'node:test';
import assert from 'node:assert/strict';

import {
  KG_QUERY_FAILED,
  emptyKg,
  enrich,
  eventAnchors,
  findWalk,
  nameTargets,
  passageTargets,
} from '../lib/enrich.mjs';
import { kgFromFixture, loadFixture, silentLog, toBackendBody } from './helpers/stack.mjs';

const WALK_FIXTURES = ['walk_plain', 'walk_event', 'kin', 'regnal'];
const noHealth = async () => {
  throw new Error('不該查 health');
};

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

describe('enrich：四種 kg.status', () => {
  for (const name of WALK_FIXTURES) {
    test(`ok：${name} 的 kg 與真實回應一致`, async () => {
      const fixture = loadFixture(name);
      const kg = kgFromFixture(fixture);

      const result = await enrich(fixture.question, toBackendBody(fixture), {
        kg,
        healthBuildId: noHealth,
        log: silentLog(),
      });

      assert.deepEqual(result, fixture);
    });
  }

  test('not_walked：沒有 graph_walk 就不查 Neo4j', async () => {
    const fixture = loadFixture('direct');
    const kg = kgFromFixture(fixture);

    const result = await enrich(fixture.question, toBackendBody(fixture), {
      kg,
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.deepEqual(result, fixture);
    assert.equal(kg.calls.length, 0);
  });

  test('walk_skipped：帶 skip_reason，不查 Neo4j', async () => {
    const fixture = loadFixture('walk_plain');
    const body = toBackendBody(fixture);
    const trace = body.graph_trace.map((op) => ({ ...op, skip_reason: 'timeout' }));
    const kg = kgFromFixture(fixture);

    const result = await enrich(fixture.question, { ...body, graph_trace: trace }, {
      kg,
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.deepEqual(result.kg, emptyKg('walk_skipped', 'timeout'));
    assert.equal(kg.calls.length, 0);
    assert.equal(result.answer, fixture.answer);
  });

  test('unavailable：任一查詢失敗，答案照回且 kg 其餘欄位為空', async () => {
    const fixture = loadFixture('walk_event');
    const log = silentLog();
    const kg = {
      ...kgFromFixture(fixture),
      mentions: async () => {
        throw Object.assign(new Error('boom'), { kind: 'timeout' });
      },
    };

    const result = await enrich(fixture.question, toBackendBody(fixture), {
      kg,
      healthBuildId: noHealth,
      log,
    });

    assert.deepEqual(result.kg, emptyKg('unavailable', KG_QUERY_FAILED));
    assert.equal(result.answer, fixture.answer);
    assert.deepEqual(result.sources, fixture.sources);
    assert.match(log.lines.join('\n'), /timeout/);
  });
});

describe('enrich：build_id', () => {
  test('取第一個 source 的 build_id，並用它查 Neo4j', async () => {
    const fixture = loadFixture('walk_event');
    const body = toBackendBody(fixture);
    const sources = body.sources.map((s, i) => (i === 0 ? { ...s, build_id: 'b_first' } : s));
    const kg = kgFromFixture(fixture);

    const result = await enrich(fixture.question, { ...body, sources }, {
      kg,
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.equal(result.build_id, 'b_first');
    assert.ok(kg.calls.length > 0);
    assert.ok(kg.calls.every(([, b]) => b === 'b_first'));
  });

  test('沒有 source 就用 health 的 build_id', async () => {
    const fixture = loadFixture('walk_plain');
    const kg = kgFromFixture(fixture);

    const result = await enrich(fixture.question, { ...toBackendBody(fixture), sources: [] }, {
      kg,
      healthBuildId: async () => 'b_health',
      log: silentLog(),
    });

    assert.equal(result.build_id, 'b_health');
    assert.equal(result.kg.status, 'ok');
    assert.ok(kg.calls.every(([, b]) => b === 'b_health'));
  });

  test('拿不到 build_id：絕不做無過濾查詢，回 unavailable', async () => {
    const fixture = loadFixture('walk_plain');
    const kg = kgFromFixture(fixture);
    const log = silentLog();

    const result = await enrich(fixture.question, { ...toBackendBody(fixture), sources: [] }, {
      kg,
      healthBuildId: async () => {
        throw new Error('health 掛了');
      },
      log,
    });

    assert.equal(result.build_id, null);
    assert.deepEqual(result.kg, emptyKg('unavailable', KG_QUERY_FAILED));
    assert.equal(kg.calls.length, 0);
  });

  test('not_walked 且沒有 source：build_id 仍取 health，頁尾才有得顯示', async () => {
    const fixture = loadFixture('direct');

    const result = await enrich(fixture.question, { ...toBackendBody(fixture), sources: [] }, {
      kg: kgFromFixture(fixture),
      healthBuildId: async () => 'b_health',
      log: silentLog(),
    });

    assert.equal(result.build_id, 'b_health');
    assert.equal(result.kg.status, 'not_walked');
  });
});

describe('enrich：集合規則', () => {
  test('name 集合＝nodes 前 names.length 個 ∪ seeds 中 nm: 開頭者，後者才算問題裡的名字', () => {
    const walk = {
      nodes: ['nm:a', 'nm:b', 'ps:x'],
      names: ['甲', '乙'],
      seeds: ['ps:x', 'nm:b', 'nm:c'],
    };

    const { ids, inQuestion } = nameTargets(walk);

    assert.deepEqual(ids, ['nm:a', 'nm:b', 'nm:c']);
    assert.deepEqual([...inQuestion], ['nm:b', 'nm:c']);
  });

  test('nodes 超過 names.length 的部分不算名字，即使長得像名字', () => {
    const { ids } = nameTargets({ nodes: ['nm:a', 'nm:z'], names: ['甲'], seeds: [] });

    assert.deepEqual(ids, ['nm:a']);
  });

  test('passage 集合：member_ids 優先，再 passage_id，再 id，只留 ps:', () => {
    const walk = { walked: ['ps:w', 'ck:skip'] };
    const sources = [
      { id: 'rom.8', member_ids: ['ps:rom.8.1', 'ps:rom.8.18'], passage_id: 'ps:ignored' },
      { id: 'ck:jhn.4.1~jhn.4.20', member_ids: [], passage_id: 'ps:jhn.4.1' },
      { id: 'ps:only.id', member_ids: [] },
      { id: 'vs:jhn.3.16', member_ids: [] },
    ];

    assert.deepEqual(passageTargets(walk, sources), [
      'ps:w',
      'ps:rom.8.1',
      'ps:rom.8.18',
      'ps:jhn.4.1',
      'ps:only.id',
    ]);
  });

  test('events：每條 anchor 邊一筆，沒帶 edges 的不列', () => {
    const trace = [
      { op: 'event_registry', edges: [['ev1', 'anchor', 'ps:a'], ['ev2', 'anchor', 'ps:b']] },
      { op: 'event_registry', edges: [] },
      { op: 'event_registry' },
      { op: 'graph_walk', edges: [['x', 'anchor', 'ps:z']] },
    ];

    assert.deepEqual(eventAnchors(trace), [
      { id: 'ev1', passage: 'ps:a' },
      { id: 'ev2', passage: 'ps:b' },
    ]);
  });

  test('Neo4j 查不到名字的事件不列，UI 不會出現沒有名字的節點', async () => {
    const fixture = loadFixture('walk_event');
    const kg = { ...kgFromFixture(fixture), events: async () => [] };

    const result = await enrich(fixture.question, toBackendBody(fixture), {
      kg,
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.deepEqual(result.kg.events, []);
    assert.equal(result.kg.status, 'ok');
  });

  test('findWalk 容忍壞掉的 trace', () => {
    assert.equal(findWalk(null), null);
    assert.equal(findWalk([null, { op: 'kin_card' }]), null);
    assert.deepEqual(findWalk([{ op: 'graph_walk' }]), { op: 'graph_walk' });
  });
});

describe('enrich：輸出', () => {
  test('欄位只有 AskResponse，route 取自 route_used，開發者統計不外傳', async () => {
    const fixture = loadFixture('direct');

    const result = await enrich(fixture.question, toBackendBody(fixture), {
      kg: kgFromFixture(fixture),
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.deepEqual(Object.keys(result), Object.keys(fixture));
    assert.equal(result.route, 'R1');
    assert.equal('retrieval_stats' in result, false);
  });

  test('不改輸入物件', async () => {
    const fixture = loadFixture('walk_event');
    const body = deepFreeze(toBackendBody(fixture));

    const result = await enrich(fixture.question, body, {
      kg: kgFromFixture(fixture),
      healthBuildId: noHealth,
      log: silentLog(),
    });

    assert.equal(result.kg.status, 'ok');
  });

  test('缺欄位的 backend 回應：不當掉，當作沒走圖', async () => {
    const result = await enrich('問題', { answer: '答案' }, {
      kg: kgFromFixture(loadFixture('direct')),
      healthBuildId: async () => null,
      log: silentLog(),
    });

    assert.equal(result.answer, '答案');
    assert.equal(result.route, null);
    assert.deepEqual(result.sources, []);
    assert.deepEqual(result.graph_trace, []);
    assert.equal(result.kg.status, 'not_walked');
  });
});
