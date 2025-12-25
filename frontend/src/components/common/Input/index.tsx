/**
 * Input Component
 *
 * A form input with integrated label and error handling.
 *
 * @example
 * // Basic usage
 * <Input
 *   value={email}
 *   onChange={setEmail}
 *   placeholder="Enter email"
 * />
 *
 * // With label and error
 * <Input
 *   label="Email"
 *   value={email}
 *   onChange={setEmail}
 *   error="Invalid email format"
 *   required
 * />
 */

import { forwardRef, useId, type InputHTMLAttributes } from 'react';
import type { InputProps } from '@/types/component.types';
import { cn } from '@/lib/utils';

type NativeInputProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  'type' | 'value' | 'onChange' | 'disabled' | 'required' | 'placeholder'
>;

export const Input = forwardRef<
  HTMLInputElement,
  InputProps & NativeInputProps
>(function Input(
  {
    type = 'text',
    value,
    onChange,
    placeholder,
    disabled = false,
    error,
    label,
    required = false,
    className,
    ...props
  },
  ref
) {
  const generatedId = useId();
  const inputId = props.id || generatedId;
  const errorId = `${inputId}-error`;

  return (
    <div className="w-full">
      {label && (
        <label
          htmlFor={inputId}
          className={cn(
            'input-label',
            required && "after:content-['*'] after:ml-0.5 after:text-error"
          )}
        >
          {label}
        </label>
      )}
      <input
        ref={ref}
        id={inputId}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={disabled}
        required={required}
        aria-invalid={!!error}
        aria-describedby={error ? errorId : undefined}
        className={cn(
          'input-base',
          error && 'input-error',
          className
        )}
        {...props}
      />
      {error && (
        <p id={errorId} className="input-error-message" role="alert">
          {error}
        </p>
      )}
    </div>
  );
});

export default Input;
