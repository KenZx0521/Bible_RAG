/**
 * Bible RAG - Main Layout Component
 *
 * The main application layout that wraps all pages.
 * Features:
 * - Header at the top
 * - Sidebar on the left (collapsible)
 * - Main content area with React Router Outlet
 * - Responsive adjustments based on sidebar state
 *
 * @example
 * // In router configuration:
 * {
 *   element: <MainLayout />,
 *   children: [
 *     { path: '/', element: <HomePage /> },
 *     { path: '/browse', element: <BrowsePage /> },
 *     { path: '/graph', element: <GraphPage /> },
 *   ]
 * }
 */

import { Outlet } from 'react-router-dom';
import { cn } from '@/lib/utils';
import { Header } from '../Header';
import { Sidebar } from '../Sidebar';

/** Main layout component */
export function MainLayout() {
  return (
    <div className="min-h-screen bg-gray-50 transition-colors duration-200">
      {/* Header */}
      <Header />

      {/* Main Container */}
      <div className="flex">
        {/* Sidebar */}
        <Sidebar />

        {/* Main Content */}
        <main
          className={cn(
            'flex-1 min-w-0', // min-w-0 prevents flex child from overflowing
            'transition-all duration-300 ease-in-out',
            // Add top padding for mobile nav bar
            'pt-12 lg:pt-0'
          )}
        >
          {/* Content Container */}
          <div
            className={cn(
              'min-h-[calc(100vh-4rem)]', // Full height minus header
              'lg:min-h-[calc(100vh-4rem)]',
              'p-4 lg:p-6'
            )}
          >
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

export default MainLayout;
