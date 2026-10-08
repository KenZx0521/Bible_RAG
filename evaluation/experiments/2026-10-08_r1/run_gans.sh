#!/usr/bin/env bash
# R1 答案端守門 G-ANS（prereg.md「答案端」）：對照臂收兩次（A1、A2，:8001），
# 處理臂收一次（R，:8002），各臂只問 frozen_r1.json 的 200 題 gans_subset，
# 再用 quick_faithfulness_eval.py 判 zh + strict faithfulness 與 coverage。
#
# - 兩臂共用同一個 Ollama（intent、生成 gemma4:e4b、judge gemma4:26b），
#   所以一次只跑一步，而且要等 G-NONINF 檢索跑完、Ollama 上沒有其他工作才開跑。
# - 預設順序：先收齊三臂，再依序判三臂（生成與 judge 不在臂間來回換模型）。
# - 只跑某幾步：./run_gans.sh collect:R judge:R（步驟：ids、collect:<臂>、judge:<臂>）。
# - 重跑只限基礎設施失敗、每臂最多 2 次（prereg）：OVERWRITE=1 ./run_gans.sh collect:A1
#   （收集預設拒絕覆寫已有 raw_responses.json 的目錄）。收集完有失敗題（src/validity.py
#   answer_failure：基礎設施失敗或生成失敗）就非零結束，不往下判分。
set -euo pipefail

cd /home/kenzx0521/Bible_RAG-rb/evaluation
PY=.venv/bin/python
R1EVAL=/mnt/ollama-data/bible_rag_store/reports/r1eval
FROZEN=experiments/2026-10-08_r1/frozen_r1.json
IDS=$R1EVAL/gans_ids.txt

# judge 與 2026-09-17 量尺修復的基線相同；GT v2 凍結版。
export EVAL_LLM_PROVIDER=ollama
export EVAL_OLLAMA_MODEL=gemma4:26b-a4b-it-q8_0
export EVAL_GT_VERSION=v2

declare -A URL=([A1]=http://localhost:8001 [A2]=http://localhost:8001 [R]=http://localhost:8002)
declare -A BUILD=([A1]=legacy-20261004 [A2]=legacy-20261004 [R]=b20261008_6daa4f31)

log() { echo "[$(date +%T)] $*"; }

write_ids() {
    mkdir -p "$R1EVAL"
    $PY -c '
import sys
from src.r1_frozen import load_frozen
ids = sorted(load_frozen(sys.argv[1]).gans_subset)
assert len(ids) == 200, f"gans_subset has {len(ids)} ids, prereg says 200"
print("\n".join(ids))' "$FROZEN" > "$IDS"
    log "gans_subset → $IDS ($(wc -l < "$IDS") ids)"
}

check_build() {  # 臂的 /health 必須是預期的 build（沒有 build_id = legacy）
    local arm=$1 got
    got=$(curl -sf -m 60 "${URL[$arm]}/api/v1/health" \
        | $PY -c 'import json, sys; print(json.load(sys.stdin).get("build_id") or "legacy-20261004")')
    if [[ $got != "${BUILD[$arm]}" ]]; then
        echo "$arm: ${URL[$arm]} serves $got, expected ${BUILD[$arm]}" >&2
        exit 1
    fi
}

collect() {  # 完整生成 + include_context；run_meta.json 記下 /health 的 build
    local arm=$1 dir=$R1EVAL/gans_$1
    [[ -s $IDS ]] || write_ids
    check_build "$arm"
    log "collect $arm from ${URL[$arm]} → $dir"
    BACKEND_URL=${URL[$arm]} $PY run_eval.py --collect-only --gt v2 --ids-file "$IDS" \
        --results-dir "$dir" ${OVERWRITE:+--overwrite} 2>&1 | tee "$R1EVAL/gans_${arm}_collect.log"
    # 失敗題（基礎設施失敗；backend 以 HTTP 200 回「生成回答時發生錯誤」）判分時一律 invalid，
    # 而守門要三臂 n_invalid 都是 0，所以在這裡就停下來重收。
    if ! $PY -c '
import collections, sys
from pathlib import Path
from src.data_loader import load_gt
from src.evaluator import load_samples_from_checkpoint
from src.validity import answer_failure
samples = load_samples_from_checkpoint(raw_path=Path(sys.argv[1]), gt=load_gt("v2"))
failed = {s.question_id: why for s in samples if (why := answer_failure(s))}
ctx = collections.Counter(s.context_source or "-" for s in samples)
print(f"{len(samples)} answers; failures {len(failed)} {failed}; context_source {dict(ctx)}")
sys.exit(1 if failed else 0)' "$dir/raw_responses.json"; then
        echo "$arm: failed answers; rerun (prereg: infra failures only, at most 2 per arm):" \
            "OVERWRITE=1 $0 collect:$arm" >&2
        exit 1
    fi
}

judge() {  # zh + strict faithfulness 與 coverage，同一個 judge、同一批題
    local arm=$1 dir=$R1EVAL/gans_$1 out=$R1EVAL/gans_${1}_faith.json
    log "judge $arm → $out"
    # --no-rebuild：context 只用 backend 回傳的生成器區塊；R 臂的來源不可拿 legacy PG 重建，
    # 缺區塊的題會讓 meta.context_format 不是 generator_blocks。
    $PY quick_faithfulness_eval.py --results-dir "$dir" --gt v2 --ids-file "$IDS" --coverage \
        --no-rebuild --out "$out" 2>&1 | tee "$R1EVAL/gans_${arm}_judge.log"
    $PY -c '
import json, sys
r = json.load(open(sys.argv[1], encoding="utf-8"))
m = r["meta"]
print({k: m.get(k) for k in ("data_build_id", "gt_version", "n_samples", "n_scored",
                             "n_coverage_scored", "invalid_samples", "context_format")},
      r["overall"])' "$out"
}

STEPS=("$@")
[[ ${#STEPS[@]} -gt 0 ]] || STEPS=(ids collect:A1 collect:A2 collect:R judge:A1 judge:A2 judge:R)
for step in "${STEPS[@]}"; do
    case $step in
        ids) write_ids ;;
        collect:A1 | collect:A2 | collect:R) collect "${step#collect:}" ;;
        judge:A1 | judge:A2 | judge:R) judge "${step#judge:}" ;;
        *) echo "unknown step: $step (ids, collect:<A1|A2|R>, judge:<A1|A2|R>)" >&2; exit 2 ;;
    esac
done
log "done"
