"""Pure assembly over rows of the build schema (no I/O).

- ``chunk_content``: the build stores no chunk text; a chunk is a run of its
  passage's pieces (``unit_refs``), and the passage ``content`` holds one group of
  blocks per piece (``**{label}** {text}`` for the verse, after the superscription
  and speaker labels that precede it), so the chunk's text is its pieces' groups.
- ``key_order``: canonical order of verse keys within a chapter (``19`` < ``19b``).
- ``verse_pieces``: the slots of a verse query as units (a merged unit once) and
  omitted slots (``本譯本此節從缺`` plus the variant footnote), design §2.23.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ragcommon import ids

OMITTED_TEXT = "本譯本此節從缺"
_VERSE_BLOCK = re.compile(r"\*\*[1-9][0-9]*(?:-[1-9][0-9]*)?\*\* ")
_REF_FIELDS = ("unit_key", "from", "to")


class ContentError(ValueError):
    """Rows that do not fit together (a data defect of the build)."""


def _groups(passage_content: str) -> list[list[str]]:
    """The passage's blocks grouped per piece: leading non-verse blocks, then the verse."""
    groups: list[list[str]] = []
    pending: list[str] = []
    for block in passage_content.split("\n\n"):
        pending.append(block)
        if _VERSE_BLOCK.match(block):
            groups.append(pending)
            pending = []
    if pending:
        raise ContentError(f"passage content has blocks after the last verse: {pending[:1]}")
    return groups


def _ref(ref: Mapping[str, Any]) -> tuple:
    return tuple(ref.get(k) for k in _REF_FIELDS)


def chunk_content(passage_content: str, passage_refs: Sequence[Mapping[str, Any]],
                  chunk_refs: Sequence[Mapping[str, Any]]) -> str:
    groups = _groups(passage_content)
    if len(groups) != len(passage_refs):
        raise ContentError(f"passage content has {len(groups)} verse blocks for "
                           f"{len(passage_refs)} pieces")
    wanted = [_ref(r) for r in chunk_refs]
    held = [_ref(r) for r in passage_refs]
    starts = [i for i in range(len(held)) if held[i:i + len(wanted)] == wanted]
    if not wanted or not starts:
        raise ContentError(f"chunk pieces {wanted[:2]} are not a run of the passage's pieces")
    start = starts[0]
    return "\n\n".join(b for group in groups[start:start + len(wanted)] for b in group)


def key_order(key: str) -> tuple[int, int, bool]:
    parsed = ids.validate(key, "key")
    return (parsed.chapter, parsed.verse, parsed.half)


@dataclass(frozen=True)
class VersePiece:
    """One unit (a merged unit once) or one omitted slot of a verse query."""

    unit_key: str | None
    label: str
    v_start: int
    v_end: int
    status: str
    text: str
    footnote_id: str | None = None
    footnote_text: str | None = None

    @property
    def line(self) -> str:
        if self.unit_key is None:
            return f"{self.label}. {self.text}（{self.footnote_text}）"
        return f"{self.label}. {self.text}"


def _piece(row: Mapping[str, Any]) -> VersePiece:
    if row["unit_key"] is None:
        verse = ids.validate(row["slot_key"], "slot").verse
        return VersePiece(None, str(verse), verse, verse, row["status"], OMITTED_TEXT,
                          row["variant_footnote_id"], row["footnote_text"])
    return VersePiece(row["unit_key"], row["label"], row["v_start"], row["v_end"],
                      row["status"], row["text"])


def verse_pieces(slot_keys: Sequence[str], rows: Sequence[Mapping[str, Any]]) -> list[VersePiece]:
    """The pieces covering ``slot_keys`` in order; every slot must have a row."""
    by_slot = {r["slot_key"]: r for r in rows}
    missing = [k for k in slot_keys if k not in by_slot]
    if missing:
        raise ContentError(f"the build holds no slot {missing[:3]}")
    pieces: list[VersePiece] = []
    for key in slot_keys:
        piece = _piece(by_slot[key])
        if piece.unit_key is None or not pieces or pieces[-1].unit_key != piece.unit_key:
            pieces.append(piece)
    return pieces
