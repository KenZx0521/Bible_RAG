/**
 * Card Component
 *
 * A container component for grouping related content.
 *
 * @example
 * // Basic card
 * <Card>
 *   <p>Card content</p>
 * </Card>
 *
 * // Scripture variant with click handler
 * <Card variant="scripture" padding="lg" onClick={handleClick}>
 *   <p className="verse-text">In the beginning...</p>
 * </Card>
 */

import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';

export interface CardComponentProps {
  /** Children */
  children: ReactNode;
  /** Padding */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** Visual variant */
  variant?: 'default' | 'scripture';
  /** Additional CSS class */
  className?: string;
  /** Click callback */
  onClick?: () => void;
}

const paddingStyles = {
  none: '',
  sm: 'p-3',
  md: 'p-4',
  lg: 'p-6',
} as const;

const variantStyles = {
  default: 'card',
  scripture: 'card-scripture',
} as const;

export function Card({
  children,
  padding = 'md',
  variant = 'default',
  className,
  onClick,
}: CardComponentProps) {
  const isClickable = !!onClick;

  const cardClassName = cn(
    variantStyles[variant],
    paddingStyles[padding],
    isClickable && 'card-hover',
    className
  );

  if (isClickable) {
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onClick();
          }
        }}
        className={cardClassName}
      >
        {children}
      </div>
    );
  }

  return <div className={cardClassName}>{children}</div>;
}

export default Card;
