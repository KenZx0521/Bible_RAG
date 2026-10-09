# R2 上線核可（2026-10-09）

依 `evaluation/experiments/2026-10-09_r2/prereg.md`（commit 974e760 凍結切片與腳本），R2 build `b20261008_e05d3e55`、映像 `bible_rag-backend:r2`（`sha256:c79266296cb0…`）。

| 閘門 | 結果 | 憑證 |
|---|---|---|
| G-EVENT、G-ROUTE（建置） | 通過 | `reports/pipeline_r2_load.json` |
| G-NONINF | **PASS**：C1 Δvrec@6 +0.0002 [−0.0016, +0.0026]；C2 ΔMRR −0.0012 [−0.0041, +0.0012]（δ_mrr 0.02）；C3 路由改變切片 34 題 +0.0076 | `gate_retrieval.json` |
| G-ANS | **PASS**：Δstrict（R2 − A1）+0.0153 [+0.0024, +0.0309]，δ_ans 0.0434，三份 n_invalid 0；strict R2 0.9905、A1 0.9752；coverage +0.0019 | `gate_answer.json` |
| G-HELDOUT | **SIGNOFF**（觸發 13 題 < 30，描述性）：R2 精確率 11/13 = 0.846（R1 9/11 = 0.818）；配對 R2 勝 2（w1_008、w1_017）敗 0；兩臂同錯 w1_031、w1_038（金牛犢、逾越節的近似負例）；召回 R2 11/43、R1 9/43，32 題沒有任何觸發字串 | `gate_heldout.json` |

**Kay 2026-10-09 裁決：簽核 G-HELDOUT，核可 R2 上 prod。**

已知限制（不擋上線）：事件附加槽只認字面觸發詞，盲寫正例的召回約 1/4；要提高召回需要新增觸發詞，屬於另一次觸發詞變更，要用新的 held-out 題驗收。
