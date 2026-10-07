"""G-REFINT: referential integrity of a layer snapshot.

Two kinds of checks:
- foreign keys: every id a record refers to exists in the target record type
  (struct-layer keys reach into the text layer, so gate struct together with it);
- agreement: references agree with what they point at — slots tile their unit
  and their chapter's verse grid, omitted slots and variant footnotes point at
  each other, stored aggregates equal the records, offsets fall inside their
  container and name/errata slices match its text, passages and pericopes list
  each other (passages carry their pericope's title), and prev/next links are
  mutual.
So a record that is deleted while something still refers to it or counts it,
or a reference redirected to a record that disagrees, turns this gate red
(audit G58). References that cross books (parallel targets, footnote citations)
are checked only into books the snapshot holds, so a build of some books can be
gated; that a full build holds all 66 books is G-COUNT's and G-SRC's job.
It only checks that the records agree with each other: content
that is consistently wrong or missing everywhere (a truncated verse with a
recomputed sha, a passage that skips a verse, a pericope that ends early,
dropped chunks, unset links) is the job of G-COUNT, G-TEXT, G-CONSERVE,
G-XCHECK and G-STRUCT.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping

from ragcommon import ids
from ragdata.contract import RECORD_TYPES, record_type
from ragdata.gates.base import GateResult, Snapshot, violations_result

NAME = "G-REFINT"
Index = Mapping[str, Mapping[str, Any]]
CONTAINER_TYPES = {
    "slot": "verse_units", "unit": "verse_units", "footnote": "footnotes", "heading": "headings",
    "superscription": "chapter_texts", "division": "chapter_texts", "speaker": "speakers",
}


@dataclass(frozen=True)
class ForeignKey:
    source: str
    label: str
    target: str
    refs: Callable[[Any], Iterable[str | None]]
    cross_book: bool = False  # only references into books the snapshot holds are checked


def fk(source: str, label: str, target: str,
       refs: Callable[[Any], Iterable[str | None]] | None = None,
       cross_book: bool = False) -> ForeignKey:
    return ForeignKey(source, label, target, refs or (lambda r: [getattr(r, label)]), cross_book)


def _chapter_of(key: str) -> str:
    p = ids.parse(key)
    return ids.chapter_key(p.book_id, p.chapter)


def _range_slots(field: str) -> Callable[[Any], list[str]]:
    return lambda r: [s for t in getattr(r, field) for s in (t.start_slot, t.end_slot)]


def _unit_refs(r: Any) -> list[str]:
    return [u.unit_key for u in r.unit_refs] + list(getattr(r, "overlap_unit_keys", ()))


def _new_ids(kind: str) -> Callable[[Any], list[str]]:
    """The new ids of a legacy row that are of ``kind`` (verse records as their unit key)."""
    def refs(r: Any) -> list[str]:
        found = [ids.parse(i) for i in r.new_ids]
        return [p.parent.raw if kind == "verse_record" else p.raw for p in found if p.kind == kind]
    return refs


TEXT_FKS = (
    fk("chapters", "book_id", "books"),
    fk("chapters", "omitted_slots", "verse_slots", lambda c: c.omitted_slots),
    fk("chapters", "book_division_id", "chapter_texts"),
    fk("verse_units", "chapter", "chapters", lambda u: [_chapter_of(u.unit_key)]),
    fk("verse_units", "errata_ids", "errata_applied", lambda u: u.errata_ids),
    fk("verse_slots", "chapter", "chapters", lambda s: [_chapter_of(s.slot_key)]),
    fk("verse_slots", "unit_key", "verse_units"),
    fk("verse_slots", "variant_footnote_id", "footnotes"),
    fk("chapter_texts", "chapter_key", "chapters"),
    fk("headings", "anchor_unit_key", "verse_units"),
    fk("headings", "parent_heading_id", "headings"),
    fk("parallel_refs", "heading_id", "headings"),
    fk("parallel_refs", "targets", "verse_slots", _range_slots("targets"), cross_book=True),
    fk("footnotes", "unit_key", "verse_units"),
    fk("footnotes", "variant_slot_key", "verse_slots"),
    fk("footnotes", "refs", "verse_slots", _range_slots("refs"), cross_book=True),
    fk("footnotes", "errata_ids", "errata_applied", lambda f: f.errata_ids),
    fk("speakers", "unit_key", "verse_units"),
    fk("ref_aliases", "target", "verse_slots"),
)

STRUCT_FKS = (
    fk("pericopes", "book_id", "books", lambda p: [p.book_id, p.next_book_id]),
    fk("pericopes", "heading_id", "headings", lambda p: [p.heading_id, p.section_heading_id]),
    fk("pericopes", "start/end", "verse_units", lambda p: [p.start.unit_key, p.end.unit_key]),
    fk("pericopes", "start_slot/end_slot", "verse_slots", lambda p: [p.start_slot, p.end_slot]),
    fk("pericopes", "passage_ids", "passages", lambda p: p.passage_ids),
    fk("pericopes", "prev_id/next_id", "pericopes", lambda p: [p.prev_id, p.next_id]),
    fk("passages", "pericope_id", "pericopes"),
    fk("passages", "chapter_key", "chapters"),
    fk("passages", "start_slot/end_slot", "verse_slots", lambda p: [p.start_slot, p.end_slot]),
    fk("passages", "unit_refs", "verse_units", _unit_refs),
    fk("passages", "superscription_id", "chapter_texts"),
    fk("chunks", "passage_id", "passages"),
    fk("chunks", "unit_refs", "verse_units", _unit_refs),
    fk("verse_index", "unit_key", "verse_units"),
    fk("verse_index", "passage_id", "passages",
       lambda v: [v.passage_id, *v.split_passage_ids]),
    fk("verse_index", "pericope_id", "pericopes"),
    fk("legacy_ids", "new_ids", "passages", _new_ids("passage")),
    fk("legacy_ids", "new_ids", "chunks", _new_ids("chunk")),
    fk("legacy_ids", "new_ids", "verse_units", _new_ids("verse_record")),
)

KG0_FKS = (
    fk("parallel_links", "pr_id", "parallel_refs"),
    fk("parallel_links", "from/to", "pericopes", lambda k: [k.from_pericope, k.to_pericope]),
    fk("parallel_links", "target", "verse_slots",
       lambda k: [k.target_start_slot, k.target_end_slot]),
)

EVENTS_FKS = (
    fk("events", "anchors", "passages", lambda e: [a.passage_id for a in e.anchors]),
    fk("events", "anchor slots", "verse_slots",
       lambda e: [s for a in e.anchors for s in (a.start_slot, a.end_slot)]),
    fk("anchor_changes", "event_id", "events"),
    fk("anchor_changes", "passage_id", "passages"),
    fk("anchor_changes", "slots", "verse_slots",
       lambda c: [c.legacy_start_slot, c.legacy_end_slot, *c.removed_slots]),
)


def _dangling(idx: Index, key: ForeignKey) -> list[str]:
    pk, target = record_type(key.source).pk, idx[key.target]
    held = idx["books"]
    return [f"{key.source} {getattr(rec, pk)}: {key.label} {ref} not found in {key.target}"
            for rec in idx[key.source].values() for ref in key.refs(rec)
            if ref is not None and ref not in target
            and not (key.cross_book and ids.parse(ref).book_id not in held)]


# ------------------------------------------------------------------ text agreement


def _slot_tiling(idx: Index) -> list[str]:
    covered: dict[str, set[int]] = defaultdict(set)
    grid: dict[str, list[int]] = defaultdict(list)
    for slot in idx["verse_slots"].values():
        verse = ids.parse(slot.slot_key).verse
        grid[_chapter_of(slot.slot_key)].append(verse)
        if slot.unit_key is not None:
            covered[slot.unit_key].add(verse)
    out = [f"verse_units {u.unit_key}: slots cover {sorted(covered[u.unit_key])}, "
           f"expected {u.v_start}..{u.v_end}"
           for u in idx["verse_units"].values()
           if covered[u.unit_key] != set(range(u.v_start, u.v_end + 1))]
    out += [f"chapters {c.chapter_key}: slot verses {sorted(grid[c.chapter_key])} "
            f"do not run 1..{c.max_verse}"
            for c in idx["chapters"].values()
            if sorted(grid[c.chapter_key]) != list(range(1, c.max_verse + 1))]
    return out


def _variant_links(idx: Index) -> list[str]:
    slots, notes = idx["verse_slots"], idx["footnotes"]
    out = []
    for slot in slots.values():
        note = notes.get(slot.variant_footnote_id) if slot.variant_footnote_id else None
        if note is not None and note.variant_slot_key != slot.slot_key:
            out.append(f"verse_slots {slot.slot_key}: footnote {note.fn_id} names "
                       f"{note.variant_slot_key} as its variant slot")
    for note in notes.values():
        slot = slots.get(note.variant_slot_key) if note.variant_slot_key else None
        if slot is not None and slot.variant_footnote_id != note.fn_id:
            out.append(f"footnotes {note.fn_id}: slot {slot.slot_key} ({slot.status}) "
                       f"does not point back")
    return out


def _chapter_aggregates(idx: Index) -> list[str]:
    units = Counter(_chapter_of(u.unit_key) for u in idx["verse_units"].values())
    present, omitted = Counter(), defaultdict(set)
    for slot in idx["verse_slots"].values():
        if slot.status == "omitted_variant":
            omitted[_chapter_of(slot.slot_key)].add(slot.slot_key)
        else:
            present[_chapter_of(slot.slot_key)] += 1
    supers = {t.chapter_key for t in idx["chapter_texts"].values() if t.kind == "superscription"}
    divisions = {t.chapter_key: t.id for t in idx["chapter_texts"].values()
                 if t.kind == "book_division"}
    out = []
    for c in idx["chapters"].values():
        actual = {"unit_count": units[c.chapter_key], "present_slot_count": present[c.chapter_key],
                  "omitted_slots": omitted[c.chapter_key],
                  "has_superscription": c.chapter_key in supers,
                  "book_division_id": divisions.get(c.chapter_key)}
        stored = {"unit_count": c.unit_count, "present_slot_count": c.present_slot_count,
                  "omitted_slots": set(c.omitted_slots), "has_superscription": c.has_superscription,
                  "book_division_id": c.book_division_id}
        out += [f"chapters {c.chapter_key}: {k} is {stored[k]}, records give {actual[k]}"
                for k in actual if actual[k] != stored[k]]
    return out


def _book_aggregates(idx: Index) -> list[str]:
    sums: dict[str, Counter] = defaultdict(Counter)
    for c in idx["chapters"].values():
        sums[c.book_id].update({"chapter_count": 1, "unit_count": c.unit_count,
                                "present_slot_count": c.present_slot_count,
                                "slot_rows": c.slot_rows, "omitted_count": len(c.omitted_slots)})
    return [f"books {b.book_id}: {k} is {getattr(b, k)}, chapters give {sums[b.book_id][k]}"
            for b in idx["books"].values()
            for k in ("chapter_count", "unit_count", "present_slot_count", "slot_rows",
                      "omitted_count")
            if getattr(b, k) != sums[b.book_id][k]]


def _container(idx: Index, container_id: str) -> Any:
    kind = ids.parse(container_id).kind
    return idx[CONTAINER_TYPES[kind]].get(container_id) if kind in CONTAINER_TYPES else None


def _span_slices(idx: Index) -> list[str]:
    out = []
    for span in idx["name_spans"].values():
        box = _container(idx, span.container_id)
        if box is None:
            out.append(f"name_spans {span.span_id}: container {span.container_id} not found")
        elif box.text_pdf[span.start:span.end] != span.surface:
            out.append(f"name_spans {span.span_id}: surface {span.surface!r} but the container "
                       f"has {box.text_pdf[span.start:span.end]!r}")
    return out


def _errata_slices(idx: Index) -> list[str]:
    out = []
    for e in idx["errata_applied"].values():
        box = _container(idx, e.container_id)
        if box is None:
            out.append(f"errata_applied {e.errata_id}: container {e.container_id} not found")
            continue
        at = slice(e.offset, e.offset + 1)
        if (box.text_pdf[at], box.text[at]) != (e.pdf_char, e.corrected_char):
            out.append(f"errata_applied {e.errata_id}: {e.container_id} has "
                       f"{box.text_pdf[at]!r}/{box.text[at]!r} at {e.offset}")
        listed = getattr(box, "errata_ids", None)
        if listed is not None and e.errata_id not in listed:
            out.append(f"errata_applied {e.errata_id}: not listed by {e.container_id}")
    for type_name in ("verse_units", "footnotes"):
        pk = record_type(type_name).pk
        out += [f"{type_name} {getattr(r, pk)}: lists {eid} which belongs to "
                f"{idx['errata_applied'][eid].container_id}"
                for r in idx[type_name].values() for eid in r.errata_ids
                if eid in idx["errata_applied"]
                and idx["errata_applied"][eid].container_id != getattr(r, pk)]
    return out


def _offsets(idx: Index) -> list[str]:
    units = idx["verse_units"]

    def length(key: str) -> int | None:
        return len(units[key].text) if key in units else None

    out = [f"headings {h.heading_id}: anchor_offset {h.anchor_offset} beyond {h.anchor_unit_key}"
           for h in idx["headings"].values()
           if length(h.anchor_unit_key) is not None and h.anchor_offset >= length(h.anchor_unit_key)]
    out += [f"footnotes {f.fn_id}: anchor {f.anchor.start}-{f.anchor.end} beyond {f.unit_key}"
            for f in idx["footnotes"].values()
            if f.anchor is not None and length(f.unit_key) is not None
            and f.anchor.end > length(f.unit_key)]
    out += [f"speakers {s.sk_id}: offset {s.offset} beyond {s.unit_key}"
            for s in idx["speakers"].values()
            if length(s.unit_key) is not None and s.offset >= length(s.unit_key)]
    return out


def _aliases(idx: Index) -> list[str]:
    slots = idx["verse_slots"]
    out = [f"ref_aliases {a.external_ref}: {a.external_ref} is a PDF slot; resolve it directly"
           for a in idx["ref_aliases"].values() if a.external_ref in slots]
    out += [f"ref_aliases {a.external_ref}: target {a.target} is an omitted slot"
            for a in idx["ref_aliases"].values()
            if a.target in slots and slots[a.target].status == "omitted_variant"]
    return out


# ------------------------------------------------------------------ struct agreement


def _passage_links(idx: Index) -> list[str]:
    pericopes, passages = idx["pericopes"], idx["passages"]
    out = []
    for pc in pericopes.values():
        expected = [(pc.pericope_id, i, len(pc.passage_ids)) for i in range(len(pc.passage_ids))]
        for ps_id, want in zip(pc.passage_ids, expected):
            ps = passages.get(ps_id)
            got = None if ps is None else (ps.pericope_id, ps.seg_idx, ps.seg_count)
            if ps is not None and got != want:
                out.append(f"pericopes {pc.pericope_id}: passage {ps_id} has "
                           f"(pericope_id, seg_idx, seg_count) {got}, expected {want}")
    for ps in passages.values():
        pc = pericopes.get(ps.pericope_id)
        if pc is not None and ps.passage_id not in pc.passage_ids:
            out.append(f"passages {ps.passage_id}: not listed by {ps.pericope_id}")
        if pc is not None and ps.title != pc.title:
            out.append(f"passages {ps.passage_id}: title {ps.title!r} differs from "
                       f"{pc.pericope_id} title {pc.title!r}")
    return out


def _pericope_chain(idx: Index) -> list[str]:
    pericopes = idx["pericopes"]
    out = []
    for pc in pericopes.values():
        nxt = pericopes.get(pc.next_id) if pc.next_id else None
        if nxt is not None and nxt.prev_id != pc.pericope_id:
            out.append(f"pericopes {pc.pericope_id}: next_id {nxt.pericope_id} has "
                       f"prev_id {nxt.prev_id}")
        prv = pericopes.get(pc.prev_id) if pc.prev_id else None
        if prv is not None and prv.next_id != pc.pericope_id:
            out.append(f"pericopes {pc.pericope_id}: prev_id {prv.pericope_id} has "
                       f"next_id {prv.next_id}")
    return out


# ------------------------------------------------------------------ events agreement


def _anchor_passages(idx: Index) -> list[str]:
    """An event anchor spells its passage's key and slot range."""
    passages, out = idx["passages"], []
    for event in idx["events"].values():
        for a in event.anchors:
            ps = passages.get(a.passage_id)
            spelled = (a.start_key, a.end_key, a.start_slot, a.end_slot)
            if ps is not None and spelled != (ps.start_key, ps.end_key, ps.start_slot,
                                              ps.end_slot):
                out.append(f"events {event.event_id}: anchor {spelled} is not passage "
                           f"{ps.passage_id}")
    return out


RULES: Mapping[str, tuple[tuple[ForeignKey, ...], tuple[Callable[[Index], list[str]], ...]]] = {
    "text": (TEXT_FKS, (_slot_tiling, _variant_links, _chapter_aggregates, _book_aggregates,
                        _span_slices, _errata_slices, _offsets, _aliases)),
    "struct": (STRUCT_FKS, (_passage_links, _pericope_chain)),
    "kg0": (KG0_FKS, ()),
    "events": (EVENTS_FKS, (_anchor_passages,)),
}


def check_refint(snapshot: Snapshot, layer: str) -> GateResult:
    """Gate ``layer``; ``snapshot`` must also hold the layers it refers to."""
    foreign_keys, checks = RULES[layer]
    idx = {t.name: snapshot.index(t.name) for t in RECORD_TYPES}
    violations: list[str] = []
    for key in foreign_keys:
        violations += _dangling(idx, key)
    for check in checks:
        violations += check(idx)
    return violations_result(NAME, violations)
