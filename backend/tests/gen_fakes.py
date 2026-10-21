"""A made-up Genesis layer and names file for the GEN card tests (every name and number made up).

Two chains as utils.gencard reads them: chapter 5 (five rows) and chapter 11 (three rows, their
lifespans derived). ``files`` gives the two contract files' bytes as a release holds them: the names
file pins the layer's sha256, the text layer both were read from and the routing lexicon its blockers
came from. FIRES takes the card on this layer (F1: 安東 is 190 when 卡爾 is born, two generations down);
SILENT names one chain person only, so the rule abstains.
"""

from __future__ import annotations

import copy
import hashlib
import json

# (id, name, begetting age, remaining years, stated lifespan)
CH5 = (("G05.00", "安東", 100, 800, 900), ("G05.01", "布朗", 90, 700, 790), ("G05.02", "卡爾", 80, 600, 680),
       ("G05.03", "戴維", 70, 50, 120), ("G05.04", "艾倫", 50, 510, 560))
CH11 = (("G11.00", "李奧", 30, 300, None), ("G11.01", "麥斯", 25, 200, None), ("G11.02", "尼克", 35, 100, None))
FIRES = "安東幾歲時卡爾出生"
FIRES_SEEDS = ("G05.00", "G05.02")
SILENT = "布朗是誰？"
LEXICON_KEY = "contracts/b00000000_00000000/routing_lexicon.json"   # a source label: only its basename is read


def layer_doc(text_digest: str) -> dict:
    nodes, edges, derived = [], [], {}
    for ch, rows in ((5, CH5), (11, CH11)):
        for order, (gid, name, beget, remain, total) in enumerate(rows):
            fields = {"beget": [beget, f"syn.{ch}.{3 * order}"], "remain": [remain, f"syn.{ch}.{3 * order + 1}"]}
            if total is not None:
                fields["total"] = [total, f"syn.{ch}.{3 * order + 2}"]
            else:
                derived[gid] = beget + remain
            son = rows[order + 1][1] if order + 1 < len(rows) else None
            nodes.append({"id": gid, "name": name, "chapter": ch, "order": order, "sons": [son] if son else [],
                          "fields": fields, "flood_offset": None,
                          "evidence": [v[1] for v in fields.values()]})
        edges += [[a[0], b[0], "son", f"syn.{ch}.{3 * i}"] for i, (a, b) in enumerate(zip(rows, rows[1:]))]
    return {"schema": "arith.gen_layer.v1", "text_digest": text_digest, "nodes": nodes, "edges": edges,
            "conflict_edges": [], "flood": {}, "derived": {"total": derived}, "checks": {}, "problems": []}


def names_doc(layer: dict, layer_sha: str, lexicon_sha: str) -> dict:
    chain = [{"id": n["id"], "name": n["name"], "chapter": n["chapter"]}
             for n in sorted(layer["nodes"], key=lambda n: (n["chapter"], n["order"]))]
    return {"schema": "gen_confirm.gen_names.v1", "text_digest": layer["text_digest"], "gen_layer_sha256": layer_sha,
            "chain": chain, "cain_line": [], "abram_family": [], "extra_persons": [], "other_books": [],
            "lexicon_blockers": ["卡爾城"],
            "sources": {"reports/syn/gen_layer.json": layer_sha, LEXICON_KEY: lexicon_sha}}


def encode(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, indent=1).encode("utf-8") + b"\n"


def files(text_digest: str = "0" * 64, lexicon_sha: str = "0" * 64, layer_edit=None,
          names_edit=None) -> tuple[bytes, bytes]:
    """(gen_layer.json, gen_names.json). ``layer_edit(doc)`` changes the layer file only (the names
    file still lists the unchanged layer's chain, and pins the changed file's sha256);
    ``names_edit(doc)`` changes the names file."""
    layer = layer_doc(text_digest)
    edited = copy.deepcopy(layer)
    if layer_edit:
        layer_edit(edited)
    data = encode(edited)
    names = names_doc(layer, hashlib.sha256(data).hexdigest(), lexicon_sha)
    if names_edit:
        names_edit(names)
    return data, encode(names)
