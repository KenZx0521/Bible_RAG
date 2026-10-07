"""K0 parallel links: the pericope pairs the printed parallel references draw (design §2.17).

Only ``kind=parallel`` segments count; a ``section_range`` (結1‧1－7‧27 under a book
section heading) never becomes a link (§2.8, G-REF). The link runs from the
pericope that carries the reference's heading (as its heading or as its stacked
section heading) to every pericope its target range overlaps, by verse slot; a
target that ends on a verse cut by a mid-verse heading overlaps both halves.
"""

from __future__ import annotations

from typing import Any

from ragcommon import ids
from ragdata.gates.base import Snapshot
from ragdata.stages.errors import StageError

Order = dict[str, tuple[int, int, int]]


def slot_order(snapshot: Snapshot) -> Order:
    """(book ord, chapter, verse) of every slot, for range comparisons across chapters."""
    book_ord = {b.book_id: b.ord for b in snapshot.of("books")}
    order = {}
    for slot in snapshot.of("verse_slots"):
        p = ids.parse(slot.slot_key)
        order[slot.slot_key] = (book_ord[p.book_id], p.chapter, p.verse)
    return order


def _pericope_of_heading(snapshot: Snapshot) -> dict[str, str]:
    owner = {}
    for pc in snapshot.of("pericopes"):
        for heading in (pc.heading_id, pc.section_heading_id):
            if heading is not None:
                owner.setdefault(heading, pc.pericope_id)
    return owner


def _at(order: Order, slot: str, where: str) -> tuple[int, int, int]:
    if slot not in order:
        raise StageError(f"{where}: slot {slot} is not in the text layer")
    return order[slot]


def parallel_links(snapshot: Snapshot) -> list[dict[str, Any]]:
    order = slot_order(snapshot)
    owner = _pericope_of_heading(snapshot)
    spans = [(_at(order, pc.start_slot, pc.pericope_id), _at(order, pc.end_slot, pc.pericope_id),
              pc.pericope_id) for pc in snapshot.of("pericopes")]
    rows, seen = [], set()
    for pr in snapshot.of("parallel_refs"):
        if pr.kind != "parallel":
            continue
        source = owner.get(pr.heading_id)
        if source is None:
            raise StageError(f"{pr.pr_id}: no pericope carries heading {pr.heading_id}")
        for target in pr.targets:
            lo, hi = _at(order, target.start_slot, pr.pr_id), _at(order, target.end_slot, pr.pr_id)
            for start, end, pericope in spans:
                key = f"{pr.pr_id}|{pericope}"
                if start <= hi and lo <= end and pericope != source and key not in seen:
                    seen.add(key)
                    rows.append({"link_key": key, "pr_id": pr.pr_id, "from_pericope": source,
                                 "to_pericope": pericope, "target_start_slot": target.start_slot,
                                 "target_end_slot": target.end_slot,
                                 "provenance_class": "pdf_deterministic"})
    return rows
