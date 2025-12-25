/**
 * LoadingOverlay Component
 *
 * A full-screen loading overlay with spinner and optional message.
 *
 * @example
 * // Basic usage
 * <LoadingOverlay isLoading={isSubmitting} />
 *
 * // With message
 * <LoadingOverlay
 *   isLoading={isProcessing}
 *   message="正在處理您的請求..."
 * />
 */

import { cn } from '@/lib/utils';
import { LoadingSpinner } from '../LoadingSpinner';

export interface LoadingOverlayProps {
  /** Whether to show the overlay */
  isLoading: boolean;
  /** Optional loading message */
  message?: string;
}

export function LoadingOverlay({ isLoading, message }: LoadingOverlayProps) {
  if (!isLoading) {
    return null;
  }

  return (
    <div
      className={cn(
        'fixed inset-0 z-50',
        'flex flex-col items-center justify-center gap-4',
        'bg-black/50',
        'animate-in fade-in duration-200'
      )}
      role="status"
      aria-live="polite"
      aria-label="載入中"
    >
      <div className="bg-white rounded-xl p-6 shadow-xl flex flex-col items-center gap-4">
        <LoadingSpinner size="lg" />
        {message && (
          <p className="text-gray-700 text-center font-medium">
            {message}
          </p>
        )}
      </div>
    </div>
  );
}

export default LoadingOverlay;
