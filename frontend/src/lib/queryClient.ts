/**
 * Bible RAG - TanStack Query Client
 *
 * Centralized React Query configuration.
 */

import { QueryClient } from '@tanstack/react-query';

/** Create query client with default options */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      /** Stale time: 5 minutes */
      staleTime: 5 * 60 * 1000,
      /** Garbage collection time: 30 minutes */
      gcTime: 30 * 60 * 1000,
      /** Retry configuration */
      retry: (failureCount, error) => {
        // Don't retry on 4xx errors
        if (error && typeof error === 'object' && 'response' in error) {
          const response = (error as { response?: { status?: number } }).response;
          if (response?.status && response.status >= 400 && response.status < 500) {
            return false;
          }
        }
        // Retry up to 3 times for other errors
        return failureCount < 3;
      },
      /** Retry delay: exponential backoff */
      retryDelay: (attemptIndex) => Math.min(1000 * 2 ** attemptIndex, 30000),
      /** Don't refetch on window focus by default */
      refetchOnWindowFocus: false,
    },
    mutations: {
      /** Retry once for mutations */
      retry: 1,
    },
  },
});
