# 知識圖譜資料層修復與建置管線整合計畫

> 給 Kay｜2026-10-04｜repo：Bible_RAG（branch feat/graph-strategy-gating，HEAD df7148f）
> 依據：五個缺陷族（MENTIONS、身分層、關係、交叉引用、事件）的唯讀調查，五位驗證者的逐項複核，以及架構師的資料流與整合設計。數字與根因若有出入，一律以驗證者的更正為準。全程唯讀：沒有修改 repo，也沒有寫入任何資料庫。

---

## 0. 摘要

1. **可以修，而且可以修在管線裡。** 絕大多數缺陷的根因集中在幾個地方：Step 0/1（NER 的輸入文字、字典、名稱正規化）、Step 6（規則方向、反向物化、批次 context）、Step 9（TSK 只在 ON CREATE 時寫入），以及 Step 10.x（事後補丁沒有 provenance，不會傳遞到衍生層，也不會同步三庫）。這些都能改成「下次重建自動帶上」。
2. **整合方式（採架構師建議）：** 不再新增 10.x 式的線上 Cypher 補丁。改成在 JSONL 層離線編譯出一份 KG 快照，再由單一載入器投影到 Neo4j、PG、Qdrant。先建到 staging，通過 validate_kg 品質門後才升版。LLM 產物（Step 1 Phase 4、Step 6 R4、Step 7 描述）凍結成帶來源資訊的快取，只有快取沒命中時才呼叫 LLM。
   重建可以重現現況（皆已驗證）：
   - Step 0 重跑後，7 個檔案逐位元相同；
   - NER 重跑 600 筆樣本，2,830/2,830 相同；
   - Step 6 離線挖對得到 85,439 對，與 checkpoint 完全重合；
   - MENTIONS 模擬結果扣掉 10.2 的刪除數後，等於 live 的 46,043。
3. **分批：**
   - **第 0 批（前置，約 36–50 h，不改資料語意）**：
     - 備份並凍結只存在 live 的狀態；
     - Step 1 拆成 NER 與 grounded 兩半；
     - 建立描述快取；
     - 修 EV-06；
     - 建 validate_kg 與 staging；
     - 做一次等價重建。
   - **第 1 批（不需重跑 LLM，約 80–110 h）**：
     - 1A 關係層後處理；
     - 1B 交叉引用 provenance；
     - 1C NER 根因修正；
     - 1D 實體與事件的決定性清理，加上三庫同步。
   - **第 2 批（中等工作量，約 108–152 h，另需 LLM 數小時）**：
     - 2A Step 6 可續跑化，加上定向 R4；
     - 2B RCUV 拼法與權威長名詞表；
     - 2C curated 事件單一真相來源與 registry 錨點；
     - 2D markdown 平行經文解析器。
   - **延後**：身分層重建、grounded 半邊重抽、Step 6 全量重跑。
4. **對線上的影響（誠實評估）：**
   - 線上預設 `graph_strategies=["event_registry"]` 讀的是燒進 image 的靜態檔 `backend/data/event_registry.json`，不讀 Neo4j。因此第 0、1 批對線上預設 QA 的直接影響是零。我們甚至把「預設組態 500 題的 sources/prompt 逐位相同」設成閘門。
   - 受益的地方有四個：
     - `/api/v1/entity`：直接對外。現在「馬可」回傳的段落約 9 成是書名假邊，人物、地點、群體的描述全部是空字串。
     - 可由請求開啟的圖譜策略。
     - 論文與文件的正確性。
     - 重建安全：EV-06 若不修，下次全量重建時 registry 會從 33 個事件靜默掉到 31 個，丟掉 EVENT_011 的附加軌增益。
   - 會改到線上預設 QA 的只有兩處：2C（registry 錨點），以及 2B／延後-A（因為後端路由直接 import 抽取字典）。
   - 2026-10 的圖譜價值診斷，41 題停損實驗已判 STOP（KG 橋接沒有增益，oracle 僅 +0.03～0.06）。所以 opt-in 策略的資料修好後，也不要預期檢索分數明顯上升。A/B 的用途是量測，不是預期一定會贏。
5. **先前假設的重要更正**（詳見 §1.3）：
   - 「但」的 370 條孤兒邊不是 10.2→10.3 的順序 bug。真正原因是缺 provenance 閘門，加上清理結果不會傳遞到衍生層。
   - 書名假邊是 1,745 條，不是 1,491。
   - 名稱帶空白的實體是 180 個，不是 262。
   - 同音合併的 Person 在 live 是 169 個，全型別共 268 個 id；只加聲調仍有 76 個分不開。
6. 需要你拍板的事項見 §7。最急的五項：D1 整合策略、D2 10.3 退場、D5 描述曝光、D7 字典拆分、D13 工作樹中被刪除的評估檔。

---

## 1. 範圍、標記與基準

### 1.1 可信度標記
- **【已驗證】**：驗證者重跑過 live 唯讀查詢、讀過程式碼，或離線重算確認。
- **【已驗證・更正】**：缺陷成立，但數字或行號以驗證者為準。
- **【部分成立】**：現象成立，原述的根因或修法有部分不成立。
- **【推論】**：讀程式碼推得，或由樣本外推，未直接重現。所有工時、LLM 吞吐與耗時都屬推論。

### 1.2 live 基準（2026-10-04，唯讀）
| 項目 | 數值 |
|---|---|
| Neo4j 節點／關係 | 13,589／319,988（與 bak/20260715 相同，該 dump 仍可當還原點） |
| Entity | 9,124（Neo4j、PG、Qdrant 的 id 集合相同，差集為 0） |
| MENTIONS | 46,205（抽取 46,043、manual_patch 106、head_event_backfill 56） |
| 實體間語意邊 | 15,926 |
| CROSS_REFERENCES | 250,418（tsk 249,502、markdown 774、supplementary 142） |
| event_registry.json | 33 個事件；`export_event_registry.py --check` 通過；repo 與容器的 sha 都是 9b2a5f3e…4971 |
| embedding_queue.jsonl | 34,072 筆，sha256 5d2ac0e5460c…（Step 0 重跑逐位元相同） |

### 1.3 背景假設的更正
| 原說法 | 更正 | 依據 |
|---|---|---|
| 「但」是 10.2→10.3 的順序 bug | 10.2 只刪 MENTIONS，不刪衍生邊；10.3 讀的是 5 月的快照，也不查 live MENTIONS。把兩步對調，仍會產生同樣的 370 條。根治要靠 provenance 閘門，加上讓清理結果傳遞下去 | cleanup_noise_entities.py:161-166；backfill_event_relations.py:56-70、88-120 |
| 純書名假邊約 1,491 條 | 1,745 條（1,601 條，加上 verse 段 135 條、書名加標題 9 條）。落在書名區的邊共 1,938 條，其中包含原稽核漏掉的 153 條 start_pos>0 的邊（例如 出埃及記→埃及 118 條） | live Cypher 與 jsonl 重建結果一致 |
| 10.3 有 839/122 條只靠書名支撐 | 839/122 是「第一位置落在書名區」的數字。扣掉同段另有內文提及的，只靠書名的上限是 778+104=882 條 | 驗證者的 $hb 查詢 |
| 名稱帶空白的實體 262 個 | 前後帶空白的 180 個（若算 id 帶空白則 183 個）；其中有同型乾淨孿生節點的 116 個，不限型別則 153 個 | trim 查詢 |
| 168 個 Person 同音合併 | live 169 個 Person（JSONL 171 個），全型別 268 個 id；改用 TONE3 仍有 76 個碰撞 | homophone.py |
| id 在 extract_entities.py:134-141 鑄造 | P/P/G 的 id 在 ner_extractor.py:282-292 鑄造，134-141 只處理 E/O/T。全 repo 共有 4 份 id 函式 | code-read |
| TSK 有 250,418 條 | 250,418 是 CROSS_REFERENCES 的總數。純 TSK 是 249,502 條；TSK 唯一段落對是 250,358，其中 856 對被 curated 邊吞掉 | 離線重現 |
| 交叉引用殘標標題 230 個 | 54 個（福音書 52 個）。另外 176 個其實是「(無標題)」，被 regex 誤算進來 | pericopes.jsonl |
| votes=999 是存在資料裡的哨兵值 | 999 是查詢時用 coalesce 補出來的；916 條 curated 邊在資料中根本沒有 votes | build_database.md:388 的敘述錯誤 |
| 10.2 會同步三庫 | 「但」的清理只寫 Neo4j，PG 仍有 1,882 列 | build_database.md:426 的敘述錯誤 |
| R4 批次錯置影響 42% 的配對 | 真正由批次 bug 造成的是 16,425 對（19.4%）。另有約 18.9k 對的端點名稱根本不在經文中，修好批次也救不回來 | 精確重演 |
| (無標題) 續段只是 miner 沒有錨定 | 真因是 bible_md_parser.py:190-197、221-226 把這 176 段（2,289 節）整段丟掉，grounded 抽取根本看不到 | parse_all_bible_md 重現 |

---

## 2. 缺陷總表

> 欄位：live 規模｜根因步驟（file:line）｜可信度｜修法｜是否需要重跑 LLM｜下游影響｜所屬批次。
> 縮寫：P/P/G = Person/Place/Group；E/O/T = Event/Object/Theme；opt-in = 預設關閉、可由請求開啟的圖譜策略。

### 2.1 MENTIONS 族
| ID | 缺陷 | live 規模 | 根因步驟 | 可信度 | 修法 | LLM | 下游影響 | 批次 |
|---|---|---|---|---|---|---|---|---|
| M1 | 書名或章節前綴造出假 MENTIONS | 落在書名區的邊 1,938 條（Pericope 1,573+133，Chunk 212+20）；純假邊 1,745 條；另有 337 條是真提及，只是位置記錯；12 個實體完全由書名產生（列王紀、彌迦書、民數、雅歌…）；馬可 96/103、馬太 152/160、路加 146/149 | NER 的輸入是帶前綴的 embedding 文字（hierarchical_chunker.py:170-175、process_bible.py:386-400），由 extract_entities.py:96-100 原封傳給 ner_extractor.py:116-119 | 已驗證・更正 | NER 只抽「標題區＋本文」。本文起點用 `text.find('：')+1`，34,072 筆全部成立。不改 Step 0，也不改 embedding。加 validate_mentions 閘門。**不**把「尼西米記」改名（會牽動後端、評估與 Qdrant）。**不**拿掉 verse NER（會失去 169 個長段的 3,477 個錨點） | 否（NER 重跑約 30 分鐘；描述重生放在 2B） | /api/v1/entity；opt-in graph_*；傳染到 Step 6/7/8；registry 不受影響 | 1C |
| M2 | 字典子字串汙染（撒馬利亞→馬利亞、以利亞撒→以利亞、迦勒底→迦勒、閃電→閃…） | 14 個名字合計下界 548 條；馬利亞 93–95/126、以利亞 77–82/125；正確的長名實體（Place 撒馬利亞、以利亞撒、西西拉、撒但…）不存在；relations.jsonl 中 165 筆落在汙染配對上（FATHER_OF 69、SON_OF 69） | ner_extractor.py:167-205 用 `text.find`，沒有詞界；:259-280 重疊時一律保留字典結果，CKIP 抽出的較長名字（撒馬利亞 GPE）會被丟掉，已最小重現；字典也沒收長名 | 已驗證 | 建一份權威的 RCUV 專名表，不可由 CKIP 產物自建（CKIP 也會錯，例如西西拉被標成 GPE）。字典命中若被長名覆蓋就不採用；只靠 WS 詞界不夠（例：以利亞／敬）。長 span 優先，但型別取自專名表 | 部分：新實體所在段落要定向 R4，約 1–2 h | graph_person、/api 的人物層、親屬邊精確率 | 2B |
| M3 | 單字「但」、型別覆寫，以及清理結果不會傳遞 | 不受支撐的衍生邊 374 條（OCCURRED_IN 370、RULED 3、NEAR 1，全部是「但」）；place:dan 在 PG 有 1,882 列，Neo4j 只有 26 條；Person「猶大」從未產生，福音書與使徒行傳有 22 條掛在 place:youda；以法蓮 424 筆全歸 Place | ner_extractor.py:57-63 是 name→type 的 dict，後寫覆蓋前寫；10.2 只刪 Neo4j 的 MENTIONS；10.3 無 provenance 檢查 | 部分成立（不是順序 bug） | NER 共用地理判斷規則；6.05/6.1 加 provenance 閘門（豁免 prior 與 curated，並把 chunk 層的提及算作支撐）；清理改成編譯期規則；猶大、以法蓮拆出 Person 屬於身分層 | 否（「但」）；猶大拆分在延後-A | graph_place、entity_path、/api/v1/entity/place:dan | 1A、1C、延後-A |
| M4 / ID-6 | 字典拼法與 RCUV 不一致 | 在 RCUV 出現 0 次的字典字形 19 個（若連括號消歧鍵一起算是 28 個）；撒馬利亞只以 object:samaliya（99 mc）存在；泰爾被拆成 Person 與 Place；priors 用「流便」（RCUV 0 次），RCUV 寫「呂便」（93 次） | entity_dict.py:83/97/132/150/151/158/175/207/219/260；pos_extractor.py:23-27、146 只排除字典拼法 | 已驗證 | canonical 改用 RCUV 拼法；舊拼法移到另一份「查詢別名表」（backfill_aliases 不再直接讀 entity_dict）；間隔號正規化（會改到 person:bo‧shan 等 id）；加字典對照 RCUV 的出現次數測試 | 部分（同 M2） | `backend/utils/entity_dicts.py` 直接 import 這份字典，線上 R3/R6 路由會改變 | 2B |
| M5 | 位置錯誤、null 位置、Phase 2 截斷 | start_pos 為 null 的 21,939 條（E/O/T 15,995、verse 回填 5,782、curated 162）；CKIP 位置重複 4,131/23,948 筆；Object 689 個、Theme 148 個召回被截斷；37 個 Event 的 mention_count 灌水（饑荒 90 對 6） | ner_extractor.py:235 用 `text.find` 只取第一次出現；:219-220 沒有 strip；pos_extractor.py:114 取 `[:10]`；import_neo4j.py:301-305 首筆勝出 | 已驗證・更正 | 改用 CKIP `entity.idx`，strip 後同步位移；寫入 source_region 與 verse_id；去截斷只做 O/T，做到 Event 會改到 registry 錨點；Phase 4 名稱快取要先實作 | 位置：否；去截斷要重跑 Phase 2（延後-B） | graph 與 entity_query 對 O/T 的召回；mention_count 排序 | 1C、延後-B |
| M6 | 管線陷阱：局部重跑會毀掉全量產物 | `--ner-only` 會丟掉 E/O/T 4,897 個實體、20,458 筆 mention，以及 live 15,995 條 E/O/T MENTIONS（registry 的錨點）；`extract_relations --pericope-id` 以 "w" 模式覆寫 relations.jsonl（6,958 筆）與 unclassified（77,953 筆） | extract_entities.py:383-394、456-460；extract_relations.py:41、85-92、224 | 已驗證 | Step 1 拆成兩半，grounded 半邊凍結；Step 6 分檔輸出並支援 RE_*_PATH；重建一律走 staging | 否 | 保護 registry 與描述 | 0、2A |

### 2.2 身分層
| ID | 缺陷 | live 規模 | 根因步驟 | 可信度 | 修法 | LLM | 下游影響 | 批次 |
|---|---|---|---|---|---|---|---|---|
| ID-1 | 無聲調拼音 id 造成同音合併 | live 有 169 個 Person 節點含外來字形（全型別 268 個 id）；Person 共吸收 380 種字形，58 個的顯示名是少數字形（例：Ruth 顯示為「路德」）；掛著 3,201 條 MENTIONS 與 2,310 條實體間邊；改 TONE3 仍有 76 個碰撞 | ner_extractor.py:282-292（lazy_pinyin）；:133/146 的 alias 記帳錯誤；extract_entities.py:101-110 先到先贏 | 已驗證・更正 | 凍結既有 id 的註冊表；只對誤合的群組發新 id（漢字 canonical 加全形括號限定語，**不可用 '#'**，否則 URL 會被截斷）；輸出 id_migration；拆分依 PG/JSONL，不依 Neo4j 的 text_span（後者首筆勝出，有 41 對含多種字形）；alias 記帳的修正不可單獨先上，否則會把悅納、希臘之類升格成 alias | 是（重生 K7 300–500 個實體；新配對要跑 R4） | /api/v1/entity；find_entity_by_name；opt-in graph_person | 延後-A |
| ID-2 | 同名不同人：find_canonical_name 先寫先贏 | 7 個 Person 字典條目永遠不會產生節點（雅各兩位、約瑟養父、奮銳黨的西門、猶大、但、以法蓮）；掃羅王節點掛了使徒行傳 12 條（act:13:2 確實是掃羅王，不搬）；彼得掛了 14 條其他西門；希律混了 3 個人 | entity_dict.py:333-347；ner_extractor.py:57-63；backfill_aliases.py:73-78 | 已驗證・更正 | 註冊表加 cues（限定語優先於書卷範圍）並允許 abstain；改為 name→Set[type]；canonical 要唯一，或 priors 改用 id 參照 | 是（同 ID-1） | 同上；字典結構改變會影響路由 | 延後-A |
| ID-3 | 名稱帶空白、書卷縮寫變成實體 | 前後帶空白 180 個，掛 286 條 MENTIONS 與 204 條關係邊；書卷縮寫實體約 13 個（林前、約、路、王下、弗、拉、猶…） | ner_extractor.py:127-128、215-242 沒有正規化；pos_extractor.py:139-147；grounded_classifier.py:185/189 | 已驗證 | 單一入口 normalize_surface；孿生節點合併（用 MERGE）；書卷縮寫停用表（豁免「但」，「俄」逐筆確認） | 否 | 舊的空白 id 會回 404 | 1C、1D |
| ID-4 | label 與型別錯誤、跨型別同名 | 跨型別同名的名稱 908 個；Object 與 NER 節點同名 285 個；士師被當成 Event（陀拉 96 條邊）；戶篩、示巴女王、亞拿尼亞沒有 Person 節點；group:yehehua 的 label 是 Person，造成 14 條 domain/range 違規 | grounded_classifier.py:22-47、208；extract_entities.py:155；pericope_miner.py:88；只有子型別的唯一約束 | 已驗證（合併方向必須逐案判斷：洪水、問安、聖會其實是真事件） | 加全域唯一約束（第 0 批）；domain/range 驗證（1A）；少數已確認的 relabel 放進 overrides（2B）；其餘逐案決策（延後-A） | 否（人工決策） | graph_place 查不到撒馬利亞；entity_query payload | 0、1A、2B、延後-A |
| ID-5 | aliases 幾乎全空、三庫不一致、有錯誤 alias | Person 有 aliases 的：Neo4j 13/2,419、PG 8；Qdrant 有 9,093/9,124 筆是字串；錯誤 alias：利未@馬太、掃羅@保羅、猶大@加略人（與 place:youda 撞名）、門徒@jidutu、流珥 | backfill_aliases 只寫 Neo4j，而且排在 Step 3/8 之後；Tier 1 沒有歧義檢查 | 已驗證・更正 | aliases 在編譯期產生，一次寫入三庫；新增 ambiguous_aliases 欄位；alias 若等於其他實體的 canonical 也算衝突 | 否 | find_entity_by_name 查「利未」第 1 名目前是 person:matai；/api 的 aliases | 1D |
| ID-7 | id 不穩定；curated 用字面 id；10.5 會靜默造出殭屍節點 | curated 參照共 56 個；NEW_EVENTS 的 id 在執行期由 _pinyin_id 推導；沒有 :Entity 全域約束 | backfill_head_events.py:197-198、255；backfill_manual_patches.py:228-240 用 MERGE ON CREATE | 已驗證 | NEW_EVENTS 改字面 id；10.5 遇到缺的 id 就硬失敗；加全域約束（第 0 批）；註冊表與 redirect 放延後-A | 否 | 防止 registry 斷鏈 | 0、延後-A |

### 2.3 關係層
| ID | 缺陷 | live 規模 | 根因步驟 | 可信度 | 修法 | LLM | 下游影響 | 批次 |
|---|---|---|---|---|---|---|---|---|
| REL-01 | R2 規則的方向等於字母序，訊號又太寬 | phase 2 共 771 條（親屬 646）；同型別有向邊 100% head_id<tail_id；規則親屬抽樣 3/22 正確、非親屬 3/14；例：羅得 FATHER_OF 他拉 | pair_miner.py:115-119；rule_classifier.py:36-50、81-83；yaml :33/:56/:78/:102/:239；extract_relations.py:178-183 | 已驗證（錨定比例隨 regex 寬嚴變動，結論不變） | 改用錨定句型 anchored_rules（原型抽樣 30/30 正確，召回 77 條）；刪除過寬的訊號；6.05 用錨定輸出取代 phase 2；772 個從未經 LLM 判定的 rule-hit 配對交給 2A 做 R4 | 否（R4 補判在 2A） | 只影響 opt-in entity_path；論文的 772 | 1A |
| REL-02 | R5 反向物化放大錯誤，且有性別錯誤 | inverse 756 條（親屬 736，其中 605 條來自規則）；由規則反推的 0/9 正確；女性為 head 的 FATHER_OF ≥40 條（約 22 條本身是 phase 2）；FATHER_OF 雙向矛盾 25 對；135/252 個子女有 ≥2 個父親 | inverse_materializer.py:30-61（×0.9 在 :53）；yaml :43/:54/:65；extract_relations.py:97-104 | 已驗證・更正（行號） | R5 預設關閉；6.05 丟掉 phase 5 的反向邊；去重時處理矛盾，依 prior > LLM > 錨定 的優先序 | 否 | entity_path 的 LIMIT 額度會被平行反向邊吃掉 | 1A（須與 REL-01 同步） |
| REL-03 | 同型別有向關係沒有反向名，LLM 只能照字母序寫 | phase 4：LOCATED_IN 48、PRECEDED_BY 16、CAUSED 10、SUCCEEDED_BY 1，全部 head<tail；至少 15 條 LOCATED_IN 把「容器」放在 head | grounded_re_classifier.py:101-117、249-260；yaml :421 的描述與關係名語意相反 | 已驗證 | prompt 加 subject 欄位決定方向（不新增反向邊型）；1A 先標記，並丟掉與 prior 矛盾的邊 | 是（約 75 對，分鐘級） | 方向性問答；論文的 ontology 描述 | 1A、2A |
| REL-04 | confidence 是查表常數，而且與精確率反向 | 親屬邊 ≥0.9 桶 660 條，精確率約 0.18；<0.8 桶 227 條，約 0.95；親屬整體約 0.26 | models.py:107-114；rule_classifier.py:114；grounded_re_classifier.py:266；priors_loader.py:149；backfill_event_relations.py:37 | 已驗證・更正 | 加 source 欄位，再以分層標註做校準表，或乾脆移除 confidence；匯入只在 onCreate 時寫屬性，所以要靠重建才會生效 | 否（需人工標註約 200 條） | backend 不讀；論文的「confidence-filterable」 | 1A、2A |
| REL-05 | （與 M3 合併）「但」的孤兒邊 | 見 M3 | 見 M3 | 已驗證 | provenance 閘門 | 否 | — | 1A |
| REL-06 | 10.3 共現搶救把共現升格成型別化語意邊 | 9,060 條（PARTICIPATED_IN 5,641、OCCURRED_IN 3,419，confidence 0.35）；嚴格精確率約 0.2；18.5% 的邊端點名稱根本不在段落經文中 | backfill_event_relations.py 的設計本身；unclassified 沒有狀態欄位 | 已驗證 | 預設退場（待你決定）；在 2A 用定向 R4 取代（約 9,562 個唯一配對，加上字面端點閘門） | 退場：否；取代：是（約 2–4 h） | 只影響 opt-in entity_path；論文 +5,641/+3,419、84.0%/75.5% | 1A、2A |
| REL-07 | R4 整批共用第一對的 grounding；R1 截斷依型別前綴排序 | 送進 LLM 84,541 對，其中 16,425 對（19.4%）因批次 bug 看不到自己的端點；516 段觸到 80 對上限，家譜中的 Person×Person 配對約損失 94% | grounded_re_classifier.py:124、238、267；pair_miner.py:115、147-150 | 已驗證・更正 | 依相同 context 分批，證據必須含端點；截斷改成同節優先；全量重跑留到延後-C | 是（全量 10–20 h） | entity_path 的召回 | 2A、延後-C |
| REL-08 / EV-10 | Event–Event 時序與因果邊幾乎沒有，且多為雜訊 | 26 條，其中合理的約 8 條；候選約 315 對 | pair_miner.py:21-30 只在同段配對；yaml 的規則信心值低於門檻 | 已驗證 | 停止用共現加 LLM 產生 Event–Event 邊；有需求時再建 curated 時間線 | 否 | 預設關閉的 entity_path 會泛型走訪到這些邊 | 1A |
| REL-09 | extraction_phase=5 有兩種意義；邊上沒有 source/model/run_id | phase 5：共現 9,060 條＋inverse 756 條；R4 的模型來源互相矛盾（gemma3:4b 對 gemma4:31b） | models.py:22；backfill_event_relations.py:38 | 已驗證・更正 | 新增 phase 碼，並加 source、model、run_id、schema_version 欄位 | 否 | 可稽核性；不能再用 phase 篩邊 | 1A |
| REL-10 | Step 6 不能安全續跑、會覆寫產物、匯入只寫 onCreate | checkpoint 在 R4 開始前就寫滿 85,439 對，中途崩潰後 `--resume` 會產出 0 條 LLM 邊；`--no-llm` 會覆寫 unclassified；live 有 4 條邊的屬性停在舊值 | extract_relations.py:117-128、171-192、221、224-235；import_relations_neo4j.py:53-66 | 已驗證（比原述嚴重） | 判定完成才寫 checkpoint；逐批 append；分檔輸出並帶 run_id；拒絕危險的覆寫 | 否 | 這是任何 R4 重跑的前提；論文「checkpointed and resumable」要更正 | 2A |

### 2.4 交叉引用
| ID | 缺陷 | live 規模 | 根因步驟 | 可信度 | 修法 | LLM | 下游影響 | 批次 |
|---|---|---|---|---|---|---|---|---|
| XREF-1 | supplementary 的 NT 端錨點錯位、被靜默丟棄、被 MERGE 吞掉 | 59/142 條錯位（其中 44 條是純假邊）；16 筆定義被丟棄；3 列被吞；heb:1:0 的前 6 名鄰居全是錯位的 curated 邊 | nt_cross_references.py:34-453 寫死段落序號；process_bible.py:199 與 201-215 不對稱；:222-226 靜默 continue；import_neo4j.py:155-165 | 已驗證 | 改用經文座標，兩端對稱解析；失敗就報錯；所有 curated 來源一起依 pair 聚合；走 Step 0 重建。調查中提出的 M2 線上 Cypher 有 keep 欄位 bug，照跑會刪掉 59 條、重錨 0 條，不採用 | 否 | 只影響 opt-in cross_ref_expand/cross_reference；Round 3 graph 組態的數字之後不能直接比較 | 1B |
| XREF-2 | supplementary 定義有 3 筆內容錯誤 | rev:20:0→isa:65 確定錯；rev:19:1→psa:118、rev:19:2→dan:7 屬釋經判斷 | nt_cross_references.py:429-447 | 第 1 筆已驗證，後 2 筆為推論 | 刪第 1、2 筆；第 3 筆改成 dan:2:47 或 deu:10:17，或降級為 TSK 邊（有 votes 8 的證據）；TSK 支撐閘門放在 Step 9 | 否 | 影響極小 | 1B（需你確認） |
| XREF-3 | 用「沒有 votes」推斷 curated（999 哨兵） | 916 條被當成 curated；3 條 TSK 邊的 votes≥999，被誤判成 curated；多跳 fallback 不回傳 votes | neo4j_db.py:202、239、261-275；cross_ref_retriever.py:64-71、109-110 | 已驗證 | 建置時寫入 `r.curated`；backend 改讀這個旗標，並以最短路徑的狀態判定；**部署順序：先部署 backend，再改資料** | 否 | backend 程式改動，需重建 image；只影響 opt-in xref | 1B |
| XREF-4 | TSK 匯入只在 ON CREATE 寫屬性 | 856 對 TSK 證據被既有 curated 邊吞掉，沒有寫上 votes | import_tsk_crossrefs.py:58-70、225-238 | 已驗證 | 無條件 SET votes/verse_pairs/tsk；加計數閘門 | 否 | curated 邊多了 votes，可用來排序 | 1B |
| XREF-5 | markdown 平行經文解析器漏邊 | 43 段真正的引用沒解析出來（例如徒 9/22/26 的保羅歸主）；14 條跨章引用的 verse_end 錯（其中 6 條 end<start）；36 條跨段範圍只連到第一段；70 段「細拉」被當成引用 | markdown_parser.py:35-72、216-229；process_bible.py:325-342 | 已驗證 | 重寫 CrossRefParser；跨段展開時設上限 | 否 | curated 扇出變大（opt-in xref） | 2D |
| XREF-6 | TSK 邊不存經文錨點 | 映射本身正確（300 筆抽樣缺邊 0）；跨章 to-range 有 654 行只連到端點段落 | import_tsk_crossrefs.py:134-138、190-196 | 已驗證 | 存前 5 個 anchors，跨章範圍完整展開 | 否 | 純增益 | 2D（可選） |

### 2.5 事件層
| ID | 缺陷 | live 規模 | 根因步驟 | 可信度 | 修法 | LLM | 下游影響 | 批次 |
|---|---|---|---|---|---|---|---|---|
| EV-01 | 標題型 Event 膨脹，LLM 的否決沒有約束力 | 1,714 個 Event 中，1,636 個自我指涉；1,532 個只有 1 個段落且名稱等於標題；Neo4j 只有 20/1,714 個帶 extraction_method | pericope_miner.py:87-88；grounded_classifier.py:133、199-201、**203-209（型別越界時直接沿用，屬漏列路徑）**、212-218；extract_entities.py:152-156 | 已驗證（新增一條洩漏路徑） | 判決必須生效：rejected 與 error 都不輸出，error 讓建置失敗；把標題判決固化成檔；把 provenance 帶到 Neo4j 與 Qdrant（PG 已經有） | 是（約 2,400 個標題的判決） | registry 只讀 curated 事件，有白名單保護；entity_path 會走 PARTICIPATED_IN | 1D（provenance）、延後-B |
| EV-02 | 垃圾 Event 節點 | Event 27 個（34 條 MENTIONS、139 條關係邊）；同一根因的還有 Theme 36 個、Object 25 個 | bible_md_parser.py:81-87、104；pericope_miner.py:102-115；pos_extractor.py:146 在 strip 之前做比對 | 部分成立（成因第 4 點不成立） | 共用 `_is_junk_title`，在編譯期套用到所有 E/O/T；「這是基督嗎？」列入白名單 | 否 | 無（都不在 registry 內） | 1D |
| EV-03 | 敘事標題被字尾規則標成 Object 或 Theme | 名稱等於標題的 Object 125 個（約 28% 其實是敘事事件），Theme 576 個；王名段落標題被標成 Event 的 26 個 | pericope_miner.py:41-54、77-85；rule_classifier.py:17-47、76-80、83 | 推論（Object 的比例是人工判讀） | 標題型別交給判決檔；字尾規則只用在 4 字以內的名詞；刪掉關鍵字「約」 | 是（與 EV-01 合併處理） | /api 與 entity_query 的型別 | 延後-B |
| EV-04 | (無標題) 續段被 grounded 抽取整段漏讀 | 176 段（2,289 節）；registry 中掃羅受膏缺 1sa:10:0、新天新地缺 rev:22:0 | bible_md_parser.py:190-197、221-226（原述的 miner 修法無效） | 已驗證・更正 | parser 建立隱含的 (無標題) 段，miner 做續段繼承；2 個 curated 錨點直接寫進 events.yaml | 是（Phase 2 多吃 2,289 節） | O/T/Event 召回；registry 的 2 個事件 | 2C、延後-B |
| EV-05 | registry 的 curated 錨點問題 | 4 個觸發詞的首錨錯誤（墮落、掃羅受膏、八福、所羅門獻殿）；缺漏約 29 段；保羅歸主事件重複 2 個 | backfill_head_events.py:57-194 的常數；export_event_registry.py:127-145 | 已驗證 | 建立自足的 config/curated/events.yaml；export 加 --diff；依經文本身（而非 GT）修錨點 | 否 | **直接改變 event_registry.json，也就是線上預設** | 2C |
| EV-06 | 10.5 不會重放抽取型 curated Event 的 aliases | 3 個節點；全量重建後 registry 會從 33 個事件變 31 個（離線模擬）；EVENT_011 會失去觸發 | backfill_manual_patches.py:236-245、331 | 已驗證 | 所有 node 列都合併 aliases；extracted 節點只 UPDATE aliases；10.6 加 --check 閘門 | 否 | 不修的話，重建會靜默失去線上增益 | 0 |
| EV-07 | registry 綁在抽取 id 與現行 MENTIONS 上 | 14 個 registry 事件依賴抽取節點；2,227 條 Event MENTIONS 的 start_pos 全部是 null | export_event_registry.py:67-75；4 份互相獨立的 id 函式 | 推論（斷鏈未重現） | 清理只作用於 P/P/G，並排除 curated；每次遷移後跑 --check | 否 | 守門用 | 0、2C |
| EV-08 | Event 描述只是正文擷取；Step 7 描述只存在 Neo4j | Event 有 1,005 個描述剛好 100 字；P/P/G 的 3,045 條描述只在 Neo4j 與 Qdrant，PG 是 0/4,223，所以 /api 回傳的描述一律是空字串；已知有事實錯誤（拉結條目寫「其子為以法蓮與瑪拿西」） | extract_entities.py:174；desc_generator.py:59（無 ORDER BY）、73-77 | 已驗證 | 描述寫成快取 JSONL，加 replay 與品質旗標；PG 同步放 1D；重生放 2B | 凍結：否；重生：是 | /api/v1/entity 開始會有描述 | 0、1D、2B |
| EV-09 | 泛名詞與非特定的 Event | 非標題來源的抽取 Event 37 個（瘟疫、瑪拉、瑪撒、米利巴、耶和華曉諭…） | 停用詞只在 Phase 1 生效；cleanup_noise_entities.py:50-54 又重複定義一份 | 部分成立 | 停用詞抽成共用模組，套用到所有 phase；地名事件直接刪除，**不要**併入 Place（瑪拉同時是人名） | 否 | graph_event 的雜訊 | 1D |

### 2.6 驗證者補出的跨族缺陷
| ID | 缺陷 | 規模 | 根因 | 可信度 | 修法 | 批次 |
|---|---|---|---|---|---|---|
| G-1 | chunk 與 pericope 的粒度斷層 | 169 個切了 chunk 的長段（約 5,451 節，佔 17.6%）在 Step 6 時沒有 Pericope 級的 P/P/G MENTIONS；relations.jsonl 中出自這些段的是 0 筆；live 15,839 條帶 provenance 的關係只有 3 條出自這些段 | embedding_queue 對這些段只有 chunk 與 verse 項；pair_miner.py:21-27 只讀 Pericope 級 | 已驗證 | 挖配對前，把 chunk 的提及上捲到父 pericope | 2A、延後-C |
| G-2 | yehehua 改 label 後出現 domain/range 違規 | 14 條 | cleanup_noise_entities.py:262 | 已驗證 | 在 6.05 與 validate_kg 做 domain/range 驗證 | 1A |
| G-3 | prior 邊的 source_pericope_id 是經文引用，不是 pericope id | 64/64 | priors_loader | 已驗證 | 支撐閘門豁免 prior | 1A |
| G-4 | LLM 判對、但與 prior 重複的配對被記為 unclassified | 未計數 | extract_relations.py:193-203 | 已驗證（code-read） | 先計算 classified_pair_keys，再做 prior 過濾 | 2A |
| G-5 | Object/Theme 也有同音 id 碰撞 | Object 45、Theme 8（例：聖所與繩索、天地與田地） | extract_entities.py:134-141 | 已驗證 | 併入身分層處理 | 延後-A |
| G-6 | R1 配對的端點名稱不在段落經文中 | 22,118/85,439（25.9%） | 書名前綴、別名 | 已驗證 | M1 修好後大部分會消失；R4 前加字面端點閘門 | 1C、2A |

**已確認沒有問題的部分**：TSK 的 verse→pericope 映射正確；Event 層沒有同音碰撞；三庫的 id 集合一致；live 中沒有未標記的手動 MENTIONS；Step 0 與 NER 都是決定性的。

---

## 3. 整體整合設計

### 3.1 原則
1. **先離線編譯，再投影。** 所有修正都放在 JSONL 層，以決定性轉換完成，產出一份 KG 快照，再由單一載入器寫進 Neo4j、PG、Qdrant。三庫不同步（PG 描述全空、Qdrant 的 aliases 是字串、place:dan 兩邊不一致）在結構上就不會再出現。
2. **根因修在產生缺陷的那一步。** 事後清理（10.1、10.2、10.3）改寫成編譯步驟中的資料規則，放在 git 追蹤的 `config/curated/*` 與 `config/lexicon/*`。原本的腳本保留為「斷言模式」：對新產物做 dry-run，刪除數必須是 0。
3. **LLM 結果一律成為內容定址的快取**，記錄 model、temperature、prompt_version、輸入 sha 與 commit。只有快取沒命中才呼叫 LLM；只要快取在，重建就是決定性的。
4. **entity_id 是不透明鍵**：一經發放就凍結。只有在拆分或合併時新增或重導，並輸出 `id_migration.jsonl` 給所有以 id 為鍵的消費者使用。

### 3.2 目標管線與舊步驟對照
```
K0   process_bible.py                決定性；embedding_queue/pericopes/chunks 的 sha 閘門（改了就不准進）
K1a  extract_entities --stage ner    只抽「標題區＋本文」；位置用 CKIP idx；正規化；「但」用地理規則
K1b  extract_entities --stage grounded  凍結 output/frozen/grounded_*.jsonl；只有新候選才跑 Phase 4
K1c  compile_entities.py（新）       overlay：孿生合併、junk 與停用詞、overrides、aliases（含歧義過濾）、id_migration
KV0  validate_mentions.py（新）      硬閘門
K6   relations                       第 1 批：沿用 relations.jsonl；2A 起：離線挖配對（含 chunk 上捲）＋R4 快取
K6.05 relation_postprocess.py（新）  錨定規則、丟棄 R5、provenance 閘門、domain/range、source 欄位、校準
K7   描述 replay                     快取命中才用；輸入變了就標 stale，在 2B 重生
Kc   curated overlay                 第 1 批：沿用 10.4/10.5（字面 id、缺 id 硬失敗、aliases 合併）；2C 起改讀 events.yaml
KV1  validate_kg --snapshot
L    載入 staging                    PG entities/entity_mentions、Neo4j 全庫、Qdrant bible_entities_vN、Step 9 TSK（SET 語意）
KV2  validate_kg --live --target staging；export_event_registry --check；backend pytest；評估
P    升版（見 3.7）
```
| 舊步驟 | 新位置 |
|---|---|
| Step 1 `--ner-only` | K1a（`--stage ner`）；`--ner-only` 加覆寫保護 |
| 10.1 backfill_aliases | K1c 編譯 aliases；原腳本退役，改成三庫一致性檢查 |
| 10.2 cleanup_noise_entities | 「但」的地理規則移入 NER，generic-event 與 yehehua 移入 K1c；原腳本改成斷言模式 |
| 10.3 backfill_event_relations | 預設退場（D2）；若保留，就在 K6.05 依「本次配對集＋支撐閘門＋字面端點閘門」即時推導，不再讀舊快照 |
| 10.4 / 10.5 | 第 1 批先修字面 id 與硬失敗；2C 起改由 events.yaml 驅動 |
| （新）10.6 | validate_kg --live、export_event_registry --check、三庫一致性檢查；任何一項失敗就中止 |
| export_event_registry（目前不在文件中） | 正式列入管線；registry 有 diff 時必須人工核可 |

### 3.3 Step 10 的處置，以及「順序 bug」的更正
- **「但」不是順序 bug。** 10.2 從來不刪衍生邊，10.3 讀的是 5 月的 unclassified 快照，而且不查 live MENTIONS。把兩步對調，照樣會產生 370 條孤兒邊。根治方法有兩個：(a) 每個會產生邊的步驟（6.1、10.3）都加 provenance 閘門；(b) 把清理規則移到 NER 與編譯期，讓下游一開始就讀到乾淨的 MENTIONS。
- **真正的順序問題**（都已驗證，編譯再投影的設計可一併解決）：
  1. Step 8 排在 10.1 之前：Qdrant 不含字典 aliases，9,093 筆的 aliases 是字串。
  2. Step 3 排在 Step 7 與 10.x 之前：PG 的 P/P/G 描述全空，aliases 比 Neo4j 少，place:dan 不一致。
  3. Step 7 讀的是被汙染的 MENTIONS：例如 person:maliya 的描述寫進了「撒馬利亞」。
  4. Step 5 的 curated 交叉引用先建好，Step 9 TSK 只在 ON CREATE 寫入：856 對證據被吞。
  5. Step 6 R1 在 10.2 之前執行：吃到未清理的 MENTIONS。
- 新設計中，所有變動都在 L（載入）之前完成；10.6 是最後一道閘門。

### 3.4 決定性
- K0 已驗證逐位元相同；K1a NER 已驗證可重現（transformers 5.3.0、ckip 0.3.4，要在 scripts 環境釘住版本，並另外確認 pypinyin 是否已在 uv.lock 釘版）。
- 消除順序依賴：
  - MENTIONS 匯入前先依 start_pos 排序，讓「首筆勝出」有確定的定義；
  - desc_generator 取標題時加 ORDER BY；
  - pair_miner 的截斷不再依 id 字母序；
  - 去重時的矛盾消解要有明文政策；
  - NEW_EVENTS 改用字面 id。
- 測試：
  - 等價測試：修正全關時，編譯結果與現行 JSONL 逐位元相同；
  - 6.05 連跑兩次，邊集合必須相同；
  - golden 小樣本：創 1–12、王上 12、徒 8；
  - a6 離線重建模擬改成測試（registry 必須維持 33 個事件）。

### 3.5 全量重建，還是增量遷移？
**結論：KG 衍生層做全量重建，LLM 結果從凍結快取重用；不做線上增量遷移。**
- 重建範圍：Neo4j 全庫（Step 5 本來就會清庫）、PG 的 `entities` 與 `entity_mentions`、Qdrant 的 `bible_entities`。
- 不動的部分：PG 的四張結構表、段落向量 collection、BM25。前提是 embedding_queue 的 sha 不變（K0 閘門保證）。2D 只會改到 PG pericopes 的被動欄位。
- 理由：
  1. **可重現性已逐層驗證**（§0 第 2 點）。等價重建可以用 diff 證明，不是盲跳。
  2. **線上補丁在各族調查中被驗證者抓到多個陷阱**：
     - supplementary 重錨計畫沒有 keep 欄位，照跑會刪 59 條、重錨 0 條；
     - 有 8 條錯位邊身上帶著被吞的 TSK 證據，直接刪會讓這些證據遺失；
     - `apoc.merge.relationship` 只在 onCreate 寫屬性，重匯不會刷新（live 已有 4 條邊停在舊值）；
     - Neo4j 的 MENTIONS text_span 首筆勝出，依 live 拆分身分會漏掉第二種字形；
     - repair-from-jsonl 與 live 已做的補丁衝突（yehehua、curated MENTIONS，以及 PG 與 jsonl 本來就不一致：173,768 對 173,896）。
  3. 線上增量遷移本質上就是再寫一批 10.x，與「根治、不要 workaround」相衝突。
  4. 唯一允許的例外是緊急熱修，但必須走同一份編譯程式碼加上載入流程，不准手打 Cypher。
- 代價：
  - 每次重建都要建一次 staging；不呼叫 LLM 時牆鐘約 1–1.5 h（NER 若沒改，約 30–45 分鐘）。
  - 升版時 Neo4j 停機約 1 分鐘，或改用 URI 切換。

### 3.5.1 第 0 批前必須先保住的「只存在 live」的狀態
- Step 7 的 3,045 條 P/P/G 描述，以及 E/O/T 的描述：任何 JSONL 都沒有。
- Step 1 Phase 4 沒有逐候選的快取，被拒的候選沒有任何紀錄。
- output/ 被 gitignore，bak/20260715 也沒收 LLM 產物：relations*.jsonl、entities、mentions、checkpoint、cross_references_tsk.txt 都只有磁碟上一份。
- ALIAS_INJECTIONS 與 NEW_EVENTS 寫死在 Python 程式碼中。

### 3.6 validate_kg 品質門
- 模式：`--snapshot output/kg`（離線，可放進 pytest）；`--live --target staging|prod`（唯讀）。
- 基準檔 `config/kg_quality_baseline.json`（git 追蹤），每項記錄 id、query、value、direction、tolerance、severity。
- 結束碼：0 通過、1 硬失敗、2 ratchet 退步。`--ratchet` 只能往改善的方向更新基準。
- 探針檔 `config/kg_probes.yaml`：逐條宣告 (pericope, entity) 或 (head, rel, tail) 必須存在或不存在。

| ID | 檢查 | 現值（live） | 目標 | 何時變成硬門檻 |
|---|---|---|---|---|
| H1 | entity_id 全域唯一，且 `:Entity(entity_id)` 約束存在 | 重複 0；約束不存在 | 0／約束存在 | 0 |
| H2 | 每個 Entity 恰有一個型別 label | 0 | 0 | 0 |
| H3 | 衍生邊缺少共現支持（以 source_pericope_id 判斷；豁免 prior 與 curated；chunk 層提及也算支撐） | 374 | 0 | 1A |
| H4 | 名稱前後有空白 | 180 | 0 | 1C（P/P/G）、1D（全部） |
| H5 | 三庫一致：id 集合、type、canonical、aliases（必須是 list）、description | id 差 0；PG 描述 3,045 不符；Qdrant 字串 9,093 | 全部 0 差 | 1D |
| H6 | P/P/G MENTIONS 都有 source_region，且 start_pos 不為 null | 不適用 | 100% | 1C |
| H7 | embedding_queue 的 sha 不變；id 前綴與 label 一致（overrides 白名單除外） | 不一致 1（group:yehehua） | 0 | 0 |
| H8 | CROSS_REFERENCES 有明確的 provenance 旗標 | 916 條沒有 | 0 | 1B |
| H9 | schema 的 domain/range 違規 | ≥14 | 0 | 1A |
| H10 | Event MENTIONS 集合不變（保護 registry；刻意變更時改走 D1 人工核可） | 2,227 | 不變 | 1C 起每批 |
| R1 | 書名區 MENTIONS（第一位置落在書名區） | 1,938（純假 1,745） | 0 | 1C |
| R2 | 子字串探針（馬利亞、以利亞、利亞、以利、迦勒…） | 下界 548 條汙染 | 全部通過 | 2B |
| R3 | 同音誤合（Person／全型別） | 169／268 | 0（只剩註冊表 alias） | 延後-A |
| R4 | supplementary 錨點錯位 | 59 | 0 | 1B |
| R5 | 跨型別同名 | 908 個名稱 | 只剩白名單 | 延後-A |
| R6 | 親屬探針（NOT 羅得 FATHER_OF 他拉…）、FATHER_OF 雙向矛盾、女性 head 的 FATHER_OF、FATHER_OF 函數性違反率 | 25／≥40／53.6% | 0／0／≤5% | 1A |
| R7 | 只被單一段落提及的 Event 比例 | 1,535/1,714 | 觀察 | 延後-B |
| R8 | 垃圾 E/O/T（交叉引用殘標、句子碎片） | 27+36+25 | 0 | 1D |
| R9 | CKIP 位置重複；`text[start:end]==span` | 4,131；不適用 | 0；100% | 1C |
| R10 | 歧義或衝突的 alias（同一字形有 ≥2 個擁有者，或等於其他實體的 canonical） | ≥5 | 0 | 1D |
| R11 | votes 非 null 的邊數 | 249,502 | 250,358 | 1B |
| W | 各 label 數量、各關係型別直方圖，相對基準變動超過 ±5% 就警告（刻意的大幅變動要記錄在案，例如親屬邊從 1,571 降到約 300） | — | — | 0 |
| D1 | `export_event_registry.py --check`；registry 刻意變更時改為 diff 加人工核可 | 通過 | 通過 | 0 |
| D2 | backend pytest（含 test_event_registry） | — | 全過 | 0 |
| D3 | quick_retrieval_eval：registry 與字典未變時，預設組態 top-5 100% 相同 | — | 100% | 1A |
| D4 | 改到 entity_dict 時，跑 500 題路由分布回歸 | — | 落在雜訊地板內 | 2B |

> 人工判斷型指標（親屬精確率 0.26、MENTIONS 精確率）不放進自動閘門。改用固定 seed 的抽樣審查表（標註樣本加 sha），以 ratchet 管理。

### 3.7 通用升版流程：備份、staging、升版、回滾
**R0 備份**（每批升版前都要做）：
- `git tag kg-pre-<批次>`；照 bak/README.md 建 `bak/<日期>`：
  - PG：`pg_dump -Fc` 加 globals；
  - Qdrant：三個 collection 各做 snapshot；
  - Neo4j：`docker stop -t 60`，接著 `neo4j-admin database dump`，再啟動（停機約 1 分鐘）；
  - 產生 SHA256SUMS。
- 另外把 `output/frozen/`、relations*.jsonl、entities、mentions、checkpoint、TSK 檔打包成 tar，連同 sha256 manifest 一起放進 bak。這是現在的缺口。

**R1 staging 建置**：
- 另起 neo4j-staging 容器（獨立 volume，port 7688/7475）。
- PG 建 `bible_rag_staging` 資料庫。
- Qdrant 寫入 `bible_entities_vN`。
- 所有腳本以 `NEO4J_URI`、`POSTGRES_DB`、`QDRANT_ENTITY_COLLECTION` 環境變數指向 staging。

**R2 驗證**：
- `validate_kg --live --target staging`、`export_event_registry --check`；
- 起一個指向 staging 的第二個 backend 容器（另一個 port），跑 pytest 與評估（見 §6）。

**R3 升版**：
- Neo4j：從 staging dump，再對正式 volume 做 `load --overwrite-destination`（停機約 1 分鐘，期間 /api/v1/entity 會出錯）。另一個選項是把 backend 的 NEO4J_URI 改指 staging，但需重啟 backend，因為容器的 env 是快照。
- PG：`pg_dump -t entities -t entity_mentions` 從 staging 匯出，在一個 transaction 內換表。
- Qdrant：把 `qdrant_entity_collection`（config.py:156）改指 `bible_entities_vN`，或一次性改用 Qdrant alias。
- 程式碼、registry、字典隨 image 上線：`docker compose up -d --build backend`（沒有 volume mount，只 restart 會跑舊 image；要走 uv 快取的建置流程）。

**R4 升版後檢查**：`validate_kg --live --target prod`；抽查 /api/v1/entity。

**R5 回滾**：
- 資料：載回上一份 Neo4j dump，從 bak 還原 PG 的兩張表，把 Qdrant collection 名稱切回去。
- 程式碼與 registry：`git revert`，再重建 image。
- 每份編譯快照保留在 `output/kg_snapshots/<ts>/`。回滾等於重新載入上一份快照，比還原 dump 快，而且三庫一定一致。

**順序規則**：
- backend 程式碼的變更要做成向前相容（先部署 backend，再升資料，例如 1B）；
- 一個缺陷項目一個 commit，各自附探針；validate 失敗時才分得出是哪一項造成。

---

## 4. 分批計畫

### 第 0 批：保全與管線骨架（不改資料語意、不升版）
- **涵蓋**：M6（Step 1 的部分）、EV-06、EV-07（閘門）、EV-08（凍結）、ID-7（字面 id、硬失敗、約束）、XREF 的 missed#1（Step 0 進重灌鏈）、架構師的 P0/P1。
- **要改的腳本與函式**
  - `scripts/extract_entities.py`：新增 `--stage ner|grounded|merge`。grounded 半邊從現有 entities.jsonl 依型別拆出，寫成 `output/frozen/grounded_entities.jsonl` 與 `grounded_mentions.jsonl`（已驗證可無損拆分），附 manifest。`--ner-only`（:383-394、456-460）加覆寫保護：沒有 `--force` 就拒絕執行。
  - `scripts/desc_generator.py`：每產生一條描述就寫入 `output/frozen/descriptions.jsonl`（entity_id、description、model、prompt_version、titles_sha、quality_flag）；新增 `--replay`；:59 加 ORDER BY。內容先不改。
  - 新增一次性腳本 `scripts/tools/export_live_state.py`（唯讀）：從 live Neo4j 匯出描述（3,045 條 P/P/G，加上 E/O/T）、aliases、labels、curated MENTIONS，作為快取的種子。
  - `scripts/backfill_manual_patches.py:236-245`：所有 node 列都用 `apoc.coll.toSet` 合併 aliases（排除與 canonical 相同的值）；:331 的 PG/Qdrant 同步，對 extracted 列只更新 aliases（不要走 ON CONFLICT 覆寫 description）；找不到 origin=extracted 的 id 時硬失敗，不可 MERGE ON CREATE。
  - `scripts/backfill_head_events.py`：NEW_EVENTS 改成字面 entity_id（18 個已知值，與 registry 一致），不再呼叫 `_pinyin_id`。
  - `scripts/import_neo4j.py` 的 create_constraints：加上 `CREATE CONSTRAINT FOR (e:Entity) REQUIRE e.entity_id IS UNIQUE`（現況重複數為 0；順便消除 label scan）。
  - 新增 `scripts/validate_kg.py`、`config/kg_quality_baseline.json`、`config/kg_probes.yaml`：把 §3.6 的現值記為基準。
  - 新增 `scripts/check_identity.py`：三庫的 id、type、canonical、aliases、description 比對。
  - `docs/build_database.md`：重灌鏈加入 Step 0 與 sha 閘門；Step 7 改為 replay；新增 10.6；把 export_event_registry 寫進文件；更正 :388、:426、:440、:443 的敘述。
  - staging：docker-compose override（neo4j-staging）、各腳本的環境變數管道、指向 staging 的 backend 容器。
- **新增測試**（新建 `scripts/tests/`，目前不存在）
  - `test_extract_entities_stages.py`：merge(ner, frozen grounded) 必須逐位元等於現行 entities.jsonl 與 entity_mentions.jsonl。
  - `test_desc_replay.py`：replay 冪等；titles_sha 改變時標記 stale。
  - `test_manual_patches_aliases.py`：extracted 節點重放後保有 aliases；缺 id 時硬失敗。
  - `test_registry_rebuild_sim.py`：把 a6_simulate_rebuild 改成測試，registry 必須是 33 個事件、diff 為 0。
  - `test_validate_kg.py`：以固定的快照 fixture 驗證每項檢查。
- **管線順序變更**：重灌鏈改為 0 → 1(merge) → 3 → 4（sha 未變就跳過）→ 5 → 6.1 → 7(replay) → 8 → 9 → 10.1–10.5 → 10.6（新）→ export。
- **線上遷移**：無，不升版。只做 R0 備份，並在 staging 上做 P1 等價重建；diff 必須逐項列出並解釋。預期差異：verse remap 後的 start_pos 分布（start_pos=0 從 1,785 變 1,947，null 從 21,939 變 16,106）、mention_count，以及「但」的 370 條孤兒邊重新出現（10.3 仍在跑）。
- **驗證門檻**：
  - staging 上 `export_event_registry --check` 結束碼 0，registry 是 33 個事件；
  - 三庫 id 集合差為 0；
  - E–E 各 phase 的邊數與 live 相同（允許的差異需逐項列出）；
  - 描述 replay 後，staging 與 live 逐字相同；
  - H1、H2、H7 通過。
- **工時**：36–50 h（備份與匯出 4–6；Step 1 拆半 6–8；描述快取 4–6；EV-06 與 ID-7 共 3–4；validate_kg 加基準 12–16；staging 基建 4–6；P1 重建與 diff 6–8）。
- **行為影響**：沒有。這批的作用是防止重建時退化。
- **前置決策**：D13（被刪除的評估檔）。

### 第 1 批：不需重跑 LLM、根因明確、可直接併入管線
升版分兩波：**第一波 1A＋1B**（不重跑 NER）；**第二波 1C＋1D**（兩者要一起升，因為 1C 的空白正規化需要 1D 的 id_migration）。

#### 第 1A 批：關係層的決定性後處理（Step 6.05），以及 10.3 的處置
- **涵蓋**：REL-01、REL-02、REL-03（標記）、REL-04（加 source 欄位）、REL-05/M3（閘門）、REL-06（退場）、REL-08/EV-10、REL-09、G-2、G-3。
- **要改的腳本與函式**
  - 新增 `scripts/relation_extraction/anchored_rules.py`：帶槽位的錨定句型，例如「{P}的(長|次)?(兒子|女兒){C}(、{C})*」「{C}是{P}的兒子」「{P}(又)?生(了)?{C}」「{H}的妻(子)?{W}」。名字用全實體詞庫做最長匹配，並檢查前後詞界；整個句型必須落在同一節內。方向由槽位決定。是否輸出有性別的關係見 D3。
  - 新增 `scripts/relation_extraction/relation_postprocess.py`（Step 6.05，純函式）：
    - 讀 relations.jsonl，加上 anchored 輸出與編譯後的 mentions；
    - 丟掉 phase 2 規則三元組（771）與 phase 5 反向邊（756）；
    - 丟掉 LLM 產生的 Event–Event 邊（26）；
    - 丟掉與 prior 矛盾的 phase 4 同型邊；其餘 75 條標 `direction_verified=false`；
    - provenance 閘門：source_pericope_id 或其 chunk 必須同時 MENTIONS 兩端；prior（64 條，source_pericope_id 是經文引用）與 curated 豁免；
    - 依 schema_loader 驗證 domain/range（例如 yehehua 的 14 條）；
    - 矛盾消解依 prior > LLM > anchored 的優先序，並寫衝突日誌；
    - 每條邊寫入 `source`（prior/anchored_rule/llm）、`model`、`run_id`、`confidence_raw`；
    - 讀入 `id_migration.jsonl`（1D 產出）；
    - 輸出 `relations_clean.jsonl`。
  - `rule_classifier.py:81-83`、`extract_relations.py:178-183`：只有錨定規則可以直接定案（continue），其餘交給 R4。
  - `extract_relations.py`：R5 預設關閉；`_dedup_triples`（:97-104）加矛盾消解。
  - `inverse_materializer.py`：預設停用；yaml 的 inverse 修正性別（:43、:54、:65）。
  - `config/relations/biblical_relations.yaml`：刪掉寬訊號（生、父親、…的兒子、屬…、兄弟、列祖、回到）；把 PRECEDED_BY 的描述改成與關係名一致（:421）。
  - `models.py`：新增 phase 碼 ANCHORED_RULE 與 COOCCURRENCE，ExtractedRelation 加 source、model、run_id、schema_version。
  - `import_relations_neo4j.py`：改讀 relations_clean.jsonl，寫入新欄位。
  - `backfill_event_relations.py`：預設不執行（保留 `--legacy-cooccurrence` 供論文重現），見 D2。
  - `cleanup_noise_entities.py`：「但」的部分改成斷言模式。
- **新增測試**
  - `test_anchored_rules.py`：例如「他拉生亞伯蘭、拿鶴、哈蘭；哈蘭生羅得」必須得到正確方向；「亞拿突」不可命中「亞拿」；原型的 30 條回歸樣本。
  - `test_relation_postprocess.py`：連跑兩次結果相同；prior 豁免；「但」的孤兒邊被移除；違反 domain/range 的邊被移除；女性 head 的 FATHER_OF 為 0；不存在任何 inverse 邊。
- **管線順序變更**：6 → **6.05（新）** → 6.1（讀 relations_clean.jsonl）；10.3 移出預設鏈；10.6 加入 H3、H9、R6 檢查。
- **線上遷移**：照 §3.7 的 R0–R5；與 1B 一起在 staging 重建後升版。回滾用上一份 Neo4j dump（PG 與 Qdrant 不涉及關係邊）。
- **驗證門檻**：
  - H3 = 0（原 374）；H9 = 0；
  - R6：FATHER_OF 雙向矛盾 0（原 25）、女性 head 的 FATHER_OF 0（原 ≥40）、函數性違反 ≤5%（原 53.6%；以 FATHER_OF 計，父母各一屬合法）；
  - 每條語意邊的 source 都不為 null；不存在「phase=5 且 source≠inverse」的邊；
  - 同型、無成對名稱的有向關係，在 n≥30 時，head<tail 的比例落在 0.3–0.7；
  - 錨定規則人工抽樣 n≥30，Wilson 下界 ≥0.85；
  - D3 通過；
  - entity_path 的非劣性：Δvrec ≥ −0.005。
- **工時**：24–32 h。
- **行為影響**：只有 opt-in 的 entity_path（錯邊與重複的反向邊消失）；預設路徑與 registry 都不變。論文 sec3_kg.tex:104-185 的計數（772、5,370、752）與 R2/R5 的描述需要改寫。

#### 第 1B 批：交叉引用 provenance、supplementary 重錨、TSK 證據
- **涵蓋**：XREF-1、XREF-2、XREF-3、XREF-4。
- **要改的腳本與函式**
  - `bible_chunking/nt_cross_references.py`：資料改成經文座標，例如 `SupplementaryCrossRef(src="heb 1:5", tgt="psa 2:7", …)`。以一次性腳本機械轉換舊資料（取 book:chapter 加上 source_verses），刪掉沒用到的 `resolve_pericope_id` 與 process_bible.py:43 的 import。
  - `scripts/process_bible.py:185-242`：兩端對稱，都用 `_resolve_to_pericope` 解析；逐節檢查是否落在段落內，跨段的情況依明確的扇出政策處理（目前 3 筆）；拿掉 :222-226 的 continue 與退回 chapter 的 fallback，改成累積錯誤，最後以非 0 結束碼退出；**所有 curated 來源**（markdown 加 supplementary）一起依 pair 聚合，properties 改用 list（`supp_anchors`、`curated_sources`），並寫入 `curated: True`；:325-342 的 markdown 邊也加 `curated: True`。
  - `scripts/import_neo4j.py:155-165`：改吃聚合後的列，同一個 pair 只出現一次。
  - `scripts/import_tsk_crossrefs.py:58-70`：先 MERGE，ON CREATE 時設 `source='tsk', curated=false`；之後**無條件** SET `votes`、`verse_pairs`、`tsk=true`；結束時檢查 `count(r WHERE r.tsk) == len(rows)`（250,358），並分開列印 created 與 attached_to_curated 的數量；加上 `--refresh`；supplementary 的 TSK 支撐閘門放在這一步（TSK 檔在 fresh clone 時可能不存在）。
  - `scripts/validate_output.py`：檢查定義筆數與錨點數相符、兩端節號都落在段落內、聚合後沒有重複的 pair、markdown 與 supplementary 重疊為 0。
  - `backend/database/neo4j_db.py:202、239`：改成 `max(coalesce(r.votes,0))`，curated 由旗標判定（過渡期用 coalesce 加 source 推斷）；:261-275 的 fallback 只看最短路徑上是否全為 curated；排序改為 `seed_support DESC, curated DESC, votes DESC`。
  - `backend/utils/retrieval/cross_ref_retriever.py`：:64-71 改成 `_edge_weight(hop, curated: bool)`，刪掉 `_CURATED_VOTES`；:35-45、:109-110 改傳 curated。
  - XREF-2：刪除 rev:20:0→isa:65；rev:19:1→psa:118 刪除；rev:19:2→dan:7 依你的決定（D10）改目標，或降級為 TSK。
  - 文件：build_database.md:388、400-404；evaluation/README.md:226。
- **新增測試**：
  - `tests/test_supplementary_xref.py`：161 筆定義全部能解析；節號都落在段落內；158/161 有 TSK 支撐，其餘必須帶 `tsk_exempt`；
  - `backend/tests/test_cross_ref_weight.py`：TSK votes=1268 仍走 TSK 曲線；curated 且 votes=5 走 curated 曲線；hop-2 的 curated 權重是 0.55；
  - TSK 匯入計數測試；
  - CI 用 grep 確認 backend 中不再出現 `coalesce(r.votes, 999)`。
- **管線順序變更**：Step 0（聚合，失敗就中止）→ validate_output → Step 5 → Step 9（SET 語意，加計數閘門）→ 10.6 加入 H8、R4、R11。
- **線上遷移**：
  1. 先部署帶過渡 coalesce 的 backend（`docker compose up -d --build backend`）。這時行為只差兩處：那 3 條 votes≥999 的 TSK 邊、hop≥2 的權重。
  2. 再把 staging 重建結果升版。
  - **不要**使用調查中提出的 M2/M3 線上 Cypher（理由見 §3.5）。
  - 回滾：Neo4j 載回上一份 dump，backend 退回上一個 image tag。
  - 順序絕不能顛倒：若資料先上，856 條 curated 邊會被舊 backend 的「有 votes 就是 TSK」規則降級。
- **驗證門檻**：
  - 錯位查詢：來源端與目標端節號不在段落內的數量皆為 0（原 59）；
  - H8 = 0；
  - 被誤判成 curated 的 TSK 邊 0（原 3）；
  - votes 不為 null 的邊數 = 250,358（原 249,502）；
  - 連跑兩次 Step 9，屬性 diff 為 0；
  - heb:1:0 的前 8 名鄰居不再出現 curated 的 psa:2/45/104/102/110 與 2sa:7；
  - 預設組態 500 題 sources 逐位相同；
  - 在 S1 設定下跑 kg_xref 68 題：注入槽的金段落率（現約 3%）與「靠 xref 補到金段落」的題數（現 0/18）只做報告。
- **工時**：16–22 h。
- **行為影響**：**有，backend 程式碼會改（需重建 image）**，但只影響 opt-in 的 cross_ref_expand、cross_reference 與 "all"；預設路徑與 registry 不變。Round 3 graph 組態的數字之後不能直接比較。

#### 第 1C 批：NER 根因修正（書名前綴、位置、空白、「但」）
- **涵蓋**：M1、M3（「但」）、M5（位置與空白）、ID-3（NER 端）、G-6。
- **要改的腳本與函式**
  - 新增 `scripts/entity_extraction/text_regions.py`：把 embedding 文字切成 book（書名與「第N章」）、title（標題）、body（本文）三區，本文起點為 `text.find('：')+1`（34,072 筆全部成立）。**不改** `EmbeddingQueueItem`，不重跑 Step 0，不改 embedding。
  - `ner_extractor.py`：
    - `extract_from_text` 只對 title 與 body 做字典比對與 CKIP，位置換算回全文，每筆寫 `source_region`；
    - :215-242 改用 CKIP `entity.idx`，取代 :235 的 `text.find`；
    - :127-128 與 CKIP 輸出都先經過 `normalize_surface`（strip 前後、全形與 ASCII 空白、零寬字元，以及 NFC），並同步位移 start_pos；
    - 加書卷縮寫停用表（66 卷縮寫；豁免「但」，「俄」逐筆確認）；
    - 單字「但」必須通過共用的 `is_geo_context()`。
  - 新增 `scripts/entity_extraction/geo_rules.py`：把 `_is_geo_context` 從 cleanup_noise_entities.py 搬過來，NER 與 10.2 的斷言共用同一個函式。
  - `scripts/extract_entities.py:96-100`：傳入區段資訊；`--stage ner` 只重產 P/P/G，E/O/T 用凍結檔。
  - 新增 `scripts/validate_mentions.py`（Step 1 之後的硬閘門），檢查：
    - start_pos 落在書名區的筆數為 0；
    - 不得有以書名全稱為 canonical 的實體，也不得有黑名單中的非人名詞幹（民數、雅歌、列王、歷代、使徒、福音）；**不可**拿「書名詞幹」當閘門，否則會誤殺馬可、約翰、以賽亞等真名；
    - `text[start:end]==span` 100%；
    - (source, entity, start) 重複為 0；
    - 名稱帶空白為 0。
  - `scripts/import_neo4j.py:264-311`：MENTIONS 寫入 source_region、verse_id、source_granularity；位移一律相對於本文；匯入前依 start_pos 排序，讓首筆勝出可預期。
  - `scripts/cleanup_noise_entities.py`：「但」改為斷言模式（dry-run 必須 delete=0）；所有清理都經由編譯快照同步到 PG。
  - 保留：pericope、chunk、verse 三種 NER 輸入照舊（不做 M1(c)），以免 169 個長段失去 3,477 個 Pericope 錨點；「尼西米記」不改名。
  - 書名區中其實是真提及、只是型別錯的（加拉太、哈巴谷、俄巴底亞、歌羅西）：改用本文抽取，型別錯誤交給延後-A，不刪。
- **新增測試**：
  - `test_text_regions.py`（「馬可福音 第1章 … ：」之後才是本文；出埃及記的前綴不產生「埃及」）；
  - `test_ner_positions.py`（同一個字出現多次時位置各不相同；strip 後位移正確）；
  - `test_geo_rules.py`（以 output/backups 中「但」的 733 條刪除與 26 條保留做表格測試）；
  - `test_validate_mentions.py`。
- **管線順序變更**：1a(ner) → **validate_mentions（新閘門）** → 1c 編譯（1D）→ 3/5 …；6.05 的 provenance 閘門會自動把書名支撐的關係刪掉（約 293 筆 Step 6 關係，數字以 dry-run 為準）。
- **線上遷移**：與 1D 同一波，走 staging 重建後升版，PG 兩張表與 Qdrant `bible_entities_vN` 一起切換。回滾：三庫都還原（§3.7 R5）。描述：pericope 集合改變的實體在快照中標 stale，不再曝光（D5），等 2B 重生。
- **驗證門檻**：
  - R1 = 0（原 1,938）；
  - person:make 的 MENTIONS ≤10（原 103），馬太、路加同理；
  - 純書名實體（列王紀、彌迦書、民數、雅歌、尼西米記…）為 0；
  - R9：位置重複 0（原 4,131），span 相符 100%；
  - H4（P/P/G）= 0；H6 = 100%；
  - 「但」在 PG 與 Neo4j 的計數一致，非地理語境的「但」為 0；
  - **H10：Event MENTIONS 集合不變，D1 `--check` 結束碼 0**；
  - /api/v1/entity/person:make 抽 10 個 related_passages，10/10 的本文確實含「馬可」；
  - D3：預設組態 top-5 100% 相同。
- **工時**：20–28 h，另加 NER 牆鐘約 30 分鐘。
- **行為影響**：線上預設路徑與 registry 不變。/api/v1/entity 的 related_passages 會改變，mention_count 大幅下降（馬可 794 會降到個位數），所以 find_entity_by_name 的排序也會變（neo4j_db.py:68）。opt-in 的 graph_person、graph_place、entity_query、entity_path 都會改變。

#### 第 1D 批：實體與事件的決定性清理，以及三庫同步
- **涵蓋**：ID-3（編譯端）、ID-5、EV-01（provenance 階段 A）、EV-02、EV-09、EV-08（PG 同步）、yehehua、id_migration。
- **要改的腳本與函式**
  - 新增 `scripts/compile_entities.py`（K1c）：合併 NER 與凍結的 grounded 半邊，再依序套用：
    - 名稱正規化與同型孿生合併（用 MERGE 搬移 mentions 與關係，重算 mention_count）；
    - `_is_junk_title()` 套用到全部 E/O/T（Event 27、Theme 36、Object 25；「這是基督嗎？」列白名單；判斷要在「(無標題)」處理之後）；
    - 共用停用詞套用到所有 phase 的 Event（瑪拉、瑪撒、米利巴、耶和華曉諭、曉諭摩西直接刪除，不要併進 Place）；
    - 10.2 的 generic-event 規則；
    - `config/curated/entity_overrides.yaml`（yehehua 等，見 D9）；
    - aliases：從字典與 overrides 產生，被 ≥2 個實體擁有、或等於其他實體 canonical 的字形，改放 `ambiguous_aliases`（利未、掃羅、猶大、門徒、西門、流珥）；
    - 輸出 `output/kg/entities.jsonl`、`mentions.jsonl`、`id_migration.jsonl`（供 6.05、10.4/10.5 驗證與 Qdrant 使用）。
  - 新增 `scripts/entity_extraction/stoplists.py`：停用詞的單一來源，pericope_miner.py:59-63 與 cleanup_noise_entities.py:50-54 都改讀這裡。
  - `pericope_miner.py`：新增 `_is_junk_title`；候選建立時 strip。`pos_extractor.py:139-147`：先 strip 再過濾。`grounded_classifier.py:185`：以正規化後的鍵建立 by_name。這三處是讓下次重抽也乾淨。
  - `scripts/backfill_aliases.py`：退役，改成三庫一致性檢查（併入 check_identity）。
  - `scripts/import_neo4j.py:185-219`：把 extraction_method、title_derived 帶進 Neo4j；`embed_entities.py`：payload 帶 extraction_method，aliases 一律存成 list。
  - `scripts/import_postgres.py`：entities 與 entity_mentions 一律從編譯快照匯入，含 description（replay 中非 stale 的部分）與 aliases。這一步會讓 /api/v1/entity 開始回傳描述（D5）。
  - 白名單保護：11 個 ALIAS_INJECTIONS id 與 manual patches 中的 extracted Event，不得被任何規則刪除或改型。
- **新增測試**：
  - `test_compile_entities.py`（golden 小樣本；孿生合併；27/36/25 個 junk fixture 加上反例；停用詞）；
  - `test_alias_ambiguity.py`；
  - check_identity 在 staging 上的整合測試。
- **管線順序變更**：Step 1 → **K1c 編譯（新）** → validate_mentions → Step 3（PG 的 entities 與 mentions）→ Step 5 → 6.05 → 6.1 → 7(replay) → 8 → 9 → 10.4 → 10.5 → 10.6。10.1 從鏈中移除；10.2 只剩斷言。
- **線上遷移**：與 1C 同一波，§3.7 R0–R5。約 180 個空白 id 改名或合併後，舊 id 會回 404（沒有 curated 引用，評估檔也沒有引用）；redirect 留到延後-A（D8）。
- **驗證門檻**：
  - H4 = 0（原 180）；同 (label, trim(name)) 有多個節點的情形為 0；
  - R8 = 0；書卷縮寫實體 0；
  - Event 名稱與停用詞、與字典 P/P/G 名稱的交集都是 0（白名單除外）；
  - R10 = 0；
  - H5：三庫的 id、type、canonical、aliases、description 都是 0 差，Qdrant aliases 100% 為 list（原字串 9,093 筆）；
  - Event 的 extraction_method 為 null 的數量 0（原 1,694）；
  - find_entity_by_name('利未') 的第 1 名是 person:liwei；
  - H10 與 D1 通過。
- **工時**：20–28 h。
- **行為影響**：/api/v1/entity 開始回傳人物、地點、群體的描述與修正後的 aliases；舊的空白 id 回 404；find_entity_by_name 的排序改變。registry 與預設路徑不變。

### 第 2 批：中等工作量（含小量 LLM）

#### 第 2A 批：Step 6 可續跑化、R4 快取、定向重判、校準
- **涵蓋**：REL-10、REL-07（程式部分）、REL-03（重判）、REL-01（補判 772 個 rule-hit 配對）、REL-06（取代 10.3）、REL-04（校準）、G-1（chunk 上捲）、G-4、M6（Step 6 部分）。
- **要改的腳本與函式**
  - `extract_relations.py`：
    - 判定完成才寫 checkpoint（修 :117-128、171-192），每批 append LLM 三元組；
    - 輸出分檔 `relations_{prior,rule,llm,unclassified}.jsonl` 並帶 run_id；
    - `--resume` 改為合併既有結果；已完成的 run 若沒有 `--force` 就拒絕寫入；
    - `--no-llm` 不得覆寫 unclassified；
    - `--pericope-ids` 支援多個 id，搭配 `RE_OUTPUT_PATH`、`RE_UNCLASSIFIED_PATH`、`RE_CHECKPOINT_PATH` 導到另外的檔案，跑完再合併；
    - :193-203 改成先計算 classified_pair_keys，再做 prior 過濾；
    - unclassified 加 `status` 欄位（none、unjudged、failed、context_missing）。
  - `pair_miner.py`：改讀編譯後的 mentions，並把 chunk 層的提及上捲到父 pericope（G-1）；grounding 改讀 pericopes.jsonl；截斷改成同節共現優先（:115、147-150）。
  - `grounded_re_classifier.py`：同一批只放相同 context 的配對，以整段 pericope 當 context（中位數 388 字、最長 3,544 字）；斷言每一對的端點名稱都出現在 context 中；evidence 必須非空、是 context 的子字串、且含端點（修 :124、238、267）；prompt 加 `subject` 欄位決定方向（REL-03）。
  - 新增 `output/frozen/re_cache.jsonl`：以 (pair_key, grounding_sha) 為鍵，記錄 status、model、temperature。以現有 relations.jsonl 與 unclassified 為種子，manifest 註明 NONE 與失敗分不出來、去重時有結果被吃掉。
  - 字面端點閘門：非 Event 的端點名稱必須以字面出現在段落中，才送進 R4。
  - 新增 `config/relations/calibration.yaml`：以 (source, family) 分層抽樣，每層 n≥30，約 200 條；6.05 依此覆寫 confidence（見 D4）。
- **LLM 工作**（約 1.5 對／秒，屬推論）：
  - (a) 772 個從未判定的 rule-hit 配對；
  - (b) 75 條方向未驗證的同型邊；
  - (c) 取代 10.3：Event–Person 5,946 對與 Event–Place 3,616 對，經過閘門後會再少一些（約 1.5–2 h）；
  - (d) chunk 上捲後的新配對，先以 dry-run 計數，超過約 2 萬對就移到延後-C。
  - 先確認 5 月實際用的模型（D12）。
- **新增測試**：
  - `test_extract_relations_resume.py`：在 fixture 上中途 kill，再 resume，結果要等於不中斷的跑法；
  - `test_re_batching.py`：同批 context 相同，端點必在其中；
  - `test_pair_miner_rollup.py`；
  - 6.05 加上校準後的冪等測試。
- **管線順序變更**：K6 改成離線挖配對，加上 R4 快取（缺快取的配對以 `--defer` 標 pending，不產生邊）→ 6.05 → 6.1。
- **線上遷移**：照 §3.7 R0–R5；只動 Neo4j 的語意邊。
- **驗證門檻**：
  - 送進 LLM 的配對中，context 缺端點的比例為 0；
  - unclassified 中 unjudged 加 failed ≤1%；
  - 抽樣精確率：LLM 親屬 ≥0.9；非親屬 ≥0.7；Event 參與與地點 ≥0.85（n≥50）；
  - 校準後各桶精確率單調，ECE ≤0.10；
  - 回報事件層覆蓋率的新值，並與 34.4%/31.8%、84.0%/75.5% 並列；
  - H3、H9、R6 維持通過；
  - entity_path A/B（§6.2）。
- **工時**：40–56 h，另加 LLM 牆鐘 3–8 h。
- **行為影響**：只影響 opt-in entity_path；預設路徑與 registry 不變。論文中「77,953 = LLM NONE」「checkpointed and resumable」「evidence 驗證否則拒絕」的敘述要更正。

#### 第 2B 批：RCUV 拼法、權威長名詞表、子字串汙染、描述重生
- **涵蓋**：M2、M4/ID-6、ID-4（少數已確認的 relabel）、EV-08（重生）。
- **要改的腳本與函式**
  - 新增 `config/lexicon/rcuv_proper_names.txt`（git 追蹤，人工審過，**不可**由 CKIP 產物自動建立），涵蓋已知的陷阱：撒馬利亞、以利亞撒、以利亞敬、以利亞實、迦勒底、亞拿突、亞拿尼亞、哈拿尼、尼布撒拉旦、撒拉鐵、亞伯尼歌、西西拉、腓力斯、撒但、約拿達、撒迦利亞、烏利亞…；另列「非名」詞，例如閃電、含怒、含笑。
  - `ner_extractor.py:167-205`：字典命中時，左右擴展後若能組成專名表中的長名，就不採用；`_merge_results`（:259-280）改成：權威長名 span 優先，型別取自專名表，不取 CKIP 的判斷。
  - `entity_dict.py`：canonical 改用 RCUV 拼法；舊拼法移到 `config/lexicon/query_aliases.yaml`，由編譯 aliases 與後端查詢共用；間隔號統一成 U+2027（person:bo‧shan、object:badan‧yalan 的 id 經 id_migration 處理）。
  - 字典拆分（D7）：抽取字典與 `backend/utils/entity_dicts.py` 的路由詞表分開，或保持共用並跑 500 題路由回歸。
  - `config/relations/biblical_priors.yaml`：改用 RCUV 拼法（流便改呂便等）。
  - `entity_overrides.yaml`：已驗證的 relabel，例如 object:samaliya 改 Place（新 id place:samaliya，經 id_migration）、戶篩、示巴女王、亞拿尼亞改 Person，泰爾與伯‧善的 Person/Place 重複合併成 Place。
  - 定向 R4：用 2A 的工具，針對新實體所在的約 100–300 段。
  - K7 重生：描述快取沒命中的實體（1C、1D、2B 中輸入改變的，加上已知事實錯誤的條目），desc_generator 新增 `--entity-ids`。
- **新增測試**：
  - `test_entity_dict_rcuv.py`：每個比對字形在 RCUV 本文至少出現 1 次；白名單包含括號消歧鍵與現代名（死海、地中海、客西馬尼園、巴別塔）；
  - `test_ner_substring_traps.py`：圍攻撒馬利亞、祭司以利亞撒、希勒家的兒子以利亞敬、以利亞實的兒子、像閃電、含怒、西西拉、腓力斯、但我告訴你們。
- **管線順序變更**：K1a 讀專名表；K7 改為只對快取沒命中的實體呼叫 LLM。
- **線上遷移**：照 §3.7。若字典仍共用，image 必須一起重建並一起回滾。
- **驗證門檻**：
  - R2 探針全過；
  - 分層抽 200 條 MENTIONS（必含以利亞、馬利亞、利亞、以利、迦勒），精確率 95% CI 下界 ≥0.90；
  - person:maliya 約 31–33 條（原 126）；place:samaliya ≥100 條；
  - 字典零命中字形只剩白名單；Object 中 canonical 屬於字典的實體為 0；同名同時是 Person 與 Place 的為 0；
  - priors 因拼法而解析不到的條目為 0；
  - D4：若字典共用，500 題路由分布落在雜訊地板內；
  - D1 `--check` 結束碼 0。
- **工時**：32–48 h，另加 LLM 1–3 h。
- **行為影響**：**若字典共用，backend 路由（R3/R6）會改變，線上預設也受影響**。/api 會新增 place:samaliya 等，object:samaliya 等 id 會改變。

#### 第 2C 批：curated 事件的單一真相來源，以及 registry 錨點修正
- **涵蓋**：EV-05、EV-04（curated 的 2 個錨點）、EV-07。
- **要改的腳本與函式**
  - 新增 `config/curated/events.yaml`。事件自足：每筆有 slug、凍結的字面 entity_id、canonical_name、aliases、description、有序的 anchors，以及 trigger_anchors（每個觸發詞自己的首錨）。合併 ALIAS_INJECTIONS（11）、NEW_EVENTS（18），以及 manual patches 的 5 個 Event 節點。抽取節點只做可選的合併，綁定目標不存在時就建立 curated 節點，不會斷鏈。
  - `backfill_head_events.py`、`backfill_manual_patches.py` 改讀 YAML。
  - `export_event_registry.py`：由 YAML 產生 registry；錨點以 pericopes.jsonl 與快照驗證；新增 `--out`、`--diff`。
  - 若要支援每個觸發詞各自的首錨，registry 升到 schema v2，`backend/utils/retrieval/event_registry.py` 的 loader 與 `select_aux_anchors`（:89-103）一併更新。
  - 錨點修正以經文本身為依據，不看 GT：
    - 墮落：首錨改 gen:3:0；
    - 掃羅受膏：補 1sa:10:0 並設為首錨；
    - 八福：改 mat:5:1；
    - 所羅門獻殿：1ki:8:x、2ch:5:1、2ch:6:1、2ch:7:0；
    - 十災：補 exo:8:1、9:0、9:1；
    - 第一次宣教旅程：補 act:14:1；
    - 王國分裂：補 2ch:10:0；
    - 釘十字架：補 mrk:15:4、luk:23:4、jhn:19:2；
    - 新天新地：補 rev:22:0；
    - 重建城牆：補 neh:4:0、6:1；
    - 巴比倫之囚：補 2ki:24:1、25:0、25:1；
    - 受難週、大使命、歌利亞、曠野漂流：補漏段；
    - 合併兩個保羅歸主事件（D11）。
- **新增測試**：
  - `test_events_yaml.py`：每個錨點都存在；每個 (觸發詞, 首錨) 的節範圍都涵蓋該事件，附人工審閱表；
  - backend 的 `test_event_registry.py` 隨 schema 更新。
- **管線順序變更**：10.4、10.5 改由 YAML 驅動；export 放在 10.6 之後；registry 有 diff 時必須人工核可才能 commit。
- **線上遷移**：
  1. `git diff` registry 並審閱；
  2. 用 `evaluation/experiments/2026-10-03_event_registry/run_ab.sh` 驗證；
  3. 500 題答案端評估；
  4. commit 後 `docker compose up -d --build backend`（registry 是 Dockerfile:31 COPY 進去的，只 restart 會跑舊檔）。
  - 回滾：git revert registry，重建 image。
- **驗證門檻**：
  - 同路由題的 top-5 與 graph-off 逐位相同 100%（基準 492/492）；
  - touched ≤35（基準 23）；
  - 與 k 對齊的 dense@6 相比，vrec 與 anchor 都沒有任何題變差；
  - 樣本內題（TOPIC_029、GENERAL_076）另外報告；所羅門獻殿另寫 ≥5 題 GT 外的 held-out 題；
  - 答案端：coverage 為主要指標，faithfulness strict ≥0.97 守門，|Δcoverage| 與雜訊地板 0.060 比較。
- **工時**：24–32 h（不含評估的牆鐘）。
- **行為影響**：**有：event_registry.json 改變，也就是線上預設附加的段落改變。** 這是本計畫中唯一刻意改變線上預設 QA 的項目。墮落、掃羅受膏、八福在 500 題 GT 中出現 0 次；所羅門獻殿 2 題，屬樣本內。

#### 第 2D 批：markdown 平行經文解析器與 TSK 錨點
- **涵蓋**：XREF-5、XREF-6（可選）。
- **要改的腳本與函式**
  - `bible_chunking/markdown_parser.py:35-72` 的 CrossRefParser 重寫成 `parse(ref_text, own_book_id)`：
    - 在「；」與「，」之間沿用前一段的書卷與章；
    - 支援「A‧B－C‧D」跨章範圍；
    - 支援「詩18」這類只有章號的引用；
    - 沒寫書卷縮寫時預設為本卷；
    - 同卷且範圍包含本段的，標為 section_range，不產生邊。
  - :216-229 先判斷細拉，再判斷交叉引用。
  - `bible_chunking/models.py:35-44` 加 `chapter_end`。
  - `process_bible.py:325-342`：依範圍展開，每觸及一段出一條邊（設上限並記錄），`book_id` 為空時報錯。
  - `import_tsk_crossrefs.py`：存前 5 個 anchors，跨章 to-range 完整展開。
- **新增測試**：以 43 筆漏解析案例、22 筆跨章或逗號案例當 fixture；約伯記的 section_range 為反例。
- **管線順序變更**：Step 0 輸出會改到 pericopes.jsonl 的 cross_references 欄位，所以 PG 的 pericopes 要重匯（被動欄位，正文不變）。embedding_queue 的 sha 閘門必須不變，因為 cross_references 不進 embedding 文字。
- **線上遷移**：照 §3.7，另加 PG pericopes 表的備份與換表。
- **驗證門檻**：
  - 非細拉、非 section_range 卻解析不到的引用為 0（原 39）；
  - verse_end<verse_start 為 0（原 6）；
  - 跨段範圍沒展開的為 0（原 36）；
  - curated markdown 配對數 891±5；
  - anchors 100% 落在兩端範圍內；
  - EVENT_067 的注入槽比對；kg_xref A/B。
- **工時**：12–16 h。
- **行為影響**：只影響 opt-in xref（curated 鄰居增加、扇出變大）；預設路徑不變。

### 延後（需要重跑 LLM，或身分層大改）

#### 延後-A：身分層重建
- **涵蓋**：ID-1、ID-2、ID-4（其餘部分）、ID-5（其餘部分）、ID-7（註冊表與 redirect）、M3（猶大與以法蓮）、G-5。
- **內容**：
  - 新增 `scripts/entity_extraction/identity.py`：normalize_surface、IdentityRegistry、`resolve()`（cues 依「限定語＞書卷章範圍」的優先序，必要時 abstain）、`mint_entity_id()`（漢字 canonical 加全形括號限定語）。
  - `config/curated/entity_registry.jsonl` 以 live 的 9,124 筆種子化，這一步對所有消費者都是 no-op；另建 `identity_ops.jsonl`。
  - 新增 Step 1.5 `resolve_identities.py`：同時改寫 entities、mentions、relations、relations_unclassified，以及 10.2 的輸入。
  - 人工審閱 380 種字形、8 個歧義名（含 act:13:2 屬掃羅王、1ch:26:0 的「西門」是西邊的門、希律黨），以及 285 個 Object 孿生與 15 個 Event 孿生（逐案決定合併方向）。
  - NER 的 `_all_entities` 改為 name→Set[type]，以上下文判定猶大、以法蓮、但是 Person 還是 Place。
  - canonical 要唯一，或 priors 改用 id 參照。
  - 匯出 `backend/data/entity_redirects.json`；routers/entity.py 對合併的 id 回 308，對拆分的 id 回 300 並附 split_into。
  - 重算 mention_count；受影響的實體約 300–500 個要重生 K7；新配對送 R4。
- **驗證**：
  - R3 從 169 降到 0；
  - 金標集 ≥200 條 mention，指派精確率 ≥0.95，abstain ≤0.25；
  - 字典條目中永不產生節點的從 7 降到 0；
  - fixtures：路得對 Ruth、米甲／米迦／彌迦／密迦是 4 個 id、腓力／腓利是 2 個 id；
  - 三庫一致；
  - 重灌鏈的結果與快照 diff 為 0（只在重灌鏈上驗證，因為 LLM 步驟會漂移）；
  - D1、D4。
- **工時**：64–100 h（工程 3–5 人日，標註 2–3 人日，金標集 1–2 人日），另加 LLM。
- **行為影響**：**有**：/api/v1/entity 的 id 會拆分並重導（backend router 要改）；若字典改成註冊表，路由會變；find_entity_by_name 的結果會變。Event id 凍結，registry 預期不變。

#### 延後-B：grounded 半邊（E/O/T）重抽
- **涵蓋**：EV-01（階段 B）、EV-03、EV-04（parser）、M5（Phase 2 去截斷）、M3（POS 閘門）。
- **內容**：
  - 判決強制生效：null、evidence 不符、型別越界、LLM 漏回的候選都算 rejected；error 讓建置失敗。
  - 重新設計判決 prompt，改以整段經文當 context。
  - 建立 `config/curated/event_title_verdicts.jsonl`（約 2,400 個標題；LLM 判決加人工抽查），之後重建都先查這個檔。
  - 字尾型別規則只用在 4 字以內的名詞；刪掉關鍵字「約」；王名規則限定為「王＋字典人名」整串相符。
  - `bible_md_parser.py:190-197、221-226` 建立隱含的 (無標題) 段，再做續段繼承。
  - Phase 2 去截斷只做 O/T，並建立 Phase 4 的名稱快取。
  - 下載 CKIP POS 模型（本機沒有快取，依目前頻寬約需數小時）。
- **驗證**：
  - 保留下來的 Event 抽 100 個，「具體敘事事件」的比例 ≥0.90；
  - 用判決檔重跑兩次，Event 集合 diff 為 0；
  - Object/Theme 中 mention_count>10 但 MENTIONS≤10 的為 0；
  - D1（curated 同 id 的事件若多出錨點，視為 registry 變更，要做 A/B）。
- **工時**：40–60 h，另加 LLM 數小時。
- **行為影響**：可能影響 registry，必須跑 --check；/api 與 entity_query 的型別會變。

#### 延後-C：Step 6 全量重跑（找回召回）
- 時機：延後-A、延後-B 與 2B 都上線之後。
- 用修好的批次、截斷、chunk 上捲與快取，全量重跑 R4（約 85–100k 對，10–20 h LLM）。之後全面淘汰舊的 LLM 邊。
- **工時**：8–16 h 人力，另加 LLM 牆鐘 10–20 h。只影響 opt-in entity_path。

#### 不做（YAGNI，或已確認不需要）
- EV-10 事件時間線：沒有消費者，有需求時再建 curated 檔。
- M1(c) 拿掉 verse NER：有風險，收益只是加速。
- M1(d) 書名「尼西米記」改名：本文限定的 NER 已經不會看到書名，改名卻會牽動後端、評估與 Qdrant。

---

## 5. 對 backend 與 event_registry.json 的影響

| 批次 | backend 程式碼 | backend 讀到的資料改變 | event_registry.json | 線上預設 QA |
|---|---|---|---|---|
| 0 | 不變 | 不變（不升版） | 不變；EV-06 防止重建時從 33 個掉到 31 個 | 不變 |
| 1A | 不變 | Neo4j 語意邊（opt-in entity_path） | 不變 | 不變（D3 閘門） |
| 1B | **改**：neo4j_db.py、cross_ref_retriever.py；需重建 image | CROSS_REFERENCES（opt-in xref） | 不變 | 不變 |
| 1C | 不變 | P/P/G MENTIONS、Qdrant entities（/api 的 related_passages、mention_count 排序；opt-in graph_*） | 不變（H10 與 D1 閘門） | 不變 |
| 1D | 不變 | PG 的描述與 aliases（/api 開始顯示描述）；部分 id 回 404 | 不變 | 不變 |
| 2A | 不變 | 語意邊（opt-in entity_path） | 不變 | 不變 |
| 2B | 若字典共用：**路由改變**；需重建 image | 新實體與 id 變更 | 預期不變（--check） | **可能改變**（路由）→ 跑 500 題 |
| 2C | 若 registry 升 schema v2：loader 要改 | registry | **改變** | **改變**（R4/R5 路由題的附加段落） |
| 2D | 不變 | xref（opt-in）；PG 被動欄位 | 不變 | 不變 |
| 延後-A | **改**：entity router 加 redirect；字典改註冊表 | 大量 | 預期不變（Event id 凍結） | 若字典共用則改變 |
| 延後-B | 不變 | E/O/T | 可能改變 | 可能改變 |
| 延後-C | 不變 | 語意邊 | 不變 | 不變 |

**誠實說明**
- 線上預設 `graph_strategies=["event_registry"]` 讀的是燒進 image 的靜態 `backend/data/event_registry.json`，不讀 Neo4j。只有在重新匯出 registry 並重建 image（2C），或者後端路由所用的字典改變（2B／延後-A）時，資料層的修正才會碰到線上 QA。
- 第 0、1 批對線上預設 QA 的預期影響是**恰好為 0**，而且這是閘門（D3），不是收穫。
- 真正的收穫在別處：
  1. /api/v1/entity 直接對外的正確性：書名假邊、空描述、錯誤 alias、同名混淆；
  2. 可由請求開啟的圖譜策略：錯邊、孤兒邊、999 哨兵、錯位錨點；
  3. 論文與文件的正確性；
  4. 重建安全：描述不會再消失，registry 不會靜默退化，三庫不會再分歧。
- 即使在 opt-in 策略上，也不應預設會有檢索增益。2026-10 的圖譜價值診斷顯示瓶頸在實體連結與挑選層；41 題停損實驗判定 STOP（oracle 僅 +0.03～0.06）。第 1 批修掉的是「錯」，不保證「有用」，這要靠 §6.2 的 A/B 來量。

---

## 6. 怎麼量化「修了有沒有用」

### 6.1 KG 品質指標（基準 → 目標）
| 指標 | 基準（live） | 目標 | 批次 |
|---|---|---|---|
| 書名區 MENTIONS／純假邊 | 1,938／1,745 | 0 | 1C |
| 子字串汙染（下界） | 548；馬利亞 93–95/126 | 探針全過；MENTIONS 精確率 CI 下界 ≥0.90 | 2B |
| 不受支撐的衍生邊 | 374 | 0 | 1A |
| 親屬邊精確率（分層加權） | 約 0.26（規則 3/22、反推 0/9、LLM 16/16） | 規則來源 Wilson 下界 ≥0.85，LLM ≥0.9 | 1A、2A |
| FATHER_OF 雙向矛盾、女性 head、函數性違反 | 25／≥40／53.6% | 0／0／≤5% | 1A |
| 共現回填邊（精確率約 0.2） | 9,060 | 0（以定向 R4 取代，精確率 ≥0.85） | 1A、2A |
| supplementary 錯位／999 誤判／被吞的 TSK 證據 | 59／3／856 | 0／0／0 | 1B |
| 名稱帶空白、垃圾 E/O/T | 180／88 | 0／0 | 1C、1D |
| 三庫一致（描述、aliases） | 不符 3,045／字串 9,093 | 0／0 | 1D |
| 同音誤合、跨型別同名 | 169（268）／908 | 0／只剩白名單 | 延後-A |
| 單段 Event 比例 | 1,535/1,714 | 回報 | 延後-B |

人工抽樣審查表一律固定 seed，保存標註與 sha，每批升版時更新。

### 6.2 檢索 A/B（opt-in 策略開啟時）
- **對象**：每個受影響的策略 S，包括 entity_path、graph_person、graph_place、entity_query、graph（all）、cross_ref_expand／cross_reference，各自以 `graph_strategies=[S]` 比較 prod 與 staging。
- **工具與指標**：
  - `quick_retrieval_eval`（100 題，約 15 分鐘）先跑；有差異再跑 500 題；
  - 檢索主指標用 verse_recall_at_k，並做 k 對齊；
  - 報告逐題配對差異、touched 題數、勝負題數、95% CI；
  - 樣本內（設計時看過的 GT）與 held-out 分開報告。
- **門檻**：
  - 1A 的 entity_path 要求非劣性（Δvrec ≥ −0.005）；其他策略只報告，不設必勝門檻；
  - xref 另跑 kg_xref 68 題的 S1：注入槽的金段落率（現約 3%）、「靠 xref 補到金段落」（現 0/18）；
  - 檢索結果有實質差異時才跑答案端：coverage 為主，faithfulness strict ≥0.97 守門，|Δcoverage| 與雜訊地板 0.060 比較。
- Round 3 的 graph 組態數字是在舊資料上算出來的，重跑時要註明資料版本。

### 6.3 預設路徑的非劣性
- registry 與字典都不變時（第 0、1 批、2A、2D）：預設組態 500 題的 sources 與 prompt 逐位相同，這是硬閘門。
- 會改變 registry 或字典時（2C、2B）：跑 run_ab.sh、500 題答案端評估，以及路由分布回歸。

### 6.4 /api/v1/entity 抽查（每批升版後）
- person:make 的 related_passages 10/10 確實含「馬可」（1C）。
- find_entity_by_name('利未') 的第 1 名是 person:liwei（1D）。
- 人物、地點、群體有描述（1D，依 D5）。
- place:samaliya 存在（2B）。
- person:lude 的 canonical 是「路得」（延後-A）。

### 6.5 文件與論文要隨之更新的地方
- sec3_kg.tex:104-185：772、64、5,370、752、「evidence 驗證否則拒絕」、「confidence-filterable」、「77,953 = LLM NONE」、「checkpointed and resumable」。
- sec6_experiments.tex:168、312-316：+5,641/+3,419、84.0%/75.5%。
- sec7_discussion.tex:223、319。
- build_database.md:67、69、96-97、327、388、400-404、426、440、443。
- evaluation/README.md:226。
- P0 紀錄。
- 重建前先打 run-of-record 的 git tag。

---

## 7. 需要你決定的事項

| # | 決策 | 選項 | 建議 |
|---|---|---|---|
| D1 | 整合策略 | (a) staging 全量重建後升版；(b) 線上增量 Cypher 補丁 | (a)。可重現性已驗證，線上補丁有多個已知陷阱，而且 (b) 等於再寫一批 10.x |
| D2 | 10.3 共現回填 | (a) 退場，事件層覆蓋率暫時回到 34.4%/31.8%，2A 再以定向 R4 取代；(b) 保留但閘門化，標 source='cooccurrence'，entity_path 排除這類邊（要改 backend） | (a)。精確率約 0.2，唯一消費者又是 opt-in；論文 sec6 的數字需要改寫 |
| D3 | 親屬本體與 R5 | (a) 錨定規則只在句型確定性別時輸出有性別的關係，R5 預設關閉；(b) 引入 PARENT_OF/CHILD_OF | (a)，不改本體；R5 關閉 |
| D4 | confidence | (a) 2A 用約 200 條標註做校準；(b) 從邊上移除 | (a)，若沒有標註人力就選 (b) |
| D5 | 描述曝光 | 是否把現有 3,045 條描述固化進 git（附品質旗標）並同步到 PG 讓 /api 顯示；輸入改變的實體，描述先隱藏還是沿用 | 固化並同步；輸入改變者先隱藏（不曝光被汙染的內容）；已知事實錯誤的條目（例如拉結）標 bad，2B 重生 |
| D6 | PG entity_mentions（backend 沒有消費者） | 保留並同步，或停用 | 保留並由快照同步（成本低），再觀察 |
| D7 | 字典拆分 | (a) 抽取字典與後端路由詞表分開；(b) 共用，每次改字典都跑 500 題路由回歸 | (a)，把線上路由隔離在 KG 修正之外 |
| D8 | id 規則與 redirect | 新 id 用漢字 canonical 加全形括號限定語；既有 id 凍結；第 1 批約 180 個空白 id 改名後暫時回 404，延後-A 再補 redirect | 同意 |
| D9 | group:yehehua | 保留 id（id 不透明，列入白名單）或改成 person:yehehua 並 redirect | 保留 id |
| D10 | XREF-2 的釋經判斷 | rev:19:1→psa:118 刪除？rev:19:2→dan:7 改為 dan:2:47 或 deu:10:17，或降級成 TSK 邊？ | 第一筆刪除；第二筆改成有 TSK 支撐的目標 |
| D11 | registry 錨點 | 所羅門獻殿（樣本內 2 題）怎麼做 held-out；合併兩個保羅歸主事件時 act:9:1 是否保留 | 用 held-out 題驗證；在 slots=1 下保留 act:9:1 不改變行為 |
| D12 | LLM 模型 | 5 月 R4 實際用的是 gemma3:4b 還是 gemma4:31b？新的 R4/K7 呼叫用哪一個 | 先查 Ollama log 與 git 歷史；若查不清，2A 的 R4 全部改用同一個模型 |
| D13 | 工作樹中被刪除的評估檔（git status 顯示 D） | 還原或封存 | 在第 0 批建立基準前決定；前後比較需要這些憑證 |
| D14 | 論文與 run-of-record | 每批要更新哪些數字；何時打 tag | 第 0 批就打 tag；每批升版時同步更新文件 |
| D15 | 升版方式 | Neo4j dump/load（停機約 1 分鐘），或 backend 改指 staging URI | dump/load；流程照 bak/README |
| D16 | 延後-C 全量重跑 Step 6 | 要不要做、何時做（10–20 h LLM） | 等延後-A、B 與 2B 完成後再評估 |
| D17 | 標題區提及 | 現有 382 條只出現在標題的邊，要保留嗎 | 保留，並標 source_region='title'，讓下游自行選擇 |

---

## 8. 風險、推論與尚待查證

**風險**
1. **registry 漂移**：錨點取自所有 MENTIONS。對策是 H10 加 D1 閘門，以及白名單（11 個 ALIAS_INJECTIONS 與 extracted 的 curated Event）。
2. **字典與路由耦合**：見 D7。
3. **staging 與升版**：Neo4j community 只有單一資料庫（推論），必須另起容器；升版約停機 1 分鐘。
4. **R4 快取的語意缺口**：NONE 與失敗分不出來，去重時有結果被吃掉。在 manifest 註明，新快取逐對記錄狀態。
5. **模型混用**：見 D12。
6. **親屬邊數量會大幅下降**（約 1,571 降到 300 以下）。這是刻意的；W 警示要事先登記，論文要同步更新。
7. **範圍蔓延**：一個項目一個 commit，各自附探針；不要把多個缺陷綁進同一次升版的同一個 commit。
8. **主機頻寬**：backend 重建要走 uv 快取；CKIP POS 模型下載需數小時（延後-B）。
9. **GPU 共用**：增量 R4 與 backend 的 Ollama 共用 GPU，長時間的 LLM 工作要避開評估時段。

**推論（尚未直接重現）**
- 所有工時、R4 吞吐（約 1.5 對／秒）、Neo4j 匯入與 TSK 匯入的耗時。第 0 批的第一次 staging 重建要實測，並寫回 build_database.md。
- EV-03 中 Theme 有多少比例其實是敘事事件（只抽看過）；EV-07 的實際斷鏈行為（讀碼推得）。
- XREF-2 後兩筆的釋經判斷。
- Qdrant 中 aliases 為字串的成因：推論是早期以 json.dumps 寫入。
- pypinyin 是否已在 uv.lock 釘版：未查。
- 5 月 Step 6 實際使用的程式版本：relation_extraction 的 commit 時間晚於 relations.jsonl，無法查證。

**備註**：scratchpad 位於 /tmp，可能被清除。若要長期保存，建議把附錄 A 的關鍵腳本與輸出複製到 `docs/records/2026-10-04_kg_fix/`。

---

## 附錄 A：證據與分析腳本位置

> **歸檔（2026-10-04）**：分析腳本與小型輸出已複製到 `docs/records/2026-10-04_kg_fix/`，保留下方列出的子目錄結構。完整的 95 MB scratchpad（含 pkl 與大型 json）打包成 `bak/20261004_kgfix_evidence/kgfix_scratchpad.tgz`（bak/ 已被 gitignore），sha256 是 `1ad94503…7c55`。下方的 /tmp 路徑只代表原始執行時的位置。
根目錄：`/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad/kgfix/`
- `mentions/`：a1_regions.py、a2_edges.py（書名區 1,938）、a3_substr.py、a4_contam.py、a6_rel_impact.py
- `identity/`：homophone.py、homophone.json（268 個 id 的字形分布）、ro.py、qdrant_entities.json、pg_entities.tsv
- `relations/`：dump.py、edges.json（15,926 條語意邊快照）、sample*.py、verdicts.json（118 條人工判讀）、sim.py、proto_kin2.py（錨定規則原型）
- `xref/`：supp.py、supp_migration_plan.json（注意：缺 keep 欄位，不可直接拿來執行）、md.py、md_fix.py、tsk.py、rows.json
- `events/`：a2_anchors.py、a3_desc.py、a6_simulate_rebuild.py（重建前的預檢工具）、live_events.json、junk_ids.json
- `architect/`：tsk_shadow.py、pair_sim.py、pb_out/（Step 0 逐位元比對）、ner_sample/（NER 600 筆重現與計時）
- 驗證者：`verifier_mentions/`、`verifier_identity/`、`relverify/`（exactsim.py、cap.py、resumecheck.py、schemaviol.py 等）
