// AskResponse → 要畫的圖與說明文字。純函式，不碰 DOM。
// 說明文字一律由資料產生：圖譜沒帶進新段落就不能說有帶，這是誠實性要求。
// Name 沒有型別（路由詞表的 route_types 全是 Place，是已知錯誤資料），這裡不做人物／地點分類。
import { formatRef, parseKey } from './books.js';

const DIRECT_ROUTES = new Set(['R1', 'R2']);
const DERIVED_HEADER = '依上列資料推算：';
const CHRONO_CARDS = {
  regnal: { title: '王位順序推算', caption: '答案參考了依列王紀整理的王位順序推算。' },
  gen: { title: '家譜年歲推算', caption: '答案參考了依創世記家譜年歲推算。' },
};
const NOTES = {
  direct: '這題寫明了經文出處，直接查就找到了，不需要走知識圖譜。',
  notWalked: '這題沒有走知識圖譜。',
  nothingWalked: '知識圖譜有走，但這題沒有連到相關段落。',
  unreadable: '這題有走知識圖譜，但關聯圖暫時讀不到。',
  unreadableWithCard: '這題也走了知識圖譜，但連到的段落暫時讀不到。',
  silent: '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。',
  silentWithCard: '知識圖譜這次沒有回應。',
};
const KIN_EVIDENCE = 'kin_evidence'; // 親屬卡帶進來的出處：不是走圖，也不是直接比對問題找到的
const EMPTY_KG = { status: 'unavailable', reason: null, names: [], passages: [], mentions: [], events: [] };

function findOp(resp, op) {
  return (resp.graph_trace ?? []).find((item) => item.op === op);
}

/** 一個 source 對應的段落：章節區塊用 member_ids，其餘用 passage_id（chunk、單節都有），只留 ps:。 */
function passagesOfSource(source) {
  const members = source.member_ids ?? [];
  const ids = members.length > 0 ? members : [source.passage_id || source.id];
  return ids.filter((id) => id.startsWith('ps:'));
}

function sourceSpan(source) {
  const start = parseKey(source.start_key);
  const end = parseKey(source.end_key);
  return start && end ? (end.chapter - start.chapter) * 1000 + end.verse - start.verse : 0;
}

/** 段落 id → 開它時用的 source 索引（從 0 起算）：source 就是這段的優先，否則範圍最大的（chunk 勝過單節），
 *  同範圍取最前面。節點標的是整段範圍，點開的內容才對得上。 */
function sourceIndexByPassage(sources) {
  const best = new Map();
  sources.forEach((source, index) => {
    passagesOfSource(source).forEach((id) => {
      const rank = source.id === id ? Infinity : sourceSpan(source);
      if (!best.has(id) || rank > best.get(id).rank) best.set(id, { index, rank });
    });
  });
  return new Map([...best].map(([id, { index }]) => [id, index]));
}

/** trace 的 passages／confirmed 可能是 ps: 或 ck: 等 source id，一律對回段落 id。 */
function toPassageIds(ids, sources) {
  return new Set((ids ?? []).flatMap((id) => {
    if (id.startsWith('ps:')) return [id];
    const source = sources.find((item) => item.id === id);
    return source ? passagesOfSource(source) : [];
  }));
}

function compareVerse(a, b) {
  return a.chapter - b.chapter || a.verse - b.verse;
}

/** 段落和它的來源重疊的範圍：只有 chunk 來源時，圖譜的段落比點開看得到的長，卡片要標看得到的。
 *  對不起來（壞資料）就退回段落自己的範圍。verses 是來源比段落大（章節區塊）時要高亮的節。 */
function visibleRange(passage, source) {
  const whole = { startKey: passage.start_key, endKey: passage.end_key };
  const [ps, pe, ss, se] = [passage.start_key, passage.end_key, source?.start_key, source?.end_key].map(parseKey);
  if (!ps || !pe || !ss || !se) return whole;
  const start = compareVerse(ps, ss) > 0 ? ps : ss;
  const end = compareVerse(pe, se) < 0 ? pe : se;
  if (compareVerse(start, end) > 0) return whole;
  const range = {
    startKey: start === ps ? passage.start_key : source.start_key,
    endKey: end === pe ? passage.end_key : source.end_key,
  };
  const isWider = compareVerse(ss, start) < 0 || compareVerse(end, se) < 0;
  return isWider && ss.chapter === se.chapter ? { ...range, verses: { verse: start.verse, verseEnd: end.verse } } : range;
}

function passageNode(passage, usedAt, broughtIds, sources) {
  const sourceIndex = usedAt.get(passage.id);
  const used = sourceIndex !== undefined;
  const { startKey, endKey, verses } = visibleRange(passage, sources[sourceIndex]);
  const ref = formatRef(startKey, endKey);
  return {
    id: passage.id,
    kind: 'passage',
    label: passage.title || ref,
    ref,
    walked: Boolean(passage.walked),
    used,
    brought: used && broughtIds.has(passage.id),
    ...(used ? { sourceIndex } : {}),
    ...(verses ? { verses } : {}),
  };
}

function nameNode(name) {
  return { id: name.id, kind: 'name', label: name.label, inQuestion: Boolean(name.in_question), df: name.df, idf: name.idf };
}

function mentionEdges(mentions, passageIds, nameIds) {
  const seen = new Set();
  return mentions.flatMap(([from, to]) => {
    const key = `${from}|${to}`;
    if (seen.has(key) || !passageIds.has(from) || !nameIds.has(to)) return [];
    seen.add(key);
    return [{ from, to, type: 'mentions' }];
  });
}

/** 圖上只畫圖譜真正走到的段落，否則讀者會以為全是圖譜找到的。
 *  沒走到但有事件的段落也畫，但只有 anchor 那條邊：事件對應是查表，不是走圖。
 *  名字只留連得到走到段落的，不留懸空的圓。 */
function buildWalkGraph(kg, sources, broughtIds) {
  const usedAt = sourceIndexByPassage(sources);
  const namedEvents = kg.events.filter((event) => event.name);
  const anchored = new Set(namedEvents.map((event) => event.passage));
  const passages = kg.passages
    .filter((passage) => passage.walked || anchored.has(passage.id))
    .map((passage) => passageNode(passage, usedAt, broughtIds, sources));
  const walkedIds = new Set(passages.filter((node) => node.walked).map((node) => node.id));
  const mentions = mentionEdges(kg.mentions, walkedIds, new Set(kg.names.map((name) => name.id)));
  const linkedNames = new Set(mentions.map((edge) => edge.to));
  const passageIds = new Set(passages.map((node) => node.id));
  const anchors = namedEvents
    .filter((event) => passageIds.has(event.passage))
    .map((event) => ({ from: event.id, to: event.passage, type: 'anchor' }));
  return {
    nodes: [
      ...passages,
      ...kg.names.filter((name) => linkedNames.has(name.id)).map(nameNode),
      ...namedEvents.map((event) => ({ id: event.id, kind: 'event', label: event.name })),
    ],
    edges: [...mentions, ...anchors],
  };
}

function quoted(labels) {
  return labels.map((label) => `「${label}」`).join('');
}

/** 段數看 kg.passages 的 walked，不看 trace 的 confirmed：章節區塊沒有 passage_id，
 *  它的成員段落永遠不會出現在 confirmed，但圖上確實是走到且用到。
 *  剪枝保證走到且用到的段落都留著，所以這個數字就是精簡圖上的卡片數。 */
function walkCaption(graph, askedNames) {
  const passages = graph.nodes.filter((node) => node.kind === 'passage');
  const brought = passages.filter((node) => node.brought);
  if (brought.length > 0) {
    const start = askedNames.length > 0 ? `問題裡的${quoted(askedNames)}` : '最接近問題的經文';
    return `知識圖譜從${start}出發，順著經文共同提到的人名地名往外找；${quoted(brought.map((node) => node.label))}單看問題的字句找不到，是這樣連過去才找到的。`;
  }
  const reached = passages.filter((node) => node.used && node.walked).length;
  if (reached > 0) return `知識圖譜順著人名地名，也連到答案參考的 ${reached} 段經文；這題沒有多找到新段落。`;
  return '知識圖譜有走，但連到的段落沒有用在答案裡。';
}

/** 用到但不在圖上的段落。「親屬關係的出處」要分開算：它不是走圖，也不是直接比對問題找到的。 */
function offGraphCounts(sources, graph, walkedIds) {
  const onGraph = new Set(graph.nodes.map((node) => node.id));
  const labelsById = new Map();
  sources.forEach((source) => passagesOfSource(source).forEach((id) => {
    labelsById.set(id, [...(labelsById.get(id) ?? []), ...(source.found_by ?? [''])]);
  }));
  const missing = [...labelsById].filter(([id]) => !onGraph.has(id) && !walkedIds.has(id));
  const kin = missing.filter(([, labels]) => labels.every((label) => label === KIN_EVIDENCE)).length;
  return { total: missing.length, kin, direct: missing.length - kin };
}

function offGraphNote({ direct, kin }) {
  if (direct === 0 && kin === 0) return undefined;
  if (kin === 0) return `另有 ${direct} 段是直接比對問題找到的，沒有經過圖譜，列在經文來源。`;
  if (direct === 0) return `另有 ${kin} 段是親屬關係的出處，列在經文來源。`;
  return `另有 ${direct} 段是直接比對問題找到的，沒有經過圖譜；${kin} 段是親屬關係的出處。都列在經文來源。`;
}

function buildWalkView(resp, kg, walkOp) {
  if (kg.status !== 'ok' || !walkOp || (walkOp.walked ?? []).length === 0) return [];
  const sources = resp.sources ?? [];
  const graph = buildWalkGraph(kg, sources, toPassageIds(walkOp.passages, sources));
  const asked = kg.names.filter((name) => name.in_question).map((name) => name.label);
  const counts = offGraphCounts(sources, graph, new Set(walkOp.walked));
  const note = offGraphNote(counts);
  return [{
    key: 'walk',
    title: '答案怎麼找到的',
    graph,
    caption: walkCaption(graph, asked),
    offGraph: counts.total,
    ...(note ? { offGraphNote: note } : {}),
  }];
}

function buildKinView(resp) {
  const op = findOp(resp, 'kin_card');
  if (!op || op.injected !== 'prompt') return [];
  const focus = new Set(resp.aux_card?.kind === 'kin' ? resp.aux_card.kings ?? [] : []);
  const nodes = op.nodes.flatMap((id, index) => (op.names[index]
    ? [{ id, kind: 'person', label: op.names[index], focus: focus.has(id) }]
    : []));
  const ids = new Set(nodes.map((node) => node.id));
  const edges = op.edges
    .filter(([from, , to]) => ids.has(from) && ids.has(to))
    .map(([from, type, to, verseKey]) => ({ from, to, type, verseKey, ref: formatRef(verseKey) }));
  if (nodes.length === 0) return [];
  return [{ key: 'kin', title: '親屬關係', graph: { nodes, edges }, caption: '答案參考了下面的親屬關係，每條都有經文出處。' }];
}

function derivedLines(text) {
  const at = text.indexOf(DERIVED_HEADER);
  const derived = at < 0 ? '' : text.slice(at + DERIVED_HEADER.length).trim();
  return derived || text;
}

function buildChronoView(resp) {
  const card = CHRONO_CARDS[resp.aux_card?.kind];
  if (!card) return [];
  return [{ key: 'chrono', title: card.title, text: derivedLines(resp.aux_card.text), caption: card.caption }];
}

function noteFor(resp, kg, walkOp, views) {
  if (views.some((view) => view.key === 'walk')) return undefined;
  if (kg.status === 'not_walked') return DIRECT_ROUTES.has(resp.route) ? NOTES.direct : NOTES.notWalked;
  if (kg.status === 'ok') return NOTES.nothingWalked;
  if (kg.status === 'unavailable' && walkOp && !walkOp.skip_reason) {
    return views.length > 0 ? NOTES.unreadableWithCard : NOTES.unreadable;
  }
  return views.length > 0 ? NOTES.silentWithCard : NOTES.silent;
}

/** AskResponse → { views:[{key,title,graph?,text?,caption,offGraph?,offGraphNote?}], note? }；順序：親屬、推算、走圖。 */
export function buildViews(resp) {
  const kg = resp.kg ?? EMPTY_KG;
  const walkOp = findOp(resp, 'graph_walk');
  const views = [...buildKinView(resp), ...buildChronoView(resp), ...buildWalkView(resp, kg, walkOp)];
  const note = noteFor(resp, kg, walkOp, views);
  return note === undefined ? { views } : { views, note };
}
