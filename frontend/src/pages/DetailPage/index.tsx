/**
 * DetailPage Component
 *
 * Detail page for pericopes and verses.
 * Displays detailed information about a specific passage or verse.
 *
 * Routes:
 * - /pericope/:id -> Pericope detail (passage with multiple verses)
 * - /verse/:id -> Single verse detail
 *
 * @example
 * // In router:
 * { path: '/pericope/:id', element: <DetailPage /> }
 * { path: '/verse/:id', element: <DetailPage /> }
 */

import { useParams, useLocation, Link, useNavigate } from 'react-router-dom';
import { Card, Breadcrumb, Button, LoadingSpinner } from '@/components/common';
import { usePericopeDetail } from '@/hooks/api/usePericopes';
import { useVerseDetail } from '@/hooks/api/useVerses';

/**
 * Pericope Detail View
 * Displays a passage with its title, summary, and all verses
 */
function PericopeDetailView({ id }: { id: number }) {
  const navigate = useNavigate();
  const { data, isLoading, error } = usePericopeDetail(id);

  // Loading state
  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 animate-pulse" />
        <Card padding="lg">
          <div className="flex justify-center items-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        </Card>
      </div>
    );
  }

  // Error state
  if (error || !data) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <Card padding="lg" className="text-center">
          <div className="py-8">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-4">
              找不到此段落
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
              段落 ID: {id} 不存在或無法載入。
            </p>
            <Button variant="primary" onClick={() => navigate('/browse')}>
              返回書卷列表
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // Build breadcrumb items
  const breadcrumbItems = [
    { label: '聖經', href: '/browse' },
    { label: data.book_name, href: `/browse/${data.book_id}` },
    { label: data.title },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <Breadcrumb items={breadcrumbItems} />

      <Card padding="lg">
        {/* Header */}
        <div className="mb-6">
          <div className="flex items-center gap-2 mb-2">
            <span className="px-3 py-1 bg-purple-100 dark:bg-purple-900/50 text-purple-800 dark:text-purple-200 rounded-full text-sm font-medium">
              段落
            </span>
          </div>
          <h1 className="text-2xl md:text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
            {data.title}
          </h1>
          <p className="text-gray-600 dark:text-gray-400 text-lg">
            {data.reference}
          </p>
        </div>

        {/* Summary Section */}
        {data.summary && (
          <div className="mb-6 bg-gray-50 dark:bg-gray-800/50 p-4 md:p-6 rounded-lg border border-gray-200 dark:border-gray-700">
            <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-3">
              段落摘要
            </h2>
            <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
              {data.summary}
            </p>
          </div>
        )}

        {/* Verses Container */}
        <div className="mb-6">
          <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-200 mb-4">
            經文內容
          </h2>
          <Card variant="scripture" padding="lg">
            <div className="verse-container leading-loose text-lg">
              {data.verses && data.verses.length > 0 ? (
                data.verses.map((verse) => (
                  <span key={verse.id} className="inline">
                    <sup className="verse-number text-xs text-amber-700 dark:text-amber-400 font-bold mx-1 align-super">
                      {verse.verse}
                    </sup>
                    <span
                      className="verse-text text-gray-800 dark:text-gray-200 font-serif cursor-pointer hover:bg-amber-100 dark:hover:bg-amber-900/30 rounded px-0.5 transition-colors"
                      onClick={() => navigate(`/verse/${verse.id}`)}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          navigate(`/verse/${verse.id}`);
                        }
                      }}
                      title={`點擊查看 ${verse.reference} 詳情`}
                    >
                      {verse.text}
                    </span>
                  </span>
                ))
              ) : (
                <p className="text-gray-500 dark:text-gray-400 italic">
                  尚無經文資料
                </p>
              )}
            </div>
          </Card>
        </div>

        {/* Related Links */}
        <div className="pt-4 border-t border-gray-200 dark:border-gray-700">
          <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
            相關連結
          </h3>
          <div className="flex flex-wrap gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/browse/${data.book_id}`)}
            >
              返回 {data.book_name}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/graph')}
            >
              查看知識圖譜
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/graph?pericope=${id}`)}
            >
              查看相關人物
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

/**
 * Verse Detail View
 * Displays a single verse with navigation to adjacent verses
 */
function VerseDetailView({ id }: { id: number }) {
  const navigate = useNavigate();
  const { data, isLoading, error } = useVerseDetail(id);

  // Loading state
  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/3 animate-pulse" />
        <Card variant="scripture" padding="lg">
          <div className="flex justify-center items-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        </Card>
      </div>
    );
  }

  // Error state
  if (error || !data) {
    return (
      <div className="max-w-4xl mx-auto space-y-4">
        <Card padding="lg" className="text-center">
          <div className="py-8">
            <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-4">
              找不到此經節
            </h1>
            <p className="text-gray-600 dark:text-gray-400 mb-6">
              經節 ID: {id} 不存在或無法載入。
            </p>
            <Button variant="primary" onClick={() => navigate('/browse')}>
              返回書卷列表
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  // Build breadcrumb items
  const breadcrumbItems = [
    { label: '聖經', href: '/browse' },
    { label: data.book_name, href: `/browse/${data.book_id}` },
    {
      label: `第 ${data.chapter} 章`,
      href: `/browse/${data.book_id}/${data.chapter}`,
    },
    { label: data.reference },
  ];

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <Breadcrumb items={breadcrumbItems} />

      <Card variant="scripture" padding="lg">
        {/* Header Badge */}
        <div className="flex items-center justify-center gap-2 mb-4">
          <span className="px-3 py-1 bg-blue-100 dark:bg-blue-900/50 text-blue-800 dark:text-blue-200 rounded-full text-sm font-medium">
            經節
          </span>
        </div>

        {/* Verse Content - Centered */}
        <div className="text-center py-8">
          <h1 className="text-xl md:text-2xl font-semibold text-amber-800 dark:text-amber-300 mb-6">
            {data.reference}
          </h1>
          <p className="verse-text text-xl md:text-2xl text-gray-800 dark:text-gray-200 font-serif leading-relaxed max-w-2xl mx-auto">
            {data.text}
          </p>
        </div>

        {/* Pericope Link */}
        <div className="mt-8 pt-4 border-t border-amber-200 dark:border-amber-800/50">
          <p className="text-center text-gray-600 dark:text-gray-400">
            所屬段落：
            <Link
              to={`/pericope/${data.pericope_id}`}
              className="ml-2 text-primary-600 dark:text-primary-400 hover:underline font-medium"
            >
              {data.pericope_title}
            </Link>
          </p>
        </div>

        {/* Navigation */}
        <div className="flex justify-between items-center mt-6 pt-4 border-t border-amber-200 dark:border-amber-800/50">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/verse/${id - 1}`)}
            disabled={id <= 1}
            className="flex items-center gap-1"
          >
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 19l-7-7 7-7"
              />
            </svg>
            上一節
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/browse/${data.book_id}/${data.chapter}`)}
          >
            返回第 {data.chapter} 章
          </Button>

          <Button
            variant="ghost"
            size="sm"
            onClick={() => navigate(`/verse/${id + 1}`)}
            className="flex items-center gap-1"
          >
            下一節
            <svg
              className="w-4 h-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
          </Button>
        </div>
      </Card>

      {/* Additional Metadata */}
      <Card padding="md">
        <h3 className="text-sm font-semibold text-gray-700 dark:text-gray-300 mb-3">
          經節資訊
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">
              書卷
            </span>
            <span className="text-gray-900 dark:text-gray-100 font-medium">
              {data.book_name}
            </span>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">
              章
            </span>
            <span className="text-gray-900 dark:text-gray-100 font-medium">
              {data.chapter}
            </span>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">
              節
            </span>
            <span className="text-gray-900 dark:text-gray-100 font-medium">
              {data.verse}
            </span>
          </div>
          <div className="p-3 bg-gray-50 dark:bg-gray-800 rounded-lg">
            <span className="text-xs text-gray-500 dark:text-gray-400 block mb-1">
              經節 ID
            </span>
            <span className="text-gray-900 dark:text-gray-100 font-medium">
              {data.id}
            </span>
          </div>
        </div>

        {/* Quick Actions */}
        <div className="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
          <div className="flex flex-wrap gap-3">
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate('/graph')}
            >
              查看知識圖譜
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => navigate(`/search?q=${encodeURIComponent(data.text.slice(0, 20))}`)}
            >
              搜尋相關經文
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

/**
 * Unknown Type Fallback View
 */
function UnknownTypeView() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      <Card padding="lg" className="text-center">
        <div className="py-8">
          <h1 className="text-2xl font-bold text-gray-900 dark:text-gray-100 mb-4">
            找不到此內容
          </h1>
          <p className="text-gray-600 dark:text-gray-400 mb-6">
            無法識別的頁面類型。ID: {id || '未指定'}
          </p>
          <div className="flex justify-center gap-4">
            <Button variant="primary" onClick={() => navigate('/')}>
              返回首頁
            </Button>
            <Button variant="secondary" onClick={() => navigate('/browse')}>
              瀏覽書卷
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}

/**
 * Main DetailPage Component
 * Routes to appropriate view based on URL path
 */
export function DetailPage() {
  const { id } = useParams<{ id: string }>();
  const location = useLocation();

  // Determine type from URL
  const isPericope = location.pathname.startsWith('/pericope');
  const isVerse = location.pathname.startsWith('/verse');

  // Parse ID
  const numericId = id ? parseInt(id, 10) : 0;
  const isValidId = !isNaN(numericId) && numericId > 0;

  // Invalid ID handling
  if (!isValidId) {
    return <UnknownTypeView />;
  }

  // Route to appropriate view
  if (isPericope) {
    return <PericopeDetailView id={numericId} />;
  }

  if (isVerse) {
    return <VerseDetailView id={numericId} />;
  }

  return <UnknownTypeView />;
}

export default DetailPage;
