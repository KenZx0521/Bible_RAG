# book_anchor 消融（2026-10-15）

唯一規格是 `prereg.md`（§0.1 的 M1、M2 優先於其餘段落）；審查處理見 `plan_changes.md`。
三臂 ctrl／nopin／off 在一次性批次容器（映像 `bible_rag-backend:r2`）內以行程內名稱替換實作，
每題只做一次 intent，生成直接呼叫 backend 的 `generate_answer`。輸出在
`/mnt/ollama-data/bible_rag_store/reports/ba_ablation_20261015/`（prereg §11）。

- **結果（2026-10-16）：prod 動作＝採 off（§8 第 2 條）。** nopin:ctrl 無法判定、off:ctrl 與 off:nopin 可改；不劣，不是改善。off 的代價（點名書出現率 38/39→19/39、拒答或含糊 13→28）見 prereg 執行紀錄三。改 prod 是 commit ③（§12），另起工作。報告副本：`report.md`。

## 檔案

| 檔 | 在哪裡跑 | 內容 |
|---|---|---|
| `ba_driver.py` | 容器（`/exp`） | `retrieve`：沒有待跑的題就直接結束（不載模型、不寫任何行）；照 main.py lifespan 初始化，握手或 LLM 健康檢查失敗就 exit 2 且不寫任何行（續跑乾淨）；meta 的 encoder_fingerprint 改成 /health 的 {embedder, reranker} 形狀（與 eval3c run_meta 相同，load_models 原值另存 load_models_fingerprint）；每題 1 次 intent（失敗重試 2 次），ctrl→nopin→off 循序；ctrl 沒呼叫 `routes._book_anchor` 且不在 `--force-ids` 的題不跑 nopin／off（M1）；strategy_errors 三臂整組重跑 ≤2 次。`generate`：先對整份計畫做 I7（exit 3），沒有待生成的項目就結束、不寫任何行；LLM 健康檢查失敗 exit 2 且不寫任何行；`generate_answer`、messages sha、失敗重試 ≤2 次。stdout 只有 JSONL，log 走 stderr，不寫檔 |
| `ba_arms.py` | 容器／host 測試 | `arm()` 替換 `router._gather`、`router.pin_book_anchor_candidates`、`routes._book_anchor`（不可重入鎖、finally 還原）；`intent_retry()`；`llm_capture()` |
| `_ba_io.py` | 兩邊 | JSONL（每行有 kind、壞行 raise、截到最後一個換行）、續跑鍵、`ctx_sha` |
| `ba_prep.py` | host | 3.0：git 斷言（實驗目錄與 `test_ba_*.py` 等於 HEAD、無未追蹤檔）、`questions.json`、`batch_a.json`、`force_ids.json`、`exp_meta.json`；`--smoke` |
| `_ba_checks.py` | host | I0–I5、子集、機制標記、gen_plan、judge_ids、judge_order、freeze、eval3c 重疊、smoke 預期值、`build_eval3c_ref` |
| `eval3c_ref.json` | — | 凍結：eval3c full 的 43／39／20／單書 19 題、500 題路由、第一個 R1 題；`ba_analyze.py make-ref --ba39 <ba39.json>` 重建（與設計階段 ba39.json 交叉核對） |
| `_ba_export.py` | host | collector 格式的 `raw_responses.json`＋`run_meta.json`（sources 照 `routers/query.py::_source`），contexts 再驗一次 sha |
| `ba_cov.py` | host | 只判 coverage（`quick_faithfulness_eval._load`＋`_coverage`），逐要點判定寫進 JSON |
| `_ba_stats.py` | host | 有效次數、t-CI、sign-flip、Holm、500 題換算、`verdict()`、`prod_action()` |
| `_ba_report.py` | host | 報告：判分 meta 拒收規則、判分檔的 `.src_sha` 必須等於現在的 ans、三個配對、判定、§5 全部描述項（`report` 先核對 eval3c raw／run_meta／faith_cov 的 sha） |
| `ba_analyze.py` | host | `smoke`、`check [--partial]`、`export-retr`、`export-ans`、`judge-order`、`report`、`trim`、`make-ref` |
| `run_ba.sh` | host | 步驟 3 全部（可續跑）；每個判分輸出旁寫 `<out>.src_sha`（判分成功後才寫，內容是所判 `ans/<d>/raw_responses.json` 的 sha256），只有輸出非空且 sha 等於現在的 ans 才跳過 |
| `compose.ba.yml` | — | backend-stg 的 healthcheck 改 NONE、ports 清空 |
| `oc_sim.py`、`oc_out.json` | — | §7 操作特性模擬 |

測試：`cd evaluation && .venv/bin/python -B -m pytest tests/test_ba_*.py -q -p no:cacheprovider`

## 步驟 0（Claude；被權限擋時交給 Kay）

```bash
curl -s localhost:11434/api/ps        # e4b 的 size_vram == size
nvidia-smi
REPO=/home/kenzx0521/Bible_RAG; EXP=$REPO/evaluation/experiments/2026-10-15_book_anchor
docker compose --project-directory $REPO -f $REPO/docker-compose.yml \
  -f $REPO/docker-compose.staging.yml -f $EXP/compose.ba.yml config backend-stg   # healthcheck NONE、沒有 ports
```

## 步驟 2：smoke（commit ① 之前）

```bash
REPO=/home/kenzx0521/Bible_RAG
EXP=$REPO/evaluation/experiments/2026-10-15_book_anchor
OUT=/mnt/ollama-data/bible_rag_store/reports/ba_ablation_20261015
PY=$REPO/evaluation/.venv/bin/python
export STG_IMAGE=bible_rag-backend:r2
BA_RUN=(docker compose --project-directory $REPO
  -f $REPO/docker-compose.yml -f $REPO/docker-compose.staging.yml -f $EXP/compose.ba.yml
  run --rm --no-deps -T --name bible_rag_ba
  -e RAG_ENV=prod -e RAG_BUILD_ID=b20261008_e05d3e55
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app/packages:/app/backend
  -v $EXP:/exp:ro -v $OUT:/in:ro
  backend-stg /app/backend/.venv/bin/python -B /exp/ba_driver.py)

$PY -B $EXP/ba_prep.py --out $OUT/smoke --smoke                                     # 1
"${BA_RUN[@]}" retrieve --questions /in/smoke/questions.json --force-ids /in/smoke/force_ids.json \
  > $OUT/smoke/retrieval.jsonl 2> $OUT/smoke/retrieve.log                           # 2
$PY -B $EXP/ba_analyze.py smoke --out $OUT/smoke                                    # 3（I0–I4＋§6 預期值；過了才寫 gen_plan）
"${BA_RUN[@]}" generate --plan /in/smoke/gen_plan.json --retrieval /in/smoke/retrieval.jsonl \
  > $OUT/smoke/gen.jsonl 2> $OUT/smoke/generate.log                                 # 4
$PY -B $EXP/ba_analyze.py export-ans --out $OUT/smoke                               # 5
cd $REPO/evaluation
COLUMNS=1000 $PY -B quick_faithfulness_eval.py --results-dir $OUT/smoke/ans/ctrl_r1 \
  --ids-file $OUT/smoke/checks/judge_ids_ctrl.json --gt v2 --no-rebuild \
  --out $OUT/smoke/judge/ctrl_r1.faith.json > $OUT/smoke/judge_strict.log 2>&1
for a in ctrl nopin off; do
  $PY -B $EXP/ba_cov.py --results-dir $OUT/smoke/ans/${a}_r1 \
    --ids-file $OUT/smoke/checks/judge_ids_$a.json --gt v2 --out $OUT/smoke/judge/${a}_r1.cov.json
done
```

smoke 的 `exp_meta.json` 記的是工作樹的 sha；改了程式要重跑 smoke 時，先刪掉 `$OUT/smoke`。

## 步驟 3：正式跑（commit ① 之後）

```bash
mkdir -p $OUT/logs && nohup bash $EXP/run_ba.sh > $OUT/logs/run_ba.log 2>&1 &
```

- 中止：`docker stop bible_rag_ba`。續跑：同一條指令；JSONL 先截到最後一個換行；判分輸出非空且 `.src_sha`
  等於現在的 ans 才跳過；`ba_prep.py` 會要求 HEAD、映像、Ollama digest 與輸入都沒變，`check` 會要求凍結檔不變。
  driver 沒有待跑的項目時直接結束，健康檢查或握手失敗時不寫任何行，所以續跑不會留下壞的 meta 行。
- 3.1 之後 `check --partial`（I0–I4）不過就停；3.3 `check` 不過也停，不會寫出凍結檔。
- I6 補跑（只補失敗的 (q, arm, rep)；BA_RUN 同步驟 2）：

  ```bash
  $PY -B $EXP/ba_analyze.py trim $OUT/gen.jsonl
  "${BA_RUN[@]}" generate --plan /in/checks/gen_plan.json --retrieval /in/retrieval.jsonl \
    --resume /in/gen.jsonl --retry-failed >> $OUT/gen.jsonl 2>> $OUT/logs/generate.log
  ```

  再重跑 run_ba.sh：3.6 重新匯出答案，答案有變的目錄 sha 不同，會整個目錄重判（其他目錄跳過）；
  `report` 也會拒收 `.src_sha` 與現在 ans 不符的判分檔。

## 輸出（prereg §11）

`questions.json batch_a.json force_ids.json exp_meta.json retrieval.jsonl gen.jsonl`、`smoke/`、`logs/`、
`checks/`（invariants[_partial]、subsets、mechanisms、overlap_eval3c、gen_plan、judge_ids_*、judge_order、freeze）、
`retr/{arm}/` 與 `retr/{arm}.k{5,6}.json`、`ans/{arm}_r{1..6}/`、`judge/`、`report/report.{json,md}`。
