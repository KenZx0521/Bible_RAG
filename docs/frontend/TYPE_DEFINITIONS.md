# Bible RAG TypeScript 型別定義

> 版本：v1.0.0
> 更新日期：2025-12-25

---

## 目錄

1. [列舉與常數](#1-列舉與常數)
2. [API 型別](#2-api-型別)
3. [領域模型型別](#3-領域模型型別)
4. [元件 Props 型別](#4-元件-props-型別)
5. [狀態型別](#5-狀態型別)
6. [工具型別](#6-工具型別)

---

## 1. 列舉與常數

### 1.1 Testament - 新舊約

```typescript
// types/enums.ts

/** 新舊約類型 */
export type Testament = 'OT' | 'NT';

/** 新舊約對照表 */
export const TESTAMENT_LABELS: Record<Testament, string> = {
  OT: '舊約',
  NT: '新約',
};

/** 新舊約書卷數量 */
export const TESTAMENT_BOOK_COUNTS: Record<Testament, number> = {
  OT: 39,
  NT: 27,
};
```

---

### 1.2 EntityType - 實體類型

```typescript
/** 實體類型 */
export type EntityType = 'PERSON' | 'PLACE' | 'GROUP' | 'EVENT';

/** 實體類型對照表 */
export const ENTITY_TYPE_LABELS: Record<EntityType, string> = {
  PERSON: '人物',
  PLACE: '地點',
  GROUP: '群體',
  EVENT: '事件',
};

/** 實體類型顏色 */
export const ENTITY_TYPE_COLORS: Record<EntityType, string> = {
  PERSON: '#E57373', // 紅色
  PLACE: '#64B5F6',  // 藍色
  GROUP: '#BA68C8',  // 紫色
  EVENT: '#FFB74D',  // 橙色
};
```

---

### 1.3 TopicType - 主題類型

```typescript
/** 主題類型 */
export type TopicType = 'DOCTRINE' | 'MORAL' | 'HISTORICAL' | 'PROPHETIC' | 'OTHER';

/** 主題類型對照表 */
export const TOPIC_TYPE_LABELS: Record<TopicType, string> = {
  DOCTRINE: '教義',
  MORAL: '道德',
  HISTORICAL: '歷史',
  PROPHETIC: '預言',
  OTHER: '其他',
};

/** 主題類型顏色 */
export const TOPIC_TYPE_COLORS: Record<TopicType, string> = {
  DOCTRINE: '#81C784',  // 綠色
  MORAL: '#4FC3F7',     // 淺藍色
  HISTORICAL: '#FFD54F', // 黃色
  PROPHETIC: '#7986CB', // 靛藍色
  OTHER: '#90A4AE',     // 灰色
};
```

---

### 1.4 QueryMode - 查詢模式

```typescript
/** 查詢模式 (使用者選擇) */
export type QueryMode = 'auto' | 'verse' | 'topic' | 'person' | 'event';

/** 查詢模式對照表 */
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
```

---

### 1.5 QueryType - 查詢類型

```typescript
/** 查詢類型 (系統判定) */
export type QueryType =
  | 'VERSE_LOOKUP'
  | 'TOPIC_QUESTION'
  | 'PERSON_QUESTION'
  | 'EVENT_QUESTION'
  | 'GENERAL_BIBLE_QUESTION';

/** 查詢類型對照表 */
export const QUERY_TYPE_LABELS: Record<QueryType, string> = {
  VERSE_LOOKUP: '經文查找',
  TOPIC_QUESTION: '主題問題',
  PERSON_QUESTION: '人物問題',
  EVENT_QUESTION: '事件問題',
  GENERAL_BIBLE_QUESTION: '一般聖經問題',
};
```

---

### 1.6 應用程式常數

```typescript
// utils/constants.ts

/** API 配置 */
export const API_CONFIG = {
  BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1',
  TIMEOUT: 60000, // 60 秒
} as const;

/** 分頁配置 */
export const PAGINATION = {
  DEFAULT_PAGE_SIZE: 20,
  MAX_PAGE_SIZE: 100,
} as const;

/** RAG 查詢配置 */
export const RAG_CONFIG = {
  MAX_QUERY_LENGTH: 500,
  DEFAULT_MAX_RESULTS: 5,
  MAX_RESULTS: 20,
} as const;

/** 圖譜配置 */
export const GRAPH_CONFIG = {
  DEFAULT_DEPTH: 2,
  MAX_DEPTH: 3,
} as const;

/** 書卷分類 */
export const BOOK_CATEGORIES = {
  OT: [
    { name: '律法書', range: [1, 5] },
    { name: '歷史書', range: [6, 17] },
    { name: '詩歌智慧書', range: [18, 22] },
    { name: '大先知書', range: [23, 27] },
    { name: '小先知書', range: [28, 39] },
  ],
  NT: [
    { name: '福音書', range: [1, 4] },
    { name: '使徒行傳', range: [5, 5] },
    { name: '保羅書信', range: [6, 18] },
    { name: '普通書信', range: [19, 26] },
    { name: '啟示錄', range: [27, 27] },
  ],
} as const;
```

---

## 2. API 型別

### 2.1 請求型別

#### RAG 查詢請求

```typescript
// types/api.types.ts

/** 查詢選項 */
export interface QueryOptions {
  /** 回傳的段落數量，範圍 1-20，預設 5 */
  max_results?: number;
  /** 是否包含知識圖譜上下文 */
  include_graph?: boolean;
}

/** RAG 查詢請求 */
export interface QueryRequest {
  /** 使用者問題，長度 1-500 字元 */
  query: string;
  /** 查詢模式 */
  mode?: QueryMode;
  /** 查詢選項 */
  options?: QueryOptions;
}
```

#### 分頁請求參數

```typescript
/** 通用分頁參數 */
export interface PaginationParams {
  /** 分頁偏移量，預設 0 */
  skip?: number;
  /** 每頁數量，預設 20，最大 100 */
  limit?: number;
}

/** 段落列表請求參數 */
export interface PericopesListParams extends PaginationParams {
  /** 篩選指定書卷 */
  book_id?: number;
}

/** 經文列表請求參數 */
export interface VersesListParams extends PaginationParams {
  /** 篩選指定書卷 */
  book_id?: number;
  /** 篩選指定章節 (需搭配 book_id) */
  chapter?: number;
  /** 篩選指定段落 */
  pericope_id?: number;
}

/** 經文搜尋請求參數 */
export interface VerseSearchParams {
  /** 搜尋關鍵字 */
  q: string;
  /** 限定搜尋範圍至指定書卷 */
  book_id?: number;
  /** 回傳結果數量，最大 100，預設 20 */
  limit?: number;
}

/** 實體搜尋請求參數 */
export interface EntitySearchParams {
  /** 實體名稱 (模糊搜尋) */
  name?: string;
  /** 實體類型 */
  type?: EntityType;
  /** 回傳結果數量，預設 20 */
  limit?: number;
}

/** 主題搜尋請求參數 */
export interface TopicSearchParams {
  /** 主題名稱 (模糊搜尋) */
  name?: string;
  /** 主題類型 */
  type?: TopicType;
  /** 回傳結果數量，預設 20 */
  limit?: number;
}

/** 圖譜關係請求參數 */
export interface GraphRelationshipsParams {
  /** 中心實體 ID */
  entity_id: number;
  /** 實體類型 */
  entity_type: EntityType | 'TOPIC';
  /** 展開深度，範圍 1-3，預設 2 */
  depth?: number;
}
```

---

### 2.2 回應型別

#### RAG 查詢回應

```typescript
/** 段落摘要 (查詢結果) */
export interface PericopeSegment {
  /** 段落 ID */
  id: number;
  /** 類型，固定為 "pericope" */
  type: 'pericope';
  /** 書卷名稱 */
  book: string;
  /** 起始章 */
  chapter_start: number;
  /** 起始節 */
  verse_start: number;
  /** 結束章 */
  chapter_end: number;
  /** 結束節 */
  verse_end: number;
  /** 段落標題 */
  title: string;
  /** 經文摘要 */
  text_excerpt: string;
  /** 相關度分數 (0-1) */
  relevance_score: number;
}

/** 查詢元資料 */
export interface QueryMeta {
  /** 系統判定的查詢類型 */
  query_type: QueryType;
  /** 使用的檢索器列表 */
  used_retrievers: string[];
  /** 處理時間 (毫秒) */
  total_processing_time_ms: number;
  /** 使用的 LLM 模型 */
  llm_model: string;
}

/** 圖譜上下文 */
export interface GraphContext {
  /** 相關主題列表 */
  related_topics?: string[];
  /** 相關人物列表 */
  related_persons?: string[];
}

/** RAG 查詢回應 */
export interface QueryResponse {
  /** LLM 生成的回答，Markdown 格式 */
  answer: string;
  /** 相關經文段落列表 */
  segments: PericopeSegment[];
  /** 查詢元資料 */
  meta: QueryMeta;
  /** 知識圖譜上下文 (需設定 include_graph: true) */
  graph_context?: GraphContext;
}
```

#### 書卷相關回應

```typescript
/** 書卷列表項目 */
export interface BookListItem {
  /** 書卷 ID */
  id: number;
  /** 中文書名 */
  name_zh: string;
  /** 中文縮寫 */
  abbrev_zh: string;
  /** 新舊約 */
  testament: Testament;
  /** 正典順序 (1-66) */
  order_index: number;
}

/** 書卷列表回應 */
export interface BooksListResponse {
  /** 書卷列表 */
  books: BookListItem[];
  /** 書卷總數 */
  total: number;
}

/** 書卷詳情 */
export interface BookDetail extends BookListItem {
  /** 章節數量 */
  chapter_count: number;
  /** 經文數量 */
  verse_count: number;
  /** 段落數量 */
  pericope_count: number;
}

/** 章節資訊 */
export interface ChapterInfo {
  /** 章節號 */
  chapter: number;
  /** 經文數量 */
  verse_count: number;
}

/** 書卷章節回應 */
export interface BookChaptersResponse {
  /** 書卷 ID */
  book_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 章節列表 */
  chapters: ChapterInfo[];
}

/** 書卷段落回應 */
export interface BookPericopesResponse {
  /** 書卷 ID */
  book_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 段落列表 */
  pericopes: PericopeListItem[];
  /** 段落總數 */
  total: number;
}

/** 書卷經文回應 */
export interface BookVersesResponse {
  /** 書卷 ID */
  book_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 經文列表 */
  verses: VerseItem[];
  /** 經文總數 */
  total: number;
}
```

#### 段落相關回應

```typescript
/** 段落列表項目 */
export interface PericopeListItem {
  /** 段落 ID */
  id: number;
  /** 書卷 ID */
  book_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 段落標題 */
  title: string;
  /** 經文引用 (如 "創世記 1:1-31") */
  reference: string;
  /** 起始章 */
  chapter_start: number;
  /** 起始節 */
  verse_start: number;
  /** 結束章 */
  chapter_end: number;
  /** 結束節 */
  verse_end: number;
}

/** 段落列表回應 */
export interface PericopesListResponse {
  /** 段落列表 */
  pericopes: PericopeListItem[];
  /** 段落總數 */
  total: number;
  /** 分頁偏移量 */
  skip: number;
  /** 每頁數量 */
  limit: number;
}

/** 段落詳情 */
export interface PericopeDetail extends PericopeListItem {
  /** 段落摘要 (LLM 生成，可能為 null) */
  summary: string | null;
  /** 段落內所有經文 */
  verses: VerseItem[];
}
```

#### 經文相關回應

```typescript
/** 經文項目 */
export interface VerseItem {
  /** 經文 ID */
  id: number;
  /** 書卷 ID */
  book_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 章節號 */
  chapter: number;
  /** 節號 */
  verse: number;
  /** 經文內容 */
  text: string;
  /** 經文引用 (如 "創世記 1:1") */
  reference: string;
}

/** 經文詳情 */
export interface VerseDetail extends VerseItem {
  /** 所屬段落 ID */
  pericope_id: number;
  /** 所屬段落標題 */
  pericope_title: string;
}

/** 經文列表回應 */
export interface VersesListResponse {
  /** 經文列表 */
  verses: VerseItem[];
  /** 經文總數 */
  total: number;
  /** 分頁偏移量 */
  skip: number;
  /** 每頁數量 */
  limit: number;
}

/** 經文搜尋結果項目 */
export interface VerseSearchResultItem extends VerseItem {
  /** 搜尋相關度分數 (0-1)，越高越相關 */
  rank: number;
}

/** 經文搜尋回應 */
export interface VerseSearchResponse {
  /** 搜尋關鍵字 */
  query: string;
  /** 搜尋結果 */
  verses: VerseSearchResultItem[];
  /** 結果總數 */
  total: number;
}
```

#### 知識圖譜回應

```typescript
/** 圖譜節點 */
export interface GraphNode {
  /** 節點 ID (格式：{type}_{id}，如 "person_156") */
  id: string;
  /** 顯示標籤 */
  label: string;
  /** 節點類型 */
  type: string;
  /** 節點屬性 */
  properties: Record<string, unknown>;
}

/** 圖譜邊 */
export interface GraphEdge {
  /** 來源節點 ID */
  source: string;
  /** 目標節點 ID */
  target: string;
  /** 關係類型 */
  type: string;
  /** 關係屬性 */
  properties: Record<string, unknown>;
}

/** 圖譜關係回應 */
export interface GraphRelationshipsResponse {
  /** 節點列表 */
  nodes: GraphNode[];
  /** 邊列表 */
  edges: GraphEdge[];
}

/** 圖譜健康狀態回應 */
export interface GraphHealthResponse {
  /** 連線狀態 */
  status: 'healthy' | 'unhealthy';
  /** Neo4j 連線 URI */
  uri: string;
}

/** 圖譜統計回應 */
export interface GraphStatsResponse {
  /** 人物總數 */
  total_persons: number;
  /** 地點總數 */
  total_places: number;
  /** 群體總數 */
  total_groups: number;
  /** 事件總數 */
  total_events: number;
  /** 主題總數 */
  total_topics: number;
  /** 關係總數 */
  total_relationships: number;
}

/** 實體搜尋結果 */
export interface EntitySearchResult {
  /** 實體 ID */
  id: number;
  /** 實體名稱 */
  name: string;
  /** 實體類型 */
  type: EntityType;
}

/** 實體搜尋回應 */
export interface EntitySearchResponse {
  /** 實體列表 */
  entities: EntitySearchResult[];
  /** 結果總數 */
  total: number;
}

/** 實體詳情 */
export interface EntityDetail extends EntitySearchResult {
  /** 實體描述 */
  description: string | null;
  /** 相關經文數量 */
  related_verses_count: number;
  /** 相關實體列表 */
  related_entities: EntitySearchResult[];
}

/** 主題搜尋結果 */
export interface TopicSearchResult {
  /** 主題 ID */
  id: number;
  /** 主題名稱 */
  name: string;
  /** 主題類型 */
  type: TopicType;
}

/** 主題搜尋回應 */
export interface TopicSearchResponse {
  /** 主題列表 */
  topics: TopicSearchResult[];
  /** 結果總數 */
  total: number;
}

/** 主題詳情 */
export interface TopicDetail extends TopicSearchResult {
  /** 主題描述 */
  description: string | null;
  /** 相關經文數量 */
  related_verses_count: number;
  /** 相關主題列表 */
  related_topics: TopicSearchResult[];
}

/** 關聯主題項目 */
export interface RelatedTopicItem extends TopicSearchResult {
  /** 關聯權重 (Jaccard 相似度) */
  weight: number;
  /** 共現經文數量 */
  co_occurrence: number;
}

/** 關聯主題回應 */
export interface RelatedTopicsResponse {
  /** 主題 ID */
  topic_id: number;
  /** 主題名稱 */
  topic_name: string;
  /** 關聯主題列表 */
  related: RelatedTopicItem[];
  /** 結果總數 */
  total: number;
}

/** 經文相關實體回應 */
export interface VerseEntitiesResponse {
  /** 經文 ID */
  verse_id: number;
  /** 經文引用 */
  verse_reference: string;
  /** 相關人物 */
  persons: EntitySearchResult[];
  /** 相關地點 */
  places: EntitySearchResult[];
  /** 相關群體 */
  groups: EntitySearchResult[];
  /** 相關事件 */
  events: EntitySearchResult[];
  /** 相關主題 */
  topics: TopicSearchResult[];
}

/** 交叉參照經文 */
export interface CrossReferenceVerse {
  /** 經文 ID */
  verse_id: number;
  /** 經文引用 */
  reference: string;
  /** 經文內容 */
  text: string;
}

/** 交叉參照回應 */
export interface CrossReferencesResponse {
  /** 經文 ID */
  verse_id: number;
  /** 經文引用 */
  verse_reference: string;
  /** 此經文引用的其他經文 */
  quotes: CrossReferenceVerse[];
  /** 引用此經文的其他經文 */
  quoted_by: CrossReferenceVerse[];
  /** 此經文暗示的其他經文 */
  alludes_to: CrossReferenceVerse[];
  /** 暗示此經文的其他經文 */
  alluded_by: CrossReferenceVerse[];
  /** 總數 */
  total: number;
}

/** 預言應驗回應 */
export interface PropheciesResponse {
  /** 經文 ID */
  verse_id: number;
  /** 經文引用 */
  verse_reference: string;
  /** 是否為舊約經文 */
  is_ot: boolean;
  /** 應驗此預言的新約經文 (僅舊約) */
  fulfillments: CrossReferenceVerse[];
  /** 此經文應驗的舊約預言 (僅新約) */
  prophecies: CrossReferenceVerse[];
  /** 總數 */
  total: number;
}

/** 平行經文項目 */
export interface ParallelPericope {
  /** 段落 ID */
  pericope_id: number;
  /** 書卷名稱 */
  book_name: string;
  /** 段落標題 */
  title: string;
  /** 經文引用 */
  reference: string;
  /** 平行段落名稱 */
  parallel_name: string;
}

/** 平行經文回應 */
export interface ParallelsResponse {
  /** 段落 ID */
  pericope_id: number;
  /** 段落標題 */
  pericope_title: string;
  /** 段落引用 */
  pericope_reference: string;
  /** 平行段落列表 */
  parallels: ParallelPericope[];
  /** 總數 */
  total: number;
}
```

---

### 2.3 錯誤型別

```typescript
/** API 錯誤回應 */
export interface ApiError {
  /** 錯誤訊息 */
  detail: string;
}

/** HTTP 狀態碼 */
export type HttpStatusCode = 200 | 400 | 404 | 422 | 500 | 503;

/** 自定義錯誤類別 */
export class BibleRagError extends Error {
  constructor(
    message: string,
    public statusCode?: HttpStatusCode,
    public code?: string
  ) {
    super(message);
    this.name = 'BibleRagError';
  }
}

/** 驗證錯誤詳情 */
export interface ValidationErrorDetail {
  /** 錯誤位置 */
  loc: (string | number)[];
  /** 錯誤訊息 */
  msg: string;
  /** 錯誤類型 */
  type: string;
}

/** 驗證錯誤回應 (422) */
export interface ValidationErrorResponse {
  detail: ValidationErrorDetail[];
}
```

---

## 3. 領域模型型別

### 3.1 書卷與經文

```typescript
// types/domain.types.ts

/** 書卷 */
export interface Book {
  id: number;
  name_zh: string;
  abbrev_zh: string;
  testament: Testament;
  order_index: number;
  chapter_count?: number;
  verse_count?: number;
  pericope_count?: number;
}

/** 章節 */
export interface Chapter {
  book_id: number;
  chapter_number: number;
  verse_count: number;
}

/** 經文 */
export interface Verse {
  id: number;
  book_id: number;
  book_name: string;
  chapter: number;
  verse: number;
  text: string;
  reference: string;
  pericope_id?: number;
  pericope_title?: string;
}
```

### 3.2 段落

```typescript
/** 段落 */
export interface Pericope {
  id: number;
  book_id: number;
  book_name: string;
  title: string;
  chapter_start: number;
  verse_start: number;
  chapter_end: number;
  verse_end: number;
  reference: string;
  summary?: string | null;
  verses?: Verse[];
}
```

### 3.3 知識圖譜

```typescript
/** 實體 (人物/地點/群體/事件) */
export interface Entity {
  id: number;
  name: string;
  type: EntityType;
  description?: string | null;
}

/** 主題 */
export interface Topic {
  id: number;
  name: string;
  type: TopicType;
  description?: string | null;
}

/** 圖譜視覺化節點 (擴展 GraphNode) */
export interface VisualGraphNode extends GraphNode {
  /** X 座標 */
  x?: number;
  /** Y 座標 */
  y?: number;
  /** 節點顏色 */
  color?: string;
  /** 節點大小 */
  size?: number;
  /** 是否為中心節點 */
  isCenter?: boolean;
}

/** 圖譜視覺化邊 (擴展 GraphEdge) */
export interface VisualGraphEdge extends GraphEdge {
  /** 邊顏色 */
  color?: string;
  /** 邊寬度 */
  width?: number;
}

/** 圖譜視覺化資料 */
export interface GraphData {
  nodes: VisualGraphNode[];
  edges: VisualGraphEdge[];
}
```

---

## 4. 元件 Props 型別

### 4.1 共用元件 Props

```typescript
// types/component.types.ts

/** 按鈕 Props */
export interface ButtonProps {
  /** 樣式變體 */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** 尺寸 */
  size?: 'sm' | 'md' | 'lg';
  /** 禁用狀態 */
  disabled?: boolean;
  /** 載入狀態 */
  loading?: boolean;
  /** 按鈕類型 */
  type?: 'button' | 'submit' | 'reset';
  /** 點擊回調 */
  onClick?: () => void;
  /** 子元素 */
  children: React.ReactNode;
  /** 額外 CSS 類別 */
  className?: string;
}

/** 輸入框 Props */
export interface InputProps {
  /** 輸入類型 */
  type?: 'text' | 'email' | 'password' | 'number' | 'search';
  /** 輸入值 */
  value: string;
  /** 變更回調 */
  onChange: (value: string) => void;
  /** 佔位文字 */
  placeholder?: string;
  /** 禁用狀態 */
  disabled?: boolean;
  /** 錯誤訊息 */
  error?: string;
  /** 標籤文字 */
  label?: string;
  /** 是否必填 */
  required?: boolean;
  /** 額外 CSS 類別 */
  className?: string;
}

/** 卡片 Props */
export interface CardProps {
  /** 子元素 */
  children: React.ReactNode;
  /** 內距 */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** 額外 CSS 類別 */
  className?: string;
  /** 點擊回調 */
  onClick?: () => void;
}

/** 載入指示器 Props */
export interface LoadingSpinnerProps {
  /** 尺寸 */
  size?: 'sm' | 'md' | 'lg';
  /** 額外 CSS 類別 */
  className?: string;
}

/** 分頁 Props */
export interface PaginationProps {
  /** 當前頁碼 */
  currentPage: number;
  /** 總頁數 */
  totalPages: number;
  /** 頁碼變更回調 */
  onPageChange: (page: number) => void;
  /** 顯示的相鄰頁數 */
  siblingsCount?: number;
}

/** 麵包屑項目 */
export interface BreadcrumbItem {
  /** 標籤文字 */
  label: string;
  /** 連結網址 */
  href?: string;
}

/** 麵包屑 Props */
export interface BreadcrumbProps {
  /** 麵包屑項目列表 */
  items: BreadcrumbItem[];
}
```

### 4.2 搜尋元件 Props

```typescript
/** 搜尋欄 Props */
export interface SearchBarProps {
  /** 輸入值 */
  value: string;
  /** 變更回調 */
  onChange: (value: string) => void;
  /** 送出回調 */
  onSubmit: () => void;
  /** 佔位文字 */
  placeholder?: string;
  /** 禁用狀態 */
  disabled?: boolean;
  /** 載入狀態 */
  loading?: boolean;
  /** 自動聚焦 */
  autoFocus?: boolean;
}

/** 查詢模式選擇器 Props */
export interface QueryModeSelectorProps {
  /** 當前選中模式 */
  value: QueryMode;
  /** 變更回調 */
  onChange: (mode: QueryMode) => void;
}

/** 查詢結果 Props */
export interface QueryResultProps {
  /** 查詢回應資料 */
  result: QueryResponse;
}

/** 段落卡片 Props */
export interface SegmentCardProps {
  /** 段落資料 */
  segment: PericopeSegment;
}
```

### 4.3 聖經瀏覽元件 Props

```typescript
/** 書卷選擇器 Props */
export interface BookSelectorProps {
  /** 當前選中的書卷 ID */
  selectedBookId?: number | null;
  /** 選擇回調 */
  onSelect?: (bookId: number) => void;
}

/** 章節網格 Props */
export interface ChapterGridProps {
  /** 書卷 ID */
  bookId: number;
  /** 書卷名稱 */
  bookName: string;
  /** 章節列表 */
  chapters: ChapterInfo[];
}

/** 經文列表 Props */
export interface VerseListProps {
  /** 書卷 ID */
  bookId: number;
  /** 書卷名稱 */
  bookName: string;
  /** 章節號 */
  chapter: number;
  /** 經文列表 */
  verses: VerseItem[];
  /** 書卷總章數 */
  totalChapters: number;
  /** 高亮顯示的經文 ID */
  highlightVerseId?: number;
}

/** 段落卡片 Props */
export interface PericopeCardProps {
  /** 段落資料 */
  pericope: PericopeListItem;
  /** 是否顯示書卷名稱 */
  showBook?: boolean;
}
```

### 4.4 圖譜元件 Props

```typescript
/** 圖譜視覺化 Props */
export interface GraphViewerProps {
  /** 節點資料 */
  nodes: GraphNode[];
  /** 邊資料 */
  edges: GraphEdge[];
  /** 節點點擊回調 */
  onNodeClick?: (nodeId: string) => void;
  /** 中心節點 ID */
  centerNodeId?: string;
  /** 畫布寬度 */
  width?: number;
  /** 畫布高度 */
  height?: number;
}

/** 實體面板 Props */
export interface EntityPanelProps {
  /** 實體 ID */
  entityId: number;
  /** 關閉回調 */
  onClose?: () => void;
}

/** 主題面板 Props */
export interface TopicPanelProps {
  /** 主題 ID */
  topicId: number;
  /** 關閉回調 */
  onClose?: () => void;
}
```

---

## 5. 狀態型別

### 5.1 TanStack Query Keys

```typescript
// hooks/api/queryKeys.ts

/** Query Key 工廠函數 */
export const queryKeys = {
  /** 書卷相關 */
  books: {
    all: ['books'] as const,
    detail: (id: number) => ['books', id] as const,
    chapters: (id: number) => ['books', id, 'chapters'] as const,
    pericopes: (id: number) => ['books', id, 'pericopes'] as const,
    verses: (id: number, chapter?: number) =>
      ['books', id, 'verses', { chapter }] as const,
  },

  /** 段落相關 */
  pericopes: {
    all: ['pericopes'] as const,
    list: (params: PericopesListParams) =>
      ['pericopes', 'list', params] as const,
    detail: (id: number) => ['pericopes', id] as const,
  },

  /** 經文相關 */
  verses: {
    all: ['verses'] as const,
    list: (params: VersesListParams) =>
      ['verses', 'list', params] as const,
    detail: (id: number) => ['verses', id] as const,
    search: (params: VerseSearchParams) =>
      ['verses', 'search', params] as const,
  },

  /** 知識圖譜相關 */
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

/** Query Key 型別 */
export type QueryKeys = typeof queryKeys;
```

### 5.2 Zustand Store 型別

```typescript
// stores/types.ts

/** 主題設定 */
export type Theme = 'light' | 'dark' | 'system';

/** 應用程式狀態 */
export interface AppState {
  // UI 狀態
  /** 側邊欄是否展開 */
  sidebarOpen: boolean;
  /** 主題設定 */
  theme: Theme;

  // 當前選中
  /** 選中的書卷 ID */
  selectedBookId: number | null;
  /** 選中的章節號 */
  selectedChapter: number | null;
  /** 選中的段落 ID */
  selectedPericopeId: number | null;

  // Actions
  /** 切換側邊欄 */
  toggleSidebar: () => void;
  /** 設定主題 */
  setTheme: (theme: Theme) => void;
  /** 選擇書卷 */
  selectBook: (bookId: number | null) => void;
  /** 選擇章節 */
  selectChapter: (chapter: number | null) => void;
  /** 選擇段落 */
  selectPericope: (pericopeId: number | null) => void;
  /** 重置選擇狀態 */
  reset: () => void;
}

/** 搜尋狀態 */
export interface SearchState {
  // 查詢歷史
  /** 搜尋歷史記錄 */
  history: string[];
  /** 最大歷史記錄數 */
  maxHistoryLength: number;

  // 當前查詢
  /** 當前查詢文字 */
  currentQuery: string;
  /** 當前查詢模式 */
  currentMode: QueryMode;

  // Actions
  /** 設定查詢文字 */
  setQuery: (query: string) => void;
  /** 設定查詢模式 */
  setMode: (mode: QueryMode) => void;
  /** 新增至歷史 */
  addToHistory: (query: string) => void;
  /** 清除歷史 */
  clearHistory: () => void;
}

/** 圖譜狀態 */
export interface GraphState {
  // 圖譜資料
  /** 節點列表 */
  nodes: GraphNode[];
  /** 邊列表 */
  edges: GraphEdge[];

  // 選中狀態
  /** 選中的節點 ID */
  selectedNodeId: string | null;
  /** 中心節點 ID */
  centerNodeId: string | null;

  // Actions
  /** 設定圖譜資料 */
  setGraphData: (nodes: GraphNode[], edges: GraphEdge[]) => void;
  /** 選擇節點 */
  selectNode: (nodeId: string | null) => void;
  /** 設定中心節點 */
  setCenterNode: (nodeId: string) => void;
  /** 清除圖譜 */
  clearGraph: () => void;
}
```

---

## 6. 工具型別

### 6.1 通用工具型別

```typescript
// types/utils.types.ts

/** 可為空類型 */
export type Nullable<T> = T | null;

/** 可為未定義類型 */
export type Optional<T> = T | undefined;

/** 深度可選類型 */
export type DeepPartial<T> = {
  [P in keyof T]?: T[P] extends object ? DeepPartial<T[P]> : T[P];
};

/** 取得物件的值類型 */
export type ValueOf<T> = T[keyof T];

/** 排除 null 和 undefined */
export type NonNullableFields<T> = {
  [P in keyof T]: NonNullable<T[P]>;
};

/** 從聯合類型中提取特定類型 */
export type ExtractType<T, U extends T> = T extends U ? T : never;

/** 合併兩個型別 */
export type Merge<T, U> = Omit<T, keyof U> & U;
```

### 6.2 分頁工具型別

```typescript
/** 分頁結果包裝 */
export interface PaginatedResponse<T> {
  /** 資料列表 */
  data: T[];
  /** 總數 */
  total: number;
  /** 分頁偏移量 */
  skip: number;
  /** 每頁數量 */
  limit: number;
  /** 是否有下一頁 */
  hasMore: boolean;
}

/** 分頁狀態 */
export interface PaginationState {
  /** 當前頁碼 (1-based) */
  page: number;
  /** 每頁數量 */
  pageSize: number;
  /** 總數 */
  total: number;
  /** 總頁數 */
  totalPages: number;
}

/** 計算分頁資訊 */
export function calculatePagination(
  skip: number,
  limit: number,
  total: number
): PaginationState {
  return {
    page: Math.floor(skip / limit) + 1,
    pageSize: limit,
    total,
    totalPages: Math.ceil(total / limit),
  };
}
```

### 6.3 表單工具型別

```typescript
/** 表單欄位狀態 */
export interface FieldState<T> {
  /** 欄位值 */
  value: T;
  /** 錯誤訊息 */
  error?: string;
  /** 是否已被修改 */
  touched: boolean;
  /** 是否正在驗證 */
  validating: boolean;
}

/** 表單狀態 */
export interface FormState<T extends Record<string, unknown>> {
  /** 欄位狀態 */
  fields: { [K in keyof T]: FieldState<T[K]> };
  /** 是否正在提交 */
  isSubmitting: boolean;
  /** 是否有效 */
  isValid: boolean;
  /** 是否已被修改 */
  isDirty: boolean;
}

/** 表單驗證規則 */
export type ValidationRule<T> = (value: T) => string | undefined;

/** 表單驗證結果 */
export interface ValidationResult {
  isValid: boolean;
  errors: Record<string, string>;
}
```

---

## 附錄

### A. 型別檔案結構

```
src/types/
├── index.ts            # 統一匯出
├── enums.ts            # 列舉與常數
├── api.types.ts        # API 請求/回應型別
├── domain.types.ts     # 領域模型型別
├── component.types.ts  # 元件 Props 型別
├── store.types.ts      # 狀態型別
└── utils.types.ts      # 工具型別
```

### B. 型別匯出範例

```typescript
// types/index.ts

// 列舉與常數
export * from './enums';

// API 型別
export * from './api.types';

// 領域模型
export * from './domain.types';

// 元件 Props
export * from './component.types';

// 狀態型別
export * from './store.types';

// 工具型別
export * from './utils.types';
```

### C. 與後端 Schema 對應表

| 前端 TypeScript | 後端 Pydantic | 說明 |
|-----------------|---------------|------|
| QueryRequest | QueryRequest | RAG 查詢請求 |
| QueryResponse | QueryResponse | RAG 查詢回應 |
| BookListItem | BookListItem | 書卷列表項目 |
| BookDetail | BookDetail | 書卷詳情 |
| VerseItem | VerseItem | 經文項目 |
| VerseDetail | VerseDetail | 經文詳情 |
| PericopeListItem | PericopeListItem | 段落列表項目 |
| PericopeDetail | PericopeDetail | 段落詳情 |
| GraphNode | GraphNode | 圖譜節點 |
| GraphEdge | GraphEdge | 圖譜邊 |
| EntitySearchResult | EntitySearchResult | 實體搜尋結果 |
| TopicSearchResult | TopicSearchResult | 主題搜尋結果 |

---

*文件版本: 1.0.0*
*最後更新: 2025-12-25*
