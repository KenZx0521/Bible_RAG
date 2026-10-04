"""A/A calibration of the answer-side stop rule (prereg_aa_calibration.md).

Pools all valid DENSE6 generations per question (3 from the original probe +
9 new), then repeatedly draws two disjoint sets of 3 and applies the original
rule (a set "has a problem" when ≥2 of its 3 generations are refusals or were
labelled misattribution / fabricated_citation). X counts questions where set A
has a problem and set A' does not. P_null(X≥3) is the rule's false-STOP rate.

    python aa_calibration.py   (from evaluation/)
"""
import collections
import json
import random
import statistics
from pathlib import Path

RQ = Path(__file__).resolve().parents[2] / "results_quick"
ROWS = [RQ / "answer_probe_registry_20261003.json", RQ / "answer_probe_aa_dense6_20261004.json"]
REVIEWS = [RQ / "answer_probe_registry_review_20261003.json", RQ / "answer_probe_aa_review_20261004.json"]
BAD_LABELS = {"misattribution", "fabricated_citation"}
B = 20000
SEED = 20261004
SET = 3
OBSERVED_X, OBSERVED_Y = 3, 5  # AUX-only / DENSE6-only in the original probe


def load() -> dict[str, list[bool]]:
    labels = {}
    for path in REVIEWS:
        for v in json.loads(path.read_text())["labels"].values():
            labels[(v["qid"], v["arm"], v["rep"])] = v["label"]
    per_q: dict[str, list[bool]] = collections.defaultdict(list)
    dropped = []
    for path in ROWS:
        for r in json.loads(path.read_text()):
            if r["arm"] != "DENSE6":
                continue
            if "error" in r or r["route"] not in ("R4", "R5") or r["n_sources"] != 6:
                dropped.append((r["qid"], r["rep"], r.get("route"), r.get("error")))
                continue
            label = labels[(r["qid"], r["arm"], r["rep"])]
            per_q[r["qid"]].append(bool(r["refusal"]) or label in BAD_LABELS)
    if dropped:
        print(f"dropped (invalid) generations: {dropped}")
    return per_q


def main() -> None:
    per_q = load()
    short = {q: len(v) for q, v in per_q.items() if len(v) < 2 * SET}
    usable = {q: v for q, v in per_q.items() if len(v) >= 2 * SET}
    print(f"questions {len(per_q)}; usable {len(usable)}; generations/question "
          f"{sorted(collections.Counter(len(v) for v in per_q.values()).items())}; too few: {short}")

    print("\nper-question single-generation problem rate (DENSE6):")
    for q, v in sorted(usable.items()):
        print(f"  {q:28s} {sum(v):2d}/{len(v):2d} = {sum(v) / len(v):.2f}")

    rng = random.Random(SEED)
    xs, either = [], []
    for _ in range(B):
        x = y = 0
        for v in usable.values():
            draw = rng.sample(v, 2 * SET)
            a, a2 = sum(draw[:SET]) >= 2, sum(draw[SET:]) >= 2
            x += a and not a2
            y += a2 and not a
        xs.append(x)
        either.append(max(x, y))

    dist = collections.Counter(xs)
    p_x3 = sum(x >= OBSERVED_X for x in xs) / B
    print(f"\nX_AA distribution: {dict(sorted(dist.items()))}")
    print(f"mean X_AA = {statistics.mean(xs):.3f}")
    print(f"P_null(X ≥ {OBSERVED_X}) = {p_x3:.4f}")
    print(f"P_null(max(X, Y) ≥ {OBSERVED_X}) = {sum(e >= OBSERVED_X for e in either) / B:.4f}")
    print(f"P_null(X ≥ {OBSERVED_Y}) (size of the reverse count seen) = "
          f"{sum(x >= OBSERVED_Y for x in xs) / B:.4f}")
    verdict = "rule calibrated: STOP stands as evidence of harm" if p_x3 <= 0.05 else \
        "rule NOT calibrated: the STOP is not evidence of harm (prereg: re-register a two-sided test)"
    print(f"\nprereg verdict: {verdict}")

    out = RQ / "answer_probe_aa_calibration_20261004.json"
    out.write_text(json.dumps({
        "B": B, "seed": SEED, "usable_questions": len(usable), "too_few": short,
        "x_distribution": dict(sorted(dist.items())), "mean_x": statistics.mean(xs),
        "p_x_ge_3": p_x3, "p_either_ge_3": sum(e >= OBSERVED_X for e in either) / B,
        "rates": {q: sum(v) / len(v) for q, v in usable.items()},
        "verdict": verdict,
    }, ensure_ascii=False, indent=1))
    print(f"saved → {out}")


if __name__ == "__main__":
    main()
