# Ground Truth 擴充至 500 題(2026-07-11)

## 背景與動機

2026-07-06 排序融合修復後,100 題 benchmark 飽和(overall hit 0.97、VERSE/TOPIC/EVENT hit=1.00),殘餘 3 miss 均屬需要新架構的家族。當時的策略結論為**「量尺先於系統」**:在現有 100 題上,P1(長尾重抽)、P2(事件層)、P3(RAPTOR/跨章彙總)做完讀數都會近零 — 必須先擴充評估設計,涵蓋長尾/時序/跨章彙總/跨卷雙錨四族,才能讀出後續建圖與檢索投資的效益(參 `2026-07-06_kg_p0_eval_p1_decision.md` §4.3 重啟條件)。

本次依此結論將 `ground_truth.json` 從 100 題擴充至 **500 題(每型 100)**。

## 設計原則

1. **原 100 題一字未動**(各型 `*_001-020`,metadata 標記 `family=legacy_head`),可作跨輪可比子集;新舊讀數可用 `--only` 前綴或 family 欄位切片。
2. 新 400 題(各型 `*_021-100`)每題帶 **`family` 欄位**(pydantic loader 對多餘欄位安全忽略,已冒煙驗證),共 19 個診斷家族,每族 n≥8 避免 n=2 過擬合。
3. 題目必須**語料內可答**(以 `output/pericopes.jsonl` 為唯一權威),但**現系統可能失敗**——為排序層、實體層、彙總層的改善預留讀數空間。
4. `reference` 全部通過 `evaluation/src/reference_parser.py` 實際解析驗證;計分單元(recall 分母)1–5,不超過 top_k=5。
5. 新題 reference_answer / expected_answer_points 用語對齊語料譯本(**上帝版和合本 + RCUV 式專名**),降低 answer 端字面失配噪音。

## 家族配額(400 新題 → 19 族)

| 題型 | 家族(n) | 診斷對象 |
|---|---|---|
| VERSE_LOOKUP +80 | longtail_book(48)、head_cold(14)、paraphrase(18) | 48 個未覆蓋書卷(擴充後 66 卷全覆蓋)、頭部書卷冷門段、**無出處反查**(不含「根據X:Y」,繞過 R1 直測語意/稀疏檢索) |
| TOPIC +80 | longtail_chapter(35)、multi_chapter(25)、head_cold(20) | 長尾章主題、**書內跨章彙總**(僕人之歌/五大講論/約伯三友等,P3 對症) |
| PERSON +80 | longtail_person(30)、disambiguation(12)、title_coref(12)、trajectory(18)、split_pericope(8) | 長尾人物(米非波設/利斯巴/戶勒大/以伯‧米勒等)、**同名消歧**(三亞拿尼亞/希律家族/兩掃羅,對症 entity_dict 消歧 bug)、**稱謂式問法**(不出人名,對症 coref 缺口)、跨章人物軌跡(PERSON_004 家族化)、被切塊 pericope(exo:18 型) |
| EVENT +80 | longtail_event(34)、temporal(16)、surface_form(16)、parable(14) | 長尾事件、**時序題**(P2 事件層對症)、**表面形式斷裂**(主禱文/十架七言/棕枝主日等現代標籤 vs 經文用語,對症 reranker 字面 match + aliases) |
| GENERAL +80 | prophecy_fulfillment(26)、nt_quotes_ot(16)、typology(12)、parallel_account(14)、theme_thread(12) | **跨卷雙錨家族化**(GENERAL_006/008 的 n=2 → n≥26,直測 TSK cross-ref 價值)、平行記載(王/代、符類)、3+ 錨主題貫穿 |

## 品質驗證(三層)

1. **出題前語料抽取**:全部 80 題 VERSE + ~115 個 GENERAL 錨點經節逐節抽原文後才成題;PERSON/EVENT 章節切塊結構逐章確認。
2. **機械校驗**(`scratchpad/validate_new_gt.py`):400/400 reference 可解析、book/chapter/verse 全部存在、ID 連續無衝突、單元數≤5 — 僅 1 處逗號解析陷阱(`26:31-35, 56` 的 56 被讀成第 56 章)出題時即修正。
3. **4 個並行 agent 全量逐題內容查核**(每題型 80 題全查,合計 ~90 萬 subagent tokens):確認並修正 **49 處**問題 — 內容/歸屬錯誤 17、直接引句與語料一字之差 22、語料未收之譯註/字級問題 10。

### 查核發現的語料特性(對未來出題/別名工作重要)

- 專名採 RCUV 式新譯:**呂便**(非流便)、**塞魯士**(非古列)、**大流士**(非大利烏)、**米底亞**(非瑪代)、**尼哥德慕**(非尼哥底母)、**伊利莎白/友妮基/百妮基/克勞第/克里特/馬耳他/幼發拉底河**;複合名帶「‧」(古珊‧利薩田、隱‧基底、以伯‧米勒、士求‧保羅)。
- 用字:**凶惡/凶殺**(非兇)、**燒毀**(非燒燬)、**糠詷**(非糠秕)、它(創4:7 非牠)、剃頭刀(非剃刀)。
- **詩篇篇題(superscription)未收錄**:「上行之詩」「大衛的詩」「亞薩的訓誨詩」等歸屬無法由語料支持 — 題目若需此類標籤須自帶說明。
- **民數記 24:17 星預言正文在語料中缺漏**(僅存「我看他卻不在現時;」)— 已從相關題移除該引句;此為語料品質問題,可另行修補。

## 產出

- `ground_truth.json`:500 題,metadata 含 `families` 分布與 expansion_note。
- `docs/reference/test_questions.md`:mirror 全量重生(500 題,含 question_id/family 欄位)。
- 原 100 題備份:git 歷史 + scratchpad `ground_truth.json.bak_100q`。

## 後續建議

1. 先跑 `evaluation/quick_retrieval_eval.py --label expansion_500_baseline` 建立 500 題檢索基線(retrieval-only,分鐘級);預期 legacy_head 子集維持 ~0.97,新家族(尤其 paraphrase / longtail_person / temporal / prophecy_fulfillment)顯著低於頭部 — 這個「落差」正是量尺的讀數空間。
2. per-family 切片:`results_quick/*.json` 的 per_question 已含 qid,依 family 聚合即可(family 在 gt json 內)。
3. 讀數解讀基準:雙錨題 recall=0.5 表示只找到一邊錨點(TSK 1-hop 擴展的直接讀數);paraphrase 家族 hit 低 → 稀疏/語意層;title_coref 低 → 圖譜 coref/aliases;temporal 低 → P2 事件層。
4. RAGAS/coverage 全管線(2.5h 級)建議在 quick eval 定位改善點後再跑。
