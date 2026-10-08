# 資料與 KG 分層重建：交接（2026-10-08）

新 session 從這份文件開始。重建管線的操作手冊是 `docs/rebuild_pipeline.md`。設計書與稽核報告在 store：`/mnt/ollama-data/bible_rag_store/reference/DESIGN.md`（v1.1）、`REPORT.md`。

## 1. 背景與 Kay 的決定

- 2026-10-07 做了全面稽核：69 組問題經複核成立，46 組根因在設計層。最嚴重的是：
  - 語料：轉換器丟了 268 節、4,446 字，以及 116 篇詩篇篇題；
  - KG：沒有身分層；
  - 語意邊：精確率約 0.25。
- 決定採**分層重建**：所有資料都從 66 卷 PDF 重建；W1 不升版；補丁路線（W2 以後）停止。
  - 注意：PDF 版權頁寫「新標點和合本」，實際內文是和合本修訂版（RCUV）。
- 範圍與精簡原則：
  - KG 先做 L0（名稱）與 L1（事件）。L2 身分層、L3 規則關係層，要看 5 卷 pilot 的結果再決定。
  - TSK 不載入。
  - 授權、repo 私有化、機外備份都不做：repo 維持 PUBLIC，Kay 的專案非商用。
  - 不需要的舊資料直接刪；流程盡量精簡，不搞簽核儀式。
- 已裁決的事項：
  - errata 25 處全部套用。原本無法判定字形的 6 處，Kay 選了灶、蔥、麅、虻、敕。`text_pdf` 保留 PDF 原字，`text` 用正字。
  - GT v2 的 kay_review：VL_020 改成「重新得力」；VL_001 題目不改；PERSON_013 是評分器問題，只記錄。
  - 設計書 D 編號的定案：D-03(b)、D-04(a)、D-05(a)、D-07(a)、D-08（`/api/v1/entity` 回 410）、D-09（R1 不載入 Neo4j）、D-10(a)、D-11(a)、D-12(a)。

## 2. 現況

### 程式

| 項目 | 內容 |
|---|---|
| 整合分支 | `rebuild/main`（worktree `~/Bible_RAG-rb`），四套測試全綠：ragdata 加 packages 2,361、backend 186、scripts 1,588、evaluation 380 |
| 主 checkout | 仍在 `feat/graph-strategy-gating`，這次沒有改動。`rebuild/main` 還沒併進 main，也還沒 push |
| `packages/ragcommon/` | ids、books、refs、versification、encoder（釘版 tokenizer 與探針） |
| `ragdata/` | 契約、閘門、S0–S7、K0/K1/K4、GT v2、release、loader、verify、promote、unload，以及總入口 `pipeline run` |
| backend | R1 版：讀 `rag_meta.serving` 選 build，有 strict 握手；sparse 已退役；查詢端 tokenizer 已修正；只保留預設路徑；`/api/v1/entity` 回 410 |
| evaluation | 支援 GT v2（`--gt v2`）與 slot 覆蓋；結果 meta 記錄 build_id、gt_version、gt_sha；兩臂 GT 不同時拒絕比較 |

- 測試跑法見 `docs/rebuild_pipeline.md`。
- backend venv 沒有 pytest，要用 `PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim`。

### 資料（store `/mnt/ollama-data/bible_rag_store/`）

- 現行 release 是 `b20261008_6daa4f31`。各層版本：
  - src@6a2ece2277ff
  - text@247eafe44b02
  - struct@d8d432b4df15
  - emb@ae5525447eda
  - kg0@14e68c8344b1
  - events@904becb6ccd9
  - route@5c397e2df007
- 關鍵計數：
  - 31,021 個 unit，其中 70 個合併節；31,103 列 slot，其中 11 個缺號槽。
  - 篇題 116、標題 2,603、註腳 1,013。
  - pericope 2,610、passage 2,773、chunk 433。
  - 嵌入記錄 34,058、names 2,926、事件 33（178 個錨點）。
- GT v2：`ground_truth.v2.json`，sha `7280bb42…`，slot_universe=text@247eafe44b02。v1 沒有改動。

### prod 資料庫服務

| 位置 | 內容 |
|---|---|
| PG `bible_rag` | `public` 是 legacy，線上 prod 仍讀它；`bb20261008_6daa4f31` 是新 build；`rag_meta` 含 builds、serving、serving_history |
| `rag_meta.serving` | 只有 staging → b20261008_6daa4f31（映像 `bible_rag-backend:r1`）。**prod 沒有列** |
| Qdrant | legacy 的 `bible_embeddings`、`bible_embeddings_hybrid`、`bible_entities`，加上新的 `passages__b20261008_6daa4f31` |
| Neo4j | legacy，R1 不讀 |

### 容器與映像

| 容器 | 埠 | 映像 | 用途 |
|---|---|---|---|
| bible_rag_backend | :8000 | `bible_rag-backend:latest`（9bc112a6） | **線上 prod**，讀 legacy 資料，這次沒有動 |
| bible_rag_backend_cand | :8001 | `bible_rag-backend:e0b` | legacy 資料加 E0b 修正，是 R1 評估的對照臂。restart=no |
| bible_rag_backend_r1 | :8002 | `bible_rag-backend:r1` | R1 staging，讀新 build。restart=no；重啟指令見 `docker-compose.staging.yml` 的 `backend-r1` |

- 映像備份放在 `/mnt/ollama-data/bible_rag_bak/20261007/images/`：latest 加 w1det、e0a、e0b。
- 2026-10-07 的全量備份（43 GB）也在 `/mnt/ollama-data/bible_rag_bak/20261007/`。

## 3. 已驗證的結果

- **文字層**：7 道閘門全綠。字元守恆殘差 0，poppler 互驗 31,021/31,021。
  - 稽核列出的缺陷全數補回：賽9:6「和平的君」、民24:17、詩篇篇題；10 個幽靈節改成缺號槽。
  - 與 bible_md 的差異 100% 都能歸類，「其他」類是 0。
- **決定性**：同一個 commit 跑兩次，build_id 相同、7 層全部重用，管線約 6 分鐘。
- **G-PROJ**：PG、Qdrant、契約檔與快照逐 id、逐欄位相等。
- **E0a**（退役 sparse）：與 prod 比 500 題，路由相同的 497/497 題結果逐位相同。剩下 3 題路由不同，各重抽 6 次，兩臂都會出現兩種路由，所以是 intent LLM 的取樣雜訊。
- **E0b**（修正查詢端 tokenizer）：500 題配對結果。

  | 指標 | Δ | 95% CI |
  |---|---|---|
  | vrec@6 | −0.003 | [−0.013, +0.006] |
  | MRR | +0.005 | [−0.012, +0.023] |
  | hit | +0.002 | — |

  四個指標的 CI 都包含 0。也就是說，這是正確性修正，但檢索結果沒有可量測的變化。證據在 `/mnt/ollama-data/bible_rag_store/reports/e0/`。
- **R1 staging（:8002）**：
  - 20 題 smoke 正常。
  - 合併節、缺號槽（徒8:37 回「本譯本此節從缺」加註腳）、補回的經文、事件附加槽都正確。
  - 握手的四種不符（錯 build、契約檔壞、指紋不符、點數不符）都會拒絕啟動。

## 4. 下一步（依序）

1. **R1 評估**：在 GT v2 下比較 :8001（legacy 加 E0b）與 :8002（R1）。
   - 先跑 A/A 量出雜訊帶；margin δ = max(0.02, 2×雜訊帶)。
   - 檢索：500 題、top-k 5、metric-k 6，配對 bootstrap。要求 Δvrec@6 的 95% CI 下界 > −δ，MRR 不劣於雜訊帶。
   - 受損切片（G01、G15、G02 觸及的題）預期會改善，要報告。
   - 答案端：200 題分層子集，比 faithfulness strict。
   - 工具：`evaluation/quick_retrieval_eval.py --gt v2`（BACKEND_URL 指向各臂）。`ab_compare.py` 是給附加槽用的，不適用，請寫簡單的配對 bootstrap。
   - 注意 :8001 與 :8002 共用同一個 Ollama（intent 與生成）。
2. **R1 上線**：
   - `ragdata promote --env prod --yes-prod --build b20261008_6daa4f31 --image <r1 digest>`。
   - 然後把 prod 的 backend 服務換成 r1 映像（compose 的 backend 服務要改成用映像，並掛契約目錄，參考 `backend-r1`），再跑 20 題 smoke。
   - 回滾：先 `ragdata promote --env prod --rollback --yes-prod`（第一次 promote 的回滾會刪掉該 env 的 serving 列），再把容器切回 `bible_rag-backend:latest`。
   - E0b 不需要單獨上線，它已經包含在 r1 映像裡。
3. **R1 穩定後清理**（Kay：不用的舊資料直接刪）：
   - 資料：public 舊表、`bible_embeddings*`、`bible_entities`、Neo4j 容器與 volumes、:8001 候選容器、舊映像。
   - repo：`scripts/` 的舊建置程式、`bible_chunking/`、`bible_md/`、`output/`。backend 已不 import 這些；要先確認 evaluation 也不依賴。
   - 文件：更正 `docs/ARCHITECTURE.md`、README，以及論文中與稽核不符的敘述。
   - 最後把 `rebuild/main` 併進 main，push（Kay 同意 push 到 public repo）。
4. **R2**：
   - 事件註冊表修正：合併兩個「保羅歸主」、處理 59 個殘片標題的錨點、移除英文別名與流珥。
   - 路由詞表改成 PDF 版加 query_aliases。
   - 先寫 held-out 事件題再改觸發詞，驗收用設計書的 G-HELDOUT。
5. **P5 pilot**：決定要不要做 L2 身分層與 L3 規則關係層（設計書 §13.1；可以用 Claude API 預標，Kay 已同意）。

## 5. 已知事項與陷阱

- **子代理刪資料會被擋**：權限分類器（Modify Shared Resources、Cloud Storage Mass Delete）會擋子代理的刪除動作，unload 與刪 store 這類事要由主 session 執行。
- **映像曾無故消失**：e0b 映像曾從本機不見，後來從 sda 的 tar 還原（`zstd -dc … | docker load`）。上線前先確認要用的映像在本機。
- **映像 digest 不穩定**：containerd image store 的 `.Id` 含 attestation，內容相同的重建也會得到新 digest。promote 要用當下 `docker image inspect` 的值。backend 不核對 digest。
- **build_id 的日期**取自 HEAD 的 commit 日期，隔天只改文件也會產生新的 build_id。要固定就用 `--date`。
- **重建 backend 映像**一定要帶 uv 快取：`docker build --build-context uvcache=$HOME/.cache/uv-bible-rag-backend -t bible_rag-backend:<tag> .`（頻寬約 50 KB/s）。
- **R1 刻意保留 legacy 的檢索行為**：
  - 章範圍只取第一章；
  - 路由詞表是 legacy 凍結版；
  - 策略標籤仍叫 `hybrid_hybrid`。
  這些要放到後續 release，各自用 A/B 量測後再改。
- **尚未處理的小項**：
  - reranker 句對探針分數還沒進指紋；
  - BGE-M3 探針是 24 條，設計書寫 50 條；
  - G-GT.locality 列出 16 個子句、10 題的引文在 gold 範圍外，只報告；
  - `events.yaml` 的 source.struct 標籤過時（內容可重現）。
- **舊的 W1 文件與工具**（`docs/staging_promotion*.md`、`scripts/tools/*`、`config/kg_expect*`）都已不適用，第 4 節的清理時一併移除。
