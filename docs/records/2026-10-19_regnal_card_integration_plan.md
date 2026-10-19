# 王朝年表卡接進架構：計畫（2026-10-19）

**Kay 2026-10-19 裁決：「照你的建議，五項都同意，開始做」**。D1 同意 P5 窄例外；D2 走方案甲（release 新層）；D3 沿用確認版格式；D4 用 A2＋A5 滿足非劣性；D5 上 prod 後預設開。

依據：實驗 A 確認集（`evaluation/experiments/2026-10-18_kg_cards/confirm_A.md`，commit 2d6468d）H1、H2 皆過。結論只限王朝年代題：

- H1：G-auto 對正典經文窗，Δ̄ +0.456。
- H2：G-auto 對「同一份層列交給 LLM 自己推」，Δ̄ +0.266。

prereg D1 寫明「上 prod 另需 500 題答案層非劣性」。本計畫要把**確認過的那套處理原樣搬進 prod**，只在王朝年代題上啟用，其他題逐位元不變。

## 1. 實驗和 prod 的差距

| 項目 | 確認集用的 | prod 現在 | 接上要做的 |
|---|---|---|---|
| 王朝層 | store `reports/kg_cards_20261018/A/layer_auto.json` `932d2242…`（27 KB；regex 從 `text@247eafe44b02` 建，Kay 抽查 20 列 0 錯） | 沒有。P5 已取消，KG 只有 L0＋L1 | 要 P5 的 prod 窄例外（§4 D1），並決定層放哪（D2） |
| 觸發 | 沒有。32 題全是王朝年代題 | — | 新增觸發條件，只在王朝年代題上開卡 |
| 種子 | 一次 gemma 呼叫（`seeds_a.py` prompt），讀題目與 top-5 段落 | 沒有 | 只在觸發時多一次呼叫（確認集中位數 4.8 s、最大 7.2 s） |
| 推算 | `engine.py`：±3 位繼位、篡位序、出生時在位、相隔幾代；≤900 字 | — | 移到 backend，逐位元對等 |
| 生成 prompt | prod prompt，規則 1 放寬到「輔助資料」，加輔助資料區與「逐步推理＋答案：」指示（`cards_common.py`） | `generator.py` 原 prompt | 觸發時用確認版 prompt，未觸發時原 prompt 一字不改 |
| 基底 context | prod `/query` retrieval_only、top_k 5、build `b20261008_e05d3e55` | 同左（預設 top_k 5） | 不用改 |
| 生成參數 | temperature 0.1、num_predict 10000、num_ctx 131072（Ollama 預設） | 同左 | 不用改；client 逾時 120 s，確認集最長 16.8 s |

另外有兩件事要先說：

- **500 題基準裡幾乎沒有這類題。** 我用一版草擬的觸發條件（題目點名鏈上的王，且有年代線索詞）在 CPU 上試算過：
  - 500 題中有 21 題點名鏈上的王，只有 2 題觸發，而且兩題都是誤觸：PERSON_QUESTION_038 由「年間」觸發，EVENT_QUESTION_059 由「先後順序」觸發。
  - 確認集 32 題觸發 31 題，開發集 30 題觸發 28 題。
  - 所以接上之後，500 題的主數字預期不會動，增益只會出現在王朝年代題上。
- **這次草擬時已經看過 500 題和確認集的觸發結果。** 正式的觸發規則只用開發集和題型定義來定；兩組量到的數字都只當描述，並在報告裡註明。

## 2. 設計

### 2.1 資料層（建議走 release，見 D2）

- 在 ragdata 加一個新層 `regnal@<digest>`，`depends_on` 寫 `text@247eafe44b02`。
  - stage 移植 `A/layer_build.py`、`layer_core.py`、`layer_re.py`。
  - 閘門用硬條件：產出的層必須與審過的 `932d2242…` 逐位元相同；機械檢查（鏈上節點數、同步紀年數、不聯集別名、衝突逐筆列出）照 stage-0 K0。
  - 契約檔叫 `regnal_layer.json`，進 release 的 `contracts`。contract_version 升 1.2.0。
- 組新 release，產生新 build_id；其他各層全部沿用原 digest。接著照現行流程走：load → verify → promote staging → 驗收 → promote prod。
  - 檢索資料是同一批層，loader verify 會核對內容，所以檢索結果在構造上不變。
- backend 讀 `regnal_layer.json` 時照 manifest 核對 sha。沒有這個檔的 build（例如回滾到 R2）自動關掉卡片，啟動時記一行 warning。

### 2.2 backend 流程（`routers/query.py`）

依序是：檢索 → **觸發判斷** → （觸發時）種子呼叫 → 推算卡 → 生成。

- **觸發**（`utils/regnal/gate.py`，CPU，只看題目文字），兩個條件都成立才開卡：
  1. 題目點名鏈上的王（名稱與別名都從層讀）；
  2. 題目有確認過的題型線索：之前／之後第 k 位、前一位／後一位、繼位者、篡位、出生時在位、相隔幾代。

  「年間」「在位時」「先後順序」這類泛用詞不算線索。卡片只在量過的題型上開。
- **種子與推算**：
  - `seeds_a.py` 的 prompt 和 parser 原樣搬到 `utils/regnal/seeds.py`。
  - `engine.py` 和它用到的 `regnal.py` 函式搬到 `utils/regnal/engine.py`。
  - 種子解析不到，或引擎沒有寫出推導行時，不開卡，走原路徑（這和實驗裡的「棄權」不同：實驗是用 T-rows 替補，prod 改成直接走原 prompt）。
- **生成**：`generate_answer(question, sources, aux_block=None)`。
  - `aux_block` 是 None 時，送出的 messages 必須和現在逐位元相同，用單元測試鎖住。
  - 有卡片時，用 `cards_common.py` 的 SYSTEM_PROMPT 和 USER_TEMPLATE，逐字搬過來。
- **回應**：新增 `aux_card` 欄位，內容包括：交給生成器的卡片原文、種子、每列依據的經節（層裡每個欄位都有 evidence）、層 digest。
  - `sources` 不變，所以檢索指標不受影響。
  - 使用者看得到卡片和它的出處。
- **開關**：請求參數 `use_regnal_card: bool | None`，加上 settings `rag_regnal_card`，做法同 `use_graph`。注意容器 env 是快照，改預設要重建容器。
- **紀錄**：每次觸發記一行 log：題目 hash、種子、推導行數、有沒有開卡。

### 2.3 評估端

- judge 的 context 要附上 `aux_card`（`evaluation/src/context_blocks.py` 和 quick_faithfulness 的收集器），不然由卡片推出來的句子會被判成「沒有出處」。
- 確認集 32 題留在 store 當王朝年代回歸集。題目文字不進 repo。

## 3. 驗收（看結果前寫死；不過就停下，修好再跑，不改門檻）

| # | 內容 | 資源 | 過關 |
|---|---|---|---|
| A1 對等 | 用記錄下的 contexts 和種子輸出，讓新 backend 程式組出確認集 32 題、開發集 30 題的 prompt，與實驗 `arms_jobs.json` 的 G-auto prompt 和種子 prompt 比對 | CPU | 62/62 逐位元相同 |
| A2 未觸發不變 | 單元測試：沒有卡片時 messages 逐位元等於現行版本；觸發判斷只看題目文字 | CPU | 測試通過 |
| A3 觸發清單 | 500 題逐題列出觸發的題，看是不是王朝年代題；確認集的召回只描述 | CPU | 500 題誤觸 0 題。有誤觸就只依開發集和題型定義收緊規則，再跑一次 |
| A4 staging 端到端 | 確認集 32 題打 :8002 `/query`，卡片開，跑 1 次 | Ollama 約 10–15 分鐘 | 0 錯誤、0 逾時；觸發題的 key_score 平均 ≥0.70（確認集 G-auto 是 0.802；低於 0.70 就查接線，不上 prod） |
| A5 500 題非劣性 | 未觸發的題靠 A2 在構造上成立。A3 之後如果還有觸發題，那幾題卡片開、關各跑 3 次，比 coverage 和 faithfulness strict（judge 看得到卡片） | 預期 0 題；有的話 Ollama 幾分鐘、judge <1 USD | 逐題列出，任一題 strict faithfulness 下降就停，請你決定 |
| A6 build 一致 | 新 build 的 loader verify 通過；除 regnal 以外，各層 digest 與 `b20261008_e05d3e55` 相同 | CPU | 通過 |

全部過關後，請你說「上 prod」，我才 promote prod 並換容器。換完後在 prod 用確認集抽 5 題、一般題抽 5 題做 smoke。

## 4. 要你決定的事

1. **D1：P5 的 prod 窄例外。** 王朝層進 release，只供王朝年表卡使用；regex 建，層檔就是審過的 `932d2242…`。其他身分層和關係層照樣不做。**建議同意。**
2. **D2：層放哪裡。**
   - 方案甲（建議）：照 §2.1 當 release 的新層。資料跟 build 綁在一起、有 sha 核對，回滾 build 時卡片自動跟著關。代價是要組新 release 並 load 一個新 build。
   - 方案乙：把層檔放進 backend 映像，用程式碼釘 sha。比較快（約省半天），但違反「backend 讀的資料都由 release 釘住」的原則。
3. **D3：觸發題的回答格式。** 沿用確認版，也就是先逐步推理、最後一行寫「答案：」。這類題的回答風格會跟其他題不同。**建議沿用。**拿掉指示等於換了處理，要重新量。
4. **D4：怎麼滿足「500 題答案層非劣性」。** 用「未觸發題在構造上不變（A2）＋觸發題逐題比（A5）」來滿足。**建議同意。**另一個做法是 500 題全部重跑生成，約 Ollama 1–1.5 小時加 judge 費用；但九成九以上的題 prompt 完全相同，多跑也得不到更多資訊。
5. **D5：上 prod 後預設開，還是只在請求帶參數時開？** **建議預設開**，因為觸發條件已經收得很窄。

## 5. 工時與資源

- 工程約 2–3 天：
  - ragdata 層、閘門、契約：0.5–1 天；
  - backend 移植與測試：0.5–1 天；
  - 評估端：約 2 小時；
  - release、load、staging：約半天（含等待）。
- Ollama：A4 約 10–15 分鐘，A5 預期 0。
- claude 預期 0 USD；只有 A5 有觸發題時才會花，<1 USD。
- prod 只有最後 promote 和換容器才會動，那一步要你點頭。

## 6. 風險與回滾

- **範圍只有分國後的王**（列王紀上 11:41 之後、列王紀下、歷代志下 9:29 之後）。題目點名掃羅、大衛、所羅門不會觸發。南北國的年份對照題，引擎沒有專門的推導行，這類題也不在觸發範圍內。
- **同名王**（例如約蘭、約阿施）：引擎分不開時會棄權，改走原路徑。
- **層的狀況**：記錄了 7 筆欄位衝突，處理方式是保留第一個值；K0 抽 40 欄的精確率是 1.0，Kay 抽查 20 列 0 錯。
- **確認集的弱點照搬過來**：H2 在非 pilot 21 題上是 +0.153，CI 含 0；有 6 題與開發題重疊。
- **主數字不會動**：500 題主數字預期不變，價值只看得到回歸集和真實使用者的王朝年代題。
- **回滾**有三種，由輕到重：
  1. 請求參數關掉；
  2. 改 settings 後重建容器；
  3. `ragdata promote --env prod --rollback` 回到 R2 build＋r2 映像；R2 build 沒有 `regnal_layer.json`，卡片自動關。

  換掉容器後，r2 映像沒有容器引用，Komodo 會在 24 小時內 prune。tar 已經在 `/mnt/ollama-data/bible_rag_bak/20261008/images/bible_rag-backend_r2.tar.zst`，回滾前先 `docker load`。

## 7. 這次不做

- B（家譜卡）不做。
- 不擴到別的題型。
- 不做跨國年份推導。
- 不改 500 題。
- 論文等架構定案後再跟你談。

## 執行紀錄

- 2026-10-19 13:35 王朝層進 store（G-REGNAL 通過；層的種類見下面「層名更正」）；契約檔 `regnal_layer.json` sha `932d2242…`，就是審過的 `layer_auto.json`，兩國鏈 19／20、衝突 7（commit b27e4f5）。
  - release 改成可帶選用層：沒有 regnal 的 R2 release（`b20261008_e05d3e55`）用新程式重組，位元組不變；帶 regnal 時 contract_version 1.2.0，多一個契約檔，其他契約與各層 digest 與 R2 相同（`test_regnal.py`）。
  - 另外發現：R1 release（`b20261008_6daa4f31`）在未改動的 HEAD 上就重組不過（R1 的 events 層有 `anchor_changes.jsonl`，現行閘門不收），與這次無關；回滾目標是 R2。
- 2026-10-19 backend 接線（commit 1efcc85）。
  - **A1 對等：通過。**用 store 記錄的種子輸出與 contexts，backend 組出的卡片 prompt 與實驗 G-auto 的 system／user 逐位元相同：確認集 32/32、開發集 30/30；種子 prompt 的 sha 也與兩次 run 記錄的 `prompts_sha256` 相同（`test_regnal_parity.py`）。
  - **A2 未觸發不變：通過。**沒有卡片時 messages 等於原本的 SYSTEM_PROMPT／CONTEXT_TEMPLATE，兩者 sha 與改動前相同（`test_regnal_card.py`）。
  - 觸發規則只依題型定義與開發集定案（開發集 27/30 觸發；沒觸發的 3 題：一題問親屬、兩題沒點名王），在量 A3 之前 commit。
- 2026-10-19 **A3 觸發清單：通過。**500 題中點名鏈上王的有 21 題，觸發 0 題，誤觸 0。
  - 確認集召回（只描述）：26/32。漏掉的 6 題全是 S1a，問法是「之後，第二位作…王」（中間有逗號）或「往前數第二位」。
  - **事後修正（揭露）**：看了這 6 題之後，把 S1a 線索改成容許中間的標點、並收「往前數／往後數」。改後確認集 32/32（樣本內，不當證據）、開發集 27/30 不變、500 題仍觸發 0。修正只放寬標點與數法，題型範圍沒變。
- 2026-10-19 **層名更正**：原本新增層種類 `regnal`，要改 `ragcommon/ids.py`。但 `metric_version` 是把 ids.py 等檔案的內容雜湊起來算的，一改就從 `4d0826bb8d14` 變掉，GD／QD／BA 三個已結案實驗的完整性檢查會拒跑（evaluation 測試多出 20 個失敗、4 個 error），之後的新結果也都會被工具判成不能和舊結果比。
  - 改用 ids 裡本來就為 L3「規則關係層」預留的 `relations`（設計 §13.1；ids 的關係型別也預留了 SUCCEEDED）。ids.py 不動，`metric_version` 維持 `4d0826bb8d14`。
  - 內容仍只限王朝公式（P5 窄例外）；其他關係照樣不做。層是 `relations@a04b67a301dc`（digest 只看檔案內容，和原本相同）；建法 `ragdata build relations --text …`。原本的 `layers/regnal/` 目錄已刪，release 帶它時 `layers.relations` 有值、contract_version 1.2.0；不帶時 `relations` 照舊是 null，位元組不變。
  - 同時把 `generator._build_context` 的名字改回來（BA 實驗驅動程式依賴它），另外加一個公開別名 `build_context`。
- 2026-10-19 release `b20261019_18aa84ad`（各層＝R2，加 `relations@a04b67a301dc`），load（34,058 點）。**A6 通過**：verify 的 G-SCHEMA.pg、G-PROJ C1–C6 全綠，contracts 目錄 10 個檔，含 `regnal_layer.json`。
- 2026-10-19 映像 `bible_rag-backend:r3`（commit e61f579；`docker build --build-context uvcache=…`），digest `sha256:7998a43a…`。`ragdata promote --env staging` 到新 build（前一筆是 R2＋r2），`backend-stg`（:8002）用 r3 起來，握手通過，啟動 log：「Regnal layer 932d2242dc3f (chains {'I': 19, 'J': 20})」。prod（:8000，r2）沒動。
- 2026-10-19 **A4 staging 端到端：通過**（`evaluation/experiments/2026-10-19_regnal_card/a4_staging.py`，結果在 store `reports/regnal_card_20261019/a4/`）。
  - 確認集 32 題各打 1 次 `/query`：0 錯誤、0 逾時，build_id 全是新 build；每題 17–34 秒（含意圖分類、檢索、種子、生成）。
  - 31 題有卡，有卡題 key_score 平均 0.742 ≥ 0.70；同 31 題在確認集的 G-auto 平均 0.796（這次只跑 1 次）。全部 32 題平均 0.719。
  - 沒卡的 1 題（QI1s2a1）：觸發有過，但這次種子呼叫抽到「以色列｜耶羅波安」，以色列鏈上有兩位耶羅波安，引擎分不開就棄權，改走原路徑（沒有「答案：」行，記 0）。確認集那次抽到的是另一位王。
  - Ollama：開跑前 /api/ps 是空的，約 12 分鐘，跑完 gemma 照預設 keep-alive 自動卸載。
- **A5**：500 題觸發 0 題，沒有觸發題要逐題比；未觸發題由 A2 在構造上不變。
