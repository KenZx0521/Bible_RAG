// 誠實性：圖上只畫圖譜真正走到的段落，說明的段數等於精簡圖的卡片數，說明文字沒有術語。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { extname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { buildViews } from '../public/js/graph-model.js';
import { prune } from '../public/js/prune.js';
import { FIXTURE_NAMES, deepFreeze, loadFixture } from './support/fixtures.mjs';

const PUBLIC_DIR = fileURLToPath(new URL('../public/', import.meta.url));
const FORBIDDEN_WORD = '語意搜尋';

function walkView(resp) {
  return buildViews(resp).views.find((view) => view.key === 'walk');
}

function emptyKg(status, reason = null) {
  return { status, reason, names: [], passages: [], mentions: [], events: [] };
}

function respWith(overrides) {
  return { question: 'q', answer: 'a', route: 'R4', sources: [], aux_card: null, graph_trace: [], ...overrides };
}

const WALK_OP = { op: 'graph_walk', walked: ['ps:a'], passages: [], confirmed: [], names: [], nodes: [], seeds: [], skip_reason: null };

function passage(id, walked, title = id) {
  return { id, title, book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked };
}

function source(id) {
  return { id, passage_id: id, member_ids: [], start_key: 'rom.8.1', end_key: 'rom.8.2' };
}

function name(id, label, inQuestion = false) {
  return { id, label, df: 1, idf: 5, in_question: inQuestion };
}

// 不經過 graph-model，直接從原始回應算：這樣才驗得出 graph-model 算錯
function usedIdsOf(resp) {
  return new Set(resp.sources.flatMap((item) => {
    const members = item.member_ids ?? [];
    return (members.length > 0 ? members : [item.passage_id || item.id]).filter((id) => id.startsWith('ps:'));
  }));
}

function walkedAndUsed(resp) {
  const used = usedIdsOf(resp);
  return resp.kg.passages.filter((item) => item.walked && used.has(item.id)).map((item) => item.id).sort();
}

const EXPECTED = {
  walk_event: { walkedUsed: 4, anchorOnly: 1, offGraph: 1 },
  walk_plain: { walkedUsed: 3, anchorOnly: 0, offGraph: 2 },
  kin: { walkedUsed: 1, anchorOnly: 0, offGraph: 3 },
  regnal: { walkedUsed: 2, anchorOnly: 0, offGraph: 3 },
};

for (const fixtureName of FIXTURE_NAMES) {
  test(`硬性檢查 ${fixtureName}：說明的段數＝精簡圖上走到且用到的卡片數`, () => {
    const resp = loadFixture(fixtureName);
    const walk = walkView(resp);
    if (fixtureName === 'direct') {
      assert.equal(walk, undefined, '沒走圖就沒有走圖檢視');
      return;
    }
    const pruned = prune(walk.graph);
    const cards = pruned.nodes.filter((node) => node.kind === 'passage' && node.walked && node.used).map((node) => node.id).sort();
    assert.deepEqual(cards, walkedAndUsed(resp));
    assert.equal(cards.length, EXPECTED[fixtureName].walkedUsed);
    const counted = /答案參考的 (\d+) 段經文/.exec(walk.caption);
    if (counted) assert.equal(Number(counted[1]), cards.length, walk.caption);
    for (const node of walk.graph.nodes.filter((item) => item.brought)) {
      assert.ok(walk.caption.includes(`「${node.label}」`), `${node.label} 要寫進說明`);
      assert.ok(pruned.nodes.some((item) => item.id === node.id), `${node.label} 要留在精簡圖`);
    }
  });

  test(`${fixtureName}：精簡圖的段落＝走到且用到，加上事件對應的段落`, () => {
    const resp = loadFixture(fixtureName);
    const walk = walkView(resp);
    if (!walk) return;
    const anchored = new Set(resp.kg.events.map((event) => event.passage));
    const expected = new Set([...walkedAndUsed(resp), ...anchored]);
    const drawn = prune(walk.graph).nodes.filter((node) => node.kind === 'passage').map((node) => node.id);
    assert.deepEqual([...drawn].sort(), [...expected].sort());
    assert.equal(drawn.filter((id) => !walkedAndUsed(resp).includes(id)).length, EXPECTED[fixtureName].anchorOnly);
  });

  test(`${fixtureName}：完整圖也不畫沒走到又沒有事件的段落`, () => {
    const resp = loadFixture(fixtureName);
    const walk = walkView(resp);
    if (!walk) return;
    const anchored = new Set(resp.kg.events.map((event) => event.passage));
    const expected = resp.kg.passages.filter((item) => item.walked || anchored.has(item.id)).map((item) => item.id);
    assert.deepEqual(walk.graph.nodes.filter((node) => node.kind === 'passage').map((node) => node.id), expected);
  });

  test(`${fixtureName}：offGraph＝用到但不在圖上的段落數`, () => {
    const resp = loadFixture(fixtureName);
    const walk = walkView(resp);
    if (!walk) return;
    const onGraph = new Set(walk.graph.nodes.map((node) => node.id));
    const expected = [...usedIdsOf(resp)].filter((id) => !onGraph.has(id)).length;
    assert.equal(walk.offGraph, expected);
    assert.equal(walk.offGraph, EXPECTED[fixtureName].offGraph);
  });
}

test('passageNode 帶上 walked', () => {
  const { graph } = walkView(loadFixture('walk_event'));
  const flag = (label) => graph.nodes.find((node) => node.label === label).walked;
  assert.equal(flag('安提阿的教會'), true);
  assert.equal(flag('巴拿巴和掃羅奉差遣'), false);
});

test('沒走到但有事件的段落：只有 anchor 那條邊，mentions 不畫', () => {
  const { graph } = walkView(loadFixture('walk_event'));
  const edges = graph.edges.filter((edge) => edge.from === 'ps:act.13.1' || edge.to === 'ps:act.13.1');
  assert.deepEqual(edges, [{ from: 'ev0009', to: 'ps:act.13.1', type: 'anchor' }]);
});

test('沒走到也沒有事件的段落：完全不進圖，它的邊也不在', () => {
  const { graph } = walkView(loadFixture('walk_event'));
  assert.equal(graph.nodes.some((node) => node.label === '掃羅在耶路撒冷'), false);
  assert.equal(graph.edges.some((edge) => edge.from === 'ps:act.9.26' || edge.to === 'ps:act.9.26'), false);
});

test('只連到沒走到段落的名字不畫，不留懸空的圓', () => {
  const kg = {
    ...emptyKg('ok'),
    names: [name('nm:on', '甲'), name('nm:off', '乙')],
    passages: [passage('ps:a', true), passage('ps:b', false)],
    mentions: [['ps:a', 'nm:on'], ['ps:b', 'nm:off']],
  };
  const { graph } = walkView(respWith({ kg, sources: [source('ps:a')], graph_trace: [WALK_OP] }));
  assert.deepEqual(graph.nodes.map((node) => node.id), ['ps:a', 'nm:on']);
  assert.deepEqual(graph.edges, [{ from: 'ps:a', to: 'nm:on', type: 'mentions' }]);
});

test('問題裡的名字就算沒有線連到走到的段落，說明還是從它出發', () => {
  const kg = {
    ...emptyKg('ok'),
    names: [name('nm:q', '問的人', true), name('nm:on', '甲')],
    passages: [passage('ps:a', true, '帶進來的')],
    mentions: [['ps:a', 'nm:on']],
  };
  const op = { ...WALK_OP, passages: ['ps:a'] };
  const walk = walkView(respWith({ kg, sources: [source('ps:a')], graph_trace: [op] }));
  assert.match(walk.caption, /^知識圖譜從問題裡的「問的人」出發/);
  assert.equal(walk.graph.nodes.some((node) => node.id === 'nm:q'), false);
});

// ---- 說明文字 ----

test('有帶進來：照規定的口語句子，列出問題裡的名字', () => {
  assert.equal(
    walkView(loadFixture('walk_event')).caption,
    '知識圖譜從問題裡的「巴拿巴」「保羅」出發，順著經文共同提到的人名地名往外找；「安提阿的教會」單看問題的字句找不到，是這樣連過去才找到的。',
  );
});

test('有帶進來但沒有問題裡的名字：改從最接近問題的經文出發；多段都列', () => {
  const kg = {
    ...emptyKg('ok'),
    names: [name('nm:on', '甲')],
    passages: [passage('ps:a', true, '甲段'), passage('ps:b', true, '乙段')],
    mentions: [['ps:a', 'nm:on'], ['ps:b', 'nm:on']],
  };
  const op = { ...WALK_OP, walked: ['ps:a', 'ps:b'], passages: ['ps:a', 'ps:b'] };
  const walk = walkView(respWith({ kg, sources: [source('ps:a'), source('ps:b')], graph_trace: [op] }));
  assert.equal(
    walk.caption,
    '知識圖譜從最接近問題的經文出發，順著經文共同提到的人名地名往外找；「甲段」「乙段」單看問題的字句找不到，是這樣連過去才找到的。',
  );
});

test('只有確認：寫段數，說這題沒有多找到新段落', () => {
  assert.equal(walkView(loadFixture('walk_plain')).caption, '知識圖譜順著人名地名，也連到答案參考的 3 段經文；這題沒有多找到新段落。');
  assert.equal(walkView(loadFixture('kin')).caption, '知識圖譜順著人名地名，也連到答案參考的 1 段經文；這題沒有多找到新段落。');
});

test('走了但沒用到：照實說', () => {
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true)] };
  assert.equal(walkView(respWith({ kg, graph_trace: [WALK_OP] })).caption, '知識圖譜有走，但連到的段落沒有用在答案裡。');
});

test('沒圖的說明不提術語，改說直接比對', () => {
  const skipped = { ...WALK_OP, skip_reason: 'timeout' };
  assert.equal(
    buildViews(respWith({ kg: emptyKg('walk_skipped', 'timeout'), graph_trace: [skipped] })).note,
    '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。',
  );
  assert.equal(buildViews(respWith({ kg: emptyKg('unavailable') })).note, '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。');
});

test('畫面上任何地方都不出現「語意搜尋」：資料產生的文字', () => {
  for (const fixtureName of FIXTURE_NAMES) {
    const built = buildViews(loadFixture(fixtureName));
    const texts = [built.note ?? '', ...built.views.flatMap((view) => [view.caption, view.offGraphNote ?? '', view.title])];
    for (const text of texts) assert.equal(text.includes(FORBIDDEN_WORD), false, `${fixtureName}: ${text}`);
  }
});

test('畫面上任何地方都不出現「語意搜尋」：前端原始碼（含註解）', () => {
  const files = readdirSync(PUBLIC_DIR, { recursive: true }).filter((file) => ['.js', '.html', '.css'].includes(extname(file)));
  assert.ok(files.length > 10, '要真的掃到檔案');
  for (const file of files) {
    assert.equal(readFileSync(join(PUBLIC_DIR, file), 'utf8').includes(FORBIDDEN_WORD), false, file);
  }
});

// ---- 不在圖上的段落 ----

test('offGraph 的句子：大於 0 才有，寫法照規定', () => {
  assert.equal(walkView(loadFixture('walk_event')).offGraphNote, '另有 1 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。');
  assert.equal(walkView(loadFixture('walk_plain')).offGraphNote, '另有 2 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。');
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true)] };
  const walk = walkView(respWith({ kg, sources: [source('ps:a')], graph_trace: [WALK_OP] }));
  assert.equal(walk.offGraph, 0);
  assert.equal(walk.offGraphNote, undefined);
});

test('親屬關係帶來的段落不是直接比對找到的，句子要分開講，offGraph 總數不變', () => {
  const walk = walkView(loadFixture('kin'));
  assert.equal(walk.offGraph, 3);
  assert.equal(walk.offGraphNote, '另有 1 段是直接比對問題找到的，沒有經過圖譜；2 段是親屬關係的出處。都列在經文來源。');
});

test('不在圖上的全是親屬關係的出處：不提直接比對', () => {
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true), passage('ps:b', false)] };
  const sources = [source('ps:a'), { ...source('ps:b'), found_by: ['kin_evidence'] }];
  const walk = walkView(respWith({ kg, sources, graph_trace: [WALK_OP] }));
  assert.equal(walk.offGraph, 1);
  assert.equal(walk.offGraphNote, '另有 1 段是親屬關係的出處，列在經文來源。');
});

test('同一段也被直接比對找到：算直接比對', () => {
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true), passage('ps:b', false)] };
  const sources = [source('ps:a'), { ...source('ps:b'), found_by: ['hybrid_hybrid', 'kin_evidence'] }];
  assert.equal(walkView(respWith({ kg, sources, graph_trace: [WALK_OP] })).offGraphNote, '另有 1 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。');
});

test('op 說走到、但 Neo4j 沒回這段：不能算成「直接比對找到的」', () => {
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true)] };
  const op = { ...WALK_OP, walked: ['ps:a', 'ps:lost'] };
  const walk = walkView(respWith({ kg, sources: [source('ps:a'), source('ps:lost')], graph_trace: [op] }));
  assert.equal(walk.offGraph, 0);
  assert.equal(walk.offGraphNote, undefined);
});

test('來源沒有對應段落（不是 ps: 開頭）：不算段落，也不當掉', () => {
  const kg = { ...emptyKg('ok'), passages: [passage('ps:a', true)] };
  const sources = [source('ps:a'), { id: 'mrk.1', passage_id: null, member_ids: [] }];
  assert.equal(walkView(respWith({ kg, sources, graph_trace: [WALK_OP] })).offGraph, 0);
});

test('不改輸入', () => {
  for (const fixtureName of FIXTURE_NAMES) {
    const resp = deepFreeze(loadFixture(fixtureName));
    assert.deepEqual(buildViews(resp), buildViews(resp));
  }
});
