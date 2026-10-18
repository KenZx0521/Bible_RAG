"""Pre-question segmentation of the confirmation set (confirm_A.md §1.1) → store A_confirm/segments.json.

Pure CPU on the reference layer. A segment is a run of consecutive kings of one chain with 2–4
succession edges; segments share no edge (a boundary king may be shared); 亞她利雅's two edges are
in no segment. Candidate question forms per segment: S1a (k=±2,±3, both ends inside, no genealogy
shortcut), S1b (only in ≥3-edge segments, ends ≥2 handovers apart, no shortcut), S1c (n-th usurper
after a start king, ≥2 handovers from start to answer), S4 (Judah only, ≥2 steps back, cum and
non-accession agree with margin ≥1 year, seed not 亞哈謝 / 約雅斤). Usable = ≥2 candidates incl. ≥1
S1a or S4. Per run a DP maximizes (#usable, #S4, −unused edges, #3-edge segments) lexicographically;
ties keep the first option in the order skip-edge, 2, 3, 4 edges. Ranges: earliest to latest 1–2
Kings provenance verse of the segment's kings, without the last king's death verse.
After segmentation (which the rule does not change) a candidate whose named seed (S1b: either end)
must carry a homonym father tag naming another king of its chain is not writable and is listed
under `dropped` (the tag would give a step away). Also the slot plan (§2.4) and the pilot draw (§3).
"""
from __future__ import annotations

import functools
import itertools
import random

import support as S
from c_common import (FROZEN_SHA, GAP_EDGES, KNAME, LAYER_REF, PILOT_N, S4_SEED_BANNED, SEED, SEG_EDGES, SEGMENTS,
                      cc, sha256_file, short_ref)

VARIANTS = {"athaliah_gap": GAP_EDGES, "no_gaps": (),
            "tibni_and_athaliah_gaps": (("I05", "I06"),) + GAP_EDGES}


@functools.cache
def candidates(seg: tuple) -> tuple:
    """Candidate forms of one segment (tuple of king ids in chain order), in a fixed order."""
    pos, out, kd = {x: i for i, x in enumerate(seg)}, [], S.kingdom(seg[0])
    for x, y in itertools.permutations(seg, 2):
        d = pos[y] - pos[x]
        if abs(d) in (2, 3) and not S.genealogy_shortcut(seg[min(pos[x], pos[y]):max(pos[x], pos[y]) + 1]):
            out.append({"qtype": "S1a", "seed": x, "answer": y, "k": d})
    if len(seg) - 1 >= 3:
        for i, j in itertools.combinations(range(len(seg)), 2):
            if j - i >= 2 and not S.genealogy_shortcut(seg[i:j + 1]):
                out.append({"qtype": "S1b", "a": seg[i], "b": seg[j], "value": j - i})
    for i, x in enumerate(seg):
        cnt = 0
        for t in range(i, len(seg) - 1):
            if S.etype(seg[t], seg[t + 1]) == "usurp":
                cnt += 1
                if t + 1 - i >= 2:
                    out.append({"qtype": "S1c", "seed": x, "answer": seg[t + 1], "n": cnt})
    for x in seg:
        if kd != "J" or x in S4_SEED_BANNED or x in S.alt_age():
            continue
        c, n = S.born_under(x, "cum"), S.born_under(x, "nonacc")
        if c and n and c[0] == n[0] and c[1] >= 1 and c[2] >= 2 and c[0] in pos and pos[c[0]] < pos[x]:
            out.append({"qtype": "S4", "seed": x, "answer": c[0], "steps": c[2], "margin": round(c[1], 2)})
    return tuple(out)


def cand_path(seg: tuple, q: dict) -> tuple:
    a, b = (q["a"], q["b"]) if q["qtype"] == "S1b" else (q["seed"], q["answer"])
    i, j = seg.index(a), seg.index(b)
    return seg[min(i, j):max(i, j) + 1]


def writable(seg: tuple, q: dict) -> bool:
    """No named seed's required homonym father tag names another king of the candidate's chain."""
    named = (q["a"], q["b"]) if q["qtype"] == "S1b" else (q["seed"],)
    return not any(S.tag_leak(x, cand_path(seg, q)) for x in named)


def usable(c) -> bool:
    return len(c) >= 2 and any(q["qtype"] in ("S1a", "S4") for q in c)


def best(run: tuple) -> tuple:
    """((#usable, #S4, −unused edges, #3-edge), segments) of one gap-free run."""
    E = len(run) - 1

    @functools.cache
    def dp(i):
        if i >= E:
            return (0, 0, 0, 0), ()
        sc, segs = dp(i + 1)
        opts = [((sc[0], sc[1], sc[2] - 1, sc[3]), segs)]
        for z in SEG_EDGES:
            if i + z <= E:
                seg = tuple(run[i:i + z + 1])
                c = candidates(seg)
                sc, segs = dp(i + z)
                if usable(c):
                    opts.append(((sc[0] + 1, sc[1] + sum(q["qtype"] == "S4" for q in c), sc[2], sc[3] + (z == 3)),
                                 (seg,) + segs))
        return max(opts, key=lambda o: o[0])
    return dp(0)


def runs(gaps) -> list[tuple]:
    out = []
    for kd in "IJ":
        ch = S.chains()[kd]
        cur = [ch[0]]
        for a, b in zip(ch, ch[1:]):
            if (a, b) in set(gaps):
                out.append(tuple(cur))
                cur = [b]
            else:
                cur.append(b)
        out.append(tuple(cur))
    return [r for r in out if len(r) >= 3]


def segment_tuples(gaps=GAP_EDGES) -> list[tuple]:
    return [s for run in runs(gaps) for s in best(run)[1]]


def kverses(x: str, drop_death: bool = False) -> list[str]:
    """1–2 Kings provenance verses of a king (reign, mother, father, age, pred, death, syncs)."""
    k, vs = S.ref()[x], []
    for f in ("reign", "mother", "mother_desc", "father"):
        if k[f]:
            vs.append(k[f][-1])
    if k["age"]:
        vs.append(k["age"][1])
    if k["pred"]:
        vs.append(k["pred"][2])
    if k["death"] and not drop_death:
        vs.append(k["death"][2])
    vs += [s[2] for s in k["sync"]]
    return [v for v in vs if v and v.split(".")[0] in ("1ki", "2ki") and v in S.verse_ord()]


def seg_range(seg: tuple) -> tuple[str, str, int]:
    o = S.verse_ord()
    allv = kverses(seg[0]) + kverses(seg[-1], drop_death=True) + [v for x in seg[1:-1] for v in kverses(x)]
    a, b = min(allv, key=o.get), max(allv, key=o.get)
    return a, b, o[b] - o[a] + 1


def slot_plan(cands: list[dict]) -> list[str]:
    """§2.4: S1a; then S1b if the segment has one, else S1a (reverse) if it has ≥2 S1a candidates;
    then S4, else S1c, else none."""
    types = {q["qtype"] for q in cands}
    plan = ["S1a"]
    if "S1b" in types:
        plan.append("S1b")
    elif sum(q["qtype"] == "S1a" for q in cands) >= 2:
        plan.append("S1a_rev")
    if "S4" in types:
        plan.append("S4")
    elif "S1c" in types:
        plan.append("S1c")
    return plan


def segment_rows(gaps=GAP_EDGES) -> list[dict]:
    rows, count = [], {"I": 0, "J": 0}
    for seg in segment_tuples(gaps):
        kd = S.kingdom(seg[0])
        count[kd] += 1
        a, b, n = seg_range(seg)
        c = [dict(q) for q in candidates(seg) if writable(seg, q)]
        dropped = [dict(q, reason="homonym_tag_on_chain") for q in candidates(seg) if not writable(seg, q)]
        rows.append({"id": f"{kd}{count[kd]}", "kingdom": kd, "kingdom_name": KNAME[kd], "kings": list(seg),
                     "king_names": [S.ref()[x]["name"] for x in seg],
                     "edges": [[seg[i], seg[i + 1]] for i in range(len(seg) - 1)], "n_edges": len(seg) - 1,
                     "range": [a, b], "range_label": f"{short_ref(a)}–{short_ref(b)}", "n_verses": n,
                     "types": {t: sum(q["qtype"] == t for q in c) for t in ("S1a", "S1b", "S1c", "S4")},
                     "candidates": c, "dropped": dropped, "slots": slot_plan(c)})
    return rows


def pilot_plan(segs: list[dict], seed: int = SEED) -> list[dict]:
    """§3: 12 segments by random.Random(seed).sample(sorted ids); each takes slot 1, except that in draw
    order the first segment with an S4 slot takes S4, then the first other with S1c, then with S1b."""
    by_id = {s["id"]: s for s in segs}
    drawn = random.Random(seed).sample(sorted(by_id), min(PILOT_N, len(by_id)))
    pick = {sid: 0 for sid in drawn}
    for qt in ("S4", "S1c", "S1b"):
        sid = next((s for s in drawn if pick[s] == 0 and qt in by_id[s]["slots"]), None)
        if sid:
            pick[sid] = by_id[sid]["slots"].index(qt)
    return [{"segment": s, "slot": pick[s] + 1, "qtype": by_id[s]["slots"][pick[s]]} for s in drawn]


def build() -> dict:
    segs = segment_rows()
    tot = {t: sum(s["types"][t] for s in segs) for t in ("S1a", "S1b", "S1c", "S4")}
    slots = [t for s in segs for t in s["slots"]]
    return {"ref_layer_sha256": sha256_file(LAYER_REF), "gap_edges": [list(e) for e in GAP_EDGES],
            "rule": "edges 2–4, edge-disjoint, shared boundary kings allowed; usable = ≥2 candidates incl. S1a or S4; "
                    "then candidates whose seed's homonym father tag names a chain king are dropped",
            "n_segments": len(segs), "n_by_kingdom": {kd: sum(s["kingdom"] == kd for s in segs) for kd in "IJ"},
            "n_candidates": dict(tot, total=sum(tot.values())),
            "dropped": [dict(q, segment=s["id"]) for s in segs for q in s["dropped"]],
            "n_slots": len(slots), "slots_by_type": {t: slots.count(t) for t in dict.fromkeys(slots)},
            "segments": segs, "pilot": pilot_plan(segs),
            "sensitivity": {k: len(segment_tuples(v)) for k, v in VARIANTS.items()}}


def main() -> None:
    assert sha256_file(LAYER_REF) == FROZEN_SHA["ref_layer.json"], "ref_layer.json sha256 changed"
    doc = build()
    cc.write_json(SEGMENTS, doc)
    print(SEGMENTS, doc["n_segments"], doc["n_by_kingdom"], doc["n_candidates"], doc["slots_by_type"],
          "sensitivity", doc["sensitivity"])
    for s in doc["segments"]:
        print(s["id"], "→".join(s["kings"]), s["n_edges"], s["range"], s["n_verses"], s["types"], s["slots"])
    print("pilot", [(p["segment"], p["qtype"]) for p in doc["pilot"]])


if __name__ == "__main__":
    main()
