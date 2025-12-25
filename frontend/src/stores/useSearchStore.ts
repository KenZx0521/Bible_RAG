/**
 * Bible RAG - Search Store
 *
 * Search state management with Zustand.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { QueryMode, SearchState } from '@/types';
import { STORAGE_KEYS } from '@/utils/constants';

/** Maximum history length */
const MAX_HISTORY_LENGTH = 20;

/** Initial state */
const initialState = {
  history: [] as string[],
  maxHistoryLength: MAX_HISTORY_LENGTH,
  currentQuery: '',
  currentMode: 'auto' as QueryMode,
};

/** Search store */
export const useSearchStore = create<SearchState>()(
  persist(
    (set) => ({
      // State
      ...initialState,

      // Actions
      setQuery: (query: string) => set({ currentQuery: query }),

      setMode: (mode: QueryMode) => set({ currentMode: mode }),

      addToHistory: (query: string) =>
        set((state) => {
          // Remove duplicate if exists
          const filteredHistory = state.history.filter((q) => q !== query);
          // Add to front and limit length
          const newHistory = [query, ...filteredHistory].slice(
            0,
            state.maxHistoryLength
          );
          return { history: newHistory };
        }),

      clearHistory: () => set({ history: [] }),
    }),
    {
      name: STORAGE_KEYS.SEARCH_HISTORY,
      partialize: (state) => ({
        history: state.history,
      }),
    }
  )
);
