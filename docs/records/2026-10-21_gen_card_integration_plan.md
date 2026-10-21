# 創世記年歲推導卡接進架構：計畫（2026-10-21）

**Kay 2026-10-21：「開整合計畫，照建議做」**。D1–D7（§4）是本計畫的建議，照這句話採用。其中 D1、D2 超出 prereg §9 寫的範圍（多一個資料檔、relations 多依賴 route 層），這是揭露的擴充，下次報告 Kay 時會點名。上 prod 仍要 Kay 另外說「上 prod」。

依據：GEN 確認集（`evaluation/experiments/2026-10-20_gen_confirm/prereg.md`，結果 e151ae5；`docs/records/2026-10-21_gen_confirm_results.md`）H1、H2 皆過、放行條件成立、K3 未觸發。§9 只放行三件事：

1. P5 擴充：`gen_layer.json` 當 `relations` 層第二個可選的契約檔，位元組不變；
2. `gencard` 原樣搬進 backend（A1 對等只核 sha）；
3. staging A4：第一次量 prod 檢索下的效果。

勘查用了 workflow `wf_3446968c-d44`（4 個唯讀代理），計畫審查用了 `wf_f7dd6710-e44`（4 個角度，每個角度的意見再由一位反駁者驗證）。審查成立 30 條，都已改進本稿。

## 1. 實驗和 prod 的差距

| 項目 | 確認集用的 | prod 現在（`b20261019_a86f2b06`＋r4） | 接上要做的 |
|---|---|---|---|
| 資料 | store `reports/arith_stage0_20261020/gen_layer.json`（`46d87abb…`，8,252 B）與 `reports/gen_confirm_20261020/gen_names.json`（`9e622e30…`，4,463 B） | 沒有 | 兩個檔都進 relations 層（D1）。`gencard.parse` 兩個都要，§9 只寫了第一個 |
| 觸發與種子 | `gencard.trigger`／`rule_seeds`：只看題目文字，CPU，沒有 LLM 備援；觸發＝有卡 | 只有王朝卡的觸發 | 原樣搬進 `backend/utils/gencard/`（6 檔逐位元相同） |
| 卡片 | `gencard.card(question, L).g_block`（列＋推導行，≤900 字；58 題最長 338 字） | — | 同上 |
| 生成 prompt | `cards_common.SYSTEM_PROMPT`＋`build_user(context, question, aux)` | `generator.build_messages(question, context, aux_block)` | 不用改：F2 已證明兩者逐位元相同（288/288） |
| 基底 context | 固定一個 pericope（ps:gen.5.1 或 ps:gen.11.10） | prod 檢索 top-5＋事件登錄表附加槽 | 不改；A4 第一次量這個差距 |
| 棄權 | G 沿用 B0（A 的 prompt 加空白附加區塊） | — | prod 沒卡就走原 prompt，和王朝卡一樣（D4）。這和確認集的 B0 不同（結果紀錄 §4） |
| 生成參數 | temperature 0.1、num_predict 10000、num_ctx 131072 | 只送 temperature 與 num_predict；Ollama 模型 context_length 131072，log 顯示 n_ctx_slot 131072 | 不改；A4 在第一次與最後一次呼叫後記 `/api/ps` 的 context_length |

觸發的現況（勘查用凍結的 gencard 與 prod 王朝觸發實跑，只計數）：

- gencard 在 GT v1、v2 各 500 題觸發 0；在王朝卡的開發集 30、確認集 32、問法集 138、stage-0 其他 34 題都是 0。
- prod 王朝觸發在 GEN 的每一組題（確認 58、pilot、P1、P2、stage-0 GEN 18）都是 0。兩種卡同時觸發的題，所有題組都是 0。
- 兩邊的名字沒有重疊（含別名與子字串）。
- gencard 是純函式：只依題目、兩個資料檔與模組常數；在 4 種 PYTHONHASHSEED 下 1,600 多題的結果相同。每題約 0.05 ms。

## 2. 設計

### 2.1 資料層（ragdata）

**建置**：relations 層的 stage 多建兩個檔，都只用自己的程式從上游層建，不從 `reports/` 或 `contracts/` 讀任何東西。

- `gen_layer.json`：移植 stage-0 `gen_layer.py` 的 `build()`，只讀 text 層的 `verse_units.jsonl`。
  - 數字解析逐字移植 `cards_common.cn2int`，不用 `regnal_rules.zh2int`（兩者不同）。
  - 序列化照原檔：`ensure_ascii=False, indent=1`、保留插入順序、結尾換行（和 `encode_layer`、`encode_json` 都不同）。
  - `text_digest` 由 `layer_digest(text.file_shas)` 算，對 247eafe44b02 位元組相同。
- `gen_names.json`：移植 `names_g.build()`。輸入是剛建好的 gen_layer 位元組、text 層的 `name_spans.jsonl`／`books.jsonl`／`layer_manifest.json`，以及 route 層的 `routing_lexicon.json`。
  - `sources` 的五個鍵寫成具名常數，照 names_g 的檔案順序。這些鍵是確認集凍結時審過的輸入所在的 store 路徑，只當出處標籤；值是 builder 實際讀到的位元組的 sha。G-GEN 釘住整個檔的 sha（`9e622e30…`），就證明讀到的輸入等於審過的那幾份。
- text 層裡沒有創世記 5、11 章的鏈時（例如 ragdata 的 mini 測試資料），builder 不寫 GEN 檔，依賴也只寫 text。

**相依**：

- `REQUIRED_DEPS["relations"]` 維持 `("text",)`，另加 `OPTIONAL_DEPS = {"relations": ("route",)}`。
- `_load_deps` 改成接受 required ⊆ declared ⊆ required ∪ optional，而且 given＝declared。
- `release/gating.py` 的 `deps`、`pipeline/steps.py` 的 `GATE_DEPS`／`gate_stored` 都改成傳目標層自己宣告的依賴（篩在 required ∪ optional 內），不再直接用 `REQUIRED_DEPS`。
- CLI：`build relations --text DIR --route DIR`；`gate relations` 用 `--dep` 帶 route。pipeline 的 relations 步驟傳 `built["route"]`。
- 新的 relations 層依賴 {text, route}（D2）。`resolve_layers` 會拒絕相依版本不一致，所以 release 的 route 層一定等於 gen_names 用的那一份。

**閘門 G-GEN**（硬條件）。所有釘值都放在 `contract/expectations/gen_expect.yaml`，經新的 `GateInputs.gen_expect` 讀入；CLI 有 `--gen-expect`，pipeline `Sources` 帶它，mini 測試寫自己的版本。release／load／verify 用 repo 的預設檔。

- **兩個檔要一起出現**：只有其中一個 → 紅燈。
- **有 GEN 檔時**：
  - 兩個檔的 sha 等於釘值（`46d87abb…`、`9e622e30…`）；
  - `depends_on` 含 route；
  - route 層的 `routing_lexicon.json` 的 sha 等於 gen_names `sources` 裡 lexicon 那一項的值；
  - gen_layer 的 `text_digest` 前 12 碼等於 `depends_on.text` 的版本。
- **沒有 GEN 檔時**：只有 `depends_on` 正好是 {text}、而且 `regnal_layer.json` 的 sha 在 `gen_expect.yaml` 的 `absent_ok_regnal` 清單裡，才放行。
  - repo 的清單是 `252e0955…` 與 `932d2242…`。層是內容定址的：{text}＋`252e0955…` 的層就是 `relations@ee8e78c043d2` 本身。所以這條規則只放行 GEN 之前已經存在的層，新形狀的層（依賴 route）一定要帶 GEN 檔。
  - `932d2242…` 留著，是為了讓 `test_regnal.py` 用那一層自己的 regnal 期望值跑閘門時照樣綠。
- **不另做的檢查**（精簡）：兩個檔的 sha 釘住之後，`gencard.parse` 能不能讀、K0-2、`gen_layer_sha256` 交叉核對都是固定性質，不會單獨失敗。這幾項只在 builder 的單元測試裡對 store 的位元組跑一次。ragdata 不放 gencard 的副本。

**契約與 release**：

- registry 的 `LAYER_REPORTS["relations"]` 只擴充。
- `COPIED_OPTIONAL` 改成依「檔在不在」複製，不是依「層在不在」，舊層不會因為沒有 GEN 檔而拋錯。
- contract_version：只有 regnal＝1.2.0（不變），有 GEN＝1.3.0（D7）。

**新 release**：除了 relations 一層，其他各層 digest 都和 `b20261019_a86f2b06` 相同；`regnal_layer.json` 位元組不變（`252e0955…`）。照現行流程 load → verify → promote staging。

**可以直接併 main**：regnal 期望值不動、G-GEN 對舊層放行、依檔複製、1.2.0 規則不變、依賴只放寬、LAYER_REPORTS 只擴充。

- `b20261019_a86f2b06` 在新程式上照樣能重組，有測試證明位元組相同。
- `b20261019_18aa84ad` 在 r4 之後本來就不能重組（G-REGNAL 釘 252e0955）。它當回滾目標靠的是 `promote --rollback`，那一步不讀 release，不受影響。

### 2.2 backend

- **程式位置**：`backend/utils/gencard/` 放 6 個檔，用 `cp` 複製，sha 等於 F1 manifest，不重排版。
  - 不可放成頂層 `backend/gencard`，會和實驗的 `import gencard` 撞名。
  - 轉接程式另寫 `backend/utils/gen_card.py`。`gencard/__init__` 把 `trigger`、`card` 綁成函式，所以轉接程式用 `from utils.gencard import parse, card, trigger`，不從屬性拿子模組。
- **不能改的檔**（GEN harness 的釘值或 metric_version 涵蓋）：
  - `utils/generator.py`、`utils/regnal/{trigger,layer,card}.py`；
  - `ragcommon/{__init__,routing,books,ids,regnal}.py`、`ragcommon/data/books.json`。
  - 接線只動 `routers/query.py`、`models/request.py`、`models/response.py`、`config.py`、`serving/startup.py`、`serving/context.py` 與新檔。
- **讀層**（`serving/startup.py`）：manifest 有 `gen_layer.json` 與 `gen_names.json` 時才讀。
  - 下列每一種都算一個 handshake mismatch，訊息是 `contracts: gen_*.json: …`，不讓啟動崩潰：
    - 只有其中一個檔；
    - JSON 壞掉；
    - `gencard.parse` 失敗，攔 (ValueError, KeyError, TypeError, IndexError, AttributeError)，和 `parse_layer` 相同；
    - gen_layer 位元組的 sha 不等於 `gen_names.gen_layer_sha256`；
    - gen_layer 的 `text_digest` 前 12 碼不等於 manifest `layers.text` 的 `@` 後那段；
    - gen_names `sources` 裡唯一一個以 `/routing_lexicon.json` 結尾的值，不等於 manifest `files["routing_lexicon.json"]`。
  - 啟動 log 一行：有檔時寫 sha12、兩章鏈長、blockers 數；沒檔時寫 WARNING「GEN card off」。
  - `Active.gen: Optional[Layer] = None`，`make_active(..., regnal=None, gen=None)`（保持位置參數相容）。
- **流程**（`routers/query.py`）：檢索 → 王朝觸發判斷 → （王朝沒觸發時）GEN 觸發與卡片 → 生成。
  - **優先順序（D3）**：只有在王朝觸發沒有觸發時才算 GEN，不論王朝卡最後有沒有建成。這是確認集的母體定義：F2 第 3 步刪掉王朝會觸發的題。
    - 王朝觸發用 `utils.regnal.trigger.trigger(q, active.regnal.names, active.regnal.blockers)`。這和 `chronology_card` 內部的呼叫相同，只讀、不改釘住的檔。
  - 有 GEN 卡：`generate_answer(question, results, card.g_block)`，generator 不改。
  - GEN 棄權：`aux_block=None`，走原 prompt。
  - 沒有 results 或 `retrieval_only`：不算卡，和王朝卡相同。
- **開關（D5）**：請求參數 `use_gen_card: bool | None`，settings `rag_gen_card`（env `RAG_GEN_CARD`，預設 true）。
  - 參數有值就用參數；否則要 `rag_gen_card and use_graph and not semantic_only`。
  - 消融臂（semantic_only、use_graph＝false）預設無卡。
- **回應**：沿用 `aux_card`，不改 schema（王朝卡的端點釘值要保持位元組相同）。
  - `kind="gen"`、`text=g_block`、`seeds`＝兩人的層名；
  - `kings`＝鏈節點 id（G05.xx）。欄位名沿用，model docstring 註明是「鏈節點 id」；
  - `lines`＝推導行數、`evidence`＝卡片各列節點的 evidence 經節、`layer_sha256`＝gen_layer 的 sha、`seed_source="rule"`。
  - `_aux_card` 依 kind 分支，王朝卡的輸出位元組不變。
- **紀錄**：只在 GEN 觸發時記一行 INFO：題目 hash（12 碼）、種子 id、題型、推導行數。各欄位的型別固定。不記題目原文。
- **映像**：`bible_rag-backend:r5`（`docker build --build-context uvcache=$HOME/.cache/uv-bible-rag-backend`）。

### 2.3 評估端與公開 repo

- `evaluation/src/rag_client.py` 加 `use_gen_card`。collector 與 judge 的 context 不用改：`aux_context_block` 只讀 `aux_card["text"]`，不看種類。
- 補一個測試：`context_blocks.AUX_LABEL` 等於 `generator.AUX_LABEL`（現在沒有測試釘住）。
- A4 程式放新目錄 `evaluation/experiments/2026-10-21_gen_card/`，store 結果放 `reports/gen_card_20261021/`。
  - 不在 `2026-10-20_gen_confirm/` 加檔，也不新增 `tests/test_gen_confirm_*.py`，因為那會改變凍結的 GEN harness sha。
  - 計分 import 凍結的 `score_g`（stage-0 `keys_x`），不改它。
- **確認集題目文字不進 repo**：
  - 會觸發的測試題一律從 store 讀，沒有 store 就 skip。
  - D3 的測試用現有的合成王朝題，再 monkeypatch GEN 觸發，讓它一被呼叫就拋錯。
  - assert 只比 sha 或計數，pytest 改寫 assert 時才不會印出題目或卡片。
  - A4 程式只印 id、數字與 sha。
- **新增 8 字窗測試**（store-backed，名字不叫 `test_gen_confirm_*`）：
  - 掃描範圍：`backend/utils/gen_card.py`、新的 backend 測試、ragdata 的 gen builder 與它的測試、`evaluation/experiments/2026-10-21_gen_card/`。
  - 比對對象：經文、GT v1/v2、A 確認集、stage-0 題、GEN 確認集 `questions_frozen`、qset p1/p2 題，以及確認集與 stage-0 的 g_block／t_block。
  - 原文與 NFKC 都比，用 ho_edges 那種 AST 字串常數掃描。

## 3. 驗收

### 3.0 規則（看結果前寫死）

- 接線或作廢類的失敗（A1–A3、A6，以及 A4 的接線門檻與作廢）：找出原因、修好、寫進執行紀錄後再跑。門檻不改。
- A4 的品質門檻與停止條件，只看第一次完整有效的那一輪：各臂齊全、逐次作廢都補完。
  - 不過就不提議上 prod，報告 Kay。
  - 只有找到並寫下接線或基礎設施缺陷（卡片對等、prompt 對等、作廢規則）才可以重跑。
  - 每一輪的數字都保留並報告。

### 3.1 驗收表

| # | 內容 | 資源 | 過關 |
|---|---|---|---|
| A1 對等 | (a) `backend/utils/gencard/` 6 檔 sha 等於 F1 manifest。(c) backend 從新 release 的 contracts 讀層後產生的卡：確認集 58 題比 store `run/cards.json` 的 `g` 鍵（不比 `gref`），stage-0 GEN 18 題比 stage-0 `cards.json`。(d) 用 store `run/items.json` 的 context 重組 48 題 G 的 prompt，比 `run/jobs.json` | CPU | a 6/6；c 確認集 58/58（48 題 `g_block` 逐位元相同＋10 題 `g` 是 None、backend 也沒卡），stage-0 18/18（F1／F5 14 題相同＋F3 4 題 backend 沒卡；stage-0 存的 F3 卡是 gold 種子卡，規則本來就不出）；d 48/48 |
| A2 不變 | (1) GEN 沒觸發時 messages 逐位元等於現行。(2) 王朝卡端點釘值：`test_regnal_r4_cards.py` 62 題照樣通過，另加一個同樣釘值、但 GEN 層也載入的版本（`make_active(..., layer, gen=…)`，讀 store 檔），aux_card 只能是 regnal 或 None。(3) 王朝觸發時不算 GEN（monkeypatch）。(4) 啟動失敗模式（§2.2 讀層的 6 種各一個 mismatch、不崩潰；兩個檔都沒有 → 照常服務、`Active.gen` 是 None、記 WARNING）。(5) 用 fake LLM 走 `/query` 攔下 messages：攔到的 context 等於 `"\n\n".join(sources[].context)`；有 GEN 卡時，user 訊息等於 `cc.build_user(join, q, aux_card.text)`。(6) 觸發最壞耗時（500 字對抗字串） | CPU | 全部通過 |
| A3 觸發清單 | GT v1、v2 各 500 題逐題列出 GEN 觸發；王朝卡各題組列出 GEN 觸發；GEN 各題組列出王朝觸發 | CPU | 500 題誤觸 0；兩種卡同時觸發 0 |
| A4 staging 端到端 | 見 §3.2 | Ollama 約 3 小時 | §3.2 的門檻 |
| A5 500 題非劣性 | 未觸發的題靠 A2 在構造上不變；A3 是 0 題就不用逐題比 | — | A3 為 0 |
| A6 build 一致 | 新 build 的 loader verify 全綠；除 relations 外各層 digest 與 `b20261019_a86f2b06` 相同；relations 裡 `regnal_layer.json` 位元組不變，兩個 GEN 檔 sha 等於釘值；`b20261019_a86f2b06` 在新程式上重組位元組相同；ragdata 的 `test_pipeline`、`test_pipeline_cli`、`test_regnal.py`（含舊層用自己期望值的那幾個）照樣綠；新增測試：依賴 {text, route} 但只有 regnal 檔的層是紅燈 | CPU | 通過 |
| A7 程式審查 | 子代理唯讀審查：移植逐字、prod 安全（壞檔、缺檔、回滾配對）、公開 repo 規則 | 0 USD | 成立的問題全修，修後重跑 A1–A3、A6 |

### 3.2 A4：prod 檢索下的效果

用確認集 58 題打 staging（:8002）的 `/query`，`include_context: true`，每臂 3 次。

| 臂 | 做法 | 角色 |
|---|---|---|
| ON | `/query`，**不帶** `use_gen_card`（走上線後的預設路徑） | 出卡 48 題上的上線行為 |
| OFF | `/query`，`use_gen_card: false` | 今天的 prod（描述用） |
| B0-prod | 直接呼叫 Ollama：`cards_common.SYSTEM_PROMPT`＋`build_user(ctx_on, q, None)` | H1 的雙胞胎，換成 prod 檢索 |
| T-rows-prod | 同上，附加區塊是 `cards.json` 的 `g.t_block`；只跑出卡的 48 題 | H2 的雙胞胎，換成 prod 檢索 |

**跑前**：

- 唯讀 `docker inspect` staging 容器的 env：`LLM_TEMPERATURE`、`LLM_MAX_TOKENS`、`OLLAMA_MODEL` 要等於直接呼叫用的選項與 `cards_common.MODEL`，`RAG_GEN_CARD` 要沒設或是 true。不符就不跑。

**跑法**：

- `ctx_on`＝`"\n\n".join(s["context"] for s in sources)`，取自同一次 ON 的回應。每個回應要有 ≥1 個 source、每個 source 的 context 是字串、build_id 是新 build。A2(5) 證明這就是 generator 實際用的 context。
- 順序寫死：依 rep → 依 sid 排序的題 → 先 ON，再把 {B0-prod, T-rows-prod, OFF} 依題的序號輪替（照 `arms_c.arm_jobs`）。
- 直接呼叫的選項和 backend 相同：temperature 0.1、num_predict 10000，不送 num_ctx。每次都記 done_reason、eval_count、prompt_eval_count、thinking_chars。
- 第一次呼叫後與最後一次呼叫後各讀一次 `/api/ps`，記模型與 context_length。

**作廢與重跑**：

- 一個 ON（q, r）和它配對的直接呼叫算一個單位。
  - ON 作廢：重跑 ON，再用新的 `ctx_on` 重跑 B0-prod 與 T-rows-prod。
  - 直接呼叫作廢：用同一個 `ctx_on` 重跑。
- 逐次作廢的情況：
  - HTTP 錯誤；
  - 回答以生成錯誤前綴開頭；
  - `validity.infra_failed` 成立；
  - 呼叫 ≥120 秒；
  - 直接呼叫回傳空內容或拋錯（對應 backend 把空內容變成錯誤前綴）。
- 每次呼叫最多重跑 2 次，超過就整輪作廢。
- 整輪作廢的情況：
  - build_id 不是新 build；
  - gemma digest 或 Ollama 版本前後不符；
  - 兩次 `/api/ps` 的模型或 context_length 不同；
  - 直接呼叫的某一臂截斷 ≥2 次（prereg §4.5）。
- ON 與 OFF 的截斷看不到（`/query` 不回傳 done_reason），在報告裡註明。
- 作廢次數依臂與原因列出。

**計分**：

- 照確認集用 `score_g`（stage-0 `keys_x`），`num_ctx` 傳實際讀到的 context_length。題平均是 3 次的平均。
- 棄權的 10 題 d 記 0。T-rows-prod 與 B0-prod 的 prompt 相同，所以是逐位元沿用。ON 是插補，不是沿用：prod 在這 10 題用原 prompt，和 B0-prod 不同，prereg §4.2 的前提不成立。這是事先定的慣例。

**接線門檻**（全部要過）：

- ON 卡片對等 58/58：
  - 出卡的 48 題 `aux_card.kind=="gen"`、`text` 等於 `cards.json` 的 `g.g_block`、`layer_sha256` 等於 gen_layer 的 sha；
  - 棄權的 10 題沒有 `aux_card`；
  - 全部沒有王朝卡。
- OFF 的 58 題都沒有 `aux_card`。

**品質門檻**：ON 在出卡 48 題的平均 ≥ 0.80。確認集 G 在同 48 題是 0.924；王朝卡用的是 0.70 對 0.802，比例相近。

**停止條件**：Δ(ON − B0-prod) 的 95% CI 下界 ≤ 0 時不提議上 prod，先報告 Kay。

**報告**（描述，算法事前固定；題目同確認集，規則之後沒有再改，不當新的確認證據）：

- Δ(ON − B0-prod)、Δ(ON − T-rows-prod)：58 題依 sid 排序，`sign_flip_p(d, seed=20261018)`、`bootstrap_ci(d, 10000, seed=20261018)`、W:L:T。
- 各臂平均：ON 只報出卡 48 題；B0-prod、T-rows-prod 報嚴格與寬鬆計分。
- OFF：嚴格計分預期多半是格式 0（prod 原 prompt 沒有「答案：」指示），另報整段回答的寬鬆計分（`keys_x.gold_written`），註明不能和 H 比。B0-prod 也用同一個整段計分並列，分開「prompt 格式」和「檢索」的影響。ON 不用整段計分，因為卡片含 gold。
- ON 在棄權 10 題上的真實回答：用整段寬鬆計分，和 OFF 並列，說明這是上線後那 10 題的真實行為。
- 檢索分層：每一次呼叫，看 sources 裡有沒有任何一個的 id、passage_id 或 split_passage_ids 等於該題的 `context_from`（字串相等，不切字串）。每題分成 3 次都有、部分有、都沒有三組，各報 Δ。
- 每題耗時、兩次 `/api/ps` 的 context_length、作廢統計。

**A4 的結果句**（事前寫死，只填數字）：

「staging（新 build＋r5）prod 檢索下，確認集同一批 58 題（盲寫；題目寫出兩人的層名、只在必要時加一個不在路徑上的辨識詞、不含數字、點名創世記），gemma4:e4b：ON − B0-prod Δ̄＝…（棄權記 0），95% CI …；ON − T-rows-prod Δ̄＝…，95% CI …；描述性，題目不是新樣本；Δ 固定實驗的 prompt 格式，不等於使用者看到的 ON − OFF 差」

不加任何關於真實使用者、觸發召回率或其他題型的主張。

**全部過關後**：請 Kay 說「上 prod」，才 promote prod 並換容器。換完後：

- smoke20，另檢查 GT 題都沒有 `aux_card`；
- 確認集 58 題 ON 各 1 次，**不帶**參數：卡片對等 58/58，出卡 48/48 都是 GEN 卡。

## 4. 決定（Kay「照建議做」，全部採用）

1. **D1：兩個資料檔都進 relations 層**，由 ragdata 移植的程式從上游層建，閘門釘審過的 sha。
   - §9 只寫了 `gen_layer.json`；`gen_names.json` 是 `gencard.parse` 的必要輸入，一起進，這是揭露的擴充。
   - 另一個做法是把檔放進映像，違反「backend 讀的資料都由 release 釘住」。
2. **D2：新 relations 層依賴 {text, route}**。gen_names 的 blockers 來自 route 層的 routing lexicon，相依要寫出來，release 才會自動保證 lexicon 一致。
   - 另一個做法是只依 text、把 lexicon 當外部輸入，再在 assemble 另加檢查；但相依沒寫出來，比較容易漏。
3. **D3：王朝觸發優先**。王朝觸發時不算 GEN。這是確認集的母體定義；兩種卡同時觸發在所有題組都是 0，這條規則只是寫死並測試。
4. **D4：GEN 棄權走原 prompt**，沒有 LLM 備援，和王朝卡相同。
   - 確認集的 B0 是 A 的 prompt 加空白區塊，不是 prod 的原 prompt，已在結果紀錄揭露。
   - A4 的 B0-prod 用的是確認集的 B0 做法。
5. **D5：上 prod 後預設開**（`RAG_GEN_CARD` 預設 true）。GT 1,000 題觸發 0、P2 近似題 0/20。
6. **D6：A4 用四臂、每臂 3 次**（約 3 小時 Ollama）。Kay 10-21 說不用管花費。
   - 一臂一次也做得到接線驗收，但量不到效果的 CI。
   - OFF 跑 3 次是為了讓描述用的平均穩定。
7. **D7：contract_version 依契約檔集合決定**：只有 regnal＝1.2.0，有 GEN＝1.3.0。backend 不讀這個欄位，純屬慣例。

## 5. 工時與資源

- 工程：
  - ragdata 約半天；
  - backend 約半天；
  - 評估端、A4 程式與 8 字窗測試約 3 小時；
  - release／load／staging 約 1 小時（load 34,058 點）。
- Ollama：A4 約 3 小時；上 prod 後驗證約 20 分鐘。
- claude 帳本：0 USD（A4 不用 judge）。
- prod 只有最後 promote 和換容器才會動，那一步要 Kay 點頭。

## 6. 風險與回滾

- **範圍只有確認過的題型**：F1（X 幾歲時 Y 出生，相隔 2–4 代）與 F5（X 去世那年 Y 幾歲），創世記 5、11 章，同一章。F3／洪水題、d＝1、d ≥5 的 F1、跨章題都會棄權。
- **棄權的 10/58 題**（事件族不只一個 6、出生者不是後代 4）在 prod 照原 prompt 回答。
- **真實使用者的觸發召回率沒有量過**：P2 的 48/50 是盲寫的受限寫法。
- **prod 檢索 context 與確認集不同**：A4 是第一次量。
- **回滾配對比王朝卡寬鬆**：
  - r4 配新 build 會忽略 GEN 檔（verify 照樣核 sha，沒有程式讀它），行為等於現在；
  - r5 配 `b20261019_a86f2b06` 沒有 GEN 檔，GEN 自動關，王朝卡不變。
  - 回滾仍然是映像與 build 一起回：新 build＋r5 → `b20261019_a86f2b06`＋r4 → `b20261019_18aa84ad`＋r3。
  - `b20261019_18aa84ad` 在 main 上本來就不能重組，回滾靠 `promote --rollback`，那一步不讀 release。
- **映像釘住**：
  - prod 與 staging 都離開 r4 之前，先 `docker create --name bible_rag_backend_r4_pin bible_rag-backend:r4 true`。r4 沒有 tar。
  - staging 的 `STG_IMAGE` 預設是 r2，要明確傳 r5。
- **不要卸載 `b20261019_a86f2b06`**：backend 與評估端的測試直接讀它的 contracts 目錄，它也是回滾目標。
- **text 層一變**，`pipeline run` 會在 relations 停下（G-REGNAL 與 G-GEN 都會紅），要重審兩邊的層。
- **runbook 要改的段落**（`docs/rebuild_pipeline.md`）：
  - §3：relations 那一列與說明，包括 GEN 檔、G-GEN、route 依賴、1.3.0 規則、backend 的 GEN 開關；
  - §4：text 層變動時的重審路徑；
  - §6：prod 配對與回滾鏈、r4 pin、`STG_IMAGE=r5`；
  - §8：如果 mini 測試資料改了，也要改。

## 7. 這次不做

- 不擴到別的題型、別的家譜或別的書；B′ 親屬不做。
- 不改 500 題、不改 `ids.py`；`metric_version` 維持 `4d0826bb8d14`。
- 不改凍結的 GEN 實驗檔與它的測試。
- 論文等架構定案後再跟 Kay 談。

## 執行紀錄

- 2026-10-21 計畫審查（`wf_f7dd6710-e44`）成立 30 條，主要的有：
  - A1(c) 的 stage-0 F3 期望值；
  - G-GEN 缺檔放行規則改成依「依賴＋regnal sha」；
  - mini pipeline 的期望值覆寫；
  - 8 字窗測試；
  - A4 只判第一次完整有效的那一輪；
  - ON 不帶參數；
  - 直接呼叫的作廢規則、配對重跑與順序。
  
  已全部改進本稿。不成立的 3 條（18aa84ad 措辭、OFF 跑 3 次、ON 的整段計分）只做了措辭調整。

- 2026-10-21 實作（`wf_11277065-32a`）：三條分支各自在 worktree 先寫測試再實作，再做 A7 唯讀審查與修正，之後併成 `int/gen-card`（1d17687）。
  - A7 成立的問題：
    - ragdata 3 條：build 時的 G-GEN 沒有測試；舊形詞表的 route 層報成程式錯誤；runbook §6 沒寫。
    - backend 2 條：store 測試的計數 assert 失敗時會印出題目；GEN mismatch 沒點名是哪個檔。
    - 評估端 6 條：ctx_on 的接法沒測；Δ 讀錯臂沒測；8 字窗漏掃 `gen_fakes.py`；calls.jsonl 用 splitlines 切；一處計數 assert；換完後的 GT `aux_card` 檢查沒做，已補 `a4_g.py gt-check`。
  - 全部已修。只有一處沒修：凍結的 `gencard.parse` 同時讀兩個檔時拋的錯，仍只標 `gen_*.json`。
  - 合併後的測試：ragdata＋packages 2,612 passed、5 skipped；backend 448 passed；evaluation 3,164 passed、12 skipped、2 failed。evaluation 的 2 個失敗是已知的 test_idlint 與 test_qd_common。
  - 凍結路徑沒動；`metric_version` 重算仍是 4d0826bb8d14；`backend/utils/gencard/` 6 檔 sha 等於 F1 manifest。
- 2026-10-21 資料層：
  - `ragdata build relations --text text@247eafe44b02 --route route@c31c88e4681e` 產出 `relations@ce442299b9c0`，G-REGNAL、G-GEN 全綠。
    - 層的依賴是 {text, route}。
    - `regnal_layer.json` 是 252e0955…，沒變；`gen_layer.json` 是 46d87abb…、8,252 B；`gen_names.json` 是 9e622e30…、4,463 B。兩個 GEN 檔都等於釘值。
  - release `b20261021_dfa1e3e3`（release_sha dfa1e3e3…）和 `b20261019_a86f2b06` 只差三處：relations 層、contract_version 1.3.0、契約多 `gen_layer.json` 與 `gen_names.json`。
- 2026-10-21 映像 r5：`sha256:31bb9d09e185140f4592ea432ff5160b8a303be3085edd84053ee9aa7949db05`，程式來自 1d17687。已建 `bible_rag_backend_r4_pin` 與 `bible_rag_backend_r5_pin`，防 Komodo prune。
- 2026-10-21 load 失敗（基礎設施）：Qdrant 回 `Too many open files (os error 24)`。
  - PG 已回滾，沒有留下 schema、builds 列、collection 或 contracts 目錄；prod 健康。
  - 原因：qdrant 容器的開檔軟上限是 1024，已載入 4 個 build 時用了 921 個 fd，一個 collection 約佔 230 個。
  - 照 §3.0 屬於修好再跑。修法是卸載 R1（`b20261008_6daa4f31`，r1 映像已不在，不在回滾鏈上），或調高 qdrant 的 `ulimits.nofile`（要重啟 qdrant）。兩者都會動共用資源，等 Kay 決定。
- 2026-10-21 Kay 裁決「卸 R1＋調高上限」：
  - 卸載 `b20261008_6daa4f31`：Qdrant 的 fd 從 921 降到 728。
  - qdrant 的 `ulimits.nofile` 調成 65536／524288 並重建容器（503a6e8）。prod 中斷約 11 秒（13:35:09–13:35:20），之後 3 個 collection 都是 green，prod 健康，retrieval_only 查詢正常。
- 2026-10-21 重跑 load：`b20261021_dfa1e3e3` 載入 34,058 點。
  - verify：G-SCHEMA.pg、G-PROJ C1–C6 全綠。
  - contracts 對 `b20261019_a86f2b06`：10 個檔逐位元相同，多出 `gen_layer.json`（46d87abb…）與 `gen_names.json`（9e622e30…）；manifest 只差 build 名稱、relations 層與這兩個檔的列。
  - A1(c) 改從新 contracts 讀層（`test_gen_card_release.py`）：3 passed，確認集 48 卡＋10 無、stage-0 14＋4。
  - A6 全過：verify 全綠；除 relations 外各層 digest 不變；regnal 位元組不變；兩個 GEN 檔等於釘值；a86f2b06 在新程式上重組位元組相同；test_pipeline、test_pipeline_cli、test_regnal 都綠；只有 regnal 檔的 {text, route} 層是紅燈。
- 2026-10-21 staging：`promote --env staging --build b20261021_dfa1e3e3 --image sha256:31bb9d09…`，`STG_IMAGE=bible_rag-backend:r5` 起 `backend-stg`。
  - handshake ok；啟動日誌顯示王朝層 252e0955、GEN 層 46d87abb（chains {5: 10, 11: 9}，60 個 blocker）都已載入。
  - 容器 env：LLM_TEMPERATURE 0.1、LLM_MAX_TOKENS 10000、OLLAMA_MODEL gemma4:e4b-it-q8_0，RAG_GEN_CARD 沒設。Ollama 0.32.5，gemma digest 9dcc3580。
  - 13:58 開始跑 A4（`a4_g.py a4 --build b20261021_dfa1e3e3`，store `reports/gen_card_20261021/a4/`）。
