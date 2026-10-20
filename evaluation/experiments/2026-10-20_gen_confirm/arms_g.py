"""Arms, prompts and generation jobs of the GEN confirmation set (prereg §4.1–§4.4, §3.9). CPU only.

One item per frozen question, in the frozen file's order, which the contract makes pool sid ascending (the
order of every d vector of §1.3). Base context, the same for every arm: stage-0's frozen ``items_x.gen_item``
for the slot (the pericope of X's begetting verse, ps:gen.5.1 or ps:gen.11.10, through
cards_common.build_context) with only the question swapped for the frozen one; the key
(``items_x.arith_key(gold, ["A", "Y"], basis)``) and the distractors are stage-0's. Prompt =
cards_common.SYSTEM_PROMPT + cards_common.build_user(context, question, aux), both imported unchanged, exactly
as stage-0's arms_x builds B0, G and T-rows. Arms (§4.1), 3 reps each:

  G       ``gencard.card(question, L).g_block``: the rule seeds, stage-0's rows and derived lines, fit to 900;
  T-rows  the same card's ``t_block`` (its kept rows, no derived lines);
  B0      no auxiliary block;
  G-ref   ``gencard.card_for_seeds(gold pair, L).g_block``, run only when the rule seeds are not the gold pair
          (wrong, or the rule abstained); otherwise it reuses G, whose prompt it would equal byte for byte.

A rule abstention (§4.2) has no card: no G and no T-rows job; scoring reuses B0's rep r for both (their prompts
would be B0's byte for byte, so d1 = d2 = 0). Order: rep → item → arm with the arm order ARMS rotated by the
item's index and an arm without a job skipped after the rotation (confirm/arms_c.arm_jobs's rule, written here
because that function takes A's arm list and job ids). Job ids GC|sid|arm|rep.
Meta per item (never in a prompt): the rule's outcome (fired, seeds, reason, step, shape), seeds_ok, carded,
covered (Card.covers(gold)), wrong (a card without the gold), the reuse map, block and prompt characters, the
prompt sha256 per arm (a reused arm: the prompt it would have had) and the context sha256.

questions_frozen.json (the contract this module reads; F2 step 4 writes it): {"schema": FROZEN_SCHEMA,
"n_target": int, "questions": [{"sid", "question", ...}] in strictly ascending pool sid order, "attrition":
{cause: [sid, ...]} for the six causes of §1.2 (ATTRITION)}; the frozen sids and the six lists partition the
pool; against order.json's writing order (a permutation of the pool), "unopened" is exactly the slots after
position n_target and every other slot (frozen or attrited) lies at or before it (§1.2, §2.3). Nothing here calls
an LLM or writes a file.
"""
from __future__ import annotations

from collections import Counter
from fractions import Fraction
from typing import Callable

import g_common as GC
import gencard

S = GC.stage0()
cc = S.x_common.cc
EXP = "GC"
ARMS = ("G", "T-rows", "B0", "G-ref")
REPS = 3
CAP_CHARS = 900
FROZEN_SCHEMA = "gen_confirm.questions_frozen.v1"
# §1.2's causes of a pool slot outside P_w, in the prereg's order
ATTRITION = ("unopened", "failed", "kay", "other_quantity", "dynasty_trigger", "cap_stopped")
SLOT_FIELDS = ("sid", "qtype", "chapter", "stratum", "d", "x", "y", "pair", "persons", "edges", "gold",
               "marker_required", "homonym", "shem_x", "dup_gold")
ABSTAIN_REUSE = {"G": "B0", "T-rows": "B0"}          # §4.2
GOLD_REUSE = {"G-ref": "G"}                           # §4.1: rule seeds = gold pair
SCHEMA_CARDS = "gen_confirm.cards.v1"
ItemOf = Callable[[dict, str, dict], dict]


def job_id(sid: str, arm: str, rep: int) -> str:
    return f"{EXP}|{sid}|{arm}|{rep}"


def frac_json(k: int, n: int) -> dict:
    return {"k": k, "n": n, "frac": str(Fraction(k, n)) if n else None, "float": k / n if n else None}


# ---------------------------------------------------------------- the frozen questions
def frozen_problems(doc: dict, pool: list[dict], order: list[str]) -> list[str]:
    """questions_frozen.json against the contract and the writing order (empty = ok); sids only, never question text."""
    out = [] if doc.get("schema") == FROZEN_SCHEMA else [f"schema is not {FROZEN_SCHEMA}"]
    index = {s["sid"]: i for i, s in enumerate(pool)}
    qs = doc.get("questions")
    if not isinstance(qs, list) or not qs:
        return out + ["no questions"]
    sids = [q.get("sid") if isinstance(q, dict) else None for q in qs]
    if any(s not in index for s in sids):
        return out + ["a question without a pool sid"]
    pos = [index[s] for s in sids]
    if pos != sorted(set(pos)):
        out.append("questions are not in strictly ascending pool sid order")
    blank = [s for q, s in zip(qs, sids) if not isinstance(q.get("question"), str) or not q["question"].strip()]
    qtype = [s for q, s in zip(qs, sids) if "qtype" in q and q["qtype"] != pool[index[s]]["qtype"]]
    out += [f"no question text for {blank}"] if blank else []
    out += [f"qtype differs from the slot for {qtype}"] if qtype else []
    nt, att = doc.get("n_target"), doc.get("attrition")
    if isinstance(nt, bool) or not isinstance(nt, int) or not 0 < nt <= len(pool):
        out.append("n_target is not a slot count")
    if not isinstance(att, dict) or set(att) != set(ATTRITION) or not all(isinstance(v, list) for v in att.values()):
        return out + [f"attrition is not {{cause: [sid]}} for {ATTRITION}"]
    flat = sids + [s for c in ATTRITION for s in att[c]]
    if len(flat) != len(set(flat)) or set(flat) != set(index):
        out.append("the frozen questions and the attrition lists do not partition the pool")
    if len(order) != len(set(order)) or set(order) != set(index):
        return out + ["the writing order is not a permutation of the pool"]
    if isinstance(nt, int) and not isinstance(nt, bool):
        tail = set(order[nt:])
        out += [] if set(att["unopened"]) == tail else ["unopened is not the slots after n_target in the writing order"]
        late = sorted((set(flat) - set(att["unopened"])) & tail)
        out += [f"a frozen or attrited slot lies after n_target in the writing order: {late}"] if late else []
    return out


def load_frozen(doc: dict, pool: list[dict], order: list[str]) -> list[dict]:
    """The frozen questions joined with their pool slots (SLOT_FIELDS + question), in pool sid order."""
    bad = frozen_problems(doc, pool, order)
    if bad:
        raise SystemExit(f"questions_frozen.json breaks its contract: {bad}")
    by = {s["sid"]: s for s in pool}
    return [{**{k: by[q["sid"]][k] for k in SLOT_FIELDS}, "question": q["question"]} for q in doc["questions"]]


# ---------------------------------------------------------------- items (stage-0's base context and key)
def stage0_item(slot: dict, question: str, gen: dict) -> dict:
    """stage-0's items_x.gen_item for the slot with the question swapped (its sources, key and distractors)."""
    c = dict(qtype=slot["qtype"], chapter=slot["chapter"], pool=slot["stratum"], path=list(slot["persons"]),
             gold=slot["gold"])
    return {**S.items_x.gen_item(gen, c), "question": question}


def make_item(fq: dict, gen: dict, item_of: ItemOf = stage0_item) -> dict:
    base = item_of(fq, fq["question"], gen)
    keys = base["keys"]
    if len(keys) != 1 or keys[0]["type"] != "arith" or keys[0]["value"] != fq["gold"] or keys[0]["classes"] != ["A", "Y"]:
        raise ValueError(f"{fq['sid']}: the base item's key is not arith_key(gold, ['A', 'Y'], …)")
    if base["question"] != fq["question"]:
        raise ValueError(f"{fq['sid']}: the base item does not carry the frozen question")
    return {**{k: fq[k] for k in SLOT_FIELDS}, "id": fq["sid"], "family": "GEN", "question": fq["question"],
            "keys": keys, "distractors": list(base.get("distractors") or []), "sources": base["sources"],
            "context_from": base.get("context_from")}


def context(item: dict) -> str:
    return cc.build_context(item["sources"])


def user_prompt(item: dict, aux: str | None, ctx: str) -> str:
    return cc.build_user(ctx, item["question"], aux or None)


def prompt_sha(system: str, user: str) -> str:
    return GC.sha256_text(system + "\0" + user)


# ---------------------------------------------------------------- the rule's card and G-ref's
def card_json(c: gencard.Card | None, gold: int) -> dict | None:
    if c is None:
        return None
    return {"seeds": list(c.seeds), "reason": c.reason, "g_block": c.g_block, "t_block": c.t_block,
            "rows": list(c.rows), "lines": [list(x) for x in c.lines],
            "tags": [[k, list(s), kk, v, u] for k, s, kk, v, u in c.tags], "dropped_rows": c.dropped_rows,
            "dropped_lines": c.dropped_lines, "chars_g": c.chars_g, "chars_t": c.chars_t, "covers": c.covers(gold)}


def item_cards(item: dict, L: gencard.Layer) -> dict:
    """The rule's outcome, its card (G, T-rows) and the gold-seed card (G-ref), as JSON."""
    t = gencard.trigger(item["question"], L)
    g = gencard.card(item["question"], L)
    if (g is not None) != t.fired or (g is not None and tuple(g.seeds) != tuple(t.seeds)):
        raise ValueError(f"{item['id']}: gencard.card and gencard.trigger disagree")
    gold_pair = (item["x"], item["y"])
    return {"rule": {"fired": t.fired, "seeds": list(t.seeds) if t.seeds else None, "reason": t.reason,
                     "step": t.step, "shape": t.shape},
            "seeds_ok": bool(t.fired and tuple(t.seeds) == gold_pair), "gold_seeds": list(gold_pair),
            "g": card_json(g, item["gold"]), "gref": card_json(gencard.card_for_seeds(gold_pair, L), item["gold"])}


def blocks(cd: dict) -> dict[str, str | None]:
    """{arm: auxiliary block} of the arms with a job ("" = B0's none; None = no job: reused)."""
    g = cd["g"]
    return {"G": None if g is None else g["g_block"], "T-rows": None if g is None else g["t_block"], "B0": "",
            "G-ref": None if cd["seeds_ok"] else cd["gref"]["g_block"]}


def reuse(cd: dict) -> dict[str, str]:
    """{arm without a job: the arm whose rep r it takes} (§4.1, §4.2)."""
    return {**(ABSTAIN_REUSE if cd["g"] is None else {}), **(GOLD_REUSE if cd["seeds_ok"] else {})}


def would_be(cd: dict) -> dict[str, str | None]:
    """{arm: the block its prompt has or would have}: a reused arm's own card (G-ref) or no card (G, T-rows)."""
    bl = blocks(cd)
    return {**bl, **({"G": None, "T-rows": None} if cd["g"] is None else {}),
            **({"G-ref": cd["gref"]["g_block"]} if cd["seeds_ok"] else {})}


# ---------------------------------------------------------------- jobs and meta
def arm_jobs(items: list[dict], cards: dict[str, dict]) -> list[dict]:
    jobs = []
    for rep in range(1, REPS + 1):
        for i, it in enumerate(items):
            ctx, bl = context(it), blocks(cards[it["id"]])
            for arm in ARMS[i % len(ARMS):] + ARMS[:i % len(ARMS)]:
                if bl[arm] is None:
                    continue
                jobs.append({"job_id": job_id(it["id"], arm, rep), "exp": EXP, "item": it["id"], "family": "GEN",
                             "arm": arm, "rep": rep, "kind": "gen", "system": cc.SYSTEM_PROMPT,
                             "user": user_prompt(it, bl[arm], ctx)})
    return jobs


def item_meta(item: dict, cd: dict) -> dict:
    bl, ctx, g = blocks(cd), context(item), cd["g"]
    users = {a: user_prompt(item, b, ctx) for a, b in would_be(cd).items()}
    return {"item": item["id"], **{k: item[k] for k in SLOT_FIELDS if k not in ("edges", "gold")},
            "rule": cd["rule"], "gold_seeds": cd["gold_seeds"], "seeds_ok": cd["seeds_ok"], "carded": g is not None,
            "covered": bool(g and g["covers"]), "wrong": bool(g and not g["covers"]),
            "gref_covered": cd["gref"]["covers"], "gref_job": bl["G-ref"] is not None,
            "jobs": [a for a in ARMS if bl[a] is not None], "reuse": reuse(cd),
            "block_chars": {a: (None if b is None else len(b)) for a, b in would_be(cd).items()},
            "user_chars": {a: len(u) for a, u in users.items()},
            "prompt_sha256": {a: prompt_sha(cc.SYSTEM_PROMPT, u) for a, u in users.items()},
            "context_sha256": GC.sha256_text(ctx), "context_from": item.get("context_from"),
            "rows": None if g is None else g["rows"], "n_lines": None if g is None else len(g["lines"]),
            "dropped_rows": 0 if g is None else g["dropped_rows"], "dropped_lines": 0 if g is None else g["dropped_lines"]}


def build_cards(items: list[dict], L: gencard.Layer) -> dict[str, dict]:
    return {it["id"]: item_cards(it, L) for it in items}


def build(frozen_doc: dict, pool: list[dict], L: gencard.Layer, gen: dict, item_of: ItemOf = stage0_item, *,
          order: list[str]) -> dict:
    """{"items", "cards", "jobs", "meta"} of the frozen questions (pool sid order); ``order`` is order.json's."""
    items = [make_item(fq, gen, item_of) for fq in load_frozen(frozen_doc, pool, order)]
    cards = build_cards(items, L)
    return {"items": items, "cards": cards, "jobs": arm_jobs(items, cards),
            "meta": {it["id"]: item_meta(it, cards[it["id"]]) for it in items}}


def prompts_sha256(jobs: list[dict]) -> str:
    """Experiment A's sha over (job_id, system, user) in order."""
    return S.x_common.ac.prompts_sha256(jobs)


def n_expected(meta: dict) -> int:
    return sum(REPS * len(m["jobs"]) for m in meta.values())


def summary(jobs: list[dict]) -> dict:
    return {"n_jobs": len(jobs), "by_arm": dict(sorted(Counter(j["arm"] for j in jobs).items())),
            "prompts_sha256": prompts_sha256(jobs), "system_prompt_sha256": GC.sha256_text(cc.SYSTEM_PROMPT),
            "user_template_sha256": GC.sha256_text(cc.USER_TEMPLATE)}


def rule_measures(meta: dict) -> dict:
    """§5.5 on the frozen questions: a_meas (carded and covering the gold), w_meas (carded, no line with the
    gold), R_trig (fired), R_seed (rule seeds = gold pair), as counts over n, and the abstention reasons."""
    ms, n = list(meta.values()), len(meta)
    cnt = lambda key: sum(bool(m[key]) for m in ms)  # noqa: E731
    return {"n": n, "a_meas": frac_json(cnt("covered"), n), "w_meas": frac_json(cnt("wrong"), n),
            "R_trig": frac_json(sum(m["rule"]["fired"] for m in ms), n), "R_seed": frac_json(cnt("seeds_ok"), n),
            "abstentions": dict(sorted(Counter(m["rule"]["reason"] for m in ms if not m["rule"]["fired"]).items())),
            "abstained": sorted(m["item"] for m in ms if not m["rule"]["fired"]),
            "wrong": sorted(m["item"] for m in ms if m["wrong"])}


# ---------------------------------------------------------------- checks before any call (F3)
def card_problems(items: list[dict], cards: dict[str, dict], meta: dict, cap: int = CAP_CHARS) -> dict[str, list[str]]:
    """Per item (empty = ok): blocks ≤ cap; T-rows = G's kept rows; a card iff the rule fired; the gold-seed card
    covers the gold (K0-card); a reused arm's prompt equals its source's byte for byte."""
    out = {}
    for it in items:
        cd, m, bad = cards[it["id"]], meta[it["id"]], []
        bad += [f"{a} block {n} chars > {cap}" for a, n in m["block_chars"].items() if n is not None and n > cap]
        g = cd["g"]
        if (g is not None) != cd["rule"]["fired"]:
            bad.append("a card without the rule firing, or the reverse")
        if g is not None and not (g["g_block"] == g["t_block"] if not g["lines"] else g["g_block"].startswith(g["t_block"] + "\n")):
            bad.append("T-rows is not G's kept rows")
        if not cd["gref"]["covers"]:
            bad.append("the gold-seed card does not cover the gold")
        sha = m["prompt_sha256"]
        bad += [f"{a} would not equal {src}'s prompt" for a, src in m["reuse"].items() if sha[a] != sha[src]]
        if bad:
            out[it["id"]] = bad
    return out


def job_problems(items: list[dict], jobs: list[dict], meta: dict) -> list[str]:
    """Unique ids; exactly every item × its job arms × 3 reps; one system prompt."""
    out, ids = [], [j["job_id"] for j in jobs]
    want = {job_id(it["id"], a, r) for it in items for a in meta[it["id"]]["jobs"] for r in range(1, REPS + 1)}
    if len(ids) != len(set(ids)):
        out.append("duplicate job ids")
    if set(ids) != want:
        out.append(f"jobs are not item × arm × rep: {len(set(ids) - want)} extra, {len(want - set(ids))} missing")
    if len(jobs) != n_expected(meta):
        out.append(f"{len(jobs)} jobs, expected {n_expected(meta)}")
    if any(j["system"] != cc.SYSTEM_PROMPT for j in jobs):
        out.append("a job with another system prompt")
    return out
