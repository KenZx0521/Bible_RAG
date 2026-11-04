// DOM 接線、URL 狀態、請求。單問單答：畫面只有首頁、等待、錯誤、結果四種。
// 網址 ?q= 帶問題，可分享、上一頁可回；問過的答案留在記憶體，回上一題不必再等一次 GPU。
import { formatRef, parseKey } from './books.js';
import { resolveCitation } from './citations.js';
import { charCount, el } from './dom.js';
import { buildViews } from './graph-model.js';
import { mountGraphPanel } from './graph-view.js';
import { createReader } from './reader.js';
import { renderAnswer } from './render-answer.js';

const APP_TITLE = '聖經問答';
const MAX_CHARS = 500;
const CACHE_LIMIT = 12;
const TICK_MS = 1000;
const SLOW_AFTER_SECONDS = 30; // 和 TEXT.waiting 的上限一致：過了就不能再說「通常 15–30 秒」
// 超過這個字數就改小字、限高：長問題不能把等待訊息和答案推出第一屏
const LONG_QUESTION_CHARS = 60;

const EXAMPLES = Object.freeze([
  { question: '使徒行傳裡，彼得在哪裡醫治了生來瘸腿的人？', tag: '人物與事件' },
  { question: '大衛的曾祖父是誰？', tag: '親屬關係' },
  { question: '耶穌在哪裡受洗？', tag: '地點' },
  { question: '約翰福音 3:16 說了什麼？', tag: '查經節' },
]);

const TEXT = Object.freeze({
  waiting: '正在翻閱經文，通常需要 15–30 秒',
  slow: '這題比平常久一些，還在翻閱經文',
  empty: '請先輸入問題。',
  busy: '現在問的人比較多，請稍後再試',
  noResponse: '查詢服務暫時沒有回應',
  graphBroken: '關聯圖這次畫不出來，答案和經文來源不受影響。',
});

const byId = (id) => document.getElementById(id);
const dom = {
  home: byId('home'), asked: byId('asked'), question: byId('question'),
  waiting: byId('waiting'), waitingLine: byId('waiting-line'), waitingElapsed: byId('waiting-elapsed'),
  failure: byId('failure'), failureMessage: byId('failure-message'), retry: byId('retry'),
  result: byId('result'), answer: byId('answer'), graphHost: byId('graph-host'),
  sourceList: byId('source-list'), sourcesEmpty: byId('sources-empty'),
  form: byId('ask-form'), input: byId('ask-input'), message: byId('ask-message'),
  examples: byId('examples'), askAgain: byId('ask-again'), askAgainFoot: byId('ask-again-foot'), mastheadNote: byId('masthead-note'),
  build: byId('colophon-build'),
};

const reader = createReader(byId('reader'));
const session = { controller: null, timer: 0, stopGraph: () => {}, question: '', cache: new Map() };

// ---- 畫面切換 ----

function showScreen(name) {
  dom.home.hidden = name !== 'home';
  dom.asked.hidden = name === 'home';
  dom.waiting.hidden = name !== 'waiting';
  dom.failure.hidden = name !== 'failure';
  dom.result.hidden = name !== 'result';
  dom.askAgain.hidden = name === 'home';
  dom.mastheadNote.hidden = name !== 'home';
}

function setQuestion(question) {
  session.question = question;
  dom.question.textContent = question;
  dom.question.classList.toggle('is-long', charCount(question) > LONG_QUESTION_CHARS);
  document.title = `${question} · ${APP_TITLE}`;
}

/** 收掉上一題還在跑的東西：請求、計時、圖的 observer、面板。 */
function settlePrevious() {
  session.controller?.abort();
  session.controller = null;
  clearInterval(session.timer);
  session.stopGraph();
  session.stopGraph = () => {};
  reader.close();
}

function showHome({ draft = '', error = '', focus = false } = {}) {
  settlePrevious();
  session.question = '';
  document.title = APP_TITLE;
  dom.build.textContent = '';
  dom.input.value = draft;
  setFormMessage(error);
  showScreen('home');
  if (focus) dom.input.focus();
}

// ---- 等待 ----

function startWaiting(question) {
  setQuestion(question);
  showScreen('waiting');
  dom.waitingLine.textContent = TEXT.waiting;
  const startedAt = Date.now();
  const tick = () => {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    dom.waitingElapsed.textContent = `已等 ${seconds} 秒`;
    // 分頁被節流或筆電闔上時計時器會跳過幾秒，不能只比對剛好那一秒
    if (seconds >= SLOW_AFTER_SECONDS && dom.waitingLine.textContent !== TEXT.slow) dom.waitingLine.textContent = TEXT.slow;
  };
  tick();
  session.timer = setInterval(tick, TICK_MS);
  window.scrollTo(0, 0);
}

// ---- 請求 ----

async function errorText(response) {
  if (response.status === 429) return TEXT.busy;
  if (response.status === 400) {
    const body = await response.json().catch(() => null);
    if (typeof body?.error === 'string') return body.error;
  }
  return TEXT.noResponse;
}

/** 永遠回 {data} 或 {error}；被取消回 null。 */
async function requestAnswer(question, signal) {
  try {
    const response = await fetch('/api/ask', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ question }),
      signal,
    });
    if (!response.ok) return { error: await errorText(response) };
    return { data: await response.json() };
  } catch (err) {
    return err?.name === 'AbortError' ? null : { error: TEXT.noResponse };
  }
}

function remember(question, data) {
  const kept = [...session.cache].filter(([key]) => key !== question).slice(-(CACHE_LIMIT - 1));
  session.cache = new Map([...kept, [question, data]]);
}

async function ask(question) {
  settlePrevious();
  const cached = session.cache.get(question);
  if (cached) {
    setQuestion(question);
    showResult(cached);
    return;
  }
  const controller = new AbortController();
  session.controller = controller;
  startWaiting(question);
  const outcome = await requestAnswer(question, controller.signal);
  if (outcome === null || session.controller !== controller) return;
  session.controller = null;
  clearInterval(session.timer);
  if (outcome.error) {
    showFailure(outcome.error);
    return;
  }
  remember(question, outcome.data);
  showResult(outcome.data);
}

function showFailure(message) {
  dom.failureMessage.textContent = message;
  showScreen('failure');
  dom.retry.focus();
}

// ---- 結果 ----

function openCitation(target, sources, opener) {
  if (target?.type === 'source') {
    reader.openSource(sources[target.sourceIndex], target, opener);
  } else if (target?.type === 'verse') {
    reader.openVerses(target, opener);
  }
}

function openVerseKey(verseKey, sources, opener) {
  const key = parseKey(verseKey);
  if (key) openCitation(resolveCitation({ bookId: key.bookId, chapter: key.chapter, verse: key.verse }, sources), sources, opener);
}

function openNode(node, data, opener) {
  if (node.sourceIndex !== undefined) {
    reader.openSource(data.sources[node.sourceIndex], node.verses ?? {}, opener);
    return;
  }
  const passage = data.kg?.passages?.find((item) => item.id === node.id);
  if (passage) reader.openPassage(passage, opener);
}

function broughtSources(views) {
  const walk = views.find((view) => view.key === 'walk');
  return new Set((walk?.graph.nodes ?? []).filter((node) => node.brought).map((node) => node.sourceIndex));
}

function sourceRow(source, index, isBrought) {
  const ref = formatRef(source.start_key, source.end_key);
  const button = el('button', {
    type: 'button',
    class: 'source',
    'aria-label': `開啟經文 ${source.title || ref}，${ref}`,
    on: { click: (event) => reader.openSource(source, {}, event.currentTarget) },
  }, [
    el('span', { class: 'source-no', text: String(index + 1), 'aria-hidden': 'true' }),
    el('span', { class: 'source-title', text: source.title || ref }),
    el('span', { class: 'source-meta' }, [
      isBrought ? el('span', { class: 'source-flag', text: '圖譜帶進來' }) : null,
      el('span', { class: 'source-ref', text: ref }),
    ]),
  ]);
  return el('li', {}, [button]);
}

function renderSources(sources, views) {
  const brought = broughtSources(views);
  dom.sourceList.replaceChildren(...sources.map((source, index) => sourceRow(source, index, brought.has(index))));
  dom.sourcesEmpty.hidden = sources.length > 0;
}

/** 圖壞了不能拖垮答案：答案與經文才是主角。回傳圖裡的檢視（畫不出來就是空的）。 */
function renderGraph(data) {
  const sources = data.sources ?? [];
  try {
    const model = buildViews(data);
    session.stopGraph = mountGraphPanel(dom.graphHost, model, {
      onPassage: (node, opener) => openNode(node, data, opener),
      onVerseKey: (verseKey, opener) => openVerseKey(verseKey, sources, opener),
      onSkip: () => (dom.sourceList.querySelector('.source') ?? dom.askAgainFoot).focus(),
    });
    return model.views;
  } catch (err) {
    console.error('關聯圖繪製失敗', err);
    dom.graphHost.replaceChildren(el('p', { class: 'graph-note', text: TEXT.graphBroken }));
    return [];
  }
}

function showResult(data) {
  const sources = data.sources ?? [];
  showScreen('result');
  dom.answer.replaceChildren(...renderAnswer(data.answer, {
    sources,
    onCitation: (target, opener) => openCitation(target, sources, opener),
  }));
  renderSources(sources, renderGraph(data));
  dom.build.textContent = data.build_id ? `資料版本 ${data.build_id}` : '';
  window.scrollTo(0, 0);
  dom.question.focus({ preventScroll: true });
}

// ---- 網址與輸入 ----

function setFormMessage(message) {
  dom.message.textContent = message;
  dom.message.classList.toggle('is-error', message !== '');
  if (message) dom.input.setAttribute('aria-invalid', 'true');
  else dom.input.removeAttribute('aria-invalid');
}

function validate(question) {
  if (question === '') return TEXT.empty;
  const count = charCount(question);
  return count > MAX_CHARS ? `問題太長了，請縮短到 ${MAX_CHARS} 字以內（目前 ${count} 字）。` : '';
}

function urlFor(question) {
  return question ? `/?q=${encodeURIComponent(question)}` : '/';
}

function navigate(question) {
  history.pushState(null, '', urlFor(question));
  ask(question);
}

function goHome(options) {
  history.pushState(null, '', urlFor(''));
  showHome(options);
}

/** 依目前網址決定畫面：首次載入與上一頁都走這裡。 */
function route() {
  const question = (new URLSearchParams(location.search).get('q') ?? '').trim();
  if (question === '') {
    showHome();
    return;
  }
  // 面板收回歷史後按下一頁會回到同網址：還是這一題，不必重畫、不要跳回頂端
  if (question === session.question && !dom.result.hidden) return;
  const problem = validate(question);
  if (problem) showHome({ draft: question, error: problem });
  else ask(question);
}

function submitForm(event) {
  event.preventDefault();
  const question = dom.input.value.trim();
  const problem = validate(question);
  setFormMessage(problem);
  if (problem) {
    dom.input.focus();
    return;
  }
  navigate(question);
}

function isPlainClick(event) {
  return event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey;
}

function linkHome(link) {
  link.addEventListener('click', (event) => {
    if (!isPlainClick(event)) return;
    event.preventDefault();
    goHome({ focus: true });
  });
}

function renderExamples() {
  dom.examples.replaceChildren(...EXAMPLES.map(({ question, tag }) => el('li', {}, [
    el('button', { type: 'button', class: 'example', on: { click: () => navigate(question) } }, [
      el('span', { class: 'example-question', text: question }),
      el('span', { class: 'example-tag', text: tag }),
      el('span', { class: 'example-arrow', text: '→', 'aria-hidden': 'true' }),
    ]),
  ])));
}

function wire() {
  renderExamples();
  dom.form.addEventListener('submit', submitForm);
  dom.input.addEventListener('input', () => setFormMessage(''));
  dom.retry.addEventListener('click', () => ask(session.question));
  byId('waiting-cancel').addEventListener('click', () => goHome({ focus: true }));
  byId('failure-home').addEventListener('click', () => goHome({ focus: true }));
  linkHome(dom.askAgain);
  linkHome(dom.askAgainFoot);
  linkHome(byId('nameplate'));
  window.addEventListener('popstate', () => {
    if (!reader.handlePop()) route();
  });
  route();
}

wire();
