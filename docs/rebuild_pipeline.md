# 重建管線：從 66 卷 PDF 到 release、載入與驗證

新管線的唯一入口文件。設計依據：`/mnt/ollama-data/bible_rag_store/reference/DESIGN.md`（§4 DAG、§7 loader、§8 閘門）。舊管線（`docs/build_database.md` Step 0–10、`scripts/` 的建庫程式、`bible_chunking/`）已刪除，要看請用 R1 的 commit（1618cbd）。

## 1. 前置環境

- 工具：`mutool` 1.23.10、`pdftotext` 24.02.0（G-TOOL 逐一比對版本）。
- Python：只用 `scripts/.venv` 跑 ragdata。管線不跑 backend，也不需要 backend 的 venv。
- 模型一律離線：BGE-M3 在 `HF_HOME=/mnt/ollama-data/huggingface`，reranker tokenizer 在 `/mnt/ollama-data/bible_rag_store/models/`。建議有 GPU（emb 編碼與 G-ENC 全量重編碼）。
- repo 內的輸入：`bible_pdf/`（66 卷）、`config/registries/`（K0 註冊表；K1 讀 `events.yaml` v2；K4 另讀 `query_aliases.yaml`）、`ragdata/src/ragdata/contract/expectations/`、`ground_truth.json`（GT v1，G-GT 核對 GT v2 變更紀錄用）。
  - R1 的 `config/registries/routing_lexicon.legacy.json` 與 `backend/data/event_registry.json` 已刪除（R2 管線與 backend 都不讀）；要重現 R1，從 R1 的 commit（1618cbd）跑。
- store `reference/` 的輸入：舊系統留下的唯讀副本。bible_md、legacy_output 兩個目錄各有 `SHA256SUMS`，讀取端逐檔核對，任何一檔不符就停，不會默默換掉某一層。
  - `reference/bible_md/`：66 卷 md，只做 G-DIFF 對帳。text 層 `diff_summary.json` 的 `inputs.bible_md` 記著它的摘要。
  - `reference/audit_prototypes/gap_pdf_canonical/canonical_full.jsonl`：只做 G-DIFF 對帳。稽核時就放在這裡，沒有 `SHA256SUMS`；它的 sha 記在 `diff_summary.json` 的 `inputs.canonical_full`，內容一變，text 層就換版本。
  - `reference/legacy_output/`：舊 `output/` 的五個檔。
    - `pericopes.jsonl`、`chunks.jsonl`：struct 的 legacy id 對照。
    - `embedding_queue.jsonl`、`embeddings.jsonl`：G-ENC 的相容抽樣。
    - `chapters.jsonl`：ragdata 不讀；evaluation 的 GT v1 路徑（`evaluation/src/verse_coverage.py`）讀這份。
    - 2026-10-08 從主 checkout 的 `output/` 複製，與 `/mnt/ollama-data/bible_rag_bak/20261007/output/` 逐位元相同。
  - `reference/route_live/`：只是 R1 的產物（R1 的 G-ROUTE 拿舊 backend 的凍結比對結果對帳）。R2 的 route 層沒有 live 比對，管線不讀它；要重驗 R1 的 route 層，從 R1 的 commit（e7b1173）跑。
- Store：`/mnt/ollama-data/bible_rag_store/`，底下 `layers/`、`releases/`、`contracts/`、`reference/`。
- `--load`／`--verify` 讀 repo 的 `.env`（`POSTGRES_*`、`QDRANT_*`）。

```bash
export HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RAGDATA="env PYTHONPATH=ragdata/src:packages scripts/.venv/bin/python -m ragdata"
```

## 2. 一個指令

```bash
$RAGDATA pipeline run [--date YYYYMMDD] [--load] [--verify] [--report pipeline.json]
```

- 依序：text（含 src）→ struct →〔推導檔檢查、G-GT〕→ emb → kg0 → events → route → relations → release →（`--load`）→（`--verify`）。
- 每層先跑 build 閘門，全綠才寫入 store；寫入後立刻用該層**全部** required 閘門再驗一次。
- 任何紅燈立即停止：stderr 印出停在哪一層（含版本）、哪個閘門與前幾筆細節；stdout／`--report` 是完整 JSON 報告。
- 結束碼：0 全綠；1 硬閘門紅燈；2 輸入錯誤或推導檔過期；3 程式錯誤（附 traceback，不寫報告）。
- `--date` 預設是 HEAD 的 commit 日期；`build_id = b{date}_{release_sha 前 8 碼}`。
- 單步指令（`build`、`gate`、`det`、`release`、`load`、`verify`、`unload`）仍在，只供除錯；見 `$RAGDATA --help`。

## 3. 各層產出與閘門

| 層 | 主要輸入 | 產出 | build 閘門 | 入庫後加驗 |
|---|---|---|---|---|
| src＋text（S0–S4） | PDF、errata／normalization／versification 註冊表；G-DIFF 另讀 `reference/bible_md/` 與 canonical_full | src：source_manifest、逐卷 extract；text：12 種記錄、xcheck／overlay／diff 報告 | G-TOOL、G-SRC、G-CONSERVE、G-COUNT、G-REFINT、G-TEXT、G-XCHECK、G-DIFF | G-SCHEMA、G-REF（G-CONSERVE 重讀 src、G-XCHECK 重讀 PDF） |
| struct（S5） | text、BGE-M3 tokenizer、`reference/legacy_output/` | pericopes、passages、chunks、verse_index、legacy_ids | G-SCHEMA、G-COUNT、G-REFINT、G-STRUCT | 同左 |
| emb（S6–S7） | struct、text、BGE-M3＋reranker tokenizer；G-ENC 另讀 `reference/legacy_output/` | embedding_records、指紋；向量是 `.vectors` 附件 | G-SCHEMA、G-COUNT、G-EMB、G-ENC（抽樣） | G-ENC 全量重編碼 |
| kg0（K0） | text、struct、K0 註冊表、`kg0_counts.yaml` | names、extra_spans、parallel_links | G-SCHEMA、G-REFINT、G-KG0、G-PROV | 同左 |
| events（K1） | text、struct、`events.yaml`（R2 人工註冊表，以 pericope 宣告錨點） | events、event_registry_v2.json、events_report.json | G-SCHEMA、G-COUNT、G-REFINT、G-EVENT、G-PROV | 同左 |
| route（K4） | text、kg0、events、kg0 綁定的 `divine_refs`／`name_normalization`、`query_aliases.yaml`、`ragcommon` 書名 | routing_terms、routing_lexicon.json（v2）、query_aliases.json、route_report.json | G-SCHEMA、G-COUNT、G-ROUTE、G-PROV | 同左 |
| relations（王朝層＋GEN 卡，選用） | text（列王紀上 11:41 起、列王紀下、歷代志下 9:29 起的經節與又名／就是註腳；創世記的經節、人名與書名）、route 的 `routing_lexicon.json`、`regnal_expect.yaml`、`gen_expect.yaml` | regnal_layer.json、regnal_report.json；text 有創世記 5、11 章時另有 gen_layer.json、gen_names.json（沒有記錄檔） | G-REGNAL、G-GEN | 同左 |

R2 的事件與路由層（R1 的轉換路徑已移除）：
- **K1**：`events.yaml` v2 是人工註冊表本體，不再從舊 backend 的事件註冊表轉換。錨點以 pericope 宣告，建置時展開成它的全部 passage，證據取 pericope 標題；觸發詞只有 `pdf_terms`（附 PDF 位置）與 `external_aliases`；併掉的 id 列在 `retired`（`merged_into`）。契約只剩一份 `event_registry.json`（variant R2）。
- **K4**：詞表是 PDF 各層與註冊表的聯集（kg0 名與省略「‧」的寫法、divine_refs、查詢別名、事件觸發詞、書名）。每個詞帶全部候選目標、route 型別、可否路由與其規則、來源。
- **G-ROUTE**：從 text、kg0、events 與註冊表重編一次詞表，逐位元比對，並要求 `ragcommon.routing` 接受詞表與 `query_aliases.json`。它不跟舊 backend 比對（R2 沒有 live 比對），release 組裝時也會跑。
- **比對器**：只有 `ragcommon.routing` 一份，K4 閘門與 backend 共用。先遮全書名；其他書名寫法與詞一起掃。每個出現處都是候選，排除表否決的除外。由最長的先取，同長取最左，不與已取的重疊。
- **relations（王朝層）**：ids 為 L3「規則關係層」預留的層名，目前只放王朝公式（Kay 2026-10-19 的 P5 窄例外，只供 backend 的王朝年表卡）與 GEN 卡的兩個檔（見下一項）；其他關係照樣不做。
  - 建法由實驗 A 的 regex 移植（`kg/regnal_*`）。2026-10-19 起加上根治規則 R1a–R12、R14（亞她利雅入猶大鏈、所羅門記國別 U 不在鏈上、順序補邊 0、衝突 3），產出的 `regnal_layer.json` 不再等於實驗 A 的 `layer_auto.json`（`932d2242…`，relations@a04b67a301dc 那一版）；現在審過的 sha 寫在 `expectations/regnal_expect.yaml`。
  - G-REGNAL 釘住 text 版本、這個 sha、兩國的王位鏈與衝突數（`expectations/regnal_expect.yaml`）。text 層或 regex 一變，閘門就紅：先重做 K0 抽查與 Kay 抽查，再改期望檔。
  - release 的選用層：沒有它時 `layers.relations` 是 null、contract_version 1.1.0，位元組與加入前相同；有它時 contract_version 1.2.0，契約多一個 `regnal_layer.json`。backend 啟動時讀到就開年表卡，讀不到就關，並記 warning。
  - 單步建法：`$RAGDATA build relations --text <text 層目錄> --route <route 層目錄>`；`$RAGDATA gate relations <層目錄> --dep <text> --dep <route>`（GEN 之前的層只依賴 text，只帶 `--dep <text>`）。
- **relations 的 GEN 卡檔**（創世記年歲推導卡，`docs/records/2026-10-21_gen_card_integration_plan.md` §2.1、D1、D2、D7）：
  - 建法：`kg/gen_layer.py` 移植 stage-0 的 `gen_layer.py`（數字照抄實驗 A 的 `cards_common.cn2int`），`kg/gen_names.py` 移植確認集的 `names_g.py`。輸入只有 text 層（經節、`name_spans`、`books`、`layer_manifest.json`）與 route 層的 `routing_lexicon.json`；不讀 `reports/`、`contracts/`。在 text@247eafe44b02＋route@c31c88e4681e 上，兩個檔與確認集審過的 `46d87abb…`、`9e622e30…` 逐位元相同。gen_names 的 `sources` 鍵是凍結時那幾份輸入的 store 路徑，只當出處標籤；值是實際讀到的位元組的 sha。
  - text 有創世記 5、11 章就一定建兩個檔，層依賴 {text, route}，所以 build 要給 `--route`（沒給就輸入錯誤）；text 沒有（ragdata 的 mini 測試資料）就不建，層只依賴 text。route 是 relations 的選用依賴（`runner.OPTIONAL_DEPS`）：`gate` 要帶的依賴正好是層宣告的那些，pipeline、release、load、verify 自動照層的宣告帶入；`resolve_layers` 保證 release 的 route 就是 gen_names 讀的那一份。
  - G-GEN 釘住兩個 sha（`expectations/gen_expect.yaml`）。兩個檔要一起出現，只有一個就紅燈。有檔時：層要依賴 route，route 的 `routing_lexicon.json` sha 要等於 gen_names `sources` 記的那一項，gen_layer 的 `text_digest` 要是它依賴的 text 層。沒檔時：只放行依賴正好是 {text}、而且 `regnal_layer.json` 的 sha 在 `absent_ok_regnal` 裡的層，也就是 GEN 之前就有的 relations@ee8e78c043d2 與 relations@a04b67a301dc；依賴 route 的新層一定要帶 GEN 檔。
  - contract_version：只有 regnal＝1.2.0（不變），契約有 `gen_layer.json`、`gen_names.json` 時＝1.3.0。兩個檔依「層裡有沒有這個檔」複製，所以 GEN 之前的層組出的 release（`b20261019_a86f2b06`）位元組不變。
  - backend（r5 起）：manifest 有兩個檔時才讀，讀不起來算 handshake mismatch；沒有檔時 GEN 卡關閉並記 warning（r4 不讀這兩個檔，配新 build 時行為等於沒有 GEN）。開關是請求參數 `use_gen_card`，沒帶時看 `RAG_GEN_CARD`（預設 true）且 `use_graph`、非 `semantic_only`；王朝觸發時不算 GEN。
- **契約握手**：R2 的 backend 映像不接受 R1 build（詞表 v1、registry variant R1、沒有 `query_aliases.json`）。R1 映像也讀不了 v2 詞表。

之後：
- **release（S12）**：寫 `releases/{build_id}.json`（唯讀，同內容重寫是 no-op）；組裝時各層記錄閘門再跑一次（重讀 PDF 的 G-CONSERVE、G-XCHECK 與要 GPU 的 G-ENC 除外）。
- **load（S13）**：寫入新命名空間——PG schema `b{build_id}`、`rag_meta.builds` 一列、Qdrant `passages__{build_id}`、`contracts/{build_id}/`。目標已存在就拒絕；同一份 release 已登記則標 `reused`，不重載。
  - 一個 build 的 Qdrant collection 約開 200–230 個檔。qdrant 容器原本用預設的開檔軟上限 1024：2026-10-21 已載入 4 個 build 時用了 921 個，第 5 個 load 失敗（`Too many open files (os error 24)`，PG 回滾、不留 collection）。Kay 裁決後卸載了 R1（`b20261008_6daa4f31`），並在 `docker-compose.yml` 把 qdrant 的 `ulimits.nofile` 設成 65536／524288、重建 qdrant 容器（prod 中斷約 11 秒）。
- **verify（S14）**：G-PROJ C1–C6 與 G-SCHEMA.pg，全部從三庫讀回比對；C6 要求凍結的 GT v2 指向本 release 的文字層。

## 4. 文字層改變時：推導檔

三個 commit 進 repo 的檔案記著它們出自哪個文字層。build 不寫 config/ 與 expectations（G-IMPORT），所以管線不會自動改寫它們，而是在 struct 之後檢查，不符就停在 `derived`，並依序印出要跑的指令（本 repo 的實際順序）：

1. `scripts/.venv/bin/python scripts/derive_ragcommon_data.py versification --text-layer <text 層目錄>`，然後 commit `packages/ragcommon/data`（`gt build` 拒絕未 commit 的產生器）。
2. `$RAGDATA expect kg0 --text <text> --struct <struct>`；看 diff，只該動本次改變造成的部分。
3. `$RAGDATA gt build --text-layer <text>`：重建 `ground_truth.v2.json`、`config/gold/gt_v2_changes.jsonl` 並重新凍結 `gt_v2_freeze.json`（slot_universe 指向新文字層）。
4. commit 上述檔案，再跑一次 `pipeline run`；已完成的層會直接重用。

文字層一變，`pipeline run` 也會停在 relations：G-REGNAL 釘著審過的 text 版本與 sha；G-GEN 釘著兩個 GEN 檔的 sha，而 gen_layer 的 `text_digest`、gen_names 的 `sources` 都隨 text 層改變（route 層的詞表一變，gen_names 也會變）。這是刻意的：不重審就不產出少了年表卡或 GEN 卡的 release。出路是重審（下面前兩項，該做的都做）或刻意不帶（第三項）：
- 重審 GEN 檔（text 或 route 層變了就要做）：
  1. 在新的 text、route 層上用 ragdata 的建法產生兩個檔（`kg.regnal_build.gen_files`，結果只寫進 store 的 `reports/`）。K0-2（`kg.gen_layer.check`）要 0 問題，gen_names 的 `gen_layer_sha256` 要等於 gen_layer 的 sha。
  2. 列出兩個檔對現行版本的差異（附經文的只進 store），核對後請 Kay 抽查。
  3. 確認後改 `expectations/gen_expect.yaml` 的兩個 sha，commit，再跑一次 `pipeline run`。backend 的 A1 卡片對等也要用新 build 重跑。
- 重審王朝層（text 層變了就要做），用 `evaluation/experiments/2026-10-19_regnal_fix/` 的工具（只寫 store `reports/regnal_fix_20261019/`）：
  1. `candidate.py` 在新 text 層上建候選層；`k0r.py` 對參考層 v2（`ref_v2.py`）比繼位行、邊型別、補邊、鬼節點、衝突、同步，並列出欄位、死因與邊經節的差異；`k0_diff.py` 列出對現行層的全部內容差異（附經文，只進 store）。
  2. K0-1′：三位獨立的 Claude 核對者逐筆核對 `k0_diff.json`、反駁者對抗驗證，要 0 錯誤（2026-10-19 的做法與兩輪結果在 store `k0/`）；接著 Kay 抽查改動項。
  3. 確認後用 `expect.py` 產生 `expectations/regnal_expect.yaml` 的本體（text、sha、鏈與衝突數），commit，再跑一次 `pipeline run`。
  - 不要再跑實驗 A 的 `layer_check.py`：它建的是舊規則的層，main 還會寫入凍結的 store `kg_cards_20261018/A/`。
- 刻意不帶：用 `$RAGDATA release <核心六層版本>` 手動組 release（contract 1.1.0），backend 讀不到 `regnal_layer.json` 與 GEN 檔就關年表卡與 GEN 卡，並記 warning。新 text 層上沒有「只帶王朝層、不帶 GEN 檔」的組法：G-GEN 只放行 GEN 之前就有的層。

GT v2 的人工判斷寫在 `config/gold/gt_v2_curated.yaml`；errata 的字形裁決寫在 `config/registries/errata.yaml`（套用者 `decided_by: kay`）。改了這些檔，就照上面的順序重來。

## 5. 重跑、重用與 G-DET

- store 以內容定址：同樣輸入建出同樣位元組，就是同一個版本，報告標 `reused: true`；release 與 build_id 也相同。
- 報告保存每層的檔案 sha256（emb 另含向量附件），兩次執行的報告逐檔比對即是 G-DET 的記錄檔部分。
- 向量不要求逐位元相同：重建既有的 emb 版本時，沿用已存的向量，並要求本次向量與之 cos ≥ 0.99999、top-20 相同，否則停止。
- 要在不碰正式 store 的情況下比對兩次建置，用 `--store <暫存目錄> --releases <暫存目錄>` 各跑一次，再 `$RAGDATA det <A 層目錄> <B 層目錄>`。

## 6. promote 與回滾

`rag_meta.serving` 決定 backend 服務哪個 (build_id, 映像 digest)；backend 只在啟動時讀一次，改了要重啟才生效。

```bash
DIGEST=$(docker image inspect --format '{{.Id}}' bible_rag-backend:r1)
$RAGDATA promote --env staging --build <build_id> --image "$DIGEST"   # 印出新配對與先前配對
$RAGDATA promote --env staging --rollback                             # 回到上一筆
```

- 每次 promote 在同一交易內附加一筆到 `rag_meta.serving_history`（第一次 promote 時建表）；配對與目前相同時什麼都不寫。
- `--rollback`：把該 env 最新一筆未回滾的紀錄標為已回滾，serving 改回它的前一筆；再跑一次就再退一筆。最新一筆和 serving 不一致時拒絕，不做任何修改。
- 第一次 promote 的回滾（沒有前一筆）會刪掉該 env 的 serving 列，回到「沒有 build 在服務」；之後即可 unload 該 build。
- `--env prod` 一律要加 `--yes-prod`，否則拒絕（promote 與 `--rollback` 都是）。
- prod 配對：2026-10-08 R1（`b20261008_6daa4f31`＋r1）→ 2026-10-09 R2（`b20261008_e05d3e55`＋r2）→ 2026-10-19 `b20261019_18aa84ad`＋`bible_rag-backend:r3`（R2 各層加 relations 王朝層，年表卡）→ 2026-10-20 `b20261019_a86f2b06`＋`bible_rag-backend:r4`（relations 換成修正層 `relations@ee8e78c043d2`；r4 帶 S4 守門、規則種子與放寬的觸發，見 `docs/records/2026-10-20_regnal_r4_staging.md`）→ 2026-10-21 `b20261021_dfa1e3e3`＋`bible_rag-backend:r5`（GEN 卡，見下一條）→ **2026-10-29 起同一 build＋`bible_rag-backend:r6`**（衛生包：R1 k 對齊＋詩篇首段篇題、R3/R4/R6 去拉平、`<0xNN>` 合併＋段號改寫；量測見 store `reports/hygiene_20261029/report.md`；回滾只把映像換回 r5，build 不變，r5 由 `bible_rag_backend_r5_pin` 釘住）。r4 不可配 `b20261019_18aa84ad`：回滾時 r3 與 `b20261019_18aa84ad` 一起回。G-REGNAL 的期望值已換成新層，`b20261019_18aa84ad` 不能再 release／load／verify，但 `promote --rollback` 不受影響。legacy 已刪除，回滾只能翻回前一個 serving 配對。
- GEN 卡（`docs/records/2026-10-21_gen_card_integration_plan.md` §6；2026-10-21 Kay 說「上 prod」後上線）：配對是 `b20261021_dfa1e3e3`（relations 換成依賴 {text, route}、帶兩個 GEN 檔的層，其他各層與 `b20261019_a86f2b06` 相同）＋`bible_rag-backend:r5`。回滾仍是映像與 build 一起回：新 build＋r5 → `b20261019_a86f2b06`＋r4 → `b20261019_18aa84ad`＋r3。交叉配對比王朝卡寬鬆（r4 配新 build 會忽略 GEN 檔；r5 配 `b20261019_a86f2b06` 沒有 GEN 檔，GEN 卡自動關、王朝卡不變），但不當回滾路徑用。
- **換 prod 容器**（promote 之後；只動 backend，不碰 postgres、qdrant、ollama）：先把 `docker-compose.yml` 的 `image` 改成要服務的 tag，再
  ```bash
  docker compose -p bible_rag -f docker-compose.yml up -d --no-deps --no-build --pull never --wait --wait-timeout 300 backend
  curl -s localhost:8000/api/v1/health      # build_id 與 handshake.ok
  PYTHONPATH=packages scripts/.venv/bin/python evaluation/experiments/2026-10-08_r1/smoke20.py \
    http://localhost:8000 <build_id> ground_truth.v2.json <報告.json>
  ```
  GEN 卡上線時另跑 `evaluation/.venv/bin/python -B evaluation/experiments/2026-10-21_gen_card/a4_g.py gt-check --build <build_id>`（smoke20 的 20 題 GT 都沒有 `aux_card`）與 `a4_g.py prod-check --build <build_id>`（確認集 58 題 ON 各 1 次，卡片對等 58/58）。
  回滾：`$RAGDATA promote --env prod --rollback --yes-prod`，把 `image` 改回前一個 tag，再跑同一個 `up`。不要 `docker compose build backend`、不要 `down`、不要 `--remove-orphans`。
  - `up` 用 `--pull never`，所以回滾前先確認舊映像還在本機（`docker image inspect <tag>`）。Komodo 每天會 prune 沒有容器引用的映像；換容器後用一個不啟動的容器釘住舊映像（目前是 `docker create --name bible_rag_backend_r3_pin bible_rag-backend:r3 true`；r2 仍由 `bible_rag_backend_r2_pin` 釘住）。r2 若已被刪，先 `zstd -dc /mnt/ollama-data/bible_rag_bak/20261008/images/bible_rag-backend_r2.tar.zst | docker load`；r3 沒有 tar，只靠 `bible_rag_backend_r3_pin`，不要刪它（必要時可由 commit 3cadd72 重建）。r4 也沒有 tar：staging 或 prod 第一次換 r5 之前，先 `docker create --name bible_rag_backend_r4_pin bible_rag-backend:r4 true`，之後不要刪它。
- staging backend（:8002）見 `docker-compose.staging.yml` 的 `backend-stg`，映像由 `STG_IMAGE` 指定（預設是 `bible_rag-backend:r2`；GEN 卡的 staging 要明確傳 `STG_IMAGE=bible_rag-backend:r5`）。它的 restart 是 `"no"`：握手不符就停在 exited，不會反覆重載模型；主機重開機後要重跑該檔開頭的 `up` 指令。

## 7. 清理被取代的 build

1. 確認它不在 `rag_meta.serving`，也不是回滾或比較的基準。
2. `$RAGDATA unload <build_id>`：只刪該 build 的 schema、`rag_meta.builds` 列、Qdrant collection 與 `contracts/<build_id>/`；serving 中的 build 一律拒絕，重跑可完成中斷的 unload。
3. 刪 `releases/<build_id>.json`，再刪 store 裡沒有任何剩餘 release 引用的層版本（連同 `.vectors` 附件目錄）。
4. 永不刪：`reference/`、`models/`、`tools/`、`/mnt/ollama-data/bible_rag_bak/`，以及 serving 中的 build 與它前一個配對（回滾用）。

## 8. 測試

四套測試都在 repo 根目錄跑。scripts 與 backend 的 venv 沒有 pytest，借 evaluation venv 的 pytest：
- `/mnt/ollama-data/bible_rag_store/tools/pytest_shim` 只放 pytest 相關套件的 symlink；
- `scripts/tests/run.sh` 自己建暫存 shim。

```bash
# ragdata＋packages：2,611 passed、6 skipped（其中 5 個是 PG 整合測試，要設 RAGDATA_TEST_PG_DSN），約 5.5 分鐘
# （test_regnal 與 test_gen 會用 store 的真實層組三次 release，佔約 3 分鐘）
env HF_HOME=/mnt/ollama-data/huggingface HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  scripts/.venv/bin/python -m pytest ragdata/tests packages/ragcommon/tests -q
# backend：250 passed（含 test_integration：暫時 PG 容器、資料目錄用 tmpfs）
PYTHONPATH=/mnt/ollama-data/bible_rag_store/tools/pytest_shim \
  backend/.venv/bin/python -m pytest backend/tests -q
# scripts：12 passed（只剩 derive_ragcommon_data 與 harness）
scripts/tests/run.sh -q
# evaluation：1,472 passed（2026-10-19；test_idlint、test_qd_common 各 1 個舊失敗）
evaluation/.venv/bin/python -m pytest evaluation/tests -q
```

- 上面的數字是 2026-10-19 的結果（scripts 仍是 12 passed）；ragdata＋packages 是 2026-10-21 加入 GEN 檔之後的結果。
- `test_gen.py` 讀 store 的 text@247eafe44b02 與 route@c31c88e4681e 重建兩個 GEN 檔並比 sha，沒有這兩層就 skip；ragdata 的 mini 測試資料沒有創世記，所以 mini pipeline 的 relations 層沒有 GEN 檔、只依賴 text（期望值由 `mini_pipeline.py` 自己寫），`backend/tests/fixtures/mini_build/` 不必重產。
- ragdata 的測試會讀 store 的 `reference/`（bible_md、canonical_full）、repo 的 6 卷 PDF，以及離線的 BGE-M3 tokenizer。
- backend 的 `test_integration.py` 用本機 `pgvector/pgvector:pg15` 映像起一個用完即刪的 PG（資料目錄是 tmpfs，不留匿名 volume；沒有映像就整檔 skip），載入 `backend/tests/fixtures/mini_build/`。這份 build 由 `backend/tests/fixtures/make_mini_build.py` 從 ragdata 的 mini release 產生；契約一變就要重產，否則 ragdata 的 `test_backend_mini_build.py` 會失敗。
- `test_staging_compose_restart.py`（staging compose 的 backend 服務一律 restart "no"）在 backend 套件裡。
- `test_routing_golden.py` 在 `backend/tests/fixtures/routing_r2_gt.json` 凍結、且 store 有它指名的 route 層之前一律 skip。route 層進 store 後，照 `make_routing_golden.py` 開頭的指令凍結。
