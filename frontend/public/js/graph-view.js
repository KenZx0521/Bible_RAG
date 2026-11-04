// 關聯圖面板：走圖、親屬、推算三種檢視與分段切換。
// 節點是真的 <button>（Tab 可到、Enter 可按），邊在底下一張 SVG。位置只靠 CSS 變數＋transform。
import { el, findRedrawn } from './dom.js';
import { placeEdgeLabels } from './edge-labels.js';
import { buildHint, drawHint, drawLegend, hasCards } from './graph-notes.js';
import { layout } from './layout.js';
import { prune } from './prune.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const MIN_STAGE_WIDTH = 240;
const BASE_FONT_PX = 16;
const MAX_LISTED = 8;

const RELATIONS = Object.freeze({
  PARENT_OF: { label: '父母', phrase: (a, b) => `${a} 是 ${b} 的父母` },
  SPOUSE_OF: { label: '配偶', phrase: (a, b) => `${a} 和 ${b} 是配偶` },
  SIBLING_OF: { label: '手足', phrase: (a, b) => `${a} 和 ${b} 是手足` },
});

const IDLE_TEXT = Object.freeze({
  walk: '點名字看它出現在哪些經文，點段落讀經文。',
  walkNoNames: '點段落讀經文。',
  kin: '點「父母」這類關係字，可以讀它的經文出處。',
});

function idleText(view, graph) {
  const hasNames = graph.nodes.some((node) => node.kind === 'name');
  return view.key === 'walk' && !hasNames ? IDLE_TEXT.walkNoNames : IDLE_TEXT[view.key];
}

// ---- 節點與邊 ----

/** 用在答案裡，但不是走到的：事件查表對應過來的段落。 */
function isAnchorOnly(node) {
  return node.kind === 'passage' && node.used && node.walked === false;
}

function passageRole(node) {
  if (node.brought) return '圖譜帶進來的段落';
  if (isAnchorOnly(node)) return '事件對應的段落，答案有參考';
  return node.used ? '答案參考的段落' : '連到但沒有用在答案裡的段落';
}

function nodeClass(node, box) {
  return [
    'node',
    `node--${node.kind}`,
    (node.inQuestion || node.focus) && 'is-asked',
    node.brought && 'is-brought',
    node.kind === 'passage' && !node.used && 'is-unused',
    isAnchorOnly(node) && 'is-anchored',
    box.compact && 'is-compact',
  ].filter(Boolean).join(' ');
}

function labelList(labels) {
  const shown = labels.slice(0, MAX_LISTED).join('、');
  return labels.length > MAX_LISTED ? `${shown} 等` : shown;
}

/** 邊的 SVG 對報讀器是隱藏的，所以關係要寫進標籤：名字說幾段，段落說提到誰。 */
function nodeDescription(node, linked) {
  if (node.kind === 'name') return `${node.label}${node.inQuestion ? '，問題裡的名字' : ''}，出現在 ${linked.length} 段經文。按下看是哪幾段`;
  if (node.kind === 'event') return `${node.label}，事件，對應 ${linked.length} 段經文。按下看是哪幾段`;
  if (node.kind === 'person') return `${node.label}${node.focus ? '，問題問的人' : ''}，連到 ${linked.length} 位親屬。按下看是哪幾位`;
  const names = linked.length > 0 && !isAnchorOnly(node) ? `，提到 ${labelList(linked)}` : '';
  return `${node.label}，${node.ref}，${passageRole(node)}${names}。開啟經文`;
}

function nodeRef(ref) {
  const at = ref.lastIndexOf(' ') + 1;
  return el('span', { class: 'node-ref' }, [
    el('span', { class: 'node-ref-book', text: ref.slice(0, at) }),
    document.createTextNode(ref.slice(at)),
  ]);
}

function nodeContent(node) {
  if (node.kind !== 'passage') return [el('span', { class: 'node-title', text: node.label })];
  return [
    node.brought ? el('span', { class: 'node-flag', text: '圖譜帶進來' }) : null,
    el('span', { class: 'node-title', text: node.label }),
    nodeRef(node.ref),
  ];
}

function placeBox(element, { x, y, w, h }) {
  element.style.setProperty('--x', `${x}px`);
  element.style.setProperty('--y', `${y}px`);
  element.style.setProperty('--w', `${w}px`);
  element.style.setProperty('--h', `${h}px`);
}

function nodeButton(node, box, linked, onPress) {
  const fullText = node.ref ? `${node.label}（${node.ref}）` : node.label;
  const isToggle = node.kind !== 'passage';
  const button = el('button', {
    type: 'button',
    class: nodeClass(node, box),
    title: fullText,
    'aria-label': nodeDescription(node, linked),
    'aria-pressed': isToggle ? 'false' : null,
    'data-id': node.id,
    'data-kind': node.kind,
    on: { click: (event) => onPress(node, event.currentTarget) },
  }, nodeContent(node));
  placeBox(button, box);
  return button;
}

function edgeClass(edge, nodeById) {
  const touchesBrought = nodeById.get(edge.from)?.brought || nodeById.get(edge.to)?.brought;
  return ['edge', edge.type === 'anchor' && 'edge--anchor', touchesBrought && 'edge--brought'].filter(Boolean).join(' ');
}

function edgeLayer(placed, nodeById) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'graph-edges');
  svg.setAttribute('width', String(placed.width));
  svg.setAttribute('height', String(placed.height));
  svg.setAttribute('aria-hidden', 'true');
  placed.edges.forEach((edge) => {
    const path = document.createElementNS(SVG_NS, 'path');
    path.setAttribute('d', edge.path);
    path.setAttribute('class', edgeClass(edge, nodeById));
    path.dataset.from = edge.from;
    path.dataset.to = edge.to;
    svg.append(path);
  });
  return svg;
}

function edgeLabel(edge, { x, y }, nodeById, onOpenVerse) {
  const relation = RELATIONS[edge.type];
  const phrase = relation.phrase(nodeById.get(edge.from).label, nodeById.get(edge.to).label);
  const label = el('button', {
    type: 'button',
    class: 'edge-label',
    text: relation.label,
    title: `${phrase}（${edge.ref}）`,
    'aria-label': `${phrase}，開啟出處 ${edge.ref}`,
    'data-from': edge.from,
    'data-to': edge.to,
    'data-type': edge.type,
    on: { click: (event) => onOpenVerse(edge.verseKey, event.currentTarget) },
  });
  label.style.setProperty('--x', `${x}px`);
  label.style.setProperty('--y', `${y}px`);
  return label;
}

// ---- 高亮 ----

function focusMessage(node, linked) {
  const count = linked.length;
  const tail = count > 0 ? `：${labelList(linked.map((item) => item.label))}` : '';
  if (node.kind === 'person') return `${node.label} 連到 ${count} 位親屬${tail}`;
  if (node.kind === 'event') return `${node.label} 對應 ${count} 段經文${tail}`;
  return `${node.label} 出現在 ${count} 段經文${tail}`;
}

function applyFocus(ctx) {
  const graph = ctx.graph();
  const focused = graph.nodes.find((node) => node.id === ctx.focusId);
  const linked = focused ? graph.edges.filter((edge) => edge.from === focused.id || edge.to === focused.id) : [];
  const near = new Set(linked.flatMap((edge) => [edge.from, edge.to]));
  near.delete(focused?.id);
  ctx.stage.classList.toggle('has-focus', Boolean(focused));
  ctx.stage.querySelectorAll('.node').forEach((button) => {
    const isSelected = button.dataset.id === focused?.id;
    button.classList.toggle('is-linked', near.has(button.dataset.id));
    button.classList.toggle('is-selected', isSelected);
    if (button.hasAttribute('aria-pressed')) button.setAttribute('aria-pressed', String(isSelected));
  });
  ctx.stage.querySelectorAll('[data-from]').forEach((edge) => {
    edge.classList.toggle('is-linked', edge.dataset.from === focused?.id || edge.dataset.to === focused?.id);
  });
  const message = focused ? focusMessage(focused, graph.nodes.filter((node) => near.has(node.id))) : idleText(ctx.view, graph);
  ctx.status.text.textContent = message;
  ctx.status.text.title = message;
  ctx.status.clear.hidden = !focused;
}

function clearFocus(ctx) {
  if (!ctx.focusId) return;
  ctx.focusId = null;
  applyFocus(ctx);
}

// ---- 繪製 ----

function rootFontScale() {
  return parseFloat(getComputedStyle(document.documentElement).fontSize) / BASE_FONT_PX;
}

/** 節點 id → 相鄰節點的標籤；同一對有兩條邊（例如又是配偶又是手足）只算一次。 */
function linkedLabels(graph) {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const near = new Map(graph.nodes.map((node) => [node.id, new Set()]));
  graph.edges.forEach(({ from, to }) => {
    near.get(from).add(to);
    near.get(to).add(from);
  });
  return new Map([...near].map(([id, others]) => [id, [...others].map((other) => nodeById.get(other).label)]));
}

/** 走圖圖：由左欄到右欄、由上到下。親屬圖：世代由上而下，人物與關係字照畫面位置穿插。 */
function compareTabOrder(isKin) {
  const byColumn = (a, b) => a.x - b.x || a.y - b.y;
  const byRow = (a, b) => a.y - b.y || a.x - b.x;
  return isKin ? byRow : byColumn;
}

function stageItems(ctx, graph, placed, fontScale) {
  const boxes = new Map(placed.nodes.map((box) => [box.id, box]));
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const linked = linkedLabels(graph);
  const nodes = graph.nodes.map((node) => {
    const box = boxes.get(node.id);
    return { x: box.x, y: box.y + box.h / 2, element: nodeButton(node, box, linked.get(node.id), ctx.onPress) };
  });
  const related = placed.edges.filter((edge) => RELATIONS[edge.type]);
  const points = placeEdgeLabels(related, boxes, { width: placed.width, height: placed.height, fontScale });
  const labels = related.map((edge, index) => {
    const point = points[index];
    return { ...point, element: edgeLabel(edge, point, nodeById, ctx.handlers.onVerseKey) };
  });
  return [...nodes, ...labels].sort(compareTabOrder(placed.mode === 'kin')).map((item) => item.element);
}

function drawStage(ctx) {
  const graph = ctx.graph();
  // 沒有卡片就整塊收起來，不畫空框；舊的節點也要清掉
  const isDrawable = hasCards(graph);
  ctx.canvas.hidden = !isDrawable;
  ctx.legend.hidden = !isDrawable;
  if (!isDrawable) ctx.stage.replaceChildren();
  const rawWidth = ctx.stage.clientWidth;
  if (rawWidth === 0) return;
  const fontScale = rootFontScale();
  const placed = layout(graph, { width: Math.max(MIN_STAGE_WIDTH, rawWidth), fontScale });
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const hadFocus = ctx.stage.contains(document.activeElement) ? document.activeElement : null;
  ctx.scroller.style.setProperty('--stage-height', `${placed.height}px`); // 舞台繼承；捲動區的最小高度也要看它
  ctx.stage.replaceChildren(edgeLayer(placed, nodeById), ...stageItems(ctx, graph, placed, fontScale));
  ctx.drawnWidth = rawWidth;
  ctx.drawnScale = fontScale;
  applyFocus(ctx);
  if (hadFocus) findRedrawn(hadFocus)?.focus({ preventScroll: true });
}

function setFull(ctx, isFull) {
  ctx.memory.full = isFull;
  ctx.focusId = null;
  ctx.scroller.scrollTop = 0;
  ctx.body.classList.toggle('is-full', isFull);
  drawHint(ctx);
  drawStage(ctx);
  drawLegend(ctx.legend, ctx.graph().nodes);
}

function pressNode(ctx, node, button) {
  if (node.kind === 'passage') {
    ctx.handlers.onPassage(node, button);
    return;
  }
  ctx.focusId = ctx.focusId === node.id ? null : node.id;
  applyFocus(ctx);
}

function buildStatus(ctx) {
  const text = el('p', { class: 'graph-status', 'aria-live': 'polite' });
  const clear = el('button', {
    type: 'button',
    class: 'link-button graph-clear',
    text: '還原',
    hidden: true,
    on: {
      click: () => {
        const selected = ctx.stage.querySelector('.node.is-selected');
        clearFocus(ctx);
        selected?.focus();
      },
    },
  });
  return { root: el('div', { class: 'graph-status-row' }, [text, clear]), text, clear };
}

/** 高亮怎麼退出：點頁面任何空白處或按 Esc。按鈕、連結有自己的事；面板開著時 Esc 只關面板。 */
function listenForDismiss(ctx) {
  const onClick = (event) => {
    if (!event.target.closest('button, a, input, dialog')) clearFocus(ctx);
  };
  const onKeydown = (event) => {
    if (event.key === 'Escape' && !event.target.closest?.('dialog')) clearFocus(ctx);
  };
  document.addEventListener('click', onClick);
  document.addEventListener('keydown', onKeydown);
  return () => {
    document.removeEventListener('click', onClick);
    document.removeEventListener('keydown', onKeydown);
  };
}

/** 畫一張圖；回傳收尾函式（切檢視或換題時呼叫）。 */
function mountGraph(body, view, handlers, memory) {
  const stage = el('div', { class: 'graph-stage', role: 'group', 'aria-label': `${view.title}，關聯圖` });
  const scroller = el('div', { class: 'graph-scroll' }, [stage]);
  const pruned = prune(view.graph);
  const ctx = {
    view, handlers, memory, pruned, body, stage, scroller,
    legend: el('ul', { class: 'graph-legend', 'aria-label': '圖例' }),
    focusId: null,
    drawnWidth: 0,
    drawnScale: 0,
    graph: () => (memory.full ? view.graph : pruned),
    onPress: (node, button) => pressNode(ctx, node, button),
    hint: buildHint(() => setFull(ctx, !memory.full)),
  };
  ctx.status = buildStatus(ctx);
  // 狀態列和圖包在同一層：單欄時它黏在視窗底，但不會往上蓋到說明與切換鈕；桌機時它排在圖的上方
  ctx.canvas = el('div', { class: 'graph-canvas' }, [scroller, ctx.status.root]);
  const offGraph = view.offGraphNote ? el('p', { class: 'graph-offgraph', text: view.offGraphNote }) : null;
  body.append(...[el('p', { class: 'graph-caption', text: view.caption }), ctx.hint.root, ctx.canvas, offGraph, ctx.legend].filter(Boolean));
  setFull(ctx, memory.full);
  const stopListening = listenForDismiss(ctx);
  let frame = 0;
  const observer = new ResizeObserver(() => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      if (stage.clientWidth !== ctx.drawnWidth || rootFontScale() !== ctx.drawnScale) drawStage(ctx);
    });
  });
  observer.observe(scroller);
  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
    stopListening();
  };
}

// ---- 推算文字 ----

function chronoRow(line) {
  const at = line.indexOf('：');
  if (at < 0) return el('li', { class: 'chrono-row' }, [el('span', { class: 'chrono-value', text: line })]);
  return el('li', { class: 'chrono-row' }, [
    el('span', { class: 'chrono-label', text: line.slice(0, at) }),
    el('span', { class: 'chrono-value', text: line.slice(at + 1) }),
  ]);
}

function mountChrono(body, view) {
  const lines = view.text.split('\n').map((line) => line.trim()).filter(Boolean);
  body.append(el('p', { class: 'graph-caption', text: view.caption }), el('ol', { class: 'chrono' }, lines.map(chronoRow)));
  return () => {};
}

// ---- 面板 ----

function segmentButtons(views, onSelect) {
  const buttons = views.map((view, index) => el('button', {
    type: 'button',
    class: 'segment',
    text: view.title,
    'aria-pressed': String(index === 0),
    on: {
      click: (event) => {
        if (event.currentTarget.getAttribute('aria-pressed') === 'true') return;
        buttons.forEach((button) => button.setAttribute('aria-pressed', String(button === event.currentTarget)));
        onSelect(view);
      },
    },
  }));
  return el('div', { class: 'segments', role: 'group', 'aria-label': '切換檢視' }, buttons);
}

/** mountGraphPanel(host, {views, note}, {onPassage, onVerseKey, onSkip}) → 收尾函式。 */
export function mountGraphPanel(host, { views, note }, handlers) {
  const noteNode = note ? el('p', { class: 'graph-note', text: note }) : null;
  const titleText = views.length === 1 ? views[0].title : '答案怎麼找到的';
  const heading = el('h2', { class: views.length > 1 ? 'visually-hidden' : 'slug', text: titleText });
  const body = el('div', { class: 'graph-body' });
  const memories = new Map(views.map((view) => [view.key, { full: false }]));
  let stop = () => {};
  const show = (view) => {
    stop();
    body.replaceChildren();
    body.classList.remove('is-full');
    stop = view.graph ? mountGraph(body, view, handlers, memories.get(view.key)) : mountChrono(body, view);
  };
  const segments = views.length > 1 ? segmentButtons(views, show) : null;
  // 圖是好奇才看的次要內容，鍵盤使用者不必穿過每個節點才到經文來源
  const skip = views.some((view) => view.graph)
    ? el('button', { type: 'button', class: 'link-button skip-link', text: '跳到經文來源', on: { click: handlers.onSkip } })
    : null;
  host.replaceChildren(el('section', { class: 'graph-panel' }, [skip, heading, segments, views.length > 0 ? body : null, noteNode]));
  if (views.length > 0) show(views[0]);
  return () => stop();
}
