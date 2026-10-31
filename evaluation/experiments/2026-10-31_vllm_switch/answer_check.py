"""Ask smoke20's 20 GT v2 questions in full mode and check the answers themselves.

smoke20 only checks status, sources and a non-empty answer; a failed generation still
returns a non-empty "生成回答時發生錯誤…" string. usage: python answer_check.py BASE_URL OUT_JSON
"""
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "2026-10-08_r1"))
from smoke20 import pick  # noqa: E402

GT = "/home/kenzx0521/Bible_RAG/ground_truth.v2.json"
CJK = re.compile(r"[一-鿿]")
LEAKS = ("<0x", "<|channel>", "<channel|>", "<turn|>", "<|think|>")


def ask(base, q):
    t = time.time()
    r = httpx.post(f"{base}/api/v1/query", json={"question": q["question"], "top_k": 5}, timeout=900)
    a = r.json().get("answer", "") if r.status_code == 200 else ""
    problems = []
    if r.status_code != 200:
        problems.append(f"status {r.status_code}")
    if not a.strip():
        problems.append("empty")
    if a.startswith("生成回答時發生錯誤"):
        problems.append("generation error")
    if a.startswith("thought\n"):
        problems.append("thought label")
    problems += [f"leak {s}" for s in LEAKS if s in a]
    if a and len(CJK.findall(a)) < 0.3 * len(a.replace(" ", "")):
        problems.append("not mostly Chinese")
    return {"qid": q["question_id"], "sec": round(time.time() - t, 1), "chars": len(a),
            "problems": problems, "answer": a}


def main():
    base, out = sys.argv[1], sys.argv[2]
    health = httpx.get(f"{base}/api/v1/health", timeout=30).json()
    rows = list(ThreadPoolExecutor(4).map(lambda q: ask(base, q), pick(GT)))
    bad = [r for r in rows if r["problems"]]
    rep = {"base": base, "services": health.get("services"), "build_id": health.get("build_id"),
           "passed": len(rows) - len(bad), "failed": [(r["qid"], r["problems"]) for r in bad], "rows": rows}
    json.dump(rep, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"services={health.get('services')} {rep['passed']}/{len(rows)} answers clean; failed {rep['failed']}")
    sys.exit(0 if not bad and (health.get("services") or {}).get("llm") else 1)


if __name__ == "__main__":
    main()
