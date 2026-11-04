// Neo4j Query API 唯讀 client：閉集 Cypher 模板、全部參數化、一定帶 build_id、accessMode READ。
// 錯誤訊息固定，不帶回應內容，也不可能帶出帳密。
export const TEMPLATES = Object.freeze({
  names: 'UNWIND $ids AS i MATCH (n:Name {build_id:$b,id:i}) RETURN n.id,n.label,n.df,n.idf ORDER BY n.id',
  passages:
    'UNWIND $ids AS i MATCH (p:Passage {build_id:$b,id:i}) ' +
    'RETURN p.id,p.title,p.book_id,p.chapter,p.start_key,p.end_key ORDER BY p.id',
  mentions:
    'UNWIND $ps AS i MATCH (p:Passage {build_id:$b,id:i})-[:MENTIONS]->(n:Name {build_id:$b}) ' +
    'WHERE n.id IN $ns RETURN p.id,n.id ORDER BY p.id,n.id',
  events: 'UNWIND $ids AS i MATCH (e:Event {build_id:$b,id:i}) RETURN e.id,e.name',
  ping: 'RETURN 1',
});

const ROW_SHAPES = Object.freeze({
  names: ([id, label, df, idf]) => ({ id, label, df, idf }),
  passages: ([id, title, book_id, chapter, start_key, end_key]) => ({
    id,
    title,
    book_id,
    chapter,
    start_key,
    end_key,
  }),
  mentions: ([passage, name]) => [passage, name],
  events: ([id, name]) => ({ id, name }),
});

export class Neo4jError extends Error {
  constructor(kind, { status = null, code = null } = {}) {
    super(`Neo4j 查詢失敗：${kind}`);
    this.name = 'Neo4jError';
    this.kind = kind;
    this.status = status;
    this.code = code;
  }
}

async function post({ url, authorization }, statement, parameters, signal) {
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        authorization,
        accept: 'application/json',
        'content-type': 'application/json',
      },
      body: JSON.stringify({ statement, parameters, accessMode: 'READ' }),
      signal,
    });
    return { status: response.status, text: await response.text() };
  } catch (err) {
    const timedOut = err?.name === 'TimeoutError' || err?.name === 'AbortError';
    throw new Neo4jError(timedOut ? 'timeout' : 'network');
  }
}

function parseBody(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function valuesFrom({ status, text }) {
  if (status === 401 || status === 403) throw new Neo4jError('unauthorized', { status });
  const body = parseBody(text);
  const firstError = Array.isArray(body?.errors) ? body.errors[0] : undefined;
  if (firstError || status < 200 || status >= 300) {
    throw new Neo4jError('query', { status, code: firstError?.code ?? null });
  }
  if (!Array.isArray(body?.data?.values)) throw new Neo4jError('malformed', { status });
  return body.data.values;
}

export function createNeo4jClient({ url, user, password, timeoutMs }) {
  const configured = Boolean(user && password);
  const target = {
    url,
    authorization: configured ? `Basic ${Buffer.from(`${user}:${password}`).toString('base64')}` : '',
  };

  async function execute(key, parameters, signal) {
    if (!configured) throw new Neo4jError('not_configured');
    return valuesFrom(await post(target, TEMPLATES[key], parameters, signal));
  }

  /** 一次提問一個 session：裡面所有查詢共用同一個時限，不會 4 × 2 秒。 */
  function session() {
    const signal = AbortSignal.timeout(timeoutMs);
    const scoped = async (key, lists, parameters) => {
      if (!configured) throw new Neo4jError('not_configured');
      if (!parameters.b) throw new Neo4jError('no_build_id');
      if (lists.some((list) => list.length === 0)) return [];
      return (await execute(key, parameters, signal)).map(ROW_SHAPES[key]);
    };
    return {
      names: (b, ids) => scoped('names', [ids], { b, ids }),
      passages: (b, ids) => scoped('passages', [ids], { b, ids }),
      mentions: (b, ps, ns) => scoped('mentions', [ps, ns], { b, ps, ns }),
      events: (b, ids) => scoped('events', [ids], { b, ids }),
    };
  }

  const ping = async () => {
    await execute('ping', {}, AbortSignal.timeout(timeoutMs));
  };

  return Object.freeze({ configured, session, ping });
}
