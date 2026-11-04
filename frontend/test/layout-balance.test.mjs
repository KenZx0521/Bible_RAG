// 版面：精簡圖只畫走到的段落後卡片常常很少，只有 1–2 張時也要平衡。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { layout } from '../public/js/layout.js';
import { prune } from '../public/js/prune.js';
import { buildViews } from '../public/js/graph-model.js';
import { FIXTURE_NAMES, loadFixture } from './support/fixtures.mjs';

function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

function assertInside(result, width) {
  for (const box of result.nodes) {
    assert.ok(box.x >= 0 && box.x + box.w <= width, `${box.id} 超出寬度`);
  }
  result.nodes.forEach((a, i) => result.nodes.slice(i + 1).forEach((b) => {
    assert.equal(overlaps(a, b), false, `${a.id} 與 ${b.id} 重疊`);
  }));
}

function fewCards(cardCount, nameCount) {
  const nodes = [
    ...Array.from({ length: cardCount }, (_, i) => ({ id: `ps:${i}`, kind: 'passage', label: `段${i}`, ref: 'x', used: true, walked: true, brought: false, sourceIndex: i })),
    ...Array.from({ length: nameCount }, (_, i) => ({ id: `nm:${i}`, kind: 'name', label: `名${i}`, inQuestion: false, df: 1, idf: 1 })),
  ];
  const edges = nodes.filter((node) => node.kind === 'name').flatMap((name) => Array.from({ length: cardCount }, (_, i) => ({ from: `ps:${i}`, to: name.id, type: 'mentions' })));
  return { nodes, edges };
}

function sideMargins(result) {
  const left = Math.min(...result.nodes.map((box) => box.x));
  const right = Math.max(...result.nodes.map((box) => box.x + box.w));
  return { left, right: result.width - right };
}

for (const width of [240, 320, 480, 720]) {
  test(`只有 1 張卡（${width}）：卡片加名字整組置中，不偏一邊`, () => {
    const result = layout(fewCards(1, 2), { width });
    const { left, right } = sideMargins(result);
    assert.ok(Math.abs(left - right) <= 1, `左 ${left}、右 ${right}`);
    assertInside(result, width);
    assert.ok(!result.edges.some((edge) => edge.path.includes('NaN')));
  });

  test(`只有 1 張卡、沒有名字（${width}）：卡片置中`, () => {
    const result = layout(fewCards(1, 0), { width });
    const { left, right } = sideMargins(result);
    assert.ok(Math.abs(left - right) <= 1, `左 ${left}、右 ${right}`);
  });

  test(`2 張卡（${width}）：左右各一張，名字在中間，兩邊留白一樣`, () => {
    const result = layout(fewCards(2, 2), { width });
    const boxes = new Map(result.nodes.map((box) => [box.id, box]));
    assert.ok(boxes.get('ps:0').x + boxes.get('ps:0').w <= boxes.get('nm:0').x);
    assert.ok(boxes.get('nm:0').x + boxes.get('nm:0').w <= boxes.get('ps:1').x);
    const { left, right } = sideMargins(result);
    assert.ok(Math.abs(left - right) <= 1, `左 ${left}、右 ${right}`);
  });
}

test('五份 fixture 的精簡圖：左右欄張數最多差 1', () => {
  for (const name of FIXTURE_NAMES) {
    const walk = buildViews(loadFixture(name)).views.find((view) => view.key === 'walk');
    if (walk) {
      const { nodes, edges } = prune(walk.graph);
      const graph = { nodes, edges };
      const result = layout(graph, { width: 480 });
      const boxes = new Map(result.nodes.map((box) => [box.id, box]));
      const cards = graph.nodes.filter((node) => node.kind === 'passage').map((node) => boxes.get(node.id).x);
      const xs = [...new Set(cards)].sort((a, b) => a - b);
      const counts = xs.map((x) => cards.filter((value) => value === x).length);
      assert.ok(Math.max(...counts) - Math.min(...counts) <= 1, `${name}: ${counts}`);
    }
  }
});
