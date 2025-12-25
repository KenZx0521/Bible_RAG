/**
 * useVerses Hooks
 *
 * Hooks for fetching verse data.
 * Includes detail, list, and search queries with fallback data.
 *
 * @example
 * // Get verse detail
 * const { data, isLoading, error } = useVerseDetail(123);
 * if (data) {
 *   console.log(data.reference, data.text);
 * }
 *
 * // Search verses
 * const { data } = useVerseSearch({ q: '愛', limit: 20 });
 */

import { useQuery } from '@tanstack/react-query';
import { versesApi } from '@/api/endpoints/verses';
import { queryKeys } from './queryKeys';
import type {
  VerseDetail,
  VerseSearchParams,
  VerseSearchResponse,
  VersesListParams,
  VersesListResponse,
} from '@/types';

/**
 * Mock data for development/fallback
 */
const getMockVerseDetail = (id: number): VerseDetail => ({
  id,
  book_id: 1,
  book_name: '創世記',
  chapter: 1,
  verse: 1,
  text: '起初，神創造天地。',
  reference: '創世記 1:1',
  pericope_id: 1,
  pericope_title: '天地的創造',
});

const getMockVersesListResponse = (): VersesListResponse => ({
  verses: [
    {
      id: 1,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 1,
      text: '起初，神創造天地。',
      reference: '創世記 1:1',
    },
    {
      id: 2,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 2,
      text: '地是空虛混沌，淵面黑暗；神的靈運行在水面上。',
      reference: '創世記 1:2',
    },
    {
      id: 3,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 3,
      text: '神說：「要有光」，就有了光。',
      reference: '創世記 1:3',
    },
  ],
  total: 3,
  skip: 0,
  limit: 20,
});

const getMockVerseSearchResponse = (query: string): VerseSearchResponse => ({
  query,
  verses: [
    {
      id: 1,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 1,
      text: '起初，神創造天地。',
      reference: '創世記 1:1',
      rank: 0.95,
    },
  ],
  total: 1,
});

/**
 * Hook to fetch verse detail by ID
 * @param id - Verse ID
 * @returns Query result with verse detail
 */
export function useVerseDetail(id: number) {
  return useQuery({
    queryKey: queryKeys.verses.detail(id),
    queryFn: async () => {
      try {
        return await versesApi.getById(id);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn('Verses API unavailable, using mock data');
        return getMockVerseDetail(id);
      }
    },
    enabled: !!id && id > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to fetch verses list
 * @param params - List parameters (book_id, chapter, pericope_id, skip, limit)
 * @returns Query result with verses list
 */
export function useVersesList(params?: VersesListParams) {
  return useQuery({
    queryKey: queryKeys.verses.list(params ?? {}),
    queryFn: async () => {
      try {
        return await versesApi.getList(params);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn('Verses API unavailable, using mock data');
        return getMockVersesListResponse();
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to search verses
 * @param params - Search parameters (q, book_id, limit)
 * @returns Query result with search response
 */
export function useVerseSearch(params: VerseSearchParams) {
  return useQuery({
    queryKey: queryKeys.verses.search(params),
    queryFn: async () => {
      try {
        return await versesApi.search(params);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn('Verse search API unavailable, using mock data');
        return getMockVerseSearchResponse(params.q);
      }
    },
    enabled: !!params.q && params.q.trim().length > 0,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });
}

export default useVerseDetail;
