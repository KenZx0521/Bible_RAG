import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildViews } from '../public/js/graph-model.js';
import { FIXTURE_NAMES, deepFreeze, loadFixture } from './support/fixtures.mjs';

function view(views, key) {
  return views.views.find((item) => item.key === key);
}

function node(graph, label) {
  return graph.nodes.find((item) => item.label === label);
}

function emptyKg(status, reason = null) {
  return { status, reason, names: [], passages: [], mentions: [], events: [] };
}

function respWith(overrides) {
  return { question: 'q', answer: 'a', route: 'R4', sources: [], aux_card: null, graph_trace: [], ...overrides };
}

const WALK_OP = { op: 'graph_walk', walked: ['ps:a'], passages: [], confirmed: [], names: [], nodes: [], seeds: [], skip_reason: null };

test('不改輸入、結果決定性', () => {
  for (const name of FIXTURE_NAMES) {
    const resp = deepFreeze(loadFixture(name));
    assert.deepEqual(buildViews(resp), buildViews(resp));
  }
});

test('walk_event：只有 walk 一個 view，節點齊全', () => {
  const resp = loadFixture('walk_event');
  const built = buildViews(resp);
  assert.deepEqual(built.views.map((item) => item.key), ['walk']);
  assert.equal(built.note, undefined);
  const { graph } = view(built, 'walk');
  const kinds = (kind) => graph.nodes.filter((item) => item.kind === kind);
  const walked = new Set(resp.kg.passages.filter((item) => item.walked).map((item) => item.id));
  const walkedMentions = resp.kg.mentions.filter(([from]) => walked.has(from));
  assert.equal(kinds('name').length, new Set(walkedMentions.map(([, to]) => to)).size);
  assert.equal(kinds('passage').length, walked.size + 1, '走到的段落，加上事件對應的那段');
  assert.equal(kinds('event').length, 1);
  assert.equal(graph.edges.filter((edge) => edge.type === 'mentions').length, walkedMentions.length);
  assert.equal(graph.edges.filter((edge) => edge.type === 'anchor').length, 1);
});

test('walk_event：brought 是「安提阿的教會」，只有它', () => {
  const { graph } = view(buildViews(loadFixture('walk_event')), 'walk');
  const brought = graph.nodes.filter((item) => item.brought).map((item) => item.label);
  assert.deepEqual(brought, ['安提阿的教會']);
});

test('walk_event：段落節點的 ref、used、sourceIndex 來自資料', () => {
  const resp = loadFixture('walk_event');
  const { graph } = view(buildViews(resp), 'walk');
  const sent = node(graph, '巴拿巴和掃羅奉差遣');
  assert.deepEqual(sent, {
    id: 'ps:act.13.1', kind: 'passage', label: '巴拿巴和掃羅奉差遣', ref: '使徒行傳 13:1-3',
    walked: false, used: true, brought: false, sourceIndex: 5,
  });
  const unused = node(graph, '保羅坐船往羅馬');
  assert.equal(unused.used, false);
  assert.equal('sourceIndex' in unused, false);
  for (const item of graph.nodes.filter((n) => n.used)) {
    assert.equal(resp.sources[item.sourceIndex].passage_id, item.id);
  }
});

test('walk_event：問題裡的名字與事件', () => {
  const { graph } = view(buildViews(loadFixture('walk_event')), 'walk');
  const inQuestion = graph.nodes.filter((item) => item.inQuestion).map((item) => item.label);
  assert.deepEqual(inQuestion, ['巴拿巴', '保羅']);
  assert.deepEqual(node(graph, '第一次宣教旅程'), { id: 'ev0009', kind: 'event', label: '第一次宣教旅程' });
  assert.deepEqual(graph.edges.find((edge) => edge.type === 'anchor'), { from: 'ev0009', to: 'ps:act.13.1', type: 'anchor' });
  const name = node(graph, '巴拿巴');
  assert.deepEqual(name, { id: 'nm:1216b4d0d4c6', kind: 'name', label: '巴拿巴', inQuestion: true, df: 16, idf: 5.155096 });
});

test('walk_event：caption 由資料產生', () => {
  assert.equal(
    view(buildViews(loadFixture('walk_event')), 'walk').caption,
    '知識圖譜從問題裡的「巴拿巴」「保羅」出發，順著經文共同提到的人名地名往外找；「安提阿的教會」單看問題的字句找不到，是這樣連過去才找到的。',
  );
});

test('caption 不是寫死：改資料文字就跟著變', () => {
  const resp = loadFixture('walk_event');
  const renamed = {
    ...resp,
    kg: { ...resp.kg, passages: resp.kg.passages.map((p) => (p.id === 'ps:act.11.19' ? { ...p, title: '別的標題' } : p)) },
  };
  assert.match(view(buildViews(renamed), 'walk').caption, /；「別的標題」單看問題的字句找不到/);
});

test('walk_plain：沒有 in_question 名字、沒有 brought，caption 算到 3 段（含 chunk 對回）', () => {
  const built = buildViews(loadFixture('walk_plain'));
  const { graph, caption } = view(built, 'walk');
  assert.equal(caption, '知識圖譜順著人名地名，也連到答案參考的 3 段經文；這題沒有多找到新段落。');
  assert.equal(graph.nodes.filter((item) => item.brought).length, 0);
  assert.equal(graph.nodes.filter((item) => item.inQuestion).length, 0);
});

test('walk_plain：chunk 來源 ck:jhn.4.1~jhn.4.20 對回 ps:jhn.4.1', () => {
  const { graph } = view(buildViews(loadFixture('walk_plain')), 'walk');
  const passage = graph.nodes.find((item) => item.id === 'ps:jhn.4.1');
  assert.equal(passage.used, true);
  assert.equal(passage.sourceIndex, 4);
  assert.equal(passage.label, '耶穌和撒馬利亞婦人');
  assert.equal(passage.ref, '約翰福音 4:1-20', '標的是點開看得到的範圍');
  assert.equal(graph.nodes.some((item) => item.id.startsWith('ck:')), false);
});

test('brought 含 ck: chunk id 時透過 source 對回 passage', () => {
  const resp = loadFixture('walk_plain');
  const trace = resp.graph_trace.map((op) => ({ ...op, passages: ['ck:jhn.4.1~jhn.4.20'], confirmed: [] }));
  const { graph, caption } = view(buildViews({ ...resp, graph_trace: trace }), 'walk');
  assert.deepEqual(graph.nodes.filter((item) => item.brought).map((item) => item.id), ['ps:jhn.4.1']);
  assert.equal(
    caption,
    '知識圖譜從最接近問題的經文出發，順著經文共同提到的人名地名往外找；「耶穌和撒馬利亞婦人」單看問題的字句找不到，是這樣連過去才找到的。',
  );
});

test('member_ids：章節區塊的所有段落都算 used', () => {
  const kg = {
    status: 'ok', reason: null, names: [], mentions: [], events: [],
    passages: [
      { id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.17', walked: true },
      { id: 'ps:b', title: '', book_id: 'rom', chapter: 8, start_key: 'rom.8.18', end_key: 'rom.8.30', walked: true },
    ],
  };
  const sources = [{ id: 'rom.8', kind: 'chapter', passage_id: null, member_ids: ['ps:a', 'ps:b'] }];
  const { graph } = view(buildViews(respWith({ kg, sources, graph_trace: [WALK_OP] })), 'walk');
  assert.deepEqual(graph.nodes.map((item) => [item.id, item.used, item.sourceIndex]), [['ps:a', true, 0], ['ps:b', true, 0]]);
  assert.equal(graph.nodes[1].label, '羅馬書 8:18-30', '沒有標題時退回出處');
});

test('kin：kin 在前，再來 walk；焦點與親屬邊', () => {
  const built = buildViews(loadFixture('kin'));
  assert.deepEqual(built.views.map((item) => item.key), ['kin', 'walk']);
  const { graph, caption } = view(built, 'kin');
  assert.equal(caption, '答案參考了下面的親屬關係，每條都有經文出處。');
  assert.deepEqual(graph.nodes.map((item) => item.label), ['耶西', '大衛', '俄備得', '波阿斯', '路得']);
  assert.deepEqual(graph.nodes.filter((item) => item.focus).map((item) => item.label), ['大衛']);
  assert.deepEqual(node(graph, '耶西'), { id: 'e000432', kind: 'person', label: '耶西', focus: false });
  assert.deepEqual(graph.edges[0], { from: 'e000432', to: 'e000433', type: 'PARENT_OF', verseKey: 'rut.4.17', ref: '路得記 4:17' });
  assert.deepEqual(graph.edges.map((edge) => edge.ref), ['路得記 4:17', '路得記 4:17', '路得記 4:21', '馬太福音 1:5']);
});

test('kin：walk caption 算到 1 段，沒帶新段落', () => {
  assert.equal(
    view(buildViews(loadFixture('kin')), 'walk').caption,
    '知識圖譜順著人名地名，也連到答案參考的 1 段經文；這題沒有多找到新段落。',
  );
});

test('kin 卡沒有 injected="prompt" 就沒有親屬圖', () => {
  const resp = loadFixture('kin');
  const trace = resp.graph_trace.map((op) => (op.op === 'kin_card' ? { ...op, injected: 'none' } : op));
  assert.deepEqual(buildViews({ ...resp, graph_trace: trace }).views.map((item) => item.key), ['walk']);
});

test('kin：節點缺名字就略過，不把代號露給讀者；邊的端點不存在也略過', () => {
  const op = {
    op: 'kin_card', injected: 'prompt', nodes: ['e1', 'e2', 'e3'], names: ['甲', '乙'],
    edges: [['e1', 'PARENT_OF', 'e2', 'rut.4.17'], ['e2', 'PARENT_OF', 'e3', 'rut.4.21']],
  };
  const { graph } = view(buildViews(respWith({ kg: emptyKg('not_walked'), graph_trace: [op] })), 'kin');
  assert.deepEqual(graph.nodes.map((item) => item.id), ['e1', 'e2']);
  assert.equal(graph.edges.length, 1);
});

test('direct：沒有 view，note 說直接查', () => {
  const built = buildViews(loadFixture('direct'));
  assert.deepEqual(built.views, []);
  assert.equal(built.note, '這題寫明了經文出處，直接查就找到了，不需要走知識圖譜。');
});

test('regnal：chrono 在 walk 前，文字只取推算段', () => {
  const resp = loadFixture('regnal');
  const built = buildViews(resp);
  assert.deepEqual(built.views.map((item) => item.key), ['chrono', 'walk']);
  const chrono = view(built, 'chrono');
  assert.equal(chrono.caption, '答案參考了依列王紀整理的王位順序推算。');
  assert.equal(chrono.graph, undefined, '回應的鏈節點只有代號，不畫圖');
  assert.ok(chrono.text.startsWith('以色列王拿答之前第1位以色列王：耶羅波安'));
  assert.ok(chrono.text.endsWith('以色列王拿答到以色列王撒迦利雅相隔：12代王位'));
  assert.ok(!chrono.text.includes('依上列資料推算'));
  assert.ok(!chrono.text.includes('在位22年\n'), '推算段之前的資料列不要');
  assert.equal(chrono.text.split('\n').length, 15);
});

test('regnal：walk 的 brought 與 caption', () => {
  const walk = view(buildViews(loadFixture('regnal')), 'walk');
  assert.deepEqual(walk.graph.nodes.filter((item) => item.brought).map((item) => item.label), ['以色列王亞哈']);
  assert.equal(
    walk.caption,
    '知識圖譜從問題裡的「耶羅波安」「以色列」出發，順著經文共同提到的人名地名往外找；「以色列王亞哈」單看問題的字句找不到，是這樣連過去才找到的。',
  );
});

test('chrono：沒有推算段就用全文；gen 卡換說明', () => {
  const regnal = respWith({ kg: emptyKg('not_walked'), aux_card: { kind: 'regnal', text: '第一行\n第二行' } });
  assert.equal(view(buildViews(regnal), 'chrono').text, '第一行\n第二行');
  const gen = respWith({ kg: emptyKg('not_walked'), aux_card: { kind: 'gen', text: '亞當：930歲\n依上列資料推算：\n塞特：912歲' } });
  const chrono = view(buildViews(gen), 'chrono');
  assert.equal(chrono.text, '塞特：912歲');
  assert.equal(chrono.caption, '答案參考了依創世記家譜年歲推算。');
});

test('不可出現人物／地點分類或開發者欄位', () => {
  const forbidden = /route|score|strategy|cypher|top_k|alpha|use_graph|R[1-6]\b/i;
  for (const name of FIXTURE_NAMES) {
    const built = buildViews(loadFixture(name));
    for (const item of built.views) {
      assert.doesNotMatch(`${item.title}${item.caption}${item.text ?? ''}`, forbidden);
      for (const graphNode of item.graph?.nodes ?? []) {
        for (const key of ['type', 'category', 'route_types', 'nodeType', 'label_type']) {
          assert.equal(key in graphNode, false, `${name}: ${key}`);
        }
        assert.doesNotMatch(graphNode.label, /^(nm:|ps:|ck:|ev\d|e\d{6})/);
        assert.doesNotMatch(graphNode.label, /人物|地點/);
      }
    }
    assert.doesNotMatch(built.note ?? '', forbidden);
  }
});

test('walk 圖沒有懸空邊，重複的 mention 只留一條', () => {
  for (const name of ['walk_event', 'walk_plain', 'kin', 'regnal']) {
    const { graph } = view(buildViews(loadFixture(name)), 'walk');
    const ids = new Set(graph.nodes.map((item) => item.id));
    assert.equal(ids.size, graph.nodes.length);
    for (const edge of graph.edges) assert.ok(ids.has(edge.from) && ids.has(edge.to));
  }
  const kg = {
    status: 'ok', reason: null, events: [{ id: 'ev1', name: '事件', passage: 'ps:missing' }],
    names: [{ id: 'nm:a', label: '甲', df: 1, idf: 1, in_question: false }],
    passages: [{ id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked: true }],
    mentions: [['ps:a', 'nm:a'], ['ps:a', 'nm:a'], ['ps:a', 'nm:gone'], ['ps:gone', 'nm:a']],
  };
  const { graph } = view(buildViews(respWith({ kg, graph_trace: [WALK_OP] })), 'walk');
  assert.deepEqual(graph.edges, [{ from: 'ps:a', to: 'nm:a', type: 'mentions' }]);
  assert.equal(graph.nodes.some((item) => item.kind === 'event'), true, '事件照列，只是沒有邊');
});

test('事件查不到名字就不列，不把代號露給讀者', () => {
  const kg = {
    ...emptyKg('ok'),
    events: [{ id: 'ev1', name: null, passage: 'ps:a' }, { id: 'ev2', name: '有名字', passage: 'ps:a' }],
    passages: [{ id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked: true }],
  };
  const { graph } = view(buildViews(respWith({ kg, graph_trace: [WALK_OP] })), 'walk');
  assert.deepEqual(graph.nodes.filter((item) => item.kind === 'event').map((item) => item.id), ['ev2']);
  assert.deepEqual(graph.edges.map((edge) => edge.from), ['ev2']);
});

test('walk 都沒走到答案段落', () => {
  const kg = {
    ...emptyKg('ok'),
    passages: [{ id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked: true }],
  };
  assert.equal(
    view(buildViews(respWith({ kg, graph_trace: [WALK_OP] })), 'walk').caption,
    '知識圖譜有走，但連到的段落沒有用在答案裡。',
  );
});

test('confirmed 指到不在 sources 的段落不算數', () => {
  const kg = {
    ...emptyKg('ok'),
    passages: [{ id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked: true }],
  };
  const trace = [{ ...WALK_OP, confirmed: ['ps:a', 'ck:gone'] }];
  assert.equal(
    view(buildViews(respWith({ kg, graph_trace: trace })), 'walk').caption,
    '知識圖譜有走，但連到的段落沒有用在答案裡。',
  );
});

test('kg ok 但 walked 是空的：沒有 walk view，也不假裝走到', () => {
  const trace = [{ ...WALK_OP, walked: [] }];
  const built = buildViews(respWith({ kg: emptyKg('ok'), graph_trace: trace }));
  assert.deepEqual(built.views, []);
  assert.equal(built.note, '知識圖譜有走，但這題沒有連到相關段落。');
});

test('note：not_walked 只有 R1／R2 才說直接查', () => {
  for (const route of ['R1', 'R2']) {
    assert.equal(buildViews(respWith({ route, kg: emptyKg('not_walked') })).note, '這題寫明了經文出處，直接查就找到了，不需要走知識圖譜。');
  }
  for (const route of ['R3', 'R4', 'R5', 'R6', undefined]) {
    assert.equal(buildViews(respWith({ route, kg: emptyKg('not_walked') })).note, '這題沒有走知識圖譜。');
  }
});

test('note：walk_skipped 與 unavailable', () => {
  const skippedOp = { ...WALK_OP, skip_reason: 'timeout' };
  assert.equal(
    buildViews(respWith({ kg: emptyKg('walk_skipped', 'timeout'), graph_trace: [skippedOp] })).note,
    '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。',
  );
  assert.equal(buildViews(respWith({ kg: emptyKg('unavailable') })).note, '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。');
  assert.equal(
    buildViews(respWith({ kg: emptyKg('unavailable'), graph_trace: [skippedOp] })).note,
    '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。',
  );
  assert.equal(
    buildViews(respWith({ kg: emptyKg('unavailable'), graph_trace: [WALK_OP] })).note,
    '這題有走知識圖譜，但關聯圖暫時讀不到。',
  );
});

test('note：有卡片時不說答案只靠直接比對，那不是事實', () => {
  const card = { kind: 'regnal', text: '依上列資料推算：\n某行' };
  const built = buildViews(respWith({ kg: emptyKg('walk_skipped', 'timeout'), aux_card: card, graph_trace: [{ ...WALK_OP, skip_reason: 'timeout' }] }));
  assert.deepEqual(built.views.map((item) => item.key), ['chrono']);
  assert.equal(built.note, '知識圖譜這次沒有回應。');
});

test('unavailable 時親屬圖仍可畫（資料在回應裡，不靠 Neo4j）', () => {
  const resp = loadFixture('kin');
  const built = buildViews({ ...resp, kg: emptyKg('unavailable') });
  assert.deepEqual(built.views.map((item) => item.key), ['kin']);
  assert.equal(built.note, '這題也走了知識圖譜，但連到的段落暫時讀不到。');
});

test('沒有 kg 欄位也不當掉', () => {
  const built = buildViews({ question: 'q', answer: 'a', route: 'R4', sources: [], graph_trace: [] });
  assert.deepEqual(built.views, []);
  assert.equal(built.note, '知識圖譜這次沒有回應，答案是直接比對問題找到的經文。');
});

test('每個 view 都有標題與說明', () => {
  for (const name of FIXTURE_NAMES) {
    for (const item of buildViews(loadFixture(name)).views) {
      assert.ok(item.title.length > 0);
      assert.ok(item.caption.length > 0);
    }
  }
});
