/**
 * VerseList Component
 *
 * Displays verses in a scrollable list with parchment background.
 * Uses @tanstack/react-virtual for virtualization of long chapters.
 *
 * @example
 * <VerseList
 *   bookId={1}
 *   bookName="Genesis"
 *   chapter={1}
 *   verses={verses}
 *   totalChapters={50}
 *   highlightVerseId={5}
 * />
 */

import { useRef, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { VerseItem } from '@/types';

/** Threshold for showing verse jump selector */
const VERSE_JUMP_THRESHOLD = 20;

export interface VerseListProps {
  /** Book ID */
  bookId: number;
  /** Book name for display */
  bookName: string;
  /** Current chapter number */
  chapter: number;
  /** Verses to display */
  verses: VerseItem[];
  /** Total chapters in the book (for navigation) */
  totalChapters: number;
  /** Verse ID to highlight */
  highlightVerseId?: number;
  /** Additional CSS class */
  className?: string;
}

interface VerseRowProps {
  verse: VerseItem;
  isHighlighted: boolean;
  onClick: (verseId: number) => void;
}

function VerseRow({ verse, isHighlighted, onClick }: VerseRowProps) {
  const handleClick = useCallback(() => {
    onClick(verse.id);
  }, [verse.id, onClick]);

  return (
    <div
      className={cn(
        'py-2 px-1 rounded transition-colors cursor-pointer',
        'hover:bg-bible-gold/10 dark:hover:bg-bible-gold/20',
        isHighlighted && 'bg-bible-gold/20 dark:bg-bible-gold/30'
      )}
      onClick={handleClick}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          handleClick();
        }
      }}
      aria-label={`Verse ${verse.verse}: ${verse.text}`}
    >
      <span className="verse-number">{verse.verse}</span>
      <span className="verse-text">{verse.text}</span>
    </div>
  );
}

/**
 * Navigation controls for previous/next chapter
 */
interface ChapterNavigationProps {
  bookId: number;
  chapter: number;
  totalChapters: number;
}

function ChapterNavigation({
  bookId,
  chapter,
  totalChapters,
}: ChapterNavigationProps) {
  const hasPrev = chapter > 1;
  const hasNext = chapter < totalChapters;

  return (
    <nav
      className="flex items-center justify-between pt-6 border-t border-gray-200 dark:border-gray-700"
      aria-label="Chapter navigation"
    >
      {hasPrev ? (
        <Link
          to={`/browse/${bookId}/${chapter - 1}`}
          className={cn(
            'flex items-center gap-1 px-4 py-2 rounded-lg',
            'text-primary-600 dark:text-primary-400',
            'hover:bg-primary-50 dark:hover:bg-primary-900/30',
            'transition-colors'
          )}
          aria-label={`Previous chapter: ${chapter - 1}`}
        >
          <ChevronLeft className="w-5 h-5" aria-hidden="true" />
          <span>上一章</span>
        </Link>
      ) : (
        <div />
      )}

      <span className="text-gray-500 dark:text-gray-400 text-sm">
        {chapter} / {totalChapters}
      </span>

      {hasNext ? (
        <Link
          to={`/browse/${bookId}/${chapter + 1}`}
          className={cn(
            'flex items-center gap-1 px-4 py-2 rounded-lg',
            'text-primary-600 dark:text-primary-400',
            'hover:bg-primary-50 dark:hover:bg-primary-900/30',
            'transition-colors'
          )}
          aria-label={`Next chapter: ${chapter + 1}`}
        >
          <span>下一章</span>
          <ChevronRight className="w-5 h-5" aria-hidden="true" />
        </Link>
      ) : (
        <div />
      )}
    </nav>
  );
}

export function VerseList({
  bookId,
  bookName,
  chapter,
  verses,
  totalChapters,
  highlightVerseId,
  className,
}: VerseListProps) {
  const navigate = useNavigate();
  const parentRef = useRef<HTMLDivElement>(null);
  const verseRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // Virtualization for long chapters (e.g., Psalm 119 with 176 verses)
  const virtualizer = useVirtualizer({
    count: verses.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80, // Estimated row height
    overscan: 5,
  });

  // Scroll to highlighted verse on mount
  useEffect(() => {
    if (highlightVerseId) {
      const index = verses.findIndex((v) => v.id === highlightVerseId);
      if (index !== -1) {
        virtualizer.scrollToIndex(index, { align: 'center' });
      }
    }
  }, [highlightVerseId, verses, virtualizer]);

  const handleVerseClick = useCallback(
    (verseId: number) => {
      // Navigate to verse detail page
      navigate(`/verse/${verseId}`);
    },
    [navigate]
  );

  // Determine if we need virtualization (for chapters with many verses)
  const useVirtual = verses.length > 50;

  const virtualItems = virtualizer.getVirtualItems();

  // Whether to show verse jump selector
  const showVerseJump = verses.length > VERSE_JUMP_THRESHOLD;

  // Build verse number to index map for quick lookup
  const verseIndexMap = useMemo(() => {
    const map = new Map<number, number>();
    verses.forEach((v, index) => {
      map.set(v.verse, index);
    });
    return map;
  }, [verses]);

  // Scroll to a specific verse number
  const scrollToVerse = useCallback(
    (verseNumber: number) => {
      if (useVirtual) {
        // For virtualized list, use virtualizer's scrollToIndex
        const index = verseIndexMap.get(verseNumber);
        if (index !== undefined) {
          virtualizer.scrollToIndex(index, { align: 'start', behavior: 'smooth' });
        }
      } else {
        // For regular list, use scrollIntoView
        const element = verseRefs.current.get(verseNumber);
        if (element) {
          element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }
    },
    [useVirtual, verseIndexMap, virtualizer]
  );

  // Handle verse jump selection change
  const handleVerseJumpChange = useCallback(
    (event: React.ChangeEvent<HTMLSelectElement>) => {
      const verseNumber = Number(event.target.value);
      if (verseNumber > 0) {
        scrollToVerse(verseNumber);
      }
    },
    [scrollToVerse]
  );

  // Set ref for a verse element (used in non-virtualized mode)
  const setVerseRef = useCallback((verseNumber: number, element: HTMLDivElement | null) => {
    if (element) {
      verseRefs.current.set(verseNumber, element);
    } else {
      verseRefs.current.delete(verseNumber);
    }
  }, []);

  if (verses.length === 0) {
    return (
      <div className="text-center py-8 text-gray-500 dark:text-gray-400">
        沒有經文資料
      </div>
    );
  }

  return (
    <div className={cn('space-y-4', className)}>
      {/* Header */}
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-serif font-semibold text-gray-900 dark:text-gray-100">
          {bookName} {chapter} 章
        </h1>
        <span className="text-sm text-gray-500 dark:text-gray-400">
          共 {verses.length} 節
        </span>
      </header>

      {/* Verse Jump Selector - only show for long chapters */}
      {showVerseJump && (
        <div className="flex items-center gap-2 py-2 px-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
          <label
            htmlFor="verse-jump"
            className="text-sm text-gray-600 dark:text-gray-400 whitespace-nowrap"
          >
            跳至：
          </label>
          <select
            id="verse-jump"
            onChange={handleVerseJumpChange}
            className={cn(
              'flex-1 max-w-[180px] px-3 py-1.5 rounded-md',
              'text-sm text-gray-700 dark:text-gray-300',
              'bg-white dark:bg-gray-700',
              'border border-gray-300 dark:border-gray-600',
              'focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent',
              'cursor-pointer'
            )}
            aria-label="選擇經文節數跳轉"
            defaultValue=""
          >
            <option value="" disabled>
              選擇節數...
            </option>
            {verses.map((v) => (
              <option key={v.verse} value={v.verse}>
                第 {v.verse} 節
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Verse container with parchment background */}
      <div
        ref={parentRef}
        className={cn(
          'verse-container min-h-[400px] max-h-[70vh] overflow-auto',
          useVirtual && 'relative'
        )}
        role="list"
        aria-label={`${bookName} chapter ${chapter} verses`}
      >
        {useVirtual ? (
          // Virtualized list for long chapters
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {virtualItems.map((virtualRow) => {
              const verse = verses[virtualRow.index];
              return (
                <div
                  key={virtualRow.key}
                  data-index={virtualRow.index}
                  ref={virtualizer.measureElement}
                  style={{
                    position: 'absolute',
                    top: 0,
                    left: 0,
                    width: '100%',
                    transform: `translateY(${virtualRow.start}px)`,
                  }}
                  role="listitem"
                >
                  <VerseRow
                    verse={verse}
                    isHighlighted={verse.id === highlightVerseId}
                    onClick={handleVerseClick}
                  />
                </div>
              );
            })}
          </div>
        ) : (
          // Regular list for shorter chapters
          <div className="space-y-1">
            {verses.map((verse) => (
              <div
                key={verse.id}
                role="listitem"
                ref={(el) => setVerseRef(verse.verse, el)}
                data-verse-number={verse.verse}
              >
                <VerseRow
                  verse={verse}
                  isHighlighted={verse.id === highlightVerseId}
                  onClick={handleVerseClick}
                />
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Chapter navigation */}
      <ChapterNavigation
        bookId={bookId}
        chapter={chapter}
        totalChapters={totalChapters}
      />
    </div>
  );
}

export default VerseList;
