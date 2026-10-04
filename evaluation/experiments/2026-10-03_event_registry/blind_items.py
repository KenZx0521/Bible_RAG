"""Blind probe answers for review: hide arm/rep, shuffle with a fixed seed,
keep the key separately, split into batches for parallel reviewers.

    python blind_items.py ROWS.json OUT_DIR [--batches 6] [--seed 20261003] [--prefix blind]

Writes OUT_DIR/<prefix>_batch_<i>.json and OUT_DIR/<prefix>_key.json.
"""
import argparse
import json
import random
from pathlib import Path

GT = Path(__file__).resolve().parents[3] / "ground_truth.json"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("rows", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--batches", type=int, default=6)
    ap.add_argument("--seed", type=int, default=20261003)
    ap.add_argument("--prefix", default="blind")
    a = ap.parse_args()

    rows = json.loads(a.rows.read_text())
    gt = {q["question_id"]: q for q in json.loads(GT.read_text())["questions"]}
    items, key = [], {}
    for r in rows:
        if "error" in r:
            continue
        g = gt[r["qid"]]
        items.append({
            "question_id": r["qid"],
            "question": g["question"],
            "reference_answer": g["reference_answer"],
            "expected_answer_points": g["expected_answer_points"],
            "contexts": r["contexts"],
            "answer": r["answer"],
            "_key": (r["arm"], r["rep"]),
        })
    random.Random(a.seed).shuffle(items)
    for i, it in enumerate(items):
        it["item_id"] = f"I{i:03d}"
        key[it["item_id"]] = {"qid": it["question_id"], "arm": it["_key"][0], "rep": it["_key"][1]}
        del it["_key"]

    a.out_dir.mkdir(parents=True, exist_ok=True)
    for b in range(a.batches):
        (a.out_dir / f"{a.prefix}_batch_{b}.json").write_text(
            json.dumps(items[b::a.batches], ensure_ascii=False, indent=1))
    (a.out_dir / f"{a.prefix}_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=1))
    print(f"{len(items)} items → {a.batches} batches; errors skipped: {sum('error' in r for r in rows)}")


if __name__ == "__main__":
    main()
