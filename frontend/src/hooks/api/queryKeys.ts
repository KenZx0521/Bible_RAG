/**
 * Bible RAG - Query Keys
 *
 * Centralized query key factory for TanStack Query.
 */

import type {
  EntitySearchParams,
  GraphRelationshipsParams,
  PericopesListParams,
  TopicSearchParams,
  VerseSearchParams,
  VersesListParams,
} from '@/types';

/** Query key factory */
export const queryKeys = {
  /** Book-related keys */
  books: {
    all: ['books'] as const,
    detail: (id: number) => ['books', id] as const,
    chapters: (id: number) => ['books', id, 'chapters'] as const,
    pericopes: (id: number) => ['books', id, 'pericopes'] as const,
    verses: (id: number, chapter?: number) =>
      ['books', id, 'verses', { chapter }] as const,
  },

  /** Pericope-related keys */
  pericopes: {
    all: ['pericopes'] as const,
    list: (params: PericopesListParams) =>
      ['pericopes', 'list', params] as const,
    detail: (id: number) => ['pericopes', id] as const,
  },

  /** Verse-related keys */
  verses: {
    all: ['verses'] as const,
    list: (params: VersesListParams) =>
      ['verses', 'list', params] as const,
    detail: (id: number) => ['verses', id] as const,
    search: (params: VerseSearchParams) =>
      ['verses', 'search', params] as const,
  },

  /** Knowledge graph-related keys */
  graph: {
    health: ['graph', 'health'] as const,
    stats: ['graph', 'stats'] as const,
    entitySearch: (params: EntitySearchParams) =>
      ['graph', 'entity', 'search', params] as const,
    entity: (id: number) => ['graph', 'entity', id] as const,
    topicSearch: (params: TopicSearchParams) =>
      ['graph', 'topic', 'search', params] as const,
    topic: (id: number) => ['graph', 'topic', id] as const,
    topicRelated: (id: number) => ['graph', 'topic', id, 'related'] as const,
    relationships: (params: GraphRelationshipsParams) =>
      ['graph', 'relationships', params] as const,
    verseEntities: (verseId: number) =>
      ['graph', 'verse', verseId, 'entities'] as const,
    verseCrossReferences: (verseId: number) =>
      ['graph', 'verse', verseId, 'cross-references'] as const,
    verseProphecies: (verseId: number) =>
      ['graph', 'verse', verseId, 'prophecies'] as const,
    pericopeParallels: (pericopeId: number) =>
      ['graph', 'pericope', pericopeId, 'parallels'] as const,
  },
} as const;

/** Query key types */
export type QueryKeys = typeof queryKeys;
