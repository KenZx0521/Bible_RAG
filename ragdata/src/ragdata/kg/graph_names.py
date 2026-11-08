"""The graph's name rows: Name nodes, MENTIONS from verses and passages, TITLE_MENTIONS.

A mention is one body token of the text layer (a merge group is one). A verse a heading cuts
belongs to two passages: the token's start offset picks the one whose ``unit_refs`` range holds it.
A span kg0 names no name for (a ``not_entity`` fix such as 舍客勒) is no mention.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ragdata.kg.graph_schema import edge, node
from ragdata.kg.kin_tokens import body_tokens
from ragdata.stages.errors import StageError

Row = Mapping[str, Any]
HEADING = "heading"
IDF_DIGITS = 6


@dataclass(frozen=True)
class MentionCounts:
    by_verse: Mapping[tuple[str, str], int]          # (unit_key, name_id) -> mentions
    by_passage: Mapping[tuple[str, str], int]        # (passage_id, name_id) -> mentions


@dataclass(frozen=True)
class TitleMentions:
    pairs: frozenset[tuple[str, str]]                # (pericope_id, name_id)
    unplaced: int                                    # heading names no pericope carries


def name_ids(names: Iterable[Row]) -> dict[str, str]:
    """Every norm key and surface of kg0's names, to its name id."""
    table: dict[str, str] = {}
    for name in names:
        for key in (name["norm_key"], *name["surfaces"]):
            table[key] = name["name_id"]
    return table


def _unit_ranges(passages: Iterable[Row]) -> dict[str, list[tuple[int, int | None, str]]]:
    ranges: dict[str, list[tuple[int, int | None, str]]] = defaultdict(list)
    for p in passages:
        for ref in p["unit_refs"]:
            ranges[ref["unit_key"]].append((ref["from"], ref["to"], p["passage_id"]))
    return ranges


def _owner(ranges: Sequence[tuple[int, int | None, str]], unit: str, start: int) -> str:
    for first, last, passage in ranges:
        if first <= start and (last is None or start < last):
            return passage
    raise StageError(f"no passage holds {unit}@{start}")


def mention_counts(name_spans: Iterable[Row], passages: Iterable[Row], names: Mapping[str, str]) -> MentionCounts:
    ranges = _unit_ranges(passages)
    by_verse: Counter[tuple[str, str]] = Counter()
    by_passage: Counter[tuple[str, str]] = Counter()
    for unit, tokens in body_tokens(name_spans).items():
        for token in tokens:
            name = names.get(token.norm_key)
            if name is not None:
                by_verse[(unit, name)] += 1
                by_passage[(_owner(ranges.get(unit, ()), unit, token.start), name)] += 1
    return MentionCounts(dict(by_verse), dict(by_passage))


def mention_edges(counts: MentionCounts) -> list[dict]:
    return [*(edge("MENTIONS", "Verse", u, "Name", n, count=c) for (u, n), c in counts.by_verse.items()),
            *(edge("MENTIONS", "Passage", p, "Name", n, count=c) for (p, n), c in counts.by_passage.items())]


def _heading_pericopes(pericopes: Iterable[Row]) -> dict[str, list[str]]:
    """A heading's pericopes: its own, and those under it when it is their section's."""
    table: dict[str, list[str]] = defaultdict(list)
    for p in pericopes:
        for heading in (p["heading_id"], p["section_heading_id"]):
            if heading is not None:
                table[heading].append(p["pericope_id"])
    return table


def title_mentions(extra_spans: Iterable[Row], name_spans: Iterable[Row], pericopes: Iterable[Row],
                   names: Mapping[str, str]) -> TitleMentions:
    """The names in headings: kg0's lexicon spans and any span the text layer underlines there."""
    headings = _heading_pericopes(pericopes)
    pairs: set[tuple[str, str]] = set()
    unplaced = 0
    for row in (*extra_spans, *name_spans):
        name = names.get(row["surface"])
        if row["region"] != HEADING or name is None:
            continue
        carriers = headings.get(row["container_id"], ())
        unplaced += not carriers
        pairs |= {(pericope, name) for pericope in carriers}
    return TitleMentions(frozenset(pairs), unplaced)


def title_edges(found: TitleMentions) -> list[dict]:
    return [edge("TITLE_MENTIONS", "Pericope", p, "Name", n) for p, n in found.pairs]


def name_nodes(names: Iterable[Row], counts: MentionCounts, passages: int) -> list[dict]:
    """df: the passages that mention a name; idf: log(passages / df) (df 0 counts as 1)."""
    df: Counter[str] = Counter(name for _, name in counts.by_passage)
    return [node("Name", n["name_id"], label=n["norm_key"], surfaces=list(n["surfaces"]),
                 df=df[n["name_id"]],
                 idf=round(math.log(passages / max(df[n["name_id"]], 1)), IDF_DIGITS))
            for n in names]
