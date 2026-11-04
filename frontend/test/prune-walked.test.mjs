// 剪枝：圖上只畫走到的段落後的規則（精簡圖的段落＝走到且用到，加上事件對應的段落）。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_NODES, prune } from '../public/js/prune.js';
import { assertGuarantees, degreeOf, keptIds, labels, mention, name, passage, walkGraph } from './support/prune-helpers.mjs';

function walkedPassage(id, used = true) {
  return { ...passage(id, used), walked: true };
}

test('小圖裡有沒用到的段落：精簡圖也不留，而且老實算進 hidden', () => {
  const graph = {
    nodes: [walkedPassage('ps:u'), walkedPassage('ps:n', false), name('nm:q', 5, true)],
    edges: [mention('ps:u', 'nm:q'), mention('ps:n', 'nm:q')],
  };
  const result = prune(graph);
  assert.equal(result.pruned, true);
  assert.deepEqual(keptIds(result), ['ps:u', 'nm:q']);
  assert.deepEqual(result.hidden, { names: 0, passages: 1, edges: 1 });
});

test('全部都沒用到：一段都不留，也不當掉', () => {
  const graph = {
    nodes: [walkedPassage('ps:n', false), name('nm:q', 5, true)],
    edges: [mention('ps:n', 'nm:q')],
  };
  const result = prune(graph);
  assert.deepEqual(result.nodes, []);
  assert.deepEqual(result.edges, []);
  assert.equal(result.pruned, true);
  assert.deepEqual(result.hidden, { names: 1, passages: 1, edges: 1 });
});

test('走到且用到的段落：名字都是葉子時補回最罕見的一個，段落不會消失', () => {
  const graph = walkGraph(
    [walkedPassage('ps:a'), walkedPassage('ps:b'), name('nm:rare', 9), name('nm:common', 1), name('nm:leaf', 3)],
    [mention('ps:a', 'nm:common'), mention('ps:a', 'nm:rare'), mention('ps:b', 'nm:leaf')],
  );
  const result = prune(graph);
  assert.deepEqual(labels(result, 'passage'), ['ps:a', 'ps:b']);
  assert.deepEqual(labels(result, 'name'), ['nm:rare', 'nm:leaf']);
  assert.equal(result.edges.length, 2);
  assertGuarantees(graph, result);
});

test('補名字時，已經留著的優先：不多一個節點', () => {
  // 名額只有 1：nm:a 留下、nm:b 被擠掉。ps:c 補回 nm:b 之後，ps:d 共用它，不去補更罕見的葉子 nm:leaf
  const graph = walkGraph(
    [walkedPassage('ps:a'), walkedPassage('ps:b'), walkedPassage('ps:c'), walkedPassage('ps:d'),
      name('nm:a', 9), name('nm:b', 8), name('nm:leaf', 9.5)],
    [mention('ps:a', 'nm:a'), mention('ps:b', 'nm:a'), mention('ps:c', 'nm:b'), mention('ps:d', 'nm:b'), mention('ps:d', 'nm:leaf')],
  );
  const result = prune(graph, { maxNames: 1 });
  assert.deepEqual(labels(result, 'name'), ['nm:a', 'nm:b']);
  assert.deepEqual(labels(result, 'passage'), ['ps:a', 'ps:b', 'ps:c', 'ps:d']);
});

test('走到且用到但資料裡沒有任何邊：照樣上圖（硬性檢查優先於「節點都有邊」）', () => {
  const graph = walkGraph([walkedPassage('ps:lonely'), walkedPassage('ps:n', false)], []);
  const result = prune(graph);
  assert.deepEqual(keptIds(result), ['ps:lonely']);
  assert.deepEqual(result.edges, []);
});

test('走到且用到的段落比上限還多：段落全留，寧可超過總量也不讓段數對不上', () => {
  const passages = Array.from({ length: MAX_NODES + 3 }, (_, i) => walkedPassage(`ps:${i}`));
  const names = passages.map((_, i) => name(`nm:${i}`, 5));
  const edges = passages.map((node, i) => mention(node.id, `nm:${i}`));
  const result = prune({ nodes: [...passages, ...names], edges });
  assert.equal(labels(result, 'passage').length, passages.length);
  for (const node of result.nodes) assert.ok(degreeOf(result.edges, node.id) >= 1, node.label);
  assert.deepEqual(prune({ nodes: [...passages, ...names], edges }), result, '決定性');
});
