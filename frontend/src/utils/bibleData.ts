/**
 * Bible RAG - Static Bible Books Data
 *
 * This file contains the static data for all 66 books of the Bible.
 * Will be replaced with API data in the future.
 */

/** Book item interface */
export interface BookItem {
  id: number;
  name_zh: string;
  abbrev_zh: string;
  testament: 'OT' | 'NT';
  order_index: number;
}

/** Old Testament books (39 books) */
const OLD_TESTAMENT: BookItem[] = [
  // Torah (律法書) - 5 books
  { id: 1, name_zh: '創世記', abbrev_zh: '創', testament: 'OT', order_index: 1 },
  { id: 2, name_zh: '出埃及記', abbrev_zh: '出', testament: 'OT', order_index: 2 },
  { id: 3, name_zh: '利未記', abbrev_zh: '利', testament: 'OT', order_index: 3 },
  { id: 4, name_zh: '民數記', abbrev_zh: '民', testament: 'OT', order_index: 4 },
  { id: 5, name_zh: '申命記', abbrev_zh: '申', testament: 'OT', order_index: 5 },
  // Historical Books (歷史書) - 12 books
  { id: 6, name_zh: '約書亞記', abbrev_zh: '書', testament: 'OT', order_index: 6 },
  { id: 7, name_zh: '士師記', abbrev_zh: '士', testament: 'OT', order_index: 7 },
  { id: 8, name_zh: '路得記', abbrev_zh: '得', testament: 'OT', order_index: 8 },
  { id: 9, name_zh: '撒母耳記上', abbrev_zh: '撒上', testament: 'OT', order_index: 9 },
  { id: 10, name_zh: '撒母耳記下', abbrev_zh: '撒下', testament: 'OT', order_index: 10 },
  { id: 11, name_zh: '列王紀上', abbrev_zh: '王上', testament: 'OT', order_index: 11 },
  { id: 12, name_zh: '列王紀下', abbrev_zh: '王下', testament: 'OT', order_index: 12 },
  { id: 13, name_zh: '歷代志上', abbrev_zh: '代上', testament: 'OT', order_index: 13 },
  { id: 14, name_zh: '歷代志下', abbrev_zh: '代下', testament: 'OT', order_index: 14 },
  { id: 15, name_zh: '以斯拉記', abbrev_zh: '拉', testament: 'OT', order_index: 15 },
  { id: 16, name_zh: '尼希米記', abbrev_zh: '尼', testament: 'OT', order_index: 16 },
  { id: 17, name_zh: '以斯帖記', abbrev_zh: '斯', testament: 'OT', order_index: 17 },
  // Wisdom/Poetry (詩歌智慧書) - 5 books
  { id: 18, name_zh: '約伯記', abbrev_zh: '伯', testament: 'OT', order_index: 18 },
  { id: 19, name_zh: '詩篇', abbrev_zh: '詩', testament: 'OT', order_index: 19 },
  { id: 20, name_zh: '箴言', abbrev_zh: '箴', testament: 'OT', order_index: 20 },
  { id: 21, name_zh: '傳道書', abbrev_zh: '傳', testament: 'OT', order_index: 21 },
  { id: 22, name_zh: '雅歌', abbrev_zh: '歌', testament: 'OT', order_index: 22 },
  // Major Prophets (大先知書) - 5 books
  { id: 23, name_zh: '以賽亞書', abbrev_zh: '賽', testament: 'OT', order_index: 23 },
  { id: 24, name_zh: '耶利米書', abbrev_zh: '耶', testament: 'OT', order_index: 24 },
  { id: 25, name_zh: '耶利米哀歌', abbrev_zh: '哀', testament: 'OT', order_index: 25 },
  { id: 26, name_zh: '以西結書', abbrev_zh: '結', testament: 'OT', order_index: 26 },
  { id: 27, name_zh: '但以理書', abbrev_zh: '但', testament: 'OT', order_index: 27 },
  // Minor Prophets (小先知書) - 12 books
  { id: 28, name_zh: '何西阿書', abbrev_zh: '何', testament: 'OT', order_index: 28 },
  { id: 29, name_zh: '約珥書', abbrev_zh: '珥', testament: 'OT', order_index: 29 },
  { id: 30, name_zh: '阿摩司書', abbrev_zh: '摩', testament: 'OT', order_index: 30 },
  { id: 31, name_zh: '俄巴底亞書', abbrev_zh: '俄', testament: 'OT', order_index: 31 },
  { id: 32, name_zh: '約拿書', abbrev_zh: '拿', testament: 'OT', order_index: 32 },
  { id: 33, name_zh: '彌迦書', abbrev_zh: '彌', testament: 'OT', order_index: 33 },
  { id: 34, name_zh: '那鴻書', abbrev_zh: '鴻', testament: 'OT', order_index: 34 },
  { id: 35, name_zh: '哈巴谷書', abbrev_zh: '哈', testament: 'OT', order_index: 35 },
  { id: 36, name_zh: '西番雅書', abbrev_zh: '番', testament: 'OT', order_index: 36 },
  { id: 37, name_zh: '哈該書', abbrev_zh: '該', testament: 'OT', order_index: 37 },
  { id: 38, name_zh: '撒迦利亞書', abbrev_zh: '亞', testament: 'OT', order_index: 38 },
  { id: 39, name_zh: '瑪拉基書', abbrev_zh: '瑪', testament: 'OT', order_index: 39 },
];

/** New Testament books (27 books) */
const NEW_TESTAMENT: BookItem[] = [
  // Gospels (福音書) - 4 books
  { id: 40, name_zh: '馬太福音', abbrev_zh: '太', testament: 'NT', order_index: 40 },
  { id: 41, name_zh: '馬可福音', abbrev_zh: '可', testament: 'NT', order_index: 41 },
  { id: 42, name_zh: '路加福音', abbrev_zh: '路', testament: 'NT', order_index: 42 },
  { id: 43, name_zh: '約翰福音', abbrev_zh: '約', testament: 'NT', order_index: 43 },
  // Acts (使徒行傳) - 1 book
  { id: 44, name_zh: '使徒行傳', abbrev_zh: '徒', testament: 'NT', order_index: 44 },
  // Pauline Epistles (保羅書信) - 13 books
  { id: 45, name_zh: '羅馬書', abbrev_zh: '羅', testament: 'NT', order_index: 45 },
  { id: 46, name_zh: '哥林多前書', abbrev_zh: '林前', testament: 'NT', order_index: 46 },
  { id: 47, name_zh: '哥林多後書', abbrev_zh: '林後', testament: 'NT', order_index: 47 },
  { id: 48, name_zh: '加拉太書', abbrev_zh: '加', testament: 'NT', order_index: 48 },
  { id: 49, name_zh: '以弗所書', abbrev_zh: '弗', testament: 'NT', order_index: 49 },
  { id: 50, name_zh: '腓立比書', abbrev_zh: '腓', testament: 'NT', order_index: 50 },
  { id: 51, name_zh: '歌羅西書', abbrev_zh: '西', testament: 'NT', order_index: 51 },
  { id: 52, name_zh: '帖撒羅尼迦前書', abbrev_zh: '帖前', testament: 'NT', order_index: 52 },
  { id: 53, name_zh: '帖撒羅尼迦後書', abbrev_zh: '帖後', testament: 'NT', order_index: 53 },
  { id: 54, name_zh: '提摩太前書', abbrev_zh: '提前', testament: 'NT', order_index: 54 },
  { id: 55, name_zh: '提摩太後書', abbrev_zh: '提後', testament: 'NT', order_index: 55 },
  { id: 56, name_zh: '提多書', abbrev_zh: '多', testament: 'NT', order_index: 56 },
  { id: 57, name_zh: '腓利門書', abbrev_zh: '門', testament: 'NT', order_index: 57 },
  // General Epistles (普通書信) - 8 books
  { id: 58, name_zh: '希伯來書', abbrev_zh: '來', testament: 'NT', order_index: 58 },
  { id: 59, name_zh: '雅各書', abbrev_zh: '雅', testament: 'NT', order_index: 59 },
  { id: 60, name_zh: '彼得前書', abbrev_zh: '彼前', testament: 'NT', order_index: 60 },
  { id: 61, name_zh: '彼得後書', abbrev_zh: '彼後', testament: 'NT', order_index: 61 },
  { id: 62, name_zh: '約翰一書', abbrev_zh: '約一', testament: 'NT', order_index: 62 },
  { id: 63, name_zh: '約翰二書', abbrev_zh: '約二', testament: 'NT', order_index: 63 },
  { id: 64, name_zh: '約翰三書', abbrev_zh: '約三', testament: 'NT', order_index: 64 },
  { id: 65, name_zh: '猶大書', abbrev_zh: '猶', testament: 'NT', order_index: 65 },
  // Revelation (啟示錄) - 1 book
  { id: 66, name_zh: '啟示錄', abbrev_zh: '啟', testament: 'NT', order_index: 66 },
];

/** All 66 books of the Bible */
export const BIBLE_BOOKS: BookItem[] = [...OLD_TESTAMENT, ...NEW_TESTAMENT];

/** Get Old Testament books only */
export const getOldTestamentBooks = (): BookItem[] => OLD_TESTAMENT;

/** Get New Testament books only */
export const getNewTestamentBooks = (): BookItem[] => NEW_TESTAMENT;

/** Get book by ID */
export const getBookById = (id: number): BookItem | undefined =>
  BIBLE_BOOKS.find((book) => book.id === id);

/** Get book by abbreviation */
export const getBookByAbbrev = (abbrev: string): BookItem | undefined =>
  BIBLE_BOOKS.find((book) => book.abbrev_zh === abbrev);
