"""Field-by-field diff of the text layer against the audit's ``canonical_full.jsonl``.

The audit built canonical_full (31,032 records: 31,021 units and 11 omitted
slots) with its own MuPDF parser (design §4, S2 row). Every field the two share
is compared — ids, numbering, text, line starts, pages, provenance, and the
heading, parallel-reference, name, footnote, speaker and selah annotations.
canonical_full holds the PDF wording, so ``text`` is compared with ``text_pdf``;
the serving ``text`` (and footnote text) is compared too, position by position,
and a difference there is ``errata`` when an errata record of that container
explains it. Anything else is ``other``, and G-DIFF requires none.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from ragcommon import ids
from ragdata.stages.diffs.md import DiffError

ERRATA, OTHER = "errata", "other"
TSV_COLUMNS = ("record", "field", "layer_value", "canonical_value", "class")
Rows = Mapping[str, Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class FieldDiff:
    record: str
    field: str
    layer: str
    canonical: str
    cls: str


@dataclass(frozen=True)
class CanonicalDiff:
    rows: tuple[FieldDiff, ...]
    summary: Mapping[str, Any]


def _show(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _read(path: Path, books: set[str]) -> list[dict[str, Any]]:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise DiffError(f"{path}: canonical reference unreadable: {exc}") from None
    return [r for r in records if r["book"] in books]


class _Layer:
    """The layer's records keyed the way canonical_full keys its annotations."""

    def __init__(self, rows: Rows):
        self.units = {u["unit_key"]: u for u in rows["verse_units"]}
        self.slots = {s["slot_key"]: s for s in rows["verse_slots"]}
        self.files = {b["book_id"]: b["file_name"] for b in rows["books"]}
        self.by_unit: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for h in rows["headings"]:
            self.by_unit[h["anchor_unit_key"]]["heading"].append(h)
        anchor = {h["heading_id"]: h["anchor_unit_key"] for h in rows["headings"]}
        for p in rows["parallel_refs"]:
            self.by_unit[anchor[p["heading_id"]]]["parallel_ref"].append(p)
        for s in rows["speakers"]:
            self.by_unit[s["unit_key"]]["speaker"].append(s)
        for n in rows["name_spans"]:
            if n["region"] == "body":
                self.by_unit[n["container_id"]]["name"].append(n)
        for f in rows["footnotes"]:
            self.by_unit[f["unit_key"]]["footnote"].append(f)
        self.errata: dict[str, dict[int, str]] = defaultdict(dict)
        for e in rows["errata_applied"]:
            self.errata[e["container_id"]][e["offset"]] = e["pdf_char"]


def _annotations(record: Mapping[str, Any], kind: str) -> list[Mapping[str, Any]]:
    return [a for a in record["annotations"] if a["type"] == kind]


def _mine(layer: _Layer, unit: Mapping[str, Any]) -> dict[str, Any]:
    key, notes = unit["unit_key"], layer.by_unit[unit["unit_key"]]
    heads = sorted(notes["heading"], key=lambda h: (h["anchor_offset"],
                                                     ids.parse(h["heading_id"]).seq))
    return {
        "book": unit["book_id"], "book_file": layer.files[unit["book_id"]],
        "chapter": unit["chapter"], "verse": unit["label"], "v_start": unit["v_start"],
        "v_end": unit["v_end"], "status": "present", "text": unit["text_pdf"],
        "line_starts": [0, *(b["offset"] for b in unit["line_breaks"])], "pages": unit["pages"],
        "prov.pdf": layer.files[unit["book_id"]] + ".pdf",
        "prov.pdf_sha256": unit["prov"]["pdf_sha256"],
        "prov.first_glyph": list(unit["prov"]["first_glyph"]),
        "ann.heading": [[h["anchor_offset"], h["pos"], h["text_pdf"]] for h in heads],
        "ann.parallel_ref": sorted({p["raw"] for p in notes["parallel_ref"]}),
        "ann.speaker": [[s["offset"], s["pos"], s["text_pdf"]] for s in notes["speaker"]],
        "ann.name": sorted([n["start"], n["end"], n["surface"]] for n in notes["name"]),
        "ann.footnote": [[f["n"], f["text_pdf"],
                          None if f["anchor"] is None else [f["anchor"]["start"],
                                                            f["anchor"]["end"]]]
                         for f in sorted(notes["footnote"], key=lambda f: f["n"])],
        "ann.selah": [[m["start"], m["end"]] for m in unit["markers"] if m["type"] == "selah"],
    }


def _theirs(record: Mapping[str, Any]) -> dict[str, Any]:
    plain = ("book", "book_file", "chapter", "verse", "v_start", "v_end", "status", "text",
             "line_starts", "pages")
    out = {k: record[k] for k in plain}
    out.update({f"prov.{k}": record["prov"][k] for k in ("pdf", "pdf_sha256", "first_glyph")})
    for kind, keys in (("heading", ("offset", "pos", "text")), ("speaker", ("offset", "pos",
                                                                              "text")),
                       ("footnote", ("n", "text", "anchor")), ("selah", ("start", "end"))):
        out[f"ann.{kind}"] = [[a[k] for k in keys] for a in _annotations(record, kind)]
    out["ann.parallel_ref"] = sorted({a["text"] for a in _annotations(record, "parallel_ref")})
    out["ann.name"] = sorted([a["start"], a["end"], a["surface"]]
                             for a in _annotations(record, "name"))
    return out


def _serving(record: str, field: str, container: str, mine: str, theirs: str,
             layer: _Layer) -> list[FieldDiff]:
    """Position by position: a difference is errata when the container has one there."""
    if len(mine) != len(theirs):
        return [FieldDiff(record, field, mine, theirs, OTHER)]
    misglyphs = layer.errata.get(container, {})
    return [FieldDiff(record, f"{field}[{i}]", a, b, ERRATA if misglyphs.get(i) == b else OTHER)
            for i, (a, b) in enumerate(zip(mine, theirs)) if a != b]


def _present(record: Mapping[str, Any], layer: _Layer) -> list[FieldDiff]:
    key, unit = record["id"], layer.units[record["id"]]
    mine, theirs = _mine(layer, unit), _theirs(record)
    out = [FieldDiff(key, f, _show(mine[f]), _show(theirs[f]), OTHER)
           for f in theirs if mine[f] != theirs[f]]
    out += _serving(key, "text@serving", key, unit["text"], record["text"], layer)
    texts = {a["n"]: a["text"] for a in _annotations(record, "footnote")}
    for note in sorted(layer.by_unit[key]["footnote"], key=lambda f: f["n"]):
        if note["n"] in texts:
            out += _serving(key, "ann.footnote@serving", note["fn_id"], note["text"],
                            texts[note["n"]], layer)
    return out


def _omitted(record: Mapping[str, Any], layer: _Layer) -> list[FieldDiff]:
    slot = layer.slots[record["id"]]
    note = slot.get("variant_footnote_id")
    mine = {"status": slot["status"],
            "variant_in_footnote_of": ids.parse(note).parent.raw if note else None}
    return [FieldDiff(record["id"], f, _show(mine[f]), _show(record.get(f)), OTHER)
            for f in mine if mine[f] != record.get(f)]


def _compare(records: Sequence[Mapping[str, Any]], layer: _Layer) -> Iterator[FieldDiff]:
    for record in records:
        key = record["id"]
        if record["status"] == "omitted_variant" and key in layer.slots:
            yield from _omitted(record, layer)
        elif record["status"] != "omitted_variant" and key in layer.units:
            yield from _present(record, layer)
        else:
            yield FieldDiff(key, "id", "", key, OTHER)
    omitted = {k for k, s in layer.slots.items() if s["status"] == "omitted_variant"}
    for key in sorted((set(layer.units) | omitted) - {r["id"] for r in records}):
        yield FieldDiff(key, "id", key, "", OTHER)


def diff_canonical(rows: Rows, path: Path) -> CanonicalDiff:
    """Compare the built text layer with canonical_full for the books it holds."""
    records = _read(path, {b["book_id"] for b in rows["books"]})
    out = tuple(_compare(records, _Layer(rows)))
    by_class = {ERRATA: 0, OTHER: 0}
    for row in out:
        by_class[row.cls] += 1
    summary = {"records_compared": len(records),
               "layer_records": len(rows["verse_units"]) + sum(
                   s["status"] == "omitted_variant" for s in rows["verse_slots"]),
               "rows": len(out), "by_class": by_class}
    return CanonicalDiff(out, summary)


def _cell(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n")


def encode_tsv(rows: Sequence[FieldDiff]) -> bytes:
    lines = ["\t".join(TSV_COLUMNS)]
    lines += ["\t".join(_cell(v) for v in (r.record, r.field, r.layer, r.canonical, r.cls))
              for r in rows]
    return ("\n".join(lines) + "\n").encode("utf-8")
