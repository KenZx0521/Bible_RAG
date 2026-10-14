# ho_tools：§7 HO 盲出題工具

規格是上一層的 `prereg.md` §7（另見 §5、§10）。正式出題（約 120 題）要等附錄 A 之後、而且 V1 沒有停損才開始（`run_gen.py`、`run_audit.py` 對非 pilot 根目錄會檢查守門與 `v1_old31.json` 的 `stop: false`）；在那之前只准用試跑根目錄 `ho/pilot/`，結果一律丟棄。

## 根目錄
- 正式：store `reports/graph_gd_20261014/ho/`；試跑：`ho/pilot/`（題號 `H_KIN_P01`…，freeze 拒收）。
- 每個根目錄有 `state.json`（草稿依提交順序、稽核、修正、Kay 抽查、各次執行的 meta）、`transcripts/<run>.jsonl`（stream-json transcript：prompt、agent 文字、API 端 thinking 摘要、工具呼叫與結果、structured output；不含原始 thinking，也不含 Claude Code 自行注入的環境區塊與帳號 email）、`prompts/<run>.json`（實際送出的 system 與 user prompt）、`bin/`（`bt`、`bt-guard` 包裝）、`mech/`（機械稽核報告）、`kay/`（抽查頁）。

## 檔案
| 檔 | 用途 |
|---|---|
| `gen_prompt.md`、`audit_prompt.md` | 要在附錄 A 凍結的出題與稽核 prompt（`<!-- section:… -->` 分段，`{{…}}` 佔位） |
| `bt.py`（`_ho_text.py`） | agent 唯一的工具：v、grep、pid、books、old。`old 正規式` 只搜 GT v2 與 OLD31；`old --gold` 對 NEW82、OLD31、HO 草稿只報段 id 與來源；不像經節鍵的參數只印「第 n 個參數」，不回顯 |
| `bt_guard.py` | PreToolUse hook：只放行單一個 `bt …` 與 StructuredOutput；引號外的 `* ? [ ] { } ~` 一律拒絕（否則 shell 展開成檔名，bt 等於 ls） |
| `banned.py` | 禁用字（§7）、目的字、專案記憶特徵字的機械檢查；`banned.py gen_prompt.md audit_prompt.md` |
| `run_gen.py`、`run_audit.py`（`_ho_claude.py`、`_ho_runs.py`、`_ho_prompts.py`、`_ho_state.py`） | headless `claude -p` 執行器、生成順序與配額、提交 |
| `mech_check.py`（`_ho_transcript.py`） | 題目規則（另有 warn：core 互為子字串）與 transcript 規則：t_init、t_tool、t_path（絕對路徑；指令與工具結果裏的相對路徑）、t_memory、t_banned（只在 system prompt）是 error；agent 自己寫的禁用字是 t_banned_agent（warn） |
| `annotate.py`、`build_page.py`、`page_template.html` | 經文標註與審題頁（只產生檔案） |
| `sample_kay.py` | Kay 抽查：`random.Random(20261014).sample(sorted(ids), 15)`，套用決定 |
| `freeze.py` | 寫 `heldout_ho.json` 與附錄 B 清單（`heldout_ho_freeze.json`） |

## agent 的環境（盲化）
cwd `/srv`（空、唯讀、在 repo 外；SDK 會把 cwd 寫進 agent 的環境資訊，store 路徑會讓 agent 看到 graph、rag）；`--thinking-display summarized`（--help 未列的選項；不加則 thinking 全是空字串，`showThinkingSummaries` 設定無效，見 store ho/probe/README.txt）；`--system-prompt` 取代預設提示；`--tools Bash`、`--allowedTools "Bash(bt *)"`、`--disallowedTools Read Edit Write …`、`--permission-mode dontAsk`；Claude Code 仍會自動放行唯讀指令（ls、cat、`bt x; ls`），所以另以 `--settings` 掛 `bt-guard` hook；`--setting-sources local`、`--strict-mcp-config`、`--disable-slash-commands`、`--no-session-persistence`（不用 `--safe-mode`：它會連 hook 一起停用）；移除父行程的 `CLAUDE*` 環境變數；`--model claude-opus-5-5 --effort xhigh`；`claude --version` 必須是 2.1.299（附錄 A 釘版，不符就拒跑）。

## 正式流程（附錄 A 之後、V1 未停損）
1. `run_gen.py loop --root <ho> --rounds N [--per-round B]`：每輪依 KIN、DIS、TO、MH 輪替出題（MH 依 SUC、BRP、BRL、OQ 輪替，配額 8／7／8／7），平行出題、依序提交（標註＋機械檢查＋該題各次執行的 transcript 盲化檢查），再稽核；major、critical 修一次並複驗，否則刪題；任何一次執行（出題、稽核、修題）有盲化 error 就當場刪題、由後續題遞補，記在紀錄的 `transcript`；直到每類 30 題或草稿達 60 題。出題、修題、稽核的 prompt 都列出所有已用核心與題數（「約西亞（2 題，已滿）」），別名異寫算同一核心，稽核判 major。
2. `mech_check.py questions --root <ho> --scope selected` 與 `mech_check.py transcripts --root <ho> --scope all`。
3. `sample_kay.py draw --root <ho>` → Kay 看 `kay/kay_sample.html` → `sample_kay.py apply --root <ho> --decisions D.json`；要修改的題跑 `run_gen.py fix` 再 `run_audit.py`，刪掉的由 `run_gen.py loop` 遞補。
4. `freeze.py --root <ho>`：寫 `heldout_ho.json` 與附錄 B 清單。`blocked_by_overlap` 只算機械檢查擋下的草稿（agent 會先用 `old --gold` 避開，幾乎都是 0）；另列描述性的 `overlap_avoided`（每類 gen／fix 執行中 `old --gold` 回報衝突的不同段落數、遇到衝突的執行數、理由提到衝突或重疊而放棄的草稿數；試跑 4 題為 KIN 18、DIS 1、TO 81、MH 12 段）與 `transcript_breaches`。

## 測試
在 `evaluation/` 下：`.venv/bin/python -B -m pytest tests/test_graph_gd_ho*.py -q -p no:cacheprovider`。不會啟動 agent；需要 store 的測試在 store 未掛載時 skip。
