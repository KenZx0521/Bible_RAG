"""G-REF: verse references resolve the way the services will resolve them (design §8).

The services resolve verse numbers through ``ragcommon.versification`` (backend
verse_parser, evaluation reference_parser, GT lint), so its data must be the
text layer's own: for every book of the snapshot, the same last chapter, the
same max verse in each chapter, the same omitted slots (with the unit whose
variant footnote holds them) and the same ref_aliases, each resolving to a
present slot. Every parallel-reference and footnote-citation target lies on
that grid, and a section_range stays inside its own book (it is never a
parallel link). Run ``scripts/derive_ragcommon_data.py`` on a new text layer
to bring ragcommon up to date.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterator

from ragcommon import ids
from ragcommon.versification import Versification, VersificationError
from ragdata.gates.base import GateResult, Snapshot, violations_result

NAME = "G-REF"


def _grid(snapshot: Snapshot, vers: Versification) -> list[str]:
    out = []
    last: dict[str, int] = defaultdict(int)
    for c in snapshot.of("chapters"):
        last[c.book_id] = max(last[c.book_id], c.chapter)
        try:
            theirs = vers.max_verse(c.book_id, c.chapter)
        except (VersificationError, KeyError) as exc:
            out.append(f"{c.chapter_key}: ragcommon has no such chapter ({exc})")
            continue
        if theirs != c.max_verse:
            out.append(f"{c.chapter_key}: max verse {c.max_verse}, ragcommon {theirs}")
    for book, chapter in sorted(last.items()):
        theirs = len(vers.max_verses.get(book, ()))
        if theirs != chapter:
            out.append(f"{book}: last chapter {chapter}, ragcommon {theirs}")
    return out


def _omitted(snapshot: Snapshot, vers: Versification, held: set[str]) -> list[str]:
    mine = {s.slot_key: ids.parse(s.variant_footnote_id).parent.raw
            for s in snapshot.of("verse_slots") if s.status == "omitted_variant"}
    theirs = {k: o.variant_in_footnote_of for k, o in vers.omitted.items()
              if ids.parse(k).book_id in held}
    return [f"omitted slot {k}: layer {mine.get(k)}, ragcommon {theirs.get(k)}"
            for k in sorted(set(mine) | set(theirs)) if mine.get(k) != theirs.get(k)]


def _aliases(snapshot: Snapshot, vers: Versification, held: set[str]) -> list[str]:
    mine = {a.external_ref: (a.relation, a.target) for a in snapshot.of("ref_aliases")}
    theirs = {k: (a.relation, a.target) for k, a in vers.aliases.items()
              if ids.parse(k).book_id in held}
    out = [f"ref alias {k}: layer {mine.get(k)}, ragcommon {theirs.get(k)}"
           for k in sorted(set(mine) | set(theirs)) if mine.get(k) != theirs.get(k)]
    present = {s.slot_key for s in snapshot.of("verse_slots") if s.status != "omitted_variant"}
    out += [f"ref alias {k}: target {target} is not a present slot"
            for k, (_, target) in sorted(mine.items()) if target not in present]
    return out


def _targets(snapshot: Snapshot) -> Iterator[tuple[str, str]]:
    for p in snapshot.of("parallel_refs"):
        for t in p.targets:
            yield p.pr_id, t.start_slot
            yield p.pr_id, t.end_slot
    for f in snapshot.of("footnotes"):
        for t in f.refs:
            yield f.fn_id, t.start_slot
            yield f.fn_id, t.end_slot


def _resolve(snapshot: Snapshot, vers: Versification) -> list[str]:
    out = []
    for owner, slot in _targets(snapshot):
        s = ids.parse(slot)
        if s.book_id not in vers.max_verses or not vers.has_slot(s.book_id, s.chapter, s.verse):
            out.append(f"{owner}: target {slot} is not on the verse grid")
    headings = {h.heading_id: h.book_id for h in snapshot.of("headings")}
    out += [f"{p.pr_id}: section_range leaves its book {headings.get(p.heading_id)}"
            for p in snapshot.of("parallel_refs") if p.kind == "section_range"
            and any(t.book_id != headings.get(p.heading_id) for t in p.targets)]
    return out


def check_ref(snapshot: Snapshot, vers: Versification) -> GateResult:
    held = {b.book_id for b in snapshot.of("books")}
    violations = _grid(snapshot, vers) + _omitted(snapshot, vers, held) \
        + _aliases(snapshot, vers, held) + _resolve(snapshot, vers)
    if not snapshot.of("chapters"):
        violations.append("no chapters to check")
    return violations_result(NAME, violations)
