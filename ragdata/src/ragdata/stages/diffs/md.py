"""Diff of the text layer against ``bible_md/`` — the corpus the services load today.

bible_md is the output of ``scripts/convert_bible_pdf.py`` plus 39 hand-edited
lines (audit G01–G03). Every difference to the text layer gets one cause:

- whitespace: md keeps the PDF line breaks the layer removed (rule N1), or a
  space after a footnote caller;
- errata: md prints the misglyph the layer corrects (S4);
- converter losses, by the mechanism that cut the md text (G01): a footnote at
  a page bottom (the rest of the verse is on the next page), a mid-verse
  heading, a line starting at x ≥ 85 (taken for a heading), a （細拉） line,
  glyphs past the page edge (clipped), a speaker label glued to the verse
  before, a footnote with a range caller (``10-11:``), notes glued on one line,
  and Psalm superscriptions and book divisions dropped altogether;
- hand edits (G02): 有古卷 readings merged into the verse or inserted as verses
  of their own (ghost verses), and their variant footnotes deleted;
- other: anything else. It must stay 0 (G-DIFF).
Units are compared on ``text`` (serving text); offsets are into it.
"""

from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ragcommon import ids
from ragdata.stages.errors import StageError
from ragdata.stages.s01_extract import OVERFLOW_PT

CONVERTER_HEADING_X = 85.0  # convert_bible_pdf.py:205-225 makes a line starting there a heading
SELAH = "（細拉）"
WHITESPACE, ERRATA, OTHER = "whitespace", "errata", "other"
PAGEBREAK, HEADING, INDENT = ("converter_footnote_pagebreak", "converter_midverse_heading",
                              "converter_indented_line")
SELAH_ONLY, SELAH_MID, CLIP = "converter_selah", "converter_selah_midverse", \
    "converter_offpage_clip"
SPEAKER, SUPERSCRIPTION, DIVISION = ("converter_speaker_label", "converter_superscription_lost",
                                     "converter_division_lost")
FN_CLIP, FN_RANGE, FN_GLUED = ("converter_footnote_offpage_clip",
                               "converter_footnote_range_caller", "converter_footnotes_glued")
GHOST, MERGED, FN_REMOVED = ("hand_edit_ghost_verse", "hand_edit_variant_merged",
                             "hand_edit_footnote_removed")
LOSS = (PAGEBREAK, HEADING, INDENT, SELAH_MID, CLIP)  # verse text the md lost (G01: 268 units)
GROUPS = {WHITESPACE: "空白", ERRATA: "errata", OTHER: "其他",
          **{c: "人工修改" for c in (GHOST, MERGED, FN_REMOVED)},
          **{c: "轉換器遺失" for c in (PAGEBREAK, HEADING, INDENT, SELAH_ONLY, SELAH_MID, CLIP,
                                    SPEAKER, SUPERSCRIPTION, DIVISION, FN_CLIP, FN_RANGE,
                                    FN_GLUED)}}
TSV_COLUMNS = ("container", "kind", "op", "offset", "layer_text", "md_text", "class")
_CHAPTER = re.compile(r"^## 第 (\d+) 章\s*$")
_VERSE = re.compile(r"^\*\*([0-9]+(?:[-–－][0-9]+)?)\*\*\s?(.*)$")
_CALLER = re.compile(r"(\d+):(\d+(?:[-–－]\d+)?):")
_WS = re.compile(r"\s+")


class DiffError(StageError):
    """A reference corpus the diff needs is missing or unreadable."""


@dataclass(frozen=True)
class CharInfo:
    """Where one character of a container was typeset (from the S1 glyph)."""

    page: int
    past_edge: bool
    x0: float


@dataclass(frozen=True)
class DiffRow:
    container: str
    kind: str
    op: str
    offset: int | None
    layer: str
    md: str
    cls: str


@dataclass(frozen=True)
class MdDiff:
    rows: tuple[DiffRow, ...]
    summary: Mapping[str, Any]


def char_info(glyphs: Mapping[str, Sequence[Any]],
              page_edges: Mapping[int, float]) -> tuple[CharInfo, ...]:
    """CharInfo of a container's glyphs (S1 ``Glyph``s); ``page_edges`` are right page edges."""
    return tuple(CharInfo(g.page, g.x1 > page_edges[g.page] + OVERFLOW_PT, g.x0) for g in glyphs)


# ------------------------------------------------------------------ the md files


@dataclass
class MdChapter:
    verses: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


def _label(raw: str) -> str:
    return raw.replace("–", "-").replace("－", "-")


def parse_md(text: str) -> dict[int, MdChapter]:
    """Chapters of one md file: verses by label, footnote lines, and the other lines."""
    chapters: dict[int, MdChapter] = {}
    chapter, verse, in_notes = None, None, False
    for line in text.split("\n"):
        found = _CHAPTER.match(line)
        if found:
            chapter, verse, in_notes = chapters.setdefault(int(found.group(1)), MdChapter()), \
                None, False
            continue
        if chapter is None or not line.strip() or line.startswith("**註腳"):
            continue
        if line.strip() == "---" or in_notes:
            in_notes = True
            if line.startswith("- "):
                chapter.notes.append(line[2:])
            continue
        found = _VERSE.match(line)
        if found:
            verse = _label(found.group(1))
            chapter.verses[verse] = found.group(2)
        elif verse is not None and not line.startswith("#"):
            chapter.verses[verse] += "\n" + line
        else:
            verse = None
            chapter.other.append(line)
    return chapters


def read_md(md_dir: Path, books: Iterable[Mapping[str, Any]]) -> dict[str, dict[int, MdChapter]]:
    out = {}
    for book in books:
        path = Path(md_dir) / f"{book['file_name']}.md"
        try:
            out[book["book_id"]] = parse_md(path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise DiffError(f"{path}: unreadable: {exc}") from None
    return out


# ------------------------------------------------------------------ what the classifier knows

Rows = Mapping[str, Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class _Ctx:
    chars: Mapping[str, Sequence[CharInfo]]
    errata: Mapping[str, Mapping[int, tuple[str, str]]]  # container -> offset -> (pdf, fixed)
    mid_headings: Mapping[str, frozenset[int]]
    speakers: Mapping[str, tuple[tuple[int, str], ...]]
    next_unit: Mapping[str, str]
    variant_removed: frozenset[str]  # units whose variant footnote the md dropped or cut


def _context(rows: Rows, chars: Mapping[str, Sequence[CharInfo]],
             variant_removed: frozenset[str]) -> _Ctx:
    errata: dict[str, dict[int, tuple[str, str]]] = defaultdict(dict)
    for e in rows["errata_applied"]:
        errata[e["container_id"]][e["offset"]] = (e["pdf_char"], e["corrected_char"])
    mids: dict[str, set[int]] = defaultdict(set)
    for h in rows["headings"]:
        if h["pos"] == "mid":
            mids[h["anchor_unit_key"]].add(h["anchor_offset"])
    speakers: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for s in rows["speakers"]:
        speakers[s["unit_key"]].append((s["offset"], s["text"]))
    order = [u["unit_key"] for u in sorted(rows["verse_units"], key=lambda u: u["ord"])]
    return _Ctx(chars, errata, {k: frozenset(v) for k, v in mids.items()},
                {k: tuple(v) for k, v in speakers.items()}, dict(zip(order, order[1:])),
                variant_removed)


def _errata_only(container: str, layer: str, md: str, start: int, ctx: _Ctx) -> bool:
    fixes = ctx.errata.get(container, {})
    return len(layer) == len(md) and all(
        a == b or fixes.get(start + k) == (b, a) for k, (a, b) in enumerate(zip(layer, md)))


def _slides(text: str, i1: int, i2: int) -> list[tuple[int, int]]:
    """Equivalent positions of a deletion inside a run of repeated characters."""
    out, a, b = [(i1, i2)], i1, i2
    while a > 0 and text[a - 1] == text[b - 1]:
        a, b = a - 1, b - 1
        out.append((a, b))
    a, b = i1, i2
    while b < len(text) and text[a] == text[b]:
        a, b = a + 1, b + 1
        out.append((a, b))
    return out


def _clipped(key: str, text: str, i1: int, i2: int, ctx: _Ctx) -> bool:
    info = ctx.chars[key]
    return any(all(info[i].past_edge for i in range(a, b)) for a, b in _slides(text, i1, i2))


def _truncation(unit: Mapping[str, Any], i1: int, ctx: _Ctx) -> str | None:
    """Why the md verse stops at ``i1`` (the rest of the verse is missing)."""
    key, text, info = unit["unit_key"], unit["text"], ctx.chars[unit["unit_key"]]
    if i1 in {m["start"] for m in unit["markers"] if m["type"] == "selah"}:
        return SELAH_ONLY if text[i1:] == SELAH else SELAH_MID
    if i1 in ctx.mid_headings.get(key, ()):
        return HEADING
    if i1 in {b["offset"] for b in unit["line_breaks"]} and info[i1].x0 >= CONVERTER_HEADING_X:
        return INDENT
    if 0 < i1 < len(info) and info[i1].page != info[i1 - 1].page:
        return PAGEBREAK
    return None


def _speaker_label(key: str, i1: int, end: int, inserted: str, ctx: _Ctx) -> bool:
    here = any(off == i1 and t == inserted for off, t in ctx.speakers.get(key, ()))
    nxt = ctx.speakers.get(ctx.next_unit.get(key, ""), ())
    return here or (i1 == end and any(off == 0 and t == inserted for off, t in nxt))


def _verse_cause(unit: Mapping[str, Any], op: str, span: tuple[int, int], md: str,
                 ctx: _Ctx) -> str:
    key, text = unit["unit_key"], unit["text"]
    i1, i2 = span
    if op == "replace" and _errata_only(key, text[i1:i2], md, i1, ctx):
        return ERRATA
    if op == "delete" and _clipped(key, text, i1, i2, ctx):
        return CLIP
    cut = _truncation(unit, i1, ctx) if op == "delete" and i2 == len(text) else None
    if cut is not None:
        return cut
    if op == "insert" and _speaker_label(key, i1, len(text), md, ctx):
        return SPEAKER
    return MERGED if op != "delete" and key in ctx.variant_removed else OTHER


def _strip(md: str) -> tuple[str, list[tuple[int, str]]]:
    flat, spaces, at = [], [], 0
    for piece in re.split(r"(\s+)", md):
        if piece and piece.isspace():
            spaces.append((at, piece))
        else:
            flat.append(piece)
            at += len(piece)
    return "".join(flat), spaces


def _layer_offset(k: int, matcher: difflib.SequenceMatcher) -> int:
    for a, b, size in matcher.get_matching_blocks():
        if b <= k <= b + size:
            return a + k - b
    return k


def _unit_rows(unit: Mapping[str, Any], md: str, ctx: _Ctx) -> list[DiffRow]:
    key, text = unit["unit_key"], unit["text"]
    flat, spaces = _strip(md)
    matcher = difflib.SequenceMatcher(None, text, flat, autojunk=False)
    rows = [DiffRow(key, "unit", "insert", _layer_offset(k, matcher), "", run, WHITESPACE)
            for k, run in spaces]
    rows += [DiffRow(key, "unit", op, i1, text[i1:i2], flat[j1:j2],
                     _verse_cause(unit, op, (i1, i2), flat[j1:j2], ctx))
             for op, i1, i2, j1, j2 in matcher.get_opcodes() if op != "equal"]
    return rows


# ------------------------------------------------------------------ footnotes


def _md_notes(book_id: str, chapters: Mapping[int, MdChapter]
              ) -> tuple[dict[str, list[str]], list[DiffRow]]:
    """md footnote texts by the unit their caller names, and rows for glued or stray lines."""
    notes: dict[str, list[str]] = defaultdict(list)
    rows = []
    for number, chapter in sorted(chapters.items()):
        where = ids.chapter_key(book_id, number)
        for line in chapter.notes:
            calls = list(_CALLER.finditer(line))
            if not calls or calls[0].start() != 0:
                rows.append(DiffRow(where, "md_footnote", "md_only", None, "", line, OTHER))
                continue
            if len(calls) > 1:
                rows.append(DiffRow(where, "md_footnote", "glued", None, "", line, FN_GLUED))
            for call, nxt in zip(calls, [*calls[1:], None]):
                start, _, end = _label(call.group(2)).partition("-")
                unit = ids.unit_key(book_id, int(call.group(1)), int(start),
                                    int(end) if end else None)
                notes[unit].append(line[call.end():nxt.start() if nxt else len(line)])
    return notes, rows


def _status(note: Mapping[str, Any], raw: str, ctx: _Ctx) -> str | None:
    """How one md footnote relates to a layer footnote (None: it is another note)."""
    flat = _WS.sub("", raw)
    if flat == note["text"]:
        return "whitespace" if flat != raw else "equal"
    if _errata_only(note["fn_id"], note["text"], flat, 0, ctx):
        return "errata"
    return "clip" if _clip_only(note["fn_id"], note["text_pdf"], flat, ctx) else None


def _clip_only(key: str, text: str, md: str, ctx: _Ctx) -> bool:
    """md is ``text`` less glyphs typeset past the page edge (a boundary glyph may survive)."""
    ops = [o for o in difflib.SequenceMatcher(None, text, md, autojunk=False).get_opcodes()
           if o[0] != "equal"]
    return bool(ops) and all(op == "delete" and _clipped(key, text, i1, i2, ctx)
                             for op, i1, i2, _, _ in ops)


def _take(pool: list[str], fits) -> str | None:
    raw = next((r for r in pool if fits(r)), None)
    if raw is not None:
        pool.remove(raw)
    return raw


def _match_notes(notes: Sequence[Mapping[str, Any]], md_notes: Mapping[str, list[str]],
                 ctx: _Ctx) -> tuple[dict[str, tuple[str, str]], list[DiffRow]]:
    """Pair each layer footnote with an md footnote of its unit: (status, md raw text).

    Notes that match (equal, whitespace, errata, clipped) pair first; an md note
    that is only a prefix of a layer note (cut short) pairs in a second pass.
    """
    left = {unit: list(texts) for unit, texts in md_notes.items()}
    found: dict[str, tuple[str, str]] = {}
    for note in notes:
        pool = left.get(note["unit_key"], [])
        raw = _take(pool, lambda r, n=note: _status(n, r, ctx) is not None)
        if raw is not None:
            found[note["fn_id"]] = (_status(note, raw, ctx), raw)
    for note in (n for n in notes if n["fn_id"] not in found):
        pool = left.get(note["unit_key"], [])
        raw = _take(pool, lambda r, n=note: n["text"].startswith(_WS.sub("", r)))
        if raw is not None:
            found[note["fn_id"]] = ("truncated", raw)
    stray = [DiffRow(unit, "md_footnote", "md_only", None, "", raw, OTHER)
             for unit, texts in sorted(left.items()) for raw in texts]
    return {n["fn_id"]: found.get(n["fn_id"], ("missing", "")) for n in notes}, stray


def _note_cause(note: Mapping[str, Any], status: str, linked: bool) -> str | None:
    simple = {"equal": None, "whitespace": WHITESPACE, "errata": ERRATA, "clip": FN_CLIP}
    if status in simple:
        return simple[status]
    if note["kind"] == "variant" and linked:
        return FN_REMOVED
    if status == "missing" and "-" in note["unit_key"].rsplit(".", 1)[-1]:
        return FN_RANGE
    return OTHER


def _note_rows(notes: Sequence[Mapping[str, Any]], statuses: Mapping[str, tuple[str, str]],
               merged: set[str], ghosts: set[str]) -> list[DiffRow]:
    out = []
    for note in notes:
        status, raw = statuses[note["fn_id"]]
        linked = note["unit_key"] in merged or note["variant_slot_key"] in ghosts
        cause = _note_cause(note, status, linked)
        if cause is not None:
            out.append(DiffRow(note["fn_id"], "footnote", status, 0, note["text"], raw, cause))
    return out


# ------------------------------------------------------------------ verses and chapter texts


def _verse_rows(rows: Rows, md: Mapping[str, Mapping[int, MdChapter]],
                ctx: _Ctx) -> list[DiffRow]:
    out = []
    for unit in sorted(rows["verse_units"], key=lambda u: u["ord"]):
        chapter = md.get(unit["book_id"], {}).get(unit["chapter"])
        text = chapter.verses.get(unit["label"]) if chapter else None
        if text is None:
            out.append(DiffRow(unit["unit_key"], "unit", "missing", 0, unit["text"], "", OTHER))
        elif text != unit["text"]:
            out += _unit_rows(unit, text, ctx)
    return out


def _md_only_rows(rows: Rows, md: Mapping[str, Mapping[int, MdChapter]],
                  removed: set[str]) -> list[DiffRow]:
    have = {u["unit_key"] for u in rows["verse_units"]}
    slots = {s["slot_key"]: s for s in rows["verse_slots"]}
    out = []
    for book, chapters in md.items():
        for number, chapter in sorted(chapters.items()):
            for label, text in chapter.verses.items():
                key = f"{book}.{number}.{label}"
                if key in have:
                    continue
                slot = slots.get(key, {})
                ghost = slot.get("status") == "omitted_variant" \
                    and slot.get("variant_footnote_id") in removed
                out.append(DiffRow(key, "md_verse", "md_only", None, "", _WS.sub("", text),
                                   GHOST if ghost else OTHER))
    return out


def _flat_chapter(chapter: MdChapter | None) -> str:
    return "" if chapter is None else _WS.sub("", "".join([*chapter.verses.values(),
                                                            *chapter.other]))


def _chapter_text_rows(rows: Rows, md: Mapping[str, Mapping[int, MdChapter]]) -> list[DiffRow]:
    out = []
    for t in rows["chapter_texts"]:
        key = ids.parse(t["chapter_key"])
        chapters = md.get(key.book_id, {})
        superscription = t["kind"] == "superscription"
        hay = _flat_chapter(chapters.get(key.chapter)) if superscription \
            else "".join(_flat_chapter(c) for c in chapters.values())
        if t["text"] not in hay:
            out.append(DiffRow(t["id"], t["kind"], "missing", None, t["text"], "",
                               SUPERSCRIPTION if superscription else DIVISION))
    return out


# ------------------------------------------------------------------ the diff and its summary


def summarize(rows: Sequence[DiffRow], **counts: int) -> dict[str, Any]:
    """Rows, distinct containers and layer characters per class; the G01 loss total."""
    by: dict[str, dict[str, Any]] = {OTHER: {"rows": 0, "containers": set(), "chars": 0}}
    for r in rows:
        entry = by.setdefault(r.cls, {"rows": 0, "containers": set(), "chars": 0})
        entry["rows"] += 1
        entry["containers"].add(r.container)
        entry["chars"] += len(r.layer)
    loss = [r for r in rows if r.cls in LOSS]
    return {**counts, "rows": len(rows),
            "by_class": {c: {**v, "containers": len(v["containers"])}
                         for c, v in sorted(by.items())},
            "groups": dict(sorted(Counter(GROUPS[r.cls] for r in rows).items())),
            "loss": {"units": len({r.container for r in loss}),
                     "chars": sum(len(r.layer) for r in loss)}}


def diff_md(rows: Rows, chars: Mapping[str, Sequence[CharInfo]], md_dir: Path) -> MdDiff:
    """Compare the built text layer with bible_md, book by book."""
    md = read_md(md_dir, rows["books"])
    md_notes: dict[str, list[str]] = {}
    out: list[DiffRow] = []
    for book, chapters in md.items():
        notes, extra = _md_notes(book, chapters)
        md_notes.update(notes)
        out += extra
    ctx = _context(rows, chars, frozenset())
    statuses, stray = _match_notes(rows["footnotes"], md_notes, ctx)
    removed = {fid for fid, (status, _) in statuses.items() if status in ("missing", "truncated")}
    variant_removed = frozenset(n["unit_key"] for n in rows["footnotes"]
                                if n["kind"] == "variant" and n["fn_id"] in removed)
    ctx = _context(rows, chars, variant_removed)
    verses = _verse_rows(rows, md, ctx)
    md_only = _md_only_rows(rows, md, removed)
    merged = {r.container for r in verses if r.cls == MERGED}
    ghosts = {r.container for r in md_only if r.cls == GHOST}
    out = verses + md_only + _note_rows(rows["footnotes"], statuses, merged, ghosts) + stray \
        + out + _chapter_text_rows(rows, md)
    summary = summarize(out, units_compared=len(rows["verse_units"]), md_only_verses=len(md_only),
                        footnotes_compared=len(rows["footnotes"]),
                        chapter_texts_compared=len(rows["chapter_texts"]))
    return MdDiff(tuple(out), summary)


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n") \
        .replace("\r", "\\r")


def encode_tsv(rows: Iterable[DiffRow]) -> bytes:
    lines = ["\t".join(TSV_COLUMNS)]
    lines += ["\t".join(_cell(v) for v in (r.container, r.kind, r.op, r.offset, r.layer, r.md,
                                           r.cls)) for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")
