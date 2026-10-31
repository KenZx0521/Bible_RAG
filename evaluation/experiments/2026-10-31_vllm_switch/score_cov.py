"""Coverage (the project's judge, Haiku via evaluation/.env) for each gen_*.jsonl answer set.

usage (from evaluation/): .venv/bin/python -B score_cov.py OUT_JSON GEN_JSONL...
Writes {set name: {qid: {"value", "valid"}}}.
"""
import json
import sys
from pathlib import Path

from src.data_loader import load_gt
from src.metrics.coverage_eval import compute_coverage
from src.models import EvalSample

RAW = Path("/home/kenzx0521/Bible_RAG/evaluation/results_graph/raw_responses.json")


def main() -> None:
    out, sets = Path(sys.argv[1]), sys.argv[2:]
    gt = load_gt("v2").by_id()
    raw = {x["question_id"]: x for x in json.loads(RAW.read_text())}
    scores = json.loads(out.read_text()) if out.exists() else {}
    for path in sets:
        name = Path(path).stem
        if name in scores:
            continue
        rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
        samples = [EvalSample(question_id=r["qid"], question=gt[r["qid"]].question,
                              question_type=gt[r["qid"]].question_type, rag_answer=r["answer"],
                              contexts=raw[r["qid"]]["contexts"], context_source="backend",
                              ground_truth=gt[r["qid"]]) for r in rows]
        results, _ = compute_coverage(samples)
        scores[name] = {qid: {"value": rs[0].value, "valid": rs[0].valid} for qid, rs in results.items()}
        out.write_text(json.dumps(scores, ensure_ascii=False, indent=1))
        print(name, len(samples), flush=True)


if __name__ == "__main__":
    main()
