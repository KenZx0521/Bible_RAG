#!/usr/bin/env python3
"""
Validate JSONL output files from Bible processing.

The curated CROSS_REFERENCES rows go through the Step 0 cross-reference gate
(validate_cross_references): every problem there is an error and exits 1.

Usage:
    python scripts/validate_output.py [OUTPUT_DIR]
"""

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Set, Tuple

# Add parent directory to path for imports
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bible_chunking.curated_xrefs import (
    XrefDefinitionError,
    format_verses,
    parse_anchor,
    resolve_definitions,
    verse_map_from_pericopes,
)
from bible_chunking.nt_cross_references import SUPPLEMENTARY_CROSS_REFS

# The lists each curated source writes on its pairs (aggregate_curated), in
# priority order: a pair's scalar `source` is the first source it has.
CURATED_SOURCE_LISTS = {
    "markdown": ("md_ref_texts", "md_anchors"),
    "supplementary": ("supp_anchors", "supp_ref_types", "supp_descriptions"),
}
# optional: a subset of supp_anchors, exactly the anchors of tsk_exempt definitions
TSK_EXEMPT_LIST = "supp_tsk_exempt_anchors"
MAX_LISTED = 10  # lines printed per cross-reference check; the rest are counted
SAMPLES = 3      # examples quoted in a warning


def load_jsonl(filepath: Path) -> List[dict]:
    """Load all records from a JSONL file."""
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as e:
                raise ValueError(f"{filepath.name}:{line_num}: Invalid JSON - {e}")
    return records


# ---------------------------------------------------------------------------
# Cross references (1B): Step 0 writes one curated CROSS_REFERENCES row per
# (start, end) pair; Step 5 MERGEs on the pair and Step 9 adds TSK to it.
# ---------------------------------------------------------------------------

def _pair(row: Mapping) -> str:
    return f"{row.get('start')}→{row.get('end')}"


def _str_list(value) -> List[str]:
    """The str elements of a list value; [] for anything else (checked elsewhere)."""
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _sources(props: Mapping) -> List[str]:
    return _str_list(props.get("curated_sources"))


def _capped(lines: Sequence[str], label: str) -> List[str]:
    """The first MAX_LISTED lines of one check, then a count of the rest."""
    if len(lines) <= MAX_LISTED:
        return list(lines)
    return [*lines[:MAX_LISTED], f"{label}: … and {len(lines) - MAX_LISTED} more"]


def _duplicate_pairs(xrefs: List[dict]) -> List[str]:
    counts = Counter(_pair(row) for row in xrefs)
    return [f"duplicate pair: {pair} ({n} rows)" for pair, n in sorted(counts.items()) if n > 1]


def _endpoint_problems(xrefs: List[dict], pericope_ids: Set[str]) -> List[str]:
    """Endpoints that are not a Pericope, e.g. the old chapter fallback 'isa:9'."""
    return [f"not a Pericope: {side} {row.get(side)} of {_pair(row)}"
            for row in xrefs for side in ("start", "end") if row.get(side) not in pericope_ids]


def _value_problems(xrefs: List[dict]) -> List[str]:
    """None values and non-str list elements (Neo4j stores neither)."""
    lines = []
    for row in xrefs:
        for key, value in row["properties"].items():
            if value is None:
                lines.append(f"{_pair(row)}: {key} is None")
            elif isinstance(value, list) and len(_str_list(value)) != len(value):
                bad = ", ".join(repr(x) for x in value if not isinstance(x, str))
                lines.append(f"{_pair(row)}: {key} holds {bad}")
    return lines


def _flag_problems(props: Mapping) -> List[str]:
    """curated true, tsk false, curated_sources sorted ⊆ CURATED_SOURCE_LISTS and
    source = the first of them (Step 9 relies on all four)."""
    problems = []
    if props.get("curated") is not True:
        problems.append("curated is not true")
    if props.get("tsk") is not False:
        problems.append("tsk is not false")
    sources = props.get("curated_sources")
    present = [s for s in CURATED_SOURCE_LISTS if isinstance(sources, list) and s in sources]
    if not present or sources != sorted(present):
        problems.append(f"curated_sources {sources!r} is not a non-empty sorted subset "
                        f"of {list(CURATED_SOURCE_LISTS)}")
    elif props.get("source") != present[0]:
        problems.append(f"source {props.get('source')!r} is not {present[0]!r}")
    return problems


def _source_list_problems(props: Mapping, source: str, names: Sequence[str]) -> List[str]:
    """A source's lists: non-empty and aligned when it is a source, absent otherwise."""
    if source not in _sources(props):
        return [f"{name} present but {source} is not a source" for name in names if name in props]
    problems, lengths = [], {}
    for name in names:
        value = props.get(name)
        if name not in props:
            problems.append(f"{name} missing ({source} is a source)")
        elif isinstance(value, list) and value:
            lengths[name] = len(value)
        elif value is not None:  # None is reported with the values
            problems.append(f"{name} is not a non-empty list: {value!r}")
    if len(set(lengths.values())) > 1:
        problems.append(f"{source} lists misaligned: "
                        + ", ".join(f"{name} {n}" for name, n in lengths.items()))
    return problems


def _exempt_problems(props: Mapping) -> List[str]:
    exempt = props.get(TSK_EXEMPT_LIST)
    if exempt is None:  # absent, or reported with the values
        return []
    if not isinstance(exempt, list) or not exempt:
        return [f"{TSK_EXEMPT_LIST} is not a non-empty list: {exempt!r}"]
    stray = [text for text in exempt if text not in _str_list(props.get("supp_anchors"))]
    return [f"{TSK_EXEMPT_LIST} {stray!r} not among supp_anchors"] if stray else []


def _row_problems(xrefs: List[dict]) -> Tuple[List[str], List[str]]:
    """(curated flag problems, one line per row; list problems, one line each)."""
    flags, lists = [], []
    for row in xrefs:
        props = row["properties"]
        found = _flag_problems(props)
        if found:
            flags.append(f"{_pair(row)}: " + "; ".join(found))
        for source, names in CURATED_SOURCE_LISTS.items():
            lists += [f"{_pair(row)}: {p}" for p in _source_list_problems(props, source, names)]
        lists += [f"{_pair(row)}: {p}" for p in _exempt_problems(props)]
    return flags, lists


def _pericope_verses(verse_map: Mapping[Tuple[str, int, int], str]) -> Dict[str, Set[int]]:
    verses: Dict[str, Set[int]] = {}
    for (_, _, verse), pid in verse_map.items():
        verses.setdefault(pid, set()).add(verse)
    return verses


def _coord_problems(text: str, coord, pid: str, verses_of: Mapping[str, Set[int]]) -> List[str]:
    """One end of a supplementary anchor against its endpoint pericope."""
    if pid not in verses_of:  # reported as not a Pericope
        return []
    book, chapter = pid.split(":")[:2]
    if (coord.book, str(coord.chapter)) != (book, chapter):
        return [f"{text!r}: {coord.book} {coord.chapter} is not the chapter of {pid}"]
    outside = set(coord.verses) - verses_of[pid]
    return [f"{text!r}: verses {format_verses(outside)} are not in {pid}"] if outside else []


def _anchor_problems(xrefs: List[dict], verses_of: Mapping[str, Set[int]]) -> List[str]:
    """Supplementary anchors that do not parse or name verses outside their pericopes."""
    lines = []
    for row in xrefs:
        for text in _str_list(row["properties"].get("supp_anchors")):
            try:
                coords = parse_anchor(text)
            except XrefDefinitionError as err:
                lines.append(f"{_pair(row)}: unparseable anchor {err}")
                continue
            for coord, pid in zip(coords, (row.get("start"), row.get("end"))):
                lines += [f"{_pair(row)}: {p}" for p in _coord_problems(text, coord, pid, verses_of)]
    return lines


def _anchor_keys(xrefs: List[dict], name: str = "supp_anchors") -> Counter:
    """The anchors of one list in the rows, as a multiset of (start, end, anchor)."""
    return Counter((str(row.get("start")), str(row.get("end")), text) for row in xrefs
                   for text in _str_list(row["properties"].get(name)))


def _exempt_coverage(xrefs: List[dict], anchors: Iterable) -> List[Tuple[List[str], str]]:
    """TSK_EXEMPT_LIST must be, as a multiset of (start, end, anchor), exactly the
    anchors of the definitions with tsk_exempt: Step 9's support gate skips every
    listed anchor, so a stray entry would let an unsupported anchor through."""
    expected = Counter((a.start, a.end, a.text) for a in anchors if a.tsk_exempt is not None)
    listed = _anchor_keys(xrefs, TSK_EXEMPT_LIST)
    extra = [f"tsk_exempt anchor whose definition has no tsk_exempt: {s}→{e} {t!r}"
             for s, e, t in sorted((listed - expected).elements())]
    missing = [f"tsk_exempt definition anchor not in {TSK_EXEMPT_LIST}: {s}→{e} {t!r}"
               for s, e, t in sorted((expected - listed).elements())]
    return [(extra, "tsk_exempt anchor whose definition has no tsk_exempt"),
            (missing, f"tsk_exempt definition anchor not in {TSK_EXEMPT_LIST}")]


def _coverage(xrefs: List[dict], definitions: List,
              verse_map: Mapping) -> Tuple[List[Tuple[List[str], str]], int]:
    """([(lines, label)] per coverage check, definitions whose anchors are all present).

    The anchors in the rows must equal what the definitions resolve to: a
    definition with none of its anchors is reported once, the missing anchors
    of a partly present one each, and every anchor left over as extra. The
    exempt anchors are checked the same way (_exempt_coverage)."""
    resolved, unresolved = resolve_definitions(definitions, verse_map)
    remaining = _anchor_keys(xrefs)
    without, missing, covered = [], [], 0
    for i, definition in enumerate(definitions):
        anchors, errors = resolve_definitions([definition], verse_map)
        absent = []
        for key in [(a.start, a.end, a.text) for a in anchors]:
            if remaining[key] > 0:
                remaining[key] -= 1
            else:
                absent.append(key)
        covered += bool(anchors and not absent and not errors)
        if anchors and len(absent) == len(anchors):
            without.append(f"definition {i} ({definition.src}>{definition.tgt}) "
                           f"has no anchor in the rows")
        elif absent:
            missing += [f"anchor missing from the rows: {s}→{e} {t!r}" for s, e, t in absent]
    extra = [f"anchor from no definition: {s}→{e} {t!r}"
             for s, e, t in sorted((+remaining).elements())]
    return [(unresolved, "definition does not resolve"), (without, "definition without anchors"),
            (missing, "anchor missing from the rows"), (extra, "anchor from no definition"),
            *_exempt_coverage(xrefs, resolved)], covered


def _marker_warnings(xrefs: List[dict]) -> Tuple[List[str], Dict[str, int]]:
    """Overlapping pairs (X4) and markdown anchors marking what the parser left
    unread (XREF-5): both owned by 2D, neither an error. Markdown verses are
    not checked."""
    overlap = sorted(_pair(row) for row in xrefs
                     if set(CURATED_SOURCE_LISTS) <= set(_sources(row["properties"])))
    md_anchors = sorted(text for row in xrefs
                        for text in _str_list(row["properties"].get("md_anchors")))
    unknown_end = [text for text in md_anchors if text.endswith("-?")]
    unread = [text for text in md_anchors if text.endswith(",?")]
    found = [
        (overlap, "markdown∩supplementary pairs: {n} (X4: one aggregated row each; "
                  "expected after 2D), e.g. {samples}"),
        (unknown_end, "markdown anchors with unknown target end: {n} (XREF-5, owned by 2D), "
                      "e.g. {samples}"),
        (unread, "markdown anchors with unread ranges after a comma: {n} "
                 "(XREF-5, owned by 2D), e.g. {samples}"),
    ]
    warnings = [template.format(n=len(items), samples=", ".join(items[:SAMPLES]))
                for items, template in found if items]
    return warnings, {"overlap": len(overlap), "md_unknown_end": len(unknown_end),
                      "md_unread_ranges": len(unread)}


def validate_cross_references(rels: Iterable[dict], pericopes: Iterable[dict],
                              definitions: Iterable) -> Tuple[List[str], List[str], dict]:
    """(errors, warnings, stats) of the curated CROSS_REFERENCES rows of a
    Step 0 output against its pericopes and the supplementary definitions
    (bible_chunking.nt_cross_references.SUPPLEMENTARY_CROSS_REFS).

    Errors: duplicate pairs, endpoints that are not a Pericope, curated
    flags, source lists missing or misaligned, None values, supplementary
    anchors that do not parse or leave their pericopes, and definition
    coverage, of the anchors and of the tsk_exempt anchors. Warnings: see
    _marker_warnings."""
    xrefs = [row for row in rels if row.get("type") == "CROSS_REFERENCES"]
    pericopes, definitions = list(pericopes), list(definitions)
    verse_map = verse_map_from_pericopes(pericopes)
    duplicates = _duplicate_pairs(xrefs)
    endpoints = _endpoint_problems(xrefs, {p["id"] for p in pericopes})
    flags, lists = _row_problems(xrefs)
    coverage, covered = _coverage(xrefs, definitions, verse_map)
    checks = [(duplicates, "duplicate pair"), (endpoints, "not a Pericope"),
              (flags, "curated flags"), (lists, "source lists"),
              (_value_problems(xrefs), "None or non-string value"),
              (_anchor_problems(xrefs, _pericope_verses(verse_map)), "supplementary anchor"),
              *coverage]
    errors = [line for lines, label in checks for line in _capped(lines, label)]
    warnings, marker_stats = _marker_warnings(xrefs)
    stats = {
        "rows": len(xrefs),
        **{source: sum(source in _sources(row["properties"]) for row in xrefs)
           for source in CURATED_SOURCE_LISTS},
        "duplicates": len(duplicates), "non_pericope_endpoints": len(endpoints),
        "anchors": sum(_anchor_keys(xrefs).values()),
        "definitions": len(definitions), "definitions_covered": covered,
        **marker_stats,
    }
    return errors, warnings, stats


def _print_xref_stats(stats: Mapping) -> None:
    print(f"  CROSS_REFERENCES: {stats['rows']} rows (markdown {stats['markdown']}, "
          f"supplementary {stats['supplementary']})")
    print(f"  Duplicate pairs: {stats['duplicates']}")
    print(f"  Non-Pericope endpoints: {stats['non_pericope_endpoints']}")
    print(f"  Supplementary anchors: {stats['anchors']}")
    print(f"  Definitions covered: {stats['definitions_covered']}/{stats['definitions']}")
    print(f"  markdown∩supplementary pairs: {stats['overlap']}")
    print(f"  Markdown anchors with unknown target end: {stats['md_unknown_end']}, "
          f"with unread ranges after a comma: {stats['md_unread_ranges']} "
          f"(markdown verses are not checked: XREF-5, 2D)")


def validate_output(output_dir: Path) -> bool:
    """Validate all output files."""
    print(f"Validating output directory: {output_dir}")
    print("=" * 60)

    # Required files
    required_files = [
        "books.jsonl",
        "chapters.jsonl",
        "pericopes.jsonl",
        "chunks.jsonl",
        "embedding_queue.jsonl",
        "neo4j_nodes.jsonl",
        "neo4j_relationships.jsonl",
    ]

    errors = []
    warnings = []

    # Check file existence
    for filename in required_files:
        filepath = output_dir / filename
        if not filepath.exists():
            errors.append(f"Missing required file: {filename}")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Load all files
    print("\nLoading files...")
    data: Dict[str, List[dict]] = {}
    for filename in required_files:
        filepath = output_dir / filename
        try:
            data[filename] = load_jsonl(filepath)
            print(f"  {filename}: {len(data[filename])} records")
        except ValueError as e:
            errors.append(str(e))

    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        return False

    # Validate books
    print("\nValidating books...")
    books = data["books.jsonl"]
    if len(books) != 66:
        warnings.append(f"Expected 66 books, found {len(books)}")

    book_ids = {b["id"] for b in books}
    print(f"  Found {len(book_ids)} unique book IDs")

    # Validate chapters
    print("\nValidating chapters...")
    chapters = data["chapters.jsonl"]
    chapter_ids = {c["id"] for c in chapters}
    print(f"  Found {len(chapters)} chapters")

    # Check parent references
    orphan_chapters = 0
    for c in chapters:
        if c.get("parent_id") not in book_ids:
            orphan_chapters += 1
    if orphan_chapters > 0:
        warnings.append(f"{orphan_chapters} chapters have invalid parent_id")

    # Validate pericopes
    print("\nValidating pericopes...")
    pericopes = data["pericopes.jsonl"]
    pericope_ids = {p["id"] for p in pericopes}
    print(f"  Found {len(pericopes)} pericopes")

    # Check parent references
    orphan_pericopes = 0
    for p in pericopes:
        if p.get("parent_id") not in chapter_ids:
            orphan_pericopes += 1
    if orphan_pericopes > 0:
        warnings.append(f"{orphan_pericopes} pericopes have invalid parent_id")

    # Count pericopes requiring chunking
    requires_chunking = sum(1 for p in pericopes if p.get("metadata", {}).get("requires_chunking", False))
    print(f"  Pericopes requiring chunking: {requires_chunking}")

    # Validate chunks
    print("\nValidating chunks...")
    chunks = data["chunks.jsonl"]
    chunk_ids = {c["id"] for c in chunks}
    print(f"  Found {len(chunks)} chunks")

    # Check parent references
    orphan_chunks = 0
    for c in chunks:
        if c.get("parent_id") not in pericope_ids:
            orphan_chunks += 1
    if orphan_chunks > 0:
        warnings.append(f"{orphan_chunks} chunks have invalid parent_id")

    # Validate embedding queue
    print("\nValidating embedding queue...")
    embedding_queue = data["embedding_queue.jsonl"]
    print(f"  Found {len(embedding_queue)} embedding items")

    # Count by type
    pericope_embeds = sum(1 for e in embedding_queue if e.get("type") == "pericope")
    chunk_embeds = sum(1 for e in embedding_queue if e.get("type") == "chunk")
    print(f"    Pericope embeddings: {pericope_embeds}")
    print(f"    Chunk embeddings: {chunk_embeds}")

    # Expected: non-chunked pericopes + all chunks
    expected_embeds = (len(pericopes) - requires_chunking) + len(chunks)
    if len(embedding_queue) != expected_embeds:
        warnings.append(
            f"Embedding queue count mismatch: expected {expected_embeds}, got {len(embedding_queue)}"
        )

    # Validate Neo4j nodes
    print("\nValidating Neo4j nodes...")
    neo4j_nodes = data["neo4j_nodes.jsonl"]
    print(f"  Found {len(neo4j_nodes)} nodes")

    # Count by label
    label_counts: Dict[str, int] = {}
    for node in neo4j_nodes:
        for label in node.get("labels", []):
            label_counts[label] = label_counts.get(label, 0) + 1
    for label, count in sorted(label_counts.items()):
        print(f"    {label}: {count}")

    # Validate Neo4j relationships
    print("\nValidating Neo4j relationships...")
    neo4j_rels = data["neo4j_relationships.jsonl"]
    print(f"  Found {len(neo4j_rels)} relationships")

    # Count by type
    rel_counts: Dict[str, int] = {}
    for rel in neo4j_rels:
        rel_type = rel.get("type", "UNKNOWN")
        rel_counts[rel_type] = rel_counts.get(rel_type, 0) + 1
    for rel_type, count in sorted(rel_counts.items()):
        print(f"    {rel_type}: {count}")

    # Cross references (1B gate): every problem is an error
    print("\nValidating cross references...")
    xref_errors, xref_warnings, xref_stats = validate_cross_references(
        neo4j_rels, pericopes, SUPPLEMENTARY_CROSS_REFS)
    _print_xref_stats(xref_stats)
    errors.extend(xref_errors)
    warnings.extend(xref_warnings)

    # Token statistics
    print("\nToken statistics...")
    token_counts = [p.get("metadata", {}).get("token_count", 0) for p in pericopes]
    if token_counts:
        total_tokens = sum(token_counts)
        avg_tokens = total_tokens / len(token_counts)
        max_tokens = max(token_counts)
        min_tokens = min(t for t in token_counts if t > 0) if any(t > 0 for t in token_counts) else 0
        print(f"  Total tokens: {total_tokens:,}")
        print(f"  Average tokens/pericope: {avg_tokens:.1f}")
        print(f"  Min tokens: {min_tokens}")
        print(f"  Max tokens: {max_tokens}")

    # Print results
    print("\n" + "=" * 60)
    if errors:
        print("VALIDATION FAILED")
        for e in errors:
            print(f"  [ERROR] {e}")
        return False

    if warnings:
        print("VALIDATION PASSED WITH WARNINGS")
        for w in warnings:
            print(f"  [WARNING] {w}")
    else:
        print("VALIDATION PASSED")

    return True


def main():
    output_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "output")

    if not output_dir.exists():
        print(f"Error: Directory not found: {output_dir}")
        sys.exit(1)

    success = validate_output(output_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
