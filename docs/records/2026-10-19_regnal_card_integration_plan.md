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
- **S4 守門的上線順序**（2026-10-19 加，分支 `feat/regnal-s4-guard`，還沒上線）：
  - 守門預設開，而且直接採信層裡 age／reign 衝突的替代值。
  - 舊層 `relations@a04b67a301dc`（`932d2242…`）把約西亞的「作王第 N 年」記成 reign 衝突（約西亞的替代值是 18）。守門開在這一層上時：
    - 62 張卡改了 13 張（確認集 6、開發集 7，實測）；
    - 約哈斯、約雅敬的 born 行是對的，卻被拿掉；
    - 開發集 T_S4_02 在 G-auto 是 2/2 答對，被拿掉的正是這一題的 born 行（實測）。
  - 修正層（`fix/regnal-layer`，規則 R10，`1789c0de…`）上只改 6 張（實測）。
  - 要遵守的事：
    - 兩個分支同一批合併，放進同一個映像（r4）；
    - r4 只配帶修正層的 build 做 promote，不准配 `b20261019_18aa84ad`；
    - 回滾時映像和 build 一起回，也就是 r3＋`b20261019_18aa84ad`（r3 沒有守門）；不准只把 build 退回去、卻留著 r4。
  - 層這一端有機械檢查：`fix/regnal-layer` 的 G-REGNAL 釘住修正層的 sha 和衝突數 3。程式和 build 的配對沒有機械檢查，只能靠這一條。
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
- 2026-10-19 **程式審查（子代理，唯讀）**：invariant 1–3、8 沒有問題（release 位元組、兩種 prompt、移植逐字、judge context 只附一次）。找到 5 個問題，都已處理：
  1. text 層一變，`pipeline run` 會停在 relations：保留這個行為（不重審就不產出少了年表卡的 release），出路寫進 `rebuild_pipeline.md` §4。
  2. 種子 regex 遇到退化輸出（大量空白）會回溯數秒到一分鐘，卡住 event loop：解析前先跳過超過 64 字的行，同一段輸出只解析一次。對等測試照樣 62/62。
  3. 觸發太寬：「繼位時幾歲」「篡位後做了什麼」這類事件題也會觸發。每個線索都改成要問序數或「是誰」：
     - S1a：「接續…作王的是誰」「繼位的是誰」；
     - S1c：序數後 12 字內出現「篡」，因為題型定義本身寫成「第 n 個篡位（背叛、殺王奪位）」；
     - S4：「出生時…在位／作…王／王是誰」。
     - 改後的觸發數：500 題（v1、v2）都是 0；開發集 27/30；確認集 32/32（樣本內）。收緊後確認集一度是 29/32，漏的 3 題是序數和「篡」中間隔了「背叛君王、殺王」，所以放寬到 12 字。
  4. 壞掉的層檔會讓 backend 啟動或 G-REGNAL 直接拋例外：改成 handshake mismatch 或紅燈。
  5. semantic_only 與 use_graph=false 的消融臂原本會有卡片：改成預設關閉，請求帶 `use_regnal_card` 才開；evaluation 的 `rag_client` 也加了這個開關。
- 2026-10-19 審查修正後重建 r3（commit 3cadd72，digest `sha256:6168c213…`），staging 重新 promote（前一筆是同 build＋舊 r3），`backend-stg` 換上新映像，握手通過。
- 2026-10-19 **A4 重跑（新 r3）：通過**（store `reports/regnal_card_20261019/a4_r3b/`）。32/32 有卡，key_score 平均 0.812（確認集 G-auto 0.802），0 錯誤、0 逾時；每題 17–27 秒，中位數 21 秒。Ollama 約 12 分鐘，開跑前 /api/ps 是空的。第一次 A4（舊 r3）的結果留在 `a4/`。
- 驗收 A1–A6 全部通過。prod（:8000，r2＋`b20261008_e05d3e55`）到這裡都沒動；上 prod 等 Kay。
- 2026-10-19 Kay：「上 prod」。
  - 15:28 `docker-compose.yml` backend 改成 `bible_rag-backend:r3`（commit f0cfc71）；`ragdata promote --env prod --build b20261019_18aa84ad --image sha256:6168c213… --yes-prod`（前一筆：`b20261008_e05d3e55`＋r2 `sha256:c7926629…`）。
  - 只換 backend 容器（`docker compose -p bible_rag -f docker-compose.yml up -d --no-deps --no-build --pull never --wait`），15:28:52 healthy；health：build `b20261019_18aa84ad`、handshake ok、無 mismatch；啟動 log：「Regnal layer 932d2242dc3f (chains {'I': 19, 'J': 20})」。切換前 Ollama 沒在用。
  - smoke20：20/20 通過（store `reports/regnal_card_20261019/prod/smoke20.json`）。
  - 確認集抽 5 題（四種題型都有）：5/5 有卡，4/5 答對；答錯的 QJ1s2a2（S1b）在確認集 G-auto 平均也只有 0.33（`prod/card5.json`）。請求只帶 question 與 include_context，沒有 `use_regnal_card`，走的是預設路徑；腳本是 a4_staging 的 post／score_line 在 shell 內直接呼叫，沒有另存。
  - staging（`backend-stg`）已停；staging 的 serving 列仍指向新 build＋r3。
  - 回滾：`ragdata promote --env prod --rollback --yes-prod`，compose 改回 r2，再跑同一個 `up`。r2 映像現在沒有容器引用，Komodo 24 小時內會 prune，到時先 `docker load` `/mnt/ollama-data/bible_rag_bak/20261008/images/bible_rag-backend_r2.tar.zst`。
- 2026-10-19 **上線驗證（workflow，3 個唯讀代理）**：部署狀態、輸出、回滾三個角度都判定正確。
  - 部署狀態逐項一致：compose、容器 image id、`rag_meta.serving`、`serving_history`、`rag_meta.builds`、contracts manifest、health 與啟動 log；啟動後 0 個 ERROR，45 個 POST 全部 200。
  - smoke20 的一般題在 log 裡沒有觸發卡片；trigger 在 GT v1、v2 各 500 題都是 0。
  - 處理掉的事：r2 映像沒有容器引用，會被 Komodo prune，已用 `bible_rag_backend_r2_pin`（不啟動的容器）釘住；r2 tar 的 sha 和 SHA256SUMS 相符；`rebuild_pipeline.md` §6 更新了 prod 配對，並補上 `docker load` 步驟。
  - 已知、不修：
    - 同一題每次的卡片可能不同：種子呼叫有隨機性，prod 和 staging 有 4/5 題抽到的王不一樣，分數相同。
    - 少數回答的「答案：」不在最後一行行首（計分照樣抓得到）。
    - 審過的層把所羅門算成猶大鏈的第一位，亞他利雅不在鏈上（stage-0 就知道的 38/39），所以「某王之前第 k 位」跨過這兩處時會差一位。
- 2026-10-19 晚～10-20 **r4（層修正＋S4 守門＋規則種子＋觸發放寬）上 staging，驗收全過**，詳見 `2026-10-20_regnal_r4_staging.md`。
  - release `b20261019_a86f2b06`，和 prod 的 `b20261019_18aa84ad` 只差 relations 一層（`relations@ee8e78c043d2`，檔 sha `252e0955…`）；映像 `bible_rag-backend:r4`（`sha256:ea94bd5e…`，commit 96843f0）。
  - r4 的處理方式和確認版不同：層修正、S4 守門、規則種子優先、觸發放寬。H1／H2 的措辭只屬於確認版，也就是 932d2242＋gemma 種子＋無守門。r4 只用樣本內回歸與 A4′ 驗收。
  - prod 仍是 `b20261019_18aa84ad`＋r3，上 prod 等 Kay。
