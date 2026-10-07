"""S4: the errata overlay (design §2.12, audit G11, decision D-03(b)).

``config/registries/errata.yaml`` lists every place where the PDF prints a wrong
character: nine misglyphs from one Big5 run (E041–E050), 25 places in verse
text and one footnote. ``text_pdf`` always keeps the printed character. When a
misglyph's correction is decided (``status: apply``), ``text`` gets the
corrected character at the same offset — equal length, nothing else changes —
and the container lists the errata id; an ``uncertain`` correction is listed
but not applied. Characters of the same run that are right where they stand
(E046 誆) are declared ``not_errata``.

The registry must fit the PDF text exactly, or the stage raises OverlayError:
each entry's container holds the misglyph at its offset; every occurrence of a
listed misglyph is an entry; an applied correction occurs nowhere in the PDF
text (it was replaced everywhere, G11). Entries in books outside the build are
skipped, so a build of some books can apply its share.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator, Mapping, Sequence

import yaml

from ragcommon import ids
from ragdata.stages.errors import StageError

REPO = Path(__file__).resolve().parents[5]
DEFAULT_PATH = REPO / "config" / "registries" / "errata.yaml"
SCHEMA = "ragdata.errata.v1"
STATUSES = ("apply", "uncertain")
_ID_RE = re.compile(r"er:[0-9]{4}")
# record type -> (primary key, errata container kind); ids.parse kinds -> container kind
CONTAINERS = {"verse_units": ("unit_key", "unit"), "footnotes": ("fn_id", "footnote"),
              "chapter_texts": ("id", "superscription"), "speakers": ("sk_id", "speaker")}
_KIND = {"slot": "unit", "unit": "unit", "footnote": "footnote",
         "superscription": "superscription", "speaker": "speaker"}
PDF_TEXT = (("verse_units", "text_pdf"), ("footnotes", "text_pdf"), ("headings", "text_pdf"),
            ("chapter_texts", "text_pdf"), ("speakers", "text_pdf"), ("parallel_refs", "raw"))


class OverlayError(StageError):
    """A registry does not fit the text it overlays."""


@dataclass(frozen=True)
class Misglyph:
    char: str
    big5: str
    status: str
    corrected: str | None
    candidates: tuple[str, ...]
    word: str


@dataclass(frozen=True)
class Entry:
    errata_id: str
    container: str
    offset: int
    pdf_char: str
    corrected_char: str | None


@dataclass(frozen=True)
class Errata:
    cls: str
    decided_by: str
    misglyphs: Mapping[str, Misglyph]
    correct: Mapping[str, str]
    entries: tuple[Entry, ...]


@dataclass(frozen=True)
class ErrataResult:
    rows: Mapping[str, tuple[dict[str, Any], ...]]
    applied: tuple[dict[str, Any], ...]
    report: Mapping[str, Any]


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise OverlayError(message)


def _char(value: Any, what: str) -> str:
    _require(isinstance(value, str) and len(value) == 1, f"{what} must be one character")
    return value


def _misglyph(char: str, raw: Mapping[str, Any]) -> Misglyph:
    status = raw.get("status")
    _require(status in STATUSES, f"misglyph {char}: status must be one of {STATUSES}")
    if status == "apply":
        return Misglyph(char, str(raw["big5"]), status, _char(raw.get("corrected"),
                        f"misglyph {char} corrected"), (), str(raw["word"]))
    candidates = tuple(_char(c, f"misglyph {char} candidate") for c in raw.get("candidates", []))
    _require(bool(candidates), f"misglyph {char}: an uncertain correction lists its candidates")
    return Misglyph(char, str(raw["big5"]), status, None, candidates, str(raw["word"]))


def _entry(raw: Mapping[str, Any], misglyphs: Mapping[str, Misglyph],
           correct: Mapping[str, str]) -> Entry:
    eid, container, offset, pdf = (raw.get(k) for k in ("id", "container", "offset", "pdf"))
    _require(isinstance(eid, str) and _ID_RE.fullmatch(eid) is not None,
             f"entry id must look like er:0001, got {eid!r}")
    _require(pdf not in correct, f"{eid}: {pdf} is declared correct (not_errata)")
    _require(pdf in misglyphs, f"{eid}: {pdf!r} is not a listed misglyph")
    _require(isinstance(offset, int) and not isinstance(offset, bool) and offset >= 0,
             f"{eid}: offset must be a non-negative integer")
    kind = ids.parse(container).kind if ids.is_valid(container) else None
    _require(kind in _KIND, f"{eid}: errata in a {kind or container!r} are not supported")
    glyph = misglyphs[pdf]
    if glyph.status == "uncertain":
        _require(raw.get("fix") is None, f"{eid}: {pdf} is uncertain; its fix must be null")
    else:
        _require(raw.get("fix") == glyph.corrected, f"{eid}: fix must be {glyph.corrected}")
    return Entry(eid, container, offset, pdf, glyph.corrected)


def load_errata(path: Path | str = DEFAULT_PATH) -> Errata:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OverlayError(f"{path}: unreadable: {exc}") from None
    _require(isinstance(doc, dict) and doc.get("schema") == SCHEMA,
             f"{path}: schema must be {SCHEMA}")
    correct = {_char(c, "not_errata key"): str(v.get("big5", "")) for c, v in
               (doc.get("not_errata") or {}).items()}
    misglyphs = {_char(c, "misglyph key"): _misglyph(c, raw)
                 for c, raw in (doc.get("misglyphs") or {}).items()}
    entries = tuple(_entry(raw, misglyphs, correct) for raw in doc.get("entries") or [])
    dup = [k for k, n in Counter(e.errata_id for e in entries).items() if n > 1]
    dup += [f"{c}@{o}" for (c, o), n in Counter((e.container, e.offset) for e in entries).items()
            if n > 1]
    _require(not dup, f"{path}: duplicate entries {dup}")
    return Errata(str(doc.get("class")), str(doc.get("decided_by")),
                  MappingProxyType(misglyphs), MappingProxyType(correct), entries)


# ------------------------------------------------------------------ fit and application

PK = {"verse_units": "unit_key", "footnotes": "fn_id", "headings": "heading_id",
      "chapter_texts": "id", "speakers": "sk_id", "parallel_refs": "pr_id"}
Rows = Mapping[str, Sequence[Mapping[str, Any]]]


def _texts(rows: Rows) -> Iterator[tuple[str, str]]:
    """(record id, PDF text) of every record that carries PDF wording."""
    for type_name, field in PDF_TEXT:
        for row in rows.get(type_name, ()):
            yield row[PK[type_name]], row[field]


def _count(rows: Rows, chars: str) -> Counter[str]:
    if not chars:
        return Counter()
    pattern = re.compile(f"[{re.escape(chars)}]")
    return Counter(m.group() for _, text in _texts(rows) for m in pattern.finditer(text))


def _check_fit(errata: Errata, entries: Sequence[Entry], rows: Rows) -> None:
    index = {row[PK[t]]: row for t in CONTAINERS for row in rows.get(t, ())}
    for e in entries:
        _require(e.container in index, f"{e.errata_id}: no container {e.container} in the build")
        found = index[e.container]["text_pdf"][e.offset:e.offset + 1]
        _require(found == e.pdf_char, f"{e.errata_id}: {e.container} has {found!r} at "
                                      f"{e.offset}, not {e.pdf_char!r}")
    listed = {(e.container, e.offset) for e in entries}
    pattern = re.compile(f"[{re.escape(''.join(errata.misglyphs))}]")
    unlisted = [f"{key}@{m.start()}" for key, text in _texts(rows) for m in pattern.finditer(text)
                if (key, m.start()) not in listed]
    _require(not unlisted, f"misglyphs not listed in the registry: {unlisted[:10]}")
    fixes = "".join(g.corrected for g in errata.misglyphs.values() if g.corrected)
    present = _count(rows, fixes)
    _require(not present, "corrections that already occur in the PDF text: "
                          + ", ".join(f"{c} occurs {n} times" for c, n in present.items()))


def _fixed(row: Mapping[str, Any], fixes: Sequence[Entry]) -> dict[str, Any]:
    chars = list(row["text"])
    for e in fixes:
        chars[e.offset] = e.corrected_char
    text = "".join(chars)
    out = {**row, "text": text}
    if "errata_ids" in row:
        out["errata_ids"] = sorted({*row["errata_ids"], *(e.errata_id for e in fixes)})
    if "text_sha256" in row:
        out["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return out


def _applied_row(e: Entry, errata: Errata, seen: Counter[str]) -> dict[str, Any]:
    glyph = errata.misglyphs[e.pdf_char]
    return {"errata_id": e.errata_id, "container_id": e.container,
            "container_kind": _KIND[ids.parse(e.container).kind], "offset": e.offset,
            "pdf_char": e.pdf_char, "corrected_char": e.corrected_char, "class": errata.cls,
            "evidence": {"big5": glyph.big5, "word": glyph.word,
                         "pdf_char_occurrences": seen[e.pdf_char],
                         "corrected_occurrences_in_pdf_text": 0},
            "decided_by": errata.decided_by, "provenance_class": "curated_human"}


def _report(errata: Errata, entries: Sequence[Entry], rows: Rows) -> dict[str, Any]:
    seen = _count(rows, "".join(errata.misglyphs) + "".join(errata.correct))
    candidates = _count(rows, "".join(c for g in errata.misglyphs.values() for c in g.candidates))
    glyphs = {g.char: {"big5": g.big5, "status": g.status, "word": g.word,
                       "occurrences": seen[g.char],
                       **({"corrected": g.corrected, "corrected_occurrences": 0} if g.corrected
                          else {"candidates": {c: candidates[c] for c in g.candidates}})}
              for g in errata.misglyphs.values()}
    return {"class": errata.cls, "decided_by": errata.decided_by, "entries": len(entries),
            "applied": sum(e.corrected_char is not None for e in entries),
            "uncertain": [{"errata_id": e.errata_id, "container": e.container,
                           "offset": e.offset, "pdf_char": e.pdf_char,
                           "candidates": list(errata.misglyphs[e.pdf_char].candidates)}
                          for e in entries if e.corrected_char is None],
            "misglyphs": glyphs, "not_errata": {c: seen[c] for c in errata.correct}}


def apply_errata(rows: Rows, errata: Errata, books: set[str]) -> ErrataResult:
    """Check the registry against the PDF text of ``books`` and apply its decided entries."""
    entries = [e for e in errata.entries if ids.parse(e.container).book_id in books]
    _check_fit(errata, entries, rows)
    fixes: dict[str, list[Entry]] = {}
    for e in entries:
        if e.corrected_char is not None:
            fixes.setdefault(e.container, []).append(e)
    out = {name: tuple(_fixed(r, fixes[r[PK[name]]]) if r[PK[name]] in fixes else r
                       for r in rows[name]) if name in CONTAINERS else tuple(rows[name])
           for name in rows}
    seen = _count(rows, "".join(errata.misglyphs))
    applied = tuple(_applied_row(e, errata, seen) for e in entries if e.corrected_char)
    return ErrataResult(MappingProxyType(out), applied, _report(errata, entries, rows))
