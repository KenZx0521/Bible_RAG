/**
 * Bible RAG - Sidebar Component
 *
 * A collapsible sidebar displaying all 66 books of the Bible.
 * Features:
 * - Old Testament section (39 books) with bible-ot color
 * - New Testament section (27 books) with bible-nt color
 * - 4-column grid layout for books
 * - Desktop: fixed left sidebar (w-64)
 * - Mobile: overlay drawer mode (slide from left)
 * - Click on book navigates to /browse/:bookId
 *
 * @example
 * <Sidebar />
 */

import { useCallback, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Book, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAppStore } from '@/stores/useAppStore';
import {
  getOldTestamentBooks,
  getNewTestamentBooks,
  type BookItem,
} from '@/utils/bibleData';

/** Book button component props */
interface BookButtonProps {
  book: BookItem;
  isSelected: boolean;
  onClick: () => void;
}

/** Book button component */
function BookButton({ book, isSelected, onClick }: BookButtonProps) {
  const isOT = book.testament === 'OT';

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'flex items-center justify-center',
        'w-full aspect-square rounded-lg',
        'text-sm font-medium',
        'transition-all duration-200',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary-500',
        // Testament-specific colors
        isOT
          ? isSelected
            ? 'bg-bible-ot text-white'
            : 'bg-bible-ot/10 text-bible-ot hover:bg-bible-ot/20 dark:bg-bible-ot/20 dark:text-bible-ot-light dark:hover:bg-bible-ot/30'
          : isSelected
            ? 'bg-bible-nt text-white'
            : 'bg-bible-nt/10 text-bible-nt hover:bg-bible-nt/20 dark:bg-bible-nt/20 dark:text-bible-nt-light dark:hover:bg-bible-nt/30'
      )}
      title={book.name_zh}
      aria-label={book.name_zh}
      aria-current={isSelected ? 'page' : undefined}
    >
      {book.abbrev_zh}
    </button>
  );
}

/** Section header component props */
interface SectionHeaderProps {
  title: string;
  count: number;
  testament: 'OT' | 'NT';
}

/** Section header component */
function SectionHeader({ title, count, testament }: SectionHeaderProps) {
  const isOT = testament === 'OT';

  return (
    <div className="flex items-center gap-2 mb-3">
      <div
        className={cn(
          'w-1 h-5 rounded-full',
          isOT ? 'bg-bible-ot' : 'bg-bible-nt'
        )}
        aria-hidden="true"
      />
      <h3
        className={cn(
          'text-sm font-semibold',
          isOT
            ? 'text-bible-ot dark:text-bible-ot-light'
            : 'text-bible-nt dark:text-bible-nt-light'
        )}
      >
        {title}
      </h3>
      <span className="text-xs text-gray-500 dark:text-gray-400">
        ({count} 卷)
      </span>
    </div>
  );
}

/** Sidebar component */
export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const { sidebarOpen, toggleSidebar, selectedBookId, selectBook } =
    useAppStore();

  const otBooks = getOldTestamentBooks();
  const ntBooks = getNewTestamentBooks();

  // Extract book ID from URL if on browse page
  useEffect(() => {
    const match = location.pathname.match(/^\/browse\/(\d+)/);
    if (match) {
      const bookId = parseInt(match[1], 10);
      if (!isNaN(bookId) && bookId !== selectedBookId) {
        selectBook(bookId);
      }
    }
  }, [location.pathname, selectedBookId, selectBook]);

  // Handle book selection
  const handleBookClick = useCallback(
    (book: BookItem) => {
      selectBook(book.id);
      navigate(`/browse/${book.id}`);
      // Close sidebar on mobile after selection
      if (window.innerWidth < 1024 && sidebarOpen) {
        toggleSidebar();
      }
    },
    [selectBook, navigate, sidebarOpen, toggleSidebar]
  );

  // Handle escape key to close sidebar on mobile
  useEffect(() => {
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && sidebarOpen && window.innerWidth < 1024) {
        toggleSidebar();
      }
    };

    document.addEventListener('keydown', handleEscape);
    return () => document.removeEventListener('keydown', handleEscape);
  }, [sidebarOpen, toggleSidebar]);

  // Prevent body scroll when mobile sidebar is open
  useEffect(() => {
    if (sidebarOpen && window.innerWidth < 1024) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    return () => {
      document.body.style.overflow = '';
    };
  }, [sidebarOpen]);

  // Sidebar content
  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Mobile Header with Close Button */}
      <div className="lg:hidden flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-2">
          <Book className="h-5 w-5 text-primary-600 dark:text-primary-400" />
          <span className="font-semibold text-gray-900 dark:text-white">
            聖經目錄
          </span>
        </div>
        <button
          type="button"
          onClick={toggleSidebar}
          className={cn(
            'flex h-8 w-8 items-center justify-center rounded-lg',
            'text-gray-500 dark:text-gray-400',
            'hover:bg-gray-100 dark:hover:bg-gray-700',
            'transition-colors duration-200'
          )}
          aria-label="關閉側邊欄"
        >
          <X className="h-5 w-5" aria-hidden="true" />
        </button>
      </div>

      {/* Desktop Header */}
      <div className="hidden lg:flex items-center gap-2 p-4 border-b border-gray-200 dark:border-gray-700">
        <Book className="h-5 w-5 text-primary-600 dark:text-primary-400" />
        <span className="font-semibold text-gray-900 dark:text-white">
          聖經目錄
        </span>
      </div>

      {/* Scrollable Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Old Testament Section */}
        <section aria-labelledby="ot-section-title">
          <SectionHeader
            title="舊約"
            count={otBooks.length}
            testament="OT"
          />
          <div
            className="grid grid-cols-4 gap-2"
            role="list"
            aria-label="舊約書卷"
          >
            {otBooks.map((book) => (
              <BookButton
                key={book.id}
                book={book}
                isSelected={selectedBookId === book.id}
                onClick={() => handleBookClick(book)}
              />
            ))}
          </div>
        </section>

        {/* New Testament Section */}
        <section aria-labelledby="nt-section-title">
          <SectionHeader
            title="新約"
            count={ntBooks.length}
            testament="NT"
          />
          <div
            className="grid grid-cols-4 gap-2"
            role="list"
            aria-label="新約書卷"
          >
            {ntBooks.map((book) => (
              <BookButton
                key={book.id}
                book={book}
                isSelected={selectedBookId === book.id}
                onClick={() => handleBookClick(book)}
              />
            ))}
          </div>
        </section>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div
          className={cn(
            'fixed inset-0 z-40 lg:hidden',
            'bg-black/50',
            'transition-opacity duration-300'
          )}
          onClick={toggleSidebar}
          aria-hidden="true"
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          // Base styles
          'bg-white dark:bg-gray-900',
          'border-r border-gray-200 dark:border-gray-700',
          'transition-transform duration-300 ease-in-out',

          // Desktop styles
          'lg:relative lg:z-0',
          'lg:w-64 lg:flex-shrink-0',
          sidebarOpen ? 'lg:translate-x-0' : 'lg:-translate-x-full lg:w-0 lg:border-0',

          // Mobile styles - overlay drawer
          'fixed inset-y-0 left-0 z-50',
          'w-72 max-w-[80vw]',
          'lg:static lg:max-w-none',
          sidebarOpen ? 'translate-x-0' : '-translate-x-full',

          // Height
          'h-[calc(100vh-4rem)] lg:h-[calc(100vh-4rem)]',
          'top-16 lg:top-0'
        )}
        aria-label="聖經目錄側邊欄"
        aria-hidden={!sidebarOpen}
      >
        {sidebarContent}
      </aside>
    </>
  );
}

export default Sidebar;
