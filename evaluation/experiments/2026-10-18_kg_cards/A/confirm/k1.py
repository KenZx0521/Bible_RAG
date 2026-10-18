"""K1 of the confirmation set (confirm_A.md §3) → store A_confirm/k1.json. CPU, no arm is read.

For every audited pilot question: the questioner's gold seeds (reference main names of the resolved
seed ids, as the stage-0 dry run wrote them) go through arms_a.resolve_all on G-auto (engine.resolve
with the question text), then engine.cards; hit = the engine writes derivation lines and
keys_a.covered finds the item's key in their payloads (stage-0 a_hit with gold seeds). G-ref is
described only. K1 = hits / passed pilot questions; stop when passed < 10 or K1 < 0.80.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import items_c
from arms_a import resolve_all
from c_common import (K1_JSON, K1_MIN, K1_MIN_PASS, LAYER_AUTO, LAYER_REF, QUESTIONS_PASSED, SEGMENTS, WORDING,
                      cc, read_json, sha256_file)
from engine import cards
from keys_a import covered, item_ctx, king_lexicon
from regnal import load_auto, load_ref


def gold_seed_pairs(it: dict, VR) -> list[tuple[str, str]]:
    return [(VR.nodes[x]["kingdom"], VR.nodes[x]["name"]) for x in it["seeds"]]


def engine_hit(it: dict, V, VR, base: set) -> dict:
    """Stage-0 a_hit with gold seeds on layer V (G-auto or G-ref) for one stage-0-schema item."""
    ids = resolve_all(V, gold_seed_pairs(it, VR), it["question"])
    g = cards(V, ids) if ids else {"g_block": None, "payloads": []}
    fired = g["g_block"] is not None
    ctx = item_ctx(it, VR, base)
    hit = fired and all(covered(ctx, k, g["payloads"]) for k in it["keys"])
    return {"ids": ids, "fired": fired, "hit": hit}


def k1_rows(items: list[dict], VA, VR) -> list[dict]:
    base = king_lexicon(VR)
    rows = []
    for it in items:
        a, r = engine_hit(it, VA, VR, base), engine_hit(it, VR, VR, base)
        rows.append({"id": it["id"], "qtype": it.get("qtype", it.get("kind")), "unit": it.get("unit"),
                     "auto_ids": a["ids"], "auto_fired": a["fired"], "hit": a["hit"],
                     "ref_fired": r["fired"], "ref_hit": r["hit"]})
    return rows


def verdict(rows: list[dict]) -> dict:
    n, h = len(rows), sum(r["hit"] for r in rows)
    k1 = h / n if n else 0.0
    if n < K1_MIN_PASS:
        stop, why = True, WORDING["stop"].format(rule="K1 通過題數", value=f"{n}<{K1_MIN_PASS}", state="未跑")
    elif k1 < K1_MIN:
        stop, why = True, WORDING["stop"].format(rule="K1", value=f"{h}/{n}", state="未跑")
    else:
        stop, why = False, f"K1＝{h}/{n}＝{k1:.3f} ≥ {K1_MIN}，通過"
    return {"n_pass": n, "n_hit": h, "K1": round(k1, 4), "min_pass": K1_MIN_PASS, "threshold": K1_MIN,
            "stop": stop, "wording": why, "ref_hit": sum(r["ref_hit"] for r in rows)}


def pilot_items(questions: list[dict], segments: list[dict], VR) -> list[dict]:
    return [items_c.to_item(q, [], VR, segments) for q in questions if q.get("pilot")]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="K1（CPU）：pilot 通過題以 gold 種子跑 G-auto 引擎")
    ap.add_argument("--questions", type=Path, default=QUESTIONS_PASSED, help="稽核通過題（§2.8 schema，pilot 題標 pilot: true）")
    args = ap.parse_args(argv)
    VA, VR = load_auto(LAYER_AUTO), load_ref(LAYER_REF)
    segs = read_json(SEGMENTS)["segments"]
    items = pilot_items(items_c.questions_of(read_json(args.questions)), segs, VR)
    rows = k1_rows(items, VA, VR)
    doc = {"label": "K1 (gold seeds, G-auto; G-ref descriptive)", **verdict(rows), "rows": rows,
           "inputs_sha256": {"questions": sha256_file(args.questions), "segments.json": sha256_file(SEGMENTS),
                             "layer_auto.json": sha256_file(LAYER_AUTO), "ref_layer.json": sha256_file(LAYER_REF)}}
    cc.write_json(K1_JSON, doc)
    print(K1_JSON, {k: doc[k] for k in ("n_pass", "n_hit", "K1", "stop", "wording")})


if __name__ == "__main__":
    main()
