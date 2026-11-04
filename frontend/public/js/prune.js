// 圖太亂時剪枝：回答「這題靠哪些名字串起哪些段落」，其餘藏起來但要算清楚數量。
// 純函式、不改輸入、輸出維持輸入順序。UI 依 hidden 顯示隱藏了多少，並提供「顯示完整圖譜」。

export const MAX_NODES = 14;
export const MAX_EDGES = 24;
export const MAX_NAMES = 8;
export const MAX_NAME_PER_PASSAGE = 4;

const DEFAULT_LIMITS = {
  maxNodes: MAX_NODES,
  maxEdges: MAX_EDGES,
  maxNames: MAX_NAMES,
  maxNamePerPassage: MAX_NAME_PER_PASSAGE,
};

function countOf(nodes, kinds) {
  return nodes.filter((node) => kinds.includes(node.kind)).length;
}

function finish(graph, keptNodeIds, keptEdges) {
  const nodes = graph.nodes.filter((node) => keptNodeIds.has(node.id)).map((node) => ({ ...node }));
  const edges = graph.edges.filter((edge) => keptEdges.has(edge)).map((edge) => ({ ...edge }));
  const hidden = {
    names: countOf(graph.nodes, ['name', 'person']) - countOf(nodes, ['name', 'person']),
    passages: countOf(graph.nodes, ['passage']) - countOf(nodes, ['passage']),
    edges: graph.edges.length - edges.length,
  };
  return { nodes, edges, hidden, pruned: nodes.length < graph.nodes.length || edges.length < graph.edges.length };
}

function keepEverything(graph) {
  return finish(graph, new Set(graph.nodes.map((node) => node.id)), new Set(graph.edges));
}

// ---- 走圖圖 ----

/** mentions 邊 → {edge, passage, name}；只留連到 used 段落的（第 1 步），方向不拘，懸空的不算。 */
function usedMentions(graph, nodeById) {
  return graph.edges.flatMap((edge) => {
    if (edge.type !== 'mentions') return [];
    const ends = [nodeById.get(edge.from), nodeById.get(edge.to)];
    const passage = ends.find((node) => node?.kind === 'passage');
    const name = ends.find((node) => node?.kind === 'name');
    return passage?.used && name ? [{ edge, passage, name }] : [];
  });
}

/** 事件的 anchor 邊與它的段落一律留著：精簡圖的段落＝走到且用到，加上事件對應的段落。 */
function anchorLinks(graph, nodeById) {
  return graph.edges.flatMap((edge) => {
    if (edge.type !== 'anchor') return [];
    const ends = [nodeById.get(edge.from), nodeById.get(edge.to)];
    const passage = ends.find((node) => node?.kind === 'passage');
    const event = ends.find((node) => node?.kind === 'event');
    return passage && event ? [{ edge, passage }] : [];
  });
}

function compareRank(a, b) {
  if (a.node.inQuestion !== b.node.inQuestion) return a.node.inQuestion ? -1 : 1;
  if (a.score !== b.score) return b.score - a.score;
  return a.node.id < b.node.id ? -1 : 1;
}

/** 第 2–4 步：score = d × idf；問題名字 d≥1 或任何名字 d≥2 才有資格；問題名字優先且不受名額截斷。 */
function rankNames(graph, links, maxNames) {
  const degree = new Map();
  links.forEach(({ name }) => degree.set(name.id, (degree.get(name.id) ?? 0) + 1));
  const ranked = graph.nodes
    .filter((node) => node.kind === 'name')
    .map((node) => {
      const d = degree.get(node.id) ?? 0;
      return { node, d, score: d * (node.idf ?? 0) };
    })
    .filter(({ node, d }) => (node.inQuestion && d >= 1) || d >= 2)
    .sort(compareRank);
  const askedCount = ranked.filter(({ node }) => node.inQuestion).length;
  return ranked.slice(0, Math.max(askedCount, maxNames));
}

/** 每段留排名最前的幾條邊；問題名字的邊都留（硬性保證優先於每段上限）。 */
function capPerPassage(names, links, cap) {
  const rankOf = new Map(names.map(({ node }, index) => [node.id, index]));
  const byPassage = new Map();
  links.filter(({ name }) => rankOf.has(name.id)).forEach((link) => {
    byPassage.set(link.passage.id, [...(byPassage.get(link.passage.id) ?? []), link]);
  });
  return [...byPassage.values()].flatMap((group) => [...group]
    .sort((a, b) => rankOf.get(a.name.id) - rankOf.get(b.name.id))
    .filter(({ name }, index) => name.inQuestion || index < cap));
}

/** 第 5 步：套用每段上限，度數不夠的名字一次藏一個（排名高的先），它騰出的位子讓後面的名字補上，到穩定為止。 */
function settle(names, links, cap) {
  const kept = capPerPassage(names, links, cap);
  const degree = new Map();
  kept.forEach(({ name }) => degree.set(name.id, (degree.get(name.id) ?? 0) + 1));
  const failing = names.find(({ node }) => (degree.get(node.id) ?? 0) < (node.inQuestion ? 1 : 2));
  if (!failing) return { names, links: kept };
  return settle(names.filter((item) => item !== failing), links, cap);
}

function connectedPassages(state, anchors) {
  return new Set([...state.links, ...anchors].map(({ passage }) => passage.id));
}

function isOverBudget(state, anchors, eventCount, limits) {
  const nodes = state.names.length + connectedPassages(state, anchors).size + eventCount;
  const edges = state.links.length + anchors.length;
  return nodes > limits.maxNodes || edges > limits.maxEdges;
}

/** 超過總上限時再藏一個非問題名字：從排名最低的開始，優先選不會讓任何段落落單的。 */
function dropOneName(state, links, anchors, cap) {
  const candidates = [...state.names].reverse().filter(({ node }) => !node.inQuestion);
  if (candidates.length === 0) return null;
  const trials = candidates.map((candidate) => settle(state.names.filter((item) => item !== candidate), links, cap));
  const before = connectedPassages(state, anchors).size;
  return trials.find((trial) => connectedPassages(trial, anchors).size === before) ?? trials[0];
}

function fitBudget(names, links, anchors, eventCount, limits) {
  let state = settle(names, links, limits.maxNamePerPassage);
  while (isOverBudget(state, anchors, eventCount, limits)) {
    const next = dropOneName(state, links, anchors, limits.maxNamePerPassage);
    if (!next) break;
    state = next;
  }
  return state;
}

function compareRescue(kept) {
  return (a, b) => Number(kept.has(b.name.id)) - Number(kept.has(a.name.id))
    || (b.name.idf ?? 0) - (a.name.idf ?? 0)
    || (a.name.id < b.name.id ? -1 : 1);
}

/** 走到且用到的段落一定要上圖，說明寫的段數才等於卡片數。它的邊都被剪光時補回一個名字：
 *  已經留著的優先（不多一個節點），否則最罕見的。這是硬性檢查，優先於「葉子名字要藏」與總量上限。 */
function rescueWalked(state, links, walkedUsed) {
  return walkedUsed.reduce((current, passage) => {
    const own = links.filter((link) => link.passage.id === passage.id);
    if (own.length === 0 || current.links.some((link) => link.passage.id === passage.id)) return current;
    const kept = new Set(current.names.map(({ node }) => node.id));
    const [best] = [...own].sort(compareRescue(kept));
    const names = kept.has(best.name.id) ? current.names : [...current.names, { node: best.name }];
    return { names, links: [...current.links, best] };
  }, state);
}

function pruneWalk(graph, limits) {
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const links = usedMentions(graph, nodeById);
  const anchors = anchorLinks(graph, nodeById);
  const events = graph.nodes.filter((node) => node.kind === 'event');
  const walkedUsed = graph.nodes.filter((node) => node.kind === 'passage' && node.walked && node.used);
  const ranked = rankNames(graph, links, limits.maxNames);
  const state = rescueWalked(fitBudget(ranked, links, anchors, events.length, limits), links, walkedUsed);
  // 第 6–7 步：事件一律留；段落留還有邊的，以及走到且用到的（就算它本來就沒有任何邊）
  const keptNodeIds = new Set([
    ...events.map((node) => node.id),
    ...state.names.map(({ node }) => node.id),
    ...connectedPassages(state, anchors),
    ...walkedUsed.map((node) => node.id),
  ]);
  return finish(graph, keptNodeIds, new Set([...state.links, ...anchors].map(({ edge }) => edge)));
}

// ---- 親屬圖 ----

function adjacency(edges) {
  const neighbors = new Map();
  const link = (a, b) => neighbors.set(a, [...(neighbors.get(a) ?? []), b]);
  edges.forEach(({ from, to }) => {
    link(from, to);
    link(to, from);
  });
  return neighbors;
}

/** 從 focus 廣度優先，近的先留；這一塊走完還有名額就換下一個沒走過的節點。 */
function nearestPeople(graph, maxNodes) {
  const neighbors = adjacency(graph.edges);
  const focus = graph.nodes.filter((node) => node.focus).map((node) => node.id);
  const pending = graph.nodes.map((node) => node.id);
  const kept = new Set();
  let queue = focus;
  while (kept.size < maxNodes && (queue.length > 0 || pending.some((id) => !kept.has(id)))) {
    const [next, ...rest] = queue.length > 0 ? queue : [pending.find((id) => !kept.has(id))];
    queue = rest;
    if (!kept.has(next)) {
      kept.add(next);
      queue = [...queue, ...(neighbors.get(next) ?? [])];
    }
  }
  return kept;
}

function pruneKin(graph, limits) {
  const kept = nearestPeople(graph, limits.maxNodes);
  const edges = graph.edges.filter((edge) => kept.has(edge.from) && kept.has(edge.to));
  const connected = new Set(edges.flatMap((edge) => [edge.from, edge.to]));
  return finish(graph, connected, new Set(edges));
}

function hasUnusedPassage(graph) {
  return graph.nodes.some((node) => node.kind === 'passage' && !node.used);
}

/** prune(graph, opts?) → { nodes, edges, hidden:{names, passages, edges}, pruned }。
 *  節點與邊都沒超過上限就原樣保留；但走圖圖再小，沒用到的段落也不進精簡圖。
 *  opts 可覆寫 maxNodes／maxEdges／maxNames／maxNamePerPassage。 */
export function prune(graph, opts = {}) {
  const limits = { ...DEFAULT_LIMITS, ...opts };
  const isKin = graph.nodes.some((node) => node.kind === 'person');
  const fits = graph.nodes.length <= limits.maxNodes && graph.edges.length <= limits.maxEdges;
  if (fits && (isKin || !hasUnusedPassage(graph))) return keepEverything(graph);
  return isKin ? pruneKin(graph, limits) : pruneWalk(graph, limits);
}
