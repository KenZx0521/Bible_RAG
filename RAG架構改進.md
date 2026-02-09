# 聖經 RAG 智慧路由策略

> **Signal-driven routing**：根據查詢信號特徵選擇最佳搜尋路徑，取代全並行策略

---

## 引擎圖例

| 引擎 | 說明 |
|------|------|
| **SQL** | 精確經文查詢（PostgreSQL） |
| **Semantic** | 語意向量搜尋（Embedding + ANN） |
| **Graph** | 知識圖譜遍歷（Neo4j） |
| **Cross-Ref** | 交叉引用展開（Neo4j prophecy/typology 邊） |

---

## 信號定義 (Signals)

| 信號 ID | 名稱 | 範例 | 偵測方式 |
|---------|------|------|----------|
| `has_book_chapter_verse` | 書卷+章:節 | 約翰福音3:16, 創世記1:27 | Regex: `/[書卷名]\s*\d+:\d+/` |
| `has_book_chapter` | 書卷+章（無節） | 羅馬書第8章, 以弗所書第6章 | Regex: `/[書卷名]\s*第?\d+章/` |
| `has_multi_person` | 多人物（≥2） | 亞伯拉罕、以撒、雅各 | NER or dict match ≥2 persons |
| `has_event_keyword` | 事件關鍵詞 | 十災, 過紅海, 被擄 | Dict match: event entity list |
| `has_multi_book` | 跨書卷（≥2） | 出埃及記...約翰福音 | Regex: ≥2 distinct book names |
| `has_place` | 地名 | 伯利恆, 耶路撒冷, 迦南 | Dict match: place entity list |

---

## 路由規則 (Routes)

### R1 — 精確經文查詢 (Exact Verse Lookup)

- **觸發條件：** `has_book + has_chapter:verse`
- **預估延遲：** ~30ms
- **範例問題：** 「根據約翰福音3:16，神如何表達祂對世人的愛？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **SQL** | 精確查找 書卷+章:節 | 100% | ~30ms |

**策略說明：** 有明確章節，SQL 直接命中，無需其他路徑。

**降級策略 (Fallback)：** 若 SQL 無結果 → 降級為 R2

---

### R2 — 章節範圍 + 語意搜尋 (Chapter Scope + Semantic)

- **觸發條件：** `has_book + has_chapter (no verse)`
- **預估延遲：** ~230ms
- **範例問題：** 「根據羅馬書第8章，保羅如何描述信徒在患難中仍有盼望？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **SQL** | 過濾該章所有經節 | 60% | ~30ms |
| 2 | **Semantic** | 主題語意搜尋 (topic keywords) | 40% | ~200ms |

**策略說明：** SQL 縮小範圍到指定章，Semantic 從中找最相關段落。先 SQL 再 Semantic，非並行。

**降級策略 (Fallback)：** 若 SQL 空 → 純 Semantic 搜尋

---

### R3 — 人物關係圖譜 (Person Graph Traversal)

- **觸發條件：** `has_person ≥ 2, no chapter/verse`
- **預估延遲：** ~380ms
- **範例問題：** 「亞伯拉罕、以撒、雅各三代之間的關係和神的應許如何延續？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **Graph** | 實體匹配 → MENTIONS 遍歷 → 關係邊 | 50% | ~150ms |
| 2 | **Semantic** | 人物名 + 關係語意搜尋 | 30% | ~200ms |
| 3 | **SQL** | 相關書卷章節補充 | 20% | ~30ms |

**策略說明：** Graph 先找人物節點和關係邊，取得涉及的經文 ID。Semantic 補充敘述性上下文。SQL 精確取回具體經節。

**降級策略 (Fallback)：** Graph 無實體命中 → 純 Semantic + SQL

---

### R4 — 事件序列搜尋 (Event Sequence Search)

- **觸發條件：** `has_event OR (has_book + has_chapter + event pattern)`
- **預估延遲：** ~380ms
- **範例問題：** 「十災事件的順序和法老的反應為何？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **Graph** | 事件實體匹配 → 時序關係遍歷 | 40% | ~150ms |
| 2 | **Semantic** | 事件描述語意搜尋 | 35% | ~200ms |
| 3 | **SQL** | 相關章節範圍補充 | 25% | ~30ms |

**策略說明：** Graph 找事件節點和序列關係。Semantic 搜尋事件描述的段落。若有明確章節，SQL 優先過濾。

**降級策略 (Fallback)：** 無事件實體 → 純 Semantic

---

### R5 — 跨書卷交叉引用 (Cross-Reference Multi-hop)

- **觸發條件：** `has_multi_book OR cross-ref pattern`
- **預估延遲：** ~580ms
- **範例問題：** 「出埃及記的嗎哪如何預表約翰福音的生命糧？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **Cross-Ref** | Neo4j 交叉引用展開 (prophecy, typology) | 35% | ~200ms |
| 2 | **Graph** | 多實體 MENTIONS 遍歷 | 25% | ~150ms |
| 3 | **Semantic** | 神學主題語意搜尋 | 25% | ~200ms |
| 4 | **SQL** | 各書卷精確經節取回 | 15% | ~30ms |

**策略說明：** 最複雜路徑。Cross-Ref 和 Graph 並行展開多書卷關係，Semantic 補充主題上下文，SQL 取回具體經節。

**降級策略 (Fallback)：** Cross-Ref 無結果 → Graph + Semantic 雙路徑

---

### R6 — 地名 + 語意搜尋 (Place-based Search)

- **觸發條件：** `has_place, no chapter/verse, no multi-person`
- **預估延遲：** ~380ms
- **範例問題：** 「伯利恆在聖經中有哪些重要事件？」

| 步驟 | 引擎 | 動作 | 權重 | 延遲 |
|------|------|------|------|------|
| 1 | **Graph** | 地名實體 → LOCATED_IN 遍歷 | 45% | ~150ms |
| 2 | **Semantic** | 地名 + 語境搜尋 | 35% | ~200ms |
| 3 | **SQL** | 含地名的經節過濾 | 20% | ~30ms |

**策略說明：** Graph 以地名為起點找相關人物和事件。Semantic 補充語境。

**降級策略 (Fallback)：** 地名不在圖譜 → 純 Semantic

---

## 決策樹 (Decision Tree)

優先級從高到低：

```
1. 有 書卷+章:節？        ── YES → R1 精確經文查詢
                            ── NO  ↓
2. 有 書卷+章（無節）？     ── YES → R2 章節範圍 + 語意搜尋
                            ── NO  ↓
3. 有 ≥2 書卷名？          ── YES → R5 跨書卷交叉引用
                            ── NO  ↓
4. 有 ≥2 人物名？          ── YES → R3 人物關係圖譜
                            ── NO  ↓
5. 有 事件關鍵詞？          ── YES → R4 事件序列搜尋
                            ── NO  ↓
6. 有 地名？               ── YES → R6 地名 + 語意搜尋
                            ── NO  ↓
7. 其他                    ── YES → Semantic fallback
```

---

## 題型對應表 (Question Type → Route Mapping)

| 題型 | 題數 | 主路由 | 信號 | 問句模式 | 路徑策略 |
|------|------|--------|------|----------|----------|
| VERSE_LOOKUP | 20 | R1 | 書卷+章:節 | 「根據 [書卷] [章]:[節]，...」 | SQL → 直接命中 |
| TOPIC_QUESTION | 20 | R2 | 書卷+章 + 主題詞 | 「根據 [書卷] 第[N]章，...如何描述...」 | SQL(章過濾) → Semantic(主題) |
| PERSON_QUESTION | 20 | R3 | ≥2 人物名 | 「[人物A]、[人物B]、[人物C]之間的關係...」 | Graph(關係) → Semantic(敘事) → SQL(經節) |
| EVENT_QUESTION | 20 | R4 | 事件詞 + 時序模式 | 「[事件]的經過為何？」 | Graph(事件序列) → Semantic(描述) → SQL(章節) |
| GENERAL_BIBLE | 20 | R5 | ≥2 書卷 + 預表/應驗 | 「[書卷A]如何預表/呼應[書卷B]？」 | Cross-Ref ∥ Graph → Semantic → SQL |

---

## 關鍵設計原則

1. **精確優先：** 有明確章節引用時，SQL 先行，省去 Semantic/Graph 開銷
2. **圖譜先行：** 無章節但有人物/事件/地名時，Graph 提供結構化起點
3. **語意兜底：** 所有路徑都以 Semantic 作為補充或 fallback
4. **跨書卷最重：** 涉及多書卷的交叉引用走最完整的四引擎路徑
5. **非並行：** 除 R5 的 Cross-Ref∥Graph 外，步驟按序執行，前步結果可引導後步查詢

---

