/**
 * useRagQuery Hook
 *
 * TanStack Query mutation hook for RAG query execution.
 * Handles API calls to the RAG query endpoint and manages search history.
 *
 * @example
 * const { mutate, isPending, data, error } = useRagQuery();
 *
 * // Execute a query
 * mutate({ query: "What does the Bible say about love?", mode: "auto" });
 *
 * // With options
 * mutate({
 *   query: "Who was David?",
 *   mode: "person",
 *   options: { max_results: 10, include_graph: true }
 * });
 */

import { useMutation } from '@tanstack/react-query';
import { queryApi } from '@/api/endpoints/query';
import { useSearchStore } from '@/stores/useSearchStore';
import type { QueryRequest, QueryResponse } from '@/types';

/** Hook options */
export interface UseRagQueryOptions {
  /** Callback on successful query */
  onSuccess?: (data: QueryResponse) => void;
  /** Callback on query error */
  onError?: (error: Error) => void;
}

/**
 * RAG Query mutation hook
 *
 * @param options - Hook options
 * @returns TanStack Query mutation result
 */
export function useRagQuery(options?: UseRagQueryOptions) {
  const addToHistory = useSearchStore((state) => state.addToHistory);

  return useMutation({
    mutationFn: async (request: QueryRequest): Promise<QueryResponse> => {
      return queryApi.query(request);
    },
    onSuccess: (data, variables) => {
      // Add query to search history
      addToHistory(variables.query);

      // Call user callback
      options?.onSuccess?.(data);
    },
    onError: (error: Error) => {
      console.error('[useRagQuery] Query failed:', error);
      options?.onError?.(error);
    },
  });
}

export default useRagQuery;
