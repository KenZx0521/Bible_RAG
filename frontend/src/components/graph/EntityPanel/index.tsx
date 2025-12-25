/**
 * EntityPanel Component
 *
 * Side panel displaying entity details.
 * Shows entity name, type, description, related verses, and related entities.
 *
 * @example
 * <EntityPanel
 *   entityId={1}
 *   onClose={() => setSelectedEntity(null)}
 *   onEntityClick={(id) => navigate(`/graph/entity/${id}`)}
 *   onVerseClick={(ref) => navigate(`/bible/${ref}`)}
 * />
 */

import { X, User, MapPin, Users, Calendar, BookOpen, ChevronRight } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useEntityDetail, useGraphRelationships } from '@/hooks/api/useGraph';
import { LoadingSpinner, Button } from '@/components/common';
import { ENTITY_TYPE_LABELS, ENTITY_TYPE_COLORS, type EntityType } from '@/types';

// =============================================================================
// Types
// =============================================================================

export interface EntityPanelProps {
  /** Entity ID to display */
  entityId: number;
  /** Close panel handler */
  onClose?: () => void;
  /** Entity click handler (for navigation) */
  onEntityClick?: (entityId: number) => void;
  /** Verse reference click handler */
  onVerseClick?: (reference: string) => void;
  /** Additional class name */
  className?: string;
}

// =============================================================================
// Helper Components
// =============================================================================

/** Entity type icon props */
interface EntityTypeIconProps {
  type: EntityType;
  className?: string;
  style?: React.CSSProperties;
}

/** Entity type icon */
function EntityTypeIcon({ type, className, style }: EntityTypeIconProps) {
  const iconClass = cn('w-5 h-5', className);

  switch (type) {
    case 'PERSON':
      return <User className={iconClass} style={style} />;
    case 'PLACE':
      return <MapPin className={iconClass} style={style} />;
    case 'GROUP':
      return <Users className={iconClass} style={style} />;
    case 'EVENT':
      return <Calendar className={iconClass} style={style} />;
    default:
      return <User className={iconClass} style={style} />;
  }
}

// =============================================================================
// Component
// =============================================================================

export function EntityPanel({
  entityId,
  onClose,
  onEntityClick,
  onVerseClick,
  className,
}: EntityPanelProps) {
  // Fetch entity detail
  const { data: entity, isLoading, error } = useEntityDetail(entityId);

  // Fetch relationships for context
  const { data: relationships } = useGraphRelationships({
    entity_id: entityId,
    entity_type: entity?.type ?? 'PERSON',
    depth: 1,
  });

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
  if (error || !entity) {
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
          <p>無法載入實體資料</p>
          <p className="text-sm mt-1">請稍後再試</p>
        </div>
      </div>
    );
  }

  const typeColor = ENTITY_TYPE_COLORS[entity.type] || '#90A4AE';
  const typeLabel = ENTITY_TYPE_LABELS[entity.type] || '未知';

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
            <EntityTypeIcon type={entity.type} style={{ color: typeColor }} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-900 dark:text-gray-100">
              {entity.name}
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
        {entity.description && (
          <section>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
              描述
            </h3>
            <p className="text-gray-700 dark:text-gray-300 leading-relaxed">
              {entity.description}
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
                {entity.related_verses_count}
              </p>
            </div>
            <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-3">
              <div className="flex items-center gap-2 text-gray-600 dark:text-gray-300">
                <Users className="w-4 h-4" />
                <span className="text-sm">相關實體</span>
              </div>
              <p className="text-2xl font-bold text-gray-900 dark:text-gray-100 mt-1">
                {entity.related_entities?.length ?? 0}
              </p>
            </div>
          </div>
        </section>

        {/* Related Entities */}
        {entity.related_entities && entity.related_entities.length > 0 && (
          <section>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
              相關實體
            </h3>
            <div className="space-y-2">
              {entity.related_entities.map((relatedEntity) => {
                const relColor = ENTITY_TYPE_COLORS[relatedEntity.type] || '#90A4AE';
                const relLabel = ENTITY_TYPE_LABELS[relatedEntity.type] || '未知';

                return (
                  <button
                    key={relatedEntity.id}
                    onClick={() => onEntityClick?.(relatedEntity.id)}
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
                        <EntityTypeIcon
                          type={relatedEntity.type}
                          className="w-4 h-4"
                          style={{ color: relColor }}
                        />
                      </div>
                      <div className="text-left">
                        <p className="font-medium text-gray-900 dark:text-gray-100">
                          {relatedEntity.name}
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

        {/* Relationship Summary */}
        {relationships && relationships.edges && relationships.edges.length > 0 && (
          <section>
            <h3 className="text-sm font-medium text-gray-500 dark:text-gray-400 mb-2">
              關係類型
            </h3>
            <div className="flex flex-wrap gap-2">
              {Array.from(new Set(relationships.edges.map((e) => e.type))).map((relType) => (
                <span
                  key={relType}
                  className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300"
                >
                  {relType.replace(/_/g, ' ')}
                </span>
              ))}
            </div>
          </section>
        )}
      </div>

      {/* Footer Actions */}
      <div className="p-4 border-t border-gray-200 dark:border-gray-700">
        <Button
          variant="secondary"
          className="w-full"
          onClick={() => onVerseClick?.(`entity/${entityId}`)}
        >
          <BookOpen className="w-4 h-4 mr-2" />
          查看相關經文
        </Button>
      </div>
    </div>
  );
}

export default EntityPanel;
