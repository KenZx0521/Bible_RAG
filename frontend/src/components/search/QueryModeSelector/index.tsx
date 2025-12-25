/**
 * QueryModeSelector Component
 *
 * A button group for selecting query mode.
 * Provides 5 modes: auto, verse, topic, person, event.
 *
 * @example
 * <QueryModeSelector
 *   value={mode}
 *   onChange={setMode}
 * />
 */

import { cn } from '@/lib/utils';
import type { QueryMode } from '@/types';
import { QUERY_MODE_OPTIONS } from '@/types';

export interface QueryModeSelectorProps {
  /** Current selected mode */
  value: QueryMode;
  /** Change handler */
  onChange: (mode: QueryMode) => void;
}

export function QueryModeSelector({ value, onChange }: QueryModeSelectorProps) {
  return (
    <div
      className="flex flex-wrap gap-2 justify-center"
      role="group"
      aria-label="Query mode selection"
    >
      {QUERY_MODE_OPTIONS.map((option) => {
        const isSelected = value === option.value;

        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={isSelected}
            title={option.description}
            className={cn(
              'px-4 py-2',
              'rounded-lg',
              'text-sm font-medium',
              'transition-all duration-200',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
              isSelected
                ? [
                    'bg-primary-600 text-white',
                    'hover:bg-primary-700',
                    'shadow-md',
                  ]
                : [
                    'bg-gray-100 dark:bg-gray-800',
                    'text-gray-700 dark:text-gray-300',
                    'hover:bg-gray-200 dark:hover:bg-gray-700',
                    'border border-gray-200 dark:border-gray-700',
                  ]
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

export default QueryModeSelector;
