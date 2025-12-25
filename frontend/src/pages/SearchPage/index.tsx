/**
 * SearchPage Component
 *
 * The main search page for Bible RAG.
 * Allows users to ask questions and get AI-powered answers
 * based on biblical content.
 *
 * Features:
 * - RAG query execution with loading states
 * - Query mode selection (auto, verse, topic, person, event)
 * - Search history dropdown
 * - Error handling with retry functionality
 * - Responsive design with dark mode support
 *
 * @example
 * // In router:
 * { path: '/', element: <SearchPage /> }
 * { path: '/search', element: <SearchPage /> }
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { AlertCircle, History, RefreshCw, X } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button, Card, LoadingOverlay } from '@/components/common';
import {
  SearchBar,
  QueryModeSelector,
  QueryResult,
} from '@/components/search';
import { useRagQuery } from '@/hooks/api';
import { useSearchStore } from '@/stores/useSearchStore';
import type { QueryMode, QueryResponse } from '@/types';

export function SearchPage() {
  // Local state
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState<QueryMode>('auto');
  const [result, setResult] = useState<QueryResponse | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const historyRef = useRef<HTMLDivElement>(null);

  // Store
  const history = useSearchStore((state) => state.history);

  // RAG Query mutation
  const {
    mutate: executeQuery,
    isPending,
    error,
    reset: resetError,
  } = useRagQuery({
    onSuccess: (data) => {
      setResult(data);
    },
  });

  // Handle search submission
  const handleSubmit = useCallback(() => {
    if (!query.trim()) return;

    resetError();
    setResult(null);

    executeQuery({
      query: query.trim(),
      mode,
      options: {
        include_graph: true,
        max_results: 5,
      },
    });
  }, [query, mode, executeQuery, resetError]);

  // Handle history item selection
  const handleHistorySelect = useCallback((historyQuery: string) => {
    setQuery(historyQuery);
    setShowHistory(false);
  }, []);

  // Close history dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        historyRef.current &&
        !historyRef.current.contains(event.target as Node)
      ) {
        setShowHistory(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle retry
  const handleRetry = useCallback(() => {
    handleSubmit();
  }, [handleSubmit]);

  // Error message extraction
  const errorMessage =
    error instanceof Error ? error.message : '查詢時發生錯誤，請稍後再試';

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Loading Overlay */}
      <LoadingOverlay
        isLoading={isPending}
        message="正在查詢中，請稍候... (RAG 查詢可能需要 3-10 秒)"
      />

      {/* Page Header */}
      <div className="text-center py-8">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-gray-100 mb-2">
          聖經智慧問答
        </h1>
        <p className="text-gray-600 dark:text-gray-400">
          透過 AI 探索聖經的智慧與真理
        </p>
      </div>

      {/* Search Section */}
      <div className="space-y-4">
        {/* Search Bar with History */}
        <div className="relative" ref={historyRef}>
          <SearchBar
            value={query}
            onChange={setQuery}
            onSubmit={handleSubmit}
            loading={isPending}
            autoFocus
          />

          {/* History Toggle Button */}
          {history.length > 0 && (
            <button
              type="button"
              onClick={() => setShowHistory(!showHistory)}
              className={cn(
                'absolute right-20 top-1/2 -translate-y-1/2',
                'p-2 rounded-lg',
                'text-gray-400 hover:text-gray-600',
                'dark:text-gray-500 dark:hover:text-gray-300',
                'transition-colors duration-200',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500'
              )}
              aria-label="搜尋歷史"
              aria-expanded={showHistory}
            >
              <History className="w-5 h-5" aria-hidden="true" />
            </button>
          )}

          {/* History Dropdown */}
          {showHistory && history.length > 0 && (
            <div
              className={cn(
                'absolute top-full left-0 right-0 mt-2',
                'bg-white dark:bg-gray-800',
                'border border-gray-200 dark:border-gray-700',
                'rounded-xl shadow-lg',
                'overflow-hidden z-50',
                'animate-fade-in'
              )}
            >
              <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-700">
                <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
                  搜尋歷史
                </span>
                <button
                  type="button"
                  onClick={() => setShowHistory(false)}
                  className="p-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                  aria-label="關閉歷史"
                >
                  <X className="w-4 h-4 text-gray-400" aria-hidden="true" />
                </button>
              </div>
              <ul className="max-h-60 overflow-y-auto" role="listbox">
                {history.map((item, index) => (
                  <li key={`history-${index}`}>
                    <button
                      type="button"
                      onClick={() => handleHistorySelect(item)}
                      className={cn(
                        'w-full px-4 py-3 text-left',
                        'text-gray-700 dark:text-gray-300',
                        'hover:bg-gray-50 dark:hover:bg-gray-700',
                        'transition-colors duration-150',
                        'focus-visible:outline-none focus-visible:bg-gray-100 dark:focus-visible:bg-gray-700'
                      )}
                      role="option"
                    >
                      <span className="line-clamp-1">{item}</span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Query Mode Selector */}
        <QueryModeSelector value={mode} onChange={setMode} />
      </div>

      {/* Error State */}
      {error && !isPending && (
        <Card
          padding="lg"
          className={cn(
            'border-error/50',
            'bg-error-light dark:bg-error-dark/20',
            'animate-fade-in'
          )}
        >
          <div className="flex flex-col items-center gap-4 text-center">
            <AlertCircle
              className="w-12 h-12 text-error"
              aria-hidden="true"
            />
            <div>
              <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100 mb-1">
                查詢失敗
              </h2>
              <p className="text-gray-600 dark:text-gray-400">{errorMessage}</p>
            </div>
            <Button
              variant="primary"
              onClick={handleRetry}
              className="mt-2"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              重試
            </Button>
          </div>
        </Card>
      )}

      {/* Query Result */}
      {result && !error && !isPending && <QueryResult result={result} />}

      {/* Empty State */}
      {!result && !error && !isPending && (
        <Card padding="lg" className="text-center">
          <div className="py-8 space-y-4">
            <div className="text-6xl" aria-hidden="true">
              📖
            </div>
            <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
              開始您的探索
            </h2>
            <p className="text-gray-600 dark:text-gray-400 max-w-md mx-auto">
              輸入您想了解的聖經主題、人物、事件或經文，AI
              將為您提供深入的解答和相關經文。
            </p>
            <div className="pt-4">
              <p className="text-sm text-gray-500 dark:text-gray-500">
                試試這些問題：
              </p>
              <div className="flex flex-wrap justify-center gap-2 mt-2">
                {[
                  '聖經怎麼談饒恕？',
                  '誰是大衛？',
                  '出埃及記講什麼？',
                  '什麼是愛的真諦？',
                ].map((example) => (
                  <button
                    key={example}
                    type="button"
                    onClick={() => {
                      setQuery(example);
                    }}
                    className={cn(
                      'px-3 py-1.5 rounded-full',
                      'text-sm',
                      'bg-gray-100 dark:bg-gray-800',
                      'text-gray-600 dark:text-gray-400',
                      'hover:bg-gray-200 dark:hover:bg-gray-700',
                      'transition-colors duration-200'
                    )}
                  >
                    {example}
                  </button>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

export default SearchPage;
