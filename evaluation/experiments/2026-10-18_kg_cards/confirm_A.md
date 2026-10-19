# 實驗 A 盲集確認：事前登記（2026-10-18）

依據：FP＝store `reports/kg_niche_20261018/kgniche/final_plan.md` §3 實驗 A；P0＝本目錄 `prereg.md`（stage-0，A 開發集已通過）。Kay 2026-10-18 授權：「開 A 確認集，照你的建議跑」。
本檔在 F1 commit；F1 之前不花任何 USD。看到任何臂的答案後，判定、門檻與措辭都不改（FP D10）。程式只修基礎設施，修了記在文末「執行紀錄」。
程式在 `A/confirm/`（stage-0 的 `A/*.py`、`cards_common.py`、`2026-10-14_graph_gd/` 一律不改，要改的部分複製到 `A/confirm/` 再改）。資料只放 store `reports/kg_cards_20261018/A_confirm/`（下稱 OUT）。repo 不放經文、題目文字、TIPNR。

## 0. 不變項與凍結點

- **裁決**：D2、D3、D4b、D4c（P0 §0）；D6（只開 A，先出 12 題 pilot）；D7（出題前依段配額，接受輕度洩漏）。
- **沿用 stage-0，不重算**（開跑前核 sha，`c_common.frozen_mismatches()` 必須為空）：
  - 層 `layer_auto.json` `932d2242…`、`ref_layer.json` `79d57efe…`；`cards_common.py` `ae9dc16c…`。
  - A/ 的 `engine.py`、`regnal.py`、`tcanon.py`、`seeds_a.py`、`keys_a.py`、`arms_a.py`、`score_a.py`、`items_a.py`、`a_common.py`、`layer_re.py`、`analyze_a.py`、`run_a.py`（sha 見 store `A/inputs_manifest.json`）。
  - prompt：生成 system `f58c03fa…`、user 模板 `677e91e5…`、種子 system `5405fbb0…`、種子 user `dd00c3df…`。
  - 選項：temperature 0.1、num_predict 10000、num_ctx 131072（P0 K0-3）；附加區塊上限 900 字。
- **F1**（花任何出題 USD 之前；CLI 重測 0.36 USD 已花）：commit 本檔與 `A/confirm/`；`segments.json` `3d85f9c0…`、`alias_table.json` `810aaa61…`、出題 prompt `gen_a.md` `9d3890c7…`、稽核 prompt `audit_a.md` `60969cd1…`、`bt_guard.py` `a81cba6e…`（HO 原檔）、CLI 釘版 `cli_pin.json` `085eaa3a…`（2.1.302，帶 thinking 摘要）；全部逐檔 sha 在 store `A_confirm/f1_manifest.json` `8affe6eb…`；slot 計畫見 §2.4。
- **F2**（Kay 抽查頁處理完、K-U2 通過、Ollama 夜之前）：`questions_frozen.json` `93ca70af…`；附錄 C 只列題號、段、題型、鍵型別。`ho_a/freeze_a.py` 把此 sha 寫進 `inputs_manifest.json` 的 `frozen`（並寫 `k_u2.json`）；`collect_ctx.py` 與 `run_c.py prepare` 只認這兩份紀錄。
- **F3**（Ollama 夜收完 context、種子開跑前）：`contexts.json` `672f6e2c…` 寫進 run_meta（`items.json` `a601d13e…`）。
- **順序**：CLI 重測（§8.3）→ F1 → pilot 12 題 → K1（CPU）→ 其餘出題與稽核 → 機械與 transcript 檢查 → Kay 抽查頁（§7）與修刪 → K-U2 → F2 → Ollama 夜（收 context → F3 → 種子 → 各臂）→ 計分與分析（CPU）→ 報告。

## 1. 分段（FP 確認集單位；D7）

- **鏈**：以色列 I01–I19；猶大 J01–J20（J00 所羅門不在鏈上）。輸入只有參照層與 text 層（`text@247eafe44b02`），0 LLM。
- **缺口**：亞她利雅的兩條邊（J06→J07、J07→J08）不放進任何段。提比尼不設缺口，由稽核查措辭（§2.6）。
- **段**：同一條鏈上連續的王，含 2–4 條繼位邊；段與段的邊不重疊，可以共用交界王（支撐事實仍兩兩不交：A(b) 只在前段、R(b) 只在後段）。
- **候選題形**（§2.1）：S1a（k=±2、±3，兩端在段內）；S1b（只在 ≥3 邊的段，兩端相隔 ≥2 次交接）；S1c（第 n 個篡位者，起點到答案 ≥2 次交接）；S4（只限猶大，往回 ≥2 步，累加制與非登基年制答案相同且差 ≥1 年，種子不是 J06、J19）。
- **家譜一節捷徑**：鏈全是子繼父，而且 1ch 或 mat 某一節依序寫出每一對父子（「A的兒子是B」或「A生B」，含別名），刪掉這個 S1a／S1b 候選（`support.genealogy_shortcut`）。
- **可用段**：至少 2 個候選，其中至少 1 個是 S1a 或 S4。每條無缺口的鏈段以動態規劃依序最大化（可用段數、S4 數、−未用邊數、3 邊段數），平手取「跳過一邊、2、3、4 邊」中先列者（`segments.py`）。
- **同名標記洩漏鏈**（分段之後才套用，不改分段）：被點名的種子（S1b 兩端）是同國同名王、必須寫「name（F的兒子）」，而 F 是該候選鏈上的另一位王（中間王或答案王），這個候選就不可出，列在 `segments.json` 的 `dropped`。現況只刪 I6 反向（耶羅波安→約哈斯，F＝約阿施是中間王）。若在分段前套用，I6 會變成不可用段、以色列重分成 8 段（共 13 段），所以照分段後套用。
- **結果**（出題前的輸入，不是結果；`segments.json` `3d85f9c0…`）：14 段（以色列 9、猶大 5），候選 44 個（S1a 29、S1b 7、S1c 4、S4 4；刪 1 個）。

| 段 | 王 | 邊 | 範圍（列王紀） | 節數 | slot |
|---|---|---|---|---|---|
| I1 | 耶羅波安→拿答→巴沙 | 2 | 1ki.11.26–1ki.15.33 | 149 | S1a、S1a 反向、S1c |
| I2 | 巴沙→以拉→心利 | 2 | 1ki.15.27–1ki.16.15 | 23 | S1a、S1a 反向、S1c |
| I3 | 心利→暗利→亞哈 | 2 | 1ki.16.10–1ki.16.29 | 20 | S1a、S1a 反向 |
| I4 | 亞哈→亞哈謝→約蘭 | 2 | 1ki.16.28–2ki.3.1 | 267 | S1a、S1a 反向 |
| I5 | 約蘭→耶戶→約哈斯 | 2 | 2ki.1.17–2ki.13.1 | 323 | S1a、S1a 反向 |
| I6 | 約哈斯→約阿施→耶羅波安 | 2 | 2ki.10.35–2ki.14.23 | 92 | S1a |
| I7 | 耶羅波安→撒迦利雅→沙龍 | 2 | 2ki.14.16–2ki.15.13 | 27 | S1a、S1a 反向、S1c |
| I8 | 沙龍→米拿現→比加轄 | 2 | 2ki.15.10–2ki.15.23 | 14 | S1a、S1a 反向 |
| I9 | 比加轄→比加→何細亞 | 2 | 2ki.15.22–2ki.17.1 | 38 | S1a、S1a 反向、S1c |
| J1 | 亞比央→亞撒→約沙法→約蘭→亞哈謝 | 4 | 1ki.14.31–2ki.9.29 | 537 | S1a、S1b、S4 |
| J2 | 約阿施→亞瑪謝→亞撒利雅→約坦→亞哈斯 | 4 | 2ki.11.2–2ki.16.2 | 135 | S1a、S1b、S4 |
| J3 | 亞哈斯→希西家→瑪拿西→亞們→約西亞 | 4 | 2ki.15.38–2ki.22.1 | 184 | S1a、S1b、S4 |
| J4 | 約西亞→約哈斯→約雅敬 | 2 | 2ki.21.24–2ki.23.36 | 59 | S1a、S1a 反向、S4 |
| J5 | 約雅敬→約雅斤→西底家 | 2 | 2ki.23.34–2ki.24.18 | 22 | S1a、S1a 反向 |

- **揭露（敏感度，參數依效度理由選，不依段數選）**：不設缺口 16 段；提比尼與亞她利雅都設缺口 13 段；不共用交界王約 11 段。猶大 S1a 候選有 32/70 被家譜捷徑刪掉，以色列 0/66。
- **範圍**：起點＝段內第一位王在列王紀的最早出處節（含繼位節）；終點＝最後一位王的最晚出處節，不含他的死亡或繼任節。
- **交給出題者**只有：國別、範圍、slot 題型，以及段代號與題號（例如 J4、QJ4s3a1；不含任何結果資訊）。不給王的清單、層、引擎、模板、開發題、其他段的題。鏈上每一位王都必須是本國、而且登基或作王的記載在範圍內；可以用 bt 讀全本，但 gold 依據節只能是範圍內的列王紀經節。
- **出題後**（`support.support_record`）：種子、鏈、答案的王名依參照層名稱與別名、國別、「name（F的兒子）」映射成參照 id；解析不到記 `name_unresolved`；鏈上有王不在指定段（含跨缺口）記 `seg_cross`。兩者都退回修一次（中性提示「鏈上有王不在本段範圍」），修不好就刪，由同 slot 重出。
- **支撐事實**（`support.py` 定義，存檔）：S1a、S1b、S1c＝鏈上相鄰對的 E；S4＝A(種子)、R(走過的王，不含種子)、E。
- **參照層不判 gold**：出題者的鏈與參照層不符只記隱藏旗標 `ref_disagree`；出題者、稽核、Kay 都看不到，跑完才當描述與敏感度。
  - 揭露：`name_unresolved` 退件等於由參照層的王名單部分決定「誰算一位王」（例如把提比尼算進鏈，會被退件到拿掉為止）。
- **K-U（出題前）**：可用段 <12 就停。現為 14，通過。
- **K-U2（F2 前）**：至少有 1 題凍結的段 <12 就停，不跑 Ollama 夜。措辭：「依事先規則停止（K-U2＝凍結單位 n<12），不構成無效證據；盲集未跑」。

## 2. 題型、出題與稽核

### 2.1 允許的題型（每題一個答案鍵）

- **S1a 第 k 位王**：點名起點王（國別加王名），問之後或之前的第二／第三位同國王；鍵＝王名。
- **S1b 交接次數**：點名同國兩王，問從甲到乙王位一共交接幾次（甲傳給下一位算第一次）；鍵＝數字加「次」；只在 ≥3 邊的段，≥2 次。2 邊段不出（答案永遠是 2）。
- **S1c 第 n 個篡位者**：點名起點王，問他之後第 n 個篡位（背叛、殺王奪位）得國的同國王；起點到答案 ≥2 次交接；鍵＝王名。
- **S4 出生時在位**：點名一位猶大王，問他出生時在位的猶大王；題目寫明「依經文記載的登基年齡與歷代在位年數，各王在位年數前後相接推算」；≥2 步，兩種算法答案相同且差 ≥1 年；種子不是亞哈謝、約雅斤（列王紀與歷代志登基歲數衝突）。
- **FP 用詞的解讀**（FP 的範圍設定，不是看結果挑題；報告揭露）：「篡位計數」＝S1c；「繼位計數」＝S1b（等於引擎的「相隔 N 代王位」）；k≤3。
- **同名**：同國同名王一律寫「name（F的兒子）」（現有 I01、I13、J10、J17）。這是題目裡唯一可寫的父名；其他王加父名（例如「約蘭（亞哈的兒子）」）算寫出別的王名。

### 2.2 禁止（稽核判 critical；機械檢查能抓的記 error）

- S2 跨國同步紀年、S3 同時代、單屬性查詢、附加屬性（第二個問題）。
- 起點王用事蹟描述而不點名；題目寫出中間王或答案王；題目寫經文出處。
- 用同步紀年節當繼位依據（三筆自相衝突的登基同步因此自動排除）；鏈跨過亞她利雅或本段。

### 2.3 gold、答案鍵、正規化表

- **gold**：經文數字與王名，每一步附列王紀依據節；S4 另附兩種算法的數字與差距。
- **名鍵**：出題者寫的名字＋稽核核過的又名＋`alias_table` 該王的名字與別名，扣掉同國另一王的主名（本王主名保留；items_a.gold_accept 規則）。
- **數鍵**：值必須帶單位「次|代|任|位」、前面不是「第」、先刪經文引用（keys_a.number_hit，不改程式）。
- **`alias_table.json`**（F1 凍結，`810aaa61…`）：39 王、別名 10 個、詞庫 42 個（keys_a.king_lexicon，含所羅門）；國字數字依 cards_common.cn2int／numbers_in。陷阱詞庫不改。

### 2.4 slot 計畫（F1 寫死；35 slot）

- 規則：slot 1＝S1a；slot 2＝S1b（段有 S1b 候選時），否則 S1a 反向（段有 ≥2 個 S1a 候選時），否則沒有；slot 3＝S4，否則 S1c，否則沒有。結果見 §1 表：S1a 24（含反向 10）、S1b 3、S1c 4、S4 4；I6 只有 1 個 slot。
- 每個 slot 最多 3 次出題嘗試（含退件後重出），用完就空著，不換題型。
- 重跑只限基礎設施失敗（沒有 result 事件、逾時、CLI 啟動失敗、API 錯誤；以及 CLI 把 session 改派給別的模型：有 `model_refusal_fallback` 事件，或 modelUsage 出現 claude-opus-5-5 以外的模型，該次輸出一律不用），每 job 最多重跑 2 次，不計嘗試。job 觸及代理上限（`--max-budget-usd`、max turns、structured output 重試；result subtype `error_max_*`，或 total_cost_usd ≥ 該 job 上限）不算基礎設施失敗、不重跑：出題計一次嘗試（棄題），稽核或修題則刪稿（同 slot 有剩餘嘗試就重出）。
- 同一段內（題型, 種子, 答案）不得重複；「反向」＝方向與同段 slot 1 相反，或 k 不同。
- 每輪對每個開放的段出一個 slot，依段序執行，最多 4 個 job 平行；提交依 slot 序。

### 2.5 盲化（沿用 2026-10-14 HO 機制）

- 出題者不可看到：層、引擎、推導行、模板題、stage-0 開發題、其他段的題、任何專案字樣。
- cwd `/srv`；`--system-prompt` 取代預設提示；只有 `bt`（v、grep、books；拿掉 old、pid），由 bt_guard hook 把關；移除 `CLAUDE*` 環境變數；`--setting-sources local`；auto-memory 目錄為空；transcript 規則 t_init、t_tool、t_path、t_memory、t_banned。
- task 可列「本段已出題」：只列本段自己已通過的題目與答案（出題者的產物，不是開發題）。

### 2.6 出題與稽核 prompt（`ho_a/gen_a.md`、`ho_a/audit_a.md`，F1 凍結 sha）

- 出題：HO `gen_prompt.md` 改成列王紀王位承繼推算題；保留 HO 規則 1、6、9、11；規則 2–5 改寫為：≥2 次交接（S4 往回 ≥2 位王）且每步必要；鏈上的王都在範圍內有登基記載；只點名起點王（S1b 點兩端）；捷徑搜尋（含代上 3 章、太 1 章家譜）有捷徑就改題（change_log 加 `[SHORTCUT]`）或放棄；每個數字與交接都 grep 歷代志平行記載，有出入就放棄；繼位依據只用繼位句；算法有爭議（提比尼、共同執政）就在題目寫明算法，寫不明就放棄。刪規則 7、8。四類定義換成 §2.1，§2.2 逐條列入。
- 禁用字（`banned_a.py`）：HO PROMPT_TERMS，加引擎、推導、推導行、卡片、年表層、王朝層、層列、模板、種子、gemma、Ollama、開發集、確認集、pilot、盲集、參照層、stage、kg_cards、kgniche、T-canon、T-rows、G-auto、G-ref。「推算」不禁。
- 稽核標準：每一步由所列經文明說、親自重算（S4 兩種算法都算）；只靠經文；≥2 步且每步必要；沒有一節單獨給出答案（自己 grep 起點、答案的名字與別名，及代上 3 章、太 1 章）；題目沒寫中間王、答案王或出處；題型、國別、範圍正確；算法無歧義；與歷代志沒有出入；答案鍵單一、可接受寫法完整且沒收同國另一王的主名；自然度。
- severity：critical＝事實或答案錯、一節可答、S2／S3／單屬性、鏈跨段；major＝算法有歧義、與歷代志有出入、洩漏中間王、鍵缺寫法或多收、某步不必要；minor＝措辭。major 與 critical 修一次、複驗一次，否則刪題（MAX_FIX_ROUNDS=1）。

### 2.7 輸出 schema 與機械檢查（`ho_a/mech_a.py`；error 退件修題，warn 只記錄）

- schema：`id, segment, qtype, kingdom(以色列|猶大), question, seeds[{name, father|null}](1–2), k|n|null, answer{kind: name|count, text, accept[], value|null, unit|null}, chain[{king, father|null, role: seed|step|answer, fact, basis[]}], convention, shortcut_search, conflict_search, notes, change_log`。
- error：`schema`、`slot_mismatch`、`seeds_named`、`seeds_chain`（S1a、S1c、S4 的 seeds 正好一位且等於鏈第一列；S1b 正好兩位且等於鏈的第一與最後一列）、`extra_king`（種子名字以外的任何王名，兩國都算；唯一例外是同國同名種子必寫的父名標記；這個父名若是鏈上另一位王也記 error）、`has_ref`、`chain_len`、`s1b_short_seg`、`seg_cross`、`name_unresolved`、`basis_exists`、`basis_in_range`、`genealogy_shortcut`、`key_form`、`dup_in_segment`；transcript 規則照 HO，禁用字換成 banned_a。
- `forbidden_form`、`has_ref` 是盡力而為的 regex（例如「先後有哪幾位王」「北國當時的王」「登基時多大」「（15.8）」抓不到），漏網的由稽核 critical 規則與 Kay 抽查兜底。
- 隱藏旗標（只供跑完後描述）：`ref_disagree`、`gen_passage`（鏈的父子關係都在代上 3:10–16 或太 1:2–16 同一段家譜）、`answer_is_father`（答案王是種子的父或子；S1b 為兩端互為父子；依參照層父名）。

## 3. Pilot 12 → K1

- **抽選**：`random.Random(20261018).sample(sorted(段 id), 12)`；各取 slot 1，但依抽出順序，第一個有 S4 slot 的段改出 S4；其餘段中第一個有 S1c slot 的改出 S1c；再其餘段中第一個有 S1b slot 的改出 S1b。結果（`segments.json` pilot，依抽出順序）：J5、J4（S4）、I4、I6、I2（S1c）、I8、J1（S1b）、I7、I9、I1、I3、J2，未註明者為 S1a，共 S1a 9、S4 1、S1c 1、S1b 1；I5、J3 不在 pilot。
- **流程**：出題 → 機械檢查 → 稽核 → 修題（≤1 次）→ 複驗；每 slot ≤3 次嘗試。12 個 slot 都通過或用完嘗試，pilot 才凍結。
- **K1（CPU，不看任何臂；`k1.py`）**：出題者的 gold 種子（解析到的參照 id 的主名）經 `arms_a.resolve_all` 解析到 G-auto 節點，跑 `engine.cards`；命中＝引擎出手且推導行 payload 以 `keys_a.covered` 涵蓋答案鍵（stage-0 a_hit，種子換成 gold）。K1＝命中數÷通過的 pilot 題數。G-ref 版本只描述。
- **停損**：通過的 pilot 題 <10，或 K1 <0.80，A 就停，不補題。措辭：「依事先規則停止（K1＝x/n），不構成無效證據；盲集未跑」（題數不足時〈條目〉寫「K1 通過題數」）。
- pilot 題留在確認集；K1 之後 prompt 與工具都不改，只修基礎設施。
- K1 以 pilot 題當時的版本計算。Kay 抽查（§7）若修改或刪除 pilot 題，門檻不重算；改以凍結版本重算一次 K1，只當描述。

## 4. 基底 context（Ollama 夜第一步；`collect_ctx.py`）

- `POST http://localhost:8000/api/v1/query`，body `{"question", "top_k": 5, "include_sources": true, "include_context": true, "retrieval_only": true}`，不帶其他參數＝prod 原樣：核心 5 段，event_registry 附加槽照 prod 預設，共 ≤6 段（FP「top-6」依此解讀）。所有 source 的 build_id 必須是 `b20261008_e05d3e55`；不改 prod。
- retrieval_only 仍會由 gemma 做路由，所以只在授權時段跑，每題 1 次，序列執行，timeout 180 秒；先收完全部 context 再開始 harness 呼叫；前後各讀一次 /api/ps。
- 檢查（HTTP 錯誤、逾時或基礎設施失敗最多重試 2 次）：每個 source 有 context 區塊；build_id 一致；不是 `validity.infra_failed`；`cards_common.build_context([realkg_source(s)])` 逐塊 sha 等於回傳區塊。任一條不過就停在 F3 之前，不部分凍結。
- 凍結 `contexts.json`（每題 request、原始 sources、intent、route_used、event_registry_events、strategy_errors、context_sha、時間戳），`items_c.py` 再依此產生 `items.json`。

## 5. 臂與執行（P0 §2；A/ 附錄 A.4）

- 臂 G-auto、T-canon、T-rows、B0、G-ref 與 stage-0 逐字相同（`arms_a.item_arms`）；種子 `seeds_a.seed_jobs` 每題 1 次，各臂共用。只有 items 與 contexts 不同。開跑前斷言 §0 的四個 prompt sha。
- **次數**：5 臂各 3 次（G-ref 也 3 次）。
- **棄權**：G-auto 第 r 次 ← 該題 T-rows 第 r 次；G-ref 第 r 次 ← T-rows 第 r 次。
- **順序**：rep → 題 → 臂，臂序依題序輪替（`arms_c.arm_jobs`，只把 rep 改成 1–3）。
- **K0**：K0_1、K0_2 引用 stage-0 `A/k0_status.json`（層 sha 相同）；K0_1b＝Kay 抽查 20 列（§7），只取 `kay_a.py apply` 寫的 `ho/kay/k0_1b.json`（`run_c.py k0-1b` 或 prepare 讀入並記 sha；之後檔案變動就擋），沒有手填入口；K0_3＝num_ctx 131072。截斷＝done_reason=length 或 prompt_eval_count+eval_count ≥ num_ctx，記格式失敗 0。
- **canary**（取代 smoke）：種子全部跑完、加上前 30 個臂呼叫之後，有錯誤行或缺漏呼叫就停下來修基礎設施，此時不看答案。截斷只計數、列入報告，不停：num_ctx 已是 C0、num_predict 凍結，沒有可調的基礎設施；依 P0 §1，正式跑中的截斷記格式失敗（種子截斷＝沒有種子，G 臂棄權改取 T-rows）。`--canary-fixed` 重跑時放過的錯誤行數記在 `canary.json`，`run_c.py canary` 也照它計算。
- **程式防呆**：prepare 記下 `A/confirm/*.py` 的 sha（`inputs_manifest.json` `code_confirm`）；之後 prepare、seeds、arms、score、analyze 遇到程式變動就拒跑，除非加 `--code-change 說明`（只限基礎設施），每次記 {時間, 檔名, 說明} 到 `code_changes` 並列入報告。
- **斷行**：程序被強制終止後，jsonl 最後一行若不完整，刪掉該行再續跑，並記在執行紀錄。
- 呼叫數：種子 N＋各臂 15N 減棄權（N=35 時 560）。防呆照 A.6：options 與 prompt sha、種子完整性、items 與 contexts 的 frozen sha、k0_status 存在。

## 6. 主指標、檢定、判定與措辭

- **key_score**：`score_a.answer_text`＋`keys_a.score_line`，每題單一鍵（0 或 1）。
  - 陷阱豁免＝推算鏈上所有王（種子到答案）的名字與參照層別名，加名鍵的可接受寫法（items 的 `exempt`）。模板題規則（`exempt_template`，只豁免種子與答案）與不套陷阱規則另報敏感度。
  - 父名片語、同國同名錯父、另一國前綴、刪括號、引用刪除、國字數字照 A.5 不變。S1b 沒有 a_strict（只影響描述）。
- **彙總**：題值＝每臂 3 次平均（G 棄權依 §5 替補）；d_q＝題值差；單位值 v_u＝段內各題 d_q 的不加權平均；Δ̄＝所有單位 v_u 的平均（含 v=0 的單位）。
- **主檢定**（固定序列，FWER 0.05）：H1＝G-auto−T-canon；H2＝G-auto−T-rows，只在 H1 過了才檢、才報 p。每步過關＝`src.ab_stats.sign_flip_p(v_u, seed=20261018)` <0.05（雙尾；非零單位 ≤16 時精確列舉）**且** Δ̄≥+0.10。p<0.05 但 Δ̄<+0.10 不算過，記「顯著但未達事先定的最小效果」，後續依未過處理。CI：`ab_stats.bootstrap_ci(v_u, n_boot=10000, seed=20261018)`；另報單位 W:L:T。
- **判定與寫死的措辭**：
  - K-U、K-U2、K1、K0-1b 停：「依事先規則停止（〈條目〉＝〈值〉），不構成無效證據；盲集〈未跑／未出完〉」。
  - H1 不過：「王朝年表推導卡在盲集上未達事先登記的門檻（單位 n＝…，Δ̄＝…，95% CI …），記 null；王朝層結案」。
  - H1 顯著為負（p<0.05 且 Δ̄<0）：上一句再加「且 G-auto 顯著劣於正典經文窗」。
  - H1 過、H2 不過：「結構化年表加程式計算，在王朝年代題上顯著優於同流程的正典經文窗；未證明圖譜操作優於『同一份層列加 LLM 自己推』，不計為圖譜增益」。
  - H1、H2 都過：「regex 可建的王朝鏈上，程式多步走訪與推算，在王朝年代題上顯著優於同流程的正典經文窗與層列平鋪」，加範圍限定「只限王朝年代題（S1、S4 窄題型、出題前配額的盲題）」。
  - 全部停止時用 FP §5 的分層說法，第 3 點填「確認集（盲集）停在〈條目〉」。不寫「圖譜有效」或「圖譜無效」。論文不動。
- **K3（傷害）**：錯答率＝有答案行的呼叫中 key_score=0 的次數÷呼叫數（G-auto 含替補）。G-auto−T-canon >0.05 時附加「不談 prod」，不改 K2 措辭；另報單位 bootstrap CI。
- **只描述**（Δ̄、CI、W:L；p 只當描述；H1 未過時，H2 配對 G-auto−T-rows 在分層、排除 `ref_disagree`、陷阱規則敏感度與題層級也一律不算、不報 p，只報 Δ̄、CI、W:L:T）：G-auto−B0、G-ref−G-auto（G-ref 只稱理想上限）；各臂錯答率、格式失敗率、截斷、陷阱次數、附加字數；分層（題型、國別、pilot／非 pilot、`gen_passage`、`answer_is_father`）；排除 `ref_disagree` 題；題層級 sign-flip；陷阱規則敏感度；棄權題；gemma 與 gold 種子解析一致率、a、K1 型 a、h、pR、pC；T-canon 窗含齊依據公式節的子集；答案行列出 ≥2 位非種子同國王的猶豫答案次數；交界王題數；與開發題（種子, 答案）重疊題數。
- **檢定力揭露**：FP 表為 C=12／15、m=3；本案 C=14、m 平均約 2.5（35 slot／14 段），檢定力略低於表上數字；3 次生成不獨立，檢定以單位為準。

## 7. Kay 抽查（一頁，所有題通過稽核後、F2 前）

- store 裡的本機 HTML 頁（含經文，不進 repo），一頁兩部分，不給任何臂的輸出、隱藏旗標（`ref_disagree`、`gen_passage`、`answer_is_father`）或推導行：
  1. **層 20 列**：`random.Random(20261018).sample(sorted(兩鏈上的 G-auto 節點), 20)`，以 `engine.row_text` 渲染，附每欄出處節經文；Kay 逐列標「對／錯」。20 列中 ≥2 列錯：K0-1b 不過，A 停，措辭用 §6 第一條（〈條目〉＝K0-1b，〈值〉＝錯列數/20）。1 列錯：記錄，不修層、不改任何設定。
  2. **10 題**：`random.Random(20261018).sample(sorted(通過稽核的題號), 10)`，附題目、gold、推算鏈、依據節經文、答案鍵、可接受寫法。Kay 每題選 accept（不動）／revise（寫意見，跑 fix 再複驗）／drop（刪題；同 slot 還有嘗試次數就重出 1 次，否則留空）。頁上寫明：「題目的接受／修改／刪除只依經文與題目本身判斷，不看層列對錯。」
- 決定全部套用後才跑 K-U2 與 F2。F1 之前沒有 Kay 頁；分段參數在 F1 由本檔凍結。

## 8. 預算與 CLI

- **帳本**：OUT/ho 所有 transcript 的 `total_cost_usd`，加 CLI 重測（transcript 留在 OUT/ho/probe/，不刪）。
- **單次上限**（`--max-budget-usd`）：出題 4、修題 3、稽核 1.5 USD。CLI 可能多跑一輪才停，實際花費可能略超過單次上限，因此總花費也可能略超過 140；照實報告。
- **硬上限 140 USD**：每個 job 啟動前，若「已花＋該 job 上限」>140 就不啟動。主出題階段被擋下且「已花＋出題上限 4」>140 時停止出題（`run_ho_a.py loop` 自動，或 `stop-drafting`；記在 state `cap_stop`）：不再出新題，等待中的稿在剩餘預算內照常稽核／修題，被上限擋下的稿刪除；之後用已通過的題走 Kay 抽查頁與 K-U2，過了就凍結並照實報告 n，不過就停。
- **pilot 後重估**：預估＝已花＋剩餘 slot 數×pilot 平均每題成本。>140：取消所有 slot 3（目標每段最多 2 題，共 27 題；I6 只有 1 題）；仍 >140：停止出題，用已通過的題走 K-U2，過了就凍結並照實報告 n，不過就停。
- **CLI 重新釘版**（F1 前由主程序執行 `ho_a/probe_cli.py`，≤1 USD，結果在 OUT/ho/probe/；啟動前先核 bt_guard 是 HO 原檔）：參數與正式 launch 相同、cwd=/srv、假題 `bt books`、`bt v rut.1.16`，跑 3 次。檢查 (1) init 的 cwd 是 /srv、tools 只有 Bash，且全程由 claude-opus-5-5 回答（沒有模型改派）；(2) 現場的 `ls` 被 hook 擋下，另外離線把 `bt x; ls`、`ls`、`bt v ../*`、`cat /etc/passwd` 餵給 hook 包裝檔，都要被拒（exit 2）；(3) thinking 摘要非空；(4) 沒載入 CLAUDE.md 或 memory：可見文字沒有記憶標記、auto-memory 目錄為空、第一個請求的 prompt（input＋cache token）≤6000（使用者 rules 單獨就約 16 萬字元，載入任何說明檔都會超過）；(5) result 有 structured_output。
  - 全過：CLAUDE_VERSION 改釘 `2.1.302`（HO 原釘 2.1.299）。
  - 只有 (3) 不過：拿掉 `--thinking-display`，接受 transcript 沒有 thinking 摘要並揭露（盲化檢查不依賴 thinking）。
  - CLI 直接拒絕 `--thinking-display`（帶旗標的每次都沒有 init、也沒有成功的 result；verdict `rerun_no_thinking_display`）：用 `--no-thinking-display` 重測一次。全過就以 `pin --after-rejected 〈第一次 verdict〉` 釘 thinking_display=false，並記揭露文字；其他結果就停止。這是事先登記的順序，不算臨時修基礎設施。
  - 其他任何一條不過：停止，先修基礎設施。

## 9. 程式與測試

- `A/confirm/`：`c_common.py`（路徑、REPS 全 3、SEED 20261018、USD 上限、凍結 sha、措辭）、`segments.py`、`support.py`、`alias_table.py`、`k1.py`、`items_c.py`、`ho_a/*`（HO fork）、`collect_ctx.py`、`arms_c.py`、`score_c.py`、`run_c.py`、`analyze_c.py`、`report_c.py`。
- 測試 `evaluation/tests/test_kg_cards_confirm_a*.py`：不啟動 agent、不呼叫 Ollama；需要 store 的測試在 store 未掛載時 skip。必含：14 段、44 候選、35 slot 重現且與 PYTHONHASHSEED 無關；家譜捷徑（J09→J11 是、J09→J12 否）；歸段與名稱解析（「耶羅波安（約阿施的兒子）」→I13）；mech 合成題逐條擋（含 seeds_chain、非必要父名、同名標記洩漏鏈）；bt_a 拒 old／pid；K1 在 stage-0 模板題以 gold 種子全中；score_c 以 REPS=2 重現 stage-0 scores；analyze 精確 p；collect_ctx 拒收各類錯誤；run_c 防呆。

## 10. 揭露事項

- 題型對齊引擎模板範圍（FP 的設定，出題者看不到引擎）；陷阱豁免比開發集模板題寬（保守方向，模板規則列為敏感度）。
- 交界王出現在兩段的題目裡；確認題與開發模板題的（種子, 答案）可能重疊（只有 39 王，臂是固定程式，不算洩漏），兩者都描述題數。
- B0＝同 prompt、無輔助區塊，不是 prod 原 prompt。猶大中段只剩跨節 k=3 題與 S4。
- 交給出題者的範圍讓他知道負責哪一段王（D7 已接受的輕度洩漏）。

## 附錄 C（F2 時填入）

`questions_frozen.json` `93ca70af9f1266b58f2cb7ccbd67f6e6851852d9e7a65e9c839e4186ea9822be`（32 題，14 段；清單 `questions_frozen_manifest.json`）。各段題數：I1 3、I2 3、I3 2、I4 2、I5 2、I6 1、I7 3、I8 2、I9 3、J1 3、J2 1、J3 3、J4 2、J5 2；題型：S1a 24、S1b 2、S1c 4、S4 2。空 slot：J2 的 S1b、J2 的 S4、J4 的 S4（三次嘗試用完）。

| 題號 | 段 | 題型 | 鍵型別 | pilot |
|---|---|---|---|---|
| QI1s1a1 | I1 | S1a | name | 是 |
| QI2s3a1 | I2 | S1c | name | 是 |
| QI3s1a1 | I3 | S1a | name | 是 |
| QI4s1a1 | I4 | S1a | name | 是 |
| QI6s1a1 | I6 | S1a | name | 是 |
| QI7s1a1 | I7 | S1a | name | 是 |
| QI8s1a1 | I8 | S1a | name | 是 |
| QI9s1a1 | I9 | S1a | name | 是 |
| QJ2s1a1 | J2 | S1a | name | 是 |
| QJ1s2a2 | J1 | S1b | number | 是 |
| QJ5s1a2 | J5 | S1a | name | 是 |
| QI1s2a1 | I1 | S1a | name |  |
| QI2s1a1 | I2 | S1a | name |  |
| QI3s2a1 | I3 | S1a | name |  |
| QI4s2a1 | I4 | S1a | name |  |
| QI5s1a1 | I5 | S1a | name |  |
| QI7s2a1 | I7 | S1a | name |  |
| QI8s2a1 | I8 | S1a | name |  |
| QI9s2a1 | I9 | S1a | name |  |
| QJ1s1a1 | J1 | S1a | name |  |
| QJ3s1a1 | J3 | S1a | name |  |
| QJ4s1a1 | J4 | S1a | name |  |
| QI1s3a1 | I1 | S1c | name |  |
| QI2s2a1 | I2 | S1a | name |  |
| QI5s2a1 | I5 | S1a | name |  |
| QI7s3a1 | I7 | S1c | name |  |
| QI9s3a1 | I9 | S1c | name |  |
| QJ1s3a1 | J1 | S4 | name |  |
| QJ3s2a1 | J3 | S1b | number |  |
| QJ4s2a1 | J4 | S1a | name |  |
| QJ5s2a2 | J5 | S1a | name |  |
| QJ3s3a1 | J3 | S4 | name |  |

## 執行紀錄

- 2026-10-19 00:41 CLI 重測第 1 次（verdict_1，0.26 USD）：action＝stop，只有 (4) 不過。原因與處理（F1 之前，沒有任何臂或題目輸出）：
  - (4) 誤判：當時的假題要代理列出看到的說明檔，代理在 thinking 裡寫「沒看到 CLAUDE.md」，被記憶標記擋下；三次自報的 context 檔都是空的，第一個請求的 prompt 都只有 2,786 token，沒有載入任何說明檔。改成機械判定（上面 §8 第 4 條），刪掉自報欄位。
  - 新發現：3 次中有 2 次被 Opus 5.5 的安全機制（cyber 類）擋下，CLI 改派 claude-opus-4-8 回答；init 仍寫 claude-opus-5-5，所以舊的 (1) 沒抓到。10-14 HO 的 probe b、c 也有同樣情形，當時 12 個正式出題、稽核與修題 job 都沒有。判斷是假題叫代理去試被擋的串接指令所致：假題改成只在現場試 `ls`，串接指令改離線檢查 hook；(1) 加上模型改派檢查；正式 job 遇到改派一律當基礎設施失敗重跑、不用該次輸出（§2.4）。
  - 依 §8「其他任何一條不過：停止，先修基礎設施」修完後重測。
- 2026-10-19 00:47 CLI 重測第 2 次（verdict_2，0.10 USD）：5 條全過（3 次都由 claude-opus-5-5 回答、沒有改派；現場 `ls` 與離線 4 條都被拒；thinking 摘要非空；第一個請求 prompt 2,667 token；有 structured_output）。釘 2.1.302、thinking_display＝true。帳本 0.36 USD。
- F1：本檔、`A/confirm/`、測試（123 passed）一起 commit；之後才開始 pilot 出題。
- 2026-10-19 00:58 pilot 完成（帳本 6.10 USD；pilot 5.74）：12 slot 通過 11（J4 的 S4 三次嘗試都沒出成，留空），0 次模型改派，transcript 盲化 0 違規。K1（`k1.json`）＝11/11＝1.000 ≥0.80，通過；G-ref 版本也是 11/11（描述）。重估（一次）：每題平均 0.52 USD，剩 23 slot，預估總額 18.1 USD，action＝none，不取消任何 slot。
- 2026-10-19 01:27 出題完成（帳本 17.89 USD）：35 slot 通過 32，14 段都有題；空著的 3 個 slot（J2 S1b、J2 S4、J4 S4）都是 3 次嘗試用完。共 86 個 job，0 次模型改派，transcript 盲化 0 違規。
- 2026-10-19 01:28 Kay 抽查頁（`ho/kay/kay_page.html`，sha `2c9821d7…`；抽樣紀錄 `kay_sample.json`）：層 20 列、題 10 題，等 Kay 決定。
- 2026-10-19 09:16 Kay 要求改發私人網頁。`ho/kay/build_kay_artifact.py`（sha `5b288b94…`）把 `kay_page.html` 的 body 內容逐字包進新頁 `ho/kay/kay_check.html`（sha `19737b94…`；腳本先核 `2c9821d7…`，再斷言內容子串原樣出現），只換外觀與決定控制項。決定自動存到 artifact db `decisions/kay`，格式同 `kay_a.py apply` 的輸入；`kay_a.py apply` 要求每列都有決定；未選的列依給 Kay 的回覆說明（沒提到的當「對」與 accept）在轉 D.json 時明寫補上，並記錄補了哪幾列。網頁只有 Kay 能開，store 只放副本。
- 2026-10-19 09:57 Kay 回傳決定（`ho/kay/kay_decisions.json` `5679f6bc…`；與網頁存的 `decisions/kay` 逐欄相同，沒有空白列，不必補預設）。`kay_a.py apply`：K0-1b＝0/20 列錯，通過；9 題 accept；QI3s2a1 revise（在「暗利」一步的依據補王上16:21）；無 drop。
- 2026-10-19 09:57 修題第一次沒啟動：CLI 在 06:33 自動更新成 2.1.303，launch 的版本檢查拒絕（「claude --version is '2.1.303'; pinned 2.1.302」），沒有花費。2.1.302 執行檔仍在 `~/.local/share/claude/versions/2.1.302`（sha `60d7eb7f…`），改以 PATH 最前面放一個指向它的 `claude` 連結重跑；程式碼與釘版檔都沒改，版本檢查照常核對並通過。child PATH＝`<root>/bin`＋父程序 PATH，`<root>/bin` 只有 bt 包裝檔。
- 2026-10-19 09:59 QI3s2a1 修題（0.19 USD）＋複驗 ok（0.18 USD），兩次都只有 claude-opus-5-5、0 次改派、transcript 0 違規。只補依據節，題目、答案、答案鍵不變；這題不是 pilot 題，K1 不重算。帳本 18.25 USD。
- 2026-10-19 09:59 K-U2：凍結單位 n＝14 ≥ 12，通過。F2：`questions_frozen.json` `93ca70af…`（32 題），寫入 `inputs_manifest.json` 的 `frozen`；附錄 C 已填。之後不再改題。
- 2026-10-19 10:00 Kay：「現在就跑」，授權白天跑 Ollama 夜（原預設晚上）。開跑前 /api/ps 沒有載入任何模型。
- 2026-10-19 10:06 collect：32/32 題，每題 5 段，build_id 全是 `b20261008_e05d3e55`，逐塊 sha 核對通過，沒有重試。F3：`contexts.json` `672f6e2c…`。prepare：items 32、單位 14（`items.json` `a601d13e…`），code_confirm 記下；dry-run 合成集 prompt sha 全對。
- 2026-10-19 10:06–10:09 種子：32/32，一輪完成，沒有重試（`gen_seed.jsonl` `19a87d42…`）。開跑時 /api/ps 已載入 gemma4:e4b-it-q8_0（collect 打 backend 時載入的，同一模型）。
- 2026-10-19 10:09–11:06 各臂：canary（32 個種子＋前 30 個臂呼叫）10:12 通過：0 缺漏、0 錯誤、0 截斷（`canary.json` `c960ae26…`）。全部 477/477，一輪完成，沒有重試（`gen_arms.jsonl` `98e5916c…`）。477＝G-auto、T-canon、T-rows、B0 各 96，加 G-ref 93：G-ref 在 QJ4s1a1 棄權，依 §5 用 T-rows 替補，不出 job。G-auto 沒有棄權題。
- 2026-10-19 11:07 canary 複查通過。截斷（`trunc_report.json`）：種子 0/32、各臂 0/477，done_reason＝length 0 次；prompt＋eval 最大 5,892，num_ctx 131,072。prepare 之後的程式修改 0 次。跑完 /api/ps 仍載著 gemma，是預設的 5 分鐘 keep-alive（11:11 到期），沒有手動卸載。Ollama 實際使用 10:00–11:07，約 67 分鐘。
- 2026-10-19 11:07 score 一次：477 筆，缺漏 0（`scores.json` `bca7bdf4…`）。analyze 一次（`report.json` `aefbd6fe…`、`report.md` `57f9e27b…`）。
- **判定：H1、H2 皆過。**寫死的措辭（§6）：「regex 可建的王朝鏈上，程式多步走訪與推算，在王朝年代題上顯著優於同流程的正典經文窗與層列平鋪」；範圍限定「只限王朝年代題（S1、S4 窄題型、出題前配額的盲題）」。
  - H1 G-auto−T-canon：單位 n＝14，Δ̄＝+0.456，95% CI [+0.317, +0.599]，精確 sign-flip p＝0.00024，W:L:T 13:0:1。
  - H2 G-auto−T-rows：單位 n＝14，Δ̄＝+0.266，95% CI [+0.075, +0.433]，精確 p＝0.01562，W:L:T 12:1:1。
  - K3：錯答率 G-auto（含替補）0.198、T-canon 0.635，差 −0.438，未超過 +0.05。
  - 描述（不進判定）：
    - 題層平均：G-auto 0.802、G-ref 0.802、T-rows 0.521、T-canon 0.365、B0 0.208。
    - G-auto−B0 +0.647（14:0:0）；G-ref−G-auto +0.008（2:2:10）。
    - H2 配對在兩個分層的 CI 含 0：非 pilot 21 題 +0.153 [−0.153, +0.431]；S1a +0.190 [−0.012, +0.381]。
    - 與開發題（種子, 答案）重疊 6 題；gemma 與 gold 種子解析一致率 0.250，但 a＝0.875。
    - 陷阱規則用模板規則時，兩個配對都更大；沒有 `ref_disagree` 題。
- 花費：claude 帳本 18.25 USD（上限 140），Ollama 這段 0 USD。不寫「圖譜有效」或「圖譜無效」；論文不動。
