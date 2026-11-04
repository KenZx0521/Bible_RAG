// 親屬圖關係字的位置：不互相蓋住、不蓋人名、不超出舞台。純函式，不碰 DOM。
// 先放在線的中點；被佔了就沿著線滑動，還不行才找舞台上最近的空位。這樣字盡量留在自己那條線上，讀者才對得起來。

// 兩個字加內距的大小（以 16px 字級為準），字級放大時等比放大。要和 .edge-label 的樣式對得上。
export const LABEL_SIZE = Object.freeze({ w: 34, h: 20 });

const LIFT = 10;
const GAP = 2;
const CURVE_STOPS = [0.5, 0.4, 0.6, 0.3, 0.7, 0.2, 0.8, 0.12, 0.88];

function rectAt({ x, y }, size) {
  const [halfW, halfH] = [size.w / 2 + GAP / 2, size.h / 2 + GAP / 2];
  return { left: x - halfW, right: x + halfW, top: y - halfH, bottom: y + halfH };
}

function boxRect({ x, y, w, h }) {
  return { left: x, right: x + w, top: y, bottom: y + h };
}

function hits(a, b) {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/** 同列相鄰的兩人之間只有一道窄縫，標籤放縫上會蓋住名字，所以抬到節點上方。 */
function idealPoint(edge, boxes, fontScale) {
  const box = boxes.get(edge.from);
  const isInGap = box.y === boxes.get(edge.to).y && edge.mid.y >= box.y;
  return isInGap ? { x: edge.mid.x, y: box.y - LIFT * Math.max(1, fontScale) } : edge.mid;
}

/** 三次貝茲曲線上的點；path 是 layout 產生的「M x y C a b, c d, e f」。 */
function curvePoint(numbers, t) {
  const blend = (p0, p1, p2, p3) => {
    const u = 1 - t;
    return u * u * u * p0 + 3 * u * u * t * p1 + 3 * u * t * t * p2 + t * t * t * p3;
  };
  const [x0, y0, x1, y1, x2, y2, x3, y3] = numbers;
  return { x: blend(x0, x1, x2, x3), y: blend(y0, y1, y2, y3) };
}

function alongCurve(edge) {
  const numbers = edge.path.match(/-?\d+(?:\.\d+)?/g).map(Number);
  return CURVE_STOPS.map((t) => curvePoint(numbers, t));
}

function clamp(value, low, high) {
  return high < low ? (low + high) / 2 : Math.min(Math.max(value, low), high);
}

function keepInside({ x, y }, size, bounds) {
  return {
    x: clamp(x, size.w / 2, bounds.width - size.w / 2),
    y: clamp(y, size.h / 2, bounds.height - size.h / 2),
  };
}

/** 以 center 為原點、標籤大小為格距，鋪滿整個舞台的格點，由近而遠。 */
function gridAround(center, size, bounds) {
  const [stepX, stepY] = [size.w + GAP, size.h + GAP];
  const [cols, rows] = [Math.ceil(bounds.width / stepX), Math.ceil(bounds.height / stepY)];
  const offsets = [];
  for (let dy = -rows; dy <= rows; dy += 1) {
    for (let dx = -cols; dx <= cols; dx += 1) offsets.push({ dx, dy, far: (dx * stepX) ** 2 + (dy * stepY) ** 2 });
  }
  return offsets
    .sort((a, b) => a.far - b.far || a.dy - b.dy || a.dx - b.dx)
    .map(({ dx, dy }) => ({ x: center.x + dx * stepX, y: center.y + dy * stepY }));
}

/** placeEdgeLabels(edges, boxes, {width, height, fontScale}) → 與 edges 同順序的 [{x,y}]（標籤中心）。
 *  由上而下依序放，所以結果決定性；真的放不下就回到理想位置，不會當掉。 */
export function placeEdgeLabels(edges, boxes, { width, height, fontScale = 1 }) {
  const scale = Math.max(1, fontScale);
  const size = { w: Math.ceil(LABEL_SIZE.w * scale), h: Math.ceil(LABEL_SIZE.h * scale) };
  const bounds = { width, height };
  const nodeRects = [...boxes.values()].map(boxRect);
  const ideals = edges.map((edge) => idealPoint(edge, boxes, fontScale));
  const order = edges.map((_, index) => index).sort((a, b) => ideals[a].y - ideals[b].y || ideals[a].x - ideals[b].x || a - b);
  const placed = new Map();
  const taken = [];
  const isFree = (point) => {
    const rect = rectAt(point, size);
    return !taken.some((other) => hits(rect, other)) && !nodeRects.some((other) => hits(rect, other));
  };
  const inside = (point) => keepInside(point, size, bounds);
  order.forEach((index) => {
    const ideal = inside(ideals[index]);
    const onLine = [ideal, ...alongCurve(edges[index]).map(inside)];
    // 線上都被佔了才掃整個舞台：多數情況用不到，不必每條都排序一次格點
    const point = onLine.find(isFree) ?? gridAround(ideal, size, bounds).map(inside).find(isFree) ?? ideal;
    placed.set(index, point);
    taken.push(rectAt(point, size));
  });
  return edges.map((_, index) => placed.get(index));
}
