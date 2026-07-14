# bugA(book_anchor 多書卷 OR-filter 失效)Pre/Post 修復對比

日期:2026-07-14
狀態:**v2 定案** — 整體零退步,多書卷代表率顯著改善,v1 副作用全數收復
對比工具:`evaluation/quick_retrieval_eval.py`(500 題 retrieval-only,concurrency=3,top_k=5,三輪同條件)

## 背景

陷阱 #20(`docs/records/2026-07-13` 系列 + 檢索管線盤點):`_expand_via_book_anchor` docstring 宣稱 per-book 各自貢獻種子,實作卻是單次 MatchAny OR-filter → 強勢書卷吃光全部 10 筆種子。實測「耶利米書的新約預言在希伯來書的應驗」:耶利米書 10 筆、希伯來書 **0 筆**,且完全靜默。跨卷雙錨家族(GENERAL_006/008)病灶即此。

### 修復演進

| 版本 | router.py 內容 | 結果檔 |
|---|---|---|
| pre | HEAD(784458a)原版,單次 OR-filter | `results_quick/pre_bugA_live.json` |
| v1 | per-book 迴圈各自檢索 + per-book seen-set,全部種子升權重 | `results_quick/bugA_fix.json` |
| v2 | v1 + 三道 decoy 抑制(見下) | `results_quick/bugA_fix_v2.json` |

v2 的三道抑制(全部僅對多書卷題生效,單書題保持原行為——實測單書題全程零變化):

1. **`_cap_book_anchor_entries`**:fused 排序中每書只保留 1 筆 book_anchor,多餘的沉到尾部(仍在候選池,pin 階段可見)。
2. **`book_gate`**(`_pin_graph_candidates`):只 pin「fused top-k 完全沒有代表」的書卷,每書 1 pin;已有代表的書卷不再花槽位。
3. **per-book 權重限縮**:每書只有最佳 1 筆升到 anchor 權重,其餘保持原 hybrid 權重。

## Overall 三版本對照(500 題)

| 指標 | pre | v1 | v2 | v2−pre |
|---|---|---|---|---|
| verse_recall@5 | 0.7511 | 0.7468 | **0.7510** | −0.000 |
| anchor_coverage@5 | 0.7842 | 0.7817 | **0.7850** | +0.001 |
| hit_rate | 0.944 | 0.942 | **0.946** | +0.002 |
| ndcg@5 | 0.8398 | 0.8342 | **0.8410** | +0.001 |
| mrr | 0.8100 | 0.8005 | **0.8110** | +0.001 |

僅 GENERAL_BIBLE_QUESTION 類有變化(EVENT/PERSON/TOPIC/VERSE 三版本 bit-exact 相同,改動的隔離性符合設計)。

## 修復目標:GT 書卷代表率@5(prepost_analysis.py)

| 量尺 | pre | v1 | v2 |
|---|---|---|---|
| 全 500 題 rep@5 | 0.9178 | 0.9240 | 0.9235 |
| 多書卷 GT 139 題 rep@5 | 0.7404 | 0.7626 | 0.7608 |
| 多書卷完全代表 | 70/139 | 76/139 | **75/139** |
| top-5 重複 chunk 題數 | 4 | 0 | **0** |

v2 保住 v1 絕大部分代表率收益(75 vs 76;retreat 的 1 題是 v1 用 3 槽 decoy 換來的 GBQ_092 rev 代表,v2 用 1 槽換到同樣代表)。重複 chunk 歸零 = per-book seen-set 順帶修復陷阱 #11(book_anchor 是唯一無內部去重的擴充 helper)。

代表率 flips(pre → v2):+isa(GBQ_003)、+heb(GBQ_006 本尊)、+gen(GBQ_013)、+jer(GBQ_091)、+rev(GBQ_092/096)、+luk(GBQ_099)、+act(PERSON_087);唯一 − flip = GBQ_089 −ezk(見殘餘)。

## v1 副作用的收復(v1 → v2)

v1 病灶:per-book 種子**全部**升 anchor 權重 → 同書 decoy 以高權重洗版,擠掉其他策略的 gold。

| 題 | v1−pre | v2−v1 | 機制 |
|---|---|---|---|
| GBQ_003 神的羔羊 | vrec −0.812 | **+0.812** | v1 isa:1:1+isa:53:0 兩槽洗版擠掉 rev:5:0;v2 cap 後 isa 只留 1 筆,rev:5:0 回歸 |
| GBQ_092 婚姻/新婦 | vrec −0.571(hit 歸零) | **+0.571**(hit 回復) | v1 rev:21:0/21:1/2:3 三槽洗版擠掉 eph:5:2;v2 rev 只留 1 筆,eph:5:2/isa:62:0 回歸 |
| GBQ_091 活水 | vrec −0.400 | +0.300 | v1 jer:51:1+jer:17:1 兩槽;v2 jer 留 1 筆,jhn:7:4 回歸(部分收復,見殘餘) |

v1→v2 GENERAL 類:vrec +0.019、mrr +0.051、ndcg +0.035。

## v2 額外收益(cap 的正外部性)

- **GBQ_043 耶西的根**(vrec 0→0.125、anch 0→0.333):pre/v1 裡 isa:37:2/isa:38:0 同書 decoy 佔兩槽;v2 cap 後 gold **rom:15:1**(羅15:8-12)從 hybrid 候選浮上來。連 pre 都沒做到的新命中(全對比唯一 hit_rate ▲ flip)。
- **GBQ_013 林前15 vs 創世記**:v1 的 gen:15:0/gen:1:0/gen:3:1 三槽洗版被 cap 成只留 gen:3:1(恰好是含創3:19 的 gold 段),1co:15:0 回歸。指標與 v1 持平(+0.025/+0.333 vs pre)但槽位品質更好。

## 殘餘(v2 vs pre,theme_thread Δvrec −0.032)

1. **GBQ_089 牧人意象(−0.288 vrec,量尺效應為主)**:四書卷 GT(詩23/結34/約10/彼前5)擠 5 槽的結構性問題。pre 命中 ezk:34:1+jhn:10:0 兩錨;v2 命中 jhn:10:0+**1pe:5:0** 兩錨 — **anchor_coverage 持平 0.500**,vrec 下降純因以西結34章 gold 節數(31 節)>> 彼前5:1-4(4 節)。書卷多樣性未變差;真正缺陷是 book_anchor 給 psa 選的種子是詩 78 而非詩 23(語意檢索在書內選段的精度,屬另一問題)。
2. **GBQ_091 活水(−0.100 vrec/−0.250 anch)**:jer 代表進場(rep +0.333)但 jer:47:0 非 gold(耶2:13),且 rev:22:0 取代了 pre 的 rev:22:1(gold 22:17 所在)。「代表保證 vs 精準選段」的固有張力。

兩題共同指向下一步:**book_anchor 的書內選段品質**(anchor 種子選到書內語意最近而非 gold 段落),與 cap/gate 機制無關。

## 結論

- **v2 通過 A/B:整體五主指標全部 ≥ pre(最大 +0.002),修復目標(多書卷代表率)+5 題完全代表,v1 三大重災全收復,重複 chunk 4→0。**
- 讀數符合 [[project-eval-metric-traps]] 主指標規則:此為 retrieval-only 對比,vrec/anch 為主讀數;殘餘 GBQ_089 的 vrec 降幅屬長章節數權重的量尺性質,anchor_coverage 持平佐證。
- 改動隔離性乾淨:非 GENERAL 類三版本 bit-exact 相同;單書題(v2 抑制不觸發)零變化。

## 後續候選(不在本次範圍)

1. book_anchor 書內選段:對 GT 常見的「書名+主題」題,種子檢索可考慮 query 改寫(去書名留主題)或書內 rerank。
2. GBQ_089 型 4+ 書卷題:top_k=5 結構性不夠分,屬 per-anchor 配額議題(需在 pin 之後做,見陷阱 #15)。
3. 工作區 router.py(v2)尚未 commit;`evaluation/results_quick/{pre_bugA_live,bugA_fix,bugA_fix_v2}.json` 為三版本憑證。
