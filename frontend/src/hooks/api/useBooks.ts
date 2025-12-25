/**
 * useBooks Hook
 *
 * Fetches all Bible books data.
 * Uses static data as fallback when API is unavailable.
 *
 * @example
 * const { data, isLoading, error } = useBooks();
 * if (data) {
 *   console.log(data.books); // BookListItem[]
 * }
 */

import { useQuery } from '@tanstack/react-query';
import { booksApi } from '@/api/endpoints/books';
import { queryKeys } from './queryKeys';
import { BIBLE_BOOKS } from '@/utils/bibleData';
import type { BooksListResponse, BookListItem } from '@/types';
import type { Testament } from '@/types/enums';

/**
 * Convert static book data to API response format
 */
function getStaticBooksResponse(): BooksListResponse {
  const books: BookListItem[] = BIBLE_BOOKS.map((book) => ({
    id: book.id,
    name_zh: book.name_zh,
    abbrev_zh: book.abbrev_zh,
    testament: book.testament as Testament,
    order_index: book.order_index,
  }));

  return {
    books,
    total: books.length,
  };
}

/**
 * Hook to fetch all Bible books
 * @returns Query result with books data
 */
export function useBooks() {
  return useQuery({
    queryKey: queryKeys.books.all,
    queryFn: async () => {
      try {
        return await booksApi.getAll();
      } catch {
        // Fallback to static data when API is unavailable
        console.warn('Books API unavailable, using static data');
        return getStaticBooksResponse();
      }
    },
    staleTime: Infinity, // Book data never changes
    gcTime: Infinity, // Keep in cache forever
  });
}

export default useBooks;
