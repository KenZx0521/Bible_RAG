/**
 * Bible RAG - Query API Endpoints
 *
 * RAG query related API calls.
 */

import apiClient from '../client';
import type { QueryRequest, QueryResponse } from '@/types';

/** RAG Query API */
export const queryApi = {
  /**
   * Execute RAG query
   * @param request - Query request
   * @returns Query response with answer and segments
   */
  query: async (request: QueryRequest): Promise<QueryResponse> => {
    const response = await apiClient.post<QueryResponse>('/query', request);
    return response.data;
  },
};
