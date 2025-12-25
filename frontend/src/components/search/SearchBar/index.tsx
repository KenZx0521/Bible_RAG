/**
 * SearchBar Component
 *
 * A large search input with submit button for RAG queries.
 * Features loading state, keyboard navigation, and accessibility support.
 *
 * @example
 * <SearchBar
 *   value={query}
 *   onChange={setQuery}
 *   onSubmit={handleSearch}
 *   placeholder="Ask a question..."
 *   loading={isSearching}
 * />
 */

import { useCallback, type KeyboardEvent } from 'react';
import { Search } from 'lucide-react';
import { cn } from '@/lib/utils';
import { LoadingSpinner } from '@/components/common';

export interface SearchBarProps {
  /** Current input value */
  value: string;
  /** Change handler */
  onChange: (value: string) => void;
  /** Submit handler */
  onSubmit: () => void;
  /** Input placeholder */
  placeholder?: string;
  /** Disabled state */
  disabled?: boolean;
  /** Loading state */
  loading?: boolean;
  /** Auto focus on mount */
  autoFocus?: boolean;
}

export function SearchBar({
  value,
  onChange,
  onSubmit,
  placeholder = '請輸入您的問題，例如：聖經怎麼談饒恕？',
  disabled = false,
  loading = false,
  autoFocus = false,
}: SearchBarProps) {
  const isDisabled = disabled || loading;

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLInputElement>) => {
      if (e.key === 'Enter' && !isDisabled && value.trim()) {
        e.preventDefault();
        onSubmit();
      }
    },
    [isDisabled, value, onSubmit]
  );

  const handleSubmit = useCallback(() => {
    if (!isDisabled && value.trim()) {
      onSubmit();
    }
  }, [isDisabled, value, onSubmit]);

  return (
    <div className="relative w-full">
      <div
        className={cn(
          'flex items-center gap-2',
          'rounded-xl shadow-lg',
          'bg-white dark:bg-gray-800',
          'border border-gray-200 dark:border-gray-700',
          'transition-all duration-200',
          'focus-within:ring-2 focus-within:ring-primary-500 focus-within:border-transparent'
        )}
      >
        {/* Search Input */}
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={isDisabled}
          autoFocus={autoFocus}
          aria-label="Search query"
          aria-describedby="search-hint"
          className={cn(
            'flex-1',
            'text-lg py-4 px-5',
            'bg-transparent',
            'text-gray-900 dark:text-gray-100',
            'placeholder:text-gray-400 dark:placeholder:text-gray-500',
            'border-none outline-none',
            'disabled:cursor-not-allowed disabled:opacity-50'
          )}
        />

        {/* Submit Button */}
        <button
          type="button"
          onClick={handleSubmit}
          disabled={isDisabled || !value.trim()}
          aria-label={loading ? '搜尋中' : '搜尋'}
          className={cn(
            'flex items-center justify-center',
            'w-14 h-14 mr-1',
            'rounded-lg',
            'bg-primary-600 hover:bg-primary-700',
            'text-white',
            'transition-all duration-200',
            'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-primary-600',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2'
          )}
        >
          {loading ? (
            <LoadingSpinner size="sm" className="text-white" />
          ) : (
            <Search className="w-5 h-5" aria-hidden="true" />
          )}
        </button>
      </div>

      {/* Screen reader hint */}
      <span id="search-hint" className="sr-only">
        輸入您的問題後按 Enter 鍵或點擊搜尋按鈕開始搜尋
      </span>
    </div>
  );
}

export default SearchBar;
