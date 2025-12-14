# Bible RAG API 規格文件

> 版本：v1.0.0
> 更新日期：2025-12-14
> Base URL：`http://localhost:8000/api/v1`

---

## 目錄

1. [概述](#1-概述)
2. [認證與錯誤處理](#2-認證與錯誤處理)
3. [RAG 查詢 API](#3-rag-查詢-api)
4. [書卷 API](#4-書卷-api)
5. [段落 API](#5-段落-api)
6. [經文 API](#6-經文-api)
7. [知識圖譜 API](#7-知識圖譜-api)
8. [資料型別定義](#8-資料型別定義)

---

## 1. 概述

### 1.1 系統簡介

Bible RAG API 是基於新標點和合本聖經的知識型檢索增強生成系統，提供：

- **RAG 查詢**：自然語言問答，結合向量檢索、全文檢索和知識圖譜
- **經文瀏覽**：書卷、章節、段落、經文的結構化存取
- **知識圖譜**：人物、地點、事件、主題的關係探索

### 1.2 API 文檔入口

| 端點 | 說明 |
|------|------|
| `/api/v1/docs` | Swagger UI - 互動式 API 測試 |
| `/api/v1/redoc` | ReDoc - 閱讀式 API 文檔 |
| `/api/v1/openapi.json` | OpenAPI 3.0 規格 - 可匯入 Postman |

### 1.3 資料統計

| 項目 | 數量 | 說明 |
|------|------|------|
| 書卷 | 66 | 舊約 39 卷 + 新約 27 卷 |
| 章節 | 1,189 | - |
| 經文 | 31,103 | - |
| 段落 | 7,912 | 以小標題劃分的經文單元 |
| 人物 | 1,833 | 聖經中出現的人物 |
| 地點 | 2,295 | 聖經中出現的地點 |
| 群體 | 2,011 | 民族、國家、組織等 |
| 事件 | 5,349 | 聖經中的重要事件 |
| 主題 | 3,437 | 教義、道德、歷史等主題 |

---

## 2. 認證與錯誤處理

### 2.1 認證

目前 API 無需認證，適用於本地開發環境。

### 2.2 CORS 設定

允許來源：
- `http://localhost:5173` (Vite 開發伺服器)
- `http://localhost:3000` (React 開發伺服器)

### 2.3 錯誤回應格式

所有錯誤皆回傳統一格式：

```json
{
  "detail": "錯誤訊息描述"
}
```

### 2.4 HTTP 狀態碼

| 狀態碼 | 說明 |
|--------|------|
| 200 | 成功 |
| 400 | 請求參數錯誤 |
| 404 | 資源不存在 |
| 422 | 驗證錯誤 (參數格式不正確) |
| 500 | 伺服器內部錯誤 |
| 503 | 服務不可用 (Neo4j/Ollama 連線失敗) |

---

## 3. RAG 查詢 API

### 3.1 POST `/query` - 智慧問答

執行完整 RAG 管線，根據使用者問題檢索相關經文並生成回答。

#### 請求

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{
    "query": "聖經怎麼談饒恕？",
    "mode": "auto",
    "options": {
      "max_results": 5,
      "include_graph": true
    }
  }'
```

#### 請求參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `query` | string | **是** | - | 使用者的自然語言問題，長度 1-500 字元 |
| `mode` | string | 否 | `"auto"` | 查詢模式，影響檢索策略 |
| `options` | object | 否 | - | 查詢選項 |
| `options.max_results` | integer | 否 | `5` | 回傳的段落數量，範圍 1-20 |
| `options.include_graph` | boolean | 否 | `false` | 是否包含知識圖譜上下文 |

#### 查詢模式 (`mode`)

| 值 | 說明 | 適用場景 |
|----|------|----------|
| `auto` | 自動判斷查詢類型 | 一般問題 |
| `verse` | 經文查詢模式 | 「創世記 1:1 說什麼？」 |
| `topic` | 主題查詢模式 | 「聖經怎麼談愛？」 |
| `person` | 人物查詢模式 | 「亞伯拉罕是誰？」 |
| `event` | 事件查詢模式 | 「出埃及的過程是什麼？」 |

#### 回應

```json
{
  "answer": "## 饒恕的核心教導\n\n根據聖經教導，饒恕是基督徒信仰的核心...",
  "segments": [
    {
      "id": 5678,
      "type": "pericope",
      "book": "馬太福音",
      "chapter_start": 18,
      "verse_start": 21,
      "chapter_end": 18,
      "verse_end": 35,
      "title": "饒恕七十個七次",
      "text_excerpt": "那時，彼得進前來，對耶穌說：「主啊，我弟兄得罪我，我當饒恕他幾次呢？...",
      "relevance_score": 0.87
    }
  ],
  "meta": {
    "query_type": "TOPIC_QUESTION",
    "used_retrievers": ["sparse", "dense", "graph"],
    "total_processing_time_ms": 3542,
    "llm_model": "qwen2"
  },
  "graph_context": {
    "related_topics": ["饒恕", "恩典", "憐憫"],
    "related_persons": ["耶穌", "彼得"]
  }
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `answer` | string | LLM 生成的回答，Markdown 格式 |
| `segments` | array | 相關經文段落列表 |
| `segments[].id` | integer | 段落 ID，可用於取得詳細資料 |
| `segments[].type` | string | 固定為 `"pericope"` |
| `segments[].book` | string | 書卷名稱 |
| `segments[].chapter_start` | integer | 起始章 |
| `segments[].verse_start` | integer | 起始節 |
| `segments[].chapter_end` | integer | 結束章 |
| `segments[].verse_end` | integer | 結束節 |
| `segments[].title` | string | 段落標題 |
| `segments[].text_excerpt` | string | 經文摘要 |
| `segments[].relevance_score` | float | 相關度分數 (0-1) |
| `meta.query_type` | string | 系統判定的查詢類型 |
| `meta.used_retrievers` | array | 使用的檢索器列表 |
| `meta.total_processing_time_ms` | integer | 處理時間 (毫秒) |
| `meta.llm_model` | string | 使用的 LLM 模型 |
| `graph_context` | object | 知識圖譜上下文 (需設定 `include_graph: true`) |

#### 查詢類型 (`query_type`)

| 值 | 說明 |
|----|------|
| `VERSE_LOOKUP` | 經文查詢 |
| `TOPIC_QUESTION` | 主題問題 |
| `PERSON_QUESTION` | 人物問題 |
| `EVENT_QUESTION` | 事件問題 |
| `GENERAL_BIBLE_QUESTION` | 一般聖經問題 |

---

## 4. 書卷 API

### 4.1 GET `/books` - 取得所有書卷

取得聖經 66 卷書的基本資訊。

#### 請求

```bash
curl http://localhost:8000/api/v1/books
```

#### 回應

```json
{
  "books": [
    {
      "id": 4,
      "name_zh": "創世記",
      "abbrev_zh": "創",
      "testament": "OT",
      "order_index": 1
    },
    {
      "id": 43,
      "name_zh": "馬太福音",
      "abbrev_zh": "太",
      "testament": "NT",
      "order_index": 40
    }
  ],
  "total": 66
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `books` | array | 書卷列表 |
| `books[].id` | integer | 書卷 ID |
| `books[].name_zh` | string | 中文書名 |
| `books[].abbrev_zh` | string | 中文縮寫 |
| `books[].testament` | string | 新舊約：`OT` (舊約) / `NT` (新約) |
| `books[].order_index` | integer | 正典順序 (1-66) |
| `total` | integer | 書卷總數 |

---

### 4.2 GET `/books/{book_id}` - 取得書卷詳情

取得指定書卷的詳細資訊，包含統計數據。

#### 請求

```bash
curl http://localhost:8000/api/v1/books/4
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `book_id` | integer | 書卷 ID |

#### 回應

```json
{
  "id": 4,
  "name_zh": "創世記",
  "abbrev_zh": "創",
  "testament": "OT",
  "order_index": 1,
  "chapter_count": 50,
  "verse_count": 1319,
  "pericope_count": 221
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `chapter_count` | integer | 章節數量 |
| `verse_count` | integer | 經文數量 |
| `pericope_count` | integer | 段落數量 |

---

### 4.3 GET `/books/{book_id}/chapters` - 取得書卷章節

取得指定書卷的所有章節及每章經文數。

#### 請求

```bash
curl http://localhost:8000/api/v1/books/4/chapters
```

#### 回應

```json
{
  "book_id": 4,
  "book_name": "創世記",
  "chapters": [
    {"chapter": 1, "verse_count": 31},
    {"chapter": 2, "verse_count": 25},
    {"chapter": 3, "verse_count": 24}
  ]
}
```

---

### 4.4 GET `/books/{book_id}/pericopes` - 取得書卷段落

取得指定書卷的所有段落。

#### 請求

```bash
curl http://localhost:8000/api/v1/books/4/pericopes
```

#### 回應

```json
{
  "book_id": 4,
  "book_name": "創世記",
  "pericopes": [
    {
      "id": 52,
      "title": "第1章",
      "chapter_start": 1,
      "verse_start": 1,
      "chapter_end": 1,
      "verse_end": 31
    }
  ],
  "total": 221
}
```

---

### 4.5 GET `/books/{book_id}/verses` - 取得書卷經文

取得指定書卷的所有經文，可篩選特定章節。

#### 請求

```bash
# 取得創世記所有經文
curl http://localhost:8000/api/v1/books/4/verses

# 取得創世記第1章經文
curl "http://localhost:8000/api/v1/books/4/verses?chapter=1"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 說明 |
|------|------|------|------|
| `chapter` | integer | 否 | 篩選指定章節 |

#### 回應

```json
{
  "book_id": 4,
  "book_name": "創世記",
  "verses": [
    {
      "id": 238,
      "chapter": 1,
      "verse": 1,
      "text": "起初，上帝創造天地。"
    }
  ],
  "total": 1319
}
```

---

## 5. 段落 API

### 5.1 GET `/pericopes` - 段落列表

取得段落列表，支援分頁和篩選。

#### 請求

```bash
# 基本請求
curl http://localhost:8000/api/v1/pericopes

# 帶分頁和篩選
curl "http://localhost:8000/api/v1/pericopes?skip=0&limit=20&book_id=4"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `skip` | integer | 否 | `0` | 分頁偏移量 |
| `limit` | integer | 否 | `20` | 每頁數量，最大 100 |
| `book_id` | integer | 否 | - | 篩選指定書卷 |

#### 回應

```json
{
  "pericopes": [
    {
      "id": 52,
      "book_id": 4,
      "book_name": "創世記",
      "title": "第1章",
      "reference": "創世記 1:1-31",
      "chapter_start": 1,
      "verse_start": 1,
      "chapter_end": 1,
      "verse_end": 31
    }
  ],
  "total": 7912,
  "skip": 0,
  "limit": 20
}
```

---

### 5.2 GET `/pericopes/{pericope_id}` - 段落詳情

取得指定段落的詳細內容，包含所有經文。

#### 請求

```bash
curl http://localhost:8000/api/v1/pericopes/52
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `pericope_id` | integer | 段落 ID |

#### 回應

```json
{
  "id": 52,
  "book_id": 4,
  "book_name": "創世記",
  "title": "第1章",
  "reference": "創世記 1:1-31",
  "chapter_start": 1,
  "verse_start": 1,
  "chapter_end": 1,
  "verse_end": 31,
  "summary": null,
  "verses": [
    {
      "id": 238,
      "book_id": 4,
      "book_name": "創世記",
      "chapter": 1,
      "verse": 1,
      "text": "起初，上帝創造天地。",
      "reference": "創世記 1:1"
    },
    {
      "id": 239,
      "book_id": 4,
      "book_name": "創世記",
      "chapter": 1,
      "verse": 2,
      "text": "地是空虛混沌，深淵上面一片黑暗；上帝的靈運行在水面上。",
      "reference": "創世記 1:2"
    }
  ]
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `summary` | string \| null | 段落摘要 (LLM 生成，可能為 null) |
| `verses` | array | 段落內所有經文 |

---

## 6. 經文 API

### 6.1 GET `/verses` - 經文列表

取得經文列表，支援分頁和多種篩選條件。

#### 請求

```bash
# 基本請求
curl http://localhost:8000/api/v1/verses

# 篩選創世記第1章
curl "http://localhost:8000/api/v1/verses?book_id=4&chapter=1&limit=10"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `skip` | integer | 否 | `0` | 分頁偏移量 |
| `limit` | integer | 否 | `20` | 每頁數量，最大 100 |
| `book_id` | integer | 否 | - | 篩選指定書卷 |
| `chapter` | integer | 否 | - | 篩選指定章節 (需搭配 book_id) |
| `pericope_id` | integer | 否 | - | 篩選指定段落 |

#### 回應

```json
{
  "verses": [
    {
      "id": 238,
      "book_id": 4,
      "book_name": "創世記",
      "chapter": 1,
      "verse": 1,
      "text": "起初，上帝創造天地。",
      "reference": "創世記 1:1"
    }
  ],
  "total": 31103,
  "skip": 0,
  "limit": 20
}
```

---

### 6.2 GET `/verses/{verse_id}` - 經文詳情

取得指定經文的詳細資訊。

#### 請求

```bash
curl http://localhost:8000/api/v1/verses/238
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `verse_id` | integer | 經文 ID |

#### 回應

```json
{
  "id": 238,
  "book_id": 4,
  "book_name": "創世記",
  "chapter": 1,
  "verse": 1,
  "text": "起初，上帝創造天地。",
  "reference": "創世記 1:1",
  "pericope_id": 52,
  "pericope_title": "第1章"
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `reference` | string | 經文引用格式 (書卷 章:節) |
| `pericope_id` | integer | 所屬段落 ID |
| `pericope_title` | string | 所屬段落標題 |

---

### 6.3 GET `/verses/search` - 經文搜尋

全文搜尋經文內容。

#### 請求

```bash
curl "http://localhost:8000/api/v1/verses/search?q=創造&limit=10"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `q` | string | **是** | - | 搜尋關鍵字 |
| `book_id` | integer | 否 | - | 限定搜尋範圍至指定書卷 |
| `limit` | integer | 否 | `20` | 回傳結果數量，最大 100 |

#### 回應

```json
{
  "query": "創造",
  "verses": [
    {
      "id": 238,
      "book_id": 4,
      "book_name": "創世記",
      "chapter": 1,
      "verse": 1,
      "text": "起初，上帝創造天地。",
      "reference": "創世記 1:1",
      "rank": 0.95
    }
  ],
  "total": 45
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `rank` | float | 搜尋相關度分數 (0-1)，越高越相關 |

---

## 7. 知識圖譜 API

### 7.1 GET `/graph/health` - 圖譜連線狀態

檢查 Neo4j 知識圖譜的連線狀態。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/health
```

#### 回應

```json
{
  "status": "healthy",
  "uri": "bolt://localhost:7687"
}
```

| 欄位 | 類型 | 說明 |
|------|------|------|
| `status` | string | 連線狀態：`healthy` / `unhealthy` |
| `uri` | string | Neo4j 連線 URI |

---

### 7.2 GET `/graph/stats` - 圖譜統計

取得知識圖譜的統計資訊。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/stats
```

#### 回應

```json
{
  "total_persons": 1833,
  "total_places": 2295,
  "total_groups": 2011,
  "total_events": 5349,
  "total_topics": 3437,
  "total_relationships": 189155
}
```

---

### 7.3 GET `/graph/entity/search` - 實體搜尋

搜尋知識圖譜中的實體 (人物、地點、群體、事件)。

#### 請求

```bash
curl "http://localhost:8000/api/v1/graph/entity/search?name=摩西&type=PERSON&limit=10"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `name` | string | 否 | - | 實體名稱 (模糊搜尋) |
| `type` | string | 否 | - | 實體類型 |
| `limit` | integer | 否 | `20` | 回傳結果數量 |

#### 實體類型 (`type`)

| 值 | 說明 | 範例 |
|----|------|------|
| `PERSON` | 人物 | 亞伯拉罕、摩西、大衛 |
| `PLACE` | 地點 | 耶路撒冷、伯利恆、埃及 |
| `GROUP` | 群體 | 以色列人、法利賽人、門徒 |
| `EVENT` | 事件 | 出埃及、大洪水、耶穌受洗 |

#### 回應

```json
{
  "entities": [
    {
      "id": 156,
      "name": "摩西",
      "type": "PERSON"
    }
  ],
  "total": 1
}
```

---

### 7.4 GET `/graph/entity/{entity_id}` - 實體詳情

取得指定實體的詳細資訊及相關實體。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/entity/156
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `entity_id` | integer | 實體 ID |

#### 回應

```json
{
  "id": 156,
  "name": "摩西",
  "type": "PERSON",
  "description": null,
  "related_verses_count": 847,
  "related_entities": [
    {
      "id": 157,
      "name": "亞倫",
      "type": "PERSON"
    },
    {
      "id": 289,
      "name": "法老",
      "type": "PERSON"
    }
  ]
}
```

---

### 7.5 GET `/graph/topic/search` - 主題搜尋

搜尋知識圖譜中的主題。

#### 請求

```bash
curl "http://localhost:8000/api/v1/graph/topic/search?name=愛&type=DOCTRINE"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `name` | string | 否 | - | 主題名稱 (模糊搜尋) |
| `type` | string | 否 | - | 主題類型 |
| `limit` | integer | 否 | `20` | 回傳結果數量 |

#### 主題類型 (`type`)

| 值 | 說明 | 範例 |
|----|------|------|
| `DOCTRINE` | 教義 | 救恩、稱義、聖靈 |
| `MORAL` | 道德 | 饒恕、愛、誠實 |
| `HISTORICAL` | 歷史 | 創造、出埃及、被擄 |
| `PROPHETIC` | 預言 | 彌賽亞、末世、審判 |
| `OTHER` | 其他 | - |

#### 回應

```json
{
  "topics": [
    {
      "id": 50,
      "name": "愛",
      "type": "DOCTRINE"
    }
  ],
  "total": 5
}
```

---

### 7.6 GET `/graph/topic/{topic_id}` - 主題詳情

取得指定主題的詳細資訊。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/topic/1
```

#### 回應

```json
{
  "id": 1,
  "name": "創造",
  "type": "HISTORICAL",
  "description": null,
  "related_verses_count": 156,
  "related_topics": [
    {
      "id": 2,
      "name": "光與暗的分隔",
      "type": "DOCTRINE"
    }
  ]
}
```

---

### 7.7 GET `/graph/verse/{verse_id}/entities` - 經文相關實體

取得指定經文的所有相關實體和主題。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/verse/238/entities
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `verse_id` | integer | 經文 ID |

#### 回應

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "persons": [],
  "places": [],
  "groups": [],
  "events": [
    {
      "id": 1,
      "name": "上帝創造天地",
      "type": "EVENT"
    }
  ],
  "topics": [
    {
      "id": 1,
      "name": "創造",
      "type": "HISTORICAL"
    },
    {
      "id": 4,
      "name": "生命之源",
      "type": "DOCTRINE"
    }
  ]
}
```

---

### 7.8 GET `/graph/relationships` - 關係子圖

取得以指定實體為中心的關係子圖，用於視覺化呈現。

#### 請求

```bash
curl "http://localhost:8000/api/v1/graph/relationships?entity_id=1&entity_type=TOPIC&depth=2"
```

#### 查詢參數

| 參數 | 類型 | 必填 | 預設值 | 說明 |
|------|------|------|--------|------|
| `entity_id` | integer | **是** | - | 中心實體 ID |
| `entity_type` | string | **是** | - | 實體類型：`PERSON`/`PLACE`/`GROUP`/`EVENT`/`TOPIC` |
| `depth` | integer | 否 | `2` | 展開深度，範圍 1-3 |

#### 回應

```json
{
  "nodes": [
    {
      "id": "topic_1",
      "label": "創造",
      "type": "Topic",
      "properties": {
        "type": "HISTORICAL"
      }
    },
    {
      "id": "topic_2",
      "label": "光與暗的分隔",
      "type": "Topic",
      "properties": {
        "type": "DOCTRINE"
      }
    }
  ],
  "edges": [
    {
      "source": "topic_1",
      "target": "topic_2",
      "type": "RELATED_TO",
      "properties": {
        "weight": 0.2093
      }
    }
  ]
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `nodes` | array | 節點列表 |
| `nodes[].id` | string | 節點 ID (格式：`{type}_{id}`) |
| `nodes[].label` | string | 顯示標籤 |
| `nodes[].type` | string | 節點類型 |
| `nodes[].properties` | object | 節點屬性 |
| `edges` | array | 邊列表 |
| `edges[].source` | string | 來源節點 ID |
| `edges[].target` | string | 目標節點 ID |
| `edges[].type` | string | 關係類型 |
| `edges[].properties` | object | 關係屬性 |

---

### 7.9 GET `/graph/topic/{topic_id}/related` - 關聯主題

取得與指定主題相關的其他主題，基於經文共現分析。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/topic/1/related
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `topic_id` | integer | 主題 ID |

#### 回應

```json
{
  "topic_id": 1,
  "topic_name": "創造",
  "related": [
    {
      "id": 2,
      "name": "光與暗的分隔",
      "type": "DOCTRINE",
      "weight": 0.2093,
      "co_occurrence": 27
    },
    {
      "id": 3,
      "name": "天、地和海的命名",
      "type": "HISTORICAL",
      "weight": 0.2093,
      "co_occurrence": 27
    }
  ],
  "total": 3
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `related[].weight` | float | 關聯權重 (Jaccard 相似度) |
| `related[].co_occurrence` | integer | 共現經文數量 |

---

### 7.10 GET `/graph/verse/{verse_id}/cross-references` - 經文交叉參照

取得指定經文的交叉參照關係 (引用、暗示)。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/verse/238/cross-references
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `verse_id` | integer | 經文 ID |

#### 回應

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "quotes": [],
  "quoted_by": [],
  "alludes_to": [],
  "alluded_by": [],
  "total": 0
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `quotes` | array | 此經文引用的其他經文 |
| `quoted_by` | array | 引用此經文的其他經文 |
| `alludes_to` | array | 此經文暗示的其他經文 |
| `alluded_by` | array | 暗示此經文的其他經文 |

---

### 7.11 GET `/graph/verse/{verse_id}/prophecies` - 預言應驗連結

取得指定經文的預言應驗關係。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/verse/238/prophecies
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `verse_id` | integer | 經文 ID |

#### 回應

```json
{
  "verse_id": 238,
  "verse_reference": "創世記 1:1",
  "is_ot": true,
  "fulfillments": [],
  "prophecies": [],
  "total": 0
}
```

#### 回應欄位說明

| 欄位 | 類型 | 說明 |
|------|------|------|
| `is_ot` | boolean | 是否為舊約經文 |
| `fulfillments` | array | 應驗此預言的新約經文 (僅舊約) |
| `prophecies` | array | 此經文應驗的舊約預言 (僅新約) |

---

### 7.12 GET `/graph/pericope/{pericope_id}/parallels` - 福音書平行經文

取得福音書段落的平行經文 (同一事件在不同福音書的記載)。

#### 請求

```bash
curl http://localhost:8000/api/v1/graph/pericope/5000/parallels
```

#### 路徑參數

| 參數 | 類型 | 說明 |
|------|------|------|
| `pericope_id` | integer | 段落 ID |

#### 回應

```json
{
  "pericope_id": 5000,
  "pericope_title": "耶穌受洗",
  "pericope_reference": "馬太福音 3:13-17",
  "parallels": [
    {
      "pericope_id": 5100,
      "book_name": "馬可福音",
      "title": "耶穌受洗",
      "reference": "馬可福音 1:9-11",
      "parallel_name": "耶穌受洗"
    }
  ],
  "total": 2
}
```

> **注意**：平行經文功能僅適用於福音書 (馬太、馬可、路加福音)。

---

## 8. 資料型別定義

### 8.1 Testament (新舊約)

```typescript
type Testament = "OT" | "NT";
```

| 值 | 說明 |
|----|------|
| `OT` | 舊約 (Old Testament) |
| `NT` | 新約 (New Testament) |

### 8.2 EntityType (實體類型)

```typescript
type EntityType = "PERSON" | "PLACE" | "GROUP" | "EVENT";
```

### 8.3 TopicType (主題類型)

```typescript
type TopicType = "DOCTRINE" | "MORAL" | "HISTORICAL" | "PROPHETIC" | "OTHER";
```

### 8.4 QueryMode (查詢模式)

```typescript
type QueryMode = "auto" | "verse" | "topic" | "person" | "event";
```

### 8.5 QueryType (查詢類型)

```typescript
type QueryType =
  | "VERSE_LOOKUP"
  | "TOPIC_QUESTION"
  | "PERSON_QUESTION"
  | "EVENT_QUESTION"
  | "GENERAL_BIBLE_QUESTION";
```

---

## 附錄

### A. 常用查詢範例

#### 取得創世記第一章所有經文

```bash
curl "http://localhost:8000/api/v1/books/4/verses?chapter=1"
```

#### 搜尋包含「愛」的經文

```bash
curl "http://localhost:8000/api/v1/verses/search?q=愛&limit=20"
```

#### 查詢「大衛」相關的人物關係圖

```bash
# 1. 先搜尋大衛
curl "http://localhost:8000/api/v1/graph/entity/search?name=大衛&type=PERSON"

# 2. 取得關係圖 (假設 ID 為 200)
curl "http://localhost:8000/api/v1/graph/relationships?entity_id=200&entity_type=PERSON&depth=2"
```

#### 問一個聖經問題

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "耶穌為什麼要受洗？"}'
```

### B. 前端整合建議

1. **狀態管理**：使用 TanStack Query 管理 API 請求快取
2. **錯誤處理**：統一處理 4xx/5xx 錯誤
3. **Loading 狀態**：RAG 查詢可能需要 3-10 秒，需顯示載入狀態
4. **分頁處理**：經文列表使用 `skip`/`limit` 實作無限捲動
5. **圖譜視覺化**：使用 vis-network 或 D3.js 呈現關係圖

### C. 版本歷史

| 版本 | 日期 | 說明 |
|------|------|------|
| v1.0.0 | 2025-12-14 | 初始版本 |
