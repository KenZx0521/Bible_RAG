# Bible RAG 前端架構規格文件

> 版本：v1.0.0
> 更新日期：2025-12-25
> 對應後端版本：v1.0.0

---

## 目錄

1. [概述](#1-概述)
2. [專案結構](#2-專案結構)
3. [元件架構](#3-元件架構)
4. [狀態管理](#4-狀態管理)
5. [路由設計](#5-路由設計)
6. [API 層封裝](#6-api-層封裝)
7. [樣式解決方案](#7-樣式解決方案)
8. [效能優化](#8-效能優化)
9. [開發規範](#9-開發規範)

---

## 1. 概述

### 1.1 系統簡介

Bible RAG 前端是基於 React 的單頁應用程式 (SPA)，提供：

- **RAG 智慧問答**：自然語言問答介面，展示 LLM 生成的答案和相關經文
- **聖經瀏覽**：書卷、章節、經文的結構化導航
- **知識圖譜視覺化**：人物、地點、事件、主題的關係探索
- **經文搜尋**：全文搜尋功能

### 1.2 技術棧版本

| 技術 | 版本 | 用途 |
|------|------|------|
| React | 19.x | UI 框架 |
| TypeScript | 5.9+ | 型別系統 |
| Vite | 7.x (rolldown) | 建構工具 |
| TanStack Query | 5.x | 伺服器狀態管理 |
| Zustand | 4.x | 客戶端狀態管理 |
| React Router | 7.x | 路由管理 |
| Tailwind CSS | 4.x | CSS 框架 |
| Shadcn/ui | latest | UI 元件庫 |
| D3.js | 7.x | 圖譜視覺化 |
| Axios | 1.x | HTTP 客戶端 |
| React Markdown | 9.x | Markdown 渲染 |

### 1.3 設計原則

| 原則 | 說明 |
|------|------|
| **元件化設計** | 將 UI 拆分為可重用的獨立元件 |
| **關注點分離** | 視圖、邏輯、資料獲取明確分離 |
| **型別安全** | 全面使用 TypeScript 確保型別正確性 |
| **漸進式增強** | 優先考慮核心功能，再添加進階特性 |
| **效能優先** | 程式碼分割、快取策略、虛擬化列表 |

---

## 2. 專案結構

### 2.1 目錄架構

```
frontend/
├── public/                     # 靜態資源
│   ├── favicon.ico
│   └── fonts/                  # 字型檔案
├── src/
│   ├── api/                    # API 層
│   │   ├── client.ts           # Axios 客戶端配置
│   │   ├── endpoints/          # API 端點定義
│   │   │   ├── index.ts
│   │   │   ├── query.ts        # RAG 查詢 API
│   │   │   ├── books.ts        # 書卷 API
│   │   │   ├── pericopes.ts    # 段落 API
│   │   │   ├── verses.ts       # 經文 API
│   │   │   └── graph.ts        # 知識圖譜 API
│   │   └── index.ts
│   ├── components/             # 共用元件
│   │   ├── common/             # 基礎元件
│   │   │   ├── Button/
│   │   │   ├── Card/
│   │   │   ├── Input/
│   │   │   ├── LoadingSpinner/
│   │   │   ├── ErrorBoundary/
│   │   │   ├── Pagination/
│   │   │   └── index.ts
│   │   ├── layout/             # 佈局元件
│   │   │   ├── MainLayout/
│   │   │   ├── Header/
│   │   │   ├── Sidebar/
│   │   │   └── index.ts
│   │   ├── search/             # 搜尋相關
│   │   │   ├── SearchBar/
│   │   │   ├── QueryModeSelector/
│   │   │   ├── QueryResult/
│   │   │   ├── SegmentCard/
│   │   │   └── index.ts
│   │   ├── bible/              # 聖經瀏覽相關
│   │   │   ├── BookSelector/
│   │   │   ├── ChapterGrid/
│   │   │   ├── VerseList/
│   │   │   ├── PericopeCard/
│   │   │   └── index.ts
│   │   └── graph/              # 圖譜相關
│   │       ├── GraphViewer/
│   │       ├── EntityPanel/
│   │       ├── TopicPanel/
│   │       └── index.ts
│   ├── hooks/                  # 自定義 Hooks
│   │   ├── api/                # TanStack Query hooks
│   │   │   ├── useBooks.ts
│   │   │   ├── useVerses.ts
│   │   │   ├── usePericopes.ts
│   │   │   ├── useGraph.ts
│   │   │   ├── useRagQuery.ts
│   │   │   └── index.ts
│   │   ├── useDebounce.ts
│   │   ├── useLocalStorage.ts
│   │   └── index.ts
│   ├── pages/                  # 頁面元件
│   │   ├── SearchPage/
│   │   ├── BrowsePage/
│   │   ├── GraphPage/
│   │   ├── DetailPage/
│   │   └── index.ts
│   ├── stores/                 # Zustand 狀態
│   │   ├── useAppStore.ts      # 應用程式狀態
│   │   ├── useSearchStore.ts   # 搜尋狀態
│   │   └── index.ts
│   ├── types/                  # TypeScript 型別
│   │   ├── api.types.ts        # API 請求/回應型別
│   │   ├── domain.types.ts     # 領域模型型別
│   │   ├── component.types.ts  # 元件 Props 型別
│   │   └── index.ts
│   ├── utils/                  # 工具函數
│   │   ├── formatters.ts       # 格式化工具
│   │   ├── validators.ts       # 驗證工具
│   │   ├── constants.ts        # 常數定義
│   │   └── index.ts
│   ├── lib/                    # 第三方庫封裝
│   │   ├── queryClient.ts      # TanStack Query 配置
│   │   └── index.ts
│   ├── App.tsx                 # 應用程式根元件
│   ├── main.tsx                # 應用程式入口
│   ├── router.tsx              # 路由配置
│   └── index.css               # 全域樣式
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── vite.config.ts
└── .env                        # 環境變數
```

### 2.2 檔案命名規範

| 類型 | 命名規則 | 範例 |
|------|----------|------|
| 元件檔案 | PascalCase | `SearchBar.tsx` |
| 元件目錄 | PascalCase | `SearchBar/index.tsx` |
| Hooks | camelCase + use 前綴 | `useBooks.ts` |
| 型別檔案 | camelCase + .types.ts | `api.types.ts` |
| 工具函數 | camelCase | `formatters.ts` |
| 常數 | UPPER_SNAKE_CASE | `API_BASE_URL` |
| CSS 模組 | camelCase + .module.css | `styles.module.css` |

### 2.3 元件目錄結構

每個元件使用獨立目錄：

```
SearchBar/
├── index.tsx           # 元件主體
├── SearchBar.types.ts  # 元件型別定義 (選用)
├── SearchBar.test.tsx  # 單元測試 (選用)
└── styles.module.css   # 元件樣式 (選用)
```

---

## 3. 元件架構

### 3.1 元件層次結構

```
┌─────────────────────────────────────────────────────────────────┐
│                           App.tsx                                │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │                    QueryClientProvider                       │ │
│  │  ┌─────────────────────────────────────────────────────────┐ │ │
│  │  │                     RouterProvider                       │ │ │
│  │  │  ┌─────────────────────────────────────────────────────┐ │ │ │
│  │  │  │                    MainLayout                        │ │ │ │
│  │  │  │  ┌──────────┐  ┌──────────────────────────────────┐ │ │ │ │
│  │  │  │  │  Header  │  │            Content                │ │ │ │ │
│  │  │  │  └──────────┘  │  ┌──────────────────────────────┐ │ │ │ │ │
│  │  │  │  ┌──────────┐  │  │           Pages               │ │ │ │ │ │
│  │  │  │  │ Sidebar  │  │  │  ┌────────────────────────┐  │ │ │ │ │ │
│  │  │  │  │          │  │  │  │  SearchPage            │  │ │ │ │ │ │
│  │  │  │  │          │  │  │  │  BrowsePage            │  │ │ │ │ │ │
│  │  │  │  │          │  │  │  │  GraphPage             │  │ │ │ │ │ │
│  │  │  │  │          │  │  │  │  DetailPage            │  │ │ │ │ │ │
│  │  │  │  │          │  │  │  └────────────────────────┘  │ │ │ │ │ │
│  │  │  │  └──────────┘  │  └──────────────────────────────┘ │ │ │ │ │
│  │  │  │                └──────────────────────────────────┘ │ │ │ │
│  │  │  └─────────────────────────────────────────────────────┘ │ │ │
│  │  └─────────────────────────────────────────────────────────┘ │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 元件分類

| 分類 | 說明 | 範例 |
|------|------|------|
| **Pages** | 對應路由的頁面元件 | SearchPage, BrowsePage, GraphPage |
| **Layouts** | 頁面佈局容器 | MainLayout, Header, Sidebar |
| **Features** | 特定功能的複合元件 | SearchBar, GraphViewer, BookSelector |
| **Common** | 可重用的基礎元件 | Button, Card, Input, LoadingSpinner |

### 3.3 元件通訊模式

```
┌────────────────────────────────────────────────────────────┐
│                      Props (父→子)                          │
│  ┌──────────────┐                    ┌──────────────┐      │
│  │   Parent     │ ───── props ────→ │    Child     │      │
│  └──────────────┘                    └──────────────┘      │
├────────────────────────────────────────────────────────────┤
│                    Callbacks (子→父)                        │
│  ┌──────────────┐                    ┌──────────────┐      │
│  │   Parent     │ ←── callback ──── │    Child     │      │
│  └──────────────┘                    └──────────────┘      │
├────────────────────────────────────────────────────────────┤
│                   Context/Store (跨層級)                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │    Store     │ ←→│  Component  │ ←→│  Component  │      │
│  │  (Zustand)   │   │      A      │   │      B      │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
├────────────────────────────────────────────────────────────┤
│                   TanStack Query (API 狀態)                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐      │
│  │  Query Cache │ ←→│  Component  │ ←→│  Component  │      │
│  └──────────────┘  └──────────────┘  └──────────────┘      │
└────────────────────────────────────────────────────────────┘
```

---

## 4. 狀態管理

### 4.1 狀態分層策略

```
┌─────────────────────────────────────────────────────────────────┐
│                        狀態管理架構                               │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              TanStack Query (伺服器狀態)                   │   │
│  │                                                          │   │
│  │  • API 請求快取                                           │   │
│  │  • 自動重新獲取 (refetch)                                 │   │
│  │  • 樂觀更新 (optimistic updates)                         │   │
│  │  • 背景同步 (background sync)                            │   │
│  │                                                          │   │
│  │  適用：書卷、經文、段落、圖譜等 API 資料                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                 Zustand (客戶端狀態)                      │   │
│  │                                                          │   │
│  │  • UI 狀態 (側邊欄開關、主題切換)                         │   │
│  │  • 使用者偏好設定                                         │   │
│  │  • 暫存的表單資料                                         │   │
│  │  • 當前選中項目                                           │   │
│  │                                                          │   │
│  │  適用：不需要持久化的應用狀態                              │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                React State (元件狀態)                     │   │
│  │                                                          │   │
│  │  • 表單輸入值                                             │   │
│  │  • 元件內部 UI 狀態 (展開/收合、hover)                    │   │
│  │  • 臨時性的本地狀態                                       │   │
│  │                                                          │   │
│  │  適用：單一元件內的狀態                                    │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 TanStack Query 配置

```typescript
// src/lib/queryClient.ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // 資料過期時間
      staleTime: 5 * 60 * 1000, // 5 分鐘
      // 快取保留時間
      gcTime: 30 * 60 * 1000, // 30 分鐘
      // 失敗重試次數
      retry: 2,
      // 視窗聚焦時重新獲取
      refetchOnWindowFocus: false,
    },
    mutations: {
      // mutation 失敗重試
      retry: 1,
    },
  },
});
```

### 4.3 Query 快取策略

| 資料類型 | staleTime | gcTime | 說明 |
|----------|-----------|--------|------|
| 書卷列表 | Infinity | 24h | 靜態資料，不常變動 |
| 章節列表 | Infinity | 24h | 靜態資料 |
| 經文內容 | 5min | 30min | 標準快取 |
| 段落內容 | 5min | 30min | 標準快取 |
| 圖譜資料 | 5min | 15min | 較短快取，確保新鮮 |
| RAG 查詢 | 0 | 5min | 不快取，每次重新查詢 |

### 4.4 Zustand Store 設計

```typescript
// src/stores/useAppStore.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface AppState {
  // UI 狀態
  sidebarOpen: boolean;
  theme: 'light' | 'dark' | 'system';

  // 當前選中
  selectedBookId: number | null;
  selectedChapter: number | null;

  // Actions
  toggleSidebar: () => void;
  setTheme: (theme: 'light' | 'dark' | 'system') => void;
  selectBook: (bookId: number | null) => void;
  selectChapter: (chapter: number | null) => void;
  reset: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      // 初始狀態
      sidebarOpen: true,
      theme: 'system',
      selectedBookId: null,
      selectedChapter: null,

      // Actions
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setTheme: (theme) => set({ theme }),
      selectBook: (bookId) => set({ selectedBookId: bookId, selectedChapter: null }),
      selectChapter: (chapter) => set({ selectedChapter: chapter }),
      reset: () => set({
        selectedBookId: null,
        selectedChapter: null,
      }),
    }),
    {
      name: 'bible-rag-app',
      partialize: (state) => ({
        theme: state.theme,
        sidebarOpen: state.sidebarOpen,
      }),
    }
  )
);
```

---

## 5. 路由設計

### 5.1 路由結構

| 路徑 | 頁面元件 | 說明 |
|------|----------|------|
| `/` | SearchPage | 首頁，RAG 智慧問答 |
| `/browse` | BrowsePage | 聖經瀏覽 (書卷列表) |
| `/browse/:bookId` | BrowsePage | 特定書卷 (章節列表) |
| `/browse/:bookId/:chapter` | BrowsePage | 特定章節 (經文列表) |
| `/pericope/:id` | DetailPage | 段落詳情 |
| `/verse/:id` | DetailPage | 經文詳情 |
| `/graph` | GraphPage | 知識圖譜首頁 |
| `/graph/entity/:id` | GraphPage | 實體詳情 (人物/地點/群體/事件) |
| `/graph/topic/:id` | GraphPage | 主題詳情 |
| `/search` | SearchPage | 經文搜尋結果 |

### 5.2 路由配置

```typescript
// src/router.tsx
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { lazy, Suspense } from 'react';
import { MainLayout } from '@/components/layout';
import { LoadingSpinner } from '@/components/common';

// 懶載入頁面元件
const SearchPage = lazy(() => import('@/pages/SearchPage'));
const BrowsePage = lazy(() => import('@/pages/BrowsePage'));
const GraphPage = lazy(() => import('@/pages/GraphPage'));
const DetailPage = lazy(() => import('@/pages/DetailPage'));

// 載入中元件
const PageLoader = () => (
  <div className="flex items-center justify-center h-screen">
    <LoadingSpinner size="lg" />
  </div>
);

export const router = createBrowserRouter([
  {
    path: '/',
    element: <MainLayout />,
    children: [
      {
        index: true,
        element: (
          <Suspense fallback={<PageLoader />}>
            <SearchPage />
          </Suspense>
        ),
      },
      {
        path: 'browse',
        element: (
          <Suspense fallback={<PageLoader />}>
            <BrowsePage />
          </Suspense>
        ),
      },
      {
        path: 'browse/:bookId',
        element: (
          <Suspense fallback={<PageLoader />}>
            <BrowsePage />
          </Suspense>
        ),
      },
      {
        path: 'browse/:bookId/:chapter',
        element: (
          <Suspense fallback={<PageLoader />}>
            <BrowsePage />
          </Suspense>
        ),
      },
      {
        path: 'pericope/:id',
        element: (
          <Suspense fallback={<PageLoader />}>
            <DetailPage type="pericope" />
          </Suspense>
        ),
      },
      {
        path: 'verse/:id',
        element: (
          <Suspense fallback={<PageLoader />}>
            <DetailPage type="verse" />
          </Suspense>
        ),
      },
      {
        path: 'graph',
        element: (
          <Suspense fallback={<PageLoader />}>
            <GraphPage />
          </Suspense>
        ),
      },
      {
        path: 'graph/entity/:id',
        element: (
          <Suspense fallback={<PageLoader />}>
            <GraphPage />
          </Suspense>
        ),
      },
      {
        path: 'graph/topic/:id',
        element: (
          <Suspense fallback={<PageLoader />}>
            <GraphPage />
          </Suspense>
        ),
      },
      {
        path: 'search',
        element: (
          <Suspense fallback={<PageLoader />}>
            <SearchPage />
          </Suspense>
        ),
      },
    ],
  },
]);
```

### 5.3 導航元件

```typescript
// 主要導航項目
const navItems = [
  { path: '/', label: '問答', icon: 'search' },
  { path: '/browse', label: '瀏覽', icon: 'book' },
  { path: '/graph', label: '圖譜', icon: 'network' },
];
```

---

## 6. API 層封裝

### 6.1 API Client 架構

```
┌─────────────────────────────────────────────────────────────────┐
│                         API 層架構                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │   Hooks      │ ──→ │   Endpoints  │ ──→ │   Client     │    │
│  │ (TanStack Q) │     │  (Functions) │     │   (Axios)    │    │
│  └──────────────┘     └──────────────┘     └──────────────┘    │
│         │                    │                    │             │
│         ▼                    ▼                    ▼             │
│  useBooks()           booksApi.getAll()    apiClient.get()     │
│  useVerses()          versesApi.search()   apiClient.post()    │
│  useRagQuery()        queryApi.execute()                        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 6.2 Axios Client 配置

```typescript
// src/api/client.ts
import axios, { AxiosError, AxiosInstance, AxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

// 建立 Axios 實例
export const apiClient: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 60000, // 60 秒 (RAG 查詢需要較長時間)
});

// 請求攔截器
apiClient.interceptors.request.use(
  (config) => {
    // 可在此添加認證 token
    // const token = getAuthToken();
    // if (token) {
    //   config.headers.Authorization = `Bearer ${token}`;
    // }
    return config;
  },
  (error) => Promise.reject(error)
);

// 回應攔截器
apiClient.interceptors.response.use(
  (response) => response.data,
  (error: AxiosError<{ detail: string }>) => {
    const message = error.response?.data?.detail || error.message || '發生未知錯誤';
    const status = error.response?.status;

    // 統一錯誤處理
    console.error(`API Error [${status}]:`, message);

    return Promise.reject(new Error(message));
  }
);

// 型別安全的請求方法
export const api = {
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    apiClient.get<unknown, T>(url, config),

  post: <T, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig) =>
    apiClient.post<unknown, T>(url, data, config),

  put: <T, D = unknown>(url: string, data?: D, config?: AxiosRequestConfig) =>
    apiClient.put<unknown, T>(url, data, config),

  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    apiClient.delete<unknown, T>(url, config),
};
```

### 6.3 API Endpoints 範例

```typescript
// src/api/endpoints/books.ts
import { api } from '../client';
import type { BooksListResponse, BookDetail, BookChaptersResponse } from '@/types/api.types';

export const booksApi = {
  /** 取得所有書卷列表 */
  getAll: () => api.get<BooksListResponse>('/books'),

  /** 取得書卷詳情 */
  getById: (bookId: number) => api.get<BookDetail>(`/books/${bookId}`),

  /** 取得書卷章節列表 */
  getChapters: (bookId: number) => api.get<BookChaptersResponse>(`/books/${bookId}/chapters`),

  /** 取得書卷段落列表 */
  getPericopes: (bookId: number) => api.get(`/books/${bookId}/pericopes`),

  /** 取得書卷經文 */
  getVerses: (bookId: number, chapter?: number) =>
    api.get(`/books/${bookId}/verses`, { params: { chapter } }),
};
```

```typescript
// src/api/endpoints/query.ts
import { api } from '../client';
import type { QueryRequest, QueryResponse } from '@/types/api.types';

export const queryApi = {
  /** 執行 RAG 查詢 */
  execute: (request: QueryRequest) =>
    api.post<QueryResponse>('/query', request),
};
```

### 6.4 Query Hooks 範例

```typescript
// src/hooks/api/useBooks.ts
import { useQuery } from '@tanstack/react-query';
import { booksApi } from '@/api/endpoints/books';
import { queryKeys } from './queryKeys';

/** 取得所有書卷 */
export function useBooks() {
  return useQuery({
    queryKey: queryKeys.books.all,
    queryFn: booksApi.getAll,
    staleTime: Infinity, // 書卷資料不會變動
  });
}

/** 取得書卷詳情 */
export function useBook(bookId: number) {
  return useQuery({
    queryKey: queryKeys.books.detail(bookId),
    queryFn: () => booksApi.getById(bookId),
    enabled: !!bookId,
  });
}

/** 取得書卷章節 */
export function useBookChapters(bookId: number) {
  return useQuery({
    queryKey: queryKeys.books.chapters(bookId),
    queryFn: () => booksApi.getChapters(bookId),
    enabled: !!bookId,
    staleTime: Infinity,
  });
}
```

```typescript
// src/hooks/api/useRagQuery.ts
import { useMutation } from '@tanstack/react-query';
import { queryApi } from '@/api/endpoints/query';
import type { QueryRequest, QueryResponse } from '@/types/api.types';

/** RAG 查詢 Mutation */
export function useRagQuery() {
  return useMutation<QueryResponse, Error, QueryRequest>({
    mutationFn: queryApi.execute,
    onError: (error) => {
      console.error('RAG 查詢失敗:', error.message);
    },
  });
}
```

### 6.5 Query Keys 定義

```typescript
// src/hooks/api/queryKeys.ts

export const queryKeys = {
  books: {
    all: ['books'] as const,
    detail: (id: number) => ['books', id] as const,
    chapters: (id: number) => ['books', id, 'chapters'] as const,
    pericopes: (id: number) => ['books', id, 'pericopes'] as const,
    verses: (id: number, chapter?: number) =>
      ['books', id, 'verses', { chapter }] as const,
  },
  pericopes: {
    all: ['pericopes'] as const,
    list: (params: { skip?: number; limit?: number; book_id?: number }) =>
      ['pericopes', 'list', params] as const,
    detail: (id: number) => ['pericopes', id] as const,
  },
  verses: {
    all: ['verses'] as const,
    list: (params: { skip?: number; limit?: number; book_id?: number; chapter?: number }) =>
      ['verses', 'list', params] as const,
    detail: (id: number) => ['verses', id] as const,
    search: (params: { q: string; book_id?: number; limit?: number }) =>
      ['verses', 'search', params] as const,
  },
  graph: {
    health: ['graph', 'health'] as const,
    stats: ['graph', 'stats'] as const,
    entitySearch: (params: { name?: string; type?: string; limit?: number }) =>
      ['graph', 'entity', 'search', params] as const,
    entity: (id: number) => ['graph', 'entity', id] as const,
    topicSearch: (params: { name?: string; type?: string; limit?: number }) =>
      ['graph', 'topic', 'search', params] as const,
    topic: (id: number) => ['graph', 'topic', id] as const,
    relationships: (params: { entity_id: number; entity_type: string; depth?: number }) =>
      ['graph', 'relationships', params] as const,
    verseEntities: (verseId: number) => ['graph', 'verse', verseId, 'entities'] as const,
  },
} as const;
```

---

## 7. 樣式解決方案

### 7.1 Tailwind CSS 配置

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // 主色調
        primary: {
          50: '#EFF6FF',
          100: '#DBEAFE',
          200: '#BFDBFE',
          300: '#93C5FD',
          400: '#60A5FA',
          500: '#3B82F6',
          600: '#2563EB',
          700: '#1D4ED8',
          800: '#1E40AF',
          900: '#1E3A8A',
        },
        // 聖經專用色彩
        bible: {
          ot: '#8B4513',      // 舊約 - 棕色
          nt: '#1E3A5F',      // 新約 - 藍色
          gold: '#B8860B',    // 經文強調
          parchment: '#FDF5E6', // 經文背景
        },
      },
      fontFamily: {
        sans: ['Noto Sans TC', 'sans-serif'],
        serif: ['Noto Serif TC', 'serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-in': 'slideIn 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideIn: {
          '0%': { transform: 'translateY(-10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [
    require('@tailwindcss/typography'),
    require('@tailwindcss/forms'),
  ],
};

export default config;
```

### 7.2 全域樣式

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
  }

  body {
    @apply bg-background text-foreground;
    font-feature-settings: "rlig" 1, "calt" 1;
  }
}

@layer components {
  /* 經文樣式 */
  .verse-text {
    @apply font-serif text-lg leading-relaxed tracking-wide;
  }

  .verse-number {
    @apply text-xs text-bible-gold align-super mr-1 font-sans;
  }

  /* 卡片樣式 */
  .card {
    @apply bg-white dark:bg-gray-800 rounded-lg shadow-sm border border-gray-200 dark:border-gray-700;
  }

  /* 按鈕樣式 */
  .btn-primary {
    @apply px-4 py-2 bg-primary-600 text-white rounded-lg
           hover:bg-primary-700 focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
           disabled:opacity-50 disabled:cursor-not-allowed transition-colors;
  }

  .btn-secondary {
    @apply px-4 py-2 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-200
           rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors;
  }
}
```

### 7.3 Shadcn/ui 整合

使用 Shadcn/ui 提供的元件作為基礎：

| 元件 | 用途 |
|------|------|
| Button | 按鈕 |
| Input | 輸入框 |
| Card | 卡片容器 |
| Dialog | 對話框 |
| Dropdown | 下拉選單 |
| Tabs | 標籤頁 |
| Toast | 提示訊息 |
| Skeleton | 載入骨架 |

---

## 8. 效能優化

### 8.1 程式碼分割

```typescript
// 路由級別的懶載入
const SearchPage = lazy(() => import('@/pages/SearchPage'));
const BrowsePage = lazy(() => import('@/pages/BrowsePage'));
const GraphPage = lazy(() => import('@/pages/GraphPage'));

// 大型元件的懶載入
const GraphViewer = lazy(() => import('@/components/graph/GraphViewer'));
```

### 8.2 虛擬化列表

使用 `@tanstack/react-virtual` 處理長列表：

```typescript
// 經文列表虛擬化
import { useVirtualizer } from '@tanstack/react-virtual';

function VerseList({ verses }) {
  const parentRef = useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: verses.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 80, // 預估每個項目高度
  });

  return (
    <div ref={parentRef} className="h-[600px] overflow-auto">
      <div style={{ height: `${virtualizer.getTotalSize()}px`, position: 'relative' }}>
        {virtualizer.getVirtualItems().map((virtualItem) => (
          <div
            key={virtualItem.key}
            style={{
              position: 'absolute',
              top: 0,
              left: 0,
              width: '100%',
              transform: `translateY(${virtualItem.start}px)`,
            }}
          >
            <VerseItem verse={verses[virtualItem.index]} />
          </div>
        ))}
      </div>
    </div>
  );
}
```

### 8.3 圖片優化

```typescript
// 使用 loading="lazy" 延遲載入
<img src={imageUrl} alt={alt} loading="lazy" />

// 使用 srcset 提供不同尺寸
<img
  src={imageUrl}
  srcSet={`${imageUrl}?w=400 400w, ${imageUrl}?w=800 800w`}
  sizes="(max-width: 600px) 400px, 800px"
  alt={alt}
/>
```

### 8.4 效能指標目標

| 指標 | 目標 | 說明 |
|------|------|------|
| FCP | < 1.5s | 首次內容繪製 |
| LCP | < 2.5s | 最大內容繪製 |
| TTI | < 3.5s | 可互動時間 |
| Bundle Size | < 200KB gzip | 初始載入大小 |

---

## 9. 開發規範

### 9.1 程式碼風格

使用 ESLint + Prettier 確保程式碼一致性：

```json
// .eslintrc.json
{
  "extends": [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react-hooks/recommended",
    "prettier"
  ],
  "rules": {
    "@typescript-eslint/no-unused-vars": "error",
    "@typescript-eslint/explicit-function-return-type": "off",
    "react-hooks/exhaustive-deps": "warn"
  }
}
```

### 9.2 Git Commit 規範

使用 Conventional Commits：

| 類型 | 說明 |
|------|------|
| feat | 新功能 |
| fix | 修復 bug |
| docs | 文檔更新 |
| style | 程式碼格式 (不影響邏輯) |
| refactor | 重構 |
| perf | 效能優化 |
| test | 測試相關 |
| chore | 建構/工具相關 |

範例：
```
feat(search): add query mode selector component
fix(bible): fix chapter navigation not updating
docs(readme): update installation instructions
```

### 9.3 測試策略

| 層級 | 工具 | 覆蓋範圍 |
|------|------|----------|
| 單元測試 | Vitest | 工具函數、Hooks |
| 元件測試 | Testing Library | 元件互動 |
| E2E 測試 | Playwright | 關鍵使用者流程 |

### 9.4 環境變數

```bash
# .env.example
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_APP_TITLE=Bible RAG
VITE_ENABLE_MOCK=false
```

---

## 附錄

### A. 相關文檔

| 文檔 | 說明 |
|------|------|
| [API 規格](../API_SPEC.md) | 後端 API 完整規格 |
| [後端架構](../BACKEND_ARCHITECTURE.md) | 後端系統架構 |
| [元件規格](./COMPONENT_SPEC.md) | 前端元件詳細規格 |
| [型別定義](./TYPE_DEFINITIONS.md) | TypeScript 型別定義 |
| [樣式指南](./STYLE_GUIDE.md) | UI 樣式規範 |

### B. 技術棧版本對照

| 套件 | 版本 | npm 指令 |
|------|------|----------|
| react | ^19.0.0 | `npm install react react-dom` |
| typescript | ^5.9.0 | `npm install -D typescript` |
| @tanstack/react-query | ^5.0.0 | `npm install @tanstack/react-query` |
| zustand | ^4.5.0 | `npm install zustand` |
| react-router-dom | ^7.0.0 | `npm install react-router-dom` |
| axios | ^1.7.0 | `npm install axios` |
| d3 | ^7.9.0 | `npm install d3` |
| tailwindcss | ^4.0.0 | `npm install -D tailwindcss` |

---

*文件版本: 1.0.0*
*最後更新: 2025-12-25*
