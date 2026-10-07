"""G-CONSERVE: glyph conservation from the PDF rows to the parse output (design §8).

Per book and category the style-classified source count must equal what the
parse produced, counted from the records it wrote (residual 0); the categories
must add up to every non-space glyph S1 extracted; nothing may stay
unclassified; and the corpus totals of the categories named in the
expectations (body 1,059,384, navy 27,568, footnote 13,463, division 32 for the
66 PDFs) must be met exactly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Mapping

from ragdata.gates.base import GateResult, capped

NAME = "G-CONSERVE"
CATEGORIES = ("page_header", "book_title", "division", "verse_number", "body", "chapter_number",
              "navy", "footnote", "colophon", "unclassified")


@dataclass(frozen=True)
class Tally:
    """One book's glyph accounting (built by ``stages.s02_parse.conserve``)."""

    glyphs: int                    # non-space glyphs in the S1 lines
    source: Mapping[str, int]      # by row style
    output: Mapping[str, int]      # by the records (and dropped categories) the parse produced


def _total(tallies: Mapping[str, Tally], side: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for tally in tallies.values():
        counts.update(getattr(tally, side))
    return dict(sorted(counts.items()))


def _book_details(book: str, tally: Tally) -> list[str]:
    out = [f"{book} {cat}: source {tally.source[cat]}, output {tally.output[cat]}"
           for cat in CATEGORIES if tally.source[cat] != tally.output[cat]]
    classified = sum(tally.source.values())
    if classified != tally.glyphs:
        out.append(f"{book}: {tally.glyphs} glyphs extracted but {classified} classified")
    if tally.source["unclassified"]:
        out.append(f"{book}: {tally.source['unclassified']} unclassified glyphs")
    return out


def check_conserve(tallies: Mapping[str, Tally], expected_totals: Mapping[str, int]) -> GateResult:
    details = [d for book, tally in tallies.items() for d in _book_details(book, tally)]
    source = _total(tallies, "source")
    details += [f"total {cat}: {source.get(cat, 0)}, expected {n}"
                for cat, n in sorted(expected_totals.items()) if source.get(cat, 0) != n]
    if not tallies:
        details.append("no book was tallied")
    observed = {"glyphs": sum(t.glyphs for t in tallies.values()), "source": source,
                "output": _total(tallies, "output")}
    expected = {"residual": 0, "unclassified": 0, "totals": dict(sorted(expected_totals.items()))}
    return GateResult(NAME, True, not details, observed, expected, capped(details))
