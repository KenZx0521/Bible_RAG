"""Which relation row wins: the source policy of Step 6.05 (relation_postprocess).

When two rows disagree (the two directions of one parent/child pair, the two
orientations of an undirected pair) or support the same key, 6.05 keeps the
best-ranked source (plan §4: curated > prior > LLM > anchored rule). The
sources 6.05 never emits (rule, inverse, cooccurrence) have no rank, and
ranking one is a bug, so rank() raises instead of guessing.

Rows are plain dicts (relations.jsonl lines). A row that predates the
`source` field gets its source from its phase (models.derive_source).
No database: like the rest of 6.05, this reads rows only.
"""

from __future__ import annotations

from collections.abc import Mapping

from .anchored_rules import parent_child as _parent_child
from .models import derive_source

SOURCE_RANK = {"curated": 0, "prior": 1, "llm": 2, "anchored_rule": 3}   # lower wins


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


def parent_child(row: Mapping) -> tuple[str, str] | None:
    """(parent, child) of a FATHER_OF / MOTHER_OF / SON_OF / DAUGHTER_OF row, else None."""
    return _parent_child(row["head_id"], row["relation"], row["tail_id"])
