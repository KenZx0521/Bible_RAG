"""Arm blocks and generation jobs of the ordered-chain arithmetic stage-0 (prereg §1 順序, §4 臂; K0-6). CPU only.

Per item: G = engine_x.card's g_block, T-rows = its t_block (the same kept rows, no derived lines);
T-canon (DYN, S6, SYNC) = experiment A's tcanon.tcanon(seed_names, question) block; B0 = no auxiliary
block; B0p (B0′, GEN only) = no block and no passages, cards_common.build_user("", question, ""). Every
other arm's base context is cards_common.build_context(item sources), as experiment A builds it, under
cards_common.SYSTEM_PROMPT (both imported unchanged, so the auxiliary label is the same for every arm).
Arms and reps: x_common.ARMS[family] (+ B0p for GEN) × x_common.REPS_BY_ARM. Order: rep → item → arm,
the arm order rotated by the item's index — confirm/arms_c.arm_jobs's rule, mirrored here because that
function takes A's arm list and A's job ids. Job ids X|item|arm|rep; 588 jobs.
Meta per item (never in a prompt): block chars per arm, covered, tcanon_complete as items_x computed it
(and whether this window agrees), the T-canon window, dropped rows and lines, prompt sha256 per arm.
Nothing here calls an LLM or writes a file.
"""
from __future__ import annotations

from collections import Counter

import engine_x as E
import tcanon as TC
import x_common as X

cc = X.cc
EXP = "X"
B0P = X.B0_BARE
SCHEMA_CARDS = "arith.cards.v1"


def arm_order(family: str) -> tuple[str, ...]:
    """The family's arms in base order (prereg §4; B0′ only for GEN)."""
    return X.ARMS[family] + ((B0P,) if family == "GEN" else ())


def job_id(item: str, arm: str, rep: int) -> str:
    return f"{EXP}|{item}|{arm}|{rep}"


def n_expected(items: list[dict]) -> int:
    return sum(X.REPS_BY_ARM[a] for it in items for a in arm_order(it["family"]))


# ---------------------------------------------------------------- cards (engine + T-canon)
def tcanon_of(item: dict) -> dict | None:
    """Experiment A's canonical window for the item's seeds (dynasty only; GEN has no T-canon, §4)."""
    if item["family"] == "GEN":
        return None
    return TC.tcanon([tuple(s) for s in item["seed_names"]], item["question"])


def build_cards(items: list[dict], gen: dict, r4=None) -> dict[str, dict]:
    """{item id: engine_x.card + "tcanon"} for every item."""
    r4 = r4 if r4 is not None else X.r4_view()
    return {it["id"]: {**E.card(it, r4=r4, gen=gen), "tcanon": tcanon_of(it)} for it in items}


def blocks(item: dict, cd: dict) -> dict[str, str]:
    """{arm: auxiliary block} of the item's arms ("" = none)."""
    out = {"G": cd["g_block"], "T-rows": cd["t_block"], "B0": ""}
    if "T-canon" in arm_order(item["family"]):
        out["T-canon"] = (cd.get("tcanon") or {}).get("block", "")
    if item["family"] == "GEN":
        out[B0P] = ""
    return {a: out[a] for a in arm_order(item["family"])}


def user_prompt(item: dict, arm: str, block: str, context: str) -> str:
    if arm == B0P:
        return cc.build_user("", item["question"], "")
    return cc.build_user(context, item["question"], block or None)


def prompt_sha(system: str, user: str) -> str:
    return X.sha256_text(system + "\0" + user)


# ---------------------------------------------------------------- jobs and meta
def arm_jobs(items: list[dict], cards: dict[str, dict], reps: dict = X.REPS_BY_ARM) -> list[dict]:
    jobs = []
    for rep in range(1, max(reps.values()) + 1):
        for i, it in enumerate(items):
            arms = [a for a in arm_order(it["family"]) if reps[a] >= rep]
            arms = arms[i % len(arms):] + arms[:i % len(arms)]
            ctx, bl = cc.build_context(it["sources"]), blocks(it, cards[it["id"]])
            for arm in arms:
                jobs.append({"job_id": job_id(it["id"], arm, rep), "exp": EXP, "item": it["id"],
                             "family": it["family"], "arm": arm, "rep": rep, "kind": "gen",
                             "system": cc.SYSTEM_PROMPT, "user": user_prompt(it, arm, bl[arm], ctx)})
    return jobs


def item_meta(item: dict, cd: dict) -> dict:
    bl, ctx = blocks(item, cd), cc.build_context(item["sources"])
    tc = cd.get("tcanon")
    tc_missing = None if tc is None else [v for v in item.get("tc_basis") or [] if v not in set(tc["verses"])]
    users = {a: user_prompt(item, a, b, ctx) for a, b in bl.items()}
    return {"item": item["id"], "family": item["family"], "qtype": item["qtype"], "covered": cd["covered"],
            "nested": item["nested"], "units_touched": item["units_touched"],
            "block_chars": {a: len(b) for a, b in bl.items()}, "user_chars": {a: len(u) for a, u in users.items()},
            "prompt_sha256": {a: prompt_sha(cc.SYSTEM_PROMPT, u) for a, u in users.items()},
            "rows": cd["rows"], "n_lines": len(cd["lines"]), "dropped_rows": cd["dropped_rows"],
            "dropped_lines": cd["dropped_lines"], "over_cap": cd["over_cap"],
            "tcanon_complete": item.get("tcanon_complete"), "tcanon_missing": item.get("tcanon_missing"),
            "tcanon_agrees": None if tc is None else tc_missing == item.get("tcanon_missing"),
            "tcanon": None if tc is None else {k: v for k, v in tc.items() if k != "block"}}


def build_arms(items: list[dict], cards: dict[str, dict]) -> tuple[list[dict], dict]:
    """(the 588 jobs in run order, {item id: meta})."""
    return arm_jobs(items, cards), {it["id"]: item_meta(it, cards[it["id"]]) for it in items}


def prompts_sha256(jobs: list[dict]) -> str:
    """Experiment A's sha over (job_id, system, user) in order."""
    return X.ac.prompts_sha256(jobs)


def summary(jobs: list[dict]) -> dict:
    return {"n_jobs": len(jobs), "by_family_arm": dict(sorted(Counter(f"{j['family']}|{j['arm']}" for j in jobs).items())),
            "prompts_sha256": prompts_sha256(jobs), "system_prompt_sha256": X.sha256_text(cc.SYSTEM_PROMPT),
            "user_template_sha256": X.sha256_text(cc.USER_TEMPLATE)}


# ---------------------------------------------------------------- K0-6 and the job list
def card_problems(items: list[dict], cards: dict[str, dict], meta: dict, cap: int = X.CAP_CHARS) -> dict[str, list[str]]:
    """K0-6 per item (empty = ok): engine_x.check_card (G, T-rows ≤ cap, core rows kept, T-rows = G's rows),
    every arm's block ≤ cap, a T-canon window found, and this window's tcanon_complete equal to items_x's."""
    out = {}
    for it in items:
        cd, m = cards[it["id"]], meta[it["id"]]
        bad = E.check_card(it, cd, cap)
        bad += [f"{a} block {n} chars > {cap}" for a, n in m["block_chars"].items() if n > cap and a not in ("G", "T-rows")]
        if "T-canon" in m["block_chars"]:
            if not m["block_chars"]["T-canon"]:
                bad.append("T-canon window empty (no seed centre found)")
            if not m["tcanon_agrees"]:
                bad.append(f"T-canon window misses {m['tcanon_missing']} by items_x but not by this window")
        if bad:
            out[it["id"]] = bad
    return out


def job_problems(items: list[dict], jobs: list[dict]) -> list[str]:
    """The job list (prereg §1, §4): 588 unique ids, every item × arm × rep once, one system prompt."""
    out = []
    want = {job_id(it["id"], a, r) for it in items for a in arm_order(it["family"])
            for r in range(1, X.REPS_BY_ARM[a] + 1)}
    ids = [j["job_id"] for j in jobs]
    if len(ids) != len(set(ids)):
        out.append("duplicate job ids")
    if set(ids) != want:
        out.append(f"jobs are not item × arm × rep: {len(set(ids) - want)} extra, {len(want - set(ids))} missing")
    if len(jobs) != n_expected(items):
        out.append(f"{len(jobs)} jobs, expected {n_expected(items)}")
    if any(j["system"] != cc.SYSTEM_PROMPT for j in jobs):
        out.append("a job with another system prompt")
    return out
