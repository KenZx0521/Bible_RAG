# Bible RAG 知識圖譜搭建文檔

> **專案**：Bible RAG — 繁體中文聖經問答系統
> **資料庫**：Neo4j 5.x（圖資料庫）
> **資料來源**：`bible_md/`（66 卷新標點和合本 markdown）
> **更新日期**：2026-04-29
> **驗證方式**：MCP Neo4j Cypher 即時查詢
> **⚠️ 歷史版本**：本文數據為 KG P0 修復前快照。P0 後（2026-07-06）anchor coverage 83.8%→98.2%、CROSS_REFERENCES 916→250,418、Event 參與者/地點補至 84%/75% 等已大幅變動，現況以 [kg_optimization_progress.md](kg_optimization_progress.md) 為準。重建至線上現況的完整步驟（含 TSK 匯入與 curated 資料重放鏈）見 [build_database.md](build_database.md) Step 9–10。

---

## 目錄

1. [概覽](#1-概覽)
2. [圖譜單位（核心問題 1）](#2-圖譜單位核心問題-1)
3. [跨書卷處理（核心問題 2）](#3-跨書卷處理核心問題-2)
4. [實際 KG 架構（MCP 查詢驗證）](#4-實際-kg-架構mcp-查詢驗證)
5. [搭建原理](#5-搭建原理)
6. [完整搭建流程](#6-完整搭建流程)
7. [附錄](#7-附錄)

---

## 1. 概覽

Bible RAG 的知識圖譜由 **兩大核心** 組成：

```
┌─────────────────────────────────────────────────────────────────┐
│                  聖經知識圖譜（Neo4j）                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ① 階層結構（Bible Hierarchy）                                  │
│     Book ──CONTAINS──► Chapter ──CONTAINS──► Pericope          │
│                                                  │              │
│                                                  └─CONTAINS──► Chunk
│                                                                 │
│     書卷之間：NEXT_BOOK    章/段/塊之間：NEXT                   │
│                                                                 │
│  ② 實體網路（Entity Network）                                   │
│     Pericope/Chunk ──MENTIONS──► Person/Place/Group/           │
│                                  Event/Object/Theme            │
│                                                                 │
│  ③ 跨段落引用（Cross References）                               │
│     Pericope ──CROSS_REFERENCES──► Pericope（含跨書卷）         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**圖譜規模（即時 MCP 查詢結果）**：

| 元素 | 數量 |
|------|------|
| 總節點數（含 Bible 與 Entity 雙標籤） | 23,490 |
| 總關係數 | 49,389 |
| Book / Chapter / Pericope / Chunk | 66 / 1,189 / 2,779 / 431 |
| Person / Place / Group / Event / Object / Theme | 2,418 / 1,299 / 506 / 1,710 / 2,200 / 987 |
| MENTIONS 關係 | 41,034 |
| CROSS_REFERENCES 關係 | 916（跨書 880, 同書 36） |
| CONTAINS / NEXT / NEXT_BOOK | 4,399 / 2,975 / 65 |

---

## 2. 圖譜單位（核心問題 1）

### 答：以 **Pericope（段落）** 為主要單位，採 4 層階層 + 1 層內嵌

聖經知識圖譜並非單一粒度。它使用 **Book → Chapter → Pericope → Chunk** 四層階層，同時存在 Verse（經節）作為向量庫的補充粒度（不在 Neo4j 中當作獨立節點）。

### 2.1 各層級的職責

| 層級 | Neo4j 節點 | ID 格式 | 範例 | 數量 | 用途 |
|------|:----------:|---------|------|:----:|------|
| **Book**（書卷） | `:Book:Bible` | `{book}` | `gen` | 66 | 跨書卷導航；分類（舊約／新約） |
| **Chapter**（章） | `:Chapter:Bible` | `{book}:{ch}` | `gen:1` | 1,189 | 章節定位；R2 路由的主鍵 |
| **Pericope**（段落） | `:Pericope:Bible` | `{book}:{ch}:{idx}` | `gen:1:0` | 2,779 | **核心單位**：嵌入、實體連結、交叉引用 |
| **Chunk**（分塊） | `:Chunk:Bible` | `{book}:{ch}:{idx}:{chunk}` | `gen:1:0:0` | 431 | 僅當段落超過 768 tokens 時切分 |
| Verse（經節） | ❌（不存在 Neo4j） | `{book}:{ch}:{idx}:v:{n}` | `gen:1:0:v:1` | — | 僅供 Qdrant 向量檢索 |

### 2.2 為什麼以 Pericope 為主要單位？

聖經的「段落（pericope）」是聖經學中已確立的詮釋單位 — 一段語意完整的故事、宣講或詩篇章節。專案的 markdown 來源是「新標點和合本」，已用 `### 段落標題` 將每章切成 pericope（例：創 1 → 「創世」、「人類受造」），與本系統的 H3 解析器（`MarkdownParser.H3_PATTERN`）一一對應。

優點：
- **語意完整**：不會把一個故事切成兩半。
- **嵌入精度**：BGE-M3 在 ~512 tokens 上下表現最佳，pericope 平均長度恰好落在這個區間。
- **檢索可解釋性**：返回「以撒娶妻」比返回「創 24:15-16」更直覺。

### 2.3 為什麼還需要 Chunk？

少數 pericope 篇幅過長（例如 民 7:0「各族長奉獻祭物」共 2,506 tokens、創 24:0「以撒娶妻」2,089 tokens），會超過 BGE-M3 推薦的嵌入長度。`HierarchicalChunker`（`bible_chunking/hierarchical_chunker.py`）的策略：

1. 計算 pericope 的 token 數。
2. 若 ≤ `max_chunk_tokens`（768），不切分。
3. 若 > 768，沿著「節（verse）邊界」切分，每塊目標 `target_chunk_tokens`（512）。
4. 相鄰 chunk 之間保留 `overlap_verses`（1 節）重疊，維持語意連續。
5. 若末塊 < `min_chunk_tokens`（128）且 ≤ 3 節，併回前塊。

**實測結果**（MCP 查詢）：

```
┌────────────┬──────────┬─────────────┬──────┐
│ pericope   │ tokens   │ title       │ chunks
├────────────┼──────────┼─────────────┼──────┤
│ num:7:0    │ 2506     │ 各族長奉獻祭物 │ 6
│ gen:24:0   │ 2089     │ 以撒娶妻     │ 5
│ jdg:9:0    │ 1860     │ 亞比米勒     │ 5
│ deu:28:1   │ 1659     │ 悖逆的後果   │ 4
│ lev:13:0   │ 1501     │ 皮膚病的條例  │ 4
└────────────┴──────────┴─────────────┴──────┘
```

全 66 卷僅 ~120 個 pericope（4.3%）需要切塊，產出 431 個 chunk。**95.7% 的 pericope 直接作為一個整體單位，不需切分。**

### 2.4 雙標籤設計

每個階層節點同時擁有 **2 個標籤**：

```cypher
(:Book:Bible)        // 既是 Book，也是 Bible
(:Chapter:Bible)
(:Pericope:Bible)
(:Chunk:Bible)
```

`Bible` 是一個「總稱」標籤，方便一次性 MATCH 整個聖經結構（如 `MATCH (n:Bible)`），同時保留具體類型（`Book`、`Chapter`...）的精確匹配。實體節點同理：`(:Person:Entity)`、`(:Place:Entity)` 等。

---

## 3. 跨書卷處理（核心問題 2）

### 答：**有，且是核心設計**。跨書卷引用佔全部 CROSS_REFERENCES 的 96.1%（880/916）

### 3.1 為什麼跨書卷重要？

聖經的詮釋天然是跨書卷的：
- **平行對觀**：太、可、路三本福音書記載同一件事（例：登山寶訓、變像、受難）。
- **NT→OT 引用**：新約大量引用舊約預言（例：太 1:23 引賽 7:14 童女懷孕；來 8 引耶 31 新約應許）。
- **歷史平行**：撒上下與代上下記載同一段以色列王朝歷史。
- **時間先後**：王上下與代上下、福音書與使徒行傳。

### 3.2 兩種跨書卷引用來源

系統用 **兩個獨立來源** 構建 CROSS_REFERENCES 邊：

#### 來源 A：Markdown 原始標記（`source: "markdown"`）

新標點和合本的 markdown 來源在每個 pericope 後用 H3 標題加括號的形式標註平行段落，例：

```markdown
### 耶穌受洗
### （可1‧9－11；路3‧21－22）
**13** 當下，耶穌從加利利來到約但河...
```

`CrossRefParser`（`bible_chunking/markdown_parser.py:22`）使用正則表達式解析中文書卷縮寫 + 章·節（-節）的格式，再查 `CROSS_REF_ABBREV` 將縮寫（如「可」）映射到 book id（`mrk`）。

**MCP 統計**：來源 markdown 的 CROSS_REFERENCES 共 **774 條**（跨書佔絕大多數）。

#### 來源 B：人工補強清單（`source: "supplementary"`）

`bible_chunking/nt_cross_references.py` 內維護了一份 **NT→OT 著名引用** 的人工列表（`SUPPLEMENTARY_CROSS_REFS`），補足 markdown 沒有標註的引用，例如：

```python
SupplementaryCrossRef("mat:1:2", "isa:7:0", "22-23", "14", "quotation",
                      "童女懷孕生子"),
SupplementaryCrossRef("mat:4:0", "deu:8:0", "4", "3", "quotation",
                      "人活著不是單靠食物"),
SupplementaryCrossRef("mat:21:3", "psa:118:0", "42", "22-23", "quotation",
                      "匠人所棄的石頭已作了房角石"),
```

每筆都標明：
- `source_pericope_id`（NT 出處）
- `target_pericope_id`（OT 來源）
- `source_verses` / `target_verses`（節範圍）
- `ref_type`：`quotation`（直接引用）or `allusion`（暗指）
- `description`（簡短說明）

**MCP 統計**：來源 supplementary 共 **142 條**（114 quotation + 28 allusion）。

### 3.3 引用解析的關鍵：Pericope-Level Resolution

雙層引用 ID（書、章、節）在 markdown 中是 **章節級別**（如「路 3:23-38」），但圖譜需要 **段落級別** 才有檢索意義。處理流程在 `process_bible.py:_build_verse_lookup()` 與 `_resolve_to_pericope()`：

```python
# Step 1: 預先建立 (book_id:chapter:verse_num) → pericope_id 反查表
verse_lookup = {
    "luk:3:23": "luk:3:0",  # 路 3:23 屬於哪個 pericope
    "luk:3:24": "luk:3:0",
    ...
}

# Step 2: 解析跨引用時，用首節查到實際 pericope
target_id = self._resolve_to_pericope(verse_lookup, "luk", 3, 23)
# → "luk:3:0"

# Step 3: 若找不到 pericope（罕見），退回章節級別
target_id = "luk:3"  # fallback
```

### 3.4 跨書卷統計（MCP 即時查詢）

| 維度 | 數值 | 比例 |
|------|------|------|
| **全部 CROSS_REFERENCES** | 916 | 100% |
| 跨書卷（`s.book_id <> t.book_id`） | **880** | **96.1%** |
| 同書卷內 | 36 | 3.9% |
| 全部 target 解析至 pericope 層級（depth=3） | 916 | 100% |
| 退回 chapter 層級的數量 | 0 | 0% |

**Top 跨書卷引用對**：

```
mat → luk : 93   (對觀福音平行)
luk → mat : 89
mat → mrk : 74
mrk → mat : 69
luk → mrk : 64
mrk → luk : 61
2ch → 2ki : 29   (歷史平行)
2ki → 2ch : 26
2ch → 1ki : 24
1ki → 2ch : 24
heb → psa : 14   (NT 引用詩篇)
1ch → 2sa : 13
```

對觀福音之間（mat/mrk/luk）佔最大宗，符合預期。

### 3.5 CROSS_REFERENCES 邊屬性

實際儲存的關係屬性（MCP schema 結果）：

```
[:CROSS_REFERENCES {
  ref_text:        "路3‧23－38",           # 原始字串
  source_verses:   "23-38",               # 起點節
  target_verses:   "23-38",               # 終點節
  verse_start:     23,                    # 起點節（int）
  verse_end:       38,                    # 終點節（int）
  source:          "markdown" | "supplementary",
  ref_type:        "quotation" | "allusion" | null,
  description:     "童女懷孕生子" | null
}]
```

### 3.6 為何同書卷僅 36 條？

新標點和合本的 markdown 不會把同書內的「上下文」當作交叉引用標註（那本來就是順序閱讀的部分）。同書 36 條主要來自：
1. 大型敘事的回指（例：John 18 → John 13）。
2. 詩篇間的對觀（例：詩 14 ↔ 詩 53，幾乎一字不差的兩篇）。
3. 補強清單中極少數 NT 內部引用。

---

## 4. 實際 KG 架構（MCP 查詢驗證）

> 以下數據透過 MCP `mcp__neo4j-cypher__read_neo4j_cypher` 與 `apoc.meta.schema` 即時取得。

### 4.1 節點 Schema

```
┌──────────┬─────────┬──────────────────┬──────────┐
│ Label    │ Count   │ Indexed PK       │ Type     │
├──────────┼─────────┼──────────────────┼──────────┤
│ Book     │     66  │ id               │ Bible    │
│ Chapter  │  1,189  │ id               │ Bible    │
│ Pericope │  2,779  │ id               │ Bible    │
│ Chunk    │    431  │ id               │ Bible    │
│ Person   │  2,418  │ entity_id        │ Entity   │
│ Place    │  1,299  │ entity_id        │ Entity   │
│ Group    │    506  │ entity_id        │ Entity   │
│ Event    │  1,710  │ entity_id        │ Entity   │
│ Object   │  2,200  │ entity_id        │ Entity   │
│ Theme    │    987  │ entity_id        │ Entity   │
└──────────┴─────────┴──────────────────┴──────────┘
```

### 4.2 節點屬性（重要欄位）

#### Book
```
id: STRING (indexed)         e.g. "gen"
name: STRING                 e.g. "創世記"
name_en: STRING              e.g. "Genesis"
testament: STRING            "old" | "new"
category: STRING             "pentateuch" | "gospels" | ...
order: INTEGER               1-66
total_chapters: INTEGER
total_pericopes: INTEGER
```

#### Pericope（核心單位）
```
id: STRING (indexed)         e.g. "exo:20:0"
title: STRING                e.g. "十誡"
book_id: STRING              "exo"            ← 反正規化欄位
book_name: STRING            "出埃及記"        ← 反正規化欄位
chapter_id: STRING           "exo:20"         ← 反正規化欄位
chapter_num: INTEGER         20               ← 反正規化欄位
verse_range: STRING          "1-17"
token_count: INTEGER         BGE-M3 token 數
requires_chunking: BOOLEAN   是否需切塊
```

> 反正規化（denormalization）目的：避免每次查詢都要 traverse 回 Book/Chapter，提升 Cypher 效能。

#### Chunk
```
id: STRING (indexed)         e.g. "exo:26:0:0"
pericope_id: STRING          e.g. "exo:26:0"
pericope_title: STRING       e.g. "聖幕的構造"
chunk_index: INTEGER         0-based
total_chunks: INTEGER        該 pericope 共有幾塊
verse_range: STRING          e.g. "1-18"
token_count: INTEGER
has_overlap: BOOLEAN         是否與前塊有重疊
```

#### Entity（6 種子類型共用）
```
entity_id: STRING (indexed)  e.g. "person:abolahan"
canonical_name: STRING       e.g. "亞伯拉罕"
aliases: LIST<STRING>        e.g. ["亞伯蘭", "Abraham"]（P0 後為原生 LIST）
description: STRING
mention_count: INTEGER       全聖經被提及次數
```

> ⚠ `aliases` 自 P0 修復（2026-07-06）起為 **原生 LIST**（`import_neo4j.py` 已移除 `json.dumps`），查詢寫法為 `any(a IN e.aliases WHERE a CONTAINS $name)`（見 §8.2）。本文初版所述「JSON 字串 + `apoc.convert.fromJsonList()`」為 P0 前舊 schema，已不適用。

### 4.3 關係 Schema

| 關係類型 | 數量 | 起 → 終 | 屬性 | 用途 |
|----------|-----:|--------|------|------|
| `CONTAINS` | 4,399 | Book→Chapter, Chapter→Pericope, Pericope→Chunk | — | 階層歸屬 |
| `NEXT` | 2,975 | Chapter→Chapter, Pericope→Pericope, Chunk→Chunk | — | 章內順序 |
| `NEXT_BOOK` | 65 | Book→Book | — | 書卷順序（66 卷 - 1 = 65 個 next） |
| `MENTIONS` | 41,034 | Pericope/Chunk → Entity | `text_span`, `start_pos`, `end_pos` | 實體出現 |
| `CROSS_REFERENCES` | 916 | Pericope → Pericope | `ref_text`, `verse_*`, `source`, `ref_type`, `description` | 跨段落引用 |

### 4.4 唯一性約束（Constraints）

```
┌─────────────┬──────────────────────────────┐
│ Label       │ Unique Property              │
├─────────────┼──────────────────────────────┤
│ Book        │ id                           │
│ Chapter     │ id                           │
│ Pericope    │ id                           │
│ Chunk       │ id                           │
│ Person      │ entity_id                    │
│ Place       │ entity_id                    │
│ Group       │ entity_id                    │
│ Event       │ entity_id                    │
│ Object      │ entity_id                    │
│ Theme       │ entity_id                    │
└─────────────┴──────────────────────────────┘
```

由 `import_neo4j.py:create_constraints()` 在匯入前建立。

### 4.5 MENTIONS 來源分布（MCP 查詢）

```
Pericope → Entity:  36,365  (88.6%)
Chunk    → Entity:   4,669  (11.4%)
─────────────────────────────────
Total:              41,034
```

**設計選擇**：Chunk 也獨立指向 Entity（不依賴父 Pericope），讓「短句級」實體查詢可以直接命中分塊範圍，而非整段。但匯入腳本對「未切塊的 pericope」只建立 Pericope→Entity，避免重複。

---

## 5. 搭建原理

### 5.1 三階段管線

```
┌───────────────┐      ┌────────────────┐      ┌──────────────┐
│ Stage 1:      │      │ Stage 2:       │      │ Stage 3:     │
│ 解析與分塊    │ ───► │ 實體抽取       │ ───► │ 匯入 Neo4j   │
│               │      │                │      │              │
│ process_bible │      │ extract_entities│      │ import_neo4j │
│ 7 個 JSONL    │      │ 2 個 JSONL      │      │ 構建圖譜     │
└───────────────┘      └────────────────┘      └──────────────┘
       │                       │                      │
       ▼                       ▼                      ▼
  bible_md/*.md          embedding_queue       neo4j_nodes
  bible_chunking/        + entity dicts         + neo4j_rels
                                                + entities
                                                + entity_mentions
```

### 5.2 Stage 1：解析與階層分塊（`process_bible.py`）

**演算法**：

```
for each book in canonical_order(66 books):
    parse markdown to Book/Chapter/Pericope/Verse objects   ← MarkdownParser
    for each pericope:
        compute token_count                                ← BGE-M3 tokenizer
        if token_count > max_chunk_tokens (768):
            split into chunks at verse boundaries          ← HierarchicalChunker
                with overlap_verses=1
                target=512, min=128
        else:
            keep as single embedding unit

    for each pericope cross_reference (parsed from H3 brackets):
        resolve verse → pericope using verse_lookup
        emit Pericope-CROSS_REFERENCES->Pericope edge

emit 7 JSONL files:
  books.jsonl
  chapters.jsonl
  pericopes.jsonl
  chunks.jsonl
  embedding_queue.jsonl       ← 給 BGE-M3 嵌入用
  neo4j_nodes.jsonl           ← Book/Chapter/Pericope/Chunk 節點
  neo4j_relationships.jsonl   ← CONTAINS/NEXT/NEXT_BOOK/CROSS_REFERENCES

# Final step: 補強 NT→OT 引用
for ref in SUPPLEMENTARY_CROSS_REFS:
    resolve target verse → target pericope
    emit Pericope-CROSS_REFERENCES->Pericope edge (source="supplementary")
```

**關鍵設定**（`bible_chunking/config.py`）：

```python
TOKEN_CONFIG = {
    "model_name": "BAAI/bge-m3",
    "max_model_tokens": 8192,
    "embedding_dim": 1024,
    "target_chunk_tokens": 512,    # 切塊目標
    "max_chunk_tokens": 768,       # 觸發切塊閾值（1.5× target）
    "min_chunk_tokens": 128,       # 最小塊尺寸
    "overlap_verses": 1,           # 相鄰塊重疊節數
}
```

### 5.3 Stage 2：實體抽取（`extract_entities.py`）

預設使用 **Grounded Pipeline**（4 階段），輔以 NER：

```
┌──────────────────────────────────────────────────────────┐
│ Phase 1: Pericope Title Mining                            │
│   從 H3 標題中挖事件/主題候選                              │
│   e.g. "出埃及" → Event, "立約" → Theme                  │
├──────────────────────────────────────────────────────────┤
│ Phase 2: CKIP POS Tagging                                 │
│   中文詞性標注，抽取頻率 ≥ min_freq 的名詞短語             │
├──────────────────────────────────────────────────────────┤
│ Phase 3: Rule-based Classification                        │
│   字典/規則分類為 Event / Object / Theme                  │
│   Confidence ≥ rule_confidence 直接接受                   │
├──────────────────────────────────────────────────────────┤
│ Phase 4: LLM-as-Classifier (Grounded)                     │
│   僅對 Phase 3 未分類者呼叫 LLM                           │
│   Grounding：限制 LLM 在已抽取候選範圍內分類              │
└──────────────────────────────────────────────────────────┘

加上獨立的 NER Extraction（不在 4 phase 中）：
  CKIP NER + 字典查詢 (entity_dict.py)
  → Person / Place / Group
```

**字典查詢機制**（`entity_extraction/entity_dict.py`）：
- `PERSON_DICT`：聖經人物字典（含別名）
- `PLACE_DICT`：地名字典
- `GROUP_DICT`：群體字典（以色列人、法利賽人...）

**輸出**：
```
output/entities.jsonl         (~14,845 條，含 6 類)
output/entity_mentions.jsonl  (~80,912 條，含位置)
```

> 註：實際匯入 Neo4j 後因 MERGE 去重，最終實體節點為 9,120，MENTIONS 為 41,034（部分 mention 因 source_id 不存在而被丟棄）。

### 5.4 Stage 3：Neo4j 匯入（`import_neo4j.py`）

**匯入順序**（重要：有依賴）：

```
1. clear_database()        # 可選，預設清空
   └ MATCH (n) DETACH DELETE n

2. create_constraints()    # 10 個唯一性約束
   └ CREATE CONSTRAINT ... REQUIRE n.{id|entity_id} IS UNIQUE

3. import_nodes()          # 從 neo4j_nodes.jsonl
   └ MERGE (n:{labels} {id: $id}) SET n += $props

4. import_relationships()  # 從 neo4j_relationships.jsonl
   └ MATCH (a {id: $start}), (b {id: $end})
     MERGE (a)-[r:{type}]->(b) SET r += $props

5. import_entities()       # 從 entities.jsonl
   └ MERGE (n:Entity:{type} {entity_id: $eid}) SET ...

6. import_entity_mentions()# 從 entity_mentions.jsonl
   └ MATCH (e:Entity {entity_id: ...})
     MATCH (s {id: ...})
     MERGE (s)-[r:MENTIONS]->(e) ON CREATE SET ...
```

**批次大小**：節點 500、關係 1000、MENTIONS 2000。
**冪等性**：所有寫入都用 `MERGE`，重複執行不會產生重複資料。

---

## 6. 完整搭建流程

### Step 0：準備聖經 markdown

確認 `bible_md/` 目錄下有 66 個檔案，以中文書名命名：

```bash
ls bible_md/ | wc -l         # 應為 66
ls bible_md/創世記.md          # 應存在
ls bible_md/啟示錄.md          # 應存在
```

### Step 1：解析與階層分塊

```bash
uv run --project scripts python scripts/process_bible.py \
    --input-dir bible_md \
    --output-dir output \
    --verbose
```

**預期輸出**：

```
[Phase 1] Parsing markdown files...
  Successfully parsed 66 books
[Phase 2] Processing hierarchical chunking...
  Total pericopes: 2779
  Pericopes requiring chunking: ~120
  Total chunks created: 431
[Phase 3] Exporting JSONL files...
  Wrote 66    records to books.jsonl
  Wrote 1189  records to chapters.jsonl
  Wrote 2779  records to pericopes.jsonl
  Wrote 431   records to chunks.jsonl
  Wrote 3041  records to embedding_queue.jsonl
  Wrote 4465  records to neo4j_nodes.jsonl
  Wrote 8209  records to neo4j_relationships.jsonl
  Added 142 supplementary cross-references
```

**驗證輸出**：

```bash
# 檢查節點數量
wc -l output/neo4j_nodes.jsonl       # 應為 4465
wc -l output/neo4j_relationships.jsonl
```

### Step 2：實體抽取

#### 選項 A：完整 Grounded Pipeline（建議，含 LLM）

```bash
uv run --project scripts python scripts/extract_entities.py \
    --bible-md-dir bible_md \
    --output-dir output \
    --verbose
```

#### 選項 B：僅 NER（快速，無 API 成本）

```bash
uv run --project scripts python scripts/extract_entities.py \
    --ner-only \
    --output-dir output
```

#### 選項 C：分階段 debug（單獨跑某 Phase）

```bash
# 只跑 Phase 1（H3 標題挖掘）
uv run --project scripts python scripts/extract_entities.py \
    --bible-md-dir bible_md --phase 1

# 只跑 Phase 4（LLM 分類）
uv run --project scripts python scripts/extract_entities.py \
    --bible-md-dir bible_md --phase 4
```

#### 選項 D：採樣測試

```bash
# 只處理前 50 個 pericope
uv run --project scripts python scripts/extract_entities.py \
    --bible-md-dir bible_md --sample 50
```

**預期輸出**：

```
=== Phase 1: Pericope Title Mining ===
=== Phase 2: CKIP POS Tagging ===
=== Phase 3: Rule-based Classification ===
=== Phase 4: LLM-as-Classifier (Grounded) ===
Entity type distribution:
  Person: ~2400
  Place:  ~1300
  Group:  ~500
  Event:  ~1700
  Object: ~2200
  Theme:  ~1000
Total entities: ~14000
Total mentions: ~80000
```

### Step 3：匯入 Neo4j

```bash
uv run --project scripts python scripts/import_neo4j.py \
    --output-dir output \
    --batch-size 500
```

**預期輸出**：

```
============================================================
Neo4j Import
============================================================
Connecting to Neo4j...
✓ Connected successfully

Clearing database...
  ✓ Database cleared

Creating constraints...
  ✓ Created 10 constraints

Importing nodes...
  Imported 500 nodes...
  ...
✓ Imported 4,465 nodes

Importing relationships...
✓ Imported 8,209 relationships

Importing entity nodes...
✓ Imported 9,120 entity nodes

Importing MENTIONS relationships...
✓ Imported 41,034 MENTIONS relationships

Database Stats:
  Total nodes: 23,490
  Total relationships: 49,389
```

> ⚠ 上列預期輸出為 P0 前快照。P0 後 `import_neo4j.py` 內建 verse→pericope remap 與誠實計數器：重跑時 MENTIONS 會高於 41,034（97,235 條 verse 級 mention 不再靜默丟棄，落空者計入 `skipped_missing` 並輸出 log）。匯入完成後還需執行 TSK 匯入與修復重放鏈才會到線上現況 — 見 [build_database.md](build_database.md) Step 9–10。

#### 進階選項

```bash
# 不清空資料庫，增量匯入
python scripts/import_neo4j.py --no-clear

# 跳過 MENTIONS（測試用，可大幅縮短時間）
python scripts/import_neo4j.py --skip-mentions

# 自訂批次大小
python scripts/import_neo4j.py --batch-size 1000
```

---

## 7. 附錄

### 7.1 關鍵檔案索引

| 檔案 | 用途 |
|------|------|
| `bible_chunking/config.py` | TOKEN_CONFIG, BOOK_CONFIG, CROSS_REF_ABBREV |
| `bible_chunking/markdown_parser.py` | MD 解析 + CrossRefParser |
| `bible_chunking/hierarchical_chunker.py` | Pericope 切塊邏輯 |
| `bible_chunking/models.py` | Book/Chapter/Pericope/Chunk/CrossReference 資料類 |
| `bible_chunking/nt_cross_references.py` | NT→OT 補強清單 |
| `scripts/process_bible.py` | Stage 1 主腳本 |
| `scripts/extract_entities.py` | Stage 2 主腳本 |
| `scripts/entity_extraction/ner_extractor.py` | CKIP NER（Person/Place/Group） |
| `scripts/entity_extraction/llm_extractor.py` | LLM 抽取（Event/Object/Theme） |
| `scripts/entity_extraction/grounded_classifier.py` | LLM-as-Classifier (Phase 4) |
| `scripts/entity_extraction/pericope_miner.py` | Phase 1 標題挖掘 |
| `scripts/entity_extraction/pos_extractor.py` | Phase 2 CKIP POS |
| `scripts/entity_extraction/rule_classifier.py` | Phase 3 規則分類 |
| `scripts/entity_extraction/entity_dict.py` | 人物/地點/群體字典 |
| `scripts/import_neo4j.py` | Stage 3 匯入腳本 |
| `docker-compose.yml` | Neo4j + PG + Qdrant 服務定義 |

### 7.2 ID 格式總表

| 元素 | 格式 | 範例 | 部件數 | Neo4j 標籤 |
|------|------|------|:----:|------------|
| Book | `{book}` | `gen` | 1 | `:Book:Bible` |
| Chapter | `{book}:{ch}` | `gen:1` | 2 | `:Chapter:Bible` |
| Pericope | `{book}:{ch}:{idx}` | `gen:1:0` | 3 | `:Pericope:Bible` |
| Chunk | `{book}:{ch}:{idx}:{chunk}` | `gen:1:0:0` | 4 | `:Chunk:Bible` |
| Verse | `{book}:{ch}:{idx}:v:{n}` | `gen:1:0:v:1` | 5 (含 `v`) | 不存在 Neo4j |
| Entity | `{type}:{slug}` | `person:abolahan` | 2 | `:{Type}:Entity` |

### 7.3 BOOK_CONFIG 縮寫對照（節錄）

| 中文 | id | 英文 | 約 | 類別 |
|------|----|------|:--:|------|
| 創世記 | gen | Genesis | OT | pentateuch |
| 出埃及記 | exo | Exodus | OT | pentateuch |
| 詩篇 | psa | Psalms | OT | wisdom |
| 以賽亞書 | isa | Isaiah | OT | major_prophets |
| 馬太福音 | mat | Matthew | NT | gospels |
| 馬可福音 | mrk | Mark | NT | gospels |
| 路加福音 | luk | Luke | NT | gospels |
| 約翰福音 | jhn | John | NT | gospels |
| 羅馬書 | rom | Romans | NT | pauline |
| 希伯來書 | heb | Hebrews | NT | general |
| 啟示錄 | rev | Revelation | NT | apocalyptic |

完整清單見 `bible_chunking/config.py:BOOK_CONFIG`。

### 7.4 常用查詢範例

```cypher
// 找出某段落的完整跨引用網路（2-hop）
MATCH (p:Pericope {id: "mat:1:2"})-[:CROSS_REFERENCES*1..2]-(other)
RETURN p, other;

// 找某人物在哪些段落出現
MATCH (e:Person {canonical_name: "亞伯拉罕"})<-[:MENTIONS]-(p:Pericope)
RETURN p.id, p.title, p.book_name LIMIT 20;

// 找同時提到兩個人物的段落（R3 路由的核心查詢）
MATCH (p:Pericope)-[:MENTIONS]->(:Person {canonical_name: "亞伯拉罕"}),
      (p)-[:MENTIONS]->(:Person {canonical_name: "以撒"})
RETURN p.id, p.title;

// NT→OT 引用清單
MATCH (s:Pericope)-[r:CROSS_REFERENCES]->(t:Pericope)
WHERE r.source = "supplementary" AND r.ref_type = "quotation"
RETURN s.book_name, s.id, t.book_name, t.id, r.description
ORDER BY s.id;

// 章節順序遍歷（從創 1 走到末了）
MATCH path = (start:Chapter {id: "gen:1"})-[:NEXT*]->(end:Chapter)
RETURN length(path) AS hops, end.id LIMIT 10;
```

### 7.5 與其他資料庫的關聯

本文件聚焦 **Neo4j 知識圖譜**。完整三庫架構（PostgreSQL + Neo4j + Qdrant）請參閱：

- `database_architecture_report.md` — 三庫整合分析
- `build_database.md` — 完整建置流程（含 PG 與 Qdrant）
- `bible_rag_latest.md` — 系統架構總覽

跨庫 ID 統一為冒號分隔的階層格式，所有路由結果最終會回到 PostgreSQL 進行 ID 水合（`get_content_by_id()`）取得完整文本內容。

---

## 8. Graph 檢索策略使用的演算法

> 本節回答：「現在有用到 Graph 檢索策略的是用什麼樣子的檢索演算法？」
>
> 結論：Bible_RAG 的 Graph 檢索 **沒有使用** PageRank、Personalized PageRank、GNN、Random Walk、Neo4j GDS、Community Detection 等進階圖演算法。它是純粹的 **Cypher pattern matching + 1-hop 遍歷 + 加權線性融合**，最後統一交給 BGE reranker 做最終排序。

### 8.1 演算法總覽

```
┌──────────────────────────────────────────────────────────────────┐
│ Graph 檢索五層演算法（由下而上）                                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ⑤ BGE Reranker（最終排序）                                      │
│     ↑                                                            │
│  ④ 加權線性融合 + Dedup（同 id 取最高 weight）                   │
│     ↑                                                            │
│  ③ 1-Hop / Multi-Entity Intersection / CROSS_REFERENCES         │
│     ↑                                                            │
│  ② 實體錨定（CONTAINS 子字串 + mention_count DESC）              │
│     ↑                                                            │
│  ① Query Signal Detection（人物/事件/地點關鍵字偵測）            │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### 8.2 第 1 層：實體錨定（Entity Anchoring）— 子字串匹配

**檔案**：`backend/database/neo4j_db.py:53-74` `find_entity_by_name()`

```cypher
MATCH (e)
WHERE (e:Person OR e:Place OR e:Group OR e:Event OR e:Object OR e:Theme)
  AND (e.canonical_name CONTAINS $name
       OR any(a IN e.aliases WHERE a CONTAINS $name))
RETURN e.entity_id AS entity_id,
       e.canonical_name AS canonical_name,
       labels(e) AS labels,
       e.description AS description,
       e.mention_count AS mention_count
ORDER BY e.mention_count DESC
LIMIT $limit
```

**特性**：
- ❌ 不是向量相似度
- ❌ 不是 fulltext index（Lucene）
- ✅ 純 `CONTAINS` 子字串匹配
- ✅ 排序使用 **mention_count DESC**（popularity prior，相當於先驗權重）

### 8.3 第 2 層：1-Hop MENTIONS 遍歷（R3/R4/R6 核心）

**檔案**：`neo4j_db.py:77-96` `get_entity_related_pericopes()`

```cypher
MATCH (e {entity_id: $entity_id})-[:MENTIONS]-(p)
WHERE p:Pericope OR p:Chunk
RETURN p.id AS id, p.title AS title, p.book_name AS book_name,
       p.chapter_num AS chapter_num, p.verse_range AS verse_range
LIMIT $limit
```

**特性**：
- 一跳：Entity → Pericope/Chunk
- **無向匹配**（`-[:MENTIONS]-`），來回兩端皆可
- 同樣的 1-hop 演算法分別用於：
  - `get_entity_related_pericopes()`（R3 人物）
  - `get_event_related_content()`（R4 事件，filter `:Event`）
  - `get_place_related_content()`（R6 地點，filter `:Place`）

### 8.4 第 3 層：多實體交集（Multi-Entity Intersection, R3 專用）

**檔案**：`neo4j_db.py:99-124` `get_entities_shared_pericopes()`

```cypher
MATCH (e {entity_id: $first_id})-[:MENTIONS]-(p)
WHERE (p:Pericope OR p:Chunk)
  AND ALL(eid IN $other_ids WHERE
    EXISTS {
      MATCH (e2 {entity_id: eid})-[:MENTIONS]-(p)
    }
  )
RETURN p.id AS id, ...
LIMIT $limit
```

**演算法本質**：
- 等價於 **set intersection / bipartite co-occurrence**
- 找出「同時被多個實體 MENTIONS」的 pericope
- 共現 pericope 給更高權重 **0.9**（比單實體的 **0.8** 高）
- 觸發條件：`len(all_entity_ids) >= 2`（至少兩個人物共同出現的查詢）

### 8.5 第 4 層：CROSS_REFERENCES 單向跳轉（R5 跨書）

**檔案**：`neo4j_db.py:127-144` + `backend/utils/retrieval/cross_ref_retriever.py`

```cypher
MATCH (p:Pericope {id: $pericope_id})-[:CROSS_REFERENCES]->(target)
RETURN target.id AS id, labels(target) AS labels,
       target.title AS title, target.book_name AS book_name,
       target.chapter_num AS chapter_num
LIMIT $limit
```

**特性**：
- **單向匹配**（`->`），與 MENTIONS 的雙向不同
- 起點是 `_get_semantic(query)` 拿到的 **top-5 種子 pericope**
- 沿預建的 CROSS_REFERENCES 邊跳一跳到目標 pericope
- 邊是建圖時就寫死的（markdown H3 + supplementary 清單），**不是 query-time 動態算的**

### 8.6 第 5 層：加權線性融合 + BGE Reranker

**檔案**：`backend/utils/retrieval/router.py` 各 `_route_rN`

| Route | 觸發條件 | graph 權重 | semantic | sql / cross-ref |
|------|---------|----------|---------|----------------|
| **R3** 人物 | ≥2 人物 | 0.9 | 0.7 | sql_supplement 0.5 |
| **R4** 事件 | 偵測到事件關鍵字 | 0.85 | 0.7 | sql_supplement 0.5 |
| **R5** 跨書 | ≥2 書卷 | graph 0.75 / cross_ref 0.85 | 0.65 | sql_chapter 0.85 |
| **R6** 地點 | 偵測到地名 | 0.85 | 0.7 | sql_supplement 0.5 |

**融合流程**（以 R3 為例）：

```python
# 1. 並行：graph + semantic
tasks = [
    asyncio.create_task(retrieve_by_entities(person_names)),  # 1-hop
    asyncio.create_task(_get_semantic(query)),                # BGE-M3
]
results = await asyncio.gather(*tasks, return_exceptions=True)

# 2. 套用 route 預設權重
_apply_weights(graph_results, 0.9)
_apply_weights(sem_results, 0.7)

# 3. 合併並 dedup（同 id 取最高 weight）
all_candidates = graph_results + sem_results
deduped = _dedup(all_candidates)

# 4. SQL 補強（從匹配章節抓額外段落）
supplements = await _sql_supplement(book_chapters, existing_ids, limit=3)
_apply_weights(supplements, 0.5)
deduped.extend(supplements)

# 5. 最終由 BGE reranker 重新排序（router.py:130）
ranked = reranker_mod.rerank(query, candidates, top_k=k, text_key="content")
```

**為何 weight 不是直接決定排名？**
- weight 只用於 **dedup tie-break**（同 id 多來源時保留最高權重的版本）
- 真正的順序由 **BGE reranker** 決定（cross-encoder 重算 query-passage 相關性）
- 例外：R1（精確經文匹配）跳過 rerank，直接 SQL 命中返回

### 8.7 use_graph Flag：Graph 子系統的全域開關

**檔案**：`backend/utils/retrieval/router.py:50-75`

```python
async def retrieve_and_rerank(
    query: str,
    ...
    use_graph: bool | None = None,  # 每請求覆寫
    semantic_only: bool = False,
) -> tuple[list[dict], dict]:
    effective_use_graph = use_graph if use_graph is not None else settings.rag_use_graph
```

| 模式 | 行為 |
|------|------|
| `use_graph=True`（預設） | R3/R4/R5/R6 全部啟用 graph 路徑 |
| `use_graph=False` | R3/R4/R6 跳過 graph_*，僅 semantic + SQL；R5 同時跳過 cross_reference |
| `semantic_only=True` | 完全繞過 signal detection 與 route dispatch，純 BGE-M3 + Qdrant baseline |

此 flag 用於評估 graph 對 RAG 品質的實際貢獻（A/B 對照）。

### 8.8 沒有使用的圖演算法（潛在優化方向）

| 演算法類別 | 範例 | 為何沒用 |
|-----------|------|---------|
| 排序類 | PageRank、Personalized PageRank | 候選集小（≤30），rerank 已足夠 |
| 嵌入類 | node2vec、FastRP、GraphSAGE | 未引入 GDS；建圖時無嵌入需求 |
| 神經類 | GNN、GCN、R-GCN | 訓練成本高；資料量不足以收斂 |
| 路徑類 | Shortest path、All paths | 1-hop 已涵蓋 99% 用例 |
| 社群類 | Louvain、Label Propagation | 沒有「找相似族群」的查詢場景 |
| 索引類 | Neo4j fulltext index（Lucene） | 目前用 `CONTAINS` 線性掃，量大時會慢 |
| 既有但未呼叫 | `find_related_entities()`（2-hop entity-entity projection） | 寫了但主路由沒用到，預留給未來 |

### 8.9 一句話總結

> Bible_RAG 的 Graph 檢索是 **schema-driven 1-hop graph lookup**：把 KG 當作「實體 → 相關經文」的 inverted index 來用，配合預建的 CROSS_REFERENCES 邊做跨書卷跳轉，最終排序交給 BGE reranker。圖結構提供 **召回（recall）** 與 **可解釋性（explainability）**，而非 **排序（ranking）**。

---

**文件結束**
