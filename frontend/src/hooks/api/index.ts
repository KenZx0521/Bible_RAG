/**
 * Bible RAG - API Hooks
 *
 * This file re-exports all API-related hooks.
 */

export { queryKeys } from './queryKeys';
export type { QueryKeys } from './queryKeys';

export { useRagQuery } from './useRagQuery';
export type { UseRagQueryOptions } from './useRagQuery';

// Books API hooks
export { useBooks } from './useBooks';
export { useBookChapters } from './useBookChapters';
export { useBookVerses } from './useBookVerses';

// Pericopes API hooks
export { usePericopeDetail, usePericopes } from './usePericopes';

// Verses API hooks
export { useVerseDetail, useVersesList, useVerseSearch } from './useVerses';

// Graph API hooks
export {
  useGraphRelationships,
  useEntitySearch,
  useEntityDetail,
  useTopicSearch,
  useTopicDetail,
  useRelatedTopics,
  useGraphStats,
} from './useGraph';
