# Bible RAG 樣式指南

> 版本：v1.0.0
> 更新日期：2025-12-25

---

## 目錄

1. [設計系統](#1-設計系統)
2. [色彩系統](#2-色彩系統)
3. [字型系統](#3-字型系統)
4. [間距系統](#4-間距系統)
5. [元件樣式](#5-元件樣式)
6. [響應式設計](#6-響應式設計)
7. [暗色模式](#7-暗色模式)
8. [動畫與過渡](#8-動畫與過渡)

---

## 1. 設計系統

### 1.1 設計原則

| 原則 | 說明 |
|------|------|
| **簡潔** | 去除不必要的裝飾，讓內容成為焦點 |
| **一致** | 保持視覺元素和互動模式的一致性 |
| **可及** | 確保色彩對比、字體大小符合無障礙標準 |
| **莊重** | 符合聖經內容的莊重氣質 |

### 1.2 設計語彙

本專案採用現代且典雅的設計風格，融合：

- **現代感**：扁平化設計、簡潔線條
- **典雅感**：襯線字體用於經文、羊皮紙風格背景
- **親和感**：圓角、柔和陰影

---

## 2. 色彩系統

### 2.1 主色調 (Primary)

```css
--primary-50:  #EFF6FF;
--primary-100: #DBEAFE;
--primary-200: #BFDBFE;
--primary-300: #93C5FD;
--primary-400: #60A5FA;
--primary-500: #3B82F6;  /* 主色 */
--primary-600: #2563EB;  /* 主要按鈕 */
--primary-700: #1D4ED8;
--primary-800: #1E40AF;
--primary-900: #1E3A8A;
```

**使用情境**:
- 主要按鈕背景
- 連結文字
- 選中狀態
- 焦點環

### 2.2 語意色彩

| 名稱 | 色值 | 用途 |
|------|------|------|
| Success | `#22C55E` | 成功訊息、正確狀態 |
| Warning | `#F59E0B` | 警告訊息、注意提示 |
| Error | `#EF4444` | 錯誤訊息、危險操作 |
| Info | `#3B82F6` | 資訊提示 |

```css
--success: #22C55E;
--success-light: #DCFCE7;
--success-dark: #166534;

--warning: #F59E0B;
--warning-light: #FEF3C7;
--warning-dark: #92400E;

--error: #EF4444;
--error-light: #FEE2E2;
--error-dark: #991B1B;

--info: #3B82F6;
--info-light: #DBEAFE;
--info-dark: #1E40AF;
```

### 2.3 聖經專用色彩

| 名稱 | 色值 | 用途 |
|------|------|------|
| OT Brown | `#8B4513` | 舊約標識、舊約書卷邊框 |
| NT Blue | `#1E3A5F` | 新約標識、新約書卷邊框 |
| Scripture Gold | `#B8860B` | 經文節號、經文強調 |
| Parchment | `#FDF5E6` | 經文背景、卡片背景 |
| Parchment Dark | `#2D2A24` | 暗色模式經文背景 |

```css
--bible-ot: #8B4513;
--bible-ot-light: #D2B48C;
--bible-ot-dark: #5D2E0C;

--bible-nt: #1E3A5F;
--bible-nt-light: #4A6B8A;
--bible-nt-dark: #0F1D2F;

--bible-gold: #B8860B;
--bible-gold-light: #DAA520;
--bible-gold-dark: #8B6914;

--bible-parchment: #FDF5E6;
--bible-parchment-dark: #2D2A24;
```

### 2.4 中性色

```css
--gray-50:  #F9FAFB;
--gray-100: #F3F4F6;
--gray-200: #E5E7EB;
--gray-300: #D1D5DB;
--gray-400: #9CA3AF;
--gray-500: #6B7280;
--gray-600: #4B5563;
--gray-700: #374151;
--gray-800: #1F2937;
--gray-900: #111827;
--gray-950: #030712;
```

**使用情境**:

| 色階 | 亮色模式 | 暗色模式 |
|------|----------|----------|
| 50 | 頁面背景 | - |
| 100 | 卡片 hover | - |
| 200 | 邊框、分隔線 | - |
| 300 | 禁用邊框 | - |
| 400 | 佔位文字 | 次要文字 |
| 500 | 次要文字 | - |
| 600 | 正文 | 邊框 |
| 700 | 標題 | 分隔線 |
| 800 | - | 卡片背景 |
| 900 | - | 頁面背景 |

---

## 3. 字型系統

### 3.1 字體家族

| 用途 | 字體 | Tailwind Class | 說明 |
|------|------|----------------|------|
| 正文 | Noto Sans TC | `font-sans` | 現代無襯線，適合 UI 文字 |
| 經文 | Noto Serif TC | `font-serif` | 傳統襯線，經文展示 |
| 程式碼 | JetBrains Mono | `font-mono` | 等寬字體，程式碼區塊 |

```css
--font-sans: 'Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', sans-serif;
--font-serif: 'Noto Serif TC', 'Songti TC', serif;
--font-mono: 'JetBrains Mono', 'Fira Code', monospace;
```

### 3.2 字級

| 名稱 | 大小 | 行高 | Tailwind | 用途 |
|------|------|------|----------|------|
| xs | 12px | 16px | `text-xs` | 輔助文字、標籤 |
| sm | 14px | 20px | `text-sm` | 次要文字、按鈕 |
| base | 16px | 24px | `text-base` | 正文 |
| lg | 18px | 28px | `text-lg` | 重要段落、經文 |
| xl | 20px | 28px | `text-xl` | 小標題 |
| 2xl | 24px | 32px | `text-2xl` | 區塊標題 |
| 3xl | 30px | 36px | `text-3xl` | 頁面標題 |
| 4xl | 36px | 40px | `text-4xl` | 主標題 |

### 3.3 字重

| 名稱 | 值 | Tailwind | 用途 |
|------|-----|----------|------|
| Normal | 400 | `font-normal` | 正文 |
| Medium | 500 | `font-medium` | 按鈕、標籤 |
| Semibold | 600 | `font-semibold` | 小標題 |
| Bold | 700 | `font-bold` | 標題 |

### 3.4 經文專用樣式

```css
/* 經文容器 */
.verse-container {
  background-color: var(--bible-parchment);
  border-radius: 0.5rem;
  padding: 1.5rem;
}

/* 經文文字 */
.verse-text {
  font-family: var(--font-serif);
  font-size: 1.125rem;   /* 18px */
  line-height: 2;        /* 雙倍行高 */
  letter-spacing: 0.05em;
  color: var(--gray-800);
}

/* 經文節號 */
.verse-number {
  font-family: var(--font-sans);
  font-size: 0.75rem;    /* 12px */
  font-weight: 600;
  color: var(--bible-gold);
  vertical-align: super;
  margin-right: 0.25rem;
}

/* 經文引用 */
.verse-reference {
  font-family: var(--font-sans);
  font-size: 0.875rem;   /* 14px */
  color: var(--gray-500);
  margin-top: 0.5rem;
}
```

---

## 4. 間距系統

### 4.1 基礎間距

採用 **4px** 為基準的間距系統：

| 名稱 | 值 | Tailwind | 用途 |
|------|-----|----------|------|
| 0 | 0 | `p-0` | 無間距 |
| 0.5 | 2px | `p-0.5` | 極小間距 |
| 1 | 4px | `p-1` | 緊湊間距 |
| 1.5 | 6px | `p-1.5` | 小間距 |
| 2 | 8px | `p-2` | 標準小間距 |
| 3 | 12px | `p-3` | 中小間距 |
| 4 | 16px | `p-4` | 基本間距 |
| 5 | 20px | `p-5` | 中間距 |
| 6 | 24px | `p-6` | 中大間距 |
| 8 | 32px | `p-8` | 大間距 |
| 10 | 40px | `p-10` | 區塊間距 |
| 12 | 48px | `p-12` | 大區塊間距 |
| 16 | 64px | `p-16` | 頁面間距 |

### 4.2 間距使用指南

```
┌─────────────────────────────────────────┐
│  Page (p-6 ~ p-8)                       │
│  ┌───────────────────────────────────┐  │
│  │  Section (py-8 ~ py-12)           │  │
│  │  ┌─────────────────────────────┐  │  │
│  │  │  Card (p-4 ~ p-6)           │  │  │
│  │  │  ┌───────────────────────┐  │  │  │
│  │  │  │  Content (gap-2 ~ 4)  │  │  │  │
│  │  │  └───────────────────────┘  │  │  │
│  │  └─────────────────────────────┘  │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

| 元素 | 建議間距 |
|------|----------|
| 頁面內距 | `p-6` (24px) 或 `p-8` (32px) |
| 區塊間距 | `py-8` (32px) 或 `py-12` (48px) |
| 卡片內距 | `p-4` (16px) 或 `p-6` (24px) |
| 表單欄位間距 | `gap-4` (16px) |
| 按鈕內距 | `px-4 py-2` (16px × 8px) |
| 標籤內距 | `px-2 py-1` (8px × 4px) |

### 4.3 圓角

| 名稱 | 值 | Tailwind | 用途 |
|------|-----|----------|------|
| none | 0 | `rounded-none` | 無圓角 |
| sm | 2px | `rounded-sm` | 細微圓角 |
| DEFAULT | 4px | `rounded` | 預設圓角 |
| md | 6px | `rounded-md` | 中圓角 |
| lg | 8px | `rounded-lg` | 大圓角 (卡片) |
| xl | 12px | `rounded-xl` | 特大圓角 |
| 2xl | 16px | `rounded-2xl` | 超大圓角 |
| full | 9999px | `rounded-full` | 完全圓角 (標籤) |

### 4.4 陰影

| 名稱 | Tailwind | 用途 |
|------|----------|------|
| sm | `shadow-sm` | 卡片懸浮效果 |
| DEFAULT | `shadow` | 一般卡片 |
| md | `shadow-md` | 彈出視窗 |
| lg | `shadow-lg` | 模態框 |
| xl | `shadow-xl` | 下拉選單 |

---

## 5. 元件樣式

### 5.1 按鈕

#### 樣式變體

| 變體 | 用途 | 樣式 |
|------|------|------|
| Primary | 主要操作 | 實心藍色背景 |
| Secondary | 次要操作 | 灰色邊框 |
| Ghost | 低調操作 | 透明背景 |
| Danger | 危險操作 | 紅色背景 |

#### 尺寸

| 尺寸 | Padding | Font Size | 用途 |
|------|---------|-----------|------|
| sm | 6px 12px | 14px | 緊湊按鈕 |
| md | 8px 16px | 14px | 標準按鈕 |
| lg | 12px 24px | 16px | 大型按鈕 |

#### 程式碼範例

```css
/* Primary Button */
.btn-primary {
  @apply px-4 py-2
         bg-primary-600 text-white
         rounded-lg font-medium
         hover:bg-primary-700
         focus:outline-none focus:ring-2 focus:ring-primary-500 focus:ring-offset-2
         disabled:opacity-50 disabled:cursor-not-allowed
         transition-colors duration-200;
}

/* Secondary Button */
.btn-secondary {
  @apply px-4 py-2
         border border-gray-300 text-gray-700
         dark:border-gray-600 dark:text-gray-200
         rounded-lg font-medium
         hover:bg-gray-50 dark:hover:bg-gray-700
         focus:outline-none focus:ring-2 focus:ring-gray-500 focus:ring-offset-2
         transition-colors duration-200;
}

/* Ghost Button */
.btn-ghost {
  @apply px-4 py-2
         text-gray-600 dark:text-gray-300
         rounded-lg font-medium
         hover:bg-gray-100 dark:hover:bg-gray-800
         transition-colors duration-200;
}

/* Danger Button */
.btn-danger {
  @apply px-4 py-2
         bg-error text-white
         rounded-lg font-medium
         hover:bg-red-600
         focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2
         transition-colors duration-200;
}
```

### 5.2 表單元素

#### 輸入框

```css
/* Base Input */
.input-base {
  @apply w-full px-4 py-2
         border border-gray-300 dark:border-gray-600
         rounded-lg
         bg-white dark:bg-gray-800
         text-gray-900 dark:text-gray-100
         placeholder:text-gray-400 dark:placeholder:text-gray-500
         focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent
         disabled:bg-gray-100 dark:disabled:bg-gray-700 disabled:cursor-not-allowed
         transition-shadow duration-200;
}

/* Input with Error */
.input-error {
  @apply border-error focus:ring-error;
}

/* Input Label */
.input-label {
  @apply block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1;
}

/* Input Label Required */
.input-label-required::after {
  content: '*';
  @apply text-error ml-1;
}

/* Input Error Message */
.input-error-message {
  @apply text-sm text-error mt-1;
}
```

#### 選擇框

```css
/* Select */
.select {
  @apply w-full px-4 py-2 pr-10
         border border-gray-300 dark:border-gray-600
         rounded-lg
         bg-white dark:bg-gray-800
         text-gray-900 dark:text-gray-100
         focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-transparent
         appearance-none
         bg-no-repeat bg-right
         transition-shadow duration-200;
  background-image: url("data:image/svg+xml,..."); /* chevron icon */
  background-position: right 0.75rem center;
  background-size: 1rem;
}
```

### 5.3 卡片

```css
/* Base Card */
.card {
  @apply bg-white dark:bg-gray-800
         rounded-lg
         shadow-sm
         border border-gray-200 dark:border-gray-700;
}

/* Card Hover */
.card-hover {
  @apply card
         hover:shadow-md hover:border-gray-300 dark:hover:border-gray-600
         transition-all duration-200;
}

/* Scripture Card */
.card-scripture {
  @apply bg-bible-parchment dark:bg-gray-800
         rounded-lg
         border border-bible-gold/30
         p-6;
}

/* Card Header */
.card-header {
  @apply px-6 py-4 border-b border-gray-200 dark:border-gray-700;
}

/* Card Body */
.card-body {
  @apply p-6;
}

/* Card Footer */
.card-footer {
  @apply px-6 py-4 border-t border-gray-200 dark:border-gray-700;
}
```

### 5.4 標籤

```css
/* Base Tag */
.tag {
  @apply inline-flex items-center
         px-2.5 py-0.5
         rounded-full
         text-xs font-medium;
}

/* Tag Variants */
.tag-primary {
  @apply tag bg-primary-100 text-primary-700
         dark:bg-primary-900 dark:text-primary-300;
}

.tag-success {
  @apply tag bg-green-100 text-green-700
         dark:bg-green-900 dark:text-green-300;
}

.tag-warning {
  @apply tag bg-yellow-100 text-yellow-700
         dark:bg-yellow-900 dark:text-yellow-300;
}

.tag-error {
  @apply tag bg-red-100 text-red-700
         dark:bg-red-900 dark:text-red-300;
}

/* Bible Tags */
.tag-ot {
  @apply tag bg-bible-ot/10 text-bible-ot
         dark:bg-bible-ot/20 dark:text-bible-ot-light;
}

.tag-nt {
  @apply tag bg-bible-nt/10 text-bible-nt
         dark:bg-bible-nt/20 dark:text-bible-nt-light;
}
```

---

## 6. 響應式設計

### 6.1 斷點定義

| 名稱 | 最小寬度 | Tailwind | 目標裝置 |
|------|----------|----------|----------|
| xs | 0 | 預設 | 手機 (直向) |
| sm | 640px | `sm:` | 大型手機 |
| md | 768px | `md:` | 平板 |
| lg | 1024px | `lg:` | 小型桌面 |
| xl | 1280px | `xl:` | 標準桌面 |
| 2xl | 1536px | `2xl:` | 大型桌面 |

### 6.2 容器寬度

```css
/* Container */
.container {
  @apply mx-auto px-4;
}

@screen sm {
  .container {
    @apply px-6;
  }
}

@screen lg {
  .container {
    @apply px-8 max-w-7xl;
  }
}
```

### 6.3 響應式佈局策略

| 元件 | 手機 (xs-sm) | 平板 (md) | 桌面 (lg+) |
|------|-------------|-----------|------------|
| 側邊欄 | 抽屜 (overlay) | 收合式 | 固定顯示 |
| 導航 | 漢堡選單 | 水平導航 | 水平導航 |
| 書卷選擇 | 2 欄 | 4 欄 | 6-8 欄 |
| 章節網格 | 5 欄 | 8 欄 | 10-12 欄 |
| 搜尋結果 | 單欄 | 單欄 | 雙欄 |
| 圖譜視圖 | 全螢幕 | 分割視圖 | 分割視圖 |

### 6.4 響應式範例

```html
<!-- 書卷網格 -->
<div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-8 gap-2">
  <!-- books -->
</div>

<!-- 章節網格 -->
<div class="grid grid-cols-5 sm:grid-cols-8 md:grid-cols-10 lg:grid-cols-12 gap-2">
  <!-- chapters -->
</div>

<!-- 側邊欄佈局 -->
<div class="flex">
  <aside class="hidden lg:block w-64 shrink-0">
    <!-- sidebar -->
  </aside>
  <main class="flex-1">
    <!-- content -->
  </main>
</div>
```

---

## 7. 暗色模式

### 7.1 啟用方式

使用 Tailwind 的 `class` 策略：

```typescript
// tailwind.config.ts
export default {
  darkMode: 'class',
  // ...
};
```

### 7.2 色彩對應表

| 元素 | 亮色模式 | 暗色模式 |
|------|----------|----------|
| 頁面背景 | `gray-50` | `gray-900` |
| 卡片背景 | `white` | `gray-800` |
| 正文 | `gray-900` | `gray-100` |
| 次要文字 | `gray-600` | `gray-400` |
| 邊框 | `gray-200` | `gray-700` |
| 分隔線 | `gray-200` | `gray-700` |
| 經文背景 | `parchment` | `gray-800` |
| 主色調 | `primary-600` | `primary-500` |

### 7.3 實作範例

```html
<!-- 基本使用 -->
<div class="bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100">
  Content
</div>

<!-- 邊框 -->
<div class="border border-gray-200 dark:border-gray-700">
  Bordered content
</div>

<!-- 經文容器 -->
<div class="bg-bible-parchment dark:bg-gray-800 border border-bible-gold/30 dark:border-gray-600">
  Scripture
</div>
```

### 7.4 主題切換 Hook

```typescript
// hooks/useTheme.ts
import { useEffect } from 'react';
import { useAppStore } from '@/stores/useAppStore';

export function useTheme() {
  const { theme, setTheme } = useAppStore();

  useEffect(() => {
    const root = document.documentElement;

    if (theme === 'system') {
      const isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
      root.classList.toggle('dark', isDark);
    } else {
      root.classList.toggle('dark', theme === 'dark');
    }
  }, [theme]);

  const toggleTheme = () => {
    const nextTheme = theme === 'light' ? 'dark' : theme === 'dark' ? 'system' : 'light';
    setTheme(nextTheme);
  };

  return { theme, setTheme, toggleTheme };
}
```

---

## 8. 動畫與過渡

### 8.1 過渡時間

| 名稱 | 時間 | 用途 |
|------|------|------|
| fast | 150ms | 按鈕 hover |
| normal | 200ms | 顏色變化、一般過渡 |
| slow | 300ms | 展開/收合 |
| slower | 500ms | 頁面切換 |

### 8.2 Tailwind 過渡類別

```html
<!-- 快速過渡 -->
<button class="transition-colors duration-150">Button</button>

<!-- 標準過渡 -->
<div class="transition-all duration-200">Card</div>

<!-- 慢速過渡 -->
<div class="transition-all duration-300">Accordion</div>
```

### 8.3 自定義動畫

```css
/* 淡入 */
@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.animate-fade-in {
  animation: fadeIn 0.3s ease-in-out;
}

/* 滑入 */
@keyframes slideIn {
  from {
    transform: translateY(-10px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.animate-slide-in {
  animation: slideIn 0.3s ease-out;
}

/* 脈動 */
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.animate-pulse {
  animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

/* 旋轉 */
@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.animate-spin {
  animation: spin 1s linear infinite;
}
```

### 8.4 Tailwind 配置

```typescript
// tailwind.config.ts
export default {
  theme: {
    extend: {
      animation: {
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-in': 'slideIn 0.3s ease-out',
        'slide-in-right': 'slideInRight 0.3s ease-out',
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
        slideInRight: {
          '0%': { transform: 'translateX(100%)', opacity: '0' },
          '100%': { transform: 'translateX(0)', opacity: '1' },
        },
      },
    },
  },
};
```

---

## 附錄

### A. Tailwind 配置完整範例

```typescript
// tailwind.config.ts
import type { Config } from 'tailwindcss';

const config: Config = {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
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
        bible: {
          ot: '#8B4513',
          'ot-light': '#D2B48C',
          nt: '#1E3A5F',
          'nt-light': '#4A6B8A',
          gold: '#B8860B',
          parchment: '#FDF5E6',
        },
        success: '#22C55E',
        warning: '#F59E0B',
        error: '#EF4444',
        info: '#3B82F6',
      },
      fontFamily: {
        sans: ['Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', 'sans-serif'],
        serif: ['Noto Serif TC', 'Songti TC', 'serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
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

### B. CSS 變數定義

```css
/* src/index.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    /* Colors */
    --background: 249 250 251; /* gray-50 */
    --foreground: 17 24 39; /* gray-900 */
    --card: 255 255 255; /* white */
    --card-foreground: 17 24 39; /* gray-900 */
    --primary: 37 99 235; /* primary-600 */
    --primary-foreground: 255 255 255;
    --border: 229 231 235; /* gray-200 */
    --ring: 59 130 246; /* primary-500 */

    /* Bible Colors */
    --bible-ot: 139 69 19;
    --bible-nt: 30 58 95;
    --bible-gold: 184 134 11;
    --bible-parchment: 253 245 230;
  }

  .dark {
    --background: 17 24 39; /* gray-900 */
    --foreground: 243 244 246; /* gray-100 */
    --card: 31 41 55; /* gray-800 */
    --card-foreground: 243 244 246; /* gray-100 */
    --border: 55 65 81; /* gray-700 */
    --bible-parchment: 45 42 36; /* custom dark parchment */
  }

  body {
    @apply bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100;
  }
}
```

---

*文件版本: 1.0.0*
*最後更新: 2025-12-25*
