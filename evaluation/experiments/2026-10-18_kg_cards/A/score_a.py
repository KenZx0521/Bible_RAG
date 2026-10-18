"""Score experiment A generations (prereg §1 計分前處理, §2 指標; appendix A.5) -> d/scores.json.

Answer text: NFKC, Markdown symbols removed, then the text after the last 「答案：」 up to the first
blank line (leading list markers dropped, lines joined by ;). None = format failure, 0. A call is
truncated (format failure) when done_reason=length or prompt_eval_count+eval_count ≥ num_ctx;
num_ctx comes from run_meta_arms.json options (or --num-ctx = /api/ps context_length for a smoke
run without num_ctx). keys_a.score_line gives the key_score. An abstaining G arm takes the item's
T-rows scores (G-auto rep r <- T-rows rep r, G-ref <- rep 1).
"""
from __future__ import annotations

import re
import unicodedata

from a_common import ARMS_META, GEN_ARMS, GEN_SEED, ITEMS, LAYER_REF, OUT, SCORES, cc, read_json
from arms_a import ARMS, REPS
from keys_a import item_ctx, king_lexicon, score_line
from regnal import load_ref

ANS = re.compile(r"答案\s*[:：]")
MD = re.compile(r"[*_#`>]")  # the Markdown symbols cards_common.norm removes
LIST = re.compile(r"^(?:[-+•·]|[0-9]{1,2}[.、)]|\([0-9]{1,2}\))")


def answer_text(content: str) -> str | None:
    text = MD.sub("", unicodedata.normalize("NFKC", content or ""))
    ms = list(ANS.finditer(text))
    if not ms:
        return None
    lines = []
    for ln in text[ms[-1].end():].splitlines():
        s = cc.norm(LIST.sub("", ln.strip()))
        if s:
            lines.append(s)
        elif lines:
            break
    return ";".join(lines) or None


def truncated(rec: dict, num_ctx: int | None) -> bool:
    if rec.get("done_reason") == "length":
        return True
    used = (rec.get("prompt_eval_count") or 0) + (rec.get("eval_count") or 0)
    return bool(num_ctx) and used >= num_ctx


def run_num_ctx(d, tag: str, cli: int | None) -> int:
    """num_ctx of a run: run_meta options, else the CLI value (smoke without num_ctx); refuse otherwise."""
    p = d / f"run_meta_{tag}.json"
    have = read_json(p)["options"].get("num_ctx") if p.exists() else None
    if have and cli and have != cli:
        raise SystemExit(f"--num-ctx {cli} differs from {p} num_ctx {have}")
    if d.resolve() == OUT.resolve() and not have:
        raise SystemExit(f"formal run without num_ctx in {p}: prereg §1 needs an explicit num_ctx")
    if not (have or cli):
        raise SystemExit(f"no num_ctx for {tag}: pass --num-ctx (/api/ps context_length of the smoke)")
    return have or cli


def score_record(ctx: dict, rec: dict, num_ctx: int) -> dict:
    trunc = truncated(rec, num_ctx)
    line = None if trunc else answer_text(rec.get("content", ""))
    return {**score_line(ctx, line), "truncated": trunc, "answer_line": line, "job_id": rec["job_id"]}


def arm_rep_scores(it, meta, by_job, ctx, num_ctx) -> dict:
    out = {}
    for arm in ARMS:
        for rep in range(1, REPS[arm] + 1):
            rec = by_job.get(f"A|{it['id']}|{arm}|{rep}")
            out[(arm, rep)] = score_record(ctx, rec, num_ctx) if rec else None
    for arm, fired in (("G-auto", meta["g_auto_fired"]), ("G-ref", meta["g_ref_fired"])):
        if not fired:
            for rep in range(1, REPS[arm] + 1):
                src = out.get(("T-rows", rep))
                out[(arm, rep)] = dict(src, substituted_from="T-rows") if src else None
    return out


def seed_status(d, items, num_ctx: int) -> dict:
    recs = cc.done_jobs(d / GEN_SEED.name)
    got = {it["id"]: recs.get(f"A|{it['id']}|seed|1") for it in items}
    return {"missing": sorted(i for i, r in got.items() if r is None),
            "truncated": sorted(i for i, r in got.items() if r and truncated(r, num_ctx))}


def score_all(num_ctx: int | None = None, d=OUT) -> dict:
    """Reads d/gen_arms.jsonl, d/arms_meta.json, d/run_meta_*.json; writes d/scores.json."""
    meta = read_json(d / ARMS_META.name)
    items = [it for it in read_json(ITEMS)["items"] if it["id"] in meta]
    nc_arms, nc_seed = run_num_ctx(d, "arms", num_ctx), run_num_ctx(d, "seeds", num_ctx)
    VR = load_ref(LAYER_REF)
    base = king_lexicon(VR)
    by_job = cc.done_jobs(d / GEN_ARMS.name)
    per_item, missing = {}, []
    for it in items:
        reps = arm_rep_scores(it, meta[it["id"]], by_job, item_ctx(it, VR, base), nc_arms)
        missing += [f"A|{it['id']}|{a}|{r}" for (a, r), v in reps.items() if v is None]
        per_item[it["id"]] = {
            "set": it["set"], "kind": it["kind"],
            "reps": {f"{a}|{r}": v for (a, r), v in reps.items()},
            "mean": {a: mean([reps[(a, r)]["score"] for r in range(1, REPS[a] + 1) if reps[(a, r)]])
                     for a in ARMS}}
    doc = {"num_ctx": nc_arms, "num_ctx_seeds": nc_seed, "n_items": len(items), "n_records": len(by_job),
           "missing_jobs": missing, "seeds": seed_status(d, items, nc_seed), "items": per_item}
    cc.write_json(d / SCORES.name, doc)
    return doc


def trunc_report(d, num_ctx: int | None) -> dict:
    """K0-3 helper (CPU): truncation counts of every call in d (seed and arm outputs)."""
    out = {}
    for name in (GEN_SEED.name, GEN_ARMS.name):
        recs = list(cc.done_jobs(d / name).values())
        used = [(r.get("prompt_eval_count") or 0) + (r.get("eval_count") or 0) for r in recs]
        out[name] = {"n": len(recs), "truncated": sum(truncated(r, num_ctx) for r in recs),
                     "done_reason_length": sum(r.get("done_reason") == "length" for r in recs),
                     "max_prompt_plus_eval": max(used) if used else None,
                     "max_prompt_eval": max((r.get("prompt_eval_count") or 0 for r in recs), default=None)}
    return {"num_ctx_or_context_length": num_ctx, **out}


def mean(xs):
    return sum(xs) / len(xs) if xs else None
