/**
 * Bible RAG - Store Types
 */

import type { QueryMode } from './enums';
import type { GraphEdge, GraphNode } from './api.types';

// =============================================================================
// Theme
// =============================================================================

/** Theme setting */
export type Theme = 'light' | 'dark' | 'system';

// =============================================================================
// App State
// =============================================================================

/** Application state */
export interface AppState {
  // UI State
  /** Sidebar open status */
  sidebarOpen: boolean;
  /** Theme setting */
  theme: Theme;

  // Current Selection
  /** Selected book ID */
  selectedBookId: number | null;
  /** Selected chapter number */
  selectedChapter: number | null;
  /** Selected pericope ID */
  selectedPericopeId: number | null;

  // Actions
  /** Toggle sidebar */
  toggleSidebar: () => void;
  /** Set theme */
  setTheme: (theme: Theme) => void;
  /** Select book */
  selectBook: (bookId: number | null) => void;
  /** Select chapter */
  selectChapter: (chapter: number | null) => void;
  /** Select pericope */
  selectPericope: (pericopeId: number | null) => void;
  /** Reset selection state */
  reset: () => void;
}

// =============================================================================
// Search State
// =============================================================================

/** Search state */
export interface SearchState {
  // Query History
  /** Search history records */
  history: string[];
  /** Maximum history length */
  maxHistoryLength: number;

  // Current Query
  /** Current query text */
  currentQuery: string;
  /** Current query mode */
  currentMode: QueryMode;

  // Actions
  /** Set query text */
  setQuery: (query: string) => void;
  /** Set query mode */
  setMode: (mode: QueryMode) => void;
  /** Add to history */
  addToHistory: (query: string) => void;
  /** Clear history */
  clearHistory: () => void;
}

// =============================================================================
// Graph State
// =============================================================================

/** Graph state */
export interface GraphState {
  // Graph Data
  /** Nodes list */
  nodes: GraphNode[];
  /** Edges list */
  edges: GraphEdge[];

  // Selection State
  /** Selected node ID */
  selectedNodeId: string | null;
  /** Center node ID */
  centerNodeId: string | null;

  // Actions
  /** Set graph data */
  setGraphData: (nodes: GraphNode[], edges: GraphEdge[]) => void;
  /** Select node */
  selectNode: (nodeId: string | null) => void;
  /** Set center node */
  setCenterNode: (nodeId: string) => void;
  /** Clear graph */
  clearGraph: () => void;
}
