/**
 * BrowsePage Component
 *
 * Browse the Bible by book and chapter.
 * Supports three viewing modes:
 * - Book list (no params) - Shows all 66 books
 * - Chapter list (bookId only) - Shows all chapters for a book
 * - Chapter content (bookId + chapter) - Shows all verses in a chapter
 *
 * @example
 * // In router:
 * { path: '/browse', element: <BrowsePage /> }
 * { path: '/browse/:bookId', element: <BrowsePage /> }
 * { path: '/browse/:bookId/:chapter', element: <BrowsePage /> }
 */

import { useMemo } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card, Breadcrumb, LoadingSpinner } from '@/components/common';
import { BookSelector, ChapterGrid, VerseList } from '@/components/bible';
import { useBookChapters, useBookVerses } from '@/hooks/api';
import { getBookById } from '@/utils/bibleData';

export function BrowsePage() {
  const { bookId: bookIdParam, chapter: chapterParam } = useParams<{
    bookId?: string;
    chapter?: string;
  }>();
  const navigate = useNavigate();

  // Parse URL params
  const bookId = bookIdParam ? parseInt(bookIdParam, 10) : undefined;
  const chapter = chapterParam ? parseInt(chapterParam, 10) : undefined;

  // Get book info from static data
  const bookInfo = useMemo(
    () => (bookId ? getBookById(bookId) : undefined),
    [bookId]
  );

  // Fetch chapters when book is selected
  const {
    data: chaptersData,
    isLoading: isLoadingChapters,
    error: chaptersError,
  } = useBookChapters(bookId || 0);

  // Fetch verses when chapter is selected
  const {
    data: versesData,
    isLoading: isLoadingVerses,
    error: versesError,
  } = useBookVerses(bookId || 0, chapter || 0);

  // Build breadcrumb items
  const breadcrumbItems = useMemo(() => {
    const items = [
      { label: '首頁', href: '/' },
      { label: '聖經書卷', href: '/browse' },
    ];

    if (bookId && bookInfo) {
      items.push({
        label: bookInfo.name_zh,
        href: `/browse/${bookId}`,
      });
    }

    if (chapter && bookId) {
      items.push({
        label: `第 ${chapter} 章`,
        href: `/browse/${bookId}/${chapter}`,
      });
    }

    return items;
  }, [bookId, bookInfo, chapter]);

  // Handler for book selection
  const handleBookSelect = (selectedBookId: number) => {
    navigate(`/browse/${selectedBookId}`);
  };

  // Handler for chapter selection
  const handleChapterSelect = (selectedChapter: number) => {
    if (bookId) {
      navigate(`/browse/${bookId}/${selectedChapter}`);
    }
  };

  // Render content based on params
  const renderContent = () => {
    // Full chapter view - show verses
    if (bookId && chapter && bookInfo) {
      if (isLoadingVerses) {
        return (
          <Card className="p-6">
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner size="lg" />
              <span className="ml-3 text-gray-600 dark:text-gray-400">
                載入經文中...
              </span>
            </div>
          </Card>
        );
      }

      if (versesError) {
        return (
          <Card className="p-6">
            <div className="text-center py-12">
              <p className="text-error mb-4">載入經文時發生錯誤</p>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="btn-primary"
              >
                重新載入
              </button>
            </div>
          </Card>
        );
      }

      const verses = versesData?.verses || [];
      const totalChapters = chaptersData?.chapters.length || 0;

      return (
        <Card className="p-6">
          <VerseList
            bookId={bookId}
            bookName={bookInfo.name_zh}
            chapter={chapter}
            verses={verses}
            totalChapters={totalChapters}
          />
        </Card>
      );
    }

    // Chapter list view - show chapter grid
    if (bookId && bookInfo) {
      if (isLoadingChapters) {
        return (
          <Card className="p-6">
            <div className="flex items-center justify-center py-12">
              <LoadingSpinner size="lg" />
              <span className="ml-3 text-gray-600 dark:text-gray-400">
                載入章節中...
              </span>
            </div>
          </Card>
        );
      }

      if (chaptersError) {
        return (
          <Card className="p-6">
            <div className="text-center py-12">
              <p className="text-error mb-4">載入章節時發生錯誤</p>
              <button
                type="button"
                onClick={() => window.location.reload()}
                className="btn-primary"
              >
                重新載入
              </button>
            </div>
          </Card>
        );
      }

      const chapters = chaptersData?.chapters || [];

      return (
        <Card className="p-6">
          <ChapterGrid
            bookId={bookId}
            bookName={bookInfo.name_zh}
            chapters={chapters}
            onChapterSelect={handleChapterSelect}
          />
        </Card>
      );
    }

    // Book list view - show book selector
    return (
      <Card className="p-6">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            聖經書卷
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            選擇要瀏覽的書卷，共 66 卷
          </p>
        </div>
        <BookSelector
          selectedBookId={bookId}
          onSelect={handleBookSelect}
        />
      </Card>
    );
  };

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <Breadcrumb items={breadcrumbItems} />
      {renderContent()}
    </div>
  );
}

export default BrowsePage;
