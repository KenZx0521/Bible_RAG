/**
 * Pagination Component
 *
 * Page navigation with numbered buttons and ellipsis for large page counts.
 *
 * @example
 * <Pagination
 *   currentPage={5}
 *   totalPages={20}
 *   onPageChange={(page) => setCurrentPage(page)}
 *   siblingsCount={1}
 * />
 */

import { useMemo } from 'react';
import { ChevronLeft, ChevronRight, MoreHorizontal } from 'lucide-react';
import type { PaginationProps } from '@/types/component.types';
import { cn } from '@/lib/utils';

/**
 * Generate page numbers to display
 */
function generatePagination(
  currentPage: number,
  totalPages: number,
  siblingsCount: number
): (number | 'ellipsis')[] {
  const totalPageNumbers = siblingsCount * 2 + 5; // siblings + first + last + current + 2 ellipsis

  // If total pages is less than what we want to show, show all
  if (totalPages <= totalPageNumbers) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  const leftSiblingIndex = Math.max(currentPage - siblingsCount, 1);
  const rightSiblingIndex = Math.min(currentPage + siblingsCount, totalPages);

  const shouldShowLeftEllipsis = leftSiblingIndex > 2;
  const shouldShowRightEllipsis = rightSiblingIndex < totalPages - 1;

  const firstPageIndex = 1;
  const lastPageIndex = totalPages;

  // No left ellipsis, but right ellipsis
  if (!shouldShowLeftEllipsis && shouldShowRightEllipsis) {
    const leftRange = 3 + 2 * siblingsCount;
    return [
      ...Array.from({ length: leftRange }, (_, i) => i + 1),
      'ellipsis',
      lastPageIndex,
    ];
  }

  // Left ellipsis, but no right ellipsis
  if (shouldShowLeftEllipsis && !shouldShowRightEllipsis) {
    const rightRange = 3 + 2 * siblingsCount;
    return [
      firstPageIndex,
      'ellipsis',
      ...Array.from({ length: rightRange }, (_, i) => totalPages - rightRange + 1 + i),
    ];
  }

  // Both ellipsis
  return [
    firstPageIndex,
    'ellipsis',
    ...Array.from(
      { length: rightSiblingIndex - leftSiblingIndex + 1 },
      (_, i) => leftSiblingIndex + i
    ),
    'ellipsis',
    lastPageIndex,
  ];
}

const buttonBaseClass = cn(
  'inline-flex items-center justify-center',
  'min-w-[2.5rem] h-10 px-3',
  'text-sm font-medium',
  'rounded-lg',
  'transition-colors duration-200',
  'focus-visible:outline-none focus-visible:ring-2',
  'focus-visible:ring-primary-500 focus-visible:ring-offset-2',
  'dark:focus-visible:ring-offset-gray-900'
);

export function Pagination({
  currentPage,
  totalPages,
  onPageChange,
  siblingsCount = 1,
}: PaginationProps) {
  const pages = useMemo(
    () => generatePagination(currentPage, totalPages, siblingsCount),
    [currentPage, totalPages, siblingsCount]
  );

  // Don't render if only 1 page
  if (totalPages <= 1) {
    return null;
  }

  const canGoPrevious = currentPage > 1;
  const canGoNext = currentPage < totalPages;

  return (
    <nav
      role="navigation"
      aria-label="pagination"
      className="flex items-center justify-center gap-1"
    >
      {/* Previous Button */}
      <button
        type="button"
        onClick={() => canGoPrevious && onPageChange(currentPage - 1)}
        disabled={!canGoPrevious}
        aria-label="上一頁"
        className={cn(
          buttonBaseClass,
          'text-gray-600 dark:text-gray-300',
          canGoPrevious
            ? 'hover:bg-gray-100 dark:hover:bg-gray-800'
            : 'opacity-50 cursor-not-allowed'
        )}
      >
        <ChevronLeft className="w-5 h-5" />
      </button>

      {/* Page Numbers */}
      {pages.map((page, index) => {
        if (page === 'ellipsis') {
          return (
            <span
              key={`ellipsis-${index}`}
              className="inline-flex items-center justify-center min-w-[2.5rem] h-10 text-gray-400 dark:text-gray-500"
              aria-hidden="true"
            >
              <MoreHorizontal className="w-5 h-5" />
            </span>
          );
        }

        const isCurrentPage = page === currentPage;

        return (
          <button
            key={page}
            type="button"
            onClick={() => !isCurrentPage && onPageChange(page)}
            aria-current={isCurrentPage ? 'page' : undefined}
            aria-label={`第 ${page} 頁`}
            className={cn(
              buttonBaseClass,
              isCurrentPage
                ? 'bg-primary-600 text-white dark:bg-primary-500'
                : cn(
                    'text-gray-600 dark:text-gray-300',
                    'hover:bg-gray-100 dark:hover:bg-gray-800'
                  )
            )}
          >
            {page}
          </button>
        );
      })}

      {/* Next Button */}
      <button
        type="button"
        onClick={() => canGoNext && onPageChange(currentPage + 1)}
        disabled={!canGoNext}
        aria-label="下一頁"
        className={cn(
          buttonBaseClass,
          'text-gray-600 dark:text-gray-300',
          canGoNext
            ? 'hover:bg-gray-100 dark:hover:bg-gray-800'
            : 'opacity-50 cursor-not-allowed'
        )}
      >
        <ChevronRight className="w-5 h-5" />
      </button>
    </nav>
  );
}

export default Pagination;
