/**
 * Bible RAG - Page Components
 *
 * This file exports lazy-loaded page components for code splitting.
 * Using React.lazy enables automatic code splitting at the page level,
 * reducing the initial bundle size and improving load performance.
 *
 * @example
 * import { SearchPage, BrowsePage } from '@/pages';
 *
 * // In router:
 * {
 *   path: '/',
 *   element: (
 *     <Suspense fallback={<LoadingOverlay isLoading />}>
 *       <SearchPage />
 *     </Suspense>
 *   )
 * }
 */

import { lazy } from 'react';

/**
 * SearchPage - Main search and Q&A interface
 * Route: / and /search
 */
export const SearchPage = lazy(() => import('./SearchPage'));

/**
 * BrowsePage - Bible book and chapter browser
 * Routes: /browse, /browse/:bookId, /browse/:bookId/:chapter
 */
export const BrowsePage = lazy(() => import('./BrowsePage'));

/**
 * GraphPage - Knowledge graph visualization
 * Routes: /graph, /graph/entity/:id, /graph/topic/:id
 */
export const GraphPage = lazy(() => import('./GraphPage'));

/**
 * DetailPage - Pericope and verse detail view
 * Routes: /pericope/:id, /verse/:id
 */
export const DetailPage = lazy(() => import('./DetailPage'));
