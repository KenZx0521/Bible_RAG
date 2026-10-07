"""G-COUNT: compare absolute counts with the expectation file (design §8).

Every counter must have an expectation and every expectation a counter, so a
key dropped from either side turns the gate red instead of checking less.
List-valued counts (e.g. the omitted slot keys) compare as sets.
"""

from __future__ import annotations

from collections import Counter as Tally
from typing import Any, Callable, Collection, Mapping

from ragcommon import ids
from ragdata.contract.counts import Expectation
from ragdata.gates.base import GateResult, Snapshot, capped

NAME = "G-COUNT"
Counter = Callable[[Snapshot], Any]


def rows(type_name: str, where: Callable[[Any], bool] = lambda r: True) -> Counter:
    return lambda s: sum(1 for r in s.of(type_name) if where(r))


def distinct(type_name: str, value: Callable[[Any], Any],
             where: Callable[[Any], bool] = lambda r: True) -> Counter:
    return lambda s: len({value(r) for r in s.of(type_name) if where(r)})


def _omitted(slot) -> bool:
    return slot.status == "omitted_variant"


def _selah(s: Snapshot) -> int:
    return sum(1 for u in s.of("verse_units") for m in u.markers if m.type == "selah")


def _superscription_chars(s: Snapshot) -> int:
    return sum(len(t.text_pdf) for t in s.of("chapter_texts") if t.kind == "superscription")


def _omitted_keys(s: Snapshot) -> list[str]:
    return sorted(slot.slot_key for slot in s.of("verse_slots") if _omitted(slot))


def _stacked(s: Snapshot) -> int:
    """Headings beyond the first at one start key (``hd:{key}#2`` and later)."""
    starts = Tally(ids.parse(h.heading_id).parent.raw for h in s.of("headings"))
    return sum(n - 1 for n in starts.values())


def _footnote_refs(s: Snapshot) -> int:
    return sum(len(f.refs) for f in s.of("footnotes"))


def _footnote_kind(kind: str) -> Counter:
    return rows("footnotes", lambda f: f.kind == kind)


TEXT_COUNTERS: Mapping[str, Counter] = {
    "books": rows("books"),
    "chapters": rows("chapters"),
    "verse_units": rows("verse_units"),
    "merged_units": rows("verse_units", lambda u: u.v_end > u.v_start),
    "present_slots": rows("verse_slots", lambda s: not _omitted(s)),
    "omitted_slots": rows("verse_slots", _omitted),
    "omitted_slot_keys": _omitted_keys,
    "slot_rows": rows("verse_slots"),
    "superscriptions": rows("chapter_texts", lambda t: t.kind == "superscription"),
    "superscription_chars": _superscription_chars,
    "book_divisions": rows("chapter_texts", lambda t: t.kind == "book_division"),
    "selah_markers": _selah,
    "speakers": rows("speakers"),
    "headings": rows("headings"),
    "headings_before": rows("headings", lambda h: h.pos == "before"),
    "headings_mid": rows("headings", lambda h: h.pos == "mid"),
    "headings_dash_sub": rows("headings", lambda h: h.text_pdf.startswith("－")),
    "headings_stacked": _stacked,
    "parallel_lines": distinct("parallel_refs", lambda p: p.heading_id),
    "parallel_segments": rows("parallel_refs"),
    "section_ranges": rows("parallel_refs", lambda p: p.kind == "section_range"),
    "footnotes": rows("footnotes"),
    "footnotes_alt_rendering": _footnote_kind("alt_rendering"),
    "footnotes_original": _footnote_kind("original"),
    "footnotes_name_meaning": _footnote_kind("name_meaning"),
    "footnotes_variant": _footnote_kind("variant"),
    "footnote_refs": _footnote_refs,
    "name_spans_body": rows("name_spans", lambda n: n.region == "body"),
    "name_surfaces_body": distinct("name_spans", lambda n: n.surface, lambda n: n.region == "body"),
    "name_spans_footnote": rows("name_spans", lambda n: n.region == "footnote"),
    "merge_groups": distinct("name_spans", lambda n: n.merge_group,
                             lambda n: n.merge_group is not None),
}

STRUCT_COUNTERS: Mapping[str, Counter] = {
    "pericopes": rows("pericopes"),
    "pericopes_cross_chapter": rows("pericopes", lambda p: len(p.chapters) > 1),
    "pericopes_untitled": rows("pericopes", lambda p: p.heading_id is None),
    "passages": rows("passages"),
    "passages_continued": rows("passages", lambda p: p.continued),
}

COUNTERS: Mapping[str, Mapping[str, Counter]] = {"text": TEXT_COUNTERS, "struct": STRUCT_COUNTERS}


def _same(observed: Any, expected: Any) -> bool:
    if isinstance(expected, tuple):
        return isinstance(observed, list) and sorted(observed) == sorted(expected)
    return not isinstance(observed, list) and observed == expected


def _show(value: Any) -> Any:
    return list(value) if isinstance(value, tuple) else value


def check_counts(snapshot: Snapshot, layer: str, expectations: Mapping[str, Expectation],
                 keys: Collection[str] | None = None) -> GateResult:
    """Compare every count of ``layer`` (or only ``keys``, for a stage that writes part of it)."""
    counters = COUNTERS[layer]
    if keys is not None:
        counters = {k: counters[k] for k in keys if k in counters}
        expectations = {k: expectations[k] for k in keys if k in expectations}
    wanted = set(counters) if keys is None else set(keys)
    details = [f"{key}: no expectation" for key in sorted(wanted - set(expectations))]
    uncounted = (set(expectations) | wanted) - set(counters)
    details += [f"{key}: no counter" for key in sorted(uncounted)]
    observed = {key: counters[key](snapshot) for key in sorted(counters)}
    expected = {key: _show(e.value) for key, e in sorted(expectations.items())}
    for key in sorted(set(counters) & set(expectations)):
        exp = expectations[key]
        if not _same(observed[key], exp.value):
            details.append(f"{key}: observed {observed[key]}, expected {expected[key]} "
                           f"({', '.join(exp.g)})")
    return GateResult(NAME, True, not details, observed, expected, capped(details))
