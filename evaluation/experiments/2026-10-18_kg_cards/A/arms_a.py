"""Stage 2 of experiment A (prereg §2 臂, 次數): arm prompts built from the stage-1 seed parse.

Arms G-auto, T-canon, T-rows, B0 run reps 1–2, G-ref rep 1. Order: rep → item → arm, the arm
order rotated by item index. A G arm whose engine writes no derivation line abstains (no job;
the scorer reuses that item's T-rows scores). Every prompt is cards_common.build_user under
cards_common.SYSTEM_PROMPT; B0 has no auxiliary section. Metadata only (never in a prompt):
a_hit (prereg a), a_strict and the T-canon window's cover of the key basis verses (descriptive).
"""
from __future__ import annotations

from a_common import cc
from engine import cards, resolve
from keys_a import covered, item_ctx, king_lexicon
from regnal import map_auto_to_ref
from seeds_a import parse_seeds
from tcanon import formula_verses, tcanon

ARMS = ("G-auto", "T-canon", "T-rows", "B0", "G-ref")
REPS = {"G-auto": 2, "T-canon": 2, "T-rows": 2, "B0": 2, "G-ref": 1}
EMPTY = {"g_block": None, "t_block": "", "rows": [], "rows_read": [], "rows_dropped": [], "lines": [], "payloads": [],
         "tags": []}


def resolve_all(V, seeds, question) -> list[str]:
    ids = [resolve(V, kd, nm, question) for kd, nm in seeds]
    return list(dict.fromkeys(x for x in ids if x))


def strict_hit(it: dict, ga: dict, ctx: dict, a2r: dict) -> bool:
    """The asked line (it['asked'] on the item's first reference seed) alone covers every key."""
    rel, k = it["asked"][0], (it["asked"][1] if len(it["asked"]) > 1 else None)
    pays = [p for (r, x, kk), p in zip(ga["tags"], ga["payloads"])
            if r == rel and kk == k and a2r.get(x) == it["seeds"][0]]
    return bool(pays) and all(covered(ctx, key, pays) for key in it["keys"])


def tcanon_cover(it: dict, tc: dict) -> list[str]:
    """Key basis verses that are 1–2 Kings formula verses but lie outside the T-canon window."""
    formula = {k for k, _t in formula_verses()}
    need = dict.fromkeys(v for key in it["keys"] for v in key["basis"] if v in formula)
    return [v for v in need if v not in set(tc["verses"])]


def item_arms(it: dict, seed_text: str | None, VA, VR, base: set, a2r: dict) -> dict:
    """Blocks per arm (None = abstain) and the metadata the analysis needs (a, aux chars)."""
    seeds = parse_seeds(seed_text or "")
    q = it["question"]
    auto_ids, ref_ids = resolve_all(VA, seeds, q), resolve_all(VR, seeds, q)
    ga = cards(VA, auto_ids) if auto_ids else EMPTY
    gr = cards(VR, ref_ids) if ref_ids else EMPTY
    tc = tcanon(seeds, q)
    blocks = {"G-auto": ga["g_block"], "T-canon": tc["block"], "T-rows": ga["t_block"], "B0": "",
              "G-ref": gr["g_block"]}
    ctx = item_ctx(it, VR, base)
    fired = ga["g_block"] is not None
    cov = [covered(ctx, k, ga["payloads"]) for k in it["keys"]] if fired else [False] * len(it["keys"])
    ref_cov = [covered(ctx, k, gr["payloads"]) for k in it["keys"]] if gr["g_block"] else []
    missing = tcanon_cover(it, tc)
    return {"blocks": blocks, "meta": {
        "item": it["id"], "seed_output": seed_text, "seeds_parsed": seeds, "auto_ids": auto_ids, "ref_ids": ref_ids,
        "g_auto_fired": fired, "g_auto_keys_covered": cov, "a_hit": fired and all(cov),
        "a_strict": fired and strict_hit(it, ga, ctx, a2r),
        "g_ref_fired": gr["g_block"] is not None, "g_ref_keys_covered": ref_cov,
        "auto_rows": ga["rows"], "auto_rows_dropped": ga["rows_dropped"], "auto_lines": ga["lines"],
        "auto_tags": ga["tags"], "ref_rows": gr["rows"], "ref_lines": gr["lines"],
        "tcanon": {k: v for k, v in tc.items() if k != "block"},
        "tcanon_basis_missing": missing, "tcanon_basis_covered": not missing,
        "aux_chars": {a: (len(b) if b is not None else None) for a, b in blocks.items()},
        "t_rows_empty": not ga["t_block"]}}


def arm_jobs(items: list[dict], built: dict) -> list[dict]:
    jobs = []
    for rep in (1, 2):
        for i, it in enumerate(items):
            arms = [a for a in ARMS if REPS[a] >= rep]
            arms = arms[i % len(arms):] + arms[:i % len(arms)]
            ctx = cc.build_context(it["sources"])
            for arm in arms:
                block = built[it["id"]]["blocks"][arm]
                if block is None:
                    continue
                jobs.append({"job_id": f"A|{it['id']}|{arm}|{rep}", "exp": "A", "item": it["id"], "arm": arm,
                             "rep": rep, "kind": "gen", "system": cc.SYSTEM_PROMPT,
                             "user": cc.build_user(ctx, it["question"], block or None)})
    return jobs


def build_arms(items: list[dict], seed_text: dict, VA, VR) -> tuple[list[dict], dict]:
    """seed_text: item id -> stage-1 content ("" = no usable seed output)."""
    base, a2r = king_lexicon(VR), map_auto_to_ref(VA, VR)
    built = {it["id"]: item_arms(it, seed_text.get(it["id"]), VA, VR, base, a2r) for it in items}
    return arm_jobs(items, built), {k: v["meta"] for k, v in built.items()}
