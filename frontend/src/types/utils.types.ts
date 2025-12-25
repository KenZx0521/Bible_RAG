/**
 * Bible RAG - Utility Types
 */

// =============================================================================
// Generic Utility Types
// =============================================================================

/** Nullable type */
export type Nullable<T> = T | null;

/** Optional type */
export type Optional<T> = T | undefined;

/** Deep partial type */
export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

/** Get value type of object */
export type ValueOf<T> = T[keyof T];

/** Exclude null and undefined */
export type NonNullableFields<T> = {
  [P in keyof T]: NonNullable<T[P]>;
};

/** Extract specific type from union */
export type ExtractType<T, U extends T> = T extends U ? T : never;

/** Merge two types */
export type Merge<T, U> = Omit<T, keyof U> & U;

// =============================================================================
// Pagination Utility Types
// =============================================================================

/** Paginated response wrapper */
export interface PaginatedResponse<T> {
  /** Data list */
  data: T[];
  /** Total count */
  total: number;
  /** Pagination offset */
  skip: number;
  /** Page size */
  limit: number;
  /** Has more pages */
  hasMore: boolean;
}

/** Pagination state */
export interface PaginationState {
  /** Current page number (1-based) */
  page: number;
  /** Page size */
  pageSize: number;
  /** Total count */
  total: number;
  /** Total pages */
  totalPages: number;
}

/** Calculate pagination info */
export function calculatePagination(
  skip: number,
  limit: number,
  total: number
): PaginationState {
  return {
    page: Math.floor(skip / limit) + 1,
    pageSize: limit,
    total,
    totalPages: Math.ceil(total / limit),
  };
}

// =============================================================================
// Form Utility Types
// =============================================================================

/** Form field state */
export interface FieldState<T> {
  /** Field value */
  value: T;
  /** Error message */
  error?: string;
  /** Has been touched */
  touched: boolean;
  /** Is validating */
  validating: boolean;
}

/** Form state */
export interface FormState<T extends Record<string, unknown>> {
  /** Field states */
  fields: { [K in keyof T]: FieldState<T[K]> };
  /** Is submitting */
  isSubmitting: boolean;
  /** Is valid */
  isValid: boolean;
  /** Has been modified */
  isDirty: boolean;
}

/** Form validation rule */
export type ValidationRule<T> = (value: T) => string | undefined;

/** Form validation result */
export interface ValidationResult {
  isValid: boolean;
  errors: Record<string, string>;
}
