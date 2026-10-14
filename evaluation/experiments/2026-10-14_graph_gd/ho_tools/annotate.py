"""Verse text and the annotate.py checks for HO questions (copy of E7/newq/annotate.py).

annotate_item() adds what the review page and the §7 format need to one question: `hops`
(role and, per verse, key / passage / title / text), `n_hops`, `n_passages`, `books`,
`cross_book` and `auto_warnings` (the archived checks: a key that does not resolve, hops
that share a passage, fewer than 2 hops). It reads the pinned text layer (_ho_text) and
never /tmp; passages follow gd's verse_index (§4).

    annotate.py IN.json OUT.json      IN: {"questions": [...]}, a list, or a state.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from _ho_common import HoToolError, gd  # first: sets sys.path

import _ho_text as T  # noqa: E402

__all__ = ["annotate_item", "annotate_all", "load_items", "ANNOTATED_KEYS", "main"]

ANNOTATED_KEYS = ("hops", "n_hops", "n_passages", "books", "cross_book", "auto_warnings")


def _hop(i: int, slots: Sequence[str], roles: Sequence[str], warn: list[str]) -> tuple[dict, set]:
    verses, pids = [], set()
    for key in slots:
        st = T.resolve(key)
        if st.problem:
            warn.append(f"第 {i + 1} 跳經節 {key} 不存在" if st.problem == "not found"
                        else f"第 {i + 1} 跳經節 {key} 是半節鍵")
            continue
        for unit in st.units:
            passages = T.unit_passages(unit)
            pids.update(passages)
            verses.append({"key": unit, "pid": passages[0], "split": list(passages[1:]),
                           "title": T.passage_meta()[passages[0]][0], "text": T.verses()[unit].text})
    role = roles[i] if i < len(roles) else ""
    return {"role": role, "verses": verses}, pids


def annotate_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """A new dict: `item` plus ANNOTATED_KEYS (existing values of those keys are replaced)."""
    slots = item.get("hop_slots") or []
    roles = item.get("hop_roles") or []
    warn: list[str] = []
    hops, per_hop = [], []
    for i, hop in enumerate(slots):
        h, pids = _hop(i, hop if isinstance(hop, list) else [], roles, warn)
        hops.append(h)
        per_hop.append(pids)
    for i in range(len(per_hop)):
        for j in range(i + 1, len(per_hop)):
            shared = per_hop[i] & per_hop[j]
            if shared:
                warn.append(f"第 {i + 1}、{j + 1} 跳共用段落 {', '.join(sorted(shared))}")
    if len(hops) < 2:
        warn.append("少於 2 跳")
    all_pids = set().union(*per_hop) if per_hop else set()
    books = sorted({p.split(":")[1].split(".")[0] for p in all_pids if ":" in p})
    return {**item, "hops": hops, "n_hops": len(hops), "n_passages": len(all_pids), "books": books,
            "cross_book": len(books) > 1, "auto_warnings": warn}


def load_items(path: Path) -> list[dict[str, Any]]:
    """Questions of a {"questions": [...]} file, a plain list, or a state.json (records' items)."""
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("questions"), list):
        return doc["questions"]
    if isinstance(doc, dict) and isinstance(doc.get("records"), list):
        return [r["item"] for r in doc["records"] if r.get("item")]
    raise HoToolError(f"{path}: expected a question list, {{'questions': [...]}} or a state.json")


def annotate_all(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [annotate_item(q) for q in items]


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("annotate.py: usage: annotate.py IN.json OUT.json", file=sys.stderr)
        return 2
    try:
        out = annotate_all(load_items(Path(args[0])))
    except (gd.GdError, OSError, ValueError) as err:
        print(f"annotate.py: {type(err).__name__}: {err}", file=sys.stderr)
        return 2
    Path(args[1]).write_text(json.dumps({"questions": out}, ensure_ascii=False, indent=1) + "\n",
                             encoding="utf-8")
    print(f"annotate.py: {len(out)} questions, "
          f"{sum(bool(q['auto_warnings']) for q in out)} with warnings -> {args[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
