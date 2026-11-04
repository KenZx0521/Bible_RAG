// 親屬圖的關係字：不互相蓋住、不蓋人名、不超出舞台。
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { LABEL_SIZE, placeEdgeLabels } from '../public/js/edge-labels.js';
import { layout } from '../public/js/layout.js';
import { prune } from '../public/js/prune.js';
import { buildViews } from '../public/js/graph-model.js';
import { deepFreeze, loadFixture } from './support/fixtures.mjs';

function rectOf({ x, y }, scale = 1) {
  const w = LABEL_SIZE.w * scale;
  const h = LABEL_SIZE.h * scale;
  return { left: x - w / 2, right: x + w / 2, top: y - h / 2, bottom: y + h / 2 };
}

function hit(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

function boxRect(box) {
  return { left: box.x, right: box.x + box.w, top: box.y, bottom: box.y + box.h };
}

function bigFamily() {
  const people = ['亞伯拉罕', '撒拉', '夏甲', '以撒', '以實瑪利', '利百加', '雅各', '以掃', '拉結', '利亞',
    '約瑟', '便雅憫', '流便', '西緬', '利未', '猶大', '以法蓮', '瑪拿西'];
  const id = (name) => `p${people.indexOf(name)}`;
  const parent = (a, b) => ({ from: id(a), to: id(b), type: 'PARENT_OF', verseKey: 'gen.21.3', ref: 'x' });
  const other = (a, type, b) => ({ from: id(a), to: id(b), type, verseKey: 'gen.21.3', ref: 'x' });
  return {
    nodes: people.map((name) => ({ id: id(name), kind: 'person', label: name, focus: name === '雅各' })),
    edges: [
      parent('亞伯拉罕', '以撒'), parent('撒拉', '以撒'), parent('亞伯拉罕', '以實瑪利'), parent('夏甲', '以實瑪利'),
      other('亞伯拉罕', 'SPOUSE_OF', '撒拉'), other('以撒', 'SPOUSE_OF', '利百加'),
      parent('以撒', '雅各'), parent('以撒', '以掃'), parent('利百加', '雅各'), other('雅各', 'SIBLING_OF', '以掃'),
      other('雅各', 'SPOUSE_OF', '拉結'), other('雅各', 'SPOUSE_OF', '利亞'),
      parent('拉結', '約瑟'), parent('拉結', '便雅憫'), parent('利亞', '流便'), parent('利亞', '西緬'), parent('利亞', '利未'), parent('利亞', '猶大'),
      parent('約瑟', '以法蓮'), parent('約瑟', '瑪拿西'),
    ],
  };
}

function place(graph, width, fontScale = 1) {
  const placed = layout(graph, { width, fontScale });
  const boxes = new Map(placed.nodes.map((box) => [box.id, box]));
  return { placed, boxes, points: placeEdgeLabels(placed.edges, boxes, { width: placed.width, height: placed.height, fontScale }) };
}

for (const fontScale of [1, 1.5, 2]) {
  for (const width of [240, 320, 480, 720]) {
    test(`大家族完整圖（${width}、字級 ×${fontScale}）：關係字互不重疊、不蓋人物、不超出舞台`, () => {
      const { placed, boxes, points } = place(bigFamily(), width, fontScale);
      assert.equal(points.length, placed.edges.length);
      const rects = points.map((point) => rectOf(point, fontScale));
      rects.forEach((a, i) => rects.slice(i + 1).forEach((b, j) => {
        assert.equal(hit(a, b), false, `第 ${i} 與第 ${i + 1 + j} 個關係字重疊`);
      }));
      for (const rect of rects) {
        for (const box of boxes.values()) assert.equal(hit(rect, boxRect(box)), false, `關係字蓋到 ${box.id}`);
        assert.ok(rect.left >= -0.5 && rect.right <= placed.width + 0.5, `超出寬度 ${JSON.stringify(rect)}`);
        assert.ok(rect.top >= -0.5 && rect.bottom <= placed.height + 0.5, `超出高度 ${JSON.stringify(rect)} / ${placed.height}`);
      }
    });
  }
}

test('真實親屬圖：沒有衝突時關係字就在線的中點', () => {
  const { graph } = buildViews(loadFixture('kin')).views.find((view) => view.key === 'kin');
  const { placed, points } = place(graph, 480);
  placed.edges.forEach((edge, i) => {
    assert.equal(points[i].x, edge.mid.x);
    assert.equal(points[i].y, edge.mid.y);
  });
});

test('兩條線中點相同：第二個沿著線移開', () => {
  const boxes = new Map([
    ['a', { id: 'a', x: 0, y: 0, w: 80, h: 34 }],
    ['b', { id: 'b', x: 200, y: 0, w: 80, h: 34 }],
    ['c', { id: 'c', x: 0, y: 160, w: 80, h: 34 }],
    ['d', { id: 'd', x: 200, y: 160, w: 80, h: 34 }],
  ]);
  const edges = [
    { from: 'a', to: 'd', path: 'M 40 34 C 40 97, 240 97, 240 160', mid: { x: 140, y: 97 } },
    { from: 'b', to: 'c', path: 'M 240 34 C 240 97, 40 97, 40 160', mid: { x: 140, y: 97 } },
  ];
  const [first, second] = placeEdgeLabels(deepFreeze(edges), boxes, { width: 300, height: 200 });
  assert.deepEqual(first, { x: 140, y: 97 });
  assert.equal(hit(rectOf(first), rectOf(second)), false);
  assert.ok(Math.abs(second.x - 140) < 120, '還在這條線附近');
});

test('同列相鄰：抬到節點上方，不蓋住名字', () => {
  const boxes = new Map([
    ['a', { id: 'a', x: 100, y: 40, w: 92, h: 34 }],
    ['b', { id: 'b', x: 202, y: 40, w: 92, h: 34 }],
  ]);
  const edges = [{ from: 'a', to: 'b', path: 'M 192 57 C 192 57, 202 57, 202 57', mid: { x: 197, y: 57 } }];
  const [point] = placeEdgeLabels(edges, boxes, { width: 400, height: 100 });
  assert.equal(hit(rectOf(point), boxRect(boxes.get('a'))), false);
  assert.equal(hit(rectOf(point), boxRect(boxes.get('b'))), false);
  assert.ok(point.y < 40);
});

test('決定性；不改輸入', () => {
  const graph = deepFreeze(bigFamily());
  const first = place(graph, 320);
  const second = place(graph, 320);
  assert.deepEqual(first.points, second.points);
});

test('擠到放不下也不當掉：回到原本的位置，而且還在舞台裡', () => {
  const boxes = new Map([
    ['a', { id: 'a', x: 0, y: 0, w: 40, h: 20 }],
    ['b', { id: 'b', x: 0, y: 30, w: 40, h: 20 }],
  ]);
  const edges = Array.from({ length: 12 }, () => ({ from: 'a', to: 'b', path: 'M 20 20 C 20 25, 20 25, 20 30', mid: { x: 20, y: 25 } }));
  const points = placeEdgeLabels(edges, boxes, { width: 40, height: 50 });
  assert.equal(points.length, 12);
  for (const point of points) {
    assert.ok(Number.isFinite(point.x) && Number.isFinite(point.y));
    assert.ok(point.x >= 0 && point.x <= 40);
  }
});

test('精簡親屬圖也適用', () => {
  const pruned = prune(bigFamily());
  const { points } = place({ nodes: pruned.nodes, edges: pruned.edges }, 320);
  const rects = points.map((point) => rectOf(point));
  rects.forEach((a, i) => rects.slice(i + 1).forEach((b) => assert.equal(hit(a, b), false)));
});
