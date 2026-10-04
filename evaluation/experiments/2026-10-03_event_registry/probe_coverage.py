"""Descriptive coverage for the answer probe (prereg: not used for decisions).

    python probe_coverage.py ROWS.json OUT.json
"""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, "/home/kenzx0521/Bible_RAG/evaluation")
from src.data_loader import load_ground_truth
from src.models import EvalSample
from src.metrics.coverage_eval import _score_one

ROWS, OUT = Path(sys.argv[1]), Path(sys.argv[2])
rows = json.loads(ROWS.read_text())
gts = {g.question_id: g for g in load_ground_truth()}

async def main():
    sem = asyncio.Semaphore(2)
    async def score(i, r):
        g = gts[r["qid"]]
        s = EvalSample(question_id=f"{r['qid']}|{r['arm']}|{r['rep']}", question=g.question,
                       question_type=g.question_type, ground_truth=g, rag_answer=r["answer"])
        _, m = await _score_one(s, sem)
        return {"qid": r["qid"], "arm": r["arm"], "rep": r["rep"], "coverage": m.value, "valid": m.valid}
    out = await asyncio.gather(*(score(i, r) for i, r in enumerate(rows)))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(f"scored {len(out)}; invalid {sum(not o['valid'] for o in out)}")

asyncio.run(main())
