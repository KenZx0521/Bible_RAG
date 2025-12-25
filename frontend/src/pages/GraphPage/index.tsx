/**
 * GraphPage Component
 *
 * Knowledge graph visualization page.
 * Displays relationships between biblical entities and topics.
 *
 * Features:
 * - Search for entities and topics
 * - D3.js force-directed graph visualization
 * - Side panel for entity/topic details
 * - Responsive layout (desktop: side panel, mobile: bottom panel)
 * - URL synchronization
 *
 * Routes:
 * - /graph -> Graph home (shows popular topics)
 * - /graph/entity/:id -> Entity detail
 * - /graph/topic/:id -> Topic detail
 *
 * @example
 * // In router:
 * { path: '/graph', element: <GraphPage /> }
 * { path: '/graph/entity/:id', element: <GraphPage /> }
 * { path: '/graph/topic/:id', element: <GraphPage /> }
 */

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useParams, useLocation, useNavigate } from 'react-router-dom';
import { Search, X, User, Tag } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Breadcrumb, LoadingSpinner, Card } from '@/components/common';
import { GraphViewer, EntityPanel, TopicPanel } from '@/components/graph';
import {
  useEntitySearch,
  useTopicSearch,
  useGraphRelationships,
  useEntityDetail,
  useTopicDetail,
  useGraphStats,
} from '@/hooks/api';
import type { GraphNode, EntityType } from '@/types';
import { ENTITY_TYPE_COLORS, ENTITY_TYPE_LABELS, TOPIC_TYPE_COLORS, TOPIC_TYPE_LABELS } from '@/types';

// =============================================================================
// Types
// =============================================================================

type SearchResultType = 'entity' | 'topic';

interface SearchResult {
  type: SearchResultType;
  id: number;
  name: string;
  subtype: string;
  color: string;
}

// =============================================================================
// Constants
// =============================================================================

/** Popular topics for initial display */
const POPULAR_TOPICS = [
  { id: 1, name: '救贖', type: 'DOCTRINE' as const },
  { id: 2, name: '信心', type: 'MORAL' as const },
  { id: 3, name: '愛', type: 'MORAL' as const },
  { id: 4, name: '創造', type: 'DOCTRINE' as const },
  { id: 5, name: '末世', type: 'PROPHETIC' as const },
];

/** Popular entities for initial display */
const POPULAR_ENTITIES = [
  { id: 1, name: '摩西', type: 'PERSON' as EntityType },
  { id: 2, name: '大衛', type: 'PERSON' as EntityType },
  { id: 3, name: '耶穌', type: 'PERSON' as EntityType },
  { id: 4, name: '耶路撒冷', type: 'PLACE' as EntityType },
  { id: 5, name: '以色列', type: 'GROUP' as EntityType },
];

// =============================================================================
// Component
// =============================================================================

export function GraphPage() {
  const { id } = useParams<{ id?: string }>();
  const location = useLocation();
  const navigate = useNavigate();

  // Determine the type from the URL path
  const isEntityView = location.pathname.includes('/entity/');
  const isTopicView = location.pathname.includes('/topic/');
  const entityId = isEntityView && id ? parseInt(id, 10) : null;
  const topicId = isTopicView && id ? parseInt(id, 10) : null;

  // State
  const [searchQuery, setSearchQuery] = useState('');
  const [isSearchFocused, setIsSearchFocused] = useState(false);
  const [showMobilePanel, setShowMobilePanel] = useState(false);

  // Fetch data
  const { data: entitySearchResults, isLoading: isSearchingEntities } = useEntitySearch(searchQuery);
  const { data: topicSearchResults, isLoading: isSearchingTopics } = useTopicSearch(searchQuery);
  const { data: graphStats } = useGraphStats();

  // Get entity/topic details for graph center
  const { data: entityDetail } = useEntityDetail(entityId ?? 0);
  const { data: topicDetail } = useTopicDetail(topicId ?? 0);

  // Get relationships for the graph
  const relationshipsParams = useMemo(() => {
    if (entityId && entityDetail) {
      return { entity_id: entityId, entity_type: entityDetail.type, depth: 2 };
    }
    if (topicId) {
      return { entity_id: topicId, entity_type: 'TOPIC' as const, depth: 2 };
    }
    // Default to Moses if no selection
    return { entity_id: 1, entity_type: 'PERSON' as const, depth: 2 };
  }, [entityId, topicId, entityDetail]);

  const { data: relationships, isLoading: isLoadingGraph } = useGraphRelationships(relationshipsParams);

  // Combine search results
  const searchResults = useMemo<SearchResult[]>(() => {
    const results: SearchResult[] = [];

    if (entitySearchResults?.entities) {
      entitySearchResults.entities.forEach((entity) => {
        results.push({
          type: 'entity',
          id: entity.id,
          name: entity.name,
          subtype: ENTITY_TYPE_LABELS[entity.type] || entity.type,
          color: ENTITY_TYPE_COLORS[entity.type] || '#90A4AE',
        });
      });
    }

    if (topicSearchResults?.topics) {
      topicSearchResults.topics.forEach((topic) => {
        results.push({
          type: 'topic',
          id: topic.id,
          name: topic.name,
          subtype: TOPIC_TYPE_LABELS[topic.type] || topic.type,
          color: TOPIC_TYPE_COLORS[topic.type] || '#90A4AE',
        });
      });
    }

    return results;
  }, [entitySearchResults, topicSearchResults]);

  const isSearching = isSearchingEntities || isSearchingTopics;
  const showSearchResults = isSearchFocused && searchQuery.length >= 2;

  // Handlers
  const handleSearchResultClick = useCallback(
    (result: SearchResult) => {
      setSearchQuery('');
      setIsSearchFocused(false);
      if (result.type === 'entity') {
        navigate(`/graph/entity/${result.id}`);
      } else {
        navigate(`/graph/topic/${result.id}`);
      }
    },
    [navigate]
  );

  const handleNodeClick = useCallback(
    (node: GraphNode) => {
      const [type, idStr] = node.id.split('_');
      const nodeId = parseInt(idStr, 10);

      if (type === 'topic') {
        navigate(`/graph/topic/${nodeId}`);
      } else {
        navigate(`/graph/entity/${nodeId}`);
      }
    },
    [navigate]
  );

  const handleEntityClick = useCallback(
    (newEntityId: number) => {
      navigate(`/graph/entity/${newEntityId}`);
    },
    [navigate]
  );

  const handleTopicClick = useCallback(
    (newTopicId: number) => {
      navigate(`/graph/topic/${newTopicId}`);
    },
    [navigate]
  );

  const handleClosePanel = useCallback(() => {
    setShowMobilePanel(false);
    navigate('/graph');
  }, [navigate]);

  const handleQuickSelect = useCallback(
    (type: 'entity' | 'topic', itemId: number) => {
      if (type === 'entity') {
        navigate(`/graph/entity/${itemId}`);
      } else {
        navigate(`/graph/topic/${itemId}`);
      }
    },
    [navigate]
  );

  // Initialize mobile panel state based on URL
  const initialMobilePanelState = !!(entityId || topicId);

  // Update mobile panel when selection changes
  useEffect(() => {
    setShowMobilePanel(initialMobilePanelState);
  }, [initialMobilePanelState]);

  // Build breadcrumb items
  const breadcrumbItems = useMemo(() => {
    const items = [
      { label: '首頁', href: '/' },
      { label: '知識圖譜', href: '/graph' },
    ];

    if (isEntityView && entityDetail) {
      items.push({
        label: entityDetail.name,
        href: `/graph/entity/${entityId}`,
      });
    } else if (isTopicView && topicDetail) {
      items.push({
        label: topicDetail.name,
        href: `/graph/topic/${topicId}`,
      });
    }

    return items;
  }, [isEntityView, isTopicView, entityId, topicId, entityDetail, topicDetail]);

  // Get center node ID for graph
  const centerNodeId = useMemo(() => {
    if (entityId && entityDetail) {
      return `${entityDetail.type.toLowerCase()}_${entityId}`;
    }
    if (topicId) {
      return `topic_${topicId}`;
    }
    return 'person_1'; // Default to Moses
  }, [entityId, topicId, entityDetail]);

  // Determine if we have a selection
  const hasSelection = !!(entityId || topicId);

  return (
    <div className="h-[calc(100vh-8rem)] flex flex-col">
      {/* Header */}
      <div className="flex-shrink-0 space-y-4 mb-4">
        <Breadcrumb items={breadcrumbItems} />

        {/* Search Bar */}
        <div className="relative">
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onFocus={() => setIsSearchFocused(true)}
              onBlur={() => setTimeout(() => setIsSearchFocused(false), 200)}
              placeholder="搜尋人物、地點、事件或主題..."
              className={cn(
                'w-full pl-10 pr-10 py-3 rounded-lg',
                'bg-white dark:bg-gray-800',
                'border border-gray-200 dark:border-gray-700',
                'text-gray-900 dark:text-gray-100',
                'placeholder-gray-400 dark:placeholder-gray-500',
                'focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent'
              )}
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-gray-100 dark:hover:bg-gray-700"
              >
                <X className="w-4 h-4 text-gray-400" />
              </button>
            )}
          </div>

          {/* Search Results Dropdown */}
          {showSearchResults && (
            <div
              className={cn(
                'absolute top-full left-0 right-0 mt-2 z-50',
                'bg-white dark:bg-gray-800',
                'border border-gray-200 dark:border-gray-700',
                'rounded-lg shadow-lg',
                'max-h-80 overflow-y-auto'
              )}
            >
              {isSearching ? (
                <div className="p-4 text-center">
                  <LoadingSpinner size="sm" />
                  <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">搜尋中...</p>
                </div>
              ) : searchResults.length > 0 ? (
                <div className="py-2">
                  {searchResults.map((result) => (
                    <button
                      key={`${result.type}-${result.id}`}
                      onClick={() => handleSearchResultClick(result)}
                      className={cn(
                        'w-full flex items-center gap-3 px-4 py-2',
                        'hover:bg-gray-50 dark:hover:bg-gray-700',
                        'transition-colors'
                      )}
                    >
                      <span
                        className="w-3 h-3 rounded-full flex-shrink-0"
                        style={{ backgroundColor: result.color }}
                      />
                      <span className="flex-1 text-left">
                        <span className="text-gray-900 dark:text-gray-100">{result.name}</span>
                        <span className="text-sm text-gray-500 dark:text-gray-400 ml-2">
                          {result.subtype}
                        </span>
                      </span>
                      {result.type === 'topic' && (
                        <Tag className="w-4 h-4 text-gray-400" />
                      )}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="p-4 text-center text-gray-500 dark:text-gray-400">
                  找不到符合的結果
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex flex-col lg:flex-row gap-4 min-h-0">
        {/* Graph Area */}
        <div className="flex-1 min-h-0">
          {isLoadingGraph ? (
            <div className="h-full flex items-center justify-center bg-gray-50 dark:bg-gray-900/50 rounded-lg">
              <div className="text-center">
                <LoadingSpinner size="lg" />
                <p className="text-gray-500 dark:text-gray-400 mt-4">載入圖譜中...</p>
              </div>
            </div>
          ) : (
            <GraphViewer
              nodes={relationships?.nodes ?? []}
              edges={relationships?.edges ?? []}
              centerNodeId={centerNodeId}
              onNodeClick={handleNodeClick}
              height={hasSelection ? 500 : 600}
              className="h-full"
            />
          )}
        </div>

        {/* Desktop Side Panel */}
        {hasSelection && (
          <div className="hidden lg:block w-80 flex-shrink-0">
            {entityId ? (
              <EntityPanel
                entityId={entityId}
                onClose={handleClosePanel}
                onEntityClick={handleEntityClick}
                onVerseClick={(ref) => navigate(`/bible/${ref}`)}
                className="h-full rounded-lg"
              />
            ) : topicId ? (
              <TopicPanel
                topicId={topicId}
                onClose={handleClosePanel}
                onTopicClick={handleTopicClick}
                onVerseClick={(ref) => navigate(`/bible/${ref}`)}
                className="h-full rounded-lg"
              />
            ) : null}
          </div>
        )}

        {/* Mobile Bottom Panel */}
        {hasSelection && showMobilePanel && (
          <div
            className={cn(
              'lg:hidden fixed inset-x-0 bottom-0 z-40',
              'bg-white dark:bg-gray-800',
              'border-t border-gray-200 dark:border-gray-700',
              'rounded-t-2xl shadow-2xl',
              'max-h-[60vh] overflow-hidden',
              'animate-slide-up'
            )}
          >
            {/* Handle */}
            <div className="flex justify-center py-2">
              <div className="w-12 h-1.5 bg-gray-300 dark:bg-gray-600 rounded-full" />
            </div>

            {/* Panel Content */}
            <div className="overflow-y-auto max-h-[calc(60vh-2rem)]">
              {entityId ? (
                <EntityPanel
                  entityId={entityId}
                  onClose={() => {
                    setShowMobilePanel(false);
                    handleClosePanel();
                  }}
                  onEntityClick={handleEntityClick}
                  onVerseClick={(ref) => navigate(`/bible/${ref}`)}
                />
              ) : topicId ? (
                <TopicPanel
                  topicId={topicId}
                  onClose={() => {
                    setShowMobilePanel(false);
                    handleClosePanel();
                  }}
                  onTopicClick={handleTopicClick}
                  onVerseClick={(ref) => navigate(`/bible/${ref}`)}
                />
              ) : null}
            </div>
          </div>
        )}
      </div>

      {/* Quick Access (when no selection) */}
      {!hasSelection && (
        <div className="flex-shrink-0 mt-4 space-y-4">
          {/* Stats */}
          {graphStats && (
            <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
              {[
                { label: '人物', value: graphStats.total_persons, color: ENTITY_TYPE_COLORS.PERSON },
                { label: '地點', value: graphStats.total_places, color: ENTITY_TYPE_COLORS.PLACE },
                { label: '群體', value: graphStats.total_groups, color: ENTITY_TYPE_COLORS.GROUP },
                { label: '事件', value: graphStats.total_events, color: ENTITY_TYPE_COLORS.EVENT },
                { label: '主題', value: graphStats.total_topics, color: '#81C784' },
                { label: '關係', value: graphStats.total_relationships, color: '#90A4AE' },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className="bg-white dark:bg-gray-800 rounded-lg p-3 text-center border border-gray-200 dark:border-gray-700"
                >
                  <p
                    className="text-xl font-bold"
                    style={{ color: stat.color }}
                  >
                    {stat.value.toLocaleString()}
                  </p>
                  <p className="text-xs text-gray-500 dark:text-gray-400">{stat.label}</p>
                </div>
              ))}
            </div>
          )}

          {/* Quick Access Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Popular Entities */}
            <Card padding="md">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
                <User className="w-5 h-5" style={{ color: ENTITY_TYPE_COLORS.PERSON }} />
                熱門人物
              </h3>
              <div className="flex flex-wrap gap-2">
                {POPULAR_ENTITIES.map((entity) => (
                  <button
                    key={entity.id}
                    onClick={() => handleQuickSelect('entity', entity.id)}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                      'bg-gray-100 dark:bg-gray-700',
                      'hover:bg-gray-200 dark:hover:bg-gray-600',
                      'text-gray-700 dark:text-gray-300',
                      'text-sm transition-colors'
                    )}
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: ENTITY_TYPE_COLORS[entity.type] }}
                    />
                    {entity.name}
                  </button>
                ))}
              </div>
            </Card>

            {/* Popular Topics */}
            <Card padding="md">
              <h3 className="font-semibold text-gray-900 dark:text-gray-100 mb-3 flex items-center gap-2">
                <Tag className="w-5 h-5" style={{ color: '#81C784' }} />
                熱門主題
              </h3>
              <div className="flex flex-wrap gap-2">
                {POPULAR_TOPICS.map((topic) => (
                  <button
                    key={topic.id}
                    onClick={() => handleQuickSelect('topic', topic.id)}
                    className={cn(
                      'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full',
                      'bg-gray-100 dark:bg-gray-700',
                      'hover:bg-gray-200 dark:hover:bg-gray-600',
                      'text-gray-700 dark:text-gray-300',
                      'text-sm transition-colors'
                    )}
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: TOPIC_TYPE_COLORS[topic.type] }}
                    />
                    {topic.name}
                  </button>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* Backdrop for mobile panel */}
      {hasSelection && showMobilePanel && (
        <div
          className="lg:hidden fixed inset-0 bg-black/50 z-30"
          onClick={() => setShowMobilePanel(false)}
        />
      )}

      {/* Custom styles for animation */}
      <style>{`
        @keyframes slide-up {
          from {
            transform: translateY(100%);
          }
          to {
            transform: translateY(0);
          }
        }
        .animate-slide-up {
          animation: slide-up 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}

export default GraphPage;
