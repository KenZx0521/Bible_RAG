/**
 * useBookVerses Hook
 *
 * Fetches verses for a specific book and chapter.
 * Uses mock data as fallback when API is unavailable.
 *
 * @example
 * const { data, isLoading, error } = useBookVerses(1, 1); // Genesis 1
 * if (data) {
 *   console.log(data.verses); // VerseItem[]
 * }
 */

import { useQuery } from '@tanstack/react-query';
import { booksApi } from '@/api/endpoints/books';
import { queryKeys } from './queryKeys';
import { getBookById } from '@/utils/bibleData';
import type { BookVersesResponse, VerseItem } from '@/types';

/**
 * Sample verses for Genesis 1 (demo data)
 */
const GENESIS_1_VERSES: string[] = [
  '起初，神創造天地。',
  '地是空虛混沌，淵面黑暗；神的靈運行在水面上。',
  '神說：「要有光」，就有了光。',
  '神看光是好的，就把光暗分開了。',
  '神稱光為「晝」，稱暗為「夜」。有晚上，有早晨，這是頭一日。',
  '神說：「諸水之間要有空氣，將水分為上下。」',
  '神就造出空氣，將空氣以下的水、空氣以上的水分開了。事就這樣成了。',
  '神稱空氣為「天」。有晚上，有早晨，是第二日。',
  '神說：「天下的水要聚在一處，使旱地露出來。」事就這樣成了。',
  '神稱旱地為「地」，稱水的聚處為「海」。神看著是好的。',
];

/**
 * Generate mock verses for demo when API is unavailable
 */
function getMockVersesResponse(bookId: number, chapter: number): BookVersesResponse {
  const book = getBookById(bookId);
  const bookName = book?.name_zh || `Book ${bookId}`;

  // Use Genesis 1 sample data for Genesis chapter 1
  const verseTexts = (bookId === 1 && chapter === 1)
    ? GENESIS_1_VERSES
    : Array.from({ length: 10 }, (_, i) => `${bookName} ${chapter}:${i + 1} 經文內容（示範資料）`);

  const verses: VerseItem[] = verseTexts.map((text, i) => ({
    id: bookId * 10000 + chapter * 100 + (i + 1),
    book_id: bookId,
    book_name: bookName,
    chapter,
    verse: i + 1,
    text,
    reference: `${bookName} ${chapter}:${i + 1}`,
  }));

  return {
    book_id: bookId,
    book_name: bookName,
    verses,
    total: verses.length,
  };
}

/**
 * Hook to fetch verses for a specific book and chapter
 * @param bookId - Book ID (1-66)
 * @param chapter - Chapter number
 * @returns Query result with verses data
 */
export function useBookVerses(bookId: number, chapter: number) {
  return useQuery<BookVersesResponse>({
    queryKey: queryKeys.books.verses(bookId, chapter),
    queryFn: async () => {
      try {
        return await booksApi.getVerses(bookId, chapter);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn(`Verses API unavailable for ${bookId}:${chapter}, using mock data`);
        return getMockVersesResponse(bookId, chapter);
      }
    },
    enabled: !!bookId && !!chapter && bookId >= 1 && bookId <= 66 && chapter >= 1,
    staleTime: 5 * 60 * 1000, // 5 minutes - verses may have updates
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

export default useBookVerses;
