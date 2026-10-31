# generator 從 Ollama 換成 vLLM（2026-10-31）

Kay：「接下來模型不想用 ollama 部署，改成用 vllm，模型一樣」。build 不變（`b20261021_dfa1e3e3`），只換 generator 的服務方式與 backend 映像（r8 → r9）。

## 1. 換了什麼

| 項目 | r8（Ollama） | r9（vLLM） |
|---|---|---|
| 服務 | compose `ollama`（`ollama/ollama:latest`，0.32.5），:11434 | compose `vllm`（`vllm/vllm-openai:nightly-8e2beaa3…`，0.32.1rc1.dev197），容器 `bible_rag_vllm`，127.0.0.1:8010 |
| 權重 | `gemma4:e4b-it-q8_0`（GGUF Q8_0） | HF `google/gemma-4-E4B-it` BF16，revision `ee0ef6023621cff504d758262d4e04895a5af4a2`，`model.safetensors` sha256 `cfbd3d2f…3125503`（與 HF LFS oid 相符） |
| context | 131072（`ollama ps`） | `--max-model-len 131072` |
| thinking | Ollama 0.32.5 對 gemma4 預設開（`message.thinking` 另放），`num_predict` 含思考 | 每個請求帶 `chat_template_kwargs.enable_thinking=true`；`--reasoning-parser gemma4` 把思考放到 `reasoning`；`max_tokens` 含思考 |
| 取樣預設 | Modelfile：top_k 64、top_p 0.95 | `generation_config.json`：top_k 64、top_p 0.95（請求端 temperature 0.1 兩邊相同） |
| 模板 | Ollama 內建 renderer（字串 content） | HF `chat_template.jinja`；`--chat-template-content-format string`（自動偵測成 openai 時，每個 system turn 結尾會多一個空白 token） |
| 其他 | `<0xNN>` byte token 要在 client 端合併 | HF tokenizer 解碼，沒有 `<0xNN>`；`--language-model-only`（不載入視覺、音訊塔） |
| GPU | 用到才載入，閒置 5 分鐘卸載（約 6–10 GB） | 常駐 `--gpu-memory-utilization 0.30`（EngineCore 約 25.6 GB；KV 350,654 tokens） |

程式：`backend/utils/llm/vllm_client.py`（新 provider `vllm`）、`factory.py`、`config.py`（預設 provider 改 `vllm`）；`evaluation/src/run_record.py` 的 generator 段在 vLLM 下記 `root`（snapshot 路徑，含 revision）、`max_model_len`、`server_version` 與 vLLM 容器的映像與啟動參數。r9 與 r8 的映像內容只差 `config.py`、`factory.py`、`llm/__init__.py`、`vllm_client.py` 與一個測試檔。

Q8_0 → BF16 不是位元相同的模型：BF16 是 Google 發布的原始權重，Q8_0 是它的 8-bit 量化。vLLM 載不了 Ollama 的 gemma4 GGUF blob，所以「模型一樣」取原始權重。

## 2. 驗證

### 2.1 staging（:8002，`b20261021_dfa1e3e3`＋r9）

- `/api/v1/health`：handshake ok，`services.llm=true`，log 為 `LLM provider verified: vLLM (google/gemma-4-E4B-it)`。
- smoke20：20/20（加 `--chat-template-content-format string` 前後各跑一次，都 20/20）。
- 答案內容檢查（`evaluation/experiments/2026-10-31_vllm_switch/answer_check.py`；smoke20 只看答案非空，生成失敗時的「生成回答時發生錯誤：…」也算非空）：同 20 題 full 模式，0 題錯誤前綴、0 題 `<0x`／`<|channel>`／`thought\n` 外洩、全部以中文作答。

### 2.2 意圖分類對拍（GT v2 500 題）

retrieval_only 唯一依賴 LLM 的是 `classify_intent`，所以直接在主機用 backend 的同一個函式跑，只換 provider（繞過 CPU 上的 reranker）。vLLM 跑兩次；Ollama 用 step2（2026-10-29）graph 臂收集時記下的逐題 intent（classifier 自 10-08 起沒改）。`p20_graph` 與 `page2_graph` 的 495 題 intent 完全相同，視為同一次收集，不當獨立重跑。

| 配對 | 類型一致率 | entity Jaccard |
|---|---|---|
| vLLM A × vLLM B | 0.970 | 0.862 |
| Ollama ret_r7 × Ollama p20 | 0.974 | 0.803 |
| vLLM × Ollama（4 對） | 0.962–0.968（合併 0.964，95% bootstrap [0.956, 0.972]） | 0.775–0.786 |

- 類型分布幾乎相同（例：verse_lookup 171／174 vs 169／170，cross_reference 102／103 vs 102）。
- 不一致的種類在三種配對裡相同（event↔person、event↔topic 這類邊界題），entity 差異是「信徒、上帝、耶和華」這類一般詞，沒有系統性偏差。跨 provider 比同 provider 低約 0.006–0.010，與重跑雜訊同量級。
- 只有 user 訊息，不受 system turn 空白 token 影響。

### 2.3 生成端（100 題分層子集，同一份輸入）

輸入是 `evaluation/results_graph/raw_responses.json`（2026-10-26 graph 臂）的 generator context blocks，經 backend 的 `build_messages`，以 `generate_answer` 的參數（temperature 0.1、max_tokens 10000）呼叫。generator.py 自 10-19 沒改，所以 prompt 與當時相同。

- vLLM 兩次（模板修正後）、Ollama 兩次：各 100 題，0 題錯誤、0 題外洩。同題答案長度比（vLLM／Ollama）中位數 1.0。
- coverage（Haiku 5.5 judge，正式 eval 的同一套 `compute_coverage`，400 份全部有效）：

| 組 | coverage |
|---|---|
| vLLM A／B | 0.661／0.673 |
| Ollama A／B | 0.678／0.670 |

| 配對（同題） | Δ | 95% bootstrap CI |
|---|---|---|
| vLLM A − vLLM B | −0.013 | [−0.030, +0.005] |
| Ollama A − Ollama B | +0.009 | [−0.016, +0.035] |
| vLLM − Ollama（4 對） | −0.018～+0.004 | 每對都含 0 |
| vLLM（兩次平均）− Ollama（兩次平均） | **−0.007** | [−0.024, +0.009] |

  逐題 \|Δ\| 平均：vLLM×vLLM 0.053、Ollama×Ollama 0.072、跨 provider 0.063。分題型 Δ 在 −0.025（VERSE_LOOKUP）到 +0.009（PERSON）之間，每型 20 題，不解讀。結論：換服務方式的差異落在兩邊各自的重跑雜訊內。
- 模板修正前的 vLLM 兩次放在 `gen_prefix/`，不計入。

### 2.4 審查

四個視角（行為對等、部署維運、評估紀錄、測試）各一個 reviewer＋一個對抗驗證。成立且已修：system turn 空白 token（加 `--chat-template-content-format string`）、runbook §6 的 r9→r8 回滾、staging 預設映像（改 r9）、run_meta 補記 vLLM 版本與旗標、與 `~/bifrost` vLLM 搶 GPU（寫進 runbook §6）。駁回：G-ANS 閘門不檢查 generator（現行協議湊不出混合 generator 的組合）。

## 3. 上 prod 與回滾

2026-10-31 13:30（台北）上 prod，Kay 同意後照下列指令切換：

```bash
DIGEST=$(docker image inspect --format '{{.Id}}' bible_rag-backend:r9)
$RAGDATA promote --env prod --build b20261021_dfa1e3e3 --image "$DIGEST" --yes-prod
# docker-compose.yml 的 backend：image 改 bible_rag-backend:r9、LLM_PROVIDER 改 vllm
docker compose -p bible_rag -f docker-compose.yml up -d --no-deps --no-build --pull never --wait --wait-timeout 300 backend
curl -s localhost:8000/api/v1/health    # handshake.ok 且 services.llm=true
```

之後照 runbook §6 跑 smoke20、`a4_g.py gt-check`、`a4_g.py prod-check`，加 2.1 的答案內容檢查。結果（:8000，`b20261021_dfa1e3e3`＋r9，digest `sha256:f3acfb5f…63d2`）：

| 檢查 | 結果 | 存檔（store） |
|---|---|---|
| `/api/v1/health` | status ok，handshake ok、mismatches 空，`services.llm=true`；log `LLM provider verified: vLLM (google/gemma-4-E4B-it)` | — |
| smoke20 | 20/20 | `reports/vllm_switch_20261031/smoke20_prod_vllm.json` |
| gt-check | 20/20，無錯誤、無 `aux_card` | `reports/gen_card_20261021/gt_check_r9_20261031/` |
| prod-check（確認集 58 題 ON 各 1 次） | pass；卡片對等 58/58，GEN 卡 48；ON 觸發題分數 15/16＝0.938（r6、r8 都是 7/8＝0.875）；耗時中位數 17.9 s（r8 15.9 s），最長 28.2 s | `reports/gen_card_20261021/prod_check_r9_20261031/` |
| 答案內容（2.1 同一支） | 20/20：0 題錯誤前綴、0 題外洩、全中文 | `reports/vllm_switch_20261031/answers_prod_vllm.json` |

- prod-check 的 `run_meta.json` 的 `model`／`expected_digest`／`ollama_version` 是 `a4_g.py` 寫死的直連臂常數（gemma4 Ollama），prod-check 只有 ON 臂、經 backend 生成，不代表 prod 的 generator；這次的 generator 以本紀錄為準。
- 第一次 prod-check 忘了帶 `--run`：預設目錄 `prod_check` 是 10-21 那次，58 題都已完成，所以沒有打 prod，只用 10-21 的 calls 重寫了 `prod_check/report.json`（calls.jsonl、run_meta 內容未變；報告數字相同，只多列出 `other_runs` 的 r6、r8 兩次）。runbook §6 已註明兩個檢查都要帶新的 `--run`。

回滾（r9 → r8）：`promote --env prod --rollback --yes-prod`；backend 的 `image` 改回 r8、`LLM_PROVIDER` 改回 `ollama`；ollama 已停的話先 `docker compose -p bible_rag -f docker-compose.yml --profile ollama up -d --wait ollama`；再跑同一個 `up`。r8 由 `bible_rag_backend_r8_pin`、r9 由 `bible_rag_backend_r9_pin` 釘住。

## 4. 之後的評估

- 10-31 以前的分數都是 Ollama Q8_0 generator 量的；r9 之後的分數不能直接和它們比 generator 相關的指標（coverage、faithfulness）。run_meta 的 `generator` 段會標出是哪一個。
- ollama 容器仍在跑（compose 已把它放進 profile `ollama`，`up` 不會再啟動它），只是 prod 與 staging 都不再用到；`/mnt/ollama-data/ollama` 的模型沒刪。
