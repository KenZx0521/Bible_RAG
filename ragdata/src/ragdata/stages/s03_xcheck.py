"""S3: cross-check the text layer against poppler (design §4, §8 G-XCHECK).

S1 and S2 both read the PDFs through MuPDF; poppler's ``pdftotext`` is the one
independent reader (audit G70). Each PDF is read twice, ``-raw`` (content order)
and ``-layout`` (visual order), with the crop box widened so the 852 glyphs
typeset past the page edge are kept. The checks:

- containment: each PDF line of a verse unit (``text_pdf`` cut at
  ``line_breaks``) occurs in the whitespace-free poppler text of its book, in
  canonical order, at most ``MAX_PIECE_GAP`` characters after the line before
  it (both modes);
- gaps (``-raw``): what poppler prints between two lines of a unit must be what
  the layer says stands there — a mid-verse heading (with its parallel line) or
  speaker label at that line break — or a page break after which the line goes
  on at the top of the page. A glyph the layer lost at the start or the end of
  a line is an unexplained gap;
- characters (both modes): per book, poppler's non-space characters outside the
  running heads and the colophon page equal what the layer accounts for: the
  PDF text of every record, verse labels, footnote callers, chapter numerals
  and the book title. A glyph lost anywhere, at the end of a unit too, is a
  difference;
- verse numbers: in ``-raw`` the printed number stands right before the unit's
  first line, so unit boundaries are where the PDF puts them;
- running heads: each page's head names the book and the first and last verse
  that start on that page; a page where no verse starts names the verse running
  over it (詩篇 p.204). Only a book's last page (its colophon) has no head.

The report is deterministic (no timings) and is stored in the text layer.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import accumulate
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from ragcommon import ids
from ragdata.contract.registry import XCHECK_REPORT, record_type
from ragdata.gates.base import GateResult, capped
from ragdata.stages.errors import StageError
from ragdata.stages.s02_parse.conserve import record_counts

NAME = "G-XCHECK"
REPORT_FILE = XCHECK_REPORT
REPORT_SCHEMA = "ragdata.xcheck_report.v2"
MODES = ("raw", "layout")
CROP = ("-x", "0", "-y", "0", "-W", "2000", "-H", "2000")
MAX_PIECE_GAP = 200  # characters between two lines of one verse; the corpus maximum is 72
TIMEOUT_S = 300
DASHES = ("-", "–", "－")
BOOK_TYPES = ("verse_units", "chapter_texts", "headings", "parallel_refs", "footnotes",
              "speakers")
CHAPTER_ONE_NUMERAL = frozenset({"psa", "oba"})  # the only books that print 1 before chapter 1
_WS = re.compile(r"\s+")
_REF = r"(\S+?)\s*(?:([0-9]+):)?([0-9]+)(?:[-–－]([0-9]+))?"
_HEAD = re.compile(rf"{_REF}\s+[ivxlcdm]+\s+{_REF}")

Runner = Callable[[Path, str], str]
Records = Mapping[str, Sequence[Mapping[str, Any]]]
Gap = tuple[int, int, int]  # (index of the line after the gap, gap start, gap end) in a stream


class XcheckError(StageError):
    """pdftotext failed, or the PDFs are not the ones the layer was built from."""


@dataclass(frozen=True)
class Unit:
    key: str
    chapter: int
    v_start: int
    v_end: int
    label: str
    lines: tuple[str, ...]
    pages: tuple[int, ...]
    inserts: tuple[str, ...]  # inserts[i]: what the PDF prints right before line i (no spaces)

    def offset(self, line: int) -> int:
        return sum(len(text) for text in self.lines[:line])


@dataclass(frozen=True)
class Page:
    number: int
    head: tuple | None  # (name, chapter, verse, end, name, chapter, verse, end) when present
    body: str


@dataclass(frozen=True)
class Stream:
    """The whitespace-free page bodies of one book and where each page starts in them."""

    text: str
    page_starts: tuple[int, ...]


def book_records(records: Records) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    """The records of each book in ``records["books"]`` by type (``BOOK_TYPES``), told
    apart by the book their key names; records of other books are left out."""
    out: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        b["book_id"]: {t: [] for t in BOOK_TYPES} for b in records["books"]}
    for type_name in BOOK_TYPES:
        pk = record_type(type_name).pk
        for row in records.get(type_name, ()):
            book = ids.parse(row[pk]).book_id
            if book in out:
                out[book][type_name].append(row)
    return out


def _inserted(records: Records) -> dict[tuple[str, int], str]:
    """What the PDF prints inside a unit, by (unit, offset): mid-verse headings with their
    parallel-reference line, then speaker labels, whitespace removed."""
    lines = {p["heading_id"]: p["raw"] for p in records.get("parallel_refs", ())}
    out: dict[tuple[str, int], str] = defaultdict(str)
    for h in sorted(records.get("headings", ()), key=lambda h: h["ord"]):
        if h["pos"] == "mid":
            out[(h["anchor_unit_key"], h["anchor_offset"])] += \
                h["text_pdf"] + lines.get(h["heading_id"], "")
    for s in records.get("speakers", ()):
        if s["pos"] == "mid":
            out[(s["unit_key"], s["offset"])] += s["text_pdf"]
    return {key: _WS.sub("", text) for key, text in out.items()}


def _unit(row: Mapping[str, Any], inserted: Mapping[tuple[str, int], str]) -> Unit:
    cuts = [0, *(b["offset"] for b in row["line_breaks"]), len(row["text_pdf"])]
    return Unit(row["unit_key"], row["chapter"], row["v_start"], row["v_end"], row["label"],
                tuple(row["text_pdf"][a:b] for a, b in zip(cuts, cuts[1:])),
                tuple(row["pages"]),
                tuple(inserted.get((row["unit_key"], cut), "") for cut in cuts[:-1]))


def units_of(records: Records) -> dict[str, tuple[Unit, ...]]:
    """Verse units by book, in canonical (``ord``) order."""
    inserted = _inserted(records)
    by_book: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in records["verse_units"]:
        by_book[row["book_id"]].append(row)
    return {book: tuple(_unit(r, inserted) for r in sorted(group, key=lambda r: r["ord"]))
            for book, group in by_book.items()}


def run_pdftotext(pdf: Path, mode: str) -> str:
    argv = ["pdftotext", f"-{mode}", "-enc", "UTF-8", *CROP, str(pdf), "-"]
    try:
        done = subprocess.run(argv, capture_output=True, check=False, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise XcheckError(f"pdftotext {mode} {pdf.name}: {exc}") from None
    if done.returncode != 0:
        raise XcheckError(f"pdftotext {mode} {pdf.name} exited {done.returncode}: "
                          f"{done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout.decode("utf-8")


def split_pages(text: str) -> tuple[Page, ...]:
    """Pages split on form feeds; a first line that parses as a running head is set apart."""
    chunks = text.split("\f")
    if chunks and chunks[-1] == "":
        chunks = chunks[:-1]
    pages = []
    for number, chunk in enumerate(chunks, start=1):
        first, _, rest = chunk.partition("\n")
        found = _HEAD.fullmatch(first.strip())
        head = found.groups() if found else None
        pages.append(Page(number, head, rest if found else chunk))
    return tuple(pages)


def stream_of(pages: Sequence[Page]) -> Stream:
    bodies = [_WS.sub("", p.body) for p in pages]
    return Stream("".join(bodies), tuple(accumulate((len(b) for b in bodies[:-1]), initial=0)))


# ------------------------------------------------------------------ containment and gaps


def _find_lines(lines: Sequence[str], text: str,
                pos: int) -> tuple[int, int, tuple[Gap, ...]] | None:
    """(first line start, end, gaps) of ``lines`` found in order from ``pos``."""
    first, end, gaps = None, pos, []
    for i, line in enumerate(lines):
        at = text.find(line, end)
        if at < 0 or (first is not None and at - end > MAX_PIECE_GAP):
            return None
        if first is None:
            first = at
        elif at > end:
            gaps.append((i, end, at))
        end = at + len(line)
    return first, end, tuple(gaps)


def locate(units: Sequence[Unit], text: str) -> dict[str, tuple[int, int, tuple[Gap, ...]]]:
    """Where each unit poppler has was found; a unit it lacks is skipped, later ones match."""
    pos, found = 0, {}
    for unit in units:
        hit = _find_lines(unit.lines, text, pos)
        if hit is not None:
            found[unit.key], pos = hit, hit[1]
    return found


def containment(units: Sequence[Unit], found: Mapping[str, tuple]) -> dict[str, Any]:
    widths = [at - end for _, _, gaps in found.values() for _, end, at in gaps]
    return {"contained": len(found), "misses": [u.key for u in units if u.key not in found],
            "max_gap": max(widths, default=0)}


def _numbered(unit: Unit, text: str, at: int) -> bool:
    labels = {unit.label.replace("-", d) for d in DASHES}
    return any(text[at - len(label):at] == label for label in labels)


def boundaries(units: Sequence[Unit], found: Mapping[str, tuple], text: str) -> dict[str, Any]:
    present = [u for u in units if u.key in found]
    misses = [u.key for u in present if not _numbered(u, text, found[u.key][0])]
    return {"ok": len(present) - len(misses), "misses": misses}


def _explained(unit: Unit, gap: Gap, stream: Stream) -> bool:
    """The gap is what the layer prints at that line break, or a page break after which the
    line goes on at once (the insert may stand at either side of the break)."""
    line, end, at = gap
    insert = unit.inserts[line]
    breaks = [p for p in stream.page_starts if end < p <= at]
    if not breaks:
        return stream.text[end:at] == insert
    top = stream.text[breaks[-1]:at]
    return top == insert or (top == "" and stream.text[end:breaks[-1]].startswith(insert))


def gaps(units: Sequence[Unit], found: Mapping[str, tuple], stream: Stream) -> dict[str, Any]:
    explained, unexplained = 0, []
    for unit in (u for u in units if u.key in found):
        for gap in found[unit.key][2]:
            if _explained(unit, gap, stream):
                explained += 1
            else:
                unexplained.append({"unit": unit.key, "offset": unit.offset(gap[0]),
                                    "text": stream.text[gap[1]:gap[2]]})
    return {"explained": explained, "unexplained": unexplained}


# ------------------------------------------------------------------ characters


def _nonspace(text: str) -> int:
    return sum(1 for c in text if not c.isspace())


def poppler_chars(pages: Sequence[Page]) -> int:
    """Non-space characters poppler printed outside the running heads and the colophon."""
    body = pages[:-1] if pages and pages[-1].head is None else pages
    return sum(_nonspace(p.body) for p in body)


def layer_chars(book: Mapping[str, Any], records: Records) -> int:
    """Non-space characters the layer accounts for in one book's PDF (``records`` of it)."""
    first = 1 if book["book_id"] in CHAPTER_ONE_NUMERAL else 2
    numerals = sum(len(str(c)) for c in range(first, book["chapter_count"] + 1))
    labels = sum(len(u["label"]) for u in records["verse_units"])
    return sum(record_counts(records).values()) + labels + numerals + _nonspace(book["name"])


# ------------------------------------------------------------------ running heads


def _ref(chapter: str | None, verse: str, end: str | None) -> tuple[int, int, int]:
    return int(chapter or 1), int(verse), int(end or verse)


def _expected(page: int, units: Sequence[Unit], starts: Mapping[int, list[Unit]]):
    if starts.get(page):
        return starts[page][0], starts[page][-1], False
    running = [u for u in units if u.pages[0] < page and page in u.pages]
    return (running[-1], running[-1], True) if running else (None, None, True)


def _head_ok(head: tuple, left: Unit, right: Unit, name: str) -> bool:
    n1, c1, v1, w1, n2, c2, v2, w2 = head
    lo, hi = (left.chapter, left.v_start, left.v_end), (right.chapter, right.v_start, right.v_end)
    return n1 == name == n2 and _ref(c1, v1, w1) in (lo, lo[:2] + (lo[1],)) \
        and _ref(c2, v2, w2) in (hi, hi[:2] + (hi[1],), (hi[0], hi[2], hi[2]))


def check_heads(pages: Sequence[Page], units: Sequence[Unit], name: str) -> dict[str, Any]:
    starts: dict[int, list[Unit]] = defaultdict(list)
    for unit in units:
        starts[unit.pages[0]].append(unit)
    ok, continued, mismatches = 0, 0, []
    for page in (p for p in pages if p.head is not None):
        left, right, running = _expected(page.number, units, starts)
        continued += running
        if left is not None and _head_ok(page.head, left, right, name):
            ok += 1
        else:
            mismatches.append({"page": page.number, "head": list(page.head),
                               "expected": [u.key for u in (left, right) if u is not None]})
    headless = [p.number for p in pages if p.head is None]
    return {"pages": len(pages), "with_head": len(pages) - len(headless), "ok": ok,
            "continued": continued, "mismatches": mismatches,
            "without_head_not_last": [n for n in headless if n != len(pages)]}


def _read(text: str, units: Sequence[Unit]):
    pages = split_pages(text)
    stream = stream_of(pages)
    return pages, stream, locate(units, stream.text)


def check_book(texts: Mapping[str, str], book: Mapping[str, Any],
               records: Records) -> dict[str, Any]:
    """All checks of one book from its poppler text in each mode (``records`` of the book)."""
    units = units_of(records).get(book["book_id"], ())
    read = {mode: _read(texts[mode], units) for mode in MODES}
    pages, stream, found = read["raw"]
    want = layer_chars(book, records)
    return {"units": len(units),
            "containment": {m: containment(units, read[m][2]) for m in MODES},
            "gaps": gaps(units, found, stream),
            "characters": {m: {"poppler": poppler_chars(read[m][0]), "layer": want}
                           for m in MODES},
            "boundaries": boundaries(units, found, stream.text),
            "running_heads": check_heads(pages, units, book["name"])}


# ------------------------------------------------------------------ report and gate


def _node(result: Mapping[str, Any], path: Sequence[str]) -> Mapping[str, Any]:
    for step in path:
        result = result[step]
    return result


def _sum(results: Mapping[str, Mapping[str, Any]], path: Sequence[str], key: str) -> int:
    return sum(_node(r, path)[key] for r in results.values())


def _tagged(book: str, item: Any) -> Any:
    """Unit keys name their book already; pages and dict items get it added."""
    if isinstance(item, dict):
        return {"book": book, **item}
    return item if isinstance(item, str) else f"{book} p{item}"


def _listed(results: Mapping[str, Mapping[str, Any]], path: Sequence[str], key: str) -> list:
    return [_tagged(book, item) for book, r in results.items() for item in _node(r, path)[key]]


def _characters(results: Mapping[str, Mapping[str, Any]], mode: str) -> dict[str, Any]:
    path = ("characters", mode)
    return {"poppler": _sum(results, path, "poppler"), "layer": _sum(results, path, "layer"),
            "books_off": [{"book": book, **r["characters"][mode]} for book, r in results.items()
                          if r["characters"][mode]["poppler"] != r["characters"][mode]["layer"]]}


def assemble(results: Mapping[str, Mapping[str, Any]], unit_count: int) -> dict[str, Any]:
    """The corpus report from per-book results; ``unit_count`` is how many units the layer has."""
    heads = ("running_heads",)
    return {
        "schema": REPORT_SCHEMA, "tool": "pdftotext", "modes": list(MODES), "crop": list(CROP),
        "max_piece_gap": MAX_PIECE_GAP, "units": unit_count,
        "units_checked": sum(r["units"] for r in results.values()),
        "containment": {mode: {"contained": _sum(results, ("containment", mode), "contained"),
                               "max_gap": max((r["containment"][mode]["max_gap"]
                                               for r in results.values()), default=0),
                               "misses": _listed(results, ("containment", mode), "misses")}
                        for mode in MODES},
        "gaps": {"explained": _sum(results, ("gaps",), "explained"),
                 "unexplained": _listed(results, ("gaps",), "unexplained")},
        "characters": {mode: _characters(results, mode) for mode in MODES},
        "boundaries": {"ok": _sum(results, ("boundaries",), "ok"),
                       "misses": _listed(results, ("boundaries",), "misses")},
        "running_heads": {**{k: _sum(results, heads, k)
                             for k in ("pages", "with_head", "ok", "continued")},
                          "mismatches": _listed(results, heads, "mismatches"),
                          "without_head_not_last": _listed(results, heads,
                                                           "without_head_not_last")},
    }


def encode_report(report: Mapping[str, Any]) -> bytes:
    return (json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()


def _pdf(pdf_dir: Path, book: Mapping[str, Any]) -> Path:
    path = Path(pdf_dir) / f"{book['file_name']}.pdf"
    if not path.is_file():
        raise XcheckError(f"{path}: missing PDF for {book['book_id']}")
    if hashlib.sha256(path.read_bytes()).hexdigest() != book["pdf_sha256"]:
        raise XcheckError(f"{path}: sha256 differs from the layer's books record")
    return path


def xcheck(pdf_dir: Path, records: Records, run: Runner = run_pdftotext,
           workers: int = 8) -> dict[str, Any]:
    """Read every book's PDF with poppler in both modes and cross-check the layer's records
    (``records`` by type: books and ``BOOK_TYPES``)."""
    books = records["books"]
    paths = {b["book_id"]: _pdf(pdf_dir, b) for b in books}
    jobs = [(b["book_id"], mode) for b in books for mode in MODES]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        texts = dict(zip(jobs, pool.map(lambda job: run(paths[job[0]], job[1]), jobs)))
    by_book = book_records(records)
    results = {b["book_id"]: check_book({m: texts[(b["book_id"], m)] for m in MODES}, b,
                                        by_book[b["book_id"]])
               for b in books}
    return assemble(results, len(records["verse_units"]))


def _failures(report: Mapping[str, Any]) -> list[str]:
    units, heads = report["units"], report["running_heads"]
    details = [] if report["units_checked"] == units else \
        [f"{report['units_checked']} of {units} units were checked"]
    for mode in MODES:
        found = report["containment"][mode]
        details += [f"{mode}: {found['contained']}/{units} units contained"] \
            if found["contained"] != units else []
        details += [f"{mode}: {key} not contained" for key in found["misses"]]
    details += [f"raw: {g['text']!r} before offset {g['offset']} of {g['unit']} is neither "
                "a mid-verse heading or speaker of the layer nor a page break"
                for g in report["gaps"]["unexplained"]]
    details += [f"{mode}: {b['book']} poppler prints {b['poppler']} characters, the layer "
                f"accounts for {b['layer']}"
                for mode in MODES for b in report["characters"][mode]["books_off"]]
    details += [f"verse number not before {key}" for key in report["boundaries"]["misses"]]
    details += [f"running head {m['book']} p{m['page']}: {m['head']} vs {m['expected']}"
                for m in heads["mismatches"]]
    return details + [f"no running head on {p}" for p in heads["without_head_not_last"]]


def check_xcheck(report: Mapping[str, Any]) -> GateResult:
    """G-XCHECK: every unit contained in both modes with every raw gap explained, every
    book's characters accounted for, every number and running head agrees."""
    units, heads, chars = report["units"], report["running_heads"], report["characters"]
    observed = {"units": units, **{m: report["containment"][m]["contained"] for m in MODES},
                "unexplained_gaps": len(report["gaps"]["unexplained"]),
                "characters": {m: f"{chars[m]['poppler']}/{chars[m]['layer']}" for m in MODES},
                "numbers": report["boundaries"]["ok"],
                "running_heads": f"{heads['ok']}/{heads['with_head']}"}
    expected = {"units": units, **{m: units for m in MODES}, "unexplained_gaps": 0,
                "characters": {m: f"{chars[m]['layer']}/{chars[m]['layer']}" for m in MODES},
                "numbers": units, "running_heads": f"{heads['with_head']}/{heads['with_head']}"}
    details = _failures(report)
    return GateResult(NAME, True, not details, observed, expected, capped(details))
