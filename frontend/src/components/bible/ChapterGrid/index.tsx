/**
 * ChapterGrid Component
 *
 * Displays chapters in a responsive grid for a given book.
 * Shows chapter number and verse count.
 *
 * @example
 * <ChapterGrid
 *   bookId={1}
 *   bookName="Genesis"
 *   chapters={[{ chapter: 1, verse_count: 31 }, ...]}
 *   onChapterSelect={(chapter) => navigate(`/browse/1/${chapter}`)}
 * />
 */

import { useCallback } from 'react';
import { cn } from '@/lib/utils';
import type { ChapterInfo } from '@/types';

export interface ChapterGridProps {
  /** Book ID */
  bookId: number;
  /** Book name for display */
  bookName: string;
  /** Chapters list */
  chapters: ChapterInfo[];
  /** Callback when a chapter is selected */
  onChapterSelect?: (chapter: number) => void;
  /** Currently selected chapter */
  selectedChapter?: number;
  /** Additional CSS class */
  className?: string;
}

interface ChapterButtonProps {
  chapter: ChapterInfo;
  isSelected: boolean;
  onSelect: (chapter: number) => void;
}

function ChapterButton({ chapter, isSelected, onSelect }: ChapterButtonProps) {
  const handleClick = useCallback(() => {
    onSelect(chapter.chapter);
  }, [chapter.chapter, onSelect]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelect(chapter.chapter);
      }
    },
    [chapter.chapter, onSelect]
  );

  return (
    <button
      type="button"
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        'aspect-square flex flex-col items-center justify-center',
        'rounded-lg transition-all duration-200',
        'bg-gray-100 dark:bg-gray-800',
        'hover:bg-primary-100 dark:hover:bg-primary-900/50',
        'hover:border-primary-500 border-2 border-transparent',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
        isSelected && [
          'bg-primary-100 dark:bg-primary-900/50',
          'border-primary-500',
          'ring-2 ring-primary-500',
        ]
      )}
      aria-label={`Chapter ${chapter.chapter}${chapter.verse_count > 0 ? `, ${chapter.verse_count} verses` : ''}`}
      aria-pressed={isSelected}
    >
      <span className="text-lg font-semibold text-gray-700 dark:text-gray-200">
        {chapter.chapter}
      </span>
      {chapter.verse_count > 0 && (
        <span className="text-xs text-gray-500 dark:text-gray-400">
          {chapter.verse_count} 節
        </span>
      )}
    </button>
  );
}

export function ChapterGrid({
  bookId: _bookId,
  bookName,
  chapters,
  onChapterSelect,
  selectedChapter,
  className,
}: ChapterGridProps) {
  // bookId is kept in props for potential future use (e.g., linking)
  const handleSelect = useCallback(
    (chapter: number) => {
      onChapterSelect?.(chapter);
    },
    [onChapterSelect]
  );

  if (chapters.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        沒有章節資料
      </div>
    );
  }

  return (
    <div className={cn('space-y-4', className)}>
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
          {bookName}
        </h2>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          共 {chapters.length} 章
        </span>
      </div>
      <div
        className="grid grid-cols-4 sm:grid-cols-8 md:grid-cols-10 lg:grid-cols-12 gap-2"
        role="group"
        aria-label={`${bookName} chapters`}
      >
        {chapters.map((chapter) => (
          <ChapterButton
            key={chapter.chapter}
            chapter={chapter}
            isSelected={selectedChapter === chapter.chapter}
            onSelect={handleSelect}
          />
        ))}
      </div>
    </div>
  );
}

export default ChapterGrid;
