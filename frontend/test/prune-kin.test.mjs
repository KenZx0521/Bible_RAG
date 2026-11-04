// 剪枝：親屬圖。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_EDGES, MAX_NODES, prune } from '../public/js/prune.js';
import { deepFreeze } from './support/fixtures.mjs';
import { assertGuarantees } from './support/prune-helpers.mjs';

function person(id, focus = false) {
  return { id, kind: 'person', label: id, focus };
}

function kinEdge(from, to, type = 'PARENT_OF') {
  return { from, to, type, verseKey: 'rut.4.17', ref: '路得記 4:17' };
}

function chainGraph(length, focusAt = 0) {
  const nodes = Array.from({ length }, (_, i) => person(`e${String(i).padStart(2, '0')}`, i === focusAt));
  const edges = nodes.slice(1).map((node, i) => kinEdge(nodes[i].id, node.id));
  return { nodes, edges };
}

test('親屬圖超過上限：從 focus BFS，近的優先，留到 MAX_NODES，保留留下節點間的邊', () => {
  const graph = deepFreeze(chainGraph(30, 15));
  const result = prune(graph);
  assert.equal(result.pruned, true);
  assert.equal(result.nodes.length, MAX_NODES);
  assert.ok(result.nodes.some((node) => node.focus));
  const kept = result.nodes.map((node) => Number(node.id.slice(1)));
  for (const index of kept) assert.ok(Math.abs(index - 15) <= 7, `e${index} 離焦點太遠`);
  assert.equal(result.hidden.passages, 0);
  assert.equal(result.hidden.names, 16);
  assertGuarantees(graph, result);
  assert.deepEqual(prune(graph), result);
});

test('親屬圖沒有 focus：從第一個節點開始；環不當掉', () => {
  const nodes = Array.from({ length: 20 }, (_, i) => person(`e${String(i).padStart(2, '0')}`));
  const edges = nodes.map((node, i) => kinEdge(node.id, nodes[(i + 1) % nodes.length].id, 'SIBLING_OF'));
  const graph = { nodes, edges };
  const result = prune(graph);
  assert.equal(result.nodes.length, MAX_NODES);
  assert.ok(result.nodes.some((node) => node.id === 'e00'));
  assertGuarantees(graph, result);
});

test('親屬圖不連通：焦點那塊優先；另一塊補到上限；落單的不畫', () => {
  const main = chainGraph(10, 0);
  const other = Array.from({ length: 10 }, (_, i) => person(`z${String(i).padStart(2, '0')}`));
  const otherEdges = other.slice(1).map((node, i) => kinEdge(other[i].id, node.id));
  const graph = { nodes: [...main.nodes, ...other, person('lonely')], edges: [...main.edges, ...otherEdges] };
  const result = prune(graph);
  assert.ok(result.nodes.length <= MAX_NODES);
  for (const node of main.nodes) assert.ok(result.nodes.some((item) => item.id === node.id));
  assert.ok(!result.nodes.some((item) => item.id === 'lonely'));
  assertGuarantees(graph, result);
});

test('親屬圖節點沒超過但邊超過：節點照留，pruned 為 false', () => {
  const nodes = Array.from({ length: 10 }, (_, i) => person(`e${i}`, i === 0));
  const edges = nodes.flatMap((a, i) => nodes.slice(i + 1).map((b) => kinEdge(a.id, b.id, 'SIBLING_OF')));
  assert.ok(edges.length > MAX_EDGES);
  const result = prune({ nodes, edges });
  assert.equal(result.nodes.length, 10);
  assert.equal(result.edges.length, edges.length);
  assert.equal(result.pruned, false);
});
