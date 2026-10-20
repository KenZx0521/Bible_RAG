"""The GEN confirmation-set pool and its CPU checks (prereg §2, §8 K0). Writes store pool.json only.

Pool = stage-0's own candidate functions (``items_x.f1_candidates`` and ``f5_candidates``: stage-0 prereg
§3.4, committed in b960221 before any stage-0 result) on stage-0's frozen ``gen_layer.json``, minus the
14 stage-0 F1/F5 development slots (held out); F3 is not in the pool. One slot = (type, X, Y).

Per slot it records layer ids, chapter, stratum, distance, the path's persons and begetting edges, the
gold, and flags: marker required (a namesake reading exists in which the namesakes are also ancestor and
descendant), homonym end, 閃 as X, duplicate gold, coincidence with a number stated in Genesis 5/7/9/11.

Checks (0 USD):
  K0-gold   ``items_x.verify_gold`` (the independent verse reader) agrees with the layer gold on every slot.
  K0-lines  every born-age and death-age line of the gold-seed card of every same-chapter pair with d >= 2
            (not only pool slots: the rules may fire on any pair) equals the independent reader's value.
  K0-card   every slot's gold-seed card covers the gold; the largest G block in characters.
The output holds layer ids and numbers only, never question, card or scripture text.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

import g_common as GC

STRATA = ("F1c5", "F1c11", "F5c5", "F5c11")
# Genesis 4's line 亞當 > 該隱 > 以諾 > … > 拉麥: a namesake X that is also an ancestor of a namesake Y
CAIN_LINE_ANCESTORS_OF = {"以諾": {"亞當"}, "拉麥": {"亞當", "以諾"}}
TERAH_SON_NAMESAKE = "拿鶴"                          # Terah's son: a descendant of every chapter-11 ancestor


def marker_required(name_x: str, name_y: str) -> bool:
    """True when the slot has a second reading through a namesake, so the question needs one marker."""
    if name_y == TERAH_SON_NAMESAKE:
        return True
    return name_x in CAIN_LINE_ANCESTORS_OF.get(name_y, set())


def _key(c: dict) -> tuple:
    return (c["qtype"], c["path"][0], c["path"][-1])


def stated_numbers(S) -> set[int]:
    vs = [r for r in S.x_common.jsonl(S.x_common.TEXT / "verse_units.jsonl") if r["book_id"] == "gen"]
    out: set[int] = set()
    for r in vs:
        if r["chapter"] in (5, 7, 9, 11):
            out |= set(S.items_x.numbers_in_text(r["text"]))
    return out


def build() -> dict:
    S = GC.stage0()
    G, I, E = S.gen_layer, S.items_x, S.engine_x
    if not GC.sha256_file(GC.GEN_LAYER).startswith(GC.GEN_LAYER_SHA256_PREFIX):
        raise SystemExit(f"{GC.GEN_LAYER}: sha256 is not {GC.GEN_LAYER_SHA256_PREFIX} (prereg §2)")
    gen = G.load()
    log: dict = {}
    every = I.f1_candidates(gen, log) + I.f5_candidates(gen, log)
    dev = {(it["qtype"], it["path"][0], it["path"][-1])
           for it in GC.read_json(S.x_common.ITEMS)["items"] if it["family"] == "GEN"}
    name = lambda i: G.node(gen, i)["name"]  # noqa: E731
    stated = stated_numbers(S)
    gold_count = Counter(c["gold"] for c in every)
    kept = sorted((c for c in every if _key(c) not in dev), key=lambda c: (c["qtype"], c["chapter"], *_key(c)[1:]))
    pool = []
    for k, c in enumerate(kept):
        p = c["path"]
        x, y = p[0], p[-1]
        card = E.card({"family": "GEN", "seeds": [x, y], "gold": c["gold"],
                       "keys": [{"type": "arith", "classes": ["A", "Y"]}]}, gen=gen)
        pool.append(dict(
            sid=f"S{k:02d}", qtype=c["qtype"], chapter=c["chapter"], stratum=f"{c['qtype']}c{c['chapter']}",
            d=len(p) - 1, x=x, y=y, pair=f"{x}>{y}", persons=list(p),
            edges=[f"{p[i]}>{p[i + 1]}" for i in range(len(p) - 1)], gold=c["gold"],
            marker_required=marker_required(name(x), name(y)),
            homonym=any(name(z) in I.GEN_HOMONYMS for z in (x, y)), shem_x=name(x) == "閃",
            coincide=c["gold"] in stated, dup_gold=gold_count[c["gold"]] > 1,
            verify_gold_ok=not I.verify_gold(I.gen_item(gen, c)),
            covered_gold_seeds=bool(card["covered"]), chars_g=card["chars_g"]))
    checks, bad = 0, []
    for ch in G.CHAPTERS:
        ids = G.chain(gen, ch)
        for i in range(len(ids)):
            for j in range(i + 2, len(ids)):
                for ln in E.gen_pair_lines(gen, ids[i], ids[j]):
                    if ln["kind"] not in ("born_age", "death_age"):
                        continue
                    qt = "F1" if ln["kind"] == "born_age" else "F5"
                    c = dict(qtype=qt, chapter=ch, pool="chk", path=ids[i:j + 1], gold=ln["value"])
                    checks += 1
                    problems = I.verify_gold(I.gen_item(gen, c))
                    if problems:
                        bad.append([ids[i], ids[j], ln["kind"], problems])
    summary = dict(
        n=len(pool), by_stratum={s: sum(p["stratum"] == s for p in pool) for s in STRATA},
        pairs=len({p["pair"] for p in pool}), top_x=len({p["x"] for p in pool}),
        edges=len({e for p in pool for e in p["edges"]}),
        marker_required=sum(p["marker_required"] for p in pool), homonym_end=sum(p["homonym"] for p in pool),
        shem_x=sum(p["shem_x"] for p in pool), coincide=sum(p["coincide"] for p in pool),
        dup_gold_slots=sum(p["dup_gold"] for p in pool), dev_slots_held_out=len(every) - len(kept),
        k0_gold=f"{sum(p['verify_gold_ok'] for p in pool)}/{len(pool)}",
        k0_card=f"{sum(p['covered_gold_seeds'] for p in pool)}/{len(pool)}", max_chars_g=max(p["chars_g"] for p in pool),
        k0_lines=f"{checks - len(bad)}/{checks}", k0_lines_bad=bad,
        gen_layer_sha256=GC.sha256_file(GC.GEN_LAYER))
    return {"schema": "gen_confirm.pool.v1", "summary": summary, "pool": pool}


def k0_problems(doc: dict) -> list[str]:
    s, out = doc["summary"], []
    for k in ("k0_gold", "k0_card", "k0_lines"):
        ok, n = s[k].split("/")
        if ok != n:
            out.append(f"{k} {s[k]}")
    if s["max_chars_g"] > 900:
        out.append(f"largest G block {s['max_chars_g']} > 900")
    return out


def main() -> int:
    doc = build()
    problems = k0_problems(doc)
    if problems:
        print("K0 failed:", problems)
        return 1
    GC.write_json(GC.POOL, doc)
    print(json.dumps(doc["summary"], ensure_ascii=False))
    print("pool.json sha256", GC.sha256_file(GC.POOL))
    return 0


if __name__ == "__main__":
    sys.exit(main())
