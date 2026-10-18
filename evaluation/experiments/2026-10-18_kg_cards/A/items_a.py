"""Dev items of experiment A (prereg §2 題, dev 30): 6 natural + 24 template, written to store A/items.json.

Natural keys: the probe_C5 dev_eval.py Q walk / lookup keys the question asks, death keys as terms
(K0 gold check), numbers with their unit; the other dev_eval walk / lookup kings (the walk path)
are exempt from the trap. Templates follow probe_C5 supply.py on the reference layer: S1 k∈{2,3,−2,−3}
and S4 born-under with steps_back ≥ 2 and determinate (cum = nonacc, margin ≥ 1);
random.Random(20261018) draws S1 18 then S4 6 (S1 tops up if S4 is short). Gold = the reference
answer king; accepted names are its name and aliases minus another same-kingdom king's main name.
`asked` = the derivation line the question asks (a_strict, descriptive only).
"""
from __future__ import annotations

import random
import sys

from a_common import (GD_DIR, KNAME, LANES, LAYER_REF, REALKG_INPUTS, SEED, cc, passage_source,
                      read_json, realkg_source, verse_passage)
from engine import homonym
from regnal import born_under, load_ref


def name_key(name, basis, accept=None):
    return {"type": "name", "accept": accept or [name], "basis": basis}


def num_key(value, unit, basis):
    return {"type": "number", "value": value, "unit": unit, "basis": basis}


def term_key(accept, basis, reject=()):
    return {"type": "term", "accept": list(accept), "reject": list(reject), "basis": basis}


NATURAL = {
    "SUC_01": dict(set="old31", seeds=["I10"], gold=["I13"], kingdom="I", path=["I10", "I11", "I12", "I13"],
                   asked=["succ", 3],
                   keys=[name_key("耶羅波安", ["2ki.10.35", "2ki.13.9", "2ki.14.16"]), num_key(41, "年", ["2ki.14.23"])],
                   note="Q: kth_succ I10 +3 → I13 (walk), reign 41 (lookup); father 約阿施 not asked: a wrong "
                        "father (尼八) voids the name"),
    "SUC_02": dict(set="old31", seeds=["I02"], gold=["I05"], kingdom="I", path=["I02", "I03", "I04", "I05"],
                   asked=["usurper", 2],
                   keys=[num_key(7, "日|天", ["1ki.15.28", "1ki.16.6", "1ki.16.10", "1ki.16.15"]),
                         term_key(["焚", "火"], ["1ki.16.18"])],
                   note="Q: nth_usurper_after I02 (2, I05) (walk), reign 七日 (lookup, unit 日), death 自焚 "
                        "(lookup, term 焚／火; K0 gold correction)"),
    "N_SUC_01": dict(set="new82", seeds=["I16"], gold=["I19"], kingdom="I", path=["I16", "I17", "I18", "I19"],
                     asked=["usurper", 2],
                     keys=[name_key("以拉", ["2ki.15.22", "2ki.15.25", "2ki.15.30"]), num_key(9, "年", ["2ki.17.1"])],
                     note="Q: edges I17→I18→I19 usurp (walk), father 以拉 and reign 9 (lookup)"),
    "N_SUC_05": dict(set="new82", seeds=["J13"], gold=["J15"], kingdom="J", path=["J13", "J14", "J15"],
                     asked=["succ", 2],
                     keys=[name_key("亞們", ["2ki.20.21", "2ki.21.18"]), num_key(22, "歲", ["2ki.21.19"]),
                           num_key(2, "年", ["2ki.21.19"]),
                           term_key(["殺", "弒"], ["2ki.21.23"], [r"(?:不是|並非|沒有)被?(?:殺|弒)"])],
                     note="Q: kth_succ J13 +2 → J15 (walk), age 22, reign 2, death killed (lookup, term 殺／弒; "
                          "K0 gold correction)"),
    "N_TO_08": dict(set="new82", seeds=["J16"], gold=["J14"], kingdom="J", path=["J16", "J15", "J14"],
                    asked=["born"],
                    keys=[name_key("瑪拿西", ["2ki.22.1", "2ki.21.19", "2ki.21.24", "2ki.21.1", "2ki.21.18"])],
                    note="Q: born_under J16 → J14 (walk); ages/reigns are the asked explanation (reasoning lines), "
                         "the answer line asks the king"),
    "N_KIN_14": dict(set="new82", seeds=["J16", "J13"], gold=[], kingdom="J", path=["J16", "J15", "J14", "J13"],
                     asked=["succ", -3],
                     keys=[term_key(["曾祖", "曾孫"], ["2ki.20.21", "2ki.21.18", "2ki.21.24", "mat.1.10", "1ch.3.13",
                                                       "1ch.3.14"], [r"約西亞的?曾孫", r"希西家的?曾祖",
                                                                     r"(?:不是|並非|而非)曾"])],
                     note="Q: kth_succ J16 −3 → J13 曾祖父 (walk); the question asks a kinship term only; "
                          "a reversed direction (約西亞的曾孫, 希西家的曾祖) or a negation misses"),
}
CN = {2: "二", 3: "三"}


def acc_verse(VR, x) -> str:
    """Seed accession verse in the reference layer: primary sync, else age, pred, founder, reign verse."""
    prim = [v for (n, o, y, v, p) in VR.syncs if n == x and p]
    prov = VR.nodes[x]["prov"]
    return next(v for v in prim + [prov.get(f) for f in ("age", "pred", "founder", "reign")] if v)


def gold_accept(VR, y) -> list[str]:
    n = VR.nodes[y]
    mains = {m["name"] for z, m in VR.nodes.items() if z != y and m["kingdom"] == n["kingdom"]}
    return [nm for nm in VR.names(y) if nm == n["name"] or nm not in mains]


def seed_desc(VR, x) -> str:
    n = VR.nodes[x]
    return f"{KNAME[n['kingdom']]}王{n['name']}" + (f"（{n['father']}的兒子）" if homonym(VR, x) else "")


def s1_candidates(VR) -> list[dict]:
    out = []
    for x, n in VR.nodes.items():
        if n["name"] == "所羅門":
            continue
        for k in (2, 3, -2, -3):
            y = VR.succ(x, k)
            if y is None or VR.nodes[y]["name"] == "所羅門":
                continue
            path = [VR.succ(x, i) for i in (range(0, k + 1) if k > 0 else range(k, 1))]
            out.append(dict(stratum="S1", seed=x, k=k, answer=y, path=path))
    return out


def s4_candidates(VR) -> list[dict]:
    out = []
    for x, n in VR.nodes.items():
        if n["name"] == "所羅門" or n["age"] is None:
            continue
        rc, walked = born_under(VR, x, "cum")
        rn, _ = born_under(VR, x, "nonacc")
        if not rc or rc[0] in ("UNKNOWN_REIGN", "BEFORE_CHAIN"):
            continue
        steps = VR.idx(x) - VR.idx(rc[0])
        if rn and rn[0] == rc[0] and rc[1] >= 1 and steps >= 2:
            out.append(dict(stratum="S4", seed=x, answer=rc[0], path=[x] + walked, steps_back=steps,
                            margin_years=round(rc[1], 2)))
    return out


def draw(VR) -> tuple[list[dict], dict]:
    s1, s4 = s1_candidates(VR), s4_candidates(VR)
    rng = random.Random(SEED)
    pick1 = rng.sample(s1, 18)
    pick4 = rng.sample(s4, min(6, len(s4)))
    extra = rng.sample([c for c in s1 if c not in pick1], 6 - len(pick4)) if len(pick4) < 6 else []
    log = dict(n_s1=len(s1), n_s4=len(s4), s1_topup=len(extra))
    return pick1 + extra + pick4, log


def template_question(VR, c) -> str:
    kd = KNAME[VR.nodes[c["seed"]]["kingdom"]]
    if c["stratum"] == "S1":
        return f"{seed_desc(VR, c['seed'])}之{'後' if c['k'] > 0 else '前'}的第{CN[abs(c['k'])]}位{kd}王是誰？"
    return f"{seed_desc(VR, c['seed'])}出生時，在位的{kd}王是誰？"


def template_basis(VR, c) -> list[str]:
    P = lambda z, f: VR.nodes[z]["prov"].get(f)  # noqa: E731
    vs = [acc_verse(VR, c["seed"])]
    if c["stratum"] == "S1":
        vs += [P(z, "pred") for z in c["path"][1:]] + [acc_verse(VR, c["answer"])]
    else:
        vs += [P(c["seed"], "age")] + [P(z, "pred") for z in c["path"][:-1]] + [P(z, "reign") for z in c["path"][1:]]
    return [v for v in dict.fromkeys(vs) if v]


def template_item(VR, c, i) -> dict:
    y, x = c["answer"], c["seed"]
    return dict(id=f"T_{c['stratum']}_{i:02d}", set="template", kind=c["stratum"], question=template_question(VR, c),
                kingdom=VR.nodes[y]["kingdom"], seeds=[x], gold=[y], k=c.get("k"), path=c["path"],
                steps_back=c.get("steps_back"), margin_years=c.get("margin_years"),
                asked=["succ", c["k"]] if c["stratum"] == "S1" else ["born"],
                keys=[name_key(VR.nodes[y]["name"], template_basis(VR, c), gold_accept(VR, y))],
                exempt=sorted(set(VR.names(x)) | set(VR.names(y))),
                sources=[passage_source(verse_passage()[acc_verse(VR, x)])],
                context_from=f"struct passage of reference accession verse {acc_verse(VR, x)}",
                flags=template_flags(VR, c))


def template_flags(VR, c) -> list[str]:
    flags = []
    if any(VR.nodes[z]["name"] == "亞她利雅" for z in c["path"][1:-1] + [c["answer"]]):
        flags.append("path counts queen 亞她利雅 as a king of Judah")
    same = [q for q, n in NATURAL.items() if n["seeds"][:1] == [c["seed"]] and n["gold"] == [c["answer"]]]
    if same:
        flags.append(f"same seed and answer king as natural item {same[0]} (different wording and context)")
    dropped = [a for a in VR.names(c["answer"]) if a not in gold_accept(VR, c["answer"])]
    if dropped:
        flags.append(f"aliases not accepted (another same-kingdom king's name): {dropped}")
    return flags


def new82_rows() -> dict:
    """Question texts via GD _gd_sets.load_new82 (pinned file + sha) and the pinned original rows."""
    sys.path.insert(0, str(GD_DIR))
    import _gd_sets  # noqa: E402
    qs = _gd_sets.load_new82().by_id()
    raw = {q["id"]: q for q in read_json(_gd_sets.NEW82_FILE)["questions"]}
    return {qid: dict(question=qs[qid].question, key_points=raw[qid]["key_points"],
                      source_file=str(_gd_sets.NEW82_FILE)) for qid in qs}


def new82_sources(qid: str, lanes: dict) -> list[dict]:
    pids = lanes[qid]["C5"] + [r["pid"] for r in lanes[qid]["QD"] if r["rep"] == 1]
    return [passage_source(p) for p in dict.fromkeys(pids)]


def natural_items(VR) -> list[dict]:
    old = {q["id"]: q for q in read_json(REALKG_INPUTS)}
    new, lanes = new82_rows(), read_json(LANES)
    out = []
    for qid, spec in NATURAL.items():
        if spec["set"] == "old31":
            q = old[qid]
            question, sources = q["question"], [realkg_source(s) for s in q["dk_sources"]]
            ctx = "MH/realkg/inputs_nogold.json dk_sources (prod-returned contexts)"
        else:
            question, sources = new[qid]["question"], new82_sources(qid, lanes)
            ctx = "graph_qd lanes.json C5 + QD rep1 pid (QD@6), struct@d8d432b4df15 passages"
        names = {nm for x in spec["seeds"] + spec["gold"] + spec["path"] for nm in VR.names(x)}
        names |= {a for k in spec["keys"] if k["type"] == "name" for a in k["accept"]}
        out.append(dict(id=qid, set=spec["set"], kind="natural", question=question, kingdom=spec["kingdom"],
                        seeds=spec["seeds"], gold=spec["gold"], path=spec["path"], asked=spec["asked"],
                        keys=spec["keys"], exempt=sorted(names),
                        sources=sources, context_from=ctx, note=spec["note"], flags=[]))
    return out


def build_items() -> dict:
    VR = load_ref(LAYER_REF)
    picks, log = draw(VR)
    counters = {"S1": 0, "S4": 0}
    templ = []
    for c in picks:
        counters[c["stratum"]] += 1
        templ.append(template_item(VR, c, counters[c["stratum"]]))
    items = natural_items(VR) + templ
    return dict(seed=SEED, draw=log, n_items=len(items), items=items)


def main() -> None:
    from a_common import ITEMS
    doc = build_items()
    cc.write_json(ITEMS, doc)
    print(ITEMS, doc["n_items"], doc["draw"])


if __name__ == "__main__":
    main()
