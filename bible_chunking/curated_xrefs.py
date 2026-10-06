"""Curated cross references in verse coordinates (W1 1B, XREF-1 / X4).

A supplementary definition names both ends as 'book chapter:verses', e.g.
'rev 18:2-8' > 'jer 51:6-9,45'. Each end resolves verse by verse through a
(book, chapter, verse) → pericope_id map (the keys of
import_tsk_crossrefs.build_verse_map). A definition whose verses straddle a
pericope boundary yields one anchor per touched (source, target) pericope
pair, each carrying only that pair's verses, at most MAX_FANOUT per
definition: 'rev 18:2-8>jer 51:6-9' (jer:51:0) and 'rev 18:2-8>jer 51:45'
(jer:51:5). Anything that does not resolve cleanly is an error, a pair whose
two ends are one pericope included; nothing falls back to a chapter or skips
silently.

aggregate_curated folds those anchors and the markdown refs into one
CROSS_REFERENCES row per (start, end) pair (Step 5 MERGEs on the pair, so a
second row used to overwrite the first): curated true, tsk false (Step 9 sets
it), curated_sources, and per-source lists aligned element by element. A
markdown ref is pericope-level, so its anchor marks unknown verses with '?',
including what CrossRefParser left unread: 'num 21:?>deu 2:26-?' for
申2‧26－3‧11, 'jer 52:?>2ki 25:18-21,?' for 王下25‧18－21，27－30.

edge_fingerprint hashes the CROSS_REFERENCES table after Step 9, read live with
EDGE_FINGERPRINT_CYPHER or projected offline, so the two can be compared.

Pure: no I/O. Shared by Step 0 (process_bible), validate_output, Step 9 and
xref_probe.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Iterable, Mapping, NamedTuple

from .markdown_parser import CrossRefParser

MAX_FANOUT = 3  # anchors one definition may produce (X4)

VerseMap = Mapping[tuple[str, int, int], str]

_BOOK = re.compile(r"[0-9a-z]+")
_NUMBER = re.compile(r"[0-9]+")


class XrefDefinitionError(ValueError):
    """A coordinate or definition that does not resolve; .errors lists every problem."""

    def __init__(self, *errors: str):
        super().__init__("\n".join(errors))
        self.errors = errors


class Coord(NamedTuple):
    book: str
    chapter: int
    verses: tuple[int, ...]


class Anchor(NamedTuple):
    """One (source pericope, target pericope) pair of a definition."""

    start: str
    end: str
    text: str           # e.g. 'rev 18:2-8>jer 51:45': this pair's verse subsets
    ref_type: str
    description: str
    tsk_exempt: str | None


def _parse_verses(spec: str, text: str) -> tuple[int, ...]:
    """'n', 'a-b' or a comma list of those, ascending ranges, no verse twice."""
    if not spec:
        raise XrefDefinitionError(f"{text!r}: no verses")
    if any(ch.isspace() for ch in spec):
        raise XrefDefinitionError(f"{text!r}: a space inside the verses")
    if ":" in spec:
        raise XrefDefinitionError(f"{text!r}: crosses a chapter (one chapter per end)")
    verses: list[int] = []
    for part in spec.split(","):
        lo, dash, hi = part.partition("-")
        if not _NUMBER.fullmatch(lo) or (dash and not _NUMBER.fullmatch(hi)):
            raise XrefDefinitionError(f"{text!r}: {part!r} is not n or a-b")
        first, last = int(lo), int(hi or lo)
        if last < first:
            raise XrefDefinitionError(f"{text!r}: descending range {part!r}")
        verses.extend(range(first, last + 1))
    if len(set(verses)) != len(verses):
        raise XrefDefinitionError(f"{text!r}: a verse is listed twice")
    return tuple(verses)


def parse_coord(text: str) -> Coord:
    """'jer 51:6-9,45' → Coord('jer', 51, (6, 7, 8, 9, 45))."""
    book, space, rest = text.partition(" ")
    chapter, colon, spec = rest.partition(":")
    if not (space and colon and _BOOK.fullmatch(book) and _NUMBER.fullmatch(chapter)):
        raise XrefDefinitionError(f"{text!r}: expected 'book chapter:verses'")
    return Coord(book, int(chapter), _parse_verses(spec, text))


def format_verses(verses: Iterable[int]) -> str:
    """Sorted runs: [6, 7, 8, 9] → '6-9', [14, 27] → '14,27'."""
    ordered = sorted(set(verses))
    if not ordered:
        raise ValueError("no verses to format")
    runs, start, prev = [], ordered[0], ordered[0]
    for verse in ordered[1:]:
        if verse != prev + 1:
            runs.append((start, prev))
            start = verse
        prev = verse
    runs.append((start, prev))
    return ",".join(str(a) if a == b else f"{a}-{b}" for a, b in runs)


def format_coord(coord: Coord) -> str:
    return f"{coord.book} {coord.chapter}:{format_verses(coord.verses)}"


def format_anchor(src: Coord, tgt: Coord) -> str:
    """→ 'rev 18:2-8>jer 51:45'."""
    return f"{format_coord(src)}>{format_coord(tgt)}"


def parse_anchor(text: str) -> tuple[Coord, Coord]:
    src, arrow, tgt = text.partition(">")
    if not arrow or ">" in tgt:
        raise XrefDefinitionError(f"{text!r}: expected 'source>target'")
    return parse_coord(src), parse_coord(tgt)


def resolve_span(coord: Coord, verse_map: VerseMap) -> dict[str, tuple[int, ...]]:
    """{pericope_id: verses}, both in first-seen order; every missing verse is reported."""
    parts: dict[str, list[int]] = {}
    missing = []
    for verse in coord.verses:
        pid = verse_map.get((coord.book, coord.chapter, verse))
        if pid is None:
            missing.append(verse)
        else:
            parts.setdefault(pid, []).append(verse)
    if missing:
        raise XrefDefinitionError(
            f"{format_coord(coord)!r}: verses {format_verses(missing)} are in no pericope")
    return {pid: tuple(verses) for pid, verses in parts.items()}


def _resolve_ends(src_text: str, tgt_text: str,
                  verse_map: VerseMap) -> list[tuple[Coord, dict[str, tuple[int, ...]]]]:
    """Both ends parsed and resolved; the errors of both ends together."""
    ends, errors = [], []
    for text in (src_text, tgt_text):
        try:
            coord = parse_coord(text)
            ends.append((coord, resolve_span(coord, verse_map)))
        except XrefDefinitionError as err:
            errors.extend(err.errors)
    if errors:
        raise XrefDefinitionError(*errors)
    return ends


def build_anchors(src_text: str, tgt_text: str, verse_map: VerseMap, *, ref_type: str,
                  description: str, tsk_exempt: str | None = None) -> list[Anchor]:
    """One Anchor per touched (source pericope, target pericope) pair, source-major.
    A pair whose two ends are one pericope fails the whole definition: TSK drops
    self-loops (aggregate_tsk), so no curated edge may be one."""
    (src, src_parts), (tgt, tgt_parts) = _resolve_ends(src_text, tgt_text, verse_map)
    fanout = len(src_parts) * len(tgt_parts)
    if fanout > MAX_FANOUT:
        raise XrefDefinitionError(
            f"{src_text!r}>{tgt_text!r}: {fanout} pericope pairs (max {MAX_FANOUT}): "
            f"{', '.join(src_parts)} × {', '.join(tgt_parts)}")
    loops = [pid for pid in src_parts if pid in tgt_parts]
    if loops:
        raise XrefDefinitionError(f"{src_text!r}>{tgt_text!r}: both ends in {', '.join(loops)}")
    return [
        Anchor(start, end,
               format_anchor(src._replace(verses=src_verses), tgt._replace(verses=tgt_verses)),
               ref_type, description, tsk_exempt)
        for start, src_verses in src_parts.items()
        for end, tgt_verses in tgt_parts.items()
    ]


def resolve_definitions(defs: Iterable, verse_map: VerseMap) -> tuple[list[Anchor], list[str]]:
    """Anchors of every definition (.src, .tgt, .ref_type, .description, .tsk_exempt)
    in definition order, and the complete error list, each prefixed 'definition <i>'."""
    anchors: list[Anchor] = []
    errors: list[str] = []
    for i, d in enumerate(defs):
        try:
            anchors.extend(build_anchors(d.src, d.tgt, verse_map, ref_type=d.ref_type,
                                         description=d.description, tsk_exempt=d.tsk_exempt))
        except XrefDefinitionError as err:
            errors.extend(f"definition {i}: {message}" for message in err.errors)
    return anchors, errors


def verse_map_from_pericopes(records: Iterable[Mapping]) -> dict[tuple[str, int, int], str]:
    """(book, chapter, verse) → pericope_id from output/pericopes.jsonl rows;
    verse numbers like '1-2' are expanded, as in build_verse_map."""
    verse_map: dict[tuple[str, int, int], str] = {}
    for record in records:
        meta = record["metadata"]
        for verse in record["verses"]:
            lo, _, hi = verse["num"].partition("-")
            for n in range(int(lo), int(hi or lo) + 1):
                verse_map[(meta["book_id"], meta["chapter_num"], n)] = record["id"]
    return verse_map


# What CrossRefParser's first match leaves unread in a markdown ref (XREF-5,
# 2D rewrites the parser): '‧15' of 代下11‧5－12‧15 makes the '12' it kept as
# verse_end the end chapter; '，27－30' of 王下25‧18－21，27－30 are more verses.
_END_CHAPTER_TAIL = re.compile(r"[‧·.]\d+")
_MORE_VERSES_TAIL = re.compile(r"[，,]")


def _unread_tail(ref_text: str) -> str:
    match = CrossRefParser.SINGLE_REF_PATTERN.search(ref_text)
    return ref_text[match.end():] if match else ""


def _markdown_target_verses(ref) -> str:
    vs, ve, tail = ref.verse_start, ref.verse_end, _unread_tail(ref.reference_text)
    if vs is None:
        return "?"
    end_chapter = bool(_END_CHAPTER_TAIL.fullmatch(tail))
    if end_chapter or (ve is not None and ve < vs):
        verses = f"{vs}-?"
    elif ve is None or ve == vs:
        verses = str(vs)
    else:
        verses = f"{vs}-{ve}"
    if not tail or end_chapter:
        return verses
    if _MORE_VERSES_TAIL.match(tail):
        return f"{verses},?"
    raise XrefDefinitionError(f"{ref.reference_text!r}: no anchor marks the unread {tail!r}")


def markdown_anchor(src_book: str, src_ch: int, ref) -> str:
    """'gen 5:?>1ch 1:1-4' for a parsed markdown ref (.book_id, .chapter,
    .verse_start, .verse_end, .reference_text, as CrossRefParser builds it).

    The source verse is never known. The target marks with '?' what the parser
    left unread: the end verse of a cross-chapter ref, whose end chapter it kept
    as verse_end ('2ch 15:16-?' for 代下15‧16－16‧6, never '2ch 15:16'; also any
    descending range), and the ranges after a comma ('2ki 25:18-21,?'). Any
    other unread text raises XrefDefinitionError."""
    return f"{src_book} {src_ch}:?>{ref.book_id} {ref.chapter}:{_markdown_target_verses(ref)}"


# (source, the list a pair of that source carries) in priority order: a pair's
# scalar `source` is the first one present, so markdown wins over supplementary.
_SOURCE_MARKERS = (("markdown", "md_anchors"), ("supplementary", "supp_anchors"))


def _source_lists(md_rows: Iterable[Mapping], supp_anchors: Iterable[Anchor]) -> dict:
    """(start, end) → {list name: values}, in input order."""
    pairs: dict[tuple[str, str], dict[str, list]] = {}

    def add(start: str, end: str, values: dict) -> None:
        lists = pairs.setdefault((start, end), {})
        for key, value in values.items():
            lists.setdefault(key, []).append(value)

    for row in md_rows:
        add(row["start"], row["end"], {"md_ref_texts": row["ref_text"],
                                       "md_anchors": row["md_anchor"]})
    for anchor in supp_anchors:
        add(anchor.start, anchor.end, {"supp_anchors": anchor.text,
                                       "supp_ref_types": anchor.ref_type,
                                       "supp_descriptions": anchor.description})
        if anchor.tsk_exempt is not None:  # never a null list element (Neo4j refuses it)
            add(anchor.start, anchor.end, {"supp_tsk_exempt_anchors": anchor.text})
    return pairs


def _check_strings(pair: tuple[str, str], lists: dict[str, list]) -> None:
    for key, values in lists.items():
        if not all(isinstance(value, str) for value in values):
            raise XrefDefinitionError(
                f"{pair[0]}->{pair[1]}: {key} holds a non-string {values!r}")


def aggregate_curated(md_rows: Iterable[Mapping],
                      supp_anchors: Iterable[Anchor]) -> list[dict]:
    """One curated CROSS_REFERENCES relationship per (start, end), sorted by pair.

    md_rows are {start, end, ref_text, md_anchor}. Every value is a bool, a str
    or a non-empty list of str (XrefDefinitionError otherwise); a source's lists
    are present only when the pair has that source."""
    relationships = []
    for pair, lists in sorted(_source_lists(md_rows, supp_anchors).items()):
        _check_strings(pair, lists)
        sources = [source for source, marker in _SOURCE_MARKERS if marker in lists]
        relationships.append({
            "start": pair[0], "end": pair[1], "type": "CROSS_REFERENCES",
            "properties": {"source": sources[0], "curated": True, "tsk": False,
                           "curated_sources": sorted(sources), **lists},
        })
    return relationships


# One row per CROSS_REFERENCES edge, in the columns edge_fingerprint hashes.
EDGE_FINGERPRINT_CYPHER = """
MATCH (a:Pericope)-[r:CROSS_REFERENCES]->(b:Pericope)
RETURN a.id AS a, b.id AS b, r.votes AS votes, r.verse_pairs AS verse_pairs,
       r.curated AS curated, r.tsk AS tsk
"""
_FINGERPRINT_FIELDS = ("a", "b", "votes", "verse_pairs", "curated", "tsk")


def edge_fingerprint(rows: Iterable[Mapping]) -> str:
    """sha256 of one json.dumps([a, b, votes, verse_pairs, curated, tsk]) line per
    edge, sorted by (a, b) and joined by newlines (sim_w1_1b.py's projection).
    Input order does not matter. Every row carries all six keys: the query
    returns null for a property the edge lacks (a curated edge has no votes
    until Step 9 attaches TSK to it)."""
    lines = sorted((row["a"], row["b"], json.dumps([row[k] for k in _FINGERPRINT_FIELDS]))
                   for row in rows)
    return hashlib.sha256("\n".join(line for _, _, line in lines).encode()).hexdigest()
