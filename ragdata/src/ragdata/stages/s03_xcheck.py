"""S3: cross-check the text layer against poppler (design §4, §8 G-XCHECK).

S1 and S2 both read the PDFs through MuPDF; poppler's ``pdftotext`` is the one
independent reader (audit G70). Each PDF is read twice, ``-raw`` (content order)
and ``-layout`` (visual order), with the crop box widened so the 852 glyphs
typeset past the page edge are kept. Three checks over every verse unit:

- containment: each PDF line of the unit (``text_pdf`` cut at ``line_breaks``)
  occurs in the whitespace-free poppler text of its book, in canonical order, at
  most ``MAX_PIECE_GAP`` characters after the line before it (both modes);
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
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from ragdata.contract.registry import XCHECK_REPORT
from ragdata.gates.base import GateResult, capped
from ragdata.stages.errors import StageError

NAME = "G-XCHECK"
REPORT_FILE = XCHECK_REPORT
REPORT_SCHEMA = "ragdata.xcheck_report.v1"
MODES = ("raw", "layout")
CROP = ("-x", "0", "-y", "0", "-W", "2000", "-H", "2000")
MAX_PIECE_GAP = 200  # characters between two lines of one verse; the corpus maximum is 72
TIMEOUT_S = 300
DASHES = ("-", "–", "－")
_WS = re.compile(r"\s+")
_REF = r"(\S+?)\s*(?:([0-9]+):)?([0-9]+)(?:[-–－]([0-9]+))?"
_HEAD = re.compile(rf"{_REF}\s+[ivxlcdm]+\s+{_REF}")

Runner = Callable[[Path, str], str]


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


@dataclass(frozen=True)
class Page:
    number: int
    head: tuple | None  # (name, chapter, verse, end, name, chapter, verse, end) when present
    body: str


def _lines(text: str, breaks: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    cuts = [0, *(b["offset"] for b in breaks), len(text)]
    return tuple(text[a:b] for a, b in zip(cuts, cuts[1:]))


def units_of(rows: Iterable[Mapping[str, Any]]) -> dict[str, tuple[Unit, ...]]:
    """Verse-unit rows by book, in canonical (``ord``) order."""
    by_book: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_book[row["book_id"]].append(row)
    return {book: tuple(Unit(r["unit_key"], r["chapter"], r["v_start"], r["v_end"], r["label"],
                             _lines(r["text_pdf"], r["line_breaks"]), tuple(r["pages"]))
                        for r in sorted(group, key=lambda r: r["ord"]))
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


def _flat(pages: Sequence[Page]) -> str:
    return _WS.sub("", "".join(p.body for p in pages))


# ------------------------------------------------------------------ containment and numbers


def _find_lines(lines: Sequence[str], stream: str, pos: int) -> tuple[int, int, int] | None:
    """(first line start, end, largest gap) of ``lines`` found in order from ``pos``."""
    first, end, gap = None, pos, 0
    for line in lines:
        at = stream.find(line, end)
        if at < 0 or (first is not None and at - end > MAX_PIECE_GAP):
            return None
        if first is None:
            first = at
        else:
            gap = max(gap, at - end)
        end = at + len(line)
    return first, end, gap


def _numbered(unit: Unit, stream: str, at: int) -> bool:
    labels = {unit.label.replace("-", d) for d in DASHES}
    return any(stream[at - len(label):at] == label for label in labels)


def contain(units: Sequence[Unit], stream: str, check_numbers: bool) -> dict[str, Any]:
    pos, contained, gap = 0, 0, 0
    misses, numbered, unnumbered = [], 0, []
    for unit in units:
        found = _find_lines(unit.lines, stream, pos)
        if found is None:
            misses.append(unit.key)
            continue
        first, pos, unit_gap = found
        contained, gap = contained + 1, max(gap, unit_gap)
        if check_numbers and _numbered(unit, stream, first):
            numbered += 1
        elif check_numbers:
            unnumbered.append(unit.key)
    result = {"contained": contained, "misses": misses, "max_gap": gap}
    return {**result, "boundaries": {"ok": numbered, "misses": unnumbered}} if check_numbers \
        else result


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


def check_book(texts: Mapping[str, str], units: Sequence[Unit], name: str) -> dict[str, Any]:
    """All checks of one book from its poppler text in each mode."""
    containment, boundaries = {}, None
    for mode in MODES:
        found = contain(units, _flat(split_pages(texts[mode])), check_numbers=mode == "raw")
        boundaries = found.pop("boundaries", boundaries)
        containment[mode] = found
    return {"units": len(units), "containment": containment, "boundaries": boundaries,
            "running_heads": check_heads(split_pages(texts["raw"]), units, name)}


# ------------------------------------------------------------------ report and gate


def _node(result: Mapping[str, Any], path: Sequence[str]) -> Mapping[str, Any]:
    for step in path:
        result = result[step]
    return result


def _sum(results: Mapping[str, Mapping[str, Any]], path: Sequence[str], key: str) -> int:
    return sum(_node(r, path)[key] for r in results.values())


def _tagged(book: str, item: Any) -> Any:
    """Unit keys name their book already; pages and head mismatches get it added."""
    if isinstance(item, dict):
        return {"book": book, **item}
    return item if isinstance(item, str) else f"{book} p{item}"


def _listed(results: Mapping[str, Mapping[str, Any]], path: Sequence[str], key: str) -> list:
    return [_tagged(book, item) for book, r in results.items() for item in _node(r, path)[key]]


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


def xcheck(pdf_dir: Path, books: Sequence[Mapping[str, Any]],
           units: Iterable[Mapping[str, Any]], run: Runner = run_pdftotext,
           workers: int = 8) -> dict[str, Any]:
    """Read every book's PDF with poppler in both modes and cross-check its units."""
    unit_rows = list(units)
    by_book = units_of(unit_rows)
    paths = {b["book_id"]: _pdf(pdf_dir, b) for b in books}
    jobs = [(b["book_id"], mode) for b in books for mode in MODES]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        texts = dict(zip(jobs, pool.map(lambda job: run(paths[job[0]], job[1]), jobs)))
    results = {b["book_id"]: check_book({m: texts[(b["book_id"], m)] for m in MODES},
                                        by_book.get(b["book_id"], ()), b["name"])
               for b in books}
    return assemble(results, len(unit_rows))


def check_xcheck(report: Mapping[str, Any]) -> GateResult:
    """G-XCHECK: every unit contained in both modes, every number and running head agrees."""
    units, heads = report["units"], report["running_heads"]
    details = [] if report["units_checked"] == units else \
        [f"{report['units_checked']} of {units} units were checked"]
    for mode in MODES:
        found = report["containment"][mode]
        details += [f"{mode}: {found['contained']}/{units} units contained"] \
            if found["contained"] != units else []
        details += [f"{mode}: {key} not contained" for key in found["misses"]]
    details += [f"verse number not before {key}" for key in report["boundaries"]["misses"]]
    details += [f"running head {m['book']} p{m['page']}: {m['head']} vs {m['expected']}"
                for m in heads["mismatches"]]
    details += [f"no running head on {p}" for p in heads["without_head_not_last"]]
    observed = {"units": units, **{m: report["containment"][m]["contained"] for m in MODES},
                "numbers": report["boundaries"]["ok"],
                "running_heads": f"{heads['ok']}/{heads['with_head']}"}
    expected = {"units": units, **{m: units for m in MODES}, "numbers": units,
                "running_heads": f"{heads['with_head']}/{heads['with_head']}"}
    return GateResult(NAME, True, not details, observed, expected, capped(details))
