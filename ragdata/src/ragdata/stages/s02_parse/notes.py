"""S2b: footnote records of one book (design §2.9, D-04(a)).

- ``kind`` follows the marker the note prints: 古卷 ``variant``, 或譯 ``alt_rendering``,
  原文 ``original``, 的意思 ``name_meaning``, anything else ``other``. In the 66 PDFs
  no note prints two of them; one that does is a ParseError, not a guess.
- ``anchor``: the PDF prints no caller inside the verse, so a note is anchored to its
  verse only — unless it starts with a lemma (得：或譯成) that occurs exactly once in the
  verse text; a lemma written 甲……乙 spans from 甲 to the 乙 after it.
- ``refs``: every 「X章Y節」 the note cites, in the book named right before it or, with
  none, the note's own book, resolved to PDF slots by ``ragcommon.refs``; a citation
  that names no verse is a ParseError.
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
_NUMERAL = "[〇零一二三四五六七八九十百]+"
CHAPTER_VERSE = re.compile(f"第?{_NUMERAL}章第?{_NUMERAL}節")


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


def _citation(text: str, match: re.Match[str], book_id: str,
              found: refs.FindResult) -> tuple[refs.VerseRef, ...]:
    if any(r.end == match.end() for r in found.rejected):
        raise refs.RefParseError("names no verse", match.group())
    named = [m for m in found.matches if m.end == match.end() and m.start <= match.start()]
    if named:
        return named[0].refs
    return refs.parse_refs(match.group(), strict=True, default_book=book_id).refs


def note_refs(text: str, book_id: str, where: str) -> list[dict[str, str]]:
    """Slot ranges of the 「X章Y節」 citations in ``text``, in order."""
    found = refs.find_refs(text)
    out: list[dict[str, str]] = []
    for match in CHAPTER_VERSE.finditer(text):
        try:
            cited = _citation(text, match, book_id, found)
        except refs.RefParseError as exc:
            raise ParseError(f"{where}: citation {match.group()!r} in {text!r} does not "
                             f"resolve: {exc.reason}") from None
        out.extend(slot_range(r) for r in cited)
    return out


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
