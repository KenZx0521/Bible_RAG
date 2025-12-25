/**
 * SegmentCard Component
 *
 * Displays a pericope segment from RAG query results.
 * Shows title, reference, excerpt, and relevance score.
 *
 * @example
 * <SegmentCard
 *   segment={segment}
 *   onClick={() => navigate(`/pericope/${segment.id}`)}
 * />
 */

import { useNavigate } from 'react-router-dom';
import { BookOpen } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card } from '@/components/common';
import type { PericopeSegment } from '@/types';

export interface SegmentCardProps {
  /** Pericope segment data */
  segment: PericopeSegment;
}

/**
 * Format scripture reference
 * e.g., "Genesis 1:1-31" or "Genesis 1:1 - 2:3"
 */
function formatReference(segment: PericopeSegment): string {
  const { book, chapter_start, verse_start, chapter_end, verse_end } = segment;

  if (chapter_start === chapter_end) {
    if (verse_start === verse_end) {
      return `${book} ${chapter_start}:${verse_start}`;
    }
    return `${book} ${chapter_start}:${verse_start}-${verse_end}`;
  }

  return `${book} ${chapter_start}:${verse_start} - ${chapter_end}:${verse_end}`;
}

/**
 * Get score color based on relevance
 * >= 0.8: green, >= 0.6: blue, < 0.6: gray
 */
function getScoreColor(score: number): string {
  if (score >= 0.8) {
    return 'text-green-600 dark:text-green-400 bg-green-100 dark:bg-green-900/30';
  }
  if (score >= 0.6) {
    return 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30';
  }
  return 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800';
}

export function SegmentCard({ segment }: SegmentCardProps) {
  const navigate = useNavigate();

  const reference = formatReference(segment);
  const scorePercent = Math.round(segment.relevance_score * 100);
  const scoreColor = getScoreColor(segment.relevance_score);

  const handleClick = () => {
    navigate(`/pericope/${segment.id}`);
  };

  return (
    <Card
      variant="scripture"
      padding="lg"
      onClick={handleClick}
      className={cn(
        'group',
        'transition-all duration-200',
        'hover:shadow-md hover:border-bible-gold/50'
      )}
    >
      {/* Header: Title and Score */}
      <div className="flex items-start justify-between gap-4 mb-3">
        <h3
          className={cn(
            'font-semibold text-gray-900 dark:text-gray-100',
            'group-hover:text-primary-600 dark:group-hover:text-primary-400',
            'transition-colors duration-200'
          )}
        >
          {segment.title}
        </h3>

        {/* Relevance Score Badge */}
        <span
          className={cn(
            'shrink-0 px-2.5 py-1 rounded-full',
            'text-xs font-semibold',
            scoreColor
          )}
          title={`相關度: ${scorePercent}%`}
        >
          {scorePercent}%
        </span>
      </div>

      {/* Reference */}
      <div className="flex items-center gap-2 mb-3 text-sm text-gray-600 dark:text-gray-400">
        <BookOpen className="w-4 h-4" aria-hidden="true" />
        <span className="font-medium">{reference}</span>
      </div>

      {/* Text Excerpt */}
      <p
        className={cn(
          'text-sm text-gray-700 dark:text-gray-300',
          'line-clamp-3',
          'font-serif leading-relaxed'
        )}
      >
        {segment.text_excerpt}
      </p>

      {/* Accessibility */}
      <span className="sr-only">
        點擊查看 {segment.title} 的完整內容，相關度 {scorePercent}%
      </span>
    </Card>
  );
}

export default SegmentCard;
