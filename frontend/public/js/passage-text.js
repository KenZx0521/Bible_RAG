// 把 source.context 解析成經節陣列。純函式，不碰 DOM。
// 第一行是標頭「[1] 使徒行傳 第15章 - 標題 (36-41節)」；內文有段落「**36** …」（空行分節）、
// 單節「16. …」兩種，章節區塊另有【標題】行。同一節裡的換行是詩體，要留著。
// 節標籤可能是合併節（**29-30**、2-3.），語料裡有 70 個。

const HEADER = /^\[\d+\]/;
const HEADING = /^【(.+)】$/;
const LABEL = '\\d+[a-z]?(?:-\\d+[a-z]?)?';
const VERSE_LINE = new RegExp(`^(?:\\*\\*(${LABEL})\\*\\*|(${LABEL})\\.)\\s*(.*)$`);
const LABEL_SPAN = /^(\d+)[a-z]?(?:-(\d+)[a-z]?)?$/;

function stripHeader(context) {
  const lines = context.split('\n');
  return HEADER.test(lines[0]) ? lines.slice(1) : lines;
}

function appendToLast(items, line) {
  const last = items[items.length - 1];
  if (last && 'verse' in last) {
    return [...items.slice(0, -1), { ...last, text: `${last.text}\n${line}` }];
  }
  return [...items, { verse: '', text: line }];
}

function addLine(items, line) {
  const heading = HEADING.exec(line);
  if (heading) return [...items, { heading: heading[1] }];
  const verse = VERSE_LINE.exec(line);
  if (verse) return [...items, { verse: verse[1] ?? verse[2], text: verse[3] }];
  return appendToLast(items, line);
}

/** context → [{verse:'36', text}|{heading}]；節號之前的文字 verse 為空字串，一個字都不丟。 */
export function parsePassageText(context) {
  if (typeof context !== 'string' || context === '') return [];
  return stripHeader(context)
    .map((line) => line.trim())
    .filter((line) => line !== '')
    .reduce(addLine, []);
}

/** 節標籤 → 涵蓋的節：'29-30' → {first:29,last:30}；'31b' → 31；沒有節號回 null。 */
export function verseSpan(label) {
  const match = LABEL_SPAN.exec(label ?? '');
  if (!match) return null;
  const first = Number(match[1]);
  return { first, last: match[2] ? Number(match[2]) : first };
}

/** 這個節標籤有沒有落在引用的任一段裡；引用第 30 節時，合併節「29-30」也算。spans 是 [[起,迄]…]。 */
export function verseIsCited(label, spans) {
  const span = verseSpan(label);
  return span !== null && spans.some(([first, last]) => span.first <= last && first <= span.last);
}
