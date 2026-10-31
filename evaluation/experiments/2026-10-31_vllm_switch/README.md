# generator 換 vLLM 的對拍（2026-10-31）

紀錄：`docs/records/2026-10-31_vllm_switch.md`。資料：store `reports/vllm_switch_20261031/`。

- `answer_check.py BASE_URL OUT_JSON`：smoke20 的 20 題 full 模式，檢查答案本身（錯誤前綴、`<0x`／thinking 外洩、是否中文）與 `services.llm`。
  `PYTHONPATH=packages scripts/.venv/bin/python evaluation/experiments/2026-10-31_vllm_switch/answer_check.py http://localhost:8000 out.json`
- `intent_run.py {vllm|ollama} OUT CONC [--ids F]`：backend 的 `classify_intent`，只換 provider（在 `backend/` 下以 `PYTHONPATH=.:../packages .venv/bin/python` 執行）。
- `compare_intent.py`：vLLM 兩次 × step2 的 Ollama graph 臂 intent。
- `gen_run.py {vllm|ollama} OUT CONC --ids subset100.txt`：10-26 graph 臂的 context blocks 經 `build_messages`，照 `generate_answer` 的參數生成。
- `score_cov.py OUT GEN...`：正式 eval 的 `compute_coverage`（Haiku 5.5），在 `evaluation/` 下以 `PYTHONPATH=. .venv/bin/python -B experiments/2026-10-31_vllm_switch/score_cov.py …` 執行。
