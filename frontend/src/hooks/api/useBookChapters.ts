/**
 * useBookChapters Hook
 *
 * Fetches chapters for a specific Bible book.
 * Uses static data as fallback when API is unavailable.
 *
 * @example
 * const { data, isLoading, error } = useBookChapters(1); // Genesis
 * if (data) {
 *   console.log(data.chapters); // ChapterInfo[]
 * }
 */

import { useQuery } from '@tanstack/react-query';
import { booksApi } from '@/api/endpoints/books';
import { queryKeys } from './queryKeys';
import { getBookById } from '@/utils/bibleData';
import type { BookChaptersResponse, ChapterInfo } from '@/types';

/**
 * Static chapter counts for each book (1-66)
 * Source: Protestant Bible canon
 */
const BOOK_CHAPTER_COUNTS: Record<number, number> = {
  // Old Testament
  1: 50, // Genesis
  2: 40, // Exodus
  3: 27, // Leviticus
  4: 36, // Numbers
  5: 34, // Deuteronomy
  6: 24, // Joshua
  7: 21, // Judges
  8: 4, // Ruth
  9: 31, // 1 Samuel
  10: 24, // 2 Samuel
  11: 22, // 1 Kings
  12: 25, // 2 Kings
  13: 29, // 1 Chronicles
  14: 36, // 2 Chronicles
  15: 10, // Ezra
  16: 13, // Nehemiah
  17: 10, // Esther
  18: 42, // Job
  19: 150, // Psalms
  20: 31, // Proverbs
  21: 12, // Ecclesiastes
  22: 8, // Song of Solomon
  23: 66, // Isaiah
  24: 52, // Jeremiah
  25: 5, // Lamentations
  26: 48, // Ezekiel
  27: 12, // Daniel
  28: 14, // Hosea
  29: 3, // Joel
  30: 9, // Amos
  31: 1, // Obadiah
  32: 4, // Jonah
  33: 7, // Micah
  34: 3, // Nahum
  35: 3, // Habakkuk
  36: 3, // Zephaniah
  37: 2, // Haggai
  38: 14, // Zechariah
  39: 4, // Malachi
  // New Testament
  40: 28, // Matthew
  41: 16, // Mark
  42: 24, // Luke
  43: 21, // John
  44: 28, // Acts
  45: 16, // Romans
  46: 16, // 1 Corinthians
  47: 13, // 2 Corinthians
  48: 6, // Galatians
  49: 6, // Ephesians
  50: 4, // Philippians
  51: 4, // Colossians
  52: 5, // 1 Thessalonians
  53: 3, // 2 Thessalonians
  54: 6, // 1 Timothy
  55: 4, // 2 Timothy
  56: 3, // Titus
  57: 1, // Philemon
  58: 13, // Hebrews
  59: 5, // James
  60: 5, // 1 Peter
  61: 3, // 2 Peter
  62: 5, // 1 John
  63: 1, // 2 John
  64: 1, // 3 John
  65: 1, // Jude
  66: 22, // Revelation
};

/**
 * Generate static chapters response for a book
 */
function getStaticChaptersResponse(bookId: number): BookChaptersResponse | null {
  const book = getBookById(bookId);
  if (!book) return null;

  const chapterCount = BOOK_CHAPTER_COUNTS[bookId] || 0;
  const chapters: ChapterInfo[] = Array.from({ length: chapterCount }, (_, i) => ({
    chapter: i + 1,
    verse_count: 0, // Unknown without API
  }));

  return {
    book_id: bookId,
    book_name: book.name_zh,
    chapters,
  };
}

/**
 * Hook to fetch chapters for a specific book
 * @param bookId - Book ID (1-66)
 * @returns Query result with chapters data
 */
export function useBookChapters(bookId: number) {
  return useQuery({
    queryKey: queryKeys.books.chapters(bookId),
    queryFn: async () => {
      try {
        return await booksApi.getChapters(bookId);
      } catch {
        // Fallback to static data when API is unavailable
        console.warn(`Book chapters API unavailable for book ${bookId}, using static data`);
        const response = getStaticChaptersResponse(bookId);
        if (!response) {
          throw new Error(`Book with ID ${bookId} not found`);
        }
        return response;
      }
    },
    enabled: !!bookId && bookId >= 1 && bookId <= 66,
    staleTime: Infinity, // Chapter data never changes
    gcTime: Infinity,
  });
}

export default useBookChapters;
