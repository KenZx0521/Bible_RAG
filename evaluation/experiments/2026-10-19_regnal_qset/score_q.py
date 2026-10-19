"""Scorer of the question set (qset.md §5–§7, CPU): how often the chronology card's path takes the questions.

The layer is built as the backend builds it: ``parse_layer``, then, when this checkout's layer module
has ``with_lexicon`` (the rule-seed change), the build's routing lexicon attached as ``make_active``
does (--lexicon, default the routing_lexicon.json next to --layer; refused when missing), and the
trigger gets ``layer.blockers`` when it takes them. Without that the scorer's R_trig and R_seed
would part from prod silently (review 2026-10-19).

Per positive question, cumulatively (each stage needs the one before):
  R_trig  ``trigger(question, layer.names[, layer.blockers])`` fires; a miss is split into king_miss
          (no chain king found), cue_miss (a king, no cue) and king_and_cue_miss;
  R_seed  the rule seeds (``backend/utils/regnal/seeds.py`` rule_seeds(layer, question), when the
          module has it; n/a otherwise) include the gold start king (S1b: both ends), mapped from the
          reference to the scored layer by kingdom, name and homonym order;
  R_card  ``engine.cards`` on those seeds holds the asked line (succ k, usurper n, born, gap) and its
          payload is the reference gold (the king's name; S1b the number of handovers).
R_card_oracle (descriptive) is the card on the gold seeds of a fired question: the layer and the engine
alone. The denominator is every valid positive (mech_q validity); label-inconsistent, unlabelled
and flagged questions stay in it and are also reported apart (qset.md §5; the scouting design's label-consistent
denominator was corrected).
False triggers: near misses by family (labeller-gray ones apart), and the 500-question GT v1 / v2.
Regression (in-sample, trigger only): the 30 dev and 32 confirmation questions of experiment A.

Every result records the layer sha and role (score_pin: q_common.SCORE_LAYER_SHA256, the r4 layer;
pre_fix: 932d2242…, describe only; unpinned), the lexicon sha and blocker count, the sha of
trigger.py, seeds.py, engine.py, layer.py, ragcommon/regnal.py and ragcommon/routing.py as imported
from this checkout, the spec and items sha. Every command needs --layer (no default: the adoption
gates gt and regress depend on the layer's names too). ``score`` refuses the pre-fix layer, any layer
but the pinned one once SCORE_LAYER_SHA256 is set, and P2 while it is not. P2 is locked: its run
prints and appends (p2_runs.jsonl, one line per run) aggregates only; a second run needs --again
and must be disclosed. ``--compare-trigger FILE`` scores the same items under another trigger.py too
(old vs new rule, paired).

    score_q.py score --set p1|p2 --layer FILE [--lexicon FILE] [--compare-trigger FILE] [--again]
    score_q.py gt --layer FILE [--lexicon FILE] [--compare-trigger FILE]
    score_q.py regress --layer FILE [--lexicon FILE]
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import q_common
import spec_q as S
from q_common import (CONFIRM_FROZEN, DEV_ITEMS, FLAGS, GT_FILES, KINGDOMS, LAYER_PRE_FIX_SHA256, LEXICON_FILE,
                      POS_TYPES, NEAR_FAMILIES, ROOT, QError, append_jsonl, counts, now, read_json, read_jsonl, regnal,
                      sha256_bytes, sha256_file, write_json)

P2_RUNS = "p2_runs.jsonl"
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Rules:
    fire: Callable[[str], Any]                 # trigger on one question, the layer's names (and blockers) bound
    rule_seeds: Callable[[Any, str], Any] | None
    engine: Any
    layer: Any
    provenance: Mapping[str, Any]


def _module_from(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def layer_role(sha: str) -> str:
    pin = q_common.SCORE_LAYER_SHA256           # read at call time: one source, set with the formal prereg
    if pin and sha == pin:
        return "score_pin"
    return "pre_fix" if sha == LAYER_PRE_FIX_SHA256 else "unpinned"


def score_layer_check(sha: str, side: str) -> None:
    """``score`` only on the r4 layer: never the pre-fix one; the pinned one once pinned; P2 needs the pin."""
    pin = q_common.SCORE_LAYER_SHA256
    if sha == LAYER_PRE_FIX_SHA256:
        raise QError(f"layer {sha[:12]} is the pre-fix prod layer (describe only, gt / regress): score on r4")
    if pin and sha != pin:
        raise QError(f"layer {sha[:12]} is not the pinned score layer {pin[:12]}")
    if side == "p2" and not pin:
        raise QError("P2 is scored once, on the pinned r4 layer: set q_common.SCORE_LAYER_SHA256 first")


def make_fire(trig: Callable[..., Any], layer: Any) -> Callable[[str], Any]:
    """The trigger bound to the layer: its blockers passed when the trigger takes them (card.py's call)."""
    if "blockers" in inspect.signature(trig).parameters:
        blockers = tuple(getattr(layer, "blockers", ()))
        return lambda q: trig(q, layer.names, blockers)
    return lambda q: trig(q, layer.names)


def _attach_lexicon(R: Any, layer: Any, layer_path: Path, lexicon_path: Path | None) -> tuple[Any, dict | None]:
    attach = getattr(R.layer, "with_lexicon", None)
    if attach is None:
        if lexicon_path is not None:
            raise QError("this checkout's layer module takes no routing lexicon (no with_lexicon)")
        return layer, None
    path = Path(lexicon_path) if lexicon_path is not None else Path(layer_path).with_name(LEXICON_FILE)
    if not path.is_file():
        raise QError(f"this checkout's layer takes the build's routing lexicon (with_lexicon): no {path}, "
                     "give --lexicon")
    layer = attach(layer, R.routing.load_lexicon(path))
    return layer, {"path": str(path), "sha256": sha256_file(path), "blockers": len(layer.blockers)}


def load_rules(layer_path: Path, trigger_file: Path | None = None, lexicon_path: Path | None = None) -> Rules:
    """The checkout's regnal modules on a layer file (lexicon attached as the backend does);
    ``trigger_file`` swaps in another trigger.py."""
    R = regnal()
    data = Path(layer_path).read_bytes()
    layer, lex = _attach_lexicon(R, R.layer.parse_layer(data), Path(layer_path), lexicon_path)
    trig = R.trigger.trigger
    files = dict(R.files_sha256)
    if trigger_file is not None:
        trig = _module_from(Path(trigger_file), f"qset_trigger_{sha256_file(trigger_file)[:12]}").trigger
        files["trigger.py"] = sha256_file(trigger_file)
    fn = getattr(R.seeds, "rule_seeds", None)
    sha = sha256_bytes(data)
    prov = {"layer": {"path": str(layer_path), "sha256": sha, "role": layer_role(sha), "chains": layer.chain_size()},
            "lexicon": lex, "blockers_passed": "blockers" in inspect.signature(trig).parameters,
            "files_sha256": files, "rule_seeds": fn is not None,
            "trigger_file": str(trigger_file) if trigger_file else None}
    return Rules(make_fire(trig, layer), fn, R.engine, layer, prov)


# ---------------------------------------------------------------- reference → layer

def ref_to_layer(ch: S.Chains, V: Any) -> dict[str, str | None]:
    """Reference id → layer id: same kingdom, a shared name, the same position among same-named kings."""
    out: dict[str, str | None] = {}
    for kd in KINGDOMS:
        for x in ch.chain[kd]:
            nth = [y for y in ch.chain[kd] if ch.name(y) == ch.name(x)].index(x)
            cands = [y for y in V.chain.get(kd, []) if any(n in V.names(y) for n in ch.names(x))]
            same = [y for y in cands if V.nodes[y]["name"] == ch.name(x)] or cands
            out[x] = same[nth] if nth < len(same) else None
    return out


def wilson(k: int, n: int, z: float = Z95) -> list[float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def rate(k: int, n: int) -> dict[str, Any]:
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": wilson(k, n)}


# ---------------------------------------------------------------- one question

def _payload_name(payload: str) -> str:
    return re.split(r"[（(]", payload, maxsplit=1)[0]


def card_line(rules: Rules, ids: Sequence[str], item: Mapping[str, Any], ch: S.Chains,
              idmap: Mapping[str, str | None]) -> tuple[bool, str]:
    """(the card holds the asked line with the gold payload, why)."""
    V = rules.layer.view
    try:
        built = rules.engine.cards(V, list(ids))
    except Exception as exc:  # noqa: BLE001 — a crash on a seed set is a card failure to report
        return False, f"engine_error {type(exc).__name__}"
    if built["g_block"] is None:
        return False, "no_card"
    q, start = item["qtype"], idmap.get(item["start"])
    for tag, payload in zip(built["tags"], built["payloads"]):
        tag = list(tag)
        if q == "S1b":
            if tag[0] == "gap" and set(tag[1:3]) == {start, idmap.get(item["other"])}:
                ok = payload == f"{item['gold']}代王位"
                return ok, "ok" if ok else "wrong_payload"
            continue
        want = {"S1a": ["succ", start, item["k"]], "S1c": ["usurper", start, item["n"]], "S4": ["born", start]}[q]
        if tag[:len(want)] == want:
            ok = _payload_name(payload) in ch.names(item["gold"])
            return ok, "ok" if ok else "wrong_payload"
    return False, "no_line"


def rule_seed_ids(rules: Rules, question: str) -> tuple[list[str] | None, str | None]:
    """(node ids, reason) from rule_seeds(layer, question); (None, 'n/a') without the function."""
    if rules.rule_seeds is None:
        return None, "n/a"
    try:
        res = rules.rule_seeds(rules.layer, question)
    except Exception as exc:  # noqa: BLE001 — reported per question, never hidden
        return [], f"error {type(exc).__name__}"
    ids = getattr(res, "ids", res)
    return [str(x) for x in (ids or ())], getattr(res, "reason", None)


def score_item(rules: Rules, item: Mapping[str, Any], ch: S.Chains, idmap: Mapping[str, str | None]) -> dict[str, Any]:
    t = rules.fire(item["question"])
    row = {"id": item["item_id"], "kind": item["kind"], "qtype": item["qtype"], "kingdom": item["kingdom"],
           "writer": item["writer"], "persona": item["persona"], "fired": bool(t.fired), "cues": list(t.cues),
           "kings_found": len(t.kings), "label_consistent": item.get("label_consistent"),
           "flags": list(item.get("flags") or ())}
    if item["kind"] == "near":
        return row
    row["fail"] = None if t.fired else ("king_and_cue_miss" if not t.kings and not t.cues
                                        else "king_miss" if not t.kings else "cue_miss")
    gold = [idmap.get(item["start"])] + ([idmap.get(item["other"])] if item["qtype"] == "S1b" else [])
    row["gold_mapped"] = None not in gold
    row["card_oracle"], row["oracle_why"] = card_line(rules, gold, item, ch, idmap) if t.fired and row["gold_mapped"] \
        else (False, "not_fired" if not t.fired else "gold_not_in_layer")
    if rules.rule_seeds is None:
        row.update(seed=None, seed_reason="n/a", card=None, card_why="n/a")
        return row
    ids, reason = rule_seed_ids(rules, item["question"]) if t.fired else ([], "not_fired")
    row["seed"] = bool(ids) and row["gold_mapped"] and all(g in ids for g in gold)
    row["seed_reason"] = reason
    row["card"], row["card_why"] = card_line(rules, ids, item, ch, idmap) if row["seed"] else (False, "no_seed")
    return row


# ---------------------------------------------------------------- aggregates

def _stage(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any] | str:
    if rows and rows[0].get(key) is None:
        return "n/a"
    return rate(sum(1 for r in rows if r.get(key)), len(rows))


def _pos_block(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"n": len(rows), "R_trig": rate(sum(r["fired"] for r in rows), len(rows)), "R_seed": _stage(rows, "seed"),
            "R_card": _stage(rows, "card"), "R_card_oracle": _stage(rows, "card_oracle"),
            "fail": counts(r["fail"] for r in rows if r["fail"])}


def aggregate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Counts and rates only (no ids, no text): what a P2 run may print."""
    pos = [r for r in rows if r["kind"] == "pos"]
    near = [r for r in rows if r["kind"] == "near"]

    def by(key: str, vals: Sequence[str]) -> dict[str, Any]:
        return {v: _pos_block([r for r in pos if r[key] == v]) for v in vals if any(r[key] == v for r in pos)}
    return {
        "positives": {**_pos_block(pos), "by_type": by("qtype", POS_TYPES), "by_kingdom": by("kingdom", KINGDOMS),
                      "by_writer": by("writer", sorted({r["writer"] for r in pos})),
                      "by_persona": by("persona", sorted({r["persona"] for r in pos})),
                      "label_consistent": _pos_block([r for r in pos if r["label_consistent"] is True]),
                      "label_inconsistent": _pos_block([r for r in pos if r["label_consistent"] is False]),
                      "unlabelled": sum(1 for r in pos if r["label_consistent"] is None),
                      "flagged": {f: _pos_block([r for r in pos if f in r["flags"]])
                                  for f in FLAGS}},
        "near": {"n": len(near), "fired": sum(r["fired"] for r in near),
                 "by_family": {f: {"n": sum(1 for r in near if r["qtype"] == f),
                                   "fired": sum(1 for r in near if r["qtype"] == f and r["fired"])}
                               for f in NEAR_FAMILIES},
                 "gray": {"n": sum(1 for r in near if r["label_consistent"] is False),
                          "fired": sum(1 for r in near if r["label_consistent"] is False and r["fired"])}}}


def paired(new: Sequence[Mapping[str, Any]], old: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """New vs old trigger on the same questions (positives: who fires; near misses: false triggers)."""
    o = {r["id"]: r for r in old}
    pos = [(r["fired"], o[r["id"]]["fired"]) for r in new if r["kind"] == "pos"]
    near = [(r["fired"], o[r["id"]]["fired"]) for r in new if r["kind"] == "near"]
    return {"positives": {"both": sum(a and b for a, b in pos), "new_only": sum(a and not b for a, b in pos),
                          "old_only": sum(b and not a for a, b in pos),
                          "neither": sum(not a and not b for a, b in pos)},
            "near_fired": {"new": sum(a for a, _ in near), "old": sum(b for _, b in near)}}


# ---------------------------------------------------------------- sets

def _fired(rules: Rules, questions: Sequence[tuple[str, str]]) -> dict[str, Any]:
    hits = [qid for qid, q in questions if rules.fire(q).fired]
    return {"n": len(questions), "fired": len(hits), "ids": hits}


def gt_check(rules: Rules, files: Sequence[Path] = GT_FILES) -> dict[str, Any]:
    out = {}
    for f in files:
        qs = read_json(f)["questions"]
        out[Path(f).name] = _fired(rules, [(q["question_id"], q["question"]) for q in qs])
    return out


def regression(rules: Rules, dev: Path = DEV_ITEMS, confirm: Path = CONFIRM_FROZEN) -> dict[str, Any]:
    """Trigger counts on experiment A's sets (in-sample); miss ids only."""
    out = {}
    for name, path, key in (("dev", dev, "items"), ("confirm", confirm, "questions")):
        qs = [(q["id"], q["question"]) for q in read_json(path)[key]]
        f = _fired(rules, qs)
        out[name] = {"n": f["n"], "fired": f["fired"], "missed": sorted(set(i for i, _ in qs) - set(f["ids"]))}
    return out


def score_rows(rules: Rules, items: Sequence[Mapping[str, Any]], ch: S.Chains) -> list[dict[str, Any]]:
    idmap = ref_to_layer(ch, rules.layer.view)
    return [score_item(rules, it, ch, idmap) for it in items if it["valid"]]


def score_doc(rules: Rules, items: Sequence[Mapping[str, Any]], ch: S.Chains, side: str,
              compare: Rules | None = None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """(result without rows, rows) of one set under ``rules`` (and paired under ``compare``)."""
    rows = score_rows(rules, items, ch)
    out = {"utc": now(), "set": side, "rules": rules.provenance,
           "invalid_excluded": sum(1 for i in items if not i["valid"]), "aggregate": aggregate(rows)}
    if compare is not None:
        old_rows = score_rows(compare, items, ch)
        out["compare"] = {"rules": compare.provenance, "aggregate": aggregate(old_rows),
                          "paired": paired(rows, old_rows)}
    return out, rows


def record(root: Path, out: Mapping[str, Any], rows: Sequence[Mapping[str, Any]],
           again: bool = False) -> dict[str, Any]:
    """P2: one appended line of aggregates (refused when P2 was scored before, unless ``again``);
    P1: scores/p1_<utc>.json with the rows."""
    out = dict(out)
    if out["set"] == "p2":
        before = read_jsonl(Path(root) / P2_RUNS)
        if before and not again:
            raise QError(f"P2 was scored {len(before)} time(s) already; rerun only with --again (and disclose it)")
        out["run_index"] = len(before) + 1
        append_jsonl(Path(root) / P2_RUNS, out, root)
        return out
    stamp = out["utc"].replace(":", "").replace("-", "")[:15]
    write_json(Path(root) / "scores" / f"{out['set']}_{stamp}.json", {**out, "rows": list(rows)}, root)
    return out


def score_set(root: Path, side: str, layer: Path, compare_trigger: Path | None = None,
              again: bool = False, lexicon: Path | None = None) -> dict[str, Any]:
    score_layer_check(sha256_file(layer), side)
    spec = S.load_spec(root)
    ref = S.load_ref()
    if ref.sha256 != spec["ref"]["sha256"]:
        raise QError("the reference layer changed since the spec was built")
    path = Path(root) / side / "items.json"
    doc = read_json(path)
    if doc["spec_sha256"] != S.spec_sha(spec):
        raise QError(f"{side}/items.json was assembled from another spec")
    if side == "p2" and read_jsonl(Path(root) / P2_RUNS) and not again:
        raise QError("P2 was scored already; rerun only with --again (and disclose it)")
    compare = load_rules(layer, compare_trigger, lexicon) if compare_trigger is not None else None
    out, rows = score_doc(load_rules(layer, lexicon_path=lexicon), doc["items"], S.Chains(ref.rows), side, compare)
    out.update(spec_sha256=S.spec_sha(spec), items_sha256=sha256_file(path), ref_sha256=ref.sha256)
    return record(root, out, rows, again)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="問法集計分（CPU）")
    ap.add_argument("cmd", choices=("score", "gt", "regress"))
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--set", choices=("p1", "p2"))
    ap.add_argument("--layer", type=Path, required=True,
                    help="regnal_layer.json to score on (formal scores: the r4 layer, qset.md §5)")
    ap.add_argument("--lexicon", type=Path, default=None,
                    help="routing_lexicon.json (default: next to --layer; used when the layer takes one)")
    ap.add_argument("--compare-trigger", type=Path, default=None)
    ap.add_argument("--again", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "score":
        if not a.set:
            raise QError("score needs --set p1|p2")
        out: Any = score_set(a.root, a.set, a.layer, a.compare_trigger, a.again, a.lexicon)
    elif a.cmd == "gt":
        rules = load_rules(a.layer, lexicon_path=a.lexicon)
        out = {"rules": rules.provenance, "gt": gt_check(rules)}
        if a.compare_trigger:
            cmp_rules = load_rules(a.layer, a.compare_trigger, a.lexicon)
            out["compare_gt"] = gt_check(cmp_rules)
            out["compare_rules"] = cmp_rules.provenance
    else:
        rules = load_rules(a.layer, lexicon_path=a.lexicon)
        out = {"rules": rules.provenance, "regression": regression(rules)}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (QError, OSError, ValueError) as err:
        print(json.dumps({"error": f"{type(err).__name__}: {err}"}, ensure_ascii=False))
        sys.exit(2)
