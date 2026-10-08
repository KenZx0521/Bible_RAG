#!/usr/bin/env bash
# R2 評估（prereg.md「執行順序」第 4–6 步）。前提：第 1–3 步完成——R2 staging 在 :8002、
# L2 已跑、frozen_r2.json 已凍結並把 sha256 釘進 src/r2_frozen.py、與 prereg 一起 commit。
#
# - 對照 R1 在 prod :8000，處理 R2 在 staging :8002；兩臂共用一個 Ollama，所以一步一步跑。
# - 只跑某幾步：./run_r2.sh retrieval gate_retrieval collect:A2 …（步驟見最下面）。
# - 重跑只限基礎設施失敗、每臂最多 2 次（prereg）：OVERWRITE=1 ./run_r2.sh collect:A2。
set -euo pipefail

cd /home/kenzx0521/Bible_RAG-r2/evaluation
PY=.venv/bin/python
OUT=/mnt/ollama-data/bible_rag_store/reports/r2eval
R1EVAL=/mnt/ollama-data/bible_rag_store/reports/r1eval
FROZEN=experiments/2026-10-09_r2/frozen_r2.json
IDS=$OUT/gans_ids.txt

# judge 與 R1 預登記相同；GT v2 凍結版。
export EVAL_LLM_PROVIDER=ollama
export EVAL_OLLAMA_MODEL=gemma4:26b-a4b-it-q8_0
export EVAL_GT_VERSION=v2

declare -A URL=([R1]=http://localhost:8000 [A2]=http://localhost:8000 [R2]=http://localhost:8002)
declare -A BUILD=([R1]=b20261008_6daa4f31 [A2]=b20261008_6daa4f31 [R2]=b20261008_e05d3e55)

log() { echo "[$(date +%T)] $*"; }

check_build() {
    local arm=$1 got
    got=$(curl -sf -m 60 "${URL[$arm]}/api/v1/health" | $PY -c 'import json, sys; print(json.load(sys.stdin).get("build_id"))')
    [[ $got == "${BUILD[$arm]}" ]] || { echo "$arm: ${URL[$arm]} serves $got, expected ${BUILD[$arm]}" >&2; exit 1; }
}

retrieval() {  # R2 臂 500 題檢索
    check_build R2
    log "retrieval R2 → $OUT/r2eval_r2.json"
    BACKEND_URL=${URL[R2]} $PY -u quick_retrieval_eval.py --gt v2 --top-k 5 --metric-k 6 \
        --concurrency 3 --label r2eval_r2 > "$OUT/r2_retrieval.log" 2>&1
    cp results_quick/r2eval_r2.json "$OUT/"
}

gate_retrieval() {
    $PY r1_gate.py retrieval --prereg r2 --aa "$R1EVAL/r1eval_r1.json" "$OUT/r2eval_r1_L2.json" \
        --treatment "$OUT/r2eval_r2.json" --frozen "$FROZEN" --out "$OUT/gate_retrieval.json" \
        ${OVERWRITE:+--overwrite} 2>&1 | tee "$OUT/gate_retrieval.log" || true
}

write_ids() {
    $PY -c '
import sys
from src.r1_frozen import load_frozen
ids = sorted(load_frozen().gans_subset)
assert len(ids) == 200
print("\n".join(ids))' > "$IDS"
}

collect() {  # 完整生成 + include_context
    local arm=$1 dir=$OUT/gans_$1
    [[ -s $IDS ]] || write_ids
    check_build "$arm"
    log "collect $arm from ${URL[$arm]} → $dir"
    BACKEND_URL=${URL[$arm]} $PY run_eval.py --collect-only --gt v2 --ids-file "$IDS" \
        --results-dir "$dir" ${OVERWRITE:+--overwrite} > "$OUT/gans_${arm}_collect.log" 2>&1
    $PY -c '
import collections, sys
from pathlib import Path
from src.data_loader import load_gt
from src.evaluator import load_samples_from_checkpoint
from src.validity import answer_failure
samples = load_samples_from_checkpoint(raw_path=Path(sys.argv[1]), gt=load_gt("v2"))
failed = {s.question_id: why for s in samples if (why := answer_failure(s))}
ctx = collections.Counter(s.context_source or "-" for s in samples)
print(f"{len(samples)} answers; failures {len(failed)} {failed}; context_source {dict(ctx)}")
sys.exit(1 if failed else 0)' "$dir/raw_responses.json"
}

judge() {
    local arm=$1 dir=$OUT/gans_$1 out=$OUT/gans_${1}_faith.json
    log "judge $arm → $out"
    $PY quick_faithfulness_eval.py --results-dir "$dir" --gt v2 --ids-file "$IDS" --coverage \
        --no-rebuild --out "$out" > "$OUT/gans_${arm}_judge.log" 2>&1
}

gate_answer() {
    $PY r1_gate.py answer --prereg r2 --aa "$R1EVAL/gans_R_faith.json" "$OUT/gans_A2_faith.json" \
        --treatment "$OUT/gans_R2_faith.json" --frozen "$FROZEN" --out "$OUT/gate_answer.json" \
        ${OVERWRITE:+--overwrite} 2>&1 | tee "$OUT/gate_answer.log" || true
}

heldout() {  # 兩臂 held-out 收集
    local arm=$1
    check_build "$arm"
    log "heldout $arm"
    BACKEND_URL=${URL[$arm]} $PY heldout_gate.py collect --arm "$arm" --build "${BUILD[$arm]}" \
        --out "$OUT/heldout_${arm}.json" ${OVERWRITE:+--overwrite}
}

gate_heldout() {
    $PY heldout_gate.py score --r1 "$OUT/heldout_R1.json" --r2 "$OUT/heldout_R2.json" \
        --out "$OUT/gate_heldout.json" ${OVERWRITE:+--overwrite} 2>&1 | tee "$OUT/gate_heldout.log" || true
}

STEPS=("$@")
[[ ${#STEPS[@]} -gt 0 ]] || STEPS=(retrieval gate_retrieval collect:A2 collect:R2 judge:A2 judge:R2
                                    gate_answer heldout:R1 heldout:R2 gate_heldout)
for step in "${STEPS[@]}"; do
    case $step in
        retrieval | gate_retrieval | gate_answer | gate_heldout) $step ;;
        collect:A2 | collect:R2) collect "${step#collect:}" ;;
        judge:A2 | judge:R2) judge "${step#judge:}" ;;
        heldout:R1 | heldout:R2) heldout "${step#heldout:}" ;;
        *) echo "unknown step: $step" >&2; exit 2 ;;
    esac
done
log "done"
