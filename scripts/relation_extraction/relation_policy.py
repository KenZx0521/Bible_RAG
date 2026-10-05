"""Which relation row wins: the source policy of Step 6.05 (relation_postprocess).

When two rows disagree (the two directions of one parent/child pair, the two
orientations of an undirected pair) or support the same key, 6.05 keeps the
best-ranked source (plan §4: curated > prior > LLM > anchored rule). The
sources 6.05 never emits (rule, inverse, cooccurrence) have no rank, and
ranking one is a bug, so rank() raises instead of guessing.

Between rows of one rank the choice is explicit, never the first row read
(preference): the smallest (source_pericope_id, verse, head_id), then relation,
tail_id and the row's JSON, so the result is a function of the row set alone.

Rows are plain dicts (relations.jsonl lines). A row that predates the
`source` field gets its source from its phase (models.derive_source).
No database: like the rest of 6.05, this reads rows only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from .anchored_rules import parent_child as _parent_child
from .models import derive_source
from .schema_loader import RelationSchema

SOURCE_RANK = {"curated": 0, "prior": 1, "llm": 2, "anchored_rule": 3}   # lower wins
KIN_DIRECTION_CONFLICT = "kin_direction_conflict"   # the conflict reason of a dropped direction
BRIEF_KEYS = ("head_id", "relation", "tail_id", "source", "source_pericope_id", "verse")


def source_of(row: Mapping) -> str | None:
    """The row's source, else the one its phase implies (None when neither says)."""
    return row.get("source") or derive_source(row.get("extraction_phase"), row.get("notes") or "",
                                              row.get("backfilled"))


def rank(row: Mapping) -> int:
    """SOURCE_RANK of the row's source; ValueError for a source with no rank."""
    source = source_of(row)
    if source not in SOURCE_RANK:
        raise ValueError(f"cannot rank source {source!r} of {row.get('head_id')} {row.get('relation')} "
                         f"{row.get('tail_id')}; ranked sources are {list(SOURCE_RANK)}")
    return SOURCE_RANK[source]


def preference(row: Mapping) -> tuple:
    """The sort key of the rows 6.05 prefers, the smallest first.

    rank, then the smallest (source_pericope_id, verse, head_id); relation,
    tail_id and the row's JSON make the order total, so no two distinct rows
    tie (A FATHER_OF B and A SON_OF B share a head and read opposite ways).
    """
    return (rank(row), row.get("source_pericope_id") or "", row.get("verse") or 0,
            row["head_id"], row["relation"], row["tail_id"], _json(row))


def parent_child(row: Mapping) -> tuple[str, str] | None:
    """(parent, child) of a FATHER_OF / MOTHER_OF / SON_OF / DAUGHTER_OF row, else None."""
    return _parent_child(row["head_id"], row["relation"], row["tail_id"])


def resolve_kinship_direction(rows: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """One direction per parent/child pair: (the rows kept, in input order; the conflicts, sorted).

    Each row of the four parent relations names a (parent, child) pair; the
    preferred row of an unordered pair sets its direction. Every row of the
    other direction is a conflict, {BRIEF_KEYS…, reason, kept: the winner's
    BRIEF_KEYS}; every row of the winning direction stays, whatever its rank.
    """
    best: dict[frozenset, dict] = {}
    for row in rows:
        pair = parent_child(row)
        if pair is not None:
            current = best.get(frozenset(pair))
            if current is None or preference(row) < preference(current):
                best[frozenset(pair)] = row
    kept, conflicts = [], []
    for row in rows:
        pair = parent_child(row)
        winner = None if pair is None else best[frozenset(pair)]
        if winner is None or parent_child(winner) == pair:
            kept.append(row)
        else:
            conflicts.append({**_brief(row), "reason": KIN_DIRECTION_CONFLICT, "kept": _brief(winner)})
    return kept, sorted(conflicts, key=_json)


def dedup_undirected(rows: Sequence[dict], schema: RelationSchema) -> tuple[list[dict], list[dict]]:
    """One row per pair of an undirected relation: (kept, dropped), both in input order.

    The preferred row of each (relation, {head, tail}) stays in its own
    orientation; the others go, a row of the other orientation and a second
    row of the same key alike. Every row of a directed relation stays.
    """
    undirected = {entry.name for entry in schema.iter_entries() if entry.direction == "undirected"}
    best: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        if row["relation"] in undirected:
            group = (row["relation"], frozenset((row["head_id"], row["tail_id"])))
            if group not in best or preference(row) < preference(rows[best[group]]):
                best[group] = i
    winners = set(best.values())
    kept = [row for i, row in enumerate(rows) if row["relation"] not in undirected or i in winners]
    dropped = [row for i, row in enumerate(rows) if row["relation"] in undirected and i not in winners]
    return kept, dropped


def _brief(row: Mapping) -> dict:
    return {**{key: row.get(key) for key in BRIEF_KEYS}, "source": source_of(row)}


def _json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
