// 關聯圖周邊的文字：隱藏了多少（剪枝提示）、圖例。節點與邊在 graph-view。
import { el } from './dom.js';

const isAnchorOnly = (n) => n.kind === 'passage' && n.used && n.walked === false;

const LEGEND_ITEMS = [
  { key: 'asked', test: (n) => n.kind === 'name' && n.inQuestion, label: '問題裡的名字' },
  { key: 'name', test: (n) => n.kind === 'name' && !n.inQuestion, label: '其他名字' },
  { key: 'event', test: (n) => n.kind === 'event', label: '事件' },
  { key: 'brought', test: (n) => n.brought, label: '圖譜帶進來的段落' },
  { key: 'used', test: (n) => n.kind === 'passage' && n.used && !n.brought && !isAnchorOnly(n), label: '答案參考的段落' },
  { key: 'anchored', test: isAnchorOnly, label: '事件對應的段落' },
  { key: 'unused', test: (n) => n.kind === 'passage' && !n.used, label: '連到但沒用在答案' },
  { key: 'focus', test: (n) => n.focus, label: '問題問的人' },
];

/** 圖上有沒有卡片可畫。走圖圖沒有段落時，名字與事件自己沒有意義，不畫空框。 */
export function hasCards(graph) {
  return graph.nodes.some((node) => node.kind === 'passage' || node.kind === 'person');
}

function hiddenPhrase(view, hidden) {
  const people = view.key === 'kin' ? `${hidden.names} 位人物` : `${hidden.names} 個人名地名`;
  const parts = [hidden.names > 0 && people, hidden.passages > 0 && `${hidden.passages} 段經文`].filter(Boolean);
  return parts.length > 0 ? parts.join('、') : `${hidden.edges} 條連線`;
}

function fullGraphPhrase(view) {
  const { nodes, edges } = view.graph;
  return view.key === 'kin'
    ? `完整圖譜：${nodes.length} 位人物、${edges.length} 條關係`
    : `完整圖譜：${nodes.length} 個名字與段落、${edges.length} 條連線`;
}

export function buildHint(onToggle) {
  const text = el('span', {});
  const toggle = el('button', { type: 'button', class: 'link-button hint-toggle', on: { click: onToggle } });
  const dot = el('span', { 'aria-hidden': 'true', text: ' · ' });
  const root = el('p', { class: 'prune-hint', hidden: true }, [text, dot, toggle]);
  return { root, text, dot, toggle };
}

export function drawHint({ view, pruned, memory, hint }) {
  if (!pruned.pruned) {
    hint.root.hidden = true;
    return;
  }
  // 精簡圖一張卡都沒有（走了但沒用到）：只留「顯示完整圖譜」，沒有圖可以說「隱藏了多少」
  const isEmpty = !memory.full && !hasCards(pruned);
  hint.root.hidden = false;
  hint.text.textContent = memory.full ? fullGraphPhrase(view) : isEmpty ? '' : `為了好讀，隱藏了 ${hiddenPhrase(view, pruned.hidden)}`;
  hint.dot.hidden = isEmpty;
  hint.toggle.textContent = memory.full ? '回到精簡圖' : '顯示完整圖譜';
}

export function drawLegend(legend, nodes) {
  const seen = new Set();
  const items = LEGEND_ITEMS.filter((item) => {
    if (seen.has(item.label) || !nodes.some(item.test)) return false;
    seen.add(item.label);
    return true;
  });
  legend.replaceChildren(...items.map((item) => el('li', {}, [
    el('span', { class: `swatch swatch--${item.key}`, 'aria-hidden': 'true' }),
    document.createTextNode(item.label),
  ])));
}
