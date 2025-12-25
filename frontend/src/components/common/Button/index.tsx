/**
 * Button Component
 *
 * A versatile button component with multiple variants and states.
 *
 * @example
 * // Primary button
 * <Button variant="primary">Click me</Button>
 *
 * // Loading state
 * <Button loading>Submitting...</Button>
 *
 * // With icon
 * <Button variant="ghost" size="sm">
 *   <Search className="w-4 h-4 mr-2" />
 *   Search
 * </Button>
 */

import { forwardRef, type ButtonHTMLAttributes } from 'react';
import type { ButtonProps } from '@/types/component.types';
import { cn } from '@/lib/utils';
import { LoadingSpinner } from '../LoadingSpinner';

const variantStyles = {
  primary: 'btn-primary',
  secondary: 'btn-secondary',
  ghost: 'btn-ghost',
  danger: 'btn-danger',
} as const;

const sizeStyles = {
  sm: 'btn-sm',
  md: '', // default size in CSS
  lg: 'btn-lg',
} as const;

type NativeButtonProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  'type' | 'onClick' | 'disabled'
>;

export const Button = forwardRef<
  HTMLButtonElement,
  ButtonProps & NativeButtonProps
>(function Button(
  {
    variant = 'primary',
    size = 'md',
    disabled = false,
    loading = false,
    type = 'button',
    onClick,
    children,
    className,
    ...props
  },
  ref
) {
  const isDisabled = disabled || loading;

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      onClick={isDisabled ? undefined : onClick}
      className={cn(
        'inline-flex items-center justify-center gap-2',
        'transition-all duration-200',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2',
        'dark:focus-visible:ring-offset-gray-900',
        variantStyles[variant],
        sizeStyles[size],
        isDisabled && 'opacity-50 cursor-not-allowed',
        className
      )}
      aria-busy={loading}
      {...props}
    >
      {loading && (
        <LoadingSpinner
          size={size === 'lg' ? 'md' : 'sm'}
          className="text-current"
        />
      )}
      {children}
    </button>
  );
});

export default Button;
