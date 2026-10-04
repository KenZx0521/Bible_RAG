#!/usr/bin/env bash
# Registry aux lane A/B — all arms against ONE backend process (rebuilt beforehand).
set -euo pipefail
cd /home/kenzx0521/Bible_RAG/evaluation
TAG=${TAG:-20261003}
PY=.venv/bin/python
OUT=results_quick
SP=/tmp/claude-1001/-home-kenzx0521-Bible-RAG/b7e022b5-365b-41d1-9092-7a9860b09a84/scratchpad

echo "[$(date +%T)] aux (event_registry, top5 + appended, scored @6)"
$PY quick_retrieval_eval.py --graph-strategies event_registry --top-k 5 --metric-k 6 --label aux_registry_$TAG

echo "[$(date +%T)] dense5 (graph off, scored @6)"
$PY quick_retrieval_eval.py --no-use-graph --top-k 5 --metric-k 6 --label dense5_$TAG

$PY - <<EOF
import json
pq = json.load(open("$OUT/aux_registry_$TAG.json"))["per_question"]
touched = sorted(q for q, e in pq.items() if len(e["sources"]) > 5)
open("$SP/touched_$TAG.txt", "w").write("\n".join(touched) + "\n")
print(f"touched: {len(touched)}")
EOF

echo "[$(date +%T)] dense6 on touched (graph off, independent top_k=6)"
$PY quick_retrieval_eval.py --no-use-graph --top-k 6 --metric-k 6 --ids-file $SP/touched_$TAG.txt --label dense6_touched_$TAG

echo "[$(date +%T)] s2 reference (graph_event in pool, scored @6)"
$PY quick_retrieval_eval.py --graph-strategies graph_event --top-k 5 --metric-k 6 --label s2_graph_event_$TAG

echo "[$(date +%T)] compare"
$PY ab_compare.py $OUT/dense5_$TAG.json $OUT/aux_registry_$TAG.json --control-ext $OUT/dense6_touched_$TAG.json --label aux_vs_dense_$TAG
$PY ab_compare.py $OUT/dense5_$TAG.json $OUT/s2_graph_event_$TAG.json --label s2_vs_dense_$TAG
echo "[$(date +%T)] done"
