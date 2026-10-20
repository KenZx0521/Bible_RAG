"""Score the GEN confirmation-set generations (prereg §6, §4.1–§4.2 reuse, §4.5 void counts, §1.5-8). CPU only.

Per call: truncated (experiment A's score_a.truncated rule, copied: done_reason length, or prompt + eval tokens
≥ num_ctx) or no answer line = 0; otherwise stage-0's keys_x.answer_text_x and keys_x.score_line_x on the item's
key (items_x.arith_key(gold, ["A", "Y"], basis): 歲 first, 年 when the line has no 歲; ordinal false; a bare
number only after 「＝」 or alone; Chinese numerals by cn2int_x), both imported unchanged. Reuse: a rule
abstention's G and T-rows rep r is B0's rep r (§4.2); a gold-seed item's G-ref rep r is G's (§4.1); a reused
record carries ``substituted_from``. Item value per arm = mean of its 3 reps, an exact Fraction; a missing rep
leaves it undefined, never a shorter mean. ``score_any`` (keys_x's lenient score, §6 sensitivity) gets the same
item table (``mean_any``). Per arm, over the calls made (a reused record is not a call): truncations, calls over
120 s (the prod client's timeout), format failures, hedges. ``truncation_problems`` is §4.5's void rule: an arm
truncated ≥ 2 times (every arm, G-ref included) or G and T-rows differing by ≥ 2. ``gen_sha256`` records the
scored generation file, so a report is never made from another state of it. ``score_all`` writes nothing.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import arms_g as A
import g_common as GC

K = A.S.keys_x
cc = A.cc
GEN = GC.RUN_GEN
TRUNC_ARM_MAX, TRUNC_GAP_MAX = GC.TRUNC_ARM_MAX, GC.TRUNC_GAP_MAX   # §4.5
SLOW_S = 120.0                                    # §1.5-8, §4.3: prod client's timeout


def truncated(rec: dict, num_ctx: int | None) -> bool:
    """Experiment A's score_a.truncated, copied (the rule stage-0's score_x imports)."""
    if rec.get("done_reason") == "length":
        return True
    used = (rec.get("prompt_eval_count") or 0) + (rec.get("eval_count") or 0)
    return bool(num_ctx) and used >= num_ctx


def fx(f: Fraction | None) -> dict | None:
    return None if f is None else {"frac": str(f), "float": float(f)}


def frac(v) -> Fraction | None:
    """A score value ({"frac": …}), Fraction, int or "a/b"; floats are refused (exactness)."""
    if v is None:
        return None
    if isinstance(v, dict):
        return Fraction(v["frac"])
    if isinstance(v, (bool, float)) or not isinstance(v, (Fraction, int, str)):
        raise TypeError(f"{v!r}: exact values only")
    return Fraction(v)


def gen_sha256(out_dir: Path | str) -> str | None:
    p = Path(out_dir) / GEN
    return GC.sha256_file(p) if p.is_file() else None


def score_record(item: dict, rec: dict, num_ctx: int) -> dict:
    trunc = truncated(rec, num_ctx)
    line = None if trunc else K.answer_text_x(rec.get("content", ""))
    return {**K.score_line_x(item, line), "truncated": trunc, "answer_line": line, "job_id": rec["job_id"],
            "elapsed_s": rec.get("elapsed_s")}


def item_reps(item: dict, meta: dict, by_job: dict, num_ctx: int) -> tuple[dict, list[str]]:
    """{"arm|r": scored record | None} with the reuse applied, and the job ids missing."""
    reps, missing = {}, []
    for arm in meta["jobs"]:
        for r in range(1, A.REPS + 1):
            jid = A.job_id(item["id"], arm, r)
            rec = by_job.get(jid)
            reps[f"{arm}|{r}"] = score_record(item, rec, num_ctx) if rec else None
            if rec is None:
                missing.append(jid)
    for arm, src in meta["reuse"].items():
        for r in range(1, A.REPS + 1):
            v = reps[f"{src}|{r}"]
            reps[f"{arm}|{r}"] = None if v is None else dict(v, substituted_from=src)
    return {f"{a}|{r}": reps[f"{a}|{r}"] for a in A.ARMS for r in range(1, A.REPS + 1)}, missing


def arm_means(reps: dict, field: str = "score") -> dict[str, Fraction | None]:
    out = {}
    for arm in A.ARMS:
        vs = [reps[f"{arm}|{r}"] for r in range(1, A.REPS + 1)]
        out[arm] = None if any(v is None for v in vs) else Fraction(sum(v[field] for v in vs), len(vs))
    return out


def calls(rows: dict, arm: str) -> list[dict]:
    """The calls an arm made (reused records left out)."""
    return [v for r in rows.values() for k, v in r["reps"].items()
            if k.split("|")[0] == arm and v and "substituted_from" not in v]


def arm_counts(rows: dict) -> dict[str, dict]:
    out = {}
    for arm in A.ARMS:
        cs = calls(rows, arm)
        out[arm] = {"calls": len(cs), "correct": sum(v["score"] for v in cs), "correct_any": sum(v["score_any"] for v in cs),
                    "format_fail": sum(v["format_fail"] for v in cs), "truncated": sum(v["truncated"] for v in cs),
                    "over_120s": sum((v.get("elapsed_s") or 0) > SLOW_S for v in cs),
                    "hedge": sum(v["trap"] == ["hedge"] for v in cs), "no_value": sum("no_value" in v["flags"] for v in cs)}
    return out


def truncation_problems(trunc: dict[str, int]) -> list[str]:
    """§4.5: an arm truncated ≥ 2 times, or G and T-rows truncation counts differing by ≥ 2."""
    out = [f"{a} truncated {n} times" for a, n in trunc.items() if n >= TRUNC_ARM_MAX]
    gap = abs(trunc.get("G", 0) - trunc.get("T-rows", 0))
    return out + ([f"G and T-rows truncations differ by {gap}"] if gap >= TRUNC_GAP_MAX else [])


def _item_json(it: dict, reps: dict) -> dict:
    keep = ("sid", "qtype", "chapter", "stratum", "d", "x", "y", "pair", "persons", "marker_required", "homonym",
            "shem_x", "dup_gold")
    return {**{k: it[k] for k in keep}, "unit": it["id"], "reps": reps,
            "mean": {a: fx(m) for a, m in arm_means(reps).items()},
            "mean_any": {a: fx(m) for a, m in arm_means(reps, "score_any").items()}}


def score_all(out_dir: Path | str, items: list[dict], meta: dict, jobs: list[dict], *, num_ctx: int) -> dict:
    """Reads out_dir/gen_arms.jsonl; items and meta are the build's (arms_g), jobs the run's job list."""
    want = {j["job_id"] for j in jobs}
    by_job = {k: v for k, v in cc.done_jobs(Path(out_dir) / GEN).items() if k in want}
    rows, missing = {}, []
    for it in items:
        reps, miss = item_reps(it, meta[it["id"]], by_job, num_ctx)
        rows[it["id"]], missing = _item_json(it, reps), missing + miss
    stray = sorted(want - {A.job_id(it["id"], a, r) for it in items for a in meta[it["id"]]["jobs"]
                           for r in range(1, A.REPS + 1)})
    if stray:
        raise ValueError(f"{len(stray)} jobs of no item arm")
    counts = arm_counts(rows)
    trunc = {a: c["truncated"] for a, c in counts.items()}
    means = {a: [frac(r["mean"][a]) for r in rows.values()] for a in A.ARMS}
    return {"schema": "gen_confirm.scores.v1", "num_ctx": num_ctx, "n_items": len(rows), "n_jobs": len(jobs),
            "n_records": len(by_job), "missing_jobs": missing, "gen_sha256": gen_sha256(out_dir), "items": rows,
            "arm_means": {a: fx(sum(v, Fraction(0)) / len(v)) if v and None not in v else None for a, v in means.items()},
            "counts": counts, "truncation": trunc, "truncation_problems": truncation_problems(trunc),
            "code_sha256": {p: GC.sha256_file(GC.HERE / p) for p in ("score_g.py", "arms_g.py")}
            | {"keys_x.py": GC.sha256_file(GC.STAGE0_DIR / "keys_x.py")}}
