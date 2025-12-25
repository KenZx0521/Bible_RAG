/**
 * usePericopes Hooks
 *
 * Hooks for fetching pericope data.
 * Includes list and detail queries with fallback data.
 *
 * @example
 * // Get pericope detail
 * const { data, isLoading, error } = usePericopeDetail(123);
 * if (data) {
 *   console.log(data.title, data.verses);
 * }
 *
 * // List pericopes with filter
 * const { data } = usePericopes({ book_id: 1, limit: 10 });
 */

import { useQuery } from '@tanstack/react-query';
import { pericopesApi } from '@/api/endpoints/pericopes';
import { queryKeys } from './queryKeys';
import type {
  PericopeDetail,
  PericopesListParams,
  PericopesListResponse,
} from '@/types';

/**
 * Mock data for development/fallback
 */
const getMockPericopeDetail = (id: number): PericopeDetail => ({
  id,
  book_id: 1,
  book_name: '創世記',
  title: '天地的創造',
  reference: '創世記 1:1-31',
  chapter_start: 1,
  verse_start: 1,
  chapter_end: 1,
  verse_end: 31,
  summary:
    '這段經文描述了神創造天地的開始。神在六天內創造了光、空氣、陸地、植物、日月星辰、海洋生物、飛鳥、陸地動物，最後按照自己的形象創造了人類。每一天的創造，神都看為美好。',
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
    {
      id: 4,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 4,
      text: '神看光是好的，就把光暗分開了。',
      reference: '創世記 1:4',
    },
    {
      id: 5,
      book_id: 1,
      book_name: '創世記',
      chapter: 1,
      verse: 5,
      text: '神稱光為「晝」，稱暗為「夜」。有晚上，有早晨，這是頭一日。',
      reference: '創世記 1:5',
    },
  ],
});

const getMockPericopesListResponse = (): PericopesListResponse => ({
  pericopes: [
    {
      id: 1,
      book_id: 1,
      book_name: '創世記',
      title: '天地的創造',
      reference: '創世記 1:1-31',
      chapter_start: 1,
      verse_start: 1,
      chapter_end: 1,
      verse_end: 31,
    },
    {
      id: 2,
      book_id: 1,
      book_name: '創世記',
      title: '安息日',
      reference: '創世記 2:1-3',
      chapter_start: 2,
      verse_start: 1,
      chapter_end: 2,
      verse_end: 3,
    },
  ],
  total: 2,
  skip: 0,
  limit: 20,
});

/**
 * Hook to fetch pericope detail by ID
 * @param id - Pericope ID
 * @returns Query result with pericope detail
 */
export function usePericopeDetail(id: number) {
  return useQuery({
    queryKey: queryKeys.pericopes.detail(id),
    queryFn: async () => {
      try {
        return await pericopesApi.getById(id);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn('Pericopes API unavailable, using mock data');
        return getMockPericopeDetail(id);
      }
    },
    enabled: !!id && id > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to fetch pericopes list
 * @param params - List parameters (book_id, skip, limit)
 * @returns Query result with pericopes list
 */
export function usePericopes(params?: PericopesListParams) {
  return useQuery({
    queryKey: queryKeys.pericopes.list(params ?? {}),
    queryFn: async () => {
      try {
        return await pericopesApi.getList(params);
      } catch {
        // Fallback to mock data when API is unavailable
        console.warn('Pericopes API unavailable, using mock data');
        return getMockPericopesListResponse();
      }
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

export default usePericopeDetail;
