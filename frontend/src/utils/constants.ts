/**
 * Bible RAG - Application Constants
 */

/** API Configuration */
export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  TIMEOUT: 60000, // 60 seconds
} as const;

/** Pagination Configuration */
export const PAGINATION = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
} as const;

/** RAG Query Configuration */
export const RAG_CONFIG = {
  MAX_QUERY_LENGTH: 500,
  DEFAULT_MAX_RESULTS: 5,
  MAX_RESULTS: 20,
} as const;

/** Graph Configuration */
export const GRAPH_CONFIG = {
  DEFAULT_DEPTH: 2,
  MAX_DEPTH: 3,
} as const;

/** Book Categories */
export const BOOK_CATEGORIES = {
  OT: [
    { name: '律法書', range: [1, 5] as const },
    { name: '歷史書', range: [6, 17] as const },
    { name: '詩歌智慧書', range: [18, 22] as const },
    { name: '大先知書', range: [23, 27] as const },
    { name: '小先知書', range: [28, 39] as const },
  ],
  NT: [
    { name: '福音書', range: [1, 4] as const },
    { name: '使徒行傳', range: [5, 5] as const },
    { name: '保羅書信', range: [6, 18] as const },
    { name: '普通書信', range: [19, 26] as const },
    { name: '啟示錄', range: [27, 27] as const },
  ],
} as const;

/** Local Storage Keys */
export const STORAGE_KEYS = {
  THEME: 'bible-rag-theme',
  SEARCH_HISTORY: 'bible-rag-search-history',
} as const;

/** Route Paths */
export const ROUTES = {
  HOME: '/',
  SEARCH: '/search',
  BOOKS: '/books',
  BOOK_DETAIL: '/books/:bookId',
  CHAPTER: '/books/:bookId/chapters/:chapter',
  PERICOPES: '/pericopes',
  PERICOPE_DETAIL: '/pericopes/:pericopeId',
  GRAPH: '/graph',
} as const;
