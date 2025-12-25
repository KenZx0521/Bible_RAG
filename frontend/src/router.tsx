/**
 * Bible RAG - Router Configuration
 *
 * Defines the application's routing structure using React Router v6.
 * All page components are lazy-loaded for optimal bundle splitting.
 *
 * Route Structure:
 * / (MainLayout)
 * +-- index -> SearchPage
 * +-- browse -> BrowsePage
 * +-- browse/:bookId -> BrowsePage
 * +-- browse/:bookId/:chapter -> BrowsePage
 * +-- pericope/:id -> DetailPage
 * +-- verse/:id -> DetailPage
 * +-- graph -> GraphPage
 * +-- graph/entity/:id -> GraphPage
 * +-- graph/topic/:id -> GraphPage
 * +-- search -> SearchPage
 */

import { Suspense } from 'react';
import { createBrowserRouter, Outlet } from 'react-router-dom';
import { MainLayout } from '@/components/layout';
import { LoadingSpinner } from '@/components/common';
import { SearchPage, BrowsePage, GraphPage, DetailPage } from '@/pages';

/**
 * Loading fallback component for lazy-loaded pages
 */
function PageLoadingFallback() {
  return (
    <div className="min-h-[50vh] flex items-center justify-center">
      <div className="text-center">
        <LoadingSpinner size="lg" />
        <p className="mt-4 text-gray-600 dark:text-gray-400">
          載入中...
        </p>
      </div>
    </div>
  );
}

/**
 * Wrapper component that adds Suspense to lazy-loaded pages
 */
function SuspenseWrapper() {
  return (
    <Suspense fallback={<PageLoadingFallback />}>
      <Outlet />
    </Suspense>
  );
}

/**
 * Application router configuration
 */
export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      {
        element: <SuspenseWrapper />,
        children: [
          // Home / Search
          {
            index: true,
            element: <SearchPage />,
          },
          {
            path: 'search',
            element: <SearchPage />,
          },

          // Browse Bible
          {
            path: 'browse',
            element: <BrowsePage />,
          },
          {
            path: 'browse/:bookId',
            element: <BrowsePage />,
          },
          {
            path: 'browse/:bookId/:chapter',
            element: <BrowsePage />,
          },

          // Detail Pages
          {
            path: 'pericope/:id',
            element: <DetailPage />,
          },
          {
            path: 'verse/:id',
            element: <DetailPage />,
          },

          // Knowledge Graph
          {
            path: 'graph',
            element: <GraphPage />,
          },
          {
            path: 'graph/entity/:id',
            element: <GraphPage />,
          },
          {
            path: 'graph/topic/:id',
            element: <GraphPage />,
          },
        ],
      },
    ],
  },
]);

export default router;
