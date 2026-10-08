"""G-STRUCT's legacy-map condition: every ``legacy_ids`` row means what its relation says.

Checked from the struct layer alone; the old ``output/`` is not needed. A row's
``start_slot``–``end_slot`` is the verse range the old record covered, and it may
map only to the records an old row of its kind maps to in that chapter (its
pool): passages for an old pericope; the chunks of a chunked passage, or the
passage itself when it is not chunked, for an old chunk; units (``vs:``) for an
old verse record. Ranges compare as sets of integer verses, as S5 builds the map
(``stages.s05_struct.legacy``; a verse cut by a mid-verse heading counts in both
halves):

- ``exact``: the one record covers the same verses;
- ``contained``: the one record covers more, and no record of the pool covers
  exactly these verses;
- ``split``: no record holds the range on its own, the records listed are every
  record of the pool that overlaps it, and together they cover it;
- ``retired``: every slot of the range is one the PDF omits.

How many rows of each kind there are is G-COUNT's (``legacy_*`` in the counts).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Iterator, Mapping, Sequence

from ragcommon import ids

Verses = frozenset[tuple[str, int, int]]            # (book_id, chapter, verse)
Pool = Mapping[tuple[str, int], Mapping[str, Verses]]   # (book_id, chapter) -> {id: verses}


def key_verses(start_key: str, end_key: str) -> Verses:
    """The integer verses from ``start_key`` to ``end_key`` (one chapter; b halves count)."""
    s, e = ids.parse(start_key), ids.parse(end_key)
    return frozenset((s.book_id, s.chapter, v) for v in range(s.verse, e.verse + 1))


def _chapter(verses: Verses) -> tuple[str, int]:
    book_id, chapter, _ = min(verses)
    return book_id, chapter


def _by_chapter(targets: Iterable[tuple[str, Verses]]) -> Pool:
    pool: dict[tuple[str, int], dict[str, Verses]] = defaultdict(dict)
    for new_id, verses in targets:
        pool[_chapter(verses)][new_id] = verses
    return pool


def pools(units: Iterable[Any], passages: Mapping[str, Any],
          chunks: Mapping[str, Sequence[Any]]) -> Mapping[str, Pool]:
    """What an old row of each kind may map to, by chapter."""
    own = [(pid, key_verses(p.start_key, p.end_key)) for pid, p in passages.items()]
    retrieval = [(c.chunk_id, key_verses(c.start_key, c.end_key)) for pid, verses in own
                 for c in chunks.get(pid, ())]
    retrieval += [(pid, verses) for pid, verses in own if not chunks.get(pid)]
    verse_records = [(ids.verse_record_id(u.unit_key),
                      frozenset((u.book_id, u.chapter, v) for v in range(u.v_start, u.v_end + 1)))
                     for u in units]
    return {"pericope": _by_chapter(own), "chunk": _by_chapter(retrieval),
            "verse": _by_chapter(verse_records)}


def _fits(relation: str, want: Verses, new_ids: Sequence[str],
          targets: Mapping[str, Verses]) -> bool:
    got = [targets[i] for i in new_ids]
    if relation == "exact":
        return got == [want]
    if relation == "contained":
        return len(got) == 1 and got[0] > want and want not in targets.values()
    overlapping = {i for i, verses in targets.items() if verses & want}
    return (relation == "split" and set(new_ids) == overlapping
            and not any(verses >= want for verses in got) and want <= frozenset().union(*got))


def _row(row: Any, pool: Pool, omitted: frozenset[str]) -> Iterator[str]:
    want = key_verses(row.start_slot, row.end_slot)
    if row.relation == "retired":
        held = sorted(s for s in (ids.slot_key(*v) for v in want) if s not in omitted)
        if held:
            yield f"{row.legacy_id}: retired, but the PDF holds {', '.join(held)}"
        return
    targets = pool.get(_chapter(want), {})
    foreign = [i for i in row.new_ids if i not in targets]
    if foreign:
        yield (f"{row.legacy_id}: maps to {', '.join(foreign)}, outside what an old "
               f"{row.kind} maps to in its chapter")
    elif not _fits(row.relation, want, row.new_ids, targets):
        yield (f"{row.legacy_id}: {row.relation} does not hold between "
               f"{row.start_slot}~{row.end_slot} and {', '.join(row.new_ids)}")


def violations(rows: Iterable[Any], pools_: Mapping[str, Pool],
               omitted: frozenset[str]) -> Iterator[str]:
    """Every legacy row whose relation does not hold against its pool."""
    for row in rows:
        yield from _row(row, pools_[row.kind], omitted)
