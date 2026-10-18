"""Descriptives of the confirmation set (confirm_A.md §6.6): none of them enters the verdict; p is description.

Unit-level G-auto − B0 and G-ref − G-auto (G-ref = ideal ceiling only); H1/H2 pairs within strata
(qtype, kingdom, pilot, gen_passage, answer_is_father, ref_disagree excluded); the trap-rule sensitivities (template
rule, no trap rule); seeds (gemma vs gold resolution, a, K1-type a with gold seeds, h, pR, pC);
hesitant answer lines (≥2 non-seed same-kingdom kings named); boundary-king and stage-0 overlap counts.
The H2 pair (G-auto − T-rows) carries no p anywhere unless the fixed sequence tested H2 (§6: H2 is
tested, and its p reported, only after H1 passes): h2_tested=False gives Δ̄, CI and W:L:T only.
"""
from __future__ import annotations

from analyze_c import DESC_PAIRS, H1, H2, mean, name, unit_test, unit_values
from c_common import ARMS, QTYPES
from keys_a import king_lexicon, own_spans
from score_c import rule_ctx


def subset(rows: dict, keep) -> dict:
    return {i: r for i, r in rows.items() if keep(r)}


def pair_tests(rows: dict, h2_tested: bool, get=lambda r: r["mean"]) -> dict:
    return {name(H1): unit_test(unit_values(rows, *H1, get)),
            name(H2): unit_test(unit_values(rows, *H2, get), with_p=h2_tested)}


def strata(rows: dict, h2_tested: bool) -> dict:
    hid = lambda r, k: bool((r.get("hidden") or {}).get(k))  # noqa: E731
    cuts = {**{f"qtype={q}": (lambda r, q=q: r.get("qtype") == q) for q in QTYPES},
            "kingdom=I": lambda r: r.get("kingdom") == "I", "kingdom=J": lambda r: r.get("kingdom") == "J",
            "pilot": lambda r: bool(r.get("pilot")), "non_pilot": lambda r: not r.get("pilot"),
            "gen_passage": lambda r: hid(r, "gen_passage"), "not_gen_passage": lambda r: not hid(r, "gen_passage"),
            "answer_is_father": lambda r: hid(r, "answer_is_father"),
            "not_answer_is_father": lambda r: not hid(r, "answer_is_father"),
            "excl_ref_disagree": lambda r: not hid(r, "ref_disagree")}
    out = {}
    for label, keep in cuts.items():
        sub = subset(rows, keep)
        out[label] = {"n_items": len(sub), **(pair_tests(sub, h2_tested) if sub else {})}
    return out


def trap_sensitivity(rows: dict, h2_tested: bool) -> dict:
    rules = sorted({k for r in rows.values() for k in (r.get("sens") or {})})
    return {rule: {"trap_calls": sum(r["sens"][rule]["trap_calls"] for r in rows.values()),
                   **pair_tests(rows, h2_tested, lambda r, rule=rule: r["sens"][rule]["mean"])} for rule in rules}


def seeds(rows: dict, meta: dict, items: dict, VA, VR) -> dict:
    from k1 import engine_hit
    base = king_lexicon(VR)
    ids = sorted(rows)
    agree = [i for i in ids if meta[i]["ref_ids"] == items[i]["seeds"]]
    gold_hit = [i for i in ids if engine_hit(items[i], VA, VR, base)["hit"]]
    a_hit = [i for i in ids if meta[i]["a_hit"]]
    return {"gemma_gold_agree": len(agree) / len(ids) if ids else None, "disagree_items": sorted(set(ids) - set(agree)),
            "a": len(a_hit) / len(ids) if ids else None, "a_gold_seeds": len(gold_hit) / len(ids) if ids else None,
            "h": mean([rows[i]["mean"]["G-auto"] for i in a_hit]),
            "pR": mean([rows[i]["mean"]["T-rows"] for i in ids]), "pC": mean([rows[i]["mean"]["T-canon"] for i in ids]),
            "seed_unresolved_auto": [i for i in ids if not meta[i]["auto_ids"]],
            "seed_unresolved_ref": [i for i in ids if not meta[i]["ref_ids"]]}


def bearer_groups(VR, kd: str, names: set[str]) -> set[tuple]:
    return {g for g in (tuple(sorted(x for x, n in VR.nodes.items() if n["kingdom"] == kd and nm in VR.names(x)))
                        for nm in names) if g}


def hesitant(line: str, it: dict, ctx: dict, VR) -> bool:
    """The answer line names ≥2 same-kingdom kings other than the seeds (aliases of one king count once)."""
    groups = bearer_groups(VR, it["kingdom"], {n for _i, n in own_spans(ctx, line)})
    return len([g for g in groups if not set(g) & set(it["seeds"])]) >= 2


def hesitation(rows: dict, items: dict, VR) -> dict:
    base = king_lexicon(VR)
    out = {a: {"calls": 0, "hesitant": 0} for a in ARMS}
    for i, r in rows.items():
        ctx = rule_ctx(items[i], VR, base)
        for k, v in r["reps"].items():
            if not v or "substituted_from" in v or v["answer_line"] is None:
                continue
            arm = k.split("|")[0]
            out[arm]["calls"] += 1
            out[arm]["hesitant"] += hesitant(v["answer_line"], items[i], ctx, VR)
    return out


def flag_count(items: dict, prefix: str) -> list[str]:
    return sorted(i for i, it in items.items() if any(f.startswith(prefix) for f in it.get("flags") or []))


def describe(rows: dict, meta: dict, items: dict, VA, VR, h2_tested: bool) -> dict:
    return {"pairs_desc": {name(p): unit_test(unit_values(rows, *p)) for p in DESC_PAIRS},
            "strata": strata(rows, h2_tested), "trap_rule_sensitivity": trap_sensitivity(rows, h2_tested),
            "seeds_desc": seeds(rows, meta, items, VA, VR), "hesitation": hesitation(rows, items, VR),
            "boundary_king_items": flag_count(items, "boundary kings"),
            "stage0_overlap_items": flag_count(items, "same seed and answer")}
