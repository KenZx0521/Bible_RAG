"""Two-sided + non-inferiority answer test for the registry lane
(prereg_two_sided.md). Run from evaluation/ after the blind review:

    python experiments/2026-10-03_event_registry/twosided_analysis.py
"""
import collections
import json
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(EVAL))
from src.ab_stats import bootstrap_ci, sign_flip_p  # noqa: E402

RQ = EVAL / "results_quick"
ROWS = RQ / "answer_probe_twosided_20261004.json"
REVIEW = RQ / "answer_probe_twosided_review_20261004.json"
COVERAGE = RQ / "answer_probe_twosided_coverage_20261004.json"
BAD = {"misattribution", "fabricated_citation"}
SEED = 20261004
MARGIN = 0.10
MIN_VALID = 6
CURATED = {"EVENT_QUESTION_008", "EVENT_QUESTION_011", "EVENT_QUESTION_014", "EVENT_QUESTION_019",
           "GENERAL_BIBLE_QUESTION_065", "GENERAL_BIBLE_QUESTION_076"}


def main() -> None:
    labels = {(v["qid"], v["arm"], v["rep"]): v["label"]
              for v in json.loads(REVIEW.read_text())["labels"].values()}
    per = collections.defaultdict(lambda: collections.defaultdict(list))
    refusals = collections.Counter()
    dropped = []
    for r in json.loads(ROWS.read_text()):
        ok = ("error" not in r and r["route"] in ("R4", "R5") and r["n_sources"] == 6
              and (r["arm"] != "AUX" or r["appended"]))
        if not ok:
            dropped.append((r["qid"], r["arm"], r["rep"], r.get("route"), r.get("appended"), r.get("error")))
            continue
        bad = bool(r["refusal"]) or labels[(r["qid"], r["arm"], r["rep"])] in BAD
        per[r["qid"]][r["arm"]].append(bad)
        refusals[r["arm"]] += bool(r["refusal"])

    excluded = sorted(q for q, arms in per.items()
                      if min(len(arms["AUX"]), len(arms["DENSE6"])) < MIN_VALID)
    qids = sorted(q for q in per if q not in excluded)
    d = {q: sum(per[q]["AUX"]) / len(per[q]["AUX"]) - sum(per[q]["DENSE6"]) / len(per[q]["DENSE6"])
         for q in qids}
    diffs = [d[q] for q in qids]
    mean_d = sum(diffs) / len(diffs)
    p = sign_flip_p(diffs, seed=SEED)
    lo90, hi90 = bootstrap_ci(diffs, seed=SEED, level=0.90)
    lo95, hi95 = bootstrap_ci(diffs, seed=SEED, level=0.95)

    if p < 0.05 and mean_d > 0:
        verdict = "STOP: AUX significantly worse"
    elif hi90 < MARGIN:
        verdict = "PASS: AUX non-inferior (answer-side gate passed)"
    else:
        verdict = "INCONCLUSIVE: keep the current default"

    print(f"dropped generations: {dropped or '-'}")
    print(f"excluded questions (<{MIN_VALID} valid in an arm): {excluded or '-'}")
    print(f"\n{'question':28s} AUX      DENSE6   d")
    for q in qids:
        a, b = per[q]["AUX"], per[q]["DENSE6"]
        print(f"{q:28s} {sum(a)}/{len(a):<6} {sum(b)}/{len(b):<6} {d[q]:+.3f}")
    print(f"\nn questions = {len(qids)}; mean d (AUX − DENSE6 problem rate) = {mean_d:+.4f}")
    print(f"wins/losses (AUX fewer/more problems) = {sum(x < 0 for x in diffs)}/{sum(x > 0 for x in diffs)}")
    print(f"two-sided sign-flip p = {p:.4f}")
    print(f"bootstrap 90% CI = [{lo90:+.4f}, {hi90:+.4f}]  (non-inferiority margin +{MARGIN})")
    print(f"bootstrap 95% CI = [{lo95:+.4f}, {hi95:+.4f}]")
    print(f"refusals: {dict(refusals)}")
    print(f"\nprereg verdict: {verdict}")

    nc = [d[q] for q in qids if q not in CURATED]
    print(f"\n[descriptive] mean d excluding curated questions (n={len(nc)}): {sum(nc) / len(nc):+.4f}")
    cov = None
    if COVERAGE.exists():
        rows = [c for c in json.loads(COVERAGE.read_text()) if c["valid"]]
        by = collections.defaultdict(lambda: collections.defaultdict(list))
        for c in rows:
            by[c["qid"]][c["arm"]].append(c["coverage"])
        cd = [sum(by[q]["AUX"]) / len(by[q]["AUX"]) - sum(by[q]["DENSE6"]) / len(by[q]["DENSE6"])
              for q in qids if by[q]["AUX"] and by[q]["DENSE6"]]
        cov = sum(cd) / len(cd)
        print(f"[descriptive] mean coverage AUX − DENSE6: {cov:+.4f} (wins/losses {sum(x > 0 for x in cd)}/{sum(x < 0 for x in cd)})")

    out = RQ / "answer_probe_twosided_result_20261004.json"
    out.write_text(json.dumps({
        "n_questions": len(qids), "excluded": excluded, "dropped": dropped,
        "per_question_d": d, "mean_d": mean_d, "sign_flip_p": p,
        "ci90": [lo90, hi90], "ci95": [lo95, hi95], "margin": MARGIN,
        "refusals": dict(refusals), "verdict": verdict,
        "mean_d_excluding_curated": sum(nc) / len(nc), "mean_coverage_delta": cov,
    }, ensure_ascii=False, indent=1))
    print(f"saved → {out}")


if __name__ == "__main__":
    main()
