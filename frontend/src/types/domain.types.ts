/**
 * Bible RAG - Domain Model Types
 */

import type { EntityType, Testament, TopicType } from './enums';
import type { GraphEdge, GraphNode } from './api.types';

// =============================================================================
// Books and Verses
// =============================================================================

/** Book */
export interface Book {
  id: number;
  name_zh: string;
  abbrev_zh: string;
  testament: Testament;
  order_index: number;
  chapter_count?: number;
  verse_count?: number;
  pericope_count?: number;
}

/** Chapter */
export interface Chapter {
  book_id: number;
  chapter_number: number;
  verse_count: number;
}

/** Verse */
export interface Verse {
  id: number;
  book_id: number;
  book_name: string;
  chapter: number;
  verse: number;
  text: string;
  reference: string;
  pericope_id?: number;
  pericope_title?: string;
}

// =============================================================================
// Pericopes
// =============================================================================

/** Pericope */
export interface Pericope {
  id: number;
  book_id: number;
  book_name: string;
  title: string;
  chapter_start: number;
  verse_start: number;
  chapter_end: number;
  verse_end: number;
  reference: string;
  summary?: string | null;
  verses?: Verse[];
}

// =============================================================================
// Knowledge Graph
// =============================================================================

/** Entity (person/place/group/event) */
export interface Entity {
  id: number;
  name: string;
  type: EntityType;
  description?: string | null;
}

/** Topic */
export interface Topic {
  id: number;
  name: string;
  type: TopicType;
  description?: string | null;
}

/** Visual graph node (extends GraphNode) */
export interface VisualGraphNode extends GraphNode {
  /** X coordinate */
  x?: number;
  /** Y coordinate */
  y?: number;
  /** Node color */
  color?: string;
  /** Node size */
  size?: number;
  /** Is center node */
  isCenter?: boolean;
}

/** Visual graph edge (extends GraphEdge) */
export interface VisualGraphEdge extends GraphEdge {
  /** Edge color */
  color?: string;
  /** Edge width */
  width?: number;
}

/** Graph visualization data */
export interface GraphData {
  nodes: VisualGraphNode[];
  edges: VisualGraphEdge[];
}
