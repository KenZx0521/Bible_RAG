"""S2b: footnote records of one book (design §2.9, D-04(a)).

- ``kind`` follows the marker the note prints: 古卷 ``variant``, 或譯 ``alt_rendering``,
  原文 ``original``, 的意思 ``name_meaning``, anything else ``other``. In the 66 PDFs
  no note prints two of them; one that does is a ParseError, not a guess.
- ``anchor``: the PDF prints no caller inside the verse, so a note is anchored to its
  verse only — unless it starts with a lemma (得：或譯成) that occurs exactly once in the
  verse text; a lemma written 甲……乙 spans from 甲 to the 乙 after it.
- ``refs``: every 「X章Y節」 the note cites, with the verse ranges and lists that continue
  it (九至十節, 九節，十節), resolved to PDF slots by ``ragcommon.refs``. The book is the
  one ``find_refs`` reads around the citation (one reference holding several citations
  counts once); a citation with no book name falls back to the note's own book only at
  the start of the note or after 見/在/看/，/；/、, and only when no book-named reference
  precedes it. Anything else — a book name ``find_refs`` does not know, a named book
  without that verse, a citation that names no verse — is a ParseError, never a guess.
- ``variant_slot_key``: the omitted slot that points at this 有古卷 note (D-04(a)).
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from ragcommon import ids, refs
from ragdata.stages.errors import ParseError
from ragdata.stages.s02_parse.parallels import slot_range
from ragdata.stages.s02_parse.stream import Footnote

PDF = "pdf_deterministic"
KIND_MARKERS = (("variant", "古卷"), ("alt_rendering", "或譯"), ("original", "原文"),
                ("name_meaning", "的意思"))
LEMMA = re.compile(r"([^：]+)：(?:或譯|原文|有古卷|有些古卷|又作|七十士譯本|或作)")
ELLIPSIS = re.compile(r"\.{3,}|…+")
_NUMERAL = "(?:[〇零一二三四五六七八九十百]+|[0-9０-９]+)"
_JOIN = "[至到~～\\-－–—，、；,]"
# 「X章Y節」 and the ranges and lists that continue it: 九至十節, 九節，十節, 九節；十章一節.
CITATION = re.compile(f"第?{_NUMERAL}章第?{_NUMERAL}"
                      f"(?:節?{_JOIN}第?{_NUMERAL}(?:章第?{_NUMERAL})?)*節")
# What may stand right before a citation that names no book, for it to be the note's own.
OWN_BOOK_LEADS = frozenset("見在看，；、")


def note_kind(text: str, where: str) -> str:
    kinds = [kind for kind, marker in KIND_MARKERS if marker in text]
    if len(kinds) > 1:
        raise ParseError(f"{where}: note {text!r} prints the markers of kinds {kinds}")
    return kinds[0] if kinds else "other"


def _span(start: int, end: int) -> dict[str, int]:
    return {"start": start, "end": end}


def lemma_anchor(text: str, verse: str) -> dict[str, int] | None:
    """Where the note's lemma stands in ``verse``, when it stands there exactly once."""
    found = LEMMA.match(text)
    if found is None:
        return None
    parts = ELLIPSIS.split(found.group(1))
    head = re.split(r"[，,]", parts[0])[0]
    if not head or verse.count(head) != 1:
        return None
    start = verse.find(head)
    if len(parts) == 1:
        return _span(start, start + len(head))
    tail = parts[-1]
    end = verse.find(tail, start + len(head)) if tail else -1
    return None if end < 0 else _span(start, end + len(tail))


def _overlaps(start: int, end: int, match: re.Match[str]) -> bool:
    return start < match.end() and match.start() < end


def _own_book(match: re.Match[str], text: str, book_id: str,
              found: refs.FindResult) -> refs.RefMatch:
    """A citation with no book name before it: the note's own book, when unambiguous."""
    at = match.start()
    if at and text[at - 1] not in OWN_BOOK_LEADS:
        raise refs.RefParseError(f"follows {text[at - 1]!r}, neither a known book nor a lead",
                                 match.group())
    if any(m.start < at for m in (*found.matches, *found.rejected)):
        raise refs.RefParseError("names no book but follows one that does", match.group())
    parsed = refs.parse_refs(match.group(), strict=True, default_book=book_id)
    return refs.RefMatch(at, match.end(), match.group(), parsed.refs)


def _citation(match: re.Match[str], text: str, book_id: str,
              found: refs.FindResult) -> refs.RefMatch:
    """The whole reference a citation belongs to."""
    if any(_overlaps(r.start, r.end, match) for r in found.rejected):
        raise refs.RefParseError("names no verse", match.group())
    named = [m for m in found.matches if m.start <= match.start() and match.end() <= m.end]
    return named[0] if named else _own_book(match, text, book_id, found)


def _resolved(match: re.Match[str], text: str, book_id: str, found: refs.FindResult,
              where: str) -> refs.RefMatch:
    try:
        return _citation(match, text, book_id, found)
    except refs.RefParseError as exc:
        raise ParseError(f"{where}: citation {match.group()!r} in {text!r} does not "
                         f"resolve: {exc.reason}") from None


def note_refs(text: str, book_id: str, where: str) -> list[dict[str, str]]:
    """Slot ranges of the 「X章Y節」 citations in ``text``, in order."""
    found = refs.find_refs(text)
    cited = dict.fromkeys(_resolved(m, text, book_id, found, where)
                          for m in CITATION.finditer(text))
    return [slot_range(r) for hit in cited for r in hit.refs]


def footnote_rows(book_id: str, notes: Sequence[tuple[str, Footnote]],
                  units: Sequence[Mapping[str, Any]],
                  slots: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Records of the numbered notes of one book (``units.number_footnotes``)."""
    texts = {u["unit_key"]: u["text_pdf"] for u in units}
    variants = {s["variant_footnote_id"]: s["slot_key"] for s in slots
                if s["variant_footnote_id"] is not None}
    rows = []
    for fid, note in notes:
        parsed = ids.parse(fid)
        unit = parsed.parent.raw
        rows.append({
            "fn_id": fid, "unit_key": unit, "n": parsed.seq, "kind": note_kind(note.text, fid),
            "anchor": lemma_anchor(note.text, texts[unit]), "text_pdf": note.text,
            "text": note.text, "variant_slot_key": variants.get(fid),
            "refs": note_refs(note.text, book_id, fid), "errata_ids": [], "provenance_class": PDF,
        })
    return tuple(rows)
