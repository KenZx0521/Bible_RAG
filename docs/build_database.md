# Bible RAG 建庫管線（Step 0–10）

## 環境設定

使用 uv 管理 scripts 的 Python 依賴：
```bash
# 在專案根目錄執行，安裝所有 scripts 依賴
uv sync --project scripts
```

### scripts 測試

scripts/ 的測試放在 `scripts/tests/`，以 `scripts/tests/run.sh` 執行。它用 scripts 的 venv，pytest 借自 evaluation 的 venv（scripts 的 venv 沒有 pytest，加進去就得重鎖 scripts/uv.lock）：
```bash
scripts/tests/run.sh               # 全部
scripts/tests/run.sh -q -k step0   # 其餘參數照傳給 pytest
```
backend 與 evaluation 的測試各自在 `backend/tests/`、`evaluation/tests/`，不由這支執行。

## 從零重建 Checklist（fresh clone）

在全新機器 clone 後、跑 Step 0–10 之前，依序完成本節。**現機重灌**（`output/` JSONL 俱在）只需確認 0.2/0.3，然後走本節末「執行順序」的重灌鏈。

### 0.1 Git 內已備，不需重跑

- `bible_md/`（66 卷）與 `bible_pdf/`（66 卷）皆已 git-tracked —— **不需**跑 `scripts/convert_bible_pdf.py`（其輸入/輸出路徑 hardcode 在 repo 外，屬歷史工具）
- `config/relations/*.yaml`、`config/curated/manual_graph_patches.jsonl`、`config/step0_sha.json`（Step 0 sha 基準）、`scripts/uv.lock` 皆已 git-tracked
- `output/` 整個被 gitignore：所有 JSONL 產物需由管線重新產生。LLM 產物（`output/frozen/`、relations*.jsonl、entities／mentions、checkpoint、TSK 原始檔）重跑必有漂移，只能從備份還原（[staging_promotion.md](staging_promotion.md) R0 的 `llm_artifacts.tgz`）

### 0.2 建立 .env（不進 git；組態即建庫結果的一部分）

```bash
cp .env.example .env   # 再填入 ANTHROPIC_API_KEY 等秘密值
```

對建庫結果有決定性影響、且與程式碼 fallback **不同**的 key（`.env.example` 已含，勿刪）：

| Key | 值 | 影響 |
|-----|-----|------|
| `ENTITY_EXTRACT_OLLAMA_MODEL` | `gemma4:31b-it-q8_0` | Step 1 Phase 4；code fallback 是 `gemma3:4b`，漏設會用小一個量級的模型抽實體 |
| `DESC_OLLAMA_MODEL` | `gemma4:26b-a4b-it-q8_0` | Step 7；code fallback 是 `gemma4:e4b-it-q8_0` |
| `HYBRID_SEARCH_ENABLED` | `true` | 查詢期走 hybrid collection；backend code 預設 `false` |

### 0.3 啟動資料庫服務（⚠ 不要一次 up 全部）

```bash
docker compose up -d postgres qdrant neo4j ollama
```

**backend 必須留到管線跑完最後**才 `docker compose up -d --build backend`：backend 服務 bind-mount `./output/bm25_vocabulary.json`，檔案尚不存在時先起 backend，Docker 會在 host 建出同名**目錄**，Step 2.1 寫檔會直接失敗。

- PG volume 為空時 `scripts/db/schema.sql` 自動建表（docker-entrypoint-initdb.d）
- Neo4j APOC 已由 compose 配置（`NEO4J_PLUGINS: ["apoc"]`），Step 6.1 與 Step 10 重放鏈依賴它
- compose 的 ollama 服務要求 NVIDIA container runtime；無 GPU 機器 `up` 會直接失敗

### 0.4 Ollama 模型（不會自動 pull，volume 是空的）

```bash
docker exec ollama ollama pull gemma4:31b-it-q8_0      # Step 1 Phase 4 + Step 6 R4
docker exec ollama ollama pull gemma4:26b-a4b-it-q8_0  # Step 7
```

### 0.5 Python 環境

```bash
uv sync --project scripts   # BGE-M3 / CKIP 權重於首次執行時自動從 HuggingFace 下載
```

### 0.6 外部資料

- Step 9 的 `output/cross_references_tsk.txt` 需自行下載（來源與授權見 Step 9 前提）

### 執行順序

- **從零**（沒有 staging 的機器）：`process_bible.py` → `check_step0.py`（Step 0 是決定性的，fresh clone 重跑應與 git 追蹤的基準逐位元相同；不符就先查原因）→ `validate_output.py`（必跑，見 Step 0）→ Step 1 → 2 / 2.1 → 3 → 4 / 4.1 → 5 → 6 → 6.05 → 6.1 → 8a → 9 → 10.1 → 10.2 → 10.4 → 10.5 → 7 → 8b → 10.6（改用 `--target prod`）→ `export_event_registry.py --check` → `docker compose up -d --build backend`。共現搶救已退出預設鏈（見 Step 10）。若能從 [staging_promotion.md](staging_promotion.md) R0 的 `llm_artifacts.tgz` 還原 `output/frozen/`、relations.jsonl 與兩個實體檔，Step 6 沿用還原的 relations.jsonl、Step 7 改走 `--replay --fail-on-stale`，就不必重跑 LLM。第 1 批期間 Step 1 照重灌鏈換成 `check_merged_inputs.py`，不要 merge（理由見表下）；W2 重跑 NER 之後才回到 `--stage merge`。
- **重灌**（JSONL 與 `output/frozen/` 俱在；一律先建在 staging，見 [staging_promotion.md](staging_promotion.md)）。下面是第 1 批 W1 的重灌鏈，在第 1D 批改寫重灌鏈之前是唯一的一條：

  **0 → check_step0 → validate_output（必跑）→ xref_probe expect（重算比對）→ check_merged_inputs（取代 1）→ 6.05 → 3 → 4（sha 未變就跳過）→ 5 → 6.1 → 8a(embed) → 9（連跑兩次＋xref_probe fingerprint --expect）→ 10.1 → 10.2 → 10.4 → 10.5 → 7(replay --fail-on-stale) → 8b(embed --recreate) → 10.6 → export_event_registry --check**

  | 順序 | 指令（前綴 `uv run --project scripts python`） | 說明 |
  |---|---|---|
  | 0 | `scripts/process_bible.py --input-dir bible_md --output-dir output`，再 `scripts/tools/check_step0.py`、`scripts/validate_output.py output` | 三者都不寫庫，結束碼不是 0 就停（見 Step 0）。validate_output 必跑 |
  | xref_probe expect | `scripts/tools/xref_probe.py expect --output-dir output --tsk output/cross_references_tsk.txt --out bak/$D/xref_probe/xref_rebuild.json`，再以 `cmp` 比對登記的 `config/kg_expect/batch1_w1/xref.json` | `D` 是 R0 的日期。期望檔在 W1 第 2 步之前登記，這裡只重算比對，不同就停，不可覆寫（[staging_promotion.md](staging_promotion.md) R2「W1 的交叉引用檢查」第 1 項） |
  | check_merged_inputs | `scripts/tools/check_merged_inputs.py` | 取代 Step 1：entities.jsonl、entity_mentions.jsonl 的 sha256 要等於 `output/frozen/grounded_manifest.json` 記的 source。結束碼 0 相符；1 不符或缺檔，照它印出的 `tar` 指令從 [staging_promotion.md](staging_promotion.md) R0 的 `llm_artifacts.tgz` 還原兩檔（先以 `MANIFEST.sha256` 核對）；2 無法檢查 |
  | 6.05 | `-m scripts.relation_extraction.relation_postprocess`，連跑兩次並 `cmp`（見 Step 6.05） | 離線、不連庫：relations.jsonl → relations_clean.jsonl 加報告。排在所有寫庫的步驟之前，輸入有錯就在清庫之前停下 |
  | 3 | `scripts/import_postgres.py` | 六張表 |
  | 4 / 4.1 | （跳過） | 閘門通過＝embedding_queue 未變，段落向量與 BM25 都不必重建，Step 2 / 2.1 也不跑。閘門沒過而且是刻意變更時，才重跑 2 / 2.1 / 4 / 4.1 |
  | 5 | `scripts/import_neo4j.py` | 先清空目標 Neo4j 再重建 |
  | 6.1 | `scripts/import_relations_neo4j.py` | 讀 6.05 的 relations_clean.jsonl 與報告，不帶 `--replace`。必須緊接在 Step 5 之後：圖裡已有語意邊就拒絕（見 Step 6.1） |
  | 8a | `scripts/embed_entities.py --recreate` | 只為了讓 10.x 有 collection 可寫：沒有它，10.2（staging 下）刪點、10.4 upsert 都會失敗，10.5 找不到 extracted 點會 SystemExit。這時 P/P/G 描述還是空的，8b 會整個取代。W1 寫 `bible_entities_v3`（建議，待 Kay 確認，見 Step 8） |
  | 9 | `scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt` 連跑兩次，再 `scripts/tools/xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json` | 第二次 `created 0`、兩次同一個指紋，fingerprint 結束碼 0（見 Step 9） |
  | 10.1 | `scripts/backfill_aliases.py` | 見 Step 10 |
  | 10.2 | `scripts/cleanup_noise_entities.py` | 第 1C 批之前，「但」的誤命中仍在這裡真的刪 MENTIONS |
  | 10.4 | `scripts/backfill_head_events.py` | |
  | 10.5 | `scripts/backfill_manual_patches.py --apply` | 10.3（共現搶救）已退出預設鏈，不在這裡跑（見 Step 10） |
  | 7 | `-m scripts.relation_extraction.desc_generator --replay --fail-on-stale` | 從正式快取 `output/frozen/descriptions.jsonl` 重放，不呼叫 LLM。必須在 10.5 之後：種子的 titles_sha 是用 live（10.x 之後）的 MENTIONS 算的。W1 不改 MENTIONS，stale 與 missing 都必須是 0（見 Step 7） |
  | 8b | `scripts/embed_entities.py --recreate` | 用最終的描述、aliases、MENTIONS 重嵌。10.2/10.4/10.5 寫進 Qdrant 的都是它們在 Neo4j 寫下的狀態的投影，8b 從 Neo4j 重讀，全部涵蓋 |
  | 10.6 | `scripts/validate_kg.py --live --target staging`、`scripts/check_identity.py --target staging --fail-on id`、`scripts/tools/check_edge_set.py --target staging` | 判準見 Step 10.6 |
  | export | `scripts/export_event_registry.py --check` | 結束碼 0 才算建完。只有刻意改 registry 的批次才不帶 `--check` 重寫，並人工審 diff |

  **W1 為什麼跳過 Step 1**：`output/ner_*.jsonl` 是第 0 批在 7526e12 之前產生的 NER 半邊，字典已把流珥併進葉忒羅。merge 不會拒絕它，只發 WARNING，接著寫出少了 person:liuer 的 entities.jsonl（9,119 行）；6.05 再因 6 列的端點 person:liuer 不存在而硬失敗。所以 W1 不重寫兩個實體檔，只確認它們仍是第 0 批的 build（[第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §6 #10）。check_merged_inputs 只用於 W1。

- **一致性**：結構層（Step 0，已驗證逐位元相同）、NER 半邊（600 筆樣本重跑 2,830/2,830 相同）、TSK、curated 層、6.05（同一份輸入連跑兩次逐位元相同）都是決定性的。LLM 產物（Step 1 Phase 4 的 grounded 半邊、Step 6 R4、Step 7 描述，temperature=0.2）重跑必有漂移，所以重灌鏈一律重用凍結產物：grounded 半邊與描述在 `output/frozen/`，關係沿用 relations.jsonl，再由 6.05 處理。只有刻意重跑 LLM 的批次（2A、2B、延後-B/C）才會讓這些層變動。
- **事前登記**（[第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §3）：W1 的期望檔（1A 的 `relations_expected.json`、`residuals_expected.json`，1B 的 `xref.json`）與合併允許清單 `config/kg_diff_allow_batch1w1.yaml`，都在 W1 第 2 步（staging 重建）之前產生並記下 sha256；重建與 R2 只拿來比對，看過 staging 的 diff 之後不可再改。順序與指令見 [staging_promotion.md](staging_promotion.md) R2。
- ⚠ Step 6 長跑注意（已驗證，比舊說法嚴重）：checkpoint 是在配對**送進 R4 之前**逐對寫入的（`_stream_with_checkpoint`），所以 R4 中途崩潰後 `--resume` 會把整批配對當成已處理，產出 0 條 LLM 邊；`--no-llm` 與 `--pericope-id` 都以覆寫模式改寫 `relations.jsonl` 與 `relations_unclassified.jsonl`。第 2A 批修好之前，不要對既有產物重跑 Step 6；試跑時用 `RE_OUTPUT_PATH`、`RE_CHECKPOINT_PATH`、`RE_UNCLASSIFIED_PATH` 導到別的檔案，跑完比對量級（歷史 run 約 6,958 條）。

## Step 0: 經文切分與 sha 閘門

### 說明
- Hierarchical Chunking（Book → Chapter → Pericope → Chunk）
- JSONL 輸出（7 個檔案）：books、chapters、pericopes、chunks、embedding_queue、neo4j_nodes、neo4j_relationships
- 決定性：2026-10-04 重跑，7 個檔案逐位元相同

### 指令
```bash
uv run --project scripts python scripts/process_bible.py --input-dir bible_md --output-dir output

# sha 閘門：結束碼 0 才可往下走
uv run --project scripts python scripts/tools/check_step0.py

# 交叉引用閘門（第 1B 批起必跑）：結束碼 0 才可往下走
uv run --project scripts python scripts/validate_output.py output
```

### sha 閘門（`scripts/tools/check_step0.py`）
- 計算 output/ 中 5 個檔案（books、chapters、pericopes、chunks、embedding_queue）的 sha256，與 git 追蹤的 `config/step0_sha.json` 比對。這 5 個檔案是重灌時**不重建**的幾層的輸入：PG 的四張結構表（Step 3）、段落向量（Step 2 → 4 / 4.1）、BM25 詞表（Step 2.1）。neo4j_*.jsonl 不在閘門內，因為它們只餵 Step 5，而 Step 5 每次都清庫重建；第 1B 批也會刻意改動其中的交叉引用。
- 結束碼：0 表示 5 個檔案全部相符；1 表示有檔案改變或缺檔，逐檔列出 expected 與 actual 的 sha、行數、位元組數；2 表示無法檢查（沒有基準檔，或 `--record` 時 output/ 缺檔）。
- 基準於 2026-10-04 由現行 output/ 記錄：embedding_queue.jsonl 34,072 行，sha256 `5d2ac0e5460c…`，與計畫 §1.2 的 run-of-record 相同。
- 不一致時先停下來查原因（bible_md/、bible_chunking/、process_bible.py 是否有改）。若是刻意的變更（例如第 2D 批會改 pericopes.jsonl 的 cross_references 欄位；第 1B 批只改 neo4j_relationships.jsonl，閘門照樣結束碼 0）：
  1. 若 embedding_queue.jsonl 也變了，要重跑 Step 2 / 2.1 / 4 / 4.1（段落向量與 BM25 會變，這次就不再是「重灌」），Step 1 也要先重跑 `--stage ner`（merge 會拒絕抽自舊 queue 的 NER 半邊）；
  2. 先 `check_step0.py --record --dry-run` 預覽，再 `--record` 寫入新基準；
  3. 新基準與造成變更的程式碼放在同一個 commit。
- 重錄時若 5 個檔案逐位元未變，基準檔不會被改寫，不會產生只改了 recorded_at 的 diff。

### 交叉引用（第 1B 批起）
- **supplementary 定義用經文座標**：`bible_chunking/nt_cross_references.py` 的 159 筆定義兩端都寫成 `book ch:verses`（例：`rev 19:16` → `dan 2:47`）。process_bible 用 `bible_chunking/curated_xrefs.py` 逐節查出所在段落，每個觸及的（來源段, 目標段）產生一個錨點字串（`rev 18:2-8>jer 51:45`，只帶落在該段落對上的節）；一筆定義最多扇出到 3 個段落對。舊碼來源端直接用段落 id、目標端只看第一節，59 筆錯位、16 筆被靜默丟掉（XREF-1）。
- **fail-fast**：任一筆定義解析失敗（缺節、跨章、扇出超過 3、格式錯），就逐條列出並結束碼 1，在寫任何 JSONL 之前停下。
- **每個段落對一列**：markdown 與 supplementary 依 (start, end) 聚合成一列，屬性見 Step 5。markdown 引用只到段落層級，錨點的來源節記 `?`；解析器沒讀到的部分也記 `?`，不寫成看似合法的值：跨章範圍的終點（`deu 2:26-?`，14 個）與逗號後的範圍（`2ki 25:18-21,?`，8 個），留給第 2D 批（XREF-5）。
- **只改 neo4j_relationships.jsonl 的 CROSS_REFERENCES 列**：上面 5 個閘門檔不變，check_step0 照樣結束碼 0。
- **validate_output 的交叉引用閘門**（錯誤即結束碼 1）：重複的段落對；端點不是 Pericope；curated 列的旗標與出處清單不齊（`curated`、`tsk`、`curated_sources`、`source`、各來源清單的長度）；任何 None 值；supplementary 錨點的書卷、章、節不在端點段落內；定義覆蓋（由定義解析出的錨點與列上的錨點，以多重集合相等）。markdown 與 supplementary 重疊、`-?`、`,?` 只發警告。
- W1 的 Step 0（neo4j_relationships.jsonl sha256 `d2389c73…`，2026-10-05 重跑）：CROSS_REFERENCES 932 列（markdown 774、supplementary 158）、重複段落對 0、非 Pericope 端點 0、supplementary 錨點 162、定義覆蓋 159/159；警告為 `-?` 14 個、`,?` 8 個，另有既有的 embedding queue 計數警告。1B 之前的 output/ 會被擋下：重複段落對 2 個、919 列沒有 curated 旗標、定義覆蓋 0/159。

---

## Step 1: 實體抽取

### 輸入
- `output/embedding_queue.jsonl`（34,072 筆：pericope 2,610 + chunk 431 + verse 31,031）

### 待抽取實體類型
| 類型 | 說明 |
|------|------|
| Person | 人物（亞伯拉罕、摩西、耶穌） |
| Place | 地點（耶路撒冷、埃及、加利利） |
| Group | 群體（以色列人、法利賽人） |
| Event | 事件（出埃及、復活） |
| Object | 物件（約櫃、會幕） |
| Theme | 主題（救贖、恩典、信心） |

### 兩個半邊（第 0 批起）
| 半邊 | 型別 | 來源 | 重跑 |
|---|---|---|---|
| NER 半邊 | Person / Place / Group | 字典＋CKIP，決定性（600 筆樣本重跑 2,830/2,830 相同） | 約 30 分鐘，不需 LLM |
| grounded 半邊 | Event / Object / Theme | pericope 標題探勘＋CKIP POS＋Phase 4 LLM 判決 | 需 LLM 數小時；Phase 4 沒有逐候選快取，重跑必有漂移 |

grounded 半邊凍結在 `output/frozen/`，重建時只重跑 NER 半邊，再與凍結檔合併。

### 指令
```bash
# 一次性：從現行 entities.jsonl / entity_mentions.jsonl 依型別拆出 grounded 半邊，凍結成
# output/frozen/grounded_entities.jsonl、grounded_mentions.jsonl、grounded_manifest.json。
# 凍結檔已存在時拒絕覆寫（要覆寫須加 --force）；--dry-run 只驗證並報告
uv run --project scripts python scripts/extract_entities.py --stage freeze-grounded

# NER 半邊（P/P/G，CKIP，無 LLM，約 30 分鐘）→ output/ner_entities.jsonl、ner_mentions.jsonl，最後寫 ner_manifest.json
uv run --project scripts python scripts/extract_entities.py --stage ner

# 合併 NER 半邊與凍結的 grounded 半邊 → output/entities.jsonl、output/entity_mentions.jsonl（拒絕條件見下）；--dry-run 只驗證
uv run --project scripts python scripts/extract_entities.py --stage merge
```

- 第一次：`freeze-grounded` → `ner` → `merge`。merge 要讀 `output/ner_entities.jsonl`、`ner_mentions.jsonl`、`ner_manifest.json`，而 freeze-grounded 不會寫出它們，所以凍結後第一次 merge 之前**必須先跑過一次 `--stage ner`**（約 30 分鐘；第 0 批之前產生的 ner_* 沒有 manifest，同樣要重跑；`merge --dry-run` 的 log 會說 NER 半邊與凍結時是否相同，等於順便驗證 NER 能完整重現）。之後重灌鏈只跑 `merge`；NER 程式、字典、embedding_queue 有改時才重跑 `--stage ner`。凍結的 manifest 是 `output/frozen/grounded_manifest.json`（不是 manifest.json：`output/frozen/` 還放描述快取等其他凍結檔）。等價要求：兩個半邊都沒改時，merge 的結果必須與現行 entities.jsonl、entity_mentions.jsonl 逐位元相同。
- **NER 半邊的來歷**：`--stage ner` 先刪掉舊的 `output/ner_manifest.json`，兩個 ner 檔寫完才寫新的，記錄兩檔的 sha256 與行數、`sampled`／`sample`、輸入檔（embedding_queue）的路徑與 sha256、git commit。merge 遇到下列任一情況就拒絕（結束碼 1，什麼都不寫，`--dry-run` 也一樣）：沒有 manifest、讀不到或欄位格式不對；manifest 標成 sampled（`--sample N` 的結果；只有明寫 `"sampled": false` 才算完整）；ner 檔與 manifest 記的 sha 不符（跑完後被改過）；manifest 記的輸入 sha256 與目前 `-i`（預設 `output/embedding_queue.jsonl`）的內容不符，或該檔不存在（NER 半邊抽自另一份 queue，例如 Step 0 重錄之後；比的是內容不是路徑）。加 `--force` 才放行，每個被放行的問題記一行 WARNING。凍結檔與 grounded_manifest 不符、grounded_manifest 讀不到或格式不對，則連 `--force` 也拒絕。
- **grounded 半邊的防護**：freeze 遇到空的 grounded 半邊、或缺 Event／Object／Theme 任一型別時拒絕（`--dry-run` 也檢查），`--force` 放行。重新凍結本來就要 `--force`，所以另設 `--accept-grounded-drift`：新半邊的實體或 mention 行數相對於被取代的快照變動超過 5%（舊 manifest 不見時改比現存凍結檔的行數；manifest 讀不到、或連凍結檔也不齊時一律要這個旗標）時，沒有它就拒絕，以免 `--sample`、`--phase`、`--ner-only --force` 留下的殘缺 build 蓋掉唯一一份 Phase 4 產物。merge 遇到凍結快照是空的、或現行 entities.jsonl 一個 E/O/T 都沒有（多半是被清掉了）時拒絕；查明原因後加 `--force` 會以凍結檔還原。
- **「NER half differs」WARNING**：merge 把 NER 半邊與 grounded_manifest 的 `ner_half`（凍結時那次 build 的 NER 半邊）比對，不同時照樣寫出，但記一行 WARNING：`NER half differs from the frozen build's: entities a -> b (±n), mentions …; by type: …`；相同時只記 INFO（`NER half identical …`）。一般重灌出現它代表 NER 沒有重現，要查。第 1C 批刻意改 NER，必然出現：核對各型別的增減與該批預期相符、記進該批紀錄後，跑一次 `--stage freeze-grounded --force` 把 `ner_half` 重設成新基準（grounded 沒變，漂移為 0，不需 `--accept-grounded-drift`），否則之後每次 merge 都會出現這個 WARNING，久了就沒人看。
- `--ner-only`（舊介面）會用只有 P/P/G 的結果覆寫 entities.jsonl 與 entity_mentions.jsonl，丟掉 E/O/T 共 4,897 個實體、20,458 筆 mention，而 registry 的錨點就在其中。現在沒有 `--force` 會拒絕執行；請改用 `--stage ner` 加 `--stage merge`。
- 完整抽取（含 Phase 4 LLM，需 `ENTITY_EXTRACT_*` 設定）只在兩種情況使用：fresh clone 拿不到凍結檔，或刻意重抽 grounded 半邊（延後-B）。它會覆寫兩個輸出檔：
  ```bash
  uv run --project scripts python scripts/extract_entities.py
  ```

### 輸出
- `output/entities.jsonl`
- `output/entity_mentions.jsonl`
- `output/ner_entities.jsonl`、`output/ner_mentions.jsonl`、`output/ner_manifest.json`（`--stage ner`）
- `output/frozen/grounded_entities.jsonl`、`grounded_mentions.jsonl`、`grounded_manifest.json`（`--stage freeze-grounded`）

---

## Step 2: Embeddings 生成 ✅

### 輸入
- `output/embedding_queue.jsonl`（34,072 筆：pericope 2,610 + chunk 431 + verse 31,031）

### 模型
- BGE-M3（BAAI/bge-m3），1024 維，最大 8192 tokens

### 指令
```bash
uv run --project scripts python scripts/generate_embeddings.py --batch-size 32
```

### 輸出
- `output/embeddings.jsonl`（34,072 筆，每筆 1024 維向量）

---

## Step 2.1: Sparse Vectors 生成（Hybrid Search）

### 說明
為 Hybrid Search 生成 BM25-based sparse vectors，使用 CKIP 進行中文斷詞。

### 輸入
- `output/embedding_queue.jsonl`

### 指令
```bash
uv run --project scripts python scripts/generate_sparse_vectors.py --batch-size 32

# 使用 GPU 加速 CKIP
uv run --project scripts python scripts/generate_sparse_vectors.py --batch-size 32 --use-gpu
```

### 輸出
- `output/sparse_vectors.jsonl`（每筆包含 sparse vector indices 和 values）
- `output/bm25_vocabulary.json`（BM25 詞彙表和 IDF 值）

---

## Step 3: 匯入 PostgreSQL ✅

### 匯入資料
- `output/` 的 books、chapters、pericopes、chunks、entities、entity_mentions（各一個 `.jsonl`）

### 指令
```bash
uv run --project scripts python scripts/import_postgres.py
```

### 結果
- books 66、chapters 1,189、pericopes 2,779、chunks 431、entities 9,120、entity_mentions 173,896，**總計 187,481 筆**

> 上列為 JSONL 產物匯入量。Step 10 curated 重放後 live 為 entities 9,122 / entity_mentions 173,768（+18 curated Event、−16 泛名詞 Event、噪音 mention 清理 −128）。

---

## Step 4: 匯入 Qdrant ✅

### 匯入資料
- Embeddings（from Step 2）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings`（pericope + chunk embeddings）

### 指令
```bash
uv run --project scripts python scripts/import_qdrant.py
```

> ⚠ 預設會先刪除再重建目標 collection（`--no-recreate` 可關閉）。collection 名取自 `QDRANT_COLLECTION`（預設 `bible_embeddings`，與 backend 設定 `qdrant_collection` 同名）。staging 不跑這一步：Step 0 閘門通過時段落向量不變，staging 與 production 共用同一個段落 collection。

### 結果
- Vectors: 34,072 (1024 維度)

---

## Step 4.1: 匯入 Qdrant Hybrid Collection

### 說明
建立包含 dense + sparse vectors 的 hybrid collection，支援 RRF 混合檢索。

### 匯入資料
- `output/embeddings.jsonl`（dense vectors）
- `output/sparse_vectors.jsonl`（sparse vectors）
- Metadata（from pericopes/chunks）

### Collection 設計
- `bible_embeddings_hybrid`
  - dense: 1024D BGE-M3 向量（COSINE distance）
  - sparse: BM25-based sparse 向量

### 指令
```bash
uv run --project scripts python scripts/import_qdrant_hybrid.py
```

> ⚠ 與 Step 4 相同：預設刪除後重建（`--no-recreate` 可關閉），collection 名取自 `QDRANT_HYBRID_COLLECTION`；staging 不跑。

### 結果
- Points: 34,072（每個點包含 dense + sparse vectors）

### 啟用 Hybrid Search
在 `.env` 中設定：
```bash
HYBRID_SEARCH_ENABLED=true
```

---

## Step 5: 匯入 Neo4j ✅

### 匯入資料
- `output/neo4j_nodes.jsonl`（4,465 筆）
- `output/neo4j_relationships.jsonl`（8,371 筆，W1 的 Step 0，其中 CROSS_REFERENCES 932 列；1B 之前是 8,358 筆）
- 實體節點與關係（from Step 1）

### 節點類型
- Book、Chapter、Pericope、Chunk
- Person、Place、Group、Event、Object、Theme

### 關係類型
- CONTAINS、NEXT、NEXT_BOOK
- CROSS_REFERENCES
- MENTIONS（實體出現）

### 指令
```bash
uv run --project scripts python scripts/import_neo4j.py
```

> ⚠ 預設先清空 `NEO4J_URI` 指向的整個資料庫（`--no-clear` 可關閉）。重建一律對 staging（`bolt://localhost:7688`）執行，跑之前先做 [staging_promotion.md](staging_promotion.md)「執行前檢查」中的環境變數檢查。

### 交叉引用（第 1B 批起）
- Step 0 每個段落對只寫一列，這裡以 `MERGE (a)-[r:CROSS_REFERENCES]->(b) SET r += props` 寫入。屬性：
  - `curated: true`、`tsk: false`。Step 9 會把有 TSK 證據的段落對改成 `tsk: true`，並寫上 votes。
  - `curated_sources`：排序過的來源清單（markdown、supplementary）。`source` 是單一值，兩者都有時取 markdown。
  - markdown：`md_ref_texts`（原文，例如 `撒上31‧1－13`）與 `md_anchors`（同一列是 `1ch 10:?>1sa 31:1-13`），兩個清單逐項對齊。
  - supplementary：`supp_anchors`、`supp_ref_types`（quotation／allusion）、`supp_descriptions`，三個清單逐項對齊。`supp_tsk_exempt_anchors` 只在定義帶 tsk_exempt 時才寫，因為 Neo4j 的 list 不能含 null。
  - 不再寫 ref_text、verse_start、verse_end、ref_type、description、source_verses、target_verses。validate_kg 的 R4 只在讀 1B 之前建的圖時用到舊欄位。
- **重複段落對防護**：連線之前（也就是清庫之前）檢查 neo4j_relationships.jsonl。CROSS_REFERENCES 有兩列以上同一個 (start, end) 時，逐對列出並結束碼 1，因為 MERGE 加 `SET r += props` 只會留下最後一列的屬性（XREF-1(b) 就這樣吞掉錨點）。通過時印出 `✓ 932 CROSS_REFERENCES rows, no duplicate pair`；檔案不存在時跳過，與匯入本身一致。

### 結果
- Total nodes: 19,310
- Total relationships: 57,877

> ⚠️ 上列為 2026-05 快照。P0 修復（2026-07-06）後 `import_neo4j.py` 內建 verse→pericope remap 與誠實計數器，重匯的 MENTIONS 會多於舊快照（verse 級 mention 不再靜默丟棄，落空者計入 `skipped_missing`）；live 現況見 [kg_optimization_progress.md](kg_optimization_progress.md)。

---

## Step 6: 關係抽取（Grounded RE）

### 說明
為 Entity 之間補上語意關係邊（FATHER_OF、RULED、BORN_IN 等 37 種），修復對照論文 *Graph RAG Survey* 後發現的「Entity↔Entity 邊 = 0」最大缺口。LLM 受限於 yaml schema 候選池（不能自由生成關係名稱），且 `evidence_span` 必須是上下文子字串才會被接受。產物是原始 triples：第 1A 批起先經 Step 6.05 清理，6.1 只匯入 6.05 的輸出。

### 前提
- Step 5 完成（Entity / Pericope / MENTIONS 已在 Neo4j）
- Postgres `pericopes.content` 可讀（用於 grounding text）
- Ollama 已 pull `gemma4:31b-it-q8_0`（或加 `--no-llm` 跳過 Phase R4）

### 輸入
- `config/relations/biblical_relations.yaml`（37 個敘事級關係本體）
- `config/relations/biblical_priors.yaml`（~70 條黃金族譜先驗）
- Neo4j（Entity + Pericope + MENTIONS）
- Postgres `pericopes.content`

### Grounded Pipeline
| Phase | 動作 |
|------|------|
| R1 Pair Mining | 同 pericope 共現 entity 對（schema type-allowed 才保留） |
| R3 Domain Priors | yaml priors 直接賦邊（專家共識，bypass LLM） |
| R4 Grounded LLM | gemma4:31b-it-q8_0 從候選池選一個或回 NONE，evidence 必須是子字串 |
| R5 Inverse Materializer | 選用，加 `--inverse` 才跑（預設關閉，REL-02）。schema 只為不分性別的兩對（ANCESTOR_OF／DESCENDANT_OF、TEACHER_OF／DISCIPLE_OF）保留反向；6.05 本來就會丟掉反向列 |

R2（yaml `prompt_signals` 的字面訊號規則，方向取自 id 順序）已在第 1A 批移除（REL-01）：每個候選對都進 R4，親屬的字面訊號改由 6.05 的錨定句型處理。2026-05 那次 run 的 relations.jsonl 仍含 R2 的規則列（772）與 R5 的反向列（752），由 6.05 丟掉。

### 指令
```bash
# 完整抽取（估 10-20 小時離線；支援 --resume）
uv run --project scripts python -m scripts.relation_extraction.extract_relations --resume

# priors only（無 LLM，適合快速驗證）
uv run --project scripts python -m scripts.relation_extraction.extract_relations --no-llm

# 限定 pericope 範圍 debug
uv run --project scripts python -m scripts.relation_extraction.extract_relations --limit-pericopes 30
```

### 輸出
- `output/relations.jsonl`（原始 triples，Step 6.05 的輸入）
- `output/relations_checkpoint.jsonl`（resumable state；`--resume` 讀此檔跳過已處理對）
- `output/relations_unclassified.jsonl`（LLM 回 NONE 的對，事後分析是否擴張 schema；也是已退役的 10.3 的輸入）

---

## Step 6.05: 關係後處理（第 1A 批起）

### 說明
Step 6 寫出各 phase 的全部產物：字母序規則列（phase 2）、priors（3）、LLM 列（4）、反向物化列（5）。第 1A 批之前 6.1 原樣匯入它們。6.05 夾在中間：離線（不連庫、不看 `KG_TARGET`），依固定順序跑一串清理規則，寫出 6.1 唯一接受的 `output/relations_clean.jsonl` 與報告 `output/relations_clean.report.json`。程式是 `scripts/relation_extraction/relation_postprocess.py`，句型與防護在 `config/relations/anchored_rules.yaml`。

### 輸入
- `output/` 的 relations.jsonl（W1 沿用 2026-05 的 6,958 列）、entities.jsonl、entity_mentions.jsonl、chunks.jsonl、pericopes.jsonl
- `config/curated/entity_overrides.yaml`（最終型別）、`config/relations/anchored_rules.yaml`、`config/relations/biblical_relations.yaml`
- 端點不在 entities.jsonl、某列沒有可辨識的 source、檔案讀不到，或規則跑完後同一個鍵還有兩列，都在寫檔之前停下（結束碼 1）

### 規則（依序；W1 實跑，輸入 6,958 列）
| 規則 | 動作 | W1 |
|---|---|---|
| drop_inverse | 丟 R5 的反向物化列 | −752 |
| rules_to_anchored | 丟 R2 的字母序規則列，換成錨定句型命中（見下） | −772；錨定唯一鍵 +328 |
| drop_llm_event_event | 丟兩端都是 Event 的 LLM 列（PRECEDED_BY、CAUSED：同段落探勘出的配對，多半是雜訊） | −38 |
| domain_range | 丟 schema 不接受的端點型別（以 entity_overrides 之後的最終型別判斷） | −13 |
| provenance_gate | 丟兩端沒有同時出現在出處段落的列。MENTIONS 取 10.2「但」過濾之後的狀態；prior、curated 豁免 | −1 |
| flag_id_order | id 序關係（CAUSED、LOCATED_IN、PRECEDED_BY、SUCCEEDED_BY）的 LLM 列標 `direction_verified: false`，與 prior 相反的丟掉 | 標記 48；與 prior 相反 −1 |
| resolve_kinship_direction | 同一對父母子女只留一個方向，依來源 curated > prior > llm > anchored_rule | 0 |
| dedup_undirected | 無向關係（SPOUSE_OF、SIBLING_OF、NEAR…）每對只留一列 | −6 |
| collapse_by_key | 每個 (head, relation, tail) 一列，各來源併進 `sources`、`support_pericopes`、`evidence_count` | 7 鍵由兩個來源合成 |
| stamp_provenance | 寫 run_id、model（LLM 列）、confidence_raw（錨定列為 null），刪掉 `confidence` | |

結果 5,696 列，主來源 llm 5,313、anchored_rule 319、prior 64。10.2 刪掉 16 個泛名詞 Event 時會帶走其中 80 條，所以圖上應有 5,616 條，邊集合 sha256 `661cfc62…`（報告的 expected_after_10_2）。

### 錨定句型與兩段同名防護
- 四個句型都在同一節內比對：P1「P 的兒子／女兒 C」、P2「C 是 P 的兒子／女兒」、P3「給 F 生 C」、P4「H 的妻 W」。方向由句型決定，不看 id 順序。兩端經該段落的 MENTIONS 解析成唯一的 Person，詞庫只用 Person／Place／Group 的名稱。W1 命中 701、輸出 465、唯一鍵 328。
- 第一段防護：子女已有 curated、prior 或 llm 的其他父母，或任一端是已知的同名節點（`guard.homonym_ids`：彼得、使徒約翰），就 abstain（W1 為 56 與 4）。第二段（`guard.disagreement`）只看第一段留下的錨定命中：同一個子女被給了兩個以上的父母，表示這個節點合併了同名的人（亞撒利雅有 11 個錨定父親），它的父母命中全數 abstain（W1 49 個子女、176 筆）。abstain 都記在報告的 conflicts。
- `enabled: false` 是事前登記的 K9 退路：K9 人工抽樣（`scripts/tools/kin_review.py`，閘門欄位 text_correct，Wilson 下界 ≥ 0.85；[第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §2.1）沒過才改。這時 6.05 照樣丟規則列，但不加錨定列，圖上應有 5,297 條（sha256 `bbc5c830…`），期望檔要用這個 sha 重產。

### 報告（relations_clean.report.json）
- pp_version（程式與設定檔的 sha256）、schema_version、rules（mode 與跑過的規則）、run_id（pp_version 加全部輸入的 sha256），以及每個輸入的 {path, sha256, rows}。
- flow：input、各規則的 drops（依關係型別）、drops_due_to_dan_filter、anchored（命中、防護、唯一鍵與其 sha256）、flagged、collapsed_keys、output；conflicts 是每一筆 abstain 與方向衝突。
- output：{path, sha256, rows, by_source, by_relation}。6.1 只匯入 sha256 與列數都對得上的檔。
- expected_after_10_2：10.2 刪除泛名詞 Event 之後圖上應有的邊（edges、edge_set_sha256、by_ee_key、by_type），10.6 的 check_edge_set 拿它比對 staging。

### 指令
```bash
# 全部規則 → output/relations_clean.jsonl 與 output/relations_clean.report.json
uv run --project scripts python -m scripts.relation_extraction.relation_postprocess

# 決定性：連跑兩次逐位元相同。輸出路徑要相同，因為報告記了 output.path；D 是 R0 的日期
mkdir -p bak/$D/pp_run1
cp output/relations_clean.jsonl output/relations_clean.report.json bak/$D/pp_run1/
uv run --project scripts python -m scripts.relation_extraction.relation_postprocess
cmp output/relations_clean.jsonl bak/$D/pp_run1/relations_clean.jsonl
cmp output/relations_clean.report.json bak/$D/pp_run1/relations_clean.report.json

# K8 的 staging-P1 對照組：不跑任何規則，6,958 列只蓋上 source、schema_version、pp_version。
# 寫到另一組檔，不覆寫 relations_clean；6.1 以 output/relations_p1.jsonl 匯入（報告取同名的 .report.json）
uv run --project scripts python -m scripts.relation_extraction.relation_postprocess --rules none \
  --out output/relations_p1.jsonl --report output/relations_p1.report.json
```
- 輸出只取決於輸入的位元組與程式（`PP_FILES`）：列依 (head_id, relation, tail_id) 排序、沒有時間戳，jsonl 與報告都先寫暫存檔再 rename。W1 實跑兩次：output sha256 `1c0cf064…`、pp-f22a025275cc、run_id 6.05-5f333ab72253，兩個檔都 cmp 相同。改到 PP_FILES 裡任何檔都會改變 pp_version、run_id 與 output sha256（邊集合不一定變）。
- 結束碼：0 寫出；1 輸入錯誤，什麼都沒寫；2 參數錯誤。

---

## Step 6.1: 匯入關係到 Neo4j

### 說明
把 6.05 的 relations_clean.jsonl 寫成 Entity↔Entity 邊，透過 APOC `apoc.merge.relationship` 建立動態邊型（FATHER_OF、RULED 等）。第 1A 批起：
- **只收 6.05 的產物**：連線之前核對報告（同目錄的 `.report.json`，或 `--report`）。檔案的 sha256 與列數要等於報告的 output，每列要帶報告的 pp_version 與 head_id、relation、tail_id、source，(head_id, relation, tail_id) 不可重複；不符就結束碼 2，什麼都不匯入。Step 6 的 relations.jsonl 沒有報告，一律拒絕。
- **只能緊接在 Step 5 之後**：語意層（MENTIONS、CROSS_REFERENCES 以外的 Entity↔Entity 邊）已經有邊時，結束碼 1、不寫入（訊息是 `Step 5 empties the graph`）。所以 6.1 不能在建好的圖上重跑，要重匯就從 Step 5 重建。`--replace` 只限 staging（source 過 staging.env 的 shell）：在同一個交易內先刪掉整個語意層（10.3 的邊也刪），再寫入檔案，供手動驗證用，標準鏈不帶。
- **不靜默略過**：先以一次讀取列出圖裡缺的端點，缺任何一個就結束碼 1、不寫入。全部列都在同一個寫入交易內，每個 statement 寫入的邊數必須等於送出的列數，否則整個匯入回滾（結束碼 1）。
- **邊屬性整組覆寫**：每條邊的屬性就是檔案那一列扣掉 head_id、relation、tail_id、去掉 null 值，新邊舊邊都一樣。舊版只在 ON CREATE 寫屬性，舊匯入的屬性會殘留在既有的邊上（REL-10）。

### 輸入
- `output/relations_clean.jsonl` 與 `output/relations_clean.report.json`（from Step 6.05）

### 邊屬性
- `source`、`sources`、`run_id`、`pp_version`、`schema_version`、`extraction_phase`、`evidence_span`、`evidence_count`、`support_pericopes`、`source_pericope_id`、`head_canonical`、`tail_canonical`、`notes`
- prior 與 LLM 列有 `confidence_raw`（Step 6 原本的 confidence；錨定列沒有），LLM 列有 `model`，錨定列有 `verse`，id 序關係的列有 `direction_verified`（LLM 列 false，prior 列 true）。不再寫 `confidence`。

### 指令
```bash
uv run --project scripts python scripts/import_relations_neo4j.py   # 預設讀 output/relations_clean.jsonl
```

### 結果
- W1：5,696 條、35 種關係型別；10.2 之後 5,616 條（10.6 的 check_edge_set 比對）
- 結束碼：0 匯入（或檔案是空的）；1 已有語意層（沒帶 `--replace`）、缺端點或寫入數不符，什麼都沒寫；2 沒有輸入檔或契約拒絕，都在連線之前

---

## Step 7: Entity 描述補完（產生與 replay）

### 說明
Person/Place/Group 三類 entity 中有 ~4,223 個 `description` 欄位空白（Object/Event/Theme 的 description 來自 Step 1；Event 的多半只是正文擷取，1,005 個剛好 100 字）。使用較小的 gemma4 系列模型（描述生成不需要 31B）為這些 entity 從其 mentioning pericope titles 推導 ≤80 字 grounded description。模型由 `DESC_OLLAMA_MODEL` 控制：現行 `.env` 為 `gemma4:26b-a4b-it-q8_0`；code fallback 為 `gemma4:e4b-it-q8_0`（11GB，原始 run 所用）。

產生的描述只寫進 Neo4j（Step 8 再帶進 Qdrant payload），不在任何 JSONL；PG 的 `entities.description` 對 P/P/G 是 0/4,223，所以 /api/v1/entity 回傳的描述一律是空字串（PG 同步排在第 1D 批）。Step 5 清庫重建後描述必然消失，因此第 0 批起改成快取：
- 產生模式每接受一條描述，就先附加到 `output/frozen/descriptions.jsonl`，再寫回 Neo4j。每行記錄 entity_id、description、model、temperature（固定 0.2）、prompt_version（prompt 內容雜湊）、titles_sha、quality_flag、git_commit（HEAD，工作樹有改時加 `-dirty`）、generated_at（計畫 §3.1）；
- 快取的種子是 live 現有的描述（3,045 條 P/P/G，加上 E/O/T）：R0（見 [staging_promotion.md](staging_promotion.md)）由 `scripts/tools/export_live_state.py`（唯讀）匯出到 `output/frozen/live_state/<YYYYMMDD>/descriptions.jsonl`，再以 `--promote` 複製成正式快取 `output/frozen/descriptions.jsonl`。種子不知道當初的生成參數：temperature 是 null，model、prompt_version、git_commit 是 `live_export_unknown`；
- 重灌鏈用 `--replay` 從正式快取寫回 Neo4j，不呼叫 LLM。快取以 (entity_id, titles_sha) 定址：實體目前的標題集合雜湊對不上任何快取條目時，回報為 stale、不寫回，留到第 2B 批重生。快取裡有、圖裡沒有的實體回報為 missing。
- **replay 排在 10.5 之後**：種子的 titles_sha 是用 live 的 MENTIONS 算的，也就是 10.2 刪掉「但」的誤命中、10.4/10.5 補上 curated 邊之後的狀態。放在 6.1 之後會讓 place:dan、person:yeteluo 判為 stale，而 10.5 對 extracted 節點不寫描述，兩條描述就永久遺失（scripts/tests/test_export_live_state.py 模擬了兩種順序）。
- replay 是閘門：每次都把 written、stale、missing 寫成 JSON 報告（`--report`，預設 `output/frozen/replay_reports/replay_<時間>.json`；stale 附目前的標題與快取裡的 titles_sha），`--fail-on-stale` 在 stale 或 missing 不是 0 時結束碼 1。相符的列照樣寫回（冪等）。
- **第 1A、1B 批（W1）不改 MENTIONS**（10.3 退場只少了共現邊），stale 與 missing 都必須是 0：`--fail-on-stale` 結束碼不是 0 就停下查，不走下一項的核可流程。
- **會刻意改動 MENTIONS 的批次（1C、1D）**：標題集合變了，stale 是預期的，鏈會停在 Step 7。處理：(1) 讀這次的報告，逐筆確認 stale 與 missing 都落在該批預期改動的實體內（stale 條目附目前的標題與兩個 titles_sha；missing 只能來自刻意的刪除或改 id）；(2) 把清單與報告路徑列進該批紀錄並核可；(3) 確認後不帶 `--fail-on-stale` 重跑 Step 7（相符的列第一次就已寫回，重跑只是讓這一步以結束碼 0 留下報告），再接 8b。stale 的實體保留 Step 5 匯入的描述（P/P/G 是空的），留到 2B 重生；它們與 live 的描述差異逐條列進該批的 diff_kg 允許清單（`config/kg_diff_allow_<批次>.yaml` 的 `descriptions` section，見 [staging_promotion.md](staging_promotion.md) R2）。名單外的 stale 一律當退步查。
- 兩種模式在連線前都呼叫 `kg_target.assert_target("neo4j")`（見 [staging_promotion.md](staging_promotion.md)「執行前檢查」）。

### 前提
- Step 5 完成；重灌鏈中還要 10.1、10.2、10.4、10.5 完成
- 產生模式：Ollama 已 pull `DESC_OLLAMA_MODEL` 指定的模型（見 Checklist 0.4）；replay 模式：快取檔存在（預設 `output/frozen/descriptions.jsonl`，可用 `--cache` 或 `DESC_CACHE_PATH` 改）

### 指令
```bash
# 重灌：從正式快取 replay（不呼叫 LLM；先加 --dry-run 只分類、只寫報告）
uv run --project scripts python -m scripts.relation_extraction.desc_generator --replay --fail-on-stale

# 產生：預設處理 Person、Place、Group（呼叫 LLM）
uv run --project scripts python -m scripts.relation_extraction.desc_generator

# 限定類型 + dry-run（不寫 Neo4j）
uv run --project scripts python -m scripts.relation_extraction.desc_generator \
  --target-types Person,Place \
  --dry-run

# 限量（debug）
uv run --project scripts python -m scripts.relation_extraction.desc_generator --limit 100
```

### 輸出
- 寫回 Neo4j `Entity.description` 欄位
- 產生模式另寫入 `output/frozen/descriptions.jsonl`；replay 模式寫 `output/frozen/replay_reports/`
- 產生模式的失敗者跳過（log warning），不阻擋整體流程

---

## Step 8: Entity 向量化

### 說明
為每個 Entity 生成 BGE-M3 1024 維向量，寫入新 Qdrant collection `bible_entities`，啟用模糊實體查詢（例：「亞伯拉罕的兒子」→ 命中 Isaac entity）。文字組合 `{name}({aliases})。{description}。常見於：{titles}`，截斷 200 字以避免 text embedding collapse。

### 前提
- Step 5 完成
- **Step 7 要在前面**（Person/Place/Group 若 description 為空會降低嵌入質量）。重灌鏈因此跑兩次：8a 在 10.x 之前（只為建 collection），8b 在 Step 7 之後（最終向量）

### Collection 設計
- `bible_entities`（1024 維 BGE-M3，COSINE distance）；名稱取自 `QDRANT_ENTITY_COLLECTION`，與 backend 設定 `qdrant_entity_collection` 同名。staging 寫入 `bible_entities_vN`（見 [staging_promotion.md](staging_promotion.md)），10.2/10.4/10.5 的 Qdrant 同步也跟著這個變數走
- 第 1 批 W1 的 staging collection 是 `bible_entities_v3`（建議，待 Kay 確認）：W1 的 R0 把 `scripts/tools/staging.env` 從 v2 遞增到 v3，第 0 批的 v2 留作對照，8a、8b 的 `--recreate` 只動 v3。v3 要與 `bible_entities_detB` 逐點相同，見 Step 10.6
- payload：`{entity_id, type, canonical_name, aliases, description, pericope_titles, pericope_ids}`
- point id：由 `entity_id` 經 UUID5 衍生（idempotent upsert）

### 指令
```bash
# 標準
uv run --project scripts python scripts/embed_entities.py --batch-size 64

# GPU 加速
uv run --project scripts python scripts/embed_entities.py --batch-size 64 --device cuda

# 重建 collection（清掉舊向量）
uv run --project scripts python scripts/embed_entities.py --recreate
```

### 結果
- Points: ~9,120（每個 entity 一個 vector）
- 後續 backend `entity_path_retriever.retrieve_by_entity_query()` 讀此 collection

---

## Step 9: TSK 串珠交叉引用匯入

### 說明
將 Treasury of Scripture Knowledge（19 世紀公版串珠註解）的 verse 級交叉引用映射到 Pericope 層，匯入 Neo4j `CROSS_REFERENCES` 邊。2026-07 的 P0 把串珠從 916 條擴充到 250,418 條（tsk 249,502、markdown 774、supplementary 142）；第 1B 批之後是 250,366 條。

- **寫入語意（第 1B 批起）**：每個 TSK 段落對都無條件 SET `votes`（該段落對的最大社群投票數）、`verse_pairs`、`tsk: true`，包括 Step 5 已寫成 curated 的段落對（保留它的 `source` 與 `curated`）。新建的邊是 `source: 'tsk'`、`curated: false`。所以同一個段落對可以同時是 curated 與 TSK。舊碼只在 ON CREATE 時寫 votes，與 curated 重疊的段落對拿不到 TSK 證據，匯入卻照樣顯示成功（XREF-4）。
- **backend 怎麼分權**：讀 `r.curated`（`neo4j_db._CURATED_XREF`）。過渡期沒有旗標的邊以 `source IN ['markdown', 'supplementary']` 推斷；W2 在 prod 的 H8.unflagged 為 0 之後縮成只讀 `r.curated`。curated 邊的權重是 0.75/0.55，TSK 邊是 0.60/0.50。舊 backend 以 `coalesce(r.votes, 999)` 判斷：votes ≥ 999 的 3 條 TSK 邊因此被當成 curated（XREF-3）；新資料裡 924 條 curated 邊帶了 votes，舊 backend 會把它們當成 TSK。**所以先上 backend、後上資料**，載入資料前先用 deploy-guard 確認，見 [staging_promotion.md](staging_promotion.md) R3。

### 前提
- Step 5 完成，而且是用第 1 批之後的 Step 0 輸出建的：每條 curated 邊都要有旗標
- `output/embedding_queue.jsonl` 存在（verse→pericope 反查表，31,102 節全覆蓋）
- 原始資料 `output/cross_references_tsk.txt`：**不進 git**（`output/` 被 ignore），fresh clone 需自 [scrollmapper/bible_databases](https://github.com/scrollmapper/bible_databases) 下載 openbible.info 的 cross_references.txt（CC-BY）

### 指令
```bash
# 先 dry-run：映射率、旗標前置條件、supplementary 支撐閘門都會跑，不寫入
uv run --project scripts python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt --dry-run

uv run --project scripts python scripts/import_tsk_crossrefs.py output/cross_references_tsk.txt
```

### 閘門（第 1B 批起；任一不過就結束碼 1）
- **寫入之前**（`--dry-run` 也跑；只用 READ session，一個 MERGE 都不送）：
  - 旗標前置條件：CROSS_REFERENCES 中 `curated` 或 `tsk` 未設的邊必須是 0。第 1 批之前建的圖（例如第 0 批的 staging）一律拒絕，不會寫一半。
  - curated 邊至少一條。Step 5 找不到 `neo4j_relationships.jsonl` 時不會失敗，只是一條交叉引用都不建；這時照跑 Step 9 只會建出 250,358 條純 TSK 邊，attached_to_curated 是 0，寫入後的計數閘門照樣全過。所以 `Before:` 一行是 `(0 curated)` 時一律拒絕，要先重跑 Step 5。
  - supplementary 節級支撐，只認同向：圖上每個 supplementary 錨點都要有一筆 TSK，從錨點的某個來源節指向某個目標節（定義的方向）。只有反向支撐或完全沒有支撐的錨點，除非列在 `supp_tsk_exempt_anchors`，否則逐筆印出兩個方向的最大 votes。用節級而不用段落級，是因為段落級連 XREF-2 刪掉的錯誤定義都「有支撐」。W1 印出 `supplementary anchors: 162 on 158 edges, tsk_exempt 0`，162 個錨點全部有同向支撐。
- **寫入之後**：matched 等於 TSK 段落對數、count(tsk) 等於段落對數、count(tsk 且 curated) 等於 attached_to_curated、旗標未設的邊為 0。

### 結果
- 344,799 行 → 過濾負 votes（1,166）與自環（9,811）→ 250,358 條 unique pericope 對（僅 7 條 unmapped）
- 第 1B 批之後（W1 預期，由 `xref_probe.py expect` 從 Step 0 輸出離線重放）：印出 `After: created 249,434, attached_to_curated 924, matched 250,358`。CROSS_REFERENCES 共 250,366 條：curated 932 條（924 條同時是 TSK，8 條 markdown 沒有 TSK 證據），純 TSK 249,434 條。
- 第 1B 批之前：有 856 對與 curated 邊重疊而沒有寫上 votes，live 的 tsk 邊是 249,502 條（250,358 − 856），而且沒有任何邊帶旗標。
- **指紋與連跑兩次**：最後一行印 `fingerprint: <sha256>`，以每條邊的 (a, b, votes, verse_pairs, curated, tsk) 依 (a, b) 排序後計算，與寫入順序無關；W1 是 `e522411e…`。Step 9 沒有 refresh 模式，重灌時緊接著再跑一次：第二次必須印出 `created 0` 與同一個指紋。接著跑 `xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json`，結束碼必須是 0（期望檔在 W1 第 2 步之前登記，重建時只重算比對，見 [staging_promotion.md](staging_promotion.md) R2「W1 的交叉引用檢查」第 1 項）。curated 邊的清單屬性（`curated_sources`、`md_ref_texts`、`md_anchors`、`supp_anchors`、`supp_ref_types`、`supp_descriptions`、`supp_tsk_exempt_anchors`）不在指紋內。這些清單的內容只由 Step 0 的 validate_output 在 JSONL 上驗證，Step 5 以 `SET r += props` 原樣寫入；圖上的 R4 只看 supp_anchors 是否對齊，H8 只看 curated_sources 是否非空。
- **回滾**：從 Step 5 重建（Step 5 清庫，再依「執行順序」跑完後面各步）；production 則照 [staging_promotion.md](staging_promotion.md) R5 載回 dump。不要用 `source: 'tsk'` 或 `tsk` 旗標刪邊：curated 邊也帶 `tsk: true` 與 votes，照謂詞刪會刪錯邊，或只刪掉一半的證據。

---

## Step 10: KG 修復與 curated 資料重放（重建後必跑）

### 說明
P0（2026-07-06）與排序層修復產生的 curated 資料**不在 Step 1–9 的 JSONL 產物中**：字典 aliases、噪音清理、18 個頭部 Event 節點、106 條手動 MENTIONS 邊。P0 的共現關係搶救（10.3）已在第 1A 批退出預設鏈，見下方指令。任何全量重建（重灌三庫）後若不重放此鏈，圖譜停在 P0 前狀態，檢索端依賴的資料（alias 查詢、curated Event 錨點、keyword-exact pin 的橋）會缺失。

**不需重跑**：`backfill_verse_mentions.py` — 其 verse→pericope remap 已內建於 `import_neo4j.py`（Step 5 匯入時自動處理）。

### 前提
- Step 1–6.1、8a、9 完成（W1 以 check_merged_inputs 取代 Step 1；Step 7 與 8b 排在 10.5 之後）；`QDRANT_ENTITY_COLLECTION` 指向的 entity collection 已由 8a 建好：10.2（staging 下）刪點、10.4 upsert 對不存在的 collection 都會失敗，10.5 找不到 extracted 點會 SystemExit
- 只有 legacy 的 10.3 讀 `output/relations_unclassified.jsonl`（Step 6 產物）
- `config/curated/manual_graph_patches.jsonl`（git-tracked，106 邊/6 節點快照，10.5 的輸入）
- `config/curated/entity_overrides.yaml`（git-tracked，10.2 yehehua 改成的型別取自此檔；碰任何庫之前先驗證，格式不對就中止）

### 指令（依序執行；每個腳本支援 `--dry-run` 預檢）
```bash
# 10.1 字典 aliases 直灌（38 節點；原生 LIST，backend alias 查詢的前提）
#      只寫 Neo4j
uv run --project scripts python scripts/backfill_aliases.py

# 10.2 噪音清理（「但」子字串誤命中 gate、16 泛名詞 Event 刪除、耶和華 Group→Person，型別讀 entity_overrides.yaml）
#      同步範圍不是三庫：「但」只刪 Neo4j 的 MENTIONS（PG entity_mentions 仍有 place:dan 1,882 列，
#      Qdrant 不動）；generic-events 與 yehehua 才同步 PG 與 Qdrant。KG_TARGET=staging 下：碰 Neo4j 之前先確認 PG 兩張表與
#      entity collection 都在，同步失敗就中止，修好後以同一組 --actions 重跑會補完同步；production 照舊只印警告並跳過。
#      第 1C 批把「但」的判斷移進 NER 之前，「但」在這裡仍是真的刪除
uv run --project scripts python scripts/cleanup_noise_entities.py

# 10.3 已退出預設鏈（第 1A 批，D2）：共現升格，嚴格精確率約 0.2，而且晚於 6.05，出處閘門管不到。
#      不帶旗標時結束碼 2、不連庫。只有 K8 的 staging-P1 對照組與重現論文數字才跑（原本 +5,641 PARTICIPATED_IN、
#      +3,419 OCCURRED_IN；寫入 source 'cooccurrence'、extraction_phase 7）：
# uv run --project scripts python scripts/backfill_event_relations.py --legacy-cooccurrence

# 10.4 頭部 Event curated 補灌（11 個既有 Event 灌問法別名 + 18 curated 節點/56 邊；三庫同步）
uv run --project scripts python scripts/backfill_head_events.py

# 10.5 手動圖邊 patch 重放（106 MENTIONS 邊 + 受難週/大使命節點；三庫同步，語意見註記）
uv run --project scripts python scripts/backfill_manual_patches.py --apply
```

### 順序依據
- 語意邊全部由 6.1 匯入，6.05 事先就以 10.2 之後的狀態判斷：provenance_gate 用 10.2「但」過濾後的 MENTIONS（同一份 geo_rules），擋掉只靠「但」誤命中支撐的列（W1：NEAR 1）；expected_after_10_2 預先扣掉 10.2 刪除泛名詞 Event 時帶走的 80 條。10.2 對 place:dan 只刪 MENTIONS，不刪節點與衍生邊。第 1A 批之前的「但」孤兒邊（370 條 OCCURRED_IN）來自 10.3：它讀 2026-05 的 relations_unclassified.jsonl 快照、不查 live MENTIONS，調整順序擋不住，所以根治靠 6.05 的閘門與 10.3 退場（計畫 §3.3）。
- 10.4/10.5 依賴 entity collection（8a）與 PG entities 表（Step 3）；10.5 放最後 — 其快照導出自 10.4 之後的線上狀態。
- Step 7（replay）在 10.5 之後、8b 在 Step 7 之後：理由見「執行順序」與 Step 7。

### 註記
- 若重跑 `extract_entities.py`：`pericope_miner.py` 的 `GENERIC_TITLE_STOPLIST` 只在 pericope 標題候選（Phase 1）生效，而且與 10.2 的 `GENERIC_EVENT_STOPLIST` 是同一組 24 個詞的兩份定義。其他 phase 產生的同名泛名詞 Event 擋不住，所以 10.2 的 generic-events、dan、yehehua 三個動作都仍然必要。另有 37 個非標題來源的泛名詞或地名 Event（瘟疫、瑪拉、瑪撒、米利巴、耶和華曉諭…）兩份停用詞都沒有收，留給第 1D 批。重抽一律走 `--stage ner` 加 `--stage merge`；`--ner-only` 會丟掉整個 grounded 半邊（見 Step 1）。
- 各步驟的執行細節、發現與回滾指令：[records/2026-07-06_kg_p0_execution.md](records/2026-07-06_kg_p0_execution.md)（10.1–10.3）、[records/2026-07-06_kg_fixes_execution.md](records/2026-07-06_kg_fixes_execution.md)（10.4）、`scripts/backfill_manual_patches.py` docstring（10.5）。
- 10.5 的語意（第 0 批起）：
  - 每個節點列都用 `apoc.coll.toSet` 把 patch 的 aliases 合併進節點，排除與 canonical 相同的值（EV-06：山上寶訓與兩個保羅敘述歸主事件的 registry 觸發詞只來自這裡；舊版只在 ON CREATE 寫，重建後 registry 從 33 掉到 31）。
  - 只建 origin=manual 的節點。extracted id 不在圖中時，任何寫入前就硬失敗：這代表抽取改了 id 或丟了節點，要改 patch，不可補建（ID-7）。
  - PG 與 Qdrant：manual 列整列 upsert／重嵌；extracted 列只同步 aliases，不碰 description 與向量。extracted 列在 PG 或 Qdrant 缺席時，同樣在任何寫入前失敗（以 `--skip-pg`／`--skip-qdrant` 略過的庫除外；`--dry-run` 也會檢查）。
  - `--export` 也遵守 `--dry-run`。`--apply` 的備份 `output/backups/manual_patches_<ts>.jsonl` 為每個節點記下執行前的 aliases：Neo4j（`aliases_before`）、PG、Qdrant（原始 payload 值），回滾用。

### 10.6 品質閘門（第 0 批新增）
export_event_registry `--check`（鏈的最後一步）之前的關卡：
```bash
# KG 品質門（計畫 §3.6）：0 通過；1 硬失敗，或有檢查 error／unmeasured（沒跑成的檢查不算通過）；2 ratchet 退步
uv run --project scripts python scripts/validate_kg.py --live --target staging

# 三庫身分一致（id、type、canonical、aliases、description 全部列出）；--fail-on id：只有 id 集合有差、或有庫沒讀到時結束碼 1
uv run --project scripts python scripts/check_identity.py --target staging --fail-on id
```
- 兩項都在 source 過 staging.env 的 shell 跑：`--target staging` 只讀 shell 的變數（不讀 .env），解析到 production 的庫會拒絕；Qdrant 沒有 staging 預設值，沒設 `QDRANT_ENTITY_COLLECTION` 時 H5 判 unmeasured、check_identity 判「庫被略過」，都是結束碼 1。從零鏈（沒有 staging 的機器）兩項都改用 `--target prod`，而且要在乾淨的 shell 跑（見 [staging_promotion.md](staging_promotion.md) R4）。
- **第 0 批的判準**。等價重建刻意保留 live 的狀態，所以不會全綠；預期差異要逐項列進該批的紀錄，不可直接 ratchet：
  - validate_kg：hard（H1、H2、H7）全過；結束碼 2 只能來自事先列出的退步。已知 R1 從基準 1,938 升到約 2,124（以 output/ JSONL 投影實測；verse remap 後 start_pos=0 從 1,785 變 1,947）。「但」的 370 條孤兒邊仍會被 10.3 重新產生（H3 到第 1A 批才是硬門檻）；mention_count 也會變。
  - check_identity：`--fail-on id` 結束碼 0，即三庫 id 集合差為 0。其餘欄位的差異在第 1D 批前屬正常：PG 的 P/P/G description 全空（Step 3 早於 Step 7；live 為 3,045 筆）、PG aliases（部分 10.x 補的 aliases 只進了 Neo4j；live 為 14 筆）。staging 的 Qdrant 預期 0 差異（8b 從 Neo4j 重讀，aliases 是原生 list），但 live 的 Qdrant aliases 是 JSON 字串（9,093 筆），所以 staging 對 live 的比對在這裡會不同，同樣屬正常。
- **第 1A 批起的硬門檻：H3、H9、H11、R6**（關係），加上第 0 批的 H1、H2、H7、D1。
  - H3（沒有共現支撐的衍生邊）、H9（domain/range 違規）是 0；H11 的 source_null、inverse_edges、cooccurrence_edges、rule_edges、llm_event_event_edges、unflagged_id_order_edges、undirected_pair_duplicates 都是 0；R6 的 probe_failures、contradictions、female_head 是 0，failing_probes 是 `[]`。R6 的函數性指標（functional_violation_rate 與全部父母編碼的多父母計數）仍是 record ratchet。
  - W1 預期（以 validate_kg 對 6.05 輸出的離線投影實跑）：以上全為 0；R6 的 functional_violation_rate 0.0638（基準 0.5357）、children_with_2plus_nonfemale_parents 8（基準 135）、children_with_gt2_parents 1（基準 87）；PROBES 的 failing 剩 7 個 id，都在基準的 13 個之內（subset 規則，不算退步），1A 新增的探針全過。升版前的 prod 是 H3 374、H9 14、H11.source_null 15,926，所以 1A 同樣只驗 staging。
  - 結束碼 1 一律不接受；結束碼 2 只能來自 R1（第 0 批的殘差，W1 不改 MENTIONS）。在 staging 的 shell：
    ```bash
    uv run --project scripts python scripts/validate_kg.py --live --target staging --json > bak/$D/validate_staging_w1.json
    jq -e '.failures == [] and .regressions - ["R1"] == []' bak/$D/validate_staging_w1.json
    jq -e --slurpfile e config/kg_expect/batch1_w1/residuals_expected.json \
      '.checks.R1.metrics.book_region_mentions.value == $e[0].validate_kg.R1.b' bak/$D/validate_staging_w1.json
    uv run --project scripts python scripts/tools/check_edge_set.py --target staging --expect config/kg_expect/batch1_w1/relations_expected.json
    ```
    兩個 jq 都要結束碼 0：沒有失敗、退步只有 R1，而且 R1 等於事前登記的殘差（`residuals_expected.json`，2,124）。mention_count 的 4 筆殘差由 R2 的 diff_kg 比對，合併允許清單的 mention_count 只取自 `residuals_allow.yaml`。
  - check_edge_set 結束碼 0：staging 的語意層等於 6.05 報告扣掉 10.2（5,616 條，sha256 `661cfc62…`；ee 鍵 prior 22、llm 35、anchored_rule 4），也等於事前登記的 `relations_expected.json`。第 0 批的 staging 是 15,926 條，結束碼 1。
  - 6.05 連跑兩次逐位元相同（Step 6.05 的 cmp）。
  - entity collection（建議，待 Kay 確認）：W1 不改實體、MENTIONS 與描述，所以 8b 寫出的 `bible_entities_v3` 必須與 W1-0 用同一份 embed 程式建的 `bible_entities_detB` 逐點相同（point id、向量、payload；比法同 [W0 紀錄](records/2026-10-05_kg_batch1_w0_results.md)「補記：W1-0 opt-in 決定性」）。通過後 detB 可以刪。
- **第 1B 批起的硬門檻：H8、R4、R11**（交叉引用）。
  - H8：`no_provenance`（curated 與 votes 都沒有）、`unflagged`（curated 或 tsk 任一未設）、`flag_mismatch`（curated 與 curated_sources 是否非空不符，或 tsk 與 votes 是否存在不符），target 都是 0。
  - R4：source 或 curated_sources 含 supplementary 的邊，逐個錨點判定。`misaligned` 是任一錨點某一端的第一節不在端點段落的 verse_range；`misaligned_any_verse` 是任一節不在；`unparsed` 是錨點或段落讀不了。target 都是 0。沒有錨點的邊（1B 之前建的圖）退回讀舊欄位 source_verses/target_verses。
  - R11：`tsk_votes_edges`（votes 不是 null 的邊）是 equal、target 250,358；`tsk_flag_without_votes`（tsk 為 true 而 votes 是 null；Step 9 會同時寫 tsk 與 votes）的 target 是 0。250,358 綁定目前的 TSK 檔與段落切分，第 2D 批要重新 `--accept R11`。
  - W1 預期（由 Step 0 輸出與 TSK 離線投影）：H8 0/0/0；R4 0/0/0，158 條邊、162 個錨點都讀錨點；R11 250,358/0；kg_probes 的 14 個 xref 探針全過。升版前的 prod 是 H8 916/250,418/0、R4 59/62/0、R11 249,502/0，對 prod 跑完整閘門必然結束碼 1，所以升版前只驗 staging（[第 1 批計畫](records/2026-10-04_kg_batch1_plan.md) §2.1）。基準的 value 在實作期間不 ratchet，R4 之後才與允許清單放在同一個 commit 裡 ratchet 或 `--accept`，見 [staging_promotion.md](staging_promotion.md) R4。
- staging 對 live 的等價比對（E–E 各 phase 的邊數、描述逐字比對等）用 `scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_<批次>.yaml`（唯讀），與上面兩項相反，**必須在沒有 source staging.env 的乾淨 shell 跑**，見 [staging_promotion.md](staging_promotion.md) R2。

### export_event_registry（registry 匯出）
`scripts/export_event_registry.py` 從 Neo4j 讀 curated 事件（backfill_head_events.py 的 ALIAS_INJECTIONS 與 NEW_EVENTS，以及 manual_graph_patches.jsonl 的 Event 節點）的名稱、aliases 與錨點，寫成 `backend/data/event_registry.json`。線上預設 `graph_strategies=["event_registry"]` 只讀這個燒進 image 的靜態檔，不讀 Neo4j；所以重建只要讓這個檔案的內容變了，線上 QA 就會變。

```bash
uv run --project scripts python scripts/export_event_registry.py --check   # 只比對（重灌鏈最後一步），不寫檔
uv run --project scripts python scripts/export_event_registry.py           # 重寫檔案
```
- 重灌鏈的最後一步：由目標圖重算的 registry（觸發詞、錨點等，generated_at 除外）必須與 backend/data/event_registry.json 相同（現為 33 個事件），結束碼 0 就不必重寫（重寫只會改到 generated_at）。validate_kg 的 D1 也跑同一個 `--check`。
- 只有刻意改 registry 的批次（第 2C 批）才不帶 `--check` 重寫。git diff 必須人工核可；檔案由 Dockerfile COPY 進 image，要 `docker compose up -d --build backend` 才會上線（只 restart 會跑舊檔）。
- 讀 `NEO4J_URI`，對 staging 執行時讀的是 staging 圖；除非該批的目的就是改 registry，否則不要在 staging 上重寫 repo 裡的 registry。不帶 `--check` 時會寫入 git 追蹤的檔案，沒有 `--dry-run`；要預覽就用 `--check`。

---

## Staging 與升版流程

> 整章已移到 [staging_promotion.md](staging_promotion.md)（2026-10-04 拆出，內容未刪減）。依據是[計畫](records/2026-10-04_kg_data_layer_fix_plan.md) §3.5、§3.7（D1：staging 全量重建後升版，不做線上增量補丁）。每批升版都走 R0 → R1 → R2 → R3 → R4，出事走 R5；**第 0 批只做 R0、R1、R2**，不升版。

| 節 | 內容 |
|---|---|
| 拓撲 | production 與 staging 的 Neo4j、PG、Qdrant、backend 對照；`docker-compose.staging.yml` 的 neo4j-staging、backend-staging |
| 環境變數契約 | 腳本只從環境變數讀連線設定；`scripts/tools/staging.env` 的值；各腳本的連線盤點表 |
| 執行前檢查 | 每次在 staging 跑寫入步驟之前：`source scripts/tools/staging.env`，再跑 `kg_target.py --require-staging neo4j postgres qdrant`，結束碼 0 才往下走 |
| R0 備份 | `git tag`、三庫備份、PG 兩張實體表的 plain SQL、LLM 產物與 NER 半邊打包（`llm_artifacts.tgz`） |
| R1 staging 建置 | 起 neo4j-staging、建 `bible_rag_staging`，再依本檔「執行順序」的重灌鏈執行；各步實測耗時 |
| R2 驗證 | Step 10.6 判準、diff_kg（乾淨的 shell）、各批的驗證門檻、backend-staging 評估 |
| R3 升版 | Neo4j dump／load、PG 換表、Qdrant collection 切換、`docker compose up -d --build backend` |
| R4 升版後檢查 | 在沒有 source staging.env 的 shell 跑 `--target prod` 的檢查，抽查 /api/v1/entity |
| R5 回滾 | Neo4j dump、R0 的 `entity_tables.sql`、collection 名切回、`git revert` |
| 收尾 | 停掉並移除 staging 容器、資料庫與 volume |

---

## 資料庫啟動指令

> ⚠ fresh clone 首次建庫請改用「從零重建 Checklist」0.3 —— backend 需等管線跑完最後啟動，否則 bind-mount 會把 `output/bm25_vocabulary.json` 建成目錄。

```bash
# 啟動所有資料庫
docker compose up -d

# 停止資料庫
docker compose down
```

staging（見 [staging_promotion.md](staging_promotion.md)）一律指名服務：
```bash
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d neo4j-staging
docker compose -f docker-compose.yml -f docker-compose.staging.yml up -d backend-staging   # R2 才需要
```

### 服務端點
| 服務 | 端點 |
|------|------|
| PostgreSQL | localhost:5432（staging：同一實例，資料庫 `bible_rag_staging`） |
| Qdrant | http://localhost:6333/dashboard（staging：同一實例，collection `bible_entities_vN`） |
| Neo4j | http://localhost:7474（staging：http://localhost:7475、bolt://localhost:7688） |
| backend | http://localhost:8000（staging：http://localhost:8001） |
