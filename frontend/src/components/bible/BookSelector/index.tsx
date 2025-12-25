/**
 * BookSelector Component
 *
 * Displays all 66 books of the Bible in a responsive grid.
 * Books are organized by Old Testament (39 books) and New Testament (27 books).
 *
 * @example
 * // Basic usage
 * <BookSelector onSelect={(bookId) => console.log('Selected:', bookId)} />
 *
 * // With selected book
 * <BookSelector
 *   selectedBookId={1}
 *   onSelect={(bookId) => navigate(`/browse/${bookId}`)}
 * />
 */

import { useMemo, useCallback } from 'react';
import { cn } from '@/lib/utils';
import {
  getOldTestamentBooks,
  getNewTestamentBooks,
  type BookItem,
} from '@/utils/bibleData';

export interface BookSelectorProps {
  /** Currently selected book ID */
  selectedBookId?: number;
  /** Callback when a book is selected */
  onSelect: (bookId: number) => void;
  /** Additional CSS class */
  className?: string;
}

interface BookButtonProps {
  book: BookItem;
  isSelected: boolean;
  onSelect: (bookId: number) => void;
}

/**
 * Individual book button
 */
function BookButton({ book, isSelected, onSelect }: BookButtonProps) {
  const isOT = book.testament === 'OT';

  const handleClick = useCallback(() => {
    onSelect(book.id);
  }, [book.id, onSelect]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        onSelect(book.id);
      }
    },
    [book.id, onSelect]
  );

  return (
    <button
      type="button"
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      className={cn(
        'relative px-2 py-3 rounded-lg text-center transition-all duration-200',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
        // Base styles by testament
        isOT
          ? [
              'bg-bible-ot/10 hover:bg-bible-ot/20 text-bible-ot',
              'dark:bg-bible-ot/20 dark:hover:bg-bible-ot/30 dark:text-bible-ot-light',
              'focus-visible:ring-bible-ot',
            ]
          : [
              'bg-bible-nt/10 hover:bg-bible-nt/20 text-bible-nt',
              'dark:bg-bible-nt/20 dark:hover:bg-bible-nt/30 dark:text-bible-nt-light',
              'focus-visible:ring-bible-nt',
            ],
        // Selected state
        isSelected && [
          isOT
            ? 'ring-2 ring-bible-ot bg-bible-ot/30 dark:bg-bible-ot/40'
            : 'ring-2 ring-bible-nt bg-bible-nt/30 dark:bg-bible-nt/40',
        ]
      )}
      title={book.name_zh}
      aria-label={book.name_zh}
      aria-pressed={isSelected}
    >
      <span className="font-medium text-sm">{book.abbrev_zh}</span>
    </button>
  );
}

/**
 * Book section (Old Testament or New Testament)
 */
interface BookSectionProps {
  title: string;
  books: BookItem[];
  selectedBookId?: number;
  onSelect: (bookId: number) => void;
  testament: 'OT' | 'NT';
}

function BookSection({
  title,
  books,
  selectedBookId,
  onSelect,
  testament,
}: BookSectionProps) {
  return (
    <section className="space-y-3">
      <h2
        className={cn(
          'text-lg font-semibold flex items-center gap-2',
          testament === 'OT'
            ? 'text-bible-ot dark:text-bible-ot-light'
            : 'text-bible-nt dark:text-bible-nt-light'
        )}
      >
        <span
          className={cn(
            'w-3 h-3 rounded-full',
            testament === 'OT' ? 'bg-bible-ot' : 'bg-bible-nt'
          )}
          aria-hidden="true"
        />
        {title}
        <span className="text-sm font-normal text-gray-500 dark:text-gray-400">
          ({books.length} 卷)
        </span>
      </h2>
      <div
        className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2"
        role="group"
        aria-label={title}
      >
        {books.map((book) => (
          <BookButton
            key={book.id}
            book={book}
            isSelected={selectedBookId === book.id}
            onSelect={onSelect}
          />
        ))}
      </div>
    </section>
  );
}

/**
 * BookSelector - Main component
 */
export function BookSelector({
  selectedBookId,
  onSelect,
  className,
}: BookSelectorProps) {
  const oldTestamentBooks = useMemo(() => getOldTestamentBooks(), []);
  const newTestamentBooks = useMemo(() => getNewTestamentBooks(), []);

  return (
    <div className={cn('space-y-6', className)} role="navigation" aria-label="Bible books">
      <BookSection
        title="舊約"
        books={oldTestamentBooks}
        selectedBookId={selectedBookId}
        onSelect={onSelect}
        testament="OT"
      />
      <BookSection
        title="新約"
        books={newTestamentBooks}
        selectedBookId={selectedBookId}
        onSelect={onSelect}
        testament="NT"
      />
    </div>
  );
}

export default BookSelector;
