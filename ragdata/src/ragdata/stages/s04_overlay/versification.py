"""S4: ``ref_aliases`` — external verse numbers that have no PDF slot (design §2.12).

``config/registries/versification.yaml`` declares each alias with evidence the
text layer must bear out: the external verse lies past its chapter's last
verse in the PDF (otherwise it is a slot and needs no alias), the target is a
present slot, and the target verse starts with the words the external verse
holds (jhn.7.53 「於是各人都回家去了；」 opens the PDF's 8:1). Everything else
about the verse grid — each chapter's max verse and the 11 omitted slots —
comes from the text layer itself; ``scripts/derive_ragcommon_data.py`` copies
it, with these aliases, into ``packages/ragcommon/data`` for the services.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from ragcommon import ids
from ragdata.stages.s04_overlay.errata import REPO, OverlayError

DEFAULT_PATH = REPO / "config" / "registries" / "versification.yaml"
SCHEMA = "ragdata.versification.v1"
RELATIONS = ("contained_in",)
Rows = Mapping[str, Sequence[Mapping[str, Any]]]


@dataclass(frozen=True)
class AliasDecl:
    external_ref: str
    relation: str
    target: str
    target_starts_with: str
    note: str


def _decl(raw: Mapping[str, Any]) -> AliasDecl:
    for field in ("external_ref", "target"):
        if not ids.is_valid(raw.get(field), "slot"):
            raise OverlayError(f"alias {field} must be a slot key, got {raw.get(field)!r}")
    if raw.get("relation") not in RELATIONS:
        raise OverlayError(f"alias {raw['external_ref']}: relation must be one of {RELATIONS}")
    for field in ("target_starts_with", "note"):
        if not isinstance(raw.get(field), str) or not raw[field]:
            raise OverlayError(f"alias {raw['external_ref']}: {field} must be non-empty text")
    return AliasDecl(raw["external_ref"], raw["relation"], raw["target"],
                     raw["target_starts_with"], raw["note"])


def load_aliases(path: Path | str = DEFAULT_PATH) -> tuple[AliasDecl, ...]:
    try:
        doc = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OverlayError(f"{path}: unreadable: {exc}") from None
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise OverlayError(f"{path}: schema must be {SCHEMA}")
    decls = tuple(_decl(raw) for raw in doc.get("aliases") or [])
    refs = [d.external_ref for d in decls]
    if len(set(refs)) != len(refs):
        raise OverlayError(f"{path}: an external_ref is declared twice")
    return decls


def _check(decl: AliasDecl, rows: Rows) -> None:
    ref = ids.parse(decl.external_ref)
    chapter_key = ids.chapter_key(ref.book_id, ref.chapter)
    chapter = next((c for c in rows["chapters"] if c["chapter_key"] == chapter_key), None)
    if chapter is None:
        raise OverlayError(f"{decl.external_ref}: no chapter {chapter_key} in the text layer")
    if ref.verse <= chapter["max_verse"]:
        raise OverlayError(f"{decl.external_ref} is a PDF slot; resolve it directly")
    slot = next((s for s in rows["verse_slots"] if s["slot_key"] == decl.target), None)
    if slot is None or slot["status"] == "omitted_variant":
        raise OverlayError(f"{decl.external_ref}: target {decl.target} is not a present slot")
    unit = next(u for u in rows["verse_units"] if u["unit_key"] == slot["unit_key"])
    if not unit["text_pdf"].startswith(decl.target_starts_with):
        raise OverlayError(f"{decl.external_ref}: {unit['unit_key']} does not start with "
                           f"{decl.target_starts_with!r}")


def alias_rows(rows: Rows, decls: Sequence[AliasDecl], books: set[str]) -> tuple[dict, ...]:
    """``ref_aliases`` rows of the aliases whose book is built, each checked against ``rows``."""
    out = []
    for decl in decls:
        if ids.parse(decl.external_ref).book_id not in books:
            continue
        _check(decl, rows)
        out.append({"external_ref": decl.external_ref, "relation": decl.relation,
                    "target": decl.target, "note": decl.note,
                    "provenance_class": "external_reference"})
    return tuple(out)
