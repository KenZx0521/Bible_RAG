"""Stage 2 of the confirmation set (confirm_A.md §5): arm prompts, fork of arms_a.arm_jobs with 3 reps.

The arms are stage-0's (arms_a.item_arms, unchanged); only the rep loop changes: every arm, G-ref
included, runs reps 1–3. Order: rep → item → arm, the arm order rotated by item index (as A0). A G arm
whose engine writes no derivation line abstains (no job); the scorer substitutes rep r of the item's
T-rows for G-auto rep r and for G-ref rep r (SUBST). Job ids keep the stage-0 form A|item|arm|rep.
"""
from __future__ import annotations

from arms_a import ARMS, item_arms
from c_common import REPS, cc
from keys_a import king_lexicon
from regnal import map_auto_to_ref

SUBST = {"G-auto": "T-rows", "G-ref": "T-rows"}   # abstaining arm <- same rep of this arm
FIRED = {"G-auto": "g_auto_fired", "G-ref": "g_ref_fired"}


def job_id(item: str, arm: str, rep: int) -> str:
    return f"A|{item}|{arm}|{rep}"


def arm_jobs(items: list[dict], built: dict, reps: dict = REPS) -> list[dict]:
    jobs = []
    for rep in range(1, max(reps.values()) + 1):
        for i, it in enumerate(items):
            arms = [a for a in ARMS if reps[a] >= rep]
            arms = arms[i % len(arms):] + arms[:i % len(arms)]
            ctx = cc.build_context(it["sources"])
            for arm in arms:
                block = built[it["id"]]["blocks"][arm]
                if block is None:
                    continue
                jobs.append({"job_id": job_id(it["id"], arm, rep), "exp": "A", "item": it["id"], "arm": arm,
                             "rep": rep, "kind": "gen", "system": cc.SYSTEM_PROMPT,
                             "user": cc.build_user(ctx, it["question"], block or None)})
    return jobs


def build_arms(items: list[dict], seed_text: dict, VA, VR, reps: dict = REPS) -> tuple[list[dict], dict]:
    """seed_text: item id -> stage-1 content ("" = no usable seed output)."""
    base, a2r = king_lexicon(VR), map_auto_to_ref(VA, VR)
    built = {it["id"]: item_arms(it, seed_text.get(it["id"]), VA, VR, base, a2r) for it in items}
    return arm_jobs(items, built, reps), {k: v["meta"] for k, v in built.items()}


def expected_jobs(meta: dict, reps: dict = REPS) -> int:
    """Arm calls: Σ reps over arms minus the abstaining G arms' reps."""
    full = sum(reps.values()) * len(meta)
    return full - sum(reps[a] for m in meta.values() for a, f in FIRED.items() if not m[f])
