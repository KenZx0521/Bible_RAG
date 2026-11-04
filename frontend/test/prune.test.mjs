import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_EDGES, MAX_NAMES, MAX_NAME_PER_PASSAGE, MAX_NODES, prune } from '../public/js/prune.js';
import { buildViews } from '../public/js/graph-model.js';
import { deepFreeze, loadFixture } from './support/fixtures.mjs';
import { PADDING, assertGuarantees, assertVitalNodesKept, degreeOf, keptIds, labels, mention, name, passage, walkGraph } from './support/prune-helpers.mjs';

function viewGraph(fixture, key) {
  return buildViews(loadFixture(fixture)).views.find((view) => view.key === key).graph;
}

const WALK_GRAPHS = {
  walk_event: () => viewGraph('walk_event', 'walk'),
  walk_plain: () => viewGraph('walk_plain', 'walk'),
  'kin 的走圖': () => viewGraph('kin', 'walk'),
  'regnal 的走圖': () => viewGraph('regnal', 'walk'),
};

for (const [name, load] of Object.entries(WALK_GRAPHS)) {
  test(`真實資料 ${name}：硬性保證與上限`, (t) => {
    const input = deepFreeze(load());
    const result = prune(input);
    t.diagnostic(`${name} 剪前 ${input.nodes.length} 節點／${input.edges.length} 邊 → 剪後 ${result.nodes.length} 節點／${result.edges.length} 邊`
      + `（藏 ${result.hidden.names} 名字、${result.hidden.passages} 段、${result.hidden.edges} 邊）`);
    t.diagnostic(`  段落：${labels(result, 'passage').join('、')}`);
    t.diagnostic(`  名字：${labels(result, 'name').join('、')}`);
    t.diagnostic(`  事件：${labels(result, 'event').join('、') || '（無）'}`);
    assert.equal(result.pruned, true);
    assert.ok(result.nodes.length <= MAX_NODES, `節點 ${result.nodes.length}`);
    assert.ok(result.edges.length <= MAX_EDGES, `邊 ${result.edges.length}`);
    assertGuarantees(input, result);
    assertVitalNodesKept(input, result);
    assert.ok(result.nodes.filter((n) => n.kind === 'name').length <= MAX_NAMES);
    assert.deepEqual(prune(input), result, '同輸入同輸出');
  });

  test(`真實資料 ${name}：只留答案參考的段落，走到沒用的全藏`, () => {
    const result = prune(load());
    for (const node of result.nodes.filter((item) => item.kind === 'passage')) assert.equal(node.used, true, node.label);
  });

  test(`真實資料 ${name}：每段最多 ${MAX_NAME_PER_PASSAGE} 個名字`, () => {
    const result = prune(load());
    const byPassage = new Map();
    for (const edge of result.edges.filter((item) => item.type === 'mentions')) {
      byPassage.set(edge.from, (byPassage.get(edge.from) ?? 0) + 1);
    }
    for (const [id, count] of byPassage) assert.ok(count <= MAX_NAME_PER_PASSAGE, `${id}: ${count}`);
  });

  test(`真實資料 ${name}：留下的非問題名字至少串起兩段`, () => {
    const result = prune(load());
    for (const node of result.nodes.filter((item) => item.kind === 'name' && !item.inQuestion)) {
      assert.ok(degreeOf(result.edges, node.id) >= 2, node.label);
    }
  });

  test(`真實資料 ${name}：回傳新物件，不與輸入共用`, () => {
    const input = load();
    const result = prune(input);
    const original = new Map(input.nodes.map((node) => [node.id, node]));
    for (const node of result.nodes) assert.notEqual(node, original.get(node.id));
    assert.deepEqual(input, load(), '輸入沒被改');
  });
}

test('walk_event：巴拿巴、保羅、安提阿的教會、事件都留著', () => {
  const result = prune(viewGraph('walk_event', 'walk'));
  assert.ok(labels(result, 'name').includes('巴拿巴'));
  assert.ok(labels(result, 'name').includes('保羅'));
  assert.ok(labels(result, 'passage').includes('安提阿的教會'));
  assert.deepEqual(labels(result, 'event'), ['第一次宣教旅程']);
  assert.ok(result.edges.some((edge) => edge.type === 'anchor' && edge.from === 'ev0009'));
});

test('walk_event：高頻 hub「猶太」被壓低，在「安提阿的教會」讓位給罕見的「腓尼基」', () => {
  const input = viewGraph('walk_event', 'walk');
  const idOf = (label) => input.nodes.find((node) => node.label === label).id;
  const linkedToChurch = (edges, label) => edges.some((edge) => edge.from === 'ps:act.11.19' && edge.to === idOf(label));
  assert.ok(linkedToChurch(input.edges, '猶太'), '輸入確實有這條邊');
  // 圖上只剩走到的段落後，這段預設剛好放得下 4 條，所以把上限收緊到會真的擠掉
  const result = prune(input, { maxNamePerPassage: 3 });
  assert.equal(linkedToChurch(result.edges, '猶太'), false);
  assert.equal(linkedToChurch(result.edges, '腓尼基'), true);
});

test('regnal 走圖：帶進來的「以色列王亞哈」留著', () => {
  assert.ok(labels(prune(viewGraph('regnal', 'walk')), 'passage').includes('以色列王亞哈'));
});

test('親屬圖不被剪：原樣保留', () => {
  const input = deepFreeze(viewGraph('kin', 'kin'));
  const result = prune(input);
  assert.equal(result.pruned, false);
  assert.deepEqual(result.nodes, input.nodes);
  assert.deepEqual(result.edges, input.edges);
  assert.deepEqual(result.hidden, { names: 0, passages: 0, edges: 0 });
});

test('小圖不剪；空圖不當掉；不剪時也回傳新物件', () => {
  const small = {
    nodes: [
      { id: 'ps:a', kind: 'passage', label: 'A', used: true, brought: false },
      { id: 'nm:a', kind: 'name', label: '甲', inQuestion: false, df: 1, idf: 1 },
    ],
    edges: [{ from: 'ps:a', to: 'nm:a', type: 'mentions' }],
  };
  const result = prune(small);
  assert.equal(result.pruned, false);
  assert.deepEqual(result.nodes, small.nodes);
  assert.notEqual(result.nodes[0], small.nodes[0]);
  assert.notEqual(result.edges[0], small.edges[0]);
  assert.deepEqual(prune({ nodes: [], edges: [] }), {
    nodes: [], edges: [], hidden: { names: 0, passages: 0, edges: 0 }, pruned: false,
  });
});

test('上限判斷：剛好 14 節點 24 邊不剪；多一個就剪', () => {
  const nodes = Array.from({ length: MAX_NODES }, (_, i) => ({ id: `ps:${i}`, kind: 'passage', label: `${i}`, used: true, brought: false }));
  assert.equal(prune({ nodes, edges: [] }).pruned, false);
  const more = [...nodes, { id: 'ps:x', kind: 'passage', label: 'x', used: false, brought: false }];
  assert.equal(prune({ nodes: more, edges: [] }).pruned, true);
});

// ---- 合成圖：釘住每一步規則 ----

test('第 1 步：走到但沒進答案的段落全藏', () => {
  const result = prune(walkGraph(
    [passage('ps:u'), passage('ps:n', false), name('nm:q', 5, true)],
    [mention('ps:u', 'nm:q'), mention('ps:n', 'nm:q')],
  ));
  assert.deepEqual(keptIds(result), ['ps:u', 'nm:q']);
  assert.equal(result.hidden.passages, PADDING.length + 1);
  assert.equal(result.hidden.edges, 1);
});

test('第 2–3 步：d=1 的非問題名字是葉子要藏；問題名字 d=1 留著；d 只算留下的段落', () => {
  const graph = walkGraph(
    [passage('ps:a'), passage('ps:b'), passage('ps:n', false),
      name('nm:leaf', 8), name('nm:leaf2', 8), name('nm:q', 1, true), name('nm:bridge', 3)],
    [mention('ps:a', 'nm:leaf'), mention('ps:a', 'nm:q'), mention('ps:a', 'nm:bridge'),
      mention('ps:b', 'nm:bridge'), mention('ps:a', 'nm:leaf2'), mention('ps:n', 'nm:leaf2')],
  );
  const result = prune(graph);
  assert.deepEqual(keptIds(result), ['ps:a', 'ps:b', 'nm:q', 'nm:bridge']);
  assertGuarantees(graph, result);
  assertVitalNodesKept(graph, result);
});

test('問題名字沒有連到任何留下的段落才藏', () => {
  const graph = walkGraph(
    [passage('ps:a'), passage('ps:n', false), name('nm:q', 5, true), name('nm:lost', 5, true)],
    [mention('ps:a', 'nm:q'), mention('ps:n', 'nm:lost')],
  );
  const result = prune(graph);
  assert.deepEqual(keptIds(result), ['ps:a', 'nm:q']);
  assertVitalNodesKept(graph, result);
});

test('第 4 步：分數 d×idf，高頻 hub 被壓低；同分依 id；最多 MAX_NAMES', () => {
  // 兩段都連到：hub idf 1、其餘 idf 由高到低；只取前 MAX_NAMES（每段上限放大以免干擾）
  const rare = Array.from({ length: MAX_NAMES + 2 }, (_, i) => name(`nm:r${i}`, 10 - i * 0.1));
  const nodes = [passage('ps:a'), passage('ps:b'), name('nm:hub', 1), ...rare];
  const edges = nodes.filter((node) => node.kind === 'name')
    .flatMap((node) => [mention('ps:a', node.id), mention('ps:b', node.id)]);
  const result = prune(walkGraph(nodes, edges), { maxNamePerPassage: 100, maxEdges: 1000 });
  const kept = labels(result, 'name');
  assert.equal(kept.length, MAX_NAMES);
  assert.ok(!kept.includes('nm:hub'), '高頻 hub 分數最低');
  assert.deepEqual(kept, rare.slice(0, MAX_NAMES).map((node) => node.id));
  const tie = [passage('ps:a'), passage('ps:b'), name('nm:b', 5), name('nm:a', 5)];
  const tieEdges = tie.slice(2).flatMap((node) => [mention('ps:a', node.id), mention('ps:b', node.id)]);
  const tied = prune(walkGraph(tie, tieEdges), { maxNames: 1 });
  assert.deepEqual(labels(tied, 'name'), ['nm:a']);
});

test('第 4 步：問題名字優先且不受 MAX_NAMES 截斷', () => {
  const asked = Array.from({ length: MAX_NAMES + 1 }, (_, i) => name(`nm:q${i}`, 1, true));
  const nodes = [...asked, name('nm:rare', 9)];
  const passages = asked.map((_, i) => passage(`ps:${i}`));
  const edges = asked.flatMap((node, i) => [mention(`ps:${i}`, node.id)])
    .concat([mention('ps:0', 'nm:rare'), mention('ps:1', 'nm:rare')]);
  const graph = walkGraph([...passages, ...nodes], edges);
  const result = prune(graph);
  assert.deepEqual(labels(result, 'name'), asked.map((node) => node.id));
  assertVitalNodesKept(graph, result);
});

test('第 5 步：每段最多 4 條，問題名字優先，再依分數；度數掉到 <2 的再藏，迭代到穩定', () => {
  const others = ['nm:1', 'nm:2', 'nm:3', 'nm:4'].map((id, i) => name(id, 9 - i));
  const nodes = [passage('ps:a'), passage('ps:b'), name('nm:q', 1, true), ...others];
  // ps:b 只連到分數最低的 nm:4；ps:a 滿了以後 nm:4 被擠掉只剩一條邊 → 藏，ps:b 跟著沒邊
  const edges = [
    mention('ps:a', 'nm:q'), ...others.map((node) => mention('ps:a', node.id)),
    mention('ps:b', 'nm:4'),
    mention('ps:c', 'nm:1'), mention('ps:c', 'nm:2'), mention('ps:c', 'nm:3'),
  ];
  const graph = walkGraph([...nodes, passage('ps:c')], edges);
  const result = prune(graph);
  assert.deepEqual(labels(result, 'name'), ['nm:q', 'nm:1', 'nm:2', 'nm:3']);
  assert.deepEqual(labels(result, 'passage'), ['ps:a', 'ps:c']);
  assert.equal(result.edges.filter((edge) => edge.from === 'ps:a').length, MAX_NAME_PER_PASSAGE);
  assertGuarantees(graph, result);
  assertVitalNodesKept(graph, result);
});

test('第 5 步：被上限擠掉的邊，在別的名字藏掉後要補回來（段落不會還有連線卻被藏）', () => {
  // 每段上限 2：A、B 在 Q 被 X、Y 擠掉只剩一條邊要藏；騰出 P 的位子後 C 補上，P 與 S 才不會落單
  const nodes = [passage('ps:P'), passage('ps:Q'), passage('ps:R'), passage('ps:S'),
    name('nm:X', 9), name('nm:Y', 8), name('nm:A', 7), name('nm:B', 6), name('nm:C', 5)];
  const edges = [
    mention('ps:Q', 'nm:X'), mention('ps:Q', 'nm:Y'), mention('ps:Q', 'nm:A'), mention('ps:Q', 'nm:B'),
    mention('ps:R', 'nm:X'), mention('ps:R', 'nm:Y'),
    mention('ps:P', 'nm:A'), mention('ps:P', 'nm:B'), mention('ps:P', 'nm:C'),
    mention('ps:S', 'nm:C'),
  ];
  const graph = walkGraph(nodes, edges);
  const result = prune(graph, { maxNamePerPassage: 2 });
  assert.deepEqual(labels(result, 'name'), ['nm:X', 'nm:Y', 'nm:C']);
  assert.deepEqual(labels(result, 'passage'), ['ps:P', 'ps:Q', 'ps:R', 'ps:S']);
  assertGuarantees(graph, result);
  assertVitalNodesKept(graph, result);
});

test('問題名字超過每段上限時邊不被砍（保證優先於上限）', () => {
  const asked = Array.from({ length: MAX_NAME_PER_PASSAGE + 1 }, (_, i) => name(`nm:q${i}`, 1, true));
  const graph = walkGraph([passage('ps:a'), ...asked], asked.map((node) => mention('ps:a', node.id)));
  const result = prune(graph);
  assert.equal(labels(result, 'name').length, asked.length);
  assertVitalNodesKept(graph, result);
});

test('第 6 步：事件與 anchor 邊一律保留，而且算段落的連線', () => {
  const event = { id: 'ev1', kind: 'event', label: '事件' };
  const graph = walkGraph(
    [passage('ps:a'), event],
    [{ from: 'ev1', to: 'ps:a', type: 'anchor' }],
  );
  const result = prune(graph);
  assert.deepEqual(keptIds(result), ['ps:a', 'ev1']);
  assert.equal(result.edges.length, 1);
  assertGuarantees(graph, result);
});

test('第 6 步：anchor 的段落就算沒用到也留著，事件不會落單', () => {
  const event = { id: 'ev1', kind: 'event', label: '事件' };
  const graph = walkGraph(
    [passage('ps:n', false), event],
    [{ from: 'ev1', to: 'ps:n', type: 'anchor' }],
  );
  const result = prune(graph);
  assert.deepEqual(keptIds(result), ['ps:n', 'ev1']);
  assert.equal(result.edges.length, 1);
  assertGuarantees(graph, result);
});

test('第 7 步：沒有任何邊的 used 段落不畫，計入 hidden.passages', () => {
  const graph = walkGraph(
    [passage('ps:a'), passage('ps:lonely'), name('nm:q', 5, true)],
    [mention('ps:a', 'nm:q')],
  );
  const result = prune(graph);
  assert.deepEqual(labels(result, 'passage'), ['ps:a']);
  assert.equal(result.hidden.passages, PADDING.length + 1);
  assertVitalNodesKept(graph, result);
});

test('超過上限時先藏不會讓段落落單的名字；問題名字不動', () => {
  // 6 段＋8 名字＋事件＝15 節點：要再藏一個名字。分數最低的 nm:low 是 ps:f 唯一的連線，不能先藏它
  const passages = ['a', 'b', 'c', 'd', 'e', 'f'].map((id) => passage(`ps:${id}`));
  const fillers = ['1', '2', '3', '4', '5', '6'].map((id, i) => name(`nm:${id}`, 8 - i * 0.1));
  const low = name('nm:low', 0.1);
  const asked = name('nm:q', 0.1, true);
  const event = { id: 'ev1', kind: 'event', label: '事件' };
  const edges = [
    ...['a', 'b', 'c', 'd', 'e'].map((id) => mention(`ps:${id}`, 'nm:q')),
    ...fillers.flatMap((node, i) => [mention('ps:a', node.id), mention(`ps:${'bcde'[i % 4]}`, node.id)]),
    mention('ps:b', 'nm:low'), mention('ps:f', 'nm:low'),
    { from: 'ev1', to: 'ps:a', type: 'anchor' },
  ];
  const graph = walkGraph([...passages, ...fillers, low, asked, event], edges);
  const result = prune(graph);
  assert.ok(result.nodes.length <= MAX_NODES, `節點 ${result.nodes.length}`);
  assert.ok(labels(result, 'name').includes('nm:q'));
  assert.ok(labels(result, 'passage').includes('ps:f'), 'ps:f 不該因為預算落單');
  assertGuarantees(graph, result);
  assertVitalNodesKept(graph, result);
});

test('全部都是會落單的名字時，還是藏分數最低的以守住上限', () => {
  // 每個名字都是某段唯一的連線
  const pairs = Array.from({ length: 9 }, (_, i) => i);
  const passages = pairs.map((i) => passage(`ps:${i}`));
  const names = pairs.map((i) => name(`nm:${i}`, 9 - i));
  const edges = pairs.flatMap((i) => [mention(`ps:${i}`, `nm:${i}`), mention(`ps:${(i + 1) % 9}`, `nm:${i}`)]);
  const graph = walkGraph([...passages, ...names], edges);
  const result = prune(graph, { maxNodes: 12, maxNames: 9 });
  assert.ok(result.nodes.length <= 12, `節點 ${result.nodes.length}`);
  assertGuarantees(graph, result);
  assertVitalNodesKept(graph, result);
});

test('上限數字可由 opts 覆寫', () => {
  const graph = viewGraph('walk_event', 'walk');
  const result = prune(graph, { maxNames: 3 });
  assert.ok(labels(result, 'name').length <= 3);
  assertGuarantees(graph, result);
  const unused = new Set(graph.nodes.filter((node) => node.kind === 'passage' && !node.used).map((node) => node.id));
  const onlyUsed = {
    nodes: graph.nodes.filter((node) => !unused.has(node.id)),
    edges: graph.edges.filter((edge) => !unused.has(edge.from) && !unused.has(edge.to)),
  };
  const loose = prune(onlyUsed, { maxNodes: 1000, maxEdges: 1000 });
  assert.equal(loose.pruned, false);
  assert.equal(loose.nodes.length, onlyUsed.nodes.length);
});

test('邊的方向不影響結果（名字在前也認得）', () => {
  const graph = walkGraph(
    [passage('ps:a'), name('nm:q', 5, true)],
    [{ from: 'nm:q', to: 'ps:a', type: 'mentions' }],
  );
  assert.deepEqual(keptIds(prune(graph)), ['ps:a', 'nm:q']);
});

test('懸空的輸入邊不會出現在輸出', () => {
  const graph = walkGraph(
    [passage('ps:a'), name('nm:q', 5, true)],
    [mention('ps:a', 'nm:q'), mention('ps:gone', 'nm:q'), mention('ps:a', 'nm:gone')],
  );
  const result = prune(graph);
  assert.equal(result.edges.length, 1);
  assertGuarantees(graph, result);
});
