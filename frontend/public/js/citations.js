// 從答案文字解析經文引用，並決定每筆引用要開哪裡。純函式，不碰 DOM。
// 只認完整書名（列王紀、歷代志這類對應兩卷的不是引用）；沒有節也沒有 source 編號的
// 「創世記 第28章」留成文字，因為它對不到任何一節可查。
import { BOOKS, bookById, bookByName, parseKey } from './books.js';

const SPACE = '[ \\t\\u3000]*';
const NUMBER = '[1-9]\\d{0,2}';
const BLOCK = '[1-9]\\d?';
const DASH = '[-–—~～至到]';
const LIST = '[,，、]';
const NAMES = BOOKS.map((book) => book.name)
  .sort((a, b) => b.length - a.length)
  .join('|');

// 「13:1-3」；尾端若接冒號就是跨章（13:1-14:2），範圍不成立，只取起點
const COLON_FORM = `(?<colonChapter>${NUMBER})${SPACE}[:：]${SPACE}(?<colonVerse>${NUMBER})`
  + `(?:${SPACE}${DASH}${SPACE}(?<colonEnd>${NUMBER})(?![\\d:：]))?(?!\\d)`;

// 答案是 LLM 輸出、沒有長度上限：兩段空白之間不可夾可省略的字（「節?」「第?」），同一段空白會有多種切法，
// 列舉一長就指數回溯、凍結分頁。所以一律寫成「(?:節 空白)?」，空白只能歸給它前面那個字。
const OPTIONAL_DI = `(?:第${SPACE})?`;

// 節的部分：「5」「27-28」「13節-14」「7, 8」「13節、14」，後面的「節」由外層比對
const VERSES = `${NUMBER}(?:${SPACE}(?:節${SPACE})?(?:${DASH}|${LIST})${SPACE}${OPTIONAL_DI}${NUMBER})*`;

// 「第22章 41節」「第28章 [3]」「第32章（24-26節）」；章與篇都有人寫
const CHAPTER_FORM = `${OPTIONAL_DI}(?<chapter>${NUMBER})${SPACE}[章篇]${SPACE}(?:`
  + `[\\[［]${SPACE}(?<chapterBlock>${BLOCK})${SPACE}[\\]］]`
  + `|[（(]${SPACE}${OPTIONAL_DI}(?<parenVerses>${VERSES})${SPACE}節${SPACE}[）)]`
  + `|${OPTIONAL_DI}(?<verses>${VERSES})${SPACE}節)`;

const BLOCK_ONLY_FORM = `經文${SPACE}[\\[［]${SPACE}(?<block>${BLOCK})${SPACE}[\\]］]`;

// 書名可能包在書名號裡：「《路加福音》第11章第28節」
const BOOK_NAME = `(?:《(?<quotedBook>${NAMES})》|(?<plainBook>${NAMES}))`;

const CITATION_PATTERN = `(?:${BOOK_NAME}${SPACE}(?:${COLON_FORM}|${CHAPTER_FORM}))|${BLOCK_ONLY_FORM}`;

// 列舉的一段：「27-28」→ 27,28；「第14」→ 14
const LIST_SPLIT = new RegExp(LIST);
const RANGE = new RegExp(`(\\d+)(?:\\s*(?:節\\s*)?${DASH}\\s*(?:第\\s*)?(\\d+))?`);

function withVerses(base, verse, verseEnd) {
  const start = Number(verse);
  const end = Number(verseEnd);
  return end > start ? { ...base, verse: start, verseEnd: end } : { ...base, verse: start };
}

/** 「38-39、41」→ [[38,39],[41,41]]；倒過來的段當單節。 */
function verseRanges(verses) {
  return verses.split(LIST_SPLIT).map((part) => {
    const [, first, last] = RANGE.exec(part);
    const start = Number(first);
    return [start, Math.max(start, Number(last ?? first))];
  });
}

function parseMatch(match) {
  const base = { start: match.index, end: match.index + match[0].length, raw: match[0] };
  const { quotedBook, plainBook, colonChapter, colonVerse, colonEnd, chapter, chapterBlock, parenVerses, verses, block } = match.groups;
  const book = quotedBook ?? plainBook;
  if (!book) return { ...base, bookId: null, bookName: null, chapter: null, block: Number(block) };
  const named = { ...base, bookId: bookByName(book).book_id, bookName: book };
  if (colonChapter) return withVerses({ ...named, chapter: Number(colonChapter) }, colonVerse, colonEnd);
  const inChapter = { ...named, chapter: Number(chapter) };
  if (chapterBlock) return { ...inChapter, block: Number(chapterBlock) };
  const ranges = verseRanges(parenVerses ?? verses);
  const [[first, last]] = ranges;
  const parsed = withVerses(inChapter, first, last);
  return ranges.length > 1 ? { ...parsed, ranges } : parsed;
}

/** 文字 → [{start,end,raw,bookId,bookName,chapter,verse?,verseEnd?,ranges?,block?}]，依出現順序、互不重疊。
 *  verse／verseEnd 是第一段；列舉式（「4節、6節」）另有 ranges 列出每一段。
 *  「經文[1]」沒有書卷，bookId／bookName／chapter 為 null。 */
export function findCitations(text) {
  if (typeof text !== 'string') return [];
  const pattern = new RegExp(CITATION_PATTERN, 'gu');
  return Array.from(text.matchAll(pattern), parseMatch);
}

/** 引用的每一段 [[起,迄]…]；沒有節回空陣列。 */
export function citedSpans({ verse, verseEnd, ranges }) {
  if (ranges) return ranges;
  return verse === undefined ? [] : [[verse, verseEnd ?? verse]];
}

/** [[33,40],[45,45]] → '33-40、45'。 */
export function formatVerseList(spans) {
  return spans.map(([first, last]) => (first === last ? `${first}` : `${first}-${last}`)).join('、');
}

/** {bookId, chapter, verse, verseEnd?, ranges?} → '使徒行傳 13:4、6-8'：引用實際引了哪些節。 */
export function formatCitedRef(target) {
  return `${bookById(target.bookId).name} ${target.chapter}:${formatVerseList(citedSpans(target))}`;
}

/** 來源在這一章涵蓋到的節；不是這卷這章回 null。 */
function boundsInChapter(source, { bookId, chapter }) {
  const start = parseKey(source.start_key);
  const end = parseKey(source.end_key);
  if (!start || !end || start.bookId !== bookId || chapter < start.chapter || chapter > end.chapter) return null;
  return {
    first: start.chapter === chapter ? start.verse : 1,
    last: end.chapter === chapter ? end.verse : Infinity,
  };
}

function covers(source, citation) {
  const bounds = boundsInChapter(source, citation);
  if (!bounds) return false;
  return citation.verse === undefined || (bounds.first <= citation.verse && citation.verse <= bounds.last);
}

/** 引用裡落在來源之外的節，還是 [[起,迄]…]。 */
function missingSpans(source, citation) {
  const bounds = boundsInChapter(source, citation);
  return citedSpans(citation).flatMap(([first, last]) => [
    [first, Math.min(last, bounds.first - 1)],
    [Math.max(first, bounds.last + 1), last],
  ].filter(([from, to]) => from <= to));
}

function countVerses(spans) {
  return spans.reduce((sum, [first, last]) => sum + last - first + 1, 0);
}

/** 涵蓋起點的來源裡，缺的節最少的那個；一樣多就取最前面（單節引用因此維持開第一個涵蓋的來源）。 */
function bestSource(citation, sources) {
  return sources.reduce((best, source, sourceIndex) => {
    if (!covers(source, citation)) return best;
    const missing = missingSpans(source, citation);
    return best && countVerses(best.missing) <= countVerses(missing) ? best : { sourceIndex, missing };
  }, null);
}

function versePart({ verse, verseEnd, ranges }) {
  return {
    ...(verse === undefined ? {} : { verse }),
    ...(verseEnd === undefined ? {} : { verseEnd }),
    ...(ranges === undefined ? {} : { ranges }),
  };
}

/** 引用該開哪裡，順序依契約：
 *  {type:'source', sourceIndex, verse?, verseEnd?, ranges?, missing?}（sources 的索引，從 0 起算）→ 開該段並高亮；
 *  missing 是引用了但這段來源沒有的節，面板要照實說；
 *  {type:'verse', bookId, chapter, verse, verseEnd?, ranges?} → 模型自己引的，改查 /api/verse；
 *  null → 無法解析，不准做成按鈕。 */
export function resolveCitation(citation, sources = []) {
  const byBlock = citation.block === undefined ? undefined : sources[citation.block - 1];
  // 「創世記 第28章 [1]」若第 1 個 source 根本不是創世記 28 章，就不信這個編號，改依書卷章找
  if (byBlock && (citation.bookId === null || covers(byBlock, citation))) {
    return { type: 'source', sourceIndex: citation.block - 1, ...versePart(citation) };
  }
  if (citation.bookId === null) return null;
  const best = bestSource(citation, sources);
  if (best) {
    const missing = best.missing.length > 0 ? { missing: best.missing } : {};
    return { type: 'source', sourceIndex: best.sourceIndex, ...versePart(citation), ...missing };
  }
  if (citation.verse === undefined) return null;
  const { bookId, chapter } = citation;
  return { type: 'verse', bookId, chapter, ...versePart(citation) };
}
