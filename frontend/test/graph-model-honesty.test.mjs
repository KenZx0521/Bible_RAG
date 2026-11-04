// 說明與節點要跟實際內容一致：章節區塊的段數、點開哪個來源、親屬圖畫得出來時的說明。
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatRef } from '../public/js/books.js';
import { buildViews } from '../public/js/graph-model.js';
import { loadFixture } from './support/fixtures.mjs';

function view(views, key) {
  return views.views.find((item) => item.key === key);
}

function emptyKg(status, reason = null) {
  return { status, reason, names: [], passages: [], mentions: [], events: [] };
}

function respWith(overrides) {
  return { question: 'q', answer: 'a', route: 'R4', sources: [], aux_card: null, graph_trace: [], ...overrides };
}

const WALK_OP = { op: 'graph_walk', walked: ['ps:a'], passages: [], confirmed: [], names: [], nodes: [], seeds: [], skip_reason: null };


function chapterBlockResp(extraSources = []) {
  const resp = loadFixture('walk_plain');
  const block = {
    id: 'mrk.1', kind: 'chapter', book: '馬可福音', chapter: 1, title: '', verse_range: '1-45',
    start_key: 'mrk.1.1', end_key: 'mrk.1.45', passage_id: null, member_ids: ['ps:mrk.1.1', 'ps:mrk.1.9'],
    split_passage_ids: [], context: '[1] 馬可福音 第1章 (1-45節)\n**9** 那時。', build_id: resp.build_id,
  };
  const keep = resp.sources.filter((source) => extraSources.includes(source.passage_id));
  const trace = resp.graph_trace.map((op) => (op.op === 'graph_walk'
    ? { ...op, confirmed: keep.map((source) => source.id), passages: [] }
    : op));
  return { ...resp, route: 'R5', sources: [block, ...keep], graph_trace: trace };
}

test('章節區塊的成員段落走到且用在答案裡：caption 不可說沒用到', () => {
  const resp = chapterBlockResp();
  const { graph, caption } = view(buildViews(resp), 'walk');
  assert.equal(graph.nodes.find((item) => item.id === 'ps:mrk.1.9').used, true);
  assert.equal(caption, '知識圖譜順著人名地名，也連到答案參考的 1 段經文；這題沒有多找到新段落。');
});

test('混合來源：章節區塊的成員也算進段數', () => {
  const resp = chapterBlockResp(['ps:jhn.3.22', 'ps:jhn.4.1']);
  assert.equal(view(buildViews(resp), 'walk').caption, '知識圖譜順著人名地名，也連到答案參考的 3 段經文；這題沒有多找到新段落。');
});

test('用到但沒走到的段落不算進段數', () => {
  const kg = {
    ...emptyKg('ok'),
    passages: [
      { id: 'ps:a', title: 'A', book_id: 'rom', chapter: 8, start_key: 'rom.8.1', end_key: 'rom.8.2', walked: false },
      { id: 'ps:b', title: 'B', book_id: 'rom', chapter: 8, start_key: 'rom.8.3', end_key: 'rom.8.4', walked: true },
    ],
  };
  const sources = [{ id: 'ps:a', passage_id: 'ps:a', member_ids: [] }];
  assert.equal(view(buildViews(respWith({ kg, sources, graph_trace: [WALK_OP] })), 'walk').caption, '知識圖譜有走，但連到的段落沒有用在答案裡。');
});

// ---- 節點標的範圍要和點開的內容一致 ----

test('同一段落有 chunk 與完整來源時，節點開完整來源', () => {
  // 真實資料（kin fixture）裡這段沒走到，已不在圖上；形狀照它，把 walked 打開
  const resp = loadFixture('kin');
  const kg = { ...resp.kg, passages: resp.kg.passages.map((item) => (item.id === 'ps:1sa.17.12' ? { ...item, walked: true } : item)) };
  const { graph } = view(buildViews({ ...resp, kg }), 'walk');
  const passage = graph.nodes.find((item) => item.label === '大衛在掃羅的營中');
  assert.equal(passage.ref, '撒母耳記上 17:12-40');
  assert.equal(resp.sources[passage.sourceIndex].id, 'ps:1sa.17.12');
});

test('沒有完整來源時，開範圍最大的那個（chunk 勝過單節），同範圍取最前面', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'jhn', chapter: 3, start_key: 'jhn.3.1', end_key: 'jhn.3.21', walked: true };
  const kg = { ...emptyKg('ok'), passages: [passage] };
  const verse = { id: 'vs:jhn.3.16', passage_id: 'ps:a', member_ids: [], start_key: 'jhn.3.16', end_key: 'jhn.3.16' };
  const chunk = { id: 'ck:a', passage_id: 'ps:a', member_ids: [], start_key: 'jhn.3.1', end_key: 'jhn.3.12' };
  const twin = { id: 'ck:b', passage_id: 'ps:a', member_ids: [], start_key: 'jhn.3.2', end_key: 'jhn.3.13' };
  const { graph } = view(buildViews(respWith({ kg, sources: [verse, chunk, twin], graph_trace: [WALK_OP] })), 'walk');
  assert.equal(graph.nodes[0].sourceIndex, 1);
});

test('只有 chunk 來源：節點標 chunk 的範圍，和點開的內容一致（兩個真實範例）', () => {
  for (const [fixture, label, ref] of [['walk_plain', '耶穌和撒馬利亞婦人', '約翰福音 4:1-20'], ['regnal', '以色列王亞哈', '列王紀上 16:29-34']]) {
    const resp = loadFixture(fixture);
    const { graph } = view(buildViews(resp), 'walk');
    const passage = graph.nodes.find((item) => item.label === label);
    const source = resp.sources[passage.sourceIndex];
    assert.equal(passage.ref, ref);
    assert.equal(passage.verses, undefined, '範圍一樣就不必高亮');
    assert.equal(formatRef(source.start_key, source.end_key), ref, '和面板標頭同一個範圍');
  }
});

test('只有 chunk 來源（完整圖裡的 regnal 章節）：節點範圍取和來源的交集', () => {
  const resp = loadFixture('regnal');
  const kg = { ...resp.kg, passages: resp.kg.passages.map((item) => (item.id === 'ps:2ch.13.1' ? { ...item, walked: true } : item)) };
  const { graph } = view(buildViews({ ...resp, kg }), 'walk');
  assert.equal(graph.nodes.find((item) => item.id === 'ps:2ch.13.1').ref, '歷代志下 13:1-11');
});

test('只有單節來源：節點標那一節', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'jhn', chapter: 3, start_key: 'jhn.3.1', end_key: 'jhn.3.21', walked: true };
  const verse = { id: 'vs:jhn.3.16', passage_id: 'ps:a', member_ids: [], start_key: 'jhn.3.16', end_key: 'jhn.3.16' };
  const { graph } = view(buildViews(respWith({ kg: { ...emptyKg('ok'), passages: [passage] }, sources: [verse], graph_trace: [WALK_OP] })), 'walk');
  assert.equal(graph.nodes[0].ref, '約翰福音 3:16');
});

test('來源比段落大（章節區塊）：節點標段落的範圍，點開時高亮那幾節', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'mrk', chapter: 1, start_key: 'mrk.1.9', end_key: 'mrk.1.11', walked: true };
  const block = { id: 'mrk.1', kind: 'chapter', passage_id: null, member_ids: ['ps:a'], start_key: 'mrk.1.1', end_key: 'mrk.1.45' };
  const { graph } = view(buildViews(respWith({ kg: { ...emptyKg('ok'), passages: [passage] }, sources: [block], graph_trace: [WALK_OP] })), 'walk');
  assert.equal(graph.nodes[0].ref, '馬可福音 1:9-11');
  assert.deepEqual(graph.nodes[0].verses, { verse: 9, verseEnd: 11 });
});

test('跨章的段落在單章來源裡：範圍照實，高亮只取這一章的節', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'act', chapter: 12, start_key: 'act.12.25', end_key: 'act.13.3', walked: true };
  const block = { id: 'act.13', kind: 'chapter', passage_id: null, member_ids: ['ps:a'], start_key: 'act.13.1', end_key: 'act.13.52' };
  const { graph } = view(buildViews(respWith({ kg: { ...emptyKg('ok'), passages: [passage] }, sources: [block], graph_trace: [WALK_OP] })), 'walk');
  assert.equal(graph.nodes[0].ref, '使徒行傳 13:1-3');
  assert.deepEqual(graph.nodes[0].verses, { verse: 1, verseEnd: 3 });
});

test('跨章的來源比段落大：不高亮（節號在兩章會撞），範圍照段落', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'act', chapter: 12, start_key: 'act.12.25', end_key: 'act.13.3', walked: true };
  const block = { id: 'x', kind: 'chapter', passage_id: null, member_ids: ['ps:a'], start_key: 'act.12.1', end_key: 'act.13.52' };
  const { graph } = view(buildViews(respWith({ kg: { ...emptyKg('ok'), passages: [passage] }, sources: [block], graph_trace: [WALK_OP] })), 'walk');
  assert.equal(graph.nodes[0].ref, '使徒行傳 12:25-13:3');
  assert.equal(graph.nodes[0].verses, undefined);
});

test('來源和段落對不起來（壞資料）或來源沒有範圍：退回段落自己的範圍', () => {
  const passage = { id: 'ps:a', title: 'A', book_id: 'mrk', chapter: 1, start_key: 'mrk.1.9', end_key: 'mrk.1.11', walked: true };
  for (const keys of [{ start_key: 'mrk.2.1', end_key: 'mrk.2.5' }, { start_key: undefined, end_key: undefined }]) {
    const source = { id: 'ps:a', passage_id: 'ps:a', member_ids: [], ...keys };
    const { graph } = view(buildViews(respWith({ kg: { ...emptyKg('ok'), passages: [passage] }, sources: [source], graph_trace: [WALK_OP] })), 'walk');
    assert.equal(graph.nodes[0].ref, '馬可福音 1:9-11');
    assert.equal(graph.nodes[0].verses, undefined);
  }
});

test('沒用到的段落：範圍是整段（面板另外說明只列開頭）', () => {
  const { graph } = view(buildViews(loadFixture('walk_plain')), 'walk');
  assert.equal(graph.nodes.find((item) => item.id === 'ps:luk.3.1').ref, '路加福音 3:1-20');
});

// ---- 親屬圖畫得出來時，不能同時說關聯圖讀不到 ----

test('kg 讀不到但親屬圖有畫：note 只說走過的段落讀不到', () => {
  const built = buildViews({ ...loadFixture('kin'), kg: emptyKg('unavailable', 'neo4j_query_failed') });
  assert.deepEqual(built.views.map((item) => item.key), ['kin']);
  assert.doesNotMatch(built.note, /關聯圖/);
  assert.equal(built.note, '這題也走了知識圖譜，但連到的段落暫時讀不到。');
});
