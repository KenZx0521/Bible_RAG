"""S0: the source manifest (design §2.1) and its gates G-SRC and G-TOOL (design §8).

The manifest says which PDFs were read and with which tools: each file's sha256,
page count, the book name printed on its title line (尼西米記.pdf prints 尼希米記,
G13), its colophon as printed (it claims 新標點和合本, but the text is RCUV, G04),
the running-head names, how many glyphs sit past the page edge and how many
strokes the page has. The edition verdict rests on proper-name spellings that
tell RCUV from CUNP (呂便/流便, 塞魯士/古列, 凱撒/該撒, 泰爾/推羅 …), counted over
everything but running heads and colophon, whitespace removed.

Everything except the file sha comes from the S1 rows, so S0 runs after S1 and
both land in the ``src`` layer. ``source_expect.yaml`` pins what G-SRC and
G-TOOL compare against.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ragcommon import books
from ragdata.gates.base import GateResult, capped
from ragdata.stages import layout
from ragdata.stages.errors import StageError
from ragdata.stages.s01_extract import S1Book, mutool_version, overflow_glyphs, script_sha256

EXPECT_PATH = Path(__file__).resolve().parents[1] / "contract" / "expectations" / \
    "source_expect.yaml"
EXPECT_SCHEMA = "ragdata.source_expect.v1"
EXPECT_KEYS = ("toolchain", "ebible_uuid", "pdfs", "edition_markers", "pages",
               "overflow_glyphs", "strokes", "style_groups", "conserve")
MANIFEST_SCHEMA = "src.v1"
EDITION_MARKERS = (("呂便", "流便"), ("塞魯士", "古列"), ("凱撒", "該撒"), ("大流士", "大利烏"),
                   ("泰爾", "推羅"), ("撒馬利亞", "撒瑪利亞"))  # (RCUV, CUNP)
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_HEADER_RE = re.compile(r"(\S+?)\s*(?:[0-9]+:)?[0-9]+(?:[-–－][0-9]+)?")


class SourceError(StageError):
    """The PDF directory or the source expectations are not what S0 can describe."""


@dataclass(frozen=True)
class SourcePdf:
    book_id: str
    path: Path
    sha256: str

    @property
    def file(self) -> str:
        return self.path.name


def discover(pdf_dir: Path) -> tuple[SourcePdf, ...]:
    """Every ``*.pdf`` in ``pdf_dir``, named as in books.json, in canonical order."""
    by_file = {b.file_name: b for b in books.all_books()}
    found = sorted(Path(pdf_dir).glob("*.pdf"))
    if not found:
        raise SourceError(f"{pdf_dir}: no PDF files")
    unknown = [p.name for p in found if p.stem not in by_file]
    if unknown:
        raise SourceError(f"{pdf_dir}: not a book of books.json: {unknown}")
    pdfs = [SourcePdf(by_file[p.stem].book_id, p, hashlib.sha256(p.read_bytes()).hexdigest())
            for p in found]
    return tuple(sorted(pdfs, key=lambda p: books.get_book(p.book_id).ord))


def pdftotext_version() -> str:
    done = subprocess.run(["pdftotext", "-v"], capture_output=True, text=True, check=False,
                          timeout=60)
    found = re.search(r"pdftotext version (\S+)", done.stdout + done.stderr)
    if done.returncode != 0 or found is None:
        raise SourceError(f"cannot read the pdftotext version: {done.stderr.strip()}")
    return found.group(1)


def toolchain() -> dict[str, str]:
    return {"mutool": mutool_version(), "pdftotext": pdftotext_version(),
            "python": platform.python_version(), "s01_script_sha256": script_sha256()}


# ------------------------------------------------------------------ the manifest


def _header_names(book: S1Book) -> list[str]:
    names = set()
    for ln in book.lines:
        if all(g.color == layout.BLUE for g in ln.glyphs):
            found = _HEADER_RE.fullmatch(ln.text.strip())
            if found:
                names.add(found.group(1))
    return sorted(names)


def _title_line(rows: Sequence[layout.Row]) -> str:
    return "".join(layout.clean_text(r.text) for r in rows
                   if layout.classify(r) == layout.BOOK_TITLE)


def describe(pdf: SourcePdf, book: S1Book, rows: Sequence[layout.Row]) -> dict[str, Any]:
    _, colophon = layout.split_colophon(rows, pdf.file)
    title = _title_line(rows)
    return {
        "file": pdf.file, "book_id": pdf.book_id, "sha256": pdf.sha256, "pages": len(book.pages),
        "book_title_line": title, "file_name_mismatch": pdf.path.stem != title,
        "colophon_text": " / ".join(r.text.strip() for r in colophon),
        "header_names": _header_names(book), "overflow_glyphs": overflow_glyphs(book),
        "strokes": len(book.strokes),
    }


def edition_markers(rows_by_book: Mapping[str, Sequence[layout.Row]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for book_id, rows in rows_by_book.items():
        body, _ = layout.split_colophon(rows, book_id)
        text = "".join(g.c for r in body if layout.classify(r) != layout.HEADER
                       for g in r.glyphs if not g.c.isspace())
        counts.update({m: text.count(m) for pair in EDITION_MARKERS for m in pair})
    return {m: counts[m] for pair in EDITION_MARKERS for m in pair}


def _verdict(markers: Mapping[str, int]) -> str:
    """RCUV when only RCUV spellings occur, CUNP when only CUNP ones do."""
    rcuv = sum(markers[a] for a, _ in EDITION_MARKERS)
    cunp = sum(markers[b] for _, b in EDITION_MARKERS)
    return {(True, False): "RCUV", (False, True): "CUNP"}.get((rcuv > 0, cunp > 0), "unknown")


def style_fingerprint(s1_books: Mapping[str, S1Book]) -> dict[str, Any]:
    counts = Counter(f"{g.font}|{g.size}|{g.color}" for b in s1_books.values()
                     for ln in b.lines for g in ln.glyphs if not g.c.isspace())
    return {"groups": len(counts), "char_counts": dict(sorted(counts.items()))}


def build_manifest(pdfs: Sequence[SourcePdf], s1_books: Mapping[str, S1Book],
                   tools: Mapping[str, str]) -> dict[str, Any]:
    rows = {p.book_id: layout.rows_of(s1_books[p.book_id].lines) for p in pdfs}
    entries = [describe(p, s1_books[p.book_id], rows[p.book_id]) for p in pdfs]
    uuids = {u for e in entries for u in _UUID_RE.findall(e["colophon_text"])}
    markers = edition_markers(rows)
    return {
        "schema": MANIFEST_SCHEMA, "pdfs": entries,
        "ebible_uuid": uuids.pop() if len(uuids) == 1 else None,
        "toolchain": dict(tools), "style_fingerprint": style_fingerprint(s1_books),
        "edition_detection": {"verdict": _verdict(markers), "markers": markers},
    }


def encode_manifest(manifest: Mapping[str, Any]) -> bytes:
    return (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode()


# ------------------------------------------------------------------ expectations and gates


def load_expect(path: Path | str = EXPECT_PATH) -> dict[str, Any]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SourceError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != EXPECT_SCHEMA:
        raise SourceError(f"{path}: schema must be {EXPECT_SCHEMA}")
    missing = [k for k in EXPECT_KEYS if k not in doc]
    if missing:
        raise SourceError(f"{path}: missing {missing}")
    return doc


def _diff(name: str, observed: Any, expected: Any) -> list[str]:
    return [] if observed == expected else [f"{name}: observed {observed!r}, expected {expected!r}"]


def _pdf_details(manifest: Mapping[str, Any], expect: Mapping[str, Any]) -> list[str]:
    seen = {p["file"]: p for p in manifest["pdfs"]}
    out = [f"{f}: expected PDF is missing" for f in sorted(set(expect["pdfs"]) - set(seen))]
    out += [f"{f}: PDF is not in the expectations" for f in sorted(set(seen) - set(expect["pdfs"]))]
    for f in sorted(set(seen) & set(expect["pdfs"])):
        p = seen[f]
        out += _diff(f"{f} sha256", p["sha256"], expect["pdfs"][f])
        out += _diff(f"{f} title line", p["book_title_line"], books.get_book(p["book_id"]).name)
    colophons = {p["colophon_text"] for p in manifest["pdfs"]}
    out += [] if len(colophons) == 1 else [f"colophon texts differ: {len(colophons)} variants"]
    return out


def _totals(manifest: Mapping[str, Any]) -> dict[str, Any]:
    pdfs = manifest["pdfs"]
    return {"pages": sum(p["pages"] for p in pdfs),
            "overflow_glyphs": sum(p["overflow_glyphs"] for p in pdfs),
            "strokes": sum(p["strokes"] for p in pdfs),
            "ebible_uuid": manifest["ebible_uuid"],
            "edition_markers": dict(manifest["edition_detection"]["markers"]),
            "style_groups": manifest["style_fingerprint"]["char_counts"]}


def check_source(manifest: Mapping[str, Any], expect: Mapping[str, Any]) -> GateResult:
    """G-SRC: the PDFs, their title lines, colophon, edition markers and S1 totals."""
    totals = _totals(manifest)
    details = _pdf_details(manifest, expect)
    details += _diff("verdict", manifest["edition_detection"]["verdict"], "RCUV")
    for key in ("pages", "overflow_glyphs", "strokes", "ebible_uuid"):
        details += _diff(key, totals[key], expect[key])
    for marker, count in sorted(expect["edition_markers"].items()):
        details += _diff(f"edition marker {marker}", totals["edition_markers"].get(marker), count)
    groups, pinned = totals["style_groups"], expect["style_groups"]
    for group in sorted(set(groups) | set(pinned)):
        details += _diff(f"style group {group}", groups.get(group), pinned.get(group))
    observed = {**totals, "pdfs": len(manifest["pdfs"]),
                "verdict": manifest["edition_detection"]["verdict"]}
    expected = {k: expect[k] for k in EXPECT_KEYS if k not in ("toolchain", "pdfs", "conserve")}
    return GateResult("G-SRC", True, not details, observed,
                      {**expected, "pdfs": len(expect["pdfs"]), "verdict": "RCUV"}, capped(details))


def check_tools(tools: Mapping[str, str], expect: Mapping[str, Any]) -> GateResult:
    """G-TOOL: the extraction and cross-check tools are the pinned versions."""
    pinned = expect["toolchain"]
    details = [d for name in sorted(pinned) for d in _diff(name, tools.get(name), pinned[name])]
    return GateResult("G-TOOL", True, not details, {k: tools.get(k) for k in pinned},
                      dict(pinned), tuple(details))
