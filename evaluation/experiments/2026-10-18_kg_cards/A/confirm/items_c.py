"""Items of the confirmation set (confirm_A.md §2.3, §4, §6.1): frozen questions + frozen prod contexts
→ store A_confirm/items.json in the stage-0 items schema (arms_a / keys_a / score_a read it unchanged),
plus qtype, unit (= segment id), exempt_template and the hidden flags.

One key per item. Name key: the questioner's answer name + audited accept + alias_table accept
(items_a.gold_accept), minus another same-kingdom king's main name. Count key (S1b): the value with
unit 次|代|任|位 (keys_a.number_hit). Trap exemption `exempt`: every name of every chain king (seed to
answer) plus the accept list; `exempt_template` (seed and answer names only) is the stage-0 template
rule, a required sensitivity. Sources: the prod-returned blocks of contexts.json through
a_common.realkg_source (header line dropped; cards_common.build_context re-renders it).
"""
from __future__ import annotations

import support as S
from c_common import CONTEXTS, ITEMS, KD, QUESTIONS_FROZEN, S1B_UNIT, SEED, SEGMENTS, ST0_ITEMS, ac, cc, read_json, \
    sha256_file
from items_a import gold_accept
from regnal import load_ref

ASKED = {"S1a": "succ", "S1b": "gap", "S1c": "usurper", "S4": "born"}
CONTEXT_FROM = "A_confirm/contexts.json: prod /api/v1/query top_k 5, retrieval_only, event_registry at prod default"


def questions_of(doc) -> list[dict]:
    return doc["questions"] if isinstance(doc, dict) else list(doc)


def contexts_of(doc) -> dict:
    """contexts.json {"meta", "items": {qid: {"sources": [...], ...}}} (a list of records with "id" also works)."""
    items = doc["items"] if isinstance(doc, dict) else doc
    return items if isinstance(items, dict) else {r["id"]: r for r in items}


def name_accept(q: dict, y: str, VR) -> list[str]:
    kd = VR.nodes[y]["kingdom"]
    mains = {m["name"] for z, m in VR.nodes.items() if z != y and m["kingdom"] == kd}
    ans = q.get("answer") or {}
    written = [S.parse_name(ans.get("text", ""))[0]] + [S.parse_name(a)[0] for a in ans.get("accept") or []]
    own = VR.nodes[y]["name"]
    return [a for a in dict.fromkeys(written + gold_accept(VR, y)) if a and (a == own or a not in mains)]


def basis_of(q: dict) -> list[str]:
    return list(dict.fromkeys(v for c in q.get("chain", []) for v in c.get("basis") or []))


def build_key(q: dict, answer: str | None, VR) -> dict:
    ans = q.get("answer") or {}
    if q["qtype"] == "S1b" or ans.get("kind") == "count":
        if ans.get("value") is None:
            raise ValueError(f"{q.get('id')}: count key without value")
        return {"type": "number", "value": int(ans["value"]), "unit": S1B_UNIT, "basis": basis_of(q)}
    if answer is None:
        raise ValueError(f"{q.get('id')}: answer king unresolved")
    return {"type": "name", "accept": name_accept(q, answer, VR), "basis": basis_of(q)}


def asked(qtype: str, path: tuple, seed: str, answer: str | None) -> list:
    if qtype == "S1a":
        return ["succ", S.chain_index(answer) - S.chain_index(seed)]
    if qtype == "S1c":
        return ["usurper", sum(S.etype(a, b) == "usurp" for a, b in zip(path, path[1:]))]
    return [ASKED[qtype]]


def source_c(src: dict) -> dict:
    return dict(ac.realkg_source(src), **{"from": f"A_confirm/contexts.json {src.get('id')}"})


def to_item(q: dict, sources: list[dict], VR, segments: list[dict], dev_pairs: dict | None = None) -> dict:
    """One frozen §2.8 question → stage-0 item; ValueError when names or the segment do not check."""
    rec = S.support_record(q, segments)
    if rec["errors"]:
        raise ValueError(f"{q.get('id')}: {rec['errors']} {rec['unresolved']}")
    seeds, path, answer = rec["seeds"], tuple(rec["path"]), rec["answer"]
    key = build_key(q, answer, VR)
    accept = key.get("accept", [])
    exempt = sorted({nm for x in path for nm in VR.names(x)} | set(accept))
    tmpl = sorted({nm for x in seeds + ([answer] if answer else []) for nm in VR.names(x)})
    flags = [f"boundary kings {rec['boundary_kings']}"] if rec["boundary_kings"] else []
    same = (dev_pairs or {}).get((seeds[0], answer)) if seeds and answer else None
    if same:
        flags.append(f"same seed and answer as stage-0 item {same}")
    return {"id": q["id"], "set": "confirm", "kind": q["qtype"], "qtype": q["qtype"], "unit": q["segment"],
            "segment": q["segment"], "pilot": bool(q.get("pilot")), "question": q["question"],
            "kingdom": KD[q["kingdom"]], "seeds": seeds, "gold": [answer] if key["type"] == "name" else [],
            "k": q.get("k"), "n": q.get("n"), "path": list(path), "asked": asked(q["qtype"], path, seeds[0], answer),
            "keys": [key], "exempt": exempt, "exempt_template": tmpl,
            "sources": [source_c(s) for s in sources], "context_from": CONTEXT_FROM,
            "support": rec["support"], "hidden": rec["hidden"], "flags": flags}


def dev_pairs() -> dict:
    """(seed, answer) -> stage-0 item id, for the R16 overlap description."""
    if not ST0_ITEMS.is_file():
        return {}
    return {(it["seeds"][0], it["gold"][0]): it["id"] for it in read_json(ST0_ITEMS)["items"]
            if it["seeds"] and it["gold"]}


def build_items(questions: list[dict], contexts: dict, segments: list[dict], VR=None) -> dict:
    VR = VR or load_ref(ac.LAYER_REF)
    missing = [q["id"] for q in questions if q["id"] not in contexts]
    if missing:
        raise ValueError(f"no frozen context for {missing}")
    pairs = dev_pairs()
    items = [to_item(q, contexts[q["id"]]["sources"], VR, segments, pairs) for q in questions]
    return {"seed": SEED, "n_items": len(items), "n_units": len({it["unit"] for it in items}), "items": items}


def main() -> None:
    segs = read_json(SEGMENTS)["segments"]
    doc = build_items(questions_of(read_json(QUESTIONS_FROZEN)), contexts_of(read_json(CONTEXTS)), segs)
    doc["inputs_sha256"] = {"questions_frozen.json": sha256_file(QUESTIONS_FROZEN),
                            "contexts.json": sha256_file(CONTEXTS), "segments.json": sha256_file(SEGMENTS)}
    cc.write_json(ITEMS, doc)
    print(ITEMS, doc["n_items"], "units", doc["n_units"])


if __name__ == "__main__":
    main()
