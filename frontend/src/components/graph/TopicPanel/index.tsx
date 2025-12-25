/**
 * TopicPanel Component
 *
 * Side panel displaying topic details.
 * Shows topic name, type, description, related verses, and related topics.
 *
 * @example
 * <TopicPanel
 *   topicId={1}
 *   onClose={() => setSelectedTopic(null)}
 *   onTopicClick={(id) => navigate(`/graph/topic/${id}`)}
 *   onVerseClick={(ref) => navigate(`/bible/${ref}`)}
 * />
 */

import { X, Tag, BookOpen, ChevronRight, Lightbulb, Heart, History, Eye } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useTopicDetail, useRelatedTopics } from '@/hooks/api/useGraph';
import { LoadingSpinner, Button } from '@/components/common';
import { TOPIC_TYPE_LABELS, TOPIC_TYPE_COLORS, type TopicType } from '@/types';

// =============================================================================
// Types
// =============================================================================

export interface TopicPanelProps {
  /** Topic ID to display */
  topicId: number;
  /** Close panel handler */
  onClose?: () => void;
  /** Topic click handler (for navigation) */
  onTopicClick?: (topicId: number) => void;
  /** Verse reference click handler */
  onVerseClick?: (reference: string) => void;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// Helper Components
// =============================================================================

/** Topic type icon props */
interface TopicTypeIconProps {
  type: TopicType;
  className?: string;
  style?: React.CSSProperties;
}

/** Topic type icon */
function TopicTypeIcon({ type, className, style }: TopicTypeIconProps) {
  const iconClass = cn('w-5 h-5', className);

  switch (type) {
    case 'DOCTRINE':
      return <Lightbulb className={iconClass} style={style} />;
    case 'MORAL':
      return <Heart className={iconClass} style={style} />;
    case 'HISTORICAL':
      return <History className={iconClass} style={style} />;
    case 'PROPHETIC':
      return <Eye className={iconClass} style={style} />;
    default:
      return <Tag className={iconClass} style={style} />;
  }
}

// =============================================================================
// Component
// =============================================================================

export function TopicPanel({
  topicId,
  onClose,
  onTopicClick,
  onVerseClick,
  className,
}: TopicPanelProps) {
  // Fetch topic detail
  const { data: topic, isLoading, error } = useTopicDetail(topicId);

  // Fetch related topics with weights
  const { data: relatedTopicsData } = useRelatedTopics(topicId);

  // Loading state
  if (isLoading) {
    return (
      <div
        className={cn(
          'bg-white dark:bg-gray-800',
          'border-l border-gray-200 dark:border-gray-700',
          'h-full flex items-center justify-center',
          className
        )}
      >
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  // Error state
  if (error || !topic) {
    return (
      <div
        className={cn(
          'bg-white dark:bg-gray-800',
          'border-l border-gray-200 dark:border-gray-700',
          'h-full p-6',
          className
        )}
      >
        <div className="flex justify-end mb-4">
          {onClose && (
            <button
              onClick={onClose}
              className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
              aria-label="關閉面板"
            >
              <X className="w-5 h-5 text-gray-500 dark:text-gray-400" />
            </button>
          )}
        </div>
        <div className="text-center text-gray-500 dark:text-gray-400">
          <p>無法載入主題資料</p>
          <p className="text-sm mt-1">請稍後再試</p>
        </div>
      </div>
    );
  }

  const typeColor = TOPIC_TYPE_COLORS[topic.type] || '#90A4AE';
  const typeLabel = TOPIC_TYPE_LABELS[topic.type] || '其他';

  return (
    <div
      className={cn(
        'bg-white dark:bg-gray-800',
        'border-l border-gray-200 dark:border-gray-700',
        'h-full flex flex-col overflow-hidden',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center gap-3">
          <div
            className="w-12 h-12 rounded-full flex items-center justify-center"
            style={{ backgroundColor: `${typeColor}20` }}
          >
            <TopicTypeIcon type={topic.type} style={{ color: typeColor }} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              {topic.name}
            </h2>
            <span
              className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium"
              style={{
                backgroundColor: `${typeColor}20`,
                color: typeColor,
              }}
            >
              {typeLabel}
            </span>
          </div>
        </div>
        {onClose && (
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors"
            aria-label="關閉面板"
          >
            <X className="w-5 h-5 text-gray-500 dark:text-gray-400" />
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {/* Description */}
        {topic.description && (
          <section>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
              描述
            </h3>
            <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
              {topic.description}
            </p>
          </section>
        )}

        {/* Stats */}
        <section>
          <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
            統計
          </h3>
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                <BookOpen className="w-4 h-4" />
                <span className="text-sm">相關經文</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                {topic.related_verses_count}
              </p>
            </div>
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                <Tag className="w-4 h-4" />
                <span className="text-sm">相關主題</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                {topic.related_topics?.length ?? 0}
              </p>
            </div>
          </div>
        </section>

        {/* Related Topics with Weights */}
        {relatedTopicsData && relatedTopicsData.related && relatedTopicsData.related.length > 0 && (
          <section>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
              相關主題
            </h3>
            <div className="space-y-2">
              {relatedTopicsData.related.map((relatedTopic) => {
                const relColor = TOPIC_TYPE_COLORS[relatedTopic.type] || '#90A4AE';
                const relLabel = TOPIC_TYPE_LABELS[relatedTopic.type] || '其他';
                const weightPercent = Math.round(relatedTopic.weight * 100);

                return (
                  <button
                    key={relatedTopic.id}
                    onClick={() => onTopicClick?.(relatedTopic.id)}
                    className={cn(
                      'w-full flex items-center justify-between',
                      'p-3 rounded-lg',
                      'bg-gray-50 dark:bg-gray-700/50',
                      'hover:bg-gray-100 dark:hover:bg-gray-700',
                      'transition-colors'
                    )}
                  >
                    <div className="flex items-center gap-3">
                      <div
                        className="w-8 h-8 rounded-full flex items-center justify-center"
                        style={{ backgroundColor: `${relColor}20` }}
                      >
                        <TopicTypeIcon
                          type={relatedTopic.type}
                          className="w-4 h-4"
                          style={{ color: relColor }}
                        />
                      </div>
                      <div className="text-left">
                        <p className="font-medium text-gray-900 dark:text-gray-100">
                          {relatedTopic.name}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-gray-400">
                          {relLabel} | 關聯度 {weightPercent}%
                        </p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-gray-400 dark:text-gray-500">
                        共現 {relatedTopic.co_occurrence} 次
                      </span>
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    </div>
                  </button>
                );
              })}
            </div>
          </section>
        )}

        {/* Basic Related Topics (from topic detail) */}
        {(!relatedTopicsData || !relatedTopicsData.related.length) &&
          topic.related_topics &&
          topic.related_topics.length > 0 && (
            <section>
              <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
                相關主題
              </h3>
              <div className="space-y-2">
                {topic.related_topics.map((relatedTopic) => {
                  const relColor = TOPIC_TYPE_COLORS[relatedTopic.type] || '#90A4AE';
                  const relLabel = TOPIC_TYPE_LABELS[relatedTopic.type] || '其他';

                  return (
                    <button
                      key={relatedTopic.id}
                      onClick={() => onTopicClick?.(relatedTopic.id)}
                      className={cn(
                        'w-full flex items-center justify-between',
                        'p-3 rounded-lg',
                        'bg-gray-50 dark:bg-gray-700/50',
                        'hover:bg-gray-100 dark:hover:bg-gray-700',
                        'transition-colors'
                      )}
                    >
                      <div className="flex items-center gap-3">
                        <div
                          className="w-8 h-8 rounded-full flex items-center justify-center"
                          style={{ backgroundColor: `${relColor}20` }}
                        >
                          <TopicTypeIcon
                            type={relatedTopic.type}
                            className="w-4 h-4"
                            style={{ color: relColor }}
                          />
                        </div>
                        <div className="text-left">
                          <p className="font-medium text-gray-900 dark:text-gray-100">
                            {relatedTopic.name}
                          </p>
                          <p className="text-xs text-gray-500 dark:text-gray-400">
                            {relLabel}
                          </p>
                        </div>
                      </div>
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    </button>
                  );
                })}
              </div>
            </section>
          )}
      </div>

      {/* Footer Actions */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => onVerseClick?.(`topic/${topicId}`)}
        >
          <BookOpen className="w-4 h-4 mr-2" />
          查看相關經文
        </Button>
      </div>
    </div>
  );
}

export default TopicPanel;
