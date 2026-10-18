"""F1 normalisation table of the confirmation set (confirm_A.md §2.3) → store A_confirm/alias_table.json.

Per divided-kingdom king (39; 所羅門 off the chain): reference name and aliases, the name-key
accept list items_a.gold_accept gives (minus another same-kingdom king's main name) and the
dropped aliases. Also the full keys_a.king_lexicon(VR) (所羅門 included, as keys_a scores), the
S1b number-key unit and the numeral rule (cards_common.cn2int / numbers_in, keys_a.number_hit).
Questioner-added accept spellings are not here: they enter an item only after the audit checked
them against the text (items_c.name_accept).
"""
from __future__ import annotations

from c_common import A_DIR, ALIAS_TABLE, CHAIN_EXCLUDE, FROZEN_SHA, LAYER_REF, S1B_UNIT, cc, read_json, sha256_file
from items_a import gold_accept
from keys_a import king_lexicon
from regnal import load_ref


def build() -> dict:
    VR = load_ref(LAYER_REF)
    kings = []
    for x, n in VR.nodes.items():
        if x in CHAIN_EXCLUDE:
            continue
        acc = gold_accept(VR, x)
        kings.append({"id": x, "kingdom": n["kingdom"], "name": n["name"], "aliases": VR.names(x)[1:],
                      "accept": acc, "not_accepted": [a for a in VR.names(x) if a not in acc]})
    return {"ref_layer_sha256": sha256_file(LAYER_REF),
            "keys_a_sha256": sha256_file(A_DIR / "keys_a.py"),
            "cards_common_sha256": sha256_file(A_DIR.parent / "cards_common.py"),
            "n_kings": len(kings), "n_aliases": sum(len(k["aliases"]) for k in kings),
            "kings": kings, "lexicon": sorted(king_lexicon(VR)),
            "units": {"S1b": S1B_UNIT},
            "numerals": "cards_common.cn2int / numbers_in; keys_a.number_hit: value written with its unit, "
                        "not after 第, citations removed (keys_a.CITE)",
            "accept_rule": "name key = questioner's name + audited accept + this table's accept; another "
                           "same-kingdom king's main name is never accepted (items_a.gold_accept)"}


def load() -> dict:
    return read_json(ALIAS_TABLE)


def main() -> None:
    assert sha256_file(LAYER_REF) == FROZEN_SHA["ref_layer.json"], "ref_layer.json sha256 changed"
    doc = build()
    cc.write_json(ALIAS_TABLE, doc)
    print(ALIAS_TABLE, "kings", doc["n_kings"], "aliases", doc["n_aliases"], "lexicon", len(doc["lexicon"]),
          "not_accepted", {k["id"]: k["not_accepted"] for k in doc["kings"] if k["not_accepted"]})


if __name__ == "__main__":
    main()
