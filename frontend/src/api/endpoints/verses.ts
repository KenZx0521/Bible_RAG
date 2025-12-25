/**
 * Bible RAG - Verses API Endpoints
 *
 * Verse-related API calls.
 */

import apiClient from '../client';
import type {
  VerseDetail,
  VerseSearchParams,
  VerseSearchResponse,
  VersesListParams,
  VersesListResponse,
} from '@/types';

/** Verses API */
export const versesApi = {
  /**
   * Get verses list
   * @param params - List parameters
   * @returns Verses list response
   */
  getList: async (params?: VersesListParams): Promise<VersesListResponse> => {
    const response = await apiClient.get<VersesListResponse>('/verses', {
      params,
    });
    return response.data;
  },

  /**
   * Get verse by ID
   * @param verseId - Verse ID
   * @returns Verse detail
   */
  getById: async (verseId: number): Promise<VerseDetail> => {
    const response = await apiClient.get<VerseDetail>(`/verses/${verseId}`);
    return response.data;
  },

  /**
   * Search verses
   * @param params - Search parameters
   * @returns Verse search response
   */
  search: async (params: VerseSearchParams): Promise<VerseSearchResponse> => {
    const response = await apiClient.get<VerseSearchResponse>('/verses/search', {
      params,
    });
    return response.data;
  },
};
