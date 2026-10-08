"""20-question smoke against the R1 staging backend: GT v2, 4 per type, retrieval_only and full.

usage: python smoke20.py BASE_URL BUILD_ID GT_JSON OUT_JSON
Exit 0 only when every request is 200 and every check holds.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

from ragcommon import ids

SOURCE_KINDS = {"passage", "chunk", "verse_record", "verse_range"}
VERSE_RANGE = re.compile(r"[1-9][0-9]*(-[1-9][0-9]*)?")


def post(base, body, timeout=600):
    req = urllib.request.Request(f"{base}/api/v1/query", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read()), time.time() - start
    except urllib.error.HTTPError as exc:
        return exc.code, {"error": exc.read().decode(errors="replace")[:500]}, time.time() - start


def source_problems(source, build_id):
    problems = []
    try:
        kind = ids.parse(source["id"]).kind
    except ValueError as exc:
        return [f"{source['id']!r}: not an id ({exc})"]
    if kind not in SOURCE_KINDS:
        problems.append(f"{source['id']}: kind {kind}")
    if not VERSE_RANGE.fullmatch(source.get("verse_range") or ""):
        problems.append(f"{source['id']}: verse_range {source.get('verse_range')!r}")
    if source.get("build_id") != build_id:
        problems.append(f"{source['id']}: build_id {source.get('build_id')!r}")
    return problems


def check(mode, status, body, build_id):
    if status != 200:
        return [f"{mode}: HTTP {status} {body}"]
    problems = [] if body.get("sources") else [f"{mode}: no sources"]
    for source in body.get("sources", []):
        problems += [f"{mode}: {p}" for p in source_problems(source, build_id)]
    answer = body.get("answer", "")
    if mode == "retrieval_only" and answer:
        problems.append("retrieval_only: answer is not empty")
    if mode == "full" and not answer.strip():
        problems.append("full: empty answer")
    return problems


def pick(gt_path):
    questions = json.load(open(gt_path, encoding="utf-8"))["questions"]
    chosen = defaultdict(list)
    for q in questions:
        if len(chosen[q["question_type"]]) < 4:
            chosen[q["question_type"]].append(q)
    return [q for group in chosen.values() for q in group]


def run_one(base, build_id, q):
    row = {"question_id": q["question_id"], "problems": []}
    for mode, extra in (("retrieval_only", {"retrieval_only": True}), ("full", {})):
        status, body, seconds = post(base, {"question": q["question"], "top_k": 5, **extra})
        row[mode] = {"status": status, "seconds": round(seconds, 1),
                     "route": body.get("retrieval_stats", {}).get("route_used"),
                     "events": body.get("retrieval_stats", {}).get("event_registry_events"),
                     "sources": [(s["id"], s.get("verse_range"), s.get("strategy"))
                                 for s in body.get("sources", [])],
                     "answer_chars": len(body.get("answer", ""))}
        row["problems"] += check(mode, status, body, build_id)
    return row


def main():
    base, build_id, gt_path, out = sys.argv[1:5]
    rows = [run_one(base, build_id, q) for q in pick(gt_path)]
    bad = [r for r in rows if r["problems"]]
    report = {"base": base, "build_id": build_id, "questions": len(rows),
              "requests": 2 * len(rows), "passed": len(rows) - len(bad),
              "failed": [{"question_id": r["question_id"], "problems": r["problems"]} for r in bad],
              "rows": rows}
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    sys.stdout.write(f"{report['passed']}/{len(rows)} passed; failed {report['failed']}\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
