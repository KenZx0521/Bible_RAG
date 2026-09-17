# Faithfulness(幻覺指標)體檢:評估太嚴還是模型沒答好?

日期:2026-09-10
資料:`evaluation/results_graph/`(2026-07-15 run of record,500 題;answer = gemma4:e4b-it-q8_0 temp 0.1;judge = gemma4:26b-a4b-it-q8_0;RAGAS 0.4.3)
狀態:分析 + 兩個實驗完成(2026-09-10);**§7.1 量尺修復已於 2026-09-17 實作**(見 §8)。憑證檔在 `evaluation/results_quick/faith_audit_2026-09-10/`。

## 0. 一句話結論

faithfulness 0.912 的 8.8% 缺口,約四分之三是量尺問題,不是模型捏造經文。主因是 **judge 拿到的 context 少了生成器看到的標頭**(書卷/章/節/段落標題),於是 SYSTEM_PROMPT 規則 2 強制要求的「根據約翰福音第3章第16節」這類出處句被判成「無法從 context 推得」。補回標頭重評,141 題非滿分題平均從 0.688 升到 0.931,推估全體 0.912 → 0.979;再把殘餘否定判定逐條人工分類,只算模型真錯誤時全體約 0.994。真正的生成端錯誤集中在 PERSON 類敘事題的**人物/角色綁定**(以利寫成以利亞、父子關係反向、說話者與聽者對調),約 5% 的題目含至少一句,佔陳述句的 2%。

## 1. 現況讀數(stored run)

| 切面 | faithfulness | 備註 |
|---|---|---|
| overall(n=499 valid) | 0.9119 | 358 題 =1.0、39 題 0.9-1、33 題 0.8-0.9、42 題 0.5-0.8、19 題 0-0.5、8 題 =0 |
| VERSE_LOOKUP | **0.859**(最低) | 檢索 vrec 0.96、coverage 0.88 全場最好,faithfulness 卻最低 |
| GENERAL_BIBLE | 0.858 | |
| TOPIC | 0.969 | |
| route R1(單節 context) | 0.888;5 題 =0 | 5 題 0 分全部 coverage=1.0、vrec=1.0 |
| 答案 <300 字 | 0.863 | ≥600 字 0.980:**越長越「忠實」**,與真幻覺方向相反 |
| 問「出自哪裡/哪卷書/哪幾位」的題(n=54) | 0.803 | 其他 445 題 0.925 |
| 家族最低三名 | paraphrase 0.741 / nt_quotes_ot 0.750 / disambiguation 0.762 | 全是答案必須寫出處的家族 |

缺口分解:總缺口 44.0 題當量,f<0.8 的 69 題貢獻 36.3(83%)。faithfulness 與 coverage r=0.09、與答案長度 r=+0.22。

## 2. 病灶一:judge 的 context 沒有標頭(主因)

- 生成器(`backend/utils/generator.py:_build_context`)看到 `[1] 啟示錄 第3章 - 標題 (20節)\n20. 看哪,我站在門外叩門…`。
- 評估端(`evaluation/src/collector.py` → `content_fetcher.fetch_contexts`)只拿 source id 回 PostgreSQL 撈 `content`,**標頭全部丟掉**;500 題 0 題的 judge context 含書卷名。
- RAGAS faithfulness = 把答案拆成 statements → 逐條 NLI 問「能否由 context 直接推得」。「根據啟示錄第3章第20節,耶穌說…」拆出的 statement 含書卷/章/節/說話者,judge 找不到就給 0。
- 鐵證 VERSE_LOOKUP_017(啟3:20):答案逐字正確、cov 1.0、vrec 1.0,faithfulness **0.0**;judge 理由:「context 沒有明說 Revelation / Chapter 3 / Verse 20 / Jesus / Laodicean」。同型 0 分:VERSE_LOOKUP_030/067/071/076/096、GENERAL_057/100。
- 短答案受害最重:3 句 statements 裡 1 句是出處 → 0.667。這就是「答案越短 faithfulness 越低」與「問出處的家族最低」的來源。
- 同一 judge 對同型答案並不一致:VERSE_LOOKUP_001/005/008/009/010/012 的出處句被放行(理由寫「雖然沒標書名,但內容吻合」),017/003/004/006/020 被判 0。

## 3. 病灶二:R1 經節 id 與 pericope id 撞名(小,但是真 bug)

`content_fetcher.get_content_by_id` 對三段式 id 先查 pericope 再退回單節。R1 單節 id `3jn:1:2`(約三 1:2)剛好也是「約翰三書第 1 章第 2 個 pericope」(13-15 節),judge 拿到**別段經文**,VERSE_LOOKUP_067 全 0。本次 500 題撞名 1 題(47 個 R1 單節 id 中);任何「小節號 + 多 pericope 章」都會再發生。後端 `Source.strategy` 已有 `verse_direct` 可判別,評估端沒用。

## 4. 病灶三:RAGAS 預設判準對這個任務的四處不合

1. **問題前提**:NLI prompt 只給 context + statements,**不給問題**。「耶穌對多馬說」的多馬、「所羅門向上帝求」的所羅門、「被擄之民」、「詩篇作者摩西」都來自題目,judge 一律判 0(VERSE_LOOKUP_019/026/030/069/071/076/067)。
2. **標題句、後設句**:「**耶穌的解釋:**」「提供的經文段落中未包含雅各書」被當事實陳述判 0 或「無法判定」(GENERAL_028/060/067/080、TOPIC_058、EVENT_008)。
3. **題目要求的歸納/比較**:「可分為三個階段」「兩者在『擴展到萬民』層面連結」「重大差別在存活人數」「預表」「呼應」被判「文本沒有這樣分類」(PERSON_077 一題 12 句全滅、GENERAL_004/007/013/015/020/097、TOPIC_061/068)。
4. **statement 拆解副作用**:RAGAS 要求 statements 不含代名詞,judge 把引句的「我/你/你們」改寫成人名再判「經文說的是尊敬我不是尊敬耶穌」(GENERAL_052 三句、GENERAL_041 兩句、GENERAL_067、PERSON_026/073)。
5. **溫度設定沒生效 + judge 本身不穩**:RAGAS 0.4.3 `LangchainLLMWrapper.generate()` 呼叫時把溫度覆寫成 0.01/1e-8,`langchain_factory.py` 設的 0.3 **實際沒有用到**(記憶中「judge temp 0.3」的說法應更正)。即便 greedy,同一題同 context 重判平均 |Δ|=0.106,180 題中 29 題移動 ≥0.2(49 題上升、18 題下降),因為 statements 每次拆得不同。

## 5. 重評分實驗(`refaith.py`)

設計:同一 judge 模型、greedy;statements 只生成一次,三種 NLI 條件共用。
- **orig**:stored run 的無標頭 context(重跑 = 量 judge 噪音)
- **hdr**:補回生成器標頭 + 修撞名,判準不變(RAGAS 英文預設)
- **hdr_zh**:hdr + 把問題給 judge + 繁中判準(出處對標頭即可、問題前提不算捏造、標題/後設句依正確與否、歸納句看組成事實、意譯可)

樣本:141 題非滿分 + 40 題滿分對照(seed 42),有效 180 題,2,199 條 statements。

| 子集 | stored | orig(重判) | hdr | hdr_zh | 只算真錯誤(人工分類) |
|---|---|---|---|---|---|
| 非滿分 141 題 | 0.688 | 0.758 | **0.931** | 0.976 | 0.980 |
| 滿分對照 39 題 | 1.000 | 0.987 | 0.998 | 0.999 | 1.000 |
| **全體 499 題推估** | 0.912 | 0.922 | **0.979** | 0.993 | 0.994 |

(全體推估 = 358 題滿分題按對照組均值 + 141 題實測。)

| 題型(非滿分子集) | n | stored | hdr | hdr_zh |
|---|---|---|---|---|
| VERSE_LOOKUP | 31 | 0.544 | 0.932 | 1.000 |
| GENERAL_BIBLE | 38 | 0.625 | 0.896 | 0.964 |
| EVENT | 25 | 0.740 | 0.972 | 0.996 |
| PERSON | 29 | 0.793 | 0.912 | 0.946 |
| TOPIC | 18 | 0.829 | 0.975 | 0.979 |

家族:paraphrase 0.417 → 1.000、nt_quotes_ot 0.600 → 0.947、longtail_book 0.553 → 0.925(hdr);PERSON 系家族(title_coref 0.861、trajectory 0.856、longtail_person 0.925)在 hdr 下仍最低,因為那裡是真錯誤。8 題 0 分題補標頭後 6 題回到 1.0,剩 2 題是「該猶/摩西」問題前提。

**hdr 條件殘餘 101 條否定判定(2,199 條中,4.6%)人工逐條分類**:

| 類別 | 條數 | 佔比 | 例 |
|---|---|---|---|
| 模型真錯誤 | 44 | 44% | 見 §6 |
| 題目要求的歸納/比較被判「文本沒說」 | 29 | 29% | PERSON_077 三階段 12 條、GENERAL_020 連結 3 條 |
| statement 拆解代名詞誤解 | 10 | 10% | 尊敬我→尊敬耶穌、你們→門徒 |
| 問題前提實體 | 8 | 8% | 該猶、摩西、大衛、登山寶訓 |
| judge 吹毛求疵 | 6 | 6% | 「不是欺哄人是欺哄上帝」判矛盾 |
| 標題句/後設句 | 4 | 4% | 「王國的分裂過程如下:」 |

hdr_zh 把後五類壓到剩 53 條(多為真錯誤),但對細微張冠李戴會漏判(GENERAL_071 亞伯→亞伯拉罕、GENERAL_039 補「彼西底的安提阿」兩題 hdr 與 hdr_zh 都給 1.0;stored run 抓到過一次)——judge 對真錯誤的召回不完美,兩種判準都一樣。

## 6. 模型真錯誤(22 題 / 44 句;PERSON 12、GENERAL 5、TOPIC 4、EVENT 1)

| 機制 | 例 |
|---|---|
| 相似人名混用 | PERSON_089 把撒上 4:18 以利之死寫進以利亞生平(檢索撈到的 decoy chunk 被綁到題目實體上) |
| 說話者/聽者對調 | PERSON_063 拔示巴告訴拿單(經文相反);PERSON_007 以利問哈拿為何哭(是以利加拿) |
| 父子/主從關係反向 | PERSON_061 「烏西雅是撒迦利雅的兒子」寫成「烏西雅的兒子撒迦利亞」×3;PERSON_078 「大衛的兒子亞希米勒」 |
| 動作/話語歸錯人 | PERSON_018 使徒和長老差西拉→寫成保羅巴拿巴;TOPIC_070 上帝的吩咐寫成耶利米的禱告;TOPIC_056 塞魯士是牧人→耶和華 |
| 數字/細節 | PERSON_035 二他連得→一他連得;TOPIC_081 先給山羊羔(是承諾) |
| 缺段硬湊 | GENERAL_077 沒撈到列王紀下就拿歷代志下 35 章跟自己比;EVENT_068 沒撈到創 22 把「獻以撒」寫成行割禮 |
| 比較題結論自相矛盾 | GENERAL_081 先說「順序相同」再列出不同順序,馬太順序寫錯 |
| 平行經文混用 | GENERAL_041 把馬可「我是」寫進馬太(馬太是「你說的是」) |
| 出處張冠李戴 | GENERAL_097 尼 10:35 的內容標成利 23:35 |
| 對 context 的錯誤後設宣稱 | TOPIC_079 「僅有詩篇 32」(還有 4 段);PERSON_013 「沒有大利烏」(末尾有) |

共同點:多段落敘事 + 人名密集;不是「亂編經文」,是**把 context 裡真有的句子綁到錯的人/方向**。這是 [[project-eval500-2026-07-12]] 多錨湊齊缺口的生成端投影。

## 7. 建議(不換模型)

### 7.1 先修量尺(P0;不修,後面任何生成端 A/B 都在噪音裡)

1. **context 對齊生成器**(根治):後端 `Source` 加 `content` 欄位(或直接回傳 `_build_context` 的字串),`collector.py` 不再回資料庫重抓;順帶消滅撞名 bug。退而求其次:`content_fetcher` 用 `Source.strategy == 'verse_direct'` 決定走單節,`collector` 組 `[i] 書卷 第N章 - 標題 (節)` 標頭。
2. **判準**:`ragas_eval.py` 用 `Faithfulness(nli_statements_prompt=ZhNLIPrompt())`(本次 `refaith.py` 版本可直接用),NLI context 前綴使用者問題;statement 拆解也換繁中版並要求「引句內的我/你/你們原樣保留」。
3. **同時報兩個數**:`faithfulness_strict`(標頭 + RAGAS 預設)當保守讀數、`faithfulness_zh` 當主讀數;結果檔存全部 statements/verdicts(現在只留前 5 條 reason,無法事後審計)。
4. **判準門檻**:faithfulness_strict ≥ 0.97 守門(對照組 0.998;真錯誤天花板約 0.994)。
5. **論文**:sec6 三張表的 faithfulness 列(0.957/0.951/0.899/0.903、0.9513/0.9564/0.9495)全是無標頭 judge 產物,系統性低估 0.06-0.08,VERSE_LOOKUP/GENERAL 分佈被扭曲;「faithfulness 0.90→0.95 propagates from retrieval」受答案引用密度干擾,重判後再定稿。
6. 記憶/文件更正:RAGAS judge 實際溫度 ≈ 0,不是 0.3。

### 7.2 生成端(P1;真錯誤天花板約 0.6 pp,但有便宜解)

Pilot(`pilot_gen.py`,22 題錯誤案例,生產模型、同 context):

| 版本 | faithfulness(hdr_zh) | coverage |
|---|---|---|
| stored 答案 | 0.910 | 0.543 |
| 同 prompt 重生成一次 | 0.960 | 0.539 |
| 加 grounding 規則的 prompt v2 | 0.960 | 0.547 |

- temp 0.1 的取樣變異與 prompt 效果同量級(重生成就修掉 GENERAL_071/081、EVENT_068);任何 prompt A/B 要多 seed 或 temp 0。
- v2 修好 VERSE_LOOKUP_090(答對箴言 9:10,cov 0.25→1.0)、PERSON_089(以利/以利亞,重生成修不掉)、GENERAL_081 一致;但 GENERAL_077 變整題拒答(cov 0.4→0)、GENERAL_020 多加因果句;父子關係反向(PERSON_061)與缺段替代(EVENT_068)三個版本都沒解。
- 建議規則(取 v2 修正版):出處只能取自標頭;缺段要「指出缺少 X,但仍回答有經文支持的部分」(避免 v2 的整題拒答);比較/順序題先逐段核對再下結論;引述話語/行動照段落中的人物;家譜關係照抄「甲是乙的兒子」方向。
- 結構性做法(不動模型):(a) 段落標頭加 KG `MENTIONS` 的人物清單(以利 vs 以利亞一眼可辨);(b) 二段式「草稿 → 逐句對 context 自檢 → 定稿」,多一次呼叫,只針對 PERSON/比較題;(c) R1 單節補段落標題與鄰近節。
- 不建議:為了 faithfulness 把回答改短或拿掉出處——那是在配合壞量尺。

### 7.3 A/B 讀數規則
coverage 為主 + 修正後 faithfulness 守門;舊 faithfulness 數字不可與新數字互比;PERSON 類另看「人物綁定錯誤題數」。

## 8. 量尺修復實作(2026-09-17)

範圍 = §7.1 全部五項(論文重判除外);生成端 prompt(§7.2)未動,留待量尺穩定後 A/B。

### 8.1 改了什麼

| 層 | 檔案 | 改動 |
|---|---|---|
| 後端 API | `backend/models/request.py`、`models/response.py`、`routers/query.py`、`utils/generator.py` | 新增請求欄位 `include_context`(預設 false,公開 API 行為不變);為 true 時每個 `Source` 附 `context` = 生成器實際看到的 `[i] 書卷 第N章 - 標題 (節)\n經文` 區塊(`build_context_blocks` 與生成器共用同一函式,不可能走樣)。容器已重建。 |
| 評估 context | `evaluation/src/rag_client.py`、`collector.py`、`context_blocks.py`(新)、`content_fetcher.py`、`models.py` | collector 直接用後端回傳的區塊;舊後端或缺欄時回資料庫重建「標頭 + 經文」(`fetch_context_blocks`,標頭格式與生成器逐字相同)。`resolve_fetch_kind` 用 `verse_range`/`strategy` 判別經節 id 與 pericope id(`3jn:1:2` 撞名根治)。 |
| 判準 | `evaluation/src/metrics/faithfulness_zh.py`(新)、`metrics/ragas_eval.py` | `FaithfulnessZh`(名稱仍為 `faithfulness`):繁中 NLI prompt + context 前綴使用者問題 + 五條判準(標頭即出處、問題前提不算捏造、標題/後設句依正確與否、歸納句看組成事實、意譯可);繁中 statement 拆解 prompt 保留引號內原句的「我/你/你們」。`FaithfulnessStrict`(`faithfulness_strict`):RAGAS 0.4.3 預設 NLI prompt、同一份含標頭 context。兩者共用一次陳述拆解(`StatementCache`),所有 statement/verdict/reason 進 `verdict_log` → `rationale.faithfulness_statements`。 |
| 設定/CLI | `src/config.py`、`run_eval.py`、`quick_faithfulness_eval.py`(新) | `EVAL_FAITHFULNESS_STRICT`(預設 true);`run_eval.py --eval-only --rebuild-contexts` 重判舊 checkpoint;`quick_faithfulness_eval.py` 只跑兩個 faithfulness judge,輸出逐句判定與 `stored_faithfulness` 對照。 |
| 呈現/文件 | `src/visualizer.py`、`templates/dashboard.html.j2`、`evaluation/README.md`、`.env.example`、`llm/langchain_factory.py`、根 `README.md`、`docs/ARCHITECTURE.md` | 儀表板多一欄/一卡 strict(缺席指標不出卡片);README 指標表改寫、API 範例加 `include_context`;factory 溫度改 0.0 並註明 RAGAS 每次呼叫覆寫為 0.01。 |
| 後端經節查詢 | `backend/database/postgres.py` | `verse_span` 解析合併節號(「29-30」),R1 查到合併節不再 `int()` 崩潰(審查發現的既有 bug)。 |
| 測試 | `tests/test_context_blocks.py`、`test_faithfulness_zh.py`、`test_content_fetcher.py`、`test_evaluator_contexts.py` | 標頭格式逐字對齊、撞名判別、後端區塊優先、cache 併發去重/取消/失敗重試、verdict 合併、NLI context 前綴、兩 judge 共用拆解、合併節號區間、checkpoint context 解析、provenance 摘要;全套通過(見 §8.2)。 |

### 8.1b 對抗式審查後的修正(同日)

兩輪多代理審查(5+4 個 lens、每項發現 2 個反駁者)確認的問題與處置:

| 嚴重度 | 問題 | 處置 |
|---|---|---|
| CRITICAL | 兩個 judge 共用的陳述拆解 future 被 RAGAS 逐題 timeout 取消時,`CancelledError` 會逃出 `except Exception`,整個 `evaluate()` 中止、幾小時結果全丟 | `StatementCache` 改 `asyncio.shield` 等待、只淘汰真正失敗的 producer、`_run_ragas` 同時接 `CancelledError`;新增取消/失敗重試測試 |
| HIGH | 資料庫的合併節號(「29-30」,70 筆)讓 `int()` 崩潰,`--rebuild-contexts` 與 quick 工具整批中止 | `verse_span` 解析為區間;`fetch_context_blocks` 逐 source 容錯,DB 失敗時退回 checkpoint 內文 |
| HIGH | strict 指標缺席(關閉或舊結果檔)時儀表板卡片顯示假的 0.00% | 缺席指標不出卡片 |
| MEDIUM | judge 看到的 context 形式沒寫進 provenance;`--eval-only` 不加旗標會默默重現舊的無標頭判法 | `EvalSample.context_source` + `meta.context_format / context_sources`;載入時明確警告 |
| MEDIUM | 含標頭 context 也會改變 `context_recall`,文件只說 faithfulness 不可比 | README 與本文註明 |
| MEDIUM | strict 用的是繁中拆解 + RAGAS 預設 NLI,不等於體檢的 hdr 條件(英文拆解) | 文件說明;守門門檻改依 §8.3 的實測值定 |
| MEDIUM | strict 未跑時 rationale 塞滿「[?]」;statements 在結果檔存三次 | rationale 改為「k/n supported + 失敗句」,未跑回空字串;結構化清單為唯一完整來源 |
| MEDIUM | rebuild 為空或較短時直接覆蓋掉 checkpoint 內文,樣本被 RAGAS 靜默跳過 | `_resolve_checkpoint_contexts` 保留內文並標 legacy |
| MEDIUM | quick 工具 stored/new 平均分母不同;`--ids` 前先重建全部 500 題 | 配對平均(`n_paired_with_stored`);`only_ids` 進 loader |
| MEDIUM | `ZhNLIPrompt` 對「經文沒提到 X」的錯誤後設宣稱沒有反例 | 加入反例;規則 2 補「與經文矛盾則 0」 |
| LOW | 後端 5 段式 `:v:` 經節 id 未對齊(後端取父 pericope)、verdict log 以 (問題,答案) 為鍵會被重複題覆蓋、`--rebuild-contexts` 在非 eval-only 靜默忽略、儀表板副標寫死 100 題、死碼 | 逐項修正 |

第三輪(聚焦 cache 引用計數、verdict 合併、loader、後端節號):8 項確認——**HIGH:我在第二輪把 `get_verses_range` 改成以經文文字去重,會把同文字的不同節吃掉**(改以 (pericope, 節號標籤) 去重);後端合併節的標籤與評估端不一致(「30.」vs「29-30.」→ `get_verse` 回 `label`,`verse_retriever` 用 label 印);`--limit` 在缺 id 檢查前截斷會誤報、負值 `--limit` 切尾;重複 question_id 只警告不去重(改保留第一筆);verdict 合併對重複陳述用 last-wins 索引;`n_statements` 算進 strict 額外句;cache 引用計數改以 future 為鍵,`reset()` 期間的舊 waiter 不會動到新 producer。

審查駁回(不改):`第None章` 對齊(生成器 `chapter_num` 不會是 None)、`verse_direct` 空 verse_range 分支、函式略長於 50 行。

### 8.2 驗證

- 冒煙(3 題,真 judge):VERSE_LOOKUP_017 0.0→1.0、VERSE_LOOKUP_067(撞名題)0.0→1.0、GENERAL_081 0.31→0.86 且仍抓到「順序相同」那句真錯誤(zh 與 strict 同判)。
- 後端:`include_context=true` 回傳的 `sources[i].context` 以 `[i] ` 開頭且含標頭(約三 1:2 回單節,不再撞到 13-15 節的 pericope);不帶旗標時 `context` 為 null,回應其餘欄位不變;合併節號章節(歷代志上 16)的 R1 查詢回 200、無策略錯誤。
- **部署狀態(已完成乾淨建置)**:當日先以 `docker cp` 熱補丁 + `docker commit` 頂著(備份標籤 `bible_rag-backend:hotpatch-2026-09-17`);乾淨建置三次卡在 `uv sync` 下載 torch/nvidia(主機對外頻寬 ~50 KB/s,大檔逾時會從頭重抓)。主機全域 uv 快取派不上用場(torch 是 2.13.0/cu13,lock 要 2.10.0/cu12,離線 dry-run 84 個套件要下載 69 個),改把原映像檔(`bible_rag-backend:pre-fix-2026-07-31`)內 uv 0.12.0 寫的 7.1 GB 快取匯出到 `~/.cache/uv-bible-rag-backend`,Dockerfile 以 BuildKit 具名 context 掛載(`FROM scratch AS uvcache` 空 stage 當後援、uv 釘 0.12.0、`UV_LINK_MODE=copy`)。結果:`uv sync` 19 秒、0 下載,整個建置約 3.5 分鐘;容器已由 `bible_rag-backend:latest`(1eceb1523c94)重建,健康檢查、`include_context`、3jn:1:2 撞名、合併節號標籤「17-18.」、預設請求無 context、完整生成皆通過。
- 全量:`quick_faithfulness_eval.py --results-dir results_graph` 對 2026-07-15 run of record 重判 500 題 → `results_quick/faith_metric_validation.json`(結果見 §8.3)。

### 8.3 500 題重判結果

`quick_faithfulness_eval.py --results-dir results_graph`,2026-07-15 run of record 的 500 題答案不變、context 以 DB 重建成生成器同款區塊,judge 同為 gemma4:26b-a4b-it-q8_0;500 題全部有效評分,3,675 條陳述。憑證 `results_quick/faith_metric_validation.json`(含逐句判定)。

| 切面 | stored(無標頭 judge) | zh(主讀數) | strict(守門) |
|---|---|---|---|
| **overall(500)** | 0.912 | **0.987** | **0.981** |
| VERSE_LOOKUP | 0.859 | 0.987 | 0.977 |
| TOPIC | 0.969 | 0.993 | 0.992 |
| PERSON | 0.940 | 0.976 | 0.978 |
| EVENT | 0.935 | 0.996 | 0.995 |
| GENERAL_BIBLE | 0.858 | 0.985 | 0.965 |
| 滿分題數 | 358 | 468 | 460 |
| <0.8 題數 | 69 | 10 | 13 |

家族:體檢時墊底的 paraphrase 0.741→1.000、nt_quotes_ot 0.750→0.975、disambiguation 0.762→0.931(仍最低,真錯誤所在)、prophecy_fulfillment 0.883→1.000。與體檢的推估(hdr 0.979 / hdr_zh 0.993)一致。

殘餘否定判定:zh 46 條(32 題)、strict 52 條(40 題)。逐題檢視新出現的低分題:
- **真錯誤且是新抓到的**(舊 judge 因無標頭反而給滿分):GENERAL_072 答案把加拉太書 5 章引成 2 章(標頭讓 judge 能核對章節);TOPIC_076 以撒的妻子寫成撒拉;PERSON_070 抹大拉的馬利亞的動作寫成愛徒;GENERAL_051 耶穌對法利賽人說的話寫成對門徒。
- **體檢清單上的真錯誤仍被抓到**:GENERAL_081 0.857、PERSON_061 0.6、PERSON_089 0.8、PERSON_063 0.75、EVENT_068 0.8;GENERAL_071(亞伯→亞伯拉罕)與 GENERAL_039(補「彼西底的安提阿」)兩題 judge 仍放行(與體檢相同)。
- **judge 噪音(約 3 題)**:VERSE_046 拆解時在引句尾多出「Ant」字串被判 0(拆解 LLM 的雜訊,整題 1 句→0.0);VERSE_023 拆解把「他的臉」改寫成「耶和華的臉」被判改動經文;PERSON_029 judge 誤讀撒下 21:8(亞摩尼、米非波設確是利斯巴之子)。
- **zh 與 strict 差 ≥0.2 的 5 題**皆屬設計差異:VERSE_071「摩西」是題目前提(zh 1.0/strict 0.0);GENERAL_041 馬太的「你說的是」被答成「我是」,zh 放行、strict 抓到——strict 作守門有價值。

**守門門檻定案**:run 層級 `ragas_faithfulness_strict` ≥ 0.97(實測 0.981;題型最低 GENERAL 0.965,故題型層級用 0.95)。

### 8.4 讀數規則(更新)

- 主讀數 `ragas_faithfulness`(zh);守門 `ragas_faithfulness_strict` run 平均 ≥ 0.97、題型 ≥ 0.95(§8.3 實測 0.981;strict 的拆解是繁中 prompt,不等於體檢的 hdr 條件)。
- 建置 backend 前 `~/.cache/uv-bible-rag-backend` 必須存在(不存在時錯誤為 `failed to get build context uvcache: stat …: no such file or directory`);空目錄也能建置,只是全部重抓。
- 2026-09-17 之前所有 faithfulness 數字(含論文 sec6)都是無標頭 judge 產物,不可與新數字互比;論文表格待用 `--eval-only --rebuild-contexts` 重判三個時點後再改。
- 讀低分題先看 `rationale.faithfulness_statements` 裡 verdict=0 的句子,再決定是模型錯還是判準錯。

## 附:憑證與工具(`evaluation/results_quick/faith_audit_2026-09-10/`)
- `refaith.py`(重評分,含 `ZhNLIPrompt`)、`refaith_results.jsonl`(543 列,含每條 statement/verdict/reason)、`refaith_statements.json`
- `analyze_refaith.py`、`dump_residuals.py`、`residuals_hdr.txt`(101 條人工分類依據)、`residuals_hdr_zh.txt`
- `pilot_gen.py`、`pilot_results.json`(22 題三版本答案 + 判定)
- `low_faith.json`(stored run 69 題 f<0.8 明細)
