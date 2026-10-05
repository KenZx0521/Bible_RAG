# KG 資料層修復第 1 批 W1：交接紀錄（2026-10-05 暫停時的狀態）

- **暫停時間**：2026-10-05，Kay 要求停下並開新 session 繼續。
- **相關文件**：
  - [第 1 批計畫](2026-10-04_kg_batch1_plan.md)：權威文件，§7 全部採用建議，§8–§9 是 Kay 的決定。
  - [W0 結果](2026-10-05_kg_batch1_w0_results.md)
  - [總計畫](2026-10-04_kg_data_layer_fix_plan.md)

## 1. 目標

第 1 批分兩波升版：W1（1A＋1B）→ W2（1C＋1D）。W0 與 W1-0 已完成，目前在做 **W1**。

- **1A：Step 6.05 關係後處理，10.3 退場。**
  - 消除無出處的衍生邊：H3 374→0。
  - 消除 domain/range 違規：H9 14→0。
  - 修正親屬方向矛盾與女性 head。
  - 字母序規則邊改成錨定句型抽取。
  - 匯入改為整組覆寫（修 onCreate-only）。
- **1B：交叉引用 provenance。**
  - supplementary 改用經文座標重錨，修正 59 條錯位，找回 16 筆被丟掉的定義。
  - 寫入 curated／tsk 旗標，TSK 證據不再被 curated 邊吞掉（856 對）。
  - backend 改讀 `r.curated`，999 哨兵退場。
  - 新增交叉引用閘門。

W1 完成的定義：
- 實作完成；
- staging 全量重建；
- R2 閘門、D3、K9 都通過；
- Kay 核可後升版到 prod；
- ratchet 與合併允許清單一起提交。

## 2. Kay 的決定（W1 相關，全部已定）

- §7 全部採用建議。
- 10.3 退場（D2）。
- C4（撤回流珥別名）放在 W2 之前做。
- K9 由 AI 雙盲標註加裁決，Kay 抽查，報告標「非人工」。
- 2026-10-04：後端決定性修正部署到 prod（9bc112a6），r0 = 0。
- 2026-10-05：W1-0「opt-in 決定性」納入 W1，已完成。
- **2026-10-05 實作期間又決定了四項**，寫在 `decisions.md`：
  1. **K9 硬門檻改用 `text_correct`**（Wilson 下界 ≥0.85）。`id_correct` 照標，但只作為延後-A 的基準報告，不擋升版。原因：規劃者試標 60 條，text 60/60，id 51/60；id 錯誤來自節點層的同名合併。
  2. `homonym_ids` 預設為 `[person:bide, "person:yuehan（shitu）"]`。
  3. 清單項後面接「的」時採 `cont`：保留第一項，清單到此結束。
  4. 納入 1A-C3c 第二段同名防護。
- 合併允許清單 `config/kg_diff_allow_batch1w1.yaml` 由主控（orchestrator）在 W1 step 4 用 1A、1B 的片段組裝。
- H11 已被 1A 使用，1D 原本規劃的 H11 改號為 H12。

**預測值（1A 規劃者重算）：**

| 項目 | 值 |
|---|---|
| 錨定邊 | 319 |
| 親屬邊 | 509 |
| 10.2 之後的邊數 | 5,616（sha 661cfc6289e2…） |
| 錨定關閉時的退路 | 5,297 邊（sha bbc5c830…） |

## 3. 進度

實作方式：
- 兩條線各在自己的 git worktree 裡並行。
- 每項的流程：先寫測試，確認修改前會失敗，再實作，一個缺陷一個 commit，最後由另一個代理做對抗性審查。
- 實作期間不寫任何資料庫，也不動容器。

暫停時三套測試全綠：

| worktree | scripts | evaluation | backend |
|---|---|---|---|
| w1a | 783 passed、1 skipped | 208 | 70 |
| w1b | 763 passed、1 skipped | 223 | 82 |

### 1A：`/home/kenzx0521/Bible_RAG-w1a`，branch `w1/1a`，HEAD f6a1fea

| 項目 | 狀態 | commit |
|---|---|---|
| 1A-C0 歸檔重算腳本 | 審查通過 | 03a255d |
| 1A-C1 provenance 欄位、phase 6／7 | 審查通過 | 7f8df82 |
| 1A-C2a geo_rules／stoplists 共用模組 | 審查通過 | 7d9e680 |
| 1A-C2b entity_overrides.yaml | 審查通過 | 0dc5ecb |
| 1A-C3a 錨定句型 P1–P4 | 審查通過 | d9db62f |
| 1A-C3b 第一段同名防護 | 審查通過 | 59e0358 |
| 1A-C3c 第二段同名防護 | 審查通過 | 73ec2c6 |
| 1A-C4a 6.05 骨架 | 審查通過 | 08d507e |
| 1A-C4b drop_inverse | 審查通過 | f099664 |
| 1A-C4c rules_to_anchored | 審查通過 | d6c0416 |
| 1A-C4d drop_llm_event_event | 審查通過 | 30c0823 |
| 1A-C4e provenance_gate（「但」） | 審查通過 | 42caf5b |
| 1A-C4f domain_range | 審查通過 | 619d549 |
| 1A-C4g1 direction_pairs 表 | 審查通過 | fc2a6e0 |
| 1A-C4g2 flag_id_order | 審查通過 | f1b513b |
| 1A-C4h 親屬方向與無向去重 | 審查通過 | f23d759 |
| 1A-C4i collapse_by_key | 審查通過 | f025bf6 |
| 1A-C4j stamp_provenance、hash seed 決定性 | 審查通過 | c41b159 |
| 1A-C5a 匯入整組覆寫 | 審查通過 | ba6308d |
| 1A-C5b 端點檢查、written==rows | 審查通過 | 34054fb |
| 1A-C5c 輸入契約（relations_clean） | 審查通過 | 4cd1f81 |
| 1A-C5d 空層防護、--replace 只限 staging | 審查通過 | 4959490 |
| 1A-C6a R5 改 opt-in、性別 inverse 改 null | 審查通過 | 9f1e681 |
| 1A-C6b 移除 R2／prompt_signals | 審查通過 | 9c1c6c3 |
| 1A-C6c PRECEDED_BY 描述 | 審查通過 | e32d20d |
| 1A-C7 10.3 退出預設鏈 | 審查通過 | 8e56e24 |
| 1A-C8a metric 層級的 severity | 審查通過 | 171ca1a |
| 1A-C8b model 讀 direction_verified／sources | 審查通過 | 00ceb5e |
| **1A-C8c** H3 以 source 判斷豁免 | **已提交，未審查** | f6a1fea |
| 1A-C8d H11 | 未開始 | — |
| 1A-C8e R6 全部父母編碼 | 未開始 | — |
| 1A-C8f H3／H9／R6 升 hard | 未開始 | — |
| 1A-C8g 探針（含流珥 absent） | 未開始 | — |
| 1A-T1 check_merged_inputs | 未開始 | — |
| 1A-T2 check_edge_set | 未開始 | — |
| 1A-T3 kin_review（K9 工具，預設 `--gate-field text_correct`） | 未開始 | — |
| 1A-T4 relations_expect | 未開始 | — |
| 1A-T5 residuals_expect（要在 7688 仍是第 0 批時跑） | 未開始 | — |
| 1A-E1 提交期望檔 | **等 Kay 核可**（實作階段刻意跳過） | — |
| 1A-C9a build_database／README 重灌鏈 | 未開始 | — |
| 1A-C9b staging_promotion（含 K9 事前登記） | 未開始 | — |
| 1A-C9c 架構文件、第 0 批紀錄更正 | 未開始 | — |

### 1B：`/home/kenzx0521/Bible_RAG-w1b`，branch `w1/1b`，HEAD bb04c8f

28 項全部提交。除最後一項外都審查通過，1B-C4a 修過一輪，已 amend。

| 項目 | commit | 項目 | commit |
|---|---|---|---|
| 1B-C3a 凍結 161 筆定義 | 1476a6c | 1B-C6b 節級 TSK 支撐閘門 | 51c1b4e |
| 1B-A0 歸檔規劃證據 | fe5b682 | 1B-T3 xref_probe expect／fingerprint | d18f5ab |
| 1B-C1 backend 改讀 r.curated | 7cd33c4 | 1B-C8a model 讀錨點欄位 | fc0f0f0 |
| 1B-T1 xref_probe seeds／predict／compare | d75b7c7 | 1B-C8b H8 | 0f3850e |
| 1B-T2 probes/xref_measure | ab1d300 | 1B-C8c R4 逐節 | 3d0257c |
| 1B-T4 deploy-guard | f0f6f00 | 1B-C8d R11 | e2adcd0 |
| 1B-C3b curated_xrefs 解析 | 0976048 | 1B-C8e 10 個 xref 探針 | 8c0ac98 |
| 1B-C3c supplementary 改經文座標 | fd7c1fe | 1B-C8f H8／R4／R11 升 hard | 903cbf2 |
| 1B-C4a 依段落對聚合、旗標 | 791c15d | 1B-D1 diff_kg xref_provenance | 35a0d85 |
| 1B-C4b import_neo4j 拒絕重複對 | 52c2647 | 1B-D2 diff_kg mention_count | a625b79 |
| 1B-C5a 刪 XREF-2 兩筆 | 45c1eeb | 1B-D3 --fail-on-unused | 6160094 |
| 1B-C5b X2 改錨 | 333dcdc | 1B-E1 xref_ab_slice | b2b4a76 |
| 1B-C7 validate_output xref 閘門 | b7f9eb8 | 1B-E2 20 題煙霧 id | 72c313f |
| 1B-C6a Step 9 無條件 SET、計數閘門 | 7cf47c6 | **1B-C9 文件** | bb04c8f（**未審查**） |

### 還沒做的事

- 審查兩個未審項目：1A-C8c、1B-C9。
- 1A 剩下 12 項，見上表。
- 兩條線各做一次整體審查（三個角度：計畫覆蓋、決定性與重灌鏈、跨線整合）。
- 約 200 條 minor 審查意見還沒分流。逐項的 minor、偏離與交接註記都在 `bak/20261005_w1_handoff/w1_item_outcomes.json`。

## 4. 環境狀態（暫停時）

- **主目錄**：`/home/kenzx0521/Bible_RAG`，branch `feat/graph-strategy-gating`。除了這份交接紀錄，W1 還沒有任何東西合併進來。
- **worktree**：
  - venv（scripts、evaluation、backend）與 `bak/` 用 symlink 指到主目錄，已寫進 `.git/info/exclude`。
  - `output/` 是各自的實體副本：不要改既有檔，暫存產物另寫到 scratch。
- **容器**：
  - prod backend：映像 9bc112a6（含 56a5440、7d322f7；**不含** W1-0 的 087ab0d／3a294a0）。
  - backend-staging：映像 `bible_rag-backend:w1det`，`QDRANT_ENTITY_COLLECTION=bible_entities_detB`。它是用 scratch 的 compose override 啟動的。
  - neo4j-staging（7688）：仍是第 0 批的等價重建。
- **映像**：目前只剩 `latest`（9bc112a6，prod 在用）與 `w1det`（d9827866，staging 在用）。
  - **回滾用的 `pre-detfix-20261004`（ae72365e）與 `detfix` tag 已經不見。** 2026-10-05 檢查時，`docker system df` 顯示可回收映像為 0，像是有人執行了 `docker image prune -a`，把沒有容器在用的映像全清掉。這個 session 的代理都沒有執行過刪映像的指令，可能來自同機的其他專案或 session。
  - detfix 部署若要回滾，只能從 git 重建：用 `7fa9d00` 加上 uv 快取，見 README「Docker 建置快取」；build cache 也還在。
  - **W1 的 R0 不能只靠 `docker tag`**：回滾映像要用 `docker save` 存到 `bak/`，或讓一個停著的容器引用它，否則可能再被 prune 清掉。
- **Qdrant collection**：
  - `bible_entities`：prod；
  - `bible_entities_v2`：第 0 批 staging；
  - `bible_entities_detB`：W1-0 驗證用，目前 backend-staging 在用。W1 重建後可以刪除。
- **備份**：`bak/20261004`（R0，第 0 批）。**W1 的 R0 還沒做**：要做三庫備份、`git tag kg-pre-batch1-w1`、`docker tag … kg-pre-batch1-w1`。

## 5. 檔案位置

`/tmp` 的 scratchpad 可能被清掉，所以全部複製到 `bak/20261005_w1_handoff/`（gitignored）：

| 檔案 | 內容 |
|---|---|
| `scratch_w1/plan_1A.json`、`plan_1B.json` | 逐 commit 的最終實作計畫（`final.items[]`），以及塑造它的審查意見（`critique`） |
| `scratch_w1/spec_1A.json`、`spec_1B.json` | 規劃者的原始設計與對抗審查 |
| `scratch_w1/decisions.md` | 生效中的決定（Q1–Q5），代理每項開工前都會重讀 |
| `scratch_w1/1A/`、`scratch_w1/1B/` | 規劃者的重算與模擬（1A 在 `rev/`） |
| `scratch_w1/impl/`、`scratch_w1/review*/` | 實作與審查的暫存產物 |
| `w1-implement.workflow.js` | 實作工作流程腳本，逐項執行「實作 → 審查 → 修正最多 2 輪」，最後做三角度整體審查 |
| `w1-implementation-plan.workflow.js` | 規劃工作流程腳本 |
| `w1-implement.journal.jsonl` | 這次執行的 journal |
| `w1_item_outcomes.json` | 逐項的 commit、審查結論、minor、偏離與交接註記 |
| `compose.w1det.yml` | backend-staging 目前用的 override（映像 w1det，實體 collection 用 detB）。重新建立容器的指令：`set -a; source scripts/tools/staging.env; set +a; docker compose -f docker-compose.yml -f docker-compose.staging.yml -f bak/20261005_w1_handoff/compose.w1det.yml --profile staging up -d --no-deps backend-staging` |
| `legacy100.txt` | legacy-100 的題號清單（opt-in AA 用） |

注意：計畫 JSON 裡的 `$SCR` 與 `/tmp/claude-1001/…/scratchpad/w1` 路徑，現在對應到 `bak/20261005_w1_handoff/scratch_w1`。

## 6. 新 session 如何續跑

1. **檢查環境**：在兩個 worktree 裡分別跑 `git status`（應該乾淨）和三套測試。backend 測試需要 pytest shim，重建方式：
   ```bash
   SHIM=$(mktemp -d); for p in pytest _pytest pluggy iniconfig pygments py.py; do ln -s /home/kenzx0521/Bible_RAG/evaluation/.venv/lib/python3.12/site-packages/$p $SHIM/$p; done
   echo $SHIM > bak/20261005_w1_handoff/backend_shim_path
   PYTHONPATH=$SHIM backend/.venv/bin/python -m pytest backend/tests -q
   ```
2. **審查兩個未審項目**：1A-C8c、1B-C9。用 `w1-implement.workflow.js` 裡 `reviewPrompt` 的同一套要求。
3. **續跑 1A**：Workflow 的 resume 只限同一個 session，所以要重新啟動 `w1-implement.workflow.js`。參數：
   - `scr`：`/home/kenzx0521/Bible_RAG/bak/20261005_w1_handoff/scratch_w1`
   - `decisions`：`…/scratch_w1/decisions.md`
   - `shimFile`：新 shim 的路徑檔
   - `mainRepo`：`/home/kenzx0521/Bible_RAG`
   - `base`：`e5fe097`
   - `streams`：
     - 1A：只放剩下的 12 項，即 1A-C8d、C8e、C8f、C8g、T1、T2、T3、T4、T5、C9a、C9b、C9c，不含 1A-E1；
     - 1B：`items: []`，這樣只會跑 1B 的整體審查。
4. **整合**：
   1. 把 `w1/1a`、`w1/1b` 合併到 `feat/graph-strategy-gating`。預期的衝突點列在 `plan_*.json` 的 `cross_stream_touchpoints`，包括：
      - `kg_validate` 的 checks_h／checks_r／model；
      - `config/kg_quality_baseline/{h,r}.json`、`kg_probes.yaml`；
      - `test_validate_kg_shipped.py` 的 hard 集合；
      - `_validate_kg_helpers.py`、`test_staging_write_guards.py`；
      - `docs/build_database.md`、`docs/staging_promotion.md`、`test_docs_alignment` 的 HELP_ARGV。
   2. 合併後跑整套測試，再做一次跨線審查。
   3. 分流 minor 意見。
   4. 第 1 批計畫 §9 補上 2026-10-05 的四項決定，以及 1A 重算後的數字（填回【待重算】的格子）。
5. **期望檔（W1 step 4 前半）**：
   - 1A-T5 `residuals_expect`：**要在 7688 仍是第 0 批時跑**。
   - 1A-T4 `relations_expect`。
   - 1B 的 `xref_probe.py expect`：產出 `config/kg_expect/batch1_w1/xref.json`，fingerprint 應為 e522411e…。
   - K9 正式標註：
     - 抽樣：錨定 n=60（seed 20261007）、llm 30、prior 全部 30。
     - 流程：AI 雙盲標註，再加裁決。
     - 門檻：text_correct 的 Wilson 下界 ≥0.85。
     - 報告：標「非人工」。
   - 全部交給 **Kay 核可**後，才提交 1A-E1 與 xref.json。
6. **W1 step 2–3**：
   1. 做 W1 的 R0 備份。
   2. staging 全量重建，照計畫 §1 的 W1 重灌鏈：跳過 Step 1，改跑 sha 前置檢查。
   3. R2 閘門：
      - `check_edge_set --expect`；
      - validate_kg：硬門檻全過，退步只允許出現在 R1；
      - diff_kg 用合併允許清單加 `--fail-on-unused`；
      - xref fingerprint；
      - Step 9 連跑兩次，fingerprint 必須相同。
   4. D3：`d3_gate.py --route-residual-max 0`，staging 端用 W1 HEAD 建出的映像。
   5. opt-in A/B（§5.2）：
      - entity_path：對照組是 staging-P1，結果只報告；
      - xref：用 `xref_ab_slice`，touched 題數 >34 就先停下來查。
   6. `/api` 的 7 個 id 必須與 prod 完全相同（§5.3）。
7. **升版**：Kay 核可後才做。
   1. backend 先上，跑 20 題煙霧測試和 deploy-guard。
   2. 再跑一次 deploy-guard，通過後才 dump staging、載入 prod Neo4j。
   3. R4：在乾淨的 shell 用 `--target prod` 跑。
   4. ratchet、accept 與合併允許清單放同一個 commit。
   5. 寫 W1 結果紀錄。
   6. 更新論文數字（U3）。
