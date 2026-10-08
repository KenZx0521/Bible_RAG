# docs/ 文檔地圖

找「系統現在長什麼樣」從 [ARCHITECTURE.md](ARCHITECTURE.md) 進入；要建資料、載入或切換 build，看 [rebuild_pipeline.md](rebuild_pipeline.md)。

| 位置 | 性質 | 更新規則 |
|------|------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 全景架構：語料、ragdata 各層、release／build、loader 與握手、線上檢索、KG 範圍、評估、舊結果的適用範圍（文件索引見其 §12） | 隨系統演進更新 |
| [rebuild_pipeline.md](rebuild_pipeline.md) | 重建管線操作手冊：`pipeline run`、各層閘門、推導檔、promote／回滾、unload、四套測試 | 隨管線演進更新 |
| `records/` | 執行、決策、驗證紀錄，檔名帶日期（`YYYY-MM-DD_主題.md`，與 `paper/record/` 同慣例） | **不可變**：只新增、不回改 |
| `archive/` | 被取代的歷史架構快照 | 不再更新，僅供考古與論文對照 |
| `reference/` | 評估參考資料：RAG 指標方法論筆記、原 100 題人讀版 | 題庫以根目錄 `ground_truth.json`（v1）與 `ground_truth.v2.json`（v2）為準 |

## 與現行系統直接相關的紀錄

| 紀錄 | 內容 |
|------|------|
| [records/2026-10-08_rebuild_handoff.md](records/2026-10-08_rebuild_handoff.md) | 分層重建的交接：Kay 的決定、資料與服務現況、已驗證結果、下一步、陷阱。新 session 從這裡開始 |
| [records/2026-10-07_e0_notes.md](records/2026-10-07_e0_notes.md) | E0a（sparse 退役）與 E0b（查詢端 tokenizer 修正） |
| [records/2026-10-03_graph_auxiliary_review.md](records/2026-10-03_graph_auxiliary_review.md) | 圖譜輔助化審查：事件註冊表附加槽的依據 |
| [records/2026-10-03_graph_benchmark_validity_audit.md](records/2026-10-03_graph_benchmark_validity_audit.md) | 圖譜 benchmark 效度審查 |

`records/` 裡 2026-10-07 以前的 KG 優化與補丁批次紀錄（P0、排序融合層、第 0 批、W0、W1 等），描述的是已退役的 legacy 系統，只供歷史對照。

## store 上的文件

重建設計書與稽核報告不在 repo，放在 store `/mnt/ollama-data/bible_rag_store/reference/`：

- `DESIGN.md`：設計書 v1.1，含 D 編號決策與閘門定義；
- `REPORT.md`：2026-10-07 稽核報告。

## 其他位置

- 評估框架與工具：[`../evaluation/README.md`](../evaluation/README.md)。
- 論文素材另見 [`paper/record/`](../paper/record/README.md)：docs 記「做了什麼、怎麼做」，paper/record 記「發現了什麼、怎麼寫進論文」。Rounds 0–3 的適用範圍見 [ARCHITECTURE §10](ARCHITECTURE.md#10-舊結果的適用範圍)。
