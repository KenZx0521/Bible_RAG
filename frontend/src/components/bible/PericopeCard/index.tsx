/**
 * PericopeCard Component
 *
 * A card component displaying a pericope (Bible passage segment) summary.
 * Shows title, reference, and book name.
 *
 * @example
 * <PericopeCard
 *   pericope={{
 *     id: 1,
 *     book_id: 1,
 *     book_name: "Genesis",
 *     title: "The Creation",
 *     reference: "Genesis 1:1-31",
 *     chapter_start: 1,
 *     verse_start: 1,
 *     chapter_end: 1,
 *     verse_end: 31
 *   }}
 *   showBook={true}
 * />
 */

import { useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { BookOpen, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PericopeListItem } from '@/types';

export interface PericopeCardProps {
  /** Pericope data */
  pericope: PericopeListItem;
  /** Whether to show the book name */
  showBook?: boolean;
  /** Additional CSS class */
  className?: string;
}

/**
 * Format verse range for display
 */
function formatVerseRange(pericope: PericopeListItem): string {
  const { chapter_start, verse_start, chapter_end, verse_end } = pericope;

  if (chapter_start === chapter_end) {
    if (verse_start === verse_end) {
      return `${chapter_start}:${verse_start}`;
    }
    return `${chapter_start}:${verse_start}-${verse_end}`;
  }

  return `${chapter_start}:${verse_start} - ${chapter_end}:${verse_end}`;
}

export function PericopeCard({
  pericope,
  showBook = true,
  className,
}: PericopeCardProps) {
  const navigate = useNavigate();

  const handleClick = useCallback(() => {
    navigate(`/pericope/${pericope.id}`);
  }, [navigate, pericope.id]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        handleClick();
      }
    },
    [handleClick]
  );

  const verseRange = formatVerseRange(pericope);

  return (
    <article
      className={cn(
        'group relative p-4 rounded-lg',
        'bg-white dark:bg-gray-800',
        'border border-gray-200 dark:border-gray-700',
        'hover:border-primary-300 dark:hover:border-primary-600',
        'hover:shadow-md',
        'transition-all duration-200',
        'cursor-pointer',
        className
      )}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      tabIndex={0}
      role="link"
      aria-label={`${pericope.title} - ${pericope.reference}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0 space-y-2">
          {/* Book name (optional) */}
          {showBook && (
            <div className="flex items-center gap-1.5 text-sm text-gray-500 dark:text-gray-400">
              <BookOpen className="w-4 h-4" aria-hidden="true" />
              <span>{pericope.book_name}</span>
            </div>
          )}

          {/* Title */}
          <h3 className="text-lg font-semibold text-gray-900 dark:text-gray-100 line-clamp-2">
            {pericope.title}
          </h3>

          {/* Reference */}
          <p className="text-sm text-gray-600 dark:text-gray-300 font-mono">
            {pericope.reference || `${pericope.book_name} ${verseRange}`}
          </p>
        </div>

        {/* Arrow indicator */}
        <ChevronRight
          className={cn(
            'w-5 h-5 text-gray-400',
            'group-hover:text-primary-500 group-hover:translate-x-1',
            'transition-all duration-200'
          )}
          aria-hidden="true"
        />
      </div>
    </article>
  );
}

export default PericopeCard;
