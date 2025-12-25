/**
 * Bible RAG - Enums and Constants
 */

// =============================================================================
// Testament - Old/New Testament
// =============================================================================

/** Testament type */
export type Testament = 'OT' | 'NT';

/** Testament labels */
export const TESTAMENT_LABELS: Record<Testament, string> = {
  OT: '舊約',
  NT: '新約',
};

/** Testament book counts */
export const TESTAMENT_BOOK_COUNTS: Record<Testament, number> = {
  OT: 39,
  NT: 27,
};

// =============================================================================
// EntityType - Entity Types
// =============================================================================

/** Entity type */
export type EntityType = 'PERSON' | 'PLACE' | 'GROUP' | 'EVENT';

/** Entity type labels */
export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  PERSON: '人物',
  PLACE: '地點',
  GROUP: '群體',
  EVENT: '事件',
};

/** Entity type colors */
export const ENTITY_TYPE_COLORS: Record<EntityType, string> = {
  PERSON: '#E57373',
  PLACE: '#64B5F6',
  GROUP: '#BA68C8',
  EVENT: '#FFB74D',
};

// =============================================================================
// TopicType - Topic Types
// =============================================================================

/** Topic type */
export type TopicType = 'DOCTRINE' | 'MORAL' | 'HISTORICAL' | 'PROPHETIC' | 'OTHER';

/** Topic type labels */
export const TOPIC_TYPE_LABELS: Record<TopicType, string> = {
  DOCTRINE: '教義',
  MORAL: '道德',
  HISTORICAL: '歷史',
  PROPHETIC: '預言',
  OTHER: '其他',
};

/** Topic type colors */
export const TOPIC_TYPE_COLORS: Record<TopicType, string> = {
  DOCTRINE: '#81C784',
  MORAL: '#4FC3F7',
  HISTORICAL: '#FFD54F',
  PROPHETIC: '#7986CB',
  OTHER: '#90A4AE',
};

// =============================================================================
// QueryMode - Query Modes (User Selection)
// =============================================================================

/** Query mode (user selection) */
export type QueryMode = 'auto' | 'verse' | 'topic' | 'person' | 'event';

/** Query mode options */
export const QUERY_MODE_OPTIONS: Array<{
  value: QueryMode;
  label: string;
  description: string;
}> = [
  { value: 'auto', label: '自動', description: '自動判斷查詢類型' },
  { value: 'verse', label: '經文', description: '查找特定經文' },
  { value: 'topic', label: '主題', description: '探索聖經主題' },
  { value: 'person', label: '人物', description: '了解聖經人物' },
  { value: 'event', label: '事件', description: '查詢聖經事件' },
];

// =============================================================================
// QueryType - Query Types (System Detection)
// =============================================================================

/** Query type (system detection) */
export type QueryType =
  | 'VERSE_LOOKUP'
  | 'TOPIC_QUESTION'
  | 'PERSON_QUESTION'
  | 'EVENT_QUESTION'
  | 'GENERAL_BIBLE_QUESTION';

/** Query type labels */
export const QUERY_TYPE_LABELS: Record<QueryType, string> = {
  VERSE_LOOKUP: '經文查找',
  TOPIC_QUESTION: '主題問題',
  PERSON_QUESTION: '人物問題',
  EVENT_QUESTION: '事件問題',
  GENERAL_BIBLE_QUESTION: '一般聖經問題',
};
