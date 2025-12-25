/**
 * QueryResult Component
 *
 * Displays the complete RAG query result including:
 * - AI-generated answer (Markdown)
 * - Related scripture segments
 * - Knowledge graph context (if available)
 * - Query metadata
 *
 * @example
 * <QueryResult result={queryResponse} />
 */

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  BookOpen,
  Brain,
  Clock,
  Cpu,
  Tag,
  User,
  Sparkles,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Card } from '@/components/common';
import { SegmentCard } from '../SegmentCard';
import type { QueryResponse } from '@/types';
import { QUERY_TYPE_LABELS } from '@/types';

export interface QueryResultProps {
  /** Query response data */
  result: QueryResponse;
}

export function QueryResult({ result }: QueryResultProps) {
  const { answer, segments, meta, graph_context } = result;

  const hasGraphContext =
    graph_context &&
    ((graph_context.related_topics && graph_context.related_topics.length > 0) ||
      (graph_context.related_persons && graph_context.related_persons.length > 0));

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Answer Section */}
      <Card padding="lg" className="overflow-hidden">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles
            className="w-5 h-5 text-primary-600 dark:text-primary-400"
            aria-hidden="true"
          />
          <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
            AI 回答
          </h2>
        </div>

        <div
          className={cn(
            'prose prose-sm sm:prose-base max-w-none',
            'prose-headings:text-gray-900 dark:prose-headings:text-gray-100',
            'prose-p:text-gray-700 dark:prose-p:text-gray-300',
            'prose-a:text-primary-600 dark:prose-a:text-primary-400',
            'prose-strong:text-gray-900 dark:prose-strong:text-gray-100',
            'prose-code:text-primary-600 dark:prose-code:text-primary-400',
            'prose-code:bg-gray-100 dark:prose-code:bg-gray-800',
            'prose-code:px-1 prose-code:py-0.5 prose-code:rounded',
            'prose-blockquote:border-l-primary-500',
            'prose-blockquote:text-gray-600 dark:prose-blockquote:text-gray-400',
            'prose-ul:text-gray-700 dark:prose-ul:text-gray-300',
            'prose-ol:text-gray-700 dark:prose-ol:text-gray-300',
            'prose-li:marker:text-primary-500'
          )}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{answer}</ReactMarkdown>
        </div>
      </Card>

      {/* Related Scripture Section */}
      {segments.length > 0 && (
        <section aria-labelledby="related-scriptures-heading">
          <div className="flex items-center gap-2 mb-4">
            <BookOpen
              className="w-5 h-5 text-bible-gold"
              aria-hidden="true"
            />
            <h2
              id="related-scriptures-heading"
              className="text-lg font-semibold text-gray-900 dark:text-gray-100"
            >
              相關經文 ({segments.length})
            </h2>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {segments.map((segment) => (
              <SegmentCard key={segment.id} segment={segment} />
            ))}
          </div>
        </section>
      )}

      {/* Graph Context Section */}
      {hasGraphContext && (
        <Card padding="lg">
          <div className="flex items-center gap-2 mb-4">
            <Brain
              className="w-5 h-5 text-purple-600 dark:text-purple-400"
              aria-hidden="true"
            />
            <h2 className="text-lg font-semibold text-gray-900 dark:text-gray-100">
              知識圖譜上下文
            </h2>
          </div>

          <div className="space-y-4">
            {/* Related Topics */}
            {graph_context.related_topics &&
              graph_context.related_topics.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Tag
                      className="w-4 h-4 text-gray-500"
                      aria-hidden="true"
                    />
                    <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      相關主題
                    </h3>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {graph_context.related_topics.map((topic, index) => (
                      <span
                        key={`topic-${index}`}
                        className={cn(
                          'inline-flex items-center',
                          'px-3 py-1 rounded-full',
                          'text-sm font-medium',
                          'bg-purple-100 dark:bg-purple-900/30',
                          'text-purple-700 dark:text-purple-300',
                          'transition-colors duration-200',
                          'hover:bg-purple-200 dark:hover:bg-purple-800/40'
                        )}
                      >
                        {topic}
                      </span>
                    ))}
                  </div>
                </div>
              )}

            {/* Related Persons */}
            {graph_context.related_persons &&
              graph_context.related_persons.length > 0 && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <User
                      className="w-4 h-4 text-gray-500"
                      aria-hidden="true"
                    />
                    <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">
                      相關人物
                    </h3>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {graph_context.related_persons.map((person, index) => (
                      <span
                        key={`person-${index}`}
                        className={cn(
                          'inline-flex items-center',
                          'px-3 py-1 rounded-full',
                          'text-sm font-medium',
                          'bg-rose-100 dark:bg-rose-900/30',
                          'text-rose-700 dark:text-rose-300',
                          'transition-colors duration-200',
                          'hover:bg-rose-200 dark:hover:bg-rose-800/40'
                        )}
                      >
                        {person}
                      </span>
                    ))}
                  </div>
                </div>
              )}
          </div>
        </Card>
      )}

      {/* Metadata Section */}
      <Card padding="md" className="bg-gray-50 dark:bg-gray-800/50">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm text-gray-500 dark:text-gray-400">
          {/* Query Type */}
          <div className="flex items-center gap-1.5">
            <Tag className="w-4 h-4" aria-hidden="true" />
            <span>
              類型:{' '}
              <span className="font-medium text-gray-700 dark:text-gray-300">
                {QUERY_TYPE_LABELS[meta.query_type] || meta.query_type}
              </span>
            </span>
          </div>

          {/* Processing Time */}
          <div className="flex items-center gap-1.5">
            <Clock className="w-4 h-4" aria-hidden="true" />
            <span>
              處理時間:{' '}
              <span className="font-medium text-gray-700 dark:text-gray-300">
                {(meta.total_processing_time_ms / 1000).toFixed(2)}s
              </span>
            </span>
          </div>

          {/* LLM Model */}
          <div className="flex items-center gap-1.5">
            <Cpu className="w-4 h-4" aria-hidden="true" />
            <span>
              模型:{' '}
              <span className="font-medium text-gray-700 dark:text-gray-300">
                {meta.llm_model}
              </span>
            </span>
          </div>
        </div>
      </Card>
    </div>
  );
}

export default QueryResult;
