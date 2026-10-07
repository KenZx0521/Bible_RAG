"""S1: unclipped per-glyph extraction of each PDF with ``mutool run`` (design §4).

``stext_noclip.js`` walks every page with ``mediabox-clip=no``: 852 glyphs of the
corpus are typeset past the right page edge (unbreakable name boxes), and the
default clip drops them silently (audit §2.3, G01). It prints page, line and
stroke rows (see the script header). Rows are validated here and re-encoded as
canonical JSONL, so the stored bytes depend only on the PDF and the toolchain,
and S2 can trust their shape.
"""

from __future__ import annotations

import hashlib
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ragdata.stages.errors import StageError
from ragdata.stages.layout import Line, to_line
from ragdata.store import StoreError, decode_jsonl, encode_jsonl

SCRIPT = Path(__file__).with_name("stext_noclip.js")
MUTOOL = "mutool"
TIMEOUT_S = 600
OVERFLOW_PT = 0.5  # a glyph whose right edge passes the page edge by more than this
_COLOR_RE = re.compile(r"#[0-9a-f]{6}")
_KEYS = {"page": {"k", "p", "bounds"}, "line": {"k", "p", "chars"},
         "stroke": {"k", "p", "lw", "path"}}
_PATH_ARITY = {"m": 2, "l": 2, "c": 6, "z": 0}


class ExtractError(StageError):
    """mutool failed, or printed rows that break the S1 row contract."""


@dataclass(frozen=True)
class Stroke:
    page: int
    lw: float
    path: tuple[tuple, ...]


@dataclass(frozen=True)
class S1Book:
    """One PDF as S1 extracted it: page bounds, structured-text lines, stroked paths.

    Glyphs are numbered (``Glyph.seq``) in the order of the extract's line rows, so a
    record can point back at the glyphs it came from (design §2.7 ``glyph_range``).
    """

    pages: Mapping[int, tuple[float, ...]]
    lines: tuple[Line, ...]
    strokes: tuple[Stroke, ...]


def script_sha256() -> str:
    return hashlib.sha256(SCRIPT.read_bytes()).hexdigest()


def _tool_version(argv: Sequence[str], pattern: str) -> str:
    done = subprocess.run(list(argv), capture_output=True, text=True, check=False, timeout=60)
    found = re.search(pattern, done.stdout + done.stderr)
    if done.returncode != 0 or found is None:
        raise ExtractError(f"cannot read the version of {argv[0]}: {done.stderr.strip()}")
    return found.group(1)


def mutool_version() -> str:
    return _tool_version([MUTOOL, "-v"], r"mutool version (\S+)")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _check(ok: bool, where: str, message: str) -> None:
    if not ok:
        raise ExtractError(f"{where}: {message}")


def _check_char(ch: Any, where: str) -> None:
    ok = isinstance(ch, list) and len(ch) == 7 and isinstance(ch[0], str) and len(ch[0]) == 1 \
        and all(_number(v) for v in (ch[1], ch[2], ch[3], ch[5])) \
        and isinstance(ch[4], str) and ch[4] != "" \
        and isinstance(ch[6], str) and _COLOR_RE.fullmatch(ch[6]) is not None
    _check(ok, where, f"bad char {ch!r}")


def _check_path(path: Any, where: str) -> tuple[tuple, ...]:
    _check(isinstance(path, list) and bool(path), where, "path must be a non-empty list")
    for op in path:
        ok = isinstance(op, list) and bool(op) and op[0] in _PATH_ARITY \
            and len(op) == 1 + _PATH_ARITY[op[0]] and all(_number(v) for v in op[1:])
        _check(ok, where, f"bad path op {op!r}")
    return tuple(tuple(op) for op in path)


def _page_row(row: dict, expected: int, where: str) -> tuple[float, ...]:
    _check(row["p"] == expected, where, f"page {row['p']} where page {expected} was due")
    bounds = row["bounds"]
    _check(isinstance(bounds, list) and len(bounds) == 4 and all(map(_number, bounds)),
           where, f"bad bounds {bounds!r}")
    return tuple(bounds)


def _typed(rows: Sequence[dict], where: str) -> S1Book:
    pages: dict[int, tuple[float, ...]] = {}
    lines, strokes = [], []
    seq = 0
    for i, row in enumerate(rows, start=1):
        at = f"{where}:{i}"
        kind = row.get("k")
        _check(kind in _KEYS, at, f"unknown row kind {kind!r}")
        _check(set(row) == _KEYS[kind], at, f"keys {sorted(row)} are not {sorted(_KEYS[kind])}")
        _check(bool(pages) or kind == "page", at, "the first row must be a page row")
        if kind == "page":
            pages[len(pages) + 1] = _page_row(row, len(pages) + 1, at)
            continue
        _check(row["p"] == len(pages), at, f"row of page {row['p']} inside page {len(pages)}")
        if kind == "line":
            _check(isinstance(row["chars"], list) and bool(row["chars"]), at, "empty chars")
            for ch in row["chars"]:
                _check_char(ch, at)
            lines.append(to_line(row["p"], row["chars"], seq))
            seq += len(row["chars"])
        else:
            _check(_number(row["lw"]) and row["lw"] > 0, at, f"bad lw {row['lw']!r}")
            strokes.append(Stroke(row["p"], row["lw"], _check_path(row["path"], at)))
    _check(bool(pages), where, "no page row")
    return S1Book(pages, tuple(lines), tuple(strokes))


def _decode(data: bytes, where: str) -> tuple[dict, ...]:
    try:
        return decode_jsonl(data, where)
    except StoreError as exc:
        raise ExtractError(str(exc)) from None


def load_s1(data: bytes, where: str) -> S1Book:
    """Validate and type the S1 rows of one PDF; raise ExtractError on any violation."""
    return _typed(_decode(data, where), where)


def run_script(pdf: Path) -> bytes:
    done = subprocess.run([MUTOOL, "run", str(SCRIPT), str(pdf)], capture_output=True,
                          check=False, timeout=TIMEOUT_S)
    if done.returncode != 0 or done.stderr.strip():
        raise ExtractError(f"{pdf.name}: mutool exited {done.returncode}: "
                           f"{done.stderr.decode('utf-8', 'replace').strip()}")
    return done.stdout


def extract_pdf(pdf: Path) -> tuple[bytes, S1Book]:
    """Canonical S1 bytes of ``pdf`` and their typed form."""
    rows = _decode(run_script(pdf), pdf.name)
    book = _typed(rows, pdf.name)
    return encode_jsonl(rows), book


def extract_all(pdfs: Mapping[str, Path], workers: int = 8) -> dict[str, tuple[bytes, S1Book]]:
    """Extract every PDF (by book id) in parallel; the result keeps the input order."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        done = dict(zip(pdfs, pool.map(extract_pdf, pdfs.values())))
    return {book_id: done[book_id] for book_id in pdfs}


def overflow_glyphs(book: S1Book) -> int:
    """Glyphs whose right edge lies past the page edge (kept only because of no clipping)."""
    return sum(1 for ln in book.lines for g in ln.glyphs
               if not g.c.isspace() and g.x1 > book.pages[ln.page][2] + OVERFLOW_PT)
