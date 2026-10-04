# KG 資料層修復：第 1 批計畫（1A–1D）

> 2026-10-04｜branch feat/graph-strategy-gating｜HEAD a32fbea｜規劃期間全程唯讀：repo 沒有改動，資料庫只做 READ，容器沒有啟停。
> 證據都在 `SP=/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/batch1plan/`
> - 規劃：`planner_1A/`、`1B/`、`1C/`、`1D/`、`crossplanner/`
> - 審查：`reviewer_1A/`、`1B-reviewer/`、`1C_reviewer/`、`1D-reviewer/`
>
> **/tmp 可能被清掉，所以 W0 的第一件事是歸檔。**
>
> 標記說明：
> - 【驗】：離線模擬、READ 查詢或讀碼確認過。
> - 【推】：推論。
> - 【更正】：審查者推翻了規劃值。
> - 【待重算】：要等決策或修正後重跑模擬。

> **歸檔**：證據已複製到 `docs/records/2026-10-04_kg_fix/batch1/`（腳本與 <200 KB 的輸出），完整 scratchpad 在 `bak/20261004_kgfix_evidence/batch1plan_scratchpad.tgz`（gitignored）。下文的 `SP=/tmp/...` 路徑是規劃時的位置。

---

## 0. 一頁摘要

### 0.1 第 1 批會修掉什麼

| 波 | 缺陷 | live → 第 1 批後 | 來源 |
|---|---|---|---|
| W1·1A | 沒有出處的衍生邊（H3） | 374 → 0 | 驗 reviewer_1A/r4_h3_on_staging.py |
| | domain/range 違規（H9） | 14 → 0 | 同上 |
| | FATHER_OF 雙向矛盾／女性 head | 25 / 42 → 0 / 0 | 驗 planner_1A/sim_1a.py（審查者重跑 sha b564a2a8 相同） |
| | 有 ≥2 個非女性父母的子女（全部父母編碼） | 135/262（51.5%）→ 60/402（14.9%）；加同名防護後會再降【待重算】 | 驗 reviewer_1A |
| | 10.3 共現升格邊／反向物化邊／字母序規則邊／LLM Event–Event 邊 | 9,060 / 756 / 771 / 26 → 全部 0 | 驗 prod READ |
| | 語意邊總數 | 15,926 → 非錨定 5,301，加上錨定邊（原模擬 425）【待重算】 | 驗 reviewer_1A/r1_flow.py |
| | 親屬邊 | 1,571 → 約 615（原模擬）【更正：計畫的「<300」不成立】【待重算】 | 驗 |
| W1·1B | supplementary 錨點錯位（首節規則／逐節規則） | 59 / 62 → 0 | 驗 1B-reviewer/r3_r4.py |
| | 被靜默丟掉的定義 | 16 → 0 | 驗 r1_supp.py |
| | 被 curated 邊吞掉的 TSK 證據 | 856 對 → 0（curated 邊帶 votes 923/924 條） | 驗 r2_tsk.py |
| | votes≥999 被誤判為 curated | 3 → 0 | 驗 |
| | heb:1:0 前 8 名中的錯位 curated 邊 | 6 → 0 | 驗 r5_backend.py |
| W2·1C | 書名區 MENTIONS（R1） | prod 1,938／staging 2,124 → 0。純書名假邊 −1,693（這是 staging 口徑；計畫寫的 1,745 是 live 口徑） | 驗 1C/result_pos_cfull.json，1C_reviewer 獨立重放 |
| | 馬可／路加／馬太的段落錨點 | 103 / 149 / 160 → 7 / 3 / 10（馬太剩下的 5 條是子字串問題 M2，歸 2B） | 驗 |
| | CKIP 重複位置（R9） | 4,131 → 0 | 驗 |
| | 書名全稱實體／縮寫碎片實體 | 12 / 8 → 0（珥、但豁免） | 驗 |
| W2·1D | 空白名（H4 全型別）／同型孿生 | 180 / 116 → 0 | 驗 1D-reviewer/r1_twins.py |
| | junk Event / Theme / Object（R8） | 27 / 36 / 25 → 0 | 驗 r3_drops.py |
| | 歧義 alias（R10，白名單之外） | 21 → 0 | 驗 r2_registry.py |
| | 三庫描述與 aliases 漂移（H5） | PG 描述 3,045、PG aliases 14、Qdrant 字串 aliases 9,093 → 全部 0 | 驗 |
| | extraction_method 為 null | 9,104 → 0 | 驗 READ |

### 0.2 不會改變的東西

- **線上預設 QA。** 預設 `graph_strategies=["event_registry"]` 只讀靜態 registry。每一波都用 D3 硬閘門驗證：500 題中同路由的題目，top-5、附加段落、context sha 必須逐位相同。
- **`backend/data/event_registry.json`。** 33 個事件逐位相同，由 D1 `--check` 驗證。前提有兩個：
  - curated Event 的 alias 豁免歧義過濾。不豁免的話會掉到 28 個事件【驗 r2_registry.py】。
  - babieta 豁免字典名規則。
- **W1 期間**，PG、Qdrant、MENTIONS、/api/v1/entity 都不動。

### 0.3 會改變的東西

| 對象 | W1 | W2 |
|---|---|---|
| /api/v1/entity | 不變 | 387 個實體的 related_passages 改變；183 個實體的 mention_count 改變；約 200 個舊 id 回 404（確切數字依 id 契約）【待重算】；P/P/G 描述首次對外曝光（依 C6 決策） |
| opt-in 策略 | entity_path 失去「人物→事件→人物」的共現 2 跳路徑；xref 候選在 262 題代理中有 17 題改變（上界） | graph_person、graph_place、graph_event、entity_query、entity_path |
| 事件層覆蓋 | 有參與者 83.1% → 34.0%，有地點 74.7% → 31.4%。這是 D2（10.3 退場）的直接後果，要等 2A 補回 | — |
| 論文 | sec3_kg.tex :164 :170 :184-185 :199 :210 :212 :263 :268 :308；sec6 :114 :313-317 :481；sec7 :316；main.tex:62；sec1:62 | sec3/sec6 的實體數與 MENTIONS 數 |

### 0.4 工時與日程【推】

- **人時（用總計畫同一把尺）：** W0 8–12，1A 30–41，1B 17–24，1C 24–32，1D 38–48，合計約 **117–157 h**。總計畫原估 80–110 h。
- **第 0 批的校準：** 計畫估 36–50 h，實際牆鐘約 2.6 h（git log 10:46→13:22）。工程本身不是瓶頸，日程由三件事決定：
  - 機器時間：NER 每次 34 分鐘，500 題評估每組約 48 分鐘。
  - Kay 的核可點。
  - 升版窗口。
- **機器時間：** W0 約 2 h，W1 5–10 h，W2 8–16 h（包含 500 題 A/B）。
- **日程：約 7–9 個工作天。** W0 1 天，W1 3 天，W2 3–5 天。

### 0.5 需要 Kay 決定的事（細節見 §7）

| 時點 | 決策 |
|---|---|
| W0 開工前 | K0 |
| W1 實作前 | K1–K10、X1–X4 |
| W2 實作前 | C1–C6、E1–E9 |
| 跨波 | U1–U4 |

**C1（1C 與 1D 的 id 契約）和 C4（流珥）會擋住 W2 開工。**

---

## 1. 分波計畫

| | W0 準備（不升版） | W1：1A＋1B | W2：1C＋1D |
|---|---|---|---|
| 前置 | K0 已核可；三套測試全綠 | W0 完成；K1–K10、X1–X4 已決；R0 完成：三庫備份、`git tag kg-pre-batch1-w1`、`docker tag bible_rag-backend:latest bible_rag-backend:kg-pre-batch1-w1` | W1 已升版並 ratchet；C1–C6、E1–E9 已決；R0 完成，另加 PG 的 entity_tables.sql、Qdrant snapshot、image tag |
| 步驟 | 見下方 W0 步驟 | 見下方 W1 步驟 | 見下方 W2 步驟 |
| 驗收 | 拆檔前後測試數相同；AA 中同路由題 100% 相同，並記錄路由殘差 r0；R3 演練的計數等於 staging（節點 13,589、關係 319,988），check_identity 的 id 差為 0 | §2.1 與 §2.2 的閘門全過；D3；opt-in A/B 報告；/api 的 W1 清單與 prod 完全相同 | §2.3 與 §2.4 的閘門全過；D3；/api 的 W2 清單符合預期 |
| 升版 | 否 | 見下方 W1 升版 | 見下方 W2 升版 |
| 回滾 | — | 載回 Neo4j dump；image 退回 kg-pre-batch1-w1。資料回滾時 backend 不必退，因為第 1 步的 image 同時相容新舊資料 | Neo4j dump、用 PG entity_tables.sql 換回兩張表、.env 切回、image tag。**W2 是第一份快照，沒有上一份快照可以重載，只能用 dump 回滾** |

**W0 步驟**
1. 歸檔 scratchpad 的證據到 docs/records/2026-10-04_kg_fix/batch1/，包括 kg_xref 68 題、questions_table.json 與各模擬器，並把路徑改成參數。
2. 拆檔，見 §4。
3. D3 工具（TDD）：quick_retrieval_eval 加 `--include-context`，ab_compare 加 `--require-identical`。
4. 零號演練（AA）：在第 0 批的 staging 上啟動 backend-staging，prod 與 staging 各跑一次 500 題預設組態，另用 legacy-100 量 opt-in 策略。
5. R3 演練：把 staging 的 dump 載入拋棄式 volume（臨時容器 7689）；把實體表換進拋棄式 PG DB，跑 check_identity。

**W1 步驟**
1. 1A 與 1B 並行實作。
2. staging 全量重建。**跳過 Step 1**，並先做 sha 前置檢查。
3. R2 閘門。
4. 核可期望檔與允許清單。
5. 升版。

**W2 步驟**
1. 先決定 C1。
2. HEAD 重跑 NER-0。
3. compile 骨架，並通過「規則全關時與現行鏈等價」的測試。
4. 1C 各缺陷，一個缺陷一個 commit。
5. 1D 各缺陷。
6. 最終 NER。
7. staging 重建。
8. R2 閘門。
9. 核可期望檔。
10. 升版。

**W1 升版**
1. backend 先上（1B 過渡版）：`up -d --build backend`，跑 20 題煙霧測試，再跑「模擬等於實測」探針。
2. staging dump 後載入 prod Neo4j，停機約 1 分鐘。
3. R4：在乾淨的 shell 跑，參數 `--target prod`。
4. R4 之後才 ratchet 與 accept，並與允許清單放同一個 commit。
5. PG、Qdrant、.env 都不動。

**W2 升版**
1. 載入 Neo4j。
2. PG 在單一 transaction 內換掉 entities 與 entity_mentions。
3. .env 只改 `QDRANT_ENTITY_COLLECTION`，指向 W2 staging 建好的 collection（建議 bible_entities_v3，v2 留作第 0 批的對照）。
4. `up -d --build backend`，同時移除 1B 的過渡 coalesce。
5. R4。
6. ratchet。
7. staging.env 遞增到下一版。

**W1 重灌鏈**

0 → check_step0 → validate_output（改為必跑）→ **〔跳過 1；前置檢查 sha256(entities.jsonl)=9f2d1f39…、entity_mentions.jsonl=ba7ed188…，不符就停〕** → 6.05 → 3 → 5 → 6.1 → 8a → 9 → 10.1 → 10.2 → 10.4 → 10.5 → 7（replay `--fail-on-stale`，stale 必須為 0）→ 8b → 10.6 → export --check

**W2 重灌鏈**

0 → check_step0 → validate_output → 1（ner，內含 validate_mentions）→ 1（merge）→ K1c compile_entities → KV1 `validate_kg --snapshot` → 3（`--kg-dir`）→ 5（`--kg-dir`）→ 6.05（讀 id_migration）→ 6.1 → 8（只跑一次）→ 9 → 10.6（含 `cleanup_noise_entities --check`）→ export --check

---

## 2. 各批

### 2.1 第 1A 批：Step 6.05 關係後處理，10.3 退場

涵蓋 REL-01–06、REL-08、REL-09、G-2、G-3。

**改動清單**（測試一律先 RED；一個缺陷一個 commit，約 20 個 commit）

| # | 內容與檔案 | 測試 | commit |
|---|---|---|---|
| C1 | models.py：新增 phase 6/7；新增 source、run_id、schema_version、pp_version、confidence_raw、direction_verified、sources、support_pericopes、evidence_count；舊列依 phase 推導 source | test_relation_models.py | feat: 關係列 provenance 欄位 |
| C2 | 新增 entity_extraction/geo_rules.py（從 cleanup 搬出）；最小版 config/curated/entity_overrides.yaml（只放 yehehua→Person） | test_geo_rules.py（dan 759→26）、test_entity_overrides.py | refactor: 「但」的地理判斷與型別覆寫改為單一來源 |
| C3 | anchored_rules.py 加 yaml：句型 P1–P4，同一節內比對，端點經該段 MENTIONS 解析。**詞庫只用 P/P/G**（E/O/T 垃圾如「兒子大衛」有 683 個 token）；**清單項後面接「的」就結束清單**；**同名防護：子女已有 curated、prior 或 llm 的其他父母時，abstain 並寫入 conflicts**；deny group:yehehua | test_anchored_rules.py：原本列的案例，加上 2ch 28:12、jer 36:12、jer 38:1、gen 28:9、2sa 2:13；「約翰的兒子西門」不得連到使徒約翰 | feat: 錨定句型親屬抽取 |
| C4a | relation_postprocess.py 骨架：`--rules none` 等價、決定性輸出；report 要模擬 10.2 刪除泛名詞 Event 端點的 80 條 | test_relation_postprocess.py | feat: 6.05 骨架 |
| C4b–j | 九條規則，各一個 commit：丟 inverse 752 條；規則邊換成錨定邊（−772）；丟 LLM 的 Event–Event 邊 38 條；出處閘門 1 條；domain/range 13 條；flag_id_order 48 條（**改讀 direction_pair 表，與 yaml 的 inverse 脫鉤**）；親屬方向矛盾與無向去重；每鍵唯一列；寫入 provenance | 每條規則各有測試 | 9 個 fix commit |
| C5 | import_relations_neo4j：改成 `SET rel = row.props`；檢查 written==rows；鍵唯一；空層防護。**標準鏈不帶 --replace**，它只給 staging 手動使用 | test_import_relations.py；同時修改 W0 拆出的 test_db_env 檔中的 fixture | fix: 關係匯入整組覆寫 |
| C6a–c | R5 改為 opt-in，帶性別的 inverse 改 null；刪除 R2、rule_classifier、prompt_signals；修正 PRECEDED_BY 的描述 | test_relation_schema.py、test_extract_relations_policy.py | 3 個 commit |
| C7 | backfill_event_relations：沒有 `--legacy-cooccurrence` 時結束碼 2 | test_backfill_event_relations_retired.py | fix: 10.3 退出預設鏈 |
| C8 | kg_validate：H3 改用 source；新增 H11；R6 新增全部父母編碼的指標；**model.py 的 live 查詢加讀 direction_verified 與 sources**；新增 6 個探針，另加流珥的 absent 探針（yeteluo SON_OF yisao、naha SON_OF yeteluo） | test_validate_kg_checks.py（W0 拆出的檔） | feat: H11 與 R6 指標 |
| C9 | 文件：新增 Step 6.05、更新重灌鏈、Step 7 改寫成「1A 不改 MENTIONS」；同步 ARCHITECTURE.md:243-249、kg_construction_overview.md:167；註明已歸檔的證據腳本要在 a32fbea 上執行（它們 import classify_by_rules） | test_docs_alignment | docs |
| C10 | staging 驗證紀錄與期望檔 | — | docs: 1A 結果 |

**模擬數字**（planner_1A 產出，reviewer_1A 重跑核對）

| 項目 | 值 | 狀態 |
|---|---|---|
| 6.05 輸入與丟棄 | 輸入 6,958 列。丟棄：rule 772、inverse 752、Event–Event 38（live 為 26）、domain/range 13、閘門 1、與 prior 相反 1、矛盾 1、無向重複 6 | 驗（兩邊一致） |
| 標記方向未驗證 | 48 條（計畫寫 75） | 【更正】驗 |
| 非錨定邊保留（扣掉 10.2 的 80 條後） | 5,301 | 驗 |
| 錨定唯一鍵 | 原本 437；改成 P/P/G 詞庫後 527；加上清單修正與同名防護後未知 | 【待重算】 |
| 錨定精確率 | 規劃者的 57/57 是「文字層」判讀；審查者以 seed 4242 抽樣，文字層 43/45（Wilson 下界 0.852）。實體層的錯例：彼得 SON_OF 使徒約翰、約瑟 SON_OF 約南、便雅憫 SON_OF 比勒罕 | 【更正】撤回價值表的「≥0.91」，改以 id 正確的人工閘門為準 |
| 錨定父母邊落在多父母衝突 | 126/420（30%），涉及 55 個子女 | 驗 |
| R6 函數性 | 只算 FATHER_OF 時是 135/252 → 3/49，但多父母的問題轉移到 SON_OF。改用全部父母編碼：135/262 → 60/402 | 【更正】 |
| 第 0 批 4 條 SON_OF 的成因 | 不是同一次匯入裡先到先得，而是 prod 舊匯入的屬性因 onCreate-only 沒有被刷新（REL-10） | 【更正第 0 批紀錄】驗 |

**相對 prod 的預期 diff**
- relationships 有 28 型改變：PARTICIPATED_IN −5,641、OCCURRED_IN −3,419；FATHER_OF、SON_OF 等親屬型【待重算】。
- ee_edges：舊鍵 `* source=-` 全部歸零；新鍵有 prior 22 鍵（+64）、llm 35 鍵（+5,233）、anchored_rule【待重算】。
- labels、mentions、entity_ids、descriptions、aliases、registry 都是 0 差。

**第 0 批的殘差會跟著上線**【驗 reviewer_1A r2、r3】。diff_kg 量不到這些，必須寫進紀錄並 accept：
- mention_count 有 4 個實體不同：event:shanshangbaoxun 23→1、兩個保羅歸主事件 4→1、person:yeteluo 3→30。
- MENTIONS 屬性：start_pos 等欄位有 5,782 條不同，source_granularity 有 40,261 條不同。
- R1 由 1,938 變 2,124，用 `--accept R1` 處理。

**閘門**

| 項目 | 目標 | 硬門檻 |
|---|---|---|
| H3、H9、H11（source_null、inverse、cooccurrence、unflagged_id_order、undirected_dup） | 0 | 是 |
| R6 contradictions、female_head（31 人清單）、failing_probes | 0 / 0 / [] | 是 |
| R6 全部父母編碼的指標 | ratchet，不得退步 | 否（record） |
| PROBES | failing ⊆ baseline 扣掉 1A 修好的 4 個；新增探針全過 | record（subset 規則） |
| 邊集合等同 | staging 的 (head, type, tail, source) 排序後的 sha，等於 relations_clean 扣掉 10.2 端點後的 sha | 是 |
| 6.05 決定性 | 連跑兩次 sha 相同 | 是 |
| 錨定規則人工抽樣（n≥40，**以 id 正確計**） | Wilson 下界 ≥0.85 | 是 |
| diff_kg（允許清單外 0、registry 0）、D1、H1、H2、H7、H10 | — | 是 |
| D3 | 同路由題逐位相同 | 是 |
| entity_path 500 題 Δvrec | ≥ −0.005（事前登記：失敗也不回退 10.3） | 否（報告） |

**風險**
- 同名不同人仍是主要殘留，屬延後-A。
- 事件層覆蓋 −49 pp，要到 2A 才補回。
- 錨定輸出依賴 NER，W2 之後要重產期望檔。
- H3、H9、H11 升為 hard 後，升版前對 prod 跑 validate_kg 必然結束碼 1，所以升版前只對 staging 驗。

### 2.2 第 1B 批：交叉引用（XREF-1/2/3/4）

**改動清單**

| # | 內容與檔案 | 測試 | commit |
|---|---|---|---|
| C1 | backend 的 neo4j_db.py 三條 xref Cypher 與 cross_ref_retriever：過渡寫法 `coalesce(r.curated, r.source IN ['markdown','supplementary'])`，刪除 999 哨兵 | backend/tests/test_cross_ref_weight.py，包含 votes=1268 且 curated=False 時權重 0.60 | fix(backend) |
| C2 | 排序加決定性 tiebreak，排序鍵依 X1 | 原始碼斷言 | fix(backend) |
| C3 | nt_cross_references 改用經文座標，新增 curated_xrefs.py，process_bible 改成 fail-fast。**先把舊的 161 筆定義凍結成 records/…/supp_defs_a32fbea.json**，舊證據腳本改讀這個檔 | test_curated_xrefs.py、test_supplementary_xref.py（golden fixture） | fix |
| C4 | 依 pair 聚合，寫 curated 與 tsk 旗標、curated_sources。**markdown 邊改寫 md_anchors，取代 verse_start/verse_end**。**豁免改存 supp_tsk_exempt_anchors，因為 Neo4j 不能存含 null 的 list**。import_neo4j 加重複 pair 防護，檔案不存在時跳過 | test_curated_xrefs.py、test_import_neo4j_xref_guard.py（含「沒有檔案」案例） | fix |
| C5a | 刪除 rev 20:4→isa 65:17 與 rev 19:1→psa 118:1 | test_supplementary_xref.py | fix |
| C5b | rev 19:11-16→dan 7 依 X2 處理 | 同上 | fix |
| C6a | TSK 匯入改成無條件 SET，加計數閘門 | test_import_tsk_crossrefs.py | fix |
| C6b | supplementary 節級支撐閘門，放在連線之後、寫入之前 | 同上 | fix |
| C7 | validate_output 加交叉引用閘門：重複 pair、端點不是 Pericope、錨點越界、定義覆蓋率。markdown 與 supplementary 重疊只發警告 | test_validate_output_xref.py | feat |
| C8 | kg_validate：H8 加 unflagged 與 flag_mismatch；R4 加 misaligned_any_verse；R11 加 tsk_flag_without_votes；**R11 的 direction 改為 equal**。diff_kg 新增 xref_provenance section。新增探針 | test_validate_kg_xref.py | feat |
| C9 | 文件；evaluation/README.md:198、:226、:239；論文清單（11 處）；更正「1B 會改 pericopes.jsonl」的誤述 | test_docs_alignment | docs |
| C10 | 移除過渡 coalesce，**綁定在 W2**，前提是 prod 的 H8.unflagged=0 | 原始碼掃描 | refactor(backend) |

**數字**

| 項目 | 值 | 狀態 |
|---|---|---|
| supplementary 邊 | 142 → 157（X2 選 c）／158（選 a） | 驗 |
| CROSS_REFERENCES 總數 | 250,418 → 250,366（−52） | 驗 |
| curated 邊 | 931/932 條，其中帶 TSK 的 923/924 條，沒有 TSK 證據的 8 條全是 markdown | 驗 |
| 節級支撐 | 保留的 158/158 條都有同向支撐；沒有支撐的恰好是 XREF-2 那 3 筆。改用段落級時 161/161 都「有支撐」，沒有鑑別力 | 驗 |
| 同分順序取決於 store | 資料相同時，prod 與 staging 在 262 題代理中有 26 題的 top-10 id 集合不同；單種子 789/2,779 個不同 | 驗 r4_tie.py |
| 資料升版的影響 | 單種子 146 個（審查者算 147，差 1 來自未模擬的 fallback）；代理題 17/262 | 驗 |
| 部署順序顛倒時 | 923 條 curated 被當成 TSK，影響 758 個單種子、86 題 | 驗 |
| 計畫文字 | 「62 題代理」應為 262 | 【更正】 |
| kg_xref「靠 xref 補到金段落」 | 14 → 14，不變，預期沒有增益 | 驗（模擬層） |

**預期 diff**
- relationships：CROSS_REFERENCES −52。
- xrefs：supplementary +16（選 a）或 +15（選 c）；tsk −68 或 −67；markdown 0。
- xref_provenance 是新 section：prod 端三個鍵各減去全量，staging 端新增四個鍵。
- 其他 section 都是 0 差。

**閘門**
- Step 0：解析錯誤 0；validate_output 錯誤 0。
- Step 9：
  - count(tsk)=250,358；attached 為 924 或 923；旗標為 null 的邊 0；節級支撐 100%。
  - 連跑兩次，**(a.id, b.id, votes, verse_pairs, curated, tsk) 的指紋 sha 必須相同**。
- 10.6：H8=0；R4 兩種口徑都是 0；R11=250,358（equal）。
- 模擬等於實測：第 1 步在 prod 跑，第 2 步在 staging 跑，逐筆比對。
- 對 5 個受 999 影響的種子，明確斷言權重為 0.60。
- D3。
- 注意：探針 jer:29:0→isa:55:0 在 live 上本來就會通過，沒有鑑別力【更正】，所以不拿它當 XREF-3 的守門。

**風險**
- 部署順序一旦顛倒，影響很大。對策：第 2 步之前，用 grep 確認容器裡已經沒有 `coalesce(r.votes, 999)`。
- 加了 tiebreak 之後，Round 3 的 opt-in 數字不能再直接比較。
- 2D 之後 markdown 與 supplementary 會開始重疊，聚合可以處理，validate_output 只發警告。

### 2.3 第 1C 批：NER 根因（M1、M5、ID-3 的 NER 端、M3「但」）

1C 原本自己規劃的拆檔（P0）取消，改由 W0 統一處理。

| # | 內容與檔案 | 測試 | commit |
|---|---|---|---|
| E0 | NER-0：用 HEAD 重跑 `--stage ner`，把字典漂移單獨隔離出來。預測只差 4 列（1sa:18 的「所以掃羅」） | 與模擬逐列比對 | chore |
| C1 | CKIP 位置改用 NerToken.idx；**移除 `_extract_by_ckip_ner` 內層的廣域 except（:246-247），否則單筆失敗仍會被吞掉** | test_ner_positions.py；「ner_driver 拋例外時 stage 失敗、不寫 manifest」 | fix |
| C2 | 新增 text_regions.py；字典只比對標題與本文；CKIP 讀全文、丟掉前綴區的 token（依 C2 決策）；每列寫 source_region；entity_normalizer 要帶上新欄位 | test_text_regions.py、test_ner_regions.py | fix |
| C3 | 交叉引用殘標標題區（54 個標題、484 筆）不產生提及。這是 **NER 端的防線，根治在 2D**。停用表 = CROSS_REF_ABBREV − {但, 珥}，維持單一來源 | test_ner_abbrev.py | fix |
| C4 | normalize_surface 處理 span 與位置；**id 怎麼鑄依 C1 決策，建議 NER 不改 id** | test_normalize_surface.py | fix |
| C5 | geo_rules.is_geo_at 移進 NER；10.2 的「但」改成斷言模式 | test_geo_rules.py、test_cleanup_dan_assert.py | fix |
| C6 | NER 單筆失敗改為整段失敗；**manifest 在 stage 一開始就刪除** | stage_guards 新增案例 | fix |
| C7 | validate_mentions V1–V9，**只檢查 NER 產生的 P/P/G 列**。原因：E/O/T 有 20,458 列本來就沒有位置；Object「箴言」「詩篇」是合法實體。「使徒」不放黑名單 | test_validate_mentions.py，含 E/O/T 列與「箴言」的反例 | feat |
| C8 | mention_edges 逐邊聚合，寫 source_region 與 text_id；**source_region 取代表列的 region，另加 has_body**，避免 15 條邊的 region 與位置不一致 | test_mention_edges.py | feat |
| C9 | 描述 stale 的核可，用 §3 的統一機制（`--expect` 加上 git 追蹤的期望檔） | test_desc_expected_stale.py | feat |
| C10 | 品質門：R1、H6、H4、R9（**含 checks_r.R9 的 live 分支與 load_live 的 text_id**）、H10、新探針（實體不得存在、提及必須存在）；R12 單字實體只記錄（40 個） | test_validate_kg_checks.py | chore |
| C11 | 文件與紀錄 | test_docs_alignment | docs |

`freeze-grounded --force` 移到 W2 的 R4 之後才做，執行前先備份 grounded_manifest.json。

**數字**（依 1C 契約算出的 FINAL 值；若採 1D 契約則【待重算】）

| 項目 | 值 | 狀態 |
|---|---|---|
| P/P/G MENTIONS 邊 | 30,048 → 28,264（−1,903／+119） | 驗（兩邊一致） |
| 改記到真提及 | 431 條（計畫寫 337＋153） | 【更正】 |
| 只出現在標題的邊 | 493 條（計畫寫 382） | 【更正】 |
| 若沿用首筆勝出會誤標為 title | 2,015 條 | 驗 |
| 實體 | P/P/G 4,223 → 4,079；消失 174、新增 30。新增的 30 個中有 2 個（「以色」）不是來自空白名，而是新的垃圾 | 驗 |
| 空白名合併 | 153 個中 137 個是同字形孿生；**14 個是跨字形的同音（約坦→約坍、乃縵→乃幔等），不是孿生，不能合併** | 【更正】 |
| 描述 | stale 52、missing 154；可承接 48 條，其中 **22 個後繼 id 在 prod 已存在，只是描述為空** | 【更正】 |
| 關係支撐消失 | 規劃者算 104 筆，審查者算 88 筆（定義不同）；phase 4 約 78–80 筆。計畫原估 293 | 【更正】 |
| 馬可的 mention_count | 794 → 20（計畫寫「個位數」） | 【更正】 |
| CKIP 只讀標題＋本文（計畫原案） | 邊 −3,320／+1,690，描述 stale 加 missing 共 918 | 驗 |
| 已知退步 | 流珥併入葉忒羅：W2 後葉忒羅的流珥列中，錯人的有 16/20；「所以掃羅」被認成以掃，2 條邊 | 驗 |

**閘門**
- validate_mentions 的 V1–V9 全部達到 0 或 100%。
- R1=0、H6=0、R9=0。
- H10 用 equal：1C 不改變它（2,227）。
- 「但」的斷言模式：會刪的邊為 0。
- replay 結果 ⊆ 期望檔。
- **MENTIONS 的邊鍵集合必須等於離線預測**，不只比 delta。
- mention_count 逐實體等於預測（diff_kg 新增 section）。
- D3。
- 人工抽樣：
  - 刪除的書名區邊抽 n=100，假邊 ≥95%；
  - 改記到真提及的抽 n=50，真提及 ≥90%；
  - 新增的邊全部審。

**風險**
- CKIP 讀全文，所以 2D 修正標題時，這 484 筆的 CKIP 輸出會再變一次。
- 1C 不能單獨升版：它依賴 1D 的 id_migration 與 1A 的 6.05。

### 2.4 第 1D 批：實體與事件的決定性清理、三庫同步

| # | 內容與檔案 | 測試 | commit |
|---|---|---|---|
| C1 | 新增 stoplists.py：GENERIC 24、PLACE_FORMULA 5、JUNK_TITLE_ALLOW。**不另立書卷縮寫表，改由 CROSS_REF_ABBREV 推導**。pericope_miner:59-63 與 cleanup_noise_entities:67-71 改成 import（計畫寫 :50-54，行號已漂移） | test_stoplists.py | refactor |
| C2a、C2b | title_rules.is_junk_title；identity.normalize_surface（與 1C 共用同一份）；pos_extractor 與 grounded_classifier 改成先正規化 | test_title_rules、test_identity、test_pos_filters、test_grounded_keys | 2 個 fix |
| C3 | 新增 compile_entities 與 kg_compile/{overlay, replay, snapshot}：把 10.1、10.2、10.4、10.5 與 K7 replay 移進編譯期；規則全關時必須與現行鏈等價 | **等價測試用 sha 釘住的凍結輸入，而且要在 1C 的 NER 產物併入之前完成** | feat |
| C4 | import_postgres 與 import_neo4j 加 `--kg-dir`；embed 只跑一次；改寫重灌鏈 | test_import_from_snapshot、test_embed_payload | feat |
| C5 | 孿生合併與 id_migration。**依 --previous-ids，以 (type, normalize(name)) 推導 merge，不依賴「compile 自己做了合併」**。新鑄的 id 若撞上既有 id 而名稱不同，硬失敗。合併後以 (source_id, entity_id, start_pos) 去重，mention_count 由去重後的列重算（有 10/169 列是同一處出現） | test_compile_twins、test_id_migration | feat |
| C6 | drop_junk：命中 protected 時失敗 | test_compile_rules | fix |
| C7 | drop_stoplist_events、drop_dictname：命中 protected 時豁免（babieta）；新增 R12 | test_compile_rules、entity_layer 測試 | fix |
| C8 | aliases 在編譯期產生，歧義字形移到 ambiguous_aliases。**curated 豁免只限 registry 相關的 Event alias，流珥不豁免**。刪除 backfill_aliases.py，**同一個 commit 移除 test_db_env 中的 3 處引用與 README:502** | test_alias_ambiguity：豁免時 33 個事件，不豁免時 28 個 | feat |
| C9 | entity_overrides.yaml 擴充（D9）；H7 改讀這個檔 | test_overrides | feat |
| C10 | extraction_method 與 title_derived 寫進 Neo4j 與 Qdrant；新增 H11 | test_compile_provenance | feat |
| C11 | cleanup_noise_entities 加 `--check` 斷言模式 | test_cleanup_check | refactor |
| C12 | 品質門升為 hard；hard 集合的斷言改由 baseline 檔驅動，避免四批都改同一行 | entity_layer 測試 | test |
| C13 | 文件 | test_docs_alignment | docs |
| C14 | 移除 1B 的過渡 coalesce（即 1B 的 C10） | 原始碼掃描 | refactor(backend) |

**數字**（1D 契約；以 live 為基準；只計 1D 本身）

| 項目 | 值 | 狀態 |
|---|---|---|
| 實體與 id_migration | 9,124 → 8,926；id_migration 198 列（merge 116、drop 82）；保留空白 id 51 個；改名 0 個 | 驗（兩邊一致） |
| 刪除 | Event 32、Theme 36、Object 14。Object 的 25 個中，6 個合併、5 個只清名稱 | 驗 |
| H10 | Event MENTIONS 2,227 → 2,165（−62）。改為 record，以 `--accept H10` 核可；registry 由 D1 守住 | 驗 |
| ambiguous_aliases | 7 個實體、7 個字形 | 驗 |
| PG entity_mentions | 171,797 列。基數是 JSONL 的 173,896，不是 PG 的 173,768 | 【更正】 |
| 描述 | stale 11、missing 196、繼承 23；PG 的 P/P/G 描述 0 → 2,952（還沒扣掉 1C 的 stale 與 suspect） | 驗；合併值【待重算】 |
| 若採 1C 契約（NER 端改 id） | 46 個 id 改名後 404；14 組同音誤合；64 條關係與 23 筆繼承失效 | 驗 |
| 利未探針 | 1C+1D 之後第 1 名是 group:liweiren（892），不是 person:liwei（173） | 【更正】驗 |
| 會曝光的已知錯誤描述 | person:maliya（撒馬利亞誤命中）、person:lajie（「其子為以法蓮與瑪拿西」），兩者都不是 stale | 驗 |

**閘門**
- compile 自身：
  - 消失的 id 100% 有 migration 紀錄，而且 **⊆ 已 commit 的期望 id_migration**；
  - protected 的 37 個 id 不得被合併、刪除或改型；
  - stale 與 missing ⊆ 期望檔；
  - 輸出決定性；
  - 由快照重算的 registry 等於 committed 檔。
- 圖譜與三庫：
  - H4=0，同 (型別, 名稱) 的重複群組為 0；
  - H5 三庫 0 差，**包含 mention_count**；
  - R8=0；
  - R10 白名單外為 0。curated_alias_conflicts 的下降要人工核可，不自動 ratchet；
  - R12=0、H11=0；
  - 快照的 R9=0；
  - D1、D3。
- API：
  - 利未探針改成「person:matai 不再因 alias 被命中，而且 person:liwei 排在 person:matai 前面」；
  - 珥、使徒回 200；
  - 合併掉的 id 回 404；
  - suspect 描述不曝光。

---

## 3. 跨批共用機制（審查後統一）

| 機制 | 統一做法 | 理由 |
|---|---|---|
| 期望檔 | staging 建置**之前**，由離線模擬產生 config/kg_expect/batch1_w{1,2}/，內容包括 id_migration_expected、label 與 MENTIONS 的 delta、MENTIONS 邊鍵集合、mention_count、stale 與 missing 清單。Kay 核可後 commit。compile、replay、diff_kg 都拿它比對，不得回填 | 1C、1D 的審查都指出：允許清單若由本次輸出回填，等於自我認證，抓不到 compile 本身的 bug |
| 允許清單 | 每一波**只用一份合併檔**（kg_diff_allow_batch1w1.yaml、…w2.yaml），delta 取合併後的值；W2 的鍵依 W1 升版後的 phase/source 格式產生；diff_kg 加 `--fail-on-unused` | diff_kg 的 `--allow` 只吃單一檔案，delta 必須完全相等（diff_kg.py:207-208、:283） |
| diff_kg 新 section | xref_provenance（1B）；mention_count（逐實體） | mention_count 影響排序與 /api，目前量不到 |
| 描述 stale | W1 維持 `--fail-on-stale`，stale 必須為 0；W2 用 replay `--expect` 讀期望檔，改名或合併的 id 沿用相同 titles_sha 的描述 | 把 1C 的 `--expected-stale` 與跨批規劃的 `--expect` 合成一個機制 |
| ratchet | 只在 prod 的 R4 之後做，與允許清單放同一個 commit | 避免 1A、1B 並行時在 baseline JSON 上衝突 |
| D3 | quick_retrieval_eval `--include-context` 加上 ab_compare `--require-identical`，用 W0 的 AA 校準 | 1B 第 1 步的 D3 同時混了資料與 image 兩個變因 |

---

## 4. 第 0 批遺留待辦的分派

| 待辦 | 處置 | 批 |
|---|---|---|
| build_database.md 已 793 行 | 把「Staging 與升版流程」（568–768 行，約 200 行）搬到 docs/staging_promotion.md；test_docs_alignment 改讀兩個檔 | W0 |
| test_db_env.py 799 行、test_validate_kg.py 794 行 | 純搬移。test_db_env 拆成環境契約、staging 寫入防護、cleanup 同步三個檔；test_validate_kg 拆成共用 fixture 加上 checks、gate/CLI、shipped 三個檔 | W0 |
| kg_quality_baseline.json 已 751 行 | 依 check 類別拆成多個檔，gate 合併讀取，並加 ≤800 行的測試 | W0 |
| 計畫文件 847 行 | §4 第 1 批移到新紀錄，原處留摘要與連結 | W0 |
| desc_generator 的預期 stale 機制 | 見 §3；W2 由 1D 實作 `--expect` | 1D |
| 第一次 R3 | W0 演練；W1 實跑 Neo4j 與 backend；W2 第一次做 PG 換表與 Qdrant 切換 | W0、1B、1D |
| backend-staging 從未啟動 | W0 的 AA 演練 | W0 |
| SON_OF onCreate-only | 更正第 0 批紀錄中的成因；6.05 保證鍵唯一，6.1 改成整組 SET | 1A |
| output/ner_*.jsonl 是舊版產物 | W1 不跑 Step 1，以 sha 前置檢查把關；W2 先跑 NER-0，再跑 1C 的最終 NER | 1A、1C |
| R1 2,124 與 4 個實體的 mention_count 殘差 | W1 寫進紀錄並 accept；1D 統一 mention_count 的定義 | 1A、1D |
| image 只有 latest 一個 tag | 每一波的 R0 都加 docker tag | 每波 |
| entity_dict 被 backend import | 第 1 批若要改字典，必須是單獨的例外 commit（有 fingerprint 測試），並經過 D3 | 全批 |
| 第 0 批是一個大 commit | 第 1 批改為一個缺陷一個 commit，約 60 個 | — |

---

## 5. 價值量測

### 5.1 D3 非劣閘門（W1、W2 的硬門檻；W0 先做 AA）

```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d backend-staging
cd evaluation
BACKEND_URL=http://localhost:8000 .venv/bin/python quick_retrieval_eval.py --top-k 5 --metric-k 6 --include-context --label d3_prod_<波>
BACKEND_URL=http://localhost:8001 .venv/bin/python quick_retrieval_eval.py --top-k 5 --metric-k 6 --include-context --label d3_stg_<波>
.venv/bin/python ab_compare.py results_quick/d3_prod_<波>.json results_quick/d3_stg_<波>.json --require-identical
```

判準：
- 兩邊的 `graph_strategies_applied` 相同。
- 同路由的題目：core、附加段落、context sha 全部 100% 相同。
- 路由不同的題目，兩邊各重問，最多 2 輪；之後仍不同的題數 ≤ W0 量到的 r0。
- invalid 題數為 0。

D3 的 staging 端必須跑「由該波 HEAD 建出的 image」。

### 5.2 opt-in 策略 A/B（只量測，不設必勝門檻）

| 波 | 策略 | 設計 | 門檻 |
|---|---|---|---|
| W1 | entity_path | 對照組是 staging-P1（6.05 用 `--rules none`，並仍跑 10.3），實驗組是 staging-1A。雜訊地板：P1 重建兩次的差異 | 500 題 Δvrec ≥ −0.005，只報告。事前登記：失敗也不回退 10.3，由 2A 補事件層 |
| W1 | cross_ref_expand、cross_reference | 同一個 image 分別接舊資料與新資料（tiebreak 後結果是決定性的） | 報告；touched 題數若 >34，先停下來查 |
| W1 | graph_event | 抽查保羅歸主、山上寶訓的題目（受 mention_count 殘差影響） | 報告 |
| W2 | graph_person、graph_place、graph_event、entity_query、entity_path、all | prod 對 backend-staging，先跑 legacy-100，有差異才跑 500 題 | entity_path 同上；其他只報告 |

- 報告內容：Δvrec 的 95% CI、touched 題數、勝負題數；樣本內與 held-out 分開報告。
- 檢索結果有實質差異時才跑答案端：coverage 為主，faithfulness strict ≥0.97 守門，|Δcoverage| 與雜訊地板 0.060 比較。
- 預期：2026-10 的 41 題停損實驗已判 STOP，kg_xref 的模擬也是 14→14。**所以不預期分數上升，這次 A/B 的目的是確認修錯沒有造成傷害。**

### 5.3 /api/v1/entity 抽查

related_passages 與 related_entities 的查詢沒有 ORDER BY，比對前一律先依 id 排序。

- **W1：以下必須與 prod 完全相同。** person:make、person:liwei、place:dan、group:yehehua、event:shanshangbaoxun、person:yeteluo、event:jinniudushijian。
- **W1 的圖譜探針（Cypher READ）：**
  - 不得有「羅得 FATHER_OF 他拉」；
  - 女性 head 的 FATHER_OF 為 0；
  - heb:1:0 的前 8 名不得出現錯位的 curated 邊；
  - 帶 votes 的邊 = 250,358。
- **W2：**
  - person:make 的全部 MENTIONS 都是真提及（用 Cypher 列出全部，不依賴 LIMIT 10）；
  - person:matai、person:lujia 的錨點各 ≤10；
  - place:dan 在 PG 的列數與 Neo4j 口徑一致；
  - group:yehehua 的 type 是 Person；
  - person:er（珥）、group:shitu（使徒）回 200；
  - 合併掉的 id 抽 5 個，都回 404，並與 id_migration 一致；
  - person:liewangji、place:niximiji 回 404；
  - event:jinniudushijian 的 aliases 仍含「金牛犢」，event:saoluodezhuanbian 仍含「保羅歸主」；
  - 沒有 stale、也不是 suspect 的 P/P/G 有描述；suspect 的（maliya、lajie、M2 的 14 個名字）不曝光；
  - 利未探針用修正後的寫法；
  - 流珥依 C4 的決策驗證。

### 5.4 KG 品質與人工抽樣

- 每次升版都保留 validate_kg、6.05 report、check_identity 的輸出與 sha。
- 人工抽樣都用固定 seed，標註結果存檔並附 sha，以 ratchet 管理：
  - 1A：錨定規則 n≥40（以 id 正確計）；LLM 親屬 n≥30（只報告）；prior 30 條全審。
  - 1C：刪除的書名區邊 n=100；改記到真提及的 n=50；新增的邊全審。
  - 1D：描述隨機抽 10 個，加上一份必查清單。

---

## 6. 與總計畫的偏離

| # | 偏離 | 理由 |
|---|---|---|
| 1 | 親屬邊不是「<300」，而是約 615【待重算】 | 原型的詞界過嚴，P1 幾乎沒有命中；照計畫列出的句型實作後，P1 有 402 條 |
| 2 | 方向未驗證的邊是 48 條，不是 75 條 | 75 條中有 26 條 Event–Event 邊本來就要丟，另 1 條與 prior 方向相反也要丟 |
| 3 | head<tail 比例門檻改為 H11 unflagged=0，並另設 direction_pair 表 | LOCATED_IN 的比例是 0.98，原門檻必然失敗；yaml inverse 改 null 之後，不能再用 inverse 推導 |
| 4 | R6 的 ≤5% 從硬門檻改為 record；改以全部父母編碼的指標 ratchet | 剩下的違反都屬身分層問題；只看 FATHER_OF 會看不到問題轉移到 SON_OF |
| 5 | PROBES 從「全過」改為 subset 規則 | baseline 裡有 13 個失敗探針，1A 只修得到 4 個 |
| 6 | 不刪減 yaml 寬訊號清單，改為整個移除 R2 與 prompt_signals | 錨定規則只在 6.05 跑一次；prompt_signals 沒有其他消費者 |
| 7 | 不只修 inverse 的性別，凡是帶性別的 inverse 一律改 null | 根治反向邊錯誤 |
| 8 | geo_rules 與 overrides 的最小版提前到 1A | 6.05 必須看到 10.2 之後的狀態，否則 H3 會剩 1、H9 會剩 13 |
| 9 | 「但」改斷言從 1A 移到 1C；generic 與 yehehua 改斷言移到 1D | NER 沒修之前，10.2 仍要真的刪 733 條 |
| 10 | W1 的重灌鏈跳過 Step 1，並加 sha 前置檢查 | 跑 merge 會讓 person:liuer 消失，6.05 會因端點缺失硬失敗 |
| 11 | 6.1 改成整組 SET、檢查 written==rows、加空層防護；標準鏈不帶 --replace | 根治 onCreate-only 與靜默丟邊 |
| 12 | 錨定規則加同名防護並只用 P/P/G 詞庫 | 錨定父母邊有 30% 落在多父母衝突；E/O/T 垃圾實體會吞掉「兒子X」 |
| 13 | 1B 新增決定性 tiebreak | 同分順序取決於 store，A/B 與升版結果會無法歸因 |
| 14 | TSK 支撐閘門改為節級 | 段落級沒有鑑別力 |
| 15 | TSK attached 的目標改為 923/924，不是 856 | 856 是重錨之前的數字 |
| 16 | 不做 `--refresh` | 依 D1，Step 5 每次都會清庫；SET 冪等加計數閘門已足夠 |
| 17 | validate_output 改為必跑；markdown 與 supplementary 重疊只發警告 | 2D 之後必然會出現重疊 |
| 18 | markdown 的 verse 欄位改成 md_anchors | 避免 provenance 退步，讓 R4 可以統一檢查兩種來源 |
| 19 | CKIP 讀全文，事後丟掉前綴區的 token | 改變 CKIP 輸入會讓描述 stale 加 missing 從 206 增加到 918 |
| 20 | 位置改為相對於該列自身文字（text_id）；MENTIONS 改成逐邊聚合 | 以本文為基準會讓 R1 誤報 2,200 條；首筆勝出會誤標 2,015 條 |
| 21 | validate_mentions 改用證據判定，只檢查 NER 產生的 P/P/G 列 | 「使徒」是合法實體；E/O/T 列本來就沒有位置 |
| 22 | 縮寫停用表豁免 {但, 珥}；殘標標題的處理定位為 NER 防線，根治在 2D | 珥是猶大的長子；殘標標題的成因在 Step 0 |
| 23 | 新增 NER-0 前置步驟 | 把字典漂移與 1C 的程式改動分開 |
| 24 | Kc 與 K7 提前移進 1D 的編譯期 | PG 要在 Step 3 就帶描述；原型已驗證與 staging 0 差 |
| 25 | 空白 id 不改名；同音不合併 | 避開 14 組同音撞號 |
| 26 | curated alias 豁免只限 registry 相關的 Event alias | 不豁免會掉到 28 個事件；流珥不應受保護 |
| 27 | H10 在 1D 改為 record 加 accept | 刪掉的 32 個 Event 帶走 62 條 MENTIONS，H10 不可能不變 |
| 28 | 期望檔先行、每波一份合併允許清單、diff_kg 新增兩個 section | 避免自我認證 |
| 29 | 新增 W0 準備波；兩波各升一次 | 第一次 R3 在風險最低的 W1 實跑 |
| 30 | 工時從 80–110 h 上修為 117–157 h | 加入新增項目與審查修正 |

---

## 7. 需要 Kay 決定的事

| ID | 時點 | 問題 | 建議 |
|---|---|---|---|
| K0 | W0 前 | 同意啟停 backend-staging 與拋棄式臨時容器 | 同意 |
| K1 | W1 前 | 「X生Y」沒有性別線索時怎麼辦 | 不輸出，只收「給F生C」 |
| K2 | W1 前 | 錨定規則的名字解析政策 | 只接受 canonical 或已宣告的 alias，詞庫只用 P/P/G，同名時 abstain |
| K3 | W1 前 | R6 的門檻口徑 | 矛盾與女性 head 升 hard；全部父母編碼的指標 ratchet；≤5% 移到延後-A |
| K4 | W1 前 | 48 條方向未驗證的邊 | 保留並標記，另設 direction_pair 表 |
| K5 | W1 前 | 是否移除 `confidence` 屬性（D4） | 移除，只留 confidence_raw |
| K6 | W1 前 | R2 與 prompt_signals | 整個移除 |
| K7 | W1 前 | backfill_event_relations.py 的去留 | 保留，需要 `--legacy-cooccurrence` 才能執行 |
| K8 | W1 前 | entity_path A/B 的對照組 | staging-P1，並事前登記 |
| K9 | W1 前 | 人工標註由誰做 | 請 Kay 指定 |
| K10 | W1 前 | 第 0 批 mention_count 殘差（4 個實體） | W1 先 accept 並抽查 graph_event；1D 根治 |
| X1 | W1 前 | xref 的 tiebreak 排序鍵 | 穩定雜湊 `apoc.util.md5(target.id)` |
| X2 | W1 前 | rev 19:11-16→dan 7（D10） | 改錨為 rev 19:16→dan 2:47 |
| X3 | W1 前 | 是否加 verse_pairs 當次排序鍵 | 不在 1B 做 |
| X4 | W1 前 | 1B 的小項（扇出政策、重疊警告、`--refresh`） | 每段一個 anchor，上限 3 段；重疊只警告；不做 `--refresh` |
| C1 | W2 前，**阻擋** | 1C 與 1D 的 id 契約 | NER 照舊用原始 token 鑄 id；只在 compile 正規化與合併 |
| C2 | W2 前 | CKIP 的輸入 | 讀全文，丟掉前綴區的 token |
| C3 | W2 前 | 位置座標 | 相對於該列自身文字，邊上寫 text_id |
| C4 | W2 前，**阻擋** | 流珥 | W2 前撤回這個別名，用 D3 確認線上不受影響；以書卷範圍限定別名的做法留給延後-A |
| C5 | W2 前 | compile 的設計 | 選項 B：三庫都從快照投影 |
| C6 | W2 前 | 描述是否曝光（D5） | 非 stale 且非 suspect 的才曝光 |
| E1 | W2 前 | 沒有孿生的空白 id | 保留 id，只清名稱 |
| E2 | W2 前 | group:yehehua（D9） | 保留 id，以 overrides 改為 Person |
| E3 | W2 前 | PG entity_mentions（D6） | 保留，從快照同步，只收抽取列 |
| E4 | W2 前 | 字典名規則的範圍 | 涵蓋 Event、Object、Theme |
| E5 | W2 前 | 「所以掃羅」被認成以掃 | 接受，登錄為已知錯誤，交給 2B |
| E6 | W2 前 | 只出現在標題的 493 條邊 | 保留，標 source_region=title |
| E7 | W2 前 | mention_count 的語意 | 1D 統一為去重後的出現次數，三庫寫同一個值 |
| E8 | W2 前 | NER 是否改用 GPU 批次 | 可以，manifest 記錄 device，並避開評估時段 |
| E9 | W2 前 | 1D 的其他小項 | 依 1D 規劃者的建議 |
| U1 | 跨波 | 升版節奏 | 每一波各升一次 |
| U2 | 跨波 | 允許清單與期望檔的做法 | 離線預測先行並 commit；每波一份合併允許清單 |
| U3 | 跨波 | 論文數字的更新（D14） | 每波升版後更新描述現行圖譜的數字；實驗數字保留原值並註明資料版本 |
| U4 | 跨波 | xref 種子中 11% 是 chunk id，永遠找不到 Pericope | 排進第 2 批，並另做 A/B |
