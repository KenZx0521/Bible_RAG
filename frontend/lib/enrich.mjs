// backend 回應 + Neo4j → AskResponse。純邏輯：Neo4j 與 health 都由呼叫端注入。
export const KG_QUERY_FAILED = 'neo4j_query_failed';

const asArray = (value) => (Array.isArray(value) ? value : []);
const hasPrefix = (prefix) => (id) => typeof id === 'string' && id.startsWith(prefix);
const isNameId = hasPrefix('nm:');
const isPassageId = hasPrefix('ps:');
const unique = (items) => [...new Set(items)];

export function emptyKg(status, reason = null) {
  return { status, reason, names: [], passages: [], mentions: [], events: [] };
}

export function findWalk(trace) {
  return asArray(trace).find((op) => op?.op === 'graph_walk') ?? null;
}

/** nodes 是「走過的名字＋段落」，前 names.length 個才是名字；seeds 裡的 nm: 是問題裡的名字。 */
export function nameTargets(walk) {
  const crossed = asArray(walk.nodes).slice(0, asArray(walk.names).length);
  const fromQuestion = asArray(walk.seeds).filter(isNameId);
  return {
    ids: unique([...crossed, ...fromQuestion].filter(isNameId)),
    inQuestion: new Set(fromQuestion),
  };
}

function sourcePassages(source) {
  const members = asArray(source?.member_ids);
  return members.length > 0 ? members : [source?.passage_id || source?.id];
}

export function passageTargets(walk, sources) {
  const candidates = [...asArray(walk.walked), ...asArray(sources).flatMap(sourcePassages)];
  return unique(candidates.filter(isPassageId));
}

/** 只有帶 edges 的 event_registry 才列；每條 anchor 邊一筆。 */
export function eventAnchors(trace) {
  return asArray(trace)
    .filter((op) => op?.op === 'event_registry')
    .flatMap((op) => asArray(op.edges))
    .filter((edge) => Array.isArray(edge) && edge[1] === 'anchor')
    .map(([id, , passage]) => ({ id, passage }));
}

async function resolveBuildId(sources, healthBuildId, log) {
  const fromSource = sources[0]?.build_id;
  if (fromSource) return fromSource;
  try {
    return (await healthBuildId()) ?? null;
  } catch (err) {
    log.warn('取不到 build_id', { name: err?.name });
    return null;
  }
}

async function queryKg({ walk, trace, sources, buildId, kg }) {
  const names = nameTargets(walk);
  const passageIds = passageTargets(walk, sources);
  const anchors = eventAnchors(trace);
  const [nameRows, passageRows, mentions, eventRows] = await Promise.all([
    kg.names(buildId, names.ids),
    kg.passages(buildId, passageIds),
    kg.mentions(buildId, passageIds, names.ids),
    kg.events(buildId, unique(anchors.map((anchor) => anchor.id))),
  ]);
  const walked = new Set(asArray(walk.walked));
  const eventNames = new Map(eventRows.map((row) => [row.id, row.name]));
  return {
    ...emptyKg('ok'),
    names: nameRows.map((row) => ({ ...row, in_question: names.inQuestion.has(row.id) })),
    passages: passageRows.map((row) => ({ ...row, walked: walked.has(row.id) })),
    mentions,
    events: anchors
      .filter((anchor) => eventNames.get(anchor.id))
      .map(({ id, passage }) => ({ id, name: eventNames.get(id), passage })),
  };
}

async function buildKg({ trace, sources, buildId, kg, log }) {
  const walk = findWalk(trace);
  if (!walk) return emptyKg('not_walked');
  if (walk.skip_reason) return emptyKg('walk_skipped', walk.skip_reason);
  if (!buildId) {
    log.warn('Neo4j 未查詢：沒有 build_id，不做跨 build 的查詢');
    return emptyKg('unavailable', KG_QUERY_FAILED);
  }
  try {
    return await queryKg({ walk, trace, sources, buildId, kg });
  } catch (err) {
    log.warn('Neo4j 查詢失敗，答案照回', { kind: err?.kind ?? err?.name, status: err?.status, code: err?.code });
    return emptyKg('unavailable', KG_QUERY_FAILED);
  }
}

/** backend 只給 answer／sources／intent／aux_card／graph_trace／retrieval_stats；統計不外傳。 */
export async function enrich(question, backend, { kg, healthBuildId, log }) {
  const sources = asArray(backend.sources);
  const trace = asArray(backend.graph_trace);
  const buildId = await resolveBuildId(sources, healthBuildId, log);
  return {
    question,
    answer: backend.answer,
    route: backend.retrieval_stats?.route_used || null,
    intent: backend.intent ?? null,
    sources,
    aux_card: backend.aux_card ?? null,
    graph_trace: trace,
    build_id: buildId,
    kg: await buildKg({ trace, sources, buildId, kg, log }),
  };
}
