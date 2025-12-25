/**
 * Bible RAG - App Store
 *
 * Global application state management with Zustand.
 */

import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { AppState, Theme } from '@/types';
import { STORAGE_KEYS } from '@/utils/constants';

/** Initial state */
const initialState = {
  sidebarOpen: true,
  theme: 'system' as Theme,
  selectedBookId: null,
  selectedChapter: null,
  selectedPericopeId: null,
};

/** App store */
export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // State
      ...initialState,

      // Actions
      toggleSidebar: () =>
        set((state) => ({ sidebarOpen: !state.sidebarOpen })),

      setTheme: (theme: Theme) => set({ theme }),

      selectBook: (bookId: number | null) =>
        set({
          selectedBookId: bookId,
          selectedChapter: null,
          selectedPericopeId: null,
        }),

      selectChapter: (chapter: number | null) =>
        set({
          selectedChapter: chapter,
          selectedPericopeId: null,
        }),

      selectPericope: (pericopeId: number | null) =>
        set({ selectedPericopeId: pericopeId }),

      reset: () => set(initialState),
    }),
    {
      name: STORAGE_KEYS.THEME,
      partialize: (state) => ({
        theme: state.theme,
        sidebarOpen: state.sidebarOpen,
      }),
    }
  )
);
