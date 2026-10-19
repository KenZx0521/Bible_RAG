"""Generation jobs of the rule-seed regression (prereg.md §4): G-auto's prompt per slot, arms interleaved.

Prompt: experiment A's cards_common.SYSTEM_PROMPT and build_user(context, question, card text), the
context being the question's G-auto context (items.json ``sources`` through cards_common.build_context);
a slot without a card gets build_user(..., None), experiment A's no-card (B0) form. Order: rep → set
(confirm, dev) → question → arm, the two arms of a question adjacent and their order alternating with
the question's index, so both arms run in the same session side by side. Job id RS|set|item|arm|rep.
"""
from __future__ import annotations

import rs_common as C
from rs_cards import slot_map
from rs_common import ARMS, REPS, ac, cc

SETS = ("confirm", "dev")


def job_id(set_name: str, item: str, arm: str, rep: int) -> str:
    return f"RS|{set_name}|{item}|{arm}|{rep}"


def build_jobs(doc: dict, items_by_set: dict[str, list[dict]]) -> list[dict]:
    slots = slot_map(doc)
    by_id = {s: {it["id"]: it for it in its} for s, its in items_by_set.items()}
    jobs = []
    for rep in range(1, REPS + 1):
        for set_name in [s for s in SETS if s in doc["items"]]:
            for i, iid in enumerate(doc["items"][set_name]):
                it = by_id[set_name][iid]
                ctx = cc.build_context(it["sources"])
                arms = ARMS[i % 2:] + ARMS[:i % 2]
                for arm in arms:
                    s = slots[(set_name, iid, arm, rep)]
                    jobs.append({"job_id": job_id(set_name, iid, arm, rep), "exp": "RS", "set": set_name, "item": iid,
                                 "arm": arm, "rep": rep, "kind": "gen", "seed_source": s["seed_source"],
                                 "card_sha256": s["text_sha256"], "system": cc.SYSTEM_PROMPT,
                                 "user": cc.build_user(ctx, it["question"], s["text"] or None)})
    return jobs


def jobs_sha256(jobs: list[dict]) -> str:
    """experiment A's prompts_sha256: one sha over (job_id, system, user) in order."""
    return ac.prompts_sha256(jobs)


def summary(jobs: list[dict]) -> dict:
    count: dict = {}
    for j in jobs:
        key = f"{j['set']}|{j['arm']}"
        count[key] = count.get(key, 0) + 1
    return {"n_jobs": len(jobs), "by_set_arm": count, "jobs_sha256": jobs_sha256(jobs),
            "system_prompt_sha256": C.sha256_text(cc.SYSTEM_PROMPT)}
