# Bible RAG 三資料庫架構完整分析報告

> **專案**: Bible RAG — 繁體中文聖經問答系統（多策略 RAG 架構）
> **版本**: 1.0
> **日期**: 2026-02-27
> **⚠️ 歷史快照（已被取代）**：本文為初版建庫時期數據（Neo4j 19,317 節點／58,031 關係、Qdrant 3,041 向量，尚無 TSK 串珠、37 型關係抽取與排序融合層），與現況差距巨大。現行三庫架構一律以 [../ARCHITECTURE.md](../ARCHITECTURE.md) 為準。

---

## 目錄

1. [系統概述](#第一章系統概述)
2. [PostgreSQL Schema](#第二章postgresql-schema)
3. [Neo4j 知識圖譜 Schema](#第三章neo4j-知識圖譜-schema)
4. [Qdrant 向量資料庫 Schema](#第四章qdrant-向量資料庫-schema)
5. [跨資料庫 ID 橋接機制](#第五章跨資料庫-id-橋接機制)
6. [欄位映射與差異分析](#第六章欄位映射與差異分析)
7. [6 路由資料庫使用分析](#第七章6-路由資料庫使用分析)
8. [資料建置 Pipeline](#第八章資料建置-pipeline)
9. [變更影響分析](#第九章變更影響分析)
10. [資料一致性驗證](#第十章資料一致性驗證)

---

## 第一章：系統概述

Bible RAG 系統採用 **三資料庫異質儲存架構**，各資料庫依其特性承擔不同的職責：

- **PostgreSQL** — 結構化資料的權威來源（Source of Truth），負責聖經階層結構與實體的完整儲存
- **Neo4j** — 知識圖譜引擎，負責實體間關係遍歷與交叉引用導航
- **Qdrant** — 向量檢索引擎，負責語義相似度搜尋（Dense + Sparse 混合檢索）

### 1.1 三資料庫角色定位圖

```mermaid
flowchart TB
    subgraph User["使用者查詢"]
        Q["Query: 繁體中文聖經問題"]
    end

    subgraph SignalRouter["Signal-Driven Router"]
        SD["Signal Detector<br/>6 布林信號"]
        DT["Decision Tree<br/>R1-R6 + Fallback"]
        SD --> DT
    end

    subgraph PG["PostgreSQL<br/>結構化儲存 (Source of Truth)"]
        direction TB
        PG_ROLE["角色：權威資料來源"]
        PG_DATA["6 張表 · ~100K 記錄<br/>書卷 → 章 → 段落 → 分塊<br/>實體 · 實體提及"]
        PG_USE["用途：精確查詢、ID 水合、SQL 補充"]
    end

    subgraph N4J["Neo4j<br/>知識圖譜引擎"]
        direction TB
        N4J_ROLE["角色：關係遍歷引擎"]
        N4J_DATA["19,317 節點 · 58,031 關係<br/>10 種節點 · 5 種關係"]
        N4J_USE["用途：人物/事件/地點圖查詢<br/>交叉引用遍歷"]
    end

    subgraph QD["Qdrant<br/>向量檢索引擎"]
        direction TB
        QD_ROLE["角色：語義相似搜尋"]
        QD_DATA["3,041 向量 · 1024 維<br/>BGE-M3 Dense + BM25 Sparse"]
        QD_USE["用途：語義檢索、混合搜尋<br/>RRF 融合排序"]
    end

    Q --> SD
    DT -->|"R1: 精確查經節"| PG
    DT -->|"R2: 章節+語義"| PG
    DT -->|"R2: 章節+語義"| QD
    DT -->|"R3: 人物圖"| N4J
    DT -->|"R3: 人物圖"| QD
    DT -->|"R4: 事件圖"| N4J
    DT -->|"R4: 事件圖"| QD
    DT -->|"R5: 交叉引用"| N4J
    DT -->|"R5: 交叉引用"| QD
    DT -->|"R6: 地點圖"| N4J
    DT -->|"R6: 地點圖"| QD
    DT -->|"Fallback: 語義"| QD

    N4J -.->|"ID 水合"| PG
    QD -.->|"ID 水合"| PG

    style PG fill:#336791,color:#fff
    style N4J fill:#018bff,color:#fff
    style QD fill:#dc382c,color:#fff
```

### 1.2 資料規模統計表

| 資料庫 | 元素 | 數量 | 說明 |
|--------|------|------|------|
| **PostgreSQL** | 表 | 6 | books, chapters, pericopes, chunks, entities, entity_mentions |
| | 記錄 | ~100,000 | 其中 entity_mentions 佔大部分 |
| **Neo4j** | 節點 | 19,317 | 10 種標籤（含雙標籤 Entity） |
| | 關係 | 58,031 | 5 種關係類型 |
| **Qdrant** | 向量 | 3,041 | pericope + chunk + verse 級別嵌入 |
| | 維度 | 1,024 | BGE-M3 模型輸出維度 |
| | 距離度量 | COSINE | 餘弦相似度 |

---

## 第二章：PostgreSQL Schema

PostgreSQL 作為系統的 **權威資料來源 (Source of Truth)**，儲存聖經的完整層級結構和所有文本內容。其他兩個資料庫（Neo4j、Qdrant）的查詢結果最終都會回到 PostgreSQL 進行 **ID 水合**（hydration），取得完整文本。

> **來源檔案**: `scripts/db/schema.sql`

### 2.1 ER 圖

```mermaid
erDiagram
    books {
        VARCHAR_10 id PK "e.g. gen, exo, mat"
        VARCHAR_20 type "DEFAULT 'book'"
        VARCHAR_100 name "中文書名"
        VARCHAR_100 name_en "英文書名"
        VARCHAR_10 testament "old | new"
        VARCHAR_50 category "律法書/歷史書/..."
        INTEGER order "排序 1-66"
        INTEGER total_chapters "章數"
        INTEGER total_pericopes "段落數"
        INTEGER total_verses "節數"
        TIMESTAMP created_at "建立時間"
    }

    chapters {
        VARCHAR_20 id PK "e.g. gen:1"
        VARCHAR_20 type "DEFAULT 'chapter'"
        VARCHAR_10 parent_id FK "→ books.id"
        INTEGER chapter_num "章編號"
        INTEGER total_verses "節數"
        INTEGER total_pericopes "段落數"
        JSONB metadata "章層級元資料"
        JSONB footnotes "註腳"
        TIMESTAMP created_at "建立時間"
    }

    pericopes {
        VARCHAR_30 id PK "e.g. gen:1:0"
        VARCHAR_20 type "DEFAULT 'pericope'"
        VARCHAR_20 parent_id FK "→ chapters.id"
        VARCHAR_200 title "段落標題"
        TEXT content "完整經文內容"
        TEXT content_for_embedding "嵌入用文本"
        JSONB metadata "verse_range/token_count/..."
        JSONB cross_references "交叉引用陣列"
        JSONB verses "逐節經文 JSON 陣列"
        TIMESTAMP created_at "建立時間"
    }

    chunks {
        VARCHAR_40 id PK "e.g. gen:1:0:0"
        VARCHAR_20 type "DEFAULT 'chunk'"
        VARCHAR_30 parent_id FK "→ pericopes.id"
        TEXT content "分塊內容"
        TEXT content_for_embedding "嵌入用文本"
        JSONB metadata "chunk_index/total_chunks/..."
        JSONB verses "逐節經文 JSON 陣列"
        TIMESTAMP created_at "建立時間"
    }

    entities {
        VARCHAR_100 entity_id PK "e.g. person_亞伯拉罕"
        VARCHAR_50 type "Person/Place/Event/..."
        VARCHAR_200 canonical_name "正典名稱"
        JSONB aliases "別名陣列"
        TEXT description "實體描述"
        VARCHAR_20 extraction_method "regex | llm"
        INTEGER mention_count "被提及次數"
        TIMESTAMP created_at "建立時間"
    }

    entity_mentions {
        VARCHAR_100 mention_id PK "唯一提及 ID"
        VARCHAR_100 entity_id FK "→ entities.entity_id"
        VARCHAR_50 source_id "pericope/chunk ID"
        VARCHAR_20 source_type "pericope | chunk"
        VARCHAR_200 text_span "原文文本片段"
        TEXT context "上下文"
        INTEGER start_pos "起始位置"
        INTEGER end_pos "結束位置"
        TIMESTAMP created_at "建立時間"
    }

    books ||--o{ chapters : "parent_id"
    chapters ||--o{ pericopes : "parent_id"
    pericopes ||--o{ chunks : "parent_id"
    entities ||--o{ entity_mentions : "entity_id"
    pericopes ||--o{ entity_mentions : "source_id (logical)"
```

### 2.2 ID 格式層級說明

PostgreSQL 的 ID 設計遵循 **冒號分隔的階層格式**，從書卷 ID 逐步加深：

| 層級 | 格式 | 範例 | 說明 |
|------|------|------|------|
| Book | `{book_abbr}` | `gen` | 書卷縮寫（3 字母） |
| Chapter | `{book}:{chapter}` | `gen:1` | 書卷 + 章號 |
| Pericope | `{book}:{chapter}:{index}` | `gen:1:0` | 章內段落索引（0-based） |
| Chunk | `{book}:{chapter}:{index}:{chunk}` | `gen:1:0:0` | 段落內分塊索引 |
| Verse | `{book}:{chapter}:{index}:v:{verse}` | `gen:1:0:v:1` | 段落內經節號 |

### 2.3 索引清單

| 表 | 索引名稱 | 欄位 | 用途 |
|----|----------|------|------|
| books | idx_books_testament | testament | 舊約/新約篩選 |
| books | idx_books_category | category | 書卷類別篩選 |
| books | idx_books_order | "order" | 排序查詢 |
| chapters | idx_chapters_parent | parent_id | 按書卷查章 |
| chapters | idx_chapters_num | chapter_num | 按章號查詢 |
| pericopes | idx_pericopes_parent | parent_id | 按章查段落 |
| pericopes | idx_pericopes_title | title | 標題搜尋 |
| chunks | idx_chunks_parent | parent_id | 按段落查分塊 |
| entities | idx_entities_type | type | 按實體類型篩選 |
| entities | idx_entities_name | canonical_name | 名稱搜尋 |
| entities | idx_entities_mention_count | mention_count DESC | 熱門實體排序 |
| entity_mentions | idx_mentions_entity | entity_id | 按實體查提及 |
| entity_mentions | idx_mentions_source | source_id | 按來源查提及 |
| entity_mentions | idx_mentions_source_type | source_type | 按來源類型篩選 |

### 2.4 JSONB 欄位內容結構

#### `pericopes.verses` — 逐節經文陣列

```json
[
  {"num": "1", "text": "起初，神創造天地。"},
  {"num": "2", "text": "地是空虛混沌，淵面黑暗；..."}
]
```

#### `pericopes.metadata` — 段落元資料

```json
{
  "book_id": "gen",
  "book_name": "創世記",
  "chapter_num": 1,
  "verse_range": "1-5",
  "token_count": 342,
  "requires_chunking": false
}
```

#### `pericopes.cross_references` — 交叉引用陣列

```json
[
  {
    "ref_text": "約1:1-3",
    "ref_type": "parallel",
    "description": "道就是神",
    "source_verses": "1",
    "target_verses": "1-3"
  }
]
```

#### `entities.aliases` — 別名陣列（JSONB 格式）

```json
["亞伯蘭", "亞伯拉罕", "Abraham"]
```

> **關鍵差異**：在 PostgreSQL 中 `aliases` 是 JSONB 原生陣列；在 Neo4j 中則是 `JSON.stringify()` 後的字串。詳見[第六章](#第六章欄位映射與差異分析)。

### 2.5 View: `embedding_sources`

`embedding_sources` 是一個 **檢視（View）**，聯合 pericopes（不需分塊者）和 chunks，提供統一的嵌入來源：

```sql
CREATE VIEW embedding_sources AS
SELECT id, 'pericope' as source_type, content_for_embedding, metadata
FROM pericopes
WHERE (metadata->>'requires_chunking')::boolean = false
   OR metadata->>'requires_chunking' IS NULL
UNION ALL
SELECT id, 'chunk' as source_type, content_for_embedding, metadata
FROM chunks;
```

---

## 第三章：Neo4j 知識圖譜 Schema

Neo4j 作為 **知識圖譜引擎**，儲存聖經結構的圖形化表達以及實體間的關係網路。其設計採用 **反正規化**（denormalization）策略，將 `book_name`、`chapter_num` 等常用欄位冗餘存放在節點上，避免查詢時需要大量 JOIN。

> **來源**: Neo4j 資料庫即時查詢（APOC schema inspection）

### 3.1 圖譜 Schema 圖

```mermaid
graph TB
    subgraph BibleHierarchy["聖經階層結構"]
        Book["Book (66)<br/>書卷"]
        Chapter["Chapter (1,189)<br/>章"]
        Pericope["Pericope (2,779)<br/>段落"]
        Chunk["Chunk (438)<br/>分塊"]
    end

    subgraph Entities["實體節點 (共 14,845)"]
        Person["Person (2,103)<br/>人物"]
        Place["Place (909)<br/>地點"]
        Event["Event (5,556)<br/>事件"]
        Group["Group (357)<br/>群體"]
        Object["Object (2,345)<br/>物件"]
        Theme["Theme (3,575)<br/>主題"]
    end

    Book -->|"CONTAINS (1,189)"| Chapter
    Book -->|"NEXT_BOOK (65)"| Book
    Chapter -->|"CONTAINS (2,779)"| Pericope
    Chapter -->|"NEXT (1,123)"| Chapter
    Pericope -->|"CONTAINS (438)"| Chunk
    Pericope -->|"NEXT (1,419)"| Pericope
    Chunk -->|"NEXT (438)"| Chunk

    Pericope -->|"CROSS_REFERENCES (912)"| Pericope
    Pericope & Chunk -->|"MENTIONS (49,668)"| Person & Place & Event & Group & Object & Theme

    style Book fill:#4C8BF5,color:#fff
    style Chapter fill:#34A853,color:#fff
    style Pericope fill:#FBBC04,color:#000
    style Chunk fill:#EA4335,color:#fff
    style Person fill:#8E24AA,color:#fff
    style Place fill:#00897B,color:#fff
    style Event fill:#F4511E,color:#fff
    style Group fill:#6D4C41,color:#fff
    style Object fill:#546E7A,color:#fff
    style Theme fill:#1E88E5,color:#fff
```

### 3.2 節點類型與屬性

#### 聖經階層節點（雙標籤：`Bible` + 具體類型）

| 節點類型 | 數量 | 標籤 | 核心屬性 |
|----------|------|------|----------|
| **Book** | 66 | `Book:Bible` | `id`(indexed), `name`, `name_en`, `testament`, `category`, `order`, `total_chapters`, `total_pericopes` |
| **Chapter** | 1,189 | `Chapter:Bible` | `id`(indexed), `book_id`, `book_name`, `chapter_num`, `total_verses`, `total_pericopes` |
| **Pericope** | 2,779 | `Pericope:Bible` | `id`(indexed), `title`, `book_id`, `book_name`, `chapter_id`, `chapter_num`, `verse_range`, `token_count`, `requires_chunking` |
| **Chunk** | 438 | `Chunk:Bible` | `id`(indexed), `pericope_id`, `pericope_title`, `chunk_index`, `total_chunks`, `verse_range`, `token_count`, `has_overlap` |

#### 實體節點（雙標籤：`Entity` + 具體類型）

| 節點類型 | 數量 | 標籤 | 屬性 |
|----------|------|------|------|
| **Person** | 2,103 | `Person:Entity` | `entity_id`(indexed), `canonical_name`, `aliases`(JSON 字串), `description`, `mention_count` |
| **Place** | 909 | `Place:Entity` | 同上 |
| **Event** | 5,556 | `Event:Entity` | 同上 |
| **Group** | 357 | `Group:Entity` | 同上 |
| **Object** | 2,345 | `Object:Entity` | 同上 |
| **Theme** | 3,575 | `Theme:Entity` | 同上 |

### 3.3 關係類型與屬性

| 關係類型 | 數量 | 方向 | 起點 → 終點 | 屬性 |
|----------|------|------|-------------|------|
| **CONTAINS** | 4,406 | 有向 | Book→Chapter, Chapter→Pericope, Pericope→Chunk | 無 |
| **NEXT** | 2,980 | 有向 | Chapter→Chapter, Pericope→Pericope, Chunk→Chunk | 無 |
| **NEXT_BOOK** | 65 | 有向 | Book→Book | 無 |
| **MENTIONS** | 49,668 | 有向 | Pericope/Chunk → Entity | `text_span`, `start_pos`, `end_pos` |
| **CROSS_REFERENCES** | 912 | 有向 | Pericope → Pericope | `ref_text`, `ref_type`, `source`, `description`, `source_verses`, `target_verses`, `verse_start`, `verse_end` |

### 3.4 反正規化設計說明

Neo4j 中的以下欄位是 **冗餘的反正規化欄位**，與 PostgreSQL 中的對應資料重複：

| 冗餘欄位 | 出現在節點 | 來源 | 理由 |
|----------|------------|------|------|
| `book_name` | Chapter, Pericope | `books.name` | 避免圖遍歷時回溯 Book 節點 |
| `book_id` | Chapter, Pericope | `books.id` | 快速識別書卷 |
| `chapter_num` | Chapter, Pericope | `chapters.chapter_num` | 避免遍歷 Chapter 節點 |
| `chapter_id` | Pericope | `chapters.id` | 直接定位章節 |
| `pericope_id` | Chunk | `pericopes.id` | 快速回溯父段落 |
| `pericope_title` | Chunk | `pericopes.title` | 顯示用途 |

---

## 第四章：Qdrant 向量資料庫 Schema

Qdrant 作為 **向量檢索引擎**，負責基於語義相似度的文本搜尋。系統支援兩種 collection：標準 Dense 向量 collection 與 Dense+Sparse 混合 collection。

> **來源檔案**: `backend/config.py`, `backend/database/qdrant_db.py`, `backend/database/qdrant_hybrid.py`, `scripts/import_qdrant.py`

### 4.1 Collection 結構圖

```mermaid
flowchart LR
    subgraph QD["Qdrant 向量資料庫"]
        subgraph STD["bible_embeddings<br/>(標準 Collection)"]
            DV1["Dense Vector<br/>1024D · COSINE<br/>BGE-M3"]
            PL1["Payload<br/>record_id, type,<br/>book_id, book_name,<br/>chapter_num, title,<br/>verse_range,<br/>content_preview"]
        end

        subgraph HYB["bible_embeddings_hybrid<br/>(混合 Collection · 可選)"]
            DV2["Named Vector: dense<br/>1024D · COSINE<br/>BGE-M3"]
            SV2["Named Vector: sparse<br/>BM25 + CKIP 分詞"]
            PL2["Payload<br/>同上 +<br/>parent_pericope_id"]
        end
    end

    style STD fill:#dc382c,color:#fff
    style HYB fill:#ff6b6b,color:#fff
```

### 4.2 向量規格

| 項目 | 標準 Collection | 混合 Collection |
|------|----------------|-----------------|
| **Collection 名稱** | `bible_embeddings` | `bible_embeddings_hybrid` |
| **Dense 向量** | 1024D, COSINE | 1024D, COSINE (named: `dense`) |
| **Sparse 向量** | 無 | BM25 (named: `sparse`) |
| **嵌入模型** | BAAI/bge-m3 | BAAI/bge-m3 + BM25(CKIP 分詞) |
| **向量數量** | 3,041 | 3,041（啟用時） |
| **融合方法** | N/A | RRF (Reciprocal Rank Fusion) |

### 4.3 Payload 欄位完整列表

| 欄位 | 型別 | 說明 | 來源 |
|------|------|------|------|
| `record_id` | string | pericope/chunk/verse ID | `embeddings.jsonl` |
| `type` | string | `"pericope"` / `"chunk"` / `"verse"` | metadata |
| `book_id` | string | 書卷縮寫 e.g. `"gen"` | metadata |
| `book_name` | string | 中文書名 e.g. `"創世記"` | metadata |
| `chapter_num` | integer | 章號 | metadata |
| `title` | string | 段落標題 | metadata |
| `verse_range` | string | 經節範圍 e.g. `"1-5"` | metadata |
| `content_preview` | string | 前 200 字元預覽 | content_for_embedding |
| `parent_pericope_id` | string | 父段落 ID（僅 verse 級別） | 計算得出 |

### 4.4 混合檢索架構圖

```mermaid
flowchart TB
    Query["使用者查詢"]

    subgraph Encoding["雙通道編碼"]
        BGEM3["BGE-M3 Encoder<br/>→ 1024D Dense Vector"]
        BM25["BM25 + CKIP 分詞<br/>→ Sparse Vector"]
    end

    subgraph Prefetch["Qdrant Prefetch (各 50 筆)"]
        DP["Dense Prefetch<br/>COSINE 相似搜尋"]
        SP["Sparse Prefetch<br/>BM25 關鍵詞匹配"]
    end

    subgraph Fusion["RRF 融合排序"]
        RRF["Reciprocal Rank Fusion<br/>score = Σ 1/(k + rank_i)"]
    end

    Result["Top-K 結果<br/>record_id + score + payload"]

    Query --> BGEM3 --> DP
    Query --> BM25 --> SP
    DP --> RRF
    SP --> RRF
    RRF --> Result

    style BGEM3 fill:#1a73e8,color:#fff
    style BM25 fill:#e8710a,color:#fff
    style RRF fill:#34a853,color:#fff
```

### 4.5 向量來源分布

系統中的 3,041 個向量來自三種層級：

| 來源類型 | 數量 | 說明 |
|----------|------|------|
| Pericope | ~2,341 | 不需分塊的段落（`requires_chunking = false`） |
| Chunk | ~438 | 長段落拆分的分塊 |
| Verse | ~262 | 經節級別嵌入（指向父段落） |

---

## 第五章：跨資料庫 ID 橋接機制

三個資料庫之間的 **ID 格式統一** 是整個系統的關鍵設計。所有資料庫都使用同一套 **冒號分隔的階層 ID**，讓查詢結果可以跨庫對應。

### 5.1 ID 格式統一標準圖

```mermaid
flowchart LR
    subgraph IDFormat["統一 ID 格式"]
        direction TB
        B["Book ID<br/>gen"]
        C["Chapter ID<br/>gen:1"]
        P["Pericope ID<br/>gen:1:0"]
        K["Chunk ID<br/>gen:1:0:0"]
        V["Verse ID<br/>gen:1:0:v:1"]
        B --> C --> P --> K
        P --> V
    end

    subgraph PG["PostgreSQL"]
        PG_B["books.id = 'gen'"]
        PG_C["chapters.id = 'gen:1'"]
        PG_P["pericopes.id = 'gen:1:0'"]
        PG_K["chunks.id = 'gen:1:0:0'"]
    end

    subgraph N4J["Neo4j"]
        N4J_B["(Book {id: 'gen'})"]
        N4J_C["(Chapter {id: 'gen:1'})"]
        N4J_P["(Pericope {id: 'gen:1:0'})"]
        N4J_K["(Chunk {id: 'gen:1:0:0'})"]
    end

    subgraph QD["Qdrant"]
        QD_P["payload.record_id = 'gen:1:0'"]
        QD_K["payload.record_id = 'gen:1:0:0'"]
        QD_V["payload.record_id = 'gen:1:0:v:1'"]
    end

    B -.-> PG_B & N4J_B
    C -.-> PG_C & N4J_C
    P -.-> PG_P & N4J_P & QD_P
    K -.-> PG_K & N4J_K & QD_K
    V -.-> QD_V

    style PG fill:#336791,color:#fff
    style N4J fill:#018bff,color:#fff
    style QD fill:#dc382c,color:#fff
```

### 5.2 各 ID 格式在三庫中的對應

| ID 格式 | 部件數 | PostgreSQL | Neo4j | Qdrant |
|---------|--------|------------|-------|--------|
| `gen` | 1 | books.id | Book.id | — |
| `gen:1` | 2 | chapters.id | Chapter.id | — |
| `gen:1:0` | 3 | pericopes.id | Pericope.id | payload.record_id |
| `gen:1:0:0` | 4 (digit) | chunks.id | Chunk.id | payload.record_id |
| `gen:1:0:v:1` | 5 (v) | — (查父段落) | — | payload.record_id |

### 5.3 `get_content_by_id()` 水合機制

所有非 PostgreSQL 的查詢結果（Neo4j 圖遍歷、Qdrant 向量搜尋），最終都會調用 `postgres.get_content_by_id()` 來取得完整文本內容。此函式根據 ID 的 **部件數量** 判斷資料類型：

```
get_content_by_id(record_id) 的路由邏輯：

  parts = record_id.split(":")

  ┌─ len == 5 且 parts[3] == "v"  →  Verse ID  →  取父 Pericope
  ├─ len == 4                      →  Chunk ID  →  get_chunk_by_id()
  └─ len == 3                      →  Pericope ID → get_pericope_by_id()
```

> **來源**: `backend/database/postgres.py:213-228`

---

## 第六章：欄位映射與差異分析

### 6.1 聖經結構欄位映射表

| 概念欄位 | PostgreSQL | Neo4j | Qdrant (Payload) |
|----------|------------|-------|-------------------|
| **書卷 ID** | `books.id` | `Book.id` | — |
| **書卷中文名** | `books.name` | `Book.name`, `Chapter.book_name`, `Pericope.book_name` | `book_name` |
| **書卷英文名** | `books.name_en` | `Book.name_en` | — |
| **約別** | `books.testament` | `Book.testament` | — |
| **類別** | `books.category` | `Book.category` | — |
| **排序** | `books."order"` | `Book.order` | — |
| **章 ID** | `chapters.id` | `Chapter.id` | — |
| **章號** | `chapters.chapter_num` | `Chapter.chapter_num`, `Pericope.chapter_num` | `chapter_num` |
| **段落 ID** | `pericopes.id` | `Pericope.id` | `record_id` |
| **段落標題** | `pericopes.title` | `Pericope.title` | `title` |
| **經文內容** | `pericopes.content` | — (不存放) | `content_preview` (前 200 字) |
| **嵌入用文本** | `pericopes.content_for_embedding` | — | — (已嵌入為向量) |
| **經節範圍** | `pericopes.metadata->>'verse_range'` | `Pericope.verse_range` | `verse_range` |
| **Token 數** | `pericopes.metadata->>'token_count'` | `Pericope.token_count` | — |
| **是否需分塊** | `pericopes.metadata->>'requires_chunking'` | `Pericope.requires_chunking` | — |
| **分塊 ID** | `chunks.id` | `Chunk.id` | `record_id` |
| **分塊索引** | `chunks.metadata->>'chunk_index'` | `Chunk.chunk_index` | — |
| **分塊總數** | `chunks.metadata->>'total_chunks'` | `Chunk.total_chunks` | — |

### 6.2 實體欄位映射表

| 概念欄位 | PostgreSQL (entities) | Neo4j (Entity 節點) | Qdrant |
|----------|----------------------|---------------------|--------|
| **實體 ID** | `entity_id` (PK) | `entity_id` (indexed) | — |
| **類型** | `type` | 節點標籤 (Person/Place/...) | — |
| **正典名稱** | `canonical_name` | `canonical_name` | — |
| **別名** | `aliases` (JSONB 陣列) | `aliases` (JSON 字串) | — |
| **描述** | `description` | `description` | — |
| **提及次數** | `mention_count` | `mention_count` | — |
| **提取方法** | `extraction_method` | — (不存放) | — |

### 6.3 entity_mentions vs MENTIONS 映射表

| 概念 | PostgreSQL (entity_mentions 表) | Neo4j (MENTIONS 關係) |
|------|-------------------------------|----------------------|
| **結構** | 獨立的關聯表 | 圖的邊（關係） |
| **來源指向** | `source_id` + `source_type` | 起點節點 (Pericope/Chunk) |
| **目標指向** | `entity_id` (FK) | 終點節點 (Entity) |
| **文本片段** | `text_span` | `text_span` |
| **位置** | `start_pos`, `end_pos` | `start_pos`, `end_pos` |
| **上下文** | `context` | — (不存放) |
| **提及 ID** | `mention_id` (PK) | — (無唯一 ID) |
| **方向** | 邏輯方向（source → entity） | `(Pericope)-[:MENTIONS]->(Entity)` |

### 6.4 cross_references (JSONB) vs CROSS_REFERENCES (關係) 差異

| 面向 | PostgreSQL | Neo4j |
|------|-----------|-------|
| **儲存形式** | `pericopes.cross_references` JSONB 陣列 | `(Pericope)-[:CROSS_REFERENCES]->(Pericope)` 關係 |
| **數量** | 嵌入每個 pericope 記錄中 | 912 條獨立關係 |
| **屬性** | `ref_text`, `ref_type`, `description`, `source_verses`, `target_verses` | `ref_text`, `ref_type`, `source`, `description`, `source_verses`, `target_verses`, `verse_start`, `verse_end` |
| **遍歷能力** | 需解析 JSONB 再查詢 | 原生圖遍歷，支援多跳查詢 |
| **用途** | 靜態儲存，回傳給前端 | R5 路由的圖遍歷檢索 |

### 6.5 關鍵差異：aliases 格式

這是三庫間最容易造成混淆的差異：

| 資料庫 | aliases 儲存格式 | 範例 |
|--------|------------------|------|
| **PostgreSQL** | JSONB 原生陣列 | `["亞伯蘭", "亞伯拉罕"]` |
| **Neo4j** | `JSON.stringify()` 字串 | `'["亞伯蘭", "亞伯拉罕"]'` |

**原因**：Neo4j 的屬性不支援原生 JSON 陣列（僅支援 `LIST<STRING>`），但 import 腳本使用 `json.dumps()` 將陣列序列化為字串存入。查詢時 Neo4j 的 `any(a IN e.aliases WHERE ...)` 是對字串做操作，利用 `CONTAINS` 進行子字串匹配。

> **來源**: `scripts/import_neo4j.py:225` — `aliases=json.dumps(record.get("aliases", []))`

---

## 第七章：6 路由資料庫使用分析

系統的 6 路由架構是 Bible RAG 的核心設計。Signal Detector 偵測 6 個布林信號，Decision Tree 根據信號優先序選擇路由。

> **來源檔案**: `backend/utils/signal_detector.py`, `backend/utils/retrieval/router.py`

### 7.1 路由決策樹圖

```mermaid
flowchart TD
    Start["查詢進入"]

    S1{"has_book_chapter_verse?<br/>書+章+節"}
    S2{"has_book_chapter?<br/>書+章（無節）"}
    S5{"has_multi_book?<br/>≥2 本書 OR<br/>intent=cross_reference"}
    S3{"has_multi_person?<br/>≥2 人物"}
    S4{"has_event_keyword?<br/>事件關鍵詞"}
    S6{"has_place?<br/>地點名稱"}

    R1["R1: 精確查經節<br/>SQL Direct Lookup"]
    R2["R2: 章節+語義<br/>SQL(0.9) + Sem(0.6)"]
    R5["R5: 交叉引用<br/>Sem Seed + XRef∥Grp + SQL"]
    R3["R3: 人物圖查詢<br/>Grp(0.9) + Sem(0.7) + SQL(0.5)"]
    R4["R4: 事件搜尋<br/>Grp(0.85) + Sem(0.7) + SQL(0.5)"]
    R6["R6: 地點搜尋<br/>Grp(0.85) + Sem(0.7) + SQL(0.5)"]
    FB["Fallback: 語義<br/>Semantic Only"]

    Start --> S1
    S1 -->|Yes| R1
    S1 -->|No| S2
    S2 -->|Yes| R2
    S2 -->|No| S5
    S5 -->|Yes| R5
    S5 -->|No| S3
    S3 -->|Yes| R3
    S3 -->|No| S4
    S4 -->|Yes| R4
    S4 -->|No| S6
    S6 -->|Yes| R6
    S6 -->|No| FB

    style R1 fill:#336791,color:#fff
    style R2 fill:#5a8a9a,color:#fff
    style R3 fill:#018bff,color:#fff
    style R4 fill:#018bff,color:#fff
    style R5 fill:#6c3483,color:#fff
    style R6 fill:#018bff,color:#fff
    style FB fill:#dc382c,color:#fff
```

**優先序**: R1 > R2 > R5 > R3 > R4 > R6 > Fallback

### 7.2 路由 × 資料庫使用矩陣

| 路由 | 觸發條件 | PostgreSQL | Neo4j | Qdrant | 策略組合 |
|------|----------|:----------:|:-----:|:------:|----------|
| **R1** | 書+章+節 | **主要** | — | — | SQL Direct Lookup |
| **R2** | 書+章 | **主要**(0.9) | — | 次要(0.6) | SQL Chapter + Semantic |
| **R3** | ≥2 人物 | 補充(0.5) | **主要**(0.9) | 次要(0.7) | Graph(person) ∥ Semantic + SQL |
| **R4** | 事件關鍵詞 | 補充(0.5) | **主要**(0.85) | 次要(0.7) | Graph(event) ∥ Semantic + SQL |
| **R5** | ≥2 書 / 交叉引用 | 補充(0.4) | **主要**(0.85) | 種子(0.65) | Sem Seed → XRef(0.85) ∥ Graph(0.75) + SQL |
| **R6** | 地點名稱 | 補充(0.5) | **主要**(0.85) | 次要(0.7) | Graph(place) ∥ Semantic + SQL |
| **FB** | 無特殊信號 | — | — | **主要** | Semantic Only |

### 7.3 R3 路由資料流（人物圖查詢範例）

> 查詢範例：「亞伯拉罕和以撒之間有什麼關係？」

```mermaid
sequenceDiagram
    participant U as 使用者
    participant SD as Signal Detector
    participant RT as Router (R3)
    participant N4J as Neo4j
    participant QD as Qdrant
    participant PG as PostgreSQL
    participant RR as Reranker

    U->>SD: "亞伯拉罕和以撒之間有什麼關係？"
    SD->>SD: match_persons → ["亞伯拉罕", "以撒"]
    SD->>SD: has_multi_person = true → R3
    SD->>RT: QuerySignals(route="R3")

    par 平行執行
        RT->>N4J: find_entity_by_name("亞伯拉罕")
        N4J-->>RT: entity_id="person_亞伯拉罕"
        RT->>N4J: get_entity_related_pericopes(entity_id)
        N4J-->>RT: [pericope IDs: gen:22:0, gen:21:0, ...]

        RT->>N4J: find_entity_by_name("以撒")
        N4J-->>RT: entity_id="person_以撒"
        RT->>N4J: get_entity_related_pericopes(entity_id)
        N4J-->>RT: [pericope IDs: gen:22:0, gen:26:0, ...]

        RT->>N4J: get_entities_shared_pericopes([...])
        N4J-->>RT: [shared: gen:22:0] (weight=0.9)
    and
        RT->>QD: search_vectors(embed("亞伯拉罕和以撒..."))
        QD-->>RT: [semantic hits] (weight=0.7)
    end

    loop 每個 Neo4j/Qdrant 結果
        RT->>PG: get_content_by_id(record_id)
        PG-->>RT: {id, content, title, book_name, ...}
    end

    RT->>PG: sql_supplement(book_chapters, limit=3)
    PG-->>RT: [supplement pericopes] (weight=0.5)

    RT->>RR: rerank(query, all_candidates, top_k=5)
    RR-->>RT: [ranked results]
    RT-->>U: 排序後的 Top-5 結果
```

### 7.4 R5 路由資料流（交叉引用範例）

> 查詢範例：「創世記和約翰福音中關於創造的描述有何異同？」

```mermaid
sequenceDiagram
    participant U as 使用者
    participant SD as Signal Detector
    participant RT as Router (R5)
    participant QD as Qdrant
    participant N4J as Neo4j
    participant PG as PostgreSQL
    participant RR as Reranker

    U->>SD: "創世記和約翰福音中關於創造的描述有何異同？"
    SD->>SD: count_books → 2 (創世記, 約翰福音)
    SD->>SD: has_multi_book = true → R5
    SD->>RT: QuerySignals(route="R5")

    Note over RT: Step 1: 語義種子
    RT->>QD: search_vectors(embed(query))
    QD-->>RT: [semantic seeds: gen:1:0, jhn:1:0, ...] (weight=0.65)

    RT->>PG: get_content_by_id(each seed)
    PG-->>RT: [hydrated content]

    Note over RT: Step 2: 平行展開
    par 交叉引用遍歷
        RT->>N4J: get_cross_references("gen:1:0")
        N4J-->>RT: [xref targets] (weight=0.85)
        RT->>N4J: get_cross_references("jhn:1:0")
        N4J-->>RT: [xref targets] (weight=0.85)
    and 圖實體檢索（如有實體）
        RT->>N4J: retrieve_by_entities(entity_names)
        N4J-->>RT: [entity-related pericopes] (weight=0.75)
    end

    loop 每個新結果
        RT->>PG: get_content_by_id(record_id)
        PG-->>RT: {content, ...}
    end

    RT->>PG: sql_supplement(book_chapters, limit=3)
    PG-->>RT: [supplements] (weight=0.4)

    RT->>RR: rerank(query, all_candidates, top_k=5)
    RR-->>RT: [ranked results]
    RT-->>U: 排序後的 Top-5 結果
```

---

## 第八章：資料建置 Pipeline

### 8.1 端到端 Pipeline 圖

```mermaid
flowchart TB
    subgraph Stage1["第 1 階段：原始資料解析"]
        RAW["聖經原始資料<br/>JSON/XML"]
        PARSE["解析腳本<br/>→ books, chapters,<br/>pericopes, chunks<br/>JSONL 檔案"]
        RAW --> PARSE
    end

    subgraph Stage2["第 2 階段：實體提取"]
        ENTITY_DICT["entity_dict.py<br/>人物/地點字典"]
        ENTITY_EXTRACT["entity_extraction<br/>regex + LLM 方法"]
        PARSE --> ENTITY_EXTRACT
        ENTITY_DICT --> ENTITY_EXTRACT
        ENTITY_EXTRACT --> ENT_OUT["entities.jsonl<br/>entity_mentions.jsonl"]
    end

    subgraph Stage3["第 3 階段：向量嵌入生成"]
        EMBED["BGE-M3 嵌入<br/>content_for_embedding<br/>→ 1024D vectors"]
        PARSE --> EMBED
        EMBED --> EMB_OUT["embeddings.jsonl"]
    end

    subgraph Stage4["第 4 階段：資料導入"]
        direction TB
        IMP_PG["import_postgres.py<br/>6 張表依序導入"]
        IMP_N4J["import_neo4j.py<br/>節點 → 關係 → 實體 → MENTIONS"]
        IMP_QD["import_qdrant.py<br/>向量 + payload"]

        PARSE --> IMP_PG
        ENT_OUT --> IMP_PG
        ENT_OUT --> IMP_N4J
        PARSE --> IMP_N4J
        EMB_OUT --> IMP_QD
        PARSE --> IMP_QD
    end

    subgraph Stage5["第 5 階段：驗證"]
        VER_PG["PostgreSQL<br/>記錄數 · FK 完整性"]
        VER_N4J["Neo4j<br/>節點/關係數 · 約束"]
        VER_QD["Qdrant<br/>向量數 · Collection 狀態"]
        IMP_PG --> VER_PG
        IMP_N4J --> VER_N4J
        IMP_QD --> VER_QD
    end

    style Stage1 fill:#f0f0f0,color:#333
    style Stage2 fill:#fff3e0,color:#333
    style Stage3 fill:#e8eaf6,color:#333
    style Stage4 fill:#e8f5e9,color:#333
    style Stage5 fill:#fce4ec,color:#333
```

### 8.2 各階段說明

| 階段 | 腳本 | 輸入 | 輸出 | 說明 |
|------|------|------|------|------|
| **1. 解析** | `scripts/parse_bible.py` | 原始聖經資料 | `output/books.jsonl`, `chapters.jsonl`, `pericopes.jsonl`, `chunks.jsonl`, `neo4j_nodes.jsonl`, `neo4j_relationships.jsonl` | 產生所有結構化 JSONL |
| **2. 實體提取** | `scripts/entity_extraction/` | pericopes + chunks | `output/entities.jsonl`, `entity_mentions.jsonl` | regex + LLM 雙方法提取 |
| **3. 向量生成** | `scripts/generate_embeddings.py` | content_for_embedding | `output/embeddings.jsonl` | BGE-M3 模型嵌入 |
| **4a. PG 導入** | `scripts/import_postgres.py` | 全部 JSONL | PostgreSQL 6 表 | 依序：books → chapters → pericopes → chunks → entities → entity_mentions |
| **4b. Neo4j 導入** | `scripts/import_neo4j.py` | nodes/rels/entities/mentions JSONL | Neo4j 圖 | 依序：constraints → nodes → rels → entities → MENTIONS |
| **4c. Qdrant 導入** | `scripts/import_qdrant.py` | embeddings.jsonl + metadata | Qdrant collection | 建立 collection → 載入 metadata → batch upsert |
| **5. 驗證** | 各 import 腳本內建 | 資料庫查詢 | 統計報告 | 記錄數、狀態確認 |

---

## 第九章：變更影響分析

### 9.1 變更影響矩陣

| 變更類型 | PostgreSQL | Neo4j | Qdrant | 影響程度 |
|----------|:----------:|:-----:|:------:|----------|
| **新增書卷** | 新增 books 記錄 | 新增 Book 節點 + CONTAINS/NEXT_BOOK | — | 中 |
| **修改段落內容** | 更新 pericopes.content | — | 需重新嵌入 | 高 |
| **新增實體** | 新增 entities + entity_mentions | 新增 Entity 節點 + MENTIONS 關係 | — | 中 |
| **修改實體別名** | 更新 entities.aliases (JSONB) | 更新 Entity.aliases (字串) | — | 低 |
| **新增交叉引用** | 更新 pericopes.cross_references (JSONB) | 新增 CROSS_REFERENCES 關係 | — | 中 |
| **修改嵌入模型** | — | — | 全部向量需重建 | 極高 |
| **新增分塊** | 新增 chunks 記錄 | 新增 Chunk 節點 + CONTAINS/NEXT | 需嵌入新向量 | 高 |

### 9.2 變更影響流程圖

```mermaid
flowchart TB
    Change["資料變更"]

    Change -->|"經文內容修改"| ContentChange
    Change -->|"實體異動"| EntityChange
    Change -->|"交叉引用異動"| XRefChange
    Change -->|"結構異動(新書卷/章)"| StructChange

    subgraph ContentChange["經文內容變更"]
        CC1["1. 更新 PG pericopes.content"]
        CC2["2. 重新生成 content_for_embedding"]
        CC3["3. 重新 BGE-M3 嵌入"]
        CC4["4. 更新 Qdrant 向量"]
        CC1 --> CC2 --> CC3 --> CC4
    end

    subgraph EntityChange["實體變更"]
        EC1["1. 更新 PG entities 表"]
        EC2["2. 更新 PG entity_mentions 表"]
        EC3["3. 更新 Neo4j Entity 節點"]
        EC4["4. 更新 Neo4j MENTIONS 關係"]
        EC1 --> EC2
        EC1 --> EC3
        EC2 --> EC4
    end

    subgraph XRefChange["交叉引用變更"]
        XC1["1. 更新 PG pericopes.cross_references"]
        XC2["2. 更新 Neo4j CROSS_REFERENCES 關係"]
        XC1 --> XC2
    end

    subgraph StructChange["結構變更"]
        SC1["1. 更新 PG 階層表 (books/chapters/pericopes)"]
        SC2["2. 更新 Neo4j 階層節點 + CONTAINS/NEXT"]
        SC3["3. 如有新 pericope: 嵌入 → Qdrant"]
        SC1 --> SC2
        SC1 --> SC3
    end

    style ContentChange fill:#fff3e0,color:#333
    style EntityChange fill:#e8eaf6,color:#333
    style XRefChange fill:#e8f5e9,color:#333
    style StructChange fill:#fce4ec,color:#333
```

### 9.3 四條關鍵同步規則

#### 規則 1：經文內容修改 → 必須同步 Qdrant

```python
# 修改 PG 段落內容後，必須重新嵌入並更新 Qdrant
async def update_pericope_content(pericope_id: str, new_content: str):
    # Step 1: 更新 PostgreSQL
    await postgres.update_pericope(pericope_id, content=new_content)

    # Step 2: 重新生成嵌入文本
    new_embedding_text = generate_embedding_text(new_content)

    # Step 3: 重新嵌入
    vector = embedder.encode_query(new_embedding_text)

    # Step 4: 更新 Qdrant
    qdrant_client.upsert(collection_name="bible_embeddings", points=[...])
```

#### 規則 2：實體變更 → 必須同步 PG 與 Neo4j

```python
# 新增實體時，PG 和 Neo4j 都需要更新
async def add_entity(entity_data: dict):
    # Step 1: 插入 PG entities 表
    await postgres.insert_entity(entity_data)

    # Step 2: 插入 PG entity_mentions 表
    for mention in entity_data["mentions"]:
        await postgres.insert_mention(mention)

    # Step 3: 建立 Neo4j Entity 節點
    # 注意：aliases 需要 json.dumps() 轉為字串
    await neo4j.create_entity_node(
        entity_data, aliases=json.dumps(entity_data["aliases"])
    )

    # Step 4: 建立 Neo4j MENTIONS 關係
    for mention in entity_data["mentions"]:
        await neo4j.create_mentions_rel(mention)
```

#### 規則 3：交叉引用變更 → 必須同步 PG JSONB 與 Neo4j 關係

```python
# 新增交叉引用時，PG 的 JSONB 和 Neo4j 的關係都要更新
async def add_cross_reference(source_id: str, target_id: str, ref_data: dict):
    # Step 1: 更新 PG pericopes.cross_references JSONB
    current = await postgres.get_pericope_by_id(source_id)
    refs = current["cross_references"]
    refs.append(ref_data)
    await postgres.update_pericope(source_id, cross_references=refs)

    # Step 2: 建立 Neo4j CROSS_REFERENCES 關係
    await neo4j.create_cross_ref(source_id, target_id, ref_data)
```

#### 規則 4：aliases 格式必須一致

```python
# PG: JSONB 原生陣列
pg_aliases = ["亞伯蘭", "亞伯拉罕"]  # Python list → JSONB

# Neo4j: JSON 字串
neo4j_aliases = json.dumps(["亞伯蘭", "亞伯拉罕"])  # '["亞伯蘭", "亞伯拉罕"]'
```

### 9.4 無需同步的情況

| 場景 | 說明 |
|------|------|
| PostgreSQL 新增索引 | 僅影響 PG 查詢效能 |
| Neo4j 新增約束/索引 | 僅影響 Neo4j 查詢效能 |
| Qdrant 調整 HNSW 參數 | 僅影響向量搜尋效能 |
| 修改路由權重 (`config.py`) | 僅影響排序，不影響資料 |
| 修改 Reranker 模型 | 僅影響重排序結果 |
| 修改 `entity_dicts.py` 字典 | 僅影響信號偵測，不影響儲存資料 |

---

## 第十章：資料一致性驗證

### 10.1 一致性檢查流程圖

```mermaid
flowchart TB
    Start["開始一致性檢查"]

    subgraph Check1["檢查 1: 記錄數一致"]
        C1A["PG books 記錄數"]
        C1B["Neo4j Book 節點數"]
        C1C["比對: 應相等 (66)"]
        C1A --> C1C
        C1B --> C1C
    end

    subgraph Check2["檢查 2: ID 完整性"]
        C2A["PG pericopes 全部 ID"]
        C2B["Neo4j Pericope 全部 ID"]
        C2C["Qdrant record_id (type=pericope)"]
        C2D["交叉比對三庫 ID 集合"]
        C2A --> C2D
        C2B --> C2D
        C2C --> C2D
    end

    subgraph Check3["檢查 3: 關係一致"]
        C3A["PG entity_mentions 數量"]
        C3B["Neo4j MENTIONS 關係數量"]
        C3C["比對: 應近似相等"]
        C3A --> C3C
        C3B --> C3C
    end

    subgraph Check4["檢查 4: 向量覆蓋"]
        C4A["PG embedding_sources VIEW"]
        C4B["Qdrant 向量總數"]
        C4C["比對: 應相等 (3,041)"]
        C4A --> C4C
        C4B --> C4C
    end

    subgraph Check5["檢查 5: 反正規化一致"]
        C5A["PG books.name"]
        C5B["Neo4j Pericope.book_name"]
        C5C["Qdrant payload.book_name"]
        C5D["三庫 book_name 應一致"]
        C5A --> C5D
        C5B --> C5D
        C5C --> C5D
    end

    Start --> Check1 --> Check2 --> Check3 --> Check4 --> Check5

    style Check1 fill:#e8f5e9,color:#333
    style Check2 fill:#e3f2fd,color:#333
    style Check3 fill:#fff3e0,color:#333
    style Check4 fill:#f3e5f5,color:#333
    style Check5 fill:#fce4ec,color:#333
```

### 10.2 驗證查詢範例

#### 檢查 1：三庫記錄數比對

**PostgreSQL**:
```sql
-- 各表記錄數
SELECT 'books' AS table_name, COUNT(*) FROM books
UNION ALL SELECT 'chapters', COUNT(*) FROM chapters
UNION ALL SELECT 'pericopes', COUNT(*) FROM pericopes
UNION ALL SELECT 'chunks', COUNT(*) FROM chunks
UNION ALL SELECT 'entities', COUNT(*) FROM entities
UNION ALL SELECT 'entity_mentions', COUNT(*) FROM entity_mentions;
```

**Neo4j (Cypher)**:
```cypher
// 各節點類型數量
CALL db.labels() YIELD label
CALL apoc.cypher.run(
  'MATCH (n:`' + label + '`) RETURN count(n) as count', {}
) YIELD value
RETURN label, value.count AS count
ORDER BY count DESC

// 各關係類型數量
MATCH ()-[r]->()
RETURN type(r) AS rel_type, count(r) AS count
ORDER BY count DESC
```

**Qdrant (Python)**:
```python
from qdrant_client import QdrantClient
client = QdrantClient(host="localhost", port=6333)
info = client.get_collection("bible_embeddings")
print(f"Vectors: {info.points_count}")
```

#### 檢查 2：ID 交叉比對

```python
import asyncio
import asyncpg
from neo4j import AsyncGraphDatabase
from qdrant_client import QdrantClient

async def check_id_consistency():
    # PG pericope IDs
    pg_pool = await asyncpg.create_pool(dsn="postgresql://...")
    async with pg_pool.acquire() as conn:
        pg_ids = set(
            row["id"] for row in
            await conn.fetch("SELECT id FROM pericopes")
        )

    # Neo4j Pericope IDs
    neo4j_driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "..."))
    async with neo4j_driver.session() as session:
        result = await session.run("MATCH (p:Pericope) RETURN p.id AS id")
        neo4j_ids = set(record["id"] for record in await result.data())

    # Qdrant pericope record_ids
    client = QdrantClient(host="localhost", port=6333)
    # scroll all points
    qdrant_ids = set()
    offset = None
    while True:
        result = client.scroll("bible_embeddings", limit=1000, offset=offset,
                               scroll_filter={"must": [{"key": "type", "match": {"value": "pericope"}}]})
        for point in result[0]:
            qdrant_ids.add(point.payload["record_id"])
        offset = result[1]
        if offset is None:
            break

    # 比對
    print(f"PG: {len(pg_ids)}, Neo4j: {len(neo4j_ids)}, Qdrant: {len(qdrant_ids)}")
    print(f"PG - Neo4j: {pg_ids - neo4j_ids}")
    print(f"Neo4j - PG: {neo4j_ids - pg_ids}")
    print(f"PG - Qdrant: {pg_ids - qdrant_ids}")
```

#### 檢查 3：MENTIONS 數量比對

```sql
-- PostgreSQL
SELECT COUNT(*) FROM entity_mentions;
```

```cypher
// Neo4j
MATCH ()-[r:MENTIONS]->() RETURN count(r)
```

#### 檢查 4：aliases 格式一致性

```python
async def check_aliases_consistency():
    # PG: JSONB → Python list
    pg_entity = await postgres.get_entity("person_亞伯拉罕")
    pg_aliases = pg_entity["aliases"]  # 已是 list

    # Neo4j: 字串 → 需 json.loads
    neo4j_result = await neo4j_session.run(
        "MATCH (e:Person {entity_id: $eid}) RETURN e.aliases",
        eid="person_亞伯拉罕"
    )
    neo4j_aliases_str = (await neo4j_result.single())[0]
    neo4j_aliases = json.loads(neo4j_aliases_str)

    assert pg_aliases == neo4j_aliases, f"Mismatch: {pg_aliases} vs {neo4j_aliases}"
```

### 10.3 常見陷阱與解決方案

| 陷阱 | 症狀 | 解決方案 |
|------|------|----------|
| **Neo4j aliases 是字串非陣列** | `any(a IN e.aliases WHERE ...)` 比對失敗 | 使用 `CONTAINS` 子字串匹配，或 `apoc.convert.fromJsonList()` |
| **Qdrant 向量與 PG 內容不同步** | 語義搜尋返回過時結果 | 修改 PG 內容後立即重新嵌入並 upsert Qdrant |
| **ID 水合失敗（null content）** | `get_content_by_id()` 返回 None | 確認 record_id 格式正確、PG 中確實存在該記錄 |
| **cross_references JSONB 與 Neo4j 不一致** | R5 路由遺漏交叉引用 | 新增交叉引用時務必同時更新 PG JSONB 和 Neo4j 關係 |
| **entity_mentions 部分匯入** | Neo4j MENTIONS 數量 < PG | 重新執行 `import_neo4j.py`（不加 `--skip-mentions`） |
| **Verse ID 水合回傳父段落** | 查詢經節但返回整個段落 | 這是預期行為：`gen:1:0:v:1` → `get_pericope_by_id("gen:1:0")` |
| **Book/Chapter 在 Qdrant 中無向量** | 書卷/章級別搜尋無語義結果 | 設計如此：僅 pericope/chunk/verse 有嵌入 |

---

## 附錄：關鍵檔案索引

| 檔案路徑 | 用途 |
|----------|------|
| `scripts/db/schema.sql` | PostgreSQL 完整 schema 定義 |
| `backend/database/postgres.py` | PG 非同步查詢函式（asyncpg） |
| `backend/database/neo4j_db.py` | Neo4j 非同步查詢函式 |
| `backend/database/qdrant_db.py` | Qdrant Dense 向量搜尋 |
| `backend/database/qdrant_hybrid.py` | Qdrant Dense+Sparse 混合搜尋 |
| `backend/config.py` | 三庫連線設定 + 嵌入模型 + 路由權重 |
| `backend/utils/retrieval/router.py` | 6 路由信號驅動分發器 |
| `backend/utils/retrieval/graph_retriever.py` | Neo4j 圖遍歷（人物/事件/地點） |
| `backend/utils/retrieval/semantic_retriever.py` | Qdrant 語義檢索 + PG 水合 |
| `backend/utils/retrieval/cross_ref_retriever.py` | 交叉引用遍歷 + PG 水合 |
| `backend/utils/signal_detector.py` | 6 信號偵測 + 決策樹路由選擇 |
| `backend/utils/entity_dicts.py` | 字典橋接模組（人物/地點/事件匹配） |
| `scripts/import_postgres.py` | PG 資料導入腳本 |
| `scripts/import_neo4j.py` | Neo4j 資料導入腳本 |
| `scripts/import_qdrant.py` | Qdrant 向量導入腳本 |
