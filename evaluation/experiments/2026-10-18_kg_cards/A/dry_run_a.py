"""Dry run of experiment A (prereg §2 K0 準備): gold seeds stand in for stage 1, every prompt is
built, nothing calls Ollama. Writes store A/dry_run/ (jobs, metadata, per-job prompt sha256,
summary.json) and runs the scorer self-test (selftest_a)."""
from __future__ import annotations

import collections

from a_common import ITEMS, LAYER_AUTO, LAYER_REF, OUT, cc, prompts_sha256, read_json, sha256_text
from arms_a import ARMS, build_arms
from regnal import load_auto, load_ref
from seeds_a import SEED_SYSTEM, SEED_USER, parse_seeds, seed_jobs, simulated_output
from selftest_a import selftest

D = OUT / "dry_run"


def stats(xs: list[int]) -> dict:
    return {"n": len(xs), "mean": round(sum(xs) / len(xs), 1) if xs else None, "max": max(xs) if xs else None}


def seed_roundtrip(items, VR, meta) -> list:
    bad = []
    for it in items:
        want = [(VR.nodes[x]["kingdom"], VR.nodes[x]["name"]) for x in it["seeds"]]
        got = parse_seeds(simulated_output(VR, it))
        if got != want or meta[it["id"]]["ref_ids"] != it["seeds"]:
            bad.append([it["id"], want, got, meta[it["id"]]["ref_ids"]])
    return bad


def dry_run() -> dict:
    items, VR, VA = read_json(ITEMS)["items"], load_ref(LAYER_REF), load_auto(LAYER_AUTO)
    sj = seed_jobs(items)
    jobs, meta = build_arms(items, {it["id"]: simulated_output(VR, it) for it in items}, VA, VR)
    for name, obj in (("seed_jobs.json", sj), ("arms_jobs.json", jobs), ("arms_meta.json", meta)):
        cc.write_json(D / name, obj)
    (D / "prompt_sha256.tsv").write_text("".join(f"{j['job_id']}\t{sha256_text(j['system'] + chr(0) + j['user'])}\n"
                                                 for j in sj + jobs), encoding="utf-8")
    by_arm = collections.Counter(j["arm"] for j in jobs)
    summary = {
        "label": "dry run with gold seeds (no Ollama)", "n_seed_jobs": len(sj), "n_arm_jobs": len(jobs),
        "n_jobs_total": len(sj) + len(jobs), "arm_jobs_by_arm": dict(by_arm),
        "aux_chars": {a: stats([m["aux_chars"][a] for m in meta.values() if m["aux_chars"][a] is not None]) for a in ARMS},
        "user_chars": {a: stats([len(j["user"]) for j in jobs if j["arm"] == a]) for a in ARMS},
        "seed_user_chars": stats([len(j["user"]) for j in sj]),
        "user_chars_max_all": max(len(j["user"]) for j in sj + jobs),
        "g_auto_abstain": [i for i, m in meta.items() if not m["g_auto_fired"]],
        "g_ref_abstain": [i for i, m in meta.items() if not m["g_ref_fired"]],
        "a_hit_gold_seeds": [i for i, m in meta.items() if m["a_hit"]],
        "t_rows_empty": [i for i, m in meta.items() if m["t_rows_empty"]],
        "rows_dropped": {i: m["auto_rows_dropped"] for i, m in meta.items() if m["auto_rows_dropped"]},
        "a_strict_gold_seeds": [i for i, m in meta.items() if m["a_strict"]],
        "tcanon_basis_missing": {i: m["tcanon_basis_missing"] for i, m in meta.items() if m["tcanon_basis_missing"]},
        "tcanon_centers": {i: m["tcanon"]["centers"] for i, m in meta.items()},
        "seed_roundtrip_mismatch": seed_roundtrip(items, VR, meta), "scorer_selftest": selftest(items, VR),
        "sha256": {"seed_system": sha256_text(SEED_SYSTEM), "seed_user_template": sha256_text(SEED_USER),
                   "system_prompt": sha256_text(cc.SYSTEM_PROMPT), "user_template": sha256_text(cc.USER_TEMPLATE),
                   "seed_prompts": prompts_sha256(sj), "arm_prompts": prompts_sha256(jobs)},
    }
    cc.write_json(D / "summary.json", summary)
    print({k: summary[k] for k in ("n_seed_jobs", "n_arm_jobs", "n_jobs_total", "user_chars_max_all")})
    return summary
