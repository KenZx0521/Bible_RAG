/**
 * Bible RAG - Component Props Types
 */

import type { ReactNode } from 'react';
import type { QueryMode } from './enums';
import type {
  ChapterInfo,
  GraphEdge,
  GraphNode,
  PericopeListItem,
  PericopeSegment,
  QueryResponse,
  VerseItem,
} from './api.types';

// =============================================================================
// Common Component Props
// =============================================================================

/** Button props */
export interface ButtonProps {
  /** Style variant */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** Size */
  size?: 'sm' | 'md' | 'lg';
  /** Disabled state */
  disabled?: boolean;
  /** Loading state */
  loading?: boolean;
  /** Button type */
  type?: 'button' | 'submit' | 'reset';
  /** Click callback */
  onClick?: () => void;
  /** Children */
  children: ReactNode;
  /** Additional CSS class */
  className?: string;
}

/** Input props */
export interface InputProps {
  /** Input type */
  type?: 'text' | 'email' | 'password' | 'number' | 'search';
  /** Input value */
  value: string;
  /** Change callback */
  onChange: (value: string) => void;
  /** Placeholder text */
  placeholder?: string;
  /** Disabled state */
  disabled?: boolean;
  /** Error message */
  error?: string;
  /** Label text */
  label?: string;
  /** Required field */
  required?: boolean;
  /** Additional CSS class */
  className?: string;
}

/** Card props */
export interface CardProps {
  /** Children */
  children: ReactNode;
  /** Padding */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** Additional CSS class */
  className?: string;
  /** Click callback */
  onClick?: () => void;
}

/** Loading spinner props */
export interface LoadingSpinnerProps {
  /** Size */
  size?: 'sm' | 'md' | 'lg';
  /** Additional CSS class */
  className?: string;
}

/** Pagination props */
export interface PaginationProps {
  /** Current page number */
  currentPage: number;
  /** Total pages */
  totalPages: number;
  /** Page change callback */
  onPageChange: (page: number) => void;
  /** Number of sibling pages to show */
  siblingsCount?: number;
}

/** Breadcrumb item */
export interface BreadcrumbItem {
  /** Label text */
  label: string;
  /** Link URL */
  href?: string;
}

/** Breadcrumb props */
export interface BreadcrumbProps {
  /** Breadcrumb items */
  items: BreadcrumbItem[];
}

// =============================================================================
// Search Component Props
// =============================================================================

/** Search bar props */
export interface SearchBarProps {
  /** Input value */
  value: string;
  /** Change callback */
  onChange: (value: string) => void;
  /** Submit callback */
  onSubmit: () => void;
  /** Placeholder text */
  placeholder?: string;
  /** Disabled state */
  disabled?: boolean;
  /** Loading state */
  loading?: boolean;
  /** Auto focus */
  autoFocus?: boolean;
}

/** Query mode selector props */
export interface QueryModeSelectorProps {
  /** Current selected mode */
  value: QueryMode;
  /** Change callback */
  onChange: (mode: QueryMode) => void;
}

/** Query result props */
export interface QueryResultProps {
  /** Query response data */
  result: QueryResponse;
}

/** Segment card props */
export interface SegmentCardProps {
  /** Segment data */
  segment: PericopeSegment;
}

// =============================================================================
// Bible Browser Component Props
// =============================================================================

/** Book selector props */
export interface BookSelectorProps {
  /** Current selected book ID */
  selectedBookId?: number | null;
  /** Select callback */
  onSelect?: (bookId: number) => void;
}

/** Chapter grid props */
export interface ChapterGridProps {
  /** Book ID */
  bookId: number;
  /** Book name */
  bookName: string;
  /** Chapters list */
  chapters: ChapterInfo[];
}

/** Verse list props */
export interface VerseListProps {
  /** Book ID */
  bookId: number;
  /** Book name */
  bookName: string;
  /** Chapter number */
  chapter: number;
  /** Verses list */
  verses: VerseItem[];
  /** Total chapters in book */
  totalChapters: number;
  /** Highlighted verse ID */
  highlightVerseId?: number;
}

/** Pericope card props */
export interface PericopeCardProps {
  /** Pericope data */
  pericope: PericopeListItem;
  /** Show book name */
  showBook?: boolean;
}

// =============================================================================
// Graph Component Props
// =============================================================================

/** Graph viewer props */
export interface GraphViewerProps {
  /** Nodes data */
  nodes: GraphNode[];
  /** Edges data */
  edges: GraphEdge[];
  /** Node click callback */
  onNodeClick?: (nodeId: string) => void;
  /** Center node ID */
  centerNodeId?: string;
  /** Canvas width */
  width?: number;
  /** Canvas height */
  height?: number;
}

/** Entity panel props */
export interface EntityPanelProps {
  /** Entity ID */
  entityId: number;
  /** Close callback */
  onClose?: () => void;
}

/** Topic panel props */
export interface TopicPanelProps {
  /** Topic ID */
  topicId: number;
  /** Close callback */
  onClose?: () => void;
}
