"""Answer-side stop check for the event registry lane (see
evaluation/experiments/2026-10-03_event_registry_answer_probe_prereg.md).

AUX (event_registry, top_k=5 + appended) vs DENSE6 (graph off, top_k=6) on the
touched questions, 3 generations per arm per question. Writes every answer with
the exact context blocks it was generated from.

    python answer_probe.py TOUCHED OUT [--arms AUX DENSE6] [--reps 3] [--rep-offset 0]

The A/A calibration (prereg_aa_calibration.md) reuses it with
--arms DENSE6 --reps 9 --rep-offset 3.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path("/home/kenzx0521/Bible_RAG")
sys.path.insert(0, str(ROOT / "evaluation"))
from src.data_loader import load_ground_truth  # noqa: E402

ARMS = {
    "AUX": {"graph_strategies": ["event_registry"], "top_k": 5},
    "DENSE6": {"use_graph": False, "top_k": 6},
}
REFUSAL_WORDS = ["找不到", "無法回答", "無法從", "沒有提到", "並未提及", "未提及", "沒有相關",
                 "不足以回答", "沒有提供", "並未提供", "未提供"]


def is_refusal(answer: str) -> bool:
    text = re.sub(r"\s+", "", answer or "")
    return len(text) < 30 or any(w in text[:80] for w in REFUSAL_WORDS)


async def one(client, sem, gt, arm, rep):
    payload = {"question": gt.question, "include_sources": True, "include_context": True, **ARMS[arm]}
    async with sem:
        for attempt in range(3):
            try:
                r = await client.post("http://localhost:8000/api/v1/query", json=payload)
                r.raise_for_status()
                d = r.json()
                break
            except Exception as e:  # noqa: BLE001
                if attempt == 2:
                    return {"qid": gt.question_id, "arm": arm, "rep": rep, "error": repr(e)[:200]}
                await asyncio.sleep(3)
    st = d["retrieval_stats"]
    srcs = d["sources"]
    return {
        "qid": gt.question_id, "arm": arm, "rep": rep,
        "route": st.get("route_used"),
        "appended": any(s.get("strategy") == "event_registry" for s in srcs),
        "n_sources": len(srcs),
        "source_ids": [s["id"] for s in srcs],
        "contexts": [s.get("context") for s in srcs],
        "answer": d["answer"],
        "refusal": is_refusal(d["answer"]),
        "strategy_errors": st.get("strategy_errors"),
    }


async def main(touched: Path, out: Path, arms: list[str], reps: int, offset: int):
    ids = [l.strip() for l in touched.read_text().split() if l.strip()]
    gts = {g.question_id: g for g in load_ground_truth()}
    sem = asyncio.Semaphore(2)
    async with httpx.AsyncClient(timeout=600.0) as client:
        tasks = [one(client, sem, gts[q], arm, rep)
                 for q in ids for arm in arms for rep in range(offset, offset + reps)]
        rows = []
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            rows.append(await coro)
            if i % 10 == 0:
                print(f"{i}/{len(tasks)}", flush=True)
                out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    rows.sort(key=lambda r: (r["qid"], r["arm"], r["rep"]))
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    print(f"wrote {len(rows)} rows → {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("touched", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--rep-offset", type=int, default=0)
    a = ap.parse_args()
    asyncio.run(main(a.touched, a.out, a.arms, a.reps, a.rep_offset))
