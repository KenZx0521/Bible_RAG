// 經文閱讀面板：原生 <dialog>，桌機右側、手機底部；ESC 可關，焦點回到打開它的元素。
// 三種入口：這題的來源（有全文）、模型自己引的節（查 /api/verse）、完整圖譜裡沒用到的段落（也查）。
import { bookById, formatRef, parseKey } from './books.js';
import { citedSpans, formatCitedRef, formatVerseList } from './citations.js';
import { el, findRedrawn } from './dom.js';
import { parsePassageText, verseIsCited } from './passage-text.js';

const MAX_LOOKUP_VERSES = 12;
const TEXT = Object.freeze({
  notFound: '找不到這節經文',
  lookupFailed: '現在查不到這節經文，請稍後再試。',
  loading: '正在查這段經文…',
  unreadable: '這段經文暫時讀不到。',
  notInSources: (count) => `${count > 1 ? '這段' : '這節'}不在這題找到的經文來源裡，這裡直接查給你看。`,
  unusedPassage: '知識圖譜連到了這段，但它沒有用在答案裡。',
  trimmed: (count) => `這段較長，這裡只列前 ${count} 節。`,
  missing: (verses) => `答案引的第 ${verses} 節不在這段來源裡。`,
});

// ---- 經文排版 ----

function verseNode(item, isCited) {
  const tag = isCited ? 'mark' : 'span';
  const number = item.verse ? el('sup', { class: 'verse-no', text: item.verse }) : null;
  return el(tag, { class: isCited ? 'verse is-cited' : 'verse', 'data-verse': item.verse }, [
    number,
    document.createTextNode(item.text),
  ]);
}

/** 依小標切段：小標之間的節連成一段，像印刷聖經那樣接著讀。 */
function scripture(items, isCited) {
  const groups = items.reduce((done, item) => {
    if ('heading' in item) return [...done, item];
    const last = done[done.length - 1];
    if (last?.verses) return [...done.slice(0, -1), { verses: [...last.verses, item] }];
    return [...done, { verses: [item] }];
  }, []);
  return groups.map((group) => (group.verses
    ? el('p', { class: 'scripture' }, group.verses.map((item) => verseNode(item, isCited(item))))
    : el('h3', { class: 'scripture-heading', text: group.heading })));
}

function citedRange(target) {
  const spans = citedSpans(target);
  return (item) => verseIsCited(item.verse, spans);
}

function message(text, className = 'reader-message') {
  return el('p', { class: className, text });
}

// ---- 查 /api/verse ----

async function fetchVerse(bookId, chapter, verse, signal) {
  const response = await fetch(`/api/verse/${bookId}/${chapter}/${verse}`, { signal });
  if (response.status === 404 || response.status === 400) return {};
  if (!response.ok) throw new Error(`經文查詢失敗：${response.status}`);
  return { data: await response.json() };
}

/** 合併節（2-3）查第 2、3 節會拿到同一筆，要去重。 */
function toVerseItems(results) {
  const seen = new Set();
  return results.flatMap(({ data }) => {
    const key = data?.unit_key ?? data?.verse;
    if (!data || seen.has(key)) return [];
    seen.add(key);
    const text = data.footnote ? `${data.text}（${data.footnote}）` : data.text;
    return [{ verse: String(data.verse_range || data.verse), text }];
  });
}

function numberRange(first, count) {
  return Array.from({ length: count }, (_, index) => first + index);
}

// ---- 面板狀態 ----

function setHead(ctx, { book, chapter, title, ref }) {
  ctx.head.book.textContent = book;
  ctx.head.numeral.textContent = chapter ?? '';
  ctx.head.title.textContent = title;
  ctx.head.ref.textContent = ref;
}

function present(ctx, from) {
  ctx.lookup?.abort();
  ctx.lookup = null;
  if (ctx.dialog.open) return;
  ctx.opener = from ?? null;
  const root = document.documentElement;
  root.style.setProperty('--scrollbar-width', `${window.innerWidth - root.clientWidth}px`);
  ctx.dialog.showModal();
  pushHistoryEntry(ctx);
}

// ---- 上一頁只關面板 ----
// 手機上按返回，讀者要的是關掉這一層，不是離開答案。所以開面板時多推一筆同網址的歷史，
// 按上一頁吃掉的就是這一筆；用其他方式關面板時，自己把這一筆收回，歷史才不會越積越多。

function pushHistoryEntry(ctx) {
  history.pushState({ reader: true }, '', location.href);
  ctx.entry = { url: location.href };
}

/** 面板關了（不論怎麼關）：這一筆還在就收回；它引起的 popstate 由 handlePop 吃掉。 */
function retireHistoryEntry(ctx) {
  if (!ctx.entry) return;
  ctx.entry = null;
  ctx.isRetiring = true;
  history.back();
}

/** popstate 先問這裡：回傳 true 表示已處理，畫面不必跟著網址換。 */
function handlePop(ctx) {
  if (ctx.isRetiring) {
    ctx.isRetiring = false;
    return true;
  }
  if (!ctx.dialog.open) return false;
  const stayedOnPage = ctx.entry?.url === location.href;
  ctx.entry = null;
  ctx.dialog.close();
  return stayedOnPage; // 一次跳兩筆以上就真的離開了，畫面要跟著網址走
}

function showBody(ctx, nodes) {
  ctx.body.replaceChildren(...nodes);
  ctx.body.scrollTop = 0;
  ctx.body.querySelector('.is-cited')?.scrollIntoView({ block: 'center' });
}

/** 面板開著時視窗改寬，圖會重畫、原本的按鈕就不在了：找回重畫後的同一顆。 */
function currentOpener(opener) {
  return !opener || opener.isConnected ? opener : findRedrawn(opener);
}

function restoreFocus(ctx) {
  ctx.lookup?.abort();
  ctx.lookup = null;
  currentOpener(ctx.opener)?.focus({ preventScroll: true });
  ctx.opener = null;
}

/** 逐節查回來再畫；中途換了內容（ctx.lookup 變了）就丟掉結果。 */
async function loadVerses(ctx, { bookId, chapter, verses, isCited, note, emptyMessage, retitle }) {
  const controller = new AbortController();
  ctx.lookup = controller;
  showBody(ctx, [message(TEXT.loading, 'reader-message is-loading')]);
  try {
    const results = await Promise.all(verses.map((verse) => fetchVerse(bookId, chapter, verse, controller.signal)));
    if (ctx.lookup !== controller) return;
    const items = toVerseItems(results);
    const title = results.find(({ data }) => data?.pericope_title)?.data.pericope_title;
    if (retitle && title) ctx.head.title.textContent = title;
    showBody(ctx, items.length > 0
      ? [message(note, 'reader-note'), ...scripture(items, isCited)]
      : [message(emptyMessage)]);
  } catch (err) {
    if (err?.name !== 'AbortError' && ctx.lookup === controller) showBody(ctx, [message(TEXT.lookupFailed)]);
  }
}

// ---- 三種入口 ----

/** 這題的來源；target 的 verse／verseEnd／ranges 是要高亮的節，missing 是引了但這段沒有的節。 */
function openSource(ctx, source, target = {}, from) {
  const items = parsePassageText(source.context);
  const ref = formatRef(source.start_key, source.end_key);
  const notice = target.missing ? [message(TEXT.missing(formatVerseList(target.missing)), 'reader-note')] : [];
  present(ctx, from);
  setHead(ctx, { book: source.book, chapter: source.chapter, title: source.title || ref, ref });
  showBody(ctx, items.length > 0 ? [...notice, ...scripture(items, citedRange(target))] : [message(TEXT.unreadable)]);
}

/** 模型自己引的：{bookId, chapter, verse, verseEnd?, ranges?}。一次最多查 MAX_LOOKUP_VERSES 節，查不完就照實說。 */
function openVerses(ctx, target, from) {
  const { bookId, chapter } = target;
  const cited = citedSpans(target).flatMap(([first, last]) => numberRange(first, last - first + 1));
  const verses = cited.slice(0, MAX_LOOKUP_VERSES);
  const ref = formatCitedRef(target);
  const isTrimmed = verses.length < cited.length;
  present(ctx, from);
  setHead(ctx, { book: bookById(bookId)?.name ?? '', chapter, title: ref, ref });
  return loadVerses(ctx, {
    bookId,
    chapter,
    verses,
    isCited: () => true,
    note: `${TEXT.notInSources(cited.length)}${isTrimmed ? TEXT.trimmed(verses.length) : ''}`,
    emptyMessage: TEXT.notFound,
    retitle: true,
  });
}

/** 完整圖譜裡沒進答案的段落：沒有全文，逐節查，太長只列開頭並照實說。 */
function openPassage(ctx, passage, from) {
  const start = parseKey(passage.start_key);
  const end = parseKey(passage.end_key);
  const ref = formatRef(passage.start_key, passage.end_key);
  present(ctx, from);
  setHead(ctx, { book: bookById(start?.bookId)?.name ?? '', chapter: start?.chapter, title: passage.title || ref, ref });
  if (!start) {
    showBody(ctx, [message(TEXT.unreadable)]);
    return undefined;
  }
  const sameChapter = end?.chapter === start.chapter;
  const total = sameChapter ? end.verse - start.verse + 1 : MAX_LOOKUP_VERSES;
  const count = Math.min(total, MAX_LOOKUP_VERSES);
  const isTrimmed = !sameChapter || total > MAX_LOOKUP_VERSES;
  return loadVerses(ctx, {
    bookId: start.bookId,
    chapter: start.chapter,
    verses: numberRange(start.verse, count),
    isCited: () => false,
    note: `${TEXT.unusedPassage}${isTrimmed ? TEXT.trimmed(count) : ''}`,
    emptyMessage: TEXT.unreadable,
    retitle: false,
  });
}

/** createReader(dialog) → { openSource, openVerses, openPassage, close, handlePop }。from 是關閉後要拿回焦點的元素。 */
export function createReader(dialog) {
  const part = (id) => dialog.querySelector(`#${id}`);
  const ctx = {
    dialog,
    head: { numeral: part('reader-numeral'), book: part('reader-book'), title: part('reader-title'), ref: part('reader-ref') },
    body: part('reader-body'),
    opener: null,
    lookup: null,
    entry: null,
    isRetiring: false,
  };
  part('reader-close').addEventListener('click', () => dialog.close());
  // 面板內容都包在 .reader-sheet 裡，target 是 dialog 本身就是點到外面（backdrop）
  dialog.addEventListener('click', (event) => {
    if (event.target === dialog) dialog.close();
  });
  dialog.addEventListener('close', () => {
    restoreFocus(ctx);
    retireHistoryEntry(ctx);
  });
  return {
    openSource: (source, range, from) => openSource(ctx, source, range, from),
    openVerses: (target, from) => openVerses(ctx, target, from),
    openPassage: (passage, from) => openPassage(ctx, passage, from),
    close: () => {
      if (dialog.open) dialog.close();
    },
    handlePop: () => handlePop(ctx),
  };
}
