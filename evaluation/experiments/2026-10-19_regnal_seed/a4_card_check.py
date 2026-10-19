"""A4′ card check (prereg.md §8): the staging backend's cards against the CPU rule cards, byte for byte.

Reads the responses.jsonl that evaluation/experiments/2026-10-19_regnal_card/a4_staging.py writes (one
line per confirmation-set question: item, error, answer, aux_card{text, seeds, kings, lines, evidence,
layer_sha256, seed_source}, …). For each of the 32 questions, on --layer + --lexicon with this
checkout's backend code: the trigger, ``seeds.rule_seeds`` and ``card.card_from_rule`` give the CPU card,
and the record must have no error, an aux_card exactly when the CPU makes a card, aux_card.text equal to
it, aux_card.seed_source "rule" (where the rules abstain the backend falls back to the gemma seed call:
seed_source "gemma", the text is not checked), and aux_card.layer_sha256, when recorded, the layer's.
The report (--out, in the store only under reports/regnal_seed_20261019/) and stdout carry ids, sha256
values and counts, never card or question text.

    python -B a4_card_check.py --responses R --layer L --lexicon X --out OUT.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rs_common as C  # noqa: E402


def expected(layer, question: str) -> dict:
    """What the backend must have sent for this question: kind "rule" (text), "gemma" or "none"."""
    B = C.backend()
    if not B.trigger.trigger(question, layer.names, layer.blockers).fired:
        return {"kind": "none", "why": "not taken", "text": None, "ids": []}
    rule = B.seeds.rule_seeds(layer, question)
    if not rule.ids:
        return {"kind": "gemma", "why": rule.reason, "text": None, "ids": []}
    card = B.card.card_from_rule(layer, rule.ids)
    if card is None:
        return {"kind": "none", "why": "no derivation line", "text": None, "ids": list(rule.ids)}
    return {"kind": "rule", "why": None, "text": card.text, "ids": list(rule.ids)}


def check_row(layer, it: dict, rec: dict | None) -> dict:
    exp = expected(layer, it["question"])
    row = {"item": it["id"], "expected": exp["kind"], "rule_ids": exp["ids"], "why": exp["why"],
           "cpu_text_sha256": C.sha256_text(exp["text"]) if exp["text"] else None, "problems": []}
    if rec is None:
        row["problems"].append("missing record")
        return row
    aux = rec.get("aux_card")
    row.update(seed_source=aux.get("seed_source") if aux else None,
               text_sha256=C.sha256_text(aux["text"]) if aux and aux.get("text") else None,
               kings=aux.get("kings") if aux else None, text_same=None)
    p = row["problems"]
    if rec.get("error"):
        p.append("error in the record")
    if exp["kind"] == "rule":
        if aux is None:
            p.append("no card where the CPU makes one")
        else:
            row["text_same"] = aux.get("text") == exp["text"]
            if not row["text_same"]:
                p.append("text differs from the CPU card")
            if aux.get("seed_source") != "rule":
                p.append(f"seed_source {aux.get('seed_source')!r}, expected 'rule'")
    elif exp["kind"] == "gemma":
        if aux is not None and aux.get("seed_source") != "gemma":
            p.append(f"seed_source {aux.get('seed_source')!r}, expected 'gemma' (the rules abstain)")
    elif aux is not None:
        p.append(f"a card where the CPU makes none ({exp['why']})")
    if aux is not None and aux.get("layer_sha256") is not None and aux["layer_sha256"] != layer.sha256:
        p.append("layer_sha256 differs from the layer's")
    return row


def check(layer, items: list[dict], responses: list[dict]) -> dict:
    by_item = {r["item"]: r for r in responses}
    rows = [check_row(layer, it, by_item.get(it["id"])) for it in items]
    missing = [r["item"] for r in rows if "missing record" in r["problems"]]
    return {"pass": not any(r["problems"] for r in rows), "n": len(rows), "layer_sha256": layer.sha256,
            "errors": sum(bool(by_item.get(it["id"], {}).get("error")) for it in items),
            "text_same": sum(r.get("text_same") is True for r in rows),
            "rule_expected": sum(r["expected"] == "rule" for r in rows),
            "abstained": [r["item"] for r in rows if r["expected"] == "gemma"],
            "no_card_expected": [r["item"] for r in rows if r["expected"] == "none"],
            "missing": missing, "extra": sorted(set(by_item) - {it["id"] for it in items}),
            "problems": {r["item"]: r["problems"] for r in rows if r["problems"]}, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A4′：staging 卡片與 CPU 規則卡逐字核對")
    ap.add_argument("--responses", required=True, type=Path)
    ap.add_argument("--layer", required=True, type=Path)
    ap.add_argument("--lexicon", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--items", type=Path, default=C.A_CONFIRM / "items.json")
    args = ap.parse_args(argv)
    out = C.writable(args.out)
    layer, info = C.load_layer(args.layer, args.lexicon)
    rep = check(layer, C.read_json(args.items)["items"], C.jsonl(args.responses))
    rep = {**rep, "responses": str(args.responses.resolve()), "responses_sha256": C.sha256_file(args.responses),
           **{k: info[k] for k in ("layer_path", "lexicon_path", "lexicon_sha256")},
           "backend_sha256": C.backend().sha256, "backend_files_sha256": C.backend().files_sha256}
    C.write_json(out, rep)
    print({k: rep[k] for k in ("pass", "n", "errors", "rule_expected", "text_same", "abstained", "no_card_expected",
                               "missing", "extra", "layer_sha256")})
    for item, problems in rep["problems"].items():
        print(item, problems)
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
