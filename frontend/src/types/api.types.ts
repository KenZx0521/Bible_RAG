/**
 * Bible RAG - API Types
 */

import type { EntityType, QueryMode, QueryType, Testament, TopicType } from './enums';

// =============================================================================
// Request Types
// =============================================================================

/** Query options */
export interface QueryOptions {
  /** Number of pericopes to return, range 1-20, default 5 */
  max_results?: number;
  /** Whether to include knowledge graph context */
  include_graph?: boolean;
}

/** RAG query request */
export interface QueryRequest {
  /** User question, length 1-500 characters */
  query: string;
  /** Query mode */
  mode?: QueryMode;
  /** Query options */
  options?: QueryOptions;
}

/** Common pagination parameters */
export interface PaginationParams {
  /** Pagination offset, default 0 */
  skip?: number;
  /** Page size, default 20, max 100 */
  limit?: number;
}

/** Pericope list request parameters */
export interface PericopesListParams extends PaginationParams {
  /** Filter by book ID */
  book_id?: number;
}

/** Verse list request parameters */
export interface VersesListParams extends PaginationParams {
  /** Filter by book ID */
  book_id?: number;
  /** Filter by chapter (requires book_id) */
  chapter?: number;
  /** Filter by pericope ID */
  pericope_id?: number;
}

/** Verse search request parameters */
export interface VerseSearchParams {
  /** Search keyword */
  q: string;
  /** Limit search to specific book */
  book_id?: number;
  /** Number of results, max 100, default 20 */
  limit?: number;
}

/** Entity search request parameters */
export interface EntitySearchParams {
  /** Entity name (fuzzy search) */
  name?: string;
  /** Entity type */
  type?: EntityType;
  /** Number of results, default 20 */
  limit?: number;
}

/** Topic search request parameters */
export interface TopicSearchParams {
  /** Topic name (fuzzy search) */
  name?: string;
  /** Topic type */
  type?: TopicType;
  /** Number of results, default 20 */
  limit?: number;
}

/** Graph relationships request parameters */
export interface GraphRelationshipsParams {
  /** Center entity ID */
  entity_id: number;
  /** Entity type */
  entity_type: EntityType | 'TOPIC';
  /** Expansion depth, range 1-3, default 2 */
  depth?: number;
}

// =============================================================================
// Response Types - RAG Query
// =============================================================================

/** Pericope segment (query result) */
export interface PericopeSegment {
  /** Pericope ID */
  id: number;
  /** Type, fixed as "pericope" */
  type: 'pericope';
  /** Book name */
  book: string;
  /** Start chapter */
  chapter_start: number;
  /** Start verse */
  verse_start: number;
  /** End chapter */
  chapter_end: number;
  /** End verse */
  verse_end: number;
  /** Pericope title */
  title: string;
  /** Text excerpt */
  text_excerpt: string;
  /** Relevance score (0-1) */
  relevance_score: number;
}

/** Query metadata */
export interface QueryMeta {
  /** System-detected query type */
  query_type: QueryType;
  /** List of retrievers used */
  used_retrievers: string[];
  /** Total processing time (ms) */
  total_processing_time_ms: number;
  /** LLM model used */
  llm_model: string;
}

/** Graph context */
export interface GraphContext {
  /** Related topics list */
  related_topics?: string[];
  /** Related persons list */
  related_persons?: string[];
}

/** RAG query response */
export interface QueryResponse {
  /** LLM-generated answer in Markdown format */
  answer: string;
  /** Related scripture segments */
  segments: PericopeSegment[];
  /** Query metadata */
  meta: QueryMeta;
  /** Knowledge graph context (requires include_graph: true) */
  graph_context?: GraphContext;
}

// =============================================================================
// Response Types - Books
// =============================================================================

/** Book list item */
export interface BookListItem {
  /** Book ID */
  id: number;
  /** Chinese name */
  name_zh: string;
  /** Chinese abbreviation */
  abbrev_zh: string;
  /** Testament */
  testament: Testament;
  /** Canon order (1-66) */
  order_index: number;
}

/** Books list response */
export interface BooksListResponse {
  /** Book list */
  books: BookListItem[];
  /** Total count */
  total: number;
}

/** Book detail */
export interface BookDetail extends BookListItem {
  /** Chapter count */
  chapter_count: number;
  /** Verse count */
  verse_count: number;
  /** Pericope count */
  pericope_count: number;
}

/** Chapter info */
export interface ChapterInfo {
  /** Chapter number */
  chapter: number;
  /** Verse count */
  verse_count: number;
}

/** Book chapters response */
export interface BookChaptersResponse {
  /** Book ID */
  book_id: number;
  /** Book name */
  book_name: string;
  /** Chapters list */
  chapters: ChapterInfo[];
}

/** Book pericopes response */
export interface BookPericopesResponse {
  /** Book ID */
  book_id: number;
  /** Book name */
  book_name: string;
  /** Pericopes list */
  pericopes: PericopeListItem[];
  /** Total count */
  total: number;
}

/** Book verses response */
export interface BookVersesResponse {
  /** Book ID */
  book_id: number;
  /** Book name */
  book_name: string;
  /** Verses list */
  verses: VerseItem[];
  /** Total count */
  total: number;
}

// =============================================================================
// Response Types - Pericopes
// =============================================================================

/** Pericope list item */
export interface PericopeListItem {
  /** Pericope ID */
  id: number;
  /** Book ID */
  book_id: number;
  /** Book name */
  book_name: string;
  /** Pericope title */
  title: string;
  /** Reference (e.g., "Genesis 1:1-31") */
  reference: string;
  /** Start chapter */
  chapter_start: number;
  /** Start verse */
  verse_start: number;
  /** End chapter */
  chapter_end: number;
  /** End verse */
  verse_end: number;
}

/** Pericopes list response */
export interface PericopesListResponse {
  /** Pericopes list */
  pericopes: PericopeListItem[];
  /** Total count */
  total: number;
  /** Pagination offset */
  skip: number;
  /** Page size */
  limit: number;
}

/** Pericope detail */
export interface PericopeDetail extends PericopeListItem {
  /** Summary (LLM-generated, may be null) */
  summary: string | null;
  /** Verses within this pericope */
  verses: VerseItem[];
}

// =============================================================================
// Response Types - Verses
// =============================================================================

/** Verse item */
export interface VerseItem {
  /** Verse ID */
  id: number;
  /** Book ID */
  book_id: number;
  /** Book name */
  book_name: string;
  /** Chapter number */
  chapter: number;
  /** Verse number */
  verse: number;
  /** Verse text */
  text: string;
  /** Reference (e.g., "Genesis 1:1") */
  reference: string;
}

/** Verse detail */
export interface VerseDetail extends VerseItem {
  /** Parent pericope ID */
  pericope_id: number;
  /** Parent pericope title */
  pericope_title: string;
}

/** Verses list response */
export interface VersesListResponse {
  /** Verses list */
  verses: VerseItem[];
  /** Total count */
  total: number;
  /** Pagination offset */
  skip: number;
  /** Page size */
  limit: number;
}

/** Verse search result item */
export interface VerseSearchResultItem extends VerseItem {
  /** Search relevance score (0-1) */
  rank: number;
}

/** Verse search response */
export interface VerseSearchResponse {
  /** Search query */
  query: string;
  /** Search results */
  verses: VerseSearchResultItem[];
  /** Total count */
  total: number;
}

// =============================================================================
// Response Types - Knowledge Graph
// =============================================================================

/** Graph node */
export interface GraphNode {
  /** Node ID (format: {type}_{id}, e.g., "person_156") */
  id: string;
  /** Display label */
  label: string;
  /** Node type */
  type: string;
  /** Node properties */
  properties: Record<string, unknown>;
}

/** Graph edge */
export interface GraphEdge {
  /** Source node ID */
  source: string;
  /** Target node ID */
  target: string;
  /** Relationship type */
  type: string;
  /** Relationship properties */
  properties: Record<string, unknown>;
}

/** Graph relationships response */
export interface GraphRelationshipsResponse {
  /** Nodes list */
  nodes: GraphNode[];
  /** Edges list */
  edges: GraphEdge[];
}

/** Graph health response */
export interface GraphHealthResponse {
  /** Connection status */
  status: 'healthy' | 'unhealthy';
  /** Neo4j connection URI */
  uri: string;
}

/** Graph stats response */
export interface GraphStatsResponse {
  /** Total persons */
  total_persons: number;
  /** Total places */
  total_places: number;
  /** Total groups */
  total_groups: number;
  /** Total events */
  total_events: number;
  /** Total topics */
  total_topics: number;
  /** Total relationships */
  total_relationships: number;
}

/** Entity search result */
export interface EntitySearchResult {
  /** Entity ID */
  id: number;
  /** Entity name */
  name: string;
  /** Entity type */
  type: EntityType;
}

/** Entity search response */
export interface EntitySearchResponse {
  /** Entities list */
  entities: EntitySearchResult[];
  /** Total count */
  total: number;
}

/** Entity detail */
export interface EntityDetail extends EntitySearchResult {
  /** Entity description */
  description: string | null;
  /** Related verses count */
  related_verses_count: number;
  /** Related entities list */
  related_entities: EntitySearchResult[];
}

/** Topic search result */
export interface TopicSearchResult {
  /** Topic ID */
  id: number;
  /** Topic name */
  name: string;
  /** Topic type */
  type: TopicType;
}

/** Topic search response */
export interface TopicSearchResponse {
  /** Topics list */
  topics: TopicSearchResult[];
  /** Total count */
  total: number;
}

/** Topic detail */
export interface TopicDetail extends TopicSearchResult {
  /** Topic description */
  description: string | null;
  /** Related verses count */
  related_verses_count: number;
  /** Related topics list */
  related_topics: TopicSearchResult[];
}

/** Related topic item */
export interface RelatedTopicItem extends TopicSearchResult {
  /** Relation weight (Jaccard similarity) */
  weight: number;
  /** Co-occurrence count */
  co_occurrence: number;
}

/** Related topics response */
export interface RelatedTopicsResponse {
  /** Topic ID */
  topic_id: number;
  /** Topic name */
  topic_name: string;
  /** Related topics list */
  related: RelatedTopicItem[];
  /** Total count */
  total: number;
}

/** Verse entities response */
export interface VerseEntitiesResponse {
  /** Verse ID */
  verse_id: number;
  /** Verse reference */
  verse_reference: string;
  /** Related persons */
  persons: EntitySearchResult[];
  /** Related places */
  places: EntitySearchResult[];
  /** Related groups */
  groups: EntitySearchResult[];
  /** Related events */
  events: EntitySearchResult[];
  /** Related topics */
  topics: TopicSearchResult[];
}

/** Cross reference verse */
export interface CrossReferenceVerse {
  /** Verse ID */
  verse_id: number;
  /** Reference */
  reference: string;
  /** Verse text */
  text: string;
}

/** Cross references response */
export interface CrossReferencesResponse {
  /** Verse ID */
  verse_id: number;
  /** Verse reference */
  verse_reference: string;
  /** Verses this verse quotes */
  quotes: CrossReferenceVerse[];
  /** Verses that quote this verse */
  quoted_by: CrossReferenceVerse[];
  /** Verses this verse alludes to */
  alludes_to: CrossReferenceVerse[];
  /** Verses that allude to this verse */
  alluded_by: CrossReferenceVerse[];
  /** Total count */
  total: number;
}

/** Prophecies response */
export interface PropheciesResponse {
  /** Verse ID */
  verse_id: number;
  /** Verse reference */
  verse_reference: string;
  /** Is Old Testament verse */
  is_ot: boolean;
  /** NT verses that fulfill this prophecy (OT only) */
  fulfillments: CrossReferenceVerse[];
  /** OT prophecies this verse fulfills (NT only) */
  prophecies: CrossReferenceVerse[];
  /** Total count */
  total: number;
}

/** Parallel pericope */
export interface ParallelPericope {
  /** Pericope ID */
  pericope_id: number;
  /** Book name */
  book_name: string;
  /** Pericope title */
  title: string;
  /** Reference */
  reference: string;
  /** Parallel name */
  parallel_name: string;
}

/** Parallels response */
export interface ParallelsResponse {
  /** Pericope ID */
  pericope_id: number;
  /** Pericope title */
  pericope_title: string;
  /** Pericope reference */
  pericope_reference: string;
  /** Parallel pericopes list */
  parallels: ParallelPericope[];
  /** Total count */
  total: number;
}

// =============================================================================
// Error Types
// =============================================================================

/** API error response */
export interface ApiError {
  /** Error message */
  detail: string;
}

/** HTTP status code */
export type HttpStatusCode = 200 | 400 | 404 | 422 | 500 | 503;

/** Custom error class */
export class BibleRagError extends Error {
  statusCode?: HttpStatusCode;
  code?: string;

  constructor(message: string, statusCode?: HttpStatusCode, code?: string) {
    super(message);
    this.name = 'BibleRagError';
    this.statusCode = statusCode;
    this.code = code;
  }
}

/** Validation error detail */
export interface ValidationErrorDetail {
  /** Error location */
  loc: (string | number)[];
  /** Error message */
  msg: string;
  /** Error type */
  type: string;
}

/** Validation error response (422) */
export interface ValidationErrorResponse {
  detail: ValidationErrorDetail[];
}
