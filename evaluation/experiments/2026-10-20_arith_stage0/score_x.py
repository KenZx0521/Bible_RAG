"""Score the stage-0 generations (prereg §1 截斷與缺漏, §5 計分, §8 描述; K0-4 store regression).

Per call: truncated (score_a.truncated: done_reason=length or prompt+eval ≥ num_ctx) = format failure 0,
else keys_x.answer_text_x and keys_x.score_line_x. Item value per arm = correct calls / reps; a missing
rep leaves the item (and its family) undefined, never a shorter mean (§1). Family value pX_f = mean of
its item values, kept as an exact Fraction like the gaps gap2 = pG − pR and gap1 = pG − pC (GEN: pC :=
pB, §4). Truncations are counted per family and arm; ``truncation_problems`` applies §1's void rule (an
arm ≥2, or G and T-rows differing by ≥2; B0′ never counts) and ``families_excl_truncated`` gives the
values without the items holding a truncated call. The lenient score ``score_any`` (keys_x; 執行紀錄)
gets the same item, family and group tables (``families_any``, ``gaps_any``, ``groups_any``) for analyze_x's
sensitivity re-judgement. ``gen_sha256`` records the scored generation files, so a report is never made
from scores of another state of them. ``score_all`` writes nothing (the caller does).
``regress_a`` rescores experiment A's stored records with their number keys read as arithmetic keys.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from pathlib import Path

import keys_x as K
import x_common as X
from keys_a import king_lexicon
from score_a import truncated

cc = X.cc
ARM_ORDER = ("G", "T-rows", "T-canon", "B0", X.B0_BARE)
JUDGED_ARMS = ("G", "T-rows", "T-canon", "B0")
GEN_ARMS = ("gen_arms.jsonl",)
TRUNC_ARM_MAX, TRUNC_GAP_MAX = 2, 2           # §1: an arm truncated ≥2 times, or |G − T-rows| ≥2, voids the family
A_UNIT_CLASSES = {"年": ["Y"], "歲": ["A", "Y"], "日|天": ["D"], "次|代|任|位": ["C"]}


def gen_sha256(out_dir: Path | str, gen_files: tuple[str, ...] = GEN_ARMS) -> dict:
    """{file name: sha256, None when the file is absent} of the generation files scores are read from."""
    return {name: (X.sha256_file(Path(out_dir) / name) if (Path(out_dir) / name).is_file() else None)
            for name in gen_files}


def fx(f: Fraction | None, n: int | None = None) -> dict | None:
    if f is None:
        return None
    out = {"frac": str(f), "float": float(f)}
    return out if n is None else dict(out, n_items=n)


def mean_f(xs: list[Fraction | None]) -> Fraction | None:
    if not xs or any(x is None for x in xs):
        return None
    return sum(xs, Fraction(0)) / len(xs)


def subtype(item: dict) -> str:
    """§8 groups: S5 by L, F1 by chapter, else the question type (F1_5, F1_11, F3, F5 are §7-4's types)."""
    if item["qtype"] == "S5":
        return f"S5_L{item.get('L')}"
    if item["qtype"] == "F1":
        return f"F1_{item.get('chapter')}"
    return item["qtype"]


def score_record_x(item: dict, rec: dict, num_ctx: int, ctxs: dict | None = None) -> dict:
    trunc = truncated(rec, num_ctx)
    line = None if trunc else K.answer_text_x(rec.get("content", ""))
    return {**K.score_line_x(item, line, ctxs), "truncated": trunc, "answer_line": line, "job_id": rec["job_id"]}


def _jobs(jobs_meta) -> list[dict]:
    jobs = jobs_meta["jobs"] if isinstance(jobs_meta, dict) else list(jobs_meta)
    return [{k: j[k] for k in ("job_id", "item", "arm", "rep")} for j in jobs]


def _records(out_dir: Path, gen_files) -> dict:
    by_job = {}
    for name in gen_files:
        by_job.update(cc.done_jobs(Path(out_dir) / name))
    return by_job


def _arms(reps: dict) -> list[str]:
    have = {k.split("|")[0] for k in reps}
    return [a for a in ARM_ORDER if a in have] + sorted(have - set(ARM_ORDER))


def _item_values(reps: dict, field: str = "score") -> tuple[dict, dict]:
    """{arm: Fraction | None} and {arm: [correct, reps]}; None when a rep is missing."""
    means, correct = {}, {}
    for arm in _arms(reps):
        rs = [v for k, v in reps.items() if k.split("|")[0] == arm]
        if any(v is None for v in rs):
            means[arm], correct[arm] = None, None
        else:
            k = sum(v[field] for v in rs)
            means[arm], correct[arm] = Fraction(k, len(rs)), [k, len(rs)]
    return means, correct


def group_means(per_item: dict, ids: list[str], field: str = "mean") -> dict:
    """{arm: Fraction | None} over the given items (an arm absent from some item is skipped there)."""
    arms = [a for a in ARM_ORDER if any(a in per_item[i][field] for i in ids)]
    return {a: mean_f([per_item[i][field][a] for i in ids if a in per_item[i][field]]) for a in arms}


def gaps_of(means: dict, family: str) -> dict:
    pc_arm = "B0" if family == "GEN" else "T-canon"
    g, r, c = means.get("G"), means.get("T-rows"), means.get(pc_arm)
    return {"gap2": fx(None if g is None or r is None else g - r),
            "gap1": fx(None if g is None or c is None else g - c), "pC_arm": pc_arm}


def _counts(recs: list[dict]) -> dict:
    dist = Counter(k for v in recs for k in (v["distractor"] or []))
    return {"calls": len(recs), "correct": sum(v["score"] for v in recs),
            "correct_any": sum(v["score_any"] for v in recs),
            "format_fail": sum(v["format_fail"] for v in recs), "truncated": sum(v["truncated"] for v in recs),
            "hedge": sum(v["trap"] == ["hedge"] for v in recs), "trap": sum(bool(v["trap"]) for v in recs),
            "no_value": sum("no_value" in v["flags"] for v in recs), "distractor": dict(sorted(dist.items()))}


def truncation_problems(trunc: dict) -> dict:
    """{family: reasons} under §1's void rule (B0′ calls never count)."""
    out = {}
    for fam, by_arm in trunc.items():
        reasons = [f"{a} truncated {n} times" for a, n in by_arm.items() if a != X.B0_BARE and n >= TRUNC_ARM_MAX]
        d = abs(by_arm.get("G", 0) - by_arm.get("T-rows", 0))
        if d >= TRUNC_GAP_MAX:
            reasons.append(f"G and T-rows truncations differ by {d}")
        if reasons:
            out[fam] = reasons
    return out


def _fam_block(per_item: dict, by_fam: dict, field: str = "mean") -> dict:
    return {f: {a: fx(m, len(ids)) for a, m in group_means(per_item, ids, field).items()} for f, ids in by_fam.items()}


def _rep_order(j: dict) -> tuple:
    return (ARM_ORDER.index(j["arm"]) if j["arm"] in ARM_ORDER else len(ARM_ORDER), j["arm"], j["rep"])


def score_items(items: list[dict], jobs: list[dict], by_job: dict, num_ctx: int, VR=None) -> tuple[dict, list[str]]:
    """{item id: {family, qtype, subtype, reps, mean, correct, mean_any[, mean_z]}} and the missing job ids."""
    jobs_of: dict[str, list[dict]] = {}
    for j in jobs:
        jobs_of.setdefault(j["item"], []).append(j)
    names = {it["id"] for it in items if any(k["type"] == "name" for k in it["keys"])}
    base = None
    if names:
        VR = VR or X.ref_v2_view()
        base = king_lexicon(VR)
    per_item, missing = {}, []
    for it in (it for it in items if it["id"] in jobs_of):
        ctxs = K.ctxs_x(it, VR, base) if it["id"] in names else None
        reps = {}
        for j in sorted(jobs_of[it["id"]], key=_rep_order):
            rec = by_job.get(j["job_id"])
            reps[f"{j['arm']}|{j['rep']}"] = score_record_x(it, rec, num_ctx, ctxs) if rec else None
            if rec is None:
                missing.append(j["job_id"])
        means, correct = _item_values(reps)
        row = {"family": it["family"], "qtype": it["qtype"], "subtype": subtype(it), "reps": reps,
               "mean": means, "correct": correct, "mean_any": _item_values(reps, "score_any")[0]}
        if it["id"] in names:
            row["mean_z"] = _item_values(reps, "score_z")[0]
        per_item[it["id"]] = row
    return per_item, missing


def family_tables(per_item: dict, by_fam: dict) -> tuple[dict, dict, dict]:
    """Truncations and call counts per family and arm, and the values without truncated items (§1)."""
    trunc, counts, excl = {}, {}, {}
    for f, ids in by_fam.items():
        arms = list(group_means(per_item, ids))
        recs = {a: [v for i in ids for k, v in per_item[i]["reps"].items() if k.split("|")[0] == a and v] for a in arms}
        trunc[f] = {a: sum(v["truncated"] for v in recs[a]) for a in arms}
        counts[f] = {a: _counts(recs[a]) for a in arms}
        dropped = sorted(i for i in ids if any(v and v["truncated"] for k, v in per_item[i]["reps"].items()
                                               if k.split("|")[0] in JUDGED_ARMS))
        keep = [i for i in ids if i not in dropped]
        m = group_means(per_item, keep) if keep else {a: None for a in arms}
        excl[f] = {"items_dropped": dropped, "means": {a: fx(v, len(keep)) for a, v in m.items()}, "gaps": gaps_of(m, f)}
    return trunc, counts, excl


def score_all(out_dir: Path | str, items, jobs_meta, *, num_ctx: int = X.OPTIONS["num_ctx"], VR=None,
              gen_files: tuple[str, ...] = GEN_ARMS) -> dict:
    """Reads out_dir/gen_arms.jsonl; jobs_meta = the expected jobs ({job_id, item, arm, rep}, a list or
    {"jobs": [...]}); items = the items (a list or the items.json document). Returns the scores."""
    items = items["items"] if isinstance(items, dict) else list(items)
    jobs = _jobs(jobs_meta)
    unknown = sorted({j["item"] for j in jobs} - {it["id"] for it in items})
    if unknown:
        raise ValueError(f"jobs for unknown items {unknown}")
    gen_sha = gen_sha256(out_dir, gen_files)
    by_job = _records(Path(out_dir), gen_files)
    per_item, missing = score_items(items, jobs, by_job, num_ctx, VR)
    by_fam, by_sub = {}, {}
    for i, row in per_item.items():
        by_fam.setdefault(row["family"], []).append(i)
        by_sub.setdefault(row["subtype"], []).append(i)
    trunc, counts, excl = family_tables(per_item, by_fam)
    sync = {f: ids for f, ids in by_fam.items() if all("mean_z" in per_item[i] for i in ids)}
    sub_sync = {s: ids for s, ids in by_sub.items() if all("mean_z" in per_item[i] for i in ids)}
    return {
        "schema": "arith.scores.v2", "num_ctx": num_ctx, "n_items": len(per_item), "n_jobs": len(jobs),
        "n_records": len(by_job), "missing_jobs": missing, "gen_sha256": gen_sha,
        "items": {i: _item_json(row) for i, row in per_item.items()},
        "families": _fam_block(per_item, by_fam), "families_z": _fam_block(per_item, sync, "mean_z"),
        "families_any": _fam_block(per_item, by_fam, "mean_any"),
        "gaps": {f: gaps_of(group_means(per_item, ids), f) for f, ids in by_fam.items()},
        "gaps_any": {f: gaps_of(group_means(per_item, ids, "mean_any"), f) for f, ids in by_fam.items()},
        "groups": _fam_block(per_item, by_sub), "groups_z": _fam_block(per_item, sub_sync, "mean_z"),
        "groups_any": _fam_block(per_item, by_sub, "mean_any"),
        "counts": counts, "truncation": trunc, "truncation_problems": truncation_problems(trunc),
        "families_excl_truncated": excl,
        "code_sha256": {p: X.sha256_file(X.HERE / p) for p in ("keys_x.py", "score_x.py")},
    }


def _item_json(row: dict) -> dict:
    out = dict(row, mean={a: fx(m) for a, m in row["mean"].items()},
               mean_any={a: fx(m) for a, m in row["mean_any"].items()})
    if "mean_z" in row:
        out["mean_z"] = {a: fx(m) for a, m in row["mean_z"].items()}
    return out


# ---------------------------------------------------------------- K0-4: experiment A's stored records
def arith_from_number(key: dict) -> dict:
    """A keys_a number key (value + unit) as an arithmetic key of the same unit class."""
    return {"type": "arith", "value": key["value"], "classes": A_UNIT_CLASSES[key["unit"]], "ordinal": False}


def regress_a(root: Path | str = X.STORE / "reports/kg_cards_20261018", runs: tuple[str, ...] = ("A", "A_confirm")) -> dict:
    """Every stored record of an item with a number key (substituted and truncated ones skipped): the
    answer line re-read by answer_text_x, each number key rescored by final_value, the record score
    recomputed with A's trap. Lists keys and records that changed (tags run|item|arm|rep[|value])."""
    out = {"n_records": 0, "n_keys": 0, "line_diff": [], "lost": [], "gained": [], "score_down": [], "score_up": []}
    for run in runs:
        d = Path(root) / run
        items = {it["id"]: it for it in X.read_json(d / "items.json")["items"]}
        gens = cc.done_jobs(d / "gen_arms.jsonl")
        for iid, per in X.read_json(d / "scores.json")["items"].items():
            nk = [i for i, k in enumerate(items[iid]["keys"]) if k["type"] == "number"]
            if not nk:
                continue
            for rk, v in per["reps"].items():
                if not v or v.get("substituted_from") or v["truncated"]:
                    continue
                tag = f"{run}|{iid}|{rk}"
                out["n_records"] += 1
                line = K.answer_text_x(gens[v["job_id"]]["content"])
                if line != v["answer_line"]:
                    out["line_diff"].append(tag)
                hits = list(v["hits"])
                for i in nk:
                    key = items[iid]["keys"][i]
                    new = bool(K.score_line_x({"id": iid, "keys": [arith_from_number(key)]}, line)["score"])
                    out["n_keys"] += 1
                    if v["hits"][i] and not new:
                        out["lost"].append(f"{tag}|{key['value']}")
                    if new and not v["hits"][i]:
                        out["gained"].append(f"{tag}|{key['value']}")
                    hits[i] = new
                score = 0.0 if v["trap"] else sum(hits) / len(hits)
                if score < v["score"]:
                    out["score_down"].append(tag)
                elif score > v["score"]:
                    out["score_up"].append(tag)
    return out
