"""K0 review files (store only, they quote verse text): fired cards with each hop's verse, and the
gold checks. Cards use the dry-run seeds (gold surfaces), since K0 runs before any Ollama call.

The checked v0 files (store v0_k0checked/) fix the 40-card sample: those 40 are re-rendered with the
current code and flagged carried / changed; dev cards outside them are added as new. Review files
carry no automatic judgement (k0_cards_auto.json holds it, for after the hand check).
"""
from __future__ import annotations

import b_arms as A
import b_build as Bd
import b_gold as Gd
import b_items as I
import b_lib as L

N_CARDS = 40
V0 = L.OUT / "v0_k0checked"


def _hop(unit_key: str | None, line: str | None = None) -> dict:
    if unit_key is None:
        return dict(line=line, unit_key=None, ref=None, text=None)
    return dict(line=line, unit_key=unit_key, ref=L.verse_ref(unit_key), text=L.verse_text().get(unit_key))


def card_record(it: dict, cd: dict) -> dict:
    g = cd["G"]
    lines = g["text"].split("\n")
    hops = [_hop(u, ln) for (m, rel, u), ln in zip(g["res"]["path"], lines)]
    return dict(id=it["id"], source=it["source"], uid=I.item_uid(it), pericope=it["pericope"],
                type=it["type"], question=it["question"], card=lines, hops=hops, conclusion=lines[-1],
                verdict=None, note=None)


def _row_record(r: dict, kid: str) -> dict:
    """A supplement row as an item record; the key is built without the validity rules (cards only)."""
    key = I.make_key(r, Gd.gold_graph(r["pericope"]))
    return Bd.record(r, key, kid, I.stratum(r), source="supplement")


def _fresh(items: list[dict], dev_cards: dict, dev: list[str]) -> tuple[list, list]:
    """The original rule: dev fired cards first, then supplement rows in Random(20261018) order."""
    out = [(it, dev_cards[it["id"]]) for it in items if dev_cards[it["id"]]["G"]["status"] == "fire"]
    for n, (r, key) in enumerate(Bd.supplement_rows(dev), 1):
        if len(out) >= N_CARDS:
            break
        rec = Bd.record(r, key, f"k{n:03d}", I.stratum(r), source="supplement")
        cd = A.cards(rec, A.simulated_seed(rec))
        if cd["G"]["status"] == "fire":
            out.append((rec, cd))
    return out, []


def _stable(items: list[dict], dev_cards: dict, v0: dict) -> tuple[list, list]:
    by_uid = {I.item_uid(it): it for it in items}
    rows = {I.item_uid(r): r for r in L.items_eval()}
    out, lost = [], []
    for c in v0["cards"]:
        it = by_uid.get(c["uid"])
        it = it if it is not None and c["source"] == "dev" else _row_record(rows[c["uid"]], c["id"])
        cd = dev_cards.get(it["id"]) if it["source"] == "dev" else A.cards(it, A.simulated_seed(it))
        if cd["G"]["status"] != "fire":
            lost.append(dict(id=c["id"], uid=c["uid"], now=cd["G"]["reason"]))
            continue
        out.append((it, cd, "carried" if cd["G"]["text"].split("\n") == c["card"] else "changed", c["id"]))
    seen = {c["uid"] for c in v0["cards"]}
    out += [(it, dev_cards[it["id"]], "new", None) for it in items
            if dev_cards[it["id"]]["G"]["status"] == "fire" and I.item_uid(it) not in seen]
    return out, lost


def cards_sample(items: list[dict], dev_cards: dict, dev: list[str]) -> tuple[dict, dict]:
    v0_path = V0 / "k0_cards_sample.json"
    if not v0_path.exists():
        pairs, lost = _fresh(items, dev_cards, dev)
        pairs = [(it, cd, "new", None) for it, cd in pairs]
    else:
        pairs, lost = _stable(items, dev_cards, L.load_json(v0_path))
    cards = [dict(card_record(it, cd), status_vs_checked=st, checked_id=cid) for it, cd, st, cid in pairs]
    auto = {c["id"]: cd["G"]["card_judge"] for c, (it, cd, _, _) in zip(cards, pairs)}
    recheck = [c["id"] for c in cards if c["status_vs_checked"] != "carried"]
    sample = dict(rule="the 40 checked v0 cards (store v0_k0checked/k0_cards_sample.json), re-rendered with the "
                       "current code (carried = same text, changed = text differs), plus dev fired cards outside "
                       "them (new); dry-run gold-surface seeds",
                  n=len(cards), n_dev=sum(c["source"] == "dev" for c in cards), recheck=recheck,
                  lost_from_v0=lost, threshold="precision >= 0.85 against the verse text", cards=cards)
    return sample, dict(note="auto card-vs-TIPNR-gold judgement; read only after the hand check", cards=auto)


def _gold_row(it: dict, status: str) -> dict:
    key = {k: v for k, v in it["key"].items() if k != "question"}
    return dict(id=it["id"], uid=I.item_uid(it), type=it["type"], stratum=it["stratum"], question=it["question"],
                key=key, chain=it["surfaces"], sig=it["sig"], hops=[_hop(u) for u in it["hop_verses"]],
                status_vs_checked=status, verdict=None, note=None)


def _status(it: dict, v0: dict) -> str:
    """replaced (other item in the slot) / answer_changed (term table or LIN answer names) /
    tables_extended (only synonyms, traps or neutral strings added) / carried."""
    old = v0.get(it["id"])
    if old is None or I.item_uid(old) != I.item_uid(it):
        return "replaced"
    ko, kn = old["key"], it["key"]
    if ko == kn:
        return "carried"
    same = ko.get("term_key") == kn.get("term_key") if kn["kind"] == "term" else ko["accept"] == kn["accept"]
    return "tables_extended" if same else "answer_changed"


RECHECK = ("replaced", "answer_changed")


def gold_check(items: list[dict]) -> tuple[dict, dict]:
    """The prereg 20 (same slot ids as v0) and all 48 (review: full check before Ollama)."""
    v0_path = V0 / "items.json"
    v0 = {it["id"]: it for it in L.load_json(v0_path)["items"]} if v0_path.exists() else {}
    pick = set(Bd.gold_check_ids(items))
    rows = [_gold_row(it, _status(it, v0)) for it in items]
    twenty = [r for r in rows if r["id"] in pick]
    rule = ("Random(20261018).sample of the 48 item ids, 20; status_vs_checked vs store v0_k0checked/items.json "
            "(carried / key_changed / replaced); a wrong gold -> its edge into gold_fixes.json or its uid into "
            "gold_exclusions.json, rerun dry-run (single-reader judgement, disclosed)")
    recheck = [r["id"] for r in rows if r["status_vs_checked"] in RECHECK]
    return (dict(rule=rule, n=len(twenty), recheck=[i for i in recheck if i in pick], items=twenty),
            dict(rule="all 48 (stricter than prereg's 20; review finding)", n=len(rows), recheck=recheck,
                 status={st: sum(r["status_vs_checked"] == st for r in rows)
                         for st in ("carried", "tables_extended", "answer_changed", "replaced")}, items=rows))
