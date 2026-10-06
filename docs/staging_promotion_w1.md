# 第 1 批 W1 的升版（R3 的 W1 步驟）

> 從 [staging_promotion.md](staging_promotion.md) 的 R3 拆出（2026-10-06，內容未刪減；只把「上面 R3 第 1 步」改成連結）：該檔已到 800 行的上限。本檔是 W1 升版的四節，依序執行：第 1 步換 backend image、/api/v1/entity 的前後比對、第 1、2 步之間的 opt-in A/B、第 2 步載入資料。開始之前要先做完該檔的 R0–R2 與「W1 第 4 步：Kay 核可」；第 2 步之後回到該檔的 R4，出事走該檔的 R5。

> 文中的 R0–R5、「執行前檢查」「W1 的交叉引用檢查」「W1 的關係層檢查」「W1 第 4 步：Kay 核可」都是 [staging_promotion.md](staging_promotion.md) 的章節；「第 1 批計畫」指 [records/2026-10-04_kg_batch1_plan.md](records/2026-10-04_kg_batch1_plan.md)。

## W1 升版第 1 步：backend 先上，資料不動
前提：R2 全部通過，而且「W1 第 4 步：Kay 核可」已記進 W1 紀錄，沒有就不開始。在主 checkout、沒有 source staging.env 的乾淨 shell 執行：這裡要對 production 做 `up`，而 `--target prod` 會拒絕 staging 的 shell；compose 的專案名取自目錄名，只有主 checkout 的 backend image 是 `bible_rag-backend:latest`。先把 `D` 設成 W1 R0 的日期（每段開頭的 `${D:?}` 沒設就停）。種子與期望檔沿用 R2「W1 的交叉引用檢查」的 `bak/$D/xref_probe/`。

三段依序貼上。前兩段是子 shell 加 `set -e`，任何一行失敗整段就停；沒有印出最後一行的訊息，就不要貼下一段。第一段保存回滾 image，只做一次：
```bash
(
set -eu -o pipefail -o noclobber
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
PROD=$(docker inspect -f '{{.Image}}' bible_rag_backend)
test "$PROD" != "$W1"
test ! -e bak/$D/images/backend_kg-pre-batch1-w1.tar.gz
echo "$PROD" > bak/$D/images/backend_kg-pre-batch1-w1.id
docker tag "$PROD" bible_rag-backend:kg-pre-batch1-w1
docker create --name bible_rag_backend_kg_pre_batch1_w1 bible_rag-backend:kg-pre-batch1-w1
docker save bible_rag-backend:kg-pre-batch1-w1 | gzip > bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part
gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part | tar -tf - | grep -Ex "(\./)?blobs/sha256/${PROD#sha256:}" >/dev/null
mv bak/$D/images/backend_kg-pre-batch1-w1.tar.gz.part bak/$D/images/backend_kg-pre-batch1-w1.tar.gz
(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)
echo 'rollback image saved'
)
```
第二段換成 R2 測過的 image，可以重跑：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
PRE=$(cat bak/$D/images/backend_kg-pre-batch1-w1.id)
P=$(docker inspect -f '{{.Image}}' bible_rag_backend)
case "$P" in "$PRE"|"$W1") ;; *) echo "prod runs $P, neither the recorded rollback image nor :w1" >&2; exit 1;; esac
grep -qF ' ./images/backend_kg-pre-batch1-w1.tar.gz' bak/$D/SHA256SUMS
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_kg_pre_batch1_w1)" = "$PRE"
test "$(docker image inspect -f '{{.Id}}' bible_rag-backend:w1)" = "$W1"
docker tag bible_rag-backend:w1 bible_rag-backend:latest
docker compose up -d --no-deps --no-build --wait --wait-timeout 300 backend
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
echo 'prod runs :w1'
)
```
第三段驗證：
```bash
(cd evaluation && rm -f results_quick/w1_step1_smoke.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/smoke20_ids.txt --label w1_step1_smoke \
  && python3 -c "import json; d = json.load(open('results_quick/w1_step1_smoke.json')); r = (d['n'], d['n_invalid'], sorted(q for q, e in d['per_question'].items() if e['strategy_errors']), d['config']['graph_strategies_applied']); print(*r); raise SystemExit(0 if r == (20, 0, [], {'event_registry': 20}) else 1)")
uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend
docker exec -i bible_rag_backend .venv/bin/python -m probes.xref_measure \
  < bak/$D/xref_probe/seeds.json > bak/$D/xref_probe/measured_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py predict --seeds bak/$D/xref_probe/seeds.json \
  --target prod --out bak/$D/xref_probe/pred_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_step1.json \
  --measured bak/$D/xref_probe/measured_prod_step1.json
uv run --project scripts python scripts/tools/xref_probe.py compare --pred bak/$D/xref_probe/pred_prod_step1.json \
  --measured bak/20261005_w1_1b_evidence/pred_trans.json
```
- **回滾 image 取自 prod 容器正在跑的 image**（升版前是 9bc112a6），不取 `latest`：`latest` 若在 R2 被重建過，已經是 W1 的 image。它的 id 記在 `backend_kg-pre-batch1-w1.id`，R5 依這個 id 退回，不依 tag。R0 若已打過這個 tag，第一段會把它改指到記下的 id。
- **第一段只做一次**：prod 已經在跑 `:w1`，或 id 檔、存檔已經存在（`noclobber` 拒絕覆寫）時就停。所以第一段重跑時，不會把 W1 的 image 記成回滾 image，不會覆寫存檔，也不會在 SHA256SUMS 多補一行。第一段中途失敗時 prod 還沒換 image：查明原因後 `docker rm bible_rag_backend_kg_pre_batch1_w1`，刪掉 `backend_kg-pre-batch1-w1.id` 與 `.tar.gz.part`，再重跑第一段。只有最後補 sha256 的那一行失敗時（`.tar.gz` 已在，SHA256SUMS 沒有它），不要照上面清理，也不要重跑第一段（`test ! -e` 會擋，第二段也會停在 SHA256SUMS 那一行）：先核對存檔，`(set -o pipefail; gunzip -c bak/$D/images/backend_kg-pre-batch1-w1.tar.gz | tar -tf - | grep -Ex "(\./)?blobs/sha256/$(cut -d: -f2 bak/$D/images/backend_kg-pre-batch1-w1.id)")` 要結束碼 0 並印出那個 blob，再手動跑 `(cd bak/$D && sha256sum ./images/backend_kg-pre-batch1-w1.tar.gz >> SHA256SUMS)`，然後貼第二段。
- **回滾 image 在換 image 之前保住**（R0 第 7 項）：停著的容器 `bible_rag_backend_kg_pre_batch1_w1` 讓 `docker image prune -a` 刪不掉它；`docker system prune` 會先刪停著的容器，所以還要 `docker save`。`pipefail` 讓 save 中斷時整段失敗；先寫到 `.part`，`tar -tf` 從頭讀到尾沒有錯誤、而且清單裡有 prod image id 的 blob（`blobs/sha256/<id>`；containerd store 下這個 id 是 index digest，R5 依它從存檔載回）才改名、記 sha256，所以正式檔名只會是完整、帶著這個 id 的存檔。grep 不加 `-q`：讀完整份清單，tar 不會被 SIGPIPE 中斷而讓 `pipefail` 誤判失敗。存檔裡沒有這個 blob 就停：prod 還沒換 image，先查 `docker load` 能不能還原同一個 id，再決定怎麼保存回滾 image。image 的內容約 7 GB，存檔與核對要幾分鐘，prod 照常服務。這個容器留到下一批 R0 之後才 `docker rm`。
- **上線的是 R2 測過的 image，不重建**：第 1 批計畫 §1「W1 升版」第 1 步原寫 `up -d --build backend`，改為把 R2 建的 `bible_rag-backend:w1` 改 tag 成 `latest`。第二段先確認第一段做完（SHA256SUMS 有存檔那一行、停著的容器還釘著回滾 image），而且 `:w1` 仍是 R2 記下的 `backend_w1.id`，才改 tag、`up`。第二段也確認 prod 仍是第一段記下的 id（重跑時已是 `backend_w1.id`）：兩者都不是，表示 prod 在第一段之後被換過（例如無關的 `up -d --build`），記下的回滾 image 就不是 W1 取代的那一個，整段就停。`--no-build`：image 不在就失敗，不會在 prod 上重建；`--no-deps`：只動 backend（理由見 R5 開頭）；`--wait`：等 healthcheck 通過才返回（start_period 120 秒），unhealthy 或超過 300 秒時結束碼不是 0，整段就停。最後確認 prod 容器跑的是 `backend_w1.id`。
- **煙霧測試**：20 題預設檢索（只有 event_registry），通過條件是印出 `20 0 [] {'event_registry': 20}`（見[題號檔 README](../evaluation/experiments/2026-10-05_kg_w1/README.md)）：最後一項是 backend 回報套用的圖譜策略計數（quick_retrieval_eval 記在 `config.graph_strategies_applied`），新 image 的預設路徑仍只套用 event_registry。先刪掉上一次的結果檔，執行與檢查用 `&&` 串起來，舊檔不會讓檢查假性通過；印出的不是這一行時，檢查的結束碼是 1。
- **deploy-guard** 結束碼 0。不是 0 就先查 image，不往下做。
- **C1 的判準是精確比對**：兩個 compare 結束碼都是 0（煙霧測試與 deploy-guard 不過同樣要停，見上兩項）。第一個是 prod 的實測對預測：5,820 個 key 0 列不同，哨兵 12/12；第二個是 `pred_prod_step1.json` 對規劃時歸檔的 `bak/20261005_w1_1b_evidence/pred_trans.json`（2026-10-05 對當時的 prod 已驗證 0/5,820）。這個 image 帶上了 087ab0d（W1-0 的 md5 平手，prod 現行的 9bc112a6 還沒有）、1B-C1（讀 `r.curated`，刪除 999 哨兵）、`backend/probes/`，以及兩個串流的全部 scripts/ 與 bible_chunking/ 改動（都 COPY 進 image）。所以**不要拿 opt-in 的線上行為與 9bc112a6 比**：光是 md5 平手就讓約 1,279/2,779 個單一種子、57/262 個代理種子集的 id 集合改變；相對於 087ab0d 的 Cypher，C1 本身只改 5 個單一種子（只有權重）與 1/262 個種子集。
- W1 紀錄要寫明：第 1 步上線的是 087ab0d 加 C1，判準是這裡的精確比對；並記下 R2 的 `backend_w1.id`、第 1 步之後 prod 容器的 image id（兩者必須相同）、回滾 image 的 id（`backend_kg-pre-batch1-w1.id`，升版前是 9bc112a6…），以及回滾存檔的 sha256。
- 第三段通過之後，接著跑下方「W1 的 /api/v1/entity 比對」第一段（擷取 before，只做一次），再進入 opt-in A/B。

## W1 的 /api/v1/entity 比對（第 1A 批）
第 1 批計畫 §1 的 W1 驗收「/api 的 W1 清單與 prod 完全相同」，id 是 §5.3 的 7 個。比的是 prod 自己在第 2 步前後：同一個 W1 image、同一個 PG，只有 Neo4j 換成 W1 的資料。/api/v1/entity 的欄位來自 PG（type、canonical_name、aliases、description、mention_count）與 MENTIONS（related_passages、related_entities，見 `backend/database/neo4j_db.py` 的 get_entity_related_pericopes、find_related_entities），W1 兩者都不改，所以正規化之後必須逐位元相同。
- **不在 R2 拿 :8000 比 :8001**：R2 時 prod 還是 9bc112a6，沒有 087ab0d 的 md5 平手；7 個 id 有 5 個的相關段落超過 10 個，同樣的資料在 LIMIT 10 會取到不同的集合。jq 的 sort_by 只固定順序，不固定取到哪些。2026-10-05 實測：prod（9bc112a6）對 backend-staging（w1det，有 087ab0d），7 個 id 的 related_* 全部不同；改用 087ab0d 的兩個查詢直接讀 prod 的 7687，7 個 id 都與 backend-staging 從 7688 讀到的相同。
- 三段都在主 checkout 的乾淨 shell 跑（同第 1 步）。第一段在第 1 步第三段通過之後、opt-in A/B 之前跑，只做一次：`noclobber` 讓重跑在第一個已存在的檔就停，不會把第 2 步之後的回應記成 before。中途失敗時刪掉 `bak/$D/api/before` 再跑。

```bash
(
set -eu -o pipefail -o noclobber
: "${D:?set D to the W1 R0 date}"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$(cat bak/$D/images/backend_w1.id)"
mkdir -p bak/$D/api/before
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  curl -sf "http://localhost:8000/api/v1/entity/$id" \
    | jq -S '.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)' > "bak/$D/api/before/$id.json"
done
echo 'api before captured'
)
```
第二段可選，只是提早示警，不是閘門：在下方 A/B 視窗裡 backend-staging 也跑 `:w1` 的時候，拿 :8000 比 :8001。兩邊的 PG 不同（bible_rag 對 bible_rag_staging），person:yeteluo 與 event:shanshangbaoxun 的 aliases 只因 PG 的資料就不同（2026-10-05 實測：prod 兩個都是 `[]`，staging 分別是 `["流珥"]` 與 `["登山寶訓", "八福"]`），所以只有這兩個 id 不比 aliases。印出 `DIFF` 的 id 先查清楚，再做第 2 步：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$W1"
mkdir -p bak/$D/api/early
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  f='.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)'
  case $id in person:yeteluo|event:shanshangbaoxun) f="$f | del(.aliases)";; esac
  for port in 8000 8001; do
    curl -sf "http://localhost:$port/api/v1/entity/$id" | jq -S "$f" > "bak/$D/api/early/$port-$id.json"
  done
  cmp -s "bak/$D/api/early/8000-$id.json" "bak/$D/api/early/8001-$id.json" || echo "DIFF $id"
done
echo 'early compare done'
)
```
第三段是閘門：第 2 步載入、`docker start bible_rag_neo4j` 之後、R4 之前跑。7 個 id 都 `cmp` 相同才印出最後一行；不同就停下來查：不做 R4 的 ratchet，也不自動走 R5。prod 這時是 W1 的資料加 W1 的 image，W1 image 新舊資料都能正確排序，留在這個狀態查是安全的；要不要 R5 由 Kay 決定，回滾時照 R5 先資料、後 image。可以重跑（Neo4j 剛起來時 curl 可能失敗）。before、after 兩組檔的 sha256 記進 W1 紀錄：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$(cat bak/$D/images/backend_w1.id)"
test "$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j)" = healthy
mkdir -p bak/$D/api/after
for id in person:make person:liwei place:dan group:yehehua event:shanshangbaoxun person:yeteluo event:jinniudushijian; do
  curl -sf "http://localhost:8000/api/v1/entity/$id" \
    | jq -S '.related_passages |= sort_by(.id) | .related_entities |= sort_by(.entity_id)' > "bak/$D/api/after/$id.json"
  cmp "bak/$D/api/before/$id.json" "bak/$D/api/after/$id.json"
done
echo 'api identical'
)
```

## W1 升版第 1、2 步之間：opt-in A/B（xref、graph_event，只報告）
第 1 批計畫 §5.2 在這裡量 W1 的兩項 opt-in：同一個 W1 image 分別接舊資料（prod，第 1 步之後）與新資料（backend-staging），兩邊參數完全相同。xref 各跑一次 500 題（kg_xref 的 68 題要在 500 題裡才算得到）；graph_event 只抽查 K10 的題（下方）。R2 第 3 項驗完已停掉 backend-staging，所以先在第 1 步的同一個 shell 用 R2 的 override 重新啟動它，等 healthcheck 通過，並確認兩邊跑的都是 `backend_w1.id`：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.State.Health.Status}}' bible_rag_neo4j_staging)" = healthy
printf 'services:\n  backend:\n    image: bible_rag-backend:w1\n  backend-staging:\n    image: bible_rag-backend:w1\n' > /tmp/w1_image.yml
docker compose -f docker-compose.yml -f docker-compose.staging.yml -f /tmp/w1_image.yml up -d --no-deps --no-build --wait --wait-timeout 300 backend-staging
test "$(docker inspect -f '{{.Image}}' bible_rag_backend_staging)" = "$W1"
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
echo 'both arms run :w1'
)
```
沒有印出最後一行就不要往下。neo4j-staging 必須仍是 W1 重建的資料而且 healthy（停了就 `docker start bible_rag_neo4j_staging`）；`--no-deps` 不碰它，`--no-build` 不重建 image。接著量測。評估指令都包在子 shell 裡，跑完仍在專案根目錄，第 2 步的相對路徑才對：
```bash
(cd evaluation && rm -f results_quick/xref_old_w1.json results_quick/xref_new_w1.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_old_w1 \
  && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_new_w1)
(cd evaluation && uv run python xref_ab_slice.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json --label w1_xref)
(cd evaluation && uv run python ab_compare.py results_quick/xref_old_w1.json results_quick/xref_new_w1.json --label w1_xref)
```
- 先刪上一次的結果檔，兩次收集用 `&&` 串起來：中途失敗時，後面的報告讀不到舊檔。
- xref_ab_slice 結束碼 2 是防呆（兩邊的策略、top_k、metric_k、metric_version 不同，或段落沒有 gold、found_by，或 `--ids` 檔不是 qid 清單，或 kg_xref 切片在兩邊都沒有有效題），不存報告：空切片會印出「0 → 0」，看起來就像預期的沒有增益。切片只有部分題目有效時印 `warning:`，結束碼不變。只在一邊出現的題列在 `unpaired`。
- xref_ab_slice 結束碼 3 是 touched 題數超過 `--max-touched`（預設 34）：先停下來查，再決定要不要做第 2 步。預期 touched 約 17 題以下；kg_xref「只經 xref 到達 gold」預期沒有增益（模擬 14 → 14）。這不是閘門。
- ab_compare 補上 §5.2 要求的其餘數字：每段印出各指標的平均 Δ、95% CI（bootstrap）與勝負題數 W/L，Δvrec 是 `verse_recall_at_k` 那一列。`[legacy]`（legacy-100，樣本內）與 `[expanded]`（擴充的 400 題；1B 設計時用過的 kg_xref 68 題都在這一段，所以不是乾淨的 held-out，kg_xref 由 xref_ab_slice 另報）兩段分開記進 W1 紀錄，`[all]` 一併記；要乾淨的 held-out 數字，從兩份結果檔的 per_question 扣掉這 68 題另算，同樣只報告。它的 `touched (passages appended)` 是指附加在 top-k 之後的段落，兩個 xref 策略不附加，所以是 0；touched 題數以 xref_ab_slice 為準。只報告，不設門檻。
- touched 的題先用同樣條件重問，排除 LLM 取樣雜訊：W0 的 legacy-100 有 1 題（GENERAL_BIBLE_QUESTION_016）只因 intent LLM 取樣就換了 top-5（[W0 紀錄](records/2026-10-05_kg_batch1_w0_results.md)「補記：W1-0 opt-in 決定性」）。

**graph_event 抽查（K10，只報告）**。K10 決定「W1 先 accept 並抽查 graph_event」，第 1 批計畫 §5.2 的 W1 列是「抽查保羅歸主、山上寶訓的題目（受 mention_count 殘差影響）」。第 0 批遺留的 mention_count 殘差有 3 個實體是 Event：event:shanshangbaoxun（山上寶訓）與兩個保羅敘述歸主的事件。graph_event 每個事件關鍵字取 mention_count 最高的 3 個事件，pin 的先後也依 mention_count，所以這些題挑到的事件與段落可能改變。題號檔 `evaluation/experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt` 是 GT 裡題目文字含有這 3 個事件在 event_registry 的觸發詞（保羅歸主、八福、山上寶訓、登山寶訓）的題，選題規則見[題號檔 README](../evaluation/experiments/2026-10-05_kg_w1/README.md)。同一個視窗、同一組參數（與上面的 xref 量測相同的 `--top-k 5 --metric-k 6`），只換資料：
```bash
(cd evaluation && rm -f results_quick/ge_old_w1.json results_quick/ge_new_w1.json \
  && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt --graph-strategies graph_event --top-k 5 --metric-k 6 --label ge_old_w1 \
  && BACKEND_URL=http://localhost:8001 uv run python quick_retrieval_eval.py --ids-file experiments/2026-10-05_kg_w1/graph_event_k10_ids.txt --graph-strategies graph_event --top-k 5 --metric-k 6 --label ge_new_w1)
(cd evaluation && uv run python ab_compare.py results_quick/ge_old_w1.json results_quick/ge_new_w1.json --label w1_graph_event)
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
rm -f bak/$D/answer_side_*.txt
for r in xref graph_event; do jq -r '.ledger | to_entries[] | select(.value.status | IN("gold_in", "gold_out", "gold_swap", "changed")) | .key' evaluation/results_quick/ab_w1_$r.json > bak/$D/answer_side_$r.txt.part; mv bak/$D/answer_side_$r.txt.part bak/$D/answer_side_$r.txt; done
echo 'answer-side candidates listed'
)
```
- ab_compare 的 core top-5 identical／mismatch、改動帳本（identical、order_only、nongold_swap、gold_in、gold_out、gold_swap）與各指標的 Δ、W/L 都記進 W1 紀錄，放在 K10 的 accept（`residuals_allow.yaml` 的 4 筆 mention_count）旁邊。有變動的題先用同樣條件重問，排除 intent LLM 的取樣雜訊（同上）。只報告，不設門檻，不擋第 2 步。
- **答案端（第 1 批計畫 §5.2）是第 2 步之前必須做完的決定**：第 2 步把 W1 的資料載入 prod 之後，舊資料那一臂就不在了，所以跑不跑、依據哪些數字，都要在這個視窗裡記進 W1 紀錄。xref 與 graph_event 都一樣，只在檢索結果有實質差異時才跑。實質差異的定義：上面最後一段從兩份 ab_compare 報告（`--label` 存的 `results_quick/ab_w1_xref.json`、`ab_w1_graph_event.json`）的改動帳本列出的題，也就是同路由、top-k 的 gold 段落有進出的題（`gold_in`、`gold_out`、`gold_swap`；`changed` 是段落沒有 gold 標記、無法判斷，也算），而且重問之後仍是這幾種；`identical`、`order_only`、`nongold_swap` 的 gold 段落沒變，不算。重問是清單裡的題兩臂以同樣參數再各跑一次，標籤另取，不覆寫上面的結果檔與 ab_compare 報告：xref 的舊資料臂是 `(cd evaluation && BACKEND_URL=http://localhost:8000 uv run python quick_retrieval_eval.py --ids-file ../bak/$D/answer_side_xref.txt --graph-strategies cross_ref_expand cross_reference --top-k 5 --metric-k 6 --label xref_old_w1_reask)`，再換成 `http://localhost:8001` 與 `xref_new_w1_reask` 跑一次，接著 `(cd evaluation && uv run python ab_compare.py results_quick/xref_old_w1_reask.json results_quick/xref_new_w1_reask.json --label w1_xref_reask)`；graph_event 改用 `--ids-file ../bak/$D/answer_side_graph_event.txt --graph-strategies graph_event`，標籤是 `ge_old_w1_reask`、`ge_new_w1_reask` 與 `--label w1_graph_event_reask`。重問的帳本（`results_quick/ab_w1_xref_reask.json`、`ab_w1_graph_event_reask.json`）裡仍是這幾種的題，才是實質差異。列清單那一段先刪掉舊清單：重跑時 jq 失敗，不會留下上一次的清單讓第 2 步的 `cat` 通過。兩個清單都是空的，或重問後都不再是這幾種：答案端不跑，W1 紀錄寫明不跑與兩個清單的題數。仍有題：趁兩臂都還開著跑 `run_eval.py`（收集加評估，500 題），兩臂參數與該項的檢索量測相同、只換 BACKEND_URL，例如 xref 先跑 `(cd evaluation && BACKEND_URL=http://localhost:8000 uv run python run_eval.py --graph-strategies cross_ref_expand cross_reference)`，再把 BACKEND_URL 換成 `http://localhost:8001` 跑一次（graph_event 是 `--graph-strategies graph_event`）。兩次都寫進 `evaluation/results/`，跑完一臂先把目錄改名（例如 `results_xref_old_w1`），下一臂的收集才不會清掉它。coverage（`answer_coverage`）是主要指標，faithfulness strict（`ragas_faithfulness_strict`）的 run 平均 ≥ 0.97 守門，清單裡的題逐題比較 |Δcoverage| 與雜訊地板 0.060（同一份 context 的 coverage |Δ| 平均）；結果一併記進 W1 紀錄。
- 兩項 A/B 量完、答案端的決定（要跑時連同結果）記進 W1 紀錄之後，才照 R2 第 3 項停掉 backend-staging，接著做第 2 步。

## W1 升版第 2 步：載入資料，第一個指令是 deploy-guard
這是 W1 唯一寫入 prod 資料的一步，所以不貼 [staging_promotion.md](staging_promotion.md) R3 第 1 步的通用指令，改貼下面這一整段（Neo4j 停機約 1 分鐘）。在主 checkout、沒有 source staging.env 的乾淨 shell 執行，同第 1 步：deploy-guard 比對的是本 checkout 的 HEAD，`--a prod` 會拒絕帶著 staging 設定的 shell，`--target staging` 在乾淨的 shell 解析成預設的 bolt://localhost:7688。整段是子 shell 加 `set -e`，任何一行失敗就停；沒有印出最後一行，就是沒有載入完成：
```bash
(
set -eu -o pipefail
: "${D:?set D to the W1 R0 date}"
uv run --project scripts python scripts/tools/xref_probe.py deploy-guard --container bible_rag_backend
W1=$(cat bak/$D/images/backend_w1.id)
test "$(docker inspect -f '{{.Image}}' bible_rag_backend)" = "$W1"
uv run --project scripts python scripts/tools/xref_probe.py fingerprint --target staging --expect config/kg_expect/batch1_w1/xref.json
uv run --project scripts python scripts/tools/check_edge_set.py --target staging --expect config/kg_expect/batch1_w1/relations_expected.json
uv run --project scripts python scripts/tools/residuals_expect.py --a prod --b staging \
  --check config/kg_expect/batch1_w1/residuals_expected.json
mkdir -p bak/$D/promote
sha256sum -c config/kg_expect/batch1_w1/kg_diff_allow_batch1w1.sha256
uv run --project scripts python scripts/tools/diff_kg.py --a prod --b staging --allow config/kg_diff_allow_batch1w1.yaml --fail-on-unused --json > bak/$D/promote/diff_kg_w1.json
cat bak/$D/answer_side_xref.txt bak/$D/answer_side_graph_event.txt
test ! -e bak/$D/promote/neo4j_staging.dump
docker stop -t 60 bible_rag_neo4j_staging
docker run --rm --user 7474:7474 --entrypoint neo4j-admin \
  -v bible_rag_neo4j_staging_data:/data neo4j:5.15-community \
  database dump neo4j --to-stdout > bak/$D/promote/neo4j_staging.dump.part
test -s bak/$D/promote/neo4j_staging.dump.part
mv bak/$D/promote/neo4j_staging.dump.part bak/$D/promote/neo4j_staging.dump
(cd bak/$D && sha256sum ./promote/neo4j_staging.dump >> SHA256SUMS)
docker stop -t 60 bible_rag_neo4j
docker run --rm -i --user 7474:7474 --entrypoint neo4j-admin \
  -v bible_rag_neo4j_data:/data neo4j:5.15-community \
  database load neo4j --from-stdin --overwrite-destination=true < bak/$D/promote/neo4j_staging.dump
docker start bible_rag_neo4j
echo 'prod neo4j loaded'
)
```
- **deploy-guard 是第一個指令**：結束碼不是 0 就停，不載入 dump：prod 容器跑的不是本 checkout HEAD 建的、讀 `r.curated` 的 image（例如第 1 步之後被重建或退回過），新資料會被舊規則排序（第 1 批計畫 §2.2 的風險；部署順序顛倒的影響見 R5）。下一行再確認 prod 跑的仍是 R2 記下的 `backend_w1.id`。
- 每個 `docker exec`、`git show` 最多等 30 秒。docker daemon 或容器沒有回應時，印出 `timed out after 30 s` 並以結束碼 1 結束，不會卡住：先查 daemon 與容器，同樣不載入。
- 第 1、2 步可能相隔數小時，deploy-guard 放在這一段裡，所以每次都會重跑。載入資料之後不要再建 image；image 一有任何變動，先重跑 deploy-guard 再碰資料。
- **staging 唯讀再驗一次**：dump 出去的必須是 R2 驗過、第 4 步經 Kay 核可的那份資料，而 staging 從 R2 到這裡一直開著。四項都對已登記的檔、判準與 R2 相同：xref 的指紋與 xref_provenance（「W1 的交叉引用檢查」第 2 項）、語意層的邊集合（「W1 的關係層檢查」第 4 項的 check_edge_set）、MENTIONS 的逐邊摘要與屬性的第 0 批殘差（同一項的 `residuals_expect.py --check`，本來就要在乾淨的 shell 跑），以及 R2 第 2 項的 diff_kg（先 `sha256sum -c` 核對合併清單，再以它加 `--fail-on-unused` 比對；labels、entity_ids、descriptions、aliases、mention_count、registry 也因此重驗一次，報告存到 `bak/$D/promote/diff_kg_w1.json`）。prod 還沒載入，diff_kg 比的仍是舊資料對 staging，與 R2 相同。任何一項結束碼不是 0 就停，這時 prod 還沒動。接著 `cat` 兩個答案端候選清單：檔案不在就停，答案端的決定（第 1、2 步之間）要先做完、記進 W1 紀錄。
- **dump 完整才停 prod**：dump 先寫到 `.part`，neo4j-admin 失敗時整段就停；`test -s` 擋掉空檔；之後才改名，sha256 補進 `bak/$D/SHA256SUMS`（同第 1 步的回滾存檔）。prod 的 `docker stop` 排在這些之後。`test ! -e` 讓 dump 只做一次，SHA256SUMS 不會多補一行。
- 中途失敗時，先看停在哪一行：
  - SHA256SUMS 補上之前：prod 沒動。staging 已停就 `docker start bible_rag_neo4j_staging`，等它 healthy；刪掉 `.part`，以及已改名、但還沒補進 SHA256SUMS 的 dump，再重跑整段。
  - SHA256SUMS 補上之後（例如載入失敗）：dump 已完整並記下 sha256，不要重跑整段（`test ! -e` 會擋，staging 也已停）。查明原因後，先以 `(cd bak/$D && grep -F ' ./promote/neo4j_staging.dump' SHA256SUMS | sha256sum -c -)` 核對 dump，再從 prod 的 `docker stop` 那一行起逐行執行；或照 R5 載回 R0 的 dump。
- staging 停在 dump 時的狀態；之後要用（R4 之後的 K8 對照組）時再 `docker start bible_rag_neo4j_staging`。
- 載入、`docker start bible_rag_neo4j` 之後，先跑上面「W1 的 /api/v1/entity 比對」第三段（它會確認 prod 的 Neo4j 已 healthy，可以重跑），相同才做 R4。
