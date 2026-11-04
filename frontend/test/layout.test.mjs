import { test } from 'node:test';
import assert from 'node:assert/strict';
import { countCrossings, layout } from '../public/js/layout.js';
import { prune } from '../public/js/prune.js';
import { buildViews } from '../public/js/graph-model.js';
import { FIXTURE_NAMES, deepFreeze, loadFixture } from './support/fixtures.mjs';

const WIDTHS = [320, 480, 720];

/** 五份 fixture 的所有圖：每個有圖的 view 各取完整圖與剪枝後。direct 沒有圖，用空圖代表。 */
function allGraphs() {
  return FIXTURE_NAMES.flatMap((name) => {
    const graphs = buildViews(loadFixture(name)).views.filter((view) => view.graph);
    if (graphs.length === 0) return [{ title: `${name} 空圖`, graph: { nodes: [], edges: [] } }];
    return graphs.flatMap((view) => [
      { title: `${name}/${view.key} 完整`, graph: view.graph },
      { title: `${name}/${view.key} 剪枝`, graph: pickGraph(prune(view.graph)) },
    ]);
  });
}

function pickGraph({ nodes, edges }) {
  return { nodes, edges };
}

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function assertSound(graph, result, width) {
  assert.equal(result.width, width);
  assert.equal(result.nodes.length, graph.nodes.length);
  assert.deepEqual(new Set(result.nodes.map((node) => node.id)), new Set(graph.nodes.map((node) => node.id)));
  for (const box of result.nodes) {
    assert.ok(box.x >= 0, `${box.id} x=${box.x}`);
    assert.ok(box.y >= 0, `${box.id} y=${box.y}`);
    assert.ok(box.x + box.w <= width, `${box.id} 超出寬度 ${box.x + box.w} > ${width}`);
    assert.ok(box.y + box.h <= result.height, `${box.id} 超出高度`);
    assert.ok(box.w > 0 && box.h > 0);
    for (const value of [box.x, box.y, box.w, box.h]) assert.ok(Number.isFinite(value));
  }
  for (let i = 0; i < result.nodes.length; i += 1) {
    for (let j = i + 1; j < result.nodes.length; j += 1) {
      assert.equal(overlaps(result.nodes[i], result.nodes[j]), false, `${result.nodes[i].id} 與 ${result.nodes[j].id} 重疊`);
    }
  }
  const ids = new Set(result.nodes.map((node) => node.id));
  assert.equal(result.edges.length, graph.edges.length);
  for (const edge of result.edges) {
    assert.ok(ids.has(edge.from) && ids.has(edge.to), `懸空邊 ${edge.from}→${edge.to}`);
    assert.match(edge.path, /^M[-\d., ]+C[-\d., ]+$/, edge.path);
    assert.ok(!edge.path.includes('NaN'));
    assert.ok(Number.isFinite(edge.mid.x) && Number.isFinite(edge.mid.y));
  }
}

for (const { title, graph } of allGraphs()) {
  for (const width of WIDTHS) {
    test(`${title}＠${width}：不重疊、不超寬、邊的兩端都在`, () => {
      assertSound(graph, layout(deepFreeze(graph), { width }), width);
    });

    test(`${title}＠${width}：結果決定性`, () => {
      assert.deepEqual(layout(graph, { width }), layout(graph, { width }));
    });

    test(`${title}＠${width}：barycenter 後交叉數不多於初始`, (t) => {
      const initial = countCrossings(layout(graph, { width, sweeps: 0 }));
      const final = countCrossings(layout(graph, { width }));
      t.diagnostic(`交叉 ${initial} → ${final}`);
      assert.ok(final <= initial, `${initial} → ${final}`);
    });
  }
}

test('走圖版面：段落分左右兩欄，名字與事件在中欄，三欄不相交', () => {
  const graph = pickGraph(prune(buildViews(loadFixture('walk_event')).views.find((v) => v.key === 'walk').graph));
  const result = layout(graph, { width: 720 });
  const boxOf = new Map(result.nodes.map((box) => [box.id, box]));
  const kinds = (kind) => graph.nodes.filter((node) => node.kind === kind).map((node) => boxOf.get(node.id));
  const sides = [...new Set(kinds('passage').map((box) => box.x))].sort((a, b) => a - b);
  assert.equal(sides.length, 2, '段落在左右兩欄');
  const middle = [...kinds('name'), ...kinds('event')];
  assert.equal(new Set(middle.map((box) => box.x)).size, 1, '名字與事件同一欄');
  const left = kinds('passage').find((box) => box.x === sides[0]);
  const right = kinds('passage').find((box) => box.x === sides[1]);
  assert.ok(left.x + left.w <= middle[0].x);
  assert.ok(middle[0].x + middle[0].w <= right.x);
});

test('走圖版面：段落依 sources 順序左右交替（初始）', () => {
  const graph = pickGraph(prune(buildViews(loadFixture('walk_event')).views.find((v) => v.key === 'walk').graph));
  const result = layout(graph, { width: 720, sweeps: 0 });
  const boxOf = new Map(result.nodes.map((box) => [box.id, box]));
  const bySource = graph.nodes.filter((node) => node.kind === 'passage').sort((a, b) => a.sourceIndex - b.sourceIndex);
  const xs = bySource.map((node) => boxOf.get(node.id).x);
  assert.ok(xs.every((x, i) => (i % 2 === 0 ? x === xs[0] : x === xs[1])));
  assert.notEqual(xs[0], xs[1]);
});

test('走圖版面：沒有 sourceIndex 的段落排在有的後面', () => {
  const graph = {
    nodes: [
      { id: 'ps:n', kind: 'passage', label: 'N', used: false, brought: false },
      { id: 'ps:b', kind: 'passage', label: 'B', used: true, brought: false, sourceIndex: 1 },
      { id: 'ps:a', kind: 'passage', label: 'A', used: true, brought: false, sourceIndex: 0 },
    ],
    edges: [],
  };
  const result = layout(graph, { width: 480, sweeps: 0 });
  const boxOf = new Map(result.nodes.map((box) => [box.id, box]));
  assert.equal(boxOf.get('ps:a').x, boxOf.get('ps:n').x);
  assert.ok(boxOf.get('ps:a').y < boxOf.get('ps:n').y);
  assert.notEqual(boxOf.get('ps:a').x, boxOf.get('ps:b').x);
});

test('barycenter 真的有在減少交叉（人造反序圖）', () => {
  const names = Array.from({ length: 5 }, (_, i) => ({ id: `nm:${i}`, kind: 'name', label: `${i}`, inQuestion: false, df: 1, idf: 1 }));
  const passages = Array.from({ length: 5 }, (_, i) => ({ id: `ps:${i}`, kind: 'passage', label: `${i}`, used: true, brought: false, sourceIndex: i * 2 }));
  const graph = {
    nodes: [...passages, ...names],
    edges: passages.map((p, i) => ({ from: p.id, to: `nm:${4 - i}`, type: 'mentions' })),
  };
  const initial = countCrossings(layout(graph, { width: 720, sweeps: 0 }));
  const final = countCrossings(layout(graph, { width: 720 }));
  assert.ok(initial > 0);
  assert.equal(final, 0);
});

test('窄版欄寬較窄，文字欄位仍有實際寬度', () => {
  const graph = pickGraph(prune(buildViews(loadFixture('walk_event')).views.find((v) => v.key === 'walk').graph));
  const narrow = layout(graph, { width: 320 });
  const wide = layout(graph, { width: 720 });
  const widest = (result) => Math.max(...result.nodes.map((box) => box.w));
  assert.ok(widest(narrow) < widest(wide));
  for (const box of narrow.nodes) assert.ok(box.w >= 56, `${box.id} 寬 ${box.w}`);
});

test('完整圖高度長大而不是把節點縮小', () => {
  const full = buildViews(loadFixture('walk_event')).views.find((v) => v.key === 'walk').graph;
  const pruned = pickGraph(prune(full));
  const big = layout(full, { width: 480 });
  const small = layout(pruned, { width: 480 });
  assert.ok(big.height > small.height);
  const nameHeight = (result, graph) => {
    const id = graph.nodes.find((node) => node.kind === 'name').id;
    return result.nodes.find((box) => box.id === id).h;
  };
  assert.equal(nameHeight(big, full), nameHeight(small, pruned));
});

test('帶進來的段落有多一點高度放小標，同欄仍不重疊', () => {
  const graph = {
    nodes: [
      { id: 'ps:a', kind: 'passage', label: 'A', used: true, brought: true, sourceIndex: 0 },
      { id: 'ps:b', kind: 'passage', label: 'B', used: true, brought: false, sourceIndex: 1 },
      { id: 'ps:c', kind: 'passage', label: 'C', used: true, brought: false, sourceIndex: 2 },
    ],
    edges: [],
  };
  const result = layout(graph, { width: 480 });
  const boxOf = new Map(result.nodes.map((box) => [box.id, box]));
  assert.ok(boxOf.get('ps:a').h > boxOf.get('ps:b').h);
  assertSound(graph, result, 480);
});

test('懸空的輸入邊不輸出；空圖不當掉；沒給寬度有預設值', () => {
  const graph = {
    nodes: [{ id: 'nm:a', kind: 'name', label: '甲', inQuestion: false, df: 1, idf: 1 }],
    edges: [{ from: 'nm:a', to: 'ps:gone', type: 'mentions' }],
  };
  assert.deepEqual(layout(graph, { width: 320 }).edges, []);
  const empty = layout({ nodes: [], edges: [] }, { width: 320 });
  assert.deepEqual([empty.nodes, empty.edges, empty.width, empty.height], [[], [], 320, 0]);
  assert.ok(layout(graph).width > 0);
});

test('非常窄也不超出（比最小欄寬還小）', () => {
  const graph = pickGraph(prune(buildViews(loadFixture('walk_event')).views.find((v) => v.key === 'walk').graph));
  for (const width of [200, 240, 280]) {
    const result = layout(graph, { width });
    for (const box of result.nodes) assert.ok(box.x + box.w <= width);
  }
  const kin = buildViews(loadFixture('kin')).views.find((v) => v.key === 'kin').graph;
  for (const width of [60, 120, 200]) {
    const result = layout(kin, { width });
    for (const box of result.nodes) assert.ok(box.x + box.w <= width, `${box.x}+${box.w} > ${width}`);
  }
});

// ---- 親屬圖 ----

function person(id, focus = false) {
  return { id, kind: 'person', label: id, focus };
}

function kinEdge(from, to, type = 'PARENT_OF') {
  return { from, to, type, verseKey: 'rut.4.17', ref: '路得記 4:17' };
}

function yOf(result, id) {
  return result.nodes.find((box) => box.id === id).y;
}

test('kin 真實資料：世代由上而下，父母在上', () => {
  const graph = buildViews(loadFixture('kin')).views.find((v) => v.key === 'kin').graph;
  for (const width of WIDTHS) {
    const result = layout(graph, { width });
    for (const edge of graph.edges) {
      assert.ok(yOf(result, edge.from) < yOf(result, edge.to), `${edge.from} 應該在 ${edge.to} 上面`);
    }
    // 波阿斯與路得都是俄備得的父母，同一層
    assert.equal(yOf(result, 'e000431'), yOf(result, 'e001772'));
  }
});

test('kin：配偶、手足同層；每層置中', () => {
  const graph = {
    nodes: [person('a', true), person('b'), person('c'), person('d')],
    edges: [kinEdge('a', 'b', 'SPOUSE_OF'), kinEdge('a', 'c'), kinEdge('c', 'd', 'SIBLING_OF')],
  };
  const result = layout(graph, { width: 480 });
  assert.equal(yOf(result, 'a'), yOf(result, 'b'));
  assert.equal(yOf(result, 'c'), yOf(result, 'd'));
  assert.ok(yOf(result, 'a') < yOf(result, 'c'));
  const row = result.nodes.filter((box) => box.y === yOf(result, 'a'));
  const left = Math.min(...row.map((box) => box.x));
  const right = Math.max(...row.map((box) => box.x + box.w));
  assert.ok(Math.abs(left - (480 - right)) <= 1, '置中');
  assertSound(graph, result, 480);
});

test('kin：一層放不下就換行，不超寬也不重疊；上一代還是在上面', () => {
  const children = Array.from({ length: 9 }, (_, i) => person(`c${i}`));
  const graph = {
    nodes: [person('p', true), ...children],
    edges: children.map((child) => kinEdge('p', child.id)),
  };
  const result = layout(graph, { width: 320 });
  assertSound(graph, result, 320);
  for (const child of children) assert.ok(yOf(result, 'p') < yOf(result, child.id));
  assert.ok(new Set(children.map((child) => yOf(result, child.id))).size > 1, '應該換行');
});

test('kin：環狀親屬資料不當掉，結果仍合理', () => {
  const cases = {
    父母環: { nodes: [person('a', true), person('b'), person('c')], edges: [kinEdge('a', 'b'), kinEdge('b', 'c'), kinEdge('c', 'a')] },
    自環: { nodes: [person('a', true), person('b')], edges: [kinEdge('a', 'a'), kinEdge('a', 'b')] },
    互為父母: { nodes: [person('a'), person('b')], edges: [kinEdge('a', 'b'), kinEdge('b', 'a')] },
    配偶環: { nodes: [person('a', true), person('b'), person('c')], edges: [kinEdge('a', 'b', 'SPOUSE_OF'), kinEdge('b', 'c', 'SPOUSE_OF'), kinEdge('c', 'a', 'SPOUSE_OF')] },
    矛盾世代: { nodes: [person('a', true), person('b'), person('c')], edges: [kinEdge('a', 'b'), kinEdge('b', 'c'), kinEdge('a', 'c', 'SIBLING_OF')] },
  };
  for (const [title, graph] of Object.entries(cases)) {
    for (const width of WIDTHS) {
      const result = layout(graph, { width });
      assertSound(graph, result, width);
      assert.deepEqual(result, layout(graph, { width }), title);
    }
  }
});

test('kin：不連通的親屬圖與沒有 focus 都能排，節點不重疊', () => {
  const graph = {
    nodes: [person('a'), person('b'), person('x'), person('y'), person('lonely')],
    edges: [kinEdge('a', 'b'), kinEdge('x', 'y')],
  };
  const result = layout(graph, { width: 480 });
  assertSound(graph, result, 480);
  assert.ok(yOf(result, 'a') < yOf(result, 'b'));
  assert.ok(yOf(result, 'x') < yOf(result, 'y'));
});

test('kin：同層 barycenter 排序能解開交叉', () => {
  const graph = {
    nodes: [person('p1', true), person('p2'), person('p3'), person('c1'), person('c2'), person('c3')],
    edges: [kinEdge('p1', 'c3'), kinEdge('p2', 'c2'), kinEdge('p3', 'c1')],
  };
  // 三條邊分屬三個連通塊，世代都正確；初始順序兩兩交叉
  const initial = countCrossings(layout(graph, { width: 720, sweeps: 0 }));
  const final = countCrossings(layout(graph, { width: 720 }));
  assert.equal(initial, 3);
  assert.equal(final, 0);
});

test('kin：同層相鄰與不相鄰的邊都有路徑，邊保留關係資料', () => {
  const graph = {
    nodes: [person('a', true), person('b'), person('c')],
    edges: [kinEdge('a', 'b', 'SIBLING_OF'), kinEdge('a', 'c', 'SIBLING_OF'), kinEdge('b', 'c', 'SIBLING_OF')],
  };
  const result = layout(graph, { width: 480 });
  assertSound(graph, result, 480);
  assert.deepEqual(result.edges.map((edge) => edge.type), ['SIBLING_OF', 'SIBLING_OF', 'SIBLING_OF']);
  assert.equal(result.edges[0].ref, '路得記 4:17');
  assert.equal(result.edges[0].verseKey, 'rut.4.17');
});

test('countCrossings：同層的親屬邊不算交叉；空圖為 0', () => {
  const graph = { nodes: [person('a', true), person('b')], edges: [kinEdge('a', 'b', 'SPOUSE_OF')] };
  assert.equal(countCrossings(layout(graph, { width: 480 })), 0);
  assert.equal(countCrossings(layout({ nodes: [], edges: [] }, { width: 480 })), 0);
});

// ---- 瀏覽器字級調大：節點高度跟著長，不然文字會被切半 ----

const WALK_SAMPLE = {
  nodes: [
    { id: 'ps:a', kind: 'passage', label: '甲', ref: '使徒行傳 13:1-3', used: true, brought: false, sourceIndex: 0 },
    { id: 'ps:b', kind: 'passage', label: '乙', ref: '使徒行傳 13:4-5', used: true, brought: true, sourceIndex: 1 },
    { id: 'nm:a', kind: 'name', label: '丙', inQuestion: false, df: 1, idf: 1 },
    { id: 'ev1', kind: 'event', label: '丁' },
  ],
  edges: [
    { from: 'ps:a', to: 'nm:a', type: 'mentions' },
    { from: 'ps:b', to: 'nm:a', type: 'mentions' },
    { from: 'ev1', to: 'ps:a', type: 'anchor' },
  ],
};
const KIN_SAMPLE = {
  nodes: [
    { id: 'p1', kind: 'person', label: '甲', focus: true },
    { id: 'p2', kind: 'person', label: '乙', focus: false },
    { id: 'p3', kind: 'person', label: '丙', focus: false },
  ],
  edges: [
    { from: 'p1', to: 'p2', type: 'PARENT_OF', verseKey: 'rut.4.17', ref: '路得記 4:17' },
    { from: 'p2', to: 'p3', type: 'SIBLING_OF', verseKey: 'rut.4.17', ref: '路得記 4:17' },
  ],
};
const heightOf = (result, id) => result.nodes.find((box) => box.id === id).h;

test('fontScale：節點高度等比長大，版面仍不重疊、不超寬', () => {
  for (const width of [288, 480, 640]) {
    const base = layout(WALK_SAMPLE, { width });
    const big = layout(WALK_SAMPLE, { width, fontScale: 1.5 });
    for (const id of ['ps:a', 'ps:b', 'nm:a', 'ev1']) {
      assert.ok(heightOf(big, id) >= heightOf(base, id) * 1.5, `${id}@${width}`);
    }
    assertSound(WALK_SAMPLE, big, width);
    const kin = layout(KIN_SAMPLE, { width, fontScale: 1.5 });
    assertSound(KIN_SAMPLE, kin, width);
    assert.ok(heightOf(kin, 'p1') >= heightOf(layout(KIN_SAMPLE, { width }), 'p1') * 1.5);
    assert.ok(kin.nodes[0].w >= layout(KIN_SAMPLE, { width }).nodes[0].w);
  }
});

test('預設 fontScale 是 1，不傳與傳 1 結果相同', () => {
  assert.deepEqual(layout(WALK_SAMPLE, { width: 480 }), layout(WALK_SAMPLE, { width: 480, fontScale: 1 }));
  assert.deepEqual(layout(KIN_SAMPLE, { width: 480 }), layout(KIN_SAMPLE, { width: 480, fontScale: 1 }));
});

test('compact：欄太窄就標 compact，高度要放得下書名換行與兩行名字', () => {
  const narrow = layout(WALK_SAMPLE, { width: 288 });
  const wide = layout(WALK_SAMPLE, { width: 640 });
  const box = (result, id) => result.nodes.find((item) => item.id === id);
  assert.equal(box(narrow, 'ps:a').compact, true);
  assert.equal(box(wide, 'ps:a').compact, false);
  assert.equal(box(narrow, 'nm:a').compact, true);
  assert.equal(box(wide, 'nm:a').compact, false);
  assert.ok(box(narrow, 'ps:a').h > box(wide, 'ps:a').h, '書名獨佔一行，要多一行高');
  assert.ok(box(narrow, 'nm:a').h >= 36, '名字折兩行要放得下');
  assert.equal(layout(KIN_SAMPLE, { width: 288 }).nodes[0].compact, false);
});

test('字級變大時 compact 門檻跟著變：同一欄寬放不下就改折行', () => {
  const at = (fontScale) => layout(WALK_SAMPLE, { width: 640, fontScale }).nodes.find((item) => item.id === 'nm:a').compact;
  assert.equal(at(1), false);
  assert.equal(at(2), true);
});

test('字級很大時 compact 段落多留一行：章節也會折行', () => {
  const heightAt = (fontScale) => layout(WALK_SAMPLE, { width: 288, fontScale }).nodes.find((item) => item.id === 'ps:a').h;
  assert.ok(heightAt(2) > heightAt(1) * 2, `${heightAt(2)} vs ${heightAt(1)}`);
  assert.equal(heightAt(1.5), Math.ceil(heightAt(1) * 1.5), '150% 還放得下，不多留');
});
