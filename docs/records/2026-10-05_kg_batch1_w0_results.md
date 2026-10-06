# KG 資料層修復第 1 批 W0：執行結果（準備與演練）

- **日期**：2026-10-04～05
- **依據**：[第 1 批計畫](2026-10-04_kg_batch1_plan.md) 的 W0 步驟與 §5.1 D3 閘門
- **證據**：`evaluation/results_quick/d3_*w0_aa*.json`、`detfix_*.json`、`w0_optin_*_legacy100.json`；R3 演練在 `bak/20261004/r3drill/`（gitignored）
- **本波不升版 KG**：三庫資料沒有改動。唯一的線上變更是後端決定性修正，部署前經 Kay 核可，見下文。

## 結論

- W0 五個步驟全部完成，驗收條件全過：
  - 拆檔前後測試數相同；
  - AA 中同路由題 100% 相同，路由殘差 r0 = 0；
  - R3 演練的計數等於 staging，check_identity 的 id 差為 0。
- **新發現並已修正：後端預設路徑不是決定性的。** 兩處用 set 迭代，結果隨每個 process 的 PYTHONHASHSEED 改變：
  - `_extract_book_chapters`：sql_supplement 取前 3 章，補哪 3 章會變；
  - `_pin_chapter_candidates`：雙章題的 pin 順序會變。

  同一題在 prod 和 backend-staging 的 top-5 不同。不修的話，D3 閘門量到的會是 hash 雜訊，而不是資料差異。已修正並部署到 prod。
- **新發現（未修）：opt-in 路徑與實體向量的建置不是決定性的。**
  - legacy-100 把策略全開，prod 對等價的 staging，有 19 題不同。
  - 根因一：`embed_entities` 挑段落標題時沒有排序。
  - 根因二：backend 的 Cypher 用 `LIMIT` 卻沒有完整排序（graph_person 的查詢連 ORDER BY 都沒有）。
  - 不修的話，W1 的 opt-in A/B 無法歸因。是否納入 W1 待 Kay 決定。
  - **補記（2026-10-06）：** Kay 2026-10-05 決定納入 W1，成為 W1-0「opt-in 決定性」，排在 1A／1B 之前修，修正為 087ab0d（backend 查詢）與 3a294a0（embed_entities），驗收見 e5fe097 與本檔末的「補記：W1-0 opt-in 決定性（2026-10-05）」。上一行保留原文。
- **D3 閘門可以用了。** W1、W2 的判準是 `d3_gate.py --route-residual-max 0`；路由殘差的處理方式見「對 W1 的意義」。

## 各步驟

| 步驟 | 結果 | commit |
|---|---|---|
| 1 歸檔與路徑參數化 | 110 個封存腳本的根路徑改讀 `BIBLE_RAG_ROOT`／`KGFIX_SP`；參數代回原值後與改寫前逐字相同。補歸檔 `questions_table.json` 與 kg_xref 68 題。從歸檔重放 1B `sim_kgxref`、1A `sim_1a`（gei/declared），輸出逐位元相同。重放步驟見 [2026-10-04_kg_fix/README.md](2026-10-04_kg_fix/README.md) | ae30554 |
| 2 拆檔 | test_db_env 拆成 3 檔（94 個 id 不變）；test_validate_kg 拆成 4 檔（原 68 個 id 保留，另加 9 個新測試）；kg_quality_baseline 改成目錄（合併後 24 項同序同內容）；Staging 章移到 [staging_promotion.md](../staging_promotion.md)；總計畫 §4 移到分批檔 | c4c6cc0、b8acc19、2a32965 |
| 3 D3 工具 | `quick_retrieval_eval --include-context`、`ab_compare --require-identical`、`evaluation/d3_gate.py`；evaluation 測試 136→208 | 4ee6712 |
| 4 AA | 見下文 | 56a5440、7d322f7（決定性修正） |
| 5 R3 演練 | 見下文 | — |

三套測試的最終狀態：scripts 568 passed、1 skipped（需要 KG_TEST_NEO4J_URI）；evaluation 208 passed；backend 55 passed。

## 後端決定性修正

**發現經過**：backend-staging 第一次啟動後做並排煙霧測試。「保羅歸主的經過是什麼？」在 prod 和 staging 上走同一個路由，用同一個映像、同樣的預設路徑資料，top-5 卻不同（`gal:1:2` 對 `act:26:3`），兩段都來自 sql_supplement。

**根因與修正**：

- 56a5440：`_extract_book_chapters` 改成依候選池中首次出現的順序，也就是語意分數高的章優先。`signal_detector` 的人物、事件、地點偵測改成首見順序去重，`EVENT_KEYWORDS` 等長時以字面排序。後面這幾項只影響 opt-in 策略。
- 7d322f7：`_pin_chapter_candidates` 改依 verse_refs 順序迭代。這處是 W0 交叉審查抓到的，第一輪漏掉。
- 預設路徑上其餘的 set 都只做成員檢查，已用 AST 掃描確認。
- `backend/tests/test_retrieval_determinism.py` 用 PYTHONHASHSEED 1–6 的子行程比對輸出。

**對 500 題的影響**：舊碼 prod 對新碼 staging，即 `detfix_prod_old` 對 `detfix_staging_new`：

- 路由相同的 491 題中，459 題 top-5 與 context 逐位元相同。
- 不同的 32 題，每一題的變動都牽涉 sql_supplement 補章，沒有其他來源。
- 這 32 題裡，新進 top-5 的 gold 有 7 段，被擠掉的 gold 0 段。
  - vrec：7 題升、0 題降；
  - ndcg：4 題升、11 題降；
  - mrr：1 題降（GENERAL_BIBLE_QUESTION_013，新補到的 2co:6:0 rerank 分數 0.49，排到第一）。
- 整體指標：

  | 指標 | 修正前 | 修正後 |
  |---|---|---|
  | vrec@6 | 0.766 | 0.768 |
  | anch@6 | 0.797 | 0.798 |
  | ndcg@6 | 0.848 | 0.847 |
  | mrr | 0.814 | 0.813 |

  差距都在雜訊範圍內。這是可重現性修正，不是品質改善。

**部署**：Kay 核可（2026-10-04）。

- 原映像保留為 `bible_rag-backend:pre-detfix-20261004`（ae72365e）。
- prod 改用 9bc112a6，由 7d322f7 建置；映像內的 `backend/` 與 `scripts/entity_extraction/` 和 HEAD 逐檔相同。
- 回滾：
  ```bash
  docker tag bible_rag-backend:pre-detfix-20261004 bible_rag-backend:latest
  docker compose up -d --no-build --force-recreate backend
  ```

**對舊數字的影響**：只要比較的兩組結果來自不同的 backend process（中間重建或重啟過容器），就會混入這份 hash 雜訊。範圍是：

- sql_supplement 的補章；
- 雙章題的 pin；
- opt-in 策略的查詢順序。

同一個 process 內的 A/B 不受影響。

## AA（第 4 步）

`d3_gate.py --label w0_aa --control-url :8000 --treatment-url :8001 --calibrate`：兩邊都是 9bc112a6，staging 接第 0 批的 staging 三庫，預設組態，500 題，101 分鐘。

| 項目 | 結果 |
|---|---|
| 第一次比對 | 路由相同的 489 題全部逐位元相同（core、附加段、context_sha）；11 題路由不同 |
| 重問第 1 輪 | 11 題中剩 5 題路由不同（EVENT_079、GENERAL_062、065、086、TOPIC_068） |
| 重問第 2 輪 | 0 題 |
| strategies | 兩邊都是 event_registry × 500 |
| invalid／未配對 | 0／0 |
| 判定 | PASS；**r0 = 0**；兩邊合併後的結果檔逐位元相同 |

- **路由不同只會是取樣雜訊。** `signal_detector` 與 `intent_classifier` 只讀靜態字典和 intent LLM（temperature 0.1），不碰任何資料庫，所以 KG 資料改變不可能讓路由改變。
- **容易翻的題目固定是那幾題。** EVENT_079、TOPIC_068 在決定性修正的比較中也出現在路由不同的名單裡。
- **跨 process 的佐證：** 修正後 staging 先跑的那一輪（`detfix_staging_new`）與 AA 合併結果相比，路由相同的 494 題全部相同。

## opt-in 策略（legacy-100）

`--graph-strategies all --ids-file legacy-100`：prod（live 三庫）對 backend-staging（第 0 批等價重建、`bible_entities_v2`）。兩邊是同一個映像，同樣的 8 個 opt-in 策略各套用 100 題。

| 項目 | 結果 |
|---|---|
| 路由 | 100／100 相同 |
| 同路由題 | 81 題逐位元相同，**19 題不同**；19 題全部都跑了 entity_query |
| 被換掉／換進的段落（以勝出策略計） | graph_person 6／7、entity_query 6／7、cross_ref_expand 2／0、graph 2／1、graph_event 1／1、entity_path 1／1、hybrid 1／2、book_anchor 1／1 |

指標（只是記錄，100 題不構成顯著差異）：

| 指標 | prod | staging |
|---|---|---|
| vrec | 0.688 | 0.697 |
| anch | 0.772 | 0.781 |
| ndcg | 0.850 | 0.857 |
| mrr | 0.808 | 0.807 |

**資料等價，opt-in 卻有 19% 的題不同。根因有兩個，都是「結果取決於存放順序」：**

1. **建置端：`scripts/embed_entities.py`（Step 8a／8b）。**
   - 原因：`collect(DISTINCT title)[0..5]` 沒有排序，挑哪 5 個段落標題寫進 embedding 文字（`常見於:…`）取決於 Neo4j 的走訪順序。
   - prod `bible_entities` 對 staging `bible_entities_v2`：
     - 9,124 個實體的 description 全部相同；
     - 但 pericope_ids 有 4,512 個不同、pericope_titles 有 4,377 個不同；
     - 向量逐位元相同 3,516 個，cos<0.99 的有 2,894 個（最低 0.38）。
   - 結果：重建出來的向量不可重現，entity_query 跟著變。
   - 另一個無害的格式差異：prod 的 payload aliases 是 JSON 字串（9,093 個），v2 是 list。`_build_text` 兩種都會解碼，不是向量差異的原因。
2. **查詢端：backend 的 Cypher 用 `LIMIT` 卻沒有完整排序。**
   - `get_entity_related_pericopes`（graph_person 的主要來源）只有 `LIMIT`，完全沒有 `ORDER BY`。
   - 其他查詢有排序，但排序鍵會同分：
     - 實體名稱查詢：`mention_count DESC`；
     - xref：`votes DESC`、`seed_support DESC, votes DESC`；
     - entity_path：`hop_distance ASC`；
     - 相關實體：`shared_pericopes DESC`。
   - 等價的兩個庫，同分時會取到不同的列。

**對 W1 的意義**：§5.2 的 opt-in A/B 比的是 prod 和 staging；不修這兩點，就算資料完全沒變，也有約 19% 的題被改變，資料效果無法歸因。計畫的 C2／X1 只替 xref 加了決勝鍵。預設路徑不受影響（AA 500／500 相同）。

## R3 演練（第 5 步）

證據在 `bak/20261004/r3drill/`：

- **Neo4j**：
  - staging dump，停機約 8 秒，產出 29.7 MB；
  - 載入拋棄式 volume 約 2 秒；
  - 臨時容器（7689）的計數是 13,589 個節點、319,988 條關係，與 staging 相同。
- **PG**：把 staging 的實體表換進拋棄式資料庫 `bible_rag_r3drill`，在單一交易內完成，不到 1 秒，PK 與 FK 都保留。
- **check_identity**（對臨時 Neo4j）：
  - PG 與 Qdrant 的 id 差都是 0。
  - PG 的描述差 3,045、aliases 差 10，是第 0 批就記錄的 PG 漂移，屬於第 1D 批的範圍。
  - Qdrant（bible_entities_v2）全部欄位差 0。
- **收尾**：臨時容器、volume 與資料庫都已移除，只留下 dump 檔。

## 對 W1 的意義

- **D3 判準**：

  ```bash
  d3_gate.py --label w1 --control-url http://localhost:8000 --treatment-url http://localhost:8001 --route-residual-max 0
  ```

  - 同路由題必須 100% 相同。
  - 路由殘差不可能來自 KG 資料。萬一兩輪重問後仍有殘差，先用同樣條件再重問一次確認是雜訊，不要直接判失敗或放寬 r0。
  - 預期中，同路由題的差異只會出現在 opt-in 策略讀的資料上，預設路徑讀的是靜態 registry。
- **backend-staging 要用 W1 HEAD 建的映像。** W0 用的是 scratchpad 裡的 compose override（`image: bible_rag-backend:detfix`）。W1 若要改 backend，就重建並另外打 tag，不要覆寫 prod 正在用的 latest。
- 以下拆分留到第 1 批之後處理（W0 交叉審查建議）：
  - `router.py` 1,786 行，超過 800 行規則；
  - 建議把 pin 相關的 helper 拆到 `retrieval/pins.py`；
  - 第 1 批期間不拆，避免 D3 映像改變。

## 補記：W1-0 opt-in 決定性（2026-10-05）

Kay 決定把上面的 opt-in 不決定性納入 W1，排在 1A／1B 之前修，修正為 087ab0d（backend 查詢）與 3a294a0（embed_entities）。

| 驗證 | 修正前 | 修正後 |
|---|---|---|
| 跨庫探針：13 類查詢，約 1,000 次呼叫，prod 對 staging Neo4j／PG | 大量不同：xref 88/120、related 55/60、entity_path 27/40、multi_hop 19/20、graph_person 17/150、place 18/80、名稱查詢 80/80（含 labels 順序） | 全部相同。唯一例外是 K10 已知的 mention_count 殘差：event:baoluoxushuguizhujingguo 在 prod 是 4、在 staging 是 1 |
| 實體向量：分別從 prod 與 staging Neo4j 重建 | 舊 collection 有 2,894 個 cos<0.99 | 9,124 個向量逐位元相同，payload 全同 |
| legacy-100 opt-in 全開 | 19 題不同 | **1 題**（GENERAL_BIBLE_QUESTION_016） |

legacy-100 這一列的條件是兩邊都用新映像 w1det：一邊是臨時容器接 prod 三庫（只讀），實體向量用 detA；另一邊是 staging，用 detB。

**剩下這 1 題不是存放順序造成的。** 同一個 backend 對這題重問 3 次，結果在兩組 top-5 之間切換，兩個庫都會出現這兩組結果。R5 的 `graph` 策略直接用 intent LLM 抽出的實體名稱（temperature 0.1 取樣），路由相同但實體名稱可能不同。

所以 opt-in 路徑還有一個 LLM 取樣造成的雜訊地板。在這組 100 題、各跑一次的比較裡，就是這 1 題。預設路徑不讀 LLM 實體，所以 D3 不受影響。§5.2 的 opt-in A/B 遇到差異題時，要先重問排除取樣雜訊。

**環境狀態：**
- 臨時容器、含密碼的 env 檔與 `bible_entities_detA` 都已移除，正式 collection 的指紋不變。
- backend-staging 目前跑 w1det 加 `bible_entities_detB`，到 W1 重建為止。
- prod 仍是 9bc112a6，新的查詢會在 W1 升版時一起上線。
