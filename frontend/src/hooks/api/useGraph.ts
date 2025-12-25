/**
 * useGraph Hooks
 *
 * Hooks for fetching knowledge graph data.
 * Includes entity, topic, and relationship queries with fallback data.
 *
 * @example
 * // Get entity relationships
 * const { data } = useGraphRelationships({ entity_id: 1, entity_type: 'PERSON' });
 *
 * // Search entities
 * const { data } = useEntitySearch('摩西');
 *
 * // Get entity detail
 * const { data } = useEntityDetail(1);
 */

import { useQuery } from '@tanstack/react-query';
import { graphApi } from '@/api/endpoints/graph';
import { queryKeys } from './queryKeys';
import type {
  EntityDetail,
  EntitySearchResponse,
  GraphRelationshipsParams,
  GraphRelationshipsResponse,
  RelatedTopicsResponse,
  TopicDetail,
  TopicSearchResponse,
} from '@/types';

// =============================================================================
// Mock Data
// =============================================================================

/** Mock nodes for development/fallback */
const mockNodes = [
  { id: 'person_1', label: '摩西', type: 'PERSON', properties: { description: '以色列的領袖和先知' } },
  { id: 'person_2', label: '亞倫', type: 'PERSON', properties: { description: '摩西的兄長，首位大祭司' } },
  { id: 'person_3', label: '米利暗', type: 'PERSON', properties: { description: '摩西的姐姐，女先知' } },
  { id: 'person_4', label: '約書亞', type: 'PERSON', properties: { description: '摩西的繼承者' } },
  { id: 'place_1', label: '西奈山', type: 'PLACE', properties: { description: '神頒布十誡之地' } },
  { id: 'place_2', label: '埃及', type: 'PLACE', properties: { description: '以色列人曾被奴役之地' } },
  { id: 'place_3', label: '曠野', type: 'PLACE', properties: { description: '以色列人漂流四十年之地' } },
  { id: 'group_1', label: '以色列人', type: 'GROUP', properties: { description: '神的選民' } },
  { id: 'event_1', label: '出埃及', type: 'EVENT', properties: { description: '以色列人離開埃及' } },
  { id: 'event_2', label: '過紅海', type: 'EVENT', properties: { description: '神分開紅海' } },
  { id: 'topic_1', label: '救贖', type: 'TOPIC', properties: { description: '神拯救人類的計劃' } },
  { id: 'topic_2', label: '信心', type: 'TOPIC', properties: { description: '對神的信靠' } },
];

/** Mock edges for development/fallback */
const mockEdges = [
  { source: 'person_1', target: 'person_2', type: 'BROTHER_OF', properties: {} },
  { source: 'person_1', target: 'person_3', type: 'SIBLING_OF', properties: {} },
  { source: 'person_1', target: 'person_4', type: 'MENTOR_OF', properties: {} },
  { source: 'person_1', target: 'place_1', type: 'VISITED', properties: {} },
  { source: 'person_1', target: 'place_2', type: 'BORN_IN', properties: {} },
  { source: 'person_1', target: 'group_1', type: 'LED', properties: {} },
  { source: 'person_1', target: 'event_1', type: 'PARTICIPATED_IN', properties: {} },
  { source: 'person_1', target: 'event_2', type: 'PARTICIPATED_IN', properties: {} },
  { source: 'event_1', target: 'topic_1', type: 'DEMONSTRATES', properties: {} },
  { source: 'group_1', target: 'place_3', type: 'LOCATED_IN', properties: {} },
];

/** Get mock graph relationships response */
const getMockGraphRelationshipsResponse = (
  params: GraphRelationshipsParams
): GraphRelationshipsResponse => {
  // Filter nodes and edges based on the center entity
  const centerNodeId = `${params.entity_type.toLowerCase()}_${params.entity_id}`;
  const centerNode = mockNodes.find((n) => n.id === centerNodeId);

  if (!centerNode) {
    // Return a subset of mock data centered on person_1 (Moses)
    return {
      nodes: mockNodes.slice(0, 6),
      edges: mockEdges.slice(0, 4),
    };
  }

  // Get connected nodes
  const connectedEdges = mockEdges.filter(
    (e) => e.source === centerNodeId || e.target === centerNodeId
  );
  const connectedNodeIds = new Set<string>();
  connectedNodeIds.add(centerNodeId);
  connectedEdges.forEach((e) => {
    connectedNodeIds.add(e.source);
    connectedNodeIds.add(e.target);
  });

  const connectedNodes = mockNodes.filter((n) => connectedNodeIds.has(n.id));

  return {
    nodes: connectedNodes,
    edges: connectedEdges,
  };
};

/** Get mock entity search response */
const getMockEntitySearchResponse = (name: string): EntitySearchResponse => ({
  entities: [
    { id: 1, name: '摩西', type: 'PERSON' as const },
    { id: 2, name: '亞倫', type: 'PERSON' as const },
    { id: 3, name: '米利暗', type: 'PERSON' as const },
    { id: 4, name: '約書亞', type: 'PERSON' as const },
    { id: 5, name: '大衛', type: 'PERSON' as const },
  ].filter((e) => e.name.includes(name) || name.length < 2),
  total: 5,
});

/** Get mock entity detail */
const getMockEntityDetail = (id: number): EntityDetail => ({
  id,
  name: id === 1 ? '摩西' : id === 2 ? '亞倫' : '未知人物',
  type: 'PERSON',
  description:
    id === 1
      ? '摩西是以色列人的領袖和先知，帶領以色列人出埃及，並在西奈山從神領受十誡。'
      : id === 2
        ? '亞倫是摩西的兄長，也是以色列的首位大祭司。'
        : '此實體資料暫無描述。',
  related_verses_count: id === 1 ? 847 : id === 2 ? 347 : 0,
  related_entities: [
    { id: id === 1 ? 2 : 1, name: id === 1 ? '亞倫' : '摩西', type: 'PERSON' },
    { id: 3, name: '米利暗', type: 'PERSON' },
    { id: 4, name: '約書亞', type: 'PERSON' },
  ],
});

/** Get mock topic search response */
const getMockTopicSearchResponse = (name: string): TopicSearchResponse => ({
  topics: [
    { id: 1, name: '救贖', type: 'DOCTRINE' as const },
    { id: 2, name: '信心', type: 'MORAL' as const },
    { id: 3, name: '愛', type: 'MORAL' as const },
    { id: 4, name: '創造', type: 'DOCTRINE' as const },
    { id: 5, name: '末世', type: 'PROPHETIC' as const },
  ].filter((t) => t.name.includes(name) || name.length < 2),
  total: 5,
});

/** Get mock topic detail */
const getMockTopicDetail = (id: number): TopicDetail => ({
  id,
  name: id === 1 ? '救贖' : id === 2 ? '信心' : '未知主題',
  type: id === 1 ? 'DOCTRINE' : id === 2 ? 'MORAL' : 'OTHER',
  description:
    id === 1
      ? '救贖是聖經的核心主題，描述神如何透過耶穌基督拯救人類脫離罪惡。'
      : id === 2
        ? '信心是對神的信靠與順服，是基督徒生命的根基。'
        : '此主題資料暫無描述。',
  related_verses_count: id === 1 ? 156 : id === 2 ? 234 : 0,
  related_topics: [
    { id: id === 1 ? 2 : 1, name: id === 1 ? '信心' : '救贖', type: 'DOCTRINE' },
    { id: 3, name: '愛', type: 'MORAL' },
  ],
});

/** Get mock related topics response */
const getMockRelatedTopicsResponse = (topicId: number): RelatedTopicsResponse => ({
  topic_id: topicId,
  topic_name: topicId === 1 ? '救贖' : '信心',
  related: [
    { id: 2, name: '信心', type: 'DOCTRINE', weight: 0.85, co_occurrence: 45 },
    { id: 3, name: '愛', type: 'MORAL', weight: 0.72, co_occurrence: 38 },
    { id: 4, name: '恩典', type: 'DOCTRINE', weight: 0.68, co_occurrence: 32 },
  ],
  total: 3,
});

// =============================================================================
// Hooks
// =============================================================================

/**
 * Hook to fetch graph relationships for an entity
 * @param params - Relationship parameters (entity_id, entity_type, depth)
 * @returns Query result with nodes and edges
 */
export function useGraphRelationships(params: GraphRelationshipsParams) {
  return useQuery({
    queryKey: queryKeys.graph.relationships(params),
    queryFn: async () => {
      try {
        return await graphApi.getRelationships(params);
      } catch {
        console.warn('Graph API unavailable, using mock data');
        return getMockGraphRelationshipsResponse(params);
      }
    },
    enabled: !!params.entity_id,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to search entities by name
 * @param name - Entity name to search
 * @returns Query result with entity search response
 */
export function useEntitySearch(name: string) {
  return useQuery({
    queryKey: queryKeys.graph.entitySearch({ name }),
    queryFn: async () => {
      try {
        return await graphApi.searchEntities({ name });
      } catch {
        console.warn('Entity search API unavailable, using mock data');
        return getMockEntitySearchResponse(name);
      }
    },
    enabled: !!name && name.length >= 2,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });
}

/**
 * Hook to fetch entity detail by ID
 * @param id - Entity ID
 * @returns Query result with entity detail
 */
export function useEntityDetail(id: number) {
  return useQuery({
    queryKey: queryKeys.graph.entity(id),
    queryFn: async () => {
      try {
        return await graphApi.getEntity(id);
      } catch {
        console.warn('Entity detail API unavailable, using mock data');
        return getMockEntityDetail(id);
      }
    },
    enabled: !!id && id > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to search topics by name
 * @param name - Topic name to search
 * @returns Query result with topic search response
 */
export function useTopicSearch(name: string) {
  return useQuery({
    queryKey: queryKeys.graph.topicSearch({ name }),
    queryFn: async () => {
      try {
        return await graphApi.searchTopics({ name });
      } catch {
        console.warn('Topic search API unavailable, using mock data');
        return getMockTopicSearchResponse(name);
      }
    },
    enabled: !!name && name.length >= 2,
    staleTime: 2 * 60 * 1000, // 2 minutes
    gcTime: 10 * 60 * 1000, // 10 minutes
  });
}

/**
 * Hook to fetch topic detail by ID
 * @param id - Topic ID
 * @returns Query result with topic detail
 */
export function useTopicDetail(id: number) {
  return useQuery({
    queryKey: queryKeys.graph.topic(id),
    queryFn: async () => {
      try {
        return await graphApi.getTopic(id);
      } catch {
        console.warn('Topic detail API unavailable, using mock data');
        return getMockTopicDetail(id);
      }
    },
    enabled: !!id && id > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to fetch related topics for a topic
 * @param topicId - Topic ID
 * @returns Query result with related topics
 */
export function useRelatedTopics(topicId: number) {
  return useQuery({
    queryKey: queryKeys.graph.topicRelated(topicId),
    queryFn: async () => {
      try {
        return await graphApi.getRelatedTopics(topicId);
      } catch {
        console.warn('Related topics API unavailable, using mock data');
        return getMockRelatedTopicsResponse(topicId);
      }
    },
    enabled: !!topicId && topicId > 0,
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000, // 30 minutes
  });
}

/**
 * Hook to get graph statistics
 * @returns Query result with graph stats
 */
export function useGraphStats() {
  return useQuery({
    queryKey: queryKeys.graph.stats,
    queryFn: async () => {
      try {
        return await graphApi.getStats();
      } catch {
        console.warn('Graph stats API unavailable, using mock data');
        return {
          total_persons: 2935,
          total_places: 1198,
          total_groups: 567,
          total_events: 423,
          total_topics: 156,
          total_relationships: 12847,
        };
      }
    },
    staleTime: 10 * 60 * 1000, // 10 minutes
    gcTime: 60 * 60 * 1000, // 1 hour
  });
}

export default useGraphRelationships;
