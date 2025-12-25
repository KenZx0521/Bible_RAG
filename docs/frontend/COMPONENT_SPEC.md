# Bible RAG 元件規格文件

> 版本：v1.0.0
> 更新日期：2025-12-25

---

## 目錄

1. [頁面元件 (Pages)](#1-頁面元件-pages)
2. [佈局元件 (Layouts)](#2-佈局元件-layouts)
3. [搜尋元件 (Search)](#3-搜尋元件-search)
4. [聖經瀏覽元件 (Bible)](#4-聖經瀏覽元件-bible)
5. [圖譜元件 (Graph)](#5-圖譜元件-graph)
6. [共用元件 (Common)](#6-共用元件-common)

---

## 1. 頁面元件 (Pages)

頁面元件是對應路由的頂層元件，負責組合多個功能元件。

### 1.1 SearchPage - RAG 問答頁面

**功能描述**: 系統首頁，提供 RAG 智慧問答功能。

**路徑**: `/`, `/search`

**元件結構**:
```
SearchPage
├── SearchBar
├── QueryModeSelector
├── LoadingOverlay (條件渲染)
└── QueryResult (條件渲染)
    ├── AnswerSection
    │   └── ReactMarkdown
    ├── SegmentList
    │   └── SegmentCard[]
    └── MetaInfo
```

**Props**: 無 (頁面元件)

**內部狀態**:

| 狀態 | 類型 | 說明 |
|------|------|------|
| query | string | 使用者輸入的查詢文字 |
| mode | QueryMode | 查詢模式 (`auto`/`verse`/`topic`/`person`/`event`) |

**使用的 Hooks**:

| Hook | 用途 |
|------|------|
| `useRagQuery` | 執行 RAG 查詢 mutation |
| `useSearchStore` | 存取搜尋歷史 |
| `useSearchParams` | 讀取 URL 查詢參數 |

**程式碼範例**:

```tsx
// pages/SearchPage/index.tsx
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SearchBar } from '@/components/search/SearchBar';
import { QueryModeSelector } from '@/components/search/QueryModeSelector';
import { QueryResult } from '@/components/search/QueryResult';
import { LoadingOverlay } from '@/components/common/LoadingOverlay';
import { useRagQuery } from '@/hooks/api/useRagQuery';
import { useSearchStore } from '@/stores/useSearchStore';
import type { QueryMode } from '@/types/api.types';

export default function SearchPage() {
  const [searchParams] = useSearchParams();
  const initialQuery = searchParams.get('q') || '';

  const [query, setQuery] = useState(initialQuery);
  const [mode, setMode] = useState<QueryMode>('auto');

  const { mutate, data, isPending, error } = useRagQuery();
  const { addToHistory } = useSearchStore();

  const handleSearch = () => {
    if (!query.trim()) return;
    addToHistory(query);
    mutate({ query, mode, options: { max_results: 5, include_graph: true } });
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-3xl font-bold mb-8 text-center">
        聖經智慧問答
      </h1>

      <div className="space-y-4">
        <SearchBar
          value={query}
          onChange={setQuery}
          onSubmit={handleSearch}
          placeholder="請輸入您的問題，例如：聖經怎麼談饒恕？"
          loading={isPending}
        />

        <QueryModeSelector value={mode} onChange={setMode} />
      </div>

      {isPending && (
        <LoadingOverlay message="正在查詢中，請稍候..." />
      )}

      {error && (
        <div className="mt-6 p-4 bg-red-50 text-red-700 rounded-lg border border-red-200">
          <p className="font-medium">查詢失敗</p>
          <p className="text-sm mt-1">{error.message}</p>
        </div>
      )}

      {data && <QueryResult result={data} />}
    </div>
  );
}
```

---

### 1.2 BrowsePage - 聖經瀏覽頁面

**功能描述**: 按書卷、章節瀏覽聖經經文。

**路徑**: `/browse`, `/browse/:bookId`, `/browse/:bookId/:chapter`

**元件結構**:
```
BrowsePage
├── Breadcrumb
├── BookSelector (無 bookId 時)
├── ChapterGrid (有 bookId，無 chapter 時)
└── VerseList (有 bookId 和 chapter 時)
    ├── PericopeSection[]
    │   ├── PericopeHeader
    │   └── VerseItem[]
    └── ChapterNavigation
```

**路由參數**:

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| bookId | string | 否 | 書卷 ID |
| chapter | string | 否 | 章節號 |

**內部狀態**:

| 狀態 | 類型 | 說明 |
|------|------|------|
| highlightVerseId | number \| null | 高亮顯示的經文 ID |

**使用的 Hooks**:

| Hook | 用途 |
|------|------|
| `useParams` | 讀取路由參數 |
| `useBooks` | 取得書卷列表 |
| `useBook` | 取得書卷詳情 |
| `useBookChapters` | 取得章節列表 |
| `useBookVerses` | 取得經文列表 |

**程式碼範例**:

```tsx
// pages/BrowsePage/index.tsx
import { useParams } from 'react-router-dom';
import { Breadcrumb } from '@/components/common/Breadcrumb';
import { BookSelector } from '@/components/bible/BookSelector';
import { ChapterGrid } from '@/components/bible/ChapterGrid';
import { VerseList } from '@/components/bible/VerseList';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { useBook, useBookChapters, useBookVerses } from '@/hooks/api/useBooks';

export default function BrowsePage() {
  const { bookId, chapter } = useParams<{ bookId?: string; chapter?: string }>();

  const bookIdNum = bookId ? parseInt(bookId) : undefined;
  const chapterNum = chapter ? parseInt(chapter) : undefined;

  const { data: book, isLoading: bookLoading } = useBook(bookIdNum!);
  const { data: chapters, isLoading: chaptersLoading } = useBookChapters(bookIdNum!);
  const { data: verses, isLoading: versesLoading } = useBookVerses(bookIdNum!, chapterNum);

  // 渲染書卷選擇器
  if (!bookIdNum) {
    return (
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-6">聖經書卷</h1>
        <BookSelector />
      </div>
    );
  }

  // 渲染章節網格
  if (!chapterNum) {
    if (bookLoading || chaptersLoading) {
      return <LoadingSpinner size="lg" />;
    }

    return (
      <div className="p-6">
        <Breadcrumb items={[
          { label: '聖經', href: '/browse' },
          { label: book?.name_zh || '' },
        ]} />
        <h1 className="text-2xl font-bold mb-6">{book?.name_zh}</h1>
        <ChapterGrid
          bookId={bookIdNum}
          bookName={book?.name_zh || ''}
          chapters={chapters?.chapters || []}
        />
      </div>
    );
  }

  // 渲染經文列表
  if (versesLoading) {
    return <LoadingSpinner size="lg" />;
  }

  return (
    <div className="p-6">
      <Breadcrumb items={[
        { label: '聖經', href: '/browse' },
        { label: book?.name_zh || '', href: `/browse/${bookIdNum}` },
        { label: `第 ${chapterNum} 章` },
      ]} />
      <VerseList
        bookId={bookIdNum}
        bookName={book?.name_zh || ''}
        chapter={chapterNum}
        verses={verses?.verses || []}
        totalChapters={book?.chapter_count || 0}
      />
    </div>
  );
}
```

---

### 1.3 GraphPage - 知識圖譜頁面

**功能描述**: 知識圖譜視覺化，探索人物、地點、事件、主題的關係。

**路徑**: `/graph`, `/graph/entity/:id`, `/graph/topic/:id`

**元件結構**:
```
GraphPage
├── GraphSearchBar
├── GraphViewer
│   ├── D3ForceGraph
│   └── NodeTooltip
├── EntityPanel (條件渲染)
│   ├── EntityHeader
│   ├── RelatedVersesList
│   └── RelatedEntitiesList
└── TopicPanel (條件渲染)
    ├── TopicHeader
    ├── RelatedTopicsList
    └── RelatedVersesList
```

**路由參數**:

| 參數 | 類型 | 說明 |
|------|------|------|
| id | string | 實體或主題 ID (選填) |

**內部狀態**:

| 狀態 | 類型 | 說明 |
|------|------|------|
| selectedNode | GraphNode \| null | 當前選中的節點 |
| graphData | { nodes: GraphNode[], edges: GraphEdge[] } | 圖譜資料 |
| searchQuery | string | 搜尋關鍵字 |

**使用的 Hooks**:

| Hook | 用途 |
|------|------|
| `useParams` | 讀取路由參數 |
| `useNavigate` | 導航到其他實體 |
| `useGraphRelationships` | 取得圖譜關係資料 |
| `useEntityDetail` | 取得實體詳情 |
| `useTopicDetail` | 取得主題詳情 |

---

### 1.4 DetailPage - 詳情頁面

**功能描述**: 段落或經文的詳細資訊頁面。

**路徑**: `/pericope/:id`, `/verse/:id`

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| type | `'pericope'` \| `'verse'` | 是 | 詳情類型 |

**元件結構**:
```
DetailPage
├── Breadcrumb
├── PericopeDetail (type='pericope')
│   ├── PericopeHeader
│   ├── PericopeSummary
│   ├── VerseList
│   └── RelatedEntities
└── VerseDetail (type='verse')
    ├── VerseHeader
    ├── VerseText
    ├── VerseContext
    ├── RelatedEntities
    └── CrossReferences
```

---

## 2. 佈局元件 (Layouts)

### 2.1 MainLayout - 主要佈局

**功能描述**: 應用程式的主要佈局容器，包含 Header、Sidebar 和內容區域。

**元件結構**:
```
MainLayout
├── Header
├── Sidebar (條件渲染)
└── main
    └── Outlet (React Router)
```

**內部狀態**:

| 狀態 | 類型 | 說明 |
|------|------|------|
| sidebarOpen | boolean | 側邊欄是否展開 (從 Zustand 讀取) |

**程式碼範例**:

```tsx
// components/layout/MainLayout/index.tsx
import { Outlet } from 'react-router-dom';
import { Header } from '../Header';
import { Sidebar } from '../Sidebar';
import { useAppStore } from '@/stores/useAppStore';

export function MainLayout() {
  const { sidebarOpen } = useAppStore();

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <Header />

      <div className="flex">
        {sidebarOpen && <Sidebar />}

        <main className={`
          flex-1 p-6 transition-all duration-300
          ${sidebarOpen ? 'ml-64' : 'ml-0'}
        `}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
```

---

### 2.2 Header - 頁首導航

**功能描述**: 頁面頂部導航列，包含 Logo、主導航、搜尋和設定。

**Props**: 無

**元件結構**:
```
Header
├── Logo
├── MainNav
│   └── NavLink[]
├── SearchTrigger
├── ThemeToggle
└── MobileMenuButton
```

**內部狀態**:

| 狀態 | 類型 | 說明 |
|------|------|------|
| mobileMenuOpen | boolean | 行動版選單是否開啟 |

**程式碼範例**:

```tsx
// components/layout/Header/index.tsx
import { Link, NavLink } from 'react-router-dom';
import { MenuIcon, SearchIcon, SunIcon, MoonIcon } from '@/components/icons';
import { useAppStore } from '@/stores/useAppStore';

const navItems = [
  { path: '/', label: '問答' },
  { path: '/browse', label: '瀏覽' },
  { path: '/graph', label: '圖譜' },
];

export function Header() {
  const { theme, setTheme, toggleSidebar } = useAppStore();

  return (
    <header className="sticky top-0 z-50 bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
      <div className="flex items-center justify-between h-16 px-4">
        {/* Logo & Menu Toggle */}
        <div className="flex items-center gap-4">
          <button
            onClick={toggleSidebar}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            aria-label="切換側邊欄"
          >
            <MenuIcon className="w-6 h-6" />
          </button>

          <Link to="/" className="text-xl font-bold text-primary-600">
            Bible RAG
          </Link>
        </div>

        {/* Main Navigation */}
        <nav className="hidden md:flex items-center gap-6">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) => `
                text-sm font-medium transition-colors
                ${isActive
                  ? 'text-primary-600 dark:text-primary-400'
                  : 'text-gray-600 dark:text-gray-300 hover:text-primary-600'
                }
              `}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        {/* Actions */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="p-2 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700"
            aria-label="切換主題"
          >
            {theme === 'dark' ? (
              <SunIcon className="w-5 h-5" />
            ) : (
              <MoonIcon className="w-5 h-5" />
            )}
          </button>
        </div>
      </div>
    </header>
  );
}
```

---

### 2.3 Sidebar - 側邊欄

**功能描述**: 側邊導航欄，顯示書卷快速導航。

**Props**: 無

**元件結構**:
```
Sidebar
├── SidebarHeader
├── BookQuickNav
│   ├── TestamentSection (舊約)
│   │   └── BookLink[]
│   └── TestamentSection (新約)
│       └── BookLink[]
└── SidebarFooter
```

**程式碼範例**:

```tsx
// components/layout/Sidebar/index.tsx
import { Link } from 'react-router-dom';
import { useBooks } from '@/hooks/api/useBooks';

export function Sidebar() {
  const { data: booksData } = useBooks();
  const books = booksData?.books || [];

  const otBooks = books.filter((b) => b.testament === 'OT');
  const ntBooks = books.filter((b) => b.testament === 'NT');

  return (
    <aside className="fixed left-0 top-16 w-64 h-[calc(100vh-4rem)] bg-white dark:bg-gray-800 border-r border-gray-200 dark:border-gray-700 overflow-y-auto">
      <div className="p-4">
        <h2 className="text-sm font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider mb-3">
          快速導航
        </h2>

        {/* 舊約 */}
        <div className="mb-4">
          <h3 className="text-xs font-medium text-bible-ot mb-2">舊約</h3>
          <div className="grid grid-cols-4 gap-1">
            {otBooks.map((book) => (
              <Link
                key={book.id}
                to={`/browse/${book.id}`}
                className="text-xs text-center py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                title={book.name_zh}
              >
                {book.abbrev_zh}
              </Link>
            ))}
          </div>
        </div>

        {/* 新約 */}
        <div>
          <h3 className="text-xs font-medium text-bible-nt mb-2">新約</h3>
          <div className="grid grid-cols-4 gap-1">
            {ntBooks.map((book) => (
              <Link
                key={book.id}
                to={`/browse/${book.id}`}
                className="text-xs text-center py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-700"
                title={book.name_zh}
              >
                {book.abbrev_zh}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </aside>
  );
}
```

---

## 3. 搜尋元件 (Search)

### 3.1 SearchBar - 搜尋輸入框

**功能描述**: 提供查詢輸入框和送出按鈕。

**Props**:

| Prop | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| value | string | 是 | - | 輸入值 |
| onChange | (value: string) => void | 是 | - | 輸入變更回調 |
| onSubmit | () => void | 是 | - | 送出回調 |
| placeholder | string | 否 | `''` | 佔位文字 |
| disabled | boolean | 否 | `false` | 禁用狀態 |
| loading | boolean | 否 | `false` | 載入中狀態 |
| autoFocus | boolean | 否 | `false` | 自動聚焦 |

**事件**:

| 事件 | 觸發時機 |
|------|----------|
| onChange | 輸入內容變更時 |
| onSubmit | 按下 Enter 或點擊搜尋按鈕 |

**程式碼範例**:

```tsx
// components/search/SearchBar/index.tsx
import { KeyboardEvent } from 'react';
import { SearchIcon, LoadingSpinner } from '@/components/common';

interface SearchBarProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  placeholder?: string;
  disabled?: boolean;
  loading?: boolean;
  autoFocus?: boolean;
}

export function SearchBar({
  value,
  onChange,
  onSubmit,
  placeholder = '',
  disabled = false,
  loading = false,
  autoFocus = false,
}: SearchBarProps) {
  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !disabled && !loading) {
      onSubmit();
    }
  };

  return (
    <div className="relative">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        disabled={disabled || loading}
        autoFocus={autoFocus}
        className="
          w-full px-4 py-3 pr-12 text-lg
          border border-gray-300 dark:border-gray-600 rounded-lg
          bg-white dark:bg-gray-800
          focus:ring-2 focus:ring-primary-500 focus:border-transparent
          disabled:bg-gray-100 dark:disabled:bg-gray-700 disabled:cursor-not-allowed
          transition-shadow
        "
      />
      <button
        onClick={onSubmit}
        disabled={disabled || loading || !value.trim()}
        className="
          absolute right-2 top-1/2 -translate-y-1/2 p-2
          text-gray-500 hover:text-primary-600
          disabled:opacity-50 disabled:cursor-not-allowed
          transition-colors
        "
        aria-label="搜尋"
      >
        {loading ? (
          <LoadingSpinner size="sm" />
        ) : (
          <SearchIcon className="w-6 h-6" />
        )}
      </button>
    </div>
  );
}
```

---

### 3.2 QueryModeSelector - 查詢模式選擇

**功能描述**: 選擇 RAG 查詢模式 (自動/經文/主題/人物/事件)。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| value | QueryMode | 是 | 當前選中的模式 |
| onChange | (mode: QueryMode) => void | 是 | 模式變更回調 |

**查詢模式**:

| 模式 | 說明 | 適用場景 |
|------|------|----------|
| `auto` | 自動判斷 | 一般問題 |
| `verse` | 經文查詢 | 「創世記 1:1 說什麼？」 |
| `topic` | 主題查詢 | 「聖經怎麼談愛？」 |
| `person` | 人物查詢 | 「亞伯拉罕是誰？」 |
| `event` | 事件查詢 | 「出埃及的過程是什麼？」 |

**程式碼範例**:

```tsx
// components/search/QueryModeSelector/index.tsx
import type { QueryMode } from '@/types/api.types';

interface QueryModeSelectorProps {
  value: QueryMode;
  onChange: (mode: QueryMode) => void;
}

const modes: { value: QueryMode; label: string; description: string }[] = [
  { value: 'auto', label: '自動', description: '自動判斷查詢類型' },
  { value: 'verse', label: '經文', description: '查找特定經文' },
  { value: 'topic', label: '主題', description: '探索聖經主題' },
  { value: 'person', label: '人物', description: '了解聖經人物' },
  { value: 'event', label: '事件', description: '查詢聖經事件' },
];

export function QueryModeSelector({ value, onChange }: QueryModeSelectorProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {modes.map((mode) => (
        <button
          key={mode.value}
          onClick={() => onChange(mode.value)}
          className={`
            px-3 py-1.5 text-sm rounded-full transition-colors
            ${value === mode.value
              ? 'bg-primary-600 text-white'
              : 'bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600'
            }
          `}
          title={mode.description}
        >
          {mode.label}
        </button>
      ))}
    </div>
  );
}
```

---

### 3.3 QueryResult - RAG 回答展示

**功能描述**: 展示 RAG 查詢的回答和相關經文段落。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| result | QueryResponse | 是 | RAG 查詢回應 |

**子元件**:

| 元件 | 說明 |
|------|------|
| AnswerSection | 顯示 LLM 生成的回答 (Markdown) |
| SegmentList | 相關段落列表 |
| MetaInfo | 查詢元資料 |
| GraphContextSection | 知識圖譜上下文 (選用) |

**程式碼範例**:

```tsx
// components/search/QueryResult/index.tsx
import ReactMarkdown from 'react-markdown';
import { SegmentCard } from '../SegmentCard';
import type { QueryResponse } from '@/types/api.types';

interface QueryResultProps {
  result: QueryResponse;
}

export function QueryResult({ result }: QueryResultProps) {
  const { answer, segments, meta, graph_context } = result;

  return (
    <div className="mt-8 space-y-8 animate-fade-in">
      {/* LLM 回答區塊 */}
      <section>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-6 bg-primary-600 rounded"></span>
          回答
        </h2>
        <div className="bg-white dark:bg-gray-800 p-6 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700">
          <article className="prose prose-lg dark:prose-invert max-w-none">
            <ReactMarkdown>{answer}</ReactMarkdown>
          </article>
        </div>
      </section>

      {/* 相關經文段落 */}
      <section>
        <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
          <span className="w-1 h-6 bg-bible-gold rounded"></span>
          相關經文 ({segments.length})
        </h2>
        <div className="space-y-4">
          {segments.map((segment) => (
            <SegmentCard key={segment.id} segment={segment} />
          ))}
        </div>
      </section>

      {/* 知識圖譜上下文 */}
      {graph_context && (
        <section>
          <h2 className="text-xl font-semibold mb-4">相關主題與人物</h2>
          <div className="flex flex-wrap gap-2">
            {graph_context.related_topics?.map((topic) => (
              <span
                key={topic}
                className="px-3 py-1 bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200 rounded-full text-sm"
              >
                {topic}
              </span>
            ))}
            {graph_context.related_persons?.map((person) => (
              <span
                key={person}
                className="px-3 py-1 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded-full text-sm"
              >
                {person}
              </span>
            ))}
          </div>
        </section>
      )}

      {/* 元資料 */}
      <section className="text-sm text-gray-500 dark:text-gray-400 border-t pt-4">
        <div className="flex flex-wrap gap-4">
          <span>查詢類型: {meta.query_type}</span>
          <span>處理時間: {meta.total_processing_time_ms} ms</span>
          <span>檢索器: {meta.used_retrievers.join(', ')}</span>
          <span>模型: {meta.llm_model}</span>
        </div>
      </section>
    </div>
  );
}
```

---

### 3.4 SegmentCard - 相關段落卡片

**功能描述**: 顯示單個相關經文段落的卡片。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| segment | PericopeSegment | 是 | 段落資料 |

**程式碼範例**:

```tsx
// components/search/SegmentCard/index.tsx
import { Link } from 'react-router-dom';
import type { PericopeSegment } from '@/types/api.types';

interface SegmentCardProps {
  segment: PericopeSegment;
}

export function SegmentCard({ segment }: SegmentCardProps) {
  const reference = `${segment.book} ${segment.chapter_start}:${segment.verse_start}${
    segment.chapter_end !== segment.chapter_start || segment.verse_end !== segment.verse_start
      ? `-${segment.chapter_end !== segment.chapter_start ? `${segment.chapter_end}:` : ''}${segment.verse_end}`
      : ''
  }`;

  const relevancePercent = Math.round(segment.relevance_score * 100);

  return (
    <Link
      to={`/pericope/${segment.id}`}
      className="block bg-bible-parchment dark:bg-gray-800 rounded-lg p-4 border border-bible-gold/30 hover:shadow-md transition-shadow"
    >
      <div className="flex items-start justify-between mb-2">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-gray-100">
            {segment.title}
          </h3>
          <p className="text-sm text-gray-600 dark:text-gray-400">
            {reference}
          </p>
        </div>
        <span className="text-xs px-2 py-1 bg-primary-100 dark:bg-primary-900 text-primary-700 dark:text-primary-300 rounded">
          {relevancePercent}% 相關
        </span>
      </div>

      <p className="text-gray-700 dark:text-gray-300 font-serif leading-relaxed line-clamp-3">
        {segment.text_excerpt}
      </p>
    </Link>
  );
}
```

---

## 4. 聖經瀏覽元件 (Bible)

### 4.1 BookSelector - 書卷選擇器

**功能描述**: 以分組方式顯示 66 卷書供使用者選擇。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| selectedBookId | number \| null | 否 | 當前選中的書卷 ID |
| onSelect | (bookId: number) => void | 否 | 選擇書卷回調 (預設導航) |

**書卷分組**:

| 分類 | 書卷數 | 範圍 |
|------|--------|------|
| 律法書 | 5 | 創世記 - 申命記 |
| 歷史書 | 12 | 約書亞記 - 以斯帖記 |
| 詩歌智慧書 | 5 | 約伯記 - 雅歌 |
| 大先知書 | 5 | 以賽亞書 - 但以理書 |
| 小先知書 | 12 | 何西阿書 - 瑪拉基書 |
| 福音書 | 4 | 馬太福音 - 約翰福音 |
| 使徒行傳 | 1 | 使徒行傳 |
| 保羅書信 | 13 | 羅馬書 - 腓利門書 |
| 普通書信 | 8 | 希伯來書 - 猶大書 |
| 啟示錄 | 1 | 啟示錄 |

**程式碼範例**:

```tsx
// components/bible/BookSelector/index.tsx
import { Link } from 'react-router-dom';
import { useBooks } from '@/hooks/api/useBooks';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

export function BookSelector() {
  const { data, isLoading, error } = useBooks();

  if (isLoading) return <LoadingSpinner />;
  if (error) return <div className="text-red-500">載入失敗</div>;

  const books = data?.books || [];
  const otBooks = books.filter((b) => b.testament === 'OT');
  const ntBooks = books.filter((b) => b.testament === 'NT');

  return (
    <div className="space-y-8">
      {/* 舊約 */}
      <section>
        <h2 className="text-xl font-bold text-bible-ot mb-4 flex items-center gap-2">
          <span className="w-2 h-2 bg-bible-ot rounded-full"></span>
          舊約聖經 ({otBooks.length} 卷)
        </h2>
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2">
          {otBooks.map((book) => (
            <Link
              key={book.id}
              to={`/browse/${book.id}`}
              className="
                p-3 text-center rounded-lg border border-bible-ot/30
                bg-white dark:bg-gray-800
                hover:bg-bible-ot/10 hover:border-bible-ot
                transition-colors
              "
            >
              <div className="font-medium">{book.abbrev_zh}</div>
              <div className="text-xs text-gray-500 mt-1">{book.name_zh}</div>
            </Link>
          ))}
        </div>
      </section>

      {/* 新約 */}
      <section>
        <h2 className="text-xl font-bold text-bible-nt mb-4 flex items-center gap-2">
          <span className="w-2 h-2 bg-bible-nt rounded-full"></span>
          新約聖經 ({ntBooks.length} 卷)
        </h2>
        <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-8 gap-2">
          {ntBooks.map((book) => (
            <Link
              key={book.id}
              to={`/browse/${book.id}`}
              className="
                p-3 text-center rounded-lg border border-bible-nt/30
                bg-white dark:bg-gray-800
                hover:bg-bible-nt/10 hover:border-bible-nt
                transition-colors
              "
            >
              <div className="font-medium">{book.abbrev_zh}</div>
              <div className="text-xs text-gray-500 mt-1">{book.name_zh}</div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
```

---

### 4.2 ChapterGrid - 章節網格

**功能描述**: 以網格方式顯示書卷的所有章節。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| bookId | number | 是 | 書卷 ID |
| bookName | string | 是 | 書卷名稱 |
| chapters | ChapterInfo[] | 是 | 章節資訊列表 |

**程式碼範例**:

```tsx
// components/bible/ChapterGrid/index.tsx
import { Link } from 'react-router-dom';
import type { ChapterInfo } from '@/types/api.types';

interface ChapterGridProps {
  bookId: number;
  bookName: string;
  chapters: ChapterInfo[];
}

export function ChapterGrid({ bookId, bookName, chapters }: ChapterGridProps) {
  return (
    <div>
      <p className="text-gray-600 dark:text-gray-400 mb-4">
        共 {chapters.length} 章
      </p>
      <div className="grid grid-cols-5 sm:grid-cols-8 md:grid-cols-10 lg:grid-cols-12 gap-2">
        {chapters.map((chapter) => (
          <Link
            key={chapter.chapter}
            to={`/browse/${bookId}/${chapter.chapter}`}
            className="
              aspect-square flex flex-col items-center justify-center
              rounded-lg border border-gray-200 dark:border-gray-700
              bg-white dark:bg-gray-800
              hover:bg-primary-50 dark:hover:bg-primary-900/20 hover:border-primary-300
              transition-colors
            "
          >
            <span className="text-lg font-medium">{chapter.chapter}</span>
            <span className="text-xs text-gray-500">{chapter.verse_count} 節</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
```

---

### 4.3 VerseList - 經文列表

**功能描述**: 顯示特定章節的所有經文。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| bookId | number | 是 | 書卷 ID |
| bookName | string | 是 | 書卷名稱 |
| chapter | number | 是 | 章節號 |
| verses | VerseItem[] | 是 | 經文列表 |
| totalChapters | number | 是 | 書卷總章數 |
| highlightVerseId | number | 否 | 高亮顯示的經文 ID |

**程式碼範例**:

```tsx
// components/bible/VerseList/index.tsx
import { Link } from 'react-router-dom';
import type { VerseItem } from '@/types/api.types';

interface VerseListProps {
  bookId: number;
  bookName: string;
  chapter: number;
  verses: VerseItem[];
  totalChapters: number;
  highlightVerseId?: number;
}

export function VerseList({
  bookId,
  bookName,
  chapter,
  verses,
  totalChapters,
  highlightVerseId,
}: VerseListProps) {
  return (
    <div>
      {/* 章節標題 */}
      <h1 className="text-2xl font-bold mb-6">
        {bookName} 第 {chapter} 章
      </h1>

      {/* 經文內容 */}
      <div className="bg-bible-parchment dark:bg-gray-800 rounded-lg p-6 shadow-sm">
        <div className="verse-text space-y-2">
          {verses.map((verse) => (
            <p
              key={verse.id}
              id={`verse-${verse.id}`}
              className={`
                ${highlightVerseId === verse.id ? 'bg-yellow-100 dark:bg-yellow-900/30 -mx-2 px-2 py-1 rounded' : ''}
              `}
            >
              <span className="verse-number">{verse.verse}</span>
              {verse.text}
            </p>
          ))}
        </div>
      </div>

      {/* 章節導航 */}
      <div className="flex justify-between mt-6">
        {chapter > 1 ? (
          <Link
            to={`/browse/${bookId}/${chapter - 1}`}
            className="btn-secondary"
          >
            ← 上一章
          </Link>
        ) : (
          <div />
        )}

        {chapter < totalChapters && (
          <Link
            to={`/browse/${bookId}/${chapter + 1}`}
            className="btn-secondary"
          >
            下一章 →
          </Link>
        )}
      </div>
    </div>
  );
}
```

---

### 4.4 PericopeCard - 段落卡片

**功能描述**: 顯示段落的摘要資訊卡片。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| pericope | PericopeListItem | 是 | 段落資料 |
| showBook | boolean | 否 | 是否顯示書卷名稱 |

---

## 5. 圖譜元件 (Graph)

### 5.1 GraphViewer - 圖譜視覺化

**功能描述**: 使用 D3.js 渲染知識圖譜力導向圖。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| nodes | GraphNode[] | 是 | 節點資料 |
| edges | GraphEdge[] | 是 | 邊資料 |
| onNodeClick | (nodeId: string) => void | 否 | 節點點擊回調 |
| centerNodeId | string | 否 | 中心節點 ID |
| width | number | 否 | 畫布寬度 (預設 800) |
| height | number | 否 | 畫布高度 (預設 600) |

**節點類型顏色對應**:

| 類型 | 顏色 | 說明 |
|------|------|------|
| Person | #E57373 (紅) | 人物節點 |
| Place | #64B5F6 (藍) | 地點節點 |
| Group | #BA68C8 (紫) | 群體節點 |
| Event | #FFB74D (橙) | 事件節點 |
| Topic | #81C784 (綠) | 主題節點 |

**程式碼範例**:

```tsx
// components/graph/GraphViewer/index.tsx
import { useRef, useEffect } from 'react';
import * as d3 from 'd3';
import type { GraphNode, GraphEdge } from '@/types/api.types';

interface GraphViewerProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeClick?: (nodeId: string) => void;
  centerNodeId?: string;
  width?: number;
  height?: number;
}

const nodeColors: Record<string, string> = {
  Person: '#E57373',
  Place: '#64B5F6',
  Group: '#BA68C8',
  Event: '#FFB74D',
  Topic: '#81C784',
};

export function GraphViewer({
  nodes,
  edges,
  onNodeClick,
  centerNodeId,
  width = 800,
  height = 600,
}: GraphViewerProps) {
  const svgRef = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll('*').remove();

    // 建立力導向模擬
    const simulation = d3
      .forceSimulation(nodes as d3.SimulationNodeDatum[])
      .force('link', d3.forceLink(edges).id((d: any) => d.id).distance(100))
      .force('charge', d3.forceManyBody().strength(-300))
      .force('center', d3.forceCenter(width / 2, height / 2));

    // 繪製邊
    const link = svg
      .append('g')
      .selectAll('line')
      .data(edges)
      .join('line')
      .attr('stroke', '#999')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 1);

    // 繪製節點
    const node = svg
      .append('g')
      .selectAll('g')
      .data(nodes)
      .join('g')
      .call(drag(simulation) as any)
      .on('click', (event, d) => {
        if (onNodeClick) onNodeClick(d.id);
      });

    // 節點圓圈
    node
      .append('circle')
      .attr('r', (d) => (d.id === centerNodeId ? 20 : 12))
      .attr('fill', (d) => nodeColors[d.type] || '#999')
      .attr('stroke', '#fff')
      .attr('stroke-width', 2);

    // 節點標籤
    node
      .append('text')
      .text((d) => d.label)
      .attr('x', 15)
      .attr('y', 4)
      .attr('font-size', 12)
      .attr('fill', '#333');

    // 更新位置
    simulation.on('tick', () => {
      link
        .attr('x1', (d: any) => d.source.x)
        .attr('y1', (d: any) => d.source.y)
        .attr('x2', (d: any) => d.target.x)
        .attr('y2', (d: any) => d.target.y);

      node.attr('transform', (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, edges, width, height, centerNodeId, onNodeClick]);

  // 拖曳行為
  function drag(simulation: d3.Simulation<d3.SimulationNodeDatum, undefined>) {
    return d3
      .drag()
      .on('start', (event) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
      })
      .on('drag', (event) => {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
      })
      .on('end', (event) => {
        if (!event.active) simulation.alphaTarget(0);
        event.subject.fx = null;
        event.subject.fy = null;
      });
  }

  return (
    <div className="border rounded-lg bg-white dark:bg-gray-800 overflow-hidden">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="w-full h-auto"
        style={{ maxHeight: '70vh' }}
      />

      {/* 圖例 */}
      <div className="flex flex-wrap gap-4 p-4 border-t">
        {Object.entries(nodeColors).map(([type, color]) => (
          <div key={type} className="flex items-center gap-2">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: color }}
            />
            <span className="text-sm text-gray-600 dark:text-gray-400">
              {type === 'Person' && '人物'}
              {type === 'Place' && '地點'}
              {type === 'Group' && '群體'}
              {type === 'Event' && '事件'}
              {type === 'Topic' && '主題'}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
```

---

### 5.2 EntityPanel - 實體資訊面板

**功能描述**: 顯示選中實體的詳細資訊。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| entityId | number | 是 | 實體 ID |
| onClose | () => void | 否 | 關閉面板回調 |

---

### 5.3 TopicPanel - 主題資訊面板

**功能描述**: 顯示選中主題的詳細資訊和相關主題。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| topicId | number | 是 | 主題 ID |
| onClose | () => void | 否 | 關閉面板回調 |

---

## 6. 共用元件 (Common)

### 6.1 Button - 按鈕

**功能描述**: 可重用的按鈕元件。

**Props**:

| Prop | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| variant | `'primary'` \| `'secondary'` \| `'ghost'` \| `'danger'` | 否 | `'primary'` | 樣式變體 |
| size | `'sm'` \| `'md'` \| `'lg'` | 否 | `'md'` | 尺寸 |
| disabled | boolean | 否 | `false` | 禁用狀態 |
| loading | boolean | 否 | `false` | 載入狀態 |
| children | ReactNode | 是 | - | 按鈕內容 |
| onClick | () => void | 否 | - | 點擊回調 |

---

### 6.2 Card - 卡片

**功能描述**: 內容容器卡片。

**Props**:

| Prop | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| children | ReactNode | 是 | - | 卡片內容 |
| className | string | 否 | `''` | 額外 CSS 類別 |
| padding | `'none'` \| `'sm'` \| `'md'` \| `'lg'` | 否 | `'md'` | 內距 |

---

### 6.3 Input - 輸入框

**功能描述**: 表單輸入框元件。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| type | string | 否 | 輸入類型 |
| value | string | 是 | 輸入值 |
| onChange | (value: string) => void | 是 | 變更回調 |
| placeholder | string | 否 | 佔位文字 |
| disabled | boolean | 否 | 禁用狀態 |
| error | string | 否 | 錯誤訊息 |
| label | string | 否 | 標籤文字 |

---

### 6.4 LoadingSpinner - 載入指示器

**功能描述**: 載入中的旋轉指示器。

**Props**:

| Prop | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| size | `'sm'` \| `'md'` \| `'lg'` | 否 | `'md'` | 尺寸 |
| className | string | 否 | `''` | 額外 CSS 類別 |

**程式碼範例**:

```tsx
// components/common/LoadingSpinner/index.tsx
interface LoadingSpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

const sizeClasses = {
  sm: 'w-4 h-4',
  md: 'w-8 h-8',
  lg: 'w-12 h-12',
};

export function LoadingSpinner({ size = 'md', className = '' }: LoadingSpinnerProps) {
  return (
    <div
      className={`
        ${sizeClasses[size]}
        border-2 border-gray-200 border-t-primary-600
        rounded-full animate-spin
        ${className}
      `}
      role="status"
      aria-label="載入中"
    />
  );
}
```

---

### 6.5 ErrorBoundary - 錯誤邊界

**功能描述**: 捕獲子元件的 JavaScript 錯誤並顯示錯誤訊息。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| children | ReactNode | 是 | 子元件 |
| fallback | ReactNode | 否 | 錯誤時顯示的元件 |
| onError | (error: Error, errorInfo: ErrorInfo) => void | 否 | 錯誤回調 |

**程式碼範例**:

```tsx
// components/common/ErrorBoundary/index.tsx
import { Component, ErrorInfo, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        this.props.fallback || (
          <div className="p-6 bg-red-50 dark:bg-red-900/20 rounded-lg border border-red-200 dark:border-red-800">
            <h2 className="text-xl font-bold text-red-700 dark:text-red-400">
              發生錯誤
            </h2>
            <p className="mt-2 text-red-600 dark:text-red-300">
              {this.state.error?.message || '未知錯誤'}
            </p>
            <button
              onClick={() => this.setState({ hasError: false, error: null })}
              className="mt-4 btn-secondary"
            >
              重試
            </button>
          </div>
        )
      );
    }

    return this.props.children;
  }
}
```

---

### 6.6 Pagination - 分頁元件

**功能描述**: 分頁導航元件。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| currentPage | number | 是 | 當前頁碼 |
| totalPages | number | 是 | 總頁數 |
| onPageChange | (page: number) => void | 是 | 頁碼變更回調 |
| siblingsCount | number | 否 | 顯示的相鄰頁數 (預設 1) |

---

### 6.7 Breadcrumb - 麵包屑導航

**功能描述**: 顯示當前頁面的路徑導航。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| items | BreadcrumbItem[] | 是 | 麵包屑項目 |

**BreadcrumbItem 型別**:

```typescript
interface BreadcrumbItem {
  label: string;
  href?: string;
}
```

**程式碼範例**:

```tsx
// components/common/Breadcrumb/index.tsx
import { Link } from 'react-router-dom';
import { ChevronRightIcon } from '@/components/icons';

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbProps {
  items: BreadcrumbItem[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <nav className="flex items-center gap-2 text-sm text-gray-500 dark:text-gray-400 mb-4">
      {items.map((item, index) => (
        <span key={index} className="flex items-center gap-2">
          {index > 0 && <ChevronRightIcon className="w-4 h-4" />}
          {item.href ? (
            <Link
              to={item.href}
              className="hover:text-primary-600 transition-colors"
            >
              {item.label}
            </Link>
          ) : (
            <span className="text-gray-900 dark:text-gray-100 font-medium">
              {item.label}
            </span>
          )}
        </span>
      ))}
    </nav>
  );
}
```

---

### 6.8 LoadingOverlay - 載入遮罩

**功能描述**: 全頁面載入遮罩，用於長時間操作 (如 RAG 查詢)。

**Props**:

| Prop | 類型 | 必填 | 說明 |
|------|------|------|------|
| message | string | 否 | 載入訊息 |

**程式碼範例**:

```tsx
// components/common/LoadingOverlay/index.tsx
import { LoadingSpinner } from '../LoadingSpinner';

interface LoadingOverlayProps {
  message?: string;
}

export function LoadingOverlay({ message = '載入中...' }: LoadingOverlayProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-gray-800 rounded-lg p-8 shadow-xl flex flex-col items-center gap-4">
        <LoadingSpinner size="lg" />
        <p className="text-gray-700 dark:text-gray-300">{message}</p>
      </div>
    </div>
  );
}
```

---

## 附錄

### A. 元件總覽表

| 分類 | 元件名稱 | 檔案路徑 |
|------|----------|----------|
| Pages | SearchPage | `pages/SearchPage/index.tsx` |
| Pages | BrowsePage | `pages/BrowsePage/index.tsx` |
| Pages | GraphPage | `pages/GraphPage/index.tsx` |
| Pages | DetailPage | `pages/DetailPage/index.tsx` |
| Layouts | MainLayout | `components/layout/MainLayout/index.tsx` |
| Layouts | Header | `components/layout/Header/index.tsx` |
| Layouts | Sidebar | `components/layout/Sidebar/index.tsx` |
| Search | SearchBar | `components/search/SearchBar/index.tsx` |
| Search | QueryModeSelector | `components/search/QueryModeSelector/index.tsx` |
| Search | QueryResult | `components/search/QueryResult/index.tsx` |
| Search | SegmentCard | `components/search/SegmentCard/index.tsx` |
| Bible | BookSelector | `components/bible/BookSelector/index.tsx` |
| Bible | ChapterGrid | `components/bible/ChapterGrid/index.tsx` |
| Bible | VerseList | `components/bible/VerseList/index.tsx` |
| Bible | PericopeCard | `components/bible/PericopeCard/index.tsx` |
| Graph | GraphViewer | `components/graph/GraphViewer/index.tsx` |
| Graph | EntityPanel | `components/graph/EntityPanel/index.tsx` |
| Graph | TopicPanel | `components/graph/TopicPanel/index.tsx` |
| Common | Button | `components/common/Button/index.tsx` |
| Common | Card | `components/common/Card/index.tsx` |
| Common | Input | `components/common/Input/index.tsx` |
| Common | LoadingSpinner | `components/common/LoadingSpinner/index.tsx` |
| Common | ErrorBoundary | `components/common/ErrorBoundary/index.tsx` |
| Common | Pagination | `components/common/Pagination/index.tsx` |
| Common | Breadcrumb | `components/common/Breadcrumb/index.tsx` |
| Common | LoadingOverlay | `components/common/LoadingOverlay/index.tsx` |

---

*文件版本: 1.0.0*
*最後更新: 2025-12-25*
