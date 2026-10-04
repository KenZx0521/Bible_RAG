# 知識圖譜資料層修復計畫：分批細節（第 1 批起）

> 從 [2026-10-04_kg_data_layer_fix_plan.md](2026-10-04_kg_data_layer_fix_plan.md)（總計畫）§4 拆出（2026-10-04，內容未刪減）。第 0 批與各批摘要表留在總計畫 §4。
> 文中的 §1–§8、決策 D1–D17、validate_kg 的檢查代號（H、R、D 系列）與升版步驟 R0–R5，都指總計畫的同名章節或定義；升版流程的指令見 [../staging_promotion.md](../staging_promotion.md)。第 1 批的執行計畫見 [2026-10-04_kg_batch1_plan.md](2026-10-04_kg_batch1_plan.md)。

---

## 4. 分批計畫（續）

### 第 1 批：不需重跑 LLM、根因明確、可直接併入管線
升版分兩波：**第一波 1A＋1B**（不重跑 NER）；**第二波 1C＋1D**（兩者要一起升，因為 1C 的空白正規化需要 1D 的 id_migration）。

#### 第 1A 批：關係層的決定性後處理（Step 6.05），以及 10.3 的處置
- **涵蓋**：REL-01、REL-02、REL-03（標記）、REL-04（加 source 欄位）、REL-05/M3（閘門）、REL-06（退場）、REL-08/EV-10、REL-09、G-2、G-3。
- **要改的腳本與函式**
  - 新增 `scripts/relation_extraction/anchored_rules.py`：帶槽位的錨定句型，例如「{P}的(長|次)?(兒子|女兒){C}(、{C})*」「{C}是{P}的兒子」「{P}(又)?生(了)?{C}」「{H}的妻(子)?{W}」。名字用全實體詞庫做最長匹配，並檢查前後詞界；整個句型必須落在同一節內。方向由槽位決定。是否輸出有性別的關係見 D3。
  - 新增 `scripts/relation_extraction/relation_postprocess.py`（Step 6.05，純函式）：
    - 讀 relations.jsonl，加上 anchored 輸出與編譯後的 mentions；
    - 丟掉 phase 2 規則三元組（771）與 phase 5 反向邊（756）；
    - 丟掉 LLM 產生的 Event–Event 邊（26）；
    - 丟掉與 prior 矛盾的 phase 4 同型邊；其餘 75 條標 `direction_verified=false`；
    - provenance 閘門：source_pericope_id 或其 chunk 必須同時 MENTIONS 兩端；prior（64 條，source_pericope_id 是經文引用）與 curated 豁免；
    - 依 schema_loader 驗證 domain/range（例如 yehehua 的 14 條）；
    - 矛盾消解依 prior > LLM > anchored 的優先序，並寫衝突日誌；
    - 每條邊寫入 `source`（prior/anchored_rule/llm）、`model`、`run_id`、`confidence_raw`；
    - 讀入 `id_migration.jsonl`（1D 產出）；
    - 輸出 `relations_clean.jsonl`。
  - `rule_classifier.py:81-83`、`extract_relations.py:178-183`：只有錨定規則可以直接定案（continue），其餘交給 R4。
  - `extract_relations.py`：R5 預設關閉；`_dedup_triples`（:97-104）加矛盾消解。
  - `inverse_materializer.py`：預設停用；yaml 的 inverse 修正性別（:43、:54、:65）。
  - `config/relations/biblical_relations.yaml`：刪掉寬訊號（生、父親、…的兒子、屬…、兄弟、列祖、回到）；把 PRECEDED_BY 的描述改成與關係名一致（:421）。
  - `models.py`：新增 phase 碼 ANCHORED_RULE 與 COOCCURRENCE，ExtractedRelation 加 source、model、run_id、schema_version。
  - `import_relations_neo4j.py`：改讀 relations_clean.jsonl，寫入新欄位。
  - `backfill_event_relations.py`：預設不執行（保留 `--legacy-cooccurrence` 供論文重現），見 D2。
  - `cleanup_noise_entities.py`：「但」的部分改成斷言模式。
- **新增測試**
  - `test_anchored_rules.py`：例如「他拉生亞伯蘭、拿鶴、哈蘭；哈蘭生羅得」必須得到正確方向；「亞拿突」不可命中「亞拿」；原型的 30 條回歸樣本。
  - `test_relation_postprocess.py`：連跑兩次結果相同；prior 豁免；「但」的孤兒邊被移除；違反 domain/range 的邊被移除；女性 head 的 FATHER_OF 為 0；不存在任何 inverse 邊。
- **管線順序變更**：6 → **6.05（新）** → 6.1（讀 relations_clean.jsonl）；10.3 移出預設鏈；10.6 加入 H3、H9、R6 檢查。
- **線上遷移**：照 §3.7 的 R0–R5；與 1B 一起在 staging 重建後升版。回滾用上一份 Neo4j dump（PG 與 Qdrant 不涉及關係邊）。
- **驗證門檻**：
  - H3 = 0（原 374）；H9 = 0；
  - R6：FATHER_OF 雙向矛盾 0（原 25）、女性 head 的 FATHER_OF 0（原 ≥40）、函數性違反 ≤5%（原 53.6%；以 FATHER_OF 計，父母各一屬合法）；
  - 每條語意邊的 source 都不為 null；不存在「phase=5 且 source≠inverse」的邊；
  - 同型、無成對名稱的有向關係，在 n≥30 時，head<tail 的比例落在 0.3–0.7；
  - 錨定規則人工抽樣 n≥30，Wilson 下界 ≥0.85；
  - D3 通過；
  - entity_path 的非劣性：Δvrec ≥ −0.005。
- **工時**：24–32 h。
- **行為影響**：只有 opt-in 的 entity_path（錯邊與重複的反向邊消失）；預設路徑與 registry 都不變。論文 sec3_kg.tex:104-185 的計數（772、5,370、752）與 R2/R5 的描述需要改寫。

#### 第 1B 批：交叉引用 provenance、supplementary 重錨、TSK 證據
- **涵蓋**：XREF-1、XREF-2、XREF-3、XREF-4。
- **要改的腳本與函式**
  - `bible_chunking/nt_cross_references.py`：資料改成經文座標，例如 `SupplementaryCrossRef(src="heb 1:5", tgt="psa 2:7", …)`。以一次性腳本機械轉換舊資料（取 book:chapter 加上 source_verses），刪掉沒用到的 `resolve_pericope_id` 與 process_bible.py:43 的 import。
  - `scripts/process_bible.py:185-242`：兩端對稱，都用 `_resolve_to_pericope` 解析；逐節檢查是否落在段落內，跨段的情況依明確的扇出政策處理（目前 3 筆）；拿掉 :222-226 的 continue 與退回 chapter 的 fallback，改成累積錯誤，最後以非 0 結束碼退出；**所有 curated 來源**（markdown 加 supplementary）一起依 pair 聚合，properties 改用 list（`supp_anchors`、`curated_sources`），並寫入 `curated: True`；:325-342 的 markdown 邊也加 `curated: True`。
  - `scripts/import_neo4j.py:155-165`：改吃聚合後的列，同一個 pair 只出現一次。
  - `scripts/import_tsk_crossrefs.py:58-70`：先 MERGE，ON CREATE 時設 `source='tsk', curated=false`；之後**無條件** SET `votes`、`verse_pairs`、`tsk=true`；結束時檢查 `count(r WHERE r.tsk) == len(rows)`（250,358），並分開列印 created 與 attached_to_curated 的數量；加上 `--refresh`；supplementary 的 TSK 支撐閘門放在這一步（TSK 檔在 fresh clone 時可能不存在）。
  - `scripts/validate_output.py`：檢查定義筆數與錨點數相符、兩端節號都落在段落內、聚合後沒有重複的 pair、markdown 與 supplementary 重疊為 0。
  - `backend/database/neo4j_db.py:202、239`：改成 `max(coalesce(r.votes,0))`，curated 由旗標判定（過渡期用 coalesce 加 source 推斷）；:261-275 的 fallback 只看最短路徑上是否全為 curated；排序改為 `seed_support DESC, curated DESC, votes DESC`。
  - `backend/utils/retrieval/cross_ref_retriever.py`：:64-71 改成 `_edge_weight(hop, curated: bool)`，刪掉 `_CURATED_VOTES`；:35-45、:109-110 改傳 curated。
  - XREF-2：刪除 rev:20:0→isa:65；rev:19:1→psa:118 刪除；rev:19:2→dan:7 依你的決定（D10）改目標，或降級為 TSK。
  - 文件：build_database.md:388、400-404；evaluation/README.md:226。
- **新增測試**：
  - `tests/test_supplementary_xref.py`：161 筆定義全部能解析；節號都落在段落內；158/161 有 TSK 支撐，其餘必須帶 `tsk_exempt`；
  - `backend/tests/test_cross_ref_weight.py`：TSK votes=1268 仍走 TSK 曲線；curated 且 votes=5 走 curated 曲線；hop-2 的 curated 權重是 0.55；
  - TSK 匯入計數測試；
  - CI 用 grep 確認 backend 中不再出現 `coalesce(r.votes, 999)`。
- **管線順序變更**：Step 0（聚合，失敗就中止）→ validate_output → Step 5 → Step 9（SET 語意，加計數閘門）→ 10.6 加入 H8、R4、R11。
- **線上遷移**：
  1. 先部署帶過渡 coalesce 的 backend（`docker compose up -d --build backend`）。這時行為只差兩處：那 3 條 votes≥999 的 TSK 邊、hop≥2 的權重。
  2. 再把 staging 重建結果升版。
  - **不要**使用調查中提出的 M2/M3 線上 Cypher（理由見 §3.5）。
  - 回滾：Neo4j 載回上一份 dump，backend 退回上一個 image tag。
  - 順序絕不能顛倒：若資料先上，856 條 curated 邊會被舊 backend 的「有 votes 就是 TSK」規則降級。
- **驗證門檻**：
  - 錯位查詢：來源端與目標端節號不在段落內的數量皆為 0（原 59）；
  - H8 = 0；
  - 被誤判成 curated 的 TSK 邊 0（原 3）；
  - votes 不為 null 的邊數 = 250,358（原 249,502）；
  - 連跑兩次 Step 9，屬性 diff 為 0；
  - heb:1:0 的前 8 名鄰居不再出現 curated 的 psa:2/45/104/102/110 與 2sa:7；
  - 預設組態 500 題 sources 逐位相同；
  - 在 S1 設定下跑 kg_xref 68 題：注入槽的金段落率（現約 3%）與「靠 xref 補到金段落」的題數（現 0/18）只做報告。
- **工時**：16–22 h。
- **行為影響**：**有，backend 程式碼會改（需重建 image）**，但只影響 opt-in 的 cross_ref_expand、cross_reference 與 "all"；預設路徑與 registry 不變。Round 3 graph 組態的數字之後不能直接比較。

#### 第 1C 批：NER 根因修正（書名前綴、位置、空白、「但」）
- **涵蓋**：M1、M3（「但」）、M5（位置與空白）、ID-3（NER 端）、G-6。
- **要改的腳本與函式**
  - 新增 `scripts/entity_extraction/text_regions.py`：把 embedding 文字切成 book（書名與「第N章」）、title（標題）、body（本文）三區，本文起點為 `text.find('：')+1`（34,072 筆全部成立）。**不改** `EmbeddingQueueItem`，不重跑 Step 0，不改 embedding。
  - `ner_extractor.py`：
    - `extract_from_text` 只對 title 與 body 做字典比對與 CKIP，位置換算回全文，每筆寫 `source_region`；
    - :215-242 改用 CKIP `entity.idx`，取代 :235 的 `text.find`；
    - :127-128 與 CKIP 輸出都先經過 `normalize_surface`（strip 前後、全形與 ASCII 空白、零寬字元，以及 NFC），並同步位移 start_pos；
    - 加書卷縮寫停用表（66 卷縮寫；豁免「但」，「俄」逐筆確認）；
    - 單字「但」必須通過共用的 `is_geo_context()`。
  - 新增 `scripts/entity_extraction/geo_rules.py`：把 `_is_geo_context` 從 cleanup_noise_entities.py 搬過來，NER 與 10.2 的斷言共用同一個函式。
  - `scripts/extract_entities.py:96-100`：傳入區段資訊；`--stage ner` 只重產 P/P/G，E/O/T 用凍結檔。
  - 新增 `scripts/validate_mentions.py`（Step 1 之後的硬閘門），檢查：
    - start_pos 落在書名區的筆數為 0；
    - 不得有以書名全稱為 canonical 的實體，也不得有黑名單中的非人名詞幹（民數、雅歌、列王、歷代、使徒、福音）；**不可**拿「書名詞幹」當閘門，否則會誤殺馬可、約翰、以賽亞等真名；
    - `text[start:end]==span` 100%；
    - (source, entity, start) 重複為 0；
    - 名稱帶空白為 0。
  - `scripts/import_neo4j.py:264-311`：MENTIONS 寫入 source_region、verse_id、source_granularity；位移一律相對於本文；匯入前依 start_pos 排序，讓首筆勝出可預期。
  - `scripts/cleanup_noise_entities.py`：「但」改為斷言模式（dry-run 必須 delete=0）；所有清理都經由編譯快照同步到 PG。
  - 保留：pericope、chunk、verse 三種 NER 輸入照舊（不做 M1(c)），以免 169 個長段失去 3,477 個 Pericope 錨點；「尼西米記」不改名。
  - 書名區中其實是真提及、只是型別錯的（加拉太、哈巴谷、俄巴底亞、歌羅西）：改用本文抽取，型別錯誤交給延後-A，不刪。
- **新增測試**：
  - `test_text_regions.py`（「馬可福音 第1章 … ：」之後才是本文；出埃及記的前綴不產生「埃及」）；
  - `test_ner_positions.py`（同一個字出現多次時位置各不相同；strip 後位移正確）；
  - `test_geo_rules.py`（以 output/backups 中「但」的 733 條刪除與 26 條保留做表格測試）；
  - `test_validate_mentions.py`。
- **管線順序變更**：1a(ner) → **validate_mentions（新閘門）** → 1c 編譯（1D）→ 3/5 …；6.05 的 provenance 閘門會自動把書名支撐的關係刪掉（約 293 筆 Step 6 關係，數字以 dry-run 為準）。
- **線上遷移**：與 1D 同一波，走 staging 重建後升版，PG 兩張表與 Qdrant `bible_entities_vN` 一起切換。回滾：三庫都還原（§3.7 R5）。描述：pericope 集合改變的實體在快照中標 stale，不再曝光（D5），等 2B 重生。
- **驗證門檻**：
  - R1 = 0（原 1,938）；
  - person:make 的 MENTIONS ≤10（原 103），馬太、路加同理；
  - 純書名實體（列王紀、彌迦書、民數、雅歌、尼西米記…）為 0；
  - R9：位置重複 0（原 4,131），span 相符 100%；
  - H4（P/P/G）= 0；H6 = 100%；
  - 「但」在 PG 與 Neo4j 的計數一致，非地理語境的「但」為 0；
  - **H10：Event MENTIONS 集合不變，D1 `--check` 結束碼 0**；
  - /api/v1/entity/person:make 抽 10 個 related_passages，10/10 的本文確實含「馬可」；
  - D3：預設組態 top-5 100% 相同。
- **工時**：20–28 h，另加 NER 牆鐘約 30 分鐘。
- **行為影響**：線上預設路徑與 registry 不變。/api/v1/entity 的 related_passages 會改變，mention_count 大幅下降（馬可 794 會降到個位數），所以 find_entity_by_name 的排序也會變（neo4j_db.py:68）。opt-in 的 graph_person、graph_place、entity_query、entity_path 都會改變。

#### 第 1D 批：實體與事件的決定性清理，以及三庫同步
- **涵蓋**：ID-3（編譯端）、ID-5、EV-01（provenance 階段 A）、EV-02、EV-09、EV-08（PG 同步）、yehehua、id_migration。
- **要改的腳本與函式**
  - 新增 `scripts/compile_entities.py`（K1c）：合併 NER 與凍結的 grounded 半邊，再依序套用：
    - 名稱正規化與同型孿生合併（用 MERGE 搬移 mentions 與關係，重算 mention_count）；
    - `_is_junk_title()` 套用到全部 E/O/T（Event 27、Theme 36、Object 25；「這是基督嗎？」列白名單；判斷要在「(無標題)」處理之後）；
    - 共用停用詞套用到所有 phase 的 Event（瑪拉、瑪撒、米利巴、耶和華曉諭、曉諭摩西直接刪除，不要併進 Place）；
    - 10.2 的 generic-event 規則；
    - `config/curated/entity_overrides.yaml`（yehehua 等，見 D9）；
    - aliases：從字典與 overrides 產生，被 ≥2 個實體擁有、或等於其他實體 canonical 的字形，改放 `ambiguous_aliases`（利未、掃羅、猶大、門徒、西門、流珥）；
    - 輸出 `output/kg/entities.jsonl`、`mentions.jsonl`、`id_migration.jsonl`（供 6.05、10.4/10.5 驗證與 Qdrant 使用）。
  - 新增 `scripts/entity_extraction/stoplists.py`：停用詞的單一來源，pericope_miner.py:59-63 與 cleanup_noise_entities.py:50-54 都改讀這裡。
  - `pericope_miner.py`：新增 `_is_junk_title`；候選建立時 strip。`pos_extractor.py:139-147`：先 strip 再過濾。`grounded_classifier.py:185`：以正規化後的鍵建立 by_name。這三處是讓下次重抽也乾淨。
  - `scripts/backfill_aliases.py`：退役，改成三庫一致性檢查（併入 check_identity）。
  - `scripts/import_neo4j.py:185-219`：把 extraction_method、title_derived 帶進 Neo4j；`embed_entities.py`：payload 帶 extraction_method，aliases 一律存成 list。
  - `scripts/import_postgres.py`：entities 與 entity_mentions 一律從編譯快照匯入，含 description（replay 中非 stale 的部分）與 aliases。這一步會讓 /api/v1/entity 開始回傳描述（D5）。
  - 白名單保護：11 個 ALIAS_INJECTIONS id 與 manual patches 中的 extracted Event，不得被任何規則刪除或改型。
- **新增測試**：
  - `test_compile_entities.py`（golden 小樣本；孿生合併；27/36/25 個 junk fixture 加上反例；停用詞）；
  - `test_alias_ambiguity.py`；
  - check_identity 在 staging 上的整合測試。
- **管線順序變更**：Step 1 → **K1c 編譯（新）** → validate_mentions → Step 3（PG 的 entities 與 mentions）→ Step 5 → 6.05 → 6.1 → 8a → 9 → 10.4 → 10.5 → 7(replay) → 8b → 10.6。10.1 從鏈中移除；10.2 只剩斷言。replay 排在 10.5 之後、8 拆成 8a/8b 的理由同第 0 批。上面 import_postgres 要在 Step 3 帶描述，就得在編譯期用「套過 curated overlay 之後」的 MENTIONS 判 stale（等於把 Kc 移進編譯期，見 §3.2）；做不到時，PG 的描述改在 7(replay) 之後另行同步，不可拿編譯前的 MENTIONS 判 stale。
- **線上遷移**：與 1C 同一波，§3.7 R0–R5。約 180 個空白 id 改名或合併後，舊 id 會回 404（沒有 curated 引用，評估檔也沒有引用）；redirect 留到延後-A（D8）。
- **驗證門檻**：
  - H4 = 0（原 180）；同 (label, trim(name)) 有多個節點的情形為 0；
  - R8 = 0；書卷縮寫實體 0；
  - Event 名稱與停用詞、與字典 P/P/G 名稱的交集都是 0（白名單除外）；
  - R10 = 0；
  - H5：三庫的 id、type、canonical、aliases、description 都是 0 差，Qdrant aliases 100% 為 list（原字串 9,093 筆）；
  - Event 的 extraction_method 為 null 的數量 0（原 1,694）；
  - find_entity_by_name('利未') 的第 1 名是 person:liwei；
  - H10 與 D1 通過。
- **工時**：20–28 h。
- **行為影響**：/api/v1/entity 開始回傳人物、地點、群體的描述與修正後的 aliases；舊的空白 id 回 404；find_entity_by_name 的排序改變。registry 與預設路徑不變。

### 第 2 批：中等工作量（含小量 LLM）

#### 第 2A 批：Step 6 可續跑化、R4 快取、定向重判、校準
- **涵蓋**：REL-10、REL-07（程式部分）、REL-03（重判）、REL-01（補判 772 個 rule-hit 配對）、REL-06（取代 10.3）、REL-04（校準）、G-1（chunk 上捲）、G-4、M6（Step 6 部分）。
- **要改的腳本與函式**
  - `extract_relations.py`：
    - 判定完成才寫 checkpoint（修 :117-128、171-192），每批 append LLM 三元組；
    - 輸出分檔 `relations_{prior,rule,llm,unclassified}.jsonl` 並帶 run_id；
    - `--resume` 改為合併既有結果；已完成的 run 若沒有 `--force` 就拒絕寫入；
    - `--no-llm` 不得覆寫 unclassified；
    - `--pericope-ids` 支援多個 id，搭配 `RE_OUTPUT_PATH`、`RE_UNCLASSIFIED_PATH`、`RE_CHECKPOINT_PATH` 導到另外的檔案，跑完再合併；
    - :193-203 改成先計算 classified_pair_keys，再做 prior 過濾；
    - unclassified 加 `status` 欄位（none、unjudged、failed、context_missing）。
  - `pair_miner.py`：改讀編譯後的 mentions，並把 chunk 層的提及上捲到父 pericope（G-1）；grounding 改讀 pericopes.jsonl；截斷改成同節共現優先（:115、147-150）。
  - `grounded_re_classifier.py`：同一批只放相同 context 的配對，以整段 pericope 當 context（中位數 388 字、最長 3,544 字）；斷言每一對的端點名稱都出現在 context 中；evidence 必須非空、是 context 的子字串、且含端點（修 :124、238、267）；prompt 加 `subject` 欄位決定方向（REL-03）。
  - 新增 `output/frozen/re_cache.jsonl`：以 (pair_key, grounding_sha) 為鍵，記錄 status、model、temperature。以現有 relations.jsonl 與 unclassified 為種子，manifest 註明 NONE 與失敗分不出來、去重時有結果被吃掉。
  - 字面端點閘門：非 Event 的端點名稱必須以字面出現在段落中，才送進 R4。
  - 新增 `config/relations/calibration.yaml`：以 (source, family) 分層抽樣，每層 n≥30，約 200 條；6.05 依此覆寫 confidence（見 D4）。
- **LLM 工作**（約 1.5 對／秒，屬推論）：
  - (a) 772 個從未判定的 rule-hit 配對；
  - (b) 75 條方向未驗證的同型邊；
  - (c) 取代 10.3：Event–Person 5,946 對與 Event–Place 3,616 對，經過閘門後會再少一些（約 1.5–2 h）；
  - (d) chunk 上捲後的新配對，先以 dry-run 計數，超過約 2 萬對就移到延後-C。
  - 先確認 5 月實際用的模型（D12）。
- **新增測試**：
  - `test_extract_relations_resume.py`：在 fixture 上中途 kill，再 resume，結果要等於不中斷的跑法；
  - `test_re_batching.py`：同批 context 相同，端點必在其中；
  - `test_pair_miner_rollup.py`；
  - 6.05 加上校準後的冪等測試。
- **管線順序變更**：K6 改成離線挖配對，加上 R4 快取（缺快取的配對以 `--defer` 標 pending，不產生邊）→ 6.05 → 6.1。
- **線上遷移**：照 §3.7 R0–R5；只動 Neo4j 的語意邊。
- **驗證門檻**：
  - 送進 LLM 的配對中，context 缺端點的比例為 0；
  - unclassified 中 unjudged 加 failed ≤1%；
  - 抽樣精確率：LLM 親屬 ≥0.9；非親屬 ≥0.7；Event 參與與地點 ≥0.85（n≥50）；
  - 校準後各桶精確率單調，ECE ≤0.10；
  - 回報事件層覆蓋率的新值，並與 34.4%/31.8%、84.0%/75.5% 並列；
  - H3、H9、R6 維持通過；
  - entity_path A/B（§6.2）。
- **工時**：40–56 h，另加 LLM 牆鐘 3–8 h。
- **行為影響**：只影響 opt-in entity_path；預設路徑與 registry 不變。論文中「77,953 = LLM NONE」「checkpointed and resumable」「evidence 驗證否則拒絕」的敘述要更正。

#### 第 2B 批：RCUV 拼法、權威長名詞表、子字串汙染、描述重生
- **涵蓋**：M2、M4/ID-6、ID-4（少數已確認的 relabel）、EV-08（重生）。
- **要改的腳本與函式**
  - 新增 `config/lexicon/rcuv_proper_names.txt`（git 追蹤，人工審過，**不可**由 CKIP 產物自動建立），涵蓋已知的陷阱：撒馬利亞、以利亞撒、以利亞敬、以利亞實、迦勒底、亞拿突、亞拿尼亞、哈拿尼、尼布撒拉旦、撒拉鐵、亞伯尼歌、西西拉、腓力斯、撒但、約拿達、撒迦利亞、烏利亞…；另列「非名」詞，例如閃電、含怒、含笑。
  - `ner_extractor.py:167-205`：字典命中時，左右擴展後若能組成專名表中的長名，就不採用；`_merge_results`（:259-280）改成：權威長名 span 優先，型別取自專名表，不取 CKIP 的判斷。
  - `entity_dict.py`：canonical 改用 RCUV 拼法；舊拼法移到 `config/lexicon/query_aliases.yaml`，由編譯 aliases 與後端查詢共用；間隔號統一成 U+2027（person:bo‧shan、object:badan‧yalan 的 id 經 id_migration 處理）。
  - 字典拆分（D7）：抽取字典與 `backend/utils/entity_dicts.py` 的路由詞表分開，或保持共用並跑 500 題路由回歸。
  - `config/relations/biblical_priors.yaml`：改用 RCUV 拼法（流便改呂便等）。
  - `entity_overrides.yaml`：已驗證的 relabel，例如 object:samaliya 改 Place（新 id place:samaliya，經 id_migration）、戶篩、示巴女王、亞拿尼亞改 Person，泰爾與伯‧善的 Person/Place 重複合併成 Place。
  - 定向 R4：用 2A 的工具，針對新實體所在的約 100–300 段。
  - K7 重生：描述快取沒命中的實體（1C、1D、2B 中輸入改變的，加上已知事實錯誤的條目），desc_generator 新增 `--entity-ids`。
- **新增測試**：
  - `test_entity_dict_rcuv.py`：每個比對字形在 RCUV 本文至少出現 1 次；白名單包含括號消歧鍵與現代名（死海、地中海、客西馬尼園、巴別塔）；
  - `test_ner_substring_traps.py`：圍攻撒馬利亞、祭司以利亞撒、希勒家的兒子以利亞敬、以利亞實的兒子、像閃電、含怒、西西拉、腓力斯、但我告訴你們。
- **管線順序變更**：K1a 讀專名表；K7 改為只對快取沒命中的實體呼叫 LLM。
- **線上遷移**：照 §3.7。若字典仍共用，image 必須一起重建並一起回滾。
- **驗證門檻**：
  - R2 探針全過；
  - 分層抽 200 條 MENTIONS（必含以利亞、馬利亞、利亞、以利、迦勒），精確率 95% CI 下界 ≥0.90；
  - person:maliya 約 31–33 條（原 126）；place:samaliya ≥100 條；
  - 字典零命中字形只剩白名單；Object 中 canonical 屬於字典的實體為 0；同名同時是 Person 與 Place 的為 0；
  - priors 因拼法而解析不到的條目為 0；
  - D4：若字典共用，500 題路由分布落在雜訊地板內；
  - D1 `--check` 結束碼 0。
- **工時**：32–48 h，另加 LLM 1–3 h。
- **行為影響**：**若字典共用，backend 路由（R3/R6）會改變，線上預設也受影響**。/api 會新增 place:samaliya 等，object:samaliya 等 id 會改變。

#### 第 2C 批：curated 事件的單一真相來源，以及 registry 錨點修正
- **涵蓋**：EV-05、EV-04（curated 的 2 個錨點）、EV-07。
- **要改的腳本與函式**
  - 新增 `config/curated/events.yaml`。事件自足：每筆有 slug、凍結的字面 entity_id、canonical_name、aliases、description、有序的 anchors，以及 trigger_anchors（每個觸發詞自己的首錨）。合併 ALIAS_INJECTIONS（11）、NEW_EVENTS（18），以及 manual patches 的 5 個 Event 節點。抽取節點只做可選的合併，綁定目標不存在時就建立 curated 節點，不會斷鏈。
  - `backfill_head_events.py`、`backfill_manual_patches.py` 改讀 YAML。
  - `export_event_registry.py`：由 YAML 產生 registry；錨點以 pericopes.jsonl 與快照驗證；新增 `--out`、`--diff`。
  - 若要支援每個觸發詞各自的首錨，registry 升到 schema v2，`backend/utils/retrieval/event_registry.py` 的 loader 與 `select_aux_anchors`（:89-103）一併更新。
  - 錨點修正以經文本身為依據，不看 GT：
    - 墮落：首錨改 gen:3:0；
    - 掃羅受膏：補 1sa:10:0 並設為首錨；
    - 八福：改 mat:5:1；
    - 所羅門獻殿：1ki:8:x、2ch:5:1、2ch:6:1、2ch:7:0；
    - 十災：補 exo:8:1、9:0、9:1；
    - 第一次宣教旅程：補 act:14:1；
    - 王國分裂：補 2ch:10:0；
    - 釘十字架：補 mrk:15:4、luk:23:4、jhn:19:2；
    - 新天新地：補 rev:22:0；
    - 重建城牆：補 neh:4:0、6:1；
    - 巴比倫之囚：補 2ki:24:1、25:0、25:1；
    - 受難週、大使命、歌利亞、曠野漂流：補漏段；
    - 合併兩個保羅歸主事件（D11）。
- **新增測試**：
  - `test_events_yaml.py`：每個錨點都存在；每個 (觸發詞, 首錨) 的節範圍都涵蓋該事件，附人工審閱表；
  - backend 的 `test_event_registry.py` 隨 schema 更新。
- **管線順序變更**：10.4、10.5 改由 YAML 驅動；export 放在 10.6 之後；registry 有 diff 時必須人工核可才能 commit。
- **線上遷移**：
  1. `git diff` registry 並審閱；
  2. 用 `evaluation/experiments/2026-10-03_event_registry/run_ab.sh` 驗證；
  3. 500 題答案端評估；
  4. commit 後 `docker compose up -d --build backend`（registry 是 Dockerfile:31 COPY 進去的，只 restart 會跑舊檔）。
  - 回滾：git revert registry，重建 image。
- **驗證門檻**：
  - 同路由題的 top-5 與 graph-off 逐位相同 100%（基準 492/492）；
  - touched ≤35（基準 23）；
  - 與 k 對齊的 dense@6 相比，vrec 與 anchor 都沒有任何題變差；
  - 樣本內題（TOPIC_029、GENERAL_076）另外報告；所羅門獻殿另寫 ≥5 題 GT 外的 held-out 題；
  - 答案端：coverage 為主要指標，faithfulness strict ≥0.97 守門，|Δcoverage| 與雜訊地板 0.060 比較。
- **工時**：24–32 h（不含評估的牆鐘）。
- **行為影響**：**有：event_registry.json 改變，也就是線上預設附加的段落改變。** 這是本計畫中唯一刻意改變線上預設 QA 的項目。墮落、掃羅受膏、八福在 500 題 GT 中出現 0 次；所羅門獻殿 2 題，屬樣本內。

#### 第 2D 批：markdown 平行經文解析器與 TSK 錨點
- **涵蓋**：XREF-5、XREF-6（可選）。
- **要改的腳本與函式**
  - `bible_chunking/markdown_parser.py:35-72` 的 CrossRefParser 重寫成 `parse(ref_text, own_book_id)`：
    - 在「；」與「，」之間沿用前一段的書卷與章；
    - 支援「A‧B－C‧D」跨章範圍；
    - 支援「詩18」這類只有章號的引用；
    - 沒寫書卷縮寫時預設為本卷；
    - 同卷且範圍包含本段的，標為 section_range，不產生邊。
  - :216-229 先判斷細拉，再判斷交叉引用。
  - `bible_chunking/models.py:35-44` 加 `chapter_end`。
  - `process_bible.py:325-342`：依範圍展開，每觸及一段出一條邊（設上限並記錄），`book_id` 為空時報錯。
  - `import_tsk_crossrefs.py`：存前 5 個 anchors，跨章 to-range 完整展開。
- **新增測試**：以 43 筆漏解析案例、22 筆跨章或逗號案例當 fixture；約伯記的 section_range 為反例。
- **管線順序變更**：Step 0 輸出會改到 pericopes.jsonl 的 cross_references 欄位，所以 PG 的 pericopes 要重匯（被動欄位，正文不變）。embedding_queue 的 sha 閘門必須不變，因為 cross_references 不進 embedding 文字。
- **線上遷移**：照 §3.7，另加 PG pericopes 表的備份與換表。
- **驗證門檻**：
  - 非細拉、非 section_range 卻解析不到的引用為 0（原 39）；
  - verse_end<verse_start 為 0（原 6）；
  - 跨段範圍沒展開的為 0（原 36）；
  - curated markdown 配對數 891±5；
  - anchors 100% 落在兩端範圍內；
  - EVENT_067 的注入槽比對；kg_xref A/B。
- **工時**：12–16 h。
- **行為影響**：只影響 opt-in xref（curated 鄰居增加、扇出變大）；預設路徑不變。

### 延後（需要重跑 LLM，或身分層大改）

#### 延後-A：身分層重建
- **涵蓋**：ID-1、ID-2、ID-4（其餘部分）、ID-5（其餘部分）、ID-7（註冊表與 redirect）、M3（猶大與以法蓮）、G-5。
- **內容**：
  - 新增 `scripts/entity_extraction/identity.py`：normalize_surface、IdentityRegistry、`resolve()`（cues 依「限定語＞書卷章範圍」的優先序，必要時 abstain）、`mint_entity_id()`（漢字 canonical 加全形括號限定語）。
  - `config/curated/entity_registry.jsonl` 以 live 的 9,124 筆種子化，這一步對所有消費者都是 no-op；另建 `identity_ops.jsonl`。
  - 新增 Step 1.5 `resolve_identities.py`：同時改寫 entities、mentions、relations、relations_unclassified，以及 10.2 的輸入。
  - 人工審閱 380 種字形、8 個歧義名（含 act:13:2 屬掃羅王、1ch:26:0 的「西門」是西邊的門、希律黨），以及 285 個 Object 孿生與 15 個 Event 孿生（逐案決定合併方向）。
  - NER 的 `_all_entities` 改為 name→Set[type]，以上下文判定猶大、以法蓮、但是 Person 還是 Place。
  - canonical 要唯一，或 priors 改用 id 參照。
  - 匯出 `backend/data/entity_redirects.json`；routers/entity.py 對合併的 id 回 308，對拆分的 id 回 300 並附 split_into。
  - 重算 mention_count；受影響的實體約 300–500 個要重生 K7；新配對送 R4。
- **驗證**：
  - R3 從 169 降到 0；
  - 金標集 ≥200 條 mention，指派精確率 ≥0.95，abstain ≤0.25；
  - 字典條目中永不產生節點的從 7 降到 0；
  - fixtures：路得對 Ruth、米甲／米迦／彌迦／密迦是 4 個 id、腓力／腓利是 2 個 id；
  - 三庫一致；
  - 重灌鏈的結果與快照 diff 為 0（只在重灌鏈上驗證，因為 LLM 步驟會漂移）；
  - D1、D4。
- **工時**：64–100 h（工程 3–5 人日，標註 2–3 人日，金標集 1–2 人日），另加 LLM。
- **行為影響**：**有**：/api/v1/entity 的 id 會拆分並重導（backend router 要改）；若字典改成註冊表，路由會變；find_entity_by_name 的結果會變。Event id 凍結，registry 預期不變。

#### 延後-B：grounded 半邊（E/O/T）重抽
- **涵蓋**：EV-01（階段 B）、EV-03、EV-04（parser）、M5（Phase 2 去截斷）、M3（POS 閘門）。
- **內容**：
  - 判決強制生效：null、evidence 不符、型別越界、LLM 漏回的候選都算 rejected；error 讓建置失敗。
  - 重新設計判決 prompt，改以整段經文當 context。
  - 建立 `config/curated/event_title_verdicts.jsonl`（約 2,400 個標題；LLM 判決加人工抽查），之後重建都先查這個檔。
  - 字尾型別規則只用在 4 字以內的名詞；刪掉關鍵字「約」；王名規則限定為「王＋字典人名」整串相符。
  - `bible_md_parser.py:190-197、221-226` 建立隱含的 (無標題) 段，再做續段繼承。
  - Phase 2 去截斷只做 O/T，並建立 Phase 4 的名稱快取。
  - 下載 CKIP POS 模型（本機沒有快取，依目前頻寬約需數小時）。
- **驗證**：
  - 保留下來的 Event 抽 100 個，「具體敘事事件」的比例 ≥0.90；
  - 用判決檔重跑兩次，Event 集合 diff 為 0；
  - Object/Theme 中 mention_count>10 但 MENTIONS≤10 的為 0；
  - D1（curated 同 id 的事件若多出錨點，視為 registry 變更，要做 A/B）。
- **工時**：40–60 h，另加 LLM 數小時。
- **行為影響**：可能影響 registry，必須跑 --check；/api 與 entity_query 的型別會變。

#### 延後-C：Step 6 全量重跑（找回召回）
- 時機：延後-A、延後-B 與 2B 都上線之後。
- 用修好的批次、截斷、chunk 上捲與快取，全量重跑 R4（約 85–100k 對，10–20 h LLM）。之後全面淘汰舊的 LLM 邊。
- **工時**：8–16 h 人力，另加 LLM 牆鐘 10–20 h。只影響 opt-in entity_path。

#### 不做（YAGNI，或已確認不需要）
- EV-10 事件時間線：沒有消費者，有需求時再建 curated 檔。
- M1(c) 拿掉 verse NER：有風險，收益只是加速。
- M1(d) 書名「尼西米記」改名：本文限定的 NER 已經不會看到書名，改名卻會牽動後端、評估與 Qdrant。
