"""Build the A layers into the store and check them (prereg §2 層, K0-2).

usage: python3 -B layer_check.py
  -> store A/layer_auto.json (fn_rule=slot), A/ref_layer.json (byte copy of K/probe_C5), A/layer_check.json
Checks: (1) fn_rule=probe reproduces K/probe_C5/auto_layer_occ.json; (2) what fn_rule=slot changes;
(3) footnote-alias bindings and node aliases against the reference layer (wrong binds must be 0).
"""
from __future__ import annotations

import json
import shutil

from a_common import K5, LAYER_AUTO, LAYER_REF, OUT, cc, read_json, sha256_file
from layer_build import build
from regnal import load_auto, load_ref, map_auto_to_ref

PROBE_OCC = K5 / "auto_layer_occ.json"
KEYS = ("nodes", "edges", "fallback_edges", "syncs", "conflicts", "log", "occ_alias")


def roundtrip(obj):
    return json.loads(json.dumps(obj, ensure_ascii=False))


def diff_keys(a: dict, b: dict) -> list[str]:
    return [k for k in KEYS if a.get(k) != b.get(k)]


def node_alias_diff(a: dict, b: dict) -> list:
    out = []
    for na, nb in zip(a["nodes"], b["nodes"]):
        rest_a = {k: v for k, v in na.items() if k != "aliases"}
        rest_b = {k: v for k, v in nb.items() if k != "aliases"}
        if rest_a != rest_b:
            out.append([na["id"], "non-alias fields differ"])
        elif na["aliases"] != nb["aliases"]:
            out.append([na["id"], na["name"], na["aliases"], nb["aliases"]])
    return out


def ref_names(VR, rid) -> set:
    n = VR.nodes[rid]
    return {n["name"]} | set(n["aliases"])


def alias_check(layer: dict, VA, VR) -> dict:
    m = map_auto_to_ref(VA, VR)
    binds = []
    for rec in layer["log"]:
        if rec[0] != "fn_alias":
            continue
        _, fid, kind, word, target, nid = rec
        rid = m.get(nid) if nid else None
        ok = bool(rid) and {word, target} <= ref_names(VR, rid)
        binds.append(dict(fn_id=fid, kind=kind, word=word, target=target, auto=nid, ref=rid, correct=ok))
    rejected = [rec[1:] for rec in layer["log"] if rec[0] == "fn_alias_rejected"]
    aliases = []
    for aid, n in VA.nodes.items():
        for a in n["aliases"]:
            rid = m.get(aid)
            aliases.append(dict(auto=aid, name=n["name"], alias=a, ref=rid,
                                correct=bool(rid) and a in ref_names(VR, rid)))
    return dict(n_bind=len(binds), n_wrong_bind=sum(not b["correct"] for b in binds), binds=binds,
                rejected=rejected, n_node_alias=len(aliases),
                n_wrong_node_alias=sum(not a["correct"] for a in aliases), node_aliases=aliases)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(K5 / "ref_layer.json", LAYER_REF)
    probe_ref = read_json(PROBE_OCC)
    probe = roundtrip(build("probe"))
    slot = roundtrip(build("slot"))
    cc.write_json(LAYER_AUTO, slot)
    VR = load_ref(LAYER_REF)
    probe_file_view = load_auto(PROBE_OCC)
    check = {
        "ref_layer_sha256": {"store": sha256_file(LAYER_REF), "probe": sha256_file(K5 / "ref_layer.json")},
        "layer_auto_sha256": sha256_file(LAYER_AUTO),
        "probe_rule_vs_probe_file": {"differing_keys": diff_keys(probe, probe_ref)},
        "slot_rule_vs_probe_file": {"differing_keys": diff_keys(slot, probe_ref),
                                    "node_alias_changes": node_alias_diff(probe_ref, slot),
                                    "same_edges_syncs_fields": all(slot[k] == probe_ref[k] for k in
                                                                   ("edges", "fallback_edges", "syncs", "conflicts"))},
        "alias_vs_ref": {"probe_file": alias_check(probe_ref, probe_file_view, VR),
                         "slot_rule": alias_check(slot, load_auto(LAYER_AUTO), VR)},
        "counts": {k: len(slot[k]) for k in KEYS},
    }
    cc.write_json(OUT / "layer_check.json", check)
    a = check["alias_vs_ref"]
    print("probe rule reproduces probe file:", not check["probe_rule_vs_probe_file"]["differing_keys"])
    print("slot rule differs in:", check["slot_rule_vs_probe_file"]["differing_keys"])
    print("node alias changes:", check["slot_rule_vs_probe_file"]["node_alias_changes"])
    for lab, v in a.items():
        print(lab, "binds", v["n_bind"], "wrong", v["n_wrong_bind"], "rejected", len(v["rejected"]),
              "node aliases", v["n_node_alias"], "wrong", v["n_wrong_node_alias"])


if __name__ == "__main__":
    main()
