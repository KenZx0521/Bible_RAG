/**
 * LoadingSpinner Component
 *
 * A simple loading spinner with configurable size.
 *
 * @example
 * // Basic usage
 * <LoadingSpinner />
 *
 * // With size
 * <LoadingSpinner size="lg" />
 *
 * // With custom class
 * <LoadingSpinner size="sm" className="text-blue-500" />
 */

import type { LoadingSpinnerProps } from '@/types/component.types';
import { cn } from '@/lib/utils';

const sizeMap = {
  sm: 'w-4 h-4',   // 16px
  md: 'w-8 h-8',   // 32px
  lg: 'w-12 h-12', // 48px
} as const;

export function LoadingSpinner({
  size = 'md',
  className,
}: LoadingSpinnerProps) {
  return (
    <div
      role="status"
      aria-label="載入中"
      className={cn(
        'inline-block animate-spin rounded-full',
        'border-2 border-current border-t-transparent',
        'text-primary-600 dark:text-primary-400',
        sizeMap[size],
        className
      )}
    >
      <span className="sr-only">載入中...</span>
    </div>
  );
}

export default LoadingSpinner;
