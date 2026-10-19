"""Plan A4 (docs/records/2026-10-19_regnal_card_integration_plan.md §3): the blind confirmation
set's 32 questions through a backend's /query, card on, one call each, scored with experiment
A's own scorer (score_a.score_line on answer_text, trap rule "chain" = confirm_A.md §6.1).

Pass: 0 request errors, 0 timeouts, and the mean key_score over the questions that got a card
>= 0.70 (the confirmation set's G-auto item mean was 0.802). Descriptive: card rate, the mean over
all 32, per-question scores beside the confirmation run's G-auto item means.

Question text, answers and scripture stay in the store (reports/regnal_card_20261019/a4/); this
file prints numbers and ids only.

    python3 -B a4_staging.py [--url http://localhost:8002] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIRM = HERE.parent / "2026-10-18_kg_cards" / "A" / "confirm"
sys.path.insert(0, str(CONFIRM))
from c_common import ITEMS, LAYER_REF, OUT as A_CONFIRM, read_json  # noqa: E402
from keys_a import king_lexicon  # noqa: E402
from regnal import load_ref  # noqa: E402
from score_a import answer_text  # noqa: E402
from keys_a import score_line  # noqa: E402
from score_c import rule_ctx  # noqa: E402

STORE_OUT = Path("/mnt/ollama-data/bible_rag_store/reports/regnal_card_20261019/a4")
TIMEOUT_S = 300
PASS_MEAN = 0.70


def post(url: str, body: dict) -> tuple[dict | None, str | None, float]:
    req = urllib.request.Request(url + "/api/v1/query", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read()), None, round(time.time() - t0, 2)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return None, repr(exc)[:300], round(time.time() - t0, 2)


def api_ps() -> str:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/ps", timeout=10) as r:
            return json.dumps([m["name"] for m in json.loads(r.read()).get("models", [])])
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return repr(exc)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8002")
    ap.add_argument("--out", type=Path, default=STORE_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    items = read_json(ITEMS)["items"]
    g_auto = {k: v["mean"]["G-auto"] for k, v in read_json(A_CONFIRM / "scores.json")["items"].items()}
    VR = load_ref(LAYER_REF)
    base = king_lexicon(VR)
    out_path = args.out / "responses.jsonl"
    done = {}
    if out_path.exists():
        done = {json.loads(l)["item"]: json.loads(l) for l in out_path.read_text(encoding="utf-8").splitlines() if l}
    print("api/ps before", api_ps())
    with out_path.open("a", encoding="utf-8") as f:
        for i, it in enumerate(items, 1):
            if it["id"] in done:
                continue
            resp, err, sec = post(args.url, {"question": it["question"], "include_context": True})
            rec = {"item": it["id"], "elapsed_s": sec, "error": err,
                   "answer": resp.get("answer") if resp else None,
                   "aux_card": resp.get("aux_card") if resp else None,
                   "sources": [s["id"] for s in resp.get("sources", [])] if resp else [],
                   "build_id": (resp.get("sources") or [{}])[0].get("build_id") if resp else None,
                   "route": (resp.get("retrieval_stats") or {}).get("route_used") if resp else None}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
            done[it["id"]] = rec
            print(f"[{i}/{len(items)}] {it['id']} {sec}s card={'y' if rec['aux_card'] else 'n'} err={bool(err)}")
    print("api/ps after", api_ps())
    rows = []
    for it in items:
        rec = done[it["id"]]
        line = answer_text(rec["answer"] or "") if rec["answer"] else None
        s = score_line(rule_ctx(it, VR, base), line)
        rows.append({"item": it["id"], "card": bool(rec["aux_card"]), "score": s["score"], "trap": s["trap"],
                     "confirm_g_auto": g_auto.get(it["id"]), "elapsed_s": rec["elapsed_s"],
                     "error": bool(rec["error"]), "build_id": rec["build_id"]})
    fired = [r for r in rows if r["card"]]
    mean = lambda xs: round(sum(xs) / len(xs), 3) if xs else None  # noqa: E731
    errors = sum(r["error"] for r in rows)
    timeouts = sum(1 for r in rows if r["error"] and r["elapsed_s"] >= TIMEOUT_S - 1)
    rep = {"url": args.url, "n": len(rows), "errors": errors, "timeouts": timeouts, "card": len(fired),
           "mean_fired": mean([r["score"] for r in fired]), "mean_all": mean([r["score"] for r in rows]),
           "confirm_g_auto_mean_fired": mean([r["confirm_g_auto"] for r in fired]),
           "elapsed_s_max": max(r["elapsed_s"] for r in rows), "build_ids": sorted({str(r["build_id"]) for r in rows}),
           "pass": errors == 0 and timeouts == 0 and (mean([r["score"] for r in fired]) or 0) >= PASS_MEAN,
           "rows": rows}
    (args.out / "a4_report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: v for k, v in rep.items() if k != "rows"})


if __name__ == "__main__":
    main()
