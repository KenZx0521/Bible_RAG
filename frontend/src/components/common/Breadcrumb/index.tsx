/**
 * Breadcrumb Component
 *
 * Navigation breadcrumb with links and separators.
 *
 * @example
 * <Breadcrumb
 *   items={[
 *     { label: '首頁', href: '/' },
 *     { label: '創世記', href: '/bible/1' },
 *     { label: '第一章' }
 *   ]}
 * />
 */

import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import type { BreadcrumbProps } from '@/types/component.types';
import { cn } from '@/lib/utils';

export function Breadcrumb({ items }: BreadcrumbProps) {
  if (!items || items.length === 0) {
    return null;
  }

  return (
    <nav aria-label="breadcrumb" className="flex items-center">
      <ol className="flex items-center gap-1 text-sm">
        {items.map((item, index) => {
          const isLast = index === items.length - 1;

          return (
            <li key={index} className="flex items-center gap-1">
              {index > 0 && (
                <ChevronRight
                  className="w-4 h-4 text-gray-400 flex-shrink-0"
                  aria-hidden="true"
                />
              )}

              {isLast || !item.href ? (
                <span
                  className={cn(
                    'font-medium',
                    isLast
                      ? 'text-gray-900'
                      : 'text-gray-500'
                  )}
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              ) : (
                <Link
                  to={item.href}
                  className={cn(
                    'text-gray-500',
                    'hover:text-gray-700',
                    'transition-colors duration-200',
                    'focus-visible:outline-none focus-visible:ring-2',
                    'focus-visible:ring-primary-500 focus-visible:rounded'
                  )}
                >
                  {item.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default Breadcrumb;
