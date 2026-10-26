# Round 3 三組態 500 題存檔（2026-09）

`results_graph/`、`results_no_graph/`、`results_semantic/` 是 Round 3 的 run of record（commit d248f18，
論文 Round 3 章節用）：legacy build、舊圖譜策略全開，現行 backend 已無法重現，只能用 legacy 映像。
2026-10-26 從 `evaluation/results_*/` 原樣搬來，讓 `run_eval.py --graph` 等指令的預設輸出目錄可以給新 run 用。
`paper/tools/replay_routes.py` 從 git 的 d248f18 讀這份資料，不讀這裡。
