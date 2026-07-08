# docs/ 文檔地圖

依文檔生命週期分四類；找「系統現在長什麼樣」一律從 [ARCHITECTURE.md](ARCHITECTURE.md) 進入。

| 位置 | 性質 | 更新規則 |
|------|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 全景架構（樞紐，文檔索引見其 §10） | 隨系統演進更新 |
| [build_database.md](build_database.md) | 建庫 runbook（Step 1–10，含 curated 重放鏈） | 隨管線演進更新 |
| [kg_optimization_progress.md](kg_optimization_progress.md) | KG 優化單一入口（P0–P3 狀態、指標演進） | 活文件 |
| `records/` | 執行／決策／驗證紀錄，檔名帶日期（`YYYY-MM-DD_主題.md`，與 `paper/record/` 同慣例） | **不可變**：只新增、不回改 |
| `archive/` | 被取代的歷史架構快照 | 不再更新，僅供考古與論文對照 |
| `reference/` | 評估參考資料（RAG 指標方法論筆記、100 題人讀版） | 題庫以根目錄 `ground_truth.json` 為準 |

論文素材（發現層級 F1–F9）另見 [`paper/record/`](../paper/record/README.md)——docs 記「做了什麼、怎麼做」，paper/record 記「發現了什麼、怎麼寫進論文」。
