# 第 0 階段:量尺修復執行紀錄(經節級檢索指標 + 主指標定案)

> **日期**:2026-07-13
> **依據**:[2026-07-13_eval500_analysis_and_rag_architecture.md](2026-07-13_eval500_analysis_and_rag_architecture.md) 第六節「第 0 步:修量尺」
> **範圍**:僅評估管線(`evaluation/`),未動 backend、未動 ground_truth.json、未改寫任何歷史結果檔。

---

## 決策(Kay 拍板)

**主指標 = `answer_coverage`,faithfulness 守門;`ragas_answer_correctness` 附 ~0.78 天花板校正僅作參考。**

理由:coverage 與 ac 對答案長度偏好相反(ac 懲罰詳盡,r=-0.477),不可同時最大化;coverage 是純 recall LLM judge,「該講的講了沒」與系統目標一致。後續生成端 prompt A/B 以 coverage↑ 且 faithfulness 不降為成功判準,**ac 同步下降屬預期量尺性質,不算退步**。

## 改動清單

### 1. 新增經節級檢索指標(核心)

`evaluation/src/verse_coverage.py`(新檔):把 GT reference 與檢索 source 都展開成明確經節集合(每章節數來自 `output/chapters.jsonl`,確定性、無 LLM):

- **`verse_recall_at_k`** = |檢回經節 ∩ gold 經節| / |gold 經節| — 取代灌水的 recall 作為檢索主讀數
- **`anchor_coverage_at_k`** = 命中的章級錨點 / 全部章級錨點(「馬太 5-7 章」= 3 個錨點,多錨題要湊齊才滿分)

接入點:`src/metrics/retrieval.py` `_compute_for_sample()` — **`run_eval.py` 全管線與 `quick_retrieval_eval.py` 快速迴路同時生效**。舊 7 指標(hit/recall/ndcg/...)保留供歷史對照,`estimate_total_relevant()` docstring 已加灌水警語。

### 2. reference parser 修復

- 跨章節範圍 `1:17-2:10` / `21:1-22:5`:原本 fallback 成**整卷**,現展開為「首章尾段 + 中間整章 + 末章頭段」(`to_chapter_end` 欄位)。受影響 GT:GENERAL_015(約拿書)、GENERAL_018(啟示錄)共 2 題。
- `120-134篇` 章範圍接受「篇」後綴(防詩篇題未來踩雷;現有 GT 無此格式)。

### 3. 評估管線小修

- `family` 欄位不再被 pydantic 丟棄:進 `evaluation_results.json` 樣本、CSV 新增 family 欄、新增 **`by_family` 聚合**(legacy 100 題歸 `legacy_head`,共 20 組);console 加 per-family 關鍵指標表。
- `evaluation_results.json` 新增 **`meta` provenance**:timestamp、n_samples、top_k、judge_provider、judge_model、ragas_version、results_dir(解決「結果檔無 judge 紀錄」問題)。
- RAGAS 鎖版 `ragas==0.4.3`(原 `>=0.2.0`,可重現性風險);pytest 進 dev group。
- dashboard `RETRIEVAL_METRICS` 把 verse 指標排最前。
- `quick_retrieval_eval.py`:`_METRIC_ORDER` 以 vrec/anch 領頭;compare/print 對舊結果檔缺欄位容錯;新增 verse_recall movers(|Δ|≥0.3)清單。

### 4. 測試

`evaluation/tests/`(新):25 個 pytest(parser 9 + verse_coverage 16),全過。含 EVENT_011 型灌水修復回歸測試(111 節撈 6 節 → vrec 0.054 而非 recall 1.0)、越界經節夾制、跨章展開。

## 驗證(用既有 07-12 的 500 題 raw_responses 重算,零 LLM 成本)

| 驗證項 | 結果 |
|---|---|
| overall verse_recall | **0.751**(四-agent 分析報告 0.7499 ✅) |
| EVENT_011 登山寶訓 | vrec **0.0541** = 6/111(報告 0.054 ✅;官方 recall 仍 1.0) |
| PERSON_001 創 12-35 | vrec **0.0108** = 8/742(報告 0.011 ✅) |
| TOPIC_062 詩 120-134 | vrec 0.0693(sql 抓詩 119 的病灶如實現形) |
| 弱家族逐一對照 | trajectory 0.3495↔0.350、multi_chapter 0.3742↔0.374、disambiguation 0.4397↔0.440、temporal 0.419、nt_quotes_ot 0.5911、longtail_book 1.0 — **全部與報告吻合** |
| 舊指標漂移 | **僅 GBQ_015/018 兩題**(parser 修復的預期修正,整卷寬鬆→精確);其餘 498 題 bit-exact |
| by_type overall | vrec:VERSE 0.960 > TOPIC 0.815 > EVENT 0.750 > GENERAL 0.634 > PERSON 0.596 |

存檔:`evaluation/results_quick/verse_metric_validation.json`(含逐題數值,可當後續 A/B 基線)。

## 之後怎麼讀數字

1. **檢索迭代**:看 `verse_recall_at_k`(廣度)+ `anchor_coverage_at_k`(多錨湊齊),hit_rate/recall_at_k 只做歷史對照。基線 = `verse_metric_validation.json`(0.751/0.784)。
2. **端到端**:主指標 `answer_coverage` + faithfulness 守門;ac 除以 ~0.78 天花板後再解讀。
3. **家族診斷**:直接用結果檔 `by_family`(20 組),不用再手動 join GT。

## 第 0 階段殘餘(未做)

- **GT 要點審計**(63% 機械化 5 要點、要點寬於題幹 ~17.6% 假失分)— 獨立工作項,建議先審低分題中評分端的 29 題。
- coverage judge 與 RAGAS judge 溫度不一致(0.0 vs 0.3)— 觀察項,暫不動。
