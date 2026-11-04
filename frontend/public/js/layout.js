// 決定性版面：同輸入同輸出，節點結構上不可能重疊（每欄、每列都是累加排列）。不用力導向。
// 走圖圖是三欄蝴蝶：段落分左右、名字與事件在中間；親屬圖是世代由上而下。
// 節點固定寬高，文字截斷由畫面處理；節點多時高度長大、由外層容器捲動，不縮字。純函式，不碰 DOM。

const DEFAULT_WIDTH = 480;
const NARROW_WIDTH = 420;
const DEFAULT_SWEEPS = 4;
const PADDING = 8;
const LARGE_FONT_SCALE = 1.5;
// 窄於這個寬度（以 16px 字級為準）就是手機上的節點：段落的書名獨佔一行，名字改小字可折行
const COMPACT_WIDTH = Object.freeze({ passage: 115, name: 80, event: 80, person: 0 });

const WALK = {
  passageRatio: 0.3,
  nameRatio: 0.19,
  narrowPassageRatio: 0.31,
  narrowNameRatio: 0.2,
  maxPassage: 210,
  maxName: 116,
  maxGutter: 120,
  // 高度要放得下字：標題兩行＋出處一行（compact 時出處也是兩行）＋內距與框線；字級變大時等比放大
  passageHeight: 58,
  compactPassageHeight: 72,
  largeFontRefLine: 15, // 根字級超過 LARGE_FONT_SCALE 時，連章節都放不下一行
  broughtExtra: 18,
  nameHeight: 30,
  compactNameHeight: 38,
  eventHeight: 40,
  compactEventHeight: 40,
  passageGap: 12,
  centerGap: 10,
};

const KIN = {
  nodeWidth: 92,
  narrowNodeWidth: 72,
  nodeHeight: 34,
  columnGap: 10,
  rowGap: 14,
  generationGap: 56,
  topPadding: 30,
  arc: 24,
};

// ---- 共用 ----

function centerX(box) {
  return box.x + box.w / 2;
}

function centerY(box) {
  return box.y + box.h / 2;
}

function mean(values) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function validEdges(graph) {
  const ids = new Set(graph.nodes.map((node) => node.id));
  return graph.edges.filter((edge) => ids.has(edge.from) && ids.has(edge.to));
}

function neighborMap(edges) {
  const neighbors = new Map();
  const link = (a, b) => neighbors.set(a, [...(neighbors.get(a) ?? []), b]);
  edges.forEach(({ from, to }) => {
    link(from, to);
    link(to, from);
  });
  return neighbors;
}

/** 依目前位置的 barycenter 重排；沒有鄰居就留在原位，同值維持原順序。 */
function reorderBy(ids, neighborsOf, positionOf) {
  return ids
    .map((id, index) => {
      const around = neighborsOf(id).map(positionOf);
      return { id, index, key: around.length > 0 ? mean(around) : positionOf(id) };
    })
    .sort((a, b) => a.key - b.key || a.index - b.index)
    .map(({ id }) => id);
}

function crossingSpan(a, b, mode) {
  const [main, side] = mode === 'kin' ? ['y', 'x'] : ['x', 'y'];
  if (a[main] === b[main]) return null;
  const [near, far] = a[main] < b[main] ? [a, b] : [b, a];
  return { group: `${near[main]}|${far[main]}`, near: near[side], far: far[side] };
}

function crossingsOf(boxes, edges, mode) {
  const spans = edges.flatMap(({ from, to }) => crossingSpan(boxes.get(from), boxes.get(to), mode) ?? []);
  return spans.reduce((total, a, i) => total + spans.slice(i + 1)
    .filter((b) => a.group === b.group && (a.near - b.near) * (a.far - b.far) < 0).length, 0);
}

/** 走訪 sweeps 輪，回傳交叉最少的排列；初始排列也算候選，所以結果不會比初始差。 */
function bestOrdering(initial, sweeps, step, score) {
  let current = initial;
  let best = { order: initial, crossings: score(initial) };
  for (let round = 0; round < sweeps; round += 1) {
    current = step(current, round);
    const crossings = score(current);
    if (crossings < best.crossings) best = { order: current, crossings };
  }
  return best.order;
}

function finishLayout(graph, edges, boxes, pathOf, mode, width, height) {
  return {
    mode,
    nodes: graph.nodes.map((node) => boxes.get(node.id)),
    edges: edges.map((edge) => ({ ...edge, ...pathOf(boxes.get(edge.from), boxes.get(edge.to)) })),
    width,
    height,
  };
}

// ---- 走圖圖：三欄蝴蝶 ----

function walkColumns(width) {
  const narrow = width < NARROW_WIDTH;
  const passage = Math.min(WALK.maxPassage, Math.floor(width * (narrow ? WALK.narrowPassageRatio : WALK.passageRatio)));
  const name = Math.min(WALK.maxName, Math.floor(width * (narrow ? WALK.narrowNameRatio : WALK.nameRatio)));
  const gutter = Math.min(WALK.maxGutter, Math.floor((width - 2 * passage - name) / 2));
  const margin = Math.floor((width - 2 * passage - name - 2 * gutter) / 2);
  return { passage, name, left: margin, center: margin + passage + gutter, right: margin + passage + gutter + name + gutter };
}

/** 只有一張卡時右欄是空的：把卡片與名字當一組置中，整張圖才不會偏一邊。 */
function centerLoneCard(columns, width, order) {
  if (order.left.length + order.right.length !== 1) return columns;
  const gap = columns.center - (columns.left + columns.passage);
  const hasCenter = order.center.length > 0;
  const total = columns.passage + (hasCenter ? gap + columns.name : 0);
  const left = Math.floor((width - total) / 2);
  return { ...columns, left, center: left + columns.passage + gap };
}

function isCompact(node, width, fontScale) {
  return width < COMPACT_WIDTH[node.kind] * fontScale;
}

function compactPassageHeight(fontScale) {
  return WALK.compactPassageHeight + (fontScale > LARGE_FONT_SCALE ? WALK.largeFontRefLine : 0);
}

function baseHeight(node, compact, fontScale) {
  if (node.kind === 'passage') {
    return (compact ? compactPassageHeight(fontScale) : WALK.passageHeight) + (node.brought ? WALK.broughtExtra : 0);
  }
  if (node.kind === 'event') return compact ? WALK.compactEventHeight : WALK.eventHeight;
  return compact ? WALK.compactNameHeight : WALK.nameHeight;
}

function walkBox(node, columns, fontScale) {
  const w = node.kind === 'passage' ? columns.passage : columns.name;
  const compact = isCompact(node, w, fontScale);
  return { w, compact, h: Math.ceil(baseHeight(node, compact, fontScale) * fontScale) };
}

function columnHeight(ids, heightOf, gap) {
  return ids.reduce((sum, id) => sum + heightOf(id), 0) + gap * Math.max(ids.length - 1, 0);
}

/** 由上而下累加，多的高度平均分給每格：節點只會離得更開，不可能重疊。 */
function stackColumn(ids, heightOf, gap, totalHeight) {
  const extra = ids.length > 0 ? Math.floor((totalHeight - columnHeight(ids, heightOf, gap)) / ids.length) : 0;
  let y = PADDING + Math.floor(extra / 2);
  return ids.map((id) => {
    const placed = { id, y, h: heightOf(id) };
    y += placed.h + gap + extra;
    return placed;
  });
}

function placeWalk(order, nodeById, columns, fontScale) {
  const sizes = new Map([...nodeById].map(([id, node]) => [id, walkBox(node, columns, fontScale)]));
  const heightOf = (id) => sizes.get(id).h;
  const totalHeight = Math.max(
    columnHeight(order.left, heightOf, WALK.passageGap),
    columnHeight(order.right, heightOf, WALK.passageGap),
    columnHeight(order.center, heightOf, WALK.centerGap),
  );
  const place = (ids, gap, x) => stackColumn(ids, heightOf, gap, totalHeight)
    .map(({ id, y, h }) => [id, { id, x, y, w: sizes.get(id).w, h, compact: sizes.get(id).compact }]);
  const boxes = new Map([
    ...place(order.left, WALK.passageGap, columns.left),
    ...place(order.center, WALK.centerGap, columns.center),
    ...place(order.right, WALK.passageGap, columns.right),
  ]);
  return { boxes, height: totalHeight + 2 * PADDING };
}

/** 段落依 sources 順序左右交替；中欄事件在前、問題名字其次。 */
function initialWalkOrder(graph) {
  const passages = graph.nodes
    .filter((node) => node.kind === 'passage')
    .map((node, index) => ({ node, index }))
    .sort((a, b) => (a.node.sourceIndex ?? Infinity) - (b.node.sourceIndex ?? Infinity) || a.index - b.index)
    .map(({ node }) => node.id);
  const middle = (test) => graph.nodes.filter(test).map((node) => node.id);
  return {
    left: passages.filter((_, index) => index % 2 === 0),
    right: passages.filter((_, index) => index % 2 === 1),
    center: [
      ...middle((node) => node.kind === 'event'),
      ...middle((node) => node.kind === 'name' && node.inQuestion),
      ...middle((node) => node.kind === 'name' && !node.inQuestion),
    ],
  };
}

function walkEdgePath(a, b) {
  const [x1, x2] = a.x < b.x ? [a.x + a.w, b.x] : [a.x, b.x + b.w];
  const [y1, y2] = [centerY(a), centerY(b)];
  const middle = (x1 + x2) / 2;
  return { path: `M ${x1} ${y1} C ${middle} ${y1}, ${middle} ${y2}, ${x2} ${y2}`, mid: { x: middle, y: (y1 + y2) / 2 } };
}

function layoutWalk(graph, width, sweeps, fontScale) {
  const edges = validEdges(graph);
  const neighbors = neighborMap(edges);
  const neighborsOf = (id) => neighbors.get(id) ?? [];
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const initial = initialWalkOrder(graph);
  const columns = centerLoneCard(walkColumns(width), width, initial);
  const place = (order) => placeWalk(order, nodeById, columns, fontScale);
  // 偶數輪排中欄、奇數輪排左右兩欄，交替掃
  const step = (order, round) => {
    const { boxes } = place(order);
    const positionOf = (id) => centerY(boxes.get(id));
    if (round % 2 === 0) return { ...order, center: reorderBy(order.center, neighborsOf, positionOf) };
    return {
      ...order,
      left: reorderBy(order.left, neighborsOf, positionOf),
      right: reorderBy(order.right, neighborsOf, positionOf),
    };
  };
  const score = (order) => crossingsOf(place(order).boxes, edges, 'walk');
  const { boxes, height } = place(bestOrdering(initial, sweeps, step, score));
  return finishLayout(graph, edges, boxes, walkEdgePath, 'walk', width, height);
}

// ---- 親屬圖：世代由上而下 ----

function generationLinks(edges) {
  const links = new Map();
  const link = (id, other, delta) => links.set(id, [...(links.get(id) ?? []), { other, delta }]);
  edges.forEach(({ from, to, type }) => {
    const delta = type === 'PARENT_OF' ? 1 : 0;
    link(from, to, delta);
    link(to, from, -delta);
  });
  return links;
}

/** 從 seed 廣度優先往外指派世代：已有世代的不再改（先到先贏），所以環或矛盾資料也會結束。 */
function spreadGeneration(seed, links, generation) {
  const queue = [seed];
  for (let head = 0; head < queue.length; head += 1) {
    const id = queue[head];
    for (const { other, delta } of links.get(id) ?? []) {
      if (!generation.has(other)) {
        generation.set(other, generation.get(id) + delta);
        queue.push(other);
      }
    }
  }
}

/** 焦點先排；不連通的每塊各自從 0 起算，最後整體平移到從 0 開始。 */
function assignGenerations(graph, edges) {
  const links = generationLinks(edges);
  const generation = new Map();
  for (const { id } of [...graph.nodes.filter((node) => node.focus), ...graph.nodes]) {
    if (!generation.has(id)) {
      generation.set(id, 0);
      spreadGeneration(id, links, generation);
    }
  }
  const lowest = Math.min(...generation.values());
  return new Map([...generation].map(([id, value]) => [id, value - lowest]));
}

function initialLayers(graph, generation) {
  const count = Math.max(...generation.values()) + 1;
  return Array.from({ length: count }, (_, level) => graph.nodes
    .filter((node) => generation.get(node.id) === level)
    .map((node) => node.id));
}

function kinMetrics(width, fontScale) {
  const base = width < NARROW_WIDTH ? KIN.narrowNodeWidth : KIN.nodeWidth;
  const nodeWidth = Math.min(Math.ceil(base * fontScale), width);
  const perRow = Math.max(1, Math.floor((width + KIN.columnGap) / (nodeWidth + KIN.columnGap)));
  return {
    nodeWidth,
    perRow,
    nodeHeight: Math.ceil(KIN.nodeHeight * fontScale),
    rowGap: Math.ceil(KIN.rowGap * fontScale),
    generationGap: Math.ceil(KIN.generationGap * fontScale),
    topPadding: Math.ceil(KIN.topPadding * fontScale),
  };
}

function chunk(ids, size) {
  return Array.from({ length: Math.ceil(ids.length / size) }, (_, i) => ids.slice(i * size, (i + 1) * size));
}

/** 一層放不下就換行；每列置中，所以不可能超寬或重疊。 */
function placeKin(layers, width, metrics) {
  const boxes = new Map();
  let y = metrics.topPadding;
  layers.forEach((layer) => {
    chunk(layer, metrics.perRow).forEach((row) => {
      const rowWidth = row.length * metrics.nodeWidth + (row.length - 1) * KIN.columnGap;
      const left = Math.floor((width - rowWidth) / 2);
      row.forEach((id, index) => boxes.set(id, {
        id, x: left + index * (metrics.nodeWidth + KIN.columnGap), y, w: metrics.nodeWidth, h: metrics.nodeHeight, compact: false,
      }));
      y += metrics.nodeHeight + metrics.rowGap;
    });
    y += metrics.generationGap - metrics.rowGap;
  });
  return { boxes, height: y - metrics.generationGap + PADDING };
}

function sameRowPath(a, b) {
  const [left, right] = a.x <= b.x ? [a, b] : [b, a];
  const y = centerY(left);
  if (right.x - (left.x + left.w) <= KIN.columnGap) {
    const [x1, x2] = [left.x + left.w, right.x];
    return { path: `M ${x1} ${y} C ${x1} ${y}, ${x2} ${y}, ${x2} ${y}`, mid: { x: (x1 + x2) / 2, y } };
  }
  // 中間隔著別人就從上方繞過去
  const [x1, x2, top, lift] = [centerX(left), centerX(right), left.y, left.y - KIN.arc];
  return { path: `M ${x1} ${top} C ${x1} ${lift}, ${x2} ${lift}, ${x2} ${top}`, mid: { x: (x1 + x2) / 2, y: top - (KIN.arc * 3) / 4 } };
}

function kinEdgePath(a, b) {
  if (a.y === b.y) return sameRowPath(a, b);
  const [upper, lower] = a.y < b.y ? [a, b] : [b, a];
  const [x1, y1, x2, y2] = [centerX(upper), upper.y + upper.h, centerX(lower), lower.y];
  const middle = (y1 + y2) / 2;
  return { path: `M ${x1} ${y1} C ${x1} ${middle}, ${x2} ${middle}, ${x2} ${y2}`, mid: { x: (x1 + x2) / 2, y: middle } };
}

function layoutKin(graph, width, sweeps, fontScale) {
  const edges = validEdges(graph);
  const generation = assignGenerations(graph, edges);
  const neighbors = neighborMap(edges);
  const metrics = kinMetrics(width, fontScale);
  const place = (layers) => placeKin(layers, width, metrics);
  // 偶數輪由上往下、奇數輪由下往上，每層依相鄰世代的位置重排
  const step = (layers, round) => {
    const going = round % 2 === 0 ? 1 : -1;
    const levels = layers.map((_, level) => level);
    return (going === 1 ? levels : [...levels].reverse()).reduce((current, level) => {
      const { boxes } = place(current);
      const aside = (id) => (neighbors.get(id) ?? []).filter((other) => generation.get(other) === level - going);
      const reordered = reorderBy(current[level], aside, (id) => centerX(boxes.get(id)));
      return current.map((layer, index) => (index === level ? reordered : layer));
    }, layers);
  };
  const score = (layers) => crossingsOf(place(layers).boxes, edges, 'kin');
  const { boxes, height } = place(bestOrdering(initialLayers(graph, generation), sweeps, step, score));
  return finishLayout(graph, edges, boxes, kinEdgePath, 'kin', width, height);
}

// ---- 入口 ----

/** layout(graph, {width, fontScale}) → {mode, nodes:[{id,x,y,w,h,compact}], edges:[{...原邊, path, mid:{x,y}}], width, height}。
 *  fontScale 是根字級除以 16：字用 rem，瀏覽器字級調大時節點高度要跟著長，字才不會被切半。
 *  邊保留原本的 type／ref 等欄位，mid 是畫關係標籤的位置；sweeps 只給測試比較初始排列用。 */
export function layout(graph, { width = DEFAULT_WIDTH, sweeps = DEFAULT_SWEEPS, fontScale = 1 } = {}) {
  const isKin = graph.nodes.some((node) => node.kind === 'person');
  if (graph.nodes.length === 0) return { mode: 'walk', nodes: [], edges: [], width, height: 0 };
  return isKin ? layoutKin(graph, width, sweeps, fontScale) : layoutWalk(graph, width, sweeps, fontScale);
}

/** 版面結果的邊交叉數：走圖看同一道欄間、親屬看同一對世代列；同層的邊不算。 */
export function countCrossings(result) {
  const boxes = new Map(result.nodes.map((box) => [box.id, box]));
  return crossingsOf(boxes, result.edges, result.mode);
}
