# 事前登記：R1 語料切換的檢索非劣性（G-NONINF）與答案端守門（G-ANS）

- **登記時間**：2026-10-08。在 R1 臂（:8002）的任何 500 題檢索或答案端結果產生之前固定。legacy 臂的檢索 A/A 與本檔同時開跑；δ 的公式先固定，數值等 A/A 跑完才算出。
- **依據**：設計書 v1.1 §8 G-NONINF、G-ANS，§13 P4。本檔把設計書沒寫死的定義補齊（雜訊帶 B、MRR 勝負判準、切片清單、200 題子集）。
- **重跑上限**：任一臂最多重跑 2 次，而且只限基礎設施失敗（invalid、HTTP 錯誤、judge 失敗）。看到 R1 結果後不改門檻、不換對照、不加減題。

## 臂與共同設定

| 臂 | 位置 | 映像 | 資料 |
|---|---|---|---|
| 對照 L | :8001 `bible_rag_backend_cand` | `bible_rag-backend:e0b` | legacy-20261004（public schema、`bible_embeddings*`） |
| 處理 R | :8002 `bible_rag_backend_r1` | `bible_rag-backend:r1` | `b20261008_6daa4f31` |

- GT v2（`ground_truth.v2.json`，sha `7280bb42…`，slot_universe `text@247eafe44b02`）。兩臂都用 GT v2 凍結的節位宇集計分。
- backend 預設設定（不覆寫 graph 策略、α），`retrieval_only`，top-k 5，metric-k 6，concurrency 3。
- 兩臂共用同一個 Ollama（intent 與生成），所以各臂依序跑，不並行。
- 配對單位是題。任一臂 invalid 的題從配對中剔除並列出；若剔除後少於 495 題，該臂重跑。
- bootstrap：以題重抽，percentile 95% CI，B=10,000，種子 20261008。

## 檢索（G-NONINF，500 題）

1. **A/A**：對照臂連跑兩次，記為 L1、L2。
   - 雜訊帶 B = max(|下界|, |上界|)，取 Δvrec@6（L2 − L1）的 95% CI。
   - **δ = max(0.02, 2B)**。
   - MRR 勝負的雜訊帶 B_wl =（L2 對 L1 的 MRR 勝題數 + 敗題數）/ n。**δ_wl = max(0.02, 2·B_wl)**。
2. **R1 對 L1**（對照固定用 L1）。三條全部成立才通過：
   - **C1**：Δvrec@6（R − L1）的 95% CI 下界 > −δ。
   - **C2（MRR 勝負）**：逐題 s_q = sign(MRR_R − MRR_L1)，mean(s_q) 的 95% CI 下界 > −δ_wl。另報 ΔMRR 平均與 CI、勝/敗題數、精確 sign test p（只報告）。
   - **C3（受損切片）**：切片 64 題的平均 Δvrec@6 ≥ 0，並報告 CI。
3. **只報告**：題型、family、legacy_head 與擴充題分層；anchor_coverage、hit；兩臂路由不同的題數（A/A 與 R1 各報）；Δvrec@6 ≤ −0.3 的題逐一列出供診斷。

## 受損切片（凍結於 `frozen_r1.json`）

由 `freeze_r1.py` 從文字層 `text@247eafe44b02` 的 `diff_vs_bible_md.tsv` 與 GT v2 機械導出，不看任何檢索結果：

- **G01**（轉換器丟字）：`converter_*` 類、kind=unit 的 335 個節位（268 節缺字，加 67 節只缺「（細拉）」），gold_slots 有交集的題，56 題。
- **G15**（節中標題、半節）：`converter_midverse_heading` 的 18 個節位，gold_slots 有交集的題，11 題。
- **G02**（人工異文）：`hand_edit_ghost_verse` 10 個幽靈節，加 `hand_edit_variant_merged` 10 節；gold_slots 或 omitted_slots 有交集的題，9 題。
- 聯集 64 題。三個子切片分開報告，但只有聯集用於 C3。
- 設計書寫的是「55–57 題、11 題、9 題」，與本次導出一致。

## 答案端（G-ANS，200 題子集）

- **子集**（凍結於 `frozen_r1.json`）：依 question_type × {legacy_head, 擴充題} 分層。每個題型各取 8 題 legacy_head 和 32 題擴充題，共 200 題。層內取 sha256(`r1-gans-200|{question_id}`) 最小者。
- **收集**：對照臂兩次（A1、A2），處理臂一次（R）。backend 預設設定、`include_context`（生成器同款 context 區塊），生成模型 gemma4:e4b（backend 設定，temperature 0.1）。
- **評分**：`quick_faithfulness_eval.py`（zh 與 strict 兩個 judge 共用陳述拆解），judge 為 ollama `gemma4:26b-a4b-it-q8_0`，與 2026-09-17 量尺修復的基線相同。
- **判準**：
  - B_ans = max(|下界|, |上界|)，取 Δstrict（A2 − A1）的 95% CI。**δ_ans = max(0.01, 2·B_ans)**。
  - 通過條件：Δstrict（R − A1）的 95% CI 下界 > −δ_ans，而且三臂 n_invalid（未判出、生成失敗）都是 0。
- **只報告**：各臂 strict 絕對值（參考線 0.97）、zh faithfulness、coverage（Round 3 的雜訊地板是 |Δ| 0.060）、拒答數。

## 決策

- G-NONINF 與 G-ANS 都通過 → 進行 R1 上線（`ragdata promote --env prod`）。
- 任一條不通過 → 不上線，先診斷原因再回報 Kay。不能用放寬門檻或換子集的方式重判。
