/**
 * Bible RAG - Graph API Endpoints
 *
 * Knowledge graph related API calls.
 */

import apiClient from '../client';
import type {
  CrossReferencesResponse,
  EntityDetail,
  EntitySearchParams,
  EntitySearchResponse,
  GraphHealthResponse,
  GraphRelationshipsParams,
  GraphRelationshipsResponse,
  GraphStatsResponse,
  ParallelsResponse,
  PropheciesResponse,
  RelatedTopicsResponse,
  TopicDetail,
  TopicSearchParams,
  TopicSearchResponse,
  VerseEntitiesResponse,
} from '@/types';

/** Graph API */
export const graphApi = {
  /**
   * Check graph health
   * @returns Graph health response
   */
  getHealth: async (): Promise<GraphHealthResponse> => {
    const response = await apiClient.get<GraphHealthResponse>('/graph/health');
    return response.data;
  },

  /**
   * Get graph statistics
   * @returns Graph stats response
   */
  getStats: async (): Promise<GraphStatsResponse> => {
    const response = await apiClient.get<GraphStatsResponse>('/graph/stats');
    return response.data;
  },

  /**
   * Search entities
   * @param params - Search parameters
   * @returns Entity search response
   */
  searchEntities: async (
    params: EntitySearchParams
  ): Promise<EntitySearchResponse> => {
    const response = await apiClient.get<EntitySearchResponse>(
      '/graph/entities/search',
      { params }
    );
    return response.data;
  },

  /**
   * Get entity by ID
   * @param entityId - Entity ID
   * @returns Entity detail
   */
  getEntity: async (entityId: number): Promise<EntityDetail> => {
    const response = await apiClient.get<EntityDetail>(
      `/graph/entities/${entityId}`
    );
    return response.data;
  },

  /**
   * Search topics
   * @param params - Search parameters
   * @returns Topic search response
   */
  searchTopics: async (
    params: TopicSearchParams
  ): Promise<TopicSearchResponse> => {
    const response = await apiClient.get<TopicSearchResponse>(
      '/graph/topics/search',
      { params }
    );
    return response.data;
  },

  /**
   * Get topic by ID
   * @param topicId - Topic ID
   * @returns Topic detail
   */
  getTopic: async (topicId: number): Promise<TopicDetail> => {
    const response = await apiClient.get<TopicDetail>(
      `/graph/topics/${topicId}`
    );
    return response.data;
  },

  /**
   * Get related topics
   * @param topicId - Topic ID
   * @returns Related topics response
   */
  getRelatedTopics: async (topicId: number): Promise<RelatedTopicsResponse> => {
    const response = await apiClient.get<RelatedTopicsResponse>(
      `/graph/topics/${topicId}/related`
    );
    return response.data;
  },

  /**
   * Get graph relationships
   * @param params - Relationship parameters
   * @returns Graph relationships response
   */
  getRelationships: async (
    params: GraphRelationshipsParams
  ): Promise<GraphRelationshipsResponse> => {
    const response = await apiClient.get<GraphRelationshipsResponse>(
      '/graph/relationships',
      { params }
    );
    return response.data;
  },

  /**
   * Get verse entities
   * @param verseId - Verse ID
   * @returns Verse entities response
   */
  getVerseEntities: async (verseId: number): Promise<VerseEntitiesResponse> => {
    const response = await apiClient.get<VerseEntitiesResponse>(
      `/graph/verses/${verseId}/entities`
    );
    return response.data;
  },

  /**
   * Get verse cross references
   * @param verseId - Verse ID
   * @returns Cross references response
   */
  getCrossReferences: async (
    verseId: number
  ): Promise<CrossReferencesResponse> => {
    const response = await apiClient.get<CrossReferencesResponse>(
      `/graph/verses/${verseId}/cross-references`
    );
    return response.data;
  },

  /**
   * Get verse prophecies
   * @param verseId - Verse ID
   * @returns Prophecies response
   */
  getProphecies: async (verseId: number): Promise<PropheciesResponse> => {
    const response = await apiClient.get<PropheciesResponse>(
      `/graph/verses/${verseId}/prophecies`
    );
    return response.data;
  },

  /**
   * Get pericope parallels
   * @param pericopeId - Pericope ID
   * @returns Parallels response
   */
  getParallels: async (pericopeId: number): Promise<ParallelsResponse> => {
    const response = await apiClient.get<ParallelsResponse>(
      `/graph/pericopes/${pericopeId}/parallels`
    );
    return response.data;
  },
};
