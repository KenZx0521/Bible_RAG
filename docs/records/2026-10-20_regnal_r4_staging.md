# 王朝年表卡 r4：層修正、規則種子、觸發放寬，staging 驗收與上 prod（2026-10-19 晚～10-20）

接續 `2026-10-19_kg_expansion_feasibility.md` §7-1～4（Kay 全照建議）與 `2026-10-19_regnal_card_integration_plan.md`。2026-10-20 08:53 起 prod 是 `b20261019_a86f2b06`＋`bible_rag-backend:r4`（§8），回滾目標是 `b20261019_18aa84ad`＋r3。

## 1. 現況

| 項目 | 回滾目標（10-20 前的 prod） | prod（10-20 起）與 staging（:8002） |
|---|---|---|
| release | `b20261019_18aa84ad` | `b20261019_a86f2b06`（只差 relations） |
| relations 層 | `relations@a04b67a301dc`（層 sha 932d2242） | `relations@ee8e78c043d2`（層 sha 252e0955） |
| 映像 | r3 `sha256:6168c213…` | r4 `sha256:ea94bd5e…`（commit 96843f0） |
| 種子 | gemma 種子呼叫 | 規則種子優先，棄權才叫 gemma |
| S4 守門 | 無 | G1＋G3（擋 born 行） |
| 觸發 | 舊規則（`90e6b528…`） | 放寬（`0fd58e6b…`） |

- **不要把 r4 配 `b20261019_18aa84ad`**：r4 的守門與規則種子只對修正層審過。回滾一律 r3＋`b20261019_18aa84ad` 一起回。
- 分支：在 `int/regnal-r4` 整合，prod 換好之後 fast-forward 併入 main。G-REGNAL 的期望值換成 252e0955 之後，舊 release 就不能重組；回滾不受影響。

## 2. 王朝層

- Kay 抽查 14 項（L1–L8 鏈與邊型別、D1–D3 刪除、S1 守門、P1–P2 預設）全部同意，沒有備註。
- K0-R：0/108、0/102，邊型別差異 0。K0-1′ 第一輪成立 3 筆死因出處錯，加了 R14 修掉；第二輪 0 錯。
- 鏈：猶大 20 位（亞她利雅第 7 位；所羅門記國別 U，不在任何鏈上），以色列 19 位。衝突剩 3 筆（亞哈謝 age、希西家 mother、約雅斤 age），補邊 0、鬼節點 0、同步 31/31。
- `ragdata build relations` 建出的檔和審過的候選層逐位元相同。release 只差這一層，load 34,058 點，verify 的 G-SCHEMA.pg 與 G-PROJ C1–C6 全綠。

## 3. 觸發放寬（問法集 qset.md §6；結果在 qset.md §13）

- P1（60 題正例，放寬前）R_trig 22/60＝0.367 < 0.70，照 §6 放寬。只看 P1 與開發集沒觸發的 3 題。
- 寫了三份草稿，在另寫的保留探測集上比：72 正例、72 近似題，寫的人沒看 P1 或任何草稿。

| 草稿 | 正例觸發 /72 | 種子錯 | 反例誤觸 /72 |
|---|---|---|---|
| 現行 | 27 | 0 | 0 |
| minimal | 44 | 0 | 0 |
| precision | 53 | 0 | 0 |
| grammar | 63 | 0 | 0 |

- 選 precision。grammar 稿在刁鑽近似題上誤觸 30/239（precision 12，現行 8），其中有會答錯的題型：外國王、非王的下一任。漏觸發只是照舊回答，誤觸卻會把卡片塞進沒量過的題型。
- 四角度審查（等價、回溯、誤觸、程式）找到這些問題，全數修掉：
  - 雙線索題裡，新線索搶先讓錨點移到別的王（構造題 301/550）；
  - 指代詞（那位王）藏在新線索的空檔裡；
  - S1b 數到別國或外邦的王位，例如「從亞撒到約沙法，以色列換了幾次王」；
  - S4 王位詞後面接別國；
  - 「X 年間的大祭司…下一任」；
  - 受害者題（死於政變的王）；
  - 「第二個王朝」；
  - 封閉的非王清單；
  - 一處二次方 lookahead；
  - 計時測試的盲點。
- 審查之前還修掉一個指數回溯：`王位(…|[,，、\s]*)*` 後面接 24 個逗號就要 0.9 秒，30 個約一分鐘；問題上限 500 字擋不住。
- 修好之後的檢查：
  - 舊規則觸發的題，觸發、規則種子與棄權理由全部不變（1,740 題，含 550 題雙線索構造題）；
  - 審查者的有害變體 24 題，新規則 0 題觸發；
  - 最壞耗時約 3 ms（500 字）。
- 正式結果：
  - P1：58/60（樣本內），近似題 0/15；
  - **P2**，唯一一次、樣本外：45/50＝0.90（95% CI 0.786–0.957），舊規則 22/50；R_card 44/50，舊規則 21/50；近似題新舊都是 0/13。
  - GT v1、v2 觸發 0；開發集 27/30、確認集 32/32 不變。§6-3 門檻全過，採用。
- 已知代價寫在 trigger.py docstring，例如：
  - 先數位置、再問那位王的事的複合題會取卡；
  - 以色列王的出生問猶大王會取卡；
  - 「北國以色列的王位」夾在兩位以色列王之間時，新線索不收。

## 4. 規則種子的樣本內回歸（`evaluation/experiments/2026-10-19_regnal_seed/`）

- prereg 定稿 5a7943c。trigger.py、seeds.py 在 Ollama 之前改釘一次（aa0201c）；62 題的觸發、種子與卡片都不變，jobs sha 649ef70e… 和 dry run 相同。
- 正式跑：store `reports/regnal_seed_20261019/r4_run1/`。354 次，0 錯誤、0 截斷，模型 digest 跑前跑後都對（9dcc3580…），約 31 分鐘；計分器在舊記錄上重現 0.802／0.767。
- **通過**（點估計門檻 −0.05）：
  - R1，確認集單位層 Δ̄ = **+0.202**（14 單位：規則臂平均 0.956、gemma 參考臂 0.754；8 個單位規則臂較好、1 個較差）；
  - R2，dev 觸發題 Δ̄ = **+0.151**（27 題：0.867 對 0.716）；
  - R3，截斷 0、錯誤 0。
- 確認集題平均 0.948 對 0.729；陷阱次數規則臂 1 次、參考臂 14 次。
- 最差的一題是 QJ1s2a2：規則 0、參考 0.33，守門拿掉了亞哈謝(J) 的 born 行。
- 這是樣本內：規則讀過這 62 題；這個門檻只抓得到約 ≥0.10–0.15 的破壞，不能宣稱非劣性。

## 5. A4′（staging 端到端）

- `a4_staging.py --url :8002`，store `reports/regnal_card_20261019/a4_r4/`：
  - 32/32 有卡，0 錯誤、0 逾時；
  - key_score 平均 0.875（門檻 0.70；r3 的 A4 是 0.812）；
  - 每題 12–19 秒。
- `a4_card_check.py`：32/32 卡片文字和本 checkout 的 CPU 規則卡逐字相同，seed_source 都是 rule，層 sha 252e0955（store `reports/regnal_seed_20261019/a4_check.json`）。

## 6. 新增的測試

- `backend/tests/test_regnal_r4_cards.py`：62 題經 `/api/v1/query` 的卡片、generator prompt 與種子呼叫逐題釘 sha。經審查補成走端點，4 種接線突變都抓得到。
- `backend/tests/test_regnal_trigger_time.py`：最壞耗時。每個字面詞，以及每個選項範例的每個前綴，後面接重複分隔符到 500 字；審查用的兩種回溯突變都會失敗。
- `evaluation/tests/test_regnal_qset.py`：每個觸發選項（含 group new 的子選項）都有範例和出題禁用詞。

## 7. 上 prod 的步驟

1. `docker create --name bible_rag_backend_r3_pin bible_rag-backend:r3 true`（釘住 r3，防 Komodo prune）。
2. `docker-compose.yml` 的 backend `image` 改成 `bible_rag-backend:r4`，commit。
3. `ragdata promote --env prod --build b20261019_a86f2b06 --image sha256:ea94bd5e76a1c885201371abf20c060722962555bd7aded3e05241546299c926 --yes-prod`。
4. `docker compose -p bible_rag -f docker-compose.yml up -d --no-deps --no-build --pull never --wait --wait-timeout 300 backend`。
5. smoke20，再抽確認集 5 題。
6. 回滾：`promote --env prod --rollback --yes-prod`，compose 改回 r3，再跑同一個 `up`。

## 8. 上 prod（2026-10-20，Kay：「上 prod」）

- 08:53：照 §7 的步驟換成 `b20261019_a86f2b06`＋r4，前一筆是 `b20261019_18aa84ad`＋r3（commit 6390c69）。只換 backend 容器，postgres、qdrant、ollama 都沒動。
- health：build `b20261019_a86f2b06`，handshake ok，沒有 mismatch。啟動 log 顯示層 252e09559cb0、鏈 19／20、28 個 blockers。
- smoke20：20/20（store `reports/regnal_card_20261019/prod_r4/smoke20.json`）。
- 確認集 32 題全跑（`a4_staging.py --url :8000`，store `prod_r4/a4/`）：32/32 有卡，0 錯誤、0 逾時，key_score 0.906。`a4_card_check.py` 的結果是卡片文字 32/32 逐字相同，seed_source 都是 rule（store `reports/regnal_seed_20261019/a4_check_prod.json`）。
- 切換後 log 裡 0 個 ERROR。staging（`backend-stg`，r4）還開著。

## 9. push 前的清理（公開 repo）

- trigger.py 的 docstring 與註解拿掉一整節經文引文。只改註解，去掉 docstring 後 AST 相同；prod 映像 r4 裡的 trigger.py 仍是 0fd58e6b…，種子回歸 prereg §1 兩個 sha 並列。
- 測試裡的題目改掉了和確認集撞題的序數（同王、同序數、同方向，30 處）、一題帶答案的是非題，以及 3 個貼近經文的字串。測試要測的結構沒變，預期值沒變。

