// 剪枝測試共用：契約的硬性保證、合成圖的小工具。
import assert from 'node:assert/strict';
import { MAX_NODES } from '../../public/js/prune.js';

export function ids(nodes) {
  return new Set(nodes.map((node) => node.id));
}

export function labels(result, kind) {
  return result.nodes.filter((node) => node.kind === kind).map((node) => node.label);
}

export function degreeOf(edges, id) {
  return edges.filter((edge) => edge.from === id || edge.to === id).length;
}

/** 契約列的硬性保證，適用任何被剪過的圖。 */
export function assertGuarantees(input, result) {
  const kept = ids(result.nodes);
  for (const edge of result.edges) {
    assert.ok(kept.has(edge.from) && kept.has(edge.to), `懸空邊 ${edge.from}→${edge.to}`);
  }
  for (const node of result.nodes.filter((item) => item.kind !== 'event')) {
    assert.ok(degreeOf(result.edges, node.id) >= 1, `沒有邊的節點 ${node.label}`);
  }
  const hiddenNodes = input.nodes.length - result.nodes.length;
  assert.equal(result.hidden.names + result.hidden.passages, hiddenNodes, '節點差額');
  assert.equal(result.hidden.edges, input.edges.length - result.edges.length, '邊差額');
  assert.equal(result.hidden.names, input.nodes.filter((n) => n.kind === 'name' || n.kind === 'person').length
    - result.nodes.filter((n) => n.kind === 'name' || n.kind === 'person').length);
  assert.equal(result.hidden.passages, input.nodes.filter((n) => n.kind === 'passage').length
    - result.nodes.filter((n) => n.kind === 'passage').length);
  assert.equal(result.nodes.filter((n) => n.kind === 'event').length, input.nodes.filter((n) => n.kind === 'event').length, '事件一律保留');
  // 留下的節點與邊都是輸入的子序列（順序決定性）
  const order = new Map(input.nodes.map((node, index) => [node.id, index]));
  const positions = result.nodes.map((node) => order.get(node.id));
  assert.deepEqual(positions, [...positions].sort((a, b) => a - b), '節點維持輸入順序');
}

/** 被藏的 used／inQuestion，必須跟留下的節點沒有任何連線。 */
export function assertVitalNodesKept(input, result) {
  const kept = ids(result.nodes);
  const hidden = input.nodes.filter((node) => !kept.has(node.id) && (node.used || node.inQuestion));
  for (const node of hidden) {
    const linked = input.edges.some((edge) => (edge.from === node.id && kept.has(edge.to))
      || (edge.to === node.id && kept.has(edge.from)));
    assert.equal(linked, false, `${node.label} 還有連線卻被藏`);
  }
}

export function passage(id, used = true) {
  return { id, kind: 'passage', label: id, ref: id, used, brought: false, ...(used ? { sourceIndex: 0 } : {}) };
}

export function name(id, idf = 5, inQuestion = false) {
  return { id, kind: 'name', label: id, inQuestion, df: 1, idf };
}

export function mention(from, to) {
  return { from, to, type: 'mentions' };
}

export const PADDING = Array.from({ length: MAX_NODES + 1 }, (_, i) => passage(`ps:pad${i}`, false));

export function walkGraph(nodes, edges) {
  return { nodes: [...nodes, ...PADDING], edges };
}

export function keptIds(result) {
  return result.nodes.map((node) => node.id);
}
