"""§7 機械稽核 of HO questions and agent transcripts (逐批跑，凍結前再全量跑一次).

Question rules (one Violation per failure; every rule is checked, not just the first):

  fields        all §7 fields (gd.HO_FIELDS) present; question and core non-empty strings,
                change_log a string, key_points a list of strings
  id_prefix     id prefix H_KIN_/H_DIS_/H_TO_/H_MH_ and a category of that class (no NULL)
  duplicate_id  an earlier question has the same id
  hops_count    2–5 hops (gd.HO_HOPS)
  half_key      an a/b half-verse key (§4 gold undefined)
  key_form      not a whole or merged verse key (range keys are refused)
  verse_missing a key that does not resolve (annotate.py: 經節存在)
  hop_no_pid    a hop with no resolvable verse (annotate.py: 每跳有 pid)
  gold          a hop's §4 gold cannot be computed
  hop_overlap   two hops of the question share a §4 gold passage
  overlap_new82 / overlap_old31 / overlap_ho
                gold shared with NEW82, OLD31 or an earlier HO question (§4 gold sets)
  core_limit    a third question on the same core (gd.HO_MAX_PER_CORE)
  core_similar  (warn) the core contains, or is contained in, an earlier question's core
                (「約西亞」/「約西亞王」): the same person under another spelling escapes
                core_limit, so the agents see every core in use and the auditor flags it
  hop_roles     (warn) hop_roles not one per hop

Questions are checked in order, each against the ones before it, so of two clashing
questions the later one is flagged (the §7 commit order). Transcript rules are in
_ho_transcript.py. The final gate is still gd.check_ho_items / gd.load_ho (freeze.py).

    mech_check.py questions   --root R [--scope live|selected] [--out F]
    mech_check.py transcripts --root R [--scope live|selected|all] [--out F]
    mech_check.py file --in QUESTIONS.json [--out F]

Exit 0 clean, 1 error-level violations (report written), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from _ho_common import HO_DIR, Violation, gd, ho_meta  # first: sets sys.path

import _gd_sets  # noqa: E402  _HO_SLOT: the whole / merged key form of the HO loader
import _ho_state as S  # noqa: E402
import _ho_transcript as TR  # noqa: E402
import annotate  # noqa: E402

__all__ = ["Context", "store_context", "item_gold", "check_item", "check_set", "main",
           "QUESTION_RULES", "SCRIPT_FILES"]

QUESTION_RULES = ("fields", "id_prefix", "duplicate_id", "hops_count", "half_key", "key_form",
                  "verse_missing", "hop_no_pid", "gold", "hop_overlap", "overlap_new82",
                  "overlap_old31", "overlap_ho", "core_limit", "core_similar", "hop_roles")
SCRIPT_FILES = tuple(HO_DIR / n for n in ("mech_check.py", "_ho_common.py", "_ho_state.py",
                                         "_ho_transcript.py", "_ho_claude.py", "_ho_text.py",
                                         "annotate.py", "banned.py", "bt_guard.py"))


@dataclass(frozen=True)
class Context:
    """Gold owners outside HO (pid -> 'new82:ID' / 'old31:ID') and the layers gold reads."""
    owners: Mapping[str, str]
    units: gd.VerseUnits | None = None
    vindex: gd.VerseIndex | None = None


def store_context() -> Context:
    """NEW82 and OLD31 gold owners from the pinned store (questions and gold only)."""
    owners = {}
    for qset in (gd.load_new82(), gd.load_old31()):
        for q in qset.questions:
            for gold in gd.question_gold(q):
                for pid in gold:
                    owners.setdefault(pid, f"{qset.name}:{q.qid}")
    return Context(MappingProxyType(owners))


def _key_violations(qid: str, h: int, key: Any, ctx: Context) -> list[Violation]:
    where = f"{qid} hop {h + 1} key {key!r}"
    if not isinstance(key, str):
        return [Violation("key_form", f"{where}: not a string")]
    if gd.is_half_verse_key(key):
        return [Violation("half_key", where)]
    if not _gd_sets._HO_SLOT.fullmatch(key):
        return [Violation("key_form", f"{where}: not a whole or merged verse key")]
    try:
        gd.resolve_key(key, ctx.units)
    except gd.GoldError:
        return [Violation("verse_missing", where)]
    return []


def item_gold(item: Mapping[str, Any], ctx: Context) -> tuple[frozenset[str], ...] | None:
    """§4 gold per hop, or None when any hop's gold cannot be computed."""
    try:
        return tuple(gd.hop_gold(list(h), ctx.units, ctx.vindex) for h in item.get("hop_slots") or ())
    except (gd.GdError, TypeError):
        return None


def _field_violations(item: Mapping[str, Any]) -> list[Violation]:
    qid = str(item.get("id", "?"))
    out = [Violation("fields", f"{qid}: missing {f}") for f in gd.HO_FIELDS if f not in item]
    for name in ("question", "core"):
        if name in item and not (isinstance(item[name], str) and item[name].strip()):
            out.append(Violation("fields", f"{qid}: {name} must be a non-empty string"))
    if "change_log" in item and not isinstance(item["change_log"], str):
        out.append(Violation("fields", f"{qid}: change_log must be a string"))
    kp = item.get("key_points")
    if "key_points" in item and not (isinstance(kp, list) and all(isinstance(k, str) for k in kp)):
        out.append(Violation("fields", f"{qid}: key_points must be a list of strings"))
    prefix = next((p for p in gd.HO_CATEGORY if qid.startswith(p)), None)
    if prefix is None:
        out.append(Violation("id_prefix", f"{qid}: prefix not one of {list(gd.HO_CATEGORY)}"))
    elif gd.NEW82_CATEGORY.get(item.get("category")) != gd.HO_CATEGORY[prefix]:
        out.append(Violation("id_prefix", f"{qid}: category {item.get('category')!r} is not a {prefix} one"))
    return out


def _hop_violations(item: Mapping[str, Any], ctx: Context) -> list[Violation]:
    qid, hops = str(item.get("id", "?")), item.get("hop_slots")
    lo, hi = gd.HO_HOPS
    if not isinstance(hops, list):
        return [Violation("hops_count", f"{qid}: hop_slots is not a list")]
    out = [] if lo <= len(hops) <= hi else [Violation("hops_count", f"{qid}: {len(hops)} hops")]
    for h, hop in enumerate(hops):
        keys = hop if isinstance(hop, list) else []
        per_key = [_key_violations(qid, h, k, ctx) for k in keys]
        out += [v for vs in per_key for v in vs]
        good = [k for k, vs in zip(keys, per_key) if not vs]
        if not good:
            out.append(Violation("hop_no_pid", f"{qid} hop {h + 1}: no resolvable verse"))
            continue
        try:
            gd.hop_gold(good, ctx.units, ctx.vindex)
        except gd.GdError as err:
            out.append(Violation("gold", f"{qid} hop {h + 1}: {err}"))
    roles = item.get("hop_roles")
    if not (isinstance(roles, list) and len(roles) == len(hops)):
        out.append(Violation("hop_roles", f"{qid}: hop_roles is not one per hop", "warn"))
    return out


def _overlap_violations(qid: str, gold: Sequence[frozenset[str]], ctx: Context,
                        earlier: Sequence[tuple[str, Sequence[frozenset[str]]]]) -> list[Violation]:
    out = []
    for i in range(len(gold)):
        for j in range(i + 1, len(gold)):
            for pid in sorted(gold[i] & gold[j]):
                out.append(Violation("hop_overlap", f"{qid}: hops {i + 1} and {j + 1} share {pid}"))
    mine = frozenset().union(*gold) if gold else frozenset()
    for pid in sorted(mine):
        owner = ctx.owners.get(pid)
        if owner:
            out.append(Violation(f"overlap_{owner.split(':')[0]}", f"{qid}: {pid} is gold of {owner}"))
    for other, ogold in earlier:
        for pid in sorted(mine & frozenset().union(*ogold)) if ogold else ():
            out.append(Violation("overlap_ho", f"{qid}: {pid} is gold of {other}"))
    return out


def check_item(item: Mapping[str, Any], ctx: Context, earlier: Sequence[Mapping[str, Any]] = (),
               earlier_gold: Sequence[tuple[frozenset[str], ...] | None] | None = None) -> list[Violation]:
    """Every question rule for `item`, against the HO questions committed before it
    (`earlier_gold`: their item_gold, when the caller already has it)."""
    qid = str(item.get("id", "?"))
    out = _field_violations(item) + _hop_violations(item, ctx)
    if any(str(e.get("id")) == qid for e in earlier):
        out.append(Violation("duplicate_id", qid))
    gold = item_gold(item, ctx)
    if gold is not None:
        golds = earlier_gold if earlier_gold is not None else [item_gold(e, ctx) for e in earlier]
        prior = [(str(e.get("id")), g) for e, g in zip(earlier, golds) if g is not None]
        out += _overlap_violations(qid, gold, ctx, prior)
    return out + _core_violations(qid, item.get("core"), earlier)


def _core_violations(qid: str, core: Any, earlier: Sequence[Mapping[str, Any]]) -> list[Violation]:
    core = core.strip() if isinstance(core, str) else None
    if not core:
        return []
    cores = [e["core"].strip() for e in earlier if isinstance(e.get("core"), str) and e["core"].strip()]
    same = cores.count(core)
    out = [Violation("core_limit", f"{qid}: core {core!r} already has {same} questions")] \
        if same >= gd.HO_MAX_PER_CORE else []
    similar = sorted({c for c in cores if c != core and min(len(c), len(core)) >= 2 and (c in core or core in c)})
    out += [Violation("core_similar", f"{qid}: core {core!r} resembles {c!r} ({cores.count(c)} questions)", "warn")
            for c in similar]
    return out


def check_set(items: Sequence[Mapping[str, Any]], ctx: Context) -> dict[str, list[Violation]]:
    """check_item for each question against the ones before it (commit order)."""
    golds = [item_gold(it, ctx) for it in items]
    return {str(it.get("id", f"#{i}")): check_item(it, ctx, items[:i], golds[:i])
            for i, it in enumerate(items)}


# ------------------------------------------------------------------ CLI

def _scoped(state: Mapping[str, Any], scope: str) -> list[dict[str, Any]]:
    if scope == "selected":
        return S.selection(state)
    if scope == "live":
        return S.records(state, statuses=S.LIVE)
    return list(state["records"])


def _report(kind: str, found: Mapping[str, Sequence[Violation]], **extra: Any) -> dict[str, Any]:
    errors = {k: [v.as_dict() for v in vs] for k, vs in found.items() if vs}
    return {"meta": ho_meta(f"mech_check.py {kind}", SCRIPT_FILES),
            "kind": kind, **extra, "checked": len(found),
            "with_errors": sorted(k for k, vs in found.items() if any(v.level == "error" for v in vs)),
            "violations": errors}


def run_cli(a: argparse.Namespace) -> tuple[dict[str, Any], Path]:
    if a.cmd == "file":
        items = annotate.load_items(a.inp)
        found = check_set([annotate.annotate_item(q) for q in items], store_context())
        return _report("file", found, input=str(a.inp)), a.out or a.inp.with_suffix(".mech.json")
    state = S.load_state(a.root)
    recs = _scoped(state, a.scope)
    if a.cmd == "questions":
        found = check_set([r["item"] for r in recs if r.get("item")], store_context())
    else:
        found = {run: TR.check_run(a.root, run) for r in recs for run in r["runs"]}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = a.out or Path(a.root) / "mech" / f"{a.cmd}_{a.scope}_{stamp}.json"
    return _report(a.cmd, found, root=str(a.root), scope=a.scope), out


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, scopes in (("questions", ("live", "selected")), ("transcripts", ("live", "selected", "all"))):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--scope", choices=scopes, default="live")
        p.add_argument("--out", type=Path)
    p = sub.add_parser("file")
    p.add_argument("--in", dest="inp", type=Path, required=True)
    p.add_argument("--out", type=Path)
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    a = parse_args(argv)
    doc, out = run_cli(a)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    n_err = len(doc["with_errors"])
    print(f"mech_check.py {a.cmd}: {doc['checked']} checked, {n_err} with errors -> {out}")
    return 1 if n_err else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (gd.GdError, OSError, ValueError) as err:
        print(f"mech_check.py: {type(err).__name__}: {err}", file=sys.stderr)
        sys.exit(2)
