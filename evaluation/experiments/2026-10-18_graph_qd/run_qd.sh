#!/usr/bin/env bash
# plan.md §6: the overnight run of step 1 (IT continuation, DEEP and the QD-family arms on
# NEW82), its evaluation, then step 2 (GT v2 multi-anchor QD). Resumable: re-running the
# same command skips finished parts (stages are keyed; frozen outputs must reproduce).
#
#   mkdir -p /mnt/ollama-data/bible_rag_store/reports/graph_qd_20261018/logs && \
#   setsid nohup bash /home/kenzx0521/Bible_RAG/evaluation/experiments/2026-10-18_graph_qd/run_qd.sh \
#     >> /mnt/ollama-data/bible_rag_store/reports/graph_qd_20261018/logs/run.log 2>&1 < /dev/null &
#
# After an infrastructure fix is committed (plan.md 執行紀錄), delete logs/head.txt to accept
# the new HEAD.
set -euo pipefail

EXP=/home/kenzx0521/Bible_RAG/evaluation/experiments/2026-10-18_graph_qd
GD=/home/kenzx0521/Bible_RAG/evaluation/experiments/2026-10-14_graph_gd
N82=/mnt/ollama-data/bible_rag_store/reports/kg_effect_eval_20261014/new82_ans
OUT=/mnt/ollama-data/bible_rag_store/reports/graph_qd_20261018
PY=/home/kenzx0521/Bible_RAG/evaluation/.venv/bin/python
IMAGE=sha256:c79266296cb0e48be2274c24a3e6744b7b3e8eb420771ef9cc5cb1fd4e8ab912
MODEL=gemma4:e4b-it-q8_0
DIGEST=9dcc35808b42e8975f1e9dd9d7866925a8d0704b6bb3613525323f355dde3923
RETRIES=3                   # attempts of a resumable python step (container-level failures)
RETRY_PAUSE=300
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$OUT/logs"

exec 9>>"$OUT/logs/run.lock"
flock -n 9 || { echo "another run_qd.sh holds $OUT/logs/run.lock"; exit 3; }

step() { echo "=== $(date -Is) $*"; }
ps_log() {
  printf '{"time":"%s","label":"%s","ps":%s}\n' "$(date -Is)" "$1" \
    "$(curl -s --max-time 30 localhost:11434/api/ps)" >> "$OUT/logs/ollama_ps.log"
}
run() { step "$*"; local rc=0; "$@" || rc=$?; echo "=== rc=$rc"; return "$rc"; }
retry() {   # a resumable step: rerun on failure, at most RETRIES times
  local i
  for ((i = 1; i <= RETRIES; i++)); do
    run "$@" && return 0
    [[ $i -lt $RETRIES ]] && { echo "=== retry in ${RETRY_PAUSE}s ($i/$RETRIES)"; sleep "$RETRY_PAUSE"; }
  done
  return 1
}
refcheck_pass() {   # last refcheck line of a refpairs file says pass
  "$PY" -c 'import json,sys; r=[json.loads(l) for l in open(sys.argv[1]) if l.strip()]; c=[x for x in r if x.get("type")=="refcheck"]; sys.exit(0 if c and c[-1]["pass"] else 1)' "$1"
}
refpairs() {   # $1 = file name; drift is recorded (K), only `before` stops the run
  local f="$OUT/logs/$1"
  [[ -f "$f" ]] || (cd "$GD" && run "$PY" -B score.py refpairs --out "$f") || true
  refcheck_pass "$f" || { echo "refpairs $1 drifted or failed (K)"; return 1; }
}
check_digest() {
  local got
  got=$(curl -s --max-time 30 localhost:11434/api/tags | "$PY" -c "import json,sys; print([m['digest'] for m in json.load(sys.stdin)['models'] if m['name']=='$MODEL'][0])")
  [[ "$got" == "$DIGEST" ]] || { echo "Ollama $MODEL digest $got != $DIGEST"; exit 3; }
}

preflight() {
  step "preflight"
  local head; head=$(git -C /home/kenzx0521/Bible_RAG rev-parse HEAD)
  [[ -z "$(git -C /home/kenzx0521/Bible_RAG status --porcelain -- evaluation/experiments evaluation/tests)" ]] \
    || { echo "experiment or test files are dirty or untracked (commit first)"; exit 3; }
  git -C /home/kenzx0521/Bible_RAG ls-files --error-unmatch evaluation/experiments/2026-10-18_graph_qd/plan.md >/dev/null
  [[ "$(docker inspect --format '{{.Image}}' bible_rag_backend)" == "$IMAGE" ]] || { echo "backend image changed"; exit 3; }
  local busy
  busy=$(docker exec bible_rag_backend sh -c 'for p in /proc/[0-9]*; do c=$(tr "\0" " " < $p/cmdline 2>/dev/null); case "$c" in "/app/backend/.venv/bin/python -B -"*) echo ${p#/proc/};; esac; done' | wc -l)
  [[ "$busy" == 0 ]] || { echo "another container script is running in the backend"; exit 3; }
  if pgrep -af 'python[0-9.]* (-B )?\S*(score|build_it|p5_query|run_eval|quick_retrieval_eval|quick_faithfulness_eval|ba_driver|qd_build|qd_step2|qd_eval|eval_iter)\.py' >/dev/null; then
    echo "another evaluation process is running:"
    pgrep -af 'python[0-9.]* (-B )?\S*(score|build_it|p5_query|run_eval|quick_retrieval_eval|quick_faithfulness_eval|ba_driver|qd_build|qd_step2|qd_eval|eval_iter)\.py' || true
    exit 3
  fi
  local loaded
  loaded=$(curl -s --max-time 30 localhost:11434/api/ps | "$PY" -c 'import json,sys; print(" ".join(m["name"] for m in json.load(sys.stdin)["models"]))')
  [[ -z "$loaded" || "$loaded" == "$MODEL" ]] || { echo "Ollama has other models loaded: $loaded"; exit 3; }
  check_digest
  [[ ! -e /var/run/reboot-required ]] || echo "note: reboot-required flag is set"
  if [[ -f "$OUT/logs/head.txt" ]]; then
    [[ "$(cat "$OUT/logs/head.txt")" == "$head" ]] || { echo "HEAD changed since the first run (see header)"; exit 3; }
  else
    echo "$head" > "$OUT/logs/head.txt"
    sha256sum "$N82"/{it_host.py,it_container.py,build_it.py,eval_iter.py,plan.md} > "$OUT/logs/new82_ans_code.sha256"
  fi
  ps_log preflight
}

warm() {   # load the decomposer for 60 min so a cold 11 GB load cannot time out a decompose call
  curl -s --max-time 600 -o /dev/null -w "warm-up http %{http_code} %{time_total}s\n" localhost:11434/api/generate \
    -d "{\"model\":\"$MODEL\",\"prompt\":\"\",\"stream\":false,\"keep_alive\":\"60m\"}"
  ps_log warm-up
}

preflight
refpairs refpairs_before.jsonl || { echo "reference pairs drifted before the run: stop (plan.md §4 K)"; exit 3; }

# IT-D / IT-GD continuation (verdict I); a failure here must not stop step 1
if [[ ! -f "$N82/it_lanes.sha256" ]]; then
  warm
  (cd "$N82" && run "$PY" -B build_it.py run) || echo "=== IT build failed (recorded; verdict I unavailable)"
fi
if [[ -f "$N82/it_lanes.sha256" && ! -f "$N82/retrieval_iter.json" ]]; then
  (cd "$N82" && run "$PY" -B eval_iter.py) || echo "=== eval_iter reference reproduction failed (recorded)"
fi
ps_log after-it

cd "$EXP"
[[ -f "$OUT/oracle_names.json" ]] || run "$PY" -B qd_build.py oracle
[[ -f "$OUT/lanes.sha256" ]] || retry "$PY" -B qd_build.py run
ps_log after-step1
refpairs refpairs_mid.jsonl || true
[[ -f "$OUT/report.json" ]] || run "$PY" -B qd_eval.py || echo "=== qd_eval failed (recorded; rerun it by day)"
step "STEP1_DONE"

# step 2 (plan.md §5): GT v2 multi-anchor QD, not a graph arm
[[ -f "$OUT/step2/ids.json" ]] || run "$PY" -B qd_step2.py ids
[[ -f "$OUT/step2/lanes2_meta.json" ]] || retry "$PY" -B qd_step2.py run
ps_log after-step2
refpairs refpairs_after.jsonl || true
run "$PY" -B qd_step2.py score
run "$PY" -B qd_step2.py analyze
step "ALL_DONE"
