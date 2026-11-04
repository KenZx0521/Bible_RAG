// 66 卷書卷表：中文名與 book_id 互查，以及經節 key 的解析與顯示。
// 資料抄自 packages/ragcommon/data/books.json（book_id、name、ord、testament），
// test/books.test.mjs 會逐欄比對來源，來源改了測試就會失敗。純函式，瀏覽器與 Node 共用。

const ROWS = [
  ['gen', '創世記', 1, 'OT'],
  ['exo', '出埃及記', 2, 'OT'],
  ['lev', '利未記', 3, 'OT'],
  ['num', '民數記', 4, 'OT'],
  ['deu', '申命記', 5, 'OT'],
  ['jos', '約書亞記', 6, 'OT'],
  ['jdg', '士師記', 7, 'OT'],
  ['rut', '路得記', 8, 'OT'],
  ['1sa', '撒母耳記上', 9, 'OT'],
  ['2sa', '撒母耳記下', 10, 'OT'],
  ['1ki', '列王紀上', 11, 'OT'],
  ['2ki', '列王紀下', 12, 'OT'],
  ['1ch', '歷代志上', 13, 'OT'],
  ['2ch', '歷代志下', 14, 'OT'],
  ['ezr', '以斯拉記', 15, 'OT'],
  ['neh', '尼希米記', 16, 'OT'],
  ['est', '以斯帖記', 17, 'OT'],
  ['job', '約伯記', 18, 'OT'],
  ['psa', '詩篇', 19, 'OT'],
  ['pro', '箴言', 20, 'OT'],
  ['ecc', '傳道書', 21, 'OT'],
  ['sng', '雅歌', 22, 'OT'],
  ['isa', '以賽亞書', 23, 'OT'],
  ['jer', '耶利米書', 24, 'OT'],
  ['lam', '耶利米哀歌', 25, 'OT'],
  ['ezk', '以西結書', 26, 'OT'],
  ['dan', '但以理書', 27, 'OT'],
  ['hos', '何西阿書', 28, 'OT'],
  ['jol', '約珥書', 29, 'OT'],
  ['amo', '阿摩司書', 30, 'OT'],
  ['oba', '俄巴底亞書', 31, 'OT'],
  ['jon', '約拿書', 32, 'OT'],
  ['mic', '彌迦書', 33, 'OT'],
  ['nam', '那鴻書', 34, 'OT'],
  ['hab', '哈巴谷書', 35, 'OT'],
  ['zep', '西番雅書', 36, 'OT'],
  ['hag', '哈該書', 37, 'OT'],
  ['zec', '撒迦利亞書', 38, 'OT'],
  ['mal', '瑪拉基書', 39, 'OT'],
  ['mat', '馬太福音', 40, 'NT'],
  ['mrk', '馬可福音', 41, 'NT'],
  ['luk', '路加福音', 42, 'NT'],
  ['jhn', '約翰福音', 43, 'NT'],
  ['act', '使徒行傳', 44, 'NT'],
  ['rom', '羅馬書', 45, 'NT'],
  ['1co', '哥林多前書', 46, 'NT'],
  ['2co', '哥林多後書', 47, 'NT'],
  ['gal', '加拉太書', 48, 'NT'],
  ['eph', '以弗所書', 49, 'NT'],
  ['php', '腓立比書', 50, 'NT'],
  ['col', '歌羅西書', 51, 'NT'],
  ['1th', '帖撒羅尼迦前書', 52, 'NT'],
  ['2th', '帖撒羅尼迦後書', 53, 'NT'],
  ['1ti', '提摩太前書', 54, 'NT'],
  ['2ti', '提摩太後書', 55, 'NT'],
  ['tit', '提多書', 56, 'NT'],
  ['phm', '腓利門書', 57, 'NT'],
  ['heb', '希伯來書', 58, 'NT'],
  ['jas', '雅各書', 59, 'NT'],
  ['1pe', '彼得前書', 60, 'NT'],
  ['2pe', '彼得後書', 61, 'NT'],
  ['1jn', '約翰一書', 62, 'NT'],
  ['2jn', '約翰二書', 63, 'NT'],
  ['3jn', '約翰三書', 64, 'NT'],
  ['jud', '猶大書', 65, 'NT'],
  ['rev', '啟示錄', 66, 'NT'],
];

export const BOOKS = Object.freeze(
  ROWS.map(([book_id, name, ord, testament]) => Object.freeze({ book_id, name, ord, testament })),
);

const BY_ID = new Map(BOOKS.map((book) => [book.book_id, book]));
const BY_NAME = new Map(BOOKS.map((book) => [book.name, book]));
const KEY_PATTERN = /^([1-9a-z]{3})\.(\d+)\.(\d+)([a-z]?)$/;

export function bookById(id) {
  return BY_ID.get(id);
}

export function bookByName(name) {
  return BY_NAME.get(name);
}

export function isBookId(id) {
  return BY_ID.has(id);
}

/** 'act.13.4' → {bookId, chapter, verse, part}；part 是半節尾碼（'1co.12.31b' 的 b）。不是合法經節 key 回 null。 */
export function parseKey(key) {
  const match = typeof key === 'string' ? KEY_PATTERN.exec(key) : null;
  if (!match || !isBookId(match[1])) return null;
  return { bookId: match[1], chapter: Number(match[2]), verse: Number(match[3]), part: match[4] };
}

function verseLabel(parsed) {
  return `${parsed.verse}${parsed.part}`;
}

/** ('act.13.1','act.13.3') → '使徒行傳 13:1-3'；單節與無法解析的尾端都只顯示起點；起點壞了回空字串。 */
export function formatRef(startKey, endKey = startKey) {
  const start = parseKey(startKey);
  if (!start) return '';
  const head = `${bookById(start.bookId).name} ${start.chapter}:${verseLabel(start)}`;
  const end = parseKey(endKey);
  if (!end || endKey === startKey) return head;
  if (end.chapter !== start.chapter) return `${head}-${end.chapter}:${verseLabel(end)}`;
  return `${head}-${verseLabel(end)}`;
}
