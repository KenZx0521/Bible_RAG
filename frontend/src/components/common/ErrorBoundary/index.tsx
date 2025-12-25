/**
 * ErrorBoundary Component
 *
 * Catches JavaScript errors in child components and displays a fallback UI.
 *
 * @example
 * // Basic usage
 * <ErrorBoundary>
 *   <App />
 * </ErrorBoundary>
 *
 * // With custom fallback
 * <ErrorBoundary
 *   fallback={<CustomErrorPage />}
 *   onError={(error, info) => logError(error, info)}
 * >
 *   <App />
 * </ErrorBoundary>
 */

import { Component, type ReactNode, type ErrorInfo } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from '../Button';
import { Card } from '../Card';

export interface ErrorBoundaryProps {
  /** Children components to wrap */
  children: ReactNode;
  /** Custom fallback UI */
  fallback?: ReactNode;
  /** Error callback */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return {
      hasError: true,
      error,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo });

    // Call the error callback if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // Log error in development
    if (import.meta.env.DEV) {
      console.error('ErrorBoundary caught an error:', error);
      console.error('Component stack:', errorInfo.componentStack);
    }
  }

  handleRetry = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    const { hasError, error } = this.state;
    const { children, fallback } = this.props;

    if (hasError) {
      // If custom fallback is provided, use it
      if (fallback) {
        return fallback;
      }

      // Default error UI
      return (
        <div className="min-h-[400px] flex items-center justify-center p-4">
          <Card padding="lg" className="max-w-md w-full text-center">
            <div className="flex flex-col items-center gap-4">
              <div className="w-16 h-16 rounded-full bg-error-light dark:bg-error-dark/20 flex items-center justify-center">
                <AlertTriangle className="w-8 h-8 text-error" />
              </div>

              <div className="space-y-2">
                <h2 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                  發生錯誤
                </h2>
                <p className="text-gray-600 dark:text-gray-400">
                  很抱歉，頁面發生了一些問題。請嘗試重新載入。
                </p>
              </div>

              {import.meta.env.DEV && error && (
                <div className="w-full mt-4 p-3 bg-gray-100 dark:bg-gray-800 rounded-lg text-left">
                  <p className="text-sm font-mono text-error break-all">
                    {error.message}
                  </p>
                </div>
              )}

              <Button
                variant="primary"
                onClick={this.handleRetry}
                className="mt-4"
              >
                <RefreshCw className="w-4 h-4" />
                重試
              </Button>
            </div>
          </Card>
        </div>
      );
    }

    return children;
  }
}

export default ErrorBoundary;
