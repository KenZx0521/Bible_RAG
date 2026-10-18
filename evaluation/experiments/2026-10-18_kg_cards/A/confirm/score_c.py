"""Score the confirmation set (confirm_A.md §6.1) -> store A_confirm/scores.json.

Per call: score_a.score_record (answer_text, truncation = format failure 0, keys_a.score_line), unchanged.
Trap rules (the items' exemption lists; keys_a is not changed):
  chain     primary: every name of every chain king plus the key's accept list (items `exempt`)
  template  stage-0 template rule: seed and answer names only (`exempt_template`; a stage-0 item has
            no such field, so its own `exempt` is used: that is the stage-0 rule)
  none      no trap rule (ctx traps emptied)
An abstaining G arm takes rep r of the item's T-rows scores (arms_c.SUBST). Item value per arm = mean
of its reps. num_ctx comes from run_meta options; a formal run (store A_confirm/) must be 131072.
"""
from __future__ import annotations

from pathlib import Path

from arms_c import FIRED, SUBST, job_id
from c_common import ARMS, ARMS_META, GEN_ARMS, ITEMS, LAYER_REF, NUM_CTX, OUT, REPS, SCORES, cc, read_json
from keys_a import item_ctx, king_lexicon
from regnal import load_ref
from score_a import score_record, seed_status

RULES = ("chain", "template", "none")
PRIMARY = "chain"
ITEM_FIELDS = ("set", "kind", "qtype", "unit", "kingdom", "pilot", "hidden", "flags")


def mean(xs):
    return sum(xs) / len(xs) if xs else None


def rule_ctx(it: dict, VR, base: set, rule: str = PRIMARY) -> dict:
    if rule not in RULES:
        raise ValueError(f"unknown trap rule {rule}")
    src = dict(it, exempt=it.get("exempt_template", it["exempt"])) if rule == "template" else it
    ctx = item_ctx(src, VR, base)
    return dict(ctx, traps=set()) if rule == "none" else ctx


def arm_rep_scores(it: dict, meta: dict, by_job: dict, ctx: dict, num_ctx: int, reps: dict = REPS) -> dict:
    out = {}
    for arm in ARMS:
        for rep in range(1, reps[arm] + 1):
            rec = by_job.get(job_id(it["id"], arm, rep))
            out[(arm, rep)] = score_record(ctx, rec, num_ctx) if rec else None
    for arm, flag in FIRED.items():
        if not meta[flag]:
            for rep in range(1, reps[arm] + 1):
                src = out.get((SUBST[arm], rep))
                out[(arm, rep)] = dict(src, substituted_from=SUBST[arm]) if src else None
    return out


def score_items(items: list[dict], meta: dict, by_job: dict, VR, num_ctx: int, reps: dict = REPS,
                rule: str = PRIMARY) -> tuple[dict, list[str]]:
    """{item id: {"reps": {"arm|r": record}, "mean": {arm: value}}} and the missing job ids."""
    base = king_lexicon(VR)
    per_item, missing = {}, []
    for it in items:
        reps_ = arm_rep_scores(it, meta[it["id"]], by_job, rule_ctx(it, VR, base, rule), num_ctx, reps)
        missing += [job_id(it["id"], a, r) for (a, r), v in reps_.items() if v is None]
        per_item[it["id"]] = {
            "reps": {f"{a}|{r}": v for (a, r), v in reps_.items()},
            "mean": {a: mean([reps_[(a, r)]["score"] for r in range(1, reps[a] + 1) if reps_[(a, r)]])
                     for a in ARMS}}
    return per_item, missing


def run_num_ctx(d: Path, tag: str) -> int:
    p = d / f"run_meta_{tag}.json"
    have = read_json(p)["options"].get("num_ctx") if p.exists() else None
    if not have:
        raise SystemExit(f"no num_ctx in {p}")
    if Path(d).resolve() == OUT.resolve() and have != NUM_CTX:
        raise SystemExit(f"{p} num_ctx {have} is not {NUM_CTX} (confirm_A.md §0)")
    return have


def trap_calls(per: dict) -> int:
    return sum(bool(v and v["trap"]) for v in per["reps"].values())


def score_all(d: Path = OUT, items_path: Path = ITEMS, reps: dict = REPS) -> dict:
    """Reads d/gen_arms.jsonl, d/arms_meta.json, d/run_meta_*.json and items; writes d/scores.json."""
    d = Path(d)
    meta = read_json(d / ARMS_META.name)
    items = [it for it in read_json(items_path)["items"] if it["id"] in meta]
    nc_arms, nc_seed = run_num_ctx(d, "arms"), run_num_ctx(d, "seeds")
    VR = load_ref(LAYER_REF)
    by_job = cc.done_jobs(d / GEN_ARMS.name)
    main, missing = score_items(items, meta, by_job, VR, nc_arms, reps, PRIMARY)
    sens = {r: score_items(items, meta, by_job, VR, nc_arms, reps, r)[0] for r in RULES if r != PRIMARY}
    per_item = {}
    for it in items:
        i = it["id"]
        per_item[i] = {**{f: it.get(f) for f in ITEM_FIELDS}, **main[i], "trap_calls": trap_calls(main[i]),
                       "sens": {r: {"mean": s[i]["mean"], "trap_calls": trap_calls(s[i])} for r, s in sens.items()}}
    doc = {"trap_rule": PRIMARY, "sensitivity_rules": [r for r in RULES if r != PRIMARY], "reps": reps,
           "num_ctx": nc_arms, "num_ctx_seeds": nc_seed, "n_items": len(items),
           "n_units": len({it.get("unit") for it in items}), "n_records": len(by_job), "missing_jobs": missing,
           "seeds": seed_status(d, items, nc_seed), "items": per_item}
    cc.write_json(d / SCORES.name, doc)
    return doc
