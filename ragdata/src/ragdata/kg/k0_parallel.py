"""K0 parallel links: the pericope pairs the printed parallel references draw (design §2.17).

Only ``kind=parallel`` segments count; a ``section_range`` (結1‧1－7‧27 under a book
section heading) never becomes a link (§2.8, G-REF). The link runs from the
pericope that carries the reference's heading (as its heading or as its stacked
section heading) to every pericope its target range reaches (``reaches``).

A printed range carries no a/b half-verse mark, so a verse cut by a mid-verse
heading counts as one slot in both pericopes. A range whose last verse is cut
means the half before the cut, one whose first verse is cut the half after it:
路9‧37－43 is 治好被污鬼附身的孩子, not also 耶穌第二次預言他的死 (pc:luk.9.43b).
A target of the cut verse alone keeps both halves.
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


def _require_slots(order: Order, where: str, *slots: str) -> None:
    for slot in slots:
        if slot not in order:
            raise StageError(f"{where}: slot {slot} is not in the text layer")


def far_half(pericope: Any, start_slot: str, end_slot: str) -> bool:
    """The range of several verses touches ``pericope`` only past a mid-verse cut: its
    last verse is where the pericope starts mid-verse, or its first verse is where the
    pericope ends mid-verse."""
    if start_slot == end_slot:
        return False
    return (end_slot == pericope.start_slot and pericope.start.offset > 0) or \
        (start_slot == pericope.end_slot and pericope.end.offset is not None)


def reaches(order: Order, pericope: Any, start_slot: str, end_slot: str) -> bool:
    """The target range ``start_slot``..``end_slot`` overlaps ``pericope`` by verse slot,
    beyond the far half of a cut verse."""
    overlaps = order[pericope.start_slot] <= order[end_slot] and \
        order[start_slot] <= order[pericope.end_slot]
    return overlaps and not far_half(pericope, start_slot, end_slot)


def _link(pr: Any, source: str, target: Any, to: str) -> dict[str, Any]:
    return {"link_key": f"{pr.pr_id}|{to}", "pr_id": pr.pr_id, "from_pericope": source,
            "to_pericope": to, "target_start_slot": target.start_slot,
            "target_end_slot": target.end_slot, "provenance_class": "pdf_deterministic"}


def parallel_links(snapshot: Snapshot) -> list[dict[str, Any]]:
    order = slot_order(snapshot)
    owner = _pericope_of_heading(snapshot)
    pericopes = snapshot.of("pericopes")
    for pc in pericopes:
        _require_slots(order, pc.pericope_id, pc.start_slot, pc.end_slot)
    rows, seen = [], set()
    for pr in snapshot.of("parallel_refs"):
        if pr.kind != "parallel":
            continue
        source = owner.get(pr.heading_id)
        if source is None:
            raise StageError(f"{pr.pr_id}: no pericope carries heading {pr.heading_id}")
        for target in pr.targets:
            _require_slots(order, pr.pr_id, target.start_slot, target.end_slot)
            for pc in pericopes:
                key = f"{pr.pr_id}|{pc.pericope_id}"
                if pc.pericope_id != source and key not in seen and \
                        reaches(order, pc, target.start_slot, target.end_slot):
                    seen.add(key)
                    rows.append(_link(pr, source, target, pc.pericope_id))
    return rows
