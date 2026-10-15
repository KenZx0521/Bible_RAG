#!/usr/bin/env bash
# book_anchor ablation, prereg §9 step 3 (3.0–3.9). Resumable: run it again after a stop.
#   mkdir -p $OUT/logs && nohup bash $EXP/run_ba.sh > $OUT/logs/run_ba.log 2>&1 &
# Every resumed JSON-lines file is first cut back to its last newline. A judge output is
# skipped only when it is not empty and its <out>.src_sha (written after the judge exits 0)
# equals the sha256 of the ans raw_responses.json it judges now: an I6 regeneration that
# export-ans wrote again re-judges that directory, a judge killed mid-way runs again.
# Judging never overlaps generation. A failed check stops the script (set -e). Stop the
# batch container with `docker stop bible_rag_ba`.
set -euo pipefail

REPO=/home/kenzx0521/Bible_RAG
EXP=$REPO/evaluation/experiments/2026-10-15_book_anchor
OUT=${BA_OUT:-/mnt/ollama-data/bible_rag_store/reports/ba_ablation_20261015}
PY=$REPO/evaluation/.venv/bin/python
# compose interpolates the staging image from STG_IMAGE: pin it to the image §6 I0 names
export STG_IMAGE=bible_rag-backend:r2
BA_RUN=(docker compose --project-directory $REPO
  -f $REPO/docker-compose.yml -f $REPO/docker-compose.staging.yml -f $EXP/compose.ba.yml
  run --rm --no-deps -T --name bible_rag_ba
  -e RAG_ENV=prod -e RAG_BUILD_ID=b20261008_e05d3e55
  -e PYTHONDONTWRITEBYTECODE=1 -e PYTHONPATH=/app/packages:/app/backend
  -v $EXP:/exp:ro -v $OUT:/in:ro
  backend-stg /app/backend/.venv/bin/python -B /exp/ba_driver.py)
ANALYZE=("$PY" -B "$EXP/ba_analyze.py")

log() { echo "[$(date -Is)] $*"; }
done_file() { [[ -s "$1" ]]; }
sha_of() { sha256sum "$1" | cut -d' ' -f1; }
# judged OUT SRC: OUT exists, is not empty and was judged from SRC as it is now
judged() { done_file "$1" && [[ -s "$1.src_sha" && "$(cat "$1.src_sha")" == "$(sha_of "$2")" ]]; }
# judge OUT SRC CMD…: run CMD, then record SRC's sha (taken before the judge started)
judge() {
  local out=$1 src=$2 sha; shift 2
  rm -f "$out.src_sha"
  sha=$(sha_of "$src") || return
  "$@" || return            # explicit: no sidecar after a failed judge, whatever the context
  echo "$sha" > "$out.src_sha"
}

mkdir -p "$OUT/logs" "$OUT/judge/logs"
log "run_ba start OUT=$OUT"

# 3.0 run-start assertions and inputs (a resume re-verifies them)
"$PY" -B "$EXP/ba_prep.py" --out "$OUT"

# 3.1 retrieval batch A, then the early gate (I0–I4)
log "3.1 retrieve batch A"
"${ANALYZE[@]}" trim "$OUT/retrieval.jsonl"
"${BA_RUN[@]}" retrieve --questions /in/questions.json --ids-file /in/batch_a.json \
  --force-ids /in/force_ids.json --resume /in/retrieval.jsonl \
  >> "$OUT/retrieval.jsonl" 2>> "$OUT/logs/retrieve.log"
"${ANALYZE[@]}" check --out "$OUT" --partial

# 3.2 retrieval of the other questions
log "3.2 retrieve the rest"
"${ANALYZE[@]}" trim "$OUT/retrieval.jsonl"
"${BA_RUN[@]}" retrieve --questions /in/questions.json \
  --force-ids /in/force_ids.json --resume /in/retrieval.jsonl \
  >> "$OUT/retrieval.jsonl" 2>> "$OUT/logs/retrieve.log"

# 3.3 invariants, subsets, plan, freeze
log "3.3 check"
"${ANALYZE[@]}" check --out "$OUT"

# 3.4 retrieval metrics of every arm (descriptive)
log "3.4 retrieval metrics"
"${ANALYZE[@]}" export-retr --out "$OUT"
cd "$REPO/evaluation"
for arm in ctrl nopin off; do
  for k in 5 6; do
    out_file="$OUT/retr/$arm.k$k.json"
    if done_file "$out_file"; then continue; fi
    "$PY" -B quick_retrieval_eval.py --from-raw "$OUT/retr/$arm/raw_responses.json" \
      --gt v2 --top-k 5 --metric-k "$k" --label "$OUT/retr/$arm.k$k" \
      > "$OUT/logs/retr_$arm.k$k.log" 2>&1
  done
done

# 3.5 generation (plan order; resumes by (q, arm, rep))
log "3.5 generate"
"${ANALYZE[@]}" trim "$OUT/gen.jsonl"
"${BA_RUN[@]}" generate --plan /in/checks/gen_plan.json --retrieval /in/retrieval.jsonl \
  --resume /in/gen.jsonl >> "$OUT/gen.jsonl" 2>> "$OUT/logs/generate.log"

# 3.6 answers as collector checkpoints (failed answers kept as they are)
log "3.6 export answers"
"${ANALYZE[@]}" export-ans --out "$OUT"

ollama_ps() { { echo "== $(date -Is) $1"; curl -s localhost:11434/api/ps || true; echo; } \
  >> "$OUT/judge/logs/ollama_ps.log"; }

# 3.7 strict faithfulness, in judge_order (r1's arms, r2's, r3's; arm order by seed)
log "3.7 strict"
strict_dirs=$("${ANALYZE[@]}" judge-order --out "$OUT" --kind strict)
for d in $strict_dirs; do
  arm=${d%_r*}
  f="$OUT/judge/$d.faith.json"
  src="$OUT/ans/$d/raw_responses.json"
  if judged "$f" "$src"; then continue; fi
  ollama_ps "$d strict"
  judge "$f" "$src" env COLUMNS=1000 "$PY" -B quick_faithfulness_eval.py \
    --results-dir "$OUT/ans/$d" --ids-file "$OUT/checks/judge_ids_$arm.json" --gt v2 \
    --no-rebuild --out "$f" > "$OUT/judge/logs/$d.log" 2>&1
done

# 3.8 coverage of every repetition, then ctrl_r1 once more (judge determinism)
log "3.8 coverage"
cov_dirs=$("${ANALYZE[@]}" judge-order --out "$OUT" --kind coverage)
for d in $cov_dirs; do
  arm=${d%_r*}
  f="$OUT/judge/$d.cov.json"
  src="$OUT/ans/$d/raw_responses.json"
  if judged "$f" "$src"; then continue; fi
  ollama_ps "$d coverage"
  judge "$f" "$src" env COLUMNS=1000 "$PY" -B "$EXP/ba_cov.py" --results-dir "$OUT/ans/$d" \
    --ids-file "$OUT/checks/judge_ids_$arm.json" --gt v2 --out "$f" \
    > "$OUT/judge/logs/$d.cov.log" 2>&1
done
f="$OUT/judge/ctrl_r1.cov_rep.json"
src="$OUT/ans/ctrl_r1/raw_responses.json"
if [[ -f "$src" ]] && ! judged "$f" "$src"; then
  ollama_ps "ctrl_r1 coverage repeat"
  judge "$f" "$src" env COLUMNS=1000 "$PY" -B "$EXP/ba_cov.py" --results-dir "$OUT/ans/ctrl_r1" \
    --ids-file "$OUT/checks/judge_ids_ctrl.json" --gt v2 --out "$f" \
    > "$OUT/judge/logs/ctrl_r1.cov_rep.log" 2>&1
fi

# 3.9 report
log "3.9 report"
"${ANALYZE[@]}" report --out "$OUT"
log "run_ba done"
