/**
 * Bible RAG - Pericopes API Endpoints
 *
 * Pericope-related API calls.
 */

import apiClient from '../client';
import type {
  PericopeDetail,
  PericopesListParams,
  PericopesListResponse,
} from '@/types';

/** Pericopes API */
export const pericopesApi = {
  /**
   * Get pericopes list
   * @param params - List parameters
   * @returns Pericopes list response
   */
  getList: async (
    params?: PericopesListParams
  ): Promise<PericopesListResponse> => {
    const response = await apiClient.get<PericopesListResponse>('/pericopes', {
      params,
    });
    return response.data;
  },

  /**
   * Get pericope by ID
   * @param pericopeId - Pericope ID
   * @returns Pericope detail
   */
  getById: async (pericopeId: number): Promise<PericopeDetail> => {
    const response = await apiClient.get<PericopeDetail>(
      `/pericopes/${pericopeId}`
    );
    return response.data;
  },
};
