// 答案渲染：只支援 **粗體**、「*   」列表（含縮排巢狀）、段落，引用變成按鈕。
// 答案是 LLM 輸出，一律 createElement／textContent，不准 innerHTML。
// parseAnswer、splitBold 是純函式（不碰 DOM），可在 Node 測試。
import { findCitations, resolveCitation } from './citations.js';
import { el } from './dom.js';

const LIST_ITEM = /^([ \t]*)\*[ \t]+(.*)$/;
const STEP_LINE = /^(\d+[.、])\s*(.*)$/;
const ONLY_BOLD = /^\*\*[^*]+\*\*$/;
const BOLD = /\*\*(.+?)\*\*/g;
const TAB_WIDTH = 4;
const OPENING_MARK = /[（(「『《【]$/u;
const CLOSING_MARKS = /^[）)」』》】]*[，。；：、！？]?/u;
// 模型偶爾把箭頭寫成 LaTeX（$\leftarrow$）。只換整段包在 $…$ 裡、又認得的符號，其他原樣留著。
const LATEX_SYMBOL = /\$\s*\\([A-Za-z]+)\s*\$/g;
const LATEX_SYMBOLS = new Map([
  ['leftarrow', '←'], ['gets', '←'], ['rightarrow', '→'], ['to', '→'],
  ['Leftarrow', '⇐'], ['Rightarrow', '⇒'], ['times', '×'],
]);

const withSymbols = (text) => text.replace(LATEX_SYMBOL, (raw, name) => LATEX_SYMBOLS.get(name) ?? raw);

function classify(raw) {
  const line = raw.trimEnd();
  if (line.trim() === '') return { kind: 'blank' };
  const item = LIST_ITEM.exec(line);
  if (item) return { kind: 'item', level: item[1].replaceAll('\t', ' '.repeat(TAB_WIDTH)).length, text: item[2] };
  return { kind: 'text', text: line.trim(), indented: /^\s/.test(line) };
}

const withLast = (blocks, last) => [...blocks.slice(0, -1), last];

function addItem(blocks, last, { level, text }) {
  const entry = { level, text };
  if (last?.type === 'list') return withLast(blocks, { ...last, items: [...last.items, entry] });
  return [...blocks, { type: 'list', items: [entry] }];
}

function addText(blocks, last, token, previous) {
  const continues = previous !== null && previous.kind !== 'blank';
  if (continues && last?.type === 'paragraph') return withLast(blocks, { ...last, lines: [...last.lines, token.text] });
  if (continues && last?.type === 'list' && token.indented) {
    const tail = last.items[last.items.length - 1];
    const items = [...last.items.slice(0, -1), { ...tail, text: `${tail.text} ${token.text}` }];
    return withLast(blocks, { ...last, items });
  }
  return [...blocks, { type: 'paragraph', lines: [token.text] }];
}

/** 文字 → [{type:'paragraph',lines}|{type:'list',items:[{level,text}]}]。列表項之間的空行不會斷開列表。 */
export function parseAnswer(text) {
  const start = { blocks: [], previous: null };
  const { blocks } = withSymbols(String(text ?? '')).split(/\r?\n/).map(classify).reduce(({ blocks: done, previous }, token) => {
    const last = done[done.length - 1];
    if (token.kind === 'blank') return { blocks: done, previous: token };
    const next = token.kind === 'item' ? addItem(done, last, token) : addText(done, last, token, previous);
    return { blocks: next, previous: token };
  }, start);
  return blocks;
}

/** 'a **b** c' → [{text:'a ',bold:false},{text:'b',bold:true},{text:' c',bold:false}]；落單的星號留成文字。 */
export function splitBold(text) {
  const parts = [];
  let at = 0;
  for (const match of text.matchAll(BOLD)) {
    if (match.index > at) parts.push({ text: text.slice(at, match.index), bold: false });
    parts.push({ text: match[1], bold: true });
    at = match.index + match[0].length;
  }
  return at < text.length ? [...parts, { text: text.slice(at), bold: false }] : parts;
}

/** 依縮排把平的項目疊成樹：比第一項深的都歸到前一項底下。 */
export function nestItems(items) {
  if (items.length === 0) return [];
  const base = items[0].level;
  const grouped = items.reduce((tree, item) => {
    const parent = tree[tree.length - 1];
    if (!parent || item.level <= base) return [...tree, { text: item.text, flat: [] }];
    return withLast(tree, { ...parent, flat: [...parent.flat, item] });
  }, []);
  return grouped.map(({ text, flat }) => ({ text, children: nestItems(flat) }));
}

function citeButton(citation, target, ctx) {
  return el('button', {
    type: 'button',
    class: 'cite',
    text: citation.raw,
    'aria-label': `開啟經文 ${citation.raw}`,
    on: { click: (event) => ctx.onCitation(target, event.currentTarget) },
  });
}

const textNode = (text) => (text ? document.createTextNode(text) : null);

/** 按鈕是 inline-block，整顆換行時會把「（」留在上一行；所以把括號與句讀和它綁成一組，一起換行。
 *  這組是 inline-block 且不超過欄寬：字級調大、放不下一行時在組內折行，不會撐破版面。 */
function citeGroup(citation, target, ctx, open, close) {
  return el('span', { class: 'cite-group' }, [textNode(open), citeButton(citation, target, ctx), textNode(close)]);
}

/** 解析不了的引用留成文字，不准變按鈕。 */
function withCitations(text, ctx) {
  const parts = [];
  let at = 0;
  for (const citation of findCitations(text)) {
    const target = resolveCitation(citation, ctx.sources);
    if (target) {
      const before = text.slice(at, citation.start);
      const open = OPENING_MARK.exec(before)?.[0] ?? '';
      const close = CLOSING_MARKS.exec(text.slice(citation.end))[0];
      parts.push(textNode(before.slice(0, before.length - open.length)), citeGroup(citation, target, ctx, open, close));
      at = citation.end + close.length;
    }
  }
  return [...parts, textNode(text.slice(at))].filter(Boolean);
}

function inline(text, ctx) {
  return splitBold(text).flatMap(({ text: run, bold }) => {
    const nodes = withCitations(run, ctx);
    return bold ? [el('strong', {}, nodes)] : nodes;
  });
}

/** 「1.  根據…」保留原文的編號，只把它吊在左邊，換行才對得齊。 */
function answerLine(line, ctx) {
  const step = STEP_LINE.exec(line);
  if (!step) return el('span', { class: 'answer-line' }, inline(line, ctx));
  return el('span', { class: 'answer-line is-step' }, [
    el('span', { class: 'step-no', text: step[1] }),
    el('span', {}, inline(step[2], ctx)),
  ]);
}

function paragraph(lines, ctx) {
  const isLead = lines.length === 1 && ONLY_BOLD.test(lines[0]);
  return el('p', { class: isLead ? 'answer-lead' : null }, lines.map((line) => answerLine(line, ctx)));
}

function listOf(tree, ctx) {
  return el('ul', { class: 'answer-list' }, tree.map(({ text, children }) => el('li', {}, [
    ...inline(text, ctx),
    children.length > 0 ? listOf(children, ctx) : null,
  ])));
}

/** renderAnswer(text, {sources, onCitation}) → DOM 節點陣列。onCitation(target, button) 由呼叫端開面板。 */
export function renderAnswer(text, ctx) {
  return parseAnswer(text).map((block) => (block.type === 'list'
    ? listOf(nestItems(block.items), ctx)
    : paragraph(block.lines, ctx)));
}
